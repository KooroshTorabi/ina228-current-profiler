# Generates the KiCad 7 schematic, symbol library and BOM for this project.
# Usage: python3 tools/gen_schematic.py [integrated|module|smart]
#   integrated: INA228 on board (hardware/)
#   module:     shunt/range-switch adapter for an off-the-shelf INA228 breakout (hardware-module/)
#   smart:      INA228 + on-board STM32G030 that does the ranging; host reads one number (hardware-smart/)
import uuid, os, json, sys

VARIANT = sys.argv[1] if len(sys.argv) > 1 else "integrated"
assert VARIANT in ("integrated", "module", "smart")
PROJ = {"integrated": "current_meter", "module": "current_adapter", "smart": "current_smart"}[VARIANT]
HWDIR = {"integrated": "hardware", "module": "hardware-module", "smart": "hardware-smart"}[VARIANT]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", HWDIR, "kicad")
os.makedirs(OUT, exist_ok=True)
NS = uuid.UUID("6f1c2a54-9b0e-4d3c-8a8e-1c0de5ca1e01")
ROOT = str(uuid.uuid5(NS, "root"))
_ctr = [0]
def U():
    _ctr[0] += 1
    return str(uuid.uuid5(NS, f"item{_ctr[0]}"))
SYM_UUID = {}
F = lambda v: f"{v:.3f}".rstrip("0").rstrip(".")

# ---------- symbol library ----------
# pin: (number, name, x, y, angle, length, hidden)
SYMS = {}

def sym(name, ref, body, pins, show_names=False, ref_at=(2.54, 0, 0), val_at=(2.54, -2.54, 0)):
    SYMS[name] = dict(ref=ref, body=body, pins=pins, show_names=show_names, ref_at=ref_at, val_at=val_at)

st = '(stroke (width 0.254) (type default)) (fill (type none))'
stf = '(stroke (width 0.254) (type default)) (fill (type outline))'

sym("R", "R",
    [f'(rectangle (start -1.016 -2.54) (end 1.016 2.54) {st})'],
    [("1", "~", 0, 3.81, 270, 1.27, False), ("2", "~", 0, -3.81, 90, 1.27, False)])

sym("C", "C",
    [f'(polyline (pts (xy -2.032 0.762) (xy 2.032 0.762)) (stroke (width 0.508) (type default)) (fill (type none)))',
     f'(polyline (pts (xy -2.032 -0.762) (xy 2.032 -0.762)) (stroke (width 0.508) (type default)) (fill (type none)))'],
    [("1", "~", 0, 3.81, 270, 3.048, False), ("2", "~", 0, -3.81, 90, 3.048, False)])

# Diode: vertical, anode on top (current flows down VIN->DUT), pin1=K, pin2=A (KiCad convention)
sym("D", "D",
    [f'(polyline (pts (xy -1.27 1.27) (xy 1.27 1.27) (xy 0 -1.27) (xy -1.27 1.27)) {st})',
     f'(polyline (pts (xy -1.27 -1.27) (xy 1.27 -1.27)) {st})'],
    [("1", "K", 0, -3.81, 90, 2.54, False), ("2", "A", 0, 3.81, 270, 2.54, False)])

def fet_body(p):
    arrow = ('(polyline (pts (xy 0.254 0) (xy 1.27 0.508) (xy 1.27 -0.508) (xy 0.254 0)) ' + stf + ')') if p else \
            ('(polyline (pts (xy 1.27 0) (xy 0.254 0.508) (xy 0.254 -0.508) (xy 1.27 0)) ' + stf + ')')
    return [
        f'(polyline (pts (xy -1.27 2.032) (xy -1.27 -2.032)) {st})',
        f'(polyline (pts (xy -0.508 2.54) (xy -0.508 1.27)) {st})',
        f'(polyline (pts (xy -0.508 0.635) (xy -0.508 -0.635)) {st})',
        f'(polyline (pts (xy -0.508 -1.27) (xy -0.508 -2.54)) {st})',
        f'(polyline (pts (xy -0.508 1.905) (xy 2.54 1.905) (xy 2.54 2.54)) {st})',
        f'(polyline (pts (xy -0.508 -1.905) (xy 2.54 -1.905) (xy 2.54 -2.54)) {st})',
        f'(polyline (pts (xy -0.508 0) (xy 2.54 0) (xy 2.54 1.905)) {st})',
        arrow,
        f'(polyline (pts (xy -5.08 0) (xy -1.27 0)) {st})',
    ]

