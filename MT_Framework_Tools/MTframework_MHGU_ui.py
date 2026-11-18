# -*- coding: utf-8 -*-
"""
MT Framework MHGU - Blender UI 面板
====================================
对应原始 3ds Max 脚本的 ReHDModTool rollout (lines 405-6025)

包含:
- 导入/导出操作符 (MOD, SBC, ADR, EMS)
- 网格过滤工具 (LOD, MatID, FVF 过滤)
- 网格重命名工具
- 游戏修复选项
"""

import bpy
import os
import struct
from bpy.props import (
    StringProperty, BoolProperty, IntProperty, FloatProperty,
    EnumProperty, CollectionProperty
)
from bpy.types import Operator, Panel

# 标准 helm XFS（1097B，藏猎人原版头/头发；所有已验收 helm 的 XFS 逐字节相同）
# 跨部位导出到 helm 时自动补上，否则「头盔显示」和藏头功能都没法用。
_BMT_XFS_B64 = "WEZTABAAAQAiAAAAAAAAAAMAAACEAQAADAAAAIwAAADkAAAA0p7IZgMAAAA8AQAABgEEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAARQEAAAaRBAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAE4BAAABAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABBTRNxAgAAAFcBAAADAAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABjAQAAAqAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAG+UfcgIAAABrAQAABQACAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAdgEAAAUAAgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAEluZm9UeXBlAG1RdWFsaXR5AEluZm9MaXN0AG1BdXRvRGVsZXRlAG1wQXJyYXkAbURpc3BGbGFnMABtRGlzcEZsYWcxAAAAAAEAAACpAgAAAQAAAAAAAAABAAAAAgAAAAEAAAADAAEAjQIAAAEAAAAAIAAAAAUAAgAQAAAAAQAAAAD8AQAAAP+BBQADABAAAAABAAAAAPwBAAAA/4EFAAQAEAAAAAEAAAAA/AEAAAD/gQUABQAQAAAAAQAAAAD8AQAAAP+BBQAGABAAAAABAAAAAPwBAAAA/4EFAAcAEAAAAAEAAAAA/AEAAAD/gQUACAAQAAAAAQAAAAD8AQAAAP+BBQAJABAAAAABAAAAAPwBAAAA/4EFAAoAEAAAAAEAAAAA/AEAAAD/gQUACwAQAAAAAQAAAAD8AQAAAP+BBQAMABAAAAABAAAAAPwBAAAA/4EFAA0AEAAAAAEAAAAA/AEAAAD/gQUADgAQAAAAAQAAAAD8AQAAAP+BBQAPABAAAAABAAAAAPwBAAAA/4EFABAAEAAAAAEAAAAA/AEAAAD/gQUAEQAQAAAAAQAAAAD8AQAAAP+BBQASABAAAAABAAAAAPwBAAAA/4EFABMAEAAAAAEAAAAA/AEAAAD/gQUAFAAQAAAAAQAAAAD8AQAAAP+BBQAVABAAAAABAAAAAPwBAAAA/4EFABYAEAAAAAEAAAAA/AEAAAD/gQUAFwAQAAAAAQAAAAD8AQAAAP+BBQAYABAAAAABAAAAAPwBAAAA/4EFABkAEAAAAAEAAAAA/AEAAAD/gQUAGgAQAAAAAQAAAAD8AQAAAP+BBQAbABAAAAABAAAAAPwBAAAA/4EFABwAEAAAAAEAAAAA/AEAAAD/gQUAHQAQAAAAAQAAAAD8AQAAAP+BBQAeABAAAAABAAAAAPwBAAAA/4EFAB8AEAAAAAEAAAAA/AEAAAD/gQUAIAAQAAAAAQAAAAD8AQAAAP+BBQAhABAAAAABAAAAAPwBAAAA/4E="

# ============================================================
# 全局状态变量 (对应原始脚本的全局变量)
# ============================================================
# 这些变量在 MTframework_MHGU.py 中定义
# 我们在这里通过场景自定义属性来存储 UI 状态

