from __future__ import annotations

import os
import re
import struct
import tempfile

try:
    import bpy
    from bpy.types import Operator
    from mathutils import Matrix, Vector
except Exception:
    bpy = None

from .MTframework_MHGU_boneadd import _bounds, _worlds
from .MTframework_MHGU_bones import bone_head_to_file_translation
from .MTframework_MHGU_phys import remember_arc
from .MTframework_MHGU_physparams import PHYS_PRESETS

INFO = 24
MAT = 64
PHYS_MIN = 20
PHYS_MAX = 254
GROUP_SZ = 80
NODE_SZ = 96
HDR_SZ = 0x3C

_GROUP_ID = 8960
_COL_ATTR = 0xFFFFFFFF
_COL_GROUP = 1
_COL_TYPE = 1
_FILL = 0xCDCDCDCD

_CTC_HEAD_TMPL = (
    b'CTC\x00' + struct.pack('<III', 22, 0, 1000)
    + struct.pack('<II', 0, 0)
    + struct.pack('<I', 0)
    + struct.pack('<f', 1.0 / 60.0)
    + struct.pack('<fff', 1.0, 0.0, 1.0)
    + struct.pack('<ff', 1.0, 1.0)
    + b'\x01' * 6 + b'\x00\x00'
)

_HEAD_STD = dict(step=1.0 / 60.0, g_scale=1.0, f24=0.0, f28=1.0, f2c=1.0, f30=1.0)

def fix_ctc_header(ctc):
    if not ctc or ctc[:4] != b'CTC\x00' or len(ctc) < 0x34:
        return ctc, [], False
    b = bytearray(ctc)
    old = []
    changed = False
    for off, key in ((0x1C, 'step'), (0x20, 'g_scale'), (0x24, 'f24'),
                     (0x28, 'f28'), (0x2C, 'f2c'), (0x30, 'f30')):
        v = struct.unpack_from('<f', b, off)[0]
        old.append(round(v, 4))
        nv = _HEAD_STD[key]
        if abs(v - nv) > 1e-6:
            struct.pack_into('<f', b, off, nv)
            changed = True
    return bytes(b), old, changed

def _parse(mod):
    n, ptr, lmat, amat, lut = _bounds(mod)
    c, worlds = _worlds(mod)
    scale = abs(struct.unpack_from('<f', mod, amat)[0]) or 1.0
    bones = []
    for i in range(n):
        o = ptr + i * INFO
        bones.append(dict(slot=i, id=mod[o], parent=mod[o + 1],
                          length=struct.unpack_from('<f', mod, o + 8)[0],
                          local=struct.unpack_from('<3f', mod, o + 12),
                          world=worlds[i]))
    return dict(n=n, ptr=ptr, lmat=lmat, amat=amat, lut=lut, c=c,
                scale=scale, bones=bones)

def _split_ctc(ctc):
    if not ctc or ctc[:4] != b'CTC\x00' or len(ctc) < HDR_SZ:
        return bytearray(_CTC_HEAD_TMPL), [], [], b''
    ng = struct.unpack_from('<I', ctc, 0x10)[0]
    nc = struct.unpack_from('<I', ctc, 0x14)[0]
    if ng > 64 or nc > 4096:
        raise ValueError('现有 CTC 头异常（组 %d / 节点 %d）' % (ng, nc))
    g_off = HDR_SZ
    n_off = HDR_SZ + GROUP_SZ * ng
    tail_off = n_off + NODE_SZ * nc
    if len(ctc) < tail_off:
        raise ValueError('现有 CTC 长度不足')
    groups = [ctc[g_off + i * GROUP_SZ: g_off + (i + 1) * GROUP_SZ] for i in range(ng)]
    nodes = [ctc[n_off + i * NODE_SZ: n_off + (i + 1) * NODE_SZ] for i in range(nc)]
    return bytearray(ctc[:HDR_SZ]), groups, nodes, ctc[tail_off:]

def _group_bytes(count, preset):
    _nm, grav, damp, spring, wind, trans, limit, reflect = preset[:8]
    g = bytearray(GROUP_SZ)
    struct.pack_into('<I', g, 0, count)
    struct.pack_into('<I', g, 4, _GROUP_ID)
    struct.pack_into('<I', g, 8, _COL_ATTR)
    struct.pack_into('<I', g, 12, _COL_GROUP)
    struct.pack_into('<I', g, 16, _COL_TYPE)
    for off in (20, 24, 28):
        struct.pack_into('<I', g, off, _FILL)
    struct.pack_into('<3f', g, 32, 0.0, float(grav), 0.0)
    struct.pack_into('<f', g, 44, 0.0)
    struct.pack_into('<f', g, 48, float(damp))
    struct.pack_into('<f', g, 52, float(trans))
    struct.pack_into('<f', g, 56, float(spring))
    struct.pack_into('<f', g, 60, float(wind))
    struct.pack_into('<f', g, 64, float(limit))
    struct.pack_into('<f', g, 68, 0.0)
    struct.pack_into('<f', g, 72, float(reflect))
    struct.pack_into('<I', g, 76, _FILL)
    return bytes(g)

def _node_bytes(jid, is_head, direction, preset, identity=False,
                axis=None, values=None):
    _nm, grav, damp, spring, wind, trans, limit, reflect, angle, mass, elastic = preset
    if values is not None:
        angle, mass, elastic = values
    if identity:
        mat = (1.0, 0.0, 0.0, 0.0,
               0.0, 1.0, 0.0, 0.0,
               0.0, 0.0, 1.0, 0.0,
               0.0, 0.0, 0.0, 1.0)
    else:
        d = Vector(direction) if direction is not None else Vector((0.0, -1.0, 0.0))
        if d.length < 1e-6:
            d = Vector((0.0, -1.0, 0.0))
        r0 = d.normalized()
        a = Vector(axis) if axis is not None else Vector((1.0, 0.0, 0.0))
        if a.length < 1e-6:
            a = Vector((1.0, 0.0, 0.0))
        r1 = a - r0 * a.dot(r0)
        if r1.length < 1e-6:
            a = Vector((0.0, 1.0, 0.0))
            r1 = a - r0 * a.dot(r0)
        r1.normalize()
        r2 = r0.cross(r1)
        mat = (r0.x, r0.y, r0.z, 0.0,
               r1.x, r1.y, r1.z, 0.0,
               r2.x, r2.y, r2.z, 0.0,
               0.0, 0.0, 0.0, 1.0)

    nd = bytearray(NODE_SZ)
    nd[0] = jid
    nd[1] = 0
    nd[2] = 1 if is_head else 0
    nd[3] = 0
    nd[4:8] = b'\x01\x00\x01\x01'
    struct.pack_into('<f', nd, 8, 5.0)
    struct.pack_into('<I', nd, 12, _FILL)
    struct.pack_into('<16f', nd, 16, *mat)
    struct.pack_into('<f', nd, 80, float(angle))
    struct.pack_into('<f', nd, 84, float(mass))
    struct.pack_into('<f', nd, 88, float(elastic))
    struct.pack_into('<I', nd, 92, _FILL)
    return bytes(nd)

