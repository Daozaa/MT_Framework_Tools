# -*- coding: utf-8 -*-
"""
跨版本兼容层 (Blender 2.93 / 3.0 / 3.x / 4.x / 5.x)
==================================================

本插件的目标基准版本是 **Blender 3.0**, 同时兼容更新的版本.
Blender 在 4.x 之后改动了不少 API, 这里统一做兼容封装, 避免在旧版本上报错:

* ``Mesh.use_auto_smooth``        4.1 起移除
* ``Mesh.calc_normals_split()``   4.1 起移除 (法线改为自动按需计算)
* Principled BSDF 的插槽改名:    3.x 用 ``Emission``, 4.0+ 用 ``Emission Color``
* ``Material.blend_method``       4.2 起改为 ``surface_render_method``
"""

import bpy

# ---------------------------------------------------------------- 版本判断
def _ver():
    try:
        return tuple(bpy.app.version[:3])
    except Exception:
        return (3, 0, 0)

BLENDER_VERSION = _ver()
# ---------------------------------------------------------------- 对象
def iter_children(obj):
    """返回 obj 的所有后代对象 (跨版本).

    ``Object.children_recursive`` 是 **Blender 3.1** 才加入的属性,
    在 3.0 上不存在, 因此这里自己递归, 保证 3.0 也能用.
    """
    out = []
    stack = list(getattr(obj, "children", ()) or ())
    seen = set()
    while stack:
        child = stack.pop()
        if child is None or child.name in seen:
            continue
        seen.add(child.name)
        out.append(child)
        stack.extend(list(getattr(child, "children", ()) or ()))
    return out

# ---------------------------------------------------------------- 网格
def calc_normals_split(mesh):
    """旧版本的拆分法线计算. 4.1+ 不需要, 静默跳过."""
    try:
        mesh.calc_normals_split()
        return True
    except Exception:
        return False

def set_auto_smooth(mesh, value=True):
    """设置自动平滑 (4.1+ 已移除该属性, 旧版本才有效)."""
    try:
        mesh.use_auto_smooth = value
        return True
    except Exception:
        return False

# ---------------------------------------------------------------- 材质
def get_principled(material):
    """找到材质里的 Principled BSDF 节点 (不依赖节点名称)."""
    if not material or not material.use_nodes or not material.node_tree:
        return None
    for node in material.node_tree.nodes:
        if node.type == 'BSDF_PRINCIPLED':
            return node
    # 有些版本节点名固定为 "Principled BSDF"
    try:
        return material.node_tree.nodes.get("Principled BSDF")
    except Exception:
        return None

def set_bsdf_input(bsdf, names, value):
    """按候选名字依次尝试设置 BSDF 插槽; 名字不存在则跳过.

    不同 Blender 版本插槽名不同 (例如 3.x 的 ``Emission`` ↔ 4.0+ 的
    ``Emission Color``), 因此这里传入候选名列表.
    """
    if bsdf is None:
        return False
    if isinstance(names, str):
        names = (names,)
    for name in names:
        try:
            sock = bsdf.inputs.get(name)
        except Exception:
            sock = None
        if sock is not None:
            try:
                sock.default_value = value
                return True
            except Exception:
                pass
    return False

def set_material_blend(material, alpha=None):
    """设置材质透明混合 (跨版本)."""
    if material is None:
        return
    if alpha is not None:
        bsdf = get_principled(material)
        set_bsdf_input(bsdf, ("Alpha",), float(alpha))
    # 3.x / 4.0 / 4.1 用 blend_method
    try:
        material.blend_method = 'BLEND'
    except Exception:
        pass
    # 4.2+ 用 surface_render_method
    try:
        material.surface_render_method = 'BLENDED'
    except Exception:
        pass

def make_simple_material(name, rgba, alpha=None):
    """创建一个用 Principled BSDF 上色的简单材质 (跨版本)."""
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = get_principled(mat)
    set_bsdf_input(bsdf, ("Base Color",), rgba)
    if alpha is not None:
        set_material_blend(mat, alpha)
    return mat, bsdf
