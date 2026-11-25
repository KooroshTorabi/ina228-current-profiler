/*
 * INA228 smart current profiler (rev C) - firmware for the on-board STM32G030F6P6.
 *
 * The host never switches ranges. It reads one current value (A), one voltage (V)
 * and the integrated charge/energy:
 *   - I2C slave at 0x48 on J3 (PA12 = SDA, PA11 = SCL), register map in README.md
 *   - CSV stream on J3 TX (USART2, 921600 8N1): "t_us,current_A,voltage_V,range"
 *     and text commands on J3 RX (see README.md)
 *
 * Ranging:
 *   - Up, fast:  U3 (comparator) pulls PA0 low when VIN - DUT_VDD exceeds ~32 mV.
 *                The EXTI interrupt steps up one range within about 1 us.
 *   - Up, slow:  a reading above 90 % of the ADC full scale also steps up.
 *   - Down:      when the current would give less than 15 mV in the next lower range
 *                for DOWN_COUNT conversions in a row.
 *   - After every switch DISCARD conversions are dropped; charge and energy keep
 *                integrating with the last good current across that gap.
 *
 * Pins: PA0 CMP_OUT, PA1 INA ALERT, PA2/PA3 USART2, PA4 CTL_H, PA5 CTL_M, PA6 LED,
 *       PB6/PB7 I2C1 (INA228), PA11/PA12 I2C2 (host), PA13/PA14 SWD.
 */
#include <stdint.h>
#include <string.h>
#include "stm32g0xx.h"

#define FW_VERSION      1
#define WHO_AM_I        0xA8
#define HOST_ADDR       0x48
#define INA_ADDR        0x40

#define R_L 0
#define R_M 1
#define R_H 2

#define DISCARD         2       /* conversions dropped after a range switch */
#define DOWN_COUNT      8       /* conversions below the down threshold before stepping down */
#define DOWN_V          0.015f  /* predicted drop in the lower range that allows stepping down */
#define UP_FRAC         0.90f   /* fraction of ADC full scale that forces stepping up */

/* INA228 registers */
#define INA_CONFIG      0x00
#define INA_ADC_CONFIG  0x01
#define INA_VSHUNT      0x04
#define INA_VBUS        0x05
#define INA_DIAG_ALRT   0x0B
#define INA_MFR_ID      0x3E
#define INA_DEVICE_ID   0x3F

/* ================================================================ settings in flash */
#define CFG_ADDR        0x08007800u      /* last 2 KB page of the 32 KB flash */
#define CFG_PAGE        15u
#define CFG_MAGIC       0x43464731u      /* "CFG1" */

typedef struct {
    uint32_t magic;
    float    r[3];        /* effective resistance of each range, ohm */
    float    off[3];      /* offset current of each range, A (subtracted) */
    uint8_t  vshct;       /* INA228 shunt conversion time code 0..7 */
    uint8_t  avg;         /* INA228 averaging code 0..7 */
    uint8_t  stream;      /* 1 = CSV on the UART */
    uint8_t  pad[9];
} cfg_t;                  /* 48 bytes = 6 double words */

static const cfg_t CFG_DEFAULT = {
    CFG_MAGIC,
    /* R1+R2+R3 in parallel with the INA228 input (~92 k), R1+R2+Rds(Q2), R1+Rds(Q1) */
    { 990.3f, 1.08f, 0.06f },
    { 0.0f, 0.0f, 0.0f },
    4, 0, 1, {0}
};
static cfg_t cfg;

/* ================================================================ host register map */
typedef struct __attribute__((packed)) {
    uint8_t  who_am_i;    /* 0x00 */
    uint8_t  fw_version;  /* 0x01 */
    uint8_t  range;       /* 0x02  0 = L, 1 = M, 2 = H */
    uint8_t  flags;       /* 0x03  bit0 data valid, bit1 INA228 found, bit2 over range */
    float    current;     /* 0x04  A */
    float    voltage;     /* 0x08  V */
    float    power;       /* 0x0C  W */
    uint32_t samples;     /* 0x10 */
    uint32_t time_us;     /* 0x14 */
    double   charge;      /* 0x18  C since reset */
    double   energy;      /* 0x20  J since reset */
    double   elapsed;     /* 0x28  s since reset */
    float    r[3];        /* 0x30  rw */
    float    off[3];      /* 0x3C  rw */
    uint8_t  vshct;       /* 0x48  rw */
    uint8_t  avg;         /* 0x49  rw */
    uint8_t  stream;      /* 0x4A  rw */
    uint8_t  cmd;         /* 0x4B  w: 0x01 reset accumulators, 0xA5 save, 0x5A defaults */
} regs_t;
#define REGS_SIZE   ((uint8_t)sizeof(regs_t))
#define RW_FIRST    0x30u

