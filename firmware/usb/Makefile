# Firmware for the USB-C power meter, rev D (STM32G0B1CBT6, USB CDC via TinyUSB)
#   make            -> build/meter.elf / .bin / .hex   (fetches TinyUSB 0.18.0 into lib/ on first run)
#   make dfu        -> program over USB with dfu-util (board in the ST bootloader, see README.md)
#   make flash      -> program over SWD with an ST-Link (optional J4)
# Needs arm-none-eabi-gcc (e.g. the xPack or Arm GNU toolchain) on PATH, or set PREFIX; git for TinyUSB.

PREFIX  ?= arm-none-eabi-
CC       = $(PREFIX)gcc
OBJCOPY  = $(PREFIX)objcopy
SIZE     = $(PREFIX)size

TUSB_TAG = 0.18.0
TUSB     = lib/tinyusb
TARGET   = build/meter
SRCS     = src/main.c src/usb_descriptors.c src/syscalls.c cmsis/device/system_stm32g0xx.c \
           $(TUSB)/src/tusb.c $(TUSB)/src/common/tusb_fifo.c $(TUSB)/src/device/usbd.c \
           $(TUSB)/src/device/usbd_control.c $(TUSB)/src/class/cdc/cdc_device.c \
           $(TUSB)/src/portable/st/stm32_fsdev/dcd_stm32_fsdev.c
ASMS     = cmsis/device/startup_stm32g0b1xx.s

MCU      = -mcpu=cortex-m0plus -mthumb
CFLAGS   = $(MCU) -Os -g -std=gnu11 -Wall -Wextra -Wno-unused-parameter -ffunction-sections -fdata-sections \
           -DSTM32G0B1xx -Icmsis/core -Icmsis/device -Isrc -I$(TUSB)/src
LDFLAGS  = $(MCU) -Tstm32g0b1cb.ld -Wl,--gc-sections -Wl,-Map=$(TARGET).map --specs=nano.specs -Wl,--no-warn-rwx-segments

OBJS = $(addprefix build/,$(SRCS:.c=.o)) $(addprefix build/,$(ASMS:.s=.o))

all: $(TUSB)/src/tusb.c $(TARGET).elf $(TARGET).bin $(TARGET).hex
	$(SIZE) $(TARGET).elf

$(TUSB)/src/tusb.c:
	git clone --quiet --depth 1 --branch $(TUSB_TAG) https://github.com/hathach/tinyusb.git $(TUSB)

build/%.o: %.c | $(TUSB)/src/tusb.c
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c $< -o $@

build/%.o: %.s
	@mkdir -p $(dir $@)
	$(CC) $(MCU) -c $< -o $@

$(TARGET).elf: $(OBJS) stm32g0b1cb.ld
	$(CC) $(OBJS) $(LDFLAGS) -o $@

$(TARGET).bin: $(TARGET).elf
	$(OBJCOPY) -O binary $< $@

$(TARGET).hex: $(TARGET).elf
	$(OBJCOPY) -O ihex $< $@

dfu: $(TARGET).bin
	dfu-util -a 0 -s 0x08000000:leave -D $(TARGET).bin

flash: $(TARGET).bin
	st-flash --reset write $(TARGET).bin 0x08000000 || STM32_Programmer_CLI -c port=SWD -w $(TARGET).hex -v -rst

clean:
	rm -rf build

.PHONY: all dfu flash clean
