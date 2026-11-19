from __future__ import annotations

import os
import shutil
import struct
import time
import zlib

ARC_MAGIC = b'ARC\x00'
MOD_MAGIC = b'MOD\x00'
CTC_MAGIC = b'CTC\x00'
CCL_MAGIC = b'CCL\0'
XFS_MAGIC = b'XFS\x00'
MRL_MAGIC = b'MRL\x00'

CCL_BONE_MAX = 19
CCL_BONE_NONE = 0xFFFF

def _ts():
    return time.strftime('%Y%m%d_%H%M%S')

def _uniq(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    for i in range(1, 1000):
        cand = '%s_%d%s' % (base, i, ext)
        if not os.path.exists(cand):
            return cand
    return '%s_%d%s' % (base, int(time.time()), ext)

def _parse_arc(data):
    problems = []
    if len(data) < 0x0C or data[:4] != ARC_MAGIC:
        return [], ['不是 ARC\\0 文件（前 4 字节 = %r）' % (data[:4],)]
    ver, count = struct.unpack_from('<HH', data, 4)
    if ver != 17:
        problems.append('ARC 版本是 %d，本插件只写 17' % ver)
    table_end = 0x0C + 80 * count
    if table_end > len(data):
        return [], ['条目表越界：count=%d 需要 %d 字节，文件只有 %d'
                    % (count, table_end, len(data))]
    entries = []
    for i in range(count):
        off = 0x0C + 80 * i
        name = data[off:off + 64].split(b'\0', 1)[0].decode('utf-8', 'replace')
        h, csz, flag, ofs = struct.unpack_from('<4I', data, off + 64)
        size = flag & 0xFFFFFF
        if ofs < table_end:
            problems.append('第 %d 条(%s) 数据区偏移 0x%X 落在条目表里' % (i, name, ofs))
        if ofs + csz > len(data):
            problems.append('第 %d 条(%s) 压缩数据越界：%d+%d > %d'
                            % (i, name, ofs, csz, len(data)))
            continue
        raw = data[ofs:ofs + csz]
        try:
            body = zlib.decompress(raw)
        except Exception:
            problems.append('第 %d 条(%s) zlib 解压失败（%d 字节）' % (i, name, csz))
            continue
        if size != len(body):
            problems.append('第 %d 条(%s) 长度字段 %d != 实际 %d'
                            % (i, name, size, len(body)))
        entries.append(dict(index=i, name=name, hash=h, flag=flag, raw=raw, body=body))
    return entries, problems

def _check_mod(body, label='MOD'):
    out = []
    if len(body) < 0x40 or body[:4] != MOD_MAGIC:
        return ['%s 不是 MOD\\0 或长度不足（%d 字节）' % (label, len(body))]
    n = struct.unpack_from('<H', body, 6)[0]
    ptr = struct.unpack_from('<I', body, 36)[0]
    end_size = struct.unpack_from('<I', body, 60)[0]
    ptr_tri = struct.unpack_from('<I', body, 56)[0]
    if n <= 0:
        out.append('%s 骨数 = 0' % label)
    need = ptr + n * 24 + n * 64
    if ptr < 0x40 or ptr > len(body) or need > len(body):
        out.append('%s 骨骼段越界：ptr=%d 骨数=%d 需要 %d，文件 %d'
                   % (label, ptr, n, need, len(body)))
    if end_size != len(body) - 4:
        out.append('%s endSize=%d，应为 len-4=%d' % (label, end_size, len(body) - 4))
    if end_size < len(body) and len(body) >= 4 and body[end_size:end_size + 4] != b'\0\0\0\0':
        out.append('%s endSize 之后不是 4 个 0（%r）'
                   % (label, body[end_size:end_size + 4]))
    if ptr_tri > end_size or (end_size - ptr_tri) % 2:
        out.append('%s 索引区不对：ptr_triangle=%d endSize=%d' % (label, ptr_tri, end_size))
    return out

def _check_ctc(body, label='CTC'):
    out = []
    if len(body) < 0x3C or body[:4] != CTC_MAGIC:
        return ['%s 不是 CTC\\0 或长度不足（%d 字节）' % (label, len(body))]
    ver, v8, v12 = struct.unpack_from('<III', body, 4)
    if (ver, v8, v12) != (22, 0, 1000):
        out.append('%s 头不对：version=%d +8=%d +12=%d（应为 22/0/1000）'
                   % (label, ver, v8, v12))
    groups, nodes = struct.unpack_from('<II', body, 0x10)
    need = 0x3C + 80 * groups + 96 * nodes
    if need > len(body):
        out.append('%s 组/节点越界：%d 组 + %d 节点 需要 %d，文件 %d'
                   % (label, groups, nodes, need, len(body)))
    return out

def _parse_ccl(body):
    if len(body) < 16 or body[:4] != CCL_MAGIC:
        raise ValueError('不是 CCL 条目')
    ver, n, size = struct.unpack_from('<3I', body, 4)
    if ver != 0x00080618:
        raise ValueError('CCL 版本 0x%08X 不认识' % ver)
    if size != n * 64 or len(body) != 16 + size:
        raise ValueError('CCL 长度不对（count=%d size=%d len=%d）' % (n, size, len(body)))
    out = []
    for i in range(n):
        o = 16 + i * 64
        a, b = struct.unpack_from('<HH', body, o + 4)
        out.append({'a': a, 'b': b,
                    'start': struct.unpack_from('<3f', body, o + 0x10),
                    'end': struct.unpack_from('<3f', body, o + 0x20),
                    'radius': struct.unpack_from('<f', body, o + 0x2C)[0]})
    return out

def _caps_equal(expected, actual, tol=1e-3):
    out = []
    if len(expected) != len(actual):
        out.append('胶囊数量不一致：写入 %d，读回 %d' % (len(expected), len(actual)))
    for i, (e, a) in enumerate(zip(expected, actual)):
        if int(e['a']) != int(a['a']) or int(e['b']) != int(a['b']):
            out.append('#%d 骨 id 不一致：写入 %s→%s，读回 %s→%s'
                       % (i, e['a'], e['b'], a['a'], a['b']))
        for key in ('start', 'end'):
            d = max(abs(float(e[key][k]) - float(a[key][k])) for k in range(3))
            if d > tol:
                out.append('#%d %s 偏移不一致（最大差 %.4f）：写入 %s，读回 %s'
                           % (i, '起点' if key == 'start' else '终点', d,
                              tuple(round(float(v), 3) for v in e[key]),
                              tuple(round(float(v), 3) for v in a[key])))
        dr = abs(float(e['radius']) - float(a['radius']))
        if dr > tol:
            out.append('#%d 半径不一致：写入 %.3f，读回 %.3f'
                       % (i, float(e['radius']), float(a['radius'])))
    return out

def check_arc_bytes(data, caps=None, want_ccl=None, strict_mod=True):
    entries, problems = _parse_arc(data)
    if not entries and problems:
        return problems
    out = list(problems)

    mods = [e for e in entries if e['body'][:4] == MOD_MAGIC]
    ctcs = [e for e in entries if e['body'][:4] == CTC_MAGIC]
    ccls = [e for e in entries if e['body'][:4] == CCL_MAGIC]
    xfss = [e for e in entries if e['body'][:4] == XFS_MAGIC]
    if len(mods) != 1:
        out.append('MOD 条目数 = %d（应为 1）' % len(mods))
    if len(ctcs) > 1:
        out.append('CTC 条目数 = %d（应为 0 或 1）' % len(ctcs))
    if len(ccls) > 1:
        out.append('CCL 条目数 = %d（应为 0 或 1）' % len(ccls))
    if mods and strict_mod:
        out.extend(_check_mod(mods[0]['body']))
    if ctcs:
        out.extend(_check_ctc(ctcs[0]['body']))
    if ccls and not ctcs:
        out.append('有 CCL 但没有 CTC：碰撞标志位没地方打开，胶囊不会生效')
    if want_ccl is True and not ccls:
        out.append('要求写 CCL，但读回没有 CCL 条目')
    if want_ccl is False and ccls:
        out.append('不应该写 CCL，但读回出现了 CCL 条目')

    if ccls:
        try:
            got = _parse_ccl(ccls[0]['body'])
        except Exception as e:
            out.append('CCL 解析失败：%r' % (e,))
            got = None
        if got is not None and caps:
            out.extend(_caps_equal(caps, got))

    return out

def arc_warnings(data):
    entries, problems = _parse_arc(data)
    if not entries:
        return list(problems)
    out = []
    ctcs = [e for e in entries if e['body'][:4] == CTC_MAGIC]
    ccls = [e for e in entries if e['body'][:4] == CCL_MAGIC]
    xfss = [e for e in entries if e['body'][:4] == XFS_MAGIC]
    if ccls and ctcs and ccls[0]['index'] != ctcs[0]['index'] + 1:
        out.append('CCL 没紧跟 CTC（CTC #%d，CCL #%d）'
                   % (ctcs[0]['index'], ccls[0]['index']))
    if xfss and len(xfss) > 1:
        out.append('XFS 条目 %d 条（通常 0 或 1 条）' % len(xfss))
    if xfss and xfss[0]['index'] != len(entries) - 1:
        out.append('XFS 不在最后一条（#%d / 共 %d 条）'
                   % (xfss[0]['index'], len(entries)))
    return out

def capsule_warnings(caps):
    warns = []
    if not caps:
        return ['自定义胶囊列表为空'], ''
    pairs = {}
    radii = []
    for i, c in enumerate(caps):
        a, b = int(c['a']), int(c['b'])
        for tag, v in (('骨A', a), ('骨B', b)):
            if v == CCL_BONE_NONE:
                continue
            if not (0 <= v <= CCL_BONE_MAX):
                warns.append('#%d %s id=%d 超出玩家骨架 0~%d（游戏只认 0~19）'
                             % (i, tag, v, CCL_BONE_MAX))
        r = float(c['radius'])
        radii.append(r)
        if not (0.1 <= r <= 400.0):
            warns.append('#%d 半径 %.2f 不在合理范围 0.1~400' % (i, r))
        m = max(abs(float(v)) for v in list(c['start']) + list(c['end']))
        if m > 512.0:
            warns.append('#%d 偏移量 |%.1f| 过大（超过 512 游戏单位）' % (i, m))
        key = (min(a, b), max(a, b))
        pairs[key] = pairs.get(key, 0) + 1
    dup = [(k, n) for k, n in pairs.items() if n > 1]
    if dup:
        warns.append('有 %d 对骨重复建胶囊：%s'
                     % (len(dup), ', '.join('%d-%d×%d' % (k[0], k[1], n) for k, n in dup[:4])))
    summary = '%d 条 | 半径 %.1f~%.1f | 骨 id %s' % (
        len(caps), min(radii), max(radii),
        ','.join(sorted({str(int(c['a'])) for c in caps} | {str(int(c['b'])) for c in caps})))
    return warns, summary

def write_arc_verified(dst, data, caps=None, want_ccl=None, backup=True,
                       strict_mod=True):
    issues = check_arc_bytes(data, caps=caps, want_ccl=want_ccl, strict_mod=strict_mod)
    if issues:
        raise ValueError('写入前校验不通过：\n  - ' + '\n  - '.join(issues[:10]))
    for w in arc_warnings(data):
        print('[MT] 警告：%s' % w)

    d = os.path.dirname(os.path.abspath(dst)) or '.'
    if not os.path.isdir(d):
        raise ValueError('目标目录不存在：%s' % d)
    tmp = os.path.join(d, '.%s.tmp_%s' % (os.path.basename(dst), _ts()))
    try:
        with open(tmp, 'wb') as f:
            f.write(data)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        with open(tmp, 'rb') as f:
            back = f.read()
        if len(back) != len(data):
            raise ValueError('落盘后长度不一致：写 %d，读回 %d' % (len(data), len(back)))
        issues2 = check_arc_bytes(back, caps=caps, want_ccl=want_ccl,
                                 strict_mod=strict_mod)
        if issues2:
            raise ValueError('落盘后校验不通过：\n  - ' + '\n  - '.join(issues2[:10]))
        backup_path = None
        if backup and os.path.exists(dst):
            backup_path = _uniq(dst + '.bak_' + _ts())
            shutil.copy2(dst, backup_path)
        os.replace(tmp, dst)
        return dst, backup_path
    except Exception as e:
        try:
            if os.path.exists(tmp):
                failed = _uniq(dst + '.failed_' + _ts())
                os.replace(tmp, failed)
                e = ValueError('%s\n（写坏了，已留在 %s；原文件未改动）'
                               % (e, os.path.basename(failed)))
        except Exception:
            pass
        raise e
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass

def describe(entries):
    return ' '.join('%s(%dB)' % (e['body'][:4].decode('latin-1').strip('\0') or '???',
                                 len(e['body'])) for e in entries)
