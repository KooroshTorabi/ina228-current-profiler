/*
 * USB-C power meter (rev D) - firmware for the on-board STM32G0B1CBT6.
 *
 * The board sits between a charger (J1, plug) and a device (J2, receptacle). U1 (INA228)
 * measures the high-side current through R1 (10 mOhm) and the bus voltage. U2 talks to the
 * PC over USB (J3) as a CDC serial port:
 *
 *   data lines   "t_us,voltage_V,current_A,power_W,range"            (every N conversions)
 *   status lines "#S,t_us,mAh,mWh,seconds,cc1_V,cc2_V,dp_V,dm_V,state[,dropped=N]"  (every 500 ms)
 *   replies      "#..." to text commands (type "help")
 *
 * Ranging is automatic and invisible to the host: the INA228 starts in ADCRANGE 1
 * (+-40.96 mV = +-4.096 A, 7.8 uA/LSB) and switches to ADCRANGE 0 (+-163.84 mV = +-16.4 A)
 * above 3.8 A; it returns below 3.0 A. One conversion is dropped after every switch.
 *
 * Pins: PA0..PA3 ADC (CC1, CC2, D+, D- through 1M/1M dividers), PA4 INA ALERT (conversion
 *       ready), PA5 LED, PA11/PA12 USB, PA13/PA14 SWD, PB6/PB7 I2C1 (INA228 at 0x40).
 */
#include <stdint.h>
#include <string.h>
#include "stm32g0xx.h"
#include "tusb.h"

#define FW_VERSION      1
#define INA_ADDR        0x40
#define R_SHUNT         0.010f              /* R1, ohms */
#define VREFINT_CAL     (*(const uint16_t *)0x1FFF75AAu)   /* raw VREFINT at 3.0 V, 30 C */
#define DIV             2.0f                /* 1M/1M monitor dividers */

/* INA228 registers */
#define INA_CONFIG      0x00
#define INA_ADC_CONFIG  0x01
#define INA_VSHUNT      0x04
#define INA_VBUS        0x05
#define INA_DIAG_ALRT   0x0B
#define INA_MFR_ID      0x3E
#define INA_DEVICE_ID   0x3F

#define FS_LO           0.04096f            /* ADCRANGE 1 full scale, V */
#define FS_HI           0.16384f            /* ADCRANGE 0 full scale, V */
#define UP_V            0.038f              /* 3.8 A: leave the fine range */
#define DOWN_V          0.030f              /* 3.0 A: return to it ... */
#define DOWN_COUNT      16                  /* ... after this many conversions in a row */

/* ================================================================ settings in flash */
#define CFG_ADDR        0x0801F800u         /* last 2 KB page of the 128 KB flash */
#define CFG_PAGE        63u
#define CFG_MAGIC       0x55534244u         /* "USBD" */
typedef struct {
    uint32_t magic;
    float gain;                             /* current = raw * gain - offset */
    float offset;                           /* A */
    float vgain;                            /* voltage = raw * vgain */
    uint16_t every;                         /* conversions averaged into one data line */
    uint8_t ct;                             /* INA228 VBUSCT = VSHCT code, 0..7 (50 us .. 4.12 ms) */
    uint8_t avg;                            /* INA228 AVG code, 0..7 (1 .. 1024) */
    uint8_t stream;                         /* data lines on/off */
    uint8_t range_mode;                     /* 0 auto, 1 fine only, 2 coarse only */
    uint8_t pad[2];
} cfg_t;                                    /* 24 bytes: a multiple of 8 for double-word programming */
static const cfg_t CFG_DEFAULT = { CFG_MAGIC, 1.0f, 0.0f, 1.0f, 10, 4, 0, 1, 0, {0, 0} };
static cfg_t cfg;

/* ================================================================ time */
static inline uint32_t micros(void) { return TIM2->CNT; }
static void delay_us(uint32_t us) { uint32_t t = micros(); while (micros() - t < us) {} }