def plan_custom_bones(mod_bytes, arm_obj, offset, preset_key='cloth_std',
                      name_map=None, ctc_bytes=None, order=None):
    from .MTframework_MHGU import get_armature_bone_name_map
    if name_map is None:
        try:
            name_map = get_armature_bone_name_map(arm_obj)
        except Exception:
            name_map = {}

    t = _parse(mod_bytes)
    n = t['n']

    _bre = re.compile(r'^b_(\d+)(?:\.[lr])?$')
    rec_of = {}
    for b in arm_obj.data.bones:
        rec = name_map.get(b.name)
        if rec is None:
            m = _bre.match(b.name)
            if m:
                rec = int(m.group(1)) - 1
        if rec is not None and 0 <= rec < n:
            rec_of[b.name] = rec
    new_bones = [b for b in arm_obj.data.bones if b.name not in rec_of]
    if not new_bones:
        raise ValueError('骨架里没有新骨：先在编辑模式加骨、摆好位置与父子，再点登记')

    for b in new_bones:
        if b.parent is None:
            raise ValueError('新骨 %s 没有父级：请把它挂到已有骨上' % b.name)

    new_names = {b.name for b in new_bones}
    if order:
        by_name = {b.name: b for b in new_bones}
        ordered, seen = [], set()
        for nm in order:
            b = by_name.get(nm)
            if b is None:
                continue
            if (b.parent is not None and b.parent.name in new_names
                    and b.parent.name not in seen):
                raise ValueError('order 里父骨不在子骨前面：%s' % b.name)
            ordered.append(b)
            seen.add(b.name)
        ordered += [b for b in new_bones if b.name not in seen]
        if len(ordered) != len(new_bones):
            raise ValueError('order 没覆盖全部新骨')
    else:
        ordered, done = [], set()
        guard = 0
        while len(ordered) < len(new_bones) and guard <= len(new_bones) + 2:
            guard += 1
            for b in new_bones:
                if b.name in done:
                    continue
                if b.parent.name not in new_names or b.parent.name in done:
                    ordered.append(b)
                    done.add(b.name)
        if len(ordered) != len(new_bones):
            raise ValueError('新骨的父子关系里有环，无法排序')

    used = {b['id'] for b in t['bones']}
    phys_used = [i for i in used if i >= PHYS_MIN]
    next_id = (max(phys_used) + 1) if phys_used else PHYS_MIN
    ids, slots = {}, {}
    for k, b in enumerate(ordered):
        while next_id in used:
            next_id += 1
        if next_id > PHYS_MAX:
            raise ValueError('物理骨 id 用尽（20~254）')
        ids[b.name] = next_id
        slots[b.name] = n + k
        used.add(next_id)

    rel = Matrix.Translation(-Vector(offset)) @ arm_obj.matrix_world
    scale = t['scale']
    worlds = {}
    for b in ordered:
        p = rel @ b.head_local
        at = bone_head_to_file_translation((p.x, p.y, p.z), scale)
        worlds[b.name] = tuple(t['c'][k] - at[k] for k in range(3))

    amat3 = [struct.unpack_from('<f', mod_bytes, t['amat'] + r * 16 + c * 4)[0]
             for r in range(3) for c in range(3)]
    n_info, n_lmat, n_amat = [], [], []
    for b in ordered:
        slot = slots[b.name]
        if b.parent.name in slots:
            par_slot = slots[b.parent.name]
            par_world = worlds[b.parent.name]
        else:
            par_slot = rec_of[b.parent.name]
            par_world = t['bones'][par_slot]['world']
        world = worlds[b.name]
        local = tuple(world[k] - par_world[k] for k in range(3))
        ln = sum(v * v for v in local) ** 0.5

        rec = bytearray(INFO)
        rec[0] = ids[b.name]
        rec[1] = par_slot & 0xFF
        rec[2] = slot & 0xFF
        rec[3] = 0
        struct.pack_into('<f', rec, 4, 0.0)
        struct.pack_into('<f', rec, 8, ln)
        struct.pack_into('<3f', rec, 12, *local)
        n_info.append(bytes(rec))

        n_lmat.append(struct.pack('<16f',
                                  1.0, 0.0, 0.0, 0.0,
                                  0.0, 1.0, 0.0, 0.0,
                                  0.0, 0.0, 1.0, 0.0,
                                  local[0], local[1], local[2], 1.0))
        n_amat.append(struct.pack('<16f',
                                  amat3[0], amat3[1], amat3[2], 0.0,
                                  amat3[3], amat3[4], amat3[5], 0.0,
                                  amat3[6], amat3[7], amat3[8], 0.0,
                                  t['c'][0] - world[0],
                                  t['c'][1] - world[1],
                                  t['c'][2] - world[2], 1.0))

    old_info = mod_bytes[t['ptr']:t['ptr'] + n * INFO]
    old_lmat = mod_bytes[t['lmat']:t['lmat'] + n * MAT]
    old_amat = mod_bytes[t['amat']:t['amat'] + n * MAT]
    lut = bytearray(mod_bytes[t['lut']:t['lut'] + 256])
    for nm, sid in ids.items():
        lut[sid] = slots[nm]

    bone_blob = (old_info + b''.join(n_info)
                 + old_lmat + b''.join(n_lmat)
                 + old_amat + b''.join(n_amat)
                 + bytes(lut))
    old_len = n * (INFO + 2 * MAT) + 256
    delta = len(bone_blob) - old_len
    out = bytearray(mod_bytes[:t['ptr']] + bone_blob
                    + mod_bytes[t['ptr'] + old_len:])
    struct.pack_into('<H', out, 6, n + len(ordered))
    for off in (40, 44, 48, 52, 56):
        v = struct.unpack_from('<I', mod_bytes, off)[0]
        if v:
            struct.pack_into('<I', out, off, v + delta)
    struct.pack_into('<I', out, 60, len(out) - 4)

    bone_by_name = {b.name: b for b in ordered}

    def kids(name):
        return [b.name for b in ordered if b.parent.name == name]

    chains, stack = [], [(r, [r]) for r in
                         [b.name for b in ordered if b.parent.name not in slots]]
    while stack:
        cur, path = stack.pop()
        ks = kids(cur)
        if not ks:
            chains.append(path)
        else:

            stack.append((ks[0], path + [ks[0]]))
            for k in ks[1:]:
                stack.append((k, [k]))

    preset = PHYS_PRESETS.get(preset_key) or PHYS_PRESETS['cloth_std']
    groups, nodes = [], []
    for path in chains:
        groups.append(_group_bytes(len(path), preset))
        for i, nm in enumerate(path):
            world = worlds[nm]
            if i + 1 < len(path):
                d = [worlds[path[i + 1]][k] - world[k] for k in range(3)]
            else:

                bb = bone_by_name[nm]
                pt = rel @ bb.tail_local
                at = bone_head_to_file_translation((pt.x, pt.y, pt.z), scale)
                tw = tuple(t['c'][k] - at[k] for k in range(3))
                d = [tw[k] - world[k] for k in range(3)]
                if sum(v * v for v in d) < 1e-12:
                    parent_name = bb.parent.name
                    if parent_name in worlds:
                        pw = worlds[parent_name]
                    else:
                        pw = t['bones'][rec_of[parent_name]]['world']
                    d = [world[k] - pw[k] for k in range(3)]
            nodes.append(_node_bytes(ids[nm], i == 0, d, preset,
                                     identity=(len(path) > 1 and i + 1 == len(path))))

    header, old_groups, old_nodes, tail = _split_ctc(ctc_bytes)
    all_groups = list(old_groups) + groups
    all_nodes = list(old_nodes) + nodes
    struct.pack_into('<I', header, 0x10, len(all_groups))
    struct.pack_into('<I', header, 0x14, len(all_nodes))
    new_ctc = bytes(header) + b''.join(all_groups) + b''.join(all_nodes) + tail

    rename = {nm: 'b_%d' % (slots[nm] + 1) for nm in ids}
    info = dict(chains=chains, ids=dict(ids), slots=dict(slots),
                rename=rename,
                names={ids[nm]: rename[nm] for nm in ids},
                preset_name=preset[0])
    return bytes(out), new_ctc, info

