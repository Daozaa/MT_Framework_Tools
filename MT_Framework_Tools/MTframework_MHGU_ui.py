import bpy
import os
import math
import struct
from bpy.props import (
    StringProperty, BoolProperty, IntProperty, FloatProperty,
    FloatVectorProperty, EnumProperty, CollectionProperty
)
from bpy.types import Operator, Panel

_BMT_XFS_B64 = "WEZTABAAAQAiAAAAAAAAAAMAAACEAQAADAAAAIwAAADkAAAA0p7IZgMAAAA8AQAABgEEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAARQEAAAaRBAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAE4BAAABAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABBTRNxAgAAAFcBAAADAAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABjAQAAAqAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAG+UfcgIAAABrAQAABQACAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAdgEAAAUAAgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAEluZm9UeXBlAG1RdWFsaXR5AEluZm9MaXN0AG1BdXRvRGVsZXRlAG1wQXJyYXkAbURpc3BGbGFnMABtRGlzcEZsYWcxAAAAAAEAAACpAgAAAQAAAAAAAAABAAAAAgAAAAEAAAADAAEAjQIAAAEAAAAAIAAAAAUAAgAQAAAAAQAAAAD8AQAAAP+BBQADABAAAAABAAAAAPwBAAAA/4EFAAQAEAAAAAEAAAAA/AEAAAD/gQUABQAQAAAAAQAAAAD8AQAAAP+BBQAGABAAAAABAAAAAPwBAAAA/4EFAAcAEAAAAAEAAAAA/AEAAAD/gQUACAAQAAAAAQAAAAD8AQAAAP+BBQAJABAAAAABAAAAAPwBAAAA/4EFAAoAEAAAAAEAAAAA/AEAAAD/gQUACwAQAAAAAQAAAAD8AQAAAP+BBQAMABAAAAABAAAAAPwBAAAA/4EFAA0AEAAAAAEAAAAA/AEAAAD/gQUADgAQAAAAAQAAAAD8AQAAAP+BBQAPABAAAAABAAAAAPwBAAAA/4EFABAAEAAAAAEAAAAA/AEAAAD/gQUAEQAQAAAAAQAAAAD8AQAAAP+BBQASABAAAAABAAAAAPwBAAAA/4EFABMAEAAAAAEAAAAA/AEAAAD/gQUAFAAQAAAAAQAAAAD8AQAAAP+BBQAVABAAAAABAAAAAPwBAAAA/4EFABYAEAAAAAEAAAAA/AEAAAD/gQUAFwAQAAAAAQAAAAD8AQAAAP+BBQAYABAAAAABAAAAAPwBAAAA/4EFABkAEAAAAAEAAAAA/AEAAAD/gQUAGgAQAAAAAQAAAAD8AQAAAP+BBQAbABAAAAABAAAAAPwBAAAA/4EFABwAEAAAAAEAAAAA/AEAAAD/gQUAHQAQAAAAAQAAAAD8AQAAAP+BBQAeABAAAAABAAAAAPwBAAAA/4EFAB8AEAAAAAEAAAAA/AEAAAD/gQUAIAAQAAAAAQAAAAD8AQAAAP+BBQAhABAAAAABAAAAAPwBAAAA/4E="

def parse_mesh_name(obj_name):
    sName = obj_name.split("_")
    if len(sName) < 8 or not obj_name.startswith("Mesh_"):
        return None
    try:
        def _after(part, sep):
            return part.split(sep)[1] if sep in part else "0"
        return {
            "index": sName[1],
            "fvf": sName[2],
            "lod": _after(sName[3], "x"),
            "matid_raw": int(_after(sName[4], ":")),
            "matid": str(int(_after(sName[4], ":")) // 16),
            "group": _after(sName[5], ":"),
            "display": _after(sName[6], ":"),
            "type": int(_after(sName[7], ":")),
        }
    except (IndexError, ValueError):
        return None

def update_mesh_filter(self, context):
    props = context.scene.MT_Framework_Props

    hidelod0 = props.hide_lod0
    hidedege = props.hide_degen

    for obj in bpy.data.objects:
        if obj.type != 'MESH' or not obj.name.startswith("Mesh_"):
            continue

        info = parse_mesh_name(obj.name)
        if info is None:
            continue

        hide_obj = False

        if hidelod0 and info["lod"] == "0":
            hide_obj = True

        if hidedege and info["type"] == 4128:
            hide_obj = True

        if props.filter_lod != "All" and info["lod"] != props.filter_lod:
            hide_obj = True

        if props.filter_mat != "All" and info["matid"] != props.filter_mat:
            hide_obj = True

        if props.filter_fvf != "All" and info["fvf"] != props.filter_fvf:
            hide_obj = True

        obj.hide_set(hide_obj)
        obj.hide_viewport = hide_obj

def update_lod_dropdown(self, context):
    update_mesh_filter(self, context)

def update_mat_dropdown(self, context):
    update_mesh_filter(self, context)

def update_fvf_dropdown(self, context):
    update_mesh_filter(self, context)

def collect_filter_values():
    lods, mats, fvfs = set(), set(), set()
    for obj in bpy.data.objects:
        if obj.type != 'MESH' or not obj.name.startswith("Mesh_"):
            continue
        info = parse_mesh_name(obj.name)
        if info is None:
            continue
        lods.add(info["lod"])
        mats.add(info["matid"])
        fvfs.add(info["fvf"])
    return lods, mats, fvfs

def _sorted_numeric(values):
    return sorted(values, key=lambda x: int(x) if x.lstrip('-').isdigit() else 0)

def lod_items_cb(self, context):
    lods, _, _ = collect_filter_values()
    items = [("All", "All", "显示所有 LOD")]
    for lod in _sorted_numeric(lods):
        items.append((lod, "LOD " + lod, "LOD 级别 " + lod))
    return items

def mat_items_cb(self, context):
    _, mats, _ = collect_filter_values()
    items = [("All", "All", "显示所有材质")]
    for mat in _sorted_numeric(mats):
        items.append((mat, "Mat " + mat, "材质 ID " + mat))
    return items

def fvf_items_cb(self, context):
    _, _, fvfs = collect_filter_values()
    items = [("All", "All", "显示所有 FVF")]
    for fvf in sorted(fvfs):
        items.append((fvf, fvf, "FVF 格式 " + fvf))
    return items

def refresh_filter_lists(self, context):
    props = context.scene.MT_Framework_Props
    lods, mats, fvfs = collect_filter_values()
    print("过滤列表: LOD={} MatID={} FVF={}".format(
        _sorted_numeric(lods), _sorted_numeric(mats), sorted(fvfs)))
    update_mesh_filter(self, context)

class MTFrameworkProperties(bpy.types.PropertyGroup):

    game_fix: EnumProperty(
        name="游戏修复",
        description="固定为 MHGU",
        items=[
            ('mhgu', 'MHGU (Switch)', 'Monster Hunter Generations Ultimate'),
            ('dmc4se', 'DMC4SE', 'Devil May Cry 4 Special Edition'),
            ('lp2', 'Lost Planet 2', 'Lost Planet 2'),
            ('dd', 'Dragon\'s Dogma', 'Dragon\'s Dogma'),
            ('re0', 'Re0 HD', 'Resident Evil 0 HD'),
            ('re2', 'Re2', 'Resident Evil 2'),
        ],
        default='mhgu',
    )

    auto_center: EnumProperty(
        name="导入后居中",
        description="导入完成后自动把模型平移, 便于与第三方模型 (例如 MMD) 对齐。"
                    "只改对象变换, 不改顶点数据; 导出时会自动换算回文件坐标",
        items=[
            ('XY_GROUND', "X/Y 居中 + Z 贴地",
             "水平居中, 最低点落到 Z=0 (推荐, 与 MMD 模型对齐最好)"),
            ('CENTER', "包围盒正中", "包围盒中心移到世界原点"),
            ('NONE', "不处理", "保持文件原始坐标"),
        ],
        default='XY_GROUND',
    )

    all_visible: BoolProperty(
        name="所有分件都可见 (0xEFFF)",
        description="导出时把每个网格的 meshtype 都改成 0xEFFF（可见主件）。"
                    "原版 arc 里通常只有 1 件是 0xEFFF，其余是影子/低模(0xE4C0)、"
                    "深度 pass(0x0020) 等，游戏里不绘制；打开这个开关就能把它们当分层用。",
        default=False,
    )

    sym_bone_names: BoolProperty(
        name="骨骼对称命名 (.l / .r)",
        description="把镜像成对的骨骼与顶点组改名为 <基础名>.l / .r, 方便使用 "
                    "Blender 的 X 轴镜像 / 对称化 / 镜像修改器。"
                    "导出时会自动换算回原本的骨序号, 不影响导出的 .mod",
        default=True,
    )

    hide_lod0: BoolProperty(
        name="隐藏 LOD 0",
        description="隐藏 LOD 0 级别的网格",
        default=False,
        update=update_mesh_filter,
    )

    hide_degen: BoolProperty(
        name="隐藏退化线",
        description="隐藏退化线模型 (Type 4128)",
        default=False,
        update=update_mesh_filter,
    )

    filter_lod: EnumProperty(
        name="LOD 级别",
        description="按 LOD 级别过滤网格",
        items=lod_items_cb,
        update=update_lod_dropdown,
    )

    filter_mat: EnumProperty(
        name="材质 ID",
        description="按材质 ID 过滤网格",
        items=mat_items_cb,
        update=update_mat_dropdown,
    )

    filter_fvf: EnumProperty(
        name="顶点格式",
        description="按 FVF 顶点格式过滤网格",
        items=fvf_items_cb,
        update=update_fvf_dropdown,
    )

    rename_mode: EnumProperty(
        name="替换模式",
        description="选择要替换的网格名称组件",
        items=[
            ('LOD', 'LOD', '替换 LOD 级别'),
            ('MAT', 'MAT', '替换材质 ID'),
            ('Group', 'Group', '替换组 ID'),
            ('Display', 'Display', '替换显示模式'),
        ],
        default='LOD',
    )

    rename_value: StringProperty(
        name="新值",
        description="输入新的值",
        default="0",
    )

    strict_phys: BoolProperty(
        name="严格物理校验（不一致就阻止导出）",
        description="物理骨与 CTC/模板不一致时：关=只警告并继续，开=阻止导出",
        default=False)

    weld_normals: BoolProperty(
        name="合并重合顶点法线",
        description="导出时把位置重合的顶点法线统一。\n"
                    "第三方模型常因 UV 分块而把一个顶点拆成多个, 每份法线不同,\n"
                    "进游戏就会在 UV 接缝处出现光影断层(常见十字/网格状)。\n"
                    "勾上可消除; 但也会抹平模型原本故意的硬边",
        default=False,
    )

    use_orig_vert: BoolProperty(
        name="使用原版顶点数据",
        description="测试用: 不改顶点数据, 只改面",
        default=False,
    )

    MT_TransplantKeepCtc: BoolProperty(
        name="保留物理 CTC", default=True,
        description="把 body 的物理链一起复制到目标部位")
    MT_TransplantOutDir: StringProperty(
        name="输出目录", subtype='DIR_PATH', default="",
        description="留空 = 输出到当前 arc 所在目录")

class MT_OT_ImportMod(Operator):
    bl_idname = "mt_framework.import_mod"
    bl_label = "导入 MOD"
    bl_description = "导入 .mod (MHGU / Switch)"

    filepath: StringProperty(subtype='FILE_PATH')

    filter_glob: StringProperty(default="*.mod;*.new;*.arc", options={'HIDDEN'})

    def execute(self, context):
        if not self.filepath:
            return {'CANCELLED'}

        from .MTframework_MHGU_phys import _apply
        if not _apply(self, context, self.filepath):
            return {'CANCELLED'}
        refresh_filter_lists(self, context)

        try:
            context.scene['MT_ArcXfs'] = ''
            context.scene['MT_MeshMats'] = ''
        except Exception:
            pass

        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

class MT_OT_ExportMod(Operator):
    bl_idname = "mt_framework.export_mod"
    bl_label = "导出 MOD"
    bl_description = "导出 .mod；若导入的是 .arc，会同时重建 .arc.new（可直接改名为 .arc 装机）"

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.mod;*.arc", options={'HIDDEN'})

    def execute(self, context):
        if not self.filepath:
            return {'CANCELLED'}

        from .MTframework_MHGU_phys import _export
        out = _export(self, context, self.filepath)
        if not out:
            return {'CANCELLED'}
        return {'FINISHED'}

    def invoke(self, context, event):
        if not self.filepath:
            arc = (context.scene.get('MT_ArcPath', '')
                   or context.scene.get('MT_ArcPathLast', '') or '')
            last = context.scene.get('MT_LastImportPath', '') or ''
            if arc and os.path.exists(arc):
                self.filepath = arc
            elif last:
                self.filepath = os.path.basename(last)
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

_clipboard_vgroups = []

def is_gu_mesh(obj):
    return any(p.startswith('Type:') for p in obj.name.split('_'))

def pick_replace_pair(context):
    sel = [o for o in context.selected_objects if o.type == 'MESH']
    act = context.active_object
    if act is not None and act.type == 'MESH' and act not in sel:
        sel = sel + [act]
    if len(sel) < 2:
        return (sel[0] if sel else None), None

    gu = [o for o in sel if is_gu_mesh(o)]
    mine = [o for o in sel if not is_gu_mesh(o)]
    if len(gu) == 1 and len(mine) == 1:
        return mine[0], gu[0]

    new = act if (act is not None and act in sel) else sel[0]
    rest = [o for o in sel if o is not new]
    return new, (rest[0] if rest else None)

class MT_OT_ReplaceMainBody(Operator):

    bl_idname = "mt_framework.replace_main_body"
    bl_label = "替换名称"
    bl_description = ("选中两个网格: 你的模型 + 要被替换的目标。\n"
                      "把目标的 对象名 / 数据块名 换到你的模型上,\n"
                      "并接上目标原本的骨架绑定。")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return len([o for o in context.selected_objects
                    if o.type == 'MESH']) >= 2

    def execute(self, context):
        new, target = pick_replace_pair(context)
        if new is None or target is None or target is new:
            self.report({'ERROR'}, "请同时选中两个网格: 你的模型 + 要被替换的目标")
            return {'CANCELLED'}

        info = []
        base = target.name
        old_name = new.name
        if old_name != base:
            target.name = base + "_OLD"
            new.name = base
            info.append("%s -> %s" % (old_name, base))
            if target.data is not None and new.data is not None:
                dbase = target.data.name
                target.data.name = dbase + "_OLD"
                new.data.name = dbase

        bpy.ops.object.select_all(action='DESELECT')
        new.select_set(True)
        context.view_layer.objects.active = new
        self.report({'INFO'}, "已替换名称: " + ("; ".join(info) if info else "名称相同, 未改动"))
        return {'FINISHED'}

class MT_OT_CopyVGroups(Operator):
    bl_idname = "mt_framework.copy_vgroups"
    bl_label = "复制顶点组"
    bl_description = "复制当前选中模型的顶点组名称"

    def execute(self, context):
        global _clipboard_vgroups
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "请先选中一个网格模型")
            return {'CANCELLED'}
        _clipboard_vgroups = [vg.name for vg in obj.vertex_groups]
        self.report({'INFO'}, f"已复制 {len(_clipboard_vgroups)} 个顶点组: {', '.join(_clipboard_vgroups[:5])}{'...' if len(_clipboard_vgroups)>5 else ''}")
        return {'FINISHED'}

class MT_OT_PasteVGroups(Operator):
    bl_idname = "mt_framework.paste_vgroups"
    bl_label = "粘贴顶点组"
    bl_description = "将剪贴板中的顶点组名称添加到选中的网格模型"

    def execute(self, context):
        global _clipboard_vgroups
        if not _clipboard_vgroups:
            self.report({'ERROR'}, "剪贴板为空，请先复制顶点组")
            return {'CANCELLED'}
        targets = [o for o in context.selected_objects if o.type == 'MESH']
        if not targets:
            self.report({'ERROR'}, "请先选中要粘贴的网格模型")
            return {'CANCELLED'}
        for obj in targets:
            existing = {vg.name for vg in obj.vertex_groups}
            for name in _clipboard_vgroups:
                if name not in existing:
                    obj.vertex_groups.new(name=name)
        self.report({'INFO'}, f"已粘贴到 {len(targets)} 个模型")
        return {'FINISHED'}

class MT_OT_ImportSBC(Operator):
    bl_idname = "mt_framework.import_sbc"
    bl_label = "导入 SBC"
    bl_description = "导入 REHD Stage Base Collision (.sbc) 文件"

    filepath: StringProperty(subtype='FILE_PATH')

    def execute(self, context):
        if not self.filepath:
            return {'CANCELLED'}

        from .MTframework_MHGU_import import import_sbc_file
        import_sbc_file(self.filepath)

        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

class MT_OT_ImportADR(Operator):
    bl_idname = "mt_framework.import_adr"
    bl_label = "导入 ADR"
    bl_description = "导入 REHD door data (.adr) 文件"

    filepath: StringProperty(subtype='FILE_PATH')

    def execute(self, context):
        if not self.filepath:
            return {'CANCELLED'}

        from .MTframework_MHGU_import import import_adr_file
        import_adr_file(self.filepath)

        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

