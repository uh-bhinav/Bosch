---
name: occ-pythonocc-reference
description: pythonOCC (OpenCASCADE) class glossary and patterns used in this codebase. Use when writing or reviewing geometry module code that touches OCC APIs.
---

# pythonOCC / OpenCASCADE Reference for This Project

## Installation

ALWAYS via conda: `conda install -c conda-forge pythonocc-core=7.7.2`
NEVER pip — C++ extensions are unreliable outside conda-forge.

## Core Classes Used

### STEP Loading
```python
from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.IFSelect import IFSelect_RetDone

reader = STEPControl_Reader()
status = reader.ReadFile(str(filepath))  # returns IFSelect_RetDone on success
reader.TransferRoots()
shape = reader.OneShape()  # → TopoDS_Shape
```

### Shape Traversal
```python
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX, TopAbs_SOLID, TopAbs_SHELL
from OCC.Core.TopoDS import topods, topods_Face, topods_Edge, topods_Vertex

exp = TopExp_Explorer(shape, TopAbs_FACE)
while exp.More():
    face = topods.Face(exp.Current())  # or topods_Face() for older versions
    # process face
    exp.Next()
```

### Surface Properties
```python
from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
from OCC.Core.GeomAbs import GeomAbs_Plane, GeomAbs_Cylinder, ...

adaptor = BRepAdaptor_Surface(face)
surface_type = adaptor.GetType()  # → GeomAbs enum
u_min, u_max = adaptor.FirstUParameter(), adaptor.LastUParameter()
```

### Normal Computation
```python
from OCC.Core.BRep import BRep_Tool
from OCC.Core.GeomLProp import GeomLProp_SLProps

surface = BRep_Tool.Surface(face)
slprops = GeomLProp_SLProps(surface, u_mid, v_mid, 1, 1e-9)
if slprops.IsNormalDefined():
    normal = slprops.Normal()  # → gp_Dir
    point = slprops.Value()    # → gp_Pnt
```

**CRITICAL**: Check `face.Orientation() == TopAbs_REVERSED` → flip normal sign to get outward normal.

### Area / Length
```python
from OCC.Core.BRepGProp import brepgprop
from OCC.Core.GProp import GProp_GProps

props = GProp_GProps()
brepgprop.SurfaceProperties(face, props)
area = props.Mass()  # surface area in mm²

brepgprop.LinearProperties(edge, props)
length = props.Mass()  # arc length in mm
```

### Bounding Box
```python
from OCC.Core.BRepBndLib import brepbndlib
from OCC.Core.Bnd import Bnd_Box

bbox = Bnd_Box()
brepbndlib.Add(shape, bbox)
xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
```

### Boolean Operations (Undercut Detection)
```python
from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakePrism
from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Common
from OCC.Core.gp import gp_Vec

# Sweep a face along pull direction
prism = BRepPrimAPI_MakePrism(face, gp_Vec(dx * dist, dy * dist, dz * dist))
swept = prism.Shape()

# Boolean intersection with original solid
common = BRepAlgoAPI_Common(solid, swept)
if common.IsDone():
    interference = common.Shape()
```

### Hash-Based Deduplication
```python
HASH_MOD = 2**31 - 1
edge_hash = edge.HashCode(HASH_MOD)  # stable for same TShape
```

Used to deduplicate edges and vertices across faces. Birthday paradox risk ≈ 6×10⁻⁶ for ≤5000 shapes.

## Version Compatibility

This codebase supports both old (`topods_Face()`) and new (`topods.Face()`) casting patterns:
```python
def _as_face(shape):
    if hasattr(topods, "Face"):
        return topods.Face(shape)
    return topods_Face(shape)
```

## Common Pitfalls

1. **UV parameter overflow**: Unbounded surfaces (open cylinders) return UV ranges of ±1e100. Always clamp: `_clamp_uv()`.
2. **Seam edges**: Full cylinders/spheres have seam edges that appear TWICE in a face's wire. Detect via same hash appearing 2× for same face.
3. **Boolean brittleness**: OCC Booleans fail on thin/degenerate geometry. Always wrap in try/except with retry offsets.
4. **Memory**: OCC shapes are C++ objects with reference counting. Don't hold unnecessary references.
