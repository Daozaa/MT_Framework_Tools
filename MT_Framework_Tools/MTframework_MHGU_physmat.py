from __future__ import annotations

import struct

try:
    import bpy
    from bpy.types import Operator
    from mathutils import Vector
except Exception:
    bpy = None

from .MTframework_MHGU_phys import recalled_arc, remember_arc

MAT_P = (0.0, 1.0, 0.0, 0.0,
         0.0, 0.0, 1.0, 0.0,
         1.0, 0.0, 0.0, 0.0,
         0.0, 0.0, 0.0, 1.0)
MAT_Q = (0.0, 0.0, 1.0, 0.0,
         1.0, 0.0, 0.0, 0.0,
         0.0, 1.0, 0.0, 0.0,
         0.0, 0.0, 0.0, 1.0)
MAT_I = (1.0, 0.0, 0.0, 0.0,
         0.0, 1.0, 0.0, 0.0,
         0.0, 0.0, 1.0, 0.0,
         0.0, 0.0, 0.0, 1.0)

def matrix_and_mode(identity):
    return (MAT_I, 1) if identity else (MAT_Q, 1)

def write_matrix(buf, node_off=0, identity=False):
    mat, mode = matrix_and_mode(identity)
    struct.pack_into('<16f', buf, node_off + 16, *mat)
    buf[node_off + 4:node_off + 8] = bytes((mode, 0, 1, 1))
    return mat, mode

def _bone_dir(arm, bone_name, next_name=None):
    b = arm.data.bones.get(bone_name)
    if b is None:
        return None
    if next_name:
        nb = arm.data.bones.get(next_name)
        if nb is not None:
            d = nb.head_local - b.head_local
            if d.length > 1e-6:
                return d.normalized()
    d = b.tail_local - b.head_local
    if d.length > 1e-6:
        return d.normalized()
    if b.parent is not None:
        d = b.head_local - b.parent.head_local
        if d.length > 1e-6:
            return d.normalized()
    return Vector((0.0, 0.0, -1.0))

def _chain_next_ids(ctc):
    n_g = struct.unpack_from('<I', ctc, 0x10)[0]
    n_c = struct.unpack_from('<I', ctc, 0x14)[0]
    off = 0x3C + 80 * n_g
    out = {}
    idx = 0
    for g in range(n_g):
        cnt = struct.unpack_from('<I', ctc, 0x3C + 80 * g)[0]
        for j in range(cnt):
            k = idx + j
            if k + 1 < idx + cnt:
                out[k] = struct.unpack_from('<H', ctc, off + (k + 1) * 96)[0]
            else:
                out[k] = None
        idx += cnt
    return out

_IDENT = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0)

def _rows9(b, o):
    return struct.unpack_from('<12f', b, o + 16)

def _is_identity(rows):
    return max(abs(rows[i] - _IDENT[i]) for i in range(12)) < 1e-4

def _axis_of(rows, fallback):
    v = Vector((rows[4], rows[5], rows[6]))
    if v.length < 0.5:
        return fallback
    return v.normalized()

def fix_matrix_modes(ctc):
    P = MAT_P
    Q = MAT_Q
    I = MAT_I
    if not ctc or ctc[:4] != b'CTC\x00' or len(ctc) < 0x3C:
        return ctc, 0
    b = bytearray(ctc)
    n_g = struct.unpack_from('<I', b, 0x10)[0]
    n_c = struct.unpack_from('<I', b, 0x14)[0]
    off = 0x3C + 80 * n_g
    fixed = 0
    for k in range(n_c):
        o = off + k * 96
        m = struct.unpack_from('<16f', b, o + 16)

        if max(abs(m[i] - I[i]) for i in range(16)) < 1e-4:
            if b[o + 4] != 1:
                b[o + 4] = 1
                fixed += 1
        elif max(abs(m[i] - Q[i]) for i in range(16)) < 1e-4:
            if b[o + 4] != 1:
                b[o + 4] = 1
                fixed += 1
    return bytes(b), fixed

def set_all_identity(ctc):
    b = bytearray(ctc)
    n_g = struct.unpack_from('<I', b, 0x10)[0]
    n_c = struct.unpack_from('<I', b, 0x14)[0]
    off = 0x3C + 80 * n_g
    mat = (1.0, 0.0, 0.0, 0.0,
           0.0, 1.0, 0.0, 0.0,
           0.0, 0.0, 1.0, 0.0,
           0.0, 0.0, 0.0, 1.0)
    changed = 0
    for k in range(n_c):
        o = off + k * 96
        cur = struct.unpack_from('<16f', b, o + 16)
        if max(abs(cur[i] - mat[i]) for i in range(16)) > 1e-6:
            changed += 1
        struct.pack_into('<16f', b, o + 16, *mat)

        b[o + 4] = 1
    return bytes(b), changed

