import math
import os
import struct
from itertools import chain, count

from .MTframework_MHGU_ctc import check_topology
from .MTframework_MHGU_physcustom import (
    INFO, MAT, PHYS_MIN, _available_phys_ids, _node_bytes, _parse, _split_ctc,
)
from .MTframework_MHGU_physparams import DEFAULT_PRESET_KEY, PHYS_PRESETS

REMAPPED_SLOTS = 'MT_PhysBridgeReslot'
JOINT_TOLERANCE = 1e-6
LEGACY_TOLERANCE = 1e-5

def _move_bone_records(mod, template, plans, *, removed=(), parent_overrides=None):
    n, ptr, local, world, lut = (template[k] for k in ('n', 'ptr', 'lmat', 'amat', 'lut'))
    records = [(bytearray(mod[ptr + i * INFO:ptr + (i + 1) * INFO]),
                bytearray(mod[local + i * MAT:local + (i + 1) * MAT]),
                bytearray(mod[world + i * MAT:world + (i + 1) * MAT]),
                bone['world']) for i, bone in enumerate(template['bones'])]
    parents = {i: bone['parent'] for i, bone in enumerate(template['bones'])}
    parents.update(parent_overrides or {})
    modified = set(parent_overrides or {})
    before = {}
    for plan in plans:
        idx, child = len(records), plan.get('child')
        info = bytearray(INFO)
        info[0] = plan['id']
        info[2] = idx
        lmat = bytearray(struct.pack('<16f', 1, 0, 0, 0, 0, 1, 0, 0,
                                     0, 0, 1, 0, 0, 0, 0, 1))
        amat = bytearray(records[0][2])
        struct.pack_into('<3f', amat, 48,
                         *(center - value for center, value in zip(template['c'], plan['world'])))
        records.append((info, lmat, amat, plan['world']))
        parents[idx] = plan['parent']
        modified.add(idx)
        if child is not None:
            parents[child] = idx
            modified.add(child)
            before[child] = idx

    order, done, visiting = [], set(), set()

    def visit(idx):
        if idx in done:
            return
        if idx in visiting:
            raise ValueError('骨骼父子关系有环')
        visiting.add(idx)
        par = parents[idx]
        if par < len(records) and par != idx:
            if par in removed:
                raise ValueError('有骨骼仍引用已删除的父骨，请核对父子关系')
            visit(par)
        visiting.remove(idx)
        done.add(idx)
        order.append(idx)

    for idx in range(len(records)):
        if idx in removed:
            continue
        if idx in before:
            visit(before[idx])
        visit(idx)
    new_slots = {old: new for new, old in enumerate(order)}
    flags = bytearray(new_slots.get(value, 255 if value in removed else value)
                      for value in mod[lut:lut + 256])
    info_parts, local_parts, world_parts = [], [], []
    for idx in order:
        info, lmat, amat, position = records[idx]
        par = parents[idx]
        if idx in modified:
            delta = tuple(a - b for a, b in zip(position, records[par][3]))
            struct.pack_into('<4f', info, 8, math.hypot(*delta), *delta)
            struct.pack_into('<3f', lmat, 48, *delta)
        info[1] = new_slots.get(par, par)
        mirror = info[2]
        info[2] = new_slots.get(mirror, new_slots[idx] if mirror in removed else mirror)
        flags[info[0]] = new_slots[idx]
        info_parts.append(info)
        local_parts.append(lmat)
        world_parts.append(amat)

    payload = b''.join(info_parts + local_parts + world_parts) + flags
    result = bytearray(mod[:ptr] + payload + mod[lut + 256:])
    struct.pack_into('<H', result, 6, len(order))
    delta = (len(order) - n) * (INFO + 2 * MAT)
    for off in (40, 44, 48, 52, 56):
        value = struct.unpack_from('<I', mod, off)[0]
        if value:
            struct.pack_into('<I', result, off, value + delta)
    struct.pack_into('<I', result, 60, len(result) - 4)
    return bytes(result), new_slots