# P-FET: S on top, D on bottom
sym("PMOS_SOT23", "Q", fet_body(True),
    [("1", "G", -5.08, 0, 0, 0, False), ("2", "S", 2.54, 5.08, 270, 2.54, False), ("3", "D", 2.54, -5.08, 90, 2.54, False)],
    show_names=False, ref_at=(5.08, 1.27, 0), val_at=(5.08, -1.27, 0))
sym("PMOS_SO8", "Q", fet_body(True),
    [("1", "S", 2.54, 5.08, 270, 2.54, False), ("2", "S", 2.54, 5.08, 270, 2.54, True), ("3", "S", 2.54, 5.08, 270, 2.54, True),
     ("4", "G", -5.08, 0, 0, 0, False),
     ("5", "D", 2.54, -5.08, 90, 2.54, False), ("6", "D", 2.54, -5.08, 90, 2.54, True),
     ("7", "D", 2.54, -5.08, 90, 2.54, True), ("8", "D", 2.54, -5.08, 90, 2.54, True)],
    show_names=False, ref_at=(5.08, 1.27, 0), val_at=(5.08, -1.27, 0))
# N-FET: D on top, S on bottom
sym("NMOS_SOT23", "Q", fet_body(False),
    [("1", "G", -5.08, 0, 0, 0, False), ("3", "D", 2.54, 5.08, 270, 2.54, False), ("2", "S", 2.54, -5.08, 90, 2.54, False)],
    show_names=False, ref_at=(5.08, 1.27, 0), val_at=(5.08, -1.27, 0))

ina_pins = [("10", "IN+", -10.16, 7.62, 0, 2.54, False), ("9", "IN-", -10.16, 5.08, 0, 2.54, False),
            ("8", "VBUS", -10.16, 2.54, 0, 2.54, False)]
for i, (n, nm) in enumerate([("6", "VS"), ("7", "GND"), ("4", "SDA"), ("5", "SCL"), ("3", "ALERT"), ("2", "A0"), ("1", "A1")]):
    ina_pins.append((n, nm, 10.16, 7.62 - 2.54 * i, 180, 2.54, False))
sym("INA228", "U", [f'(rectangle (start -7.62 10.16) (end 7.62 -10.16) (stroke (width 0.254) (type default)) (fill (type background)))'],
    ina_pins, show_names=True, ref_at=(0, 11.43, 0), val_at=(0, -11.43, 0))

def conn(n):
    pins = [(str(i + 1), f"Pin_{i+1}", -5.08, -2.54 * i, 0, 3.81, False) for i in range(n)]
    body = [f'(rectangle (start -1.27 1.27) (end 1.27 {F(-2.54*(n-1)-1.27)}) {st})']
    sym(f"Conn_1x{n:02d}", "J", body, pins, ref_at=(0, 2.54, 0), val_at=(0, -2.54 * n, 0))
conn(2)
if VARIANT == "integrated":
    conn(7)
if VARIANT == "module":
    conn(3); conn(4)