static void clock_init(void)
{
    /* HSI16 -> PLL x8 /2 = 64 MHz. Flash: 2 wait states at 64 MHz. */
    FLASH->ACR = (FLASH->ACR & ~FLASH_ACR_LATENCY) | FLASH_ACR_LATENCY_1 | FLASH_ACR_PRFTEN | FLASH_ACR_ICEN;
    while ((FLASH->ACR & FLASH_ACR_LATENCY) != FLASH_ACR_LATENCY_1) {}
    RCC->PLLCFGR = RCC_PLLCFGR_PLLSRC_HSI | (0u << RCC_PLLCFGR_PLLM_Pos) | (8u << RCC_PLLCFGR_PLLN_Pos)
                 | (1u << RCC_PLLCFGR_PLLR_Pos) | RCC_PLLCFGR_PLLREN;
    RCC->CR |= RCC_CR_PLLON;
    while (!(RCC->CR & RCC_CR_PLLRDY)) {}
    RCC->CFGR = (RCC->CFGR & ~RCC_CFGR_SW) | RCC_CFGR_SW_1;
    while ((RCC->CFGR & RCC_CFGR_SWS) != RCC_CFGR_SWS_1) {}
    SystemCoreClock = 64000000u;

    /* USB: HSI48 kept on frequency by the CRS, synchronised to the host's 1 ms SOF (no crystal) */
    RCC->APBENR1 |= RCC_APBENR1_PWREN | RCC_APBENR1_USBEN | RCC_APBENR1_CRSEN | RCC_APBENR1_TIM2EN | RCC_APBENR1_I2C1EN;
    RCC->APBENR2 |= RCC_APBENR2_SYSCFGEN | RCC_APBENR2_ADCEN;
    RCC->IOPENR |= RCC_IOPENR_GPIOAEN | RCC_IOPENR_GPIOBEN;
    PWR->CR2 |= PWR_CR2_USV;                                   /* VDDUSB valid */
    RCC->CR |= RCC_CR_HSI48ON;
    while (!(RCC->CR & RCC_CR_HSI48RDY)) {}
    RCC->CCIPR2 &= ~RCC_CCIPR2_USBSEL;                         /* 00 = HSI48 */
    CRS->CFGR = (47999u << CRS_CFGR_RELOAD_Pos) | (34u << CRS_CFGR_FELIM_Pos) | (2u << CRS_CFGR_SYNCSRC_Pos);
    CRS->CR |= CRS_CR_AUTOTRIMEN | CRS_CR_CEN;

    TIM2->PSC = 63;                                            /* 1 MHz, 32 bit */
    TIM2->ARR = 0xFFFFFFFFu;
    TIM2->EGR = TIM_EGR_UG;
    TIM2->CR1 = TIM_CR1_CEN;
}

static void gpio_init(void)
{
    /* PA0..PA3 analog (reset state), PA4 input (ALERT, pulled up by R2), PA5 LED output */
    GPIOA->MODER = (GPIOA->MODER & ~(GPIO_MODER_MODE4 | GPIO_MODER_MODE5)) | GPIO_MODER_MODE5_0;
    /* PB6 SCL, PB7 SDA: AF6, open drain (R3/R4 pull-ups) */
    GPIOB->MODER = (GPIOB->MODER & ~(GPIO_MODER_MODE6 | GPIO_MODER_MODE7)) | GPIO_MODER_MODE6_1 | GPIO_MODER_MODE7_1;
    GPIOB->OTYPER |= GPIO_OTYPER_OT6 | GPIO_OTYPER_OT7;
    GPIOB->OSPEEDR |= GPIO_OSPEEDR_OSPEED6_0 | GPIO_OSPEEDR_OSPEED7_0;
    GPIOB->AFR[0] = (GPIOB->AFR[0] & ~(0xFFu << 24)) | (6u << 24) | (6u << 28);
}
static void led(int on) { GPIOA->BSRR = on ? GPIO_BSRR_BS5 : GPIO_BSRR_BR5; }

/* ================================================================ I2C1 -> INA228 */
static void i2c_init(void)
{
    RCC->CCIPR = (RCC->CCIPR & ~RCC_CCIPR_I2C1SEL) | (2u << RCC_CCIPR_I2C1SEL_Pos);   /* HSI16 */
    I2C1->CR1 = 0;
    I2C1->TIMINGR = 0x10320309u;            /* 400 kHz from 16 MHz (RM0444 example timing) */
    I2C1->CR1 = I2C_CR1_PE;
}

