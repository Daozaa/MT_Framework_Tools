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

BODY_PROFILE = [
    (0, 2, 10.0), (3, 4, 6.0),
    (6, 7, 4.2), (10, 11, 4.2), (7, 8, 4.2), (11, 12, 4.2),
    (14, 15, 6.0), (17, 18, 6.0), (15, 16, 4.0), (18, 19, 4.0),
]

def build_ccl(capsules):
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
    if not text:
        return []
    try:
        data = json.loads(text)
    except Exception:
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

def _bone_worlds(mod_bytes):
    import numpy as np
    from .MTframework_MHGU_bones import read_bone_section, bone_section_offsets
    n = struct.unpack_from('<H', mod_bytes, 6)[0]
    ptr = struct.unpack_from('<I', mod_bytes, 36)[0]
    sec = read_bone_section(mod_bytes, ptr, n)
    _, _, world_off, _ = bone_section_offsets(ptr, n)
    S = float(sec['scale']) or 1.0
    out = []
    for i in range(n):
        inverse_bind = np.array(struct.unpack_from('<16f', mod_bytes, world_off + i * 64),
                                dtype=np.float64).reshape(4, 4).T
        inverse_bind[:3, :3] /= S
        rest = np.linalg.inv(inverse_bind)
        out.append((sec['infos'][i]['ID'], rest))
    return out, S

def body_capsules(mod_bytes, height=None, positions=None):
    import numpy as np
    worlds, _ = _bone_worlds(mod_bytes)
    pos = {bid: m[:3, 3] for bid, m in worlds}
    if positions:
        pos.update({bid: np.asarray(point, dtype=float) for bid, point in positions.items()})
    mats = {bid: m for bid, m in worlds}
    if not pos:
        return []

    if height is None:
        ys = [point[1] for bid, point in pos.items() if bid < 20]
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
        la = np.linalg.solve(mats[a][:3, :3], pa - pos[a])
        lb = np.linalg.solve(mats[b][:3, :3], pb - pos[b])
        caps.append({'a': int(a), 'b': int(b),
                     'start': tuple(float(v) for v in la[:3]),
                     'end': tuple(float(v) for v in lb[:3]),
                     'radius': float(r)})
    return caps

def _segment_distances(p, q, starts, ends):
    import numpy as np

    def dot_rows(a, b):
        return np.sum(a * b, axis=-1)

    def point_to_segment(points, origins, spans, lengths):
        with np.errstate(divide='ignore', invalid='ignore'):
            factors = np.where(lengths > 0, dot_rows(points - origins, spans) / lengths, 0.0)
        delta = points - origins - spans * np.clip(factors, 0.0, 1.0)[..., None]
        return np.linalg.norm(delta, axis=-1)

    u, v, w = q - p, ends - starts, p - starts
    uu, uv, vv = np.dot(u, u), dot_rows(u, v), dot_rows(v, v)
    uw, vw = dot_rows(u, w), dot_rows(v, w)
    best = np.minimum.reduce([
        point_to_segment(p, starts, v, vv), point_to_segment(q, starts, v, vv),
        point_to_segment(starts, p, u, uu), point_to_segment(ends, p, u, uu),
    ])
    det = uu * vv - uv * uv
    valid = det > 1e-10
    s = np.divide(uv * vw - vv * uw, det, where=valid, out=np.zeros_like(det))
    t = np.divide(uu * vw - uv * uw, det, where=valid, out=np.zeros_like(det))
    valid &= (s > 0) & (s < 1) & (t > 0) & (t < 1)
    interior = np.linalg.norm(w + s[:, None] * u - t[:, None] * v, axis=-1)
    return np.where(valid, np.minimum(best, interior), best)