if VARIANT == "smart":
    conn(5); conn(6)
    # STM32G030F6P6 (TSSOP-20): left pins top to bottom, right pins top to bottom
    lft = [("4", "VDD"), ("6", "NRST"), ("7", "PA0"), ("8", "PA1"), ("9", "PA2"), ("10", "PA3"),
           ("11", "PA4"), ("12", "PA5"), ("13", "PA6"), ("14", "PA7")]
    rgt = [("1", "PB7"), ("20", "PB6"), ("17", "PA12"), ("16", "PA11"), ("18", "PA13"), ("19", "PA14"),
           ("2", "PB9"), ("3", "PC15"), ("15", "PB0"), ("5", "VSS")]
    mp = [(n, nm, -12.7, 11.43 - 2.54 * i, 0, 2.54, False) for i, (n, nm) in enumerate(lft)] + \
         [(n, nm, 12.7, 11.43 - 2.54 * i, 180, 2.54, False) for i, (n, nm) in enumerate(rgt)]
    sym("STM32G030F6", "U", [f'(rectangle (start -10.16 13.97) (end 10.16 -13.97) (stroke (width 0.254) (type default)) (fill (type background)))'],
        mp, show_names=True, ref_at=(0, 15.24, 0), val_at=(0, -15.24, 0))
    # comparator: IN+ IN- on the left, OUT on the right, V+ top, GND bottom
    sym("TLV7021", "U", [f'(polyline (pts (xy -5.08 5.08) (xy 5.08 0) (xy -5.08 -5.08) (xy -5.08 5.08)) (stroke (width 0.254) (type default)) (fill (type background)))'],
        [("3", "+", -7.62, 2.54, 0, 2.54, False), ("4", "-", -7.62, -2.54, 0, 2.54, False),
         ("1", "~", 7.62, 0, 180, 2.54, False), ("5", "~", 0, 7.62, 270, 5.08, False), ("2", "~", 0, -7.62, 90, 5.08, False)],
        show_names=True, ref_at=(2.54, 6.35, 0), val_at=(2.54, -6.35, 0))
    # NPN: C top, E bottom, B left (SOT-23: 1=B 2=E 3=C)
    sym("NPN_SOT23", "Q", [
        f'(polyline (pts (xy -1.27 2.032) (xy -1.27 -2.032)) {st})',
        f'(polyline (pts (xy -1.27 0.762) (xy 2.54 2.54)) {st})',
        f'(polyline (pts (xy -1.27 -0.762) (xy 2.54 -2.54)) {st})',
        f'(polyline (pts (xy 1.27 -1.524) (xy 2.54 -2.54) (xy 1.016 -2.286) (xy 1.27 -1.524)) {stf})',
        f'(polyline (pts (xy -5.08 0) (xy -1.27 0)) {st})'],
        [("1", "B", -5.08, 0, 0, 0, False), ("3", "C", 2.54, 5.08, 270, 2.54, False), ("2", "E", 2.54, -5.08, 90, 2.54, False)],
        show_names=False, ref_at=(5.08, 1.27, 0), val_at=(5.08, -1.27, 0))
    # LED: anode on top, pin1 = K, pin2 = A
    sym("LED", "D",
        [f'(polyline (pts (xy -1.27 1.27) (xy 1.27 1.27) (xy 0 -1.27) (xy -1.27 1.27)) {st})',
         f'(polyline (pts (xy -1.27 -1.27) (xy 1.27 -1.27)) {st})',
         f'(polyline (pts (xy 1.778 0.508) (xy 3.048 -0.762)) {st})',
         f'(polyline (pts (xy 1.778 -0.254) (xy 3.048 -1.524)) {st})'],
        [("1", "K", 0, -3.81, 90, 2.54, False), ("2", "A", 0, 3.81, 270, 2.54, False)])
sym("MountingHole", "H", [f'(circle (center 0 0) (radius 1.27) {st})'], [], ref_at=(2.54, 0.635, 0), val_at=(2.54, -1.27, 0))

def sym_sexpr(name, prefix):
    s = SYMS[name]
    full = f"{prefix}{name}"
    o = [f'(symbol "{full}"']
    if not s["show_names"]:
        o.append('(pin_names (offset 0) hide)')
    else:
        o.append('(pin_names (offset 1.016))')
    o.append('(in_bom yes) (on_board yes)')
    rx, ry, ra = s["ref_at"]; vx, vy, va = s["val_at"]
    o.append(f'(property "Reference" "{s["ref"]}" (id 0) (at {F(rx)} {F(ry)} {ra}) (effects (font (size 1.27 1.27)) (justify left)))')
    o.append(f'(property "Value" "{name}" (id 1) (at {F(vx)} {F(vy)} {va}) (effects (font (size 1.27 1.27)) (justify left)))')
    for p in ["Footprint", "Datasheet", "Description"]:
        o.append(f'(property "{p}" "" (id {2+["Footprint","Datasheet","Description"].index(p)}) (at 0 0 0) (effects (font (size 1.27 1.27)) hide))')
    o.append(f'(symbol "{name}_0_1" ' + " ".join(s["body"]) + ')')
    pins = []
    for (n, nm, x, y, a, l, hid) in s["pins"]:
        pins.append(f'(pin passive line (at {F(x)} {F(y)} {a}) (length {F(l)}){" hide" if hid else ""} '
                    f'(name "{nm}" (effects (font (size 1.27 1.27)))) (number "{n}" (effects (font (size 1.27 1.27)))))')
    o.append(f'(symbol "{name}_1_1" ' + " ".join(pins) + ')')
    o.append(')')
    return " ".join(o)

