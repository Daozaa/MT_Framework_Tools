from __future__ import annotations

import struct

BONE_INFO_SIZE = 24
BONE_MATRIX_SIZE = 64
BONE_LUT_SIZE = 256
BONE_MATRIX_TRANS_OFFSET = 48

def bone_section_offsets(ptr_bone, bone_count):
    info_off = int(ptr_bone)
    local_off = info_off + bone_count * BONE_INFO_SIZE
    world_off = local_off + bone_count * BONE_MATRIX_SIZE
    lut_off = world_off + bone_count * BONE_MATRIX_SIZE
    return info_off, local_off, world_off, lut_off

def read_bone_section(data, ptr_bone, bone_count):
    info_off, local_off, world_off, lut_off = bone_section_offsets(
        ptr_bone, bone_count)
    if lut_off + BONE_LUT_SIZE > len(data):
        raise ValueError(
            "骨骼段超出文件范围 (ptr_Bone=%d, N=%d, 需要到 %d, 文件 %d)"
            % (ptr_bone, bone_count, lut_off + BONE_LUT_SIZE, len(data)))

    infos = []
    local_t = []
    world_t = []
    for i in range(bone_count):
        o = info_off + i * BONE_INFO_SIZE
        infos.append({
            'ID': data[o],
            'Parent': data[o + 1],
            'Child': data[o + 2],
            'uk1': data[o + 3],

            'uk4': struct.unpack_from('<f', data, o + 4)[0],
            'len': struct.unpack_from('<f', data, o + 8)[0],
            't': list(struct.unpack_from('<3f', data, o + 12)),
        })
        local_t.append(tuple(struct.unpack_from(
            '<3f', data, local_off + i * BONE_MATRIX_SIZE
            + BONE_MATRIX_TRANS_OFFSET)))
        world_t.append(tuple(struct.unpack_from(
            '<3f', data, world_off + i * BONE_MATRIX_SIZE
            + BONE_MATRIX_TRANS_OFFSET)))

    scale = _scale_from_matrix(data, world_off)
    return {
        'infos': infos, 'local_t': local_t, 'world_t': world_t,
        'scale': scale,
        'offsets': (info_off, local_off, world_off, lut_off),
    }

def _scale_from_matrix(data, world_off):
    s = abs(struct.unpack_from('<f', data, world_off)[0])
    if s < 1e-6:
        s = 1.0
    return s

def bone_head_to_file_translation(p, scale):
    return (-p[0] * scale, -p[2] * scale, p[1] * scale)

def root_record(infos):
    n = len(infos)
    for i, inf in enumerate(infos):
        par = inf['Parent']
        if par == i or not (0 <= par < n):
            return i
    return None

