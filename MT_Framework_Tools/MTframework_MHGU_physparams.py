from __future__ import annotations

import os
import struct

try:
    import bpy
    from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty
    from bpy.types import Operator
except Exception:
    bpy = None

from .MTframework_MHGU_phys import recalled_arc, remember_arc

HDR = 0x3C
GROUP_SZ = 80
CHAIN_SZ = 96

def parse_ctc(ctc):
    ng = struct.unpack_from('<I', ctc, 0x10)[0]
    nc = struct.unpack_from('<I', ctc, 0x14)[0]
    g_off = HDR
    n_off = HDR + GROUP_SZ * ng
    return dict(ng=ng, nc=nc, g_off=g_off, n_off=n_off, raw=ctc)

def read_params(ctc):
    p = parse_ctc(ctc)
    g = p['g_off']
    groups = []
    for i in range(p['ng']):
        o = g + i * GROUP_SZ
        groups.append(dict(
            node_num=struct.unpack_from('<I', ctc, o)[0],
            gravity=struct.unpack_from('<3f', ctc, o + 32),
            damping=struct.unpack_from('<f', ctc, o + 48)[0],
            trans_force=struct.unpack_from('<f', ctc, o + 52)[0],
            spring=struct.unpack_from('<f', ctc, o + 56)[0],
            wind=struct.unpack_from('<f', ctc, o + 60)[0],
            limit_force=struct.unpack_from('<f', ctc, o + 64)[0],
            friction=struct.unpack_from('<f', ctc, o + 68)[0],
            reflect=struct.unpack_from('<f', ctc, o + 72)[0],
        ))
    chains = []
    for k in range(p['nc']):
        o = p['n_off'] + k * CHAIN_SZ
        chains.append(dict(
            joint=ctc[o], rot_mode=ctc[o + 4],
            radius=struct.unpack_from('<f', ctc, o + 8)[0],
            angle=struct.unpack_from('<f', ctc, o + 80)[0],
            mass=struct.unpack_from('<f', ctc, o + 84)[0],
            elastic=struct.unpack_from('<f', ctc, o + 88)[0],
        ))
    head = dict(
        timestep=struct.unpack_from('<f', ctc, 0x1C)[0],
        gravity_scaling=struct.unpack_from('<f', ctc, 0x20)[0],
        global_damping=struct.unpack_from('<f', ctc, 0x24)[0],
        trans_coef=struct.unpack_from('<f', ctc, 0x28)[0],
        spring_scaling=struct.unpack_from('<f', ctc, 0x2C)[0],
        wind_scaling=struct.unpack_from('<f', ctc, 0x30)[0],
    )
    return head, groups, chains

def write_params(ctc, gravity=None, damping=None, spring=None, wind=None,
                 trans_force=None, limit_force=None, reflect=None, friction=None,
                 angle_limit=None, mass=None, elastic=None):
    p = parse_ctc(ctc)
    b = bytearray(ctc)
    for i in range(p['ng']):
        o = p['g_off'] + i * GROUP_SZ
        if gravity is not None:
            struct.pack_into('<3f', b, o + 32, 0.0, float(gravity), 0.0)
        for off, val in ((48, damping), (52, trans_force), (56, spring),
                         (60, wind), (64, limit_force), (68, friction), (72, reflect)):
            if val is not None:
                struct.pack_into('<f', b, o + off, float(val))
    for k in range(p['nc']):
        o = p['n_off'] + k * CHAIN_SZ
        if angle_limit is not None:
            struct.pack_into('<f', b, o + 80, float(angle_limit))
        if mass is not None:
            struct.pack_into('<f', b, o + 84, float(mass))
        if elastic is not None:
            struct.pack_into('<f', b, o + 88, float(elastic))
    return bytes(b)

