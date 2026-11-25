# Writes JLCPCB assembly files (BOM + CPL) plus the Gerber zip into <hardware dir>/jlcpcb/.
# Usage: python3 tools/jlcpcb.py [integrated|smart|usb]  (needs kicad-cli; default integrated = variant A)
#
# LCSC numbers were picked from LCSC/JLCPCB listings in Nov 2026. Stock changes daily: JLCPCB's
# BOM step shows live stock and offers replacements for anything that has run out.
import csv, json, os, shutil, subprocess, sys, tempfile

VARIANT = sys.argv[1] if len(sys.argv) > 1 else "integrated"
assert VARIANT in ("integrated", "smart", "usb")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
HW = os.path.join(ROOT, {"integrated": "hardware", "smart": "hardware-smart", "usb": "hardware-usb"}[VARIANT])
PCB = os.path.join(HW, "kicad", {"integrated": "current_meter", "smart": "current_smart", "usb": "current_usb"}[VARIANT] + ".kicad_pcb")
OUT = os.path.join(HW, "jlcpcb")

# ref -> (LCSC part, manufacturer part, JLC footprint name)
LCSC = {
    "U1":  ("C2887910", "TI INA228AIDGSR", "VSSOP-10"),
    "Q1":  ("C92137",   "onsemi FDS4465 (DMP2008USS-13 alt.)", "SO-8"),
    "Q2":  ("C110499",  "Diodes DMP2035U-7", "SOT-23"),
    "Q3":  ("C8545",    "JSCJ 2N7002", "SOT-23"),
    "Q4":  ("C8545",    "JSCJ 2N7002", "SOT-23"),
    "D1":  ("C549240",  "Nexperia BAS416Z", "SOD-323"),
    "D2":  ("C549240",  "Nexperia BAS416Z", "SOD-323"),
    "R1":  ("C323779",  "FORT CUM2512-24FR050 50mΩ 1% 2W", "2512"),
    "R2":  ("C2912606", "YAGEO 1206 1Ω 0.1% thin film", "1206"),
    "R3":  ("C856765",  "YAGEO AT0805BRD071KL 1kΩ 0.1% 25ppm", "0805"),
    "R4":  ("C25803",   "100kΩ 1% 0603", "0603"),
    "R5":  ("C25803",   "100kΩ 1% 0603", "0603"),
    "R6":  ("C25803",   "100kΩ 1% 0603", "0603"),
    "R7":  ("C25803",   "100kΩ 1% 0603", "0603"),
    "R8":  ("C25804",   "10kΩ 1% 0603", "0603"),
    "R9":  ("C23162",   "4.7kΩ 1% 0603", "0603"),
    "R10": ("C23162",   "4.7kΩ 1% 0603", "0603"),
    "C1":  ("C12891",   "Samsung CL31A226KAHNNNE 22µF 25V X5R", "1206"),
    "C2":  ("C14663",   "YAGEO CC0603KRX7R9BB104 100nF 50V X7R", "0603"),
    "J1":  ("C474952",  "KEFA KF128-5.08-2P-AA screw terminal", "THT 5.08mm 2P"),
    "J2":  ("C474952",  "KEFA KF128-5.08-2P-AA screw terminal", "THT 5.08mm 2P"),
    "J3":  ("C492406",  "XFCN PZ254V-11-07P pin header", "THT 2.54mm 1x7"),
}
DNP = set()      # footprints on the board that JLC leaves empty
if VARIANT == "smart":
    LCSC.update({
        "J3":  ("C492405",  "XFCN PZ254V-11-06P pin header", "THT 2.54mm 1x6"),
        "U2":  ("C724040",  "ST STM32G030F6P6", "TSSOP-20"),
        "U3":  ("C2860939", "TI TLV7021DBVR comparator", "SOT-23-5"),
        "Q5":  ("C20526",   "MMBT3904", "SOT-23"),
        "R11": ("C21190",   "1kΩ 1% 0603", "0603"),
        "R12": ("C4216",    "33kΩ 1% 0603", "0603"),
        "R13": ("C25803",   "100kΩ 1% 0603", "0603"),
        "R14": ("C25803",   "100kΩ 1% 0603", "0603"),
        "R15": ("C25804",   "10kΩ 1% 0603", "0603"),
        "R16": ("C21190",   "1kΩ 1% 0603", "0603"),
        "C3":  ("C14663",   "YAGEO CC0603KRX7R9BB104 100nF 50V X7R", "0603"),
        "C4":  ("C19666",   "Samsung CL10A475KO8NNNC 4.7µF 16V X5R", "0603"),
        "C5":  ("C14663",   "YAGEO CC0603KRX7R9BB104 100nF 50V X7R", "0603"),
        "C6":  ("C14663",   "YAGEO CC0603KRX7R9BB104 100nF 50V X7R", "0603"),
        "C7":  ("C14663",   "YAGEO CC0603KRX7R9BB104 100nF 50V X7R", "0603"),
        "D3":  ("C2286",    "KENTO KT-0603R red LED", "0603"),
    })
    DNP = {"J4"}  # SWD header: solder a 1x5 header (or use pogo pins) for programming

