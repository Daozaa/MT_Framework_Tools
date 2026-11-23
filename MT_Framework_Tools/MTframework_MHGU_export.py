import bpy, os, struct
from mathutils import Vector
from io import BytesIO
from .Mod import MODHeader, MeshHeaderStruct
from .MTframework_MHGU import (get_skin_weights, float_to_short,
                               get_center_offset, get_object_center_offset,
                               get_bone_name_map,
                               vertex_data_modified, remember_vertex_fingerprint,
                               vertex_normals_file_space, vertex_tangents_file_space)

_SINGLE_BONE_FVF = {0xB0983013, 0xB0983014, 0xA8FAB018, 0xA8FAB019,
                    0x0CB6800E, 0x0CB68015, 0x0CB68016}

def _bone_no_from_name(name):
    if not name or not name.startswith('b_'):
        return None
    rest = name[2:]
    if '.' in rest:
        rest = rest.split('.', 1)[0]
    if not rest.isdigit():
        return None
    return int(rest) - 1

def _arm_of(obj):
    try:
        for m in obj.modifiers:
            if m.type == 'ARMATURE' and m.object is not None:
                return m.object
    except Exception:
        pass
    return None

def _build_bone_map(obj, n_bones=0):
    bm = {}; es = {}
    name_map = {}
    try:

        name_map = get_bone_name_map(bpy.context.scene, _arm_of(obj))
    except Exception:
        name_map = {}
    for o in bpy.data.objects:
        if o.type == 'EMPTY' and o.name.startswith('b_'):
            try:
                _bn = _bone_no_from_name(o.name)
                if _bn is not None:
                    es[o.name] = _bn
            except Exception:
                pass
    skipped = []
    for vg in obj.vertex_groups:
        idx = None
        if vg.name in name_map:
            idx = name_map[vg.name]
        elif vg.name in es:
            idx = es[vg.name]
        else:
            try:
                idx = _bone_no_from_name(vg.name)
            except Exception:
                idx = None
        if idx is None:
            skipped.append(vg.name)
            continue
        if n_bones and not (0 <= idx < n_bones):
            skipped.append('%s（序号 %d 越界）' % (vg.name, idx))
            continue
        bm[vg.index] = idx
    if skipped:
        print("NOTE: 以下顶点组对不上骨架骨骼，导出时**跳过、不写权重**：%s"
              % ', '.join(skipped[:10]) + (' …' if len(skipped) > 10 else ''))
    return bm

def _short_pos(p):
    return (max(-32767, min(32767, int(p.x*32767))),
            max(-32767, min(32767, int(p.y*32767))),
            max(-32767, min(32767, int(p.z*32767))))

def _norm_byte(v):

    return max(-127, min(127, int(round(v * 127)))) & 0xFF

def _weight_byte(w): return max(0, min(255, int(w*255)))
def _weight_short(w): return max(-32767, min(32767, int(w*32767)))

def _pad4(b): return [b[0], b[1] if len(b)>1 else b[0], b[2] if len(b)>2 else b[0], b[3] if len(b)>3 else b[0]]
def _pad4w(w): return [w[0], w[1] if len(w)>1 else 0.0, w[2] if len(w)>2 else 0.0, w[3] if len(w)>3 else 0.0]