_Static_assert(sizeof(regs_t) == 0x4C, "register map layout");
_Static_assert(sizeof(cfg_t) % 8 == 0, "cfg must be whole double words");

static regs_t live;                   /* written by the main loop, copied under irq lock */
static uint8_t tx_img[sizeof(regs_t)];
static uint8_t rx_img[sizeof(regs_t)];
static volatile uint8_t host_ptr, host_first, host_lo = 0xFF, host_hi, host_dirty;

/* ================================================================ state */
static volatile uint8_t range = R_H;           /* the board starts in H (pull-ups on CTL_x) */
static volatile uint8_t discard = DISCARD;
static volatile uint32_t tim_hi;               /* upper bits of the 32-bit microsecond clock */
static uint8_t adcrange_set = 0xFF;
static uint8_t ina_ok;

/* ================================================================ clocks, time */
static void clock_init(void)
{
    /* HSI16 -> PLL x8 /2 = 64 MHz */
    FLASH->ACR = (FLASH->ACR & ~FLASH_ACR_LATENCY) | FLASH_ACR_LATENCY_1 | FLASH_ACR_PRFTEN | FLASH_ACR_ICEN;
    while ((FLASH->ACR & FLASH_ACR_LATENCY) != FLASH_ACR_LATENCY_1) {}
    RCC->PLLCFGR = RCC_PLLCFGR_PLLSRC_HSI | (0u << RCC_PLLCFGR_PLLM_Pos) | (8u << RCC_PLLCFGR_PLLN_Pos)
                 | (1u << RCC_PLLCFGR_PLLR_Pos) | RCC_PLLCFGR_PLLREN;
    RCC->CR |= RCC_CR_PLLON;
    while (!(RCC->CR & RCC_CR_PLLRDY)) {}
    RCC->CFGR = (RCC->CFGR & ~RCC_CFGR_SW) | RCC_CFGR_SW_1;
    while ((RCC->CFGR & RCC_CFGR_SWS) != RCC_CFGR_SWS_1) {}
    SystemCoreClock = 64000000u;
}

static void timer_init(void)
{
    RCC->APBENR1 |= RCC_APBENR1_TIM3EN;
    TIM3->PSC = 63;                    /* 1 MHz */
    TIM3->ARR = 0xFFFF;
    TIM3->EGR = TIM_EGR_UG;
    TIM3->SR = 0;
    TIM3->DIER = TIM_DIER_UIE;
    TIM3->CR1 = TIM_CR1_CEN;
    NVIC_SetPriority(TIM3_IRQn, 1);
    NVIC_EnableIRQ(TIM3_IRQn);
}

void TIM3_IRQHandler(void)
{
    if (TIM3->SR & TIM_SR_UIF) { TIM3->SR = ~TIM_SR_UIF; tim_hi++; }
}

static uint32_t micros(void)
{
    uint32_t pm = __get_PRIMASK();
    __disable_irq();
    uint32_t hi = tim_hi, lo = TIM3->CNT;
    if ((TIM3->SR & TIM_SR_UIF) && lo < 0x8000u) hi++;   /* overflow not serviced yet */
    __set_PRIMASK(pm);
    return (hi << 16) | lo;
}

static void delay_cycles(uint32_t n)       /* ~4 cycles per loop at 64 MHz */
{
    while (n--) __NOP();
}

/* ================================================================ range switching */
/* CTL_x HIGH = bypass FET on. L: both off, M: CTL_M on, H: both on */
static void range_apply(uint8_t r)
{
    if (r == R_L)      GPIOA->BSRR = (1u << (4 + 16)) | (1u << (5 + 16));
    else if (r == R_M) GPIOA->BSRR = (1u << (4 + 16)) | (1u << 5);
    else               GPIOA->BSRR = (1u << 4) | (1u << 5);
}

static void comparator_irq(uint8_t on)
{
    EXTI->FPR1 = EXTI_FPR1_FPIF0;
    if (on) EXTI->IMR1 |= EXTI_IMR1_IM0; else EXTI->IMR1 &= ~EXTI_IMR1_IM0;
}

/* runs in the EXTI handler (highest priority) */
static void step_up_fast(void)
{
    do {
        if (range >= R_H) break;
        range++;
        range_apply(range);
        delay_cycles(32);                          /* ~2 us: FET on, comparator recovers */
    } while (!(GPIOA->IDR & (1u << 0)) && range < R_H);  /* still over threshold: keep going */
    discard = DISCARD;
    comparator_irq(range < R_H);                   /* in H it is always tripped above ~0.5 A */
}