# JLC's 3D models use a different zero orientation than KiCad's footprints for these
# parts (checked against pin-1 dots in JLC's placement preview, Nov 2026). Degrees, CCW positive.
ROT_FIX = {"Q1": -90, "Q2": 180, "Q3": 180, "Q4": 180, "D1": 180, "D2": 180, "J3": -90}
# Variant C parts not yet seen in JLC's preview: same correction as the parts of the same package
# above (SOT-23, diodes). U2 (TSSOP-20) and U3 (SOT-23-5): check the pin-1 dot in the preview.
ROT_FIX.update({"Q5": 180, "D3": 180, "U3": 180})
# JLC places these at the body centre, KiCad's origin is pin 1: use the pad centroid instead.
CENTROID = {"J1", "J2", "J3"}

if VARIANT == "usb":
    C100N = ("C14663", "YAGEO CC0603KRX7R9BB104 100nF 50V X7R", "0603")
    LCSC = {
        "J1":  ("C5352764", "JAE DX07P024AJ1R1500 USB-C plug, straddle mount", "USB-C plug"),
        "J2":  ("C165948",  "HRO TYPE-C-31-M-12 USB-C receptacle", "USB-C-SMD_TYPE-C-31-M-12"),
        "J3":  ("C165948",  "HRO TYPE-C-31-M-12 USB-C receptacle", "USB-C-SMD_TYPE-C-31-M-12"),
        "R1":  ("C323772",  "FORT CUM2512-24FR010 10mΩ 1% 2W", "2512"),
        "D1":  ("C698968",  "YANGJIE SMBJ51A TVS 51V", "SMB"),
        "U1":  ("C2887910", "TI INA228AIDGSR", "VSSOP-10"),
        "U2":  ("C2847904", "ST STM32G0B1CBT6", "LQFP-48"),
        "U3":  ("C5446",    "TOREX XC6206P332MR-G 3.3V LDO", "SOT-23"),
        "U4":  ("C7519",    "ST USBLC6-2SC6", "SOT-23-6"),
        "C1": C100N, "C2": C100N, "C3": C100N, "C5": C100N, "C8": C100N, "C9": C100N, "C10": C100N, "C11": C100N,
        "C4":  ("C19666",   "Samsung CL10A475KO8NNNC 4.7µF 16V X5R", "0603"),
        "C6":  ("C19666",   "Samsung CL10A475KO8NNNC 4.7µF 16V X5R", "0603"),
        "R2":  ("C25804",   "10kΩ 1% 0603", "0603"),
        "R3":  ("C23162",   "4.7kΩ 1% 0603", "0603"),
        "R4":  ("C23162",   "4.7kΩ 1% 0603", "0603"),
        "R5":  ("C23186",   "5.1kΩ 1% 0603", "0603"),
        "R6":  ("C23186",   "5.1kΩ 1% 0603", "0603"),
        "R15": ("C21190",   "1kΩ 1% 0603", "0603"),
        "D2":  ("C2286",    "KENTO KT-0603R red LED", "0603"),
    }
    for r in range(7, 15):
        LCSC[f"R{r}"] = ("C22935", "1MΩ 1% 0603", "0603")
    DNP = {"J4"}       # optional SWD header; the chip is programmed over USB (DFU)
    # Same corrections as the same packages in variants A/C. Not yet seen in JLC's preview:
    # U2 (LQFP-48), U4 (SOT-23-6), J1, J2, J3. Check their pin-1 marks / orientation there.
    ROT_FIX = {"U3": 180, "D1": 180, "D2": 180}
    CENTROID = set()   # the USB-C footprints have their origin at the body already

