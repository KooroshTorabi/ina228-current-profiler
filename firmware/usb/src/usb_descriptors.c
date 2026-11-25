/* USB descriptors: a single CDC-ACM interface (shows up as COMx / ttyACMx / cu.usbmodem*). */
#include <string.h>
#include "tusb.h"
#include "stm32g0xx.h"

/* pid.codes test VID/PID (1209:0001), meant for private projects and development.
   Change both before selling boards. */
#define USB_VID   0x1209
#define USB_PID   0x0001
#define USB_BCD   0x0200

static const tusb_desc_device_t desc_device = {
    .bLength = sizeof(tusb_desc_device_t),
    .bDescriptorType = TUSB_DESC_DEVICE,
    .bcdUSB = USB_BCD,
    .bDeviceClass = TUSB_CLASS_MISC,
    .bDeviceSubClass = MISC_SUBCLASS_COMMON,
    .bDeviceProtocol = MISC_PROTOCOL_IAD,
    .bMaxPacketSize0 = CFG_TUD_ENDPOINT0_SIZE,
    .idVendor = USB_VID,
    .idProduct = USB_PID,
    .bcdDevice = 0x0100,
    .iManufacturer = 0x01,
    .iProduct = 0x02,
    .iSerialNumber = 0x03,
    .bNumConfigurations = 0x01,
};

uint8_t const *tud_descriptor_device_cb(void) { return (uint8_t const *)&desc_device; }

enum { ITF_NUM_CDC = 0, ITF_NUM_CDC_DATA, ITF_NUM_TOTAL };
#define EPNUM_CDC_NOTIF   0x81
#define EPNUM_CDC_OUT     0x02
#define EPNUM_CDC_IN      0x82
#define CONFIG_TOTAL_LEN  (TUD_CONFIG_DESC_LEN + TUD_CDC_DESC_LEN)

static const uint8_t desc_configuration[] = {
    TUD_CONFIG_DESCRIPTOR(1, ITF_NUM_TOTAL, 0, CONFIG_TOTAL_LEN, 0x00, 100),
    TUD_CDC_DESCRIPTOR(ITF_NUM_CDC, 4, EPNUM_CDC_NOTIF, 8, EPNUM_CDC_OUT, EPNUM_CDC_IN, 64),
};

uint8_t const *tud_descriptor_configuration_cb(uint8_t index) { (void)index; return desc_configuration; }

static const char *const strings[] = {
    NULL,                               /* 0: language, handled below */
    "kourosh.site",                     /* 1: manufacturer */
    "USB-C power meter rev D",          /* 2: product */
    NULL,                               /* 3: serial, from the chip's unique ID */
    "Power meter",                      /* 4: CDC interface */
};

static uint16_t desc_str[33];

uint16_t const *tud_descriptor_string_cb(uint8_t index, uint16_t langid)
{
    (void)langid;
    uint8_t n;
    if (index == 0) {
        desc_str[1] = 0x0409;
        n = 1;
    } else if (index == 3) {
        static const char hex[] = "0123456789ABCDEF";
        const uint32_t uid[3] = { *(const uint32_t *)UID_BASE, *(const uint32_t *)(UID_BASE + 4u),
                                  *(const uint32_t *)(UID_BASE + 8u) };
        n = 0;
        for (int w = 0; w < 3; w++)
            for (int s = 28; s >= 0; s -= 4) desc_str[1 + n++] = (uint16_t)hex[(uid[w] >> s) & 0xFu];
    } else if (index < sizeof(strings) / sizeof(strings[0])) {
        const char *s = strings[index];
        n = (uint8_t)strlen(s);
        if (n > 32) n = 32;
        for (uint8_t i = 0; i < n; i++) desc_str[1 + i] = (uint16_t)s[i];
    } else {
        return NULL;
    }
    desc_str[0] = (uint16_t)((TUSB_DESC_STRING << 8) | (2u * n + 2u));
    return desc_str;
}