void EXTI0_1_IRQHandler(void)
{
    if (EXTI->FPR1 & EXTI_FPR1_FPIF0) {
        EXTI->FPR1 = EXTI_FPR1_FPIF0;
        step_up_fast();
    }
}

static void set_range(uint8_t r)
{
    __disable_irq();
    range = r;
    range_apply(r);
    discard = DISCARD;
    comparator_irq(r < R_H);
    __enable_irq();
}

/* ================================================================ I2C1: INA228 */
static int i2c1_wait(uint32_t flag)
{
    uint32_t t0 = micros();
    while (!(I2C1->ISR & flag)) {
        if (I2C1->ISR & I2C_ISR_NACKF) {
            I2C1->ICR = I2C_ICR_NACKCF;
            while (!(I2C1->ISR & I2C_ISR_STOPF)) { if ((uint32_t)(micros() - t0) > 2000u) break; }
            I2C1->ICR = I2C_ICR_STOPCF;
            return -1;
        }
        if ((uint32_t)(micros() - t0) > 2000u) return -2;
    }
    return 0;
}

static void i2c1_init(void)
{
    RCC->APBENR1 |= RCC_APBENR1_I2C1EN;
    RCC->CCIPR = (RCC->CCIPR & ~RCC_CCIPR_I2C1SEL) | RCC_CCIPR_I2C1SEL_1;  /* kernel clock HSI16 */
    SYSCFG->CFGR1 |= SYSCFG_CFGR1_I2C_PB6_FMP | SYSCFG_CFGR1_I2C_PB7_FMP;
    I2C1->CR1 = 0;
    I2C1->TIMINGR = 0x00100309u;   /* ~800 kHz from 16 MHz: SCLL 625 ns, SCLH 250 ns + sync */
    I2C1->CR1 = I2C_CR1_PE;
}

static void i2c1_reset(void)
{
    I2C1->CR1 = 0; delay_cycles(8); I2C1->CR1 = I2C_CR1_PE;
}

static int ina_write(uint8_t reg, uint16_t v)
{
    const uint8_t b[3] = { reg, (uint8_t)(v >> 8), (uint8_t)v };
    I2C1->ICR = I2C_ICR_STOPCF | I2C_ICR_NACKCF;
    I2C1->CR2 = (INA_ADDR << 1) | (3u << I2C_CR2_NBYTES_Pos) | I2C_CR2_AUTOEND | I2C_CR2_START;
    for (int i = 0; i < 3; i++) {
        if (i2c1_wait(I2C_ISR_TXIS)) { i2c1_reset(); return -1; }
        I2C1->TXDR = b[i];
    }
    if (i2c1_wait(I2C_ISR_STOPF)) { i2c1_reset(); return -1; }
    I2C1->ICR = I2C_ICR_STOPCF;
    return 0;
}

static int ina_read(uint8_t reg, uint8_t *buf, uint8_t n)
{
    I2C1->ICR = I2C_ICR_STOPCF | I2C_ICR_NACKCF;
    I2C1->CR2 = (INA_ADDR << 1) | (1u << I2C_CR2_NBYTES_Pos) | I2C_CR2_START;
    if (i2c1_wait(I2C_ISR_TXIS)) { i2c1_reset(); return -1; }
    I2C1->TXDR = reg;
    if (i2c1_wait(I2C_ISR_TC)) { i2c1_reset(); return -1; }
    I2C1->CR2 = (INA_ADDR << 1) | I2C_CR2_RD_WRN | ((uint32_t)n << I2C_CR2_NBYTES_Pos) | I2C_CR2_AUTOEND | I2C_CR2_START;
    for (uint8_t i = 0; i < n; i++) {
        if (i2c1_wait(I2C_ISR_RXNE)) { i2c1_reset(); return -1; }
        buf[i] = (uint8_t)I2C1->RXDR;
    }
    if (i2c1_wait(I2C_ISR_STOPF)) { i2c1_reset(); return -1; }
    I2C1->ICR = I2C_ICR_STOPCF;
    return 0;
}

static uint16_t ina_read16(uint8_t reg)
{
    uint8_t b[2] = {0, 0};
    if (ina_read(reg, b, 2)) return 0;
    return (uint16_t)((b[0] << 8) | b[1]);
}