static int i2c_wait(uint32_t flag)
{
    uint32_t t = micros();
    while (!(I2C1->ISR & flag)) {
        if (I2C1->ISR & I2C_ISR_NACKF) { I2C1->ICR = I2C_ICR_NACKCF | I2C_ICR_STOPCF; return -1; }
        if (micros() - t > 2000u) { I2C1->CR1 = 0; I2C1->CR1 = I2C_CR1_PE; return -2; }
    }
    return 0;
}

static int ina_read(uint8_t reg, uint8_t *buf, uint8_t n)
{
    I2C1->CR2 = (INA_ADDR << 1) | (1u << I2C_CR2_NBYTES_Pos) | I2C_CR2_START;
    if (i2c_wait(I2C_ISR_TXIS)) return -1;
    I2C1->TXDR = reg;
    if (i2c_wait(I2C_ISR_TC)) return -1;
    I2C1->CR2 = (INA_ADDR << 1) | I2C_CR2_RD_WRN | ((uint32_t)n << I2C_CR2_NBYTES_Pos) | I2C_CR2_AUTOEND | I2C_CR2_START;
    for (uint8_t i = 0; i < n; i++) {
        if (i2c_wait(I2C_ISR_RXNE)) return -1;
        buf[i] = (uint8_t)I2C1->RXDR;
    }
    if (i2c_wait(I2C_ISR_STOPF)) return -1;
    I2C1->ICR = I2C_ICR_STOPCF;
    return 0;
}

static int ina_write16(uint8_t reg, uint16_t v)
{
    I2C1->CR2 = (INA_ADDR << 1) | (3u << I2C_CR2_NBYTES_Pos) | I2C_CR2_AUTOEND | I2C_CR2_START;
    uint8_t b[3] = { reg, (uint8_t)(v >> 8), (uint8_t)v };
    for (int i = 0; i < 3; i++) {
        if (i2c_wait(I2C_ISR_TXIS)) return -1;
        I2C1->TXDR = b[i];
    }
    if (i2c_wait(I2C_ISR_STOPF)) return -1;
    I2C1->ICR = I2C_ICR_STOPCF;
    return 0;
}

static uint16_t ina_read16(uint8_t reg)
{
    uint8_t b[2] = { 0, 0 };
    ina_read(reg, b, 2);
    return (uint16_t)((b[0] << 8) | b[1]);
}

/* ================================================================ measurement state */
static uint8_t ina_ok;
static uint8_t adcrange = 1;                /* 1 = fine (+-40.96 mV), 0 = coarse (+-163.84 mV) */
static uint8_t drop;                        /* conversions to drop after a range switch */
static uint8_t below;
static uint32_t t_prev, t_start;
static double q_acc, e_acc;                 /* A*s, W*s */
static double sum_v, sum_i, sum_p;
static uint32_t n_sum;
static uint8_t clipped;

static void ina_set_range(uint8_t r)
{
    adcrange = r;
    ina_write16(INA_CONFIG, r ? 0x0010u : 0x0000u);
    drop = 1;
}

static void ina_apply_adc_config(void)
{
    uint16_t ct = cfg.ct & 7u;
    ina_write16(INA_ADC_CONFIG, (uint16_t)((0xBu << 12) | (ct << 9) | (ct << 6) | (0u << 3) | (cfg.avg & 7u)));
}

static void ina_init(void)
{
    ina_ok = (ina_read16(INA_MFR_ID) == 0x5449u) && ((ina_read16(INA_DEVICE_ID) >> 4) == 0x228u);
    if (!ina_ok) return;
    ina_write16(INA_CONFIG, 0x8000u);                          /* reset */
    delay_us(1000);
    ina_write16(INA_DIAG_ALRT, 0x4000u);                       /* ALERT pin = conversion ready */
    ina_apply_adc_config();
    ina_set_range(cfg.range_mode == 2 ? 0 : 1);
}

static void accum_reset(void)
{
    q_acc = e_acc = 0.0;
    t_prev = t_start = micros();
}

/* ================================================================ USB text output */
static uint32_t dropped;                    /* lines lost because the host did not read fast enough */

static void out(const char *s)
{
    /* never blocks: a host that opens the port but stops reading must not stall the measurement */
    if (!tud_cdc_connected()) return;
    uint32_t n = (uint32_t)strlen(s);
    if (tud_cdc_write_available() < n) { tud_cdc_write_flush(); dropped++; return; }
    tud_cdc_write(s, n);
}