PHYS_PRESETS = {

    'soft_body':       ("贴身·软组织", 0.0, 0.850, 0.150, 0.10, 0.35, 100.0, 0.05, 0.30, 2.0, 1.0),
    'soft_jiggle':     ("贴身·更软",   0.0, 0.250, 0.050, 0.15, 0.50, 100.0, 0.05, 0.90, 1.0, 1.0),
    'soft_jiggle_max': ("贴身·最软",   0.0, 0.100, 0.020, 0.10, 0.60, 100.0, 0.05, 1.40, 0.6, 1.0),

    'auto_hair':       ("自动·头发",   0.0, 0.120, 0.020, 0.80, 0.80, 100.0, 0.10, 1.75, 1.0, 1.0),
    'auto_sleeve':     ("自动·长袖",   0.0, 0.180, 0.015, 1.00, 0.80, 100.0, 0.10, 1.70, 1.0, 1.0),
    'auto_cloth':      ("自动·裙摆",   0.0, 0.180, 0.015, 1.00, 0.80, 100.0, 0.10, 1.57, 1.0, 1.0),
    'auto_tail':       ("自动·尾巴",   0.0, 0.100, 0.030, 1.20, 0.90, 100.0, 0.10, 2.00, 0.8, 1.0),
    'auto_ribbon':     ("自动·丝带",   0.0, 0.100, 0.030, 1.20, 0.90, 100.0, 0.10, 2.00, 0.8, 1.0),
    'auto_other':      ("自动·通用",   0.0, 0.160, 0.015, 1.00, 0.80, 100.0, 0.10, 1.60, 1.0, 1.0),
}

PRESET_ALIASES = {
    'hair_soft': 'auto_hair',
    'hair_wave': 'auto_hair',
    'cloth_std': 'auto_cloth',
    'ribbon': 'auto_ribbon',
    'cape_heavy': 'auto_cloth',
    'armor_stiff': 'auto_other',
    'rigid': 'auto_other',
}
DEFAULT_PRESET_KEY = 'auto_other'

def normalize_preset_key(key):
    key = PRESET_ALIASES.get(key, key)
    return key if key in PHYS_PRESETS else DEFAULT_PRESET_KEY

AUTO_PRESET_KEY = 'auto'
AUTO_PRESET_LABEL = '自动·按部位/链长（重力0）'

PHYS_PRESET_ITEMS = [(k, v[0], '') for k, v in PHYS_PRESETS.items()]

def _region_key(names):
    text = ' '.join(str(n).lower() for n in names)
    if any(k in text for k in ('breast', 'bust', 'chest', '胸', '乳', '腹',
                               'belly', 'hip', '臀')):
        return 'body_soft'
    if any(k in text for k in ('hair', 'ponytail', 'braid', '发', '刘海', '辫')):
        return 'hair'
    if any(k in text for k in ('sleeve', '袖')):
        return 'sleeve'
    if any(k in text for k in ('tail', '尾')):
        return 'tail'
    if any(k in text for k in ('ribbon', 'bow', 'tassel', 'scarf', '带',
                               '蝴蝶结', '流苏', '围巾')):
        return 'ribbon'
    if any(k in text for k in ('skirt', 'cloth', 'cape', 'cloak', '裙', '布',
                               '披风')):
        return 'cloth'
    return 'other'

_REGION_INFO = {
    'body_soft': ('贴身', 'soft_body'),
    'hair': ('头发', 'auto_hair'),
    'sleeve': ('长袖', 'auto_sleeve'),
    'tail': ('尾巴', 'auto_tail'),
    'ribbon': ('丝带', 'auto_ribbon'),
    'cloth': ('裙摆', 'auto_cloth'),
    'other': ('通用', 'auto_other'),
}

