# -*- coding: utf-8 -*-
"""MHGU / MT Framework v160 ``.tex`` 读写 —— 贴图导入导出。

格式理解来源（第三方改模 skill 包，2026-10-18 收）：
    ref_mods/MHGU防具包/.../docs/TEX_FORMAT.md
    ref_mods/MHGU防具包/.../tools/texwrite.py
本文件是**独立实现**（只依赖 numpy），算法与实测常量按上述资料重写。

格式要点
--------
::

    0x00 u32 magic = "TEX\\0"
    0x04 u32 version[11:0] | unk1[23:12] | unused[27:24] | alphaFlags[31:28]
    0x08 u32 mipCount[5:0] | width[18:6] | height[31:19]
    0x0C u32 unk2[7:0] | format[15:8] | unk3[31:16]
    0x10 u32 overall = 全部 mip 像素总字节
    0x14 u32 x mipCount  各 mip 相对偏移（相对偏移表之后）
    ...  像素数据：Switch（Tegra）block-linear / GOB swizzle

支持的像素格式（实测出现过的）：0x13 DXT1 / 0x17 DXT5 / 0x19 ATI1(BC4)，
另外 0x1F ATI2(BC5) 按同理解码。0x07 RGBA8 实测无样本，这里不做。

尺寸限制：GOB 行数必须是 2 的幂，swizzle 指数 k = log2(gobs_per_col)。
128 高 → k=2、512 → k=4、1024 → k=5、2048 → k=6，都满足；高度不是 32 的
2 的幂倍（例如 96、320）才无法确定 k。
"""
from __future__ import annotations

import struct

import numpy as np

try:                                            # 纯 Python 测试时可以没有 bpy
    import bpy
except Exception:                               # noqa: BLE001
    bpy = None


MAGIC = 0x00584554
VERSION_MHGU = 160

#: format_id -> (名字, 块宽, 块高, 字节/块)
FORMATS = {
    0x07: ("RGBA8", 1, 1, 4),
    0x13: ("DXT1", 4, 4, 8),
    0x17: ("DXT5", 4, 4, 16),
    0x19: ("ATI1", 4, 4, 8),
    0x1F: ("ATI2", 4, 4, 16),
}

#: 实测 73/73 样本一致的头部常量
CONST_UNK1 = 8
CONST_UNUSED = 0
CONST_ALPHA_FLAGS = 2
CONST_UNK2 = 1
CONST_UNK3 = 1

#: GOB 内部的块排列位序（实测值，见模块文档）
GOB_PATTERNS = {16: "rcrrc", 8: "crcrrc", 4: "ccrcrrc"}



class TexInfo(object):
    """解析后的 .tex 结构。"""

    def __init__(self):
        self.version = 0
        self.unk1 = CONST_UNK1
        self.unused = CONST_UNUSED
        self.alpha_flags = CONST_ALPHA_FLAGS
        self.unk2 = CONST_UNK2
        self.unk3 = CONST_UNK3
        self.width = 0
        self.height = 0
        self.format_id = 0
        self.mip_count = 0
        self.overall = 0
        self.header_size = 0
        self.mips = []                          # [(w, h, bytes), ...]

    @property
    def format_name(self):
        return FORMATS.get(self.format_id, ("?0x%02X" % self.format_id,))[0]

    def __str__(self):
        return ("%dx%d %s mip=%d overall=%d header=%d"
                % (self.width, self.height, self.format_name,
                   self.mip_count, self.overall, self.header_size))


# ============================================================================
# 头部
# ============================================================================

def parse_tex(data):
    """解析 .tex 字节流，返回 :class:`TexInfo`。失败抛 ValueError。"""
    if len(data) < 20:
        raise ValueError("文件太小（%d 字节）" % len(data))
    if data[:4] != b"TEX\x00":
        raise ValueError("magic 不是 TEX\\0（实际 %r）" % data[:4])

    v1, v2, v3, overall = struct.unpack_from("<IIII", data, 4)
    info = TexInfo()
    info.version = v1 & 0xFFF
    info.unk1 = (v1 >> 12) & 0xFFF
    info.unused = (v1 >> 24) & 0xF
    info.alpha_flags = (v1 >> 28) & 0xF
    info.mip_count = v2 & 0x3F
    info.width = (v2 >> 6) & 0x1FFF
    info.height = (v2 >> 19) & 0x1FFF
    info.unk2 = v3 & 0xFF
    info.format_id = (v3 >> 8) & 0xFF
    info.unk3 = (v3 >> 16) & 0xFFFF
    info.overall = overall
    info.header_size = 20 + 4 * info.mip_count

    if info.version != VERSION_MHGU:
        raise ValueError("version=%d 不是 MHGU(160)，本工具不支持" % info.version)
    if info.format_id not in FORMATS:
        raise ValueError("未知像素格式 0x%02X" % info.format_id)
    if info.mip_count < 1:
        raise ValueError("mipCount=0")

    offs = list(struct.unpack_from("<%dI" % info.mip_count, data, 20))
    for i, off in enumerate(offs):
        nxt = offs[i + 1] if i + 1 < info.mip_count else info.overall
        size = nxt - off
        if size < 0:
            raise ValueError("mip%d 段大小为负" % i)
        start = info.header_size + off
        if start + size > len(data):
            raise ValueError("mip%d 数据越界（%d+%d > %d）"
                             % (i, start, size, len(data)))
        mw = max(1, info.width >> i)
        mh = max(1, info.height >> i)
        info.mips.append((mw, mh, data[start:start + size]))
    return info