# ---------- parts ----------
# (ref, sym, value, footprint, x, y, {pin: net}, description)
P = []
def part(ref, s, val, fp, x, y, nets, desc=""):
    P.append(dict(ref=ref, sym=s, val=val, fp=fp, x=x, y=y, nets=nets, desc=desc))

FP_R2512 = "Resistor_SMD:R_2512_6332Metric"
FP_R1206 = "Resistor_SMD:R_1206_3216Metric"
FP_R0805 = "Resistor_SMD:R_0805_2012Metric"
FP_R0603 = "Resistor_SMD:R_0603_1608Metric"
FP_SOT23 = "Package_TO_SOT_SMD:SOT-23"
TB = "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal"

# shunt chain
part("J1", "Conn_1x02", "VIN_IN", TB, 22.86, 40.64,
     {"1": "VIN", "2": "GND"}, "Supply input (bench PSU / 3.3V)")
part("R1", "R", "50m 1% 1W", FP_R2512, 63.5, 45.72, {"1": "VIN", "2": "NODE_A"}, "R_H shunt, high range, 4-wire layout")
part("R2", "R", "1R 0.1%", FP_R1206, 63.5, 76.2, {"1": "NODE_A", "2": "NODE_B"}, "R_M shunt, mid range")
part("R3", "R", "1k 0.1% 25ppm", FP_R0805, 63.5, 106.68, {"1": "NODE_B", "2": "DUT_VDD"}, "R_L shunt, low (nA/uA) range")
part("D1", "D", "BAS416", "Diode_SMD:D_SOD-323", 40.64, 76.2, {"2": "NODE_A", "1": "NODE_B"}, "D_M low-leakage clamp across R2")
part("D2", "D", "BAS416", "Diode_SMD:D_SOD-323", 40.64, 106.68, {"2": "NODE_B", "1": "DUT_VDD"}, "D_L low-leakage clamp across R3")
part("Q1", "PMOS_SO8", "DMP2008USS", "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm", 91.44, 63.5,
     {"1": "NODE_A", "2": "NODE_A", "3": "NODE_A", "4": "GH", "5": "DUT_VDD", "6": "DUT_VDD", "7": "DUT_VDD", "8": "DUT_VDD"},
     "Q_H: bypasses R2+R3 (high range)")
part("Q2", "PMOS_SOT23", "DMP2035U-7", FP_SOT23, 91.44, 101.6, {"1": "GM", "2": "NODE_B", "3": "DUT_VDD"},
     "Q_M: bypasses R3 (mid range)")
part("C1", "C", "22u X5R 25V", "Capacitor_SMD:C_1206_3216Metric", 116.84, 127.0, {"1": "DUT_VDD", "2": "GND"},
     "C_out, supplies DUT wake-up transient")
part("J2", "Conn_1x02", "DUT_OUT", TB, 142.24, 124.46,
     {"1": "DUT_VDD", "2": "GND"}, "To STM32 IDD jumper / VDD")

# gate drive (P-FET gate pull-ups go to VIN, upstream of all shunts!)
part("R4", "R", "100k", FP_R0603, 129.54, 43.18, {"1": "VIN", "2": "GH"}, "Q1 gate pull-up to VIN")
part("Q3", "NMOS_SOT23", "2N7002", FP_SOT23, 127.0, 63.5, {"1": "CTL_H", "3": "GH", "2": "GND"}, "Q1 gate driver")
part("R5", "R", "100k", FP_R0603, 129.54, 88.9, {"1": "VIN", "2": "GM"}, "Q2 gate pull-up to VIN")
part("Q4", "NMOS_SOT23", "2N7002", FP_SOT23, 127.0, 109.22, {"1": "CTL_M", "3": "GM", "2": "GND"}, "Q2 gate driver")
part("R6", "R", "100k", FP_R0603, 152.4, 50.8, {"1": "+3V3", "2": "CTL_H"}, "Default: high range ON at reset")
part("R7", "R", "100k", FP_R0603, 152.4, 96.52, {"1": "+3V3", "2": "CTL_M"}, "Default: mid bypass ON at reset")