def parse_mesh_name(obj_name):
    """从网格对象名解析 (index, fvf, lod, matid, group, display, type).

    名称格式:
        Mesh_<index>_<FVF>_LODx<lod>_MatID:<mat>_Group:<grp>_DisplayMode:<mode>_Type:<type>
    解析失败返回 None.
    """
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
    """
    更新网格过滤 (隐藏/显示)
    对应原始脚本 chkhl, chkh, ddMat, ddFVF, ddlod 的回调
    """
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

        # LOD 0 隐藏
        if hidelod0 and info["lod"] == "0":
            hide_obj = True

        # 退化线隐藏 (type == 4128)
        if hidedege and info["type"] == 4128:
            hide_obj = True

        # LOD 过滤
        if props.filter_lod != "All" and info["lod"] != props.filter_lod:
            hide_obj = True

        # MatID 过滤
        if props.filter_mat != "All" and info["matid"] != props.filter_mat:
            hide_obj = True

        # FVF 过滤
        if props.filter_fvf != "All" and info["fvf"] != props.filter_fvf:
            hide_obj = True

        obj.hide_set(hide_obj)
        obj.hide_viewport = hide_obj

def update_lod_dropdown(self, context):
    """更新 LOD 下拉列表"""
    update_mesh_filter(self, context)

def update_mat_dropdown(self, context):
    """更新 MatID 下拉列表"""
    update_mesh_filter(self, context)

def update_fvf_dropdown(self, context):
    """更新 FVF 下拉列表"""
    update_mesh_filter(self, context)

def collect_filter_values():
    """从场景中所有 Mesh_* 对象收集 (lods, mats, fvfs)."""
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
    """LOD 下拉列表 (动态)."""
    lods, _, _ = collect_filter_values()
    items = [("All", "All", "显示所有 LOD")]
    for lod in _sorted_numeric(lods):
        items.append((lod, "LOD " + lod, "LOD 级别 " + lod))
    return items

def mat_items_cb(self, context):
    """材质 ID 下拉列表 (动态)."""
    _, mats, _ = collect_filter_values()
    items = [("All", "All", "显示所有材质")]
    for mat in _sorted_numeric(mats):
        items.append((mat, "Mat " + mat, "材质 ID " + mat))
    return items

def fvf_items_cb(self, context):
    """FVF 下拉列表 (动态)."""
    _, _, fvfs = collect_filter_values()
    items = [("All", "All", "显示所有 FVF")]
    for fvf in sorted(fvfs):
        items.append((fvf, fvf, "FVF 格式 " + fvf))
    return items

def refresh_filter_lists(self, context):
    """
    刷新过滤下拉列表.

    下拉项现在由 lod_items_cb / mat_items_cb / fvf_items_cb 动态生成,
    这里只负责把当前选择重置为 "All" 并重新应用过滤.
    """
    props = context.scene.MT_Framework_Props
    lods, mats, fvfs = collect_filter_values()
    print("过滤列表: LOD={} MatID={} FVF={}".format(
        _sorted_numeric(lods), _sorted_numeric(mats), sorted(fvfs)))
    update_mesh_filter(self, context)

# ============================================================
# 场景属性组
# ============================================================

class MTFrameworkProperties(bpy.types.PropertyGroup):
    """MTFramework Tools 的场景属性"""

    # 游戏格式: 固定 MHGU, 不在界面里选 (内部保留, 供导入/导出调用)
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

    # 导入后自动居中 (便于与第三方模型对齐)
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

    # 导出时把所有分件都写成可见件（0xEFFF）
    all_visible: BoolProperty(
        name="所有分件都可见 (0xEFFF)",
        description="导出时把每个网格的 meshtype 都改成 0xEFFF（可见主件）。"
                    "原版 arc 里通常只有 1 件是 0xEFFF，其余是影子/低模(0xE4C0)、"
                    "深度 pass(0x0020) 等，游戏里不绘制；打开这个开关就能把它们当分层用。",
        default=False,
    )

    # 对称骨骼命名 (.l / .r)
    sym_bone_names: BoolProperty(
        name="骨骼对称命名 (.l / .r)",
        description="把镜像成对的骨骼与顶点组改名为 <基础名>.l / .r, 方便使用 "
                    "Blender 的 X 轴镜像 / 对称化 / 镜像修改器。"
                    "导出时会自动换算回原本的骨序号, 不影响导出的 .mod",
        default=True,
    )

    # 说明: 导出时固定翻转面朝向, 不再提供开关 (见 export 模块里的注释)。
    
    # 过滤选项
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
    
    # 过滤下拉列表 (动态从场景中的 Mesh_* 对象收集)
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
    
    # 重命名工具
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
    
    # 导出时合并位置重合顶点的法线 (消除 UV 接缝处的光影断层)
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

