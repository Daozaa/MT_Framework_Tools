import fnmatch
import re

import bpy
from mathutils import Vector, Matrix

from bpy.props import (
    StringProperty, BoolProperty, IntProperty, FloatProperty,
    EnumProperty, CollectionProperty, PointerProperty
)
from bpy.types import Operator, Panel, PropertyGroup, UIList

FINGER_JP = ("親指", "人指", "中指", "薬指", "小指")
FINGER_EN = ("Thumb", "IndexFinger", "MiddleFinger", "RingFinger", "LittleFinger",
             "Index", "Middle", "Ring", "Little", "Pinky")

def is_finger_name(name):
    if not name:
        return False
    for p in FINGER_JP:
        if p in name:
            return True
    low = name.lower()
    for p in FINGER_EN:
        if p.lower() in low:
            return True

    if "finger" in low:
        return True
    return False

def finger_side(name):
    if not name:
        return None
    low = name.lower()
    if name.endswith(".L") or low.endswith("_l") or "left" in low or low.endswith(".l"):
        return 'L'
    if name.endswith(".R") or low.endswith("_r") or "right" in low or low.endswith(".r"):
        return 'R'
    return None

MMD_TO_MHGU_INDEX = {

    "下半身": 1,
    "下半身2": 8,
    "上半身": 8,
    "上半身1": 8,
    "上半身2": 9,
    "上半身3": 9,
    "首": 10,
    "首1": 10,
    "頭": 11,
    "目.L": 11, "目.R": 11,
    "全ての親": 1,
    "センター": 1,
    "グルーブ": 1,
    "腰": 8,

    "肩.L": 16, "腕.L": 17, "ひじ.L": 18, "手首.L": 19,
    "腕捩.L": 17, "手捩.L": 19,
    "肩P.L": 16, "肩C.L": 16, "股.L": 5,

    "肩.R": 12, "腕.R": 13, "ひじ.R": 14, "手首.R": 15,
    "腕捩.R": 13, "手捩.R": 15,
    "肩P.R": 12, "肩C.R": 12, "股.R": 2,

    "足D.L": 5, "ひざD.L": 6, "足首D.L": 7, "足先EX.L": 7,
    "足.L": 5, "ひざ.L": 6, "足首.L": 7,
    "つま先.L": 7, "足先.L": 7,

    "足D.R": 2, "ひざD.R": 3, "足首D.R": 4, "足先EX.R": 4,
    "足.R": 2, "ひざ.R": 3, "足首.R": 4,
    "つま先.R": 4, "足先.R": 4,
}

MMD_TO_MHGU_INDEX_EN = {
    "hips": 8, "spine": 8, "chest": 9, "neck": 10, "head": 11,
    "left shoulder": 16, "left arm": 17, "left elbow": 18, "left wrist": 19,
    "right shoulder": 12, "right arm": 13, "right elbow": 14, "right wrist": 15,
    "left leg": 5, "left knee": 6, "left ankle": 7, "left toe": 7,
    "right leg": 2, "right knee": 3, "right ankle": 4, "right toe": 4,
    "zarmtwist_l": 17, "zhandtwist_l": 19,
    "zarmtwist_r": 13, "zhandtwist_r": 15,
}

FINGER_TO_HAND_INDEX = {'L': 19, 'R': 15}

def swap_side_suffix(name):
    if not name:
        return name
    low = name.lower()
    if name.endswith(".L"):
        return name[:-2] + ".R"
    if name.endswith(".R"):
        return name[:-2] + ".L"
    if name.endswith(".l"):
        return name[:-2] + ".r"
    if name.endswith(".r"):
        return name[:-2] + ".l"
    if low.endswith("_l"):
        return name[:-2] + "_R"
    if low.endswith("_r"):
        return name[:-2] + "_L"
    if "left" in low:
        return name.replace("left", "right").replace("Left", "Right")
    if "right" in low:
        return name.replace("right", "left").replace("Right", "Left")
    return name

