# Firmware for the INA228 smart current profiler (STM32G030F6P6)
#   make            -> build/profiler.elf / .bin / .hex
#   make flash      -> program over SWD with an ST-Link (st-flash or STM32_Programmer_CLI)
# Needs arm-none-eabi-gcc (e.g. the xPack or Arm GNU toolchain) on PATH, or set PREFIX.

PREFIX  ?= arm-none-eabi-
CC       = $(PREFIX)gcc
OBJCOPY  = $(PREFIX)objcopy
SIZE     = $(PREFIX)size

TARGET   = build/profiler
SRCS     = src/main.c src/syscalls.c cmsis/device/system_stm32g0xx.c
ASMS     = cmsis/device/startup_stm32g030xx.s

MCU      = -mcpu=cortex-m0plus -mthumb
CFLAGS   = $(MCU) -Os -g -std=c11 -Wall -Wextra -Wno-unused-parameter -ffunction-sections -fdata-sections \
           -DSTM32G030xx -Icmsis/core -Icmsis/device
LDFLAGS  = $(MCU) -Tstm32g030f6.ld -Wl,--gc-sections -Wl,-Map=$(TARGET).map --specs=nano.specs -Wl,--no-warn-rwx-segments

OBJS = $(addprefix build/,$(SRCS:.c=.o)) $(addprefix build/,$(ASMS:.s=.o))

all: $(TARGET).elf $(TARGET).bin $(TARGET).hex
	$(SIZE) $(TARGET).elf

build/%.o: %.c
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c $< -o $@

build/%.o: %.s
	@mkdir -p $(dir $@)
	$(CC) $(MCU) -c $< -o $@

$(TARGET).elf: $(OBJS) stm32g030f6.ld
	$(CC) $(OBJS) $(LDFLAGS) -o $@

$(TARGET).bin: $(TARGET).elf
	$(OBJCOPY) -O binary $< $@

$(TARGET).hex: $(TARGET).elf
	$(OBJCOPY) -O ihex $< $@

flash: $(TARGET).bin
	st-flash --reset write $(TARGET).bin 0x08000000 || STM32_Programmer_CLI -c port=SWD -w $(TARGET).hex -v -rst

clean:
	rm -rf build

.PHONY: all flash clean