def plan_bone_write(data, ptr_bone, bone_count, arm_obj, name_map=None,
                    offset=None, anchor=True, template_bytes=None,
                    cur_mesh_min_y=None):
    import bpy
    from mathutils import Matrix, Vector

    if bone_count <= 0 or arm_obj is None:
        return None
    sec = read_bone_section(data, ptr_bone, bone_count)
    infos = sec['infos']
    scale = sec['scale']
    off = Vector(offset) if offset is not None else Vector((0.0, 0.0, 0.0))

    rec_of = {}
    for b in arm_obj.data.bones:
        idx = None
        if name_map:
            idx = name_map.get(b.name)
        if idx is None:
            idx = _record_from_name(b.name)
        if idx is None or not (0 <= idx < bone_count):
            continue
        rec_of.setdefault(idx, b)
    if not rec_of:
        raise ValueError("骨架 %s 里没有一根骨骼能对上骨序号 (b_N)" % arm_obj.name)

    rec_by_name = {b.name: i for i, b in rec_of.items()}
    new_parent = {}
    _par_skipped = 0
    for idx, b in rec_of.items():
        p = getattr(b, 'parent', None)
        if p is None:
            continue
        pid = rec_by_name.get(p.name)
        if pid is None or not (0 <= pid < bone_count) or pid == idx:
            _par_skipped += 1
            continue
        if pid != infos[idx]['Parent']:
            new_parent[idx] = pid
    for idx, pid in new_parent.items():
        infos[idx]['Parent'] = pid

    rel = Matrix.Translation(-off) @ arm_obj.matrix_world

    new_world = [tuple(v) for v in sec['world_t']]
    for idx, b in rec_of.items():
        new_world[idx] = bone_head_to_file_translation(rel @ b.head_local, scale)

    magnitude = 1.0
    for w in list(new_world) + list(sec['world_t']):
        for v in w:
            if abs(v) > magnitude:
                magnitude = abs(v)
    tol = 1e-5 * magnitude
    _snapped = 0
    for idx in list(rec_of.keys()):
        ow = sec['world_t'][idx]
        nw = new_world[idx]
        if max(abs(nw[k] - ow[k]) for k in range(3)) <= tol:
            new_world[idx] = ow
            _snapped += 1

    _anchor_delta = None
    _anchor_dbg = None
    if anchor:
        _r = root_record(infos)
        if _r is not None:

            _tpl_root_wz = -sec['world_t'][_r][1] / (scale or 1.0)
            _cur_root_wz = -new_world[_r][1] / (scale or 1.0)
            _tpl_mesh = mesh_min_y(template_bytes) if template_bytes is not None \
                else None
            _cur_mesh = cur_mesh_min_y
            _anchor_dbg = {
                'tpl_mesh': _tpl_mesh, 'cur_mesh': _cur_mesh,
                'tpl_root_wz': _tpl_root_wz, 'cur_root_wz': _cur_root_wz,
                'has_tpl_bytes': template_bytes is not None,
                'gap': None, 'threshold': None,
            }
            if _tpl_mesh is not None and _cur_mesh is not None:
                _tpl_rel = _tpl_mesh - _tpl_root_wz
                _cur_rel = _cur_mesh - _cur_root_wz
                _gap = _cur_rel - _tpl_rel
                _anchor_dbg['gap'] = _gap
                _anchor_dbg['tpl_rel'] = _tpl_rel
                _anchor_dbg['cur_rel'] = _cur_rel
                _anchor_dbg['threshold'] = tol / max(scale or 1.0, 1e-9)
                if abs(_gap) > tol / max(scale or 1.0, 1e-9):

                    _dy = -_gap * (scale or 1.0)
                    _anchor_delta = (0.0, _dy, 0.0)
                    for _i in range(bone_count):
                        _w = list(new_world[_i])
                        _w[1] += _dy
                        new_world[_i] = tuple(_w)
                    for _i in range(bone_count):
                        if max(abs(new_world[_i][k] - sec['world_t'][_i][k])
                               for k in range(3)) <= tol:
                            new_world[_i] = sec['world_t'][_i]

    root = root_record(infos)
    new_local = [list(v) for v in sec['local_t']]
    for i in range(bone_count):
        par = infos[i]['Parent']
        if not (0 <= par < bone_count) or par == i:

            continue
        parent_moved = max(abs(new_world[par][k] - sec['world_t'][par][k])
                           for k in range(3)) > tol
        self_moved = max(abs(new_world[i][k] - sec['world_t'][i][k])
                         for k in range(3)) > tol
        if not (parent_moved or self_moved) and i not in new_parent:
            continue
        new_local[i] = [-(new_world[i][k] - new_world[par][k]) for k in range(3)]

    for i in range(bone_count):
        ol = sec['local_t'][i]
        nl = new_local[i]
        if max(abs(nl[k] - ol[k]) for k in range(3)) <= tol:
            new_local[i] = list(ol)

    return {
        'sec': sec,
        'new_local': [tuple(v) for v in new_local],
        'new_world': new_world,
        'unmapped': bone_count - len(rec_of),
        'root': root,
        'snapped': _snapped,
        'anchor_delta': _anchor_delta,
        'anchor_dbg': _anchor_dbg,
        'tol': tol,
        'scale': scale,
        'offsets': sec['offsets'],
        'new_parent': new_parent,
        'parent_skipped': _par_skipped,
    }