# ============================================================
# 操作符 (Operators)
# ============================================================
    # 跨部位移植（body -> arm/wst/leg/helm）
    MT_TransplantKeepCtc: BoolProperty(
        name="保留物理 CTC", default=True,
        description="把 body 的物理链一起复制到目标部位")
    MT_TransplantOutDir: StringProperty(
        name="输出目录", subtype='DIR_PATH', default="",
        description="留空 = 输出到当前 arc 所在目录")


class MT_OT_ImportMod(Operator):
    """导入 .mod 文件 (MHGU / Switch)"""
    bl_idname = "mt_framework.import_mod"
    bl_label = "导入 MOD"
    bl_description = "导入 .mod (MHGU / Switch)"
    
    filepath: StringProperty(subtype='FILE_PATH')
    # 文件浏览器只显示 .mod（导出产物是 .mod.new，也一并显示，方便回导验证）
    filter_glob: StringProperty(default="*.mod;*.new;*.arc", options={'HIDDEN'})

    def execute(self, context):
        if not self.filepath:
            return {'CANCELLED'}

        from .MTframework_MHGU_phys import _apply
        if not _apply(self, context, self.filepath):
            return {'CANCELLED'}
        refresh_filter_lists(self, context)
        # 新模型：清掉上一个模型遗留的材质改动，避免写进新 arc
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
    """导出 .mod 文件 (不覆盖原文件, 生成 .mod.new)"""
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

# 剪贴板存储顶点组名称
_clipboard_vgroups = []

# meshtype: .mod 分件的**类型**标记, 不是"主体"标记。
#   61439 (0xEFFF) = 可见的防具/模型件
#   58560 (0xE4C0) = 全身低模 (顶点极少但横跨全身, 疑似影子/内衬)
#   0 / 32 / 4128  = 辅助 / 退化件
def is_gu_mesh(obj):
    """判断是不是插件从 .mod 导入的网格 (名字里有 Type:NNNN 段)。"""
    return any(p.startswith('Type:') for p in obj.name.split('_'))

def pick_replace_pair(context):
    """从选中的物体里分出 (你的模型, 被替换的目标)。

    规则故意做得简单粗暴:
      * 选中两个网格  -> 一个是 .mod 分件就当目标, 另一个当你的模型
      * 认不出来      -> 活动物体 = 你的模型, 另一个 = 目标
    """
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

    # 认不出来就按"活动物体是你的模型"来分
    new = act if (act is not None and act in sel) else sel[0]
    rest = [o for o in sel if o is not new]
    return new, (rest[0] if rest else None)

class MT_OT_ReplaceMainBody(Operator):
    """把目标的名称与数据块名称换到你的模型上"""

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

        # 只换名字。**不动**父级 / matrix_parent_inverse / 骨架修改器 ——
        # 之前把目标的 matrix_parent_inverse 抄过来, 那个矩阵含缩放,
        # 贴到你的模型上就把它拉伸、位置也变了。而且这个功能本来也不需要绑定。
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
    """复制当前模型的顶点组名称到剪贴板"""
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
    """粘贴顶点组到选中的模型（不改变已有的顶点组）"""
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
    """导入 .sbc 碰撞文件"""
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
    """导入 .adr 门数据文件"""
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
    """导入 .ems 敌人出生数据文件"""
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
    """
    重命名选中的网格
    对应原始脚本 btn7 (lines 5997-6024)
    """
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
                    # 解析现有组件
                    mshHdr_lod = int(sName[3].split("x")[1]) if "x" in sName[3] else 0
                    mshHdr_matid = int(sName[4].split(":")[1]) if ":" in sName[4] else 0
                    mshHdr_grp = int(sName[5].split(":")[1]) if ":" in sName[5] else 0
                    mshHdr_mde = int(sName[6].split(":")[1]) if ":" in sName[6] else 0
                    mshHdr_type = int(sName[7].split(":")[1]) if ":" in sName[7] else 0
                    
                    # 根据模式替换
                    new_val = int(new_value)
                    if props.rename_mode == 'LOD':
                        mshHdr_lod = new_val
                    elif props.rename_mode == 'MAT':
                        mshHdr_matid = new_val
                    elif props.rename_mode == 'Group':
                        mshHdr_grp = new_val
                    elif props.rename_mode == 'Display':
                        mshHdr_mde = new_val
                    
                    # 构建新名称
                    obj.name = "Mesh_{}_{}_LODx{}_MatID:{}_Group:{}_DisplayMode:{}_Type:{}".format(
                        sName[1], sName[2],
                        mshHdr_lod, mshHdr_matid,
                        mshHdr_grp, mshHdr_mde, mshHdr_type
                    )
                    count += 1
                    
                except (IndexError, ValueError):
                    continue
        
        self.report({'INFO'}, "已重命名 {} 个网格".format(count))
        
        # 刷新过滤列表
        refresh_filter_lists(self, context)
        
        return {'FINISHED'}

