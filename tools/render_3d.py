# Renders PNG previews of a board GLB (from make_3d.py).
# Usage: PYOPENGL_PLATFORM=osmesa python3 tools/render_3d.py model.glb out_prefix
#   needs: pip install trimesh pyrender pillow "pyopengl==3.1.7", apt libosmesa6
import sys
import numpy as np
import trimesh, pyrender
from PIL import Image

GLB, OUT = sys.argv[1], sys.argv[2]
tm = trimesh.load(GLB)
scene = pyrender.Scene.from_trimesh_scene(tm, ambient_light=[0.35, 0.35, 0.35])
scene.bg_color = np.array([1.0, 1.0, 1.0, 1.0])
c = tm.bounds.mean(axis=0); size = np.linalg.norm(tm.bounds[1] - tm.bounds[0])

def look_at(eye, target, up=(0, 0, 1)):
    f = np.array(target) - eye; f /= np.linalg.norm(f)
    s = np.cross(f, up); s /= np.linalg.norm(s); u = np.cross(s, f)
    m = np.eye(4); m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3] = s, u, -f, eye
    return m

def render(direction, name, w=1600, h=1100):
    sc = scene
    eye = c + np.array(direction) / np.linalg.norm(direction) * size * 1.25
    cam = pyrender.PerspectiveCamera(yfov=np.radians(38), aspectRatio=w / h, znear=0.001)
    nc = sc.add(cam, pose=look_at(eye, c))
    l1 = sc.add(pyrender.DirectionalLight(color=np.ones(3), intensity=3.0), pose=look_at(eye, c))
    l2 = sc.add(pyrender.DirectionalLight(color=np.ones(3), intensity=1.5),
                pose=look_at(c + np.array([-direction[0], direction[1], abs(direction[2])]), c))
    r = pyrender.OffscreenRenderer(w, h)
    color, _ = r.render(sc)
    r.delete()
    for n in (nc, l1, l2):
        sc.remove_node(n)
    color = np.ascontiguousarray(color)
    if color.shape[2] == 4:
        im = Image.fromarray(color, "RGBA")
    else:
        im = Image.fromarray(color, "RGB").convert("RGBA")
        a = np.array(im); white = (a[..., :3] > 250).all(axis=2); a[white, 3] = 0; im = Image.fromarray(a, "RGBA")
    im = im.crop(im.getbbox())
    bg = Image.new("RGBA", (im.width + 60, im.height + 60), (255, 255, 255, 255))
    bg.paste(im, (30, 30), im)
    bg.convert("RGB").save(f"{OUT}_{name}.png")
    print("wrote", f"{OUT}_{name}.png")

render([0.55, -0.9, 0.95], "top")       # from the front-right, above
render([0.55, 0.9, -0.95], "bottom")    # from below
