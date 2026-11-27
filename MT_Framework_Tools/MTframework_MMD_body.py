import bpy
import struct
from pathlib import Path
from mathutils import Matrix, Vector

from .MTframework_MHGU import get_bone_name_map, get_object_center_offset
from .MTframework_MMD import _PRIMARY_MMD_NAME, _SWAP_INDEX, mmd_name_to_mhgu_bone

_PELVIS = ('下半身', 'pelvis', 'hips', 'hip', 'j_bip_c_hips', 'bip01 pelvis', '腰')

_BODY_CHAINS = ((8, 9, 10, 11), (2, 3, 4), (5, 6, 7),
                (12, 13, 14, 15), (16, 17, 18, 19))
_ENGLISH = {
    2: ('right leg', 'right thigh'), 3: ('right knee', 'right calf'),
    4: ('right ankle', 'right foot'), 5: ('left leg', 'left thigh'),
    6: ('left knee', 'left calf'), 7: ('left ankle', 'left foot'),
    8: ('spine',), 9: ('chest', 'upper chest'), 10: ('neck',), 11: ('head',),
    12: ('right shoulder',), 13: ('right arm', 'right upper arm'),
    14: ('right elbow', 'right forearm'), 15: ('right wrist', 'right hand'),
    16: ('left shoulder',), 17: ('left arm', 'left upper arm'),
    18: ('left elbow', 'left forearm'), 19: ('left wrist', 'left hand'),
}

def _name_key(name):
    name = name.strip().lower().replace('_', ' ')
    if name.startswith(('左', '右')):
        name = name[1:] + ('.l' if name[0] == '左' else '.r')
    if name.endswith((' l', ' r')):
        name = name[:-2] + '.' + name[-1]
    return name

def mmd_body_bones(arm, pelvis_name='', swap_lr=False):
    by_name = {_name_key(b.name): b for b in arm.data.bones}
    out = {}
    if pelvis_name:
        if pelvis_name not in arm.data.bones:
            raise ValueError('MMD 骨架里找不到指定的盆骨：' + pelvis_name)
        out[1] = arm.data.bones[pelvis_name]
    for slot, main in _PRIMARY_MMD_NAME.items():
        if slot in out:
            continue
        aliases = _PELVIS if slot == 1 else (main,) + _ENGLISH.get(slot, ())
        if slot in (2, 3, 4, 5, 6, 7):
            aliases += (main.replace('D.', '.'),)
        for alias in aliases:
            key = _name_key(alias)
            if key in by_name:
                out[slot] = by_name[key]
                break
    if swap_lr:
        return {_SWAP_INDEX.get(slot, slot): bone for slot, bone in out.items()}
    return out

def mt_body_bones(arm):
    recorded = get_bone_name_map(arm_obj=arm)
    slots = {}
    for bone in arm.data.bones:
        record = recorded.get(bone.name)
        if record is None and bone.name.startswith('b_') and bone.name[2:].isdigit():
            record = int(bone.name[2:]) - 1
        if record is not None and 0 <= record < 19:
            if record + 1 in slots:
                raise ValueError('MT 骨架有重复的身体骨位，请使用由 body.arc 导入的骨架')
            slots[record + 1] = bone
    return slots

def mmd_armature(context):
    props = context.scene.MT_Framework_MMD_Props
    if props.mmd_armature is not None:
        arm = props.mmd_armature
        if arm.type != 'ARMATURE' or context.view_layer.objects.get(arm.name) != arm:
            raise ValueError('请选择当前视图层里的 MMD 骨架')
        return arm

    def arm_of(obj):
        if obj is None:
            return None
        return obj if obj.type == 'ARMATURE' else obj.find_armature()

    arms = [o for o in context.view_layer.objects
            if o.type == 'ARMATURE' and {15, 19} & mmd_body_bones(o).keys()]
    active = arm_of(context.view_layer.objects.active)
    if active in arms:
        return active
    selected = {arm_of(o) for o in context.selected_objects}
    matches = [arm for arm in arms if arm in selected] or arms
    if len(matches) != 1:
        raise ValueError('请选择一副 MMD 骨架或它的网格，也可以在面板指定 MMD 骨架')
    return matches[0]