def auto_chain_values(names, positions):
    region = _region_key(names)
    label, preset_key = _REGION_INFO[region]
    row = PHYS_PRESETS[preset_key]
    _name, _grav, damp, spring, wind, trans, limit, reflect, angle, mass, elastic = row

    grav = 0.0

    length = 0.0
    for i in range(len(positions) - 1):
        a = positions[i]
        b = positions[i + 1]
        length += sum((float(b[k]) - float(a[k])) ** 2 for k in range(3)) ** 0.5
    extent = max(0.0, min(1.0, (length - 20.0) / 120.0))

    if region == 'body_soft':

        damp = max(0.25, damp - 0.10 * extent)
        trans = trans * (1.0 + 0.15 * extent)
        spring = max(0.02, spring * (1.0 - 0.20 * extent))
        angle = min(1.20, angle + 0.35 * extent)
    else:
        damp = max(0.03, min(1.0, damp * (1.0 - 0.18 * extent)))
        spring = max(0.003, spring * (1.0 - 0.15 * extent))
        trans = trans * (1.0 + 0.25 * extent)
        angle = min(2.20, angle + 0.35 * extent)
        mass = mass * (1.0 + 0.25 * extent)

    n = max(1, len(names))
    values = []
    for i in range(n):
        t = (i / float(n - 1)) if n > 1 else 0.0
        values.append((min(2.20, angle * (0.75 + 0.50 * t)),
                       mass * (1.10 - 0.20 * t), elastic))
    gp = ('自动·%s/%d节' % (label, n), grav, damp, spring, wind, trans,
          limit, reflect, angle, mass, elastic)
    return gp, values

def apply_preset(ctc, key):
    if key == AUTO_PRESET_KEY:
        raise ValueError('“自动”只用于新建/重建物理链；已有 CTC 请选具体预设')
    key = normalize_preset_key(key)
    row = PHYS_PRESETS.get(key)
    if row is None:
        raise ValueError("没有这个预设: %s" % key)
    _name, grav, damp, spring, wind, trans, limit, reflect, angle, mass, elastic = row
    return write_params(ctc, gravity=grav, damping=damp, spring=spring, wind=wind,
                        trans_force=trans, limit_force=limit, reflect=reflect,
                        angle_limit=angle, mass=mass, elastic=elastic)

def node_group_map(ctc):
    p = parse_ctc(ctc)
    node_group, group_nodes = {}, {}
    idx = 0
    for gi in range(p['ng']):
        cnt = struct.unpack_from('<I', ctc, p['g_off'] + gi * GROUP_SZ)[0]
        group_nodes[gi] = list(range(idx, idx + cnt))
        for k in range(idx, idx + cnt):
            node_group[k] = gi
        idx += cnt
    return node_group, group_nodes

def apply_preset_selected(ctc, key, selected_ids):
    if key == AUTO_PRESET_KEY:
        raise ValueError('“自动”只用于新建/重建物理链；已有 CTC 请选具体预设')
    key = normalize_preset_key(key)
    row = PHYS_PRESETS.get(key)
    if row is None:
        raise ValueError("没有这个预设: %s" % key)
    _name, grav, damp, spring, wind, trans, limit, reflect, angle, mass, elastic = row
    p = parse_ctc(ctc)
    node_group, group_nodes = node_group_map(ctc)
    sel = set(int(i) for i in selected_ids)
    hit_nodes = [k for k in range(p['nc'])
                 if ctc[p['n_off'] + k * CHAIN_SZ] in sel]
    hit_groups = sorted({node_group[k] for k in hit_nodes})
    b = bytearray(ctc)
    for gi in hit_groups:
        o = p['g_off'] + gi * GROUP_SZ
        struct.pack_into('<3f', b, o + 32, 0.0, float(grav), 0.0)
        struct.pack_into('<f', b, o + 48, float(damp))
        struct.pack_into('<f', b, o + 52, float(trans))
        struct.pack_into('<f', b, o + 56, float(spring))
        struct.pack_into('<f', b, o + 60, float(wind))
        struct.pack_into('<f', b, o + 64, float(limit))
        struct.pack_into('<f', b, o + 72, float(reflect))
    for k in hit_nodes:
        o = p['n_off'] + k * CHAIN_SZ
        struct.pack_into('<f', b, o + 80, float(angle))
        struct.pack_into('<f', b, o + 84, float(mass))
        struct.pack_into('<f', b, o + 88, float(elastic))
    return bytes(b), len(hit_groups), len(hit_nodes)

def lock_nodes(ctc, selected_ids):
    p = parse_ctc(ctc)
    sel = set(int(i) for i in selected_ids)
    b = bytearray(ctc)
    hit = 0
    for k in range(p['nc']):
        o = p['n_off'] + k * CHAIN_SZ
        if ctc[o] in sel:
            struct.pack_into('<f', b, o + 80, 0.0)
            hit += 1
    return bytes(b), hit