static char *fmt_u(char *p, uint32_t v)
{
    char t[11]; int n = 0;
    do { t[n++] = (char)('0' + v % 10u); v /= 10u; } while (v);
    while (n) *p++ = t[--n];
    return p;
}

static char *fmt_f(char *p, double v, int dec)          /* fixed point, no printf/float libs */
{
    if (v < 0) { *p++ = '-'; v = -v; }
    double sc = 1.0;
    for (int i = 0; i < dec; i++) sc *= 10.0;
    uint64_t x = (uint64_t)(v * sc + 0.5);
    uint64_t ip = x;
    for (int i = 0; i < dec; i++) ip /= 10u;
    p = fmt_u(p, (uint32_t)ip);
    if (dec) {
        *p++ = '.';
        char t[12];
        uint64_t fr = x;
        for (int i = dec - 1; i >= 0; i--) { t[i] = (char)('0' + fr % 10u); fr /= 10u; }
        for (int i = 0; i < dec; i++) *p++ = t[i];
    }
    return p;
}

/* ================================================================ ADC: CC / D+ / D- monitors */
static float mon_v[4];                      /* CC1, CC2, D+, D- in volts at the connector */
static float vdd = 3.3f;

static void adc_init(void)
{
    ADC1->CR = ADC_CR_ADVREGEN;
    delay_us(30);
    ADC1->CFGR2 = (1u << ADC_CFGR2_CKMODE_Pos);                /* PCLK/2 = 32 MHz, synchronous */
    ADC1->CR |= ADC_CR_ADCAL;
    while (ADC1->CR & ADC_CR_ADCAL) {}
    ADC1->SMPR = 7u;                                           /* 160.5 cycles: 500 kohm source */
    ADC1_COMMON->CCR |= ADC_CCR_VREFEN;
    ADC1->ISR = ADC_ISR_ADRDY;
    ADC1->CR |= ADC_CR_ADEN;
    while (!(ADC1->ISR & ADC_ISR_ADRDY)) {}
}

static uint16_t adc_read(uint32_t ch)
{
    ADC1->ISR = ADC_ISR_CCRDY;
    ADC1->CHSELR = 1u << ch;
    while (!(ADC1->ISR & ADC_ISR_CCRDY)) {}
    ADC1->CR |= ADC_CR_ADSTART;
    while (!(ADC1->ISR & ADC_ISR_EOC)) {}
    return (uint16_t)ADC1->DR;
}

static void adc_poll(void)
{
    uint32_t vr = 0;
    for (int i = 0; i < 4; i++) vr += adc_read(13);            /* VREFINT */
    vdd = 3.0f * (float)VREFINT_CAL * 4.0f / (float)vr;
    for (uint32_t ch = 0; ch < 4; ch++) {
        uint32_t s = 0;
        for (int i = 0; i < 4; i++) s += adc_read(ch);
        mon_v[ch] = (float)s / 4.0f * vdd / 4095.0f * DIV;
    }
}

/* A rough reading of what the CC and data lines say. The app does the detailed decoding. */
static const char *line_state(void)
{
    float cc = mon_v[0] > mon_v[1] ? mon_v[0] : mon_v[1];
    float other = mon_v[0] > mon_v[1] ? mon_v[1] : mon_v[0];
    if (cc < 0.2f) {
        if (mon_v[2] > 0.4f && mon_v[2] < 0.8f && mon_v[3] < 0.3f) return "BC1.2/QC-handshake";
        if (mon_v[2] > 2.5f && mon_v[3] > 2.5f) return "Apple-2.4A";
        if (mon_v[2] > 2.5f || mon_v[3] > 2.5f) return "QC-high-V";
        return "no-CC";
    }
    if (other > 4.0f) return "CC+VCONN";
    if (cc < 0.66f) return "CC-default";
    if (cc < 1.23f) return "CC-1.5A";
    if (cc < 2.2f) return "CC-3.0A";
    return "CC-open";
}