/* ADCRANGE = 1 (+-40.96 mV) for L and M, 0 (+-163.84 mV) for H */
static void ina_set_adcrange(uint8_t r)
{
    uint8_t want = (r == R_H) ? 0 : 1;
    if (want == adcrange_set) return;
    if (ina_write(INA_CONFIG, want ? 0x0010u : 0x0000u) == 0) adcrange_set = want;
}

static void ina_configure(void)
{
    uint16_t adc = (uint16_t)((0xBu << 12) | (0u << 9) | ((cfg.vshct & 7u) << 6) | (0u << 3) | (cfg.avg & 7u));
    ina_write(INA_ADC_CONFIG, adc);               /* continuous shunt + bus, VBUSCT 50 us */
    ina_write(INA_DIAG_ALRT, 0xC000u);            /* ALATCH + CNVR: ALERT low when a conversion is ready */
    adcrange_set = 0xFF;
    ina_set_adcrange(range);
}

static int ina_init(void)
{
    ina_write(INA_CONFIG, 0x8000u);               /* reset */
    for (volatile uint32_t i = 0; i < 64000u; i++) {}
    if (ina_read16(INA_MFR_ID) != 0x5449u) return 0;          /* "TI" */
    if ((ina_read16(INA_DEVICE_ID) >> 4) != 0x228u) return 0;
    ina_configure();
    return 1;
}

/* ================================================================ I2C2: host slave */
static void i2c2_init(void)
{
    RCC->APBENR1 |= RCC_APBENR1_I2C2EN;
    I2C2->CR1 = 0;
    I2C2->TIMINGR = 0x10420F13u;   /* slave: data setup/hold for up to 400 kHz at PCLK 64 MHz */
    I2C2->OAR1 = 0;
    I2C2->OAR1 = I2C_OAR1_OA1EN | (HOST_ADDR << 1);
    I2C2->CR1 = I2C_CR1_ADDRIE | I2C_CR1_RXIE | I2C_CR1_TXIE | I2C_CR1_STOPIE | I2C_CR1_NACKIE | I2C_CR1_PE;
    NVIC_SetPriority(I2C2_IRQn, 2);
    NVIC_EnableIRQ(I2C2_IRQn);
}

void I2C2_IRQHandler(void)
{
    uint32_t isr = I2C2->ISR;
    if (isr & I2C_ISR_ADDR) {
        if (isr & I2C_ISR_DIR) {                   /* host reads: freeze a consistent snapshot */
            memcpy(tx_img, &live, sizeof(regs_t));
            I2C2->ISR = I2C_ISR_TXE;               /* flush TXDR */
        } else {
            host_first = 1;
        }
        I2C2->ICR = I2C_ICR_ADDRCF;
    }
    if (isr & I2C_ISR_RXNE) {
        uint8_t d = (uint8_t)I2C2->RXDR;
        if (host_first) { host_ptr = d; host_first = 0; }
        else {
            if (host_ptr >= RW_FIRST && host_ptr < REGS_SIZE) {
                rx_img[host_ptr] = d;
                if (host_ptr < host_lo) host_lo = host_ptr;
                if (host_ptr > host_hi) host_hi = host_ptr;
                host_dirty = 1;
            }
            host_ptr++;
        }
    }
    if (isr & I2C_ISR_TXIS) {
        I2C2->TXDR = (host_ptr < REGS_SIZE) ? tx_img[host_ptr] : 0xFF;
        host_ptr++;
    }
    if (isr & I2C_ISR_NACKF) I2C2->ICR = I2C_ICR_NACKCF;
    if (isr & I2C_ISR_STOPF) I2C2->ICR = I2C_ICR_STOPCF;
    if (isr & (I2C_ISR_BERR | I2C_ISR_ARLO | I2C_ISR_OVR))
        I2C2->ICR = I2C_ICR_BERRCF | I2C_ICR_ARLOCF | I2C_ICR_OVRCF;
}

/* ================================================================ UART */
#define TXBUF 1024u
static uint8_t txbuf[TXBUF];
static volatile uint16_t tx_head, tx_tail;
static char rxline[48];
static volatile uint8_t rx_len, rx_ready;

static void uart_init(void)
{
    RCC->APBENR1 |= RCC_APBENR1_USART2EN;
    USART2->CR1 = 0;
    USART2->BRR = 64000000u / 921600u;            /* 69 -> 927.5 kBd, +0.6 % */
    USART2->CR1 = USART_CR1_TE | USART_CR1_RE | USART_CR1_RXNEIE_RXFNEIE | USART_CR1_UE;
    NVIC_SetPriority(USART2_IRQn, 3);
    NVIC_EnableIRQ(USART2_IRQn);
}

