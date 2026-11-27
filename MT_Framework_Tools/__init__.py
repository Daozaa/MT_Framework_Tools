bl_info = {
    "name": "MT_Framework_Tools",
    "author": "Daze",
    "version": (1, 4, 17),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > MTFramework",
    "description": "MHGU 模型、材质图集与物理制作工具",
    "warning": "",
    "doc_url": "",
    "category": "Import-Export",
}

__branch_items__ = ("deep_export_readback", "auto_ctc_params", "template_project_snapshot", "remove_capacity_simplify", "bone_tail_sidecar", "ui_resource_categories", "mmd_panel_default_closed", "mmd_texture_atlas", "uv_half_rounding_fix", "weight_fvf_guard")

def register():
    from . import MTframework_MHGU
    MTframework_MHGU.register()

def unregister():
    from . import MTframework_MHGU
    MTframework_MHGU.unregister()

if __name__ == "__main__":
    register()
