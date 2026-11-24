# Converts a KiCad STEP export (with colors) to a binary glTF (.glb) for web viewers.
# Usage: python3 tools/step2glb.py in.step out.glb   (needs: pip install cadquery-ocp)
import sys
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TDocStd import TDocStd_Document
from OCP.TCollection import TCollection_ExtendedString, TCollection_AsciiString
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.TDF import TDF_ChildIterator
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.RWGltf import RWGltf_CafWriter
from OCP.OCP.collections import IndexedDataMap_TCollection_AsciiString_TCollection_AsciiString as InfoMap
from OCP.Message import Message_ProgressRange
from OCP.IFSelect import IFSelect_RetDone

src, dst = sys.argv[1], sys.argv[2]
doc = TDocStd_Document(TCollection_ExtendedString("doc"))
r = STEPCAFControl_Reader(); r.SetColorMode(True); r.SetNameMode(True)
assert r.ReadFile(src) == IFSelect_RetDone, "cannot read STEP"
r.Transfer(doc)
st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
it = TDF_ChildIterator(st.Label(), False)
while it.More():
    shp = st.GetShape_s(it.Value())
    if not shp.IsNull():
        BRepMesh_IncrementalMesh(shp, 0.05, False, 0.3, True)
    it.Next()
w = RWGltf_CafWriter(TCollection_AsciiString(dst), True)  # binary .glb
ok = w.Perform(doc, InfoMap(), Message_ProgressRange()); assert ok, "glTF export failed"
print("wrote", dst)