def _trim_ctc(ctc, template, split_before=()):
    header, groups, nodes, tail = _split_ctc(ctc)
    bones = template['bones']
    parents = {b['id']: bones[b['parent']]['id'] if b['parent'] < len(bones) else None
               for b in bones if b['id'] >= PHYS_MIN}
    out_groups, out_nodes = [], []
    cursor = 0
    seen = set()
    for group in groups:
        count = struct.unpack_from('<I', group)[0]
        if not 0 < count <= len(nodes) - cursor:
            raise ValueError('CTC 的分组节点数有误')
        chains = []
        previous = None
        for node in nodes[cursor:cursor + count]:
            bid = struct.unpack_from('<H', node)[0]
            if bid not in parents:
                continue
            if bid in seen:
                raise ValueError('CTC 有重复物理节点，请先重建 CTC')
            seen.add(bid)
            if previous is None or parents[bid] != previous or bid in split_before:
                chains.append([])
            chains[-1].append(node)
            previous = bid
        cursor += count
        for chain in chains:
            new_group = bytearray(group)
            struct.pack_into('<I', new_group, 0, len(chain))
            out_groups.append(new_group)
            for index, node in enumerate(chain):
                flags = (node[2] & ~1) | (index == 0)
                out_nodes.append(node[:2] + bytes((flags,)) + node[3:])
    if cursor != len(nodes) or seen != parents.keys():
        raise ValueError('CTC 缺少已登记的物理节点，请先重建 CTC')
    struct.pack_into('<II', header, 0x10, len(out_groups), len(out_nodes))
    return bytes(header) + b''.join(out_groups) + b''.join(out_nodes) + tail

def _node_id(node):
    return struct.unpack_from('<H', node)[0]

def _group_chains(groups, nodes):
    chains = []
    cursor = 0
    for group in groups:
        count = struct.unpack_from('<I', group)[0]
        chains.append(list(nodes[cursor:cursor + count]))
        cursor += count
    return chains

def _restore_links(arm, physical, pending, locked_roots):
    registered = set(physical)
    marked = {name for name in registered if arm.data.bones[name].get('MT_PhysBridge')}
    real = {name: arm.data.bones[name] for name in registered - marked}
    keep, restore = set(), {}
    for name in sorted(marked | pending):
        bone = arm.data.bones[name]
        parent = bone.parent
        children = bone.children
        if len(children) != 1 or children[0].name not in real or parent is None:
            if name in pending:
                raise ValueError(f'「{name}」尚未登记，请先登记普通新增骨')
            raise ValueError(f'「{name}」无法识别为连接骨，请核对它的父骨和唯一物理子骨')
        child = children[0]
        if parent.name in real and bone.use_connect and child.use_connect:
            if (physical.get(name) in locked_roots and bone.use_inherit_rotation
                    and child.use_inherit_rotation and not bone.use_deform):
                keep.add(name)
                continue
        elif name in marked and parent.name not in registered:
            candidates = []
            descendants = {b.name for b in child.children_recursive} | {child.name}
            for source in real.values():
                if source.name in descendants or (source.head_local - bone.head_local).length > LEGACY_TOLERANCE:
                    continue
                anchor = source.parent
                while anchor and (anchor.name in registered or anchor.name in pending):
                    anchor = anchor.parent
                if anchor == parent:
                    candidates.append(source)
            if len(candidates) != 1:
                raise ValueError(f'找不到旧连接骨「{name}」的唯一原父骨。请在编辑模式把它接回物理父骨尾端')
            parent = candidates[0]
        elif name in pending:
            raise ValueError(f'「{name}」尚未登记。手工连接骨须两端勾选「相连」，且两端都是已登记的物理骨')
        elif parent.name not in real:
            raise ValueError(f'「{name}」的物理父骨需要先在编辑模式接好')
        restore[child.name] = (parent.name, name, physical.get(name))
    return keep, restore

