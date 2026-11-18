from __future__ import annotations

import struct
import zlib

MOD_MAGIC = b'MOD\x00'
MRL_MAGIC = b'MRL\x00'
NAME_SZ = 128
SUPPORTED_MOD_VER = 0xD4

def name_hash(name):
    return (zlib.crc32(name.encode('ascii', 'replace')) ^ 0xFFFFFFFF) & 0xFFFFFFFF

def read_mod_materials(mod_bytes):
    if len(mod_bytes) < 0x40 or mod_bytes[:4] != MOD_MAGIC:
        return None
    ver = struct.unpack_from('<h', mod_bytes, 4)[0] & 0xFFFF
    if ver != SUPPORTED_MOD_VER:
        return None
    nb, nm, nmat = struct.unpack_from('<HHH', mod_bytes, 6)
    if nmat <= 0:
        return dict(version=ver, names=[], mesh_mats=[])
    mats_off, mesh_off = struct.unpack_from('<II', mod_bytes, 0x2C)
    names = []
    for i in range(nmat):
        b = mats_off + NAME_SZ * i
        names.append(mod_bytes[b:b + NAME_SZ].split(b'\0', 1)[0]
                     .decode('ascii', 'replace'))
    mesh_mats = []
    for i in range(nm):
        o = mesh_off + 48 * i
        if o + 8 > len(mod_bytes):
            break
        d0 = struct.unpack_from('<I', mod_bytes, o + 4)[0]
        mesh_mats.append((d0 >> 12) & 0xFFF)
    return dict(version=ver, names=names, mesh_mats=mesh_mats)

def read_mrl_hashes(mrl_bytes):
    if len(mrl_bytes) < 0x1C or mrl_bytes[:4] != MRL_MAGIC:
        return set()
    mc = struct.unpack_from('<I', mrl_bytes, 8)[0]
    desc = struct.unpack_from('<I', mrl_bytes, 0x18)[0]
    out = set()
    for i in range(mc):
        o = desc + 60 * i
        if o + 8 > len(mrl_bytes):
            break
        out.add(struct.unpack_from('<I', mrl_bytes, o + 4)[0])
    return out

def check(mod_bytes, mrl_bytes):
    info = read_mod_materials(mod_bytes)
    if info is None:
        return None
    have = read_mrl_hashes(mrl_bytes)
    rows = []
    for i, n in enumerate(info['names']):
        h = name_hash(n)
        rows.append(dict(index=i, name=n, hash=h, ok=h in have))
    missing = [r for r in rows if not r['ok']]
    dead = sorted({mi for mi in info['mesh_mats']
                   if mi < len(rows) and not rows[mi]['ok']})
    return dict(version=info['version'], rows=rows, missing=missing,
                dead_meshes=dead, mesh_mats=info['mesh_mats'])

def describe(result, max_names=4):
    if result is None:
        return '这个 .mod 不是 MHGU(v0xD4) 格式，跳过材质名检查'
    if not result['missing']:
        return '材质链接正常：%d 个材质名都能在 mrl 里找到' % len(result['rows'])
    names = ['%s(0x%08X)' % (r['name'], r['hash']) for r in result['missing'][:max_names]]
    more = '' if len(result['missing']) <= max_names else ' 等 %d 个' % len(result['missing'])
    dead = result['dead_meshes']
    tail = ('；受影响网格: %s' % dead[:8]) if dead else ''
    return ('材质名在 mrl 里找不到 —— 这些网格游戏里不会显示: %s%s%s'
            % ('、'.join(names), more, tail))

try:
    import bpy
    from bpy.types import Operator
except Exception:
    bpy = None

if bpy is not None:

    def _find_template(context):
        import os as _os
        sc = getattr(context, "scene", context)
        cand = sc.get("MT_LastImportPath", "") or ""
        if cand and _os.path.exists(cand):
            return cand
        try:
            from .MTframework_MHGU_import import _last_import_path
            if _last_import_path and _os.path.exists(_last_import_path):
                return _last_import_path
        except Exception:
            pass
        return ""

    def _current_pair(context):
        import os
        mod_bytes = b''
        p = _find_template(context)
        if p:
            try:
                with open(p, 'rb') as f:
                    mod_bytes = f.read()
            except Exception:
                mod_bytes = b''
        mrl_bytes = b''
        arc = ''
        try:
            from .MTframework_MHGU_phys import recalled_arc, arc_entries, find_entry
            arc, _ctc = recalled_arc(context)
            if arc and os.path.exists(arc):
                with open(arc, 'rb') as f:
                    es = arc_entries(f.read())
                e = find_entry(es, MRL_MAGIC)
                if e is not None:
                    mrl_bytes = e['body']
        except Exception:
            mrl_bytes = b''
        return mod_bytes, mrl_bytes, arc

    class MT_OT_MatCheck(Operator):
        bl_idname = "mt_framework.mat_check"
        bl_label = "材质链接检查"
        bl_description = ("读当前模板 .mod 的材质名，算 crc32^~0，在 arc 的 .mrl 里查；"
                          "对不上的网格在游戏里不会显示")

        def execute(self, context):
            mod_bytes, mrl_bytes, arc = _current_pair(context)
            if not mod_bytes:
                self.report({'ERROR'}, '找不到当前模板 .mod（先导入一个模型）')
                return {'CANCELLED'}
            if not mrl_bytes:
                self.report({'ERROR'}, '当前 arc 里没有 .mrl（先导入 .arc 而不是 .mod）')
                return {'CANCELLED'}
            r = check(mod_bytes, mrl_bytes)
            if r is None:
                self.report({'WARNING'}, describe(r))
                return {'FINISHED'}
            for row in r['rows']:
                print('  material %d  %-34s %08X  %s'
                      % (row['index'], row['name'], row['hash'],
                         'OK' if row['ok'] else 'MISSING'))
            msg = describe(r)
            if r['missing']:
                self.report({'ERROR'}, msg)
            else:
                self.report({'INFO'}, msg)
            return {'FINISHED'}

    def register():
        bpy.utils.register_class(MT_OT_MatCheck)

    def unregister():
        try:
            bpy.utils.unregister_class(MT_OT_MatCheck)
        except Exception:
            pass

else:
    def register():
        pass

    def unregister():
        pass
