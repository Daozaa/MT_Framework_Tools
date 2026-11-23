from collections import defaultdict

def fusion_plan(pending, reserve, capacity, paired_anchors=None):
    children = defaultdict(list)
    for name, parent in pending.items():
        children[parent].append(name)
    families = {}
    paired_anchors = paired_anchors or {}
    for anchor, roots in children.items():
        if anchor in pending:
            continue
        chains = families.setdefault(paired_anchors.get(anchor, anchor), [])
        todo = list(roots)
        while todo:
            path = [todo.pop()]
            while len(children.get(path[-1], ())) == 1:
                path.append(children[path[-1]][0])
            branches = children.get(path[-1], ())
            chains.append((path, bool(branches)))
            todo.extend(branches)

    removed = {}
    endpoints = {}
    deficit = len(pending) + reserve - capacity
    while deficit > 0:
        savings = {anchor: sum((len(chain) - fork) // 2 for chain, fork in chains if len(chain) >= 3)
                   for anchor, chains in families.items()}
        choices = [name for name, count in savings.items() if count]
        if not choices:
            raise ValueError("按骨链融并后仍超出 %d 个骨位，请减少需登记的链或调整骨数预算" % deficit)
        anchor = min(choices, key=lambda name: (savings[name] > deficit,
                     abs(savings[name] - deficit), name))
        for chain, fork in families[anchor]:
            if len(chain) < 3:
                continue
            linear = chain[:-1] if fork else chain
            for keep, drop in zip(linear[::2], linear[1::2]):
                removed[drop] = keep
                endpoints[keep] = endpoints.get(drop, drop)
            chain[:] = linear[::2] + (chain[-1:] if fork else [])
        deficit -= savings[anchor]

    for name, target in removed.items():
        while target in removed:
            target = removed[target]
        removed[name] = target
    return removed, {name: tail for name, tail in endpoints.items() if name not in removed}

def _transfer_fused_weights(obj, removed):
    active = {old: new for old, new in removed.items() if obj.vertex_groups.get(old)}
    if not active:
        return
    targets = {name: (obj.vertex_groups.get(name) or obj.vertex_groups.new(name=name))
               for name in set(active.values())}
    indices = {obj.vertex_groups[old].index: new for old, new in active.items()}
    indices.update({group.index: name for name, group in targets.items()})
    for v in obj.data.vertices:
        sums = {}
        for influence in v.groups:
            name = indices.get(influence.group)
            if name is not None:
                sums[name] = sums.get(name, 0.0) + influence.weight
        for name, value in sums.items():
            targets[name].add([v.index], min(1.0, value), 'REPLACE')
    for name in active:
        obj.vertex_groups.remove(obj.vertex_groups[name])

def apply_fusion(context, arm, removed, endpoints):
    from .MTframework_MMD_rig import MMD_BONE_MAP, _edit_arm

    if not removed:
        return 0
    meshes = [o for o in context.scene.objects if o.type == "MESH" and o.find_armature() == arm]
    if arm.library or arm.data.library or arm.data.users != 1 or any(o.library for o in meshes):
        raise ValueError("融并需要本地单用户骨架和可编辑的 MT 网格")

    def fit(bones):
        ends = {name: bones[tail].tail.copy() for name, tail in endpoints.items()}
        reconnect = []
        for bone in bones:
            if bone.name in removed:
                continue
            parent = bone.parent
            if parent and parent.name in removed:
                if bone.use_connect:
                    reconnect.append(bone)
                bone.use_connect = False
                bone.parent = bones[removed[parent.name]]
            elif bone.use_connect and parent.name in ends:
                reconnect.append(bone)
                bone.use_connect = False
        for name, end in ends.items():
            if (end - bones[name].head).length > 1e-6:
                bones[name].tail = end
        for name in removed:
            bones.remove(bones[name])
        for bone in reconnect:
            bone.use_connect = (bone.head - bone.parent.tail).length < 1e-6

    _edit_arm(context, arm, fit)
    for obj in meshes:
        _transfer_fused_weights(obj, removed)
    if MMD_BONE_MAP in arm:
        arm[MMD_BONE_MAP] = {src: removed.get(dest, dest)
                            for src, dest in arm[MMD_BONE_MAP].items()}
    context.view_layer.update()
    return len(removed)