def _check_removed_references(context, arm, ids, labels):
    from .MTframework_MHGU_ccl import capsules_from_json

    capsules = capsules_from_json(context.scene.MT_CclCapsules)
    if any(ids & {cap['a'], cap['b']} for cap in capsules):
        raise ValueError('CCL 胶囊仍引用待调整的骨，请先修正胶囊的 A/B 骨位')
    for obj in context.scene.objects:
        if obj.type != 'MESH':
            continue
        linked = obj.find_armature()
        if linked != arm and (linked is not None or not obj.select_get()):
            continue
        indices = {group.index for group in obj.vertex_groups if group.name in labels}
        if indices and any(group.group in indices and group.weight > 0
                           for vertex in obj.data.vertices for group in vertex.groups):
            raise ValueError(f'「{obj.name}」仍有权重指向待调整的连接骨或已删除的骨，请先转移权重')

def sync_registered_edits(context, arm, mod, ctc):
    from .MTframework_MHGU import get_bone_name_map, get_object_center_offset
    from .MTframework_MHGU_bones import write_bone_section
    from .MTframework_MHGU_physmat import rebuild_matrices

    from .MTframework_MHGU_bones import bone_head_to_file_translation
    from .MTframework_MHGU_physcustom import _custom_records

    template = _parse(mod)
    recorded = get_bone_name_map(context.scene, arm)
    ids = {bone['id']: bone['slot'] for bone in template['bones']}
    known = {int(bid): str(name) for bid, name in (arm.get('MT_PhysIdMap') or {}).items()}
    if not known or not recorded:
        return None
    _, old_groups, old_nodes, _ = _split_ctc(ctc)
    old_chains = [tuple(map(_node_id, row)) for row in _group_chains(old_groups, old_nodes)]
    old_ids = {_node_id(node) for node in old_nodes}
    if len(old_ids) != len(old_nodes) or len(set(known.values())) != len(known):
        raise ValueError('登记的 CTC 或骨名存在重复，无法安全匹配')
    restore = {}
    for bid, name in known.items():
        if bid in ids:
            if name in recorded and recorded[name] != ids[bid]:
                raise ValueError(f'登记的物理骨「{name}」与工程模板的骨位不一致，请恢复对应工程的模板')
            recorded[name] = ids[bid]
        elif bid in old_ids and PHYS_MIN <= bid < 255:
            if name in arm.data.bones:
                restore[name] = bid
        elif name in arm.data.bones:
            raise ValueError(f'登记的物理骨「{name}」缺少模板和 CTC 记录，请恢复对应工程的模板')
    names = _custom_records(arm, template['n'], recorded)
    for name in restore:
        names.pop(name, None)
    if len(names) != len(set(names.values())):
        raise ValueError('同一模板骨位对应多个骨名')
    removed = set(range(template['n'])) - set(names.values())
    if any(template['bones'][slot]['id'] < PHYS_MIN for slot in removed):
        raise ValueError('当前骨架缺少模板里的身体骨，请恢复对应工程的骨架')
    unknown_ctc = old_ids - ids.keys() - known.keys()
    if unknown_ctc:
        raise ValueError('缺少 CTC 骨位记录，无法确认骨骼 ID：' + str(sorted(unknown_ctc)[:8]))
    removed_ids = ({template['bones'][slot]['id'] for slot in removed}
                   | (old_ids - ids.keys() - set(restore.values())))
    if restore and template['n'] - len(removed) + len(restore) > 255:
        raise ValueError('恢复已登记的物理链后超过 255 骨位')
    for index, name in enumerate(restore, start=template['n']):
        names[name] = index
    parents, plans = {}, []
    offset = get_object_center_offset(arm, context.scene)
    for name, slot in names.items():
        bone = arm.data.bones[name]
        parent = bone.parent
        if parent is not None and parent.name not in names:
            raise ValueError(f'「{name}」的父骨「{parent.name}」未登记，请先登记新骨')
        if slot >= template['n']:
            if parent is None:
                raise ValueError(f'「{name}」需要挂到已登记的父骨')
            translation = bone_head_to_file_translation(
                arm.matrix_world @ bone.head_local - offset, template['scale'])
            world = tuple(center - value for center, value in zip(template['c'], translation))
            plans.append(dict(id=restore[name], parent=names[parent.name], world=world))
            continue
        previous = template['bones'][slot]['parent']
        if parent is None:
            if previous < template['n'] and previous != slot:
                raise ValueError(f'「{name}」需要挂到已登记的父骨')
        elif previous != names[parent.name]:
            parents[slot] = names[parent.name]
    if not (removed_ids or parents or plans):
        return None
    if removed_ids:
        removed_labels = {name for name, slot in recorded.items() if slot in removed}
        removed_labels.update(known[bid] for bid in removed_ids if bid in known)
        _check_removed_references(context, arm, removed_ids, removed_labels)

    current = bytearray(mod)
    live_existing = {name: slot for name, slot in names.items() if slot < template['n']}
    write_bone_section(current, template['ptr'], template['n'], arm,
                       name_map=live_existing, offset=offset, anchor=False)
    new_mod, slots = _move_bone_records(current, _parse(current), plans, removed=removed,
                                        parent_overrides=parents)
    new_ctc = _trim_ctc(ctc, _parse(new_mod))
    _, groups, nodes, _ = _split_ctc(new_ctc)
    chains = [tuple(map(_node_id, row)) for row in _group_chains(groups, nodes)]
    changed = {bid for row in chains if row not in old_chains for bid in row}
    for slot in parents:
        bid = template['bones'][slot]['id']
        changed.update(next((row for row in chains if bid in row), ()))
    new_bones = _parse(new_mod)['bones']
    by_id = {new_bones[slots[slot]]['id']: name for name, slot in names.items()}
    changed.update(restore.values())
    protected = {_node_id(node) for node in nodes
                 if struct.unpack_from('<f', node, 8)[0] == 0
                 and struct.unpack_from('<f', node, 80)[0] == 0}
    incomplete = [by_id[row[0]] for row in chains if len(row) == 1
                  and row not in old_chains and row[0] not in protected]
    if incomplete:
        raise ValueError('融并后链只剩一个节点：' + '、'.join(incomplete[:8])
                         + '。请保留第二个链节点，或将整条链的权重转移到身体骨')
    if changed - protected:
        new_ctc, _ = rebuild_matrices(arm, new_ctc, names=by_id, nodes=changed - protected)
    problems = check_topology(new_mod, new_ctc)
    if problems:
        raise ValueError('融并后 CTC 检查失败：' + problems[0])
    name_map = {name: slots[slot] for name, slot in names.items()}
    id_map = {str(bid): name for bid, name in by_id.items() if bid in old_ids}
    return new_mod, new_ctc, name_map, id_map, len(removed_ids), len(restore)