def _write_vbuf(fvf, vc, gp, gu, gn, gt, gsk, stride=24):
    buf = bytearray(); h = float_to_short
    _is_short_pos = fvf not in (0xA7D7D036, 0x207D6037, 0xD1A47038, 0xD8297028,
                                0xC66FA03A, 0x5E7F202C, 0x49B4F029, 0x63B6C02F,
                                0x747D1031, 0x9399C033, 0xB86DE02A, 0x12553032, 0x926FD02E)
    for c in range(vc):
        p = gp(c); u = gu(c); n = gn(c); t = gt(c)
        nb = Vector((_norm_byte(n.x), _norm_byte(n.y), _norm_byte(n.z)))
        tb = Vector((_norm_byte(t.x), _norm_byte(t.y), _norm_byte(t.z)))
        b,w = gsk(c)
        start = len(buf)

        if _is_short_pos:
            cx, cy, cz = _short_pos(p)
        else:
            fx, fy, fz = p.x, p.y, p.z

        if fvf in (0xB0983013, 0xB0983014):
            cx,cy,cz = _short_pos(p)
            ux = max(0.0, min(1.0, u.x))
            uy = max(0.0, min(1.0, u.y))
            buf += struct.pack('<hhh', cx, cy, cz)
            buf += struct.pack('<BB', b[0], _weight_byte(w[0]))
            buf += struct.pack('<HH', int(ux*65535+0.5), int(uy*65535+0.5))

        elif fvf in (0xDB7DA014,0xDB7DA015):
            cx,cy,cz = _short_pos(p)
            buf += struct.pack('<hhh', cx, cy, cz)
            buf += struct.pack('<H',26470)
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),254)
            buf += struct.pack('<HH',h(u.x),h(u.y))
        elif fvf in (0xB6681034,):
            cx,cy,cz = _short_pos(p)
            buf += struct.pack('<hhh', cx, cy, cz)
            buf += b'\x00\x00\x00\x00\x00\x00'
            buf += struct.pack('<HH',h(u.x),h(u.y))

        elif fvf in (0xC66FA03E,):
            cx,cy,cz = _short_pos(p)
            buf += struct.pack('<hhh', cx, cy, cz)
            buf += struct.pack('<I',0)
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('<HH',h(u.x),h(u.y))

        elif fvf in (0xA8FAB018,0xA8FAB019,0x0CB6800E,0x0CB68015,0x0CB68016):
            cx,cy,cz = _short_pos(p)
            buf += struct.pack('<hhh', cx, cy, cz)

            buf += struct.pack('<BB', b[0], 0)
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),127)
            buf += struct.pack('BBBB',_norm_byte(t.x),_norm_byte(t.y),_norm_byte(t.z),127)
            buf += struct.pack('<HH',h(u.x),h(u.y))

        elif fvf in (0xA7D7D036,):
            ux = max(0.0, min(1.0, u.x))
            uy = max(0.0, min(1.0, u.y))
            buf += struct.pack('<fff', fx, fy, fz)
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),0)
            buf += struct.pack('<HH', int(ux*65535+0.5), int(uy*65535+0.5))

        elif fvf in (0xAFA63031,):
            cx,cy,cz = _short_pos(p)
            buf += struct.pack('<hhh', cx, cy, cz)
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),0)
            buf += struct.pack('<I',0)
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('<HH',h(u.x),h(u.y))

        elif fvf in (0xC31F201C,0xC31F201D):
            cx,cy,cz = _short_pos(p)
            buf += struct.pack('<hhh', cx, cy, cz)
            buf += struct.pack('<h', _weight_short(w[0]))
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),127)
            buf += struct.pack('BBBB',_norm_byte(t.x),_norm_byte(t.y),_norm_byte(t.z),127)
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('<HH',h(float(b[0])),h(float(b[1]) if len(b)>1 else float(b[0])))

        elif fvf in (0xCBF6C01A,):
            cx,cy,cz = _short_pos(p)
            buf += struct.pack('<hhh', cx, cy, cz)
            buf += struct.pack('<BB', _weight_byte(w[0]), b[0])
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),127)
            buf += struct.pack('BBBB',_norm_byte(t.x),_norm_byte(t.y),_norm_byte(t.z),127)
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('<BBBB',255,255,255,255)

        elif fvf in (0x207D6037,):
            buf += struct.pack('<fff', fx, fy, fz)
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),0)
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('<BBBB',255,255,255,255)
        elif fvf in (0xD1A47038, 0xC66FA03A):
            buf += struct.pack('<fff', fx, fy, fz)
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),0)
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('<HH',h(u.x),h(u.y))
        elif fvf in (0xD8297028,):
            buf += struct.pack('<fff', fx, fy, fz)
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),0)
            buf += struct.pack('<BBBB',255,255,255,255)
            buf += struct.pack('<HH',h(u.x),h(u.y))

        elif fvf in (0x9399C037,):
            cx,cy,cz = _short_pos(p)
            buf += struct.pack('<hhh', cx, cy, cz)
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),0)
            buf += struct.pack('<I',0)
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('<BBBB',255,255,255,255)

        elif fvf in (0x5E7F202C, 0x49B4F029):
            buf += struct.pack('<fff', fx, fy, fz)
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),0)
            buf += struct.pack('BBBB',_norm_byte(t.x),_norm_byte(t.y),_norm_byte(t.z),0)
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('<HH',h(u.x),h(u.y))

        elif fvf in (0x14D40019,0x14D40020,0x14D40021,0x14D40022):
            cx,cy,cz = _short_pos(p)
            _b4 = _pad4(b); _w2 = _pad4w(w)
            buf += struct.pack('<hhh', cx, cy, cz)
            buf += struct.pack('<h', _weight_short(_w2[0]))
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),127)
            buf += struct.pack('BBBB',_norm_byte(t.x),_norm_byte(t.y),_norm_byte(t.z),127)
            buf += struct.pack('BBBB', _b4[0], _b4[1], _b4[2], _b4[3])
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('<HH',h(float(_w2[1])),h(float(_w2[2])))

        elif fvf in (0xA013501E,):
            cx,cy,cz = _short_pos(p)
            buf += struct.pack('<hhh', cx, cy, cz)
            buf += struct.pack('<h', _weight_short(w[0]))
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),127)
            buf += struct.pack('BBBB',_norm_byte(t.x),_norm_byte(t.y),_norm_byte(t.z),127)
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('<HH',h(float(b[0])),h(float(b[1]) if len(b)>1 else float(b[0])))
            buf += struct.pack('<BBBB',255,255,255,255)

        elif fvf in (0x2BE814D4,0x7CD414D4,0x0D9E801D):
            cx,cy,cz = _short_pos(p)
            buf += struct.pack('<hhh', cx, cy, cz)
            buf += b'\x00' * 22

        elif fvf in (0xA320C016,0xA320C017):
            cx,cy,cz = _short_pos(p)
            buf += struct.pack('<hhh', cx, cy, cz)
            buf += struct.pack('<H',0)
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),127)
            buf += struct.pack('BBBB',_norm_byte(t.x),_norm_byte(t.y),_norm_byte(t.z),127)
            _bn = t.cross(n); _bn.normalize()
            buf += struct.pack('BBBB',_norm_byte(_bn.x),_norm_byte(_bn.y),_norm_byte(_bn.z),127)
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('<HH',h(u.x),h(u.y))

        elif fvf in (0xD877801B,):
            cx,cy,cz = _short_pos(p)
            buf += struct.pack('<hhh', cx, cy, cz)

            buf += struct.pack('<BB', b[0], 0)
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),127)
            buf += struct.pack('BBBB',_norm_byte(t.x),_norm_byte(t.y),_norm_byte(t.z),127)
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += b'\x00\x00\x00\x00'
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += b'\x00\x00\x00\x00'

        elif fvf in (0xDA55A021,):
            cx,cy,cz = _short_pos(p)
            _b4 = _pad4(b); _w4 = _pad4w(w)
            buf += struct.pack('<hhh', cx, cy, cz)
            buf += struct.pack('<H',0)
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),127)
            buf += struct.pack('BBBB',_norm_byte(t.x),_norm_byte(t.y),_norm_byte(t.z),127)
            buf += struct.pack('BBBB', _b4[0], _b4[1], _b4[2], _b4[3])
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('BBBB', _weight_byte(_w4[0]), _weight_byte(_w4[1]),
                                _weight_byte(_w4[2]), _weight_byte(_w4[3]))
            buf += struct.pack('<HH',h(u.x),h(u.y))

        elif fvf in (0x747D1031,0x9399C033,0xB86DE02A,0x12553032,0x926FD02E):
            buf += struct.pack('<fff', fx, fy, fz)
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),0)
            buf += struct.pack('BBBB',_norm_byte(t.x),_norm_byte(t.y),_norm_byte(t.z),0)
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('<BBBB',255,255,255,255)

        elif fvf in (0xA14E003C,):
            cx,cy,cz = _short_pos(p)
            buf += struct.pack('<hhh', cx, cy, cz)
            buf += b'\x00' * 26

        elif fvf in (0xB3921020,):
            cx,cy,cz = _short_pos(p)
            buf += struct.pack('<hhh', cx, cy, cz)
            buf += struct.pack('<h', _weight_short(w[0]))
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),127)
            buf += struct.pack('<I',0)
            buf += struct.pack('<HH',h(float(b[0])),h(float(b[1]) if len(b)>1 else float(b[0])))
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += b'\x00' * 8

        elif fvf in (0xBB424024,0xBB424025):
            cx,cy,cz = _short_pos(p)
            _b8 = [b[i] if i<len(b) else b[0] for i in range(8)]
            _w8 = [w[i] if i<len(w) else 0.0 for i in range(8)]
            buf += struct.pack('<hhh', cx, cy, cz)
            buf += struct.pack('<h', _weight_short(_w8[0]))
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),127)
            buf += struct.pack('BBBB',_weight_byte(_w8[1]),_weight_byte(_w8[2]),_weight_byte(_w8[3]),_weight_byte(_w8[4]))
            buf += struct.pack('BBBBBBBB', _b8[0],_b8[1],_b8[2],_b8[3],_b8[4],_b8[5],_b8[6],_b8[7])
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('<HH',h(float(_w8[5])),h(float(_w8[6])))
            buf += struct.pack('BBBB',_norm_byte(t.x),_norm_byte(t.y),_norm_byte(t.z),127)

        elif fvf in (0x63B6C02F,):
            buf += struct.pack('<fff', fx, fy, fz)
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),0)
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += b'\x00' * 12

        elif fvf in (0xB392101F,):
            cx,cy,cz = _short_pos(p)
            buf += struct.pack('<hhh', cx, cy, cz)
            buf += struct.pack('<H',0)
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),127)
            buf += struct.pack('BBBB',_norm_byte(t.x),_norm_byte(t.y),_norm_byte(t.z),127)
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += b'\x00' * 12

        elif fvf in (0x64593025, 0x64593023):
            cx,cy,cz = _short_pos(p)
            _b4 = _pad4(b); _w4 = _pad4w(w)
            buf += struct.pack('<hhh', cx, cy, cz)
            buf += struct.pack('<h', _weight_short(_w4[0]))
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),127)
            buf += struct.pack('BBBB',_norm_byte(t.x),_norm_byte(t.y),_norm_byte(t.z),127)
            buf += struct.pack('BBBB', _b4[0], _b4[1], _b4[2], _b4[3])
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('<HH',h(float(_w4[1])),h(float(_w4[2])))
            buf += b'\x00\x00\x00\x00'
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += b'\x00\x00\x00\x00'

        elif fvf in (0x75C3E025, 0xD84E3026):
            cx,cy,cz = _short_pos(p)
            buf += struct.pack('<hhh', cx, cy, cz)
            buf += b'\x00' * 14
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += b'\x00' * 16

        elif fvf in (0xCBCF7027,):
            cx,cy,cz = _short_pos(p)
            _b8 = [b[i] if i<len(b) else b[0] for i in range(8)]
            _w8 = [w[i] if i<len(w) else 0.0 for i in range(8)]
            buf += struct.pack('<hhh', cx, cy, cz)
            buf += struct.pack('<h', _weight_short(_w8[0]))
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),127)
            buf += struct.pack('BBBB',_weight_byte(_w8[1]),_weight_byte(_w8[2]),_weight_byte(_w8[3]),_weight_byte(_w8[4]))
            buf += struct.pack('BBBBBBBB', _b8[0],_b8[1],_b8[2],_b8[3],_b8[4],_b8[5],_b8[6],_b8[7])
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('<HH',h(float(_w8[5])),h(float(_w8[6])))
            buf += struct.pack('BBBB',_norm_byte(t.x),_norm_byte(t.y),_norm_byte(t.z),127)
            buf += b'\x00\x00\x00\x00'
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += b'\x00\x00\x00\x00'

        elif fvf in (0x2F55C03D,):
            cx,cy,cz = _short_pos(p)
            _b4 = _pad4(b); _w4 = _pad4w(w)
            buf += struct.pack('<hhh', cx, cy, cz)
            buf += struct.pack('<h', _weight_short(_w4[0]))
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),0)
            buf += struct.pack('BBBB',_norm_byte(t.x),_norm_byte(t.y),_norm_byte(t.z),0)
            buf += struct.pack('BBBB', _b4[0], _b4[1], _b4[2], _b4[3])
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('<HH',h(float(_w4[1])),h(float(_w4[2])))
            buf += b'\x00' * 40

        elif fvf in (0x667B1019,):
            cx,cy,cz = _short_pos(p)
            buf += struct.pack('<hhh', cx, cy, cz)
            buf += b'\x00' * 10
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('<HH',h(u.x),h(u.y))

        else:
            buf += b'\x00' * stride

        pad = stride - (len(buf) - start)
        if pad > 0: buf += b'\x00' * pad
    return bytes(buf)