def body_armatures(context):
    props = context.scene.MT_Framework_MMD_Props
    arms = [o for o in context.view_layer.objects if o.type == 'ARMATURE']
    mt = props.mhgu_armature
    mmd = props.mmd_armature
    if mt is None:
        targets = [o for o in arms if o.data.bones.get('b_1') and len(mt_body_bones(o)) >= 16]
        if len(targets) == 1:
            mt = targets[0]
    if mmd is None:
        sources = [o for o in arms if 1 in mmd_body_bones(o) and o != mt]
        candidates = {o if o.type == 'ARMATURE' else o.find_armature()
                      for o in context.selected_objects if o.type in {'MESH', 'ARMATURE'}}
        selected = [o for o in sources if o in candidates]
        matches = selected or sources
        if len(matches) == 1:
            mmd = matches[0]
    if mt not in arms or mmd not in arms or mt == mmd:
        raise ValueError('需要两副可见骨架。请导入 body.arc 和 MMD，或在面板指定骨架')
    return mt, mmd

def _linked_meshes(context, arm):
    return [obj for obj in context.view_layer.objects
            if obj.type == 'MESH' and obj.data.polygons and obj.find_armature() == arm
            and getattr(obj, 'mmd_type', 'NONE') == 'NONE']

def _inherits_transform(obj, arm):
    while obj.parent is not None:
        obj = obj.parent
        if obj == arm:
            return True
    return False

def _weight_slots(mmd, source, swap_lr):
    exact = {b.name: slot for slot, b in source.items()}
    result = {}
    for bone in mmd.data.bones:
        parent = bone
        while parent is not None:
            slot = exact.get(parent.name)
            if slot is None:
                mapped = mmd_name_to_mhgu_bone(parent.name)
                if mapped:
                    slot = int(mapped[2:])
                    if swap_lr:
                        slot = _SWAP_INDEX.get(slot, slot)
            if slot is not None:
                result[bone.name] = slot
                break
            parent = parent.parent
    return result

def _ground_z(meshes, slots):
    low = float('inf')
    for obj in meshes:
        ankles = {g.index for g in obj.vertex_groups if slots.get(g.name) in (4, 7)}
        world_z = obj.matrix_world[2]
        for v in obj.data.vertices:
            if any(g.group in ankles and g.weight > 0.1 for g in v.groups):
                p = v.co
                low = min(low, world_z[0]*p.x + world_z[1]*p.y + world_z[2]*p.z + world_z[3])
    if low == float('inf'):
        raise ValueError('找不到受双脚骨骼控制的顶点，无法确定鞋底高度')
    return low

def _fit_edit_bones(bones, heads, links):
    tails = {name: head + (bones[name].tail - bones[name].head)
             for name, head in heads.items()}
    for name, child_name in links.items():
        if (heads[child_name] - heads[name]).length > 1e-5:
            tails[name] = heads[child_name]

    connected = []
    for bone in bones:
        if bone.use_connect and (bone.name in heads or bone.parent.name in tails):
            connected.append(bone)
            bone.use_connect = False
    for name, head in heads.items():
        bone = bones[name]
        bone.head = head
        bone.tail = tails[name]
    for bone in connected:
        if (bone.head - bone.parent.tail).length <= 1e-7:
            bone.use_connect = True