def _plan_links(arm, template, groups, nodes, names, keep, restored, offset):
    from .MTframework_MHGU_bones import bone_head_to_file_translation

    by_id = {b['id']: b for b in template['bones']}
    by_slot = {slot: name for name, slot in names.items()}
    plans = []
    for index, chain in enumerate(_group_chains(groups, nodes)):
        child = by_id[_node_id(chain[0])]
        if child['parent'] >= template['n']:
            raise ValueError('CTC 链根缺少父骨')
        parent = template['bones'][child['parent']]
        if parent['id'] < PHYS_MIN:
            continue
        child_name, parent_name = by_slot[child['slot']], by_slot[parent['slot']]
        if child_name in keep:
            continue
        child_bone, parent_bone = arm.data.bones[child_name], arm.data.bones[parent_name]
        head = parent_bone.tail_local
        direct = (child_bone.head_local - head).length <= JOINT_TOLERANCE
        _, helper, old_id = restored.get(child_name, (None, None, None))
        translation = bone_head_to_file_translation(arm.matrix_world @ head - offset, template['scale'])
        world = tuple(center - value for center, value in zip(template['c'], translation))
        plans.append(dict(group=index, child=child['slot'], parent=parent['slot'],
                          child_name=child_name, parent_name=parent_name, direct=direct,
                          name=helper, old_id=old_id, world=world))
    return plans