class MT_OT_ImportEMS(Operator):
    bl_idname = "mt_framework.import_ems"
    bl_label = "导入 EMS"
    bl_description = "导入 REHD enemy spawn (.ems) 文件"

    filepath: StringProperty(subtype='FILE_PATH')

    def execute(self, context):
        if not self.filepath:
            return {'CANCELLED'}

        from .MTframework_MHGU_import import import_ems_file
        import_ems_file(self.filepath)

        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

class MT_OT_RenameSelected(Operator):
    bl_idname = "mt_framework.rename_selected"
    bl_label = "重命名选中"
    bl_description = "批量修改选中网格的名称组件 (LOD/MatID/Group/DisplayMode)"

    def execute(self, context):
        props = context.scene.MT_Framework_Props
        new_value = props.rename_value

        if not new_value:
            self.report({'WARNING'}, "请输入新值")
            return {'CANCELLED'}

        count = 0
        for obj in context.selected_objects:
            if obj.name.startswith("Mesh_") and obj.type == 'MESH':
                sName = obj.name.split("_")
                if len(sName) < 8:
                    continue

                try:

                    mshHdr_lod = int(sName[3].split("x")[1]) if "x" in sName[3] else 0
                    mshHdr_matid = int(sName[4].split(":")[1]) if ":" in sName[4] else 0
                    mshHdr_grp = int(sName[5].split(":")[1]) if ":" in sName[5] else 0
                    mshHdr_mde = int(sName[6].split(":")[1]) if ":" in sName[6] else 0
                    mshHdr_type = int(sName[7].split(":")[1]) if ":" in sName[7] else 0

                    new_val = int(new_value)
                    if props.rename_mode == 'LOD':
                        mshHdr_lod = new_val
                    elif props.rename_mode == 'MAT':
                        mshHdr_matid = new_val
                    elif props.rename_mode == 'Group':
                        mshHdr_grp = new_val
                    elif props.rename_mode == 'Display':
                        mshHdr_mde = new_val

                    obj.name = "Mesh_{}_{}_LODx{}_MatID:{}_Group:{}_DisplayMode:{}_Type:{}".format(
                        sName[1], sName[2],
                        mshHdr_lod, mshHdr_matid,
                        mshHdr_grp, mshHdr_mde, mshHdr_type
                    )
                    count += 1

                except (IndexError, ValueError):
                    continue

        self.report({'INFO'}, "已重命名 {} 个网格".format(count))

        refresh_filter_lists(self, context)

        return {'FINISHED'}

class MT_OT_RefreshFilterLists(Operator):
    bl_idname = "mt_framework.refresh_filters"
    bl_label = "刷新过滤列表"
    bl_description = "从场景中所有 Mesh_* 对象重新收集过滤选项"

    def execute(self, context):
        refresh_filter_lists(self, context)
        self.report({'INFO'}, "过滤列表已刷新")
        return {'FINISHED'}

class MT_OT_Diagnostic(Operator):
    bl_idname = "mt_framework.diagnostic"
    bl_label = "诊断"
    bl_description = "打印当前场景的模型/骨骼/顶点信息到控制台 (Window > Toggle System Console)"

    def execute(self, context):
        print("\n" + "=" * 60)
        print("MT Framework MHGU - 诊断信息")
        print("=" * 60)

        mesh_objs = [obj for obj in bpy.data.objects if obj.type == 'MESH' and obj.name.startswith('Mesh_')]
        print(f"\n网格对象数: {len(mesh_objs)}")
        for obj in mesh_objs:
            mesh = obj.data
            print(f"  {obj.name}:")
            print(f"    顶点: {len(mesh.vertices)}, 面: {len(mesh.polygons)}, UV层: {len(mesh.uv_layers)}")

            parts = obj.name.split('_')
            if len(parts) >= 3:
                print(f"    FVF: {parts[2]}")

            if obj.vertex_groups:
                print(f"    顶点组: {[vg.name for vg in obj.vertex_groups]}")

            custom = {k: v for k, v in mesh.items() if not k.startswith('_')}
            if custom:
                print(f"    属性: {custom}")

        armatures = [obj for obj in bpy.data.objects if obj.type == 'ARMATURE']
        print(f"\n骨架 (Armature) 数量: {len(armatures)}")
        for arm in armatures:
            bones = arm.data.bones
            print(f"  {arm.name}: {len(bones)} 根骨骼")
            roots = [b for b in bones if b.parent is None]
            print(f"    根骨骼: {[b.name for b in roots]}")
            if bones:
                heads = [b.head_local for b in bones]
                print("    骨骼范围 X[{:.4f},{:.4f}] Y[{:.4f},{:.4f}] Z[{:.4f},{:.4f}]".format(
                    min(h.x for h in heads), max(h.x for h in heads),
                    min(h.y for h in heads), max(h.y for h in heads),
                    min(h.z for h in heads), max(h.z for h in heads)))
            for b in bones[:12]:
                print("      {:8s} head=({:.4f},{:.4f},{:.4f}) len={:.4f} parent={}".format(
                    b.name, b.head_local.x, b.head_local.y, b.head_local.z,
                    b.length, b.parent.name if b.parent else None))
            if len(bones) > 12:
                print(f"      ... 还有 {len(bones) - 12} 根")

        print(f"\n蒙皮检测:")
        for obj in mesh_objs:
            mods = [m for m in obj.modifiers if m.type == 'ARMATURE']
            parent = obj.parent.name if obj.parent else None
            print("  {}: 顶点组={} 骨架修改器={} 父级={}".format(
                obj.name, len(obj.vertex_groups),
                mods[0].object.name if mods and mods[0].object else "无", parent))
            unweighted = sum(1 for v in obj.data.vertices if not v.groups)
            if unweighted:
                print(f"    ⚠ {unweighted}/{len(obj.data.vertices)} 个顶点没有任何权重")

        print(f"\n顶点坐标范围检测:")
        for obj in mesh_objs:
            mesh = obj.data
            if len(mesh.vertices) == 0:
                continue
            xs = [v.co.x for v in mesh.vertices]
            ys = [v.co.y for v in mesh.vertices]
            zs = [v.co.z for v in mesh.vertices]
            print(f"  {obj.name}:")
            print(f"    X: [{min(xs):.4f}, {max(xs):.4f}] 跨度={max(xs)-min(xs):.4f}")
            print(f"    Y: [{min(ys):.4f}, {max(ys):.4f}] 跨度={max(ys)-min(ys):.4f}")
            print(f"    Z: [{min(zs):.4f}, {max(zs):.4f}] 跨度={max(zs)-min(zs):.4f}")
            print(f"    对象缩放: {obj.scale}")
            extreme = [v for v in mesh.vertices if any(abs(c) > 1000 for c in v.co)]
            if extreme:
                print(f"    ⚠ {len(extreme)} 个顶点坐标绝对值 > 1000")
            if max(obj.scale) > 10:
                print(f"    ⚠ 对象缩放 > 10, 模型可能过大")

        print(f"\n面异常检测:")
        for obj in mesh_objs:
            mesh = obj.data
            for poly in mesh.polygons:
                for v in poly.vertices:
                    if v >= len(mesh.vertices):
                        print(f"  {obj.name}: 面引用了不存在的顶点 {v}")
                        break

        print(f"\nUV 检测:")
        for obj in mesh_objs:
            mesh = obj.data
            for uv_layer in mesh.uv_layers:
                invalid_uvs = 0
                for uv in uv_layer.data:
                    u, v = uv.uv
                    if u < -10 or u > 10 or v < -10 or v > 10 or (u == 0 and v == 0):
                        invalid_uvs += 1
                if invalid_uvs > len(mesh.loops) * 0.5:
                    print(f"  {obj.name}: UV层 '{uv_layer.name}' 大量异常 ({invalid_uvs}/{len(mesh.loops)})")

        print("\n物理链自检:")
        try:
            from .MTframework_MHGU_phys import recalled_arc
            from .MTframework_MHGU_ctc import check_topology
            _arc_path, _ctc = recalled_arc(context)
            _tpl = context.scene.get('MT_LastImportPath', '') or ''
            if not _ctc:
                print("  没有记住的 CTC（没导入过带物理的 arc，或已清空）")
            elif not _tpl or not os.path.exists(_tpl):
                print("  有 CTC 但找不到模板 .mod，无法比对")
            else:
                with open(_tpl, 'rb') as _f:
                    _mb = _f.read()
                _probs = check_topology(_mb, _ctc)
                if _probs:
                    print("  ⚠ CTC 与骨骼链不一致（导出时会自动重建）：")
                    for _p in _probs[:6]:
                        print("    - " + _p)
                else:
                    print("  正常：CTC 节点与骨骼链一致")
        except Exception as _e:
            print("  物理自检出错：%s" % _e)

        print("\n" + "=" * 60)
        print("诊断完成，请复制上方信息")
        print("=" * 60 + "\n")

        self.report({'INFO'}, "诊断信息已打印到控制台 (Window > Toggle System Console)")
        return {'FINISHED'}

