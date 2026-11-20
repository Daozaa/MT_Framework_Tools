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
        was_zlib = True
        try:
            body = zlib.decompress(raw)
        except Exception:
            was_zlib = False
            body = raw
            if flag & 0x40000000:
                problems.append('第 %d 条(%s) 标了压缩位，但 zlib 解压失败（%d 字节）'
                                % (i, name, csz))
                continue
        if size != (len(body) & 0xFFFFFF):
            problems.append('第 %d 条(%s) 长度字段 %d != 实际 %d（低 24 位 %d）'
                            % (i, name, size, len(body), len(body) & 0xFFFFFF))
        entries.append(dict(index=i, name=name, hash=h, flag=flag, raw=raw, body=body,
                            ofs=ofs, csz=csz, was_zlib=was_zlib))
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

MOD_VER = 0xD4
MESH_SZ = 48
MAT_NAME_SZ = 128
MRL_VER = 34
MRL_MAT_SZ = 60
MRL_TEX_SZ = 76

def _u16(buf, off):
    return struct.unpack_from('<H', buf, off)[0]

def _u32(buf, off):
    return struct.unpack_from('<I', buf, off)[0]

def _s16(buf, off):
    return struct.unpack_from('<h', buf, off)[0]

def _hf(buf, off):
    try:
        return struct.unpack_from('<e', buf, off)[0]
    except Exception:
        return float('nan')

def _tex_key(path):
    p = str(path).replace('\\', '/').strip().lower()
    while p.startswith('./'):
        p = p[2:]
    if p.endswith('.tex'):
        p = p[:-4]
    return p

def _mat_hash(name):
    return (zlib.crc32(name.encode('ascii', 'replace')) ^ 0xFFFFFFFF) & 0xFFFFFFFF

def _mesh_info(body, mesh_off, i):
    o = mesh_off + MESH_SZ * i
    return dict(
        index=i,
        meshtype=_u16(body, o),
        vert_count=_u16(body, o + 2),
        mat_slot=_u16(body, o + 5) >> 4,
        vert_stride=body[o + 10],
        vert_start=_u32(body, o + 12),
        vert_base=_u32(body, o + 16),
        fvf=_u32(body, o + 20),
        face_start=_u32(body, o + 24),
        face_count=_u32(body, o + 28),
        face_base=_u32(body, o + 32),
        min_index=_u16(body, o + 40),
        max_index=_u16(body, o + 42),
    )

def _check_weight_values(ids, weights, bone_count, where, out):
    if len(out) >= 8:
        return
    for k, (bid, w) in enumerate(zip(ids, weights)):
        if bid < 0 or bid >= bone_count:
            out.append('%s 骨骼索引 %d 越界（0~%d）' % (where, bid, bone_count - 1))
            return
        if not (w == w) or w < -0.005 or w > 1.005:
            out.append('%s 第 %d 个权重 %.5f 不在 0~1（允许 ±0.005 定点误差）'
                       % (where, k, w))
            return
    total = sum(weights)
    if total <= 1e-6:
        out.append('%s 权重和为 0（顶点会塌到原点）' % where)
    elif total > 1.02:
        out.append('%s 权重和 %.4f > 1（未归一化）' % (where, total))