def align_body(context, mt, mmd, pelvis_name='', swap_lr=False):
    context.view_layer.update()
    target = mt_body_bones(mt)
    source = mmd_body_bones(mmd, pelvis_name, swap_lr)
    if 1 not in source or 1 not in target:
        raise ValueError('找不到 MT 的 b_1 或 MMD 盆骨，请指定 MMD 盆骨')
    if not {4, 7}.issubset(source) or len(target) < 16:
        raise ValueError('需要玩家身体骨架和可识别的两根 MMD 脚踝骨')
    meshes = _linked_meshes(context, mmd)
    if not meshes:
        raise ValueError('MMD 骨架下没有带蒙皮的网格')
    if mt.data.users != 1 or mt.library or mt.data.library or mmd.library:
        raise ValueError('请先把骨架变成本地单用户数据')
    pelvis = mmd.matrix_world @ source[1].head_local
    root = mt.matrix_world @ target[1].head_local
    sole = _ground_z(meshes, _weight_slots(mmd, source, swap_lr))
    ground = get_object_center_offset(mt, context.scene).z
    if pelvis.z - sole <= 1e-6 or root.z - ground <= 1e-6:
        raise ValueError('盆骨需要高于脚底，请核对骨架和模型的朝向')
    scale = (root.z - ground) / (pelvis.z - sole)
    transform = Matrix.Translation(root) @ Matrix.Scale(scale, 4) @ Matrix.Translation(-pelvis)
    inv = mt.matrix_world.inverted()
    original = mmd.matrix_world.copy()

    desired = {b.name: inv @ transform @ original @ source[slot].head_local
               for slot, b in target.items() if slot != 1 and slot in source}
    links = {}
    for chain in _BODY_CHAINS:
        for slot, next_slot in zip(chain, chain[1:]):
            parent, child = target.get(slot), target.get(next_slot)
            if (parent and child and child.parent == parent
                    and parent.name in desired and child.name in desired):
                links[parent.name] = child.name
    for obj in meshes:
        if obj.library:
            raise ValueError('MMD 网格必须为本地对象')
    detached = [(o, transform @ o.matrix_world.copy()) for o in meshes
                if not _inherits_transform(o, mmd)]
    old_active = context.view_layer.objects.active
    selection = tuple(context.selected_objects)
    was_hidden = mt.hide_get()
    mt.hide_set(False)
    for obj in selection:
        obj.select_set(False)
    mt.select_set(True)
    context.view_layer.objects.active = mt
    try:
        bpy.ops.object.mode_set(mode='EDIT')
        _fit_edit_bones(mt.data.edit_bones, desired, links)
    finally:
        if mt.mode == 'EDIT':
            bpy.ops.object.mode_set(mode='OBJECT')
        mt.select_set(False)
        for obj in selection:
            obj.select_set(True)
        context.view_layer.objects.active = old_active
        mt.hide_set(was_hidden)
    mmd.matrix_world = transform @ original
    context.view_layer.update()
    for obj, matrix in detached:
        obj.matrix_world = matrix
    context.view_layer.update()
    return scale, len(desired) + 1, source[1].name, root.z

def restore_root_tail(context, mt, path):
    from .MTframework_MHGU import convert_bone_position, infer_bone_tails
    from .MTframework_MHGU_bones import read_bone_section
    from .MTframework_MHGU_bontails import _read
    from .MTframework_MHGU_phys import arc_entries
    from .MTframework_MMD_rig import _edit_arm

    root = mt_body_bones(mt).get(1)
    if root is None or root.parent is not None or mt.data.users != 1 or mt.data.library:
        raise ValueError('请选择具有 b_1 根骨的本地单用户 MT 身体骨架')
    path = bpy.path.abspath(path)
    data = Path(path).read_bytes()
    if data.startswith(b'ARC\0'):
        data = next((e['body'] for e in arc_entries(data) if e['body'].startswith(b'MOD\0')), b'')
    if len(data) < 64 or data[:4] != b'MOD\0':
        raise ValueError('源文件没有可读取的 MHGU MOD')
    version, count = struct.unpack_from('<HH', data, 4)
    if version != 0xD4 or not 19 <= count <= 255:
        raise ValueError('请选择对齐前用来导入身体骨架的 body.arc 或 MOD')
    section = read_bone_section(data, struct.unpack_from('<I', data, 36)[0], count)
    parents = [info['Parent'] for info in section['infos']]
    if 0 < parents[0] < min(count, 254):
        raise ValueError('源文件的 b_1 不是根骨')
    heads = [convert_bone_position(Vector(t) / section['scale']) for t in section['world_t']]
    delta = infer_bone_tails(heads, parents)[0] - heads[0]
    roll = 0.0
    records = {e['record']: e for e in (_read(path) or ()) if e.get('record') is not None}
    if 0 in records:
        origin = heads[0] - Vector(records[0]['head'])
        if all((heads[i] - Vector(e['head']) - origin).length < 1e-4
               for i, e in records.items() if 0 <= i < count):
            saved = Vector(records[0]['tail_delta'])
            if saved.length > 1e-6:
                delta, roll = saved, float(records[0].get('roll', 0.0))

    def fit(bones):
        bone = bones[root.name]
        tail = bone.head + delta
        for child in bone.children:
            if child.use_connect and (child.head - tail).length > 1e-7:
                child.use_connect = False
        bone.tail = tail
        bone.roll = roll

    _edit_arm(context, mt, fit)

