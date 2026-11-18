# -*- coding: utf-8 -*-
"""给没有物理骨的 .mod 追加物理骨（把捐献者多出来的骨全部补上）。

做法：以「物理防具」的 .mod 当骨骼捐献者，把它比目标**多出来的骨**
（通常是 id 20/21/22，部分防具还有 23）连同 BoneInfo / lmat / amat / LUT
一起追加到目标骨骼段末尾，再修正文件里所有绝对指针。

追加在末尾 → 已有槽位号不变，顶点索引不用改；CTC 直接沿用捐献者的。
"""
from __future__ import annotations

import struct

INFO = 24
MAT = 64


def _bounds(data):
    n = struct.unpack_from('<H', data, 6)[0]
    ptr = struct.unpack_from('<I', data, 36)[0]
    lmat = ptr + n * INFO
    amat = lmat + n * MAT
    lut = amat + n * MAT
    return n, ptr, lmat, amat, lut


def _worlds(data):
    n, ptr, lmat, amat, lut = _bounds(data)
    at0 = struct.unpack_from('<3f', data, amat + 48)
    lt0 = struct.unpack_from('<3f', data, lmat + 48)
    c = [at0[k] + lt0[k] for k in range(3)]
    out = []
    for i in range(n):
        a = struct.unpack_from('<3f', data, amat + i * MAT + 48)
        out.append(tuple(c[k] - a[k] for k in range(3)))
    return c, out


def bone_ids(mod_bytes):
    n, ptr, lmat, amat, lut = _bounds(mod_bytes)
    return [mod_bytes[ptr + i * INFO] for i in range(n)]


def extra_bones(donor, target):
    """捐献者里目标没有的骨（按槽位顺序）。"""
    tids = set(bone_ids(target))
    n, ptr, lmat, amat, lut = _bounds(donor)
    out = []
    for i in range(n):
        bid = donor[ptr + i * INFO]
        if bid in tids:
            continue
        out.append(dict(
            slot=i, id=bid, parent=donor[ptr + i * INFO + 1],
            info=bytes(donor[ptr + i * INFO: ptr + (i + 1) * INFO]),
            lmat=bytes(donor[lmat + i * MAT: lmat + (i + 1) * MAT]),
            amat=bytes(donor[amat + i * MAT: amat + (i + 1) * MAT]),
        ))
    return out