void USART2_IRQHandler(void)
{
    uint32_t isr = USART2->ISR;
    if (isr & USART_ISR_RXNE_RXFNE) {
        char c = (char)USART2->RDR;
        if (!rx_ready) {
            if (c == '\n' || c == '\r') { if (rx_len) { rxline[rx_len] = 0; rx_ready = 1; } }
            else if (rx_len < sizeof(rxline) - 1) rxline[rx_len++] = c;
        }
    }
    if (isr & USART_ISR_ORE) USART2->ICR = USART_ICR_ORECF;
    if ((USART2->CR1 & USART_CR1_TXEIE_TXFNFIE) && (isr & USART_ISR_TXE_TXFNF)) {
        if (tx_tail != tx_head) { USART2->TDR = txbuf[tx_tail]; tx_tail = (uint16_t)((tx_tail + 1) % TXBUF); }
        else USART2->CR1 &= ~USART_CR1_TXEIE_TXFNFIE;
    }
}

static void uart_write(const char *s, uint32_t n)
{
    for (uint32_t i = 0; i < n; i++) {
        uint16_t nx = (uint16_t)((tx_head + 1) % TXBUF);
        if (nx == tx_tail) break;                  /* full: drop rather than stall sampling */
        txbuf[tx_head] = (uint8_t)s[i];
        tx_head = nx;
    }
    USART2->CR1 |= USART_CR1_TXEIE_TXFNFIE;
}
static void uart_puts(const char *s) { uart_write(s, (uint32_t)strlen(s)); }

/* ---- tiny number formatting (no printf: keeps the image small) */
static char *put_u32(char *p, uint32_t v)
{
    char t[10]; int n = 0;
    do { t[n++] = (char)('0' + v % 10u); v /= 10u; } while (v);
    while (n) *p++ = t[--n];
    return p;
}

static char *put_fix(char *p, float v, int dec)   /* fixed point, dec <= 6 */
{
    if (v < 0) { *p++ = '-'; v = -v; }
    uint32_t sc = 1; for (int i = 0; i < dec; i++) sc *= 10u;
    uint32_t x = (uint32_t)(v * (float)sc + 0.5f);
    p = put_u32(p, x / sc);
    if (dec) {
        *p++ = '.';
        uint32_t f = x % sc;
        for (uint32_t d = sc / 10u; d; d /= 10u) { *p++ = (char)('0' + f / d); f %= d; }
    }
    return p;
}

static char *put_sci(char *p, float v)            /* 5 significant digits: -1.2345e-06 */
{
    if (v < 0) { *p++ = '-'; v = -v; }
    if (v == 0.0f) { memcpy(p, "0.0000e+00", 10); return p + 10; }
    int e = 0;
    while (v >= 10.0f) { v /= 10.0f; e++; }
    while (v < 1.0f) { v *= 10.0f; e--; }
    uint32_t m = (uint32_t)(v * 10000.0f + 0.5f);
    if (m >= 100000u) { m /= 10u; e++; }
    *p++ = (char)('0' + m / 10000u); *p++ = '.';
    for (uint32_t d = 1000u; d; d /= 10u) *p++ = (char)('0' + (m / d) % 10u);
    *p++ = 'e'; *p++ = e < 0 ? '-' : '+';
    if (e < 0) e = -e;
    *p++ = (char)('0' + e / 10); *p++ = (char)('0' + e % 10);
    return p;
}

static float parse_float(const char *s)
{
    float v = 0, sign = 1, sc = 0;
    int ex = 0, es = 1;
    while (*s == ' ') s++;
    if (*s == '-') { sign = -1; s++; } else if (*s == '+') s++;
    for (; *s; s++) {
        if (*s >= '0' && *s <= '9') { if (sc) { v += (float)(*s - '0') * sc; sc *= 0.1f; } else v = v * 10 + (float)(*s - '0'); }
        else if (*s == '.') sc = 0.1f;
        else if (*s == 'e' || *s == 'E') {
            s++; if (*s == '-') { es = -1; s++; } else if (*s == '+') s++;
            while (*s >= '0' && *s <= '9') ex = ex * 10 + (*s++ - '0');
            break;
        } else break;
    }
    while (ex--) v = (es > 0) ? v * 10.0f : v / 10.0f;
    return sign * v;
}

/* ================================================================ flash */
static void cfg_load(void)
{
    const cfg_t *f = (const cfg_t *)CFG_ADDR;
    cfg = (f->magic == CFG_MAGIC) ? *f : CFG_DEFAULT;
    for (int i = 0; i < 3; i++) if (!(cfg.r[i] > 0.0f && cfg.r[i] < 1.0e6f)) cfg = CFG_DEFAULT;
}

