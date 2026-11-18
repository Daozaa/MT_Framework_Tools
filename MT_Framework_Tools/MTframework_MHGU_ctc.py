# -*- coding: utf-8 -*-
"""MHGU 物理骨骼数据（CTC / uCnsTinyChain）读写。

结构（2026-10-24 逆向，见 PHYSICS_CTC.md）：

    0x00  "CTC\\0"
    0x04  u32 模型骨数
    0x0C  u32 1000
    0x10  u32 chain 数
    0x14  u32 node 总数
    0x1C  f32 1/60
    0x50  链组参数区（单链 60 字节；多链布局未完全解析，按原始字节保留）
    之后  每 node 96 字节：
        +0x00 u16 骨 id, u16 flags
        +0x04 u32 标志（0x01010001）
        +0x08 f32 质量/关节缩放（5.0）
        +0x0C u32 填充 0xCDCDCDCD
        +0x10 4x4 f32 矩阵
        +0x50 f32 角度上限
        +0x54 f32 1.0
        +0x58 f32 1.0
        +0x5C u32 填充

设计要点：**原样保留无法解释的字节**，只在已知偏移上改（骨 id / 矩阵 / 角度），
保证「读进来再写出去」逐字节一致 —— 这是能安全改物理数据的前提。
"""
from __future__ import annotations

import struct

MAGIC = b'CTC\x00'
HEADER_SIZE = 0x50
NODE_SIZE = 96


def _looks_like_node(d: bytes, off: int) -> bool:
    if off + NODE_SIZE > len(d):
        return False
    bid, flags = struct.unpack_from('<HH', d, off)
    u4 = struct.unpack_from('<I', d, off + 4)[0]
    mass = struct.unpack_from('<f', d, off + 8)[0]
    return (1 <= bid <= 40 and flags in (0, 1) and u4 in (0x01010001, 0x00010001)
            and 0.0 < mass < 1000.0)


class CtcNode:
    __slots__ = ('offset', 'bone_id', 'flags', 'u4', 'mass', 'matrix',
                 'angle', 'a2', 'a3', 'raw')

    def __init__(self, offset=0, bone_id=0, flags=0, u4=0x01010001, mass=5.0,
                 matrix=None, angle=0.0, a2=1.0, a3=1.0, raw=b''):
        self.offset = offset
        self.bone_id = bone_id
        self.flags = flags
        self.u4 = u4
        self.mass = mass
        self.matrix = list(matrix) if matrix else [1.0, 0.0, 0.0, 0.0,
                                                   0.0, 1.0, 0.0, 0.0,
                                                   0.0, 0.0, 1.0, 0.0,
                                                   0.0, 0.0, 0.0, 1.0]
        self.angle = angle
        self.a2 = a2
        self.a3 = a3
        self.raw = bytearray(raw)

    def pack(self):
        b = bytearray(self.raw) if self.raw else bytearray(NODE_SIZE)
        struct.pack_into('<HH', b, 0, self.bone_id, self.flags)
        struct.pack_into('<I', b, 4, self.u4)
        struct.pack_into('<f', b, 8, self.mass)
        struct.pack_into('<16f', b, 16, *self.matrix)
        struct.pack_into('<f', b, 80, self.angle)
        struct.pack_into('<f', b, 84, self.a2)
        struct.pack_into('<f', b, 88, self.a3)
        return bytes(b)