def mmd_name_to_mhgu_bone(name, overrides=None, swap_lr=False):
    if not name:
        return None
    if swap_lr:
        name = swap_side_suffix(name)

    _n = name.strip()
    if len(_n) > 2 and (_n.endswith('.l') or _n.endswith('.r')):
        _n = _n[:-1] + _n[-1].upper()
    elif len(_n) > 2 and (_n.endswith('_L') or _n.endswith('_R')):
        _n = _n[:-2] + '.' + _n[-1]
    elif len(_n) > 1 and _n[0] in ('左', '右'):
        _n = _n[1:] + ('.L' if _n[0] == '左' else '.R')
    name = _n
    if overrides and name in overrides:
        return overrides[name]

    if is_finger_name(name):
        side = finger_side(name)
        if side:
            return "b_{}".format(FINGER_TO_HAND_INDEX[side])

    if name in MMD_TO_MHGU_INDEX:
        return "b_{}".format(MMD_TO_MHGU_INDEX[name])
    low = name.lower().strip()
    if low in MMD_TO_MHGU_INDEX_EN:
        return "b_{}".format(MMD_TO_MHGU_INDEX_EN[low])

    for suf in (".l", ".r"):
        if low.endswith(suf):
            base = low[:-2].strip()
            if base in MMD_TO_MHGU_INDEX_EN:
                return "b_{}".format(MMD_TO_MHGU_INDEX_EN[base])
    return None

class MT_KeepItem(PropertyGroup):
    name: StringProperty(default="")
    keep: BoolProperty(default=False, description="勾选=改名时保留这个顶点组")

class MT_UL_KeepGroups(UIList):
    bl_idname = "MT_UL_keepgroups"

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "keep", text="")
        row.label(text=item.name, icon='GROUP_VERTEX')

class MT_OT_MMDRefreshKeep(Operator):
    bl_idname = "mt_framework.mmd_refresh_keep"
    bl_label = "刷新组列表"
    bl_description = "扫描选中网格（没选则整个场景）的顶点组，刷新勾选列表"

    def execute(self, context):
        props = context.scene.MT_Framework_MMD_Props
        objs = [o for o in context.selected_objects if o.type == 'MESH']
        if not objs:
            objs = [o for o in context.scene.objects if o.type == 'MESH']
        names = []
        seen = set()
        for o in objs:
            for vg in o.vertex_groups:
                if vg.name in seen:
                    continue
                seen.add(vg.name)
                names.append(vg.name)
        names.sort()
        old = {it.name: it.keep for it in props.keep_items}
        props.keep_items.clear()
        n = 0
        for nm in names:
            it = props.keep_items.add()
            it.name = nm
            it.keep = old.get(nm, is_kept_group(nm, props))
            if it.keep:
                n += 1
        self.report({'INFO'}, '共 %d 个顶点组，已勾选 %d 个' % (len(names), n))
        return {'FINISHED'}

class MT_OT_MMDKeepAll(Operator):
    bl_idname = "mt_framework.mmd_keep_all"
    bl_label = "全选/全不选"
    bl_description = "把所有列表项在勾选/取消之间切换"

    def execute(self, context):
        props = context.scene.MT_Framework_MMD_Props
        items = list(props.keep_items)
        if not items:
            self.report({'ERROR'}, '列表是空的，先点「刷新组列表」')
            return {'CANCELLED'}
        target = not all(it.keep for it in items)
        for it in items:
            it.keep = target
        self.report({'INFO'}, '已%s %d 个' % ('勾选' if target else '取消勾选', len(items)))
        return {'FINISHED'}