def write_params_selected(ctc, selected_ids, gravity, damping, spring, wind,
                          trans_force, limit_force, reflect,
                          angle_limit, mass, elastic):
    p = parse_ctc(ctc)
    node_group, group_nodes = node_group_map(ctc)
    sel = set(int(i) for i in selected_ids)
    hit_nodes = [k for k in range(p['nc'])
                 if ctc[p['n_off'] + k * CHAIN_SZ] in sel]
    hit_groups = sorted({node_group[k] for k in hit_nodes})
    b = bytearray(ctc)
    for gi in hit_groups:
        o = p['g_off'] + gi * GROUP_SZ
        struct.pack_into('<3f', b, o + 32, 0.0, float(gravity), 0.0)
        struct.pack_into('<f', b, o + 48, float(damping))
        struct.pack_into('<f', b, o + 52, float(trans_force))
        struct.pack_into('<f', b, o + 56, float(spring))
        struct.pack_into('<f', b, o + 60, float(wind))
        struct.pack_into('<f', b, o + 64, float(limit_force))
        struct.pack_into('<f', b, o + 72, float(reflect))
    for k in hit_nodes:
        o = p['n_off'] + k * CHAIN_SZ
        struct.pack_into('<f', b, o + 80, float(angle_limit))
        struct.pack_into('<f', b, o + 84, float(mass))
        struct.pack_into('<f', b, o + 88, float(elastic))
    return bytes(b), len(hit_groups), len(hit_nodes)