class MT_OT_RefreshFilterLists(Operator):
    """刷新过滤下拉列表"""
    bl_idname = "mt_framework.refresh_filters"
    bl_label = "刷新过滤列表"
    bl_description = "从场景中所有 Mesh_* 对象重新收集过滤选项"
    
    def execute(self, context):
        refresh_filter_lists(self, context)
        self.report({'INFO'}, "过滤列表已刷新")
        return {'FINISHED'}

class MT_OT_Diagnostic(Operator):
    """诊断 - 打印场景信息到控制台"""
    bl_idname = "mt_framework.diagnostic"
    bl_label = "诊断"
    bl_description = "打印当前场景的模型/骨骼/顶点信息到控制台 (Window > Toggle System Console)"
    
    def execute(self, context):
        print("\n" + "=" * 60)
        print("MT Framework MHGU - 诊断信息")
        print("=" * 60)
        
        # 场景中的网格对象
        mesh_objs = [obj for obj in bpy.data.objects if obj.type == 'MESH' and obj.name.startswith('Mesh_')]
        print(f"\n网格对象数: {len(mesh_objs)}")
        for obj in mesh_objs:
            mesh = obj.data
            print(f"  {obj.name}:")
            print(f"    顶点: {len(mesh.vertices)}, 面: {len(mesh.polygons)}, UV层: {len(mesh.uv_layers)}")
            # 从名称中解析 FVF
            parts = obj.name.split('_')
            if len(parts) >= 3:
                print(f"    FVF: {parts[2]}")
            # 顶点组
            if obj.vertex_groups:
                print(f"    顶点组: {[vg.name for vg in obj.vertex_groups]}")
            # 自定义属性
            custom = {k: v for k, v in mesh.items() if not k.startswith('_')}
            if custom:
                print(f"    属性: {custom}")
        
        # 骨架 (Armature) 与骨骼
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

        # 蒙皮检测
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

        # 顶点坐标范围检测
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
        
        # 面异常检测
        print(f"\n面异常检测:")
        for obj in mesh_objs:
            mesh = obj.data
            for poly in mesh.polygons:
                for v in poly.vertices:
                    if v >= len(mesh.vertices):
                        print(f"  {obj.name}: 面引用了不存在的顶点 {v}")
                        break
        
        # UV 检测
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
        
        # 物理链自检（CTC 与骨骼链是否对得上）
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
        except Exception as _e:                          # noqa: BLE001
            print("  物理自检出错：%s" % _e)

        print("\n" + "=" * 60)
        print("诊断完成，请复制上方信息")
        print("=" * 60 + "\n")
        
        self.report({'INFO'}, "诊断信息已打印到控制台 (Window > Toggle System Console)")
        return {'FINISHED'}

# ============================================================
# UI 面板
# ============================================================