class MT_PT_MainPanel(Panel):
    bl_label = "MT_Framework_Tools"
    bl_idname = "MT_PT_MainPanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "MTFramework"

    def draw(self, context):
        layout = self.layout
        scn = context.scene
        props = getattr(scn, 'MT_Framework_Props', None)
        ops = bpy.ops.mt_framework

        try:
            import MT_Framework_Tools as _M
            _ver = '.'.join(str(x) for x in _M.bl_info['version'])
        except Exception:
            _ver = '?'

        head = layout.box()
        hc = head.column(align=True)
        hc.label(text="MT Framework Tools   v%s" % _ver, icon='TOOL_SETTINGS')
        _arc = (scn.get('MT_ArcPath', '') or '')
        _nmesh = len([o for o in scn.objects if o.type == 'MESH'])
        if _arc:
            hc.label(text="%s   ·   %d 个网格" % (os.path.basename(_arc), _nmesh), icon='FILE')
        elif _nmesh:
            hc.label(text="%d 个网格（未绑定 arc，导出只有 .mod）" % _nmesh, icon='FILE')
        else:
            hc.label(text="未导入模型 —— 先点「导入模型」", icon='INFO')

        def section(key, label, icon, default=False):
            val = bool(getattr(scn, key, default))
            row = layout.row(align=True)
            row.scale_y = 1.3
            try:
                row.prop(scn, key, text=label,
                         icon=('TRIA_DOWN' if val else 'TRIA_RIGHT'), emboss=False)
            except Exception:
                row.label(text=label, icon=icon)
            return val

        def sub(box, text, icon='DOT'):
            box.label(text=text, icon=icon)

        if section('MT_UiIo', 'MOD 模型', 'MESH_DATA', default=True):
            box = layout.box()
            col = box.column(align=True)
            row = col.row(align=True)
            row.scale_y = 1.5
            row.operator("mt_framework.import_mod", text="导入模型", icon='IMPORT')
            row.operator("mt_framework.export_mod", text="导出模型", icon='EXPORT')
            row = col.row(align=True)
            if hasattr(ops, 'set_arc_container'):
                row.operator("mt_framework.set_arc_container",
                             text="选择 arc 容器", icon='FILEBROWSER')
            if _arc:
                col.label(text="导出写回: %s" % os.path.basename(_arc), icon='FILE')
            else:
                col.label(text="要导出 .arc，先导入一个 .arc 当容器", icon='INFO')
            col.prop(scn, 'MT_SkipHidden', text='导出跳过视口隐藏的网格')
            col.label(text="隐藏的网格不导出；一个不剩也照常导出空模型", icon='INFO')

            if hasattr(ops, 'part_transplant') and hasattr(scn, 'MT_TransplantKeepCtc'):
                tb = col.box()
                tb.label(text="跨部位导出（当前工程 → 其他部位）", icon='ARMATURE_DATA')
                r = tb.row(align=True)
                r.prop(scn, 'MT_TransplantKeepCtc', text='保留 CTC')
                tb.prop(scn, 'MT_TransplantSet', text='目标套号（留空=同源）')
                tb.prop(scn, 'MT_TransplantGender', text='目标性别')
                tb.prop(scn, 'MT_TransplantOutDir', text='输出目录')
                r = tb.row(align=True)
                for _part, _lab in (('body', 'body'), ('arm', 'arm'),
                                    ('wst', 'wst'), ('leg', 'leg'),
                                    ('helm', 'helm')):
                    _op = r.operator('mt_framework.part_transplant', text=_lab)
                    _op.target_part = _part
                    _op.keep_ctc = scn.MT_TransplantKeepCtc
                    _op.target_set = scn.MT_TransplantSet
                    _op.target_gender = scn.MT_TransplantGender
                    _op.out_dir = scn.MT_TransplantOutDir

        if section('MT_UiTex', 'TEX 贴图', 'IMAGE_DATA', default=False):
            try:
                if not hasattr(ops, 'import_tex'):
                    box = layout.box()
                    box.label(text="贴图模块没注册上（控制台看 NOTE）", icon='ERROR')
                else:
                    box = layout.box()
                    col = box.column(align=True)
                    row = col.row(align=True)
                    row.scale_y = 1.3
                    row.operator("mt_framework.import_tex", text="导入贴图", icon='IMAGE_DATA')
                    row.operator("mt_framework.export_tex", text="导出贴图", icon='FILE_IMAGE')
                    col.separator()
                    sub(box, "导出设置")
                    col = box.column(align=True)
                    if hasattr(scn, 'MT_TexImage'):
                        col.template_ID(scn, "MT_TexImage")
                    row = col.row(align=True)
                    if hasattr(scn, 'MT_TexSize'):
                        row.prop(scn, "MT_TexSize", text="尺寸")
                    if hasattr(scn, 'MT_TexFormat'):
                        row.prop(scn, "MT_TexFormat", text="格式")
                    if hasattr(scn, 'MT_TexMips'):
                        col.prop(scn, "MT_TexMips", text="生成完整 mip 链")
                    box.label(text="有模板时沿用原图的尺寸 / 格式 / mip，只换像素", icon='INFO')
            except Exception as _e:
                box = layout.box()
                box.label(text="贴图面板出错: %s: %s" % (type(_e).__name__, _e), icon='ERROR')

        if section('MT_UiPhys', 'CTC 物理骨骼', 'BONE_DATA', default=False):
            try:
                if hasattr(ops, 'phys_matrix_auto'):
                    box = layout.box()
                    col = box.column(align=True)
                    row = col.row(align=True)
                    row.scale_y = 1.3
                    row.operator("mt_framework.phys_matrix_auto",
                                 text="物理矩阵自适应（改骨位后必点）", icon='BONE_DATA')

                    if hasattr(ops, 'phys_params_read'):
                        pb = layout.box()
                        sub(pb, "CTC 物理参数", 'PHYSICS')
                        cc = pb.column(align=True)
                        cc.operator("mt_framework.phys_params_read",
                                    text="读取当前参数", icon='FILE_REFRESH')
                        row = cc.row(align=True)
                        if hasattr(scn, 'MT_PhysPreset'):
                            row.prop(scn, "MT_PhysPreset", text="")
                        if hasattr(ops, 'phys_preset_apply'):
                            row.operator("mt_framework.phys_preset_apply",
                                         text="套用（全部）", icon='PRESET')
                        if hasattr(ops, 'phys_preset_apply_selected'):
                            cc.operator("mt_framework.phys_preset_apply_selected",
                                        text="套用预设（选中骨）", icon='BONE_DATA')
                        if hasattr(scn, 'MT_PhysAutoInit'):
                            cc.prop(scn, "MT_PhysAutoInit",
                                    text="新链自动初值（按部位/链长）")
                        if hasattr(ops, 'phys_lock_selected'):
                            cc.operator("mt_framework.phys_lock_selected",
                                        text="锁死选中节点（只改角度，不动组）", icon='LOCKED')
                        for _attr, _lab in (("MT_PhysGravity", "重力 Y"),
                                            ("MT_PhysDamping", "阻尼"),
                                            ("MT_PhysSpring", "弹簧"),
                                            ("MT_PhysWind", "风"),
                                            ("MT_PhysTrans", "平移力"),
                                            ("MT_PhysLimit", "限力"),
                                            ("MT_PhysReflect", "反射"),
                                            ("MT_PhysAngle", "角度上限"),
                                            ("MT_PhysMass", "质量"),
                                            ("MT_PhysElastic", "弹性")):
                            if hasattr(scn, _attr):
                                cc.prop(scn, _attr, text=_lab)
                        cc.operator("mt_framework.phys_params_write",
                                    text="应用参数（全部）", icon='CHECKMARK')
                        if hasattr(ops, 'phys_params_write_selected'):
                            cc.operator("mt_framework.phys_params_write_selected",
                                        text="应用参数（选中骨）", icon='BONE_DATA')
                        if hasattr(ops, 'phys_ctc_fix'):
                            cc.separator()
                            cc.operator("mt_framework.phys_ctc_fix",
                                        text="修复 CTC 头（重力缩放）", icon='CHECKMARK')

                if hasattr(ops, 'phys_custom_register'):
                    xb = layout.box()
                    sub(xb, "CTC 自定义物理骨", 'OUTLINER_OB_ARMATURE')
                    xc = xb.column(align=True)
                    xc.operator("mt_framework.phys_custom_register",
                                text="登记自定义物理骨", icon='BONE_DATA')
                    if hasattr(ops, 'phys_rebuild_template'):
                        xc.operator("mt_framework.phys_rebuild_template",
                                    text="重建物理模板（按骨架对齐）", icon='FILE_REFRESH')
                    if hasattr(ops, 'phys_complete_chains'):
                        xc.operator("mt_framework.phys_complete_chains",
                                    text="补全单节点物理链", icon='BONE_DATA')
                    if hasattr(ops, 'phys_rebuild_ctc'):
                        xc.operator("mt_framework.phys_rebuild_ctc",
                                    text="重建 CTC（按现有物理骨）", icon='FILE_REFRESH')
                    try:
                        import base64 as _b64
                        _ct = _b64.b64decode(scn.get('MT_ArcCtc', '') or '')
                        if _ct[:4] == b'CTC\x00' and len(_ct) >= 0x18:
                            _ng, _nc = struct.unpack_from('<II', _ct, 0x10)
                            xb.label(text="当前 CTC：%d 组 / %d 节点" % (_ng, _nc),
                                     icon='CHECKMARK')
                        else:
                            xb.label(text="当前 CTC：无（点上面的「重建 CTC」或重新登记）",
                                     icon='ERROR')
                    except Exception:
                        pass

                    xb = layout.box()
                    sub(xb, "CTC 解算迭代（长头发 / 弯发束）", 'MOD_PHYSICS')
                    xb.prop(scn, 'MT_PhysIter', text="迭代次数")

                    xb = layout.box()
                    sub(xb, "CTC 骨段碰撞（ShapeObject=2）", 'MOD_PHYSICS')
                    xb.prop(scn, 'MT_PhysSegment', text="链节用骨段碰撞（链尾仍是点）")
            except Exception as _e:
                box = layout.box()
                box.label(text="CTC 面板出错: %s: %s" % (type(_e).__name__, _e), icon='ERROR')

        if section('MT_UiCcl', 'CCL 碰撞胶囊', 'MOD_PHYSICS', default=False):
            try:

                xb = layout.box()
                sub(xb, "CCL 碰撞胶囊（头发 ↔ 身体避让）", 'MOD_PHYSICS')
                xb.prop(scn, 'MT_CclEnable',
                        text="导出时写入身体胶囊（11 个，自动开 CTC 碰撞位）")
                try:
                    from .MTframework_MHGU_ccl import parse_ccl as _parse_ccl, find_ccl as _find_ccl
                    _ap = scn.get('MT_ArcPath', '') or ''
                    _nc = _ccl_arc_count(_ap, _parse_ccl, _find_ccl)
                    if _nc > 0:
                        xb.label(text="当前 arc 已有 CCL：%d 个胶囊" % _nc, icon='CHECKMARK')
                    elif _nc == 0:
                        xb.label(text="当前 arc 没有 CCL 条目", icon='INFO')
                except Exception as _e:
                    _ccl_note('面板检查 arc CCL 失败: %r' % (_e,))
                    xb.label(text="arc CCL 检查失败：%s" % type(_e).__name__, icon='ERROR')

                _caps_all = _ccl_caps(scn)
                _n_custom = len(_caps_all)
                _ccl_ensure_handler(scn)
                row = xb.row(align=True)
                row.prop(scn, 'MT_CclIndex', text='#')
                row.prop(scn, 'MT_CclBoneA', text='骨A')
                row.prop(scn, 'MT_CclBoneB', text='骨B')
                xb.prop(scn, 'MT_CclRadius', text='半径', slider=True)
                xb.prop(scn, 'MT_CclStart', text='起点偏移')
                xb.prop(scn, 'MT_CclEnd', text='终点偏移')
                if _caps_all:
                    _ci = max(0, min(_n_custom - 1, int(getattr(scn, 'MT_CclIndex', 0) or 0)))
                    _sum = _ccl_summary(_caps_all[_ci], _ci)
                    if bool(getattr(scn, 'MT_CclNewPending', False)):
                        _sum += ' | 新骨待新增'
                    xb.label(text=_sum, icon='CHECKMARK')
                else:
                    xb.label(text='还没有自定义胶囊', icon='INFO')

                row = xb.row(align=True)
                _op = row.operator('mt_framework.ccl_capsule_step', text='◀ 上一条', icon='TRIA_LEFT')
                _op.step = -1
                _op = row.operator('mt_framework.ccl_capsule_step', text='下一条 ▶', icon='TRIA_RIGHT')
                _op.step = 1
                row = xb.row(align=True)
                row.operator('mt_framework.ccl_capsule_load', text='读取该项', icon='IMPORT')
                row.operator('mt_framework.ccl_capsule_read_bone', text='读取选中骨的胶囊', icon='BONE_DATA')
                row = xb.row(align=True)
                row.operator('mt_framework.ccl_capsule_store', text='应用修改', icon='CHECKMARK')
                row.operator('mt_framework.ccl_capsule_pick', text='A/B 取选中骨', icon='POSE_HLT')
                row.operator('mt_framework.ccl_capsule_import', text='读 arc 的 CCL', icon='FILE_REFRESH')
                row.operator('mt_framework.ccl_capsule_check', text='检查', icon='CHECKMARK')

                row = xb.row(align=True)
                row.operator('mt_framework.ccl_capsule_add', text='新增', icon='ADD')
                row.operator('mt_framework.ccl_capsule_del', text='删除', icon='REMOVE')
                row.operator('mt_framework.ccl_capsule_clear', text='清空', icon='X')
                row = xb.row(align=True)
                row.operator('mt_framework.ccl_capsule_zero', text='偏移归零', icon='LOOP_BACK')
                row.operator('mt_framework.ccl_capsule_swap', text='交换起终点', icon='ARROW_LEFTRIGHT')

                row = xb.row(align=True)
                row.operator('mt_framework.ccl_preview', text='生成胶囊示意', icon='SPHERE')
                row.operator('mt_framework.ccl_preview_clear', text='清除示意', icon='TRASH')
                row = xb.row(align=True)
                row.scale_y = 1.25
                row.operator('mt_framework.ccl_drag_sync', text='拖动同步（端点手柄）', icon='HAND')
                xb.prop(scn, 'MT_CclAutoSync', text='拖动实时同步（后台处理器）')
                xb.prop(scn, 'MT_CclAutoPreview', text='改动后自动更新示意')
                xb.prop(scn, 'MT_CclBodyPick', text='可选胶囊本体')
                xb.label(text=_ccl_diag_text(), icon='INFO')
                if _CCL_CHECK_TEXT:
                    xb.label(text=_CCL_CHECK_TEXT[:120], icon='CHECKMARK')
                if _CCL_STAT.get('err'):
                    xb.label(text='上次错误: %s' % str(_CCL_STAT['err'])[:90], icon='ERROR')

            except Exception as _e:
                box = layout.box()
                box.label(text="碰撞胶囊面板出错: %s: %s" % (type(_e).__name__, _e), icon='ERROR')

        if section('MT_UiHelm', 'XFS 头部显示', 'MESH_CIRCLE', default=False):
            try:
                box = layout.box()
                sub(box, "XFS 显示标志（disp0 / disp1）")
                col = box.column(align=True)
                col.prop(scn, "MT_HelmPreset", text="预设")
                col.operator("mt_framework.helm_disp_preset",
                             text="套用预设", icon='CHECKMARK')
                col.separator()
                row = col.row(align=True)
                row.prop(scn, "MT_HelmDisp0", text="disp0")
                row.prop(scn, "MT_HelmDisp1", text="disp1")
                row = col.row(align=True)
                row.operator("mt_framework.helm_disp_read", text="读取", icon='FILE_REFRESH')
                row.operator("mt_framework.helm_disp_apply", text="应用", icon='CHECKMARK')
                _ap_low = (scn.get('MT_ArcPath', '') or '').replace('/', '\\').lower()
                if 'body' in _ap_low:
                    col.label(text="body 源：套用预设先记为待写入，跨移植到 helm 时生效",
                              icon='INFO')
                try:
                    from .MTframework_MHGU_helmd import get_modified_xfs as _gx
                    if _gx(scn):
                        _is_helm = ('helm' in _ap_low or 'hair' in _ap_low)
                        col.label(text=("已修改 XFS：导出时写回当前 arc" if _is_helm else
                                        "已设待写入 XFS：跨移植到 helm 时带上"),
                                  icon='CHECKMARK')
                except Exception:
                    pass

                col = box.column(align=True)
                col.separator()
                col.label(text="随从猫藏头（otomo h.arc / b.arc）", icon='BONE_DATA')
                r2 = col.row(align=True)
                r2.operator("mt_framework.cat_hide_head", text="猫·藏头")
                r2.operator("mt_framework.cat_hide_head2", text="猫·藏头+耳")
                r2.operator("mt_framework.cat_show_head", text="猫·不藏")
            except Exception as _e:
                box = layout.box()
                box.label(text="XFS 面板出错: %s: %s" % (type(_e).__name__, _e), icon='ERROR')

        if section('MT_UiVtx', 'VWG 顶点组 / 名称', 'GROUP_BONE', default=True):
            try:
                box = layout.box()
                col = box.column(align=True)
                row = col.row(align=True)
                row.scale_y = 1.2
                row.operator("mt_framework.copy_vgroups", text="复制顶点组", icon='COPYDOWN')
                row.operator("mt_framework.paste_vgroups", text="粘贴顶点组", icon='PASTEDOWN')
                col.separator()
                col.operator("mt_framework.replace_main_body",
                             text="替换名称", icon='AUTOMERGE_ON')
                col.separator()
                col.operator("mt_framework.weights_normalize",
                             text="权重归一化（删非骨骼组）", icon='NORMALIZE_FCURVES')
            except Exception as _e:
                box = layout.box()
                box.label(text="顶点组面板出错: %s: %s" % (type(_e).__name__, _e), icon='ERROR')

        if section('MT_UiSet', '导入设置', 'SETTINGS', default=False):
            box = layout.box()
            if props is None:
                box.label(text="属性组没注册上（控制台看 NOTE）", icon='ERROR')
            else:
                col = box.column(align=True)
                col.prop(props, "sym_bone_names")
                col.prop(props, "auto_center", text="导入后居中")
                col.prop(props, "all_visible", text="所有分件都当可见件 (分层用)")
                col.prop(props, "use_orig_vert", text="使用原版顶点")
                col.prop(props, "weld_normals")
                col.prop(props, "strict_phys", text="严格物理校验（不一致就阻止导出）")
                box.label(text="改完要重新导入模型才生效", icon='INFO')

        tl = layout.box()
        row = tl.row(align=True)
        if hasattr(ops, 'diagnostic'):
            row.operator("mt_framework.diagnostic", text="诊断", icon='CONSOLE')
        if hasattr(ops, 'refresh_filters'):
            row.operator("mt_framework.refresh_filters", text="刷新过滤", icon='FILE_REFRESH')

UI_SECTIONS = (
    ('MT_UiIo', "MOD 模型", True),
    ('MT_UiTex', "TEX 贴图", False),
    ('MT_UiPhys', "CTC 物理骨骼", False),
    ('MT_UiCcl', "CCL 碰撞胶囊", False),
    ('MT_UiHelm', "XFS 头部显示", False),
    ('MT_UiVtx', "VWG 顶点组 / 名称", True),
    ('MT_UiSet', "导入设置", False),
)

