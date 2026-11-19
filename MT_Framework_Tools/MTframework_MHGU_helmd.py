from __future__ import annotations

import base64
import os
import struct

try:
    import bpy
    from bpy.props import EnumProperty, IntProperty
    from bpy.types import Operator
except Exception:
    bpy = None

XFS_MAGIC = b'XFS\x00'
REC_SZ = 20
TAIL_SZ = 640
DISP0_OFF = 12
DISP1_OFF = 18

PRESETS = {
    'show_all':  ("全部显示", 0xFFFF, 0xFFFF),
    'face_only': ("只露脸",   0xFC01, 0xFFFF),
    'hide_all':  ("全藏头",   0xFC00, 0x81FF),
}

CAT_PRESETS = {
    'cat_hide1': ("猫·藏头（藏 1 件）",   0xFFFE, 0xFFFF),
    'cat_hide2': ("猫·藏头+耳（藏 2 件）", 0xFFFE, 0xFFFD),
    'cat_show':  ("猫·不藏（原样）",     0xFFFF, 0xFFFF),
}

def is_otomo_arc(context):
    try:
        p = context.scene.get('MT_ArcPath', '') or ''
    except Exception:
        p = ''
    p = p.replace('/', '\\').lower()
    return '\\otomo\\' in p or p.endswith('otomo') or '\\otomo\\mod\\' in p

def _find_xfs(entries):
    for e in entries:
        if e['body'][:4] == XFS_MAGIC:
            return e
    return None

def arc_xfs(context):
    from .MTframework_MHGU_phys import arc_entries
    arc = context.scene.get('MT_ArcPath', '') or ''
    if not arc or not os.path.exists(arc):
        return None
    with open(arc, 'rb') as f:
        data = f.read()
    if data[:4] != b'ARC\x00':
        return None
    e = _find_xfs(arc_entries(data))
    return e['body'] if e else None

def _rec_start(size):
    if size >= TAIL_SZ and (size - TAIL_SZ) % REC_SZ == 0:
        return size - TAIL_SZ
    if size >= REC_SZ and size % REC_SZ == 0:
        return 0
    return size - TAIL_SZ if size > TAIL_SZ else 0