def _relink_ctc(ctc, template, plans):
    header, groups, nodes, tail = _split_ctc(ctc)
    chains = _group_chains(groups, nodes)
    by_id = {b['id']: b for b in template['bones']}
    owner = {_node_id(node): index for index, chain in enumerate(chains) for node in chain}
    merged = set()
    preset = PHYS_PRESETS[DEFAULT_PRESET_KEY]

    for plan in plans:
        index = plan['group']
        if plan['direct']:
            continue
        chain = chains[index]
        child = template['bones'][plan['child']]
        direction = [a - b for a, b in zip(child['world'], plan['world'])]
        chain.insert(0, _locked_root_bytes(plan['id'], direction))
        owner[plan['id']] = index

    direct = {plan['group']: plan for plan in plans if plan['direct']}
    matches = {}
    for index, plan in direct.items():
        parent_id = template['bones'][plan['parent']]['id']
        parent_group = owner[parent_id]
        if _node_id(chains[parent_group][-1]) == parent_id and groups[index][4:] == groups[parent_group][4:]:
            matches.setdefault(parent_group, []).append(index)

    def join(index):
        children = matches.get(index, ())
        if len(children) != 1:
            return
        child_group = children[0]
        if child_group in merged:
            return
        join(child_group)
        chain = chains[index]
        parent = by_id[_node_id(chain[-1])]
        child = by_id[_node_id(chains[child_group][0])]
        direction = [a - b for a, b in zip(child['world'], parent['world'])]
        old = chain[-1]
        axis = struct.unpack_from('<3f', old, 32)
        oriented = _node_bytes(parent['id'], False, direction, preset, axis=axis)
        chain[-1] = old[:16] + oriented[16:80] + old[80:]
        chain.extend(chains[child_group])
        owner.update((_node_id(node), index) for node in chains[child_group])
        merged.add(child_group)

    for index in matches:
        join(index)

    added_parents = {plan['id']: template['bones'][plan['parent']]['id']
                     for plan in plans if not plan['direct']}
    order, visited = [], set()

    def visit(index):
        if index in visited:
            return
        visited.add(index)
        bid = _node_id(chains[index][0])
        parent_id = added_parents.get(bid)
        if parent_id is None:
            record = by_id[bid]['parent']
            if record < template['n']:
                parent_id = template['bones'][record]['id']
        if parent_id in owner and owner[parent_id] != index:
            visit(owner[parent_id])
        order.append(index)

    for index in range(len(groups)):
        if index not in merged:
            visit(index)

    out_groups, out_nodes = [], []
    for index in order:
        chain = chains[index]
        out_groups.append(struct.pack('<I', len(chain)) + groups[index][4:])
        for position, node in enumerate(chain):
            flags = (node[2] & ~1) | (position == 0)

            rotation = 1 if position == 0 and index in direct else node[3]
            out_nodes.append(node[:2] + bytes((flags, rotation)) + node[4:])
    struct.pack_into('<II', header, 0x10, len(out_groups), len(out_nodes))
    return bytes(header) + b''.join(out_groups) + b''.join(out_nodes) + tail

def _locked_root_bytes(bid, direction):
    node = bytearray(_node_bytes(bid, True, direction, PHYS_PRESETS[DEFAULT_PRESET_KEY],
                                 values=(0.0, 1.0, 1.0)))
    node[3] = 1
    struct.pack_into('<f', node, 8, 0.0)
    return bytes(node)