class MT_OT_MMDGridMarker(Operator):
    bl_idname = "mt_framework.mmd_cjk_font"
    bl_label = "修复日文显示"
    bl_description = "把 Blender 界面字体换成系统里的中日文字体，日文顶点组名就不会是方块了"

    def execute(self, context):
        import os
        cands = [
            r"C:\Windows\Fonts\msyh.ttc",
            r"C:\Windows\Fonts\msyh.ttf",
            r"C:\Windows\Fonts\YuGothM.ttc",
            r"C:\Windows\Fonts\yugothic.ttf",
            r"C:\Windows\Fonts\meiryo.ttc",
            r"C:\Windows\Fonts\simhei.ttf",
            r"C:\Windows\Fonts\simsun.ttc",
            r"C:\Windows\Fonts\msgothic.ttc",
        ]
        for p in cands:
            if os.path.exists(p):
                try:
                    context.preferences.view.font_path = p
                except Exception as e:
                    self.report({'ERROR'}, '设置字体失败: %s' % e)
                    return {'CANCELLED'}
                self.report({'INFO'}, '界面字体已切到 %s（要永久生效请保存偏好设置）'
                            % os.path.basename(p))
                return {'FINISHED'}
        self.report({'ERROR'}, '没找到系统中日文字体（msyh / YuGoth / meiryo / simhei）')
        return {'CANCELLED'}

class MTFrameworkMMDProps(PropertyGroup):

    map_mode: EnumProperty(
        name="映射方式",
        description="MMD 顶点组 → MHGU 顶点组 的映射方式",
        items=[
            ('NAME', "按名称表", "使用内置的 MMD→MHGU 骨序号表 (无需 MMD 骨架)"),
            ('POSITION', "按位置自动匹配", "需要场景中存在 MMD 骨架与 MHGU 骨架"),
        ],
        default='NAME',
    )

    merge_fingers: BoolProperty(
        name="合并手指到手掌",
        description="GU 手部没有手指骨, 把 MMD 各手指顶点组统一改到同侧手部顶点组",
        default=True,
    )

    swap_lr: BoolProperty(
        name="左右互换",
        description="默认 .L → +X 一侧(角色左手), .R → -X 一侧。若模型左右仍相反, 勾选此项",
        default=False,
    )

    keep_chest: BoolProperty(
        name="保留胸部顶点组",
        description="勾选: 胸部相关的 MMD 顶点组(胸*/乳*)不参与改名/合并/删除，原样保留。"
                    "GU 骨表里没有胸骨，默认会被并进上半身；想自己分配权重就勾这个",
        default=False,
    )

    keep_vgroups: StringProperty(
        name="额外保留的顶点组",
        description="逗号分隔，支持 * 通配。例如：胸*,乳*,スカート*,skirt*",
        default="",
    )

    keep_items: CollectionProperty(type=MT_KeepItem)
    keep_index: IntProperty(default=0)

    keep_unmapped: BoolProperty(
        name="保留未识别的顶点组",
        description="勾选: 不认识(映射不到目标骨骼)的顶点组保持原名不删; "
                    "取消: 一律删掉这些多余组",
        default=False,
    )

    remove_empty: BoolProperty(
        name="删除空顶点组",
        description="改名并合并后删除没有任何权重的顶点组",
        default=True,
    )

    delete_unmapped: BoolProperty(
        name="删除多余 MMD 顶点组",
        description="删除映射不到任何目标骨骼的 MMD 顶点组 (默认开)。"
                    "若某顶点只被这些组影响, 会先把权重转移给一个兜底骨骼"
                    "（目标骨架的根骨，或第一个 b_ 组；不是“最近的骨骼”），"
                    "避免顶点因为失去权重而塌到原点",
        default=True,
    )

    mmd_armature: PointerProperty(
        name="MMD 骨架",
        description="点右侧吸管, 再到视图里点一下 MMD 骨架",
        type=bpy.types.Object,
        poll=lambda self, obj: obj.type == 'ARMATURE',
    )

    mhgu_armature: PointerProperty(
        name="目标骨架",
        description="点右侧吸管, 再到视图里点一下目标骨架",
        type=bpy.types.Object,
        poll=lambda self, obj: obj.type == 'ARMATURE',
    )

def _is_mhgu_bone_name(name):
    if not name or not name.startswith("b_"):
        return False
    return name[2:].isdigit()