def append_physics_bones(target: bytes, donor: bytes):
    extras = extra_bones(donor, target)
    if not extras:
        raise ValueError('捐献者没有比目标更多的骨（没有物理骨可加）')

    tn, tptr, tlmat, tamat, tlut = _bounds(target)
    dn, dptr, dlmat, damat, dlut = _bounds(donor)
    if tn + len(extras) > 255:
        raise ValueError('目标骨数过多')

    t_at0 = struct.unpack_from('<3f', target, tamat + 48)
    t_lt0 = struct.unpack_from('<3f', target, tlmat + 48)
    tc = [t_at0[k] + t_lt0[k] for k in range(3)]
    _, t_world = _worlds(target)
    _, d_world = _worlds(donor)
    # 骨架缩放：新骨必须用**目标的** amat 缩放，抄捐献者会让蒙皮缩小/放大
    t_scale = abs(struct.unpack_from('<f', target, tamat)[0]) or 1.0
    d_scale = abs(struct.unpack_from('<f', donor, damat)[0]) or 1.0

    def _ratio(par_slot, d_par_slot):
        """骨架比例 = 父骨到原点距离之比（官方同骨架=1，改过比例的身体≈1.5）。"""
        if not (0 <= par_slot < tn) or not (0 <= d_par_slot < dn):
            return 1.0
        a = sum(v * v for v in t_world[par_slot]) ** 0.5
        b = sum(v * v for v in d_world[d_par_slot]) ** 0.5
        if b < 1e-3:
            return 1.0
        r = a / b
        return r if 0.2 < r < 5.0 else 1.0

    tslot = {bone_ids(target)[i]: i for i in range(tn)}
    target_bones = [(i, t_world[i]) for i in range(tn)]
    slot_of = {}
    for k, b in enumerate(extras):
        slot_of[b['id']] = tn + k

    new_infos, new_lmats, new_amats = [], [], []
    parent_map = {}
    for k, b in enumerate(extras):
        new_slot = tn + k
        par_id = donor[dptr + b['parent'] * INFO] if b['parent'] < dn else 255
        _dp = b['parent']
        if _dp < dn:
            _off = [d_world[b['slot']][i] - d_world[_dp][i] for i in range(3)]
        else:
            _off = list(d_world[b['slot']])
        world = None

        if par_id in slot_of:
            par_slot = slot_of[par_id]
            pw = d_world[extras[[e['id'] for e in extras].index(par_id)]['slot']]
        elif par_id in tslot:
            par_slot = tslot[par_id]
            pw = t_world[par_slot]
        else:
            # 同 id 在目标里对不上 → 用世界坐标最近的骨当父骨
            dw = d_world[b['parent']] if b['parent'] < dn else None
            best, bd = None, 1e9
            if dw is not None:
                for tb in target_bones:
                    dd = sum((tb[1][k] - dw[k]) ** 2 for k in range(3)) ** 0.5
                    if dd < bd:
                        best, bd = tb, dd
            if best is not None and bd <= 60.0:
                par_slot, pw = best[0], best[1]
            else:
                par_slot = 255
                pw = (0.0, 0.0, 0.0)

        ratio = _ratio(par_slot, b['parent'])
        world = tuple(pw[i] + _off[i] * ratio for i in range(3))
        local = tuple(world[i] - pw[i] for i in range(3))

        parent_map[b['id']] = par_slot
        info = bytearray(b['info'])
        struct.pack_into('<B', info, 1, par_slot)
        struct.pack_into('<B', info, 2, new_slot)          # mirror = 自己
        struct.pack_into('<f', info, 8, (local[0] ** 2 + local[1] ** 2 + local[2] ** 2) ** 0.5)
        struct.pack_into('<3f', info, 12, *local)
        # 矩阵是 4x4 行主序（16 float = 64 字节）：3x3 在 0..48，行尾 w 在 12/28/44，
        # 平移在 48..60，最后一个是 1.0。整块复制再改，别只写 9 个 float。
        dm = struct.unpack_from('<16f', donor, damat + b['slot'] * MAT)
        dk = t_scale / d_scale
        lm = list(dm)
        am = list(dm)
        for r in range(3):
            for c in range(3):
                lm[r * 4 + c] = dm[r * 4 + c] * dk
                am[r * 4 + c] = dm[r * 4 + c] * dk
        lm[12] = lm[13] = lm[14] = 0.0
        lm[15] = 1.0
        am[12] = am[13] = am[14] = 0.0
        am[15] = 1.0
        lm[12:15] = [local[0], local[1], local[2]]
        am[12:15] = [tc[i] - world[i] for i in range(3)]
        lmat = bytearray(struct.pack('<16f', *lm))
        amat = bytearray(struct.pack('<16f', *am))

        new_infos.append(bytes(info))
        new_lmats.append(bytes(lmat))
        new_amats.append(bytes(amat))

    old_info = target[tptr:tptr + tn * INFO]
    old_lmat = target[tlmat:tlmat + tn * MAT]
    old_amat = target[tamat:tamat + tn * MAT]
    lut = bytearray(target[tlut:tlut + 256])
    for bid, slot in slot_of.items():
        lut[bid] = slot

    new_bone = (old_info + b''.join(new_infos)
                + old_lmat + b''.join(new_lmats)
                + old_amat + b''.join(new_amats)
                + bytes(lut))
    old_bone_len = tn * (INFO + MAT * 2) + 256
    delta = len(new_bone) - old_bone_len
    out = bytearray(target[:tptr] + new_bone + target[tptr + old_bone_len:])

    struct.pack_into('<H', out, 6, tn + len(extras))
    # 所有绝对指针都要跟着后移：ptr_BoneMap(40) ptr_MatID(44) ptr_Mesh(48) ptr_vertex(52) ptr_triangle(56)
    for off in (40, 44, 48, 52, 56):
        v = struct.unpack_from('<I', target, off)[0]
        if v:
            struct.pack_into('<I', out, off, v + delta)
    struct.pack_into('<I', out, 60, len(out) - 4)
    return bytes(out), dict(slots=slot_of, delta=delta, ids=[e['id'] for e in extras],
                            parents=parent_map)