static int cfg_save(void)
{
    __disable_irq();
    while (FLASH->SR & FLASH_SR_BSY1) {}
    if (FLASH->CR & FLASH_CR_LOCK) { FLASH->KEYR = 0x45670123u; FLASH->KEYR = 0xCDEF89ABu; }
    FLASH->SR = FLASH->SR;                         /* clear error flags */
    FLASH->CR = FLASH_CR_PER | (CFG_PAGE << FLASH_CR_PNB_Pos);
    FLASH->CR |= FLASH_CR_STRT;
    while (FLASH->SR & FLASH_SR_BSY1) {}
    FLASH->CR = 0;
    const uint32_t *src = (const uint32_t *)&cfg;
    volatile uint32_t *dst = (volatile uint32_t *)CFG_ADDR;
    for (uint32_t i = 0; i < sizeof(cfg_t) / 4u; i += 2) {
        FLASH->CR = FLASH_CR_PG;
        dst[i] = src[i];
        __ISB();
        dst[i + 1] = src[i + 1];
        while (FLASH->SR & FLASH_SR_BSY1) {}
        FLASH->SR = FLASH_SR_EOP;
    }
    FLASH->CR = FLASH_CR_LOCK;
    __enable_irq();
    return ((const cfg_t *)CFG_ADDR)->magic == CFG_MAGIC;
}

/* ================================================================ measurement */
static double q_acc, e_acc, t_acc;
static uint32_t t_prev, n_samples;
static float i_last, v_last;
static uint8_t below;

static void accum_reset(void)
{
    q_acc = e_acc = t_acc = 0.0; n_samples = 0; t_prev = micros();
}

static void publish(uint8_t valid, uint8_t over)
{
    regs_t r;
    r.who_am_i = WHO_AM_I; r.fw_version = FW_VERSION; r.range = range;
    r.flags = (uint8_t)((valid ? 1u : 0u) | (ina_ok ? 2u : 0u) | (over ? 4u : 0u));
    r.current = i_last; r.voltage = v_last; r.power = i_last * v_last;
    r.samples = n_samples; r.time_us = t_prev;
    r.charge = q_acc; r.energy = e_acc; r.elapsed = t_acc;
    memcpy(r.r, cfg.r, sizeof r.r); memcpy(r.off, cfg.off, sizeof r.off);
    r.vshct = cfg.vshct; r.avg = cfg.avg; r.stream = cfg.stream; r.cmd = 0;
    __disable_irq();
    memcpy(&live, &r, sizeof r);
    __enable_irq();
}

static void sample(void)
{
    uint8_t b[3];
    uint32_t now = micros();
    if (ina_read(INA_VSHUNT, b, 3)) return;
    int32_t vs = (int32_t)(((uint32_t)b[0] << 24) | ((uint32_t)b[1] << 16) | ((uint32_t)b[2] << 8)) >> 12;
    if (ina_read(INA_VBUS, b, 3)) return;
    uint32_t vb = (((uint32_t)b[0] << 16) | ((uint32_t)b[1] << 8) | b[2]) >> 4;
    uint16_t diag = ina_read16(INA_DIAG_ALRT);    /* clears the latched ALERT */
    (void)diag;

    __disable_irq();
    uint8_t r = range, skip = discard;
    if (discard) discard--;
    __enable_irq();

    float lsb = (adcrange_set == 1) ? 78.125e-9f : 312.5e-9f;
    float fs = (adcrange_set == 1) ? 0.04096f : 0.16384f;
    float vsh = (float)vs * lsb;
    float v = (float)vb * 195.3125e-6f;
    uint8_t valid = !skip && adcrange_set == (r == R_H ? 0 : 1);
    uint8_t over = 0;

    if (valid) {
        i_last = vsh / cfg.r[r] - cfg.off[r];
        v_last = v;
    }
    /* integrate with the last good current (also across discarded conversions) */
    float dt = (float)(uint32_t)(now - t_prev) * 1e-6f;
    t_prev = now;
    if (dt < 1.0f) { q_acc += (double)(i_last * dt); e_acc += (double)(i_last * v_last * dt); t_acc += (double)dt; }
    n_samples++;

    if (valid) {
        float a = vsh < 0 ? -vsh : vsh;
        if (a > UP_FRAC * fs) {
            if (r < R_H) set_range((uint8_t)(r + 1)); else over = 1;
            below = 0;
        } else if (r > R_L) {
            float ia = i_last < 0 ? -i_last : i_last;
            below = (ia * cfg.r[r - 1] < DOWN_V) ? (uint8_t)(below + 1) : 0;
            if (below >= DOWN_COUNT) { set_range((uint8_t)(r - 1)); below = 0; }
        } else below = 0;

        if (cfg.stream) {
            char line[64], *p = line;
            p = put_u32(p, now); *p++ = ',';
            p = put_sci(p, i_last); *p++ = ',';
            p = put_fix(p, v_last, 4); *p++ = ',';
            *p++ = (char)('0' + r); *p++ = '\n';
            uart_write(line, (uint32_t)(p - line));
        }
    }
    publish(valid, over);

    static uint16_t blink;
    if (++blink >= (uint16_t)(200u << r)) { blink = 0; GPIOA->ODR ^= (1u << 6); }  /* faster in lower ranges */
}

