bl_info = {
    "name": "MT_Framework_Tools",
    "author": "Daze",
    "version": (1, 2, 202),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > MTFramework",
    "description": "",
    "warning": "",
    "doc_url": "",
    "category": "Import-Export",
}

def register():
    from . import MTframework_MHGU
    MTframework_MHGU.register()

def unregister():
    from . import MTframework_MHGU
    MTframework_MHGU.unregister()

if __name__ == "__main__":
    register()
