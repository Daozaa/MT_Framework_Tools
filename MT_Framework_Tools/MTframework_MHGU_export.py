# -*- coding: utf-8 -*-
"""
MT Framework MHGU - MOD Export
Full vertex+face replacement using original 3ds Max encoder
"""
import bpy, os, struct
from mathutils import Vector
from io import BytesIO
from .Mod import MODHeader, MeshHeaderStruct
from .MTframework_MHGU import (get_skin_weights, float_to_short,
                               get_center_offset, get_object_center_offset,
                               get_bone_name_map,
                               vertex_data_modified, remember_vertex_fingerprint,
                               vertex_normals_file_space, vertex_tangents_file_space)

def _bone_no_from_name(name):
    """从 ``b_12`` / ``b_12.l`` / ``b_12.r`` 取 0 基骨序号; 取不到返回 None。

    旧写法 ``int(name.split('_')[2]) - 1`` 对 ``b_12`` 必然抛 IndexError
    (``'b_12'.split('_')`` 只有 ``['b','12']`` 两段), 于是下面两条路径都只能
    进 except —— 最终拿**顶点组下标**当骨序号, 部件会被绑到错误的骨骼上。
    """
    if not name or not name.startswith('b_'):
        return None
    rest = name[2:]
    if '.' in rest:                      # b_12.l / b_12.r -> b_12
        rest = rest.split('.', 1)[0]
    if not rest.isdigit():
        return None
    return int(rest) - 1


def _arm_of(obj):
    """从网格的 Armature 修改器找到驱动它的骨架。

    用于把**该骨架自己那份**骨骼名对照表传给 get_bone_name_map —— 场景级那份
    会被下一次导入覆盖 (代码里实测 19 条目掉到 7 条目)。
    """
    try:
        for m in obj.modifiers:
            if m.type == 'ARMATURE' and m.object is not None:
                return m.object
    except Exception:
        pass
    return None


def _build_bone_map(obj, n_bones=0):
    """顶点组 → 骨序号（只保留**真的能对上骨骼**的组）。

    名字对不上骨骼的组（MMD 的 ``mmd_edge_scale`` / ``mmd_vertex_order``、
    MMD 骨名 ``Bip_L_Toe3`` / ``Upper Chest`` 等）**不能**拿组下标兜底 ——
    那会把它们当成第 N 根骨写进顶点数据，权重整体错位（越界索引更是直接坏掉）。
    现在直接跳过，由调用方把剩下的权重归一化。
    """
    bm = {}; es = {}
    name_map = {}
    try:
        # ★ 必须传该网格自己的骨架: 场景级那份会被下一次导入覆盖,
        #   带 .l/.r 后缀的骨骼名一旦查不到就解析不出记录号 (见
        #   apply_symmetric_bone_names 的说明)。
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
    # 法线/切线是**有符号字节** (原版插件用 read8s 读取), 不是 (b-127)。
    # 旧写法 int(v*127+127) 把 1.0 写成 254, 游戏按有符号读成 -2 -> 法线全错,
    # 表现就是光影断层/锯齿。正确: 分量*127 后当有符号字节存 (负数回绕到 128..255)。
    return max(-127, min(127, int(round(v * 127)))) & 0xFF

def _weight_byte(w): return max(0, min(255, int(w*255)))
def _weight_short(w): return max(-32767, min(32767, int(w*32767)))

def _pad4(b): return [b[0], b[1] if len(b)>1 else b[0], b[2] if len(b)>2 else b[0], b[3] if len(b)>3 else b[0]]
def _pad4w(w): return [w[0], w[1] if len(w)>1 else 0.0, w[2] if len(w)>2 else 0.0, w[3] if len(w)>3 else 0.0]