def mesh_min_y(data, on_error=None):
    h = None
    try:
        import struct as _s
        h = _header_of(data)
        pv = int(getattr(h, 'ptr_vertex', 0) or 0)
        pm = int(getattr(h, 'ptr_Mesh', 0) or 0)
        mc = int(getattr(h, 'MeshCount', 0) or 0)
        if not (pv and pm and mc):
            if on_error is not None:
                on_error.append('头部指针为空 pv=%s pm=%s mc=%s' % (pv, pm, mc))
            return None
        lo = 1e30
        found = False
        skipped = 0
        for i in range(mc):
            o = pm + i * 48
            if o + 48 > len(data):
                skipped += 1
                continue
            vc = _s.unpack_from('<h', data, o + 2)[0]
            st = data[o + 10]
            vs = _s.unpack_from('<i', data, o + 12)[0]
            vb = _s.unpack_from('<i', data, o + 16)[0]
            if not vc or st <= 0:
                skipped += 1
                continue
            base = pv + vb + st * vs
            if base < 0 or base + vc * st > len(data):
                skipped += 1
                continue
            for k in range(vc):
                _x, y, _z = _s.unpack_from('<3h', data, base + k * st)
                y = y / 32767.0
                if y < lo:
                    lo = y
                found = True
        if not found and on_error is not None:
            on_error.append('没有可读的子网格 (跳过 %d/%d, ptr_vertex=%d)'
                            % (skipped, mc, pv))
        return lo if found else None
    except Exception as e:
        if on_error is not None:
            on_error.append('%s: %s' % (type(e).__name__, str(e)[:70]))
        return None

def _header_of(data):
    return _MiniHeader(data)

class _MiniHeader(object):

    def __init__(self, data):
        import struct as _s
        self.BoneCount = _s.unpack_from('<h', data, 6)[0]
        self.MeshCount = _s.unpack_from('<h', data, 8)[0]
        self.VertCount = _s.unpack_from('<i', data, 12)[0]
        self.ptr_Bone = _s.unpack_from('<i', data, 36)[0]
        self.ptr_Mesh = _s.unpack_from('<i', data, 48)[0]
        self.ptr_vertex = _s.unpack_from('<i', data, 52)[0]
        self.ptr_triangle = _s.unpack_from('<i', data, 56)[0]

