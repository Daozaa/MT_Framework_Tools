# -*- coding: utf-8 -*-
"""碰撞胶囊 CCL（v2，2026-11-17 依据第三方「外观工坊」实机验证结果重做）。

格式（官方 helm/hair arc 里的 CCL 条目，实测 100% 一致）
------------------------------------------------------
    0x00  'CCL\0'
    0x04  u32 版本 0x00080618
    0x08  u32 胶囊数 n
    0x0C  u32 n * 64
    0x10  记录[0] ... 记录[n-1]，每条 64 字节：
          +0x00 u32 = 1
          +0x04 u16 骨 A 的 id（玩家骨架 0~19）
          +0x06 u16 骨 B 的 id
          +0x08 u8  = 1（启用）
          +0x10 3f  起点（相对骨 A 世界矩阵的局部坐标）
          +0x20 3f  终点（相对骨 B 世界矩阵的局部坐标）
          +0x2C f   半径（游戏单位）

**生效条件（实测，2026-11-17）**
1. CCL 只能放在 **helm / hair 槽**的 arc 里（main 只为槽 4/5 查 CCL）；
   body/wst/arm/leg 槽的同名 CCL 完全不生效 —— 以前放弃就是因为写进了 body。
2. CTC 每个物理组 +4 的标志位要带 **0x04**（0x2300 -> 0x2304），否则求解器不跑碰撞。
3. 胶囊坐标是「相对骨骼世界矩阵的局部坐标」，半径是游戏单位（和 .mod 骨矩阵同尺度）。
"""
from __future__ import annotations

import json
import struct
import zlib

CCL_MAGIC = b'CCL\0'
CCL_HASH = 0x0026E7FF
CCL_VERSION = 0x00080618
REC_SZ = 64
HEADER_SZ = 16
DEFAULT_HEIGHT = 160.0

# 官方 11 胶囊「身体体积」模板（来自外观工坊 collision.build 的默认 profile）：
# (骨A, 骨B, 半径系数) —— 坐标由骨骼世界位置 + height/160 缩放推出。
BODY_PROFILE = [
    (0, 2, 10.0), (3, 4, 6.0),
    (6, 7, 4.2), (10, 11, 4.2), (7, 8, 4.2), (11, 12, 4.2),
    (14, 15, 6.0), (17, 18, 6.0), (15, 16, 4.0), (18, 19, 4.0),
]


def build_ccl(capsules):
    """capsules: [{'a':int,'b':int,'start':(x,y,z),'end':(x,y,z),'radius':float}]"""
    n = len(capsules)
    out = bytearray(HEADER_SZ + REC_SZ * n)
    out[0:4] = CCL_MAGIC
    struct.pack_into('<3I', out, 4, CCL_VERSION, n, n * REC_SZ)
    for i, c in enumerate(capsules):
        o = HEADER_SZ + i * REC_SZ
        struct.pack_into('<I', out, o, 1)
        struct.pack_into('<HH', out, o + 4, int(c['a']) & 0xFFFF, int(c['b']) & 0xFFFF)
        out[o + 8] = 1
        struct.pack_into('<3f', out, o + 0x10, *[float(v) for v in c['start']])
        struct.pack_into('<3f', out, o + 0x20, *[float(v) for v in c['end']])
        struct.pack_into('<f', out, o + 0x2C, float(c['radius']))
    return bytes(out)


def parse_ccl(data):
    if data[:4] != CCL_MAGIC:
        raise ValueError('不是 CCL 条目')
    ver, n, size = struct.unpack_from('<3I', data, 4)
    if ver != CCL_VERSION:
        raise ValueError('CCL 版本 0x%08X 不认识' % ver)
    if size != n * REC_SZ or len(data) != HEADER_SZ + size:
        raise ValueError('CCL 长度不对（count=%d size=%d len=%d）' % (n, size, len(data)))
    out = []
    for i in range(n):
        o = HEADER_SZ + i * REC_SZ
        a, b = struct.unpack_from('<HH', data, o + 4)
        out.append({
            'a': a, 'b': b, 'enabled': bool(data[o + 8]),
            'start': struct.unpack_from('<3f', data, o + 0x10),
            'end': struct.unpack_from('<3f', data, o + 0x20),
            'radius': struct.unpack_from('<f', data, o + 0x2C)[0],
        })
    return out