def rebuild_matrices(arm, ctc, rot_axis=(1.0, 0.0, 0.0)):
    b = bytearray(ctc)
    n_g = struct.unpack_from('<I', b, 0x10)[0]
    n_c = struct.unpack_from('<I', b, 0x14)[0]
    off = 0x3C + 80 * n_g
    default_axis = Vector(rot_axis).normalized()
    nxt = _chain_next_ids(ctc)
    group_starts = set()
    _idx = 0
    for _g in range(n_g):
        group_starts.add(_idx)
        _idx += struct.unpack_from('<I', b, 0x3C + 80 * _g)[0]
    report = []

    def _name(jid):
        nm = 'b_%d' % jid
        try:
            _mp = arm.get('MT_PhysIdMap')
            if _mp:
                nm = str(_mp.get(str(jid), nm))
        except Exception:
            pass
        return nm

    for k in range(n_c):
        o = off + k * 96
        jid = b[o]
        name = _name(jid)

        if k not in group_starts:
            is_tail_k = (nxt.get(k) is None)
            if is_tail_k:
                write_matrix(b, o, True)
                report.append('%s 链尾→单位阵' % name)
                continue
        rows = _rows9(b, o)
        axis = _axis_of(rows, default_axis)
        is_tail = (nxt.get(k) is None)
        next_name = _name(nxt[k]) if not is_tail else None
        d = _bone_dir(arm, name, next_name)
        if d is None:
            report.append('%s 找不到骨，跳过' % name)
            continue

        r0 = Vector((d.x, d.z, -d.y))
        if r0.length < 1e-6:
            r0 = Vector((0.0, -1.0, 0.0))
        r0.normalize()
        r1 = axis - r0 * axis.dot(r0)
        if r1.length < 1e-6:
            r1 = Vector((1.0, 0.0, 0.0)) - r0 * r0.x
        r1.normalize()
        r2 = r0.cross(r1)
        mat = (r0.x, r0.y, r0.z, 0.0,
               r1.x, r1.y, r1.z, 0.0,
               r2.x, r2.y, r2.z, 0.0,
               0.0, 0.0, 0.0, 1.0)
        struct.pack_into('<16f', b, o + 16, *mat)
        b[o + 4] = 1
        report.append('%s 方向=(%.2f,%.2f,%.2f)' % (name, r0.x, r0.y, r0.z))
    return bytes(b), report

if bpy is not None:

    def _find_armature(context):
        objs = [o for o in context.scene.objects if o.type == 'ARMATURE']
        for o in objs:
            if o.name.startswith('MT_Armature') or o.data.name.startswith('MT_Armature'):
                return o
        return objs[0] if objs else None

    class MT_OT_PhysMatrixAuto(Operator):
        bl_idname = "mt_framework.phys_matrix_auto"
        bl_label = "物理矩阵自适应"
        bl_description = ("按骨架里物理骨链的实际朝向重算 CTC 矩阵；"
                          "改过骨位后用它，避免进游戏被摆斜")

        def execute(self, context):
            arm = _find_armature(context)
            if arm is None:
                self.report({'ERROR'}, '场景里没有骨架')
                return {'CANCELLED'}
            arc_path, ctc = recalled_arc(context)
            if not ctc:
                self.report({'ERROR'}, '当前没有 CTC（先登记物理骨或补全物理链）')
                return {'CANCELLED'}
            if ctc[:4] != b'CTC\x00':
                self.report({'ERROR'}, 'CTC 数据异常')
                return {'CANCELLED'}
            new, report = rebuild_matrices(arm, ctc)
            remember_arc(context, arc_path, new)
            context.scene['MT_CtcCustom'] = True
            self.report({'INFO'}, '已按骨链重算 %d 个节点：%s'
                        % (len(report), '；'.join(report[:4])))
            return {'FINISHED'}

    _classes = [MT_OT_PhysMatrixAuto]

    def register():
        for c in _classes:
            bpy.utils.register_class(c)

    def unregister():
        for c in reversed(_classes):
            try:
                bpy.utils.unregister_class(c)
            except Exception:
                pass

else:
    def register():
        pass

    def unregister():
        pass