def _detect_mod_format(filepath):
    try:
        with open(filepath, 'rb') as f:
            magic = f.read(4)
            if magic != b'MOD\x00':
                return None
            ver = struct.unpack('<H', f.read(2))[0]
            if ver in (0xe5, 0xe6):
                return None

            return 'mhgu'
    except Exception:
        return None

def split_hidden_meshes(objs):
    keep, hidden = [], []
    for o in objs:
        try:
            hid = bool(o.hide_get())
        except Exception:
            hid = False
        if hid or bool(o.hide_viewport):
            hidden.append(o)
        else:
            keep.append(o)
    return keep, hidden

def _mesh_triangles(mesh, loop_vertices):
    for poly in mesh.polygons:
        indices = (tuple(loop_vertices[i] for i in poly.loop_indices)
                   if loop_vertices is not None else poly.vertices)
        for i in range(1, len(indices) - 1):
            yield indices[0], indices[i], indices[i + 1]

def _mesh_parts(mesh, loop_vertices, vertices, stride, count):
    triangles = _mesh_triangles(mesh, loop_vertices)
    if count <= 0xFFFF:
        yield vertices, count, triangles
        return
    remap = {}
    buffer = bytearray()
    faces = []
    for tri in triangles:
        missing = [v for v in dict.fromkeys(tri) if v not in remap]
        if len(remap) + len(missing) > 0xFFFF:
            yield buffer, len(remap), faces
            remap, buffer, faces = {}, bytearray(), []
            missing = dict.fromkeys(tri)
        for v in missing:
            remap[v] = len(remap)
            at = v * stride
            buffer.extend(vertices[at:at + stride])
        faces.append(tuple(remap[v] for v in tri))
    if faces:
        yield buffer, len(remap), faces