def check_export(data, ptr_bone, bone_count, plan, mesh_objs, coff=None,
                 template_bytes=None, arm_obj=None):
    msgs = []
    info = {}
    _arm_for_check = arm_obj

    _objs = [o for o in (mesh_objs or []) if o is not None and o.type == 'MESH']
    if not _objs:
        try:
            import bpy as _bpy
            _objs = [o for o in _bpy.context.scene.objects if o.type == 'MESH']
            info['mesh_source'] = '场景全部网格 (调用方没给)'
        except Exception:
            _objs = []
    else:
        info['mesh_source'] = '导出实际写入的网格'
    info['mesh_checked'] = len(_objs)

    lim = 0.98
    mx = 0.0
    worst = None
    for o in _objs:
        if o is None or o.type != 'MESH':
            continue
        mw = o.matrix_world
        c = coff
        try:
            from .MTframework_MHGU import get_object_center_offset as _g
            c = _g(o)
        except Exception:
            pass
        try:
            for v in o.data.vertices:
                w = (mw @ v.co) - c
                m = max(abs(w.x), abs(w.z), abs(w.y))
                if m > mx:
                    mx = m
                    worst = o.name
        except Exception as e:
            msgs.append("顶点范围检查失败: %s" % e)
            break
    info['vert_max'] = mx
    info['vert_worst'] = worst
    if mx > 1.0:
        msgs.append(
            "顶点超出 ±1.0 (最大 %.4f, 在 %s) —— 超出部分会被 int16 钳位"
            "**压扁/截断**。把模型整体挪进 ±1.0 范围内再导出。"
            % (mx, worst))
    elif mx > lim:
        msgs.append("顶点接近上限 (最大 %.4f, 在 %s), 余量很小。"
                    % (mx, worst))

    if plan is not None and bone_count > 0:
        try:
            infos = plan['sec']['infos']
            nl = plan['new_local']
            nw = plan['new_world']
            pw = [None] * bone_count
            for _ in range(bone_count * 4):
                for i in range(bone_count):
                    if pw[i] is not None:
                        continue
                    par = infos[i]['Parent']
                    if par == i or not (0 <= par < bone_count):
                        pw[i] = tuple(nl[i])
                    elif pw[par] is not None:
                        pw[i] = tuple(pw[par][k] + nl[i][k] for k in range(3))
            if all(v is not None for v in pw):
                cs = [tuple(nw[i][k] + pw[i][k] for k in range(3))
                      for i in range(bone_count)]
                c0 = cs[0]
                spread = max(max(abs(cs[i][k] - c0[k]) for k in range(3))
                             for i in range(bone_count))
                mag = max(1.0, max(abs(v) for c in cs for v in c))
                info['amat_c'] = c0
                info['amat_spread'] = spread
                if spread > 1e-3 * mag:
                    msgs.append(
                        "骨骼段三份不同步: amat_t + p_world 在各槽位不是同一个常量 C "
                        "(最大偏差 %.5f)。绑到这些骨上的几何会在游戏里整体平移。"
                        "检查写入时 BoneInfo / lmat / amat 三份是否都更新了。"
                        % spread)
        except Exception as e:
            msgs.append("骨骼段不变量检查失败: %s" % e)

    _mesh_lo = None
    try:
        _lo = 1e30
        for o in _objs:
            mw = o.matrix_world
            c = coff
            try:
                from .MTframework_MHGU import get_object_center_offset as _g3
                c = _g3(o)
            except Exception:
                pass
            for v in o.data.vertices:
                z = (mw @ v.co).z - c.z
                if z < _lo:
                    _lo = z
        if _lo < 1e29:
            _mesh_lo = _lo
    except Exception:
        pass
    info['mesh_min'] = _mesh_lo
    if _mesh_lo is not None:

        _tol0 = 1e-3
        if _mesh_lo > _tol0:
            msgs.append(
                "网格最低点在文件 Y = %+.5f, 而官方 500 个文件**全部**是 0.00000。"
                "模型在游戏里会整体**悬空** %.5f (文件单位约 %.2f)。"
                "把模型下移 %.5f 再导出。" % (_mesh_lo, _mesh_lo, _mesh_lo * 100,
                                            _mesh_lo))
        elif _mesh_lo < -_tol0:
            msgs.append(
                "网格最低点在文件 Y = %+.5f, 而官方 500 个文件**全部**是 0.00000。"
                "模型在游戏里会整体**陷进地面** %.5f (文件单位约 %.2f)。"
                "把模型上移 %.5f 再导出。" % (_mesh_lo, _mesh_lo, -_mesh_lo * 100,
                                            -_mesh_lo))

    if _arm_for_check is not None:
        try:
            _rec = _arm_for_check.get('MT_CenterOffsetObj')
            _loc = _arm_for_check.location
            if _rec:
                _dv = (_loc[0] - float(_rec[0]),
                       _loc[1] - float(_rec[1]),
                       _loc[2] - float(_rec[2]))
                info['arm_moved'] = _dv
                if max(abs(x) for x in _dv) > 1e-4:
                    msgs.append(
                        "骨架对象被移动过: location %s, 而导入时记录的是 %s, "
                        "差 %s。干净导入时两者应当相等。"
                        "如果你是想让模型适配骨架, 应该移动**模型**而不是骨架。"
                        % (tuple(round(x, 5) for x in _loc),
                           tuple(round(float(x), 5) for x in _rec),
                           tuple(round(x, 5) for x in _dv)))
        except Exception:
            pass

    if plan is not None:
        sec = plan['sec']
        n = bone_count
        dw = 0.0
        for i in range(n):
            o = sec['world_t'][i]
            v = plan['new_world'][i]
            dw = max(dw, max(abs(v[k] - o[k]) for k in range(3)))
        info['bone_delta'] = dw
        mag = max(1.0, max(max(abs(x) for x in w) for w in sec['world_t']))
        if dw > 1e-4 * mag + 1e-4:
            msgs.append(
                "骨架相对模板挪动了 (最大 %.4f 文件单位)。如果这**不是**你有意"
                "移动的, 角色在游戏里的落点会跟着变 —— 请把骨架对回原位再导出。"
                % dw)
        r = plan.get('root')
        info['root_old'] = sec['world_t'][r] if r is not None else None
        info['root_new'] = plan['new_world'][r] if r is not None else None
        info['moved_bones'] = sum(
            1 for i in range(n)
            if plan['new_world'][i] != sec['world_t'][i]
            or plan['new_local'][i] != sec['local_t'][i])

        S = sec['scale'] or 1.0

        _err = []
        tpl_mesh = mesh_min_y(
            template_bytes if template_bytes is not None else data, _err)
        info['tpl_mesh_err'] = _err[0] if _err else None
        tpl_bone = max(sec['world_t'][i][1] for i in range(n))
        tpl_bone_wz = -tpl_bone / S
        cur_bone = max(plan['new_world'][i][1] for i in range(n))
        cur_bone_wz = -cur_bone / S
        cur_mesh = None
        if _objs:
            lo = 1e30
            for o in _objs:
                mw = o.matrix_world
                c = coff
                try:
                    from .MTframework_MHGU import get_object_center_offset as _g2
                    c = _g2(o)
                except Exception:
                    pass
                for v in o.data.vertices:
                    z = (mw @ v.co).z - c.z
                    if z < lo:
                        lo = z
            if lo < 1e29:
                cur_mesh = lo
        if tpl_mesh is not None and cur_mesh is not None:
            rel_t = tpl_mesh - tpl_bone_wz
            rel_c = cur_mesh - cur_bone_wz
            d = rel_c - rel_t
            info['rel_template'] = rel_t
            info['rel_current'] = rel_c
            info['rel_delta'] = d
            info['rel_delta_file'] = d * S
        info['tpl_mesh'] = tpl_mesh
        info['cur_mesh'] = cur_mesh
        info['tpl_bone_wz'] = tpl_bone_wz
        info['cur_bone_wz'] = cur_bone_wz
        if info.get('rel_delta') is not None and abs(info['rel_delta']) > 2e-3:
            msgs.append(
                "网格与骨架的相对关系变了 %.5f (文件单位约 %.2f)。"
                "模板里「网格最低点 - 最低骨骼」= %.5f, 现在是 %.5f。"
                "这会让模型在游戏里整体%s。"
                % (info['rel_delta'], info['rel_delta'] * S,
                   info['rel_template'], info['rel_current'],
                   '偏高' if info['rel_delta'] > 0 else '偏低'))
    return msgs, info

