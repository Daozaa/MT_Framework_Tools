import bpy
import struct
import re
from mathutils import Vector, Matrix, Euler
from bpy.props import (
    StringProperty, BoolProperty, IntProperty, FloatProperty,
    EnumProperty, CollectionProperty
)

mod_ver = 0
hidedege = False
hidelod0 = False

class Header:
    def __init__(self):
        self.BoneCount = 0
        self.MeshCount = 0
        self.MatCount = 0
        self.VertCount = 0
        self.TriangleCount = 0
        self.VertexIds = 0
        self.VertexBufferSize = 0
        self.Padding = 0
        self.BoneMapCount = 0
        self.ptr_Bone = 0
        self.ptr_BoneMap = 0
        self.ptr_MatID = 0
        self.ptr_Mesh = 0
        self.ptr_vertex = 0
        self.ptr_triangle = 0
        self.EndSize = 0

class BoneInfo:
    def __init__(self):
        self.ID = 0
        self.Parent = 0
        self.Child = 0
        self.uk1 = 0
        self.Trans = [0.0, 0.0, 0.0]
        self.uk2 = 0.0
        self.uk3 = 0.0

class MeshHeader:
    def __init__(self):
        self.meshtype = 0
        self.vertCount = 0
        self.unk01 = 0
        self.MatId = 0
        self.lodLevel = 0
        self.unk04 = 0
        self.vertFlag = 0
        self.vertStride = 0
        self.unk05 = 0
        self.vertStart = 0
        self.vertBase = 0
        self.fvfInfo = 0
        self.faceStart = 0
        self.faceCount = 0
        self.faceBase = 0
        self.bonemapindex = 0
        self.weightmaps = 0
        self.unk07 = 0
        self.unk08 = 0
        self.min_index = 0
        self.max_index = 0
        self.unk09 = 0

class EMSEntryB:
    def __init__(self):
        self.name = ""
        self.offset = 0
        self.IDA = 0
        self.IDB = 0
        self.IDC = 0
        self.IDD = 0
        self.onea = 0
        self.px = 0.0
        self.py = 0.0
        self.pz = 0.0
        self.pw = 0.0
        self.oneb = 0
        self.rx = 0.0
        self.ry = 0.0
        self.rz = 0.0
        self.rw = 0.0
        self.onec = 0
        self.bdta = 0
        self.oned = 0
        self.bdtb = 0
        self.onee = 0
        self.bdtc = 0
        self.onef = 0
        self.bidtag = 0
        self.oneg = 0
        self.IDE = 0
        self.IDF = 0
        self.oneh = 0
        self.IDG = 0
        self.onei = 0
        self.IDH = 0
        self.onej = 0
        self.bingame = 0

def read_byte(f):
    data = f.read(1)
    if not data:
        return 0
    return struct.unpack('<B', data)[0]

def read_short(f):
    data = f.read(2)
    if not data or len(data) < 2:
        return 0
    return struct.unpack('<H', data)[0]

def read_short_signed(f):
    data = f.read(2)
    if not data or len(data) < 2:
        return 0
    return struct.unpack('<h', data)[0]

def read_long(f):
    data = f.read(4)
    if not data or len(data) < 4:
        return 0
    return struct.unpack('<I', data)[0]

def read_float(f):
    data = f.read(4)
    if not data or len(data) < 4:
        return 0.0
    return struct.unpack('<f', data)[0]

def read_float16(f):
    hf = read_short(f)
    sign = (hf >> 15) & 1
    exponent = ((hf >> 10) & 0x1F) - 15
    fraction = hf & 0x03FF

    if exponent == -15:

        if fraction == 0:
            return 0.0
        output = fraction / 1024.0 * (2 ** (-14))
    elif exponent == 16:
        return 0.0
    else:
        output = (1.0 + fraction / 1024.0) * (2 ** exponent)

    if sign:
        output = -output
    return output

