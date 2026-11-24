# Generates the PCB (placement + hand-routed measurement-critical nets).
# Remaining low-current nets are routed with Freerouting (see tools/route.sh).
# Usage: /usr/bin/python3 tools/gen_pcb.py <out.kicad_pcb> [integrated|module]
import json, os, sys
import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
VARIANT = sys.argv[2] if len(sys.argv) > 2 else "integrated"
HW = os.path.join(HERE, "..", "hardware" if VARIANT == "integrated" else "hardware-module")
FPLIB = os.environ.get("KICAD_FP", "/usr/share/kicad/footprints")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HW, "kicad", "current_meter.kicad_pcb")

parts = json.load(open(os.path.join(HW, "parts.json")))
mm = pcbnew.FromMM
V = lambda x, y: pcbnew.VECTOR2I(mm(x), mm(y))

board = pcbnew.BOARD()
ds = board.GetDesignSettings()
ds.SetCopperLayerCount(2)
nc = ds.m_NetSettings.m_DefaultNetClass
nc.SetClearance(mm(0.2)); nc.SetTrackWidth(mm(0.25)); nc.SetViaDiameter(mm(0.6)); nc.SetViaDrill(mm(0.3))
ds.m_TrackMinWidth = mm(0.2); ds.m_MinClearance = mm(0.2)

nets = {}
def net(name):
    if name not in nets:
        n = pcbnew.NETINFO_ITEM(board, name); board.Add(n); nets[name] = n
    return nets[name]
for r, p in parts.items():
    for n in p["nets"].values():
        net(n)

DY = 3.0
# ref: (x, y, rotation_deg)
PLACE = {
    "J1": (106, 110, 270), "R1": (118.5, 110, 0), "Q1": (130, 111.27, 0), "J2": (156, 111.27, 90),
    "R2": (126, 119, 0), "D1": (126, 122.5, 180), "R3": (133, 119, 0), "D2": (133, 122.5, 180),
    "Q2": (138.5, 117, 0), "C1": (144, 119, 90),
    "R4": (109.6, 124, 270), "R5": (112.6, 124, 270),
    "Q3": (110, 132, 0), "Q4": (118, 132, 0), "R6": (106, 136, 270), "R7": (114, 136, 270),
    "U1": (148, 130, 0), "C2": (153.5, 133.5, 90), "R8": (139.4, 134.5, 270), "R9": (142.4, 134.5, 270),
    "R10": (145.4, 134.5, 270), "J3": (121, 143, 90),
    "H1": (103.6, 103.6 - DY, 0), "H2": (140, 103.6 - DY, 0), "H3": (158.4, 145.4 - DY, 0), "H4": (103.6, 145.4 - DY, 0),
}
if VARIANT == "module":
    for r in ("U1", "C2", "R8", "R9", "R10"):
        del PLACE[r]
    PLACE["J3"] = (113, 143, 90)
    PLACE["J4"] = (140, 132, 90)
FP = {}
for ref, (x, y, rot) in PLACE.items():
    p = parts[ref]
    lib, name = p["fp"].split(":")
    fp = pcbnew.FootprintLoad(os.path.join(FPLIB, lib + ".pretty"), name)
    fp.SetFPID(pcbnew.LIB_ID(lib, name))
    fp.SetReference(ref); fp.SetValue(p["val"])
    fp.SetPath(pcbnew.KIID_PATH("/" + p["uuid"]))
    board.Add(fp)
    fp.SetOrientationDegrees(rot)
    fp.SetPosition(V(x, y + DY))
    for pad in fp.Pads():
        n = p["nets"].get(pad.GetNumber())
        if n:
            pad.SetNet(net(n))
    FP[ref] = fp

def pad(ref, num):
    for pd in FP[ref].Pads():
        if pd.GetNumber() == num:
            pp = pd.GetPosition(); return (pcbnew.ToMM(pp.x), pcbnew.ToMM(pp.y))
    raise KeyError((ref, num))

SEGS = []  # [a, b, width, net, layer]
def track(pts, w, netname, layer=pcbnew.F_Cu):
    for (a, b) in zip(pts, pts[1:]):
        SEGS.append([tuple(round(v, 4) for v in a), tuple(round(v, 4) for v in b), w, netname, layer])