/* ================================================================ commands */
static int rsel(const char *s) { return *s == 'L' || *s == 'l' ? R_L : *s == 'M' || *s == 'm' ? R_M : *s == 'H' || *s == 'h' ? R_H : -1; }

static void print_info(void)
{
    char l[96], *p;
    uart_puts("# INA228 smart profiler fw "); p = put_u32(l, FW_VERSION); *p = 0; uart_puts(l);
    uart_puts(ina_ok ? " INA228 ok\n" : " INA228 NOT FOUND\n");
    static const char rn[3] = { 'L', 'M', 'H' };
    for (int i = 0; i < 3; i++) {
        p = l; *p++ = '#'; *p++ = ' '; *p++ = rn[i]; memcpy(p, " R=", 3); p += 3;
        p = put_sci(p, cfg.r[i]); memcpy(p, " ohm off=", 9); p += 9; p = put_sci(p, cfg.off[i]);
        memcpy(p, " A\n", 3); p += 3; uart_write(l, (uint32_t)(p - l));
    }
    p = l; memcpy(p, "# ct=", 5); p += 5; p = put_u32(p, cfg.vshct); memcpy(p, " avg=", 5); p += 5;
    p = put_u32(p, cfg.avg); memcpy(p, " charge_C=", 10); p += 10; p = put_sci(p, (float)q_acc);
    memcpy(p, " energy_J=", 10); p += 10; p = put_sci(p, (float)e_acc); *p++ = '\n';
    uart_write(l, (uint32_t)(p - l));
}

static void do_command(const char *c)
{
    int r;
    if (!strcmp(c, "info")) print_info();
    else if (!strcmp(c, "reset")) { accum_reset(); uart_puts("# accumulators reset\n"); }
    else if (!strcmp(c, "save")) uart_puts(cfg_save() ? "# saved\n" : "# save FAILED\n");
    else if (!strcmp(c, "defaults")) { cfg = CFG_DEFAULT; ina_configure(); uart_puts("# defaults (not saved)\n"); }
    else if (!strcmp(c, "stream on")) cfg.stream = 1;
    else if (!strcmp(c, "stream off")) cfg.stream = 0;
    else if (!strncmp(c, "cal ", 4) && (r = rsel(c + 4)) >= 0) { float v = parse_float(c + 5); if (v > 0) cfg.r[r] = v; print_info(); }
    else if (!strncmp(c, "off ", 4) && (r = rsel(c + 4)) >= 0) { cfg.off[r] = parse_float(c + 5); print_info(); }
    else if (!strncmp(c, "ct ", 3)) { cfg.vshct = (uint8_t)parse_float(c + 3) & 7u; ina_configure(); }
    else if (!strncmp(c, "avg ", 4)) { cfg.avg = (uint8_t)parse_float(c + 4) & 7u; ina_configure(); }
    else uart_puts("# commands: info reset save defaults stream on|off cal L|M|H <ohm> off L|M|H <A> ct <0-7> avg <0-7>\n");
}