def _is_target_bone_name(name, mhgu_arm=None):
    if not name:
        return False
    if mhgu_arm is not None:
        try:
            if mhgu_arm.data.bones.get(name) is not None:
                return True
        except Exception:
            pass
    if _is_mhgu_bone_name(name):
        return True
    for suf in ('.l', '.r', '.L', '.R'):
        if name.endswith(suf) and _is_mhgu_bone_name(name[:-2]):
            return True
    return False

def _is_mmd_bone_name(name):
    if not name:
        return False
    if any(ord(c) > 0x2E80 for c in name):
        return True
    low = name.lower()
    for k in MMD_TO_MHGU_INDEX_EN:
        if k in low:
            return True
    return is_finger_name(name)

def find_armature(context, want_mmd):
    props = context.scene.MT_Framework_MMD_Props
    obj = props.mmd_armature if want_mmd else props.mhgu_armature
    if obj is not None and obj.type == 'ARMATURE':
        return obj

    best = None
    best_score = -1
    for cand in bpy.data.objects:
        if cand.type != 'ARMATURE':
            continue
        bones = cand.data.bones
        if not bones:
            continue
        mhgu_n = sum(1 for b in bones if _is_mhgu_bone_name(b.name))
        mmd_n = sum(1 for b in bones if _is_mmd_bone_name(b.name))
        fingers = sum(1 for b in bones if is_finger_name(b.name))
        if want_mmd:
            score = mmd_n * 2 + fingers * 3 - mhgu_n * 2
        else:
            score = mhgu_n * 2 - mmd_n * 2
        if score > best_score:
            best_score = score
            best = cand
    return best

def _resolve_to_armature_bone(name, mhgu_arm):
    if name is None or mhgu_arm is None:
        return name
    bones = mhgu_arm.data.bones
    if bones.get(name) is not None:
        return name
    idx = _bone_name_to_index(name, mhgu_arm)
    if idx is None:
        return name
    for b in bones:
        if _bone_name_to_index(b.name) == idx:
            return b.name
    return name

def _keep_patterns(props):
    pats = []
    if getattr(props, "keep_chest", False):
        pats.extend(["胸*", "乳*"])
    raw = getattr(props, "keep_vgroups", "") or ""
    for part in re.split(r"[,，;；]", raw):
        p = part.strip()
        if p:
            pats.append(p)
    return pats

def is_kept_group(name, props):
    if not name:
        return False
    try:
        for it in getattr(props, "keep_items", []):
            if it.keep and it.name == name:
                return True
    except Exception:
        pass
    for p in _keep_patterns(props):
        if fnmatch.fnmatchcase(name, p) or name == p:
            return True
    return False