def _find_armature(context):
    objs = [o for o in context.scene.objects if o.type == 'ARMATURE']
    for o in objs:
        if o.name.startswith('MT_Armature') or o.data.name.startswith('MT_Armature'):
            return o
    return objs[0] if objs else None

def _rename_bones(arm, rename):
    meshes = [o for o in bpy.data.objects if o.type == 'MESH']
    n_bones = n_groups = 0
    for old, new in rename.items():
        if old == new:
            continue
        b = arm.data.bones.get(old)
        if b is None:
            continue

        for o in meshes:
            vg = o.vertex_groups.get(old)
            if vg is None:
                continue
            tgt = o.vertex_groups.get(new)
            if tgt is not None and tgt != vg:

                for v in o.data.vertices:
                    w = 0.0
                    for g in v.groups:
                        if g.group == vg.index:
                            w = g.weight
                            break
                    if w <= 0.0:
                        continue
                    cur = 0.0
                    for g in v.groups:
                        if g.group == tgt.index:
                            cur = g.weight
                            break
                    if w > cur:
                        tgt.add([v.index], w, 'REPLACE')
                o.vertex_groups.remove(vg)
            else:
                vg.name = new
            n_groups += 1
        b.name = new
        n_bones += 1
    return n_bones, n_groups

_PHYS_NAME_RE = re.compile(r'^b_(\d+)(?:\.[lr])?$')

def arm_physics_names(arm):
    out = []
    for b in arm.data.bones:
        m = _PHYS_NAME_RE.match(b.name)
        if m and int(m.group(1)) >= PHYS_MIN:
            out.append(b.name)
    return out

def template_needs_rebuild(mod_bytes, arm):
    t = _parse(mod_bytes)
    n = t['n']
    for nm in arm_physics_names(arm):
        rec = int(_PHYS_NAME_RE.match(nm).group(1)) - 1
        if rec >= n or t['bones'][rec]['id'] < PHYS_MIN:
            return True
    return False

def ensure_template(sc, arm, mod_bytes, off, preset):
    if bpy is None:
        return mod_bytes
    try:
        n_tpl = sum(1 for b in _parse(mod_bytes)['bones'] if b['id'] >= PHYS_MIN)
        n_arm = len(arm_physics_names(arm))
        if n_tpl == n_arm and not template_needs_rebuild(mod_bytes, arm):
            return mod_bytes
        print('[MT] 模板物理骨 %d ≠ 骨架 %d → 先重建物理模板' % (n_tpl, n_arm))
        r = bpy.ops.mt_framework.phys_rebuild_template()
        tpl = sc.get('MT_LastImportPath', '') or ''
        if r == {'FINISHED'} and tpl and os.path.exists(tpl):
            with open(tpl, 'rb') as f:
                return f.read()
    except Exception as e:
        print('[MT] 自动重建模板失败（继续用旧模板）:', e)
    return mod_bytes

def rebuild_template_from_armature(mod_bytes, arm_obj, offset, preset_key='cloth_std'):
    base = keep_body_bones(mod_bytes)
    names = sorted(arm_physics_names(arm_obj),
                   key=lambda nm: int(_PHYS_NAME_RE.match(nm).group(1)))
    new_mod, _ignored, info = plan_custom_bones(base, arm_obj, offset, preset_key,
                                                ctc_bytes=b'', order=names)
    return new_mod, info

