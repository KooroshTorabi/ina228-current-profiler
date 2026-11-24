#!/bin/sh
# Rebuilds the schematic, PCB, fabrication outputs and 3D model for one variant.
# Needs: KiCad 7+ (pcbnew Python + kicad-cli, footprint and 3D libraries), Java,
#        xvfb-run and the Freerouting 1.9 jar.
# Usage: tools/build_pcb.sh /path/to/freerouting-1.9.0.jar [integrated|module]
#   PYTHON = python with pcbnew (default python3), PY3D = python with the 3D packages
set -e
cd "$(dirname "$0")/.."
VARIANT=${2:-integrated}
if [ "$VARIANT" = integrated ]; then HW=hardware; NAME=current_meter; else HW=hardware-module; NAME=current_adapter; fi
PCB=$HW/kicad/$NAME.kicad_pcb
PY=${PYTHON:-python3}
$PY tools/gen_schematic.py "$VARIANT"
$PY tools/gen_pcb.py "$PCB" "$VARIANT"
xvfb-run -a $PY tools/route.py "$PCB" "$1"
rm -rf logs "$HW/fab" && mkdir -p "$HW/fab/gerbers" "$HW/3d"
kicad-cli pcb export gerbers -l F.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts -o "$HW/fab/gerbers/" "$PCB"
kicad-cli pcb export drill -o "$HW/fab/gerbers/" "$PCB"
kicad-cli pcb export pos --format csv --units mm --side front -o "$HW/fab/positions_top.csv" "$PCB"
(cd "$HW/fab" && zip -qr gerbers.zip gerbers)
kicad-cli sch export pdf -o "$HW/schematic.pdf" "$HW/kicad/$NAME.kicad_sch"
KICAD7_3DMODEL_DIR=${KICAD7_3DMODEL_DIR:-/usr/share/kicad/3dmodels} \
  kicad-cli pcb export step --subst-models --force -o "$HW/3d/$NAME.step" "$PCB"
# 3D: GLB with board textures + PNG renders (python with cadquery-ocp, trimesh, pyrender)
PY3D=${PY3D:-python3}
$PY3D tools/step2glb.py "$HW/3d/$NAME.step" "$HW/3d/$NAME.glb"
$PY3D tools/make_3d.py "$PCB" "$HW/3d/$NAME.glb" "$HW/3d/$NAME.glb"
mkdir -p docs/$VARIANT
PYOPENGL_PLATFORM=${PYOPENGL_PLATFORM:-osmesa} $PY3D tools/render_3d.py "$HW/3d/$NAME.glb" "docs/$VARIANT/3d"
for v in "F.Cu,F.SilkS,F.Mask,Edge.Cuts:top" "B.Cu,B.SilkS,Edge.Cuts:bottom"; do
  kicad-cli pcb export svg --layers "${v%:*}" --page-size-mode 2 --exclude-drawing-sheet -o "docs/$VARIANT/pcb_${v#*:}.svg" "$PCB"
done
T=$(mktemp -d); kicad-cli sch export svg -o "$T" "$HW/kicad/$NAME.kicad_sch" >/dev/null && cp "$T/$NAME.svg" "docs/$VARIANT/schematic.svg"; rm -rf "$T"
echo "done: $VARIANT"