parts = json.load(open(os.path.join(HW, "parts.json")))
placed = [r for r in parts if not r.startswith("H") and r not in DNP]
missing = sorted(set(placed) - set(LCSC))
assert not missing, f"no LCSC number for {missing}"

os.makedirs(OUT, exist_ok=True)

# BOM grouped by LCSC number
groups = {}
for ref in sorted(placed, key=lambda r: (r.rstrip("0123456789"), int("".join(c for c in r if c.isdigit())))):
    lc, comment, fp = LCSC[ref]
    groups.setdefault(lc, [comment, [], fp])[1].append(ref)
with open(os.path.join(OUT, "bom_jlcpcb.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
    for lc, (comment, refs, fp) in groups.items():
        w.writerow([comment, ",".join(refs), fp, lc])

def board_info(centroid):
    return json.loads(subprocess.check_output(["/usr/bin/python3", "-c", r'''
import pcbnew, json, sys
b = pcbnew.LoadBoard(sys.argv[1]); out = {}
for fp in b.GetFootprints():
    p = fp.GetPosition()
    if fp.GetReference() in sys.argv[2].split(","):
        pads = list(fp.Pads())
        p = pcbnew.VECTOR2I(sum(q.GetPosition().x for q in pads)//len(pads), sum(q.GetPosition().y for q in pads)//len(pads))
    out[fp.GetReference()] = (pcbnew.ToMM(p.x), -pcbnew.ToMM(p.y), fp.GetOrientationDegrees())
print(json.dumps(out))''', PCB, ",".join(centroid)]))

# CPL from KiCad's position file (all footprints, mm, top side)
tmp = tempfile.mkdtemp()
pos = os.path.join(tmp, "pos.csv")
subprocess.check_call(["kicad-cli", "pcb", "export", "pos", "--format", "csv", "--units", "mm",
                       "--side", "both", "-o", pos, PCB], stdout=subprocess.DEVNULL)
rows = list(csv.DictReader(open(pos)))
seen = set()
with open(os.path.join(OUT, "cpl_jlcpcb.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
    for r in rows:
        if r["Ref"] in LCSC and r["Ref"] not in CENTROID:
            w.writerow([r["Ref"], f'{float(r["PosX"]):.4f}mm', f'{float(r["PosY"]):.4f}mm',
                        "Top" if r["Side"].lower() == "top" else "Bottom", f'{(float(r["Rot"]) + ROT_FIX.get(r["Ref"], 0)) % 360:g}'])
            seen.add(r["Ref"])
# KiCad leaves through-hole parts out of the position file unless asked; add them from the board.
# Parts in CENTROID are always taken from the board, at their pad centroid.
left = sorted((set(LCSC) - seen) | CENTROID)
if left:
    info = board_info(CENTROID)
    with open(os.path.join(OUT, "cpl_jlcpcb.csv"), "a", newline="") as f:
        w = csv.writer(f)
        for ref in left:
            x, y, rot = info[ref]
            w.writerow([ref, f"{x:.4f}mm", f"{y:.4f}mm", "Top", f"{(rot + ROT_FIX.get(ref, 0)) % 360:g}"])
shutil.copy(os.path.join(HW, "fab", "gerbers.zip"), os.path.join(OUT, "gerbers.zip"))
print("wrote", OUT, "| BOM lines:", len(groups), "| placements:", len(LCSC))