def rebuild_template_only(mod_bytes, arm, offset, preset_key):
    base = keep_body_bones(mod_bytes)
    names = sorted(arm_physics_names(arm),
                   key=lambda nm: int(_PHYS_NAME_RE.match(nm).group(1)))
    new_mod, _ignored, info = plan_custom_bones(base, arm, offset, preset_key,
                                                ctc_bytes=b'', order=names)
    bad = []
    for nm, slot in info['slots'].items():
        m = _PHYS_NAME_RE.match(nm)
        if m and slot != int(m.group(1)) - 1:
            bad.append('%s→槽%d' % (nm, slot))
    if bad:
        raise ValueError('骨架顺序和骨名对不上，不能自动重建模板：%s' % ', '.join(bad[:5]))
    rev = {}
    try:
        for k, v in (arm.get('MT_PhysIdMap') or {}).items():
            rev[str(v)] = int(k)
    except Exception:
        rev = {}
    idbad = []
    for nm, nid in info['ids'].items():
        old = rev.get(nm)
        if old is not None and old != nid:
            idbad.append('%s: id %d→%d' % (nm, old, nid))
    if idbad:
        raise ValueError('重建后的骨 id 和原工程不一致（%s），'
                         '请重新导入一次 .arc 再登记' % ', '.join(idbad[:5]))
    return new_mod, info

def add_tip_bones(arm, names):
    if not names:
        return []
    if bpy.context.mode != 'OBJECT':
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except Exception:
            pass
    try:
        bpy.context.view_layer.objects.active = arm
        arm.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
    except Exception:
        return []
    eb = arm.data.edit_bones
    added = []
    for nm in names:
        b = eb.get(nm)
        if b is None:
            continue
        d = b.tail - b.head
        ln = d.length
        if ln < 1e-5:
            d = Vector((0.0, 0.0, -1.0))
            ln = max(b.length, 0.02)
        else:
            d = d.normalized()
        tip = eb.new('tip_' + nm)
        tip.head = b.tail
        tip.tail = b.tail + d * max(ln, 0.02)
        tip.parent = b
        tip.use_connect = False
        added.append(tip.name)
    bpy.ops.object.mode_set(mode='OBJECT')
    return added

def _prepare_two_node_chains(arm, mod_bytes, offset, preset_key, ctc_bytes):
    try:
        _, _, info = plan_custom_bones(mod_bytes, arm, offset, preset_key,
                                       ctc_bytes=ctc_bytes)
    except Exception:
        return []
    singles = [c[0] for c in info['chains'] if len(c) == 1]
    return add_tip_bones(arm, singles)

def complete_single_groups(mod_bytes, ctc_bytes, arm, offset, preset_key='cloth_std'):

    if template_needs_rebuild(mod_bytes, arm):
        mod_bytes, _rebuilt = rebuild_template_only(mod_bytes, arm, offset, preset_key)

    header, groups, nodes, tail = _split_ctc(ctc_bytes)
    counts = [struct.unpack_from('<I', g, 0)[0] for g in groups]
    singles = [gi for gi, c in enumerate(counts) if c == 1]

    if singles:
        _t = _parse(mod_bytes)
        _kids = {}
        for _b in _t['bones']:
            _ps = _b['parent']
            if _ps < _t['n'] and _t['bones'][_ps]['id'] >= PHYS_MIN:
                _kids.setdefault(_t['bones'][_ps]['id'], []).append(_b['id'])
        _idx = 0
        _fake = []
        for _c in counts:
            if _c == 1:
                _nid = struct.unpack_from('<H', nodes[_idx], 0)[0]
                if _kids.get(_nid):
                    _fake.append(_nid)
            _idx += _c
        if _fake:
            print('[MT] 发现 %d 个「分支父骨被当成单节点链」（%s）→ 先重建 CTC'
                  % (len(_fake), _fake[:6]))
            ctc_bytes = build_ctc_from_bones(mod_bytes, arm, offset, preset_key,
                                             ctc_bytes=ctc_bytes)
            header, groups, nodes, tail = _split_ctc(ctc_bytes)
            counts = [struct.unpack_from('<I', g, 0)[0] for g in groups]
            singles = [gi for gi, c in enumerate(counts) if c == 1]
    if not singles:
        return mod_bytes, ctc_bytes, dict(made=0, rename={}, names={}, tips=[],
                                          chains=[], ids={}, slots={}, rebuilt=True)

    t = _parse(mod_bytes)
    id2name = {}
    try:
        _mp = arm.get('MT_PhysIdMap') or {}
        id2name = {int(k): str(v) for k, v in _mp.items()}
    except Exception:
        pass

    idx = 0
    bone_of_group = {}
    for gi, c in enumerate(counts):
        if c == 1:
            nid = nodes[idx][0]
            nm = id2name.get(nid)
            if nm is None or arm.data.bones.get(nm) is None:

                slot = mod_bytes[t['lut'] + nid] if nid < 256 else 0xFF
                cand = ('b_%d' % (slot + 1)) if slot != 0xFF else ('b_%d' % nid)
                if arm.data.bones.get(cand) is not None:
                    nm = cand
            if nm is not None and arm.data.bones.get(nm) is not None:
                bone_of_group[gi] = (nm, nid)
        idx += c
    if not bone_of_group:
        return mod_bytes, ctc_bytes, None

    tips = add_tip_bones(arm, [nm for nm, _ in bone_of_group.values()])
    if not tips:
        return mod_bytes, ctc_bytes, None

    new_mod, _ignored, info = plan_custom_bones(
        mod_bytes, arm, offset, preset_key, ctc_bytes=ctc_bytes)
    clash = sorted({new for old, new in info['rename'].items()
                    if new != old and arm.data.bones.get(new) is not None})
    if clash:
        raise ValueError('补全后的骨名与现有骨冲突：%s（模板和骨架不一致，'
                         '先点「重建物理模板」）' % ', '.join(clash[:5]))
    tip_id = {}
    for old_tip in tips:
        if old_tip in info['ids']:
            tip_id[old_tip] = info['ids'][old_tip]

    tpl = PHYS_PRESETS.get(preset_key) or PHYS_PRESETS['cloth_std']
    new_groups = list(groups)
    out_nodes = []
    idx = 0
    made = 0
    for gi, c in enumerate(counts):
        if gi in bone_of_group:
            nm, nid = bone_of_group[gi]
            tid = tip_id.get('tip_' + nm)
            if tid is None:
                out_nodes.extend(nodes[idx: idx + c])
                idx += c
                continue
            g = bytearray(new_groups[gi])
            struct.pack_into('<I', g, 0, 2)
            new_groups[gi] = bytes(g)
            base = bytearray(nodes[idx])
            base[0] = tid & 0xFF
            base[2] = 0

            base[4:8] = b'\x01\x00\x01\x01'
            struct.pack_into('<16f', base, 16,
                             1.0, 0.0, 0.0, 0.0,
                             0.0, 1.0, 0.0, 0.0,
                             0.0, 0.0, 1.0, 0.0,
                             0.0, 0.0, 0.0, 1.0)
            out_nodes.append(nodes[idx])
            out_nodes.append(bytes(base))
            made += 1
        else:
            out_nodes.extend(nodes[idx: idx + c])
        idx += c
    if not made:
        return mod_bytes, ctc_bytes, None
    struct.pack_into('<I', header, 0x10, len(new_groups))
    struct.pack_into('<I', header, 0x14, len(out_nodes))
    new_ctc = bytes(header) + b''.join(new_groups) + b''.join(out_nodes) + tail
    info['tips'] = [info['rename'].get('tip_' + nm) for nm, _ in bone_of_group.values()]
    info['made'] = made
    return new_mod, new_ctc, info

