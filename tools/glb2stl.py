# Exports a single-colour STL (in mm) from a board GLB, for GitHub's built-in 3D file viewer.
# Usage: python3 tools/glb2stl.py in.glb out.stl   (needs: pip install trimesh)
import sys
import trimesh

src, dst = sys.argv[1], sys.argv[2]
scene = trimesh.load(src)
meshes = []
for name in scene.graph.nodes_geometry:
    if name.startswith("pcb_") and name.endswith("_layers"):  # texture overlays from make_3d.py
        continue
    T, g = scene.graph[name]
    m = scene.geometry[g].copy(); m.apply_transform(T); meshes.append(m)
mesh = trimesh.util.concatenate(meshes)
mesh.apply_scale(1000.0)  # glTF metres -> mm
mesh.export(dst)
print("wrote", dst)