class MT_PT_MainPanel(Panel):
    """MT_Framework_Tools 工具主面板"""
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

        # ---------------- 标题 / 当前状态 ----------------
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

        # ---------------- 模型 ----------------
        if section('MT_UiIo', '模型', 'MESH_DATA', default=True):
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


        # ---------------- 贴图 ----------------
        if section('MT_UiTex', '贴图 (.tex)', 'IMAGE_DATA', default=False):
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

        # ---------------- 材质 ----------------
        if section('MT_UiPhys', '物理骨骼', 'BONE_DATA', default=False):
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
                        sub(pb, "物理参数（当前 CTC）", 'PHYSICS')
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
                    sub(xb, "自定义物理骨", 'OUTLINER_OB_ARMATURE')
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
                    except Exception:                   # noqa: BLE001
                        pass

                    # ---- 解算迭代（长/弯发束）----
                    xb = layout.box()
                    sub(xb, "解算迭代（长头发 / 弯发束）", 'MOD_PHYSICS')
                    xb.prop(scn, 'MT_PhysIter', text="迭代次数")

                    # ---- 碰撞胶囊 CCL（2026-11-17 实机验证的做法）----
                    xb = layout.box()
                    sub(xb, "碰撞胶囊 CCL（头发↔身体避让）", 'MOD_PHYSICS')
                    xb.prop(scn, 'MT_CclEnable',
                            text="导出时写入身体胶囊（11 个，自动开 CTC 碰撞位）")
                    try:
                        from .MTframework_MHGU_phys import arc_entries as _arc_entries
                        from .MTframework_MHGU_ccl import parse_ccl as _parse_ccl, find_ccl as _find_ccl
                        _ap = scn.get('MT_ArcPath', '') or ''
                        if _ap and os.path.exists(_ap):
                            with open(_ap, 'rb') as _fh:
                                _e7 = _arc_entries(_fh.read())
                            _ce = _find_ccl(_e7)
                            if _ce is not None:
                                _caps = _parse_ccl(_ce['body'])
                                xb.label(text="当前 arc 已有 CCL：%d 个胶囊" % len(_caps),
                                         icon='CHECKMARK')
                            else:
                                xb.label(text="当前 arc 没有 CCL 条目", icon='INFO')
                    except Exception:                   # noqa: BLE001
                        pass
                    # ★ 1.2.197：自定义胶囊（MT_CclCapsules，JSON）—— 非空时导出用它
                    try:
                        from .MTframework_MHGU_ccl import capsules_from_json as _caps_json
                        _n_custom = len(_caps_json(getattr(scn, 'MT_CclCapsules', '') or ''))
                    except Exception:                   # noqa: BLE001
                        _n_custom = 0
                    xb.label(text="自定义胶囊 %d 个 / 自动 11 个" % _n_custom,
                             icon=('CHECKMARK' if _n_custom else 'INFO'))
                    row = xb.row(align=True)
                    row.prop(scn, 'MT_CclRadius', text='半径')
                    row = xb.row(align=True)
                    row.operator('mt_framework.ccl_capsule_add',
                                 text='加选中骨', icon='ADD')
                    row.operator('mt_framework.ccl_capsule_del',
                                 text='删最后一个', icon='REMOVE')
                    row.operator('mt_framework.ccl_capsule_clear',
                                 text='清空', icon='X')

                    # ---- 骨段碰撞 ShapeObject=2（1.2.197）----
                    xb = layout.box()
                    sub(xb, "骨段碰撞（ShapeObject=2）", 'MOD_PHYSICS')
                    xb.prop(scn, 'MT_PhysSegment', text="链节用骨段碰撞（链尾仍是点）")
            except Exception as _e:
                box = layout.box()
                box.label(text="物理面板出错: %s: %s" % (type(_e).__name__, _e), icon='ERROR')

        # ---------------- 头盔显示 ----------------
        if section('MT_UiHelm', '头盔显示', 'MESH_CIRCLE', default=False):
            try:
                box = layout.box()
                sub(box, "helm arc 的 XFS disp0 / disp1")
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
                # ★ 1.2.193 随从猫藏头（otomo 的 XFS 是另一套位，玩家预设无效）
                col = box.column(align=True)
                col.separator()
                col.label(text="随从猫藏头（otomo h.arc / b.arc）", icon='BONE_DATA')
                r2 = col.row(align=True)
                r2.operator("mt_framework.cat_hide_head", text="猫·藏头")
                r2.operator("mt_framework.cat_hide_head2", text="猫·藏头+耳")
                r2.operator("mt_framework.cat_show_head", text="猫·不藏")
            except Exception as _e:
                box = layout.box()
                box.label(text="头盔面板出错: %s: %s" % (type(_e).__name__, _e), icon='ERROR')

        # ---------------- 顶点组 ----------------
        if section('MT_UiVtx', '顶点组 / 名称', 'GROUP_BONE', default=True):
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

        # ---------------- 导入设置 ----------------
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

        # ---------------- 工具 ----------------
        tl = layout.box()
        row = tl.row(align=True)
        if hasattr(ops, 'diagnostic'):
            row.operator("mt_framework.diagnostic", text="诊断", icon='CONSOLE')
        if hasattr(ops, 'refresh_filters'):
            row.operator("mt_framework.refresh_filters", text="刷新过滤", icon='FILE_REFRESH')
# ============================================================
# 注册
# ============================================================

