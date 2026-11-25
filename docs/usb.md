# Rev D: USB-C power meter (in-line, 4–48 V, 5 A)

Rev D is a different tool from variants A–C: an in-line USB-C tester for chargers, phones, power banks and other USB-C devices, in the spirit of an FNIRSI FNB58, with all display and analysis on the PC.

```
charger ──► J1 (USB-C plug) ══ R1 10 mΩ ══ J2 (USB-C receptacle) ──► cable ──► phone / device
                     │   CC1 CC2 D+ D- SBU1 SBU2 wired straight through   │
                     └── U1 INA228 (I, V) ── U2 STM32G0B1 ── J3 USB-C ──► PC (USB CDC serial)
```

- **J1** plugs straight into the charger, with no cable in between.
- **J2** takes the device's cable.
- **J3** goes to the PC. It powers only the meter (U1, U2), never the device under test.

## What it measures

| | |
|---|---|
| Bus voltage | 0–85 V input range of the INA228, 195 µV steps. Rated use 4–48 V (USB PD 3.1 EPR) |
| Current | ±4.096 A fine range (7.8 µA steps); ±16 A coarse range (31 µA steps). Board limit 5 A |
| Ranging | automatic and invisible to the PC: above 3.8 A the INA228 switches to the coarse range, below 3.0 A it returns |
| Power, charge, energy | V × I per conversion; mAh and mWh integrated on the board at the full conversion rate |
| CC1, CC2, D+, D− | read through 1 MΩ / 1 MΩ dividers by the STM32 ADC: Type-C current advertisement, VCONN, QC/Apple/BC1.2 levels |
| Sample rate | about 925 conversions/s by default (540 µs shunt + 540 µs bus). `ct 0` … `ct 7` trades speed against noise |

The 1 % shunt sets the uncalibrated accuracy. `gain` and `zero` (see [firmware/usb](../firmware/usb)) calibrate it against a reference meter.

## Will USB PD 3.1 (48 V) damage it?

No, the electronics are designed for it:

- **INA228:** its inputs (IN+, IN−, VBUS) are rated to 85 V.
- **D1 (SMBJ51A):** stands off 51 V, so it stays quiet at 48 V EPR, and clamps surges below the INA228's 85 V limit.
- **Everything else on the 48 V side** is copper, R1 (2 W, 0.25 W at 5 A) and connectors.
- **The dividers:** CC and D± never carry VBUS, so they stay low-voltage.

The **connectors are the limit**:

- The JAE DX07 plug is rated 20 V AC rms, with 1.25 A per power pin (5 A over its four VBUS pins).
- At 28, 36 or 48 V EPR it runs above its datasheet voltage rating. It has a 100 V rms dielectric test, but there is no margin guarantee.
- For SPR chargers (up to 20 V, 5 A) everything is inside its ratings.

EPR also needs a 240 W (EPR) e-marked cable between J2 and the device. The meter passes CC and VCONN straight through, so the charger reads that cable's e-marker as if the meter were not there.

## Pass-through lines

J1 and J2 are wired pin to pin, like a short extension:

- **Straight through:** VBUS (via R1), GND, CC1, CC2, D+, D−, SBU1 and SBU2.
- **Both plug orientations work**, because the charger sees exactly what it would see with the cable alone.
- **VCONN** for e-marked cables reaches the cable.
- **SuperSpeed pairs are not passed** (J2 is a USB 2.0 receptacle), so a device behind the meter gets USB 2.0 data at most.
- **High Speed data:** the D± traces are not impedance-controlled. Charging protocols are unaffected; 480 Mbit/s data usually works over traces this short but is not guaranteed.
- **The monitor dividers** load each line with about 2 MΩ, negligible next to the Type-C Rp/Rd values (5.1–56 kΩ).

## PC connection

- **J3:** USB-C with 5.1 kΩ Rd on CC1/CC2, so any USB-C or A-to-C cable works. USBLC6-2SC6 ESD protection.
- **U2:** a USB full-speed CDC device with no crystal. HSI48 is trimmed by the CRS from the host's SOF.
- **Driver:** none needed on Windows 10+, macOS or Linux. The meter shows up as a serial port.
- **VID:PID** is `1209:0001`, the pid.codes test ID for development. Change it in `usb_descriptors.c` before selling boards.
- **Grounds:** the PC's ground and the charger's ground are joined on the board (the INA228 needs a common reference). This is the same as with any USB tester connected to a PC.

## PC app

https://kourosh.site/ina228-current-profiler/app/ (source: [app/index.html](app/index.html)). One page with no install, for Chrome, Edge or Opera on a desktop:

- **Live:** voltage, current and power charts (10 s to the whole session, peaks kept at every zoom), plus mAh, Wh and time.
- **Charger:** what the charger negotiates (USB PD level, PPS, Type-C current, QC, Apple, BC1.2) from the CC/D± voltages and the bus voltage.
- **Session report:**
  - charging phases (start-up, fast charge, taper, full) and the voltage levels used;
  - time to deliver half and 80 % of the energy, and the draw once full;
  - charger + cable resistance from the voltage sag under load;
  - battery capacity and health estimated from the energy delivered and the battery % at the start and end.
- **Exports and files:** CSV data, a JSON report and print/PDF. It also opens CSV logs from `host/meter.py`.
- **Demo:** a demo session (a phone charging on 9 V PD, sped up 40×) shows everything without a board.

## Programming

- **New chips:** the STM32G0B1 starts ST's USB DFU bootloader when its flash is empty. Connect J3 and run `make dfu` (dfu-util) or use STM32CubeProgrammer. No ST-Link needed.
- **Later updates:** the `dfu` command (or `make dfu` after it) re-enters the bootloader.
- **J4:** an optional 1.27 mm SWD header (not assembled).

## Board

- **Size:** 56 × 32 mm, plus the 5 mm plug paddle on the left edge. 2 layers.
- **5 A paths (hand-routed in `tools/gen_pcb_usb.py`):**
  - J1's four VBUS pins (on both layers) join through vias into 2 mm buses.
  - The lower half crosses the signal corridor on the top layer while the six pass-through lines run underneath on the bottom layer.
  - R1 is fed from the left, and J2's two VBUS pads are joined on the bottom layer behind the pad row.
- **Kelvin taps:** IN+ and IN− leave R1's pads on their inner corners. IN− and the INA228's VBUS pin share one trace.
- **Everything else** is routed by Freerouting, with GND pours on both layers.

### Before ordering

- **PCB thickness for J1.** The DX07 slim plug clamps the board edge between its two contact rows (straddle mount). Take the paddle thickness from JAE drawing SJ116680 and order that thickness: it is thinner than the usual 1.6 mm.
- **J1 assembly.** J1 has pads on both layers. If JLCPCB declines to place it, order it as "do not place" and solder it by hand (0.5 mm pitch, both sides).
- **Rotations in JLC's preview.** Check J1, J2, J3, U2 and U4 there. They were not yet checked against JLC's 3D models (see [ordering.md](ordering.md)).

## Files

- `hardware-usb/`: KiCad project, `fab/` (Gerbers, drill, positions), `3d/`, `jlcpcb/`, `schematic.pdf`, `BOM.csv`
- `firmware/usb/`: firmware (TinyUSB CDC) and `host/meter.py`
- `docs/usb/`: schematic, PCB and 3D renders
