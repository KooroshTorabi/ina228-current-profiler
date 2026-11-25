# Adds simple 3D bodies for the USB-C connectors of rev D, which have no 3D models in KiCad's library:
# J1 (JAE DX07 slim plug on the board-edge paddle), J2 and J3 (HRO TYPE-C-31-M-12 receptacles).
# Usage: python3 tools/add_usb_bodies.py board.kicad_pcb in.glb out.glb   (needs trimesh, numpy)
import json, math, subprocess, sys
import numpy as np
import trimesh

PCB, GLB_IN, GLB_OUT = sys.argv[1:4]
info = json.loads(subprocess.check_output(["/usr/bin/python3", "-c", r'''
import pcbnew, json, sys
b = pcbnew.LoadBoard(sys.argv[1]); mm = pcbnew.ToMM; out = {}
for fp in b.GetFootprints():
    if fp.GetReference() in ("J1", "J2", "J3"):
        p = fp.GetPosition(); out[fp.GetReference()] = (mm(p.x), mm(p.y), fp.GetOrientationDegrees())
out["t"] = mm(b.GetDesignSettings().GetBoardThickness())
print(json.dumps(out))''', PCB]))
T = info["t"]

METAL = [200, 200, 205, 255]
DARK = [25, 25, 28, 255]
BLACK = [40, 40, 44, 255]

def stadium(w, h, length, color):
    """Rounded USB-C shell: width w (x), height h (z), extruded along +y over `length`, from y = 0."""
    r = h / 2
    parts = [trimesh.creation.box(extents=[w - 2 * r, length, h])]
    for sx in (-1, 1):
        c = trimesh.creation.cylinder(radius=r, height=length, sections=24)
        c.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, [1, 0, 0]))
        c.apply_translation([sx * (w / 2 - r), 0, 0])
        parts.append(c)
    m = trimesh.util.concatenate(parts)
    m.apply_translation([0, length / 2, 0])
    m.visual.face_colors = color
    return m

def box(x0, x1, y0, y1, z0, z1, color):
    m = trimesh.creation.box(extents=[x1 - x0, y1 - y0, z1 - z0])
    m.apply_translation([(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2])
    m.visual.face_colors = color
    return m

def place(meshes, ref):
    """Footprint coordinates (mm, y towards the connector's mating side) -> glb (m, y up, z up)."""
    x, y, rot = info[ref]
    out = []
    for m in meshes:
        m = m.copy()
        # KiCad footprint y points down the screen; the glb's y points up: mirror y first
        m.apply_transform(np.diag([1, -1, 1, 1]))
        m.apply_transform(trimesh.transformations.rotation_matrix(math.radians(rot), [0, 0, 1]))
        m.apply_translation([x, -y, 0])
        m.apply_scale(0.001)
        out.append(m)
    return out

def receptacle():
    # body 8.94 x 7.3 mm, 3.26 mm tall, front face at y = +3.65 (footprint coordinates)
    shell = stadium(8.94, 3.26, 7.3, METAL); shell.apply_translation([0, -3.65, T + 1.63])
    mouth = stadium(8.34, 2.56, 0.3, DARK); mouth.apply_translation([0, 3.40, T + 1.63])
    tongue = box(-3.3, 3.3, 0.2, 3.5, T + 1.45, T + 1.85, BLACK)
    return [shell, mouth, tongue]

def plug():
    # housing clamps the paddle around the contact rows, the metal plug sticks out past the tip (y = 3.02)
    mid = T / 2
    housing = box(-4.3, 4.3, -1.2, 3.02, mid - T / 2 - 0.9, mid + T / 2 + 0.9, BLACK)
    shell = stadium(8.25, 2.4, 6.65, METAL); shell.apply_translation([0, 3.02, mid])
    mouth = stadium(7.6, 1.8, 0.3, DARK); mouth.apply_translation([0, 3.02 + 6.4, mid])
    return [housing, shell, mouth]

scene = trimesh.load(GLB_IN)
for ref, maker in (("J1", plug), ("J2", receptacle), ("J3", receptacle)):
    # one node named after the reference, like KiCad's own parts, so viewers can pick and hide it
    scene.graph.update(frame_from=scene.graph.base_frame, frame_to=ref, matrix=np.eye(4))
    for i, m in enumerate(place(maker(), ref)):
        scene.add_geometry(m, node_name=f"{ref}_body_{i}", parent_node_name=ref)
scene.export(GLB_OUT)
print("wrote", GLB_OUT)