#: 面板各分区的折叠开关（顺序 = 面板从上到下的顺序）
UI_SECTIONS = (
    ('MT_UiIo', "模型", True),
    ('MT_UiTex', "贴图 (.tex)", False),
    ('MT_UiPhys', "物理骨骼", False),
    ('MT_UiHelm', "头盔显示", False),
    ('MT_UiVtx', "顶点组 / 名称", True),
    ('MT_UiSet', "导入设置", False),
)

class MT_OT_PartTransplant(Operator):
    """把当前工程里做好的模型导出，并打包成目标部位的 arc

    以前是复制“导入时的原版 arc”，工程里改的模型不会生效；
    现在改为先用正常导出管线导出当前工程，再替换目标 arc 里的 .mod。
    """
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

        # 1) 用正常导出管线，把**当前工程**导出成临时 .mod
        tmpdir = tempfile.mkdtemp(prefix='mt_transplant_')
        tmp_mod = os.path.join(tmpdir, 'export.mod')
        # 导出只写「选中的网格」；跨部位导出要的是整个工程 → 临时全选
        prev_sel = [o for o in context.selected_objects]
        prev_active = context.view_layer.objects.active
        # 和直接导出保持一致：有选中网格就只导选中的；没选中才退回全部可见网格
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
                except Exception:                       # noqa: BLE001
                    pass
            if meshes:
                context.view_layer.objects.active = meshes[0]
            out_mod = _export(self, context, tmp_mod)
        except Exception as e:                          # noqa: BLE001
            self.report({'ERROR'}, '导出当前工程失败：%s' % e)
            return {'CANCELLED'}
        finally:
            try:
                bpy.ops.object.select_all(action='DESELECT')
                for o in prev_sel:
                    try:
                        o.select_set(True)
                    except Exception:                   # noqa: BLE001
                        pass
                context.view_layer.objects.active = prev_active
            except Exception:                           # noqa: BLE001
                pass
        if not out_mod or not os.path.exists(out_mod):
            self.report({'ERROR'}, '导出当前工程失败（没有生成 .mod）')
            return {'CANCELLED'}
        try:
            with open(out_mod, 'rb') as f:
                new_mod = f.read()
        except Exception as e:                          # noqa: BLE001
            self.report({'ERROR'}, '读取临时 .mod 失败：%s' % e)
            return {'CANCELLED'}
        if new_mod[:4] != MOD_MAGIC:
            self.report({'ERROR'}, '导出的不是 .mod（文件头不对）')
            return {'CANCELLED'}

        # 2) 容器 arc 提供 TEX/MRL 等条目；替换其中 .mod
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
        # 目标性别：same = 跟随源（f 女 / m 男）；f/m = 跨性别移植
        gender = src_gender if self.target_gender in ('', 'same') else self.target_gender
        tgt = '%s_%s%s' % (gender, self.target_part, digits)
        # 跨防具：内部资源路径里的 plNNN 目录也要换成目标套号
        _plm = re.search(r'\\pl(\d+)\\', mod_e['name'])
        src_pl = ('pl' + _plm.group(1)) if _plm else None
        tgt_pl = 'pl' + digits

        def _rename_path(path):
            if src_pl and src_pl != tgt_pl:
                path = path.replace('\\%s\\' % src_pl, '\\%s\\' % tgt_pl)
            if gender != src_gender:
                # player\mod\f\plNNN / player\com\f\NNN 这类目录里的性别段
                for _p in ('\\mod\\', '\\com\\'):
                    path = path.replace(_p + src_gender + '\\', _p + gender + '\\')
                # 共用目录里的性别贴图：common\f_skin_BM -> common\m_skin_BM
                path = path.replace('\\common\\%s_' % src_gender,
                                    '\\common\\%s_' % gender)
            return path

        # 物理 CTC：优先用场景里当前工程的，其次用容器的
        ctc = None
        try:
            _a, ctc = recalled_arc(context)
        except Exception:                               # noqa: BLE001
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
            """mrl 贴图路径是 0x28 起、每条 76B（12B 头 + 64B 定长名）的字段。"""
            b = bytearray(body)
            try:
                cnt = struct.unpack_from('<I', b, 0x0C)[0]
            except Exception:                           # noqa: BLE001
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
                # 共用目录里的性别条目（common\f_skin_BM 等）也要跟着换性别
                name = _rename_path(name)
            raw = zlib.compress(body, 9)
            flag = (e['flag'] & 0xFF000000) | (len(body) & 0xFFFFFF)
            out_entries.append(dict(name=name, hash=e['hash'],
                                    flag=flag, raw=raw, body=body))
        # helm 必须有 XFS（藏头/头盔显示）；源工程是 body 时没有，自动补标准 XFS
        if (self.target_part == 'helm' and mod_name is not None
                and not any(e['body'][:4] == b'XFS\x00' for e in out_entries)):
            _xfs = base64.b64decode(_BMT_XFS_B64)
            out_entries.append(dict(
                name=mod_name, hash=0x66C89ED2,
                flag=(0x40000000 | (len(_xfs) & 0xFFFFFF)),
                raw=zlib.compress(_xfs, 9), body=_xfs))

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

        # 3) 输出目录
        raw_dir = (self.out_dir or '').strip().strip('"')
        if raw_dir:
            out_dir = os.path.normpath(bpy.path.abspath(raw_dir))
        else:
            out_dir = os.path.dirname(arc_path)
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception as e:                          # noqa: BLE001
            self.report({'ERROR'}, '输出目录无法创建：%s（%s）' % (out_dir, e))
            return {'CANCELLED'}

        dst = os.path.join(out_dir, '%s.arc' % self.target_part)
        arc_bytes = arc_build(out_entries)
        with open(dst, 'wb') as f:
            f.write(arc_bytes)
        self.report({'INFO'}, '已从当前工程导出：%s（%d 骨）'
                    % (dst, struct.unpack_from('<H', new_mod, 6)[0]))
        return {'FINISHED'}