def emit_tracks():
    # Split segments wherever another segment of the same net ends on their interior,
    # so every T-junction is a shared vertex (needed for Specctra/Freerouting connectivity).
    def on_interior(p, a, b):
        (x, y), (x1, y1), (x2, y2) = p, a, b
        cross = (x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)
        if abs(cross) > 1e-6:
            return False
        dot = (x - x1) * (x2 - x1) + (y - y1) * (y2 - y1)
        L2 = (x2 - x1) ** 2 + (y2 - y1) ** 2
        return 1e-6 < dot < L2 - 1e-6
    changed = True
    while changed:
        changed = False
        ends = [(s[0], s[3], s[4]) for s in SEGS] + [(s[1], s[3], s[4]) for s in SEGS]
        for i, sg in enumerate(SEGS):
            for (p, n, ly) in ends:
                if n == sg[3] and ly == sg[4] and on_interior(p, sg[0], sg[1]):
                    SEGS[i] = [sg[0], p, sg[2], sg[3], sg[4]]
                    SEGS.append([p, sg[1], sg[2], sg[3], sg[4]])
                    changed = True
                    break
            if changed:
                break
    for a, b, w, n, ly in SEGS:
        if a == b:
            continue
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(V(*a)); t.SetEnd(V(*b)); t.SetWidth(mm(w)); t.SetLayer(ly)
        t.SetNet(net(n)); t.SetLocked(True); board.Add(t)

Y = lambda y: y + DY
# ---- board outline ----
W, H = 62, 49
rect = pcbnew.PCB_SHAPE(board); rect.SetShape(pcbnew.SHAPE_T_RECT)
rect.SetStart(V(100, 100)); rect.SetEnd(V(100 + W, 100 + H)); rect.SetLayer(pcbnew.Edge_Cuts); rect.SetWidth(mm(0.1))
board.Add(rect)
# keep router tracks/vias away from the board edge (Freerouting ignores KiCad's edge clearance)
KO = 0.7
for (x0, y0, x1, y1) in [(100, 100, 100 + W, 100 + KO), (100, 100 + H - KO, 100 + W, 100 + H),
                         (100, 100, 100 + KO, 100 + H), (100 + W - KO, 100, 100 + W, 100 + H)]:
    ko = pcbnew.ZONE(board)
    ko.SetIsRuleArea(True); ko.SetDoNotAllowTracks(True); ko.SetDoNotAllowVias(True)
    ko.SetDoNotAllowCopperPour(False); ko.SetDoNotAllowPads(False); ko.SetDoNotAllowFootprints(False)
    ls = pcbnew.LSET(); ls.AddLayer(pcbnew.F_Cu); ls.AddLayer(pcbnew.B_Cu); ko.SetLayerSet(ls)
    o = ko.Outline(); o.NewOutline()
    for (x, y) in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]:
        o.Append(mm(x), mm(y))
    board.Add(ko)

# ---- VIN: J1 -> R1 (2 mm), pull-ups R4/R5 tapped upstream of R1, Kelvin IN+ from R1 pad 1 ----
j11 = pad("J1", "1"); r11 = pad("R1", "1")
track([j11, r11], 2.0, "VIN")
r41 = pad("R4", "1")
track([(r41[0], j11[1]), r41], 0.3, "VIN")
track([pad("R4", "1"), pad("R5", "1")], 0.3, "VIN")
# Kelvin IN+: leaves R1 pad1 on its inner edge, runs along y=127 to U1 pin 10
kx = r11[0]
if VARIANT == "integrated":
    u10 = pad("U1", "10"); u9 = pad("U1", "9"); u8 = pad("U1", "8")
    track([(kx, r11[1]), (kx, Y(127)), (152.5, Y(127)), (152.5, u10[1]), u10], 0.2, "VIN")
else:
    s_plus = pad("J4", "1"); s_minus = pad("J4", "2")
    track([(kx, r11[1]), (kx, Y(127)), (s_plus[0], Y(127)), s_plus], 0.3, "VIN")

# ---- NODE_A: R1 pad2 -> Q1 sources (2 mm trunk), and to R2 / D1 (0.4 mm) ----
r12 = pad("R1", "2"); s_pads = [pad("Q1", n) for n in "123"]
tx = 125.8
track([r12, (tx, r12[1])], 2.0, "NODE_A")
track([(tx, s_pads[0][1]), (tx, s_pads[2][1])], 1.0, "NODE_A")
for sp in s_pads:
    track([(tx, sp[1]), sp], 0.6, "NODE_A")
xa = 122.8
track([(xa, r12[1]), (xa, pad("R2", "1")[1]), pad("R2", "1")], 0.4, "NODE_A")
track([(xa, pad("R2", "1")[1]), (xa, pad("D1", "2")[1]), pad("D1", "2")], 0.4, "NODE_A")

