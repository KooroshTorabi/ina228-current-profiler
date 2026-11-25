# Rev D PCB: placement plus the hand-routed 5 A paths (VBUS_IN, VBUS_OUT) and the shunt Kelvin taps.
# Everything else is routed with Freerouting by tools/route.py (ROUTE_CRITICAL=VBUS_IN,VBUS_OUT).
# Usage: /usr/bin/python3 tools/gen_pcb_usb.py [out.kicad_pcb]
#
# Board: 56 x 32 mm plus the plug paddle on the left. J1 (USB-C plug, straddle mount) is the input,
# J2 (USB-C receptacle) on the right is the output, J3 on the bottom edge goes to the PC.
import json, os, sys
import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
HW = os.path.join(HERE, "..", "hardware-usb")
FPLIB = os.environ.get("KICAD_FP", "/usr/share/kicad/footprints")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HW, "kicad", "current_usb.kicad_pcb")
parts = json.load(open(os.path.join(HW, "parts.json")))
mm = pcbnew.FromMM
V = lambda x, y: pcbnew.VECTOR2I(mm(x), mm(y))

board = pcbnew.BOARD()
ds = board.GetDesignSettings()
ds.SetCopperLayerCount(2)
nc = ds.m_NetSettings.m_DefaultNetClass
nc.SetClearance(mm(0.15)); nc.SetTrackWidth(mm(0.2)); nc.SetViaDiameter(mm(0.6)); nc.SetViaDrill(mm(0.3))
ds.m_TrackMinWidth = mm(0.15); ds.m_MinClearance = mm(0.15); ds.m_CopperEdgeClearance = mm(0.2)   # the JAE paddle footprint puts its shell pads 0.24 mm from its own edge

nets = {}
def net(name):
    if name not in nets:
        n = pcbnew.NETINFO_ITEM(board, name); board.Add(n); nets[name] = n
    return nets[name]
for r, p in parts.items():
    for n in p["nets"].values():
        net(n)

X0, Y0, W, H = 100.0, 100.0, 56.0, 32.0
PX, PY = 98.07, 115.0          # plug origin: paddle tip on the left, main board starts at x = PX + 1.93 = 100
X2, Y2 = 153.0, 115.0          # output receptacle, front 0.65 mm over the right edge
X3, Y3 = 141.0, 129.0          # PC receptacle, front over the bottom edge

PLACE = {
    "J1": (PX, PY, 270), "J2": (X2, Y2, 90), "J3": (X3, Y3, 0),
    "R1": (114.0, 104.2, 0), "D1": (106.0, 108.0, 270), "U1": (114.0, 109.0, 0),
    "C1": (119.6, 110.4, 90), "R2": (121.4, 108.0, 90), "R3": (123.2, 108.0, 90), "R4": (125.0, 108.0, 90),
    "U2": (124.0, 124.5, 0), "C2": (117.6, 122.2, 90), "C3": (117.6, 125.3, 90), "C5": (117.6, 128.4, 90),
    "J4": (114.4, 124.0, 0),
    "R7": (103.0, 123.0, 90), "R9": (105.6, 123.0, 90), "R11": (108.2, 123.0, 90), "R13": (110.8, 123.0, 90),
    "R8": (103.0, 126.6, 90), "R10": (105.6, 126.6, 90), "R12": (108.2, 126.6, 90), "R14": (110.8, 126.6, 90),
    "C8": (103.0, 130.0, 90), "C9": (105.6, 130.0, 90), "C10": (108.2, 130.0, 90), "C11": (110.8, 130.0, 90),
    "U4": (141.0, 120.6, 0), "R5": (134.6, 121.4, 90), "R6": (147.0, 121.4, 90),
    "U3": (150.6, 124.6, 0), "C6": (153.4, 124.6, 90), "C4": (150.6, 128.0, 0),
    "R15": (129.6, 128.6, 0), "D2": (132.6, 128.6, 180),
}
assert set(PLACE) == set(parts), set(parts) ^ set(PLACE)
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
    fp.SetPosition(V(x, y))
    for pad in fp.Pads():
        n = p["nets"].get(pad.GetNumber())
        if n:
            pad.SetNet(net(n))
    FP[ref] = fp
    if ref.startswith(("R", "C")) and ref not in ("R1",):
        fp.Reference().SetVisible(False)
    if ref == "J4":                   # optional SWD header, not assembled: no BOM line, no 3D body
        fp.SetAttributes(fp.GetAttributes() | pcbnew.FP_EXCLUDE_FROM_BOM)
        fp.Models().clear()

def pad(ref, num, layer=None):
    for pd in FP[ref].Pads():
        if pd.GetNumber() == num and (layer is None or pd.IsOnLayer(layer)):
            pp = pd.GetPosition(); return (round(pcbnew.ToMM(pp.x), 4), round(pcbnew.ToMM(pp.y), 4))
    raise KeyError((ref, num))

