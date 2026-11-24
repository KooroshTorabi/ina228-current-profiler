# INA228 auto-ranging current profiler (nA – 2.5 A)

A small, open hardware current meter for profiling microcontrollers such as the STM32, from **deep sleep (tens of nA)** up to **full load (2.5 A)**. It is built from a TI **INA228** 20-bit power monitor, three series shunt resistors and two P-MOSFETs that switch the measurement range. A separate **logger MCU** reads the INA228 over I2C, switches ranges and stores the data.

![Schematic](docs/schematic.svg)

## How it works

```
VIN ──R1 50mΩ──●──R2 1Ω──●──R3 1kΩ──● DUT_VDD ──► STM32 (DUT)
               │ NODE_A  │ NODE_B   │
               │         └── Q2 ────┤   Q2 bypasses R3        (mid range)
               └────────── Q1 ──────┘   Q1 bypasses R2 + R3   (high range)

INA228: IN+ = VIN, IN- = DUT_VDD  → always measures the whole chain
```

| Range | FETs on | Total shunt | INA228 ADCRANGE | Full scale | Useful span |
|---|---|---|---|---|---|
| L | none | ≈ 1001 Ω | 1 (±40.96 mV) | ≈ 40 µA | ~5 nA – 35 µA |
| M | Q2 | ≈ 1.05 Ω | 1 (±40.96 mV) | ≈ 38 mA | 20 µA – 35 mA |
| H | Q1 | ≈ 60 mΩ | 0 (±163.84 mV) | > 2.5 A | 20 mA – 2.5 A |

Because Q1 bypasses R2 and R3 together, only **one** MOSFET's Rds(on) sits in the path at high current.

See [docs/design.md](docs/design.md) for the design notes: wake-up transients, leakage, calibration and firmware strategy.

## Repository layout

```
hardware/
  kicad/            KiCad 7 project (opens in KiCad 8/9)
  schematic.pdf     printable schematic
  BOM.csv           bill of materials
docs/
  design.md         design notes and calibration procedure
  schematic.svg
firmware/           logger firmware (planned)
tools/
  gen_schematic.py  regenerates the KiCad schematic, symbol library and BOM
```

## Logger connector (J3)

| Pin | Signal | Notes |
|---|---|---|
| 1 | +3V3 | supplies the INA228 |
| 2 | GND | common ground with the DUT |
| 3 | SDA | INA228 at I2C address 0x40 |
| 4 | SCL | |
| 5 | ALERT | open drain; use as an interrupt for fast up-ranging |
| 6 | CTL_H | HIGH = Q1 on (high range). Pulled HIGH at reset |
| 7 | CTL_M | HIGH = Q2 on (mid range). Pulled HIGH at reset |

## Status

- [x] Concept and schematic
- [ ] PCB layout
- [ ] Logger firmware with auto-ranging
- [ ] Calibration and validation against a reference meter

## License

MIT, see [LICENSE](LICENSE).