class _CclClearance:
    def __init__(self, mod_bytes, ctc_bytes, margin, positions):
        import numpy as np

        if not ctc_bytes or ctc_bytes[:4] != b'CTC\0' or len(ctc_bytes) < 60:
            raise ValueError('请先登记物理骨，生成 CTC 后再检查胶囊')
        groups, count = struct.unpack_from('<II', ctc_bytes, 16)
        start = 60 + 80 * groups
        if not groups or not count or start + 96 * count > len(ctc_bytes):
            raise ValueError('CTC 链和节点数据不完整')
        worlds, _ = _bone_worlds(mod_bytes)
        self.mats = dict(worlds)
        self.centers = {bid: mat[:3, 3] for bid, mat in worlds}
        if positions:
            self.centers.update({bid: np.asarray(point, dtype=float) for bid, point in positions.items()})
        cursor = 0
        starts, ends, radii, ids = [], [], [], []
        for group in range(groups):
            length = struct.unpack_from('<I', ctc_bytes, 60 + 80 * group)[0]
            if cursor + length > count:
                raise ValueError('CTC 分组节点数超出声明总数')
            chain = []
            for index in range(cursor, cursor + length):
                offset = start + 96 * index
                bid = struct.unpack_from('<H', ctc_bytes, offset)[0]
                if bid not in self.centers:
                    raise ValueError('CTC 节点骨 %d 不在 MOD 内' % bid)
                radius = struct.unpack_from('<f', ctc_bytes, offset + 8)[0]
                if not np.isfinite(radius) or radius < 0:
                    raise ValueError('CTC 节点 %d 的半径无效' % bid)
                chain.append((self.centers[bid], radius, ctc_bytes[offset + 6], bid))
            for i, (point, radius, shape, bid) in enumerate(chain):

                if radius == 0.0 or shape not in (1, 2) or (shape == 2 and i + 1 == len(chain)):
                    continue
                starts.append(point)
                ends.append(chain[i + 1][0] if shape == 2 else point)
                radii.append(radius)
                ids.append(bid)
            cursor += length
        if cursor != count:
            raise ValueError('CTC 分组和节点总数不一致')
        self.starts = np.asarray(starts).reshape(-1, 3)
        self.ends = np.asarray(ends).reshape(-1, 3)
        self.radii = np.asarray(radii)
        self.ids = ids
        self.margin = margin

    def endpoint(self, bid, offset):
        if bid not in self.mats:
            raise ValueError('胶囊骨 %d 不在 MOD 内' % bid)
        return self.centers[bid] + self.mats[bid][:3, :3] @ offset

    def p_q(self, cap):
        return self.endpoint(cap['a'], cap['start']), self.endpoint(cap['b'], cap['end'])

    def radius(self, p, q):
        return float(self.gaps(p, q).min(initial=float('inf'))) - self.margin

    def gaps(self, p, q):
        return _segment_distances(p, q, self.starts, self.ends) - self.radii

    def offset_for(self, bid, world_position):
        import numpy as np
        delta = world_position - self.centers[bid]
        return tuple(float(v) for v in np.linalg.solve(self.mats[bid][:3, :3], delta))

def capsule_clearances(mod_bytes, ctc_bytes, capsules, margin=0.75, positions=None):
    geometry = _CclClearance(mod_bytes, ctc_bytes, margin, positions)
    return [geometry.radius(*geometry.p_q(cap)) for cap in capsules]

def _best_capsule_center(geometry, a, b, nominal):
    import itertools
    import numpy as np

    radius = min(nominal, geometry.radius(a, b))
    if radius >= nominal:
        return a, b, radius
    best = (a, b, radius)
    root = geometry.centers.get(0)
    centered = root is not None and max(abs(a[0] - root[0]), abs(b[0] - root[0])) < 1e-3
    directions = np.array([v for v in itertools.product((-1, 0, 1), repeat=3)
                           if v != (0, 0, 0) and (not centered or v[0] == 0)], dtype=float)
    directions /= np.linalg.norm(directions, axis=1)[:, None]
    shifts = [np.zeros(3)] + [nominal * step * d
                              for step in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6) for d in directions]
    span = b - a
    trims = ((0.0, 0.0), (0.2, 0.0), (0.0, 0.2), (0.2, 0.2),
             (0.4, 0.0), (0.0, 0.4), (0.4, 0.4))
    for trim_start, trim_end in trims:
        first = a + span * trim_start
        last = b - span * trim_end
        for offset in shifts:
            start, end = first + offset, last + offset
            radius = min(nominal, geometry.radius(start, end))

            if radius >= np.linalg.norm(offset) and radius > best[2] + 1e-5:
                best = (start, end, radius)
                if radius >= nominal:
                    return best
    return best

def fit_capsule_clearance(mod_bytes, ctc_bytes, capsules, margin=0.75,
                          positions=None, *, recenter=False, minimum_fraction=0.5):
    geometry = _CclClearance(mod_bytes, ctc_bytes, margin, positions)
    safe = []
    adjusted = skipped = 0
    for cap in capsules:
        if not cap.get('enabled', True):
            safe.append(cap)
            continue
        p, q = geometry.p_q(cap)
        if recenter:
            start, end, radius = _best_capsule_center(geometry, p, q, cap['radius'])
            minimum = max(0.1, cap['radius'] * minimum_fraction)
        else:
            start, end = p, q
            radius = min(cap['radius'], geometry.radius(p, q))
            minimum = 0.1
        if radius < minimum:
            skipped += 1
            continue
        result = dict(cap, radius=radius)
        if start is not p:
            result['start'] = geometry.offset_for(cap['a'], start)
            result['end'] = geometry.offset_for(cap['b'], end)
        if start is not p or radius < cap['radius']:
            adjusted += 1
        safe.append(result)
    return safe, adjusted, skipped

def prepare_export_capsules(mod, ctc, custom, auto, protect):
    if custom:
        if not protect or not ctc:
            return custom, 0, 0
        if len(ctc) >= 0x3C and not ctc[0x36]:
            return custom, 0, 0
        return fit_capsule_clearance(mod, ctc, custom, recenter=True, minimum_fraction=0.0)
    if auto and ctc:
        return fit_capsule_clearance(mod, ctc, body_capsules(mod), recenter=True)
    return [], 0, 0