# ---- board outline: rectangle + the plug paddle (its outline lives in the J1 footprint) ----
def seg(a, b):
    s = pcbnew.PCB_SHAPE(board); s.SetShape(pcbnew.SHAPE_T_SEGMENT); s.SetLayer(pcbnew.Edge_Cuts)
    s.SetStart(V(*a)); s.SetEnd(V(*b)); s.SetWidth(mm(0.1)); board.Add(s)
top_end = (round(PX + 1.93, 4), round(PY - 4.3, 4))       # loose ends of the J1 paddle outline
bot_end = (round(PX + 1.917, 4), round(PY + 3.9, 4))
for a, b in [(top_end, (X0, Y0)), ((X0, Y0), (X0 + W, Y0)), ((X0 + W, Y0), (X0 + W, Y0 + H)),
             ((X0 + W, Y0 + H), (X0, Y0 + H)), ((X0, Y0 + H), (X0, bot_end[1])), ((X0, bot_end[1]), bot_end)]:
    seg(a, b)
# router keep-out along the edges (Freerouting ignores KiCad's edge clearance)
KO = 0.6
for (x0, y0, x1, y1) in [(X0, Y0, X0 + W, Y0 + KO), (X0, Y0 + H - KO, X0 + W, Y0 + H),
                         (X0 + W - KO, Y0, X0 + W, Y0 + H),
                         (X0, Y0, X0 + KO, PY - 4.3), (X0, PY + 3.9, X0 + KO, Y0 + H)]:
    ko = pcbnew.ZONE(board)
    ko.SetIsRuleArea(True); ko.SetDoNotAllowTracks(True); ko.SetDoNotAllowVias(True)
    ko.SetDoNotAllowCopperPour(False); ko.SetDoNotAllowPads(False); ko.SetDoNotAllowFootprints(False)
    ls = pcbnew.LSET(); ls.AddLayer(pcbnew.F_Cu); ls.AddLayer(pcbnew.B_Cu); ko.SetLayerSet(ls)
    o = ko.Outline(); o.NewOutline()
    for (x, y) in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]:
        o.Append(mm(x), mm(y))
    board.Add(ko)

SEGS = []
F, B = pcbnew.F_Cu, pcbnew.B_Cu
def track(pts, w, n, layer=F):
    for a, b in zip(pts, pts[1:]):
        SEGS.append([tuple(round(v, 4) for v in a), tuple(round(v, 4) for v in b), w, n, layer])
def via(x, y, n, d=0.6):
    v = pcbnew.PCB_VIA(board); v.SetPosition(V(round(x, 4), round(y, 4))); v.SetWidth(mm(d)); v.SetDrill(mm(0.3))
    v.SetNet(net(n)); v.SetLayerPair(F, B); v.SetLocked(True); board.Add(v)

# ---- J1 plug: VBUS pins on both rows, joined by vias once the tracks leave the 0.5 mm pitch ----
pin_y = {"lo": PY + 1.25, "hi": PY - 1.25}
xe = PX + 0.93                       # straight out of the pad row before turning away from the signals
for side, sgn in (("lo", 1), ("hi", -1)):
    y = pin_y[side]
    xp = pad("J1", "A4" if side == "lo" else "A9")[0]
    a, b = (xp, y), (xe, y)
    c = (PX + 2.53, y + sgn * 1.6)
    for ly in (F, B):
        track([a, b], 0.25, "VBUS_IN", ly)
        track([b, c], 0.4, "VBUS_IN", ly)
    d = (PX + 2.83, y + sgn * 1.85); e = (PX + 3.53, y + sgn * 2.55)
    for ly in (F, B):
        track([c, d], 0.8, "VBUS_IN", ly)
    track([d, e], 0.8, "VBUS_IN", F)
    via(*d, "VBUS_IN"); via(*e, "VBUS_IN")
    track([d, e], 0.8, "VBUS_IN", B)
# upper half: straight up the left side to the bus that feeds R1
BUS_Y = 104.2
r1a = pad("R1", "1"); r1b = pad("R1", "2")
eh = (PX + 3.53, pin_y["hi"] - 2.55)
track([eh, (103.0, eh[1] - 0.9), (103.0, BUS_Y), (r1a[0], BUS_Y)], 2.0, "VBUS_IN")
# lower half: along y = 119.5, then up through the signal corridor on the top layer (signals pass on B.Cu)
el = (PX + 3.53, pin_y["lo"] + 2.55)
XC = 108.5
track([el, (102.6, 119.5), (XC, 119.5), (XC, BUS_Y)], 2.0, "VBUS_IN")
# TVS right on the input bus
d1k = pad("D1", "1")
track([(d1k[0], BUS_Y), d1k], 2.0, "VBUS_IN")
d1a = pad("D1", "2")
via(d1a[0] - 0.6, d1a[1] + 1.0, "GND"); via(d1a[0] + 0.6, d1a[1] + 1.0, "GND")
track([d1a, (d1a[0] - 0.6, d1a[1] + 1.0)], 0.8, "GND"); track([d1a, (d1a[0] + 0.6, d1a[1] + 1.0)], 0.8, "GND")