# ============================================================
# 碰撞胶囊自定义（1.2.197）
# ============================================================
def _ccl_bone_game_id(name, index):
    """骨名 -> 游戏骨 id：本项目约定 b_<N> => N-1。

    带 .l/.r 后缀或改过名的骨「按名字取不到」（同一个 N 会对应左右两根），
    按骨架顺序 0 基兜底。
    """
    import re
    m = re.match(r'^b_(\d+)$', name or '')
    if m:
        return int(m.group(1)) - 1
    return index


def _ccl_selected_bones(context):
    """返回 (骨架, [(骨名, 游戏骨 id)])，按骨架顺序排列（两根时「第一根」= 靠前的）。"""
    from .MTframework_MHGU_phys import _phys_armature
    arm = _phys_armature(context)
    if arm is None:
        return None, []
    names = []
    try:
        for pb in (context.selected_pose_bones or []):
            if pb is not None and pb.bone is not None and pb.bone.name not in names:
                names.append(pb.bone.name)
    except Exception:                                   # noqa: BLE001
        pass
    if not names:
        try:
            for eb in arm.data.edit_bones:
                if eb.select:
                    names.append(eb.name)
        except Exception:                               # noqa: BLE001
            pass
    if not names:
        for b in arm.data.bones:
            try:
                if b.select:
                    names.append(b.name)
            except Exception:                           # noqa: BLE001
                pass
    order = {b.name: i for i, b in enumerate(arm.data.bones)}
    names.sort(key=lambda n: order.get(n, 1 << 30))
    return arm, [(n, _ccl_bone_game_id(n, order.get(n, 0))) for n in names]


def _set_ccl_capsules(scene, capsules):
    from .MTframework_MHGU_ccl import capsules_to_json
    txt = capsules_to_json(capsules)
    try:
        scene.MT_CclCapsules = txt
    except Exception:                                   # noqa: BLE001
        scene['MT_CclCapsules'] = txt