def float_to_short(fValue):
    import struct as _struct

    Src = _struct.unpack('<I', _struct.pack('<f', fValue))[0]

    Sign = (Src >> 31) & 1
    exponent = ((Src >> 23) & 0xFF) - 127 + 15
    Mantissa = Src & 0x007FFFFF

    if 0 <= exponent <= 30:
        Result = (Sign << 15) | (exponent << 10) | ((Mantissa + 0x00001000) >> 13)
    else:
        if Src == 0:
            Result = 0
        else:
            if exponent <= 0:
                if exponent <= -10:
                    Result = 0
                else:
                    Mantissa = (Mantissa | 0x00800000) >> (1 - exponent)
                    if (Mantissa & 0x00001000):
                        Mantissa = Mantissa + 0x00002000
                        Result = (Sign << 15) | (Mantissa >> 13)
                    else:
                        Result = 0
            else:
                if exponent == 255 - 127 + 15:
                    if Mantissa == 0:
                        Result = (Sign << 15) | 0x7C00
                    else:
                        Result = (Sign << 15) | 0x7C00 | (Mantissa >> 13)
                else:
                    if (Mantissa & 0x00001000):
                        Mantissa = Mantissa + 0x00002000
                        if (Mantissa & 0x00800000):
                            Mantissa = 0
                            exponent = exponent + 1
                    if exponent >= 30:
                        Result = (Sign << 15) | 0x7C00
                    else:
                        Result = (Sign << 15) | (exponent << 10) | (Mantissa >> 13)
    return Result

def read_fixed_string(f, fixed_len):
    s = b''
    length = 0
    finished = False
    for i in range(fixed_len):
        c = read_byte(f)
        if c == 0:
            finished = True
        if finished:
            continue
        s += bytes([c])
        if c != 32:
            length = i + 1
    return s[:length].decode('ascii', errors='replace')

def paddstring(length, instring):
    s = str(instring)
    if len(s) <= length:
        return '0' * (length - len(s)) + s
    else:
        return s[:length]

def read_vec3_pos(f):
    x = read_float(f)
    z = read_float(f)
    y = -read_float(f)
    return [x, y, z]

def read_vertex_pos(f):
    x = read_short_signed(f) / 32767.0
    z = read_short_signed(f) / 32767.0
    y = -read_short_signed(f) / 32767.0
    return [x, y, z]

UV_SANE_LIMIT = 2.0

def read_byte_signed(f):
    v = read_byte(f)
    return v - 256 if v > 127 else v

def read_normal(f):
    x = read_byte_signed(f) / 127.0
    z = read_byte_signed(f) / 127.0
    y = -read_byte_signed(f) / 127.0
    read_byte(f)
    nx, ny, nz = x, y, z
    L = (nx * nx + ny * ny + nz * nz) ** 0.5
    if L > 1e-6:
        nx, ny, nz = nx / L, ny / L, nz / L
    return [nx, ny, nz]

def read_uv_half(f):
    u = read_float16(f)
    v = read_float16(f) * -1.0 + 1.0
    if (u != u or v != v or abs(u) > UV_SANE_LIMIT or abs(v) > UV_SANE_LIMIT):
        return [0.0, 0.0, 0.0]
    return [u, v, 0.0]

def read_matrix(f):
    v = [read_float(f) for _ in range(16)]

    return Matrix((
        (v[0], v[4], v[8],  v[12]),
        (v[1], v[5], v[9],  v[13]),
        (v[2], v[6], v[10], v[14]),
        (v[3], v[7], v[11], v[15]),
    ))

def get_bound(f):
    return [read_float(f), read_float(f), read_float(f), read_float(f)]

def read_header(f):
    h = Header()
    h.BoneCount = read_short(f)
    h.MeshCount = read_short(f)
    h.MatCount = read_short(f)
    h.VertCount = read_long(f)
    h.TriangleCount = read_long(f)
    h.VertexIds = read_long(f)
    h.VertexBufferSize = read_long(f)
    h.Padding = read_long(f)
    h.BoneMapCount = read_long(f)
    h.ptr_Bone = read_long(f)
    h.ptr_BoneMap = read_long(f)
    h.ptr_MatID = read_long(f)
    h.ptr_Mesh = read_long(f)
    h.ptr_vertex = read_long(f)
    h.ptr_triangle = read_long(f)
    h.EndSize = read_long(f)
    return h