def connect_physics_groups(context, arm, mod, ctc, budget):
    from .MTframework_MHGU import get_object_center_offset, get_bone_name_map
    from .MTframework_MHGU_bones import write_bone_section
    from .MTframework_MHGU_physcustom import _custom_records
    from .MTframework_MHGU_tpl import _project_template_path, store
    from .MTframework_MMD_rig import _edit_arm

    if arm.library or arm.data.library or arm.data.users != 1:
        raise ValueError('请先把 MT 骨架设为本地单用户')
    template = _parse(mod)
    names = _custom_records(arm, template['n'], get_bone_name_map(context.scene, arm))
    if len(set(names.values())) != len(names):
        raise ValueError('多个骨名对应同一模板骨位，请核对骨架和模板')
    ids = {name: template['bones'][slot]['id'] for name, slot in names.items()}
    physical = {name: bid for name, bid in ids.items() if bid >= PHYS_MIN}
    pending = {b.name for b in arm.data.bones} - names.keys()
    _, old_groups, old_nodes, _ = _split_ctc(ctc)
    locked_roots = {_node_id(c[0]) for c in _group_chains(old_groups, old_nodes)
                    if c and c[0][2:4] == b'\x01\x01'
                    and struct.unpack_from('<f', c[0], 8)[0] == 0
                    and struct.unpack_from('<f', c[0], 80)[0] == 0}
    keep, restored = _restore_links(arm, physical, pending, locked_roots)
    deleted = set(range(template['n'])) - set(names.values())
    if any(template['bones'][i]['id'] < PHYS_MIN for i in deleted):
        raise ValueError('当前骨架缺少模板里的身体骨，无法同步')
    replaced = {helper for _, helper, bid in restored.values() if bid is not None}
    removed = deleted | {names[name] for name in replaced}
    removed_ids = {template['bones'][i]['id'] for i in removed}
    removed_labels = {f'b_{i + 1}' for i in deleted}
    removed_labels.update(str(name) for bid, name in (arm.get('MT_PhysIdMap') or {}).items()
                          if int(bid) in removed_ids)
    removed_labels.difference_update(names)
    if pending or removed:
        _check_removed_references(context, arm, removed_ids, removed_labels | pending | replaced)

    offset = get_object_center_offset(arm, context.scene)
    current = bytearray(mod)
    write_bone_section(current, template['ptr'], template['n'], arm,
                       name_map=names, offset=offset, anchor=False)
    current = bytes(current)
    overrides = {names[child]: names[parent] for child, (parent, _, _) in restored.items()}
    if removed or overrides:
        current, compacted = _move_bone_records(current, _parse(current), [], removed=removed,
                                                parent_overrides=overrides)
        names = {name: compacted[slot] for name, slot in names.items() if slot not in removed}
    data = _parse(current)
    prepared = _trim_ctc(ctc, data, {ids[child] for child in restored}) if removed or restored else ctc
    problems = check_topology(current, prepared)
    if problems:
        raise ValueError('CTC 与当前骨架的链关系不一致：' + problems[0])
    _, groups, nodes, _ = _split_ctc(prepared)
    if not groups:
        raise ValueError('当前模板没有可连接的 CTC 链')
    node_ids = {_node_id(node) for node in nodes}
    if len(node_ids) != len(nodes) or node_ids != {b['id'] for b in data['bones'] if b['id'] >= PHYS_MIN}:
        raise ValueError('CTC 节点和已登记骨骼不一致，请先重建 CTC')
    plans = _plan_links(arm, data, groups, nodes, names, keep, restored, offset)
    bridges = [p for p in plans if not p['direct']]
    available = _available_phys_ids(data)
    capacity = max(0, min(len(available), budget - data['n']))
    if len(bridges) > capacity:
        raise ValueError(f'连接骨需要 {len(bridges)} 个骨位，当前还可用 {capacity} 个')
    reserved = {p['old_id'] for p in bridges if p['old_id'] is not None}
    free_ids = (bid for bid in available if bid not in reserved)
    live_names = {b.name for b in arm.data.bones}
    total = data['n'] + len(bridges)
    numbers = chain(range(total, 0, -1), count(total + 1))
    available_names = (f'b_{n}' for n in numbers if f'b_{n}' not in live_names)
    for index, plan in enumerate(bridges):
        plan['id'] = next(free_ids) if plan['old_id'] is None else plan['old_id']
        plan['record'] = data['n'] + index
        if plan['name'] is None:
            plan['name'] = next(available_names)

    new_ctc = _relink_ctc(prepared, data, plans) if plans else prepared
    def needs_edit(plan):
        child = arm.data.bones[plan['child_name']]
        return (not plan['direct'] or plan['name'] is not None or not child.use_connect
                or not child.use_inherit_rotation)

    changed = [plan for plan in plans if needs_edit(plan)]
    if not changed and not removed and new_ctc == ctc:
        return ctc, 0, 0, 0
    new_mod, slots = _move_bone_records(current, data, bridges)
    problems = check_topology(new_mod, new_ctc)
    if problems:
        raise ValueError('生成的连接链未通过检查：' + problems[0])

    def apply(bones):
        for plan in changed:
            child = bones[plan['child_name']]
            parent = bones[plan['parent_name']]
            name = plan['name']
            child.use_connect = False
            if plan['direct']:
                child.parent = parent
            else:
                helper = bones.get(name) or bones.new(name)
                helper.use_connect = False
                helper.parent = parent
                helper.head = parent.tail
                helper.tail = child.head
                helper.use_deform = False
                helper.use_inherit_rotation = True
                helper.use_connect = True
                child.parent = helper
            child.use_inherit_rotation = True
            child.use_connect = True
        for plan in changed:
            if plan['direct'] and plan['name'] is not None:
                bones.remove(bones[plan['name']])

    snapshot = {}
    for plan in changed:
        for name in (plan['child_name'], plan['name']):
            bone = arm.data.bones.get(name) if name else None
            if bone is not None:
                snapshot[name] = (bone.parent.name if bone.parent else None,
                                  bone.use_connect, bone.use_deform, bone.use_inherit_rotation, bone.head_local.copy(),
                                  bone.tail_local.copy(), bone.matrix_local.to_3x3().col[2].copy())

    def rollback(bones):
        for name, (_, _, deform, inherit_rotation, head, tail, axis) in snapshot.items():
            bone = bones.get(name) or bones.new(name)
            bone.use_connect = False
            bone.head, bone.tail, bone.use_deform = head, tail, deform
            bone.use_inherit_rotation = inherit_rotation
            bone.align_roll(axis)
        for name, (parent, connected, *_) in snapshot.items():
            bones[name].parent = bones.get(parent) if parent else None
            bones[name].use_connect = connected
        for plan in bridges:
            name = plan['name']
            if name not in snapshot and bones.get(name) is not None:
                bones.remove(bones[name])

    path = _project_template_path(context, new_mod, '_bridge')
    if not os.path.exists(path):
        with open(path, 'wb') as f:
            f.write(new_mod)
    try:
        if changed:
            _edit_arm(context, arm, apply)
        if not store(context, path):
            raise RuntimeError('无法保存带连接骨的模板')
    except (RuntimeError, ValueError):
        if changed:
            _edit_arm(context, arm, rollback)
        raise

    context.scene['MT_LastImportPath'] = path
    context.scene['MT_CtcCustom'] = True
    id_map = {str(bid): name for name, bid in physical.items() if name in names}
    for plan in bridges:
        name = plan['name']
        names[name] = plan['record']
        id_map[str(plan['id'])] = name
        arm.data.bones[name]['MT_PhysBridge'] = True
    migration = arm.get('MT_MmdBoneMap')
    if deleted and migration is not None:
        arm['MT_MmdBoneMap'] = {src: dest for src, dest in migration.items() if dest in names}
    tips = arm.get('MT_AutoTipBones')
    if deleted and tips is not None:
        arm['MT_AutoTipBones'] = [tip for tip in tips if tip in names]
    name_map = {name: slots[slot] for name, slot in names.items()}
    arm['MT_BoneNameMap'] = name_map
    context.scene['MT_BoneNameMap'] = name_map
    arm['MT_PhysIdMap'] = id_map
    arm[REMAPPED_SLOTS] = True
    context.view_layer.update()
    direct_count = sum(p['direct'] for p in changed)
    if not direct_count and new_ctc != ctc:
        direct_count = sum(p['direct'] for p in plans)
    return new_ctc, len(bridges), direct_count, len(deleted)