class MT_OT_PartTransplant(Operator):
    bl_idname = "mt_framework.part_transplant"
    bl_label = "跨部位导出（当前工程 → 目标部位）"
    bl_description = ("导出当前工程的模型，替换容器 arc 里的 .mod，"
                      "并改名到目标部位（arm/wst/leg/helm）；"
                      "TEX 条目与 mrl 贴图路径同步改名")

    target_part: EnumProperty(
        name="目标部位",
        items=[('body', 'body（身体）', ''), ('arm', 'arm（手）', ''),
               ('wst', 'wst（腰）', ''), ('leg', 'leg（腿）', ''),
               ('helm', 'helm（头）', '')],
        default='arm')
    keep_ctc: BoolProperty(name="保留物理 CTC", default=True)
    target_set: StringProperty(
        name="目标套号", default="",
        description="3 位套号（如 001/671）；留空 = 沿用源 arc 的套号")
    target_gender: EnumProperty(
        name="目标性别", default='same',
        description="same = 跟随源 arc；f/m = 强制改成女/男资源名（可跨性别移植）",
        items=[('same', '跟随源', ''), ('f', '女 f', ''), ('m', '男 m', '')])
    out_dir: StringProperty(name="输出目录", subtype='DIR_PATH', default="")

    def execute(self, context):
        import base64
        import re
        import tempfile
        import zlib
        from .MTframework_MHGU_phys import (
            arc_entries, arc_build, find_entry, recalled_arc, _export,
            MOD_MAGIC, CTC_MAGIC, CTC_HASH)
        MRL_MAGIC = b'MRL\x00'

        sc = context.scene
        arc_path = (sc.get('MT_ArcPath', '') or
                    sc.get('MT_ArcPathLast', '') or '')
        if not arc_path or not os.path.exists(arc_path):
            self.report({'ERROR'},
                        '没有 arc 容器：请先「导入模型」时选 .arc，'
                        '或到模型区点「选择 arc 容器」选原版 body.arc')
            return {'CANCELLED'}

        tmpdir = tempfile.mkdtemp(prefix='mt_transplant_')
        tmp_mod = os.path.join(tmpdir, 'export.mod')

        prev_sel = [o for o in context.selected_objects]
        prev_active = context.view_layer.objects.active

        sel_meshes = [o for o in context.selected_objects
                      if o.type == 'MESH' and len(o.data.vertices) > 0
                      and not o.hide_get()]
        meshes = sel_meshes or [o for o in context.view_layer.objects
                                if o.type == 'MESH' and len(o.data.vertices) > 0
                                and not o.hide_get()]
        print('[MT] 跨部位导出：%d 个网格（%s）' % (
            len(meshes), '选中' if sel_meshes else '全部可见'))
        try:
            bpy.ops.object.select_all(action='DESELECT')
            for o in meshes:
                try:
                    o.select_set(True)
                except Exception:
                    pass
            if meshes:
                context.view_layer.objects.active = meshes[0]
            sc['MT_SkipArcBuild'] = True
            out_mod = _export(self, context, tmp_mod)
        except Exception as e:
            self.report({'ERROR'}, '导出当前工程失败：%s' % e)
            return {'CANCELLED'}
        finally:
            sc['MT_SkipArcBuild'] = False
            try:
                bpy.ops.object.select_all(action='DESELECT')
                for o in prev_sel:
                    try:
                        o.select_set(True)
                    except Exception:
                        pass
                context.view_layer.objects.active = prev_active
            except Exception:
                pass
        if not out_mod or not os.path.exists(out_mod):
            self.report({'ERROR'}, '导出当前工程失败（没有生成 .mod）')
            return {'CANCELLED'}
        try:
            with open(out_mod, 'rb') as f:
                new_mod = f.read()
        except Exception as e:
            self.report({'ERROR'}, '读取临时 .mod 失败：%s' % e)
            return {'CANCELLED'}
        if new_mod[:4] != MOD_MAGIC:
            self.report({'ERROR'}, '导出的不是 .mod（文件头不对）')
            return {'CANCELLED'}

        with open(arc_path, 'rb') as f:
            entries = arc_entries(f.read())
        mod_e = find_entry(entries, MOD_MAGIC)
        if mod_e is None:
            self.report({'ERROR'}, '容器 arc 里没有 .mod：%s' % arc_path)
            return {'CANCELLED'}
        src = mod_e['name'].rsplit('\\', 1)[-1]
        m = re.match(r'^([fm])_([a-z]+)(\d+)$', src)
        if not m:
            self.report({'ERROR'},
                        '认不出 .mod 条目名（应为 f_body001 / m_helm247 这种）：%s' % src)
            return {'CANCELLED'}
        src_gender, src_part, src_digits = m.group(1), m.group(2), m.group(3)
        digits = (self.target_set or '').strip() or src_digits
        if not digits.isdigit():
            self.report({'ERROR'}, '目标套号必须是数字：%s' % digits)
            return {'CANCELLED'}

        gender = src_gender if self.target_gender in ('', 'same') else self.target_gender
        tgt = '%s_%s%s' % (gender, self.target_part, digits)

        _plm = re.search(r'\\pl(\d+)\\', mod_e['name'])
        src_pl = ('pl' + _plm.group(1)) if _plm else None
        tgt_pl = 'pl' + digits

        def _rename_path(path):
            if src_pl and src_pl != tgt_pl:
                path = path.replace('\\%s\\' % src_pl, '\\%s\\' % tgt_pl)
            if gender != src_gender:

                for _p in ('\\mod\\', '\\com\\'):
                    path = path.replace(_p + src_gender + '\\', _p + gender + '\\')

                path = path.replace('\\common\\%s_' % src_gender,
                                    '\\common\\%s_' % gender)
            return path

        ctc = None
        try:
            _a, ctc = recalled_arc(context)
        except Exception:
            ctc = None
        if not ctc:
            c_e = find_entry(entries, CTC_MAGIC)
            if c_e is not None:
                ctc = c_e['body']

        def _rename(name, base):
            full = _rename_path(name)
            if base == src:
                return full[:-len(base)] + tgt
            if base.startswith(src + '_'):
                return full[:-len(base)] + tgt + base[len(src):]
            return full

        def _patch_mrl_tex(body):
            b = bytearray(body)
            try:
                cnt = struct.unpack_from('<I', b, 0x0C)[0]
            except Exception:
                cnt = 0
            ob, nb = src.encode(), tgt.encode()
            for i in range(min(cnt, 64)):
                off = 0x28 + i * 76
                if off + 64 > len(b):
                    break
                s = bytes(b[off:off + 64]).split(b'\x00', 1)[0]
                _skin_tag = b'\\common\\' + src_gender.encode() + b'_'
                if (ob in s or (src_pl and src_pl.encode() in s)
                        or (gender != src_gender and _skin_tag in s)):
                    ns = s.replace(ob, nb)
                    if src_pl and src_pl != tgt_pl:
                        ns = ns.replace(('\\%s\\' % src_pl).encode(),
                                        ('\\%s\\' % tgt_pl).encode())
                    if gender != src_gender:
                        for _p in (b'\\mod\\', b'\\com\\'):
                            ns = ns.replace(_p + src_gender.encode() + b'\\',
                                            _p + gender.encode() + b'\\')
                        ns = ns.replace(b'\\common\\' + src_gender.encode() + b'_',
                                        b'\\common\\' + gender.encode() + b'_')
                    ns = ns[:63]
                    b[off:off + 64] = ns + b'\x00' + b'\xcd' * (63 - len(ns))
            return bytes(b)

        out_entries = []
        has_ctc = False
        mod_name = None
        for e in entries:
            body = e['body']
            name = e['name']
            base = name.rsplit('\\', 1)[-1]
            if body[:4] == MOD_MAGIC:
                body = new_mod
                name = _rename(name, base)
                mod_name = name
            elif body[:4] == MRL_MAGIC:
                body = _patch_mrl_tex(body)
                name = _rename(name, base)
            elif body[:4] == CTC_MAGIC:
                has_ctc = True
                if not self.keep_ctc:
                    continue
                if ctc:
                    body = ctc
                name = _rename(name, base)
            elif base.startswith(src + '_'):
                name = _rename(name, base)
            else:

                name = _rename_path(name)
            raw = zlib.compress(body, 9)
            flag = (e['flag'] & 0xFF000000) | (len(body) & 0xFFFFFF)
            out_entries.append(dict(name=name, hash=e['hash'],
                                    flag=flag, raw=raw, body=body))

        if (self.target_part == 'helm' and mod_name is not None
                and not any(e['body'][:4] == b'XFS\x00' for e in out_entries)):
            _xfs = base64.b64decode(_BMT_XFS_B64)
            out_entries.append(dict(
                name=mod_name, hash=0x66C89ED2,
                flag=(0x40000000 | (len(_xfs) & 0xFFFFFF)),
                raw=zlib.compress(_xfs, 9), body=_xfs))

        if self.target_part == 'helm':
            try:
                from .MTframework_MHGU_helmd import get_modified_xfs, read_disp
                _pending_xfs = get_modified_xfs(context)
                if _pending_xfs and _pending_xfs[:4] == b'XFS\x00':
                    _xe = next((e for e in out_entries
                                if e['body'][:4] == b'XFS\x00'), None)
                    if _xe is None:
                        _xe = dict(name=mod_name, hash=0x66C89ED2, raw=b'', body=b'')
                        out_entries.append(_xe)
                    _xe['body'] = _pending_xfs
                    _xe['raw'] = zlib.compress(_pending_xfs, 9)
                    _xe['flag'] = ((_xe.get('flag', 0x40000000) & 0xFF000000)
                                   | (len(_pending_xfs) & 0xFFFFFF))
                    _v0, _v1, _n, _mix = read_disp(_pending_xfs)
                    print('[MT] 跨部位导出：XFS 使用工程里的待写入值 disp0=0x%04X '
                          'disp1=0x%04X（%d 条）' % (_v0, _v1, _n))
            except Exception as _ex:
                print('[MT] 跨部位导出：待写入 XFS 应用失败:', _ex)

        if self.keep_ctc and ctc and not has_ctc:
            raw = zlib.compress(ctc, 9)
            _dir = mod_name.rsplit('\\', 1)[0] if mod_name else (
                'player\\mod\\' + gender + '\\' + tgt_pl)
            _ctc_e = dict(name=(_dir + '\\' + tgt), hash=CTC_HASH,
                          flag=(0x40000000 | (len(ctc) & 0xFFFFFF)),
                          raw=raw, body=ctc)
            _xfs_i = next((i for i, e in enumerate(out_entries)
                           if e['body'][:4] == b'XFS\x00'), None)
            if _xfs_i is not None:
                out_entries.insert(_xfs_i, _ctc_e)
            else:
                out_entries.append(_ctc_e)

        _caps_written2 = []
        if self.target_part == 'helm' and mod_name:
            try:
                from . import MTframework_MHGU_ccl as _CCL2
                _caps2 = _CCL2.capsules_from_json(
                    getattr(sc, 'MT_CclCapsules', '') or '')
                if not _caps2 and bool(getattr(sc, 'MT_CclEnable', False)):
                    _caps2 = _CCL2.body_capsules(new_mod)
                if _caps2:
                    _CCL2.apply_to_entries(
                        out_entries, mod_name, _CCL2.build_ccl(_caps2))
                    _caps_written2 = list(_caps2)
                    print('[MT] 跨部位导出：已写入 CCL %d 个胶囊' % len(_caps2))
                    for _e in out_entries:
                        if _e['body'][:4] != CTC_MAGIC:
                            continue
                        _nb, _nf = _CCL2.enable_collision_flags(_e['body'])
                        if _nf:
                            _e['body'] = _nb
                            _e['raw'] = zlib.compress(_nb, 9)
                            print('[MT] 跨部位导出：CTC 碰撞位 %d 组' % _nf)
                else:
                    print('[MT] 跨部位导出：没有胶囊（自定义为空且未勾 CCL）')
            except Exception as _ec:
                print('[MT] 跨部位导出 CCL 失败:', _ec)

        raw_dir = (self.out_dir or '').strip().strip('"')
        if raw_dir:
            out_dir = os.path.normpath(bpy.path.abspath(raw_dir))
        else:
            out_dir = os.path.dirname(arc_path)
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception as e:
            self.report({'ERROR'}, '输出目录无法创建：%s（%s）' % (out_dir, e))
            return {'CANCELLED'}

        dst = os.path.join(out_dir, '%s.arc' % self.target_part)
        arc_bytes = arc_build(out_entries)

        try:
            from .MTframework_MHGU_verify import write_arc_verified
            write_arc_verified(dst, arc_bytes,
                               caps=_caps_written2 or None,
                               want_ccl=True if _caps_written2 else None)
        except ValueError as e:
            self.report({'ERROR'}, '跨部位导出校验失败：%s' % e)
            return {'CANCELLED'}
        self.report({'INFO'}, '已从当前工程导出：%s（%d 骨）'
                    % (dst, struct.unpack_from('<H', new_mod, 6)[0]))
        return {'FINISHED'}

_CCL_ACTIVE = False

_CCL_GUARD = False

_CCL_LOADING = False

_CCL_SIG = None

_CCL_POSE_SIG = None

_CCL_DRAGGING = False

_CCL_STAT = {'call': 0, 'seen': 0, 'chg': 0, 'err': ''}

_CCL_CAPS_CACHE = {'text': None, 'caps': []}

_CCL_ARC_CACHE = {'key': None, 'n': -1}

_CCL_BUILD_NOTE = ''

_CCL_CHECK_TEXT = ''

_CCL_UI_GUARD = False

def _ccl_note(msg):
    _CCL_STAT['err'] = str(msg)[:180]
    try:
        print('[MT] CCL: ' + _CCL_STAT['err'])
    except Exception:
        pass

def _ccl_arc_count(path, parse_ccl, find_ccl):
    if not path or not os.path.isfile(path):
        return -1
    try:
        st = os.stat(path)
        key = (path, st.st_mtime, st.st_size)
    except Exception as e:
        _ccl_note('arc 状态读取失败: %r' % (e,))
        return -1
    if _CCL_ARC_CACHE['key'] == key:
        return _CCL_ARC_CACHE['n']
    from .MTframework_MHGU_phys import arc_entries
    with open(path, 'rb') as fh:
        entries = arc_entries(fh.read())
    e = find_ccl(entries)
    n = len(parse_ccl(e['body'])) if e is not None else 0
    _CCL_ARC_CACHE['key'] = key
    _CCL_ARC_CACHE['n'] = n
    return n

def _ccl_diag_text():
    st = _CCL_STAT
    return 'sync: 调用%d 识别%d 改动%d | handler %s' % (
        st['call'], st['seen'], st['chg'], '开' if _ccl_mounted() else '关')

def _ccl_mounted():
    try:
        return _ccl_depsgraph_update in bpy.app.handlers.depsgraph_update_post
    except Exception:
        return False

def _ccl_ensure_handler(scn=None):
    if _ccl_mounted():
        return True
    try:
        scn = scn or bpy.context.scene
        if bpy.data.collections.get('CCL_Preview') is None:
            return False
        bpy.app.handlers.depsgraph_update_post.append(_ccl_depsgraph_update)
        return True
    except Exception as e:
        _ccl_note('挂处理器失败: %r' % (e,))
        return False

def _ccl_unmount_handler():
    try:
        while _ccl_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.remove(_ccl_depsgraph_update)
    except Exception:
        pass

def _ccl_autosync_update(self, context):
    try:
        if bool(getattr(self, 'MT_CclAutoSync', True)):
            _ccl_ensure_handler(self)
        elif bpy.data.collections.get('CCL_Preview') is None:
            _ccl_unmount_handler()
    except Exception as e:
        _ccl_note('切换自动同步失败: %r' % (e,))

def _ccl_bodypick_update(self, context):
    try:
        sc = context.scene if context is not None else bpy.context.scene
        pick = bool(getattr(sc, 'MT_CclBodyPick', False))
        col = bpy.data.collections.get('CCL_Preview')
        if col is None:
            return
        for ob in col.objects:
            if ob.get('ccl_role') == 'capsule':
                ob.hide_select = not pick
    except Exception as e:
        _ccl_note('切换胶囊可选失败: %r' % (e,))

def _ccl_caps(sc):
    txt = getattr(sc, 'MT_CclCapsules', '') or ''
    if _CCL_CAPS_CACHE['text'] == txt:
        return _CCL_CAPS_CACHE['caps']
    from .MTframework_MHGU_ccl import capsules_from_json
    caps = capsules_from_json(txt)
    _CCL_CAPS_CACHE['text'] = txt
    _CCL_CAPS_CACHE['caps'] = caps
    return caps

def _set_ccl_capsules(scene, capsules):
    from .MTframework_MHGU_ccl import capsules_to_json
    txt = capsules_to_json(capsules)
    try:
        scene.MT_CclCapsules = txt
    except Exception as e:
        _ccl_note('写 MT_CclCapsules 失败: %r' % (e,))
        raise
    _CCL_CAPS_CACHE['text'] = txt
    _CCL_CAPS_CACHE['caps'] = capsules

def _ccl_panel_from(sc, caps=None, idx=None):
    global _CCL_LOADING
    if caps is None:
        caps = _ccl_caps(sc)
    if idx is None:
        idx = int(getattr(sc, 'MT_CclIndex', 0) or 0)
    if bool(getattr(sc, 'MT_CclNewPending', False)):
        if not caps:
            return None
        return caps[max(0, min(len(caps) - 1, int(idx)))]
    _CCL_LOADING = True
    try:
        if not caps:
            sc.MT_CclIndex = 0
            sc.MT_CclStart = (0.0, 0.0, 0.0)
            sc.MT_CclEnd = (0.0, 0.0, 0.0)
            return None
        idx = max(0, min(len(caps) - 1, int(idx)))
        if int(getattr(sc, 'MT_CclIndex', 0) or 0) != idx:
            sc.MT_CclIndex = idx
        c = caps[idx]
        sc.MT_CclBoneA = int(c['a'])
        sc.MT_CclBoneB = int(c['b'])
        sc.MT_CclRadius = float(c['radius'])
        sc.MT_CclStart = tuple(float(v) for v in c['start'])
        sc.MT_CclEnd = tuple(float(v) for v in c['end'])
        return c
    finally:
        _CCL_LOADING = False

def _ccl_summary(c, idx):
    return '#%d 骨 %d\u2192%d r%.0f \u8d77(%.0f,%.0f,%.0f) \u7ec8(%.0f,%.0f,%.0f)' % (
        idx, c['a'], c['b'], c['radius'],
        c['start'][0], c['start'][1], c['start'][2],
        c['end'][0], c['end'][1], c['end'][2])

def _ccl_bone_game_id(name, index, rec_ids=None, name_map=None):
    import re
    rec = None
    if name_map and name in name_map:
        rec = int(name_map[name])
    else:
        m = re.match(r'^b_(\d+)(?:\.\w+)?$', name or '')
        if m:
            rec = int(m.group(1)) - 1
    if rec is not None and rec >= 0:
        if rec_ids and rec in rec_ids:
            return int(rec_ids[rec])
        return rec
    return index

def _ccl_selected_bones(context):
    from .MTframework_MHGU_phys import _phys_armature
    arm = _phys_armature(context)
    if arm is None:
        return None, []
    names = []
    try:
        for pb in (context.selected_pose_bones or []):
            if pb is not None and pb.bone is not None and pb.bone.name not in names:
                names.append(pb.bone.name)
    except Exception:
        pass
    if not names:
        try:
            for eb in arm.data.edit_bones:
                if eb.select:
                    names.append(eb.name)
        except Exception:
            pass
    if not names:
        for b in arm.data.bones:
            try:
                if b.select:
                    names.append(b.name)
            except Exception:
                pass
    order = {b.name: i for i, b in enumerate(arm.data.bones)}
    names.sort(key=lambda n: order.get(n, 1 << 30))

    try:
        from .MTframework_MHGU import get_bone_name_map
        _name_map = get_bone_name_map(None, arm)
    except Exception:
        _name_map = {}
    _mod, _S, _bones = _ccl_mod_info(context)
    rec_ids = {info[0]: int(bid) for bid, info in _bones.items()}
    return arm, [(n, _ccl_bone_game_id(n, order.get(n, 0), rec_ids, _name_map))
                 for n in names]

def _ccl_cache_put(col, arm, S, bones):
    col['ccl_arm'] = arm.name
    col['ccl_S'] = float(S)

    d = {}
    for bid, (bname, R) in bones.items():
        d[str(int(bid))] = {'n': str(bname),
                           'R': [float(R[i][j]) for i in range(3) for j in range(3)]}
    try:
        col['ccl_bones'] = d
    except Exception as e:
        _ccl_note('缓存骨映射失败: %r' % (e,))

def _ccl_cache_get(col):
    try:
        if col is None:
            return None, 1.0, {}
        arm = bpy.data.objects.get(str(col.get('ccl_arm', '') or ''))
        S = float(col.get('ccl_S', 1.0) or 1.0)
        raw = col.get('ccl_bones')
        bones = {}
        if raw is not None:
            for k, v in raw.items():
                R = v['R']
                bones[int(k)] = (str(v['n']),
                                 ((float(R[0]), float(R[1]), float(R[2])),
                                  (float(R[3]), float(R[4]), float(R[5])),
                                  (float(R[6]), float(R[7]), float(R[8]))))
        return arm, S, bones
    except Exception as e:
        _ccl_note('读示意缓存失败: %r' % (e,))
        return None, 1.0, {}

def _ccl_preview_signature(col=None):
    col = col or bpy.data.collections.get('CCL_Preview')
    if col is None:
        return None
    sig = []
    for ob in col.objects:
        role = ob.get('ccl_role')
        if role not in ('start', 'end', 'capsule', 'move_a', 'move_b'):
            continue
        m = ob.matrix_world
        sig.append((role,
                    round(m[0][3], 6), round(m[1][3], 6), round(m[2][3], 6),
                    round(float(ob.empty_display_size), 6),
                    round(abs(ob.scale.x) + abs(ob.scale.y) + abs(ob.scale.z), 6)))
    return tuple(sig)

def _ccl_mod_bytes(context):
    sc = context.scene
    try:
        from .MTframework_MHGU_tpl import load_bytes as _tpl_load
        _emb = _tpl_load(context)
        if _emb:
            return _emb
    except Exception:
        pass
    p = sc.get('MT_LastImportPath', '') or ''
    if p and os.path.isfile(p):
        try:
            return open(p, 'rb').read()
        except Exception as e:
            _ccl_note('读模板 .mod 失败: %r' % (e,))
    arc = sc.get('MT_ArcPath', '') or ''
    if arc and os.path.isfile(arc):
        try:
            from .MTframework_MHGU_phys import arc_entries
            with open(arc, 'rb') as fh:
                for e in arc_entries(fh.read()):
                    if e['body'][:4] == b'MOD\x00':
                        return e['body']
        except Exception as e:
            _ccl_note('读 arc 里的 MOD 失败: %r' % (e,))
    return b''