def read_bone_info(f):
    info = BoneInfo()
    info.ID = read_byte(f)
    info.Parent = read_byte(f)
    info.Child = read_byte(f)
    info.uk1 = read_byte(f)
    info.Trans = [read_float(f), read_float(f), read_float(f)]
    info.uk2 = read_float(f)
    info.uk3 = read_float(f)
    return info

def read_mesh_header(f):
    m = MeshHeader()
    m.meshtype = read_short(f)
    m.vertCount = read_short(f)
    m.unk01 = read_byte(f)
    m.MatId = read_short(f)
    m.lodLevel = read_byte(f)
    m.unk04 = read_byte(f)
    m.vertFlag = read_byte(f)
    m.vertStride = read_byte(f)
    m.unk05 = read_byte(f)
    m.vertStart = read_long(f)
    m.vertBase = read_long(f)
    m.fvfInfo = read_long(f)
    m.faceStart = read_long(f)
    m.faceCount = read_long(f)
    m.faceBase = read_long(f)
    m.bonemapindex = read_byte(f)
    m.weightmaps = read_byte(f)
    m.unk07 = read_byte(f)
    m.unk08 = read_byte(f)
    m.min_index = read_short(f)
    m.max_index = read_short(f)
    m.unk09 = read_long(f)
    return m

def get_skin_weights(obj, vertex_index):
    bones = []
    weights = []

    mesh = getattr(obj, "data", None)
    verts = getattr(mesh, "vertices", None) if mesh is not None else None
    if verts is not None and 0 <= vertex_index < len(verts):
        for g in verts[vertex_index].groups:
            if g.weight > 0.001:
                bones.append(g.group)
                weights.append(g.weight)

    combined = list(zip(bones, weights))
    combined.sort(key=lambda x: -x[1])

    if combined:
        bones = [b for b, w in combined]
        weights = [w for b, w in combined]
    else:
        bones = [0]
        weights = [1.0]

    return bones, weights

NO_BONE_SENTINEL = 256

def bone_name_for(index):
    if index >= NO_BONE_SENTINEL or index <= 0:
        return "b_root"
    return "b_{}".format(index)

def convert_bone_position(trans):
    x, y, z = trans[0], trans[1], trans[2]
    return Vector((-x, z, -y))

