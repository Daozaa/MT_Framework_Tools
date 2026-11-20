from __future__ import annotations

import json
import os
import re

import bpy
from mathutils import Vector

SIDECAR_SUFFIX = '.mtbones.json'
_VERSION = 1

def sidecar_path(path):
    return (path or '') + SIDECAR_SUFFIX

def _record_from_name(name):
    m = re.match(r'^b_(\d+)$', name or '')
    if not m:
        return None
    return int(m.group(1)) - 1

def _bone_record_map(arm):
    from .MTframework_MHGU import get_armature_bone_name_map
    try:
        m = get_armature_bone_name_map(arm)
    except Exception:
        m = {}
    out = {}
    for b in arm.data.bones:
        rec = m.get(b.name)
        if rec is None:
            rec = _record_from_name(b.name)
        if rec is not None:
            out[b.name] = int(rec)
    return out

def write(path, arm):
    if not path or arm is None or arm.type != 'ARMATURE':
        return None
    try:
        recs = _bone_record_map(arm)
        entries = []
        for b in arm.data.bones:
            head = b.head_local.copy()
            tail = b.tail_local.copy()
            delta = tail - head
            entries.append({
                'name': b.name,
                'record': recs.get(b.name),
                'head': [round(float(v), 9) for v in head],
                'tail_delta': [round(float(v), 9) for v in delta],
                'roll': round(float(getattr(b, 'roll', 0.0)), 9),
            })
        doc = {
            'version': _VERSION,
            'source': os.path.basename(path),
            'bones': entries,
        }
        out = sidecar_path(path)
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False, separators=(',', ':'))
        print('[MT] 骨骼尾端 sidecar 已写入: %s（%d 根）' % (out, len(entries)))
        return out
    except Exception as e:
        print('[MT] 骨骼尾端 sidecar 写入失败（不影响 arc）:', e)
        return None

def _read(path):
    p = sidecar_path(path)
    if not os.path.exists(p):
        return None
    try:
        with open(p, 'r', encoding='utf-8') as f:
            doc = json.load(f)
        if int(doc.get('version', 0)) != _VERSION:
            return None
        entries = doc.get('bones') or []
        return entries if entries else None
    except Exception:
        return None

def apply(arm, source_path):
    if arm is None or arm.type != 'ARMATURE':
        return 0
    entries = _read(source_path)
    if not entries:
        return 0
    try:
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.context.view_layer.objects.active = arm
        arm.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        eb = arm.data.edit_bones

        offset = None
        checked = 0
        for e in entries:
            rec = e.get('record')
            if rec is None:
                continue
            b = eb.get('b_%d' % (int(rec) + 1))
            if b is None:
                continue
            h = Vector(tuple(float(x) for x in e.get('head', (0, 0, 0))))
            if offset is None:
                offset = b.head - h
            elif (b.head - h - offset).length > 1e-4:
                print('[MT] 骨骼尾端 sidecar 与当前骨架头端不匹配，已跳过')
                bpy.ops.object.mode_set(mode='OBJECT')
                return 0
            checked += 1
        if offset is None or checked == 0:
            bpy.ops.object.mode_set(mode='OBJECT')
            return 0

        n = 0
        for e in entries:
            rec = e.get('record')
            if rec is None:
                continue
            b = eb.get('b_%d' % (int(rec) + 1))
            if b is None:
                continue
            delta = Vector(tuple(float(x) for x in e.get('tail_delta', (0, 0, 0))))
            b.tail = b.head + delta
            try:
                b.roll = float(e.get('roll', 0.0))
            except Exception:
                pass
            n += 1
        bpy.ops.object.mode_set(mode='OBJECT')
        print('[MT] 已按 sidecar 还原 %d 根骨骼尾端' % n)
        return n
    except Exception as e:
        print('[MT] 骨骼尾端 sidecar 应用失败:', e)
        try:
            if bpy.context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
        except Exception:
            pass
        return 0