if VARIANT == "integrated":
    # INA228
    part("U1", "INA228", "INA228AIDGSR", "Package_SO:VSSOP-10_3x3mm_P0.5mm", 205.74, 60.96,
         {"10": "VIN", "9": "DUT_VDD", "8": "DUT_VDD", "6": "+3V3", "7": "GND", "4": "SDA", "5": "SCL",
          "3": "ALERT", "2": "GND", "1": "GND"}, "I2C addr 0x40 (A0=A1=GND)")
    part("C2", "C", "100n", "Capacitor_SMD:C_0603_1608Metric", 238.76, 45.72, {"1": "+3V3", "2": "GND"}, "U1 VS decoupling")
    part("R8", "R", "10k", FP_R0603, 254.0, 45.72, {"1": "+3V3", "2": "ALERT"}, "ALERT open-drain pull-up")
    part("R9", "R", "4.7k", FP_R0603, 266.7, 45.72, {"1": "+3V3", "2": "SDA"}, "I2C pull-up (omit if on logger)")
    part("R10", "R", "4.7k", FP_R0603, 279.4, 45.72, {"1": "+3V3", "2": "SCL"}, "I2C pull-up (omit if on logger)")
    part("J3", "Conn_1x07", "LOGGER", "Connector_PinHeader_2.54mm:PinHeader_1x07_P2.54mm_Vertical", 254.0, 96.52,
         {"1": "+3V3", "2": "GND", "3": "SDA", "4": "SCL", "5": "ALERT", "6": "CTL_H", "7": "CTL_M"},
         "To logger MCU: 3V3 GND SDA SCL ALERT CTL_H CTL_M")