def build_armature(name, bone_infos, world_matrices, bone_lut=None, dequant=None,
                   bbox_min=None, bbox_max=None, mesh_min=None, mesh_max=None):
    arm_data = bpy.data.armatures.new(name)
    arm_obj = bpy.data.objects.new(name, arm_data)
    bpy.context.collection.objects.link(arm_obj)
    arm_obj.show_in_front = True

    count = len(bone_infos)
    if not dequant or dequant <= 1e-9:
        dequant = 1.0

    raw_heads = []
    for i in range(count):
        m = world_matrices[i]

        t = (m[0][3] / dequant, m[1][3] / dequant, m[2][3] / dequant)
        raw_heads.append(convert_bone_position(t))

    heads = list(raw_heads)

    parents = []
    for i, info in enumerate(bone_infos):
        p = info.Parent
        if p is None or p >= 254 or p < 0 or p == i:
            parents.append(-1)
        else:
            parents.append(int(p))

    prev_active = bpy.context.view_layer.objects.active
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode='EDIT')

    edit_bones = []
    for i in range(count):
        eb = arm_data.edit_bones.new(bone_name_for(i + 1))
        eb.head = heads[i]
        eb.tail = heads[i] + Vector((0.0, 0.0, 1e-4))
        edit_bones.append(eb)

    for i in range(count):
        p = parents[i]
        if 0 <= p < count and p != i:
            edit_bones[i].parent = edit_bones[p]

    size = 1.0
    if heads:
        size = max(
            max(h.x for h in heads) - min(h.x for h in heads),
            max(h.y for h in heads) - min(h.y for h in heads),
            max(h.z for h in heads) - min(h.z for h in heads),
        ) or 1.0
    default_len = size * 0.06

    for i in range(count):
        children = [j for j in range(count) if parents[j] == i]
        h = heads[i]
        if len(children) == 1:
            tail = heads[children[0]]
            if (tail - h).length > 1e-6:
                edit_bones[i].tail = tail
                continue
        if children:
            acc = Vector((0.0, 0.0, 0.0))
            for j in children:
                d = heads[j] - h
                if d.length > 1e-6:
                    acc += d.normalized()
            if acc.length > 1e-6:
                L = sum((heads[j] - h).length for j in children) / len(children)
                edit_bones[i].tail = h + acc.normalized() * max(L * 0.6, default_len)
                continue

        p = parents[i]
        if 0 <= p < count:
            d = h - heads[p]
            if d.length > 1e-6:
                edit_bones[i].tail = h + d.normalized() * max(d.length * 0.5, default_len)
                continue
        edit_bones[i].tail = h + Vector((0.0, 0.0, default_len))

    bpy.ops.object.mode_set(mode='OBJECT')

    if prev_active is not None:
        bpy.context.view_layer.objects.active = prev_active

    arm_obj["mt_bone_count"] = count
    if bone_lut:
        arm_obj["mt_bone_lut"] = list(bone_lut[:256])
    return arm_obj

def compute_mesh_scale(world_matrices, bone_count):
    return (1.0, 1.0, 1.0)

def get_dequant_scale(world_matrices, bone_count):
    if bone_count <= 0 or not world_matrices:
        return 1.0
    m = world_matrices[0]
    s = abs(m[0][0])
    if s < 1e-6:
        s = 1.0
    return s

SYM_NAME_MAP_KEY = "MT_BoneNameMap"

def get_armature_bone_name_map(arm_obj):
    if arm_obj is None:
        return {}
    try:
        m = arm_obj.get(SYM_NAME_MAP_KEY)
    except Exception:
        m = None
    if not m:
        return {}
    out = {}
    try:
        for k in m.keys():
            out[str(k)] = int(m[k])
    except Exception:
        return {}
    return out

def get_bone_name_map(scene=None, arm_obj=None):
    if arm_obj is not None:
        m = get_armature_bone_name_map(arm_obj)
        if m:
            return m
    sc = scene or bpy.context.scene
    try:
        m = sc.get(SYM_NAME_MAP_KEY)
    except Exception:
        m = None
    if not m:
        return {}
    out = {}
    try:
        for k in m.keys():
            out[str(k)] = int(m[k])
    except Exception:
        return {}
    return out

VERT_FP_KEY = "mt_vert_fp"

def _q(v, lo, hi):
    i = int(round(v))
    return lo if i < lo else (hi if i > hi else i)

def vertex_normals_file_space(mesh_obj):
    md = getattr(mesh_obj, "data", None)
    if md is None:
        return []
    verts = md.vertices
    n = len(verts)
    out = [Vector((0.0, 0.0, 0.0)) for _ in range(n)]

    got = False
    try:
        from . import compat
        compat.calc_normals_split(md)
    except Exception:
        pass
    try:
        for loop in md.loops:
            ln = loop.normal
            if ln.length_squared > 0.0:
                out[loop.vertex_index] += Vector(ln)
                got = True
    except Exception:
        got = False

    if got:
        for i in range(n):
            v = out[i]
            if v.length_squared < 1e-12:
                out[i] = Vector(verts[i].normal)
            else:
                out[i] = v.normalized()
    else:
        for i in range(n):
            out[i] = Vector(verts[i].normal)

    return [Vector((v.x, v.z, -v.y)) for v in out]