def build_ctc_from_bones(mod_bytes, arm_obj, offset, preset_key='cloth_std',
                         ctc_bytes=None):
    t = _parse(mod_bytes)
    preset = PHYS_PRESETS.get(preset_key) or PHYS_PRESETS['cloth_std']
    old = {}
    old_groups = []
    if ctc_bytes:
        try:
            _ng = struct.unpack_from('<I', ctc_bytes, 0x10)[0]
            _nc = struct.unpack_from('<I', ctc_bytes, 0x14)[0]
            _off = 0x3C + 80 * _ng
            _ids = [struct.unpack_from('<H', ctc_bytes, _off + _k * 96)[0]
                    for _k in range(_nc)]
            for _k in range(_nc):
                _o = _off + _k * 96
                _jid = _ids[_k]
                _r = struct.unpack_from('<12f', ctc_bytes, _o + 16)
                _vals = struct.unpack_from('<3f', ctc_bytes, _o + 80)
                old[_jid] = ((_r[4], _r[5], _r[6]), _vals)
            _idx = 0
            for _g in range(_ng):
                _o = 0x3C + 80 * _g
                _cnt = struct.unpack_from('<I', ctc_bytes, _o)[0]
                _gids = set(_ids[_idx:_idx + _cnt])
                _idx += _cnt
                _gp = (struct.unpack_from('<3f', ctc_bytes, _o + 32)[1],
                       struct.unpack_from('<f', ctc_bytes, _o + 48)[0],
                       struct.unpack_from('<f', ctc_bytes, _o + 56)[0],
                       struct.unpack_from('<f', ctc_bytes, _o + 60)[0],
                       struct.unpack_from('<f', ctc_bytes, _o + 52)[0],
                       struct.unpack_from('<f', ctc_bytes, _o + 64)[0],
                       struct.unpack_from('<f', ctc_bytes, _o + 72)[0])
                old_groups.append((_gids, _gp))
        except Exception:
            old = {}
            old_groups = []
    phys = [b for b in t['bones'] if b['id'] >= PHYS_MIN]
    if not phys:
        raise ValueError('模板里没有物理骨（id >= 20）')
    by_id = {b['id']: b for b in phys}

    parent = {}
    for b in phys:
        pid = t['bones'][b['parent']]['id'] if b['parent'] < t['n'] else None
        parent[b['id']] = pid if pid in by_id else None
    kids = {}
    for bid, pid in parent.items():
        kids.setdefault(pid, []).append(bid)

    order, q = [], list(kids.get(None, []))
    while q:
        bid = q.pop(0)
        if bid in order:
            continue
        order.append(bid)
        q.extend(kids.get(bid, []))
    if len(order) != len(phys):
        raise ValueError('物理骨父子关系有环（%d/%d 可达）' % (len(order), len(phys)))

    chains, chain_of = [], {}
    for bid in order:
        pid = parent.get(bid)
        if pid is not None and len(kids.get(pid, [])) == 1 and pid in chain_of:
            chain_of[pid].append(bid)
            chain_of[bid] = chain_of[pid]
        else:
            c = [bid]
            chains.append(c)
            chain_of[bid] = c

    def _child_chain(pid):
        _cands = [c for c in chains if c and parent.get(c[0]) == pid and c[0] != pid]

        for c in _cands:
            if len(c) == 1:
                return c
        return _cands[0] if _cands else None

    changed = True
    while changed:
        changed = False
        for c in list(chains):
            if len(c) != 1:
                continue
            pid = c[0]
            if pid not in kids:
                continue
            cc = _child_chain(pid)
            if cc is None or cc is c:
                continue
            cc.insert(0, pid)
            for x in cc:
                chain_of[x] = cc
            chains.remove(c)
            changed = True
            break

    groups, nodes = [], []
    for path in chains:

        _gp = preset
        if old_groups:
            _best = max(old_groups, key=lambda t: len(t[0] & set(path)))
            if _best[0] & set(path):
                _g = _best[1]
                _gp = (preset[0], _g[0], _g[1], _g[2], _g[3], _g[4], _g[5], _g[6],
                       preset[8], preset[9], preset[10])
        groups.append(_group_bytes(len(path), _gp))
        for i, bid in enumerate(path):
            b = by_id[bid]
            w = b['world']

            ident = (len(path) > 1 and i == len(path) - 1)
            if ident:
                d = [0.0, 0.0, 0.0]
            elif i + 1 < len(path):
                nw = by_id[path[i + 1]]['world']
                d = [nw[k] - w[k] for k in range(3)]
            else:

                par = t['bones'][b['parent']] if b['parent'] < t['n'] else None
                if par is not None:
                    d = [w[k] - par['world'][k] for k in range(3)]
                else:
                    d = [0.0, -1.0, 0.0]
                if sum(x * x for x in d) < 1e-8:
                    d = [0.0, -1.0, 0.0]
            _ax, _vals = old.get(bid, (None, None))
            nodes.append(_node_bytes(bid, i == 0, d, preset, identity=ident,
                                     axis=_ax, values=_vals))

    header = bytearray(_CTC_HEAD_TMPL)
    struct.pack_into('<I', header, 0x10, len(groups))
    struct.pack_into('<I', header, 0x14, len(nodes))
    return bytes(header) + b''.join(groups) + b''.join(nodes)