elif VARIANT == "smart":
    # INA228 on a private I2C bus owned by the on-board MCU
    part("U1", "INA228", "INA228AIDGSR", "Package_SO:VSSOP-10_3x3mm_P0.5mm", 205.74, 60.96,
         {"10": "VIN", "9": "DUT_VDD", "8": "DUT_VDD", "6": "+3V3", "7": "GND", "4": "SDA", "5": "SCL",
          "3": "ALERT", "2": "GND", "1": "GND"}, "I2C addr 0x40 on the MCU's private bus")
    part("C2", "C", "100n", "Capacitor_SMD:C_0603_1608Metric", 238.76, 45.72, {"1": "+3V3", "2": "GND"}, "U1 VS decoupling")
    part("R8", "R", "10k", FP_R0603, 254.0, 45.72, {"1": "+3V3", "2": "ALERT"}, "ALERT open-drain pull-up")
    part("R9", "R", "4.7k", FP_R0603, 266.7, 45.72, {"1": "+3V3", "2": "SDA"}, "private I2C pull-up")
    part("R10", "R", "4.7k", FP_R0603, 279.4, 45.72, {"1": "+3V3", "2": "SCL"}, "private I2C pull-up")
    # fast up-range comparator: trips when VIN - DUT_VDD exceeds ~32 mV, in about 1 us
    part("U3", "TLV7021", "TLV7021DBVR", "Package_TO_SOT_SMD:SOT-23-5", 317.5, 60.96,
         {"3": "DUT_VDD", "4": "CMP_REF", "1": "CMP_OUT", "5": "VIN", "2": "GND"},
         "Open-drain comparator powered from VIN; OUT low = over threshold")
    part("C5", "C", "100n", "Capacitor_SMD:C_0603_1608Metric", 342.9, 50.8, {"1": "VIN", "2": "GND"}, "U3 decoupling (VIN side, not measured)")
    part("R11", "R", "1k", FP_R0603, 304.8, 40.64, {"1": "VIN", "2": "CMP_REF"}, "threshold: Vth = Isink x 1k = ~32 mV")
    part("Q5", "NPN_SOT23", "MMBT3904", FP_SOT23, 302.26, 83.82, {"1": "CMP_B", "3": "CMP_REF", "2": "CMP_E"}, "~32 uA current sink")
    part("R12", "R", "33k", FP_R0603, 304.8, 104.14, {"1": "CMP_E", "2": "GND"}, "sets Isink = (Vb - Vbe) / 33k")
    part("R13", "R", "100k", FP_R0603, 281.94, 66.04, {"1": "+3V3", "2": "CMP_B"}, "Vb = 1.65 V")
    part("R14", "R", "100k", FP_R0603, 281.94, 93.98, {"1": "CMP_B", "2": "GND"}, "Vb = 1.65 V")
    part("C6", "C", "100n", "Capacitor_SMD:C_0603_1608Metric", 269.24, 93.98, {"1": "CMP_B", "2": "GND"}, "Vb filter")
    part("R15", "R", "10k", FP_R0603, 353.06, 50.8, {"1": "+3V3", "2": "CMP_OUT"}, "comparator output pull-up (3.3 V logic)")
    # MCU
    part("U2", "STM32G030F6", "STM32G030F6P6", "Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm", 330.2, 127.0,
         {"4": "+3V3", "5": "GND", "6": "NRST", "7": "CMP_OUT", "8": "ALERT", "9": "TX", "10": "RX",
          "11": "CTL_H", "12": "CTL_M", "13": "LED", "14": "NC_PA7", "1": "SDA", "20": "SCL",
          "17": "HSDA", "16": "HSCL", "18": "SWDIO", "19": "SWCLK", "2": "NC_PB9", "3": "NC_PC15", "15": "NC_PB0"},
         "Auto-ranging controller: I2C1 = INA228, I2C2 = host (slave 0x48), USART2 = CSV stream")
    part("C3", "C", "100n", "Capacitor_SMD:C_0603_1608Metric", 297.18, 116.84, {"1": "+3V3", "2": "GND"}, "U2 decoupling")
    part("C4", "C", "4.7u", "Capacitor_SMD:C_0603_1608Metric", 287.02, 116.84, {"1": "+3V3", "2": "GND"}, "3V3 bulk")
    part("C7", "C", "100n", "Capacitor_SMD:C_0603_1608Metric", 297.18, 139.7, {"1": "NRST", "2": "GND"}, "NRST filter")
    part("R16", "R", "1k", FP_R0603, 365.76, 106.68, {"1": "LED", "2": "LED_A"}, "status LED resistor")
    part("D3", "LED", "LED red", "LED_SMD:LED_0603_1608Metric", 365.76, 132.08, {"2": "LED_A", "1": "GND"}, "status LED (blinks per range)")
    part("J3", "Conn_1x06", "HOST", "Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical", 386.08, 86.36,
         {"1": "+3V3", "2": "GND", "3": "HSDA", "4": "HSCL", "5": "TX", "6": "RX"},
         "To Raspberry Pi / PC: 3V3 GND SDA SCL TX RX (I2C slave 0x48, UART 921600 8N1)")
    part("J4", "Conn_1x05", "SWD", "Connector_PinHeader_2.54mm:PinHeader_1x05_P2.54mm_Vertical", 386.08, 127.0,
         {"1": "+3V3", "2": "SWDIO", "3": "SWCLK", "4": "NRST", "5": "GND"},
         "Programming: ST-Link (e.g. Nucleo CN4). Not assembled.")

else:
    # Off-the-shelf INA228 breakout (e.g. SparkFun SEN-31438 with SHUNT jumper opened,
    # or Adafruit 5832 with its 15 mOhm shunt removed) senses this board via J4.
    part("J4", "Conn_1x03", "SENSE", "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", 205.74, 60.96,
         {"1": "VIN", "2": "DUT_VDD", "3": "GND"},
         "Kelvin sense out: 1 = S+ to module IN+, 2 = S- to module IN- and VBUS, 3 = GND")
    part("J3", "Conn_1x04", "LOGGER", "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical", 254.0, 96.52,
         {"1": "+3V3", "2": "GND", "3": "CTL_H", "4": "CTL_M"},
         "To logger MCU: 3V3 GND CTL_H CTL_M")

for i, (hx, hy) in enumerate([(205.74, 116.84), (218.44, 116.84), (231.14, 116.84), (243.84, 116.84)]):
    part(f"H{i+1}", "MountingHole", "M3", "MountingHole:MountingHole_3.2mm_M3", hx, hy, {}, "M3 mounting hole")

# ---------- schematic emit ----------
STUB = 2.54
items = []
seen_pts = set()
def pin_abs(p, pin):
    return (p["x"] + pin[2], p["y"] - pin[3])