def rename_vertex_groups(obj, props, mhgu_arm=None, mmd_arm=None):
    renamed = 0
    merged = 0
    unmapped = []
    deleted = 0
    rescued = 0

    src_names = [vg.name for vg in obj.vertex_groups]
    if not src_names:
        return renamed, merged, unmapped, deleted, rescued, 0

    plan = []
    kept = 0
    for name in src_names:

        if is_kept_group(name, props):
            kept += 1
            continue
        target = None
        if props.map_mode == 'NAME':

            if not props.merge_fingers and is_finger_name(name):
                target = None
            else:
                target = mmd_name_to_mhgu_bone(
                    name, None, swap_lr=getattr(props, "swap_lr", False))
        else:
            target = _nearest_mhgu_bone_name_for(name, mmd_arm, mhgu_arm)
        if target is None and not props.keep_unmapped:
            target = _nearest_mhgu_bone_name_for(name, mmd_arm, mhgu_arm)
        if target is None:

            if _is_target_bone_name(name, mhgu_arm):
                target = _resolve_to_armature_bone(name, mhgu_arm)
            else:
                unmapped.append(name)
                continue

        target = _resolve_to_armature_bone(target, mhgu_arm)
        plan.append((name, target))

    if not plan:
        return 0, 0, unmapped, 0, 0, kept

    by_target = {}
    for src, tgt in plan:
        by_target.setdefault(tgt, []).append(src)

    for tgt, srcs in by_target.items():
        if len(srcs) != 1:
            continue
        if obj.vertex_groups.get(tgt) is not None:
            continue
        vg = obj.vertex_groups.get(srcs[0])
        if vg is not None and vg.name != tgt:
            vg.name = tgt
            renamed += 1

    for tgt, srcs in sorted(by_target.items()):
        srcs = list(srcs)
        dst = obj.vertex_groups.get(tgt)

        collide = (dst is not None) and (dst.name not in srcs)
        if len(srcs) < 2 and not collide:
            continue
        if dst is None:

            vg = obj.vertex_groups.get(srcs[0])
            if vg is None:
                continue
            vg.name = tgt
            renamed += 1
            dst = vg
            srcs = srcs[1:]
        else:

            srcs = [s for s in srcs if s != tgt]
        if not srcs:
            continue

        best = {}
        for sname in srcs:
            sg = obj.vertex_groups.get(sname)
            if sg is None:
                continue
            s_idx = sg.index
            for v in obj.data.vertices:
                for g in v.groups:
                    if g.group == s_idx and g.weight > 0.0:
                        if g.weight > best.get(v.index, 0.0):
                            best[v.index] = g.weight
            merged += 1

        dst_idx = dst.index
        cur_w = {}
        for v in obj.data.vertices:
            for g in v.groups:
                if g.group == dst_idx:
                    cur_w[v.index] = g.weight
        for vi, w in best.items():
            if w > cur_w.get(vi, 0.0):
                dst.add([vi], w, 'REPLACE')

        for sname in srcs:
            vg = obj.vertex_groups.get(sname)
            if vg is not None:
                try:
                    obj.vertex_groups.remove(vg)
                except Exception:
                    pass

    for v in obj.data.vertices:
        total = sum(g.weight for g in v.groups)
        if total > 0 and abs(total - 1.0) > 1e-4:
            for g in v.groups:
                try:
                    obj.vertex_groups[g.group].add([v.index], g.weight / total, 'REPLACE')
                except Exception:
                    pass

    if props.remove_empty:
        used = set()
        for v in obj.data.vertices:
            for g in v.groups:
                if g.weight > 0.0:
                    used.add(g.group)
        empty = [vg for vg in obj.vertex_groups if vg.index not in used]
        for vg in empty:
            try:
                obj.vertex_groups.remove(vg)
            except Exception:
                pass

    if props.delete_unmapped and not props.keep_unmapped:
        deleted, rescued = _delete_unmapped_groups(obj, mhgu_arm, mmd_arm, props)
        if deleted:
            unmapped = []
    return renamed, merged, unmapped, deleted, rescued, kept

def _pick_fallback_group(obj, mhgu_arm):
    root_name = None
    if mhgu_arm is not None:
        for b in mhgu_arm.data.bones:
            if b.parent is None:
                root_name = b.name
                break
        if root_name is not None and obj.vertex_groups.get(root_name) is None:
            try:
                obj.vertex_groups.new(name=root_name)
            except Exception:
                root_name = None
    if root_name is None:
        cands = [vg.name for vg in obj.vertex_groups if vg.name.startswith("b_")]
        if not cands:
            cands = [vg.name for vg in obj.vertex_groups]
        root_name = cands[0] if cands else None
    if root_name is None:
        return None
    return obj.vertex_groups.get(root_name)

