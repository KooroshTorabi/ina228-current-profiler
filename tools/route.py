# Autoroutes the non-critical nets with Freerouting and adds the ground pours.
# Usage: /usr/bin/python3 tools/route.py <board.kicad_pcb> <freerouting.jar>
# Needs Java and, for Freerouting 1.9, an X display (e.g. run under xvfb-run).
import os, re, subprocess, sys
import pcbnew

PCB, JAR = sys.argv[1], sys.argv[2]
# Hand-routed in gen_pcb.py; the router must never add copper to these.
CRITICAL = set(os.environ.get("ROUTE_CRITICAL", "VIN,NODE_A,NODE_B,DUT_VDD").split(","))
mm = pcbnew.FromMM

base = os.path.splitext(PCB)[0]
dsn, ses = base + ".dsn", base + ".ses"
LAYER = {"F.Cu": pcbnew.F_Cu, "B.Cu": pcbnew.B_Cu}

def add_pours(board):
    nets = board.GetNetsByName()
    # Ground pours on both layers
    bb = board.GetBoardEdgesBoundingBox()
    for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
        z = pcbnew.ZONE(board)
        z.SetLayer(layer); z.SetNet(nets["GND"]); z.SetLocalClearance(mm(0.3))
        z.SetMinThickness(mm(0.25)); z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
        z.SetThermalReliefGap(mm(0.3)); z.SetThermalReliefSpokeWidth(mm(0.4))
        o = z.Outline(); o.NewOutline()
        for x, y in [(bb.GetLeft(), bb.GetTop()), (bb.GetRight(), bb.GetTop()),
                     (bb.GetRight(), bb.GetBottom()), (bb.GetLeft(), bb.GetBottom())]:
            o.Append(x, y)
        board.Add(z)
    # thermal relief only on through-hole GND pads (hand soldering)
    for fp in board.GetFootprints():
        for pd in fp.Pads():
            if pd.GetNetname() == "GND" and pd.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
                pd.SetZoneConnection(pcbnew.ZONE_CONNECTION_THERMAL)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())

def route_once():
    board = pcbnew.LoadBoard(PCB)
    pcbnew.ExportSpecctraDSN(board, dsn)
    if os.path.exists(ses):
        os.remove(ses)
    subprocess.run(["java", "-jar", JAR, "-de", dsn, "-do", ses, "-mp", "40"], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600)
    text = open(ses).read()
    res = int(re.search(r"\(resolution um (\d+)\)", text).group(1))
    to_mm = lambda v: int(v) / res / 1000.0
    nets = board.GetNetsByName()
    locked = [(t.GetNetname(), t.GetLayer(), pcbnew.ToMM(t.GetStart().x), pcbnew.ToMM(t.GetStart().y),
               pcbnew.ToMM(t.GetEnd().x), pcbnew.ToMM(t.GetEnd().y))
              for t in board.GetTracks() if t.Type() == pcbnew.PCB_TRACE_T and t.IsLocked()]
    def on_seg(px, py, x1, y1, x2, y2, tol=0.002):
        dx, dy = x2 - x1, y2 - y1; L2 = dx * dx + dy * dy
        u = 0 if L2 == 0 else max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / L2))
        return ((x1 + u * dx - px) ** 2 + (y1 + u * dy - py) ** 2) ** 0.5 < tol
    def covered(name, layer, a, b):
        return any(n == name and ly == layer and on_seg(*a, *s4) and on_seg(*b, *s4)
                   for (n, ly, *s4) in locked)
    net_out = text[text.index("(network_out"):]
    added_t = added_v = 0
    for m in re.finditer(r"\(net (\S+)\n(.*?)\n      \)\n", net_out, re.S):
        name, body = m.group(1).strip('"'), m.group(2)
        if name in CRITICAL:
            continue
        ni = nets[name]
        for wm in re.finditer(r"\(path (\S+) (\d+)\s+([-\d\s]+)\)", body):
            layer, width = wm.group(1), int(wm.group(2))
            v = list(map(int, wm.group(3).split()))
            pts = [(to_mm(x), -to_mm(y)) for x, y in zip(v[::2], v[1::2])]
            for a, b in zip(pts, pts[1:]):
                if abs(a[0] - b[0]) + abs(a[1] - b[1]) < 0.01 or covered(name, LAYER[layer], a, b):
                    continue
                t = pcbnew.PCB_TRACK(board)
                t.SetStart(pcbnew.VECTOR2I(mm(a[0]), mm(a[1]))); t.SetEnd(pcbnew.VECTOR2I(mm(b[0]), mm(b[1])))
                t.SetWidth(int(width / res * 1000)); t.SetLayer(LAYER[layer]); t.SetNet(ni)
                board.Add(t); added_t += 1
        for vm in re.finditer(r'\(via "?Via\[0-1\]_(\d+):(\d+)_um"?\s+(-?\d+) (-?\d+)', body):
            dia, drill, x, y = map(int, vm.groups())
            via = pcbnew.PCB_VIA(board)
            via.SetPosition(pcbnew.VECTOR2I(mm(to_mm(x)), mm(-to_mm(y))))
            via.SetWidth(mm(dia / 1000)); via.SetDrill(mm(drill / 1000)); via.SetNet(ni)
            via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
            board.Add(via); added_v += 1
    add_pours(board)                   # ground is finished by the pours, so count after filling them
    board.BuildConnectivity()
    unrouted = board.GetConnectivity().GetUnconnectedCount(True)
    # copper DRC problems from the router (e.g. edge clearance) count as failures too
    rpt = base + "_check.rpt"
    pcbnew.WriteDRCReport(board, rpt, pcbnew.EDA_UNITS_MILLIMETRES, True)
    # a footprint's own pads sitting near its own board-edge cut-out (USB plug paddle) is not a router problem
    blocks = re.split(r"\n(?=\[)", open(rpt).read())
    bad = [b.splitlines()[0] for b in blocks if b.startswith("[") and "Severity: error" in b
           and not b.startswith(("[lib_footprint", "[silk", "[text_height", "[unconnected_items"))
           and not (b.startswith("[copper_edge_clearance") and "Track" not in b and "Via" not in b)]
    os.remove(rpt)
    if bad:
        print("  router DRC issues:", sorted(set(b.split("]")[0] + "]" for b in bad)))
    return board, unrouted + len(bad), added_t, added_v

for attempt in range(1, int(os.environ.get("ROUTE_ATTEMPTS", "5")) + 1):
    board, unrouted, added_t, added_v = route_once()
    print(f"attempt {attempt}: {added_t} tracks, {added_v} vias, {unrouted} problems")
    if unrouted == 0:
        break
else:
    rpt = base + "_unrouted.rpt"
    pcbnew.WriteDRCReport(board, rpt, pcbnew.EDA_UNITS_MILLIMETRES, True)
    lines = open(rpt).read().split("[unconnected_items]")[1:]
    for blk in lines:
        print("  unrouted:", " | ".join(l.strip() for l in blk.splitlines()[2:4]))
    sys.exit("Freerouting did not complete the board")
board.Save(PCB)
for f in (dsn, ses):
    os.remove(f)
print("routed, ground pours filled, saved", PCB)