static void host_apply(void)
{
    uint8_t lo, hi, img[sizeof(regs_t)];
    __disable_irq();
    lo = host_lo; hi = host_hi; host_lo = 0xFF; host_hi = 0; host_dirty = 0;
    memcpy(img, rx_img, sizeof img);
    __enable_irq();
    /* a field is taken only if every one of its bytes was written in this transaction */
#define TOUCHED(o, n) (lo <= (o) && hi >= (o) + (n) - 1)
    float f;
    for (int i = 0; i < 3; i++) {
        if (TOUCHED(0x30 + 4 * i, 4)) { memcpy(&f, img + 0x30 + 4 * i, 4); if (f > 0.0f && f < 1.0e6f) cfg.r[i] = f; }
        if (TOUCHED(0x3C + 4 * i, 4)) { memcpy(&f, img + 0x3C + 4 * i, 4); if (f > -1.0f && f < 1.0f) cfg.off[i] = f; }
    }
    if (TOUCHED(0x48, 1) || TOUCHED(0x49, 1)) {
        if (TOUCHED(0x48, 1)) cfg.vshct = img[0x48] & 7u;
        if (TOUCHED(0x49, 1)) cfg.avg = img[0x49] & 7u;
        ina_configure();
    }
    if (TOUCHED(0x4A, 1)) cfg.stream = img[0x4A] ? 1 : 0;
    if (TOUCHED(0x4B, 1)) {
        if (img[0x4B] == 0x01) accum_reset();
        else if (img[0x4B] == 0xA5) cfg_save();
        else if (img[0x4B] == 0x5A) { cfg = CFG_DEFAULT; ina_configure(); }
    }
#undef TOUCHED
}

/* ================================================================ init, main */
static void gpio_init(void)
{
    RCC->IOPENR |= RCC_IOPENR_GPIOAEN | RCC_IOPENR_GPIOBEN;
    RCC->APBENR2 |= RCC_APBENR2_SYSCFGEN;
    /* CTL_H, CTL_M: drive HIGH first (range H, same as the pull-ups), then outputs; LED output */
    GPIOA->BSRR = (1u << 4) | (1u << 5);
    GPIOA->MODER = (GPIOA->MODER & ~((3u << 8) | (3u << 10) | (3u << 12) | (3u << 0) | (3u << 2)))
                 | (1u << 8) | (1u << 10) | (1u << 12);           /* PA0, PA1 inputs */
    /* PA2/PA3 USART2 AF1 */
    GPIOA->MODER = (GPIOA->MODER & ~((3u << 4) | (3u << 6))) | (2u << 4) | (2u << 6);
    GPIOA->AFR[0] = (GPIOA->AFR[0] & ~((0xFu << 8) | (0xFu << 12))) | (1u << 8) | (1u << 12);
    /* PA11/PA12 I2C2 AF6 open drain */
    GPIOA->OTYPER |= (1u << 11) | (1u << 12);
    GPIOA->MODER = (GPIOA->MODER & ~((3u << 22) | (3u << 24))) | (2u << 22) | (2u << 24);
    GPIOA->AFR[1] = (GPIOA->AFR[1] & ~((0xFu << 12) | (0xFu << 16))) | (6u << 12) | (6u << 16);
    /* PB6/PB7 I2C1 AF6 open drain (PB8 bonded to PB7, PB3-5 to PB6: those stay analog) */
    GPIOB->OTYPER |= (1u << 6) | (1u << 7);
    GPIOB->MODER = (GPIOB->MODER & ~((3u << 12) | (3u << 14))) | (2u << 12) | (2u << 14);
    GPIOB->AFR[0] = (GPIOB->AFR[0] & ~((0xFu << 24) | (0xFu << 28))) | (6u << 24) | (6u << 28);
    /* comparator: EXTI line 0 = PA0, falling edge */
    EXTI->EXTICR[0] &= ~0xFFu;
    EXTI->FTSR1 |= EXTI_FTSR1_FT0;
    NVIC_SetPriority(EXTI0_1_IRQn, 0);
    NVIC_EnableIRQ(EXTI0_1_IRQn);
}

int main(void)
{
    clock_init();
    gpio_init();
    timer_init();
    cfg_load();
    i2c1_init();
    uart_init();
    ina_ok = (uint8_t)ina_init();
    i2c2_init();
    set_range(R_H);                               /* start safe, auto-range down from there */
    accum_reset();
    publish(0, 0);
    print_info();
    if (cfg.stream) uart_puts("t_us,current_A,voltage_V,range\n");

    uint32_t retry = micros();
    for (;;) {
        if (!ina_ok) {                             /* keep looking for the INA228 every 0.5 s */
            if ((uint32_t)(micros() - retry) > 500000u) { retry = micros(); ina_ok = (uint8_t)ina_init(); GPIOA->ODR ^= (1u << 6); publish(0, 0); }
        } else {
            ina_set_adcrange(range);               /* after a fast step-up from the comparator */
            if (!(GPIOA->IDR & (1u << 1))) sample();   /* ALERT low: conversion ready */
            else if ((uint32_t)(micros() - t_prev) > 1000000u) { ina_ok = (uint8_t)ina_init(); t_prev = micros(); }
        }
        if (rx_ready) { do_command(rxline); rx_len = 0; rx_ready = 0; }
        if (host_dirty) host_apply();
    }
}
