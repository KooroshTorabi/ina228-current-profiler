# Rev D firmware: USB-C power meter (STM32G0B1CBT6)

Bare-metal CMSIS plus [TinyUSB](https://github.com/hathach/tinyusb) 0.18.0 (fetched by `make`). The meter is a USB CDC serial port: open it in any terminal or with `host/meter.py`.

## Build and flash

```sh
make                      # build/meter.bin, .hex, .elf   (arm-none-eabi-gcc, git)
make dfu                  # flash over USB with dfu-util
```

- **First flash:** a new STM32G0B1 starts ST's USB DFU bootloader because its flash is empty. Connect J3 to the PC and run `make dfu`.
  - On Windows, STM32CubeProgrammer (USB mode) works as well. dfu-util there needs the WinUSB driver (Zadig).
- **Updates:** send `dfu` to the running firmware, then run `make dfu`.
- **SWD:** optional, through J4 (`make flash`).

Size: about 30 KB flash and 7.5 KB RAM out of 128 KB / 144 KB.

## Output

The meter sends only while the port is open (DTR set). Nothing is buffered while it is closed.

**Data lines:** one per `every` conversions (default 10, about 92 lines/s):

```
t_us,voltage_V,current_A,power_W,range
12345678,20.0312,2.981250,59.71640,F
```

| Field | Meaning |
|---|---|
| `t_us` | microsecond time stamp of the last conversion (32-bit, wraps after 71 min) |
| `voltage_V` | bus voltage on the device side (J2) |
| `current_A` | positive from charger to device |
| `power_W` | mean of V × I over the averaged conversions |
| `range` | `F` = fine (±4.096 A), `C` = coarse (±16.4 A). `!` = a conversion hit full scale |

**Status lines:** every 0.5 s:

```
#S,t_us,mAh,mWh,seconds,cc1_V,cc2_V,dp_V,dm_V,state[,dropped=N]
#S,40123456,12.3456,61.7280,40.1,1.650,0.000,0.600,0.000,CC-3.0A
```

- **mAh, mWh:** integrated on the board from every conversion, not only from the lines sent.
- **Line voltages:** CC and D± voltages at the connector.
- **`state`:** a rough reading for a quick look:
  - Type-C advertisement: `CC-default`, `CC-1.5A`, `CC-3.0A`.
  - `CC+VCONN` (e-marked cable).
  - D± schemes with no CC: `BC1.2/QC-handshake`, `QC-high-V`, `Apple-2.4A`, `no-CC`.
  - A PC app can decode more from the raw voltages.
- **`dropped`:** lines lost because the PC did not read fast enough. Measurement and integration never stop for the PC.

## Commands

Send a line ending in Enter. Replies start with `#`.

| Command | Effect |
|---|---|
| `help` | list of commands |
| `info` | settings: gain, offset, conversion time, averaging, range mode |
| `stream on` / `stream off` | data lines on or off (status lines always) |
| `every N` | average N conversions per data line (1 … 10000). `every 1` = full rate |
| `ct 0`…`ct 7` | INA228 conversion time for shunt and bus: 50, 84, 150, 280, 540, 1052, 2074, 4120 µs |
| `avg 0`…`avg 7` | INA228 averaging: 1, 4, 16, 64, 128, 256, 512, 1024 |
| `range auto` / `fine` / `coarse` | automatic ranging (default) or fixed |
| `reset` | mAh, mWh and seconds back to zero |
| `zero` | measure and store the zero-current offset (nothing connected to J2) |
| `gain X` | current scale factor (0.5 … 2), from a reference meter: X = reference / reading |
| `vgain X` | voltage scale factor, the same way |
| `save` | store settings and calibration in flash |
| `defaults` | factory settings (not saved until `save`) |
| `dfu` | restart into the USB DFU bootloader |

Settings are kept in the last 2 KB flash page. A blank or invalid page means defaults.

## Ranging

- **Start:** the INA228 starts in ADCRANGE 1 (±40.96 mV across 10 mΩ = ±4.096 A, 7.8 µA per step).
- **Up:** a conversion above 38 mV (3.8 A) switches to ADCRANGE 0 (±163.84 mV, 31 µA per step).
- **Down:** 16 conversions in a row below 30 mV switch back.
- **The conversion right after a switch is dropped.** Charge and energy hold the last good reading over that gap.
- **Thresholds and hysteresis:** the gap between 3.0 and 3.8 A keeps the ranges from toggling.

## Host script

```sh
pip install pyserial
python3 host/meter.py                    # live line: V, A, W, mAh, mWh, CC, D+/D-, state
python3 host/meter.py --log charge.csv   # plus every data line in a CSV file
python3 host/meter.py --cmd "every 1"    # full rate (about 925 lines/s)
```

Status: compiles without warnings. Not yet run on hardware.