# ---- R1 Kelvin taps to U1 (IN+ pin 10, IN- pin 9, VBUS pin 8) ----
u10, u9, u8 = pad("U1", "10"), pad("U1", "9"), pad("U1", "8")
kp = (r1a[0] + 0.45, r1a[1] + 1.6)
track([kp, (kp[0], 106.8), (115.0, 106.8), (115.0, u10[1]), u10], 0.2, "VBUS_IN")
km = (r1b[0] - 0.45, r1b[1] + 1.6)
xk = 117.8
track([km, (km[0], 106.0), (xk, 106.0), (xk, u8[1])], 0.2, "VBUS_OUT")
track([(xk, u9[1]), u9], 0.2, "VBUS_OUT"); track([(xk, u8[1]), u8], 0.2, "VBUS_OUT")

# ---- VBUS_OUT: R1 -> top bus -> J2. J2's two VBUS pads are joined on B.Cu behind the pad row ----
XB = 146.9
j2hi = pad("J2", "A9"); j2lo = pad("J2", "A4")
track([r1b, (XB, BUS_Y)], 2.0, "VBUS_OUT")
track([(XB, BUS_Y), (XB, j2hi[1] - 0.7)], 1.4, "VBUS_OUT")
track([(XB, j2hi[1] - 0.7), (XB, j2hi[1]), j2hi], 0.6, "VBUS_OUT")
track([(XB, j2lo[1]), j2lo], 0.6, "VBUS_OUT")
for yy in (j2hi[1], j2lo[1]):
    via(XB, yy, "VBUS_OUT"); via(XB - 0.85, yy, "VBUS_OUT")
    track([(XB - 0.85, yy), (XB, yy)], 0.6, "VBUS_OUT", F)
    track([(XB - 0.85, yy), (XB, yy)], 0.6, "VBUS_OUT", B)
track([(XB - 0.42, j2hi[1]), (XB - 0.42, j2lo[1])], 1.2, "VBUS_OUT", B)

# ---- J2 D+/D- pairs: the receptacle has two pads per line, interleaved (B6 D+, A7 D-, A6 D+, B7 D-) ----
b6, a6, a7, b7 = pad("J2", "B6"), pad("J2", "A6"), pad("J2", "A7"), pad("J2", "B7")
track([b6, (147.0, b6[1]), (147.0, a6[1]), a6], 0.2, "DP")
xv = 147.75
for p_ in (a7, b7):
    track([p_, (xv, p_[1])], 0.2, "DM"); via(xv, p_[1], "DM", 0.5)
track([(xv, a7[1]), (xv, b7[1])], 0.2, "DM", B)

# ---- J3 (PC port): its two VBUS pads are joined on B.Cu behind the pad row, like J2's ----
j3a, j3b = pad("J3", "A4"), pad("J3", "B4")
yv = j3a[1] - 1.25
for p_ in (j3a, j3b):
    track([p_, (p_[0], yv)], 0.5, "VBUS_PC"); via(p_[0], yv, "VBUS_PC")
track([(j3a[0], yv), (j3b[0], yv)], 0.5, "VBUS_PC", B)

# ---- ground: plug and J2 ground pins straight to vias / shell ----
for pn, sgn in (("A1", 1), ("A12", -1)):
    p_ = pad("J1", pn)
    vx, vy = PX + 0.38, p_[1] + sgn * 0.03
    via(vx, vy, "GND")
    for ly in (F, B):
        track([p_, (vx, vy)], 0.4, "GND", ly)
for pn in ("A1", "A12"):
    p_ = pad("J2", pn)
    sh = min((pad_ for pad_ in [pd for pd in FP["J2"].Pads() if pd.GetNumber() == "S1"]),
             key=lambda q: abs(pcbnew.ToMM(q.GetPosition().y) - p_[1]) + abs(pcbnew.ToMM(q.GetPosition().x) - p_[0]))
    s = (pcbnew.ToMM(sh.GetPosition().x), pcbnew.ToMM(sh.GetPosition().y))
    track([p_, s], 0.6, "GND")

def emit_tracks():
    for a, b, w, n, ly in SEGS:
        if a == b:
            continue
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(V(*a)); t.SetEnd(V(*b)); t.SetWidth(mm(w)); t.SetLayer(ly)
        t.SetNet(net(n)); t.SetLocked(True); board.Add(t)

def silk(text, x, y, size=1.0, angle=0, layer=pcbnew.F_SilkS):
    t = pcbnew.PCB_TEXT(board); t.SetText(text); t.SetPosition(V(x, y)); t.SetLayer(layer)
    t.SetTextSize(V(size, size)); t.SetTextThickness(mm(0.15)); t.SetTextAngleDegrees(angle); board.Add(t)
silk("USB-C power meter", 128.5, 101.4, 0.9)
silk("rev D  4-48V 5A", 136.5, 102.7, 0.8)
silk("IN", 101.9, 113.0, 0.8, 90)
silk("OUT", 144.2, 120.5, 0.8)
silk("PC", 133.6, 131.0, 0.8)
silk("SWD", 114.4, 122.2, 0.8)

emit_tracks()
board.Save(OUT)
print("saved", OUT)