if bpy is not None:

    def _register_props():
        S = bpy.types.Scene
        S.MT_PhysGravity = FloatProperty(name="重力 Y", default=-850.0,
                                         description="负数向下，越大越沉（手感主旋钮）")
        S.MT_PhysDamping = FloatProperty(name="阻尼", default=0.18, min=0.0, max=10.0)
        S.MT_PhysSpring = FloatProperty(name="弹簧", default=0.015, min=0.0, max=10.0)
        S.MT_PhysWind = FloatProperty(name="风", default=1.0, min=0.0, max=10.0)
        S.MT_PhysTrans = FloatProperty(name="平移力系数", default=0.8, min=0.0, max=10.0)
        S.MT_PhysLimit = FloatProperty(name="限力", default=100.0, min=0.0, max=10000.0)
        S.MT_PhysReflect = FloatProperty(name="反射", default=0.1, min=0.0, max=10.0)
        S.MT_PhysAngle = FloatProperty(name="角度上限", default=1.57, min=0.0, max=3.15)
        S.MT_PhysMass = FloatProperty(name="质量", default=1.0, min=0.0, max=100.0)
        S.MT_PhysElastic = FloatProperty(name="弹性", default=1.0, min=0.0, max=10.0)
        S.MT_PhysPreset = EnumProperty(
            name="物理预设",
            items=PHYS_PRESET_ITEMS,
            default=DEFAULT_PRESET_KEY)
        S.MT_PhysAutoInit = BoolProperty(
            name="新链自动初值",
            default=False,
            description="登记或重建物理链时按骨名部位和链长生成初值；已有 CTC 不受影响")
    def _unregister_props():
        for k in ('MT_PhysGravity', 'MT_PhysDamping', 'MT_PhysSpring', 'MT_PhysWind',
                  'MT_PhysTrans', 'MT_PhysLimit', 'MT_PhysReflect', 'MT_PhysAngle',
                  'MT_PhysMass', 'MT_PhysElastic', 'MT_PhysPreset', 'MT_PhysAutoInit'):
            try:
                delattr(bpy.types.Scene, k)
            except Exception:
                pass

    class MT_OT_PhysRead(Operator):
        bl_idname = "mt_framework.phys_params_read"
        bl_label = "读取物理参数"
        bl_description = "读取当前 CTC 里的参数：有选中物理骨就读它所在的组/链，否则读第一组"

        def execute(self, context):
            _arc, ctc = recalled_arc(context)
            if not ctc or ctc[:4] != b'CTC\x00':
                self.report({'ERROR'}, '当前没有 CTC（先登记物理骨或补全物理链）')
                return {'CANCELLED'}
            head, groups, chains = read_params(ctc)
            sc = context.scene

            gi = ci = None
            arm = _pick_armature(context) if '_pick_armature' in globals() else None
            ids = set()
            if arm is not None:
                try:
                    ids = _selected_phys_ids(context, arm, ctc)
                except Exception:
                    ids = set()
            if ids:
                try:
                    p = parse_ctc(ctc)
                    id2idx = {}
                    for k in range(p['nc']):
                        jid = struct.unpack_from('<H', ctc, p['n_off'] + k * 96)[0]
                        id2idx.setdefault(jid, []).append(k)
                    node_group, _gn = node_group_map(ctc)
                    for jid in ids:
                        for k in id2idx.get(jid, []):
                            g = node_group.get(k)
                            if g is not None:
                                gi, ci = g, k
                                break
                        if gi is not None:
                            break
                except Exception:
                    gi = ci = None
            if groups:
                g = groups[gi if gi is not None else 0]
                sc.MT_PhysGravity = g['gravity'][1]
                sc.MT_PhysDamping = g['damping']
                sc.MT_PhysSpring = g['spring']
                sc.MT_PhysWind = g['wind']
                sc.MT_PhysTrans = g['trans_force']
                sc.MT_PhysLimit = g['limit_force']
                sc.MT_PhysReflect = g['reflect']
            if chains:
                c = chains[ci if ci is not None else 0]
                sc.MT_PhysAngle = c['angle']
                sc.MT_PhysMass = c['mass']
                sc.MT_PhysElastic = c['elastic']
            self.report({'INFO'},
                        '已读取：%d 组 / %d 链（显示%s）'
                        % (head['ng'] if 'ng' in head else len(groups), len(chains),
                           ('选中骨所在组 %d' % gi) if gi is not None else '第一组'))
            return {'FINISHED'}

    class MT_OT_PhysWrite(Operator):
        bl_idname = "mt_framework.phys_params_write"
        bl_label = "应用物理参数"
        bl_description = "把所有组/链的对应字段改成面板上的值（导出时写入 arc）"

        def execute(self, context):
            arc_path, ctc = recalled_arc(context)
            if not ctc or ctc[:4] != b'CTC\x00':
                self.report({'ERROR'}, '当前没有 CTC（先登记物理骨或补全物理链）')
                return {'CANCELLED'}
            sc = context.scene
            new = write_params(
                ctc,
                gravity=sc.MT_PhysGravity, damping=sc.MT_PhysDamping,
                spring=sc.MT_PhysSpring, wind=sc.MT_PhysWind,
                trans_force=sc.MT_PhysTrans, limit_force=sc.MT_PhysLimit,
                reflect=sc.MT_PhysReflect,
                angle_limit=sc.MT_PhysAngle, mass=sc.MT_PhysMass,
                elastic=sc.MT_PhysElastic)
            remember_arc(context, arc_path, new)
            self.report({'INFO'}, '已应用：重力 %.0f / 阻尼 %.2f / 弹簧 %.3f / 角度 %.2f'
                        % (sc.MT_PhysGravity, sc.MT_PhysDamping, sc.MT_PhysSpring,
                           sc.MT_PhysAngle))
            return {'FINISHED'}

    def _selected_phys_ids(context, arm, ctc):
        try:
            if bpy.context.mode == 'EDIT_ARMATURE':
                sel = {e.name for e in arm.data.edit_bones if e.select}
            elif bpy.context.mode == 'POSE':
                sel = {pb.name for pb in arm.pose.bones if pb.bone.select}
            else:
                sel = {b.name for b in arm.data.bones if b.select}
        except Exception:
            sel = {b.name for b in arm.data.bones if b.select}
        if not sel:
            return set()

        def resolve(nm, slot, nid):
            cands = []
            if nm:
                cands.append(nm)
            for base in (slot + 1 if slot is not None else None, nid):
                if base is None:
                    continue
                cands += ['b_%d' % base, 'b_%d.l' % base, 'b_%d.r' % base]
            for c in cands:
                if c and arm.data.bones.get(c) is not None:
                    return c
            return None

        id2name = {}
        try:
            mp = arm.get('MT_PhysIdMap') or {}
            id2name = {int(k): str(v) for k, v in mp.items()}
        except Exception:
            pass
        tpl = context.scene.get('MT_LastImportPath', '') or ''
        try:
            if tpl and os.path.exists(tpl):
                mod = open(tpl, 'rb').read()
                if mod[:4] == b'MOD\x00':
                    n = struct.unpack_from('<H', mod, 6)[0]
                    ptr = struct.unpack_from('<I', mod, 0x24)[0]
                    lut = ptr + n * 24 + n * 64 + n * 64
                    for nid in range(256):
                        if lut + nid >= len(mod):
                            break
                        slot = mod[lut + nid]
                        if slot == 0xFF or slot >= n:
                            continue
                        nm = resolve(id2name.get(nid), slot, nid)
                        if nm is not None:
                            id2name[nid] = nm
        except Exception:
            pass

        for nid in list(id2name):
            if arm.data.bones.get(id2name[nid]) is None:
                nm = resolve(id2name[nid], None, nid)
                if nm is not None:
                    id2name[nid] = nm
        return {nid for nid, nm in id2name.items()
                if nm in sel and arm.data.bones.get(nm) is not None}

    class MT_OT_PhysPresetApply(Operator):
        bl_idname = "mt_framework.phys_preset_apply"
        bl_label = "套用物理预设"
        bl_description = "把当前 CTC 的所有组/链改成选中的预设参数"

        def execute(self, context):
            arc_path, ctc = recalled_arc(context)
            if not ctc or ctc[:4] != b'CTC\x00':
                self.report({'ERROR'}, '当前没有 CTC')
                return {'CANCELLED'}
            key = normalize_preset_key(context.scene.MT_PhysPreset)
            try:
                new = apply_preset(ctc, key)
            except Exception as e:
                self.report({'ERROR'}, str(e))
                return {'CANCELLED'}
            remember_arc(context, arc_path, new)
            self.report({'INFO'}, '已套用预设：%s' % PHYS_PRESETS[key][0])
            return {'FINISHED'}

    def _pick_armature(context):
        act = context.view_layer.objects.active
        try:
            if (act is not None and act.type == 'ARMATURE'
                    and context.mode in ('EDIT_ARMATURE', 'POSE')):
                return act
        except Exception:
            pass
        arms = [o for o in context.scene.objects if o.type == 'ARMATURE']
        for o in arms:
            if o.name.startswith('MT_Armature') or o.data.name.startswith('MT_Armature'):
                return o
        if act is not None and act.type == 'ARMATURE':
            return act
        return arms[0] if arms else None

    class MT_OT_PhysPresetApplySelected(Operator):
        bl_idname = "mt_framework.phys_preset_apply_selected"
        bl_label = "套用预设（选中骨）"
        bl_description = ("只改选中的物理骨：重力/阻尼等组参数改它所在的组，"
                          "角度/质量/弹性只改选中的那几根；其它骨一个字节不动")

        def execute(self, context):
            arm = _pick_armature(context)
            if arm is None:
                self.report({'ERROR'}, '场景里没有骨架')
                return {'CANCELLED'}
            arc_path, ctc = recalled_arc(context)
            if not ctc or ctc[:4] != b'CTC\x00':
                self.report({'ERROR'}, '当前没有 CTC')
                return {'CANCELLED'}
            ids = _selected_phys_ids(context, arm, ctc)
            if not ids:
                self.report({'ERROR'},
                            '没有选中物理骨：到编辑/姿态模式选中要改的骨，再点这里')
                return {'CANCELLED'}
            key = normalize_preset_key(context.scene.MT_PhysPreset)
            try:
                new, ng, nn = apply_preset_selected(ctc, key, ids)
            except Exception as e:
                self.report({'ERROR'}, str(e))
                return {'CANCELLED'}
            if ng == 0:
                self.report({'ERROR'},
                            '选中的骨（%d 根）不在 CTC 的任何组里：先登记成物理骨'
                            % len(ids))
                return {'CANCELLED'}
            remember_arc(context, arc_path, new)
            self.report({'INFO'},
                        '已给选中骨套用预设：%s（改 %d 组 / %d 个节点）'
                        % (PHYS_PRESETS[key][0], ng, nn))
            return {'FINISHED'}

    class MT_OT_PhysWriteSelected(Operator):
        bl_idname = "mt_framework.phys_params_write_selected"
        bl_label = "应用参数（选中骨）"
        bl_description = ("只改选中的物理骨：组参数（重力/阻尼/...）改它所在的组，"
                          "角度/质量/弹性只改选中的节点；其它骨一个字节不动")

        def execute(self, context):
            arm = _pick_armature(context)
            if arm is None:
                self.report({'ERROR'}, '场景里没有骨架')
                return {'CANCELLED'}
            arc_path, ctc = recalled_arc(context)
            if not ctc or ctc[:4] != b'CTC\x00':
                self.report({'ERROR'}, '当前没有 CTC')
                return {'CANCELLED'}
            ids = _selected_phys_ids(context, arm, ctc)
            if not ids:
                self.report({'ERROR'},
                            '没有选中物理骨：到编辑/姿态模式选中要改的骨，再点这里')
                return {'CANCELLED'}
            sc = context.scene
            try:
                new, ng, nn = write_params_selected(
                    ctc, ids, sc.MT_PhysGravity, sc.MT_PhysDamping,
                    sc.MT_PhysSpring, sc.MT_PhysWind, sc.MT_PhysTrans,
                    sc.MT_PhysLimit, sc.MT_PhysReflect,
                    sc.MT_PhysAngle, sc.MT_PhysMass, sc.MT_PhysElastic)
            except Exception as e:
                self.report({'ERROR'}, str(e))
                return {'CANCELLED'}
            if ng == 0:
                self.report({'ERROR'},
                            '选中的骨（%d 根）不在 CTC 的任何组里：先登记成物理骨'
                            % len(ids))
                return {'CANCELLED'}
            remember_arc(context, arc_path, new)
            self.report({'INFO'},
                        '已给选中骨应用参数：改 %d 组 / %d 个节点' % (ng, nn))
            return {'FINISHED'}

    class MT_OT_PhysLockSelected(Operator):
        bl_idname = "mt_framework.phys_lock_selected"
        bl_label = "锁死选中节点（只改角度）"
        bl_description = ("把选中物理骨节点的「角度上限」设为 0：它自己不摆动，"
                          "但仍被前面的物理骨带着走；组参数一个字节不动")

        def execute(self, context):
            arm = _pick_armature(context)
            if arm is None:
                self.report({'ERROR'}, '场景里没有骨架')
                return {'CANCELLED'}
            arc_path, ctc = recalled_arc(context)
            if not ctc or ctc[:4] != b'CTC\x00':
                self.report({'ERROR'}, '当前没有 CTC')
                return {'CANCELLED'}
            ids = _selected_phys_ids(context, arm, ctc)
            if not ids:
                self.report({'ERROR'},
                            '没有选中物理骨：到编辑/姿态模式选中链尾的骨，再点这里')
                return {'CANCELLED'}
            new, hit = lock_nodes(ctc, ids)
            if hit == 0:
                self.report({'ERROR'},
                            '选中的骨（%d 根）不在 CTC 节点里：先登记成物理骨'
                            % len(ids))
                return {'CANCELLED'}
            remember_arc(context, arc_path, new)
            self.report({'INFO'},
                        '已锁死选中节点：%d 个（只改角度上限，组参数未动）' % hit)
            return {'FINISHED'}

    _classes = [MT_OT_PhysRead, MT_OT_PhysWrite,
                MT_OT_PhysWriteSelected, MT_OT_PhysLockSelected,
                MT_OT_PhysPresetApply, MT_OT_PhysPresetApplySelected]

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