def _ccl_mod_info(context):
    import struct
    mod = _ccl_mod_bytes(context)
    if not mod:
        return b'', 1.0, {}
    try:
        n = struct.unpack_from('<H', mod, 6)[0]
        ptr = struct.unpack_from('<I', mod, 36)[0]
        lmat = ptr + n * 24
        wmat = lmat + n * 64
        s = abs(struct.unpack_from('<f', mod, wmat)[0])
        S = s if s > 1e-6 else 1.0
        bones = {}
        for rec in range(n):
            v = struct.unpack_from('<16f', mod, wmat + rec * 64)
            R = ((v[0] / S, v[4] / S, v[8] / S),
                 (v[1] / S, v[5] / S, v[9] / S),
                 (v[2] / S, v[6] / S, v[10] / S))
            bones[int(mod[ptr + rec * 24])] = (rec, R, (v[12], v[13], v[14]))
        return mod, S, bones
    except Exception as e:
        _ccl_note('解析 .mod 骨矩阵失败: %r' % (e,))
        return mod, 1.0, {}

def _ccl_record_bone(arm, bones, bid):
    info = bones.get(int(bid))
    if info is not None:
        rec, R, t = info

        rev = {}
        try:
            from .MTframework_MHGU import get_bone_name_map
            for _n, _r in get_bone_name_map(None, arm).items():
                rev[int(_r)] = _n
        except Exception:
            rev = {}
        bone = arm.data.bones.get(rev[rec]) if rec in rev else None
        if bone is None:
            name = 'b_%d' % (rec + 1)
            bone = arm.data.bones.get(name)
            if bone is None:
                for b in arm.data.bones:
                    if b.name.startswith(name + '.'):
                        bone = b
                        break
        if bone is None and rec < len(arm.data.bones):
            bone = arm.data.bones[rec]
        if bone is not None:
            return bone, rec, R, t
    name = 'b_%d' % (int(bid) + 1)
    for b in arm.data.bones:
        if b.name == name or b.name.startswith(name + '.'):
            return b, arm.data.bones.find(b.name), ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), (0.0, 0.0, 0.0)
    return None, -1, ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), (0.0, 0.0, 0.0)

def _ccl_bone_now(arm, bone):
    try:
        if getattr(arm, 'pose', None) is not None:
            pb = arm.pose.bones.get(bone.name)
            if pb is not None:
                return arm.matrix_world @ pb.matrix
    except Exception:
        pass
    return arm.matrix_world @ bone.matrix_local

def _ccl_point(arm, bone, R, S, offset):
    from mathutils import Vector
    from .MTframework_MHGU import convert_bone_position
    o = Vector(offset)
    d = Vector((R[0][0] * o.x + R[0][1] * o.y + R[0][2] * o.z,
                R[1][0] * o.x + R[1][1] * o.y + R[1][2] * o.z,
                R[2][0] * o.x + R[2][1] * o.y + R[2][2] * o.z))
    rest = bone.matrix_local
    local = rest.inverted() @ (bone.head_local + convert_bone_position(d / S))
    return _ccl_bone_now(arm, bone) @ local

def _ccl_offset(arm, bone, R, S, world):
    from mathutils import Vector, Matrix
    rest = bone.matrix_local
    p = (rest @ (_ccl_bone_now(arm, bone).inverted() @ Vector(world))) - bone.head_local

    g = Vector((-p.x, -p.z, p.y)) * S
    Rm = Matrix(R)
    return Rm.transposed() @ g

def _ccl_capsule_geometry(pa, pb, r, segs=16, rings=4):
    from mathutils import Vector, Quaternion
    a = Vector(pa)
    b = Vector(pb)
    axis = b - a
    length = axis.length
    center = (a + b) * 0.5
    if length < 1e-6:
        quat = Quaternion((1.0, 0.0, 0.0, 0.0))
        z_bot, z_top = -r, r
        zs = []
        n = max(2, rings * 2)
        for k in range(1, n):
            th = math.pi * k / n
            zs.append((-r * math.cos(th), r * math.sin(th)))
    else:
        quat = Vector((0.0, 0.0, 1.0)).rotation_difference(axis.normalized())
        half = length * 0.5
        zs = []
        for k in range(1, rings + 1):
            th = (math.pi * 0.5) * k / rings
            zs.append((-half - r * math.cos(th), r * math.sin(th)))
        zs.append((half, r))
        for k in range(1, rings):
            th = (math.pi * 0.5) * k / rings
            zs.append((half + r * math.sin(th), r * math.cos(th)))
        z_bot, z_top = -half - r, half + r
    verts = [(0.0, 0.0, z_bot)]
    for z, rad in zs:
        rad = max(1e-6, rad)
        for s in range(segs):
            ang = 2.0 * math.pi * s / segs
            verts.append((rad * math.cos(ang), rad * math.sin(ang), z))
    top_index = len(verts)
    verts.append((0.0, 0.0, z_top))
    faces = []
    for s in range(segs):
        faces.append((0, 1 + (s + 1) % segs, 1 + s))
    for i in range(len(zs) - 1):
        base0 = 1 + i * segs
        base1 = 1 + (i + 1) * segs
        for s in range(segs):
            s2 = (s + 1) % segs
            faces.append((base0 + s, base0 + s2, base1 + s2, base1 + s))
    last = 1 + (len(zs) - 1) * segs
    for s in range(segs):
        faces.append((top_index, last + s, last + (s + 1) % segs))
    return verts, faces, center, quat

def _ccl_capsule_mesh(name, pa, pb, r):
    verts, faces, center, quat = _ccl_capsule_geometry(pa, pb, r)
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    _ccl_fix_normals(me)
    for p in me.polygons:
        p.use_smooth = True
    return me, center, quat

def _ccl_fix_normals(me):
    try:
        import bmesh
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(me)
        bm.free()
        me.update()
    except Exception:
        pass

def _ccl_capsule_material():
    m = bpy.data.materials.get('CCL_Capsule')
    if m is not None:
        return m
    m = bpy.data.materials.new('CCL_Capsule')
    try:
        m.use_nodes = True
        bsdf = m.node_tree.nodes.get('Principled BSDF')
        if bsdf is not None:
            bsdf.inputs['Base Color'].default_value = (0.16, 0.62, 1.0, 1.0)
            bsdf.inputs['Alpha'].default_value = 0.55
            bsdf.inputs['Roughness'].default_value = 0.4
        m.blend_method = 'BLEND'
        m.show_transparent_back = False
    except Exception:
        pass
    return m

def _ccl_handle_size(r):
    try:
        return max(0.02, min(0.16, float(r) * 1.15))
    except Exception:
        return 0.03

def _ccl_style_handle(ob, role, r):
    try:
        ob.empty_display_type = 'CIRCLE'
        ob.empty_display_size = _ccl_handle_size(r)
        ob.show_in_front = True
        ob.show_name = True
        ob.hide_select = False
        ob.color = ((0.25, 1.0, 0.4, 1.0) if role == 'start'
                    else (1.0, 0.35, 0.25, 1.0))
        if (abs(ob.scale.x - 1.0) > 1e-6 or abs(ob.scale.y - 1.0) > 1e-6
                or abs(ob.scale.z - 1.0) > 1e-6):
            ob.scale = (1.0, 1.0, 1.0)
    except Exception:
        pass

def _ccl_style_move(ob, r):
    try:
        ob.empty_display_type = 'SPHERE'
        ob.empty_display_size = max(0.008, _ccl_handle_size(r) * 0.42)
        ob.show_in_front = True
        ob.show_name = False
        ob.hide_select = False
        ob.color = (1.0, 0.82, 0.2, 1.0)
        if (abs(ob.scale.x - 1.0) > 1e-6 or abs(ob.scale.y - 1.0) > 1e-6
                or abs(ob.scale.z - 1.0) > 1e-6):
            ob.scale = (1.0, 1.0, 1.0)
    except Exception:
        pass

def _ccl_capsule_object(name, pa, pb, radius, S):
    from mathutils import Matrix
    r = max(1e-5, float(radius) / (S or 1.0))
    me, center, quat = _ccl_capsule_mesh(name, pa, pb, r)
    ob = bpy.data.objects.new(name, me)
    ob.matrix_world = Matrix.Translation(center) @ quat.to_matrix().to_4x4()
    ob.show_in_front = True
    ob.display_type = 'WIRE'
    ob.show_wire = True
    ob.hide_render = True
    try:
        ob.hide_select = not bool(getattr(bpy.context.scene, 'MT_CclBodyPick', False))
    except Exception:
        ob.hide_select = True
    try:
        ob.data.materials.append(_ccl_capsule_material())
    except Exception:
        pass
    ob['ccl_radius'] = float(radius)
    ob['ccl_center'] = tuple(center)
    ob['ccl_pa'] = tuple(pa)
    ob['ccl_pb'] = tuple(pb)
    return ob

def _ccl_purge_legacy(col=None):
    col = col or bpy.data.collections.get('CCL_Preview')
    if col is None:
        return 0
    n = 0
    for ob in list(col.objects):
        role = ob.get('ccl_role')
        if role not in ('line', 'body'):
            continue
        data = ob.data
        try:
            bpy.data.objects.remove(ob, do_unlink=True)
            n += 1
        except Exception:
            continue
        if data is not None and getattr(data, 'users', 1) == 0:
            try:
                if isinstance(data, bpy.types.Mesh):
                    bpy.data.meshes.remove(data)
            except Exception:
                pass
    return n

def _ccl_preview_obj(role, idx, col=None):
    col = col or bpy.data.collections.get('CCL_Preview')
    if col is None:
        return None
    for ob in col.objects:
        if ob.get('ccl_role') == role and int(ob.get('ccl_index', -1)) == int(idx):
            return ob
    return None

def _ccl_endpoints(cap, arm, S, bones):
    ia = bones.get(int(cap['a']))
    ib = bones.get(int(cap['b']))
    if ia is None or ib is None:
        return None
    ba = arm.data.bones.get(ia[0])
    bb = arm.data.bones.get(ib[0])
    if ba is None or bb is None:
        return None
    return (_ccl_point(arm, ba, ia[1], S, cap['start']),
            _ccl_point(arm, bb, ib[1], S, cap['end']))

def _ccl_capsule_update(ob, pa, pb, radius, S):
    from mathutils import Matrix
    r = max(1e-5, float(radius) / (S or 1.0))
    verts, faces, center, quat = _ccl_capsule_geometry(pa, pb, r)
    me = ob.data
    me.clear_geometry()
    me.from_pydata(verts, [], faces)
    me.update()
    _ccl_fix_normals(me)
    for p in me.polygons:
        p.use_smooth = True
    ob.matrix_world = Matrix.Translation(center) @ quat.to_matrix().to_4x4()
    ob.display_type = 'WIRE'
    ob.show_wire = True
    ob.hide_render = True
    try:
        ob.hide_select = not bool(getattr(bpy.context.scene, 'MT_CclBodyPick', False))
    except Exception:
        pass
    ob['ccl_radius'] = float(radius)
    ob['ccl_center'] = tuple(center)
    ob['ccl_pa'] = tuple(pa)
    ob['ccl_pb'] = tuple(pb)
    return 1

def _ccl_capsule_update_idx(idx, caps, arm, S, bones, col=None):
    if not (0 <= int(idx) < len(caps)):
        return 0
    ob = _ccl_preview_obj('capsule', int(idx), col)
    if ob is None:
        return 0
    pts = _ccl_endpoints(caps[int(idx)], arm, S, bones)
    if pts is None:
        return 0
    return _ccl_capsule_update(ob, pts[0], pts[1], caps[int(idx)]['radius'], S)

def _ccl_refresh_item(idx, caps, arm, S, bones, col=None):
    if not (0 <= int(idx) < len(caps)):
        return 0
    idx = int(idx)
    c = caps[idx]
    r = max(1e-5, float(c['radius']) / (S or 1.0))
    for role in ('start', 'end'):
        ob = _ccl_preview_obj(role, idx, col)
        if ob is not None:

            _ccl_style_handle(ob, role, r)
    for role in ('move_a', 'move_b'):
        ob = _ccl_preview_obj(role, idx, col)
        if ob is not None:
            _ccl_style_move(ob, r)
    lab = _ccl_preview_obj('label', idx, col)
    pts = _ccl_endpoints(c, arm, S, bones)
    if lab is not None:
        try:
            lab.data.body = '#%d r%.1f' % (idx, float(c['radius']))
            lab.data.size = max(0.01, r * 0.45)
        except Exception:
            pass
        if pts is not None:
            try:
                from mathutils import Vector
                lab.matrix_world.translation = pts[1] + Vector((0.0, 0.0, r * 1.15))
            except Exception:
                pass
    if pts is not None:
        _ccl_capsule_update_idx(idx, caps, arm, S, bones, col)
    return 1

def _ccl_place_item(idx, caps, arm, S, bones, col=None):
    if not (0 <= int(idx) < len(caps)):
        return 0
    idx = int(idx)
    pts = _ccl_endpoints(caps[idx], arm, S, bones)
    if pts is None:
        return 0
    pa, pb = pts
    for role, pos in (('start', pa), ('end', pb)):
        ob = _ccl_preview_obj(role, idx, col)
        if ob is None:
            continue
        try:
            m = ob.matrix_world.copy()
            m.translation = pos
            ob.matrix_world = m
        except Exception:
            pass
    return _ccl_refresh_item(idx, caps, arm, S, bones, col)

def _ccl_pose_sig(arm, col=None):
    col = col or bpy.data.collections.get('CCL_Preview')
    if col is None:
        return None
    try:
        vals = []
        for row in arm.matrix_world:
            vals.extend(round(float(v), 5) for v in row)
        names = set()
        for ob in col.objects:
            n = ob.get('ccl_bone_name', '')
            if n:
                names.add(n)
        pose = getattr(arm, 'pose', None)
        if pose is not None:
            for n in sorted(names):
                pb = pose.bones.get(n)
                if pb is None:
                    continue
                for row in pb.matrix:
                    vals.extend(round(float(v), 5) for v in row)
        return tuple(vals)
    except Exception:
        return None

def _ccl_follow_pose(scene=None, col=None):
    from mathutils import Vector
    col = col or bpy.data.collections.get('CCL_Preview')
    if col is None:
        return 0
    try:
        arm, S, bones = _ccl_cache_get(col)
    except Exception:
        return 0
    if arm is None or not bones:
        return 0
    sc = scene or bpy.context.scene
    caps = _ccl_caps(sc)
    if not caps:
        return 0
    moved = 0
    for i, c in enumerate(caps):
        pts = _ccl_endpoints(c, arm, S, bones)
        if pts is None:
            continue
        pa, pb = pts
        for role, pos in (('start', pa), ('end', pb),
                          ('move_a', pa), ('move_b', pb)):
            ob = _ccl_preview_obj(role, i, col)
            if ob is None:
                continue
            m = ob.matrix_world.copy()
            if (m.translation - pos).length > 1e-7:
                m.translation = pos
                ob.matrix_world = m
                moved += 1
            if role in ('move_a', 'move_b'):
                ob['ccl_world'] = tuple(pos)
        cap = _ccl_preview_obj('capsule', i, col)
        if cap is not None:
            old_a = cap.get('ccl_pa')
            old_b = cap.get('ccl_pb')
            if (old_a is None or old_b is None
                    or (Vector(tuple(old_a)) - pa).length > 1e-6
                    or (Vector(tuple(old_b)) - pb).length > 1e-6):
                _ccl_capsule_update(cap, pa, pb, c['radius'], S)
        lab = _ccl_preview_obj('label', i, col)
        if lab is not None:
            r = max(1e-5, float(c['radius']) / (S or 1.0))
            lab.matrix_world.translation = pb + Vector((0.0, 0.0, r * 1.15))
    return moved

def _ccl_clear_preview(context=None):
    global _CCL_SIG, _CCL_POSE_SIG
    _CCL_SIG = None
    _CCL_POSE_SIG = None
    _ccl_unmount_handler()
    col = bpy.data.collections.get('CCL_Preview')
    if col is None:
        return
    for ob in list(col.objects):
        data = ob.data
        bpy.data.objects.remove(ob, do_unlink=True)
        if data is not None and data.users == 0:
            try:
                bpy.data.meshes.remove(data)
            except Exception:
                pass
    try:
        bpy.data.collections.remove(col)
    except Exception as e:
        _ccl_note('删除示意集合失败: %r' % (e,))