def _template_path():
    import hashlib
    blend = bpy.data.filepath or ''
    tag = os.path.splitext(os.path.basename(blend))[0] if blend else 'unsaved'
    tag = ''.join(c for c in tag if c.isalnum() or c in '-_')[:24] or 'unsaved'
    h = hashlib.md5((blend or 'unsaved').encode('utf-8')).hexdigest()[:6]
    return os.path.join(tempfile.gettempdir(), 'mt_template_%s_%s.mod' % (tag, h))

def keep_body_bones(mod):
    n, ptr, lmat, amat, lut = _bounds(mod)
    ids = [mod[ptr + i * 24] for i in range(n)]
    keep = [i for i in range(n) if ids[i] < 20]
    if keep != list(range(len(keep))):
        raise ValueError('模板里基础骨（id<20）不是连续排在最前面，无法自动重建')
    k = len(keep)
    blob = (mod[ptr:ptr + k * 24]
            + mod[lmat:lmat + k * 64]
            + mod[amat:amat + k * 64])
    new_lut = bytearray(b'\xff' * 256)
    for i in range(k):
        new_lut[ids[i]] = i
    blob += bytes(new_lut)
    old_len = n * (24 + 128) + 256
    delta = len(blob) - old_len
    out = bytearray(mod[:ptr] + blob + mod[ptr + old_len:])
    struct.pack_into('<H', out, 6, k)
    for off in (40, 44, 48, 52, 56):
        v = struct.unpack_from('<I', mod, off)[0]
        if v:
            struct.pack_into('<I', out, off, v + delta)
    struct.pack_into('<I', out, 60, len(out) - 4)
    return bytes(out)