def vertex_tangents_file_space(obj, uv_index=0):
    from mathutils import Vector
    me = obj.data
    if not me.uv_layers or len(me.vertices) == 0:
        return []
    uvl = me.uv_layers[min(uv_index, len(me.uv_layers) - 1)].data

    n_v = len(me.vertices)
    tan = [Vector((0.0, 0.0, 0.0)) for _ in range(n_v)]
    bit = [Vector((0.0, 0.0, 0.0)) for _ in range(n_v)]
    co = [v.co.copy() for v in me.vertices]

    for poly in me.polygons:
        lt = poly.loop_total
        if lt < 3:
            continue
        li = poly.loop_start
        vs = [me.loops[li + k].vertex_index for k in range(lt)]
        uvs = [uvl[li + k].uv for k in range(lt)]
        for k in range(1, lt - 1):
            i0, i1, i2 = vs[0], vs[k], vs[k + 1]
            w0, w1, w2 = uvs[0], uvs[k], uvs[k + 1]
            e1 = co[i1] - co[i0]
            e2 = co[i2] - co[i0]
            d1x, d1y = w1.x - w0.x, w1.y - w0.y
            d2x, d2y = w2.x - w0.x, w2.y - w0.y
            r = d1x * d2y - d2x * d1y
            if abs(r) < 1e-12:
                continue
            r = 1.0 / r
            sdir = (e1 * d2y - e2 * d1y) * r
            tdir = (e2 * d1x - e1 * d2x) * r
            tan[i0] += sdir; bit[i0] += tdir
            tan[i1] += sdir; bit[i1] += tdir
            tan[i2] += sdir; bit[i2] += tdir

    nrm_bl = [v.normal.copy() for v in me.vertices]
    out = []
    for i in range(n_v):
        n = nrm_bl[i]
        t = tan[i]
        if t.length < 1e-9:
            t = Vector((1.0, 0.0, 0.0))
            if abs(n.x) > 0.9:
                t = Vector((0.0, 1.0, 0.0))
        t = t - n * t.dot(n)
        if t.length < 1e-9:
            t = Vector((1.0, 0.0, 0.0))
            if abs(n.x) > 0.9:
                t = Vector((0.0, 1.0, 0.0))
            t = t - n * t.dot(n)
        t.normalize()

        out.append(Vector((t.x, t.z, -t.y)))
    return out

def mesh_vertex_fingerprint(mesh_obj):
    import hashlib
    import struct as _struct

    md = getattr(mesh_obj, "data", None)
    if md is None:
        return None
    h = hashlib.md5()

    try:
        from mathutils import Vector as _V
        _c = get_object_center_offset(mesh_obj)
        _m = mesh_obj.matrix_world
        _d = _m.translation - _V((_c[0], _c[1], _c[2]))

        h.update(_struct.pack("<iii",
                              int(round(_d.x * 10000)),
                              int(round(_d.y * 10000)),
                              int(round(_d.z * 10000))))

        for _r in range(3):
            for _cc in range(3):
                h.update(_struct.pack(
                    "<i", int(round(_m.to_3x3()[_r][_cc] * 100000))))
    except Exception:

        h.update(b"\xffNOXFORM")

    for v in md.vertices:
        co = v.co
        h.update(_struct.pack("<hhh", _q(co.x * 32767, -32767, 32767),
                              _q(co.z * 32767, -32767, 32767),
                              _q(-co.y * 32767, -32767, 32767)))

    for nrm in vertex_normals_file_space(mesh_obj):
        h.update(_struct.pack("<bbb", _q(nrm.x * 127, -127, 127),
                              _q(nrm.y * 127, -127, 127),
                              _q(nrm.z * 127, -127, 127)))

    if md.uv_layers and len(md.loops) and len(md.uv_layers.active.data) >= len(md.loops):
        ul = md.uv_layers.active.data
        first = {}
        for loop in md.loops:
            if loop.vertex_index not in first:
                first[loop.vertex_index] = ul[loop.index].uv
        for i in range(len(md.vertices)):
            uv = first.get(i)
            if uv is None:
                h.update(b"\x00\x00\x00\x00")
            else:
                h.update(_struct.pack("<hh", _q(uv.x * 32767, -32767, 32767),
                                      _q(uv.y * 32767, -32767, 32767)))

    for v in md.vertices:
        ent = sorted((g.group, _q(g.weight * 255, 0, 255))
                     for g in v.groups if g.weight > 0.0)
        h.update(_struct.pack("<H", len(ent)))
        for gi, w in ent:
            h.update(_struct.pack("<HB", min(65535, gi), w))

    return int.from_bytes(h.digest()[:8], "little") & ((1 << 63) - 1)

