# Adds copper / solder-mask / silkscreen textures to the board in a GLB produced by step2glb.py.
# KiCad's STEP export has the board body and parts but no copper or silkscreen, so this
# renders those layers with kicad-cli and lays them on the top and bottom faces.
# Usage: python3 tools/make_3d.py board.kicad_pcb in.glb out.glb
#   needs kicad-cli, rsvg-convert, /usr/bin/python3 with pcbnew, and: pip install trimesh pillow
import json, os, subprocess, sys, tempfile
import numpy as np
import trimesh
from PIL import Image

PCB, GLB_IN, GLB_OUT = sys.argv[1:4]
PXMM = 20  # texture resolution, px per mm

# board outline + drill holes from pcbnew (system python)
info = json.loads(subprocess.check_output(["/usr/bin/python3", "-c", r'''
import pcbnew, json, sys
b = pcbnew.LoadBoard(sys.argv[1]); bb = b.GetBoardEdgesBoundingBox(); mm = pcbnew.ToMM
holes = []
for p in b.GetPads():
    if p.GetDrillSize().x > 0:
        q = p.GetPosition(); holes.append((mm(q.x), mm(q.y), mm(p.GetDrillSize().x) / 2))
for t in b.GetTracks():
    if t.Type() == pcbnew.PCB_VIA_T:
        q = t.GetPosition(); holes.append((mm(q.x), mm(q.y), mm(t.GetDrillValue()) / 2))
print(json.dumps(dict(x0=mm(bb.GetLeft()), y0=mm(bb.GetTop()), x1=mm(bb.GetRight()), y1=mm(bb.GetBottom()),
                      t=mm(b.GetDesignSettings().GetBoardThickness()), holes=holes)))
''', PCB]))
x0, y0, x1, y1 = info["x0"], info["y0"], info["x1"], info["y1"]
W, H = int(round((x1 - x0) * PXMM)), int(round((y1 - y0) * PXMM))
tmp = tempfile.mkdtemp()

def layer_mask(layer):
    svg = os.path.join(tmp, layer + ".svg"); png = os.path.join(tmp, layer + ".png")
    subprocess.check_call(["kicad-cli", "pcb", "export", "svg", "--black-and-white", "--layers", layer,
                           "--page-size-mode", "0", "--exclude-drawing-sheet", "-o", svg, PCB],
                          stdout=subprocess.DEVNULL)
    # A4 page in mm; page coordinates are board coordinates
    subprocess.check_call(["rsvg-convert", "-w", str(297 * PXMM), "-h", str(210 * PXMM), "-b", "white", svg, "-o", png])
    im = Image.open(png).convert("L")
    im = im.crop((int(round(x0 * PXMM)), int(round(y0 * PXMM)), int(round(x0 * PXMM)) + W, int(round(y0 * PXMM)) + H))
    return np.array(im) < 128

def texture(side):
    cu, mask, silk = (layer_mask(f"{side}.{l}") for l in ("Cu", "Mask", "SilkS"))
    img = np.zeros((H, W, 4), np.uint8)
    img[...] = (22, 92, 52, 255)                   # solder mask over bare FR4
    img[cu] = (44, 128, 70, 255)                   # copper under mask
    img[mask & cu] = (212, 175, 90, 255)           # exposed copper, ENIG gold
    img[mask & ~cu] = (190, 170, 120, 255)         # mask opening without copper
    img[silk & ~mask] = (240, 240, 235, 255)       # silkscreen
    yy, xx = np.mgrid[0:H, 0:W]
    for hx, hy, r in info["holes"]:                # drill holes see-through
        cx, cy = (hx - x0) * PXMM, (hy - y0) * PXMM
        img[(xx - cx) ** 2 + (yy - cy) ** 2 <= (r * PXMM) ** 2] = (0, 0, 0, 0)
    return Image.fromarray(img, "RGBA")

scene = trimesh.load(GLB_IN)
# glb coordinates: metres, x = board x, y = -board y, z up; board spans z = [0, thickness]
t_m = info["t"] / 1000.0
eps = 0.00002
def quad(img, z, flip):
    xa, xb, ya, yb = x0 / 1000, x1 / 1000, -y0 / 1000, -y1 / 1000
    v = np.array([[xa, ya, z], [xb, ya, z], [xb, yb, z], [xa, yb, z]])
    uv = np.array([[0, 1], [1, 1], [1, 0], [0, 0]], float)
    f = np.array([[0, 2, 1], [0, 3, 2]]) if not flip else np.array([[0, 1, 2], [0, 2, 3]])
    if flip:  # bottom face seen from below: KiCad renders B.* layers as seen from the top
        pass
    mat = trimesh.visual.material.PBRMaterial(baseColorTexture=img, alphaMode="MASK", alphaCutoff=0.5,
                                              metallicFactor=0.0, roughnessFactor=0.7, doubleSided=False)
    m = trimesh.Trimesh(vertices=v, faces=f, process=False)
    m.visual = trimesh.visual.TextureVisuals(uv=uv, material=mat)
    # make the faces point the right way (up for top, down for bottom)
    want = -1 if flip else 1
    if np.sign(m.face_normals[0][2]) != want:
        m.faces = m.faces[:, ::-1]
    return m
top = quad(texture("F"), t_m + eps, False)
bot = quad(texture("B"), -eps, True)
scene.add_geometry(top, node_name="pcb_top_layers")
scene.add_geometry(bot, node_name="pcb_bottom_layers")
scene.export(GLB_OUT)
print("wrote", GLB_OUT)