def read_disp(xfs):
    start = _rec_start(len(xfs))
    n = max(0, (len(xfs) - start) // REC_SZ)
    vals = set()
    for i in range(n):
        o = start + i * REC_SZ
        vals.add((struct.unpack_from('<H', xfs, o + DISP0_OFF)[0],
                  struct.unpack_from('<H', xfs, o + DISP1_OFF)[0]))
    if not vals:
        raise ValueError('XFS 里没有记录')
    v0, v1 = sorted(vals)[0]
    return v0, v1, n, len(vals) > 1

def write_disp(xfs, disp0, disp1):
    b = bytearray(xfs)
    start = _rec_start(len(b))
    n = max(0, (len(b) - start) // REC_SZ)
    for i in range(n):
        o = start + i * REC_SZ
        struct.pack_into('<H', b, o + DISP0_OFF, int(disp0) & 0xFFFF)
        struct.pack_into('<H', b, o + DISP1_OFF, int(disp1) & 0xFFFF)
    return bytes(b), n

def get_modified_xfs(context):
    b64 = context.scene.get('MT_ArcXfs', '') or ''
    return base64.b64decode(b64) if b64 else b''

def set_modified_xfs(context, data):
    context.scene['MT_ArcXfs'] = base64.b64encode(data).decode('ascii')

def clear_modified_xfs(context):
    context.scene['MT_ArcXfs'] = ''

if bpy is not None:

    def _register_props():
        S = bpy.types.Scene
        S.MT_HelmPreset = EnumProperty(
            name="显示预设",
            items=[(k, v[0], '') for k, v in PRESETS.items()],
            default='hide_all')
        S.MT_HelmDisp0 = IntProperty(name="disp0", default=0xFC00,
                                     min=0, max=0xFFFF)
        S.MT_HelmDisp1 = IntProperty(name="disp1", default=0x81FF,
                                     min=0, max=0xFFFF)

    def _unregister_props():
        for k in ('MT_HelmPreset', 'MT_HelmDisp0', 'MT_HelmDisp1'):
            try:
                delattr(bpy.types.Scene, k)
            except Exception:
                pass

    class MT_OT_HelmRead(Operator):
        bl_idname = "mt_framework.helm_disp_read"
        bl_label = "读取显示标志"
        bl_description = "从当前 arc 的 XFS 里读出 disp0 / disp1"

        def execute(self, context):
            xfs = get_modified_xfs(context) or arc_xfs(context)
            if not xfs:
                self.report({'ERROR'}, '当前 arc 里没有 XFS（是不是没导入 helm？）')
                return {'CANCELLED'}
            try:
                v0, v1, n, mixed = read_disp(xfs)
            except Exception as e:
                self.report({'ERROR'}, str(e))
                return {'CANCELLED'}
            context.scene.MT_HelmDisp0 = v0
            context.scene.MT_HelmDisp1 = v1
            self.report({'INFO'}, '%d 条记录，disp0=0x%04X disp1=0x%04X%s'
                        % (n, v0, v1, '（记录间不一致，取最小值）' if mixed else ''))
            return {'FINISHED'}

    class MT_OT_HelmApply(Operator):
        bl_idname = "mt_framework.helm_disp_apply"
        bl_label = "应用显示标志"
        bl_description = "把 disp0 / disp1 写入所有记录；导出 .arc 时生效"

        def execute(self, context):
            sc = context.scene
            xfs = get_modified_xfs(context) or arc_xfs(context)
            if not xfs:

                from .MTframework_MHGU_ui import _BMT_XFS_B64
                xfs = base64.b64decode(_BMT_XFS_B64)
            try:
                new, n = write_disp(xfs, sc.MT_HelmDisp0, sc.MT_HelmDisp1)
            except Exception as e:
                self.report({'ERROR'}, str(e))
                return {'CANCELLED'}
            set_modified_xfs(context, new)
            self.report({'INFO'},
                        '已写入 %d 条记录：disp0=0x%04X disp1=0x%04X%s'
                        % (n, sc.MT_HelmDisp0, sc.MT_HelmDisp1,
                           '' if arc_xfs(context) else '（当前 arc 无 XFS：已记为待写入，'
                           '跨部位导出到 helm 时生效）'))
            return {'FINISHED'}

    class MT_OT_HelmPreset(Operator):
        bl_idname = "mt_framework.helm_disp_preset"
        bl_label = "套用预设"
        bl_description = "按预设设置 disp0 / disp1 并写入"

        def execute(self, context):
            sc = context.scene
            row = PRESETS.get(sc.MT_HelmPreset)
            if row is None:
                self.report({'ERROR'}, '未知预设')
                return {'CANCELLED'}
            if is_otomo_arc(context):
                self.report({'WARNING'},
                            '这是随从猫的 arc：玩家那套藏头位（0xFC00/0x81FF）在猫身上不生效，'
                            '请用「猫·藏头 / 猫·藏头+耳 / 猫·不藏」')
            sc.MT_HelmDisp0 = row[1]
            sc.MT_HelmDisp1 = row[2]
            return bpy.ops.mt_framework.helm_disp_apply()

    def _cat_apply(operator, context, disp0, disp1):
        xfs = get_modified_xfs(context) or arc_xfs(context)
        if not xfs:
            operator.report({'ERROR'},
                            '当前 arc 里没有 XFS（要先选/导入 otomo 的 h.arc 或 b.arc）')
            return {'CANCELLED'}
        try:
            new, n = write_disp(xfs, disp0, disp1)
        except Exception as e:
            operator.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        set_modified_xfs(context, new)
        sc = context.scene
        sc.MT_HelmDisp0 = disp0
        sc.MT_HelmDisp1 = disp1
        operator.report({'INFO'},
                        '随从猫藏头已写入 %d 条记录：disp0=0x%04X disp1=0x%04X'
                        '（导出 .arc 时生效）' % (n, disp0, disp1))
        return {'FINISHED'}

    class MT_OT_CatHideHead(Operator):
        bl_idname = "mt_framework.cat_hide_head"
        bl_label = "猫·藏头"
        bl_description = "把当前 otomo arc 的 XFS 写成 FFFE/FFFF，藏掉猫的头（导出 arc 时生效）"

        def execute(self, context):
            return _cat_apply(self, context, CAT_PRESETS['cat_hide1'][1], CAT_PRESETS['cat_hide1'][2])

    class MT_OT_CatHideHead2(Operator):
        bl_idname = "mt_framework.cat_hide_head2"
        bl_label = "猫·藏头+耳"
        bl_description = "把当前 otomo arc 的 XFS 写成 FFFE/FFFD（藏 2 件，部分头防具用这个）"

        def execute(self, context):
            return _cat_apply(self, context, CAT_PRESETS['cat_hide2'][1], CAT_PRESETS['cat_hide2'][2])

    class MT_OT_CatShowHead(Operator):
        bl_idname = "mt_framework.cat_show_head"
        bl_label = "猫·不藏"
        bl_description = "把 XFS 恢复成 FFFF/FFFF（身体模型什么都不藏）"

        def execute(self, context):
            return _cat_apply(self, context, CAT_PRESETS['cat_show'][1], CAT_PRESETS['cat_show'][2])

    _classes = [MT_OT_HelmRead, MT_OT_HelmApply, MT_OT_HelmPreset,
                MT_OT_CatHideHead, MT_OT_CatHideHead2, MT_OT_CatShowHead]

    def register():
        for c in _classes:
            bpy.utils.register_class(c)
        _register_props()

    def unregister():
        _unregister_props()
        for c in reversed(_classes):
            try:
                bpy.utils.unregister_class(c)
            except Exception:
                pass

else:
    def register():
        pass

    def unregister():
        pass
