#!/bin/sh
# Rebuilds hardware/kicad/current_meter.kicad_pcb and the fabrication outputs.
# Needs: KiCad 7+ (pcbnew Python + kicad-cli), Java, xvfb-run and the Freerouting 1.9 jar.
# Usage: tools/build_pcb.sh /path/to/freerouting-1.9.0.jar
set -e
cd "$(dirname "$0")/.."
PCB=hardware/kicad/current_meter.kicad_pcb
python3 tools/gen_schematic.py
python3 tools/gen_pcb.py "$PCB"
xvfb-run -a python3 tools/route.py "$PCB" "$1"
rm -rf hardware/fab && mkdir -p hardware/fab/gerbers
kicad-cli pcb export gerbers -l F.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts -o hardware/fab/gerbers/ "$PCB"
kicad-cli pcb export drill -o hardware/fab/gerbers/ "$PCB"
kicad-cli pcb export pos --format csv --units mm --side front -o hardware/fab/positions_top.csv "$PCB"
(cd hardware/fab && zip -qr gerbers.zip gerbers)
for v in "F.Cu,F.SilkS,F.Mask,Edge.Cuts:top" "B.Cu,B.SilkS,Edge.Cuts:bottom"; do
  kicad-cli pcb export svg --layers "${v%:*}" --page-size-mode 2 --exclude-drawing-sheet -o "docs/pcb_${v#*:}.svg" "$PCB"
done
echo "done"