def _ccl_build_preview(context, quiet=False):
    global _CCL_BUILD_NOTE, _CCL_POSE_SIG
    from mathutils import Vector, Matrix
    from .MTframework_MHGU_phys import _phys_armature
    sc = context.scene
    _CCL_BUILD_NOTE = ''
    arm = _phys_armature(context)
    if arm is None:
        _CCL_BUILD_NOTE = '场景里没有骨架'
        return -1
    caps = _ccl_caps(sc)
    if not caps:
        _ccl_clear_preview(context)
        _CCL_BUILD_NOTE = '没有自定义胶囊'
        return 0
    mod, S, bones = _ccl_mod_info(context)
    if not bones:

        _CCL_BUILD_NOTE = '没有 .mod 模板：骨 id 按 b_<id+1> 兜底、偏移按 1:1 换算'
    _ccl_clear_preview(context)
    sc['MT_CclPreviewArm'] = arm.name
    col = bpy.data.collections.new('CCL_Preview')
    sc.collection.children.link(col)
    cache = {}
    missing = set()
    made = 0
    for i, c in enumerate(caps):
        ba, reca, Ra, ta = _ccl_record_bone(arm, bones, c['a'])
        bb, recb, Rb, tb = _ccl_record_bone(arm, bones, c['b'])
        if ba is None:
            missing.add(int(c['a']))
        if bb is None:
            missing.add(int(c['b']))
        if ba is None or bb is None:
            continue
        pa = _ccl_point(arm, ba, Ra, S, c['start'])
        pb = _ccl_point(arm, bb, Rb, S, c['end'])
        radius = float(c['radius'])
        r = radius / S
        o = bpy.data.objects.new('CCL%d_Start' % i, None)
        _ccl_style_handle(o, 'start', r)
        o['ccl_role'] = 'start'
        o['ccl_index'] = i
        o['ccl_bone_id'] = int(c['a'])
        o['ccl_bone_name'] = ba.name
        o.matrix_world = Matrix.Translation(pa)
        col.objects.link(o)
        e = bpy.data.objects.new('CCL%d_End_r%.1f' % (i, radius), None)
        _ccl_style_handle(e, 'end', r)
        e['ccl_role'] = 'end'
        e['ccl_index'] = i
        e['ccl_bone_id'] = int(c['b'])
        e['ccl_bone_name'] = bb.name
        e.matrix_world = Matrix.Translation(pb)
        col.objects.link(e)

        for _suf, _pos, _bone, _id in (('A', pa, ba, int(c['a'])),
                                      ('B', pb, bb, int(c['b']))):
            mv = bpy.data.objects.new('CCL%d_Move%s' % (i, _suf), None)
            _ccl_style_move(mv, r)
            mv['ccl_role'] = 'move_a' if _suf == 'A' else 'move_b'
            mv['ccl_index'] = i
            mv['ccl_bone_id'] = _id
            mv['ccl_bone_name'] = _bone.name
            mv['ccl_world'] = tuple(_pos)
            mv.matrix_world = Matrix.Translation(_pos)
            col.objects.link(mv)

        try:
            cop = _ccl_capsule_object('CCL%d_Capsule' % i, pa, pb, radius, S)
            cop['ccl_role'] = 'capsule'
            cop['ccl_index'] = i
            cop['ccl_bone_name'] = bb.name
            col.objects.link(cop)
        except Exception as e3:
            _ccl_note('生成胶囊体失败: %r' % (e3,))
        try:
            cu = bpy.data.curves.new('CCL%d_Label' % i, type='FONT')
            cu.body = '#%d r%.1f' % (i, radius)
            cu.size = max(0.01, r * 0.45)
            tx = bpy.data.objects.new('CCL%d_Label' % i, cu)
            tx.location = pb + Vector((0.0, 0.0, r * 1.15))
            tx['ccl_role'] = 'label'
            tx['ccl_index'] = i
            tx['ccl_bone_name'] = bb.name
            col.objects.link(tx)
        except Exception as e2:
            _ccl_note('生成半径标签失败: %r' % (e2,))
        cache[int(c['a'])] = (ba.name, Ra)
        cache[int(c['b'])] = (bb.name, Rb)
        made += 1
    if made:
        bpy.context.view_layer.update()
        _ccl_cache_put(col, arm, S, cache)

        _ccl_follow_pose(sc, col)
        _CCL_POSE_SIG = _ccl_pose_sig(arm, col)
        if missing:
            _CCL_BUILD_NOTE = '有 %d 个骨 id 在 .mod 里找不到：%s' % (
                len(missing), ','.join(str(v) for v in sorted(missing)))
        _ccl_ensure_handler(sc)
    else:
        _ccl_clear_preview(context)
        if missing:
            _CCL_BUILD_NOTE = '骨 id %s 在 .mod 里找不到，示意建不出来' % (
                ','.join(str(v) for v in sorted(missing)))
        else:
            _CCL_BUILD_NOTE = '没有可显示的胶囊'
    return made

def _ccl_sync_from_preview(scene=None, force=False, _col=None):
    global _CCL_GUARD, _CCL_SIG
    if _CCL_GUARD:
        return 0
    try:
        sc = scene or bpy.context.scene
        if not force and not bool(getattr(sc, 'MT_CclAutoSync', True)):
            return 0
        col = _col or bpy.data.collections.get('CCL_Preview')
        if col is None:
            return 0

        _CCL_GUARD = True
        try:
            _ccl_purge_legacy(col)
        finally:
            _CCL_GUARD = False
        sig = _ccl_preview_signature(col)
        if sig == _CCL_SIG:
            return 0
        arm, S, bones = _ccl_cache_get(col)
        if arm is None:
            _CCL_SIG = sig
            return 0
        caps = _ccl_caps(sc)
        if not caps:
            _CCL_SIG = sig
            return 0
        _CCL_GUARD = True
        try:
            seen = 0
            chg = 0
            touched = set()

            for ob in col.objects:
                if ob.get('ccl_role') != 'capsule':
                    continue
                idx = int(ob.get('ccl_index', -1))
                if not (0 <= idx < len(caps)):
                    continue
                seen += 1
                k = (abs(ob.scale.x) + abs(ob.scale.y) + abs(ob.scale.z)) / 3.0
                if abs(k - 1.0) > 1e-5:
                    base = float(ob.get('ccl_radius', caps[idx].get('radius', 0.0)))
                    rad = max(0.1, base * k)
                    caps[idx]['radius'] = rad
                    ob.scale = (1.0, 1.0, 1.0)
                    ob['ccl_radius'] = rad
                    chg += 1
                    touched.add(idx)
                old_c = ob.get('ccl_center', None)
                if old_c is not None:
                    from mathutils import Vector
                    mc = ob.matrix_world.translation.copy()
                    d = mc - Vector(tuple(old_c))
                    if d.length > 1e-4:
                        pts = _ccl_endpoints(caps[idx], arm, S, bones)
                        ia = bones.get(int(caps[idx]['a']))
                        ib = bones.get(int(caps[idx]['b']))
                        ba = arm.data.bones.get(ia[0]) if ia else None
                        bb = arm.data.bones.get(ib[0]) if ib else None
                        if pts is not None and ba is not None and bb is not None:
                            caps[idx]['start'] = tuple(
                                _ccl_offset(arm, ba, ia[1], S, pts[0] + d))
                            caps[idx]['end'] = tuple(
                                _ccl_offset(arm, bb, ib[1], S, pts[1] + d))
                            chg += 2
                            touched.add(idx)

                            for _role in ('start', 'end', 'move_a', 'move_b'):
                                e2 = _ccl_preview_obj(_role, idx, col)
                                if e2 is not None:
                                    m2 = e2.matrix_world.copy()
                                    m2.translation = m2.translation + d
                                    e2.matrix_world = m2
                            for _role in ('move_a', 'move_b'):
                                e2 = _ccl_preview_obj(_role, idx, col)
                                if e2 is not None:
                                    e2['ccl_world'] = tuple(e2.matrix_world.translation)
                    ob['ccl_center'] = tuple(mc)

            for ob in col.objects:
                role = ob.get('ccl_role')
                if role not in ('move_a', 'move_b'):
                    continue
                idx = int(ob.get('ccl_index', -1))
                if not (0 <= idx < len(caps)):
                    continue
                old_w = ob.get('ccl_world', None)
                if old_w is None:
                    continue
                from mathutils import Vector
                d = ob.matrix_world.translation - Vector(tuple(old_w))
                if d.length <= 1e-4:
                    continue
                seen += 1
                pts = _ccl_endpoints(caps[idx], arm, S, bones)
                ia = bones.get(int(caps[idx]['a']))
                ib = bones.get(int(caps[idx]['b']))
                ba = arm.data.bones.get(ia[0]) if ia else None
                bb = arm.data.bones.get(ib[0]) if ib else None
                if pts is not None and ba is not None and bb is not None:
                    caps[idx]['start'] = tuple(
                        _ccl_offset(arm, ba, ia[1], S, pts[0] + d))
                    caps[idx]['end'] = tuple(
                        _ccl_offset(arm, bb, ib[1], S, pts[1] + d))
                    chg += 2
                    touched.add(idx)

                    for _role in ('start', 'end', 'move_a', 'move_b'):
                        e2 = _ccl_preview_obj(_role, idx, col)
                        if e2 is not None:
                            m2 = e2.matrix_world.copy()
                            m2.translation = m2.translation + d
                            e2.matrix_world = m2
                    for _role in ('move_a', 'move_b'):
                        e2 = _ccl_preview_obj(_role, idx, col)
                        if e2 is not None:
                            e2['ccl_world'] = tuple(e2.matrix_world.translation)

            for ob in col.objects:
                role = ob.get('ccl_role')
                if role not in ('start', 'end'):
                    continue
                idx = int(ob.get('ccl_index', -1))
                if not (0 <= idx < len(caps)):
                    continue
                info = bones.get(int(ob.get('ccl_bone_id', 0)))
                if info is None:
                    continue
                bone = arm.data.bones.get(info[0])
                if bone is None:
                    continue
                seen += 1
                off = _ccl_offset(arm, bone, info[1], S, ob.matrix_world.translation)
                key = 'start' if role == 'start' else 'end'
                old = caps[idx].get(key, (0.0, 0.0, 0.0))
                if max(abs(off[i] - float(old[i])) for i in range(3)) > 1e-4:
                    caps[idx][key] = tuple(float(v) for v in off)
                    chg += 1
                    touched.add(idx)
                k2 = (abs(ob.scale.x) + abs(ob.scale.y) + abs(ob.scale.z)) / 3.0
                if abs(k2 - 1.0) > 1e-5:
                    try:
                        ob.scale = (1.0, 1.0, 1.0)
                    except Exception:
                        pass
            _CCL_STAT['call'] += 1
            _CCL_STAT['seen'] += seen
            if chg:
                _CCL_STAT['chg'] += chg
                _set_ccl_capsules(sc, caps)

                cur = int(getattr(sc, 'MT_CclIndex', 0) or 0)
                if touched and cur not in touched:
                    cur = min(touched)
                _ccl_panel_from(sc, caps, cur)

                for _i in sorted(touched):
                    try:
                        _ccl_refresh_item(_i, caps, arm, S, bones, col)
                    except Exception:
                        pass

                try:
                    _ccl_follow_pose(sc, col)
                except Exception:
                    pass
            _CCL_SIG = sig
            return chg
        finally:
            _CCL_GUARD = False
    except Exception as e:
        _ccl_note('同步失败: %r' % (e,))
        import traceback
        traceback.print_exc()
        return 0

def _ccl_depsgraph_update(scene, depsgraph=None):
    if _CCL_GUARD:
        return
    global _CCL_POSE_SIG, _CCL_SIG
    try:
        col = bpy.data.collections.get('CCL_Preview')
        if col is None:
            _ccl_unmount_handler()
            return
        arm, S, bones = _ccl_cache_get(col)
        sigp = _ccl_pose_sig(arm, col) if arm is not None else None
        if sigp is not None and sigp != _CCL_POSE_SIG:
            _CCL_POSE_SIG = sigp
            _ccl_follow_pose(scene, col)
            _CCL_SIG = _ccl_preview_signature(col)
            return
        if not bool(getattr(scene, 'MT_CclAutoSync', True)):
            return
        _ccl_sync_from_preview(scene, _col=col)
    except Exception as e:
        _ccl_note('depsgraph 同步出错: %r' % (e,))

def _ccl_auto_refresh(context):
    sc = context.scene
    if not bool(getattr(sc, 'MT_CclAutoPreview', True)):
        return 0
    return _ccl_build_preview(context, quiet=True)

def _ccl_props_to_capsule(sc):
    return {'a': int(sc.MT_CclBoneA), 'b': int(sc.MT_CclBoneB),
            'start': tuple(float(v) for v in sc.MT_CclStart),
            'end': tuple(float(v) for v in sc.MT_CclEnd),
            'radius': float(sc.MT_CclRadius)}

def _ccl_find_capsule_for_bone(caps, bid):
    for i, c in enumerate(caps):
        if int(c['a']) == int(bid) or int(c['b']) == int(bid):
            return i
    return -1

class MT_OT_CclCapsuleAdd(Operator):
    bl_idname = "mt_framework.ccl_capsule_add"
    bl_label = "新增胶囊"
    bl_description = ("选中 1~2 根骨后点：新增一条胶囊，A/B 用选中骨，"
                      "起点/终点偏移从 0 开始（不会沿用上一条）")

    def execute(self, context):
        sc = context.scene
        caps = _ccl_caps(sc)
        _arm, _sel = _ccl_selected_bones(context)
        a = int(_sel[0][1]) if _sel else int(sc.MT_CclBoneA)
        b = int(_sel[-1][1]) if _sel else int(sc.MT_CclBoneB)
        try:
            r = float(sc.MT_CclRadius)
        except Exception:
            r = 30.0
        c = {'a': a, 'b': b, 'start': (0.0, 0.0, 0.0),
             'end': (0.0, 0.0, 0.0), 'radius': r}
        caps.append(c)
        idx = len(caps) - 1
        _set_ccl_capsules(sc, caps)
        sc.MT_CclNewPending = False
        _ccl_panel_from(sc, caps, idx)
        _ccl_auto_refresh(context)
        self.report({'INFO'}, '已新增胶囊 #%d：骨 %d→%d 半径 %.1f（偏移从 0 开始）'
                    % (idx, a, b, r))
        return {'FINISHED'}

class MT_OT_CclCapsuleClear(Operator):
    bl_idname = "mt_framework.ccl_capsule_clear"
    bl_label = "清空胶囊"
    bl_description = "清空 MT_CclCapsules（导出退回自动 11 个身体胶囊）"

    def execute(self, context):
        sc = context.scene
        _set_ccl_capsules(sc, [])
        _ccl_clear_preview(context)
        sc.MT_CclNewPending = False
        _ccl_panel_from(sc, [], 0)
        self.report({'INFO'}, '已清空自定义胶囊（导出用自动 11 个）')
        return {'FINISHED'}

class MT_OT_CclCapsuleDel(Operator):
    bl_idname = "mt_framework.ccl_capsule_del"
    bl_label = "删除当前胶囊"
    bl_description = "删掉 MT_CclIndex 指向的胶囊（序号越界时删最后一个），删完自动读取剩余那条"

    def execute(self, context):
        sc = context.scene
        caps = _ccl_caps(sc)
        if not caps:
            self.report({'WARNING'}, '没有自定义胶囊可删')
            return {'CANCELLED'}
        idx = int(getattr(sc, 'MT_CclIndex', 0) or 0)
        if idx >= len(caps):
            idx = len(caps) - 1
        caps.pop(idx)
        _set_ccl_capsules(sc, caps)
        if caps:
            idx = min(idx, len(caps) - 1)
            sc.MT_CclNewPending = False
            c = _ccl_panel_from(sc, caps, idx)
            _ccl_auto_refresh(context)
            self.report({'INFO'}, '已删除胶囊，还剩 %d 个；当前 #%d %s'
                        % (len(caps), idx, _ccl_summary(c, idx)))
        else:
            _ccl_clear_preview(context)
            sc.MT_CclNewPending = False
            _ccl_panel_from(sc, [], 0)
            self.report({'INFO'}, '已删除最后一条胶囊，面板数值归零、示意已清空')
        return {'FINISHED'}

_CCL_INDEX_GUARD = False

def _ccl_index_update(self, context):
    if _CCL_LOADING or _CCL_GUARD or _CCL_INDEX_GUARD:
        return
    try:
        caps = _ccl_caps(self)
        if not caps:
            return
        idx = int(getattr(self, 'MT_CclIndex', 0) or 0)
        self.MT_CclNewPending = False
        _ccl_panel_from(self, caps, idx)
    except Exception as e:
        _ccl_note('切换序号读取失败: %r' % (e,))

def _ccl_deferred_rebuild():
    try:
        ctx = bpy.context
        if ctx is None or ctx.scene is None:
            sc = bpy.data.scenes[0] if bpy.data.scenes else None
            if sc is None:
                return None
            ctx = {'scene': sc}
        _ccl_build_preview(ctx, quiet=True)
    except Exception as e:
        _ccl_note('重建示意失败: %r' % (e,))
    return None

def _ccl_schedule_rebuild():
    try:
        bpy.app.timers.register(_ccl_deferred_rebuild, first_interval=0.05)
    except Exception:
        _ccl_deferred_rebuild()