def _delete_unmapped_groups(obj, mhgu_arm, mmd_arm, props=None):
    doomed = []
    for vg in obj.vertex_groups:
        if props is not None and is_kept_group(vg.name, props):
            continue
        if vg.name.startswith("b_") and vg.name[2:].isdigit():
            continue
        if mmd_name_to_mhgu_bone(vg.name) is not None:
            continue
        if mhgu_arm is not None and mhgu_arm.data.bones.get(vg.name) is not None:
            continue
        doomed.append(vg)
    if not doomed:
        return 0, 0

    doomed_idx = {vg.index for vg in doomed}

    rescue = {}
    for v in obj.data.vertices:
        live = [(g.group, g.weight) for g in v.groups
                if g.weight > 0.0 and g.group not in doomed_idx]
        if live:
            continue
        lost = sum(g.weight for g in v.groups
                   if g.weight > 0.0 and g.group in doomed_idx)
        if lost > 0.0:
            rescue[v.index] = min(1.0, lost)

    rescued = 0
    if rescue:
        fb = _pick_fallback_group(obj, mhgu_arm)
        if fb is not None:
            for vi, w in rescue.items():
                fb.add([vi], w, 'REPLACE')
            rescued = len(rescue)

    deleted = 0
    for vg in doomed:
        try:
            obj.vertex_groups.remove(vg)
            deleted += 1
        except Exception:
            pass

    fixed = 0
    for v in obj.data.vertices:
        live = [(g.group, g.weight) for g in v.groups if g.weight > 0.0]
        if not live:
            continue
        total = sum(w for _gi, w in live)
        if total > 0.0 and abs(total - 1.0) > 1e-4:
            for gi, w in live:
                if gi < len(obj.vertex_groups):
                    obj.vertex_groups[gi].add([v.index], w / total, 'REPLACE')
            fixed += 1
    if fixed:
        rescued = max(rescued, 0)
    return deleted, rescued

def _nearest_mhgu_bone_name_for(group_name, mmd_arm, mhgu_arm):
    if mmd_arm is None or mhgu_arm is None:
        return None
    bone = mmd_arm.data.bones.get(group_name)
    if bone is None:
        return None
    p = mmd_arm.matrix_world @ bone.head_local
    finger = is_finger_name(group_name)
    best = None
    best_d = None
    for b in mhgu_arm.data.bones:
        if finger and is_finger_name(b.name):
            continue
        q = mhgu_arm.matrix_world @ b.head_local
        d = (p - q).length
        if best_d is None or d < best_d:
            best_d = d
            best = b
    return best.name if best else None

_PRIMARY_MMD_NAME = {
    1: "下半身", 8: "上半身", 9: "上半身2", 10: "首", 11: "頭",
    16: "肩.L", 17: "腕.L", 18: "ひじ.L", 19: "手首.L",
    12: "肩.R", 13: "腕.R", 14: "ひじ.R", 15: "手首.R",
    5: "足D.L", 6: "ひざD.L", 7: "足首D.L",
    2: "足D.R", 3: "ひざD.R", 4: "足首D.R",
}

def _bone_name_to_index(name, arm=None):
    if not name:
        return None
    try:
        from .MTframework_MHGU import get_bone_name_map
        m = get_bone_name_map(arm_obj=arm)
        if name in m:
            return int(m[name])
    except Exception:
        pass
    n = name
    low = n.lower()
    for suf in (".l", ".r", "_l", "_r"):
        if low.endswith(suf):
            n = n[:-2]
            break
    if n.startswith("b_") and n[2:].isdigit():
        return int(n[2:]) - 1
    return None

def _mhgu_to_mmd_name(bone_name, mmd_arm=None, swap_lr=False):
    idx0 = _bone_name_to_index(bone_name)
    if idx0 is None:
        return None
    idx = idx0 + 1
    if swap_lr:
        idx = _SWAP_INDEX.get(idx, idx)

    candidates = []
    if idx in _PRIMARY_MMD_NAME:
        candidates.append(_PRIMARY_MMD_NAME[idx])
    for src in (MMD_TO_MHGU_INDEX, MMD_TO_MHGU_INDEX_EN):
        for k, v in src.items():
            if v == idx and k not in candidates:
                candidates.append(k)
    if not candidates:
        return None
    if mmd_arm is not None:
        for c in candidates:
            if c in mmd_arm.data.bones:
                return c

        lower = {b.name.lower(): b.name for b in mmd_arm.data.bones}
        for c in candidates:
            if c.lower() in lower:
                return lower[c.lower()]
        return None
    return candidates[0]