def find_armature(armatures, bone_count, name_map=None):
    if not armatures:
        return None, "场景里没有骨架 (Armature)"
    cands = []
    for a in armatures:
        try:
            if a is None or a.type != 'ARMATURE':
                continue
            nb = len(a.data.bones)
        except Exception:
            continue
        if nb != bone_count:
            continue

        m = None
        try:
            from .MTframework_MHGU import get_armature_bone_name_map as _g
            m = _g(a)
        except Exception:
            m = None
        if not m:
            m = name_map or {}
        named = 0
        for b in a.data.bones:
            idx = m.get(b.name)
            if idx is None:
                idx = _record_from_name(b.name)
            if idx is not None:
                named += 1
        cands.append((named, a))
    if not cands:
        return None, "没有骨骼数 = %d 的骨架" % bone_count
    cands.sort(key=lambda x: -x[0])
    return cands[0][1], ""

def _record_from_name(name):
    if not name or not name.startswith('b_'):
        return None
    rest = name[2:]
    if not rest.isdigit():
        return None
    try:
        return int(rest) - 1
    except ValueError:
        return None

def write_bone_section(data, ptr_bone, bone_count, arm_obj, name_map=None,
                       offset=None, anchor=True, template_bytes=None,
                       cur_mesh_min_y=None):
    plan = plan_bone_write(data, ptr_bone, bone_count, arm_obj,
                           name_map=name_map, offset=offset, anchor=anchor,
                           template_bytes=template_bytes,
                           cur_mesh_min_y=cur_mesh_min_y)
    if plan is None:
        return None
    info_off, local_off, world_off, lut_off = plan['offsets']
    sec = plan['sec']

    for i in range(bone_count):
        o = info_off + i * BONE_INFO_SIZE
        t = plan['new_local'][i]
        w = plan['new_world'][i]
        old_t = sec['local_t'][i]
        old_w = sec['world_t'][i]

        _np = (plan.get('new_parent') or {}).get(i)
        if t == old_t and w == old_w and _np is None:
            continue
        if _np is not None:

            data[o + 1] = _np

        if t != old_t:
            ln = (t[0] ** 2 + t[1] ** 2 + t[2] ** 2) ** 0.5

            struct.pack_into('<f', data, o + 8, ln)
            struct.pack_into('<3f', data, o + 12, t[0], t[1], t[2])
            struct.pack_into('<3f', data,
                             local_off + i * BONE_MATRIX_SIZE
                             + BONE_MATRIX_TRANS_OFFSET, t[0], t[1], t[2])
        if w != old_w:
            struct.pack_into('<3f', data,
                             world_off + i * BONE_MATRIX_SIZE
                             + BONE_MATRIX_TRANS_OFFSET, w[0], w[1], w[2])
    return plan
