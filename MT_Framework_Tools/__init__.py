bl_info = {
    "name": "MT_Framework_Tools",
    "author": "Daze",
    "version": (1, 3, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > MTFramework",
    "description": "1.3.0：模板随工程自愈 / 自动初值重力全0 / 预设收敛 / 骨骼尾端 sidecar / 面板按资源类型分类 / MMD 面板默认收起",
    "warning": "",
    "doc_url": "",
    "category": "Import-Export",
}

__branch__ = "mainline-1.3.0-20261120"
__branch_items__ = ("deep_export_readback", "auto_ctc_params", "template_project_snapshot", "remove_capacity_simplify", "bone_tail_sidecar", "ui_resource_categories", "mmd_panel_default_closed")

def register():
    from . import MTframework_MHGU
    MTframework_MHGU.register()

def unregister():
    from . import MTframework_MHGU
    MTframework_MHGU.unregister()

if __name__ == "__main__":
    register()
