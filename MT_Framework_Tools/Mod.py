from collections import OrderedDict
from .Cstruct import PyCStruct

class MODHeader(PyCStruct):
    fields = OrderedDict([
        ("boneCount", "ushort"),
        ("meshCount", "ushort"),
        ("matCount", "ushort"),
        ("vertCount", "ulong"),
        ("triangleCount", "ulong"),
        ("vertexIds", "ulong"),
        ("vertexBufferSize", "ulong"),
        ("padding", "ulong"),
        ("boneMapCount", "ulong"),
        ("ptr_Bone", "ulong"),
        ("ptr_BoneMap", "ulong"),
        ("ptr_MatID", "ulong"),
        ("ptr_Mesh", "ulong"),
        ("ptr_vertex", "ulong"),
        ("ptr_triangle", "ulong"),
        ("endSize", "ulong"),
    ])

class MeshHeaderStruct(PyCStruct):
    fields = OrderedDict([
        ("meshtype", "ushort"),
        ("vertCount", "ushort"),
        ("unk01", "ubyte"),
        ("MatId", "ushort"),
        ("lodLevel", "ubyte"),
        ("unk04", "ubyte"),
        ("vertFlag", "ubyte"),
        ("vertStride", "ubyte"),
        ("unk05", "ubyte"),
        ("vertStart", "ulong"),
        ("vertBase", "ulong"),
        ("fvfInfo", "ulong"),
        ("faceStart", "ulong"),
        ("faceCount", "ulong"),
        ("faceBase", "ulong"),
        ("bonemapindex", "ubyte"),
        ("weightmaps", "ubyte"),
        ("unk07", "ubyte"),
        ("unk08", "ubyte"),
        ("min_index", "ushort"),
        ("max_index", "ushort"),
        ("unk09", "ulong"),
    ])
