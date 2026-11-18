# -*- coding: utf-8 -*-
"""
MT Framework Model Importer/Exporter for Blender
================================================

支持 MT Framework 引擎的 .mod 文件格式

游戏支持 (PC/Console):
- Monster Hunter Generations Ultimate (Switch)
- Devil May Cry 4 Special Edition
- Lost Planet 2
- Dragon's Dogma
- Resident Evil 0/1/2/6/7
- RE Revelations 1/2

Blender 版本要求: 3.0+ (同时兼容 4.x / 5.x)
"""

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
    """注册插件"""
    from . import MTframework_MHGU
    MTframework_MHGU.register()

def unregister():
    """注销插件"""
    from . import MTframework_MHGU
    MTframework_MHGU.unregister()

if __name__ == "__main__":
    register()