def _pack_tex(width, height, mip_count, fmt_id, offsets, payload,
              unk1, unused, alpha_flags, unk2, unk3):
    v1 = ((VERSION_MHGU & 0xFFF) | ((unk1 & 0xFFF) << 12)
          | ((unused & 0xF) << 24) | ((alpha_flags & 0xF) << 28))
    v2 = ((mip_count & 0x3F) | ((width & 0x1FFF) << 6) | ((height & 0x1FFF) << 19))
    v3 = ((unk2 & 0xFF) | ((fmt_id & 0xFF) << 8) | ((unk3 & 0xFFFF) << 16))
    out = bytearray()
    out += struct.pack("<IIII", MAGIC, v1, v2, v3)
    out += struct.pack("<I", len(payload))
    for o in offsets:
        out += struct.pack("<I", o)
    out += payload
    return bytes(out)


# ============================================================================
# Tegra block-linear (GOB swizzle)
# ============================================================================

def gob_dims(bytes_per_block):
    if 64 % bytes_per_block:
        raise ValueError("bytes_per_block=%d 无法整除 64" % bytes_per_block)
    return 64 // bytes_per_block, 8


def gob_pattern(bytes_per_block):
    p = GOB_PATTERNS.get(bytes_per_block)
    if p is None:
        raise ValueError("没有 %d 字节/块 的 GOB 位序" % bytes_per_block)
    return p


def _gob_local_index(pattern, iny, inx):
    local = np.zeros_like(iny)
    ri = ci = 0
    for pos, ch in enumerate(pattern):
        if ch == "r":
            local |= ((iny >> ri) & 1) << pos
            ri += 1
        else:
            local |= ((inx >> ci) & 1) << pos
            ci += 1
    return local