class MT_OT_CclCapsuleAdd(Operator):
    """把骨架里选中的骨加成一个碰撞胶囊（1 根 = 单球，2 根 = 骨A→骨B）"""
    bl_idname = "mt_framework.ccl_capsule_add"
    bl_label = "加胶囊（选中骨）"
    bl_description = "选中 1~2 根骨后点：加一条自定义胶囊（导出 helm/hair 时写进 CCL）"

    def execute(self, context):
        from .MTframework_MHGU_ccl import capsules_from_json
        sc = context.scene
        arm, bones = _ccl_selected_bones(context)
        if arm is None:
            self.report({'ERROR'}, '场景里没有骨架')
            return {'CANCELLED'}
        if not bones:
            self.report({'ERROR'}, '先在骨架里选中 1~2 根骨（物体模式/姿态模式都行）')
            return {'CANCELLED'}
        if len(bones) > 2:
            self.report({'WARNING'}, '选中的骨超过 2 根，只用前 2 根：%s'
                        % '、'.join(n for n, _ in bones[:2]))
            bones = bones[:2]
        try:
            radius = float(getattr(sc, 'MT_CclRadius', 10.0) or 0.0)
        except Exception:                               # noqa: BLE001
            radius = 10.0
        caps = capsules_from_json(getattr(sc, 'MT_CclCapsules', '') or '')
        a, b = bones[0][1], bones[-1][1]
        caps.append({'a': a, 'b': b, 'start': (0.0, 0.0, 0.0),
                     'end': (0.0, 0.0, 0.0), 'radius': radius})
        _set_ccl_capsules(sc, caps)
        self.report({'INFO'}, '已加胶囊：%s(骨 id %d) → %s(骨 id %d)，半径 %.2f；共 %d 个'
                    % (bones[0][0], a, bones[-1][0], b, radius, len(caps)))
        return {'FINISHED'}


class MT_OT_CclCapsuleClear(Operator):
    """清空自定义碰撞胶囊"""
    bl_idname = "mt_framework.ccl_capsule_clear"
    bl_label = "清空胶囊"
    bl_description = "清空 MT_CclCapsules（导出退回自动 11 个身体胶囊）"

    def execute(self, context):
        _set_ccl_capsules(context.scene, [])
        self.report({'INFO'}, '已清空自定义胶囊（导出用自动 11 个）')
        return {'FINISHED'}


class MT_OT_CclCapsuleDel(Operator):
    """删掉最后一个自定义碰撞胶囊"""
    bl_idname = "mt_framework.ccl_capsule_del"
    bl_label = "删最后一个胶囊"
    bl_description = "删掉自定义胶囊列表的最后一个"

    def execute(self, context):
        from .MTframework_MHGU_ccl import capsules_from_json
        sc = context.scene
        caps = capsules_from_json(getattr(sc, 'MT_CclCapsules', '') or '')
        if not caps:
            self.report({'WARNING'}, '没有自定义胶囊可删')
            return {'CANCELLED'}
        caps.pop()
        _set_ccl_capsules(sc, caps)
        self.report({'INFO'}, '已删掉最后一个胶囊，还剩 %d 个' % len(caps))
        return {'FINISHED'}


class MT_OT_WeightsNormalize(Operator):
    """删掉非骨骼顶点组，并把每个顶点的骨骼权重归一化到 1"""
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
                except Exception:                       # noqa: BLE001
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
                    except Exception:                   # noqa: BLE001
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
    MT_OT_CclCapsuleAdd,
    MT_OT_CclCapsuleClear,
    MT_OT_CclCapsuleDel,
    MT_PT_MainPanel,
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.MT_Framework_Props = bpy.props.PointerProperty(type=MTFrameworkProperties)
    # 跨部位移植的界面开关（放 Scene 上，面板直接引用）
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
    # ★ 1.2.197：自定义碰撞胶囊 / 骨段碰撞 / 导出跳过隐藏网格
    bpy.types.Scene.MT_CclRadius = FloatProperty(
        name="胶囊半径", default=10.0, min=0.0, max=10000.0,
        description="「加胶囊（选中骨）」用的半径（游戏单位，和 CCL 记录 +0x2C 同尺度）")
    bpy.types.Scene.MT_CclCapsules = StringProperty(
        name="自定义碰撞胶囊", default="",
        description="JSON 列表：a/b 骨 id、start/end 骨骼局部坐标、radius；"
                    "非空时导出用它，为空用自动 11 个身体胶囊")
    bpy.types.Scene.MT_PhysSegment = BoolProperty(
        name="骨段碰撞 ShapeObject=2", default=False,
        description="导出时把每个物理组除链尾外的节点 +6 设为 2（骨段），链尾 1，"
                    "CTC 头 +54=3；关掉完全不碰 CTC")
    bpy.types.Scene.MT_SkipHidden = BoolProperty(
        name="导出跳过隐藏网格", default=False,
        description="导出时跳过视口隐藏（hide_get / hide_viewport）的网格；"
                    "一个不剩也照常导出空模型")
    # 面板各分区的折叠状态
    for _k, _label, _default in UI_SECTIONS:
        setattr(bpy.types.Scene, _k, BoolProperty(name=_label, default=_default))

def unregister():
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