for p in P:
    s = SYMS[p["sym"]]
    pinlist = s["pins"]
    nums = [q[0] for q in pinlist]
    assert set(p["nets"]) == set(nums), (p["ref"], set(nums) ^ set(p["nets"]))
    rx, ry, _ = s["ref_at"]; vx, vy, _ = s["val_at"]
    props = [
        f'(property "Reference" "{p["ref"]}" (id 0) (at {F(p["x"]+rx)} {F(p["y"]-ry)} 0) (effects (font (size 1.27 1.27)) (justify left)))',
        f'(property "Value" "{p["val"]}" (id 1) (at {F(p["x"]+vx)} {F(p["y"]-vy)} 0) (effects (font (size 1.27 1.27)) (justify left)))',
        f'(property "Footprint" "{p["fp"]}" (id 2) (at {F(p["x"])} {F(p["y"])} 0) (effects (font (size 1.27 1.27)) hide))',
        f'(property "Datasheet" "" (id 3) (at {F(p["x"])} {F(p["y"])} 0) (effects (font (size 1.27 1.27)) hide))',
        f'(property "Description" "{p["desc"]}" (id 4) (at {F(p["x"])} {F(p["y"])} 0) (effects (font (size 1.27 1.27)) hide))',
    ]
    pins_s = " ".join(f'(pin "{n}" (uuid "{U()}"))' for n in nums)
    SYM_UUID[p["ref"]] = su = str(uuid.uuid5(NS, "sym:" + p["ref"]))
    items.append(f'(symbol (lib_id "meter:{p["sym"]}") (at {F(p["x"])} {F(p["y"])} 0) (unit 1) '
                 f'(in_bom {"no" if p["sym"]=="MountingHole" else "yes"}) (on_board yes) (dnp no) (uuid "{su}") '
                 + " ".join(props) + " " + pins_s +
                 f' (instances (project "{PROJ}" (path "/{ROOT}" (reference "{p["ref"]}") (unit 1)))))')
    for pin in pinlist:
        x, y = pin_abs(p, pin)
        key = (p["ref"], round(x, 3), round(y, 3))
        if key in seen_pts:
            continue
        seen_pts.add(key)
        a = pin[4]
        # direction outward from body
        dx, dy, la, just = {0: (-STUB, 0, 180, "right bottom"), 180: (STUB, 0, 0, "left bottom"),
                            270: (0, -STUB, 90, "left bottom"), 90: (0, STUB, 270, "right bottom")}[a]
        ex, ey = x + dx, y + dy
        items.append(f'(wire (pts (xy {F(x)} {F(y)}) (xy {F(ex)} {F(ey)})) (stroke (width 0) (type default)) (uuid "{U()}"))')
        net = p["nets"][pin[0]]
        items.append(f'(label "{net}" (at {F(ex)} {F(ey)} {la}) (fields_autoplaced) '
                     f'(effects (font (size 1.27 1.27)) (justify {just})) (uuid "{U()}"))')

notes_integrated = [
    (20.32, 154.94, "INA228 auto-ranging current meter  |  ranges: L = R1+R2+R3 (~1001 ohm, both FETs off),"),
    (20.32, 160.02, "M = R1+R2+Rds(Q2) (Q2 on), H = R1+Rds(Q1) (Q1 on).  Logger: CTL_x HIGH = bypass FET ON. Defaults ON at reset."),
    (20.32, 165.1, "Route U1 IN+ / IN- as Kelvin traces: IN+ from J1 side of R1, IN- from the J2 side of R3. Keep R3/D1/D2/Q1/Q2 area clean (leakage!)."),
    (20.32, 170.18, "R4/R5 must go to VIN (upstream of IN+), NOT to the FET source, otherwise their current is measured. VIN max ~6V (FET Vgs)."),
    (20.32, 175.26, "Calibrate each range with a known load; zero-calibrate range L with DUT disconnected (INA bias current, FET/diode leakage)."),
]
notes_module = [
    (20.32, 154.94, "Shunt / range-switch adapter for an off-the-shelf INA228 breakout. Ranges: L = R1+R2+R3, M = R1+R2+Rds(Q2), H = R1+Rds(Q1)."),
    (20.32, 160.02, "J4 is a Kelvin sense output: S+ from the R1 pad, S- from the DUT terminal. No load current flows through the module."),
    (20.32, 165.1, "Module prep: SparkFun SEN-31438 -> open the SHUNT jumper. Adafruit 5832 -> remove the 15 mOhm shunt. Tie module VBUS to S-."),
    (20.32, 170.18, "R4/R5 go to VIN upstream of the S+ tap. Logger: CTL_x HIGH = bypass FET ON (default at reset). VIN max ~6V (FET Vgs)."),
    (20.32, 175.26, "Keep sense wires short and twisted. Calibrate each range with a known load; zero-calibrate range L with the DUT disconnected."),
]
notes_smart = [
    (20.32, 154.94, "Smart variant: the on-board STM32G030 switches the ranges and the host reads one number (I2C slave 0x48 or CSV over UART)."),
    (20.32, 160.02, "Ranges as in rev A: L = R1+R2+R3, M = R1+R2+Rds(Q2), H = R1+Rds(Q1). CTL_x HIGH = bypass FET ON (default at reset)."),
    (20.32, 165.1, "U3 trips in ~1 us when VIN - DUT_VDD > Vth (~32 mV = 1k x ~32 uA from Q5) and the MCU steps up one range at once."),
    (20.32, 170.18, "U3 IN+ sits on DUT_VDD: keep it a short, clean trace (5 pA input). R11/Q5/U3 are fed from VIN, upstream of the shunts."),
    (20.32, 175.26, "VIN 1.8 V to 5.5 V (U3 supply and FET Vgs). 3V3 for INA228 + MCU comes from the host header J3. Program U2 over SWD (J4)."),
]
notes = {"integrated": notes_integrated, "module": notes_module, "smart": notes_smart}[VARIANT]
for (x, y, t) in notes:
    items.append(f'(text "{t}" (at {F(x)} {F(y)} 0) (effects (font (size 1.27 1.27)) (justify left bottom)) (uuid "{U()}"))')