# ---- DUT_VDD: Q1 drains -> J2 (2 mm), low-range bus at x=141, Kelvin IN- from J2 pad 1 ----
d_pads = [pad("Q1", n) for n in "5678"]
dx = 134.2
track([(dx, min(p[1] for p in d_pads)), (dx, max(p[1] for p in d_pads))], 1.0, "DUT_VDD")
for dp in d_pads:
    track([dp, (dx, dp[1])], 0.6, "DUT_VDD")
j21 = pad("J2", "1")
track([(dx, j21[1]), j21], 2.0, "DUT_VDD")
bx = 141
q2d = pad("Q2", "3"); r32 = pad("R3", "2"); d2k = pad("D2", "1"); c11 = pad("C1", "1")
track([(bx, j21[1]), (bx, d2k[1])], 0.5, "DUT_VDD")
track([q2d, (bx, q2d[1])], 0.4, "DUT_VDD")
track([r32, (135.5, r32[1]), (135.5, Y(120.5)), (bx, Y(120.5))], 0.4, "DUT_VDD")
track([(bx, Y(120.5)), c11], 0.4, "DUT_VDD")
track([d2k, (bx, d2k[1])], 0.4, "DUT_VDD")
# Kelvin IN- and VBUS from J2 pad 1
if VARIANT == "integrated":
    track([j21, (j21[0], u9[1]), u9], 0.2, "DUT_VDD")
    track([(151.5, u9[1]), (151.5, u8[1]), u8], 0.2, "DUT_VDD")
else:
    track([j21, (j21[0], Y(129)), (s_minus[0], Y(129)), s_minus], 0.3, "DUT_VDD")

# ---- NODE_B: R2 -> R3, D1 K, D2 A, Q2 source ----
r22 = pad("R2", "2"); r31 = pad("R3", "1"); d1k = pad("D1", "1"); d2a = pad("D2", "2"); q2s = pad("Q2", "2")
track([r22, r31], 0.4, "NODE_B")
track([d1k, d2a], 0.4, "NODE_B")
track([(129, d1k[1]), (129, r22[1])], 0.4, "NODE_B")
track([(130.5, r22[1]), (130.5, Y(116.5)), (136.0, Y(116.5)), (136.0, q2s[1]), q2s], 0.4, "NODE_B")

# ---- GM escape: Q2 gate sits inside the hand-routed area, give the router a via ----
def via(x, y, netname):
    v = pcbnew.PCB_VIA(board); v.SetPosition(V(round(x, 4), round(y, 4))); v.SetWidth(mm(0.6)); v.SetDrill(mm(0.3))
    v.SetNet(net(netname)); v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu); v.SetLocked(True); board.Add(v)
q2g = pad("Q2", "1")
track([q2g, (q2g[0], q2g[1] - 1.65)], 0.25, "GM")
via(q2g[0], q2g[1] - 1.65, "GM")

# ---- silkscreen labels ----
def silk(text, x, y, size=1.0, angle=0, layer=pcbnew.F_SilkS):
    t = pcbnew.PCB_TEXT(board); t.SetText(text); t.SetPosition(V(x, y)); t.SetLayer(layer)
    t.SetTextSize(V(size, size)); t.SetTextThickness(mm(0.15)); t.SetTextAngleDegrees(angle); board.Add(t)
j12 = pad("J1", "2"); j22 = pad("J2", "2")
silk("VIN", 113.2, j11[1], 0.8, 90); silk("GND", 113.2, j12[1], 0.8, 90)
silk("DUT", 149.0, j21[1], 0.8, 90); silk("GND", 149.0, j22[1], 0.8, 90)
if VARIANT == "integrated":
    silk("INA228 current profiler", 147, Y(140.3), 0.9)
    silk("nA - 2.5 A  rev A", 147, Y(141.8), 0.8)
    for i, s_ in enumerate(["3V3", "GND", "SDA", "SCL", "ALRT", "CTLH", "CTLM"]):
        silk(s_, 121 + 2.54 * i, Y(143) - 3.4, 0.8, 90)
else:
    silk("INA228 module adapter", 145, Y(140.3), 0.9)
    silk("nA - 2.5 A  rev A", 145, Y(141.8), 0.8)
    for i, s_ in enumerate(["3V3", "GND", "CTLH", "CTLM"]):
        silk(s_, 113 + 2.54 * i, Y(143) - 3.4, 0.8, 90)
    for i, s_ in enumerate(["S+", "S-", "GND"]):
        silk(s_, 140 + 2.54 * i, Y(132) + 3.0, 0.8)
    silk("to module IN+ / IN-,VBUS", 143, Y(132) + 4.8, 0.8)

emit_tracks()
board.Save(OUT)
print("saved", OUT)