/* ================================================================ measurement */
static void sample(void)
{
    uint8_t b[3];
    if (ina_read(INA_VSHUNT, b, 3)) return;
    int32_t raw = (int32_t)(((uint32_t)b[0] << 24) | ((uint32_t)b[1] << 16) | ((uint32_t)b[2] << 8)) >> 12;
    if (ina_read(INA_VBUS, b, 3)) return;
    uint32_t vraw = (((uint32_t)b[0] << 16) | ((uint32_t)b[1] << 8) | b[2]) >> 4;
    (void)ina_read16(INA_DIAG_ALRT);                           /* releases ALERT */
    uint32_t now = micros();

    float vsh = (float)raw * (adcrange ? 78.125e-9f : 312.5e-9f);
    float fs = adcrange ? FS_LO : FS_HI;
    float vbus = (float)vraw * 195.3125e-6f * cfg.vgain;
    float cur = vsh / R_SHUNT * cfg.gain - cfg.offset;
    float avs = vsh < 0 ? -vsh : vsh;

    uint8_t was = adcrange;
    static float cur_last, vbus_last;
    if (drop) {
        /* conversion straddles a range switch: hold the last good reading over the gap */
        uint32_t gap = now - t_prev; t_prev = now;
        q_acc += (double)cur_last * gap * 1e-6;
        e_acc += (double)cur_last * vbus_last * gap * 1e-6;
        drop--;
        return;
    }
    cur_last = cur; vbus_last = vbus;
    if (avs > 0.995f * fs) clipped = 1;
    if (cfg.range_mode == 0) {
        if (adcrange && avs > UP_V) ina_set_range(0);
        else if (!adcrange && avs < DOWN_V) { if (++below >= DOWN_COUNT) { below = 0; ina_set_range(1); } }
        else below = 0;
    }

    /* charge and energy: trapezoid-free, current held over the interval (dt is ~1 ms) */
    uint32_t dt = now - t_prev; t_prev = now;
    q_acc += (double)cur * dt * 1e-6;
    e_acc += (double)cur * vbus * dt * 1e-6;

    sum_v += vbus; sum_i += cur; sum_p += (double)cur * vbus; n_sum++;
    if (n_sum >= cfg.every) {
        if (cfg.stream) {
            char line[80], *p = line;
            p = fmt_u(p, now); *p++ = ',';
            p = fmt_f(p, sum_v / n_sum, 4); *p++ = ',';
            p = fmt_f(p, sum_i / n_sum, 6); *p++ = ',';
            p = fmt_f(p, sum_p / n_sum, 5); *p++ = ',';
            *p++ = was ? 'F' : 'C';
            if (clipped) *p++ = '!';
            *p++ = '\n'; *p = 0;
            out(line);
        }
        sum_v = sum_i = sum_p = 0; n_sum = 0; clipped = 0;
    }
}

static void status_line(void)
{
    char line[160], *p = line;
    memcpy(p, "#S,", 3); p += 3;
    p = fmt_u(p, micros()); *p++ = ',';
    p = fmt_f(p, q_acc / 3.6, 4); *p++ = ',';               /* mAh */
    p = fmt_f(p, e_acc / 3.6, 4); *p++ = ',';               /* mWh */
    p = fmt_f(p, (double)(micros() - t_start) * 1e-6, 1); *p++ = ',';
    for (int i = 0; i < 4; i++) { p = fmt_f(p, mon_v[i], 3); *p++ = ','; }
    const char *st = ina_ok ? line_state() : "INA228-missing";
    size_t n = strlen(st); memcpy(p, st, n); p += n;
    if (dropped) { memcpy(p, ",dropped=", 9); p += 9; p = fmt_u(p, dropped); }
    *p++ = '\n'; *p = 0;
    out(line);
}

/* ================================================================ flash */
static void cfg_load(void)
{
    const cfg_t *f = (const cfg_t *)CFG_ADDR;
    cfg = (f->magic == CFG_MAGIC) ? *f : CFG_DEFAULT;
    if (!(cfg.gain > 0.5f && cfg.gain < 2.0f) || !(cfg.vgain > 0.5f && cfg.vgain < 2.0f)
        || !(cfg.offset > -1.0f && cfg.offset < 1.0f) || cfg.every == 0 || cfg.range_mode > 2)
        cfg = CFG_DEFAULT;
}

