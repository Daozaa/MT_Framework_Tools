import math
import re
import unicodedata

import bpy
from mathutils import Matrix, Quaternion, Vector

from .MTframework_MMD_body import _linked_meshes, _weight_slots, mmd_body_bones, mt_body_bones
from .MTframework_MMD import is_finger_name, mmd_name_to_mhgu_bone

MMD_BONE_MAP = "MT_MmdBoneMap"
MMD_BONE_SOURCE = "MT_MmdSourceArm"
_DIGITS = (
    ("thumb", ("親指", "拇指", "thumb")),
    ("index", ("人差し指", "人指", "食指", "index")),
    ("middle", ("中指", "middle")),
    ("ring", ("薬指", "無名指", "ring")),
    ("little", ("小指", "little", "pinky", "pinkie")),
)
_DIGIT_PREFIX = re.compile(r"^(?:左|右|(?:left|right)[._ -]*|j_bip_[lr]_)")
_FLEXION = {
    "index": (32, 44, 24),
    "middle": (36, 48, 26),
    "ring": (40, 50, 28),
    "little": (42, 52, 28),
}
_UP = Vector((0, 0, 1))

def _digit(bone):
    name = unicodedata.normalize("NFKC", bone.name).lower()
    name = _DIGIT_PREFIX.sub("", name)
    for digit, aliases in _DIGITS:
        if name.startswith(aliases):
            return digit
    return None

def _hand_digits(wrist):
    digits = {}
    for bone in wrist.children_recursive:
        digit = _digit(bone)
        if digit:
            digits.setdefault(digit, []).append(bone)
    return digits

def _knuckles(digits):
    return {digit: bones[0].head_local for digit, bones in digits.items()
            if digit != "thumb"}

def _around_joint(head, rotation):
    transform = rotation.to_matrix().to_4x4()
    transform.translation = head - transform.to_3x3() @ head
    return transform

def _pitch(head, direction, toward, degrees):
    axis = direction.cross(toward)
    if axis.length_squared < 1e-12:
        return Matrix.Identity(4)
    return _around_joint(head, Quaternion(axis.normalized(), math.radians(degrees)))

def _finger_transforms(wrist, left, strength, wrist_lift, thumb_lower, up):
    digits = _hand_digits(wrist)
    roots = _knuckles(digits)
    if not {"index", "little"}.issubset(roots):
        return {}
    forward = sum(roots.values(), Vector()) / len(roots) - wrist.head_local
    across = roots["index"] - roots["little"]
    normal = forward.cross(across)
    if normal.length < 1e-7:
        return {}
    normal.normalize()
    if not left:
        normal.negate()

    hand = _pitch(wrist.head_local, forward, up, wrist_lift)
    transforms = {wrist.name: hand}
    thumb = next((b for b in digits.get("thumb", ()) if b.use_deform), None)
    turns = {}
    for bone in wrist.children_recursive:
        digit = _digit(bone)
        parent = bone.parent
        base = transforms[parent.name]
        if bone == thumb:
            down = base.to_3x3().transposed() @ -up
            transforms[bone.name] = base @ _pitch(
                bone.head_local, bone.tail_local - bone.head_local, down, thumb_lower)
            continue
        if digit is None or digit == "thumb" or not bone.use_deform:
            transforms[bone.name] = base
            continue
        step = turns.get(parent.name, 0) if _digit(parent) == digit else 0
        turns[bone.name] = step + 1
        if re.search(r'先|(?:tip|end)[._ -]?[lr]?$', bone.name, re.IGNORECASE):
            transforms[bone.name] = base
            continue
        angles = _FLEXION[digit]
        angle = angles[min(step, len(angles) - 1)] * strength
        axis = (bone.tail_local - bone.head_local).cross(normal)
        if axis.length < 1e-7:
            transforms[bone.name] = base
            continue
        bend = Quaternion(axis.normalized(), math.radians(angle))
        transforms[bone.name] = base @ _around_joint(bone.head_local, bend)
    return transforms

def _edit_arm(context, arm, apply):
    active = context.view_layer.objects.active
    selected = tuple(context.selected_objects)
    hidden = arm.hide_get()
    arm.hide_set(False)
    for obj in selected:
        obj.select_set(False)
    arm.select_set(True)
    context.view_layer.objects.active = arm
    try:
        bpy.ops.object.mode_set(mode="EDIT")
        return apply(arm.data.edit_bones)
    finally:
        if arm.mode == "EDIT":
            bpy.ops.object.mode_set(mode="OBJECT")
        arm.select_set(False)
        for obj in selected:
            obj.select_set(True)
        context.view_layer.objects.active = active
        arm.hide_set(hidden)