def remember_vertex_fingerprint(mesh_obj):
    fp = mesh_vertex_fingerprint(mesh_obj)
    if fp is None:
        return None
    text = "%016x" % fp
    try:
        mesh_obj[VERT_FP_KEY] = text
    except Exception as exc:
        print("记录顶点指纹失败: %s" % exc)
    if mesh_obj.get(VERT_FP_KEY) is None:
        print("警告: 顶点指纹没能写入 %s, 导出时会保守地重新编码顶点" % mesh_obj.name)
    return fp

def vertex_data_modified(mesh_obj):
    fp = mesh_vertex_fingerprint(mesh_obj)
    if fp is None:
        return True
    stored = mesh_obj.get(VERT_FP_KEY)
    if stored is not None:
        try:
            return int(str(stored), 16) != fp
        except Exception:
            pass
    stored = mesh_obj.get(VERT_FP_KEY + "_int")
    if stored is not None:
        try:
            return int(stored) != fp
        except Exception:
            pass
    return True

def _bone_index_from_name(name):
    if not name or not name.startswith("b_"):
        return None
    rest = name[2:]
    if rest.isdigit():
        return int(rest) - 1
    return None

def build_mirror_pairs(arm_obj, tol=0.004):
    entries = []
    for b in arm_obj.data.bones:
        idx = _bone_index_from_name(b.name)
        if idx is not None:
            entries.append((idx, b))
    entries.sort(key=lambda e: e[0])
    if not entries:
        return []

    mw = arm_obj.matrix_world
    heads = {idx: (mw @ b.head_local) for idx, b in entries}

    xs = [h.x for h in heads.values()]
    cx = (min(xs) + max(xs)) * 0.5

    pairs = []
    used = set()
    for idx_a, bone_a in entries:
        if idx_a in used:
            continue
        ha = heads[idx_a]
        da = ha.x - cx
        if abs(da) <= tol:
            continue
        partner = None
        for idx_b, bone_b in entries:
            if idx_b == idx_a or idx_b in used:
                continue
            hb = heads[idx_b]
            db = hb.x - cx
            if abs(db) <= tol:
                continue
            if abs(da + db) > tol:
                continue
            if abs(ha.y - hb.y) > tol or abs(ha.z - hb.z) > tol:
                continue
            partner = (idx_b, bone_b)
            break
        if partner is None:
            continue
        idx_b, bone_b = partner
        if da < 0:
            right, left = (idx_a, bone_a), (idx_b, bone_b)
        else:
            right, left = (idx_b, bone_b), (idx_a, bone_a)

        base = "b_%d" % (min(idx_a, idx_b) + 1)
        pairs.append((right[1].name, left[1].name, base))
        used.add(idx_a)
        used.add(idx_b)
    return pairs