def _check_vertex_weights(body, mesh, ptr_vertex, bone_count):
    out = []
    if bone_count <= 0 or mesh['vert_count'] <= 0:
        return out
    fvf = mesh['fvf']
    stride = mesh['vert_stride']
    base = ptr_vertex + mesh['vert_base'] + mesh['vert_start'] * stride
    vc = mesh['vert_count']
    if base < 0 or base + vc * stride > len(body):
        return ['分件 %d 顶点区越界（fvf=0x%08X, stride=%d）'
                % (mesh['index'], fvf, stride)]

    need = 0
    if fvf in (0x14D40019, 0x14D40020, 0x14D40021, 0x14D40022,
               0x64593023, 0x64593025, 0x2F55C03D):
        need = 28
    elif fvf in (0xBB424024, 0xBB424025, 0xCBCF7027):
        need = 36
    elif fvf == 0xDA55A021:
        need = 32
    elif fvf in (0xC31F201C, 0xC31F201D, 0xA013501E, 0xB3921020):
        need = 24
    elif fvf in (0xA8FAB018, 0xA8FAB019, 0x0CB6800E, 0x0CB68015,
                 0x0CB68016, 0xD877801B):
        need = 8
    elif fvf in (0xB0983013, 0xB0983014, 0xCBF6C01A):
        need = 8
    else:
        return out
    if stride < need:
        return ['分件 %d stride=%d 小于该 FVF 的最小 %d'
                % (mesh['index'], stride, need)]

    for vi in range(vc):
        o = base + vi * stride
        where = '分件 %d 顶点 %d' % (mesh['index'], vi)
        if fvf in (0x14D40019, 0x14D40020, 0x14D40021, 0x14D40022,
                  0x64593023, 0x64593025, 0x2F55C03D):
            ids = [body[o + 16], body[o + 17], body[o + 18], body[o + 19]]
            w1 = _s16(body, o + 6) / 32767.0
            w2 = _hf(body, o + 24)
            w3 = _hf(body, o + 26)
            _check_weight_values(ids, [w1, w2, w3, 1.0 - (w1 + w2 + w3)],
                                 bone_count, where, out)
        elif fvf in (0xBB424024, 0xBB424025, 0xCBCF7027):
            ids = [body[o + 16 + k] for k in range(8)]
            w1 = _s16(body, o + 6) / 32767.0
            w2 = body[o + 12] / 255.0
            w3 = body[o + 13] / 255.0
            w4 = body[o + 14] / 255.0
            w5 = body[o + 15] / 255.0
            w6 = _hf(body, o + 28)
            w7 = _hf(body, o + 30)
            w8 = 1.0 - (w1 + w2 + w3 + w4 + w5 + w6 + w7)
            _check_weight_values(ids, [w1, w2, w3, w4, w5, w6, w7, w8],
                                 bone_count, where, out)
        elif fvf == 0xDA55A021:
            ids = [body[o + 16 + k] for k in range(4)]
            weights = [body[o + 24 + k] / 255.0 for k in range(4)]
            _check_weight_values(ids, weights, bone_count, where, out)
        elif fvf in (0xC31F201C, 0xC31F201D):
            ids = []
            for off in (20, 22):
                v = _hf(body, o + off)
                if not (v == v) or abs(v - round(v)) > 1e-4:
                    out.append('%s 骨骼索引不是整数（%r）' % (where, v))
                    break
                ids.append(int(round(v)))
            else:
                w1 = _s16(body, o + 6) / 32767.0
                _check_weight_values(ids, [w1, 1.0 - w1], bone_count, where, out)
        elif fvf in (0xA013501E, 0xB3921020):
            ids = []
            for off in ((20, 22) if fvf == 0xA013501E else (16, 18)):
                v = _hf(body, o + off)
                if not (v == v) or abs(v - round(v)) > 1e-4:
                    out.append('%s 骨骼索引不是整数（%r）' % (where, v))
                    break
                ids.append(int(round(v)))
            else:
                w1 = _s16(body, o + 6) / 32767.0
                _check_weight_values(ids, [w1, 1.0 - w1], bone_count, where, out)
        elif fvf in (0xA8FAB018, 0xA8FAB019, 0x0CB6800E, 0x0CB68015,
                     0x0CB68016, 0xD877801B):
            bid = body[o + 6]
            _check_weight_values([bid], [1.0], bone_count, where, out)
        elif fvf in (0xB0983013, 0xB0983014):
            bid = body[o + 6]
            _check_weight_values([bid], [1.0], bone_count, where, out)
        elif fvf == 0xCBF6C01A:
            bid = body[o + 7]
            w = body[o + 6] / 255.0
            _check_weight_values([bid], [w], bone_count, where, out)
        if len(out) >= 8:
            break
    return out