def _write_vbuf(fvf, vc, gp, gu, gn, gt, gsk, stride=24):
    """Vertex encoder for all MT Framework FVF types"""
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

        # --- short3 position helper ---
        if _is_short_pos:
            cx, cy, cz = _short_pos(p)
        else:
            fx, fy, fz = p.x, p.y, p.z

        # === GROUP 0: 12 bytes, 1 bone, no normals ===
        if fvf in (0xB0983013, 0xB0983014):
            cx,cy,cz = _short_pos(p)
            ux = max(0.0, min(1.0, u.x))
            uy = max(0.0, min(1.0, u.y))
            buf += struct.pack('<hhh', cx, cy, cz)
            buf += struct.pack('<BB', b[0], _weight_byte(w[0]))
            buf += struct.pack('<HH', int(ux*65535+0.5), int(uy*65535+0.5))

        # === GROUP 1: 16 bytes, no bones, short3 pos + 6B unknown + half2 uv ===
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

        # === GROUP 2: 16-18 bytes, no bones, short3 pos + ? + 1-2x half2 uv ===
        elif fvf in (0xC66FA03E,):
            cx,cy,cz = _short_pos(p)
            buf += struct.pack('<hhh', cx, cy, cz)
            buf += struct.pack('<I',0)
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('<HH',h(u.x),h(u.y))

        # === GROUP 3: 20 bytes, 1 bone, short3 pos + normal+tangent + half2 uv ===
        elif fvf in (0xA8FAB018,0xA8FAB019,0x0CB6800E,0x0CB68015,0x0CB68016):
            cx,cy,cz = _short_pos(p)
            buf += struct.pack('<hhh', cx, cy, cz)
            # 游戏格式: +6 = 骨骼索引(0 基), +7 恒 0
            # （官方 101 个这两个 FVF 的网格 +7 全是 0；旧版写权重 → 分件不显示）
            buf += struct.pack('<BB', b[0], 0)
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),127)
            buf += struct.pack('BBBB',_norm_byte(t.x),_norm_byte(t.y),_norm_byte(t.z),127)
            buf += struct.pack('<HH',h(u.x),h(u.y))

        # === GROUP 4: 20 bytes, float3 pos, normal, 1 UV ===
        elif fvf in (0xA7D7D036,):
            ux = max(0.0, min(1.0, u.x))
            uy = max(0.0, min(1.0, u.y))
            buf += struct.pack('<fff', fx, fy, fz)
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),0)
            buf += struct.pack('<HH', int(ux*65535+0.5), int(uy*65535+0.5))

        # === GROUP 5: 22 bytes, short3 pos, normal, ?, 2x half2 uv ===
        elif fvf in (0xAFA63031,):
            cx,cy,cz = _short_pos(p)
            buf += struct.pack('<hhh', cx, cy, cz)
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),0)
            buf += struct.pack('<I',0)
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('<HH',h(u.x),h(u.y))

        # === GROUP 6: 24 bytes, 2 bones half-float, short3 pos, normal+tangent, half2 uv ===
        elif fvf in (0xC31F201C,0xC31F201D):
            cx,cy,cz = _short_pos(p)
            buf += struct.pack('<hhh', cx, cy, cz)
            buf += struct.pack('<h', _weight_short(w[0]))
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),127)
            buf += struct.pack('BBBB',_norm_byte(t.x),_norm_byte(t.y),_norm_byte(t.z),127)
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('<HH',h(float(b[0])),h(float(b[1]) if len(b)>1 else float(b[0])))

        # === GROUP 7: 24 bytes, 1 bone byte, short3 pos, normal+tangent, half2 uv, color ===
        elif fvf in (0xCBF6C01A,):
            cx,cy,cz = _short_pos(p)
            buf += struct.pack('<hhh', cx, cy, cz)
            buf += struct.pack('<BB', _weight_byte(w[0]), b[0])
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),127)
            buf += struct.pack('BBBB',_norm_byte(t.x),_norm_byte(t.y),_norm_byte(t.z),127)
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('<BBBB',255,255,255,255)

        # === GROUP 8: 24 bytes, float3 pos, normal, 1 UV + optional 2nd UV/color ===
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

        # === GROUP 9: 26 bytes, short3 pos, normal, ?, 2x half2 uv, color ===
        elif fvf in (0x9399C037,):
            cx,cy,cz = _short_pos(p)
            buf += struct.pack('<hhh', cx, cy, cz)
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),0)
            buf += struct.pack('<I',0)
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('<BBBB',255,255,255,255)

        # === GROUP 10: 28 bytes, float3 pos, normal+tangent, 2x half2 uv ===
        elif fvf in (0x5E7F202C, 0x49B4F029):
            buf += struct.pack('<fff', fx, fy, fz)
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),0)
            buf += struct.pack('BBBB',_norm_byte(t.x),_norm_byte(t.y),_norm_byte(t.z),0)
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('<HH',h(u.x),h(u.y))

        # === GROUP 11: 28 bytes, 4 bones byte, short3 pos, normal+tangent, half2 uv + w2/w3 ===
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

        # === GROUP 12: 28 bytes, 2 bones half-float, short3 pos, normal+tangent, half2 uv, color ===
        elif fvf in (0xA013501E,):
            cx,cy,cz = _short_pos(p)
            buf += struct.pack('<hhh', cx, cy, cz)
            buf += struct.pack('<h', _weight_short(w[0]))
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),127)
            buf += struct.pack('BBBB',_norm_byte(t.x),_norm_byte(t.y),_norm_byte(t.z),127)
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('<HH',h(float(b[0])),h(float(b[1]) if len(b)>1 else float(b[0])))
            buf += struct.pack('<BBBB',255,255,255,255)

        # === GROUP 13: 28 bytes, short3 pos + 22B unknown ===
        elif fvf in (0x2BE814D4,0x7CD414D4,0x0D9E801D):
            cx,cy,cz = _short_pos(p)
            buf += struct.pack('<hhh', cx, cy, cz)
            buf += b'\x00' * 22

        # === GROUP 14: 28 bytes, short3 pos + 2B + N+T+binormal + 2x half2 uv ===
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

        # === GROUP 15: 32 bytes, 1 bone byte, short3 pos, normal+tangent, 2x half2 uv ===
        elif fvf in (0xD877801B,):
            cx,cy,cz = _short_pos(p)
            buf += struct.pack('<hhh', cx, cy, cz)
            # 游戏格式: +6 = 骨骼索引(0 基), +7 = 0（实测 49 个官方网格 +7 恒 0）
            # 旧版写成 (权重, 骨骼) → +6=255 被引擎当成骨骼 255（越界）→ 网格不显示
            buf += struct.pack('<BB', b[0], 0)
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),127)
            buf += struct.pack('BBBB',_norm_byte(t.x),_norm_byte(t.y),_norm_byte(t.z),127)
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += b'\x00\x00\x00\x00'
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += b'\x00\x00\x00\x00'

        # === GROUP 16: 32 bytes, 4 bones byte, short3 pos, normal+tangent, 2x half2 uv ===
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

        # === GROUP 17: 32 bytes, float3 pos, normal+tangent, 2x half2 uv, color ===
        elif fvf in (0x747D1031,0x9399C033,0xB86DE02A,0x12553032,0x926FD02E):
            buf += struct.pack('<fff', fx, fy, fz)
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),0)
            buf += struct.pack('BBBB',_norm_byte(t.x),_norm_byte(t.y),_norm_byte(t.z),0)
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('<BBBB',255,255,255,255)

        # === GROUP 18: 32 bytes, short3 pos + 26B unknown ===
        elif fvf in (0xA14E003C,):
            cx,cy,cz = _short_pos(p)
            buf += struct.pack('<hhh', cx, cy, cz)
            buf += b'\x00' * 26

        # === GROUP 19: 36 bytes, 2 bones half-float, short3 pos, normal+tangent, 2x half2 uv ===
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

        # === GROUP 20: 36 bytes, 8 bones→4, short3 pos, normal+tangent, half2 uv ===
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

        # === GROUP 21: 36 bytes, float3 pos, 2x half2 uv, normal, 2x uv ===
        elif fvf in (0x63B6C02F,):
            buf += struct.pack('<fff', fx, fy, fz)
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),0)
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += b'\x00' * 12

        # === GROUP 22: 36 bytes, short3 pos + unknown ===
        elif fvf in (0xB392101F,):
            cx,cy,cz = _short_pos(p)
            buf += struct.pack('<hhh', cx, cy, cz)
            buf += struct.pack('<H',0)
            buf += struct.pack('BBBB',_norm_byte(n.x),_norm_byte(n.y),_norm_byte(n.z),127)
            buf += struct.pack('BBBB',_norm_byte(t.x),_norm_byte(t.y),_norm_byte(t.z),127)
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += b'\x00' * 12

        # === GROUP 23: 40 bytes, 4 bones, short3 pos, normal+tangent, 2x half2 uv + w2/w3 ===
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

        # === GROUP 24: 40 bytes, short3 pos + 14B + half2 uv + 16B ===
        elif fvf in (0x75C3E025, 0xD84E3026):
            cx,cy,cz = _short_pos(p)
            buf += struct.pack('<hhh', cx, cy, cz)
            buf += b'\x00' * 14
            buf += struct.pack('<HH',h(u.x),h(u.y))
            buf += b'\x00' * 16

        # === GROUP 25: 48 bytes, 8 bones→4, short3 pos, normal+tangent, 2x uv ===
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

        # === GROUP 26: 68 bytes, 4 bones, short3 pos, normal+tangent(signed byte), half2 uv ===
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

        # === GROUP 27: 24 bytes, short3 pos + 10B + 2x half2 uv ===
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
    """判断 .mod 属于哪个平台格式.

    已知版本号:
        0x00D4 (212)  Monster Hunter Generations Ultimate (Switch) 等
        0x0101        MHGU / 部分 PC 版本
        0x00E5/0x00E6 3DS 移动端 —— 本插件已移除该支持
    返回 'mhgu' 或 None (不支持).
    """
    try:
        with open(filepath, 'rb') as f:
            magic = f.read(4)
            if magic != b'MOD\x00':
                return None
            ver = struct.unpack('<H', f.read(2))[0]
            if ver in (0xe5, 0xe6):
                return None          # 移动版/3DS 支持已移除
            # 其余已知的 MOD 版本都走 MHGU/桌面端解析路径
            return 'mhgu'
    except Exception:
        return None

