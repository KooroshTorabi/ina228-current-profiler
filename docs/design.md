# Design notes

## Why three ranges

The span from nA to 2.5 A covers about nine decades, which no single shunt can cover. The INA228 resolves 78.125 nV/LSB on its ±40.96 mV range and has at most ±1 µV of input offset. A 1 kΩ shunt therefore resolves about 0.08 nA/LSB, and offset (which is calibrated out) corresponds to about 1 nA. At the top end, 2.5 A has to stay below 163.84 mV, so the high range uses about 60 mΩ in total.

## Range switching

- **Topology:** the shunts are in series and high-side. The INA228 always measures VIN → DUT_VDD, so the firmware only changes the shunt value and ADCRANGE for each range.
- **Q1 (DMP2008USS):** bypasses R2 + R3. Its datasheet gives Rds(on) ≤ 11 mΩ at Vgs = −2.5 V, and it is lower at −3.3 V. In range H the total is about 50 mΩ + Rds(Q1).
- **Q2 (DMP2037U):** bypasses R3. Its Rds(on) of about 43 mΩ is small next to R2 = 1 Ω and is removed by calibration.
- **Gate drive:** each P-FET gate has a 100 k pull-up and is pulled low by a 2N7002 when its CTL line is HIGH.
  - **The pull-ups (R4, R5) go to VIN, upstream of IN+.** If they went to the FET source, their current would pass through the shunts and be measured.
- **Reset default:** R6 and R7 hold CTL_H and CTL_M HIGH, so the board powers up in the high range. This prevents the DUT from browning out before the firmware takes control.
- **VIN limit:** about 6 V, set by the FET gate-source rating. A different gate drive would be needed above that.

## Wake-up transients

When the STM32 leaves deep sleep, its current jumps from µA to tens of mA within microseconds. Across 1 kΩ that would be a drop of many volts. Three mechanisms handle this:

1. **D1 and D2 (BAS416, low leakage)** clamp the voltage across R2 and R3 to about one diode drop each. Do **not** use Schottky diodes here: their leakage is in the µA range and ruins the low range.
2. **C1 (22 µF)** supplies the transient charge until the range has switched.
3. **INA228 ALERT**, configured as a shunt over-voltage limit, interrupts the logger, which switches up immediately. Switch down in firmware with a delay and hysteresis.

Mark the samples taken around a range switch as invalid in the log.

## Leakage and offsets on range L

| Source | Typical size | How to deal with it |
|---|---|---|
| INA228 input bias current | up to 2.5 nA | zero calibration with the DUT disconnected |
| INA228 differential input impedance (~92 kΩ, parallel to the shunt) | ≈ 1 % gain error | gain calibration |
| FET and diode leakage at ~40 mV | pA – nA | zero calibration; choose low-leakage parts |
| PCB surface leakage, flux residue | can reach nA | clean the board; keep guard space around R3 |
| C1 leakage | ceramic, small | part of the zero calibration |

## Calibration procedure

1. **Zero:** in range L, disconnect the DUT and average for about 10 s. The result is the offset current for range L. Repeat for ranges M and H.
2. **Gain:** for each range, connect a precision resistor as the load and compare against a good multimeter in series. Two points per range are enough: for example about 10 % and 80 % of full scale.
3. **Store:** keep the effective shunt resistance and the offset for each range in the logger's flash.

## Firmware strategy (logger)

- Run the INA228 in continuous shunt-only mode.
  - Ranges M and H: a short conversion time (50–280 µs) to follow activity.
  - Range L: a longer conversion time with averaging for low noise.
- Read the raw VSHUNT register and compute current in the logger using the per-range calibration. Do **not** rely on the INA228 CHARGE/ENERGY accumulators: SHUNT_CAL changes with every range switch, which makes them meaningless.
- **Up-range** on the ALERT interrupt, or when the reading exceeds about 85 % of full scale.
- **Down-range** when the reading stays below about 5 % of full scale for several conversions.
- **Log format:** `timestamp_us, range, vshunt_raw, current_A`.
- **Optional:** connect a GPIO from the DUT to the logger and toggle it on every state change. This lets you split the consumption by state (sleep, run, radio and so on).

## Measuring an STM32

- Insert the meter in place of the board's IDD jumper. Check your board's user manual for its location.
- During deep-sleep measurements, disconnect the debugger and any UART/SWD lines, because they back-feed current through the I/O pins.