def apply_symmetric_bone_names(arm_obj, mesh_objs, scene=None, tol=0.004):
    scene = scene or bpy.context.scene
    pairs = build_mirror_pairs(arm_obj, tol)
    if not pairs:
        return 0, {}

    ren = {}
    for rname, lname, base in pairs:
        ren[rname] = base + ".r"
        ren[lname] = base + ".l"

    prev = bpy.context.view_layer.objects.active
    try:
        bpy.context.view_layer.objects.active = arm_obj
        bpy.ops.object.mode_set(mode='EDIT')
        ebs = arm_obj.data.edit_bones
        for old, new in ren.items():
            eb = ebs.get(old)
            if eb is not None:
                eb.name = new
        bpy.ops.object.mode_set(mode='OBJECT')
    finally:
        if prev is not None:
            bpy.context.view_layer.objects.active = prev

    for obj in mesh_objs:
        if obj is None or obj.type != 'MESH':
            continue
        for old, new in ren.items():
            vg = obj.vertex_groups.get(old)
            if vg is not None:
                vg.name = new

    name_map = {}
    for b in arm_obj.data.bones:
        idx = _bone_index_from_name(b.name)
        if idx is None:
            for old, new in ren.items():
                if new == b.name:
                    idx = _bone_index_from_name(old)
                    break
        if idx is not None:
            name_map[b.name] = idx
    try:
        scene[SYM_NAME_MAP_KEY] = name_map
    except Exception:
        pass

    try:
        arm_obj[SYM_NAME_MAP_KEY] = dict(name_map)
    except Exception:
        pass
    return len(pairs), name_map

def _deprecated_get_bone_name_map(scene=None):
    return get_bone_name_map(scene)

CENTER_NONE = 'NONE'
CENTER_XY_GROUND = 'XY_GROUND'
CENTER_ALL = 'CENTER'

def compute_world_bounds(objects):
    mn = None
    mx = None
    for obj in objects:
        if obj is None or obj.type != 'MESH':
            continue
        mw = obj.matrix_world
        for v in obj.data.vertices:
            p = mw @ v.co
            if mn is None:
                mn = Vector((p.x, p.y, p.z))
                mx = Vector((p.x, p.y, p.z))
            else:
                if p.x < mn.x: mn.x = p.x
                if p.y < mn.y: mn.y = p.y
                if p.z < mn.z: mn.z = p.z
                if p.x > mx.x: mx.x = p.x
                if p.y > mx.y: mx.y = p.y
                if p.z > mx.z: mx.z = p.z
    return mn, mx

def centering_offset(mn, mx, mode):
    if mn is None or mx is None or mode == CENTER_NONE:
        return Vector((0.0, 0.0, 0.0))
    cx = (mn.x + mx.x) * 0.5
    cy = (mn.y + mx.y) * 0.5
    cz = (mn.z + mx.z) * 0.5
    if mode == CENTER_XY_GROUND:

        return Vector((-cx, -cy, -mn.z))
    if mode == CENTER_ALL:
        return Vector((-cx, -cy, -cz))
    return Vector((0.0, 0.0, 0.0))

def center_objects(objects, mode=CENTER_XY_GROUND):
    objs = [o for o in objects if o is not None]
    if not objs or mode == CENTER_NONE:
        return Vector((0.0, 0.0, 0.0))

    mn, mx = compute_world_bounds(objs)
    offset = centering_offset(mn, mx, mode)
    if offset.length < 1e-12:
        return offset

    group = set(objs)
    roots = [o for o in objs if o.parent is None or o.parent not in group]
    if not roots:
        roots = objs
    for obj in roots:
        obj.matrix_world = Matrix.Translation(offset) @ obj.matrix_world

    try:
        bpy.context.view_layer.update()
    except Exception:
        pass

    for obj in objs:
        try:
            _raw = obj.get(CENTER_OFFSET_OBJ_KEY)
            if _raw:
                prev = Vector((float(_raw[0]), float(_raw[1]), float(_raw[2])))
            else:
                prev = Vector((0.0, 0.0, 0.0))
            obj[CENTER_OFFSET_OBJ_KEY] = [float(prev[0] + offset[0]),
                                          float(prev[1] + offset[1]),
                                          float(prev[2] + offset[2])]
        except Exception:
            pass
    add_center_offset(offset)
    return offset

CENTER_OFFSET_KEY = "MT_CenterOffset"

CENTER_OFFSET_OBJ_KEY = "MT_CenterOffsetObj"

def get_object_center_offset(obj, scene=None):
    sc = scene or bpy.context.scene
    try:
        v = obj.get(CENTER_OFFSET_OBJ_KEY)
    except Exception:
        v = None
    if v:
        try:
            return Vector((float(v[0]), float(v[1]), float(v[2])))
        except Exception:
            pass
    return get_center_offset(sc)