if VARIANT == "integrated":
    TITLE = "INA228 auto-ranging current meter (nA - 2.5A)"
    COMMENT = "High-side, 3 shunts + P-FET range switching, logger MCU over I2C"
elif VARIANT == "smart":
    TITLE = "INA228 smart current profiler (nA - 2.5A), rev C"
    COMMENT = "On-board STM32G030 auto-ranging + comparator fast up-range; one value out over I2C / UART"
else:
    TITLE = "Shunt + range-switch adapter for INA228 module (nA - 2.5A)"
    COMMENT = "High-side, 3 shunts + P-FET range switching, Kelvin sense to external INA228 breakout"
libsyms = " ".join(sym_sexpr(n, "meter:") for n in SYMS)
sch = (f'(kicad_sch (version 20230121) (generator eeschema) (uuid "{ROOT}") (paper "{"A3" if VARIANT == "smart" else "A4"}") '
       f'(title_block (title "{TITLE}") (date "2026-11-24") (rev "A") '
       f'(comment 1 "{COMMENT}")) '
       f'(lib_symbols {libsyms}) ' + " ".join(items) +
       f' (sheet_instances (path "/" (page "1"))))')
open(f"{OUT}/{PROJ}.kicad_sch", "w").write(sch)

lib = '(kicad_symbol_lib (version 20220914) (generator kicad_symbol_editor) ' + \
      " ".join(sym_sexpr(n, "") for n in SYMS) + ')'
open(f"{OUT}/meter.kicad_sym", "w").write(lib)
open(f"{OUT}/sym-lib-table", "w").write(
    '(sym_lib_table\n  (version 7)\n  (lib (name "meter")(type "KiCad")(uri "${KIPRJMOD}/meter.kicad_sym")(options "")(descr "Current meter project symbols"))\n)\n')
open(f"{OUT}/{PROJ}.kicad_pro", "w").write(json.dumps({
    "meta": {"filename": f"{PROJ}.kicad_pro", "version": 1},
    "sheets": [[ROOT, "Root"]]}, indent=2))

# BOM
import csv
with open(os.path.join(OUT, "..", "BOM.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Ref", "Value", "Footprint", "Note"])
    for p in P:
        w.writerow([p["ref"], p["val"], p["fp"], p["desc"]])

# intended netlist for checking
json.dump({p["ref"]: dict(nets=p["nets"], fp=p["fp"], val=p["val"], uuid=SYM_UUID[p["ref"]]) for p in P}, open(os.path.join(OUT, "..", "parts.json"), "w"), indent=1)
json.dump({p["ref"]: p["nets"] for p in P}, open(os.path.join(OUT, "..", "intended_nets.json"), "w"))
print("written", len(P), "parts")