def _check_faces(body, mesh, ptr_triangle, end_size):
    out = []
    if mesh['face_count'] <= 0:
        return out
    start = ptr_triangle + (mesh['face_start'] + mesh['face_base']) * 2
    end = start + mesh['face_count'] * 2
    if start < ptr_triangle or end > end_size:
        return ['分件 %d 索引区越界：start=%d count=%d end=%d / %d'
                % (mesh['index'], start, mesh['face_count'], end, end_size)]
    v0 = mesh['vert_start']
    v1 = v0 + mesh['vert_count']
    group_len = 0
    bad = 0
    for p in range(start, end, 2):
        w = _u16(body, p)
        if w == 0xFFFF:
            if group_len and group_len < 3:
                out.append('分件 %d 有一组只有 %d 个索引（三角/条带至少 3 个）'
                           % (mesh['index'], group_len))
            group_len = 0
            continue
        group_len += 1
        if w < v0 or w >= v1:
            bad += 1
            if bad <= 3:
                out.append('分件 %d 面索引 %d 越界（顶点 %d~%d）'
                           % (mesh['index'], w, v0, v1 - 1))
    if group_len and group_len < 3:
        out.append('分件 %d 末尾一组只有 %d 个索引（三角/条带至少 3 个）'
                   % (mesh['index'], group_len))
    return out