def _build_swap_index():
    import re as _re
    out = {}
    for src in (MMD_TO_MHGU_INDEX, MMD_TO_MHGU_INDEX_EN):
        for name, idx in src.items():
            other = swap_side_suffix(name)
            if other == name:
                continue
            for src2 in (MMD_TO_MHGU_INDEX, MMD_TO_MHGU_INDEX_EN):
                oidx = src2.get(other)
                if oidx is not None:
                    out[idx] = oidx
                    break
    return out

_SWAP_INDEX = {}
try:
    _SWAP_INDEX = _build_swap_index()
except Exception:
    _SWAP_INDEX = {}

class MT_OT_MMDRenameVGroups(Operator):

    bl_idname = "mt_framework.mmd_rename_vgroups"
    bl_label = "MMD → MHGU 顶点组重命名"
    bl_description = "批量把 MMD 顶点组名改成 MHGU 顶点组名; GU 没有手指骨, 手指组会合并到同侧手部组"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return any(o.type == 'MESH' for o in context.selected_objects)

    def execute(self, context):
        props = context.scene.MT_Framework_MMD_Props
        targets = [o for o in context.selected_objects if o.type == 'MESH']
        mmd_arm = find_armature(context, True)
        mhgu_arm = find_armature(context, False)

        if props.map_mode == 'POSITION' and (mmd_arm is None or mhgu_arm is None):
            self.report({'ERROR'}, "按位置匹配需要场景中同时存在 MMD 骨架与 MHGU 骨架")
            return {'CANCELLED'}

        tot_r = tot_m = tot_del = tot_res = tot_kept = 0
        all_unmapped = []
        for obj in targets:
            r, m, unmapped, dele, resc, kept = rename_vertex_groups(
                obj, props, mhgu_arm, mmd_arm)
            tot_kept += kept
            tot_r += r
            tot_m += m
            tot_del += dele
            tot_res += resc
            all_unmapped.extend(unmapped)

        missing = []
        if mhgu_arm is not None:
            have = set(b.name for b in mhgu_arm.data.bones)
            for obj in targets:
                for vg in obj.vertex_groups:
                    if vg.name.startswith("b_") and vg.name not in have:
                        missing.append(vg.name)
        missing = sorted(set(missing))

        zero_b = partial_b = 0
        for obj in targets:
            bidx = {vg.index for vg in obj.vertex_groups if vg.name.startswith("b_")}
            for v in obj.data.vertices:
                s = sum(g.weight for g in v.groups if g.group in bidx)
                if s <= 1e-6:
                    zero_b += 1
                elif s < 0.99:
                    partial_b += 1

        msg = "已重命名 %d 个顶点组, 合并 %d 组" % (tot_r, tot_m)
        if tot_del:
            msg += ", 删除多余组 %d 个" % tot_del
        if tot_kept:
            msg += ", 保留组 %d 个" % tot_kept
        if tot_res:
            msg += " (其中 %d 个顶点已转移权重, 不会塌到原点)" % tot_res
        if tot_res:
            self.report({'WARNING'},
                        '有 %d 个顶点的未映射权重被并到一个兜底 b_ 组（与部位无关）：'
                        '头发/裙/外套请先合并到身体骨，或勾「保留未映射组」后再转换'
                        % tot_res)
        if props.keep_unmapped and props.delete_unmapped:
            self.report({'WARNING'},
                        '「保留未映射组」已勾选：「删除多余组」这次被忽略（两者互斥）')
        if mhgu_arm is None:
            self.report({'WARNING'},
                        '场景里没有 MHGU 骨架：只会改成 b_N 原始名（不补 .l/.r），'
                        '也不做缺骨校验；请先导入 body 或带目标骨架再执行')
        if zero_b:
            self.report({'WARNING'},
                        '有 %d 个顶点完全没有 b_ 权重（只剩未映射组）：导出会写成 '
                        'b=[0], w=[1.0] 全绑 0 号骨；请把这些组先合并到身体骨'
                        % zero_b)
        if partial_b:
            self.report({'WARNING'},
                        '有 %d 个顶点 b_ 权重不足 1.0（部分权重留在未映射组里）：'
                        '导出归一化会改变比例' % partial_b)
        if missing:
            msg += "; 目标骨架缺少 %d 个骨位: %s" % (
                len(missing), ", ".join(missing[:8]))
        if all_unmapped:
            msg += "; 未识别 %d 个: %s" % (
                len(all_unmapped), ", ".join(sorted(set(all_unmapped))[:6]))
        self.report({'INFO'} if not (missing or all_unmapped) else {'WARNING'}, msg)
        return {'FINISHED'}

