bl_info = {
    "name": "MT_Framework_Tools",
    "author": "Daze",
    "version": (1, 4, 10),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > MTFramework",
    "description": "1.4.10：CCL 预览按导出坐标换算偏移",
    "warning": "",
    "doc_url": "",
    "category": "Import-Export",
}

__branch__ = "mainline-1.4.10-20261122"
__branch_items__ = ("deep_export_readback", "auto_ctc_params", "template_project_snapshot", "remove_capacity_simplify", "bone_tail_sidecar", "ui_resource_categories", "mmd_panel_default_closed", "mmd_texture_atlas")

def register():
    from . import MTframework_MHGU
    MTframework_MHGU.register()

def unregister():
    from . import MTframework_MHGU
    MTframework_MHGU.unregister()

if __name__ == "__main__":
    register()