def split_hidden_meshes(objs):
    """把物体列表拆成 (可见, 视口隐藏)。

    视口隐藏 = 眼睛图标 hide_get() 或 显示器图标 hide_viewport。
    MT_SkipHidden 打开时导出用这个过滤选中的网格。
    """
    keep, hidden = [], []
    for o in objs:
        try:
            hid = bool(o.hide_get())
        except Exception:                               # noqa: BLE001
            hid = False
        if hid or bool(o.hide_viewport):
            hidden.append(o)
        else:
            keep.append(o)
    return keep, hidden


def export_mod_file(filepath, game_fix="mhgu", template_path=None):
    """导出 .mod.

    **不覆盖原文件**: 输出一律写成 ``<你选的名字>.new``
    (例如选 ``f_body001.mod`` -> 实际生成 ``f_body001.mod.new``)。

    成功时返回**实际写入的路径**, 失败返回 None。
    """
    if filepath and not filepath.endswith(".new"):
        filepath = filepath + ".new"
    # ★ 1.2.185：导出前先按 .blend 内嵌的模板同步（分支工程不再串模板）
    try:
        from .MTframework_MHGU_tpl import sync as _tpl_sync
        _tpl_sync(bpy.context)
    except Exception:                                   # noqa: BLE001
        pass
    from .MTframework_MHGU_import import _last_import_path
    sv = bpy.context.scene.get('MT_LastImportPath', None)
    cand = [p for p in [template_path, _last_import_path, sv] if p and os.path.exists(p)]
    # 模板不能是 .new (那是我们自己的输出); 优先用导入过的原文件
    cand = [p for p in cand if not p.endswith(".new")]
    src = cand[0] if cand else (filepath if os.path.exists(filepath) else None)
    if not src:
        print("ERROR: No template")
        return None

    # Auto-detect format from source template
    fmt = _detect_mod_format(src)
    if fmt is None:
        print("ERROR: 不支持的 .mod 版本 (本插件只支持 MHGU / Switch)")
        return None

    # MHGU format (0x0101)
    with open(src, 'rb') as f:
        data = bytearray(f.read())
        # ★ 留一份**未被改写**的原始字节: 校验要拿它读模板的网格范围。
        # 导出在校验之前会重打包 MeshHeader, 从 data 读会失败 (实测)。
        _tpl_bytes = bytes(data)
    hdr = MODHeader(); hdr.marshall(BytesIO(data[6:6+58]))
    
    headers = []
    for i in range(hdr.meshCount):
        off = hdr.ptr_Mesh + i*48
        mh = MeshHeaderStruct(); mh.marshall(BytesIO(data[off:off+48]))
        headers.append(mh)

    sel = [o for o in bpy.context.selected_objects if o.type == 'MESH']

    # ★ 1.2.197：可选跳过「视口隐藏」的网格（眼睛图标 hide_get / 显示器图标 hide_viewport）。
    #   注意保持 1.2.192 的行为：跳过之后一个网格都没有时**仍然导出空模型**，不报错。
    _hidden_skipped = []
    if bool(getattr(bpy.context.scene, 'MT_SkipHidden', False)):
        sel, _hidden = split_hidden_meshes(sel)
        _hidden_skipped = [o.name for o in _hidden]
        if _hidden_skipped:
            print('NOTE: 导出跳过 %d 个视口隐藏的网格：%s'
                  % (len(_hidden_skipped), '、'.join(_hidden_skipped)))

    # ★ 1.2.200：导出前诊断。
    #
    # 1) 非骨骼顶点组（MMD 的 mmd_edge_scale / mmd_vertex_order 之类）会被丢掉，
    #    剩下的骨骼权重按 .mod 格式**归一化到 1**（w4 = 1-(w1+w2+w3)）。
    #    源工程骨骼权重只占一部分时，导出后每个顶点的权重会被放大 1/占比 倍 ——
    #    比例不变、游戏内变形不变，但数值会变"强"。这里提前打印出来。
    # 2) 本次导出 N 个网格 → M 个分件：网格多于分件就是被合并了，先让用户看见。
    try:
        _arms0 = [o for o in bpy.context.scene.objects if o.type == 'ARMATURE']
        if _arms0 and sel:
            # 选**骨名与顶点组重合最多**的骨架（场景里可能同时有 MMD 的 Armature 和 MT_Armature）
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
    except Exception as _e_wd:                          # noqa: BLE001
        print('NOTE: 权重/分件诊断跳过 (%s)' % _e_wd)

    # ★ 1.2.192：一个网格都没选时**就是导出空模型**（用户明确要这个行为：
    #   "不选直接导出空气就可以了"）。不自动换网格、也不拦，只打一行提示。
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
            # 名称替换会把原目标改名成 <名字>_OLD, 它的 Mesh_NNN 序号和新模型
            # 相同。冲突时必须保留**新模型**, 否则导出的是被替换掉的原件。
            sm[k] = o
    # 名字里没有 Mesh_NNN 的选中网格也允许导出（1.2.179）：按名字顺序占用模板里
    # 还空着的分件槽，**优先 0xEFFF 可见件**，其次按槽位顺序；每个都打印放进哪个槽。
    # 这样新建/复制/改名的网格不用先改成原分件名就能导出。
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

    new_vert = bytearray()
    new_face = bytearray()
    rb = 0; rf = 0
    _skipped_visible = []
    new_headers_list = []
    # 只导出**你选中的**网格 (按名字里的 Mesh_NNN 序号放进对应分件槽位)。
    # 未选中的原版分件**不会**被写出去 —— 否则它们会在游戏里跟着显示出来。
    _extra = [k for k in sorted(sm.keys()) if k >= len(headers)]
    if _extra:
        print("NOTE: 这些网格的序号超出模板分件数 (%d), 将套用最大的分件头: %s"
              % (len(headers), [sm[k].name for k in _extra]))

    for i in sorted(sm.keys()):
        obj = sm[i]
        if i < len(headers):
            _tpl = headers[i]
        else:
            # 序号超出模板范围时克隆一个分件头, 避免越界崩溃
            _tpl = max(headers, key=lambda h: h.vertCount)
            print("WARNING: 网格序号 %d 超出模板 (%d 个分件头), 克隆 FVF=0x%08X"
                  % (i, len(headers), _tpl.fvfInfo))
        vs = _tpl.vertStride; fvf = _tpl.fvfInfo

        md = obj.data; vc = len(md.vertices)

        # ---- UV 接缝拆点 ----
        #
        # .mod 的顶点格式是**一顶点一个 UV**, 表达不了 UV 接缝。
        # 但 Blender 的 UV 是逐 loop 的: 接缝处同一个顶点在不同面上 UV 不同。
        # 旧实现按顶点只取第一个 loop 的 UV (`vum.setdefault`), 接缝另一侧
        # 的面就会用错 UV —— **在 Blender 里看 UV 完全正常, 进游戏却有接缝处
        # 贴图错位/拉伸**, 这就是"UV 看起来没出界但进游戏出问题"的来源。
        #
        # 这里: 有接缝时按 (顶点, UV) 拆出额外顶点, 面索引改用 loop 映射;
        # 没有接缝时 `_split` 就是恒等表, 输出与旧版逐字节相同。
        _seam_split = False
        _split = list(range(vc))          # 新索引 -> 原顶点索引
        _split_uv = None                  # 新索引 -> (u, v) 已翻转 V
        _loop_vert = None                 # loop.index -> 新索引
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


        # stride对齐：保证当前mesh从 vs 整数倍偏移开始
        pad = (vs - (rb % vs)) % vs
        if pad > 0:
            new_vert += b'\x00' * pad
            rb += pad
        vs_start = rb // vs

        # 使用原版顶点数据(勾选后或顶点数没变)
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
        # 是否沿用原始顶点字节?
        #   * 勾了「使用原版顶点」 -> 强制沿用
        #   * 顶点数变了          -> 必须重新编码
        #   * FVF 不认识          -> 只能沿用
        #   * **顶点数据被改过**  -> 必须重新编码
        #     (旧版只看顶点数, 结果用户改的法向/位置/UV 全被丢掉,
        #      游戏里显示的还是原版法向 —— 这是本次修的 bug)
        _changed = vertex_data_modified(obj)
        _can_reencode = fvf in _known_fvfs
        if _changed and not _can_reencode:
            print("WARNING: Mesh %d FVF 0x%08x 不支持重新编码, 顶点修改会被忽略" % (i, fvf))
        _reencode = (not _use_orig) and _can_reencode and (
            _changed or not (vc == _tpl.vertCount))
        if not _reencode:
            src_off = hdr.ptr_vertex + _tpl.vertStart * vs + _tpl.vertBase
            vert_data = bytes(data[src_off:src_off + _tpl.vertCount * vs])
            new_vert += vert_data
            rb += len(vert_data)
        else:
            # 完整重新编码 (含法向)
            # 法向必须取**拆分法线**(loop normal), 才读得到用户在 Blender 里
            # 用自定义法线/法向编辑改过的结果; v.normal 是按几何重算的, 读不到。
            na = vertex_normals_file_space(obj)
            # 可选: 统一"位置重合"的顶点法线 (消除 UV 接缝处的光影断层)
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
            # 逐顶点切线: 用 UV 推导, 保证切线帧连续 (见 v1.6 说明)
            ta = vertex_tangents_file_space(obj)
            # 切线必须和**实际写出去的法线**正交 (na 是文件空间的最终法线,
            # 它与 Blender 的几何法线可能不同, 尤其是用了自定义法线时)
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

            # 顶点必须换算回**文件坐标**再写.
            # 导入时如果做过"居中", 场景里记录了一个平移量; 导出时减掉它,
            # 顶点的坐标系才会和文件里的骨骼一致 —— 否则进游戏后整体偏移
            # (典型症状: 骨骼数据与原始文件完全相同, 但模型整体错开半个身位).
            # ★ 用**这个对象自己**的居中平移量, 不是场景级累加值。
            # 场景值是累加的, 而每个对象只被居中过一次 —— 用场景值会让
            # "没参与过居中的对象"(例如后来新建/额外导入的网格)被整体平移。
            # 实测你的工程里就有这种: 7 个网格, 6 个 matrix_world == coff,
            # 1 个 == (0,0,0)。
            _coff = get_object_center_offset(obj, bpy.context.scene)
            _mw = obj.matrix_world.copy()

            # ---- 顶点取自**形变后**的网格 ----
            #
            # 你在**编辑模式**挪骨骼时, Blender 视口显示的是骨架修改器形变后的
            # 形状; 而 `md.vertices[i].co` 是**静止**位置 —— 两者不是一回事。
            # 旧实现导出静止顶点, 于是游戏在绑定姿态下画出来的是**未形变**的
            # 样子, 和你在 Blender 里看到的不一致 (表现就是"权重/形变对不上")。
            #
            # 改成取 evaluated 网格后, 你看到的形状被烘焙进顶点, 而骨架又按你
            # 编辑后的位置写出 —— 两者一致, 动画从正确的绑定姿态出发。
            #
            # 没有改动时 evaluated 与静止完全相同, 所以
            # "未改动模型导出与原件逐字节一致"这条保证仍然成立。
            _pos = None
            try:
                _dg = bpy.context.evaluated_depsgraph_get()
                _ev = obj.evaluated_get(_dg)
                _em = _ev.to_mesh()
                if _em is not None:
                    # 顶点数必须一致才用 (有细分/镜像这类改拓扑的修改器时不用)
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
                """顶点 → 文件坐标 (Blender X→X, Z→Y, -Y→Z)."""
                w = _pos[i]
                return Vector((w.x, w.z, -w.y))


            def gp(i):
                return _file_space(_split[i])
            def gu(i):
                # UV 原样写出 (半精度足够表示): 不再因为"某个 UV > 1.5"就把
                # 整张 UV 图整体乘以 0.5 —— 旧代码的这个启发式会让导出的
                # UV 整体偏移/缩放, 表现为"UV 变奇怪".
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
                # 真实切线 (v1.6): UV 推导 + 对法线正交化。
                # 旧写法 "随便叉一个垂直轴" 会让相邻顶点选到不同轴 -> 切线帧跳变
                # -> 游戏里光照/法线贴图花掉。
                _i = _split[i]
                if _i < len(ta):
                    return ta[_i]
                n = gn(i)
                for ax in [Vector((1,0,0)), Vector((0,1,0)), Vector((0,0,1))]:
                    t = ax.cross(n)
                    if t.length > 0.001: t.normalize(); return t
                return Vector((1,0,0))
            def gsk(i):
                # 骨骼影响数 (v1.5 修正):
                # 旧代码写死 b=b[:2]; w=w[:2] —— 只保留权重最大的 2 根骨骼并重新
                # 归一化。但 0x14D40022 这类 FVF **支持 4 根骨骼** (b1..b4 + w1,w2,w3)。
                # 四肢顶点通常是 3~4 根骨骼混合, 被截成 2 根后形变完全变样 ——
                # 表现就是"进游戏四肢扭曲, 而头部/躯干没事"(那里多是单骨骼权重)。
                # 这里保留最多 4 根, 由 _write_vbuf 按各 FVF 实际支持的数量写入。
                b, w = get_skin_weights(obj, _split[i])
                # ★ 只保留能对上骨骼的组（MMD 元数据组/对不上的骨名直接丢），
                #   否则它们会按组下标写成别的骨，权重整体错位。
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
                # 补齐到 4, 不足的用 0 权重
                while len(b) < 4:
                    b.append(b[-1])
                while len(w) < 4:
                    w.append(0.0)
                return (b, w)
            # 位置范围检查: .mod 顶点是 int16/32767, 只能表达 [-1, 1]。
            # 超出会被钳到 ±1 (模型顶部/侧面被压扁, 就是"Z 超过 1 被截掉"的
            # 现象)。这里提前扫描并警告, 给出建议缩放倍数。
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
            # ★ 1.2.196：权重精简诊断（与 FVF 无关，按源顶点扫一遍）。
            #   依据第三方外观工坊的做法：每顶点最多保留 4 根骨，并报告被丢弃的权重
            #   （他们实测最大丢弃 0.00484）。导出本来就截到 4 根，但以前是静默截断，
            #   模型被拉变形也看不出来。
            try:
                _over = 0
                _mx = 0.0
                for _vi in range(len(md.vertices)):
                    _b0, _w0 = get_skin_weights(obj, _vi)
                    _pr = [ww for xx, ww in zip(_b0, _w0) if xx in bm and ww > 0.0]
                    if len(_pr) > 4:
                        _tot = sum(_pr)
                        if _tot > 0.0:
                            _over += 1
                            _d = 1.0 - sum(sorted(_pr, reverse=True)[:4]) / _tot
                            if _d > _mx:
                                _mx = _d
                if _over:
                    print('NOTE: 网格 %s 权重精简：%d 个顶点超过 4 根骨，'
                          '最大丢弃权重 %.4f（导出按前 4 根归一化）'
                          % (obj.name, _over, _mx))
            except Exception as _e_w:                # noqa: BLE001
                print('[MT] 权重诊断跳过：%s' % _e_w)
            vert_data = _write_vbuf(fvf, _vc_out, gp, gu, gn, gt, gsk, vs)
            new_vert += vert_data
            rb += len(vert_data)

        # 面朝向 (v1.4): **导出时固定翻转一次三角形缠绕**。
        #
        # 实测结论: 不管模型是从 .mod 导入的、还是第三方模型(自己建的 / MMD),
        # 只要按 Blender 里的正确朝向直接导出, 进游戏都会内外翻转, 必须手动
        # Flip Normals 才正常。所以这里直接写翻转后的顺序 (v0,v1,v2);
        # 原来的 (v1,v0,v2) 就是那个"需要在 Blender 里手动翻一遍"的写法。
        # 不再做成开关 —— 固定翻转即可, 没有需要不翻转的场景。
        fc = 0
        for poly in md.polygons:
            # 有 UV 接缝时, 顶点被按 (顶点, UV) 拆成多份, 面索引必须走 loop
            # 映射才对得上; 没有接缝时 `_loop_vert` 是 None, 走原来的顶点索引,
            # 输出与旧版逐字节相同。
            _li = poly.loop_indices if _loop_vert is not None else None
            for j in range(len(poly.vertices) - 2):
                if _li is not None:
                    v0 = _loop_vert[_li[0]] + vs_start
                    v1 = _loop_vert[_li[j + 1]] + vs_start
                    v2 = _loop_vert[_li[j + 2]] + vs_start
                else:
                    v0 = poly.vertices[0] + vs_start
                    v1 = poly.vertices[j + 1] + vs_start
                    v2 = poly.vertices[j + 2] + vs_start
                if fc > 0:
                    new_face += struct.pack('<H', 0xFFFF); fc += 1
                new_face += struct.pack('<HHH', v0, v1, v2)
                fc += 3

        mh = MeshHeaderStruct()
        for attr in ['meshtype','unk01','MatId','lodLevel','unk04','vertFlag',
                     'vertStride','unk05','fvfInfo','bonemapindex','weightmaps',
                     'unk07','unk08','unk09']:
            setattr(mh, attr, getattr(_tpl, attr))
        try:
            if getattr(bpy.context.scene.MT_Framework_Props, 'all_visible', False):
                # 只有带 UV/法线的分件（步长 >= 20）才适合当可见件。
                # 步长 12/16 的是纯位置数据（深度 pass），强行可见会画成黑块。
                if getattr(_tpl, 'vertStride', 0) >= 20:
                    mh.meshtype = 0xEFFF
                else:
                    _skipped_visible.append(i)
        except Exception:
            pass
        mh.vertCount=_vc_out; mh.faceCount=fc
        mh.vertStart=vs_start; mh.vertBase=0
        mh.faceStart=rf; mh.faceBase=0
        mh.min_index=vs_start; mh.max_index=vs_start+_vc_out-1 if _vc_out>0 else 0
        new_headers_list.append(mh); rf+=fc

    if _skipped_visible:
        print("NOTE: 这些分件是纯深度件（无 UV/法线），没有强行设成可见: %s"
              % [i + 1 for i in _skipped_visible])

    # ★ 1.2.199：顶点区 + 三角区**紧凑重建**。
    #
    # 旧写法：顶点原地覆盖模板（保留模板 vertexBufferSize 的剩余空间），
    # 新索引区**追加到文件尾**、ptr_triangle 指到文件尾 —— 旧的索引区留在原地。
    # 每导出一次就多一个索引区的死字节：
    # 实测 伊莎贝娜 body → 首次 1,885,398B → 重导一次 2,431,864B
    # (+546,466 = 索引区 546,462 + 4)。顶点/权重/索引内容本身逐字节相同。
    #
    # 现在：prefix 到 ptr_vertex 原样保留（骨骼/材质/分件头都在它之前），
    # 后面按「顶点 + 模板原有 padding + 索引 + 4 个 0」重建。
    # padding 取模板的 (vertexBufferSize - 模板顶点字节)，
    # 这样「什么都不改的导出」仍与模板逐字节相同。
    _tpl_used = 0
    for _mh0 in headers:
        _tpl_used += int(_mh0.vertCount) * int(_mh0.vertStride)
    _pad = int(hdr.vertexBufferSize) - _tpl_used
    if _pad < 0:
        _pad = 0
    _new = bytearray(data[:hdr.ptr_vertex])
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
    struct.pack_into('<I', data, 24, npt - hdr.ptr_vertex)

    # Overwrite mesh headers
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
    except Exception:                                   # noqa: BLE001
        pass
    struct.pack_into('<I', data, 12, total_vc)

    # ---- 骨骼回写 ----
    #
    # 1.1.7 原本**没有这一步**: 骨骼段整段照抄模板文件, 所以你在 Blender 里
    # 怎么改骨骼, 写出来的骨架都不变。
    #
    # 失败时明确打印原因, 但**不中止导出** —— 顶点/材质仍然会写出。
    _plan = None
    _arm = None
    try:
        from . import MTframework_MHGU_bones as _BONES
        _arms = [o for o in bpy.context.scene.objects if o.type == 'ARMATURE']
        # 评分用**各自骨架**的对照表 (场景级那份可能被别的导入覆盖)
        _arm, _why = _BONES.find_armature(_arms, hdr.boneCount, None)
        if _arm is None:
            print("NOTE: 跳过骨骼回写 —— %s (骨骼段将保持模板原样)" % _why)
        else:
            # 当前网格相对文件坐标的最低点 —— 锚定判据要用 (见 plan_bone_write)
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
                # 骨架也可能有自己那份平移量 (它参与过居中时)
                offset=get_object_center_offset(_arm, bpy.context.scene),
                template_bytes=_tpl_bytes,
                cur_mesh_min_y=_cur_mesh_y,
                # ★ 锚定**默认关闭**。
                #
                # 试过, 但被数据否掉了: 它是"整副骨架刚性平移", 只能保住
                # 整体位置, 保不住"用户只挪了某一根骨骼"这种形状改动 ——
                # 实测编辑模式只挪根骨时, 锚定把没动过的子骨也推离原位,
                # 相对关系反而从 0 变成 +0.10。
                # 而且用户的实机实验 (整体上移、游戏里高度不变) 说明游戏
                # **不按骨架绝对位置定位**, 锚定的前提本身站不住。
                #
                # 所以: 导出忠实反映你的编辑, 有问题由导出校验**报出来**,
                # 不在这里悄悄改。
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

    # ---- 导出校验 (只报, 不改数据) ----
    try:
        from . import MTframework_MHGU_bones as _B2
        # ★ 必须用**导出实际写的那些网格** (sm 是按网格序号去重后的表),
        # 不能用 sel —— 没选中任何东西时 sel 是空的, 校验会静默通过 (实测过)。
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
        print("  骨架相对模板挪动 %.5f 文件单位"
              % _info.get('bone_delta', 0.0))
        if _info.get('amat_c') is not None:
            # 三份同步判据: amat_t + p_world 应恒等于常量 C (第三方 skill 包结论)
            print("  骨骼三份同步 amat+p_world=C  C=(%+.3f, %+.3f, %+.3f)  偏差 %.6f"
                  % (_info['amat_c'] + (_info.get('amat_spread', 0.0),)))
        if _info.get('rel_delta') is not None:
            # 最要紧的一条: 网格最低点 相对于 最低骨骼 的这个量必须保持
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