static int cfg_save(void)
{
    __disable_irq();
    while (FLASH->SR & FLASH_SR_BSY1) {}
    if (FLASH->CR & FLASH_CR_LOCK) { FLASH->KEYR = 0x45670123u; FLASH->KEYR = 0xCDEF89ABu; }
    FLASH->SR = FLASH->SR;
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

/* ================================================================ ST USB DFU bootloader */
static void enter_dfu(void)
{
    tud_disconnect();
    delay_us(200000);
    __disable_irq();
    NVIC->ICER[0] = 0xFFFFFFFFu;
    NVIC->ICPR[0] = 0xFFFFFFFFu;
    SysTick->CTRL = 0;
    RCC->APBRSTR1 |= RCC_APBRSTR1_USBRST;                      /* hand the bootloader a clean USB block */
    RCC->APBRSTR1 &= ~RCC_APBRSTR1_USBRST;
    RCC->CFGR &= ~RCC_CFGR_SW;                                 /* back to HSI16 */
    while (RCC->CFGR & RCC_CFGR_SWS) {}
    RCC->CR &= ~RCC_CR_PLLON;
    SYSCFG->CFGR1 = (SYSCFG->CFGR1 & ~SYSCFG_CFGR1_MEM_MODE) | (1u << SYSCFG_CFGR1_MEM_MODE_Pos);  /* system flash at 0 */
    const uint32_t *sys = (const uint32_t *)0x1FFF0000u;
    __set_MSP(sys[0]);
    __enable_irq();
    ((void (*)(void))sys[1])();
    for (;;) {}
}

/* ================================================================ commands */
static float parse_f(const char *s)
{
    float v = 0, sc = 0, sign = 1;
    while (*s == ' ') s++;
    if (*s == '-') { sign = -1; s++; } else if (*s == '+') s++;
    for (; *s; s++) {
        if (*s >= '0' && *s <= '9') { if (sc) { v += (float)(*s - '0') * sc; sc *= 0.1f; } else v = v * 10 + (float)(*s - '0'); }
        else if (*s == '.') sc = 0.1f;
        else break;
    }
    return sign * v;
}

static int starts(const char *s, const char *w)
{
    size_t n = strlen(w);
    return strncmp(s, w, n) == 0 && (s[n] == 0 || s[n] == ' ');
}

static void reply_cfg(void)
{
    static const char *const ct_us[8] = { "50", "84", "150", "280", "540", "1052", "2074", "4120" };
    char line[200], *p = line;
    const char *head = "#cfg,fw=";
    memcpy(p, head, strlen(head)); p += strlen(head);
    p = fmt_u(p, FW_VERSION);
    memcpy(p, ",gain=", 6); p += 6; p = fmt_f(p, cfg.gain, 5);
    memcpy(p, ",offset_A=", 10); p += 10; p = fmt_f(p, cfg.offset, 6);
    memcpy(p, ",vgain=", 7); p += 7; p = fmt_f(p, cfg.vgain, 5);
    memcpy(p, ",ct_us=", 7); p += 7; strcpy(p, ct_us[cfg.ct & 7]); p += strlen(p);
    memcpy(p, ",avg=", 5); p += 5; p = fmt_u(p, 1u << (cfg.avg == 0 ? 0 : (cfg.avg < 4 ? 2 * cfg.avg : cfg.avg + 3)));
    memcpy(p, ",every=", 7); p += 7; p = fmt_u(p, cfg.every);
    memcpy(p, ",range=", 7); p += 7; strcpy(p, cfg.range_mode == 0 ? "auto" : cfg.range_mode == 1 ? "fine" : "coarse"); p += strlen(p);
    memcpy(p, ",stream=", 8); p += 8; *p++ = cfg.stream ? '1' : '0';
    memcpy(p, ",ina=", 5); p += 5; *p++ = ina_ok ? '1' : '0';
    *p++ = '\n'; *p = 0;
    out(line);
}

static void zero_offset(void)
{
    /* average the current for ~0.5 s with nothing drawing from J2 */
    out("#zeroing: keep J2 unloaded\n");
    float old = cfg.offset; cfg.offset = 0;
    double s = 0; uint32_t n = 0, t = micros();
    while (micros() - t < 500000u) {
        tud_task();
        if (!(GPIOA->IDR & GPIO_IDR_ID4)) {
            uint8_t b[3];
            if (ina_read(INA_VSHUNT, b, 3) == 0) {
                int32_t raw = (int32_t)(((uint32_t)b[0] << 24) | ((uint32_t)b[1] << 16) | ((uint32_t)b[2] << 8)) >> 12;
                s += raw * (adcrange ? 78.125e-9 : 312.5e-9) / R_SHUNT * cfg.gain; n++;
            }
            (void)ina_read16(INA_DIAG_ALRT);
        }
    }
    cfg.offset = n ? (float)(s / n) : old;
}

static void command(char *c)
{
    if (starts(c, "help") || c[0] == '?') {
        out("#commands: info | stream on|off | every N | ct 0-7 | avg 0-7 | range auto|fine|coarse\n"
            "#          reset (mAh/mWh) | zero (offset, J2 unloaded) | gain X | vgain X | save | defaults | dfu\n");
    } else if (starts(c, "info")) {
        reply_cfg();
    } else if (starts(c, "stream")) {
        cfg.stream = strstr(c, "on") != NULL; reply_cfg();
    } else if (starts(c, "every")) {
        float v = parse_f(c + 5); if (v >= 1 && v <= 10000) cfg.every = (uint16_t)v; reply_cfg();
    } else if (starts(c, "ct")) {
        float v = parse_f(c + 2); if (v >= 0 && v <= 7) { cfg.ct = (uint8_t)v; ina_apply_adc_config(); } reply_cfg();
    } else if (starts(c, "avg")) {
        float v = parse_f(c + 3); if (v >= 0 && v <= 7) { cfg.avg = (uint8_t)v; ina_apply_adc_config(); } reply_cfg();
    } else if (starts(c, "range")) {
        if (strstr(c, "auto")) cfg.range_mode = 0;
        else if (strstr(c, "fine")) { cfg.range_mode = 1; ina_set_range(1); }
        else if (strstr(c, "coarse")) { cfg.range_mode = 2; ina_set_range(0); }
        reply_cfg();
    } else if (starts(c, "reset")) {
        accum_reset(); out("#ok\n");
    } else if (starts(c, "zero")) {
        zero_offset(); reply_cfg();
    } else if (starts(c, "gain")) {
        float v = parse_f(c + 4); if (v > 0.5f && v < 2.0f) cfg.gain = v; reply_cfg();
    } else if (starts(c, "vgain")) {
        float v = parse_f(c + 5); if (v > 0.5f && v < 2.0f) cfg.vgain = v; reply_cfg();
    } else if (starts(c, "save")) {
        out(cfg_save() ? "#saved\n" : "#save failed\n");
    } else if (starts(c, "defaults")) {
        cfg = CFG_DEFAULT; ina_apply_adc_config(); ina_set_range(1); reply_cfg();
    } else if (starts(c, "dfu")) {
        out("#entering USB DFU bootloader\n"); tud_cdc_write_flush(); tud_task();
        enter_dfu();
    } else if (c[0]) {
        out("#? type help\n");
    }
}

static void cmd_poll(void)
{
    static char buf[64];
    static uint8_t n;
    while (tud_cdc_available()) {
        char ch = (char)tud_cdc_read_char();
        if (ch == '\r' || ch == '\n') { buf[n] = 0; if (n) command(buf); n = 0; }
        else if (n < sizeof(buf) - 1) buf[n++] = ch;
    }
}

/* ================================================================ main */
void USB_UCPD1_2_IRQHandler(void) { tud_int_handler(0); }

int main(void)
{
    clock_init();
    gpio_init();
    i2c_init();
    adc_init();
    cfg_load();
    led(1);
    ina_init();
    accum_reset();

    tusb_rhport_init_t dev_init = { .role = TUSB_ROLE_DEVICE, .speed = TUSB_SPEED_AUTO };
    tusb_init(0, &dev_init);

    uint32_t t_status = micros(), t_led = micros(), t_retry = micros();
    for (;;) {
        tud_task();
        cmd_poll();
        if (ina_ok && !(GPIOA->IDR & GPIO_IDR_ID4)) sample();
        uint32_t now = micros();
        if (now - t_status >= 500000u) {
            t_status = now;
            adc_poll();
            status_line();
        }
        if (!ina_ok && now - t_retry >= 1000000u) { t_retry = now; ina_init(); }
        /* LED: steady when the host has the port open, slow blink otherwise, dark flicker in the coarse range */
        if (now - t_led >= 250000u) {
            t_led = now;
            static uint8_t ph;
            ph++;
            led(tud_cdc_connected() ? (adcrange ? 1 : (ph & 1)) : ((ph & 3) == 0));
        }
        tud_cdc_write_flush();
    }
}