def capsules_from_json(text):
    """场景属性 MT_CclCapsules 的 JSON -> 胶囊列表（无效条目/整段坏掉返回 []）。

    [{"a": 骨id, "b": 骨id, "start": [x, y, z], "end": [x, y, z], "radius": 30.0}, ...]
    坐标是骨骼局部坐标（世界单位，和 body_capsules() 的输出同尺度，不乘去量化 S）。
    """
    if not text:
        return []
    try:
        data = json.loads(text)
    except Exception:                                   # noqa: BLE001
        print('[MT] 自定义胶囊 JSON 解析失败，改用自动胶囊')
        return []
    if not isinstance(data, list):
        return []
    out = []
    for c in data:
        if not isinstance(c, dict):
            continue
        try:
            a = int(c.get('a', 0))
            b = int(c.get('b', 0))
            st = [float(v) for v in c.get('start', (0.0, 0.0, 0.0))]
            en = [float(v) for v in c.get('end', (0.0, 0.0, 0.0))]
            r = float(c.get('radius', 0.0))
        except (TypeError, ValueError):
            continue
        if len(st) != 3 or len(en) != 3:
            continue
        out.append({'a': a, 'b': b, 'start': tuple(st), 'end': tuple(en),
                    'radius': r})
    return out


def capsules_to_json(capsules):
    """胶囊列表 -> 场景属性文本（和 capsules_from_json 互逆）。"""
    return json.dumps([{'a': int(c['a']), 'b': int(c['b']),
                        'start': [float(v) for v in c['start']],
                        'end': [float(v) for v in c['end']],
                        'radius': float(c['radius'])} for c in capsules])


def find_ccl(entries):
    for e in entries:
        if e.get('hash') == CCL_HASH or e.get('body', b'')[:4] == CCL_MAGIC:
            return e
    return None


def apply_to_entries(entries, name, body):
    """写入/替换（body=None 表示删除）。官方顺序：... CTC, CCL, XFS。"""
    cur = find_ccl(entries)
    if body is None:
        if cur is not None:
            entries.remove(cur)
        return False
    flag = 0x40000000 | (len(body) & 0xFFFFFF)
    raw = zlib.compress(body, 9)
    if cur is not None:
        entries.remove(cur)
    new_e = dict(name=name, hash=CCL_HASH, flag=flag, raw=raw, body=body)
    xfs_i = next((i for i, e in enumerate(entries)
                  if e.get('body', b'')[:4] == b'XFS\x00'), None)
    if xfs_i is not None:
        entries.insert(xfs_i, new_e)
    else:
        ctc_i = next((i for i, e in enumerate(entries)
                      if e.get('body', b'')[:4] == b'CTC\x00'), None)
        entries.insert(ctc_i + 1 if ctc_i is not None else len(entries), new_e)
    return True


def enable_collision_flags(ctc_bytes):
    """CTC 每个物理组 +4 的 flags 打开 0x04（碰撞求解开关）。返回 (新bytes, 改组数)。"""
    if not ctc_bytes or ctc_bytes[:4] != b'CTC\0' or len(ctc_bytes) < 0x3C:
        return ctc_bytes, 0
    ng = struct.unpack_from('<I', ctc_bytes, 0x10)[0]
    data = bytearray(ctc_bytes)
    n = 0
    for i in range(ng):
        o = 0x3C + i * 80 + 4
        if o + 4 > len(data):
            break
        v = struct.unpack_from('<I', data, o)[0]
        if not (v & 0x04):
            struct.pack_into('<I', data, o, v | 0x04)
            n += 1
    return bytes(data), n


