# Firmware: smart profiler (variant C, STM32G030F6P6)

Bare-metal C on CMSIS headers, no HAL. The whole build is `src/main.c`.

- **Size:** about 14 KB of 30 KB flash and 2.5 KB of 8 KB RAM.
- **Calibration:** stored in the last 2 KB flash page.

## Build and flash

```sh
# Arm GNU toolchain (arm-none-eabi-gcc) on PATH
make                 # -> build/profiler.elf / .bin / .hex
make flash           # st-flash, or STM32_Programmer_CLI as a fallback
```

- **STM32CubeIDE:** create an empty STM32G030F6Px project, replace its sources with `src/main.c` and `src/syscalls.c`, and build.
- **Wiring:** an ST-Link connects to J4 (SWDIO, SWCLK, NRST, GND). The board must be powered with 3V3 through J3.

## Host interfaces (J3)

| J3 pin | Signal | |
|---|---|---|
| 1 | 3V3 | supplies the INA228 and MCU (about 6 mA) |
| 2 | GND | |
| 3 | SDA | I2C slave 0x48, up to 400 kHz |
| 4 | SCL | |
| 5 | TX | CSV out, 921600 8N1, 3.3 V |
| 6 | RX | text commands in |

### I2C register map (little endian; read any span starting at any address)

| Addr | Type | Name | |
|---|---|---|---|
| 0x00 | u8 | WHO_AM_I | 0xA8 |
| 0x01 | u8 | FW_VERSION | 1 |
| 0x02 | u8 | RANGE | 0 = L, 1 = M, 2 = H |
| 0x03 | u8 | FLAGS | bit0 latest sample valid, bit1 INA228 found, bit2 over range |
| 0x04 | f32 | CURRENT | A, latest valid sample |
| 0x08 | f32 | VOLTAGE | V at DUT_VDD |
| 0x0C | f32 | POWER | W |
| 0x10 | u32 | SAMPLES | conversions since reset |
| 0x14 | u32 | TIME_US | timestamp of the latest conversion |
| 0x18 | f64 | CHARGE | C since reset |
| 0x20 | f64 | ENERGY | J since reset |
| 0x28 | f64 | ELAPSED | s since reset |
| 0x30 | 3 × f32 | R_L, R_M, R_H | ohm, read/write |
| 0x3C | 3 × f32 | OFF_L, OFF_M, OFF_H | A, read/write |
| 0x48 | u8 | VSHCT | 0–7, read/write |
| 0x49 | u8 | AVG | 0–7, read/write |
| 0x4A | u8 | STREAM | 1 = CSV on, read/write |
| 0x4B | u8 | CMD | write 0x01 reset accumulators, 0xA5 save to flash, 0x5A defaults |

- **Consistent reads:** a read transaction returns a consistent snapshot, so all fields belong to the same sample.
- **Exact averages:** the average current between two reads is `(CHARGE2 − CHARGE1) / (ELAPSED2 − ELAPSED1)`. It is exact however slowly you poll.

### UART commands (end with newline)

`info` · `reset` · `save` · `defaults` · `stream on|off` · `cal L|M|H <ohm>` · `off L|M|H <A>` · `ct <0-7>` · `avg <0-7>`

Status lines start with `#`.

## Host scripts

- `host/read_i2c.py`: Raspberry Pi over I2C. Prints live current and the exact average between reads, and can log CSV.
- `host/read_uart.py`: any PC or Pi with a USB-serial adapter. Prints or logs every sample.

## Status

The firmware compiles without warnings, and its number formatting, parsing and register decoding were checked on a PC. It has **not yet run on hardware**: bring-up is the first step once boards arrive.

- **INA228 check:** `info` must report `INA228 ok`.
- **Ranging check:** step a load and watch the range column.
- **Calibration:** calibrate each range.