def _check_mod_deep(body, label='MOD'):
    out = []
    if len(body) < 0x40 or body[:4] != MOD_MAGIC:
        return ['%s 不是 MOD\\0 或长度不足（%d 字节）' % (label, len(body))]
    ver = _u16(body, 4)
    if ver != MOD_VER:
        out.append('%s 版本 0x%X，MHGU 应为 0x%X' % (label, ver, MOD_VER))
    bone_count, mesh_count, mat_count = struct.unpack_from('<HHH', body, 6)
    ptr_bone = _u32(body, 36)
    ptr_mat = _u32(body, 44)
    ptr_mesh = _u32(body, 48)
    ptr_vertex = _u32(body, 52)
    ptr_triangle = _u32(body, 56)
    end_size = _u32(body, 60)
    vertex_size = _u32(body, 24)
    triangle_count = _u32(body, 16)

    if mat_count <= 0 and mesh_count > 0:
        out.append('%s 有分件但材质数 = 0（网格会没有材质）' % label)
    if mesh_count and (ptr_mesh < 0x40 or ptr_mesh + mesh_count * MESH_SZ > len(body)):
        out.append('%s 分件表越界：ptr=%d count=%d' % (label, ptr_mesh, mesh_count))
    if mat_count and (ptr_mat < 0x40 or ptr_mat + mat_count * MAT_NAME_SZ > len(body)):
        out.append('%s 材质名表越界：ptr=%d count=%d' % (label, ptr_mat, mat_count))
    if ptr_vertex > ptr_triangle or (ptr_vertex and ptr_vertex < 0x40):
        out.append('%s 顶点区起始不对：ptr_vertex=%d ptr_triangle=%d'
                   % (label, ptr_vertex, ptr_triangle))
    if ptr_vertex + vertex_size != ptr_triangle:
        out.append('%s vertexBufferSize 不对：%d + %d != ptr_triangle %d'
                   % (label, ptr_vertex, vertex_size, ptr_triangle))
    index_words = max(0, (end_size - ptr_triangle) // 2)
    if abs(index_words - triangle_count) > 1:
        out.append('%s TriangleCount 与索引区不一致：索引区 %d 个 word，头部写 %d'
                   % (label, index_words, triangle_count))

    bone_count_ok = 0 < bone_count <= 255
    if not bone_count_ok:
        out.append('%s 骨数 %d 不在 1~255' % (label, bone_count))

    for i in range(mesh_count if ptr_mesh + mesh_count * MESH_SZ <= len(body) else 0):
        m = _mesh_info(body, ptr_mesh, i)
        if mat_count and m['mat_slot'] >= mat_count:
            out.append('分件 %d 材质槽 %d 越界（材质数 %d）'
                       % (i, m['mat_slot'], mat_count))
        if m['vert_stride'] <= 0:
            out.append('分件 %d vertStride = 0' % i)
            continue
        if m['vert_count']:
            vb = ptr_vertex + m['vert_base'] + m['vert_start'] * m['vert_stride']
            ve = vb + m['vert_count'] * m['vert_stride']
            if vb < ptr_vertex or ve > ptr_triangle:
                out.append('分件 %d 顶点区越界：%d~%d / %d'
                           % (i, vb, ve, ptr_triangle))
            else:
                out.extend(_check_vertex_weights(body, m, ptr_vertex, bone_count))
        out.extend(_check_faces(body, m, ptr_triangle, end_size))
        if len(out) >= 12:
            break
    return out

def _read_mod_mat_names(body):
    mat_count = _u16(body, 10)
    ptr_mat = _u32(body, 44)
    names = []
    for i in range(mat_count):
        o = ptr_mat + i * MAT_NAME_SZ
        names.append(body[o:o + MAT_NAME_SZ].split(b'\0', 1)[0]
                     .decode('ascii', 'replace'))
    return names

def _check_material_links(mod_body, mrl_body, tex_names, label='MRL'):
    out = []
    warn = []
    if len(mrl_body) < 0x1C or mrl_body[:4] != MRL_MAGIC:
        return ['%s 不是 MRL\\0 或长度不足（%d 字节）' % (label, len(mrl_body))], warn
    if _u32(mrl_body, 4) != MRL_VER:
        out.append('%s 版本 %d，应为 %d' % (label, _u32(mrl_body, 4), MRL_VER))
    mat_count = _u32(mrl_body, 8)
    tex_count = _u32(mrl_body, 12)
    tex_off = _u32(mrl_body, 20)
    desc = _u32(mrl_body, 24)
    if mat_count > 4096 or tex_count > 4096:
        return ['%s 材质/贴图数量异常：%d / %d' % (label, mat_count, tex_count)], warn
    if desc < 28 or desc + mat_count * MRL_MAT_SZ > len(mrl_body):
        return ['%s 材质描述表越界：desc=%d count=%d len=%d'
                % (label, desc, mat_count, len(mrl_body))], warn
    if tex_off < 28 or tex_off + tex_count * MRL_TEX_SZ > desc:
        out.append('%s 贴图表越界：tex_off=%d count=%d desc=%d'
                   % (label, tex_off, tex_count, desc))
    mod_mats = _read_mod_mat_names(mod_body)
    if len(mod_mats) != mat_count:
        warn.append('MOD 材质数 %d != MRL 材质数 %d' % (len(mod_mats), mat_count))
    hashes = []
    descs = []
    for i in range(mat_count):
        o = desc + i * MRL_MAT_SZ
        h = _u32(mrl_body, o + 4)
        size = _u32(mrl_body, o + 8)
        commands = _u32(mrl_body, o + 24) & 0xFFF
        anim_len = _u32(mrl_body, o + 48)
        param_off = _u32(mrl_body, o + 52)
        anim_off = _u32(mrl_body, o + 56)
        hashes.append(h)
        descs.append(dict(o=o, h=h, size=size, commands=commands,
                          anim_len=anim_len, param_off=param_off, anim_off=anim_off))
        if param_off < desc + mat_count * MRL_MAT_SZ or param_off + size > len(mrl_body):
            out.append('材质 %d 参数块越界：off=%d size=%d' % (i, param_off, size))
        elif commands * 12 > size:
            out.append('材质 %d 渲染指令数 %d 超过参数块 %d 字节'
                       % (i, commands, size))
        if bool(anim_len) != bool(anim_off):
            out.append('材质 %d 动画块只填了长度或偏移的一半' % i)
        elif anim_len and (anim_off < desc + mat_count * MRL_MAT_SZ
                           or anim_off + anim_len > len(mrl_body)):
            out.append('材质 %d 动画块越界：off=%d len=%d' % (i, anim_off, anim_len))
    dup = sorted({h for h in hashes if hashes.count(h) > 1})
    if dup:
        out.append('%s 材质哈希重复 %s（无法唯一匹配）'
                   % (label, ','.join('0x%08X' % h for h in dup[:4])))
    for name in mod_mats:
        h = _mat_hash(name)
        if h not in hashes:
            out.append('材质「%s」的哈希 0x%08X 在 MRL 里找不到（网格不会显示）'
                       % (name, h))

    tex_paths = {}
    for i in range(tex_count):
        o = tex_off + i * MRL_TEX_SZ
        p = mrl_body[o + 12:o + 76].split(b'\0', 1)[0].decode('ascii', 'replace')
        tex_paths[i + 1] = p
    for i, d in enumerate(descs):
        o = d['o']
        for j in range(min(d['commands'], 4096)):
            q = d['param_off'] + 12 * j
            kind, value, word = struct.unpack_from('<3I', mrl_body, q)
            if kind & 15 != 3:
                continue
            if value > tex_count:
                out.append('材质 %d 采样器指向不存在的 TEX 槽 %d（共 %d）'
                           % (i, value, tex_count))
                continue
            if value == 0:
                continue
            path = tex_paths.get(value, '')
            if not path:
                continue
            if _tex_key(path) not in tex_names:
                msg = ('材质 %d 采样器 0x%03X 的贴图「%s」不在 ARC 里'
                       % (i, word & 0xFFF, path))
                if (word & 0xFFF) == 0x371:
                    out.append(msg + '（颜色贴图缺失）')
                else:
                    warn.append(msg)
    return out, warn

def _deep_errors(entries):
    out = []
    keys = {}
    ranges = []
    for e in entries:
        key = (e['name'].replace('\\', '/'), e['hash'])
        if key in keys:
            out.append('条目重复：%s / 0x%08X' % key)
        keys[key] = 1
        ranges.append((e['ofs'], e['ofs'] + e['csz'], e['name']))
    ranges.sort()
    for (_, end, first), (begin, _, second) in zip(ranges, ranges[1:]):
        if end > begin:
            out.append('数据区重叠：%s 与 %s' % (first, second))
    mods = [e for e in entries if e['body'][:4] == MOD_MAGIC]
    mrls = [e for e in entries if e['body'][:4] == MRL_MAGIC]
    texs = {_tex_key(e['name']): e for e in entries if e['body'][:4] == b'TEX\x00'}
    if len(mods) == 1:
        out.extend(_check_mod_deep(mods[0]['body']))
        if len(mods[0]['body']) >= 0x40 and _u16(mods[0]['body'], 10) > 0:
            if len(mrls) != 1:
                out.append('MOD 有材质，但 MRL 条目数 = %d（应为 1）' % len(mrls))
            else:
                errs, _warns = _check_material_links(mods[0]['body'], mrls[0]['body'], texs)
                out.extend(errs)
    return out

def _deep_warnings(entries):
    out = []
    for e in entries:
        compressed = bool(e['flag'] & 0x40000000)
        if compressed != e['was_zlib']:
            out.append('条目 %s 压缩标记与实际数据不一致' % e['name'])
    mods = [e for e in entries if e['body'][:4] == MOD_MAGIC]
    mrls = [e for e in entries if e['body'][:4] == MRL_MAGIC]
    texs = {_tex_key(e['name']): e for e in entries if e['body'][:4] == b'TEX\x00'}
    if len(mods) == 1 and len(mrls) == 1 and len(mods[0]['body']) >= 0x40:
        if _u16(mods[0]['body'], 10) > 0:
            _errs, warns = _check_material_links(mods[0]['body'], mrls[0]['body'], texs)
            out.extend(warns)
            mrl_i = mrls[0]['index']
            for e in texs.values():
                if e['index'] > mrl_i and e['name'].lower().endswith(('_bm+a', '_bm+a.tex')):
                    out.append('动画贴图 %s 排在 MRL 后面' % e['name'])
    for mod in mods:
        body = mod['body']
        if len(body) < 0x40:
            continue
        mesh_count = _u16(body, 8)
        if mesh_count == 0:
            out.append('MOD 分件数为 0（空模型）')
        ptr_triangle = _u32(body, 56)
        end_size = _u32(body, 60)
        triangle_count = _u32(body, 16)
        index_words = max(0, (end_size - ptr_triangle) // 2)
        if index_words - triangle_count == 1:
            out.append('MOD TriangleCount 比索引区少 1 个 word（通常是末尾 0xFFFF 分隔符）')
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
    if strict_mod:
        out.extend(_deep_errors(entries))
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
    out.extend(_deep_warnings(entries))
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