def _bake_rest_rotations(context, mmd, transforms, axes=None):
    meshes = _linked_meshes(context, mmd)
    if mmd.library or mmd.data.library or mmd.data.users != 1:
        raise ValueError("MMD 骨架须为本地单用户")
    context.view_layer.update()
    arm_inverse = mmd.matrix_world.inverted()
    plans = []
    for obj in meshes:
        deform_groups = {g.index for g in obj.vertex_groups
                         if mmd.data.bones.get(g.name) and mmd.data.bones[g.name].use_deform}
        affected = [g for g in obj.vertex_groups if g.index in deform_groups and g.name in transforms]
        if not affected:
            continue
        to_arm = arm_inverse @ obj.matrix_world
        from_arm = to_arm.inverted()
        by_group = {g.index: from_arm @ transforms[g.name] @ to_arm for g in affected}
        vertices = []
        for vertex in obj.data.vertices:
            hits = [(by_group[g.group], g.weight) for g in vertex.groups
                    if g.group in by_group and g.weight > 0]
            if hits:
                total = sum(g.weight for g in vertex.groups if g.group in deform_groups)
                if total > 0:
                    vertices.append((vertex.index, hits, total))
        if vertices:
            if obj.library or obj.data.library or obj.data.users != 1:
                raise ValueError("请将这个 MMD 网格设为本地单用户：" + obj.name)
            plans.append((obj, vertices))

    def apply(bones):
        connected = [bone for bone in bones if bone.use_connect
                     and (bone.name in transforms or bone.parent.name in transforms)]
        for bone in connected:
            bone.use_connect = False
        for name, transform in transforms.items():
            bone = bones[name]
            head, tail = transform @ bone.head, transform @ bone.tail
            roll = transform.to_3x3() @ bone.z_axis
            direction = axes.get(name) if axes else None
            if direction is not None:

                original = tail - head
                roll = original.rotation_difference(direction) @ roll
                tail = head + direction * original.length
            bone.head, bone.tail = head, tail
            bone.align_roll(roll)
        for bone in connected:
            if (bone.head - bone.parent.tail).length < 1e-6:
                bone.use_connect = True

    _edit_arm(context, mmd, apply)
    for obj, vertices in plans:
        keys = obj.data.shape_keys
        positions = [block.data for block in keys.key_blocks] if keys else [obj.data.vertices]
        for key in positions:
            for index, influences, total in vertices:
                point = key[index].co.copy()
                delta = sum(((matrix @ point - point) * weight for matrix, weight in influences),
                            Vector())
                key[index].co = point + delta / total
        if keys:
            for index, _, _ in vertices:
                obj.data.vertices[index].co = keys.reference_key.data[index].co
        obj.data.update()
    context.view_layer.update()
    return sum(len(v) for _, v in plans)

def apply_t_pose(context, mmd):
    source = mmd_body_bones(mmd)
    joints = {}
    axes = {}
    for slots, sign in (((12, 13, 14, 15), -1), ((16, 17, 18, 19), 1)):
        chain = [source.get(slot) for slot in slots]
        if any(bone is None for bone in chain):
            raise ValueError("需要两侧的 MMD 肩、上臂、肘和手腕骨")
        direction = Vector((sign, 0, 0))
        for joint, child in zip(chain, chain[1:]):
            if joint not in child.parent_recursive or (child.head_local - joint.head_local).length < 1e-6:
                raise ValueError("检查 MMD 手臂的骨骼父子关系和关节位置：" + joint.name)
            joints[joint.name] = child.head_local - joint.head_local
            axes[joint.name] = direction

    if all((joints[name].normalized() - axis).length < 1e-5
           and ((mmd.data.bones[name].tail_local - mmd.data.bones[name].head_local).normalized()
                - axis).length < 1e-5 for name, axis in axes.items()):
        return 0

    transforms = {}
    identity = Matrix.Identity(4)
    for bone in mmd.data.bones:
        base = transforms.get(bone.parent.name) if bone.parent else None
        if bone.name in joints:
            base = base if base is not None else identity
            direction = (base.to_3x3() @ joints[bone.name]).normalized()
            target = axes[bone.name]
            pivot_axis = direction.cross(target)
            if pivot_axis.length > 1e-8:
                turn = Quaternion(pivot_axis, math.atan2(pivot_axis.length, direction.dot(target)))
            else:
                turn = direction.rotation_difference(target)
            transforms[bone.name] = _around_joint(base @ bone.head_local, turn) @ base
        elif base is not None:
            transforms[bone.name] = base
    return _bake_rest_rotations(context, mmd, transforms, axes)

