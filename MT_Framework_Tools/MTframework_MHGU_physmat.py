# -*- coding: utf-8 -*-
"""物理矩阵自适应：按骨架里物理骨链的实际朝向，重算 CTC 里每根链的 4×4 矩阵。

矩阵语义（参考包结论 + 实测）：
  * mRotMode 取矩阵的某一行当摆动轴（1 → 第 2 行，2 → 第 3 行）
  * 其余行是骨的静止朝向（含美术手摆的 roll，无法从骨位精确反推）
  * 所以这里做**近似**：row0 = 骨方向（指向子骨），row1 = 摆动轴 X 正交化，row2 = row0×row1

适用：你改过物理骨位置/朝向，但 CTC 还是捐献者的 → 进游戏被摆斜。
"""
from __future__ import annotations

import struct

try:
    import bpy
    from bpy.types import Operator
    from mathutils import Vector
except Exception:                                       # noqa: BLE001
    bpy = None

from .MTframework_MHGU_phys import recalled_arc, remember_arc

# ★ 链块矩阵只允许两种写法（官方 1217 块统计 + 大凤 bodyZZ 实机 A/B）：
#   Q + mAngleMode=1 → 第 2 行 = (1,0,0) = 左右轴 → 前后摆（官方主流：258 块 row1=±X）
#   I + mAngleMode=1 → 链尾，运动由链首/父骨驱动
# 实机：P+mode2（第 3 行也是 (1,0,0)）会让物理整体**向上飘**；Q+mode1 不会。
# ⇒ 说明引擎消费的不止“被选中的那一行”，矩阵整体参与。统一走 write_matrix。
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
    """返回 (16 floats, mAngleMode)。identity=True → 单位阵 + mode 1。"""
    return (MAT_I, 1) if identity else (MAT_Q, 1)


def write_matrix(buf, node_off=0, identity=False):
    """把 3x3/4x4 与 +4(mAngleMode) **一起**写进链块。

    ★ node_off 是**链块起始**偏移（96B 块），不是矩阵偏移。
      以前写成 `write_matrix(b, o + 16, True)`，mode 被写到 CTC 头 b[4:8]，
      把版本号 22 覆盖成垃圾 → 游戏直接不认 CTC → **完全没有物理**。
    """
    mat, mode = matrix_and_mode(identity)
    struct.pack_into('<16f', buf, node_off + 16, *mat)
    buf[node_off + 4:node_off + 8] = bytes((mode, 0, 1, 1))
    return mat, mode


def _bone_dir(arm, bone_name, next_name=None):
    """骨在 CTC 链里的朝向。

    * 有**链上的下一根骨**（next_name）→ 指向它（真正的链方向）
    * 链尾/单节链 → 骨自己的头→尾方向
      （以前用「父骨→本骨」的偏移：单节链的偏移是横向的、骨却竖直，夹角 70~147°，
       引擎按错误朝向摆骨 → 网格塌陷）
    * 尾巴退化 → 父方向 → 默认 -Z
    """
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
    """按 CTC 组结构返回 {节点下标: 同组下一个节点的骨 id}（组尾没有下一根）。"""
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
    """读矩阵前 3 行（每行 4 个 float，含行末 0）。"""
    return struct.unpack_from('<12f', b, o + 16)


def _is_identity(rows):
    return max(abs(rows[i] - _IDENT[i]) for i in range(12)) < 1e-4


def _axis_of(rows, fallback):
    """从现有矩阵第 2 行取摆动轴；退化/单位阵就用 fallback。"""
    v = Vector((rows[4], rows[5], rows[6]))
    if v.length < 0.5:
        return fallback
    return v.normalized()


def fix_matrix_modes(ctc):
    """导出兜底：把链块矩阵/`+4` 规范成实机验证过的两种写法之一。

    * 矩阵 == P（旧版 1.2.131~133 写的）→ 改写成 Q + mode=1
      （实机：P+mode2 会让物理整体上飘；Q+mode1 正常）
    * 矩阵 == I → +4 必须是 1
    * 矩阵 == Q → +4 必须是 1
    其它矩阵（官方手作斜轴）一律不动。返回 (新 ctc, 修正个数)。
    """
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
        # 只保证「单位阵/标准置换阵」的 mode 是 1；骨方向矩阵（1.2.125 写法）不动，
        # P/mode2 也不再改写（改写会改变摆动平面，实机已验证不可取）。
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
    """把所有节点矩阵改成单位阵（保留组参数/角度/质量/弹性）。

    为什么需要：官方节点矩阵编码的是「骨相对链根/父骨的静止姿态」（含手摆 roll），
    不是世界方向；我们按世界方向重算的矩阵在链根不朝世界轴时会差一个固定旋转，
    进游戏物理就会随角色朝向变化。单位阵 = 保持骨自己的静止姿态，不引入额外旋转。
    返回 (新 ctc, 改动节点数)。
    """
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
        # 单位阵必须配 +4=1（只改矩阵不改 mode → I/2 不配对，轴会变）
        b[o + 4] = 1
    return bytes(b), changed


def rebuild_matrices(arm, ctc, rot_axis=(1.0, 0.0, 0.0)):
    """重算 ctc 里所有节点的矩阵，返回 (新 ctc, 报告)。

    ★ 保留每根骨**原来的摆动轴**（第 2 行）：默认 X = 前后摆；用户用
       「摆动方向」锁成 Z = 左右摆后，自适应不会再把它改回前后摆。
    ★ 原来是单位阵的链尾继续单位阵（官方 76% 的链尾就是单位阵）。
    """
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
        except Exception:                               # noqa: BLE001
            pass
        return nm

    for k in range(n_c):
        o = off + k * 96
        jid = b[o]
        name = _name(jid)
        # ★ 回到 1.2.125 写法（用户实机确认正常）：非链尾写「骨/链方向」矩阵、
        #   row1 = 原摆动轴正交化，链尾单位阵；mode 固定 1。
        #   P/mode2 上飘、Q/mode1 头发卷，都已实机否掉。
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
        # Blender 空间 -> 文件/游戏空间：(x, y, z) -> (x, z, -y)
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
        """按当前骨链重算物理矩阵"""
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
            except Exception:                           # noqa: BLE001
                pass

else:                                                   # pragma: no cover
    def register():
        pass

    def unregister():
        pass