def bind_body(context, mt, mmd, meshes, pelvis_name='', swap_lr=False):
    from .MTframework_MMD_rig import mmd_weight_targets

    source = mmd_body_bones(mmd, pelvis_name, swap_lr)
    target = mt_body_bones(mt)
    if 1 not in source or len(target) < 16:
        raise ValueError('请先对齐 MT 和 MMD 的身体骨架')
    if ((mt.matrix_world @ target[1].head_local) -
            (mmd.matrix_world @ source[1].head_local)).length > 0.0001:
        raise ValueError('盆骨与 MT 的 b_1 尚未对齐')
    linked = _linked_meshes(context, mmd)
    if not meshes or any(o not in linked or o.data.users != 1 or o.library for o in meshes):
        raise ValueError('请选择绑定在这副 MMD 骨架上的本地单用户网格')
    remap = mmd_weight_targets(mt, mmd, source, target, swap_lr)
    source_bones = set(mmd.data.bones.keys())
    unknown = {}
    for obj in meshes:
        unresolved = {g.index: g.name for g in obj.vertex_groups
                      if g.name in source_bones and g.name not in remap}
        if unresolved:
            used = {unresolved[g.group] for v in obj.data.vertices for g in v.groups
                    if g.group in unresolved and g.weight > 0}
            if used:
                unknown[obj.name] = sorted(used)
    if unknown:
        detail = '; '.join(f'{obj}: {", ".join(names[:8])}' for obj, names in unknown.items())
        raise ValueError('这些带权重的 MMD 骨没有对应目标，请先迁移或指定身体映射：' + detail)
    fallback = 0
    from .MTframework_MHGU import CENTER_OFFSET_OBJ_KEY
    for obj in meshes:
        by_index = {g.index: remap.get(g.name) for g in obj.vertex_groups}
        groups = []
        for v in obj.data.vertices:
            sums = {}
            for g in v.groups:
                name = by_index[g.group]
                if name is not None and g.weight > 0:
                    sums[name] = sums.get(name, 0) + g.weight
            influences = list(sums.items())
            if not influences:
                fallback += 1
                influences = [(target[1].name, 1.0)]
            total = sum(w for _, w in influences)
            groups.append([(name, w / total) for name, w in influences])
        obj.vertex_groups.clear()
        new_groups = {name: obj.vertex_groups.new(name=name)
                      for name in sorted({name for weights in groups for name, _ in weights})}
        for index, weights in enumerate(groups):
            for name, weight in weights:
                new_groups[name].add([index], weight, 'REPLACE')
        world = obj.matrix_world.copy()
        obj.parent = mt
        obj.parent_type = 'OBJECT'
        obj.matrix_world = world
        for modifier in obj.modifiers:
            if modifier.type == 'ARMATURE' and modifier.object == mmd:
                modifier.object = mt
        obj[CENTER_OFFSET_OBJ_KEY] = list(get_object_center_offset(mt, context.scene))
    context.view_layer.update()
    return fallback