def padded_block_dims(w, h, bw, bh, bpb):
    gw, gh = gob_dims(bpb)
    bx = max(1, (w + bw - 1) // bw)
    by = max(1, (h + bh - 1) // bh)
    bx = (bx + gw - 1) // gw * gw
    by = (by + gh - 1) // gh * gh
    return bx, by


def swizzle_k_for(padded_blocks_y):
    """每列 GOB 数 -> swizzle 交错位数 k。

    ★ k 上限是 4（= 每列最多 16 个 GOB 参与交错）。
    实测：2048×2048 DXT5 的原版/Kukkii 文件用 k=4；插件旧公式给出 k=6，
    导致 1024/2048 贴图进游戏后整张错位（512 及以下看不出来，因为 k<=4）。
    """
    gobs_per_col = max(1, padded_blocks_y // 8)
    k = gobs_per_col.bit_length() - 1
    if (1 << k) != gobs_per_col:
        raise ValueError("GOB 行数 %d 不是 2 的幂（高度不合规）" % gobs_per_col)
    return min(k, 4)


def _gob_index_table(padded_bx, padded_by, bpb, k):
    gw, gh = gob_dims(bpb)
    pattern = gob_pattern(bpb)
    gx_n = padded_bx // gw
    gy_n = padded_by // gh
    if padded_bx % gw or padded_by % gh:
        raise ValueError("块网格 (%d,%d) 未补齐到 GOB(%d,%d)"
                         % (padded_bx, padded_by, gw, gh))
    if (1 << k) > gy_n or gy_n % (1 << k):
        raise ValueError("swizzle k=%d 与 GOB 行数 %d 不匹配" % (k, gy_n))

    bx = np.arange(padded_bx, dtype=np.int64)[None, :].repeat(padded_by, 0)
    by = np.arange(padded_by, dtype=np.int64)[:, None].repeat(padded_bx, 1)
    gx = bx // gw
    gy = by // gh
    inx = bx % gw
    iny = by % gh
    gob_seq = (gy >> k) * (gx_n << k) + gx * (1 << k) + (gy & ((1 << k) - 1))
    idx = gob_seq * (gw * gh) + _gob_local_index(pattern, iny, inx)
    n = padded_bx * padded_by
    if idx.max() >= n or idx.min() < 0:
        raise ValueError("GOB 索引越界")
    return idx


def deswizzle_mip(raw, w, h, bw, bh, bpb, k=None, full=False):
    """原始字节 -> (块行, 块列, bpb) uint8。

    ``full=False`` 只返回实际覆盖的块（忽略 padding）；``full=True`` 返回
    补齐后的整块网格（用于「原样重组」——padding 区可能不是 0）。
    """
    pbx, pby = padded_block_dims(w, h, bw, bh, bpb)
    need = pbx * pby * bpb
    if len(raw) < need:
        raise ValueError("mip 数据不足：需要 %d，实际 %d" % (need, len(raw)))
    if k is None:
        k = swizzle_k_for(pby)
    idx = _gob_index_table(pbx, pby, bpb, k)
    src = np.frombuffer(raw[:need], dtype=np.uint8).reshape(pbx * pby, bpb)
    out = src[idx.reshape(-1)].reshape(pby, pbx, bpb)
    if full:
        return out
    bx = (w + bw - 1) // bw
    by = (h + bh - 1) // bh
    return out[:by, :bx, :]


def swizzle_mip(blocks, w, h, bw, bh, bpb, k=None):
    """(块行, 块列, bpb) -> swizzled 字节流（长度 = 补齐后块数 × bpb）。"""
    pbx, pby = padded_block_dims(w, h, bw, bh, bpb)
    if k is None:
        k = swizzle_k_for(pby)
    buf = np.zeros((pby, pbx, bpb), dtype=np.uint8)
    blk = blocks if blocks.dtype == np.uint8 else blocks.astype(np.uint8)
    buf[:blk.shape[0], :blk.shape[1], :] = blk
    idx = _gob_index_table(pbx, pby, bpb, k)
    out = np.empty((pbx * pby, bpb), dtype=np.uint8)
    out[idx.reshape(-1)] = buf.reshape(pbx * pby, bpb)
    return out.tobytes()


# ============================================================================
# 块解码
# ============================================================================

def _rgb565_to_rgb(c):
    r = (c >> 11) & 0x1F
    g = (c >> 5) & 0x3F
    b = c & 0x1F
    r = (r << 3) | (r >> 2)
    g = (g << 2) | (g >> 4)
    b = (b << 3) | (b >> 2)
    return np.stack([r, g, b], axis=1).astype(np.int32)


def _unpack_index(bits, n, nbits, count, shift_step=None):
    out = np.zeros((n, count), dtype=np.int32)
    mask = (1 << nbits) - 1
    step = shift_step or nbits
    for p in range(count):
        out[:, p] = (bits >> (step * p)) & mask
    return out


def _bc1_colour_blocks(blocks):
    n = blocks.shape[0]
    c0 = blocks[:, 0].astype(np.uint32) | (blocks[:, 1].astype(np.uint32) << 8)
    c1 = blocks[:, 2].astype(np.uint32) | (blocks[:, 3].astype(np.uint32) << 8)
    p0 = _rgb565_to_rgb(c0)
    p1 = _rgb565_to_rgb(c1)
    gt = c0 > c1
    pal = np.zeros((n, 4, 3), dtype=np.int32)
    pal[:, 0] = p0
    pal[:, 1] = p1
    pal[:, 2] = np.where(gt[:, None], (2 * p0 + p1 + 1) // 3, (p0 + p1) // 2)
    pal[:, 3] = np.where(gt[:, None], (p0 + 2 * p1 + 1) // 3, 0)

    bits = (blocks[:, 4].astype(np.uint32) | (blocks[:, 5].astype(np.uint32) << 8)
            | (blocks[:, 6].astype(np.uint32) << 16)
            | (blocks[:, 7].astype(np.uint32) << 24))
    idx = _unpack_index(bits, n, 2, 16)
    rgba = np.zeros((n, 16, 4), dtype=np.uint8)
    rgba[:, :, :3] = pal[np.arange(n)[:, None], idx].astype(np.uint8)
    transparent = (~gt)[:, None] & (idx == 3)
    rgba[:, :, 3] = np.where(transparent, 0, 255)
    return rgba


def _bc4_channel_blocks(blocks):
    n = blocks.shape[0]
    a0 = blocks[:, 0].astype(np.int32)
    a1 = blocks[:, 1].astype(np.int32)
    bits = np.zeros(n, dtype=np.int64)
    for i in range(6):
        bits |= blocks[:, 2 + i].astype(np.int64) << (8 * i)
    idx = np.zeros((n, 16), dtype=np.int32)
    for p in range(16):
        idx[:, p] = (bits >> (3 * p)) & 7

    gt = a0 > a1
    pal = np.zeros((n, 8), dtype=np.int32)
    pal[:, 0] = a0
    pal[:, 1] = a1
    for i in range(2, 8):
        v8 = ((8 - i) * a0 + (i - 1) * a1 + 3) // 7
        if i <= 5:
            v6 = ((6 - i) * a0 + (i - 1) * a1 + 2) // 5
        else:
            v6 = np.full(n, 0 if i == 6 else 255, dtype=np.int32)
        pal[:, i] = np.where(gt, v8, v6)
    return pal[np.arange(n)[:, None], idx].astype(np.uint8)


def _finish(a, w, h):
    by_n, bx_n, bh, bw, ch = a.shape
    img = a.transpose(0, 2, 1, 3, 4).reshape(by_n * bh, bx_n * bw, ch)
    return img[:h, :w]


def decode_blocks(blocks, fmt_id, w, h):
    """(块行, 块列, bpb) -> (h, w, 4) uint8 RGBA。"""
    name, bw, bh, bpb = FORMATS[fmt_id]
    by_n, bx_n = blocks.shape[0], blocks.shape[1]
    flat = blocks.reshape(by_n * bx_n, bpb)

    if name == "RGBA8":
        v = flat.reshape(by_n, bx_n, 1, 1, 4)[:, :, :, :, [2, 1, 0, 3]]
        return v.reshape(by_n, bx_n, 4)[:h, :w]

    if name == "DXT1":
        v = _bc1_colour_blocks(flat)
    elif name == "DXT5":
        v = _bc1_colour_blocks(flat[:, 8:16])
        v[:, :, 3] = _bc4_channel_blocks(flat[:, 0:8])
    elif name == "ATI1":
        r = _bc4_channel_blocks(flat)
        v = np.empty((flat.shape[0], 16, 4), dtype=np.uint8)
        v[:, :, 0] = v[:, :, 1] = v[:, :, 2] = r
        v[:, :, 3] = 255
    elif name == "ATI2":
        v = np.empty((flat.shape[0], 16, 4), dtype=np.uint8)
        v[:, :, 0] = _bc4_channel_blocks(flat[:, 0:8])
        v[:, :, 1] = _bc4_channel_blocks(flat[:, 8:16])
        v[:, :, 2] = 0
        v[:, :, 3] = 255
    else:
        raise ValueError("未知格式 0x%02X" % fmt_id)

    return _finish(v.reshape(by_n, bx_n, bh, bw, 4), w, h)


def decode_mip(info, index=0):
    """解码指定 mip，返回 (h, w, 4) uint8。"""
    mw, mh, raw = info.mips[index]
    name, bw, bh, bpb = FORMATS[info.format_id]
    blocks = deswizzle_mip(raw, mw, mh, bw, bh, bpb)
    return decode_blocks(blocks, info.format_id, mw, mh)


def rebuild_raw(info):
    """不改像素、只用已有块重新组装 —— 对真实样本应与原文件逐字节相同。

    padding 区**原样保留**（实测小 mip 的 padding 不是 0，清零会破坏逐字节一致）。
    """
    name, bw, bh, bpb = FORMATS[info.format_id]
    payload = bytearray()
    offsets = []
    for (mw, mh, raw) in info.mips:
        full = deswizzle_mip(raw, mw, mh, bw, bh, bpb, full=True)
        offsets.append(len(payload))
        payload += swizzle_mip(full, mw, mh, bw, bh, bpb)
    return _pack_tex(info.width, info.height, info.mip_count, info.format_id,
                     offsets, bytes(payload), info.unk1, info.unused,
                     info.alpha_flags, info.unk2, info.unk3)


# ============================================================================
# 块编码
# ============================================================================

def _rgb565(px):
    r = np.clip(px[:, 0].astype(np.int32), 0, 255)
    g = np.clip(px[:, 1].astype(np.int32), 0, 255)
    b = np.clip(px[:, 2].astype(np.int32), 0, 255)
    return (((r * 31 + 127) // 255) << 11) | (((g * 63 + 127) // 255) << 5) \
        | ((b * 31 + 127) // 255)


def _blockify(rgba, bw, bh):
    """(h,w,4) -> (块行, 块列, bh, bw, 4)，右侧/底部用边缘像素补齐。"""
    h, w = rgba.shape[:2]
    by = (h + bh - 1) // bh
    bx = (w + bw - 1) // bw
    ph, pw = by * bh, bx * bw
    pad = np.zeros((ph, pw, rgba.shape[2]), dtype=rgba.dtype)
    pad[:h, :w] = rgba
    if ph > h:
        pad[h:, :w] = rgba[h - 1:h, :w]
    if pw > w:
        pad[:h, w:] = pad[:h, w - 1:w]
        pad[h:, w:] = pad[h - 1:h, w - 1:w]
    return pad.reshape(by, bh, bx, bw, rgba.shape[2]).transpose(0, 2, 1, 3, 4), by, bx


def _principal_axis(px):
    """(n,16,3) -> 每块的主方向单位向量 (n,3)。"""
    d = px - px.mean(axis=1, keepdims=True)
    cov = np.einsum('npi,npj->nij', d, d)
    v = np.ones((px.shape[0], 3), dtype=np.float32) / np.sqrt(3.0)
    for _ in range(6):
        v = np.einsum('nij,nj->ni', cov, v)
        norm = np.linalg.norm(v, axis=1, keepdims=True)
        norm[norm < 1e-9] = 1.0
        v = v / norm
    return v, d


def _encode_bc1_blocks(px):
    """(n,16,3) uint8 -> (n,8) uint8 BC1 块。"""
    n = px.shape[0]
    pf = px.astype(np.float32)
    v, d = _principal_axis(pf)
    t = np.einsum('npi,ni->np', d, v)
    t0 = t.min(axis=1)
    t1 = t.max(axis=1)
    mean = pf.mean(axis=1)
    c0 = np.clip(mean + v * t0[:, None], 0, 255)
    c1 = np.clip(mean + v * t1[:, None], 0, 255)

    q0 = _rgb565(c0)
    q1 = _rgb565(c1)
    swap = q0 < q1
    q0s = np.where(swap, q1, q0)
    q1s = np.where(swap, q0, q1)
    same = q0s == q1s
    q1s = np.where(same, np.maximum(q1s - 1, 0), q1s)

    p0 = _rgb565_to_rgb(q0s)
    p1 = _rgb565_to_rgb(q1s)
    pal = np.zeros((n, 4, 3), dtype=np.int32)
    pal[:, 0] = p0
    pal[:, 1] = p1
    pal[:, 2] = (2 * p0 + p1 + 1) // 3
    pal[:, 3] = (p0 + 2 * p1 + 1) // 3

    diff = px.astype(np.int32)[:, :, None, :] - pal[:, None, :, :]
    dist = np.einsum('npck,npck->npc', diff, diff)
    idx = dist.argmin(axis=2).astype(np.uint32)          # (n,16)

    bits = np.zeros(n, dtype=np.uint32)
    for p in range(16):
        bits |= (idx[:, p] & 3) << (2 * p)

    out = np.empty((n, 8), dtype=np.uint8)
    out[:, 0] = q0s & 0xFF
    out[:, 1] = (q0s >> 8) & 0xFF
    out[:, 2] = q1s & 0xFF
    out[:, 3] = (q1s >> 8) & 0xFF
    for i in range(4):
        out[:, 4 + i] = (bits >> (8 * i)) & 0xFF
    return out


def _encode_bc4_blocks(vals):
    """(n,16) uint8 -> (n,8) uint8 BC4 块（8 值模式，a0 > a1）。"""
    n = vals.shape[0]
    a0 = vals.max(axis=1).astype(np.int32)
    a1 = vals.min(axis=1).astype(np.int32)
    eq = a0 == a1
    a1 = np.where(eq, np.maximum(a0 - 1, 0), a1)
    a0 = np.where(eq & (a0 == 0), 1, a0)

    pal = np.zeros((n, 8), dtype=np.int32)
    pal[:, 0] = a0
    pal[:, 1] = a1
    for i in range(2, 8):
        pal[:, i] = ((8 - i) * a0 + (i - 1) * a1 + 3) // 7

    diff = np.abs(vals.astype(np.int32)[:, :, None] - pal[:, None, :])
    idx = diff.argmin(axis=2).astype(np.int64)            # (n,16)

    bits = np.zeros(n, dtype=np.int64)
    for p in range(16):
        bits |= (idx[:, p] & 7) << (3 * p)

    out = np.empty((n, 8), dtype=np.uint8)
    out[:, 0] = a0
    out[:, 1] = a1
    for i in range(6):
        out[:, 2 + i] = (bits >> (8 * i)) & 0xFF
    return out


def encode_blocks(rgba, fmt_id):
    """(h,w,4) uint8 -> (块行, 块列, bpb) uint8。"""
    name, bw, bh, bpb = FORMATS[fmt_id]
    blk, by, bx = _blockify(rgba, bw, bh)
    flat = blk.reshape(by, bx, 16, 4)

    if name == "DXT1":
        out = _encode_bc1_blocks(flat[:, :, :, :3].reshape(-1, 16, 3))
    elif name == "DXT5":
        alpha = _encode_bc4_blocks(
            flat[:, :, :, 3].reshape(-1, 16).astype(np.uint8))
        colour = _encode_bc1_blocks(
            flat[:, :, :, :3].reshape(-1, 16, 3).astype(np.uint8))
        out = np.concatenate([alpha, colour], axis=1)
    elif name == "ATI1":
        out = _encode_bc4_blocks(flat[:, :, :, 0].reshape(-1, 16).astype(np.uint8))
    elif name == "ATI2":
        r = _encode_bc4_blocks(flat[:, :, :, 0].reshape(-1, 16).astype(np.uint8))
        g = _encode_bc4_blocks(flat[:, :, :, 1].reshape(-1, 16).astype(np.uint8))
        out = np.concatenate([r, g], axis=1)
    else:
        raise ValueError("不支持写入的格式 0x%02X" % fmt_id)
    return out.reshape(by, bx, bpb)


# ============================================================================
# 缩放 / mip
# ============================================================================

def resize_rgba(rgba, w, h):
    """双线性缩放到 (h,w)。够用即可，不追求与 Pillow LANCZOS 一致。"""
    src_h, src_w = rgba.shape[:2]
    if (src_w, src_h) == (w, h):
        return rgba
    xs = (np.arange(w, dtype=np.float32) + 0.5) * (src_w / float(w)) - 0.5
    ys = (np.arange(h, dtype=np.float32) + 0.5) * (src_h / float(h)) - 0.5
    xs = np.clip(xs, 0, src_w - 1)
    ys = np.clip(ys, 0, src_h - 1)
    x0 = np.floor(xs).astype(np.int32)
    y0 = np.floor(ys).astype(np.int32)
    x1 = np.minimum(x0 + 1, src_w - 1)
    y1 = np.minimum(y0 + 1, src_h - 1)
    fx = (xs - x0)[None, :, None]
    fy = (ys - y0)[:, None, None]
    a = rgba.astype(np.float32)
    top = a[y0][:, x0] * (1 - fx) + a[y0][:, x1] * fx
    bot = a[y1][:, x0] * (1 - fx) + a[y1][:, x1] * fx
    out = top * (1 - fy) + bot * fy
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def _downsample(rgba):
    """2×2 盒式平均降采样，宽高任何一个是 1 都能处理。"""
    h, w = rgba.shape[:2]
    if h <= 1 and w <= 1:
        return rgba.copy()
    nh, nw = max(1, h // 2), max(1, w // 2)
    ph, pw = nh * 2, nw * 2
    a = np.empty((ph, pw, rgba.shape[2]), dtype=np.float32)
    a[:h, :w] = rgba
    if ph > h:
        a[h:, :w] = rgba[h - 1:h]
    if pw > w:
        a[:h, w:] = a[:h, w - 1:w]
    if ph > h and pw > w:
        a[h:, w:] = a[h - 1:h, w - 1:w]
    a = a.reshape(nh, 2, nw, 2, -1).mean(axis=(1, 3))
    return np.clip(a + 0.5, 0, 255).astype(np.uint8)


def _build_mips(rgba, count):
    out = [rgba]
    for _ in range(1, count):
        out.append(_downsample(out[-1]))
    return out


def max_mip_count(w, h):
    return int(max(w, h)).bit_length()


def encode_tex(rgba, fmt_id=0x17, mip_count=None, **hdr):
    """从零编码一张贴图。"""
    h, w = rgba.shape[:2]
    name, bw, bh, bpb = FORMATS[fmt_id]
    if w % bw or h % bh:
        raise ValueError("%s 要求宽高是 %d×%d 的整数倍（当前 %d×%d）"
                         % (name, bw, bh, w, h))
    if mip_count is None:
        mip_count = max_mip_count(w, h)
    mip_count = max(1, min(int(mip_count), max_mip_count(w, h)))
    mips = _build_mips(rgba, mip_count)
    payload = bytearray()
    offsets = []
    for (mw, mh, arr) in [(m.shape[1], m.shape[0], m) for m in mips]:
        blocks = encode_blocks(arr, fmt_id)
        blob = swizzle_mip(blocks, mw, mh, bw, bh, bpb)
        offsets.append(len(payload))
        payload += blob
    return _pack_tex(w, h, len(mips), fmt_id, offsets, bytes(payload),
                     hdr.get('unk1', CONST_UNK1), hdr.get('unused', CONST_UNUSED),
                     hdr.get('alpha_flags', CONST_ALPHA_FLAGS),
                     hdr.get('unk2', CONST_UNK2), hdr.get('unk3', CONST_UNK3))


def encode_like(template, rgba):
    """沿用模板的结构（尺寸 / 格式 / mip 数 / 头部常量），只换像素。

    ``template`` 可以是 .tex 字节或 :class:`TexInfo`。尺寸不一致时自动缩放。
    """
    info = template if isinstance(template, TexInfo) else parse_tex(template)
    name, bw, bh, bpb = FORMATS[info.format_id]
    rgba = resize_rgba(rgba, info.width, info.height)
    mip_count = max(1, min(info.mip_count, max_mip_count(info.width, info.height)))
    mips = _build_mips(rgba, mip_count)
    payload = bytearray()
    offsets = []
    for arr in mips:
        mh, mw = arr.shape[:2]
        blocks = encode_blocks(arr, info.format_id)
        blob = swizzle_mip(blocks, mw, mh, bw, bh, bpb)
        offsets.append(len(payload))
        payload += blob
    return _pack_tex(info.width, info.height, len(mips), info.format_id,
                     offsets, bytes(payload), info.unk1, info.unused,
                     info.alpha_flags, info.unk2, info.unk3)


# ============================================================================
# Blender 胶水
# ============================================================================

def rgba_to_image(rgba, name, colorspace=None):
    """(h,w,4) uint8 -> bpy Image（Blender 的 pixels 是自下而上）。

    ⚠️ ``colorspace`` 必须在**写入像素之前**设。实测：先写像素再改
    ``colorspace_settings.name``，Blender 会就地转换整张缓冲，数据直接坏掉
    （maxdiff 255）。
    """
    if bpy is None:
        raise RuntimeError("没有 bpy")
    h, w = rgba.shape[:2]
    img = bpy.data.images.new(name, width=w, height=h, alpha=True)
    if colorspace:
        try:
            img.colorspace_settings.name = colorspace
        except Exception:
            pass
    buf = (rgba[::-1].astype(np.float32) / 255.0).reshape(-1)
    img.pixels.foreach_set(buf)
    img.update()
    return img


def _is_srgb_space(img):
    try:
        cs = (img.colorspace_settings.name or '').strip().lower()
    except Exception:                                   # noqa: BLE001
        return False
    return cs == 'srgb' or cs.startswith('srgb') or cs == 'filmic srgb'


def image_to_rgba(img):
    """bpy Image -> (h,w,4) uint8。

    ⚠️ **浮点图**（16 位 PNG、EXR、32 位/通道）的 img.pixels 是**线性**值，
    直接 ×255 会整体变暗（实测 sRGB 138 → 67、64 → 14，白色不变）。
    这类图要先编码回 sRGB 再取字节；8 位图（is_float=False）的 pixels
    本身就是 sRGB 原值，不能转，否则会变亮。
    """
    if bpy is None:
        raise RuntimeError("没有 bpy")
    w, h = img.size
    buf = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    a = buf.reshape(h, w, 4)[::-1].astype(np.float32, copy=True)
    if getattr(img, 'is_float', False) and _is_srgb_space(img):
        rgb = np.clip(a[..., :3], 0.0, None)
        a[..., :3] = np.where(rgb <= 0.0031308, rgb * 12.92,
                              1.055 * np.power(rgb, 1.0 / 2.4) - 0.055)
    return np.clip(a * 255.0 + 0.5, 0, 255).astype(np.uint8)


# ============================================================================
# 操作符 / UI
# ============================================================================

if bpy is not None:

    from bpy.props import (BoolProperty, EnumProperty, PointerProperty,
                           StringProperty)                       # noqa: E402
    from bpy.types import Operator                                # noqa: E402

    _SIZES = [('AUTO', "原图", "跟图片一样大（自动取 4 的倍数）"),
              ('128', "128", "缩放到最大边 128"),
              ('256', "256", "缩放到最大边 256"),
              ('512', "512", "缩放到最大边 512"),
              ('1024', "1024", "缩放到最大边 1024"),
              ('2048', "2048", "缩放到最大边 2048")]

    _FORMATS = [('AUTO', "自动", "有模板就沿用模板的格式，否则 DXT5"),
                ('DXT5', "DXT5", "带 alpha，防具主贴图 *_BM 用的就是它"),
                ('DXT1', "DXT1", "无 alpha，体积小一半"),
                ('ATI1', "ATI1", "单通道，用于遮罩/附加图 *_BM+A")]

    _FMT_IDS = {'DXT5': 0x17, 'DXT1': 0x13, 'ATI1': 0x19}

    def target_size(w, h, mode):
        if mode != 'AUTO':
            s = float(mode)
            k = s / float(max(w, h))
            w, h = int(round(w * k)), int(round(h * k))
        w = max(4, (int(w) // 4) * 4)
        h = max(4, (int(h) // 4) * 4)
        return w, h

    class MT_OT_ImportTex(Operator):
        """把 .tex 解码成 Blender 图像"""
        bl_idname = "mt_framework.import_tex"
        bl_label = "导入 .tex"
        bl_options = {'REGISTER', 'UNDO'}

        filepath: StringProperty(subtype='FILE_PATH')
        filter_glob: StringProperty(default="*.tex", options={'HIDDEN'})

        def execute(self, context):
            path = self.filepath
            try:
                with open(path, 'rb') as f:
                    data = f.read()
                info = parse_tex(data)
                rgba = decode_mip(info, 0)
                name = path.replace('\\', '/').rsplit('/', 1)[-1]
                cs = 'Non-Color' if info.format_id in (0x19, 0x1F) else 'sRGB'
                img = rgba_to_image(rgba, name, colorspace=cs)
                img['mt_tex_template'] = path
                img['mt_tex_info'] = str(info)
                try:
                    img.pack()
                except Exception:
                    pass
                scene = context.scene
                scene.MT_TexLast = path
                scene.MT_TexActive = img.name
                scene.MT_TexImage = img
                self.report({'INFO'}, "已导入 %s（%s，mip %d）"
                            % (name, info.format_name, info.mip_count))
            except Exception as e:                       # noqa: BLE001
                self.report({'ERROR'}, "导入失败: %s" % e)
                return {'CANCELLED'}
            return {'FINISHED'}

        def invoke(self, context, event):
            context.window_manager.fileselect_add(self)
            return {'RUNNING_MODAL'}

    class MT_OT_ExportTex(Operator):
        """把选定的图片编码成 .tex"""
        bl_idname = "mt_framework.export_tex"
        bl_label = "导出 .tex"
        bl_options = {'REGISTER'}

        filepath: StringProperty(subtype='FILE_PATH')
        filter_glob: StringProperty(default="*.tex", options={'HIDDEN'})

        def _pick_image(self, context):
            scene = context.scene
            img = getattr(scene, 'MT_TexImage', None)
            if img is not None:
                return img
            sp = getattr(context, 'space_data', None)
            if sp is not None and getattr(sp, 'image', None) is not None:
                return sp.image
            name = getattr(scene, 'MT_TexActive', '')
            if name:
                img = bpy.data.images.get(name)
                if img is not None:
                    return img
            for im in bpy.data.images:
                if im.get('mt_tex_template'):
                    return im
            return None

        def invoke(self, context, event):
            # ★ 1.2.191：以前这里没有 invoke，面板按钮会直接 execute，
            #   沿用上一次的 filepath —— 第二张图不弹对话框，直接按第一张的名字覆盖。
            #   现在每次都弹，并预填「当前图片名.tex」（后缀不用手打）。
            img = self._pick_image(context)
            base = 'texture'
            if img is not None:
                base = os.path.splitext(os.path.basename(img.name))[0] or 'texture'
            base = base.replace('/', '_').replace('\\', '_')
            last = context.scene.get('MT_TexLastExport', '') or ''
            d = os.path.dirname(last) if last else ''
            fn = base + '.tex'
            self.filepath = os.path.join(d, fn) if d else fn
            context.window_manager.fileselect_add(self)
            return {'RUNNING_MODAL'}

        def execute(self, context):
            scene = context.scene
            img = self._pick_image(context)
            if img is None:
                self.report({'ERROR'}, "先在面板里选一张图片")
                return {'CANCELLED'}

            if not self.filepath:
                base = os.path.splitext(os.path.basename(img.name))[0] or 'texture'
                self.filepath = base + '.tex'

            path = self.filepath
            if not path.lower().endswith('.tex'):
                path += '.tex'

            try:
                rgba = image_to_rgba(img)
                src_h, src_w = rgba.shape[:2]

                tpl = img.get('mt_tex_template')
                info = None
                if tpl:
                    try:
                        with open(tpl, 'rb') as f:
                            info = parse_tex(f.read())
                    except Exception:
                        info = None

                w, h = target_size(src_w, src_h, scene.MT_TexSize)
                fmt_mode = scene.MT_TexFormat
                if fmt_mode == 'AUTO':
                    fmt_id = info.format_id if info is not None else 0x17
                else:
                    fmt_id = _FMT_IDS[fmt_mode]

                if (w, h) != (src_w, src_h):
                    rgba = resize_rgba(rgba, w, h)

                mips = max_mip_count(w, h) if scene.MT_TexMips else 1
                blob = encode_tex(rgba, fmt_id, mips)

                with open(path, 'wb') as f:
                    f.write(blob)
                scene['MT_TexLastExport'] = path
                out = parse_tex(blob)
                self.report({'INFO'}, "已导出 %s（%d×%d %s mip%d，%d 字节）"
                            % (path.replace('\\', '/').rsplit('/', 1)[-1],
                               out.width, out.height, out.format_name,
                               out.mip_count, len(blob)))
            except Exception as e:                       # noqa: BLE001
                self.report({'ERROR'}, "导出失败: %s" % e)
                return {'CANCELLED'}
            return {'FINISHED'}

        def invoke(self, context, event):
            if self.filepath:
                return self.execute(context)
            context.window_manager.fileselect_add(self)
            return {'RUNNING_MODAL'}

    _classes = [MT_OT_ImportTex, MT_OT_ExportTex]

    _SCENE_PROPS = ('MT_TexLast', 'MT_TexActive', 'MT_TexImage',
                    'MT_TexSize', 'MT_TexFormat', 'MT_TexMips')

    def register():
        for c in _classes:
            bpy.utils.register_class(c)
        S = bpy.types.Scene
        S.MT_TexLast = StringProperty(name="上次导入的 .tex", default="")
        S.MT_TexActive = StringProperty(name="当前图像", default="")
        S.MT_TexImage = PointerProperty(type=bpy.types.Image, name="图片")
        S.MT_TexSize = EnumProperty(name="尺寸", items=_SIZES, default='AUTO')
        S.MT_TexFormat = EnumProperty(name="格式", items=_FORMATS, default='AUTO')
        S.MT_TexMips = BoolProperty(name="生成 mip", default=True)

    def unregister():
        for c in reversed(_classes):
            try:
                bpy.utils.unregister_class(c)
            except Exception:
                pass
        for attr in _SCENE_PROPS:
            try:
                delattr(bpy.types.Scene, attr)
            except Exception:
                pass

else:                                               # pragma: no cover
    def register():
        pass

    def unregister():
        pass