def _ccl_prop_update(self, context):
    global _CCL_UI_GUARD, _CCL_SIG
    if _CCL_UI_GUARD or _CCL_LOADING or _CCL_GUARD or _CCL_DRAGGING:
        return
    try:
        sc = self
        if bool(getattr(sc, 'MT_CclNewPending', False)):
            return
        caps = _ccl_caps(sc)
        if not caps:
            return
        idx = max(0, min(len(caps) - 1, int(getattr(sc, 'MT_CclIndex', 0) or 0)))
        c = caps[idx]
        na, nb = int(sc.MT_CclBoneA), int(sc.MT_CclBoneB)
        ns = tuple(float(v) for v in sc.MT_CclStart)
        ne = tuple(float(v) for v in sc.MT_CclEnd)
        nr = max(0.1, float(sc.MT_CclRadius))
        same = (na == int(c['a']) and nb == int(c['b'])
                and abs(nr - float(c['radius'])) < 1e-6
                and max(abs(ns[i] - float(c['start'][i])) for i in range(3)) < 1e-6
                and max(abs(ne[i] - float(c['end'][i])) for i in range(3)) < 1e-6)
        if same:
            return
        bones_changed = (na != int(c['a']) or nb != int(c['b']))
        c['a'], c['b'] = na, nb
        c['start'] = ns
        c['end'] = ne
        c['radius'] = nr
        _CCL_UI_GUARD = True
        try:
            _set_ccl_capsules(sc, caps)
            col = bpy.data.collections.get('CCL_Preview')
            arm = S = bones = None
            if col is not None:
                try:
                    arm, S, bones = _ccl_cache_get(col)
                except Exception:
                    arm = None
            if arm is not None:
                if bones_changed:
                    if bool(getattr(sc, 'MT_CclAutoPreview', True)):
                        _ccl_schedule_rebuild()
                else:
                    _ccl_place_item(idx, caps, arm, S, bones, col)
            _CCL_SIG = None
        finally:
            _CCL_UI_GUARD = False
    except Exception as e:
        _ccl_note('面板数值联动失败: %r' % (e,))

class MT_OT_CclCapsuleSwap(Operator):
    bl_idname = "mt_framework.ccl_capsule_swap"
    bl_label = "交换起终点"
    bl_description = ("把 MT_CclIndex 指向的胶囊的骨 A/B 与起点/终点偏移对调；"
                      "胶囊方向反了不用删了重做")

    def execute(self, context):
        sc = context.scene
        caps = _ccl_caps(sc)
        if not caps:
            self.report({'WARNING'}, '还没有自定义胶囊')
            return {'CANCELLED'}
        idx = max(0, min(len(caps) - 1, int(getattr(sc, 'MT_CclIndex', 0) or 0)))
        c = caps[idx]
        c['a'], c['b'] = int(c['b']), int(c['a'])
        c['start'], c['end'] = tuple(c['end']), tuple(c['start'])
        _set_ccl_capsules(sc, caps)
        _ccl_panel_from(sc, caps, idx)
        _ccl_auto_refresh(context)
        self.report({'INFO'}, '已交换 #%d：骨 %d→%d %s'
                    % (idx, c['a'], c['b'], _ccl_summary(c, idx)))
        return {'FINISHED'}

class MT_OT_CclCapsuleZero(Operator):
    bl_idname = "mt_framework.ccl_capsule_zero"
    bl_label = "偏移归零"
    bl_description = "把 MT_CclIndex 指向的胶囊的起点/终点偏移都设为 0"

    def execute(self, context):
        sc = context.scene
        caps = _ccl_caps(sc)
        if not caps:
            self.report({'WARNING'}, '还没有自定义胶囊')
            return {'CANCELLED'}
        idx = max(0, min(len(caps) - 1, int(getattr(sc, 'MT_CclIndex', 0) or 0)))
        caps[idx]['start'] = (0.0, 0.0, 0.0)
        caps[idx]['end'] = (0.0, 0.0, 0.0)
        _set_ccl_capsules(sc, caps)
        c = _ccl_panel_from(sc, caps, idx)
        _ccl_auto_refresh(context)
        self.report({'INFO'}, '胶囊 #%d 偏移已归零 | %s' % (idx, _ccl_summary(c, idx)))
        return {'FINISHED'}

class MT_OT_CclCapsuleStep(Operator):
    bl_idname = "mt_framework.ccl_capsule_step"
    bl_label = "切换胶囊"
    bl_description = "切到上一条/下一条胶囊并读取它的数值"

    step: IntProperty(name="步进", default=1)

    def execute(self, context):
        sc = context.scene
        caps = _ccl_caps(sc)
        if not caps:
            self.report({'WARNING'}, '还没有自定义胶囊')
            return {'CANCELLED'}
        idx = int(getattr(sc, 'MT_CclIndex', 0) or 0) + int(self.step)
        idx = max(0, min(len(caps) - 1, idx))
        c = _ccl_panel_from(sc, caps, idx)
        self.report({'INFO'}, '#%d/%d %s' % (idx, len(caps) - 1, _ccl_summary(c, idx)))
        return {'FINISHED'}

class MT_OT_CclCapsuleLoad(Operator):
    bl_idname = "mt_framework.ccl_capsule_load"
    bl_label = "读取该项"
    bl_description = "把 MT_CclIndex 指向的胶囊读进 骨A/骨B/半径/起点偏移/终点偏移"

    def execute(self, context):
        sc = context.scene
        caps = _ccl_caps(sc)
        if not caps:
            self.report({'WARNING'}, '还没有自定义胶囊：先「新增」或「A/B 取选中骨」')
            return {'CANCELLED'}
        idx = int(getattr(sc, 'MT_CclIndex', 0) or 0)
        if idx >= len(caps):
            self.report({'WARNING'}, '序号 %d 超出（现有 %d 条），已夹到 #%d'
                        % (idx, len(caps), len(caps) - 1))
            idx = len(caps) - 1
        c = _ccl_panel_from(sc, caps, idx)
        self.report({'INFO'}, '已读取 %s' % _ccl_summary(c, idx))
        return {'FINISHED'}

class MT_OT_CclReadBone(Operator):
    bl_idname = "mt_framework.ccl_capsule_read_bone"
    bl_label = "读取选中骨的胶囊"
    bl_description = "选中 1 根骨：找到 a 或 b 等于该骨 id 的胶囊，载入并切到该序号；没有就提示"

    def execute(self, context):
        sc = context.scene
        arm, sel = _ccl_selected_bones(context)
        if arm is None:
            self.report({'ERROR'}, '场景里没有骨架')
            return {'CANCELLED'}
        if not sel:
            self.report({'ERROR'}, '先在骨架里选中 1 根骨')
            return {'CANCELLED'}
        name, bid = sel[0]
        caps = _ccl_caps(sc)
        if not caps:
            self.report({'WARNING'}, '还没有自定义胶囊')
            return {'CANCELLED'}
        idx = _ccl_find_capsule_for_bone(caps, bid)
        if idx < 0:
            self.report({'WARNING'}, '骨 %s（id %d）没有胶囊：现有 %d 条都没有用到它'
                        % (name, bid, len(caps)))
            return {'CANCELLED'}
        c = _ccl_panel_from(sc, caps, idx)
        self.report({'INFO'}, '骨 %s（id %d）→ %s' % (name, bid, _ccl_summary(c, idx)))
        return {'FINISHED'}

class MT_OT_CclCapsuleStore(Operator):
    bl_idname = "mt_framework.ccl_capsule_store"
    bl_label = "应用修改"
    bl_description = "把当前面板的 骨A/骨B/半径/起点偏移/终点偏移 写回 MT_CclIndex"

    def execute(self, context):
        sc = context.scene
        caps = _ccl_caps(sc)
        idx = int(getattr(sc, 'MT_CclIndex', 0) or 0)
        new = _ccl_props_to_capsule(sc)
        if idx < len(caps):
            caps[idx] = new
        elif idx == len(caps):
            caps.append(new)
        else:
            self.report({'WARNING'}, '序号 %d 超出（现有 %d 个），已追加到末尾' % (idx, len(caps)))
            caps.append(new)
            idx = len(caps) - 1
        _set_ccl_capsules(sc, caps)
        sc.MT_CclNewPending = False
        c = _ccl_panel_from(sc, caps, idx)
        n = _ccl_auto_refresh(context)
        self.report({'INFO'}, '已写入 #%d（共 %d 个）%s%s'
                    % (idx, len(caps), ('，示意已更新' if n > 0 else ''),
                       (' | ' + _ccl_summary(c, idx)) if c else ''))
        return {'FINISHED'}

class MT_OT_CclCapsulePick(Operator):
    bl_idname = "mt_framework.ccl_capsule_pick"
    bl_label = "A/B 取选中骨"
    bl_description = "把选中的 1~2 根骨的骨 id 填进 骨A/骨B（偏移保持不变）"

    def execute(self, context):
        global _CCL_UI_GUARD
        sc = context.scene
        arm, bones = _ccl_selected_bones(context)
        if arm is None or not bones:
            self.report({'ERROR'}, '先在骨架里选中 1~2 根骨')
            return {'CANCELLED'}

        _CCL_UI_GUARD = True
        try:
            sc.MT_CclBoneA = bones[0][1]
            sc.MT_CclBoneB = bones[-1][1]
            sc.MT_CclNewPending = True
        finally:
            _CCL_UI_GUARD = False
        self.report({'INFO'}, '骨A=%s(%d) 骨B=%s(%d)（点「新增胶囊」创建，不会动已有胶囊）'
                    % (bones[0][0], bones[0][1], bones[-1][0], bones[-1][1]))
        return {'FINISHED'}

class MT_OT_CclPreview(Operator):
    bl_idname = "mt_framework.ccl_preview"
    bl_label = "生成胶囊示意"
    bl_description = ("按胶囊数据重建 起点标记/终点球/连线/半径标签，"
                      "并把第 N 条数值读进面板；重复点会重建，不会叠加")

    def execute(self, context):
        sc = context.scene
        n = _ccl_build_preview(context)
        if n < 0:
            self.report({'ERROR'}, '场景里没有骨架')
            return {'CANCELLED'}
        if n == 0:
            msg = _CCL_BUILD_NOTE or '没有自定义胶囊：先「新增」或「A/B 取选中骨」'
            self.report({'WARNING'}, msg)
            return {'CANCELLED'}
        caps = _ccl_caps(sc)
        idx = max(0, min(len(caps) - 1, int(getattr(sc, 'MT_CclIndex', 0) or 0)))
        c = _ccl_panel_from(sc, caps, idx)
        txt = '已生成 %d 个胶囊示意 | %s' % (n, _ccl_summary(c, idx) if c else '')
        if _CCL_BUILD_NOTE:
            txt += ' | ' + _CCL_BUILD_NOTE
            self.report({'WARNING'}, txt)
        else:
            self.report({'INFO'}, txt)
        return {'FINISHED'}

class MT_OT_CclFromPreview(Operator):
    bl_idname = "mt_framework.ccl_from_preview"
    bl_label = "从示意回填"
    bl_description = "读取 CCL_Preview 里端点手柄的位置与胶囊半径，写回胶囊列表"

    def execute(self, context):
        sc = context.scene
        col = bpy.data.collections.get('CCL_Preview')
        if col is None:
            self.report({'ERROR'}, '先点「生成胶囊示意」')
            return {'CANCELLED'}
        caps = _ccl_caps(sc)
        if not caps:
            self.report({'ERROR'}, '自定义胶囊列表是空的')
            return {'CANCELLED'}
        n = _ccl_sync_from_preview(sc, force=True, _col=col)
        if n <= 0:

            c = _ccl_panel_from(sc, caps)
            self.report({'INFO'}, '示意与胶囊数据一致，无需回填%s'
                        % ((' | ' + _ccl_summary(c, int(sc.MT_CclIndex))) if c else ''))
            return {'FINISHED'}
        c = _ccl_panel_from(sc, caps)
        self.report({'INFO'}, '已从示意回填 %d 处改动 | %s'
                    % (n, _ccl_summary(c, int(sc.MT_CclIndex)) if c else ''))
        return {'FINISHED'}

class MT_OT_CclPreviewClear(Operator):
    bl_idname = "mt_framework.ccl_preview_clear"
    bl_label = "清除示意"
    bl_description = "删除 CCL_Preview 集合（同时摘掉同步处理器）"

    def execute(self, context):
        _ccl_clear_preview(context)
        self.report({'INFO'}, '已清除碰撞体示意')
        return {'FINISHED'}

class MT_OT_CclDragSync(Operator):
    bl_idname = "mt_framework.ccl_drag_sync"
    bl_label = "拖动同步（端点手柄）"
    bl_description = ("进入后移动鼠标 = 拖端点手柄，面板偏移量实时更新；"
                      "滚轮 = 改半径；Tab = 切起点/终点；左键/右键 = 完成；ESC = 取消")

    def invoke(self, context, event):
        global _CCL_DRAGGING
        if _CCL_DRAGGING:
            self.report({'WARNING'}, '已经在拖动同步中：左键/右键结束')
            return {'CANCELLED'}
        sc = context.scene
        caps = _ccl_caps(sc)
        if not caps:
            self.report({'ERROR'}, '没有自定义胶囊：先「新增」')
            return {'CANCELLED'}
        col = bpy.data.collections.get('CCL_Preview')
        if col is None:
            n = _ccl_build_preview(context, quiet=True)
            col = bpy.data.collections.get('CCL_Preview')
            if col is None or n <= 0:
                self.report({'ERROR'}, _CCL_BUILD_NOTE or '示意建不出来：先「生成胶囊示意」')
                return {'CANCELLED'}
        ob = _ccl_drag_target(context, col)
        if ob is None:
            self.report({'ERROR'}, 'CCL_Preview 里没有可拖的端点手柄')
            return {'CANCELLED'}
        idx = int(ob.get('ccl_index', 0))
        self._ob = ob
        self._idx = idx
        self._role = str(ob.get('ccl_role', 'end'))
        self._json0 = str(getattr(sc, 'MT_CclCapsules', '') or '')
        self._panel0 = (int(sc.MT_CclBoneA), int(sc.MT_CclBoneB), float(sc.MT_CclRadius),
                        tuple(sc.MT_CclStart), tuple(sc.MT_CclEnd))
        self._anchor = ob.matrix_world.translation.copy()
        self._start_pos = self._anchor.copy()
        self._region = context.region
        self._rv3d = context.region_data
        self._area = context.area
        if self._rv3d is None:
            self.report({'ERROR'}, '请在 3D 视图里用这个按钮')
            return {'CANCELLED'}
        from mathutils import Vector
        self._normal = (self._rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))).normalized()
        mx = getattr(event, 'mouse_region_x', None)
        my = getattr(event, 'mouse_region_y', None)
        if mx is None or my is None:
            mx = int(self._region.width / 2)
            my = int(self._region.height / 2)
        self._mouse0 = (int(mx), int(my))
        p0 = self._mouse_world(int(mx), int(my))
        self._mouse0_pos = p0 if p0 is not None else self._start_pos.copy()
        arm, S, bones = _ccl_cache_get(col)
        self._arm = arm
        self._S = S
        self._bones = bones
        for o in context.selected_objects:
            try:
                o.select_set(False)
            except Exception:
                pass
        ob.select_set(True)
        context.view_layer.objects.active = ob
        _CCL_DRAGGING = True
        self._axis = None
        self._hdr = ('拖动同步：移动=拖端点 | X/Y/Z=锁轴 | Shift=精调 | 滚轮=半径 | '
                     'Tab=起/终点 | 左/右键=完成 | ESC=取消')
        try:
            context.area.header_text_set(self._hdr)
        except Exception:
            pass
        context.window_manager.modal_handler_add(self)
        self.report({'INFO'}, '拖动同步：#%d %s | %s'
                    % (idx, '终点' if self._role == 'end' else '起点', _ccl_diag_text()))
        return {'RUNNING_MODAL'}

    def _axis_vector(self):
        from mathutils import Vector
        if self._axis is None:
            return None
        v = Vector((0.0, 0.0, 0.0))
        v[self._axis] = 1.0
        return v

    def _constrain(self, raw, event):
        from mathutils import Vector
        d = raw - self._anchor
        if getattr(event, 'shift', False):
            d = d * 0.1
        ax = self._axis_vector()
        if ax is not None:
            d = ax * d.dot(ax)
        return self._anchor + d

    def _hdr_live(self, context):
        try:
            sc = context.scene
            caps = _ccl_caps(sc)
            if not (0 <= self._idx < len(caps)):
                return
            c = caps[self._idx]
            ax = '自由' if self._axis is None else 'XYZ'[self._axis]
            key = 'start' if self._role == 'start' else 'end'
            off = c[key]
            tag = '起' if self._role == 'start' else '终'
            self._hdr = ('拖动同步 #%d %s | 轴:%s | %s偏移(%+.1f,%+.1f,%+.1f) | r%.1f | '
                         'X/Y/Z=锁轴 Shift=精调 滚轮=半径 Tab=起/终点 左/右键=完成 ESC=取消'
                         % (self._idx, '起点' if self._role == 'start' else '终点',
                            ax, tag,
                            float(off[0]), float(off[1]), float(off[2]),
                            float(c['radius'])))
            context.area.header_text_set(self._hdr)
        except Exception:
            pass

    def _mouse_world(self, mx, my):
        try:
            from bpy_extras.view3d_utils import (region_2d_to_origin_3d,
                                                 region_2d_to_vector_3d)
            origin = region_2d_to_origin_3d(self._region, self._rv3d, (mx, my))
            direction = region_2d_to_vector_3d(self._region, self._rv3d, (mx, my))
            denom = direction.dot(self._normal)
            if abs(denom) < 1e-9:
                return None
            t = (self._anchor - origin).dot(self._normal) / denom
            return origin + direction * t
        except Exception as e:
            _ccl_note('鼠标投影失败: %r' % (e,))
            return None

    def _apply_position(self, context, pos):
        sc = context.scene
        self._ob.matrix_world.translation = pos
        caps = _ccl_caps(sc)
        if not (0 <= self._idx < len(caps)):
            return 0
        info = self._bones.get(int(self._ob.get('ccl_bone_id', 0)))
        if info is None or self._arm is None:
            return 0
        bone = self._arm.data.bones.get(info[0])
        if bone is None:
            return 0
        off = _ccl_offset(self._arm, bone, info[1], self._S, pos)
        c = caps[self._idx]
        key = 'start' if self._role == 'start' else 'end'
        old = c.get(key, (0.0, 0.0, 0.0))
        if max(abs(off[i] - float(old[i])) for i in range(3)) <= 1e-6:
            return 0
        c[key] = tuple(float(v) for v in off)
        _set_ccl_capsules(sc, caps)
        _ccl_panel_from(sc, caps, self._idx)
        try:
            _ccl_refresh_item(self._idx, caps, self._arm, self._S, self._bones)
        except Exception:
            pass
        _CCL_STAT['seen'] += 1
        _CCL_STAT['chg'] += 1
        return 1

    def _apply_radius(self, context, factor):
        sc = context.scene
        caps = _ccl_caps(sc)
        if not (0 <= self._idx < len(caps)):
            return 0
        c = caps[self._idx]
        r = max(0.1, min(10000.0, float(c['radius']) * factor))
        if abs(r - float(c['radius'])) < 1e-6:
            return 0
        c['radius'] = r
        _set_ccl_capsules(sc, caps)
        _ccl_panel_from(sc, caps, self._idx)

        try:
            _ccl_refresh_item(self._idx, caps, self._arm, self._S, self._bones)
        except Exception:
            pass
        return 1

    def _switch_role(self, context):
        col = bpy.data.collections.get('CCL_Preview')
        if col is None:
            return
        want = 'start' if self._role == 'end' else 'end'
        for ob in col.objects:
            if ob.get('ccl_role') == want and int(ob.get('ccl_index', -1)) == self._idx:
                self._ob = ob
                self._role = want
                self._anchor = ob.matrix_world.translation.copy()
                self._start_pos = self._anchor.copy()
                for o in context.selected_objects:
                    try:
                        o.select_set(False)
                    except Exception:
                        pass
                ob.select_set(True)
                context.view_layer.objects.active = ob
                _CCL_STAT['seen'] += 1
                return

    def _finish(self, context, keep):
        global _CCL_DRAGGING
        _CCL_DRAGGING = False
        try:
            context.area.header_text_set(None)
        except Exception:
            pass
        if not keep:
            sc = context.scene
            try:
                sc.MT_CclCapsules = self._json0
                _CCL_CAPS_CACHE['text'] = None
                caps = _ccl_caps(sc)
                _ccl_panel_from(sc, caps, self._idx)
                _ccl_build_preview(context, quiet=True)
            except Exception as e:
                _ccl_note('取消拖动还原失败: %r' % (e,))
        else:
            try:
                _ccl_sync_from_preview(context.scene, force=True)
            except Exception as e:
                _ccl_note('收尾同步失败: %r' % (e,))
        try:
            self._area.tag_redraw()
        except Exception:
            pass

    def modal(self, context, event):
        try:
            et = event.type
            if et == 'MOUSEMOVE' and event.value in ('MOVE', 'PRESS'):
                pos = self._mouse_world(event.mouse_region_x, event.mouse_region_y)
                if pos is not None:
                    self._apply_position(context, self._constrain(pos, event))
                self._hdr_live(context)
                if self._area is not None:
                    self._area.tag_redraw()
                return {'RUNNING_MODAL'}
            if et in ('LEFTMOUSE', 'RIGHTMOUSE') and event.value == 'PRESS':
                self._finish(context, True)
                return {'FINISHED'}
            if et == 'ESC' and event.value == 'PRESS':
                self._finish(context, False)
                return {'CANCELLED'}
            if et == 'WHEELUPMOUSE' or et == 'WHEELDOWNMOUSE':
                self._apply_radius(context, 1.05 if et == 'WHEELUPMOUSE' else (1.0 / 1.05))
                self._hdr_live(context)
                if self._area is not None:
                    self._area.tag_redraw()
                return {'RUNNING_MODAL'}
            if et == 'TAB' and event.value == 'PRESS':
                self._switch_role(context)
                self._hdr_live(context)
                return {'RUNNING_MODAL'}

            if et in ('X', 'Y', 'Z') and event.value == 'PRESS':
                ax = {'X': 0, 'Y': 1, 'Z': 2}[et]
                self._axis = None if self._axis == ax else ax
                self._hdr_live(context)
                return {'RUNNING_MODAL'}
            return {'RUNNING_MODAL'}
        except Exception as e:
            _ccl_note('拖动同步出错: %r' % (e,))
            import traceback
            traceback.print_exc()
            self._finish(context, True)
            return {'CANCELLED'}