def export_mod_file(filepath, game_fix="mhgu", template_path=None, *, expect_atlas_uv=False,
                    report=None):
    if filepath and not filepath.endswith(".new"):
        filepath = filepath + ".new"

    _synced = None
    try:
        from .MTframework_MHGU_tpl import sync as _tpl_sync
        _synced = _tpl_sync(bpy.context)
    except Exception:
        pass
    from .MTframework_MHGU_import import _last_import_path
    sv = bpy.context.scene.get('MT_LastImportPath', None)

    cand = [p for p in [template_path, _synced, sv, _last_import_path]
            if p and os.path.exists(p)]

    cand = [p for p in cand if not p.endswith(".new")]
    src = cand[0] if cand else (filepath if os.path.exists(filepath) else None)
    if not src:
        print("ERROR: No template")
        return None

    fmt = _detect_mod_format(src)
    if fmt is None:
        print("ERROR: 不支持的 .mod 版本 (本插件只支持 MHGU / Switch)")
        return None

    with open(src, 'rb') as f:
        data = bytearray(f.read())

        _tpl_bytes = bytes(data)
    hdr = MODHeader(); hdr.marshall(BytesIO(data[6:6+58]))

    remapped_slots = any(o.type == 'ARMATURE' and o.get('MT_PhysBridgeReslot')
                         and len(o.data.bones) == hdr.boneCount for o in bpy.context.scene.objects)

    headers = []
    for i in range(hdr.meshCount):
        off = hdr.ptr_Mesh + i*48
        mh = MeshHeaderStruct(); mh.marshall(BytesIO(data[off:off+48]))
        headers.append(mh)

    sel = [o for o in bpy.context.selected_objects if o.type == 'MESH']

    _hidden_skipped = []
    if bool(getattr(bpy.context.scene, 'MT_SkipHidden', False)):
        sel, _hidden = split_hidden_meshes(sel)
        _hidden_skipped = [o.name for o in _hidden]
        if _hidden_skipped:
            print('NOTE: 导出跳过 %d 个视口隐藏的网格：%s'
                  % (len(_hidden_skipped), '、'.join(_hidden_skipped)))

    try:
        _arms0 = [o for o in bpy.context.scene.objects if o.type == 'ARMATURE']
        if _arms0 and sel:

            _gnames = set()
            for _o in sel:
                _gnames.update(g.name for g in _o.vertex_groups)
            _best = None
            _best_hit = -1
            for _a0 in _arms0:
                _hit = len({b.name for b in _a0.data.bones} & _gnames)
                if _hit > _best_hit:
                    _best, _best_hit = _a0, _hit
            _bones0 = {b.name for b in _best.data.bones}
            _tot_w = 0.0
            _non_w = 0.0
            _non_n = set()
            for _o in sel:
                _gn = [g.name for g in _o.vertex_groups]
                for _v in _o.data.vertices:
                    for _g in _v.groups:
                        if _g.weight <= 1e-5:
                            continue
                        _tot_w += _g.weight
                        if _gn[_g.group] not in _bones0:
                            _non_w += _g.weight
                            _non_n.add(_gn[_g.group])
            if _non_w > 0.0 and _tot_w > 0.0:
                _keep = _tot_w - _non_w
                print('NOTE: %d 个非骨骼顶点组承载 %.1f%% 的权重（%s）→ 导出丢弃后，'
                      '骨骼权重会归一化放大约 %.2f 倍（比例不变，游戏内变形不变）'
                      % (len(_non_n), _non_w * 100.0 / _tot_w,
                         '、'.join(sorted(_non_n)[:4]),
                         (_tot_w / _keep) if _keep > 1e-6 else 0.0))
    except Exception as _e_wd:
        print('NOTE: 权重/分件诊断跳过 (%s)' % _e_wd)

    if not sel:
        if _hidden_skipped:
            print('NOTE: 选中的网格全是隐藏的（已跳过）→ 导出空模型（0 分件）')
        else:
            _all = [o.name for o in bpy.context.selected_objects]
            print('NOTE: 没有选中网格 → 导出空模型（0 分件）。当前选中：%s'
                  % ('、'.join(_all) if _all else '无'))

    def sn(n):
        p = n.split('_')
        if len(p)>=2:
            try: return int(p[1])-1
            except: pass
        return -1
    sm = {}
    for o in sel:
        k = sn(o.name)
        if k < 0 or len(o.data.vertices) == 0:
            continue
        prev = sm.get(k)
        if prev is None:
            sm[k] = o
        elif prev.name.endswith("_OLD") and not o.name.endswith("_OLD"):

            sm[k] = o

    _auto = [o for o in sel
             if sn(o.name) < 0 and len(o.data.vertices) > 0
             and not o.name.endswith("_OLD")]
    if _auto:
        _free = [i for i in range(len(headers)) if i not in sm]
        _free.sort(key=lambda i: (0 if int(getattr(headers[i], "meshtype", 0)) == 0xEFFF
                                  else 1, i))
        for _o in sorted(_auto, key=lambda x: x.name):
            if not _free:
                print("WARNING: 模板分件槽已占满（%d 个），忽略「%s」"
                      % (len(headers), _o.name))
                continue
            _k = _free.pop(0)
            sm[_k] = _o
            _mt = int(getattr(headers[_k], "meshtype", 0))
            print("NOTE: 「%s」名字里没有 Mesh_NNN 序号 → 自动放进分件 %d（第 %d 槽，"
                  "meshtype=0x%04X）%s"
                  % (_o.name, _k, _k + 1, _mt,
                     "" if _mt == 0xEFFF else
                     " —— 该槽是影子/低模件不会显示，要显示请勾选「所有分件都当可见件」"))

    if not sm and sel:
        print('NOTE: 选中的网格都被跳过了（名字以 _OLD 结尾 / 没有顶点 / 没有分件槽可用）'
              ' → 导出空模型')

    if expect_atlas_uv:
        dropped = [o.name for o in sel if o.data.polygons and o not in sm.values()]
        if not sm or dropped:
            raise ValueError('有图集网格没有分件槽：' + ('、'.join(dropped) or '没有可导出的网格'))

    new_vert = bytearray()
    new_face = bytearray()
    rb = 0; rf = 0
    _skipped_visible = []
    new_headers_list = []

    _extra = [k for k in sorted(sm.keys()) if k >= len(headers)]
    if _extra:
        print("NOTE: 这些网格的序号超出模板分件数 (%d), 将套用最大的分件头: %s"
              % (len(headers), [sm[k].name for k in _extra]))

    for i in sorted(sm.keys()):
        obj = sm[i]
        if i < len(headers):
            _tpl = headers[i]
        else:

            _tpl = max(headers, key=lambda h: h.vertCount)
            print("WARNING: 网格序号 %d 超出模板 (%d 个分件头), 克隆 FVF=0x%08X"
                  % (i, len(headers), _tpl.fvfInfo))
        vs = _tpl.vertStride; fvf = _tpl.fvfInfo

        md = obj.data; vc = len(md.vertices)

        _seam_split = False
        _split = list(range(vc))
        _split_uv = None
        _loop_vert = None
        _ul = md.uv_layers.active.data if md.uv_layers else None
        if _ul is not None and len(_ul) == len(md.loops) and md.loops:
            _per = {}
            for _lp in md.loops:
                _u0 = _ul[_lp.index].uv
                _s = _per.setdefault(_lp.vertex_index, set())
                _s.add((round(_u0.x, 6), round(_u0.y, 6)))
            if any(len(s) > 1 for s in _per.values()):
                _seam_split = True
                _key2idx = {}
                _split = []
                _split_uv = []
                _loop_vert = {}
                for _lp in md.loops:
                    _u0 = _ul[_lp.index].uv
                    _k = (_lp.vertex_index, round(_u0.x, 6), round(_u0.y, 6))
                    _idx = _key2idx.get(_k)
                    if _idx is None:
                        _idx = len(_split)
                        _key2idx[_k] = _idx
                        _split.append(_lp.vertex_index)
                        _split_uv.append((_u0.x, 1.0 - _u0.y))
                    _loop_vert[_lp.index] = _idx
                print("UV 接缝拆点: %d 顶点 -> %d 顶点 (%d 个接缝顶点)"
                      % (vc, len(_split),
                         sum(1 for s in _per.values() if len(s) > 1)))
        _vc_out = len(_split)

        _use_orig = False
        try: _use_orig = bpy.context.scene.MT_Framework_Props.use_orig_vert
        except: pass
        _known_fvfs = {0x9399C037,0xAFA63031,0xC66FA03E,0xB3921020,0x64593025,
                       0xB0983013,0xB0983014,0xDB7DA014,0xDB7DA015,0xB6681034,
                       0x0CB6800E,0x0CB68015,0x0CB68016,0xA8FAB018,0xA8FAB019,
                       0xA7D7D036,0xC31F201C,0xC31F201D,0xCBF6C01A,0x207D6037,
                       0xD1A47038,0xD8297028,0xC66FA03A,0x667B1019,
                       0x14D40019,0x14D40020,0x14D40021,0x14D40022,
                       0x5E7F202C,0x2BE814D4,0x7CD414D4,0xA320C016,0xA320C017,
                       0x49B4F029,0x0D9E801D,0xA013501E,0xD877801B,
                       0x747D1031,0x9399C033,0xB86DE02A,0x12553032,0x926FD02E,
                       0xA14E003C,0xDA55A021,0xB392101F,0xBB424024,0xBB424025,
                       0x63B6C02F,0x64593023,0x75C3E025,0xD84E3026,0xCBCF7027,
                       0x2F55C03D}

        _changed = vertex_data_modified(obj)
        _can_reencode = fvf in _known_fvfs
        if expect_atlas_uv and (_use_orig or not _can_reencode):
            cause = '已开启「使用原版顶点」' if _use_orig else 'FVF 0x%08X 无法重编码' % fvf
            raise ValueError('「%s」无法写入图集 UV：%s' % (obj.name, cause))
        if remapped_slots and (_use_orig or not _can_reencode):
            cause = '请关闭「使用原版顶点」' if _use_orig else 'FVF 0x%08X 无法重新写入骨索引' % fvf
            raise ValueError('「%s」添加连接骨后需要重写权重索引：%s' % (obj.name, cause))
        if _changed and not _can_reencode:
            print("WARNING: Mesh %d FVF 0x%08x 不支持重新编码, 顶点修改会被忽略" % (i, fvf))
        _reencode = (not _use_orig) and _can_reencode and (
            expect_atlas_uv or remapped_slots or _changed or not (vc == _tpl.vertCount))
        if not _reencode:
            src_off = hdr.ptr_vertex + _tpl.vertStart * vs + _tpl.vertBase
            vert_data = bytes(data[src_off:src_off + _tpl.vertCount * vs])
        else:

            na = vertex_normals_file_space(obj)

            try:
                _weld = bpy.context.scene.MT_Framework_Props.weld_normals
            except Exception:
                _weld = False
            if _weld and len(na) > 1:
                _weld_buckets = {}
                for _vi, _vv in enumerate(md.vertices):
                    _k = (round(_vv.co.x, 4), round(_vv.co.y, 4), round(_vv.co.z, 4))
                    _weld_buckets.setdefault(_k, []).append(_vi)
                _fixed = 0
                for _k, _ids in _weld_buckets.items():
                    if len(_ids) < 2:
                        continue
                    _sum = Vector((0.0, 0.0, 0.0))
                    for _vi in _ids:
                        if _vi < len(na):
                            _sum += na[_vi]
                    if _sum.length < 1e-9:
                        continue
                    _sum.normalize()
                    for _vi in _ids:
                        if _vi < len(na):
                            if na[_vi].dot(_sum) < 0.9999:
                                _fixed += 1
                            na[_vi] = _sum.copy()
                if _fixed:
                    print("  法线合并: UV 接缝处的法线已统一 (%d 个顶点)" % _fixed)

            ta = vertex_tangents_file_space(obj)

            for _i in range(min(len(ta), len(na))):
                _n = na[_i]
                _t = ta[_i] - _n * ta[_i].dot(_n)
                if _t.length < 1e-6:
                    _t = Vector((1.0, 0.0, 0.0))
                    if abs(_n.x) > 0.9:
                        _t = Vector((0.0, 1.0, 0.0))
                    _t = _t - _n * _t.dot(_n)
                if _t.length > 1e-9:
                    ta[_i] = _t.normalized()
            ul = md.uv_layers.active.data if md.uv_layers else None
            vum = {}
            if ul and md.loops:
                for loop in md.loops:
                    vum.setdefault(loop.vertex_index, Vector((ul[loop.index].uv.x, 1.0-ul[loop.index].uv.y)))
            _arm_bm = _arm_of(obj)
            bm = _build_bone_map(obj, len(_arm_bm.data.bones) if _arm_bm else 0)

            _coff = get_object_center_offset(obj, bpy.context.scene)
            _mw = obj.matrix_world.copy()

            _pos = None
            try:
                _dg = bpy.context.evaluated_depsgraph_get()
                _ev = obj.evaluated_get(_dg)
                _em = _ev.to_mesh()
                if _em is not None:

                    if len(_em.vertices) == len(md.vertices):
                        _pos = [(_mw @ _v.co) - _coff for _v in _em.vertices]
                    try:
                        _ev.to_mesh_clear()
                    except Exception:
                        pass
            except Exception:
                _pos = None
            if _pos is None:
                _pos = [(_mw @ _v.co) - _coff for _v in md.vertices]

            def _file_space(i):
                w = _pos[i]
                return Vector((w.x, w.z, -w.y))

            def gp(i):
                return _file_space(_split[i])
            def gu(i):

                if _seam_split:
                    return Vector(_split_uv[i])
                uv = vum.get(i)
                if uv is None:
                    return Vector((0.5, 0.5))
                return Vector((uv.x, uv.y))
            def gn(i):
                _i = _split[i]
                return na[_i] if _i<len(na) else Vector((0,0,0))
            def gt(i):

                _i = _split[i]
                if _i < len(ta):
                    return ta[_i]
                n = gn(i)
                for ax in [Vector((1,0,0)), Vector((0,1,0)), Vector((0,0,1))]:
                    t = ax.cross(n)
                    if t.length > 0.001: t.normalize(); return t
                return Vector((1,0,0))
            def gsk(i):

                b, w = get_skin_weights(obj, _split[i])

                pairs = [(bm[x], ww) for x, ww in zip(b, w)
                         if x in bm and ww > 0.0]
                if pairs:
                    pairs.sort(key=lambda t: -t[1])
                    pairs = pairs[:4]
                    b = [p[0] for p in pairs]
                    w = [p[1] for p in pairs]
                    wt = sum(w)
                    w = [x / wt for x in w]
                else:
                    b, w = [0], [1.0]

                while len(b) < 4:
                    b.append(b[-1])
                while len(w) < 4:
                    w.append(0.0)
                return (b, w)

            _mx = 0.0
            for _vi in range(vc):
                _p = _file_space(_vi)
                _a = max(abs(_p.x), abs(_p.y), abs(_p.z))
                if _a > _mx:
                    _mx = _a
            if _mx > 0.999:
                _fit = 0.999 / _mx
                print("WARNING: 网格 %s 顶点超出 int16 可表达范围 "
                      "(最大 |坐标| = %.4f > 1.0)。超出部分会被压平。"
                      "请把模型整体缩放约 %.4f (S 键输入 %.4f) 再导出。"
                      % (obj.name, _mx, _fit, _fit))

            _weight_limit = 1 if fvf in _SINGLE_BONE_FVF else 4
            try:
                _over = 0
                _mx = 0.0
                for _vi in range(len(md.vertices)):
                    _b0, _w0 = get_skin_weights(obj, _vi)
                    _pr = [ww for xx, ww in zip(_b0, _w0) if xx in bm and ww > 0.0]
                    if len(_pr) > _weight_limit:
                        _tot = sum(_pr)
                        if _tot > 0.0:
                            _d = 1.0 - sum(sorted(_pr, reverse=True)[:_weight_limit]) / _tot
                            _over += (_d > 1e-4 if _weight_limit == 1 else 1)
                            if _d > _mx:
                                _mx = _d
                if _over:
                    if _weight_limit == 1:
                        message = ('「%s」第 %d 槽只存单骨权重（FVF 0x%08X），'
                                   '%d 个顶点会丢失混合权重。可改用支持多骨权重的可见分件槽。'
                                   % (obj.name, i + 1, fvf, _over))
                        print('WARNING: %s 最大丢弃权重 %.4f' % (message, _mx))
                        if report is not None:
                            report({'WARNING'}, message)
                    else:
                        print('NOTE: 网格 %s 权重精简：%d 个顶点超过 4 根骨，'
                              '最大丢弃权重 %.4f（导出按前 4 根归一化）'
                              % (obj.name, _over, _mx))
            except Exception as _e_w:
                print('[MT] 权重诊断跳过：%s' % _e_w)
            vert_data = _write_vbuf(fvf, _vc_out, gp, gu, gn, gt, gsk, vs)

        if len(vert_data) != _vc_out * vs:
            raise ValueError('「%s」的顶点数与模板数据不符，请关闭「使用原版顶点」或选择支持的 FVF' % obj.name)
        for part_data, count, triangles in _mesh_parts(md, _loop_vert, vert_data, vs, _vc_out):
            pad = (-rb) % vs
            new_vert.extend(b'\0' * pad)
            rb += pad

            start = rb // vs
            base = 0
            if _vc_out > 0xFFFF or start + count > 0xFFFF:
                start, base = 0, rb
            new_vert.extend(part_data)
            rb += len(part_data)

            fc = 0
            for v0, v1, v2 in triangles:
                if fc:
                    new_face.extend(b'\xff\xff')
                    fc += 1
                new_face.extend(struct.pack('<HHH', v0 + start, v1 + start, v2 + start))
                fc += 3

            mh = MeshHeaderStruct()
            for attr in ['meshtype', 'unk01', 'MatId', 'lodLevel', 'unk04', 'vertFlag',
                         'vertStride', 'unk05', 'fvfInfo', 'bonemapindex', 'weightmaps',
                         'unk07', 'unk08', 'unk09']:
                setattr(mh, attr, getattr(_tpl, attr))
            if getattr(bpy.context.scene.MT_Framework_Props, 'all_visible', False):
                if vs >= 20:
                    mh.meshtype = 0xEFFF
                else:
                    _skipped_visible.append(i)
            mh.vertCount, mh.faceCount = count, fc
            mh.vertStart, mh.vertBase = start, base
            mh.faceStart, mh.faceBase = rf, 0
            mh.min_index, mh.max_index = start, start + count - 1 if count else 0
            new_headers_list.append(mh)
            rf += fc

    if _skipped_visible:
        print("NOTE: 这些分件是纯深度件（无 UV/法线），没有强行设成可见: %s"
              % [i + 1 for i in _skipped_visible])

    _tpl_used = 0
    for _mh0 in headers:
        _tpl_used += int(_mh0.vertCount) * int(_mh0.vertStride)
    _pad = int(hdr.vertexBufferSize) - _tpl_used
    if _pad < 0:
        _pad = 0
    extra_headers = max(0, len(new_headers_list) - len(headers)) * 48
    ptr_vertex = hdr.ptr_vertex + extra_headers
    _new = bytearray(data[:hdr.ptr_vertex])
    _new += b'\0' * extra_headers
    _new += bytes(new_vert)
    if _pad:
        _new += b'\x00' * _pad
    npt = len(_new)
    _new += bytes(new_face)
    _new += b'\x00\x00\x00\x00'
    data = _new
    ntc = len(new_face) // 2
    struct.pack_into('<I', data, 16, ntc)
    struct.pack_into('<I', data, 56, npt)
    struct.pack_into('<I', data, 60, len(data) - 4)
    struct.pack_into('<I', data, 52, ptr_vertex)
    struct.pack_into('<I', data, 24, npt - ptr_vertex)

    hdr_data = bytearray()
    total_vc = 0
    for mh in new_headers_list:
        hdr_data += mh.serialize()
        total_vc += mh.vertCount
    if hdr.ptr_Mesh > 0:
        data[hdr.ptr_Mesh:hdr.ptr_Mesh+len(hdr_data)] = bytes(hdr_data)
    struct.pack_into('<H', data, 8, len(new_headers_list))
    try:
        _n_in = len([o for o in sel if len(o.data.vertices) > 0])
        print('分件: 选中 %d 个网格 -> 写出 %d 个分件%s'
              % (_n_in, len(new_headers_list),
                 '（有网格被合并进同一槽）' if _n_in > len(new_headers_list) else ''))
    except Exception:
        pass
    struct.pack_into('<I', data, 12, total_vc)

    _plan = None
    _arm = None
    try:
        from . import MTframework_MHGU_bones as _BONES
        _arms = [o for o in bpy.context.scene.objects if o.type == 'ARMATURE']

        _arm, _why = _BONES.find_armature(_arms, hdr.boneCount, None)
        if _arm is None:
            print("NOTE: 跳过骨骼回写 —— %s (骨骼段将保持模板原样)" % _why)
        else:

            _cur_mesh_y = None
            try:
                _lo = 1e30
                for _o in (list(sm.values()) or sel):
                    if _o is None or _o.type != 'MESH':
                        continue
                    _c = get_object_center_offset(_o, bpy.context.scene)
                    _mw2 = _o.matrix_world
                    for _v in _o.data.vertices:
                        _z = (_mw2 @ _v.co).z - _c.z
                        if _z < _lo:
                            _lo = _z
                if _lo < 1e29:
                    _cur_mesh_y = _lo
            except Exception:
                _cur_mesh_y = None
            _plan = _BONES.write_bone_section(
                data, hdr.ptr_Bone, hdr.boneCount, _arm,
                name_map=get_bone_name_map(bpy.context.scene, _arm),

                offset=get_object_center_offset(_arm, bpy.context.scene),
                template_bytes=_tpl_bytes,
                cur_mesh_min_y=_cur_mesh_y,

                anchor=False)
            if _plan is None:
                print("NOTE: 跳过骨骼回写 —— 没算出方案")
            else:
                _nmoved = sum(
                    1 for i in range(hdr.boneCount)
                    if _plan['new_world'][i] != _plan['sec']['world_t'][i]
                    or _plan['new_local'][i] != _plan['sec']['local_t'][i])
                print("骨骼回写: %s (%d 根)   改动了 %d/%d 根"
                      % (_arm.name, len(_arm.data.bones), _nmoved, hdr.boneCount))
                _ad = _plan.get('anchor_delta')
                if _ad:
                    print("  已把骨架沿高度方向锚回原相对位置 (文件 Y 平移 %+.5f)"
                          % _ad[1])
    except Exception as _be:
        print("WARNING: 骨骼回写失败: %s" % _be)
        print("         顶点/材质仍会写出, 但骨骼位置保持模板原样。")

    try:
        from . import MTframework_MHGU_bones as _B2

        _warn, _info = _B2.check_export(
            data, hdr.ptr_Bone, hdr.boneCount, _plan,
            list(sm.values()) or sel,
            coff=get_object_center_offset(_arm, bpy.context.scene)
            if _arm is not None else get_center_offset(bpy.context.scene),
            arm_obj=_arm,
            template_bytes=_tpl_bytes)
        print("--- 导出校验 ---")
        print("  顶点最大绝对值 %.5f / 上限 1.0%s"
              % (_info.get('vert_max', 0.0),
                 ('  (在 %s)' % _info['vert_worst'])
                 if _info.get('vert_worst') else ''))
        if _info.get('mesh_min') is not None:
            print("  网格最低点(文件Y) %+.5f   (官方 500 个文件全部是 0.00000)"
                  % _info['mesh_min'])
        if _info.get('root_old') is not None:
            print("  根骨 world %s -> %s"
                  % (tuple(round(x, 3) for x in _info['root_old']),
                     tuple(round(x, 3) for x in _info['root_new'])))
        print("  单根关节相对模板最大改动 %.5f 文件单位"
              % _info.get('bone_delta', 0.0))
        if _info.get('amat_c') is not None:

            print("  骨骼三份同步 amat+p_world=C  C=(%+.3f, %+.3f, %+.3f)  偏差 %.6f"
                  % (_info['amat_c'] + (_info.get('amat_spread', 0.0),)))
        if _info.get('rel_delta') is not None:

            print("  网格-骨架相对关系   模板 %+.5f  现在 %+.5f  差 %+.5f"
                  % (_info['rel_template'], _info['rel_current'],
                     _info['rel_delta']))
        else:
            print("  网格-骨架相对关系   算不出 (模板网格最低 %s, 当前网格最低 %s)"
                  % (_info.get('tpl_mesh'), _info.get('cur_mesh')))
        if _arm is not None:
            print("  使用的骨架: %s (%d 根)"
                  % (_arm.name, len(_arm.data.bones)))
            _others = [a.name for a in bpy.context.scene.objects
                       if a.type == 'ARMATURE' and a is not _arm]
            if _others:
                print("  场景里其他骨架 (未使用): %s" % ', '.join(_others))
        for _w in _warn:
            print("  *** 注意: %s" % _w)
        if not _warn:
            print("  没发现问题。")
    except Exception as _ce:
        print("NOTE: 导出校验跳过 (%s)" % _ce)

    with open(filepath, 'wb') as f:
        f.write(data)
    print("Export complete: %s" % filepath)
    return filepath