class Ctc:
    def __init__(self):
        self.raw = b''
        self.header = bytearray(HEADER_SIZE)
        self.mid = b''            # 0x50 到第一个 node 之间的字节
        self.tail = b''           # 最后一个 node 之后的字节
        self.nodes = []
        self.bone_count = 0
        self.chain_count = 0
        self.node_count = 0

    # ---------------- 解析 ----------------
    @classmethod
    def parse(cls, data: bytes) -> 'Ctc':
        if data[:4] != MAGIC:
            raise ValueError('不是 CTC 文件')
        c = cls()
        c.raw = bytes(data)
        c.header[:] = data[:HEADER_SIZE]
        c.bone_count, c.chain_count, c.node_count = (
            struct.unpack_from('<I', data, 0x04)[0],
            struct.unpack_from('<I', data, 0x10)[0],
            struct.unpack_from('<I', data, 0x14)[0],
        )
        # 找第一个 node
        first = None
        for off in range(HEADER_SIZE, min(len(data) - NODE_SIZE, HEADER_SIZE + 0x200), 4):
            if _looks_like_node(data, off):
                first = off
                break
        if first is None:
            c.mid = data[HEADER_SIZE:]
            return c
        c.mid = data[HEADER_SIZE:first]
        off = first
        while _looks_like_node(data, off):
            blk = data[off:off + NODE_SIZE]
            bid, flags = struct.unpack_from('<HH', blk, 0)
            u4 = struct.unpack_from('<I', blk, 4)[0]
            mass = struct.unpack_from('<f', blk, 8)[0]
            mat = struct.unpack_from('<16f', blk, 16)
            angle = struct.unpack_from('<f', blk, 80)[0]
            a2 = struct.unpack_from('<f', blk, 84)[0]
            a3 = struct.unpack_from('<f', blk, 88)[0]
            c.nodes.append(CtcNode(off, bid, flags, u4, mass, mat, angle, a2, a3, blk))
            off += NODE_SIZE
        c.tail = data[off:]
        return c

    # ---------------- 生成 ----------------
    def encode(self) -> bytes:
        hdr = bytearray(self.header)
        struct.pack_into('<I', hdr, 0x04, self.bone_count)
        struct.pack_into('<I', hdr, 0x10, self.chain_count)
        struct.pack_into('<I', hdr, 0x14, self.node_count or len(self.nodes))
        out = bytearray(hdr)
        out += self.mid
        for n in self.nodes:
            out += n.pack()
        out += self.tail
        return bytes(out)

    @property
    def roundtrip_ok(self):
        return self.encode() == self.raw

    # ---------------- 操作 ----------------
    def set_bone_ids(self, ids):
        for node, bid in zip(self.nodes, ids):
            node.bone_id = bid
        return self

    def clone(self):
        c = Ctc()
        c.raw = self.raw
        c.header = bytearray(self.header)
        c.mid = self.mid
        c.tail = self.tail
        c.bone_count = self.bone_count
        c.chain_count = self.chain_count
        c.node_count = self.node_count
        c.nodes = [CtcNode(n.offset, n.bone_id, n.flags, n.u4, n.mass, n.matrix,
                           n.angle, n.a2, n.a3, n.raw) for n in self.nodes]
        return c


def parse_file(path):
    with open(path, 'rb') as f:
        return Ctc.parse(f.read())


def write_file(ctc: Ctc, path):
    with open(path, 'wb') as f:
        f.write(ctc.encode())

def filter_nodes(data: bytes, keep_ids) -> bytes:
    """只保留「节点骨 id 全部在 keep_ids 里」的链组。

    CTC 引用了模型里不存在的骨 → 游戏里链条会去拽一根空骨，表现为乱飞/不显示。
    返回新的 CTC 字节（链表/节点表重排，header 的链数/节点数同步改）。
    """
    if not data or data[:4] != MAGIC:
        return data
    keep = {int(x) for x in keep_ids}
    n_g = struct.unpack_from('<I', data, 0x10)[0]
    n_c = struct.unpack_from('<I', data, 0x14)[0]
    if n_g > 64 or n_c > 4096:
        return data
    g_off = 0x3C
    c_off = g_off + 80 * n_g
    if len(data) < c_off + 96 * n_c:
        return data
    groups = []
    nodes = []
    idx = 0
    for g in range(n_g):
        raw = bytes(data[g_off + 80 * g: g_off + 80 * (g + 1)])
        cnt = struct.unpack_from('<I', raw, 0)[0]
        if cnt <= 0 or idx + cnt > n_c:
            break
        grp_nodes = [bytes(data[c_off + 96 * k: c_off + 96 * (k + 1)])
                     for k in range(idx, idx + cnt)]
        idx += cnt
        ids = [struct.unpack_from('<H', nd, 0)[0] for nd in grp_nodes]
        if all(i in keep for i in ids):
            groups.append(raw)
            nodes.extend(grp_nodes)
    if not groups:
        print('[MT] CTC 过滤：所有链组都引用了不存在的骨，整份丢弃')
        return b''
    if len(groups) != n_g:
        print('[MT] CTC 过滤：丢掉了 %d/%d 组（引用不存在的骨）'
              % (n_g - len(groups), n_g))
    hdr = bytearray(data[:g_off])
    struct.pack_into('<I', hdr, 0x10, len(groups))
    struct.pack_into('<I', hdr, 0x14, len(nodes))
    tail_start = c_off + 96 * n_c
    return bytes(hdr) + b''.join(groups) + b''.join(nodes) + bytes(data[tail_start:])