def _ccl_drag_target(context, col):
    for ob in context.selected_objects:
        if ob.get('ccl_role') in ('start', 'end'):
            try:
                if ob.name in col.objects:
                    return ob
            except Exception:
                pass
    idx = int(getattr(context.scene, 'MT_CclIndex', 0) or 0)
    for want in ('end', 'start'):
        for ob in col.objects:
            if ob.get('ccl_role') == want and int(ob.get('ccl_index', -1)) == idx:
                return ob
    for ob in col.objects:
        if ob.get('ccl_role') in ('start', 'end'):
            return ob
    return None

class MT_OT_CclCapsuleImport(Operator):
    bl_idname = "mt_framework.ccl_capsule_import"
    bl_label = "读 arc 的 CCL"
    bl_description = "读取当前 arc 的 CCL 条目，填进自定义胶囊列表（之后可编辑/示意/回填）"

    def execute(self, context):
        from .MTframework_MHGU_ccl import find_ccl, parse_ccl
        from .MTframework_MHGU_phys import arc_entries
        sc = context.scene
        arc = sc.get('MT_ArcPath', '') or ''
        if not arc or not os.path.isfile(arc):
            self.report({'ERROR'}, '当前没有 arc 容器')
            return {'CANCELLED'}
        with open(arc, 'rb') as fh:
            entries = arc_entries(fh.read())
        e = find_ccl(entries)
        if e is None:
            self.report({'WARNING'}, '这个 arc 里没有 CCL 条目')
            return {'CANCELLED'}
        caps = parse_ccl(e['body'])
        _set_ccl_capsules(sc, caps)
        c = _ccl_panel_from(sc, caps, 0)
        n = _ccl_auto_refresh(context)
        self.report({'INFO'}, '已读入 %d 个胶囊（第一条：骨 %d→%d 半径 %.1f）%s'
                    % (len(caps), caps[0]['a'], caps[0]['b'], caps[0]['radius'],
                       '，示意已生成' if n > 0 else ''))
        return {'FINISHED'}

class MT_OT_CclCapsuleCheck(Operator):
    bl_idname = "mt_framework.ccl_capsule_check"
    bl_label = "检查胶囊"
    bl_description = ("写入前体检：骨 id 是否在玩家骨架 0~19、半径/偏移是否合理、"
                      "有没有重复骨对；导出的读回校验会用同一套判断")

    def execute(self, context):
        global _CCL_CHECK_TEXT
        sc = context.scene
        caps = _ccl_caps(sc)
        if not caps:
            _CCL_CHECK_TEXT = '没有自定义胶囊（导出会用自动 11 个身体胶囊）'
            self.report({'INFO'}, _CCL_CHECK_TEXT)
            return {'FINISHED'}
        try:
            from .MTframework_MHGU_verify import capsule_warnings
            warns, summary = capsule_warnings(caps)
        except Exception as e:
            warns, summary = ['体检模块出错：%r' % (e,)], ''
        lens = [max(abs(float(c['end'][k]) - float(c['start'][k])) for k in range(3))
                for c in caps]
        note = '%s | 端点距离 %.1f~%.1f' % (summary, min(lens), max(lens))
        if warns:
            _CCL_CHECK_TEXT = '%s | %d 条警告' % (note, len(warns))
            self.report({'WARNING'}, note + '\n' + '\n'.join(warns[:6]))
        else:
            _CCL_CHECK_TEXT = note + ' | 通过'
            self.report({'INFO'}, _CCL_CHECK_TEXT)
        return {'FINISHED'}

class MT_OT_WeightsNormalize(Operator):
    bl_idname = "mt_framework.weights_normalize"
    bl_label = "权重归一化（删非骨骼组）"
    bl_description = ("把 mmd_edge_scale / mmd_vertex_order 这类非骨骼组删掉，"
                      "剩下的骨骼权重按顶点归一化到 1（导出后数值就与这里一致）")

    def execute(self, context):
        meshes = [o for o in context.selected_objects if o.type == 'MESH']
        arms = [o for o in context.scene.objects if o.type == 'ARMATURE']
        if not meshes:
            self.report({'ERROR'}, '先选中要处理的网格')
            return {'CANCELLED'}
        if not arms:
            self.report({'ERROR'}, '场景里没有骨架')
            return {'CANCELLED'}
        removed_total = 0
        renorm_total = 0
        avg_before = []
        avg_after = []
        for o in meshes:
            gnames = [g.name for g in o.vertex_groups]
            best, hit = None, -1
            for a in arms:
                h = len({b.name for b in a.data.bones} & set(gnames))
                if h > hit:
                    best, hit = a, h
            bones = {b.name for b in best.data.bones}
            drop = [n for n in gnames if n not in bones]
            for n in drop:
                try:
                    o.vertex_groups.remove(o.vertex_groups[n])
                except Exception:
                    pass
            removed_total += len(drop)
            idx = {g.index: g.name for g in o.vertex_groups}
            keep_names = set(idx.values())
            for v in o.data.vertices:
                ws = [(g.group, g.weight) for g in v.groups
                      if idx.get(g.group) in keep_names and g.weight > 1e-6]
                tot = sum(w for _, w in ws)
                if tot <= 0:
                    continue
                avg_before.append(tot)
                for gi, w in ws:
                    try:
                        o.vertex_groups[idx[gi]].add([v.index], w / tot, 'REPLACE')
                    except Exception:
                        pass
                avg_after.append(1.0)
                renorm_total += 1
        mb = sum(avg_before) / len(avg_before) if avg_before else 0.0
        self.report({'INFO'}, '删掉 %d 个非骨骼组；%d 个顶点重归一化（平均权重和 %.3f -> 1.000）'
                    % (removed_total, renorm_total, mb))
        return {'FINISHED'}

classes = [
    MTFrameworkProperties,
    MT_OT_ImportMod,
    MT_OT_ExportMod,
    MT_OT_ReplaceMainBody,
    MT_OT_CopyVGroups,
    MT_OT_PasteVGroups,
    MT_OT_ImportSBC,
    MT_OT_ImportADR,
    MT_OT_ImportEMS,
    MT_OT_RenameSelected,
    MT_OT_RefreshFilterLists,
    MT_OT_Diagnostic,
    MT_OT_PartTransplant,
    MT_OT_WeightsNormalize,
    MT_OT_CclCapsuleStep,
    MT_OT_CclReadBone,
    MT_OT_CclDragSync,
    MT_OT_CclCapsuleZero,
    MT_OT_CclCapsuleSwap,
    MT_OT_CclCapsuleLoad,
    MT_OT_CclCapsuleStore,
    MT_OT_CclCapsulePick,
    MT_OT_CclCapsuleImport,
    MT_OT_CclCapsuleCheck,
    MT_OT_CclPreview,
    MT_OT_CclFromPreview,
    MT_OT_CclPreviewClear,
    MT_OT_CclCapsuleAdd,
    MT_OT_CclCapsuleClear,
    MT_OT_CclCapsuleDel,
    MT_PT_MainPanel,
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.MT_Framework_Props = bpy.props.PointerProperty(type=MTFrameworkProperties)

    bpy.types.Scene.MT_PhysIter = IntProperty(
        name="CTC 解算迭代", default=1, min=1, max=3,
        description="写进 CTC 头 +52/+53；长/弯发束用 3 可减少被限位拉长")
    bpy.types.Scene.MT_CclEnable = BoolProperty(
        name="碰撞胶囊 CCL", default=False,
        description="导出 helm/hair 槽时写入 11 个身体胶囊，并把 CTC 组标志位打开 0x04"
                    "（头发/身体避让用；body 槽无效）")
    bpy.types.Scene.MT_TransplantKeepCtc = BoolProperty(
        name="保留物理 CTC", default=True)
    bpy.types.Scene.MT_TransplantSet = StringProperty(
        name="目标套号", default="")
    bpy.types.Scene.MT_TransplantGender = EnumProperty(
        name="目标性别", default='same',
        items=[('same', '跟随源', '沿用源 arc 的性别（f 女 / m 男）'),
               ('f', '女 f', '目标资源名与路径用 f_（female）'),
               ('m', '男 m', '目标资源名与路径用 m_（male）')])
    bpy.types.Scene.MT_TransplantOutDir = StringProperty(
        name="输出目录", subtype='DIR_PATH', default="")

    bpy.types.Scene.MT_CclRadius = FloatProperty(
        name="胶囊半径", default=10.0, min=0.1, max=10000.0,
        soft_min=1.0, soft_max=80.0,
        description="「加胶囊（选中骨）」用的半径（游戏单位，和 CCL 记录 +0x2C 同尺度）；"
                    "拖动滑块或滚轮改动会立即同步到视口示意",
        update=_ccl_prop_update)
    bpy.types.Scene.MT_CclCapsules = StringProperty(
        name="自定义碰撞胶囊", default="",
        description="JSON 列表：a/b 骨 id、start/end 骨骼局部坐标、radius；"
                    "非空时导出用它，为空用自动 11 个身体胶囊")
    bpy.types.Scene.MT_CclAutoSync = BoolProperty(
        name="拖动实时同步", default=True,
        description="在视口里移动/缩放胶囊示意时，面板数值与胶囊列表实时更新；"
                    "关掉只停数值回写，骨骼姿态跟随仍生效",
        update=_ccl_autosync_update)
    bpy.types.Scene.MT_CclAutoPreview = BoolProperty(
        name="自动更新示意", default=True,
        description="新增/修改/删除胶囊后，自动重建 CCL_Preview 视口示意")
    bpy.types.Scene.MT_CclBodyPick = BoolProperty(
        name="可选胶囊本体", default=False,
        description="关闭时胶囊体只显示不参与选择，A/B 圆环手柄可直接拖动；"
                    "打开后才能整体移动/缩放胶囊",
        update=_ccl_bodypick_update)
    bpy.types.Scene.MT_CclNewPending = BoolProperty(
        name="待新增胶囊", default=False,
        description="按过「A/B 取选中骨」后置位：面板数值只用于下一条新增，"
                    "不写回 MT_CclIndex 指向的旧胶囊")
    bpy.types.Scene.MT_CclIndex = IntProperty(
        name="胶囊序号", default=0, min=0,
        description="当前编辑的自定义胶囊序号（从 0 开始）；改动会自动读取该条数值",
        update=_ccl_index_update)
    bpy.types.Scene.MT_CclBoneA = IntProperty(
        name="起点骨 id", default=3, min=0, max=254,
        update=_ccl_prop_update)
    bpy.types.Scene.MT_CclBoneB = IntProperty(
        name="终点骨 id", default=3, min=0, max=254,
        update=_ccl_prop_update)
    bpy.types.Scene.MT_CclStart = FloatVectorProperty(
        name="起点偏移", size=3, default=(0.0, 0.0, 0.0), subtype='TRANSLATION',
        update=_ccl_prop_update)
    bpy.types.Scene.MT_CclEnd = FloatVectorProperty(
        name="终点偏移", size=3, default=(0.0, 0.0, 0.0), subtype='TRANSLATION',
        update=_ccl_prop_update)
    bpy.types.Scene.MT_PhysSegment = BoolProperty(
        name="骨段碰撞 ShapeObject=2", default=False,
        description="导出时把每个物理组除链尾外的节点 +6 设为 2（骨段），链尾 1，"
                    "CTC 头 +54=3；关掉完全不碰 CTC")
    bpy.types.Scene.MT_SkipHidden = BoolProperty(
        name="导出跳过隐藏网格", default=False,
        description="导出时跳过视口隐藏（hide_get / hide_viewport）的网格；"
                    "一个不剩也照常导出空模型")

    for _k, _label, _default in UI_SECTIONS:
        setattr(bpy.types.Scene, _k, BoolProperty(name=_label, default=_default))

def unregister():
    _ccl_unmount_handler()
    for _k in ('MT_TransplantKeepCtc', 'MT_TransplantSet',
               'MT_TransplantOutDir', 'MT_TransplantGender',
               'MT_CclRadius', 'MT_CclCapsules',
               'MT_PhysSegment', 'MT_SkipHidden'):
        try:
            delattr(bpy.types.Scene, _k)
        except Exception:
            pass
    for _k, _label, _default in UI_SECTIONS:
        try:
            delattr(bpy.types.Scene, _k)
        except Exception:
            pass
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.MT_Framework_Props

if __name__ == "__main__":
    register()