def get_center_offset(scene=None):
    sc = scene or bpy.context.scene
    try:
        v = sc.get(CENTER_OFFSET_KEY)
    except Exception:
        v = None
    if not v:
        return Vector((0.0, 0.0, 0.0))
    try:
        return Vector((float(v[0]), float(v[1]), float(v[2])))
    except Exception:
        return Vector((0.0, 0.0, 0.0))

def set_center_offset(vec, scene=None):
    sc = scene or bpy.context.scene
    try:
        sc[CENTER_OFFSET_KEY] = [float(vec[0]), float(vec[1]), float(vec[2])]
        return True
    except Exception:
        return False

def add_center_offset(vec, scene=None):
    return set_center_offset(get_center_offset(scene) + Vector(vec), scene)

def register():
    from . import MTframework_MHGU_ui
    MTframework_MHGU_ui.register()
    from . import MTframework_MMD
    MTframework_MMD.register()

    try:
        from . import MTframework_MHGU_matcheck
        MTframework_MHGU_matcheck.register()
    except Exception as _e:
        print("NOTE: 材质名检查未启用 (%s)" % _e)
    try:
        from . import MTframework_MHGU_helmd
        MTframework_MHGU_helmd.register()
    except Exception as _e:
        print("NOTE: 头盔显示开关未启用 (%s)" % _e)
    try:
        from . import MTframework_MHGU_physparams
        MTframework_MHGU_physparams.register()
    except Exception as _e:
        print("NOTE: 物理参数编辑未启用 (%s)" % _e)
    try:
        from . import MTframework_MHGU_physmat
        MTframework_MHGU_physmat.register()
    except Exception as _e:
        print("NOTE: 物理矩阵自适应未启用 (%s)" % _e)
    try:
        from . import MTframework_MHGU_physcustom
        MTframework_MHGU_physcustom.register()
    except Exception as _e:
        print("NOTE: 自定义物理骨未启用 (%s)" % _e)
    try:
        from . import MTframework_MHGU_phys
        MTframework_MHGU_phys.register()
    except Exception as _e:
        print("NOTE: .arc/物理模块未启用 (%s)" % _e)
    try:
        from . import MTframework_MHGU_tpl
        MTframework_MHGU_tpl.register()
    except Exception as _e:
        print("NOTE: 模板自愈未启用 (%s)" % _e)
    try:
        from . import MTframework_MHGU_tex
        MTframework_MHGU_tex.register()
    except Exception as _e:
        print("NOTE: .tex 贴图模块未启用 (%s)" % _e)

def unregister():
    try:
        from . import MTframework_MHGU_matcheck
        MTframework_MHGU_matcheck.unregister()
    except Exception:
        pass
    try:
        from . import MTframework_MHGU_helmd
        MTframework_MHGU_helmd.unregister()
    except Exception:
        pass
    try:
        from . import MTframework_MHGU_physparams
        MTframework_MHGU_physparams.unregister()
    except Exception:
        pass
    try:
        from . import MTframework_MHGU_physmat
        MTframework_MHGU_physmat.unregister()
    except Exception:
        pass
    try:
        from . import MTframework_MHGU_physcustom
        MTframework_MHGU_physcustom.unregister()
    except Exception:
        pass
    try:
        from . import MTframework_MHGU_phys
        MTframework_MHGU_phys.unregister()
    except Exception:
        pass
    try:
        from . import MTframework_MHGU_tex
        MTframework_MHGU_tex.unregister()
    except Exception:
        pass
    try:
        from . import MTframework_MHGU_tpl
        MTframework_MHGU_tpl.unregister()
    except Exception:
        pass
    from . import MTframework_MMD
    MTframework_MMD.unregister()
    from . import MTframework_MHGU_ui
    MTframework_MHGU_ui.unregister()

if __name__ == "__main__":
    register()