def check_topology(mod_bytes: bytes, ctc_bytes: bytes):
    """检查 CTC 与 .mod 骨骼是否自洽，返回问题列表（空 = 正常）。

    检查项：
      1. 节点骨 id 是否都存在
      2. 节点总数是否等于物理骨（id>=20）数量
      3. 每条链内部是否满足「后一个节点的骨，父是前一个节点」
         —— 不满足说明 CTC 是另一副骨架/另一条链搬过来的，游戏里会拽错骨。
    """
    problems = []
    if not ctc_bytes or ctc_bytes[:4] != MAGIC:
        return ['没有 CTC']
    if not mod_bytes or mod_bytes[:4] != b'MOD\x00':
        return ['没有 .mod']
    n = struct.unpack_from('<H', mod_bytes, 6)[0]
    ptr = struct.unpack_from('<I', mod_bytes, 36)[0]
    slot_id = {i: mod_bytes[ptr + i * 24] for i in range(n)}
    parent = {}
    for i in range(n):
        ps = mod_bytes[ptr + i * 24 + 1]
        parent[slot_id[i]] = slot_id.get(ps, 255)
    phys = sorted(i for i in slot_id.values() if i >= 20)

    n_g = struct.unpack_from('<I', ctc_bytes, 0x10)[0]
    n_c = struct.unpack_from('<I', ctc_bytes, 0x14)[0]
    g_off = 0x3C
    c_off = g_off + 80 * n_g
    if len(ctc_bytes) < c_off + 96 * n_c:
        return ['CTC 长度不足（头部 %d 节点）' % n_c]

    if n_c != len(phys):
        problems.append('CTC 节点 %d 个，而物理骨有 %d 根（%s）'
                        % (n_c, len(phys), phys))

    idx = 0
    for g in range(n_g):
        cnt = struct.unpack_from('<I', ctc_bytes, g_off + 80 * g)[0]
        if cnt <= 0 or idx + cnt > n_c:
            problems.append('链组 %d 的节点数异常（%d）' % (g, cnt))
            break
        base = idx
        ids = [struct.unpack_from('<H', ctc_bytes, c_off + 96 * (base + j))[0]
               for j in range(cnt)]
        idx += cnt
        for b in ids:
            if b not in slot_id.values():
                problems.append('链 %d 引用了不存在的骨 id=%d' % (g, b))
        for a, b in zip(ids, ids[1:]):
            if parent.get(b) != a:
                problems.append('链 %d 顺序不对：%d→%d，但骨 %d 的父是 %d'
                                % (g, a, b, b, parent.get(b, 255)))
        # 矩阵必须是正交旋转（官方 1217/1217 满足）：引擎只取其中一行当摆动轴，
        # 缩放/剪切/镜像（det=-1）会让摆动方向歪或直接翻。
        for j in range(cnt):
            m = struct.unpack_from('<16f', ctc_bytes, c_off + 96 * (base + j) + 16)
            r0, r1, r2 = m[0:3], m[4:7], m[8:11]
            l0 = sum(v * v for v in r0) ** 0.5
            l1 = sum(v * v for v in r1) ** 0.5
            l2 = sum(v * v for v in r2) ** 0.5
            d01 = sum(r0[k] * r1[k] for k in range(3))
            det = (r0[0] * (r1[1] * r2[2] - r1[2] * r2[1])
                   - r0[1] * (r1[0] * r2[2] - r1[2] * r2[0])
                   + r0[2] * (r1[0] * r2[1] - r1[1] * r2[0]))
            if (abs(l0 - 1) > 0.02 or abs(l1 - 1) > 0.02 or abs(l2 - 1) > 0.02
                    or abs(d01) > 0.03 or det < 0.95):
                problems.append('链 %d 第 %d 个节点的矩阵不是正交旋转'
                                '（行长度 %.3f/%.3f/%.3f，det=%.2f）'
                                % (g, j, l0, l1, l2, det))
    return problems