if bpy is not None:

    class MT_OT_PhysCustomRegister(Operator):
        bl_idname = "mt_framework.phys_custom_register"
        bl_label = "登记自定义物理骨"
        bl_description = ("先在编辑模式里自己加骨、摆好位置和父子，再点这里："
                          "写进 .mod 骨骼段 + LUT，并按骨链生成 CTC")

        def execute(self, context):
            sc = context.scene
            arm = _find_armature(context)
            if arm is None:
                self.report({'ERROR'}, '场景里没有骨架')
                return {'CANCELLED'}
            tpl = sc.get('MT_LastImportPath', '') or ''
            if not tpl or not os.path.exists(tpl):
                self.report({'ERROR'}, '请先导入一个 .mod 或 .arc 作为模板')
                return {'CANCELLED'}
            if tpl.endswith('.new'):
                self.report({'ERROR'}, '模板不能是 .new 文件')
                return {'CANCELLED'}
            with open(tpl, 'rb') as f:
                mod_bytes = f.read()
            if mod_bytes[:4] != b'MOD\x00':
                self.report({'ERROR'}, '模板不是 .mod')
                return {'CANCELLED'}
            if bpy.context.mode != 'OBJECT':
                try:
                    bpy.ops.object.mode_set(mode='OBJECT')
                except Exception:
                    pass

            from .MTframework_MHGU import get_object_center_offset
            from .MTframework_MHGU_phys import recalled_arc
            off = get_object_center_offset(arm, sc)
            _arc, old_ctc = recalled_arc(context)
            preset = getattr(sc, 'MT_PhysPreset', 'cloth_std')

            rebuilt = False
            if template_needs_rebuild(mod_bytes, arm):
                try:
                    mod_bytes, _rbi = rebuild_template_only(mod_bytes, arm, off, preset)
                    rebuilt = True
                except Exception as e:
                    self.report({'ERROR'}, '模板与骨架不一致，自动重建失败: %s' % e)
                    return {'CANCELLED'}

            tips = _prepare_two_node_chains(arm, mod_bytes, off, preset, old_ctc)
            try:
                new_mod, new_ctc, info = plan_custom_bones(
                    mod_bytes, arm, off, preset, ctc_bytes=old_ctc)
            except Exception as e:
                self.report({'ERROR'}, '登记失败: %s' % e)
                return {'CANCELLED'}

            tmp = _template_path()
            with open(tmp, 'wb') as f:
                f.write(new_mod)
            sc['MT_LastImportPath'] = tmp
            try:
                from .MTframework_MHGU_tpl import store as _tpl_store
                _tpl_store(sc, tmp)
            except Exception:
                pass
            try:
                import MT_Framework_Tools.MTframework_MHGU_import as _imp
                _imp._last_import_path = tmp
            except Exception:
                pass

            remember_arc(context, _arc, new_ctc)
            context.scene['MT_CtcCustom'] = True
            _n_bones, _n_groups = _rename_bones(arm, info['rename'])

            _mp0 = dict(arm.get('MT_PhysIdMap') or {})
            _mp0.update({str(k): v for k, v in info['names'].items()})
            arm['MT_PhysIdMap'] = _mp0
            tip_final = [info['rename'].get(t) for t in tips if info['rename'].get(t)]
            if tip_final:
                try:
                    arm['MT_AutoTipBones'] = tip_final
                except Exception:
                    pass

            new_names = set(info['rename'].values())
            for b in arm.data.bones:
                b.select = b.name in new_names

            ids = sorted(info['ids'].values())
            warn = ''
            if ids and max(ids) > 27:
                warn = '（id %d~%d 超出官方 20~27，游戏侧未实测）' % (min(ids), max(ids))
            chain_desc = ' / '.join('%d 段' % len(c) for c in info['chains'])
            tip_note = ('；单骨链补了 %d 根子骨（不绑顶点）' % len(tip_final)
                        if tip_final else '')
            if rebuilt:
                tip_note += '；模板已按骨架自动重建'
            self.report({'INFO'},
                        '已登记 %d 根物理骨（%s），id %s%s；骨名与顶点组已改成 %s'
                        '（改骨 %d 根 / 顶点组 %d 个），权重不用重刷%s'
                        % (len(ids), chain_desc,
                           ','.join(str(i) for i in ids), warn,
                           ','.join(info['names'][i] for i in ids),
                           _n_bones, _n_groups, tip_note))
            return {'FINISHED'}

    class MT_OT_PhysCtcFix(Operator):
        bl_idname = "mt_framework.phys_ctc_fix"
        bl_label = "修复 CTC 头部"
        bl_description = ("把当前 CTC 头 0x1C~0x30 改成官方主流值"
                          "（重点：0x20 重力缩放 1.0）。只动这 6 个 float，"
                          "组/节点/权重一个字节不动")

        def execute(self, context):
            from .MTframework_MHGU_phys import recalled_arc
            arc_path, ctc = recalled_arc(context)
            if not ctc or ctc[:4] != b'CTC\x00':
                self.report({'ERROR'}, '当前没有 CTC（先导入带物理的 arc 或登记物理骨）')
                return {'CANCELLED'}
            new, old, changed = fix_ctc_header(ctc)
            if not changed:
                self.report({'INFO'}, 'CTC 头已是官方主流值（0x20=1.0 / 0x28=1.0），不用改')
                return {'FINISHED'}
            remember_arc(context, arc_path, new)
            self.report({'INFO'},
                        'CTC 头已修：0x1C~0x30 %s → 1/60, 1.0, 0.0, 1.0, 1.0, 1.0'
                        '（重力缩放恢复；重新导出 arc 生效）'
                        % (','.join('%.3f' % v for v in old)))
            return {'FINISHED'}

    class MT_OT_PhysRebuildTemplate(Operator):
        bl_idname = "mt_framework.phys_rebuild_template"
        bl_label = "重建物理模板"
        bl_description = ("模板和骨架的物理骨对不上（少骨/多骨、或是从别的工程 Save As 带过来的）时，"
                          "按当前骨架重写模板骨骼表：多余骨丢掉、少骨补上；"
                          "槽位变了会把骨名和同名顶点组一起改（权重不重刷）")

        def execute(self, context):
            sc = context.scene
            arm = _find_armature(context)
            if arm is None:
                self.report({'ERROR'}, '场景里没有骨架')
                return {'CANCELLED'}
            tpl = sc.get('MT_LastImportPath', '') or ''
            if not tpl or not os.path.exists(tpl):
                self.report({'ERROR'}, '找不到当前模板；请重新导入一次 .arc')
                return {'CANCELLED'}
            with open(tpl, 'rb') as f:
                mod = f.read()
            if mod[:4] != b'MOD\x00':
                self.report({'ERROR'}, '模板不是 .mod')
                return {'CANCELLED'}
            n_tpl = struct.unpack_from('<H', mod, 6)[0]
            ptr = struct.unpack_from('<I', mod, 0x24)[0]
            tpl_phys = [mod[ptr + i * 24] for i in range(n_tpl)]
            tpl_phys = [i for i in tpl_phys if i >= PHYS_MIN]
            arm_phys = arm_physics_names(arm)
            if not template_needs_rebuild(mod, arm) and len(tpl_phys) == len(arm_phys):
                self.report({'INFO'},
                            '模板和骨架一致（%d 骨 / 物理 %d 根），不需要重建'
                            % (n_tpl, len(arm_phys)))
                return {'FINISHED'}
            from .MTframework_MHGU import get_object_center_offset
            off = get_object_center_offset(arm, sc)
            preset = getattr(sc, 'MT_PhysPreset', 'cloth_std')

            try:
                new_mod, info = rebuild_template_from_armature(mod, arm, off, preset)
            except Exception as e:
                self.report({'ERROR'}, '重建失败: %s' % e)
                return {'CANCELLED'}
            tmp = _template_path()
            with open(tmp, 'wb') as f:
                f.write(new_mod)
            sc['MT_LastImportPath'] = tmp
            try:
                from .MTframework_MHGU_tpl import store as _tpl_store
                _tpl_store(sc, tmp)
            except Exception:
                pass
            try:
                import MT_Framework_Tools.MTframework_MHGU_import as _imp
                _imp._last_import_path = tmp
            except Exception:
                pass
            note = ''
            rename = {k: v for k, v in (info.get('rename') or {}).items() if k != v}
            if rename:
                try:
                    _nb, _ng = _rename_bones(arm, rename)
                    _mp0 = dict(arm.get('MT_PhysIdMap') or {})
                    _mp0.update({str(k): v for k, v in info['names'].items()})
                    arm['MT_PhysIdMap'] = _mp0
                    note = '；骨名/顶点组已按新槽位重命名（%d 骨 / %d 组）' % (_nb, _ng)
                except Exception as e:
                    self.report({'WARNING'}, '模板已重建，但重命名骨/顶点组失败: %s' % e)
            n = struct.unpack_from('<H', new_mod, 6)[0]

            try:
                from .MTframework_MHGU_phys import recalled_arc, remember_arc
                _arc, _old_ctc = recalled_arc(context)
                if _old_ctc and _old_ctc[:4] == b'CTC\x00':
                    _new_ctc = build_ctc_from_bones(new_mod, arm, off, preset,
                                                    ctc_bytes=_old_ctc)
                    remember_arc(context, _arc, _new_ctc)
                    context.scene['MT_CtcCustom'] = True
                    _ng, _nc = struct.unpack_from('<II', _new_ctc, 0x10)
                    note += '；CTC 已同步重建（%d 组 / %d 节点）' % (_ng, _nc)
            except Exception as e:
                self.report({'WARNING'},
                            '模板已重建，但 CTC 同步失败（请手动点「重建 CTC」）: %s' % e)
            self.report({'INFO'},
                        '模板已按骨架重建：%d 骨（原 %d 骨 / 骨架 %d 骨，物理 %d 根）%s'
                        % (n, n_tpl, len(arm.data.bones), len(arm_phys), note))
            return {'FINISHED'}

    class MT_OT_PhysCompleteChains(Operator):
        bl_idname = "mt_framework.phys_complete_chains"
        bl_label = "补全单节点物理链"
        bl_description = ("CTC 里节点数=1 的组（官方没有这种，单骨链静止姿态不稳）"
                          "各补一根不绑顶点的子骨，变成 2 节点；权重/其它链不动")

        def execute(self, context):
            sc = context.scene
            arm = _find_armature(context)
            if arm is None:
                self.report({'ERROR'}, '场景里没有骨架')
                return {'CANCELLED'}
            tpl = sc.get('MT_LastImportPath', '') or ''
            if not tpl or not os.path.exists(tpl):
                self.report({'ERROR'}, '找不到当前模板；先导入一次 .arc/.mod')
                return {'CANCELLED'}
            with open(tpl, 'rb') as f:
                mod_bytes = f.read()
            from .MTframework_MHGU import get_object_center_offset
            from .MTframework_MHGU_phys import recalled_arc
            arc, ctc = recalled_arc(context)
            if not ctc or ctc[:4] != b'CTC\x00':
                self.report({'ERROR'}, '当前没有 CTC')
                return {'CANCELLED'}
            if bpy.context.mode != 'OBJECT':
                try:
                    bpy.ops.object.mode_set(mode='OBJECT')
                except Exception:
                    pass
            off = get_object_center_offset(arm, sc)
            preset = getattr(sc, 'MT_PhysPreset', 'cloth_std')

            mod_bytes = ensure_template(sc, arm, mod_bytes, off, preset)

            try:
                ctc = build_ctc_from_bones(mod_bytes, arm, off, preset, ctc_bytes=ctc)
                print('[MT] 补全前已重建 CTC：%d 组 / %d 节点'
                      % struct.unpack_from('<II', ctc, 0x10))
            except Exception as _e:
                print('[MT] 补全前重建 CTC 失败（继续用旧 CTC）:', _e)
            try:
                new_mod, new_ctc, info = complete_single_groups(
                    mod_bytes, ctc, arm, off, preset)
            except Exception as e:
                self.report({'ERROR'}, '补全失败: %s' % e)
                return {'CANCELLED'}
            if info is None:
                _ng, _nc = struct.unpack_from('<II', ctc, 0x10)
                self.report({'INFO'}, '没有单节点组，不用补（CTC %d 组 / %d 节点）'
                            % (_ng, _nc))
                return {'FINISHED'}
            if info.get('made', 0) == 0:

                remember_arc(context, arc, new_ctc)
                context.scene['MT_CtcCustom'] = True
                _ng, _nc = struct.unpack_from('<II', new_ctc, 0x10)
                self.report({'INFO'},
                            '没有单节点组，不用补（已按骨架重建 CTC：%d 组 / %d 节点）'
                            % (_ng, _nc))
                return {'FINISHED'}
            tmp = _template_path()
            with open(tmp, 'wb') as f:
                f.write(new_mod)
            sc['MT_LastImportPath'] = tmp
            try:
                from .MTframework_MHGU_tpl import store as _tpl_store
                _tpl_store(sc, tmp)
            except Exception:
                pass
            try:
                import MT_Framework_Tools.MTframework_MHGU_import as _imp
                _imp._last_import_path = tmp
            except Exception:
                pass
            _rename_bones(arm, info['rename'])
            try:
                mp = dict(arm.get('MT_PhysIdMap') or {})
                for k, v in info['names'].items():
                    mp[str(k)] = v
                arm['MT_PhysIdMap'] = mp
                arm['MT_AutoTipBones'] = info.get('tips') or []
            except Exception:
                pass
            remember_arc(context, arc, new_ctc)
            context.scene['MT_CtcCustom'] = True
            self.report({'INFO'},
                        '已补全 %d 条单节点链（各加 1 根不绑顶点的子骨）；'
                        '重新导出即可' % info['made'])
            return {'FINISHED'}

    class MT_OT_PhysRebuildCtc(Operator):
        bl_idname = "mt_framework.phys_rebuild_ctc"
        bl_label = "重建 CTC（按现有物理骨）"
        bl_description = ("场景里的 CTC 丢了（面板提示「当前没有 CTC」）时点它："
                          "按模板里的物理骨和骨架的头/尾方向，重新生成整份 CTC")

        def execute(self, context):
            sc = context.scene
            arm = _find_armature(context)
            if arm is None:
                self.report({'ERROR'}, '场景里没有骨架')
                return {'CANCELLED'}
            tpl = sc.get('MT_LastImportPath', '') or ''
            if not tpl or not os.path.exists(tpl):
                self.report({'ERROR'}, '请先导入一个 .mod 或 .arc 作为模板')
                return {'CANCELLED'}
            with open(tpl, 'rb') as f:
                mod_bytes = f.read()
            if mod_bytes[:4] != b'MOD\x00':
                self.report({'ERROR'}, '模板不是 .mod')
                return {'CANCELLED'}
            from .MTframework_MHGU import get_object_center_offset
            off = get_object_center_offset(arm, sc)
            preset = getattr(sc, 'MT_PhysPreset', 'cloth_std')

            mod_bytes = ensure_template(sc, arm, mod_bytes, off, preset)
            from .MTframework_MHGU_phys import recalled_arc
            arc, _old = recalled_arc(context)
            try:
                ctc = build_ctc_from_bones(mod_bytes, arm, off, preset,
                                           ctc_bytes=_old)
            except Exception as e:
                self.report({'ERROR'}, '重建 CTC 失败: %s' % e)
                return {'CANCELLED'}
            remember_arc(context, arc, ctc)
            context.scene['MT_CtcCustom'] = True
            ng, nc = struct.unpack_from('<II', ctc, 0x10)
            self.report({'INFO'},
                        '已按现有物理骨重建 CTC：%d 组 / %d 节点（导出时写入 arc）'
                        % (ng, nc))
            return {'FINISHED'}

    _classes = [MT_OT_PhysCustomRegister,
                MT_OT_PhysCtcFix, MT_OT_PhysRebuildTemplate,
                MT_OT_PhysCompleteChains, MT_OT_PhysRebuildCtc]

    def _register_props():
        pass

    def _unregister_props():
        pass

    def register():
        for c in _classes:
            bpy.utils.register_class(c)
        _register_props()

    def unregister():
        _unregister_props()
        for c in reversed(_classes):
            try:
                bpy.utils.unregister_class(c)
            except Exception:
                pass

else:
    def register():
        pass

    def unregister():
        pass