class MT_OT_CenterModel(Operator):

    bl_idname = "mt_framework.center_model"
    bl_label = "模型居中"
    bl_description = "整体平移模型 (只改对象变换, 不改顶点), 便于与 MMD 等第三方模型对齐"
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(
        name="模式",
        items=[
            ('XY_GROUND', "X/Y 居中 + Z 贴地", "最常用: 水平居中, 最低点落到 Z=0"),
            ('CENTER', "包围盒正中", "包围盒中心移到世界原点"),
        ],
        default='XY_GROUND',
    )

    @classmethod
    def poll(cls, context):
        return any(o.type == 'MESH' for o in context.selected_objects)

    def execute(self, context):
        from .MTframework_MHGU import center_objects
        from . import compat
        objs = list(context.selected_objects)

        group = list(objs)
        for o in objs:
            for c in compat.iter_children(o):
                if c not in group:
                    group.append(c)
        off = center_objects(group, self.mode)
        self.report({'INFO'}, "已平移 (%.4f, %.4f, %.4f)" % (off.x, off.y, off.z))
        return {'FINISHED'}

class MT_PT_MMDPanel(Panel):

    bl_label = "MMD 转换"
    bl_idname = "MT_PT_MMDPanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "MTFramework"
    bl_parent_id = "MT_PT_MainPanel"

    def draw(self, context):
        layout = self.layout
        props = context.scene.MT_Framework_MMD_Props
        obj = context.active_object

        box = layout.box()
        row = box.row()
        row.label(text="顶点组改名", icon='GROUP_VERTEX')
        sel_meshes = [o for o in context.selected_objects if o.type == 'MESH']
        box.label(text="已选网格: %d 个" % len(sel_meshes),
                  icon='MESH_DATA' if sel_meshes else 'INFO')

        col = box.column(align=True)
        col.prop(props, "map_mode", text="")
        if props.map_mode == 'NAME':
            col.prop(props, "swap_lr")
            col.prop(props, "merge_fingers")
        else:
            col.prop(props, "merge_fingers")

        box.prop(props, "keep_chest", text="保留胸部顶点组（胸*/乳*）")
        box.prop(props, "keep_vgroups", text="额外保留")

        row = box.row(align=True)
        row.prop(props, "keep_unmapped", text="保留多余组")
        row.prop(props, "delete_unmapped", text="删除多余组")
        box.prop(props, "remove_empty")

        col = box.column(align=True)
        col.scale_y = 1.3
        col.operator("mt_framework.mmd_rename_vgroups",
                     text="执行改名", icon='ARMATURE_DATA')

        box = layout.box()
        box.label(text="模型居中", icon='OBJECT_ORIGIN')
        row = box.row(align=True)
        op = row.operator("mt_framework.center_model", text="X/Y 居中 + 贴地")
        op.mode = 'XY_GROUND'
        op = row.operator("mt_framework.center_model", text="包围盒正中")
        op.mode = 'CENTER'

classes = [
    MT_KeepItem,
    MT_UL_KeepGroups,
    MT_OT_MMDRefreshKeep,
    MT_OT_MMDKeepAll,
    MT_OT_MMDGridMarker,
    MTFrameworkMMDProps,
    MT_OT_MMDRenameVGroups,
    MT_OT_CenterModel,
    MT_PT_MMDPanel,
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.MT_Framework_MMD_Props = PointerProperty(type=MTFrameworkMMDProps)

def unregister():
    try:
        del bpy.types.Scene.MT_Framework_MMD_Props
    except Exception:
        pass
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