def rebuild_from_bones(mod_bytes, ctc_bytes):
    """按 .mod 里物理骨的父子链，重建 CTC 的节点表。

    适用：CTC 是从别的骨架/别的链长搬来的（节点数、顺序对不上）。
    做法：保留原 CTC 的链组参数与节点模板（矩阵/质量/角度），只按真实骨链重新排列节点：
    每条链的节点数按骨链长度，第一个节点 flags=1（根），其余 0。
    返回新的 CTC 字节；无法重建时返回 b''。
    """
    if not ctc_bytes or ctc_bytes[:4] != MAGIC or not mod_bytes or mod_bytes[:4] != b'MOD\x00':
        return b''
    n = struct.unpack_from('<H', mod_bytes, 6)[0]
    ptr = struct.unpack_from('<I', mod_bytes, 36)[0]
    slot_id = {i: mod_bytes[ptr + i * 24] for i in range(n)}
    parent = {}
    for i in range(n):
        parent[slot_id[i]] = slot_id.get(mod_bytes[ptr + i * 24 + 1], 255)
    phys = sorted(v for v in slot_id.values() if v >= 20)
    if not phys:
        return b''

    chains = []
    for pid in phys:
        if parent.get(pid, 255) < 20:
            ch, cur = [pid], pid
            while True:
                nxt = [b for b in phys if parent.get(b) == cur]
                if not nxt:
                    break
                cur = nxt[0]
                ch.append(cur)
            chains.append(ch)
    if not chains:
        return b''

    n_g = struct.unpack_from('<I', ctc_bytes, 0x10)[0]
    n_c = struct.unpack_from('<I', ctc_bytes, 0x14)[0]
    g_off = 0x3C
    c_off = g_off + 80 * n_g
    if n_g <= 0 or len(ctc_bytes) < c_off + 96 * n_c:
        return b''
    groups = [bytearray(ctc_bytes[g_off + 80 * g: g_off + 80 * (g + 1)])
              for g in range(n_g)]
    nodes = [ctc_bytes[c_off + 96 * k: c_off + 96 * (k + 1)] for k in range(n_c)]

    # 每条链的模板节点：按原 CTC 的链组划分
    tpl_per_group, idx = [], 0
    for g in range(n_g):
        cnt = struct.unpack_from('<I', groups[g], 0)[0]
        cnt = max(1, min(cnt, len(nodes) - idx)) if idx < len(nodes) else 1
        tpl_per_group.append(nodes[idx:idx + cnt] or [nodes[0]])
        idx += cnt

    out_nodes = []
    for gi, ch in enumerate(chains):
        tpl = tpl_per_group[min(gi, len(tpl_per_group) - 1)]
        for k, bid in enumerate(ch):
            nd = bytearray(tpl[k % len(tpl)])
            struct.pack_into('<H', nd, 0, bid)
            struct.pack_into('<H', nd, 2, 1 if k == 0 else 0)
            out_nodes.append(bytes(nd))
        struct.pack_into('<I', groups[gi if gi < len(groups) else -1], 0, len(ch))
        if gi >= len(groups):
            g = bytearray(groups[-1])
            struct.pack_into('<I', g, 0, len(ch))
            groups.append(g)

    hdr = bytearray(ctc_bytes[:g_off])
    struct.pack_into('<I', hdr, 0x10, len(groups))
    struct.pack_into('<I', hdr, 0x14, len(out_nodes))
    tail = ctc_bytes[c_off + 96 * n_c:]
    return bytes(hdr) + b''.join(bytes(g) for g in groups) + b''.join(out_nodes) + tail


def set_segment_shapes(data: bytes, on=True):
    """骨段碰撞开关：组内非链尾节点 +6=2（ShapeObject=2），链尾保持 1；
    CTC 头 +54 = 3（开）/ 1（关）。节点 +8 半径等其它字节一律不动。

    依据「外观工坊」physics.py：segment_collision 时 header[54]=3、
    node[6]=2（链尾 1）、node[7]=1、半径保持 5.0。

    返回 (新 bytes, 组数, 节点总数, 被改动的节点数)；结构不认识时原样返回。
    """
    if not data or data[:4] != MAGIC or len(data) < 0x3C:
        return data, 0, 0, 0
    n_g = struct.unpack_from('<I', data, 0x10)[0]
    n_c = struct.unpack_from('<I', data, 0x14)[0]
    g_off = 0x3C
    c_off = g_off + 80 * n_g
    if n_g <= 0 or n_c <= 0 or n_g > 64 or n_c > 4096:
        return data, 0, 0, 0
    if len(data) < c_off + 96 * n_c:
        return data, 0, 0, 0
    out = bytearray(data)
    changed = 0
    idx = 0
    groups = 0
    for g in range(n_g):
        cnt = struct.unpack_from('<I', data, g_off + 80 * g)[0]
        if cnt <= 0 or idx + cnt > n_c:
            break
        groups += 1
        for j in range(cnt):
            o = c_off + 96 * (idx + j) + 6
            shape = 2 if (on and j + 1 < cnt) else 1
            if out[o] != shape:
                out[o] = shape
                changed += 1
        idx += cnt
    head = 3 if on else 1
    if out[54] != head:
        out[54] = head
    return bytes(out), groups, idx, changed