def bake_grip(context, mmd, strength, wrist_lift, thumb_lower):
    if mmd.get("MT_GripBaked"):
        raise ValueError("这个 MMD 骨架已烘焙握持姿势。可撤销或从烘焙前的工程重做")
    source = mmd_body_bones(mmd)
    up = mmd.matrix_world.to_quaternion().inverted() @ _UP
    transforms = {}
    for slot in (15, 19):
        wrist = source.get(slot)
        if wrist:
            transforms.update(_finger_transforms(wrist, slot == 19, strength, wrist_lift, thumb_lower, up))
    if not transforms:
        raise ValueError("找不到可确定掌面方向的食指、小指和手腕骨")
    vertices = _bake_rest_rotations(context, mmd, transforms)
    mmd["MT_GripBaked"] = True
    return vertices

def migrate_bones(context, mt, mmd, pelvis_name, swap_lr):
    if mt.library or mt.data.library or mt.data.users != 1:
        raise ValueError("MT 骨架须为本地单用户")
    source = mmd_body_bones(mmd, pelvis_name, swap_lr)
    target = mt_body_bones(mt)
    if 1 not in source or 1 not in target or (
            mmd.matrix_world @ source[1].head_local
            - mt.matrix_world @ target[1].head_local).length > 1e-4:
        raise ValueError("请先自动对齐身体骨骼")
    body_names = {bone.name: target[slot].name for slot, bone in source.items() if slot in target}
    previous = mt.get(MMD_BONE_SOURCE)
    if previous is not None and previous != mmd:
        raise ValueError("这副 MT 骨架已登记另一副 MMD 骨架的迁移关系")
    body_slots = _weight_slots(mmd, source, swap_lr)
    for bone in mmd.data.bones:
        if bone.name not in body_names and mmd_name_to_mhgu_bone(bone.name):
            slot = body_slots.get(bone.name)
            if slot in target:
                body_names[bone.name] = target[slot].name
    mapped = {src: dest for src, dest in dict(mt.get(MMD_BONE_MAP, {})).items()
              if dest in mt.data.bones}
    meshes = _linked_meshes(context, mmd)
    selected = [obj for obj in meshes if obj.select_get()]
    weighted = set()
    for obj in selected or meshes:
        groups = {g.index: g.name for g in obj.vertex_groups}
        weighted.update(groups[g.group] for v in obj.data.vertices for g in v.groups
                        if g.weight > 1e-6)
    wanted = set()
    for name in weighted:
        bone = mmd.data.bones.get(name)
        if bone is None or not bone.use_deform or _digit(bone) or is_finger_name(name):
            continue
        path = []
        while bone and bone.name not in body_names and bone.name not in mapped:
            path.append(bone.name)
            bone = bone.parent
        if bone is not None and not is_finger_name(bone.name):
            wanted.update(path)
    if not wanted:
        return 0
    basis = mt.matrix_world.inverted() @ mmd.matrix_world
    records = [(bone.name, bone.parent.name, basis @ bone.head_local,
                basis @ bone.tail_local, basis.to_3x3() @ bone.matrix_local.col[2].xyz)
               for bone in mmd.data.bones if bone.name in wanted]

    def copy(bones):
        destinations = {**body_names, **mapped}
        for name, parent, head, tail, roll in records:
            if parent not in destinations:
                raise ValueError("找不到迁移骨的父骨：" + parent)
            bone = bones.new(name)
            bone.head, bone.tail = head, tail
            bone.align_roll(roll)
            bone.parent = bones[destinations[parent]]
            bone.use_connect = (bone.head - bone.parent.tail).length < 1e-6
            destinations[name] = mapped[name] = bone.name

    _edit_arm(context, mt, copy)
    mt[MMD_BONE_MAP] = mapped
    mt[MMD_BONE_SOURCE] = mmd
    context.view_layer.update()
    return len(records)