def collision_flags_on(ctc_bytes):
    if not ctc_bytes or ctc_bytes[:4] != b'CTC\0':
        return False
    ng = struct.unpack_from('<I', ctc_bytes, 0x10)[0]
    for i in range(ng):
        o = 0x3C + i * 80 + 4
        if o + 4 > len(ctc_bytes):
            break
        if not (struct.unpack_from('<I', ctc_bytes, o)[0] & 0x04):
            return False
    return ng > 0


# ----------------------------------------------------------------- 从 .mod 生成
def _bone_worlds(mod_bytes):
    """读 .mod 骨骼段：返回 ([(id, 4x4 世界矩阵)], 去量化尺度)。

    ★ .mod 的世界矩阵 3x3 里带着**顶点去量化系数 S**（body 193.46 / helm 99.27），
    但矩阵平移是**世界单位**。CCL 的局部坐标用的是「只有旋转+平移」的骨骼矩阵
    （官方 helm 的 CCL 起点 20/-8/22、半径 30 就是世界单位），所以这里把 3x3 除以 S
    归一化，否则算出来的局部坐标会小 S 倍。
    """
    import numpy as np
    from .MTframework_MHGU_bones import read_bone_section, bone_section_offsets
    n = struct.unpack_from('<H', mod_bytes, 6)[0]
    ptr = struct.unpack_from('<I', mod_bytes, 36)[0]
    sec = read_bone_section(mod_bytes, ptr, n)
    _, _, world_off, _ = bone_section_offsets(ptr, n)
    S = float(sec['scale']) or 1.0
    out = []
    for i in range(n):
        m = np.array(struct.unpack_from('<16f', mod_bytes, world_off + i * 64),
                     dtype=np.float64).reshape(4, 4).T     # 列主序 -> 行主序
        m = m.copy()
        m[:3, :3] /= S                                # 去掉顶点去量化系数
        out.append((sec['infos'][i]['ID'], m))
    return out, S


def body_capsules(mod_bytes, height=None):
    """按官方 11 胶囊模板，从 .mod 的骨骼世界矩阵生成身体胶囊。

    坐标全部在文件空间（游戏单位），返回可直接 build_ccl 的列表。
    """
    import numpy as np
    worlds, scale = _bone_worlds(mod_bytes)
    pos = {bid: m[:3, 3] for bid, m in worlds}
    mats = {bid: m for bid, m in worlds}
    if not pos:
        return []

    if height is None:
        ys = [p[1] for p in pos.values()]
        height = (max(ys) - min(ys)) if ys else DEFAULT_HEIGHT
    s = float(height) / DEFAULT_HEIGHT

    def p(i, fallback=None):
        if i in pos:
            return pos[i]
        if fallback is not None and fallback in pos:
            return pos[fallback]
        return pos[min(pos)]

    hip = p(1, 0)
    chest = hip + np.array([0.0, p(3, 1)[1] - hip[1] - 10.1 * s, -s])

    raw = []
    raw.append((0, 2, hip + np.array([0.0, 2 * s, -s]), chest, 10 * s))
    raw.append((3, 4, p(3, 1) + np.array([0.0, 1.9 * s, 2.5 * s]),
                p(4, 2) + np.array([0.0, 3.1 * s, -s]), 6 * s))
    for a, b in ((6, 7), (10, 11), (7, 8), (11, 12)):
        raw.append((a, b, p(a, 0), p(b, 0), 4.2 * s))
    raw.append((0, 0, hip + np.array([0.0, -7 * s, -s]),
                hip + np.array([0.0, -18 * s, -s]), 10 * s))
    for a, b, r in ((14, 15, 6.0), (17, 18, 6.0), (15, 16, 4.0), (18, 19, 4.0)):
        raw.append((a, b, p(a, 0), p(b, 0), r * s))

    caps = []
    for a, b, pa, pb, r in raw:
        if a not in mats or b not in mats:
            continue
        la = np.linalg.inv(mats[a]) @ np.r_[pa, 1.0]
        lb = np.linalg.inv(mats[b]) @ np.r_[pb, 1.0]
        caps.append({'a': int(a), 'b': int(b),
                     'start': tuple(float(v) for v in la[:3]),
                     'end': tuple(float(v) for v in lb[:3]),
                     'radius': float(r)})
    return caps
