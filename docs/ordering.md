# Ordering variant A assembled from JLCPCB

Everything JLCPCB needs is in [`hardware/jlcpcb/`](../hardware/jlcpcb):

| File | Upload at |
|---|---|
| `gerbers.zip` | the first step (PCB) |
| `bom_jlcpcb.csv` | the assembly step, as the BOM |
| `cpl_jlcpcb.csv` | the assembly step, as the CPL (pick-and-place) |

Regenerate them with `python3 tools/jlcpcb.py` after any board change.

## PCB settings

| Setting | Value |
|---|---|
| Layers | 2 |
| Dimensions | 62 × 49 mm (detected from the Gerbers) |
| Thickness | 1.6 mm |
| Copper weight | 1 oz |
| Surface finish | HASL lead-free (fastest); ENIG also fine |

## Assembly settings

- Turn on **PCB Assembly**, top side only.
- **Standard** PCBA, because J1, J2 and J3 are through-hole parts.
- Upload the BOM and CPL above.

## Parts

| Ref | Part | LCSC |
|---|---|---|
| U1 | TI INA228AIDGSR | C2887910 |
| Q1 | Diodes DMP2008USS-13 | C6934873 |
| Q2 | Diodes DMP2035U-7 | C110499 |
| Q3, Q4 | 2N7002 (JLC Basic) | C8545 |
| D1, D2 | Nexperia BAS416Z | C549240 |
| R1 | 50 mΩ 1 % 2 W 2512 | C323779 |
| R2 | 1 Ω 0.1 % 25 ppm 1206 | C513714 |
| R3 | 1 kΩ 0.1 % 25 ppm 0805 | C856765 |
| R4–R7 | 100 kΩ 0603 (Basic) | C25803 |
| R8 | 10 kΩ 0603 (Basic) | C25804 |
| R9, R10 | 4.7 kΩ 0603 (Basic) | C23162 |
| C1 | 22 µF 25 V X5R 1206 (Basic) | C12891 |
| C2 | 100 nF 0603 (Basic) | C14663 |
| J1, J2 | KF128-5.08-2P screw terminal | C474952 |
| J3 | 1×7 2.54 mm pin header | C492406 |

Stock changes daily, so check the parts page after uploading the BOM. If a part shows as out of stock, use these replacements:

| Part | Replacement | Requirement |
|---|---|---|
| R1 | C160588 | any 50 mΩ 1 % 2512 |
| R3 | C844063 (Vishay TNPW, 0.1 %) | keep 0.1 % and ≤ 25 ppm |
| D1, D2 | C549239 (BAS416F) | keep a low-leakage diode, **never a Schottky** |
| Q1 | any P-FET in SO-8 with the same S-S-S-G / D-D-D-D pinout | Rds(on) ≤ 12 mΩ at Vgs = −2.5 V, Vgs max ≥ ±8 V |

## Check in JLCPCB's placement preview

The CPL uses KiCad's rotations. JLCPCB's library sometimes defines zero degrees differently, so open the preview and check the pin 1 / polarity marks on these parts before paying:

- **U1** (VSSOP-10): the pin 1 dot sits at the corner next to pin 1 (A1).
- **Q1** (SO-8): pins 1–3 (source) face R1; pins 5–8 (drain) face J2.
- **Q2, Q3, Q4** (SOT-23): the single pin (drain) points away from the two-pin side, as on the silkscreen.
- **D1, D2** (SOD-323): the cathode band is on the right-hand pad.
- **J1, J2**: the wire openings face the nearest board edge (outward).

If a part is rotated wrongly, fix it with the rotate buttons in the preview. You can also leave a note: JLCPCB's engineers check polarity before production and email you if something is unclear.
