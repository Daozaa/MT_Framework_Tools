from __future__ import annotations

import base64
import os
import struct
import tempfile
import zlib

CTC_HASH = 0x535D969F
MOD_MAGIC = b'MOD\x00'
CTC_MAGIC = b'CTC\x00'

def arc_entries(data):
    if data[:4] != b'ARC\x00':
        raise ValueError('不是 ARC\\0 格式')
    _ver, count = struct.unpack_from('<HH', data, 4)
    out = []
    off = 0x0C
    for _ in range(count):
        name = data[off:off + 64].split(b'\0', 1)[0].decode('utf-8', 'replace')
        h, csz, flag, ofs = struct.unpack_from('<4I', data, off + 64)
        raw = data[ofs:ofs + csz]
        try:
            body = zlib.decompress(raw)
        except Exception:
            body = raw
        out.append(dict(name=name, hash=h, flag=flag, raw=raw, body=body))
        off += 80
    return out

def arc_build(entries):
    head = b'ARC\x00' + struct.pack('<HH', 17, len(entries)) + b'\0\0\0\0'

    need = 0x0C + 80 * len(entries)
    base = 0x8000
    if need > base:
        base = ((need + 0xFFFF) // 0x10000) * 0x10000
    table = bytearray()
    body = bytearray()
    pos = base
    for e in entries:
        nm = e['name']
        if isinstance(nm, bytes):
            nm_b = nm
        else:
            nm_b = nm.encode('utf-8')
        table += nm_b.ljust(64, b'\0')[:64]
        table += struct.pack('<4I', e['hash'], len(e['raw']), e['flag'], pos)
        body += e['raw']
        pos += len(e['raw'])
        pad = (-pos) % 8
        if pad:
            body += b'\0' * pad
            pos += pad
    gap = base - 0x0C - 80 * len(entries)
    return head + bytes(table) + b'\0' * gap + bytes(body)

def find_entry(entries, magic):
    for e in entries:
        if e['body'][:4] == magic:
            return e
    return None

def import_arc_file(path):
    with open(path, 'rb') as f:
        data = f.read()
    entries = arc_entries(data)
    mod = find_entry(entries, MOD_MAGIC)
    if mod is None:
        raise ValueError('这个 arc 里没有 .mod')
    ctc = find_entry(entries, CTC_MAGIC)
    tmpdir = tempfile.gettempdir()
    stem = os.path.splitext(os.path.basename(path))[0]
    tmp = os.path.join(tmpdir, stem + '.mod')
    with open(tmp, 'wb') as f:
        f.write(mod['body'])
    return tmp, (ctc['body'] if ctc else b''), path

LAST_CTC_FILTER = None

def export_arc(context, arc_path, mod_path, mod_bytes, dst=None):
    with open(arc_path, 'rb') as f:
        entries = arc_entries(f.read())
    mod = find_entry(entries, MOD_MAGIC)
    if mod is None:
        raise ValueError('模板 arc 里没有 .mod')
    mod['body'] = mod_bytes
    mod['raw'] = zlib.compress(mod_bytes, 9)
    mod['flag'] = (mod['flag'] & 0xFF000000) | (len(mod_bytes) & 0xFFFFFF)

    try:
        from .MTframework_MHGU_helmd import get_modified_xfs, read_disp
        _xfs = get_modified_xfs(context)

        if _xfs and '\\otomo\\' in (arc_path or '').replace('/', '\\').lower():
            _v0, _v1, _n, _mix = read_disp(_xfs)
            if (_v0, _v1) in ((0xFC00, 0x81FF), (0xFC01, 0xFFFF)):
                print('[MT] 随从猫 arc 用了玩家藏头位 %04X/%04X，已忽略（请用「猫·藏头」）'
                      % (_v0, _v1))
                _xfs = b''
    except Exception:
        _xfs = b''
    if _xfs:
        for _e in entries:
            if _e['body'][:4] == b'XFS\x00':
                _e['body'] = _xfs
                _e['raw'] = zlib.compress(_xfs, 9)
                _e['flag'] = (_e['flag'] & 0xFF000000) | (len(_xfs) & 0xFFFFFF)
                break

    global LAST_CTC_FILTER
    LAST_CTC_FILTER = None
    _arc_path, ctc_bytes = recalled_arc(context)
    if ctc_bytes:

        try:
            from .MTframework_MHGU_ctc import filter_nodes
            from .MTframework_MHGU_boneadd import bone_ids
            _keep = set(bone_ids(mod_bytes))
            _f = filter_nodes(ctc_bytes, _keep)
            if _f and _f != ctc_bytes:
                import struct as _st
                _old_n = _st.unpack_from('<I', ctc_bytes, 0x14)[0] if len(ctc_bytes) > 0x18 else 0
                _new_n = _st.unpack_from('<I', _f, 0x14)[0] if len(_f) > 0x18 else 0
                print('[MT] CTC 过滤：节点 %d -> %d（骨骼数 %d）'
                      % (_old_n, _new_n, len(_keep)))
                LAST_CTC_FILTER = (_old_n, _new_n)
                ctc_bytes = _f
            elif not _f:
                print('[MT] 警告：CTC 引用的骨在模型里都不存在，已跳过物理数据')
                ctc_bytes = b''
        except Exception:
            pass

        try:
            from .MTframework_MHGU_physmat import fix_matrix_modes
            _fixed, _nfix = fix_matrix_modes(ctc_bytes)
            if _nfix:
                print('[MT] 修正矩阵/mAngleMode 配对：%d 个节点' % _nfix)
                ctc_bytes = _fixed
        except Exception:
            pass

        try:
            import struct as _st2
            if ctc_bytes[:4] == CTC_MAGIC:
                _ver = _st2.unpack_from('<I', ctc_bytes, 4)[0]
                _v8 = _st2.unpack_from('<I', ctc_bytes, 8)[0]
                _v12 = _st2.unpack_from('<I', ctc_bytes, 12)[0]
                if (_ver, _v8, _v12) != (22, 0, 1000):
                    _hb = bytearray(ctc_bytes)
                    _st2.pack_into('<I', _hb, 4, 22)
                    _st2.pack_into('<I', _hb, 8, 0)
                    _st2.pack_into('<I', _hb, 12, 1000)
                    ctc_bytes = bytes(_hb)
                    print('[MT] CTC 头被修回：version %d -> 22（+8=%d +12=%d）'
                          % (_ver, _v8, _v12))
        except Exception:
            pass

    try:
        from . import MTframework_MHGU_ccl as _CCL
        _custom_caps = _CCL.capsules_from_json(
            getattr(context.scene, 'MT_CclCapsules', '') or '')
    except Exception:
        _CCL = None
        _custom_caps = []
    _ccl_on = bool(getattr(context.scene, 'MT_CclEnable', False))
    if _custom_caps:
        _ccl_on = True
    _caps_written = []
    if _ccl_on and _CCL is not None:
        try:
            _low = (arc_path or '').replace('/', '\\').lower()
            _nm_low = (mod.get('name') or '').lower()
            _helm_like = ('\\helm' in _low or '\\hair' in _low
                          or 'helm' in _nm_low or 'hair' in _nm_low)

            if _helm_like:
                _caps = _custom_caps or _CCL.body_capsules(mod_bytes)
                if _caps:

                    try:
                        from .MTframework_MHGU_verify import capsule_warnings
                        _warns, _sum = capsule_warnings(_caps)
                        print('[MT] 胶囊体检：%s' % _sum)
                        for _w in _warns:
                            print('[MT] 警告：%s' % _w)
                    except Exception:
                        pass
                    _CCL.apply_to_entries(entries, mod['name'], _CCL.build_ccl(_caps))
                    _caps_written = list(_caps)
                    print('[MT] 已写入 CCL：%d 个胶囊（%s，%s）'
                          % (len(_caps),
                             '自定义' if _custom_caps else '自动',
                             mod.get('name')))
                else:
                    print('[MT] 警告：CCL 没生成出胶囊（骨表里没有 0~19 号骨？）')
            elif _custom_caps:
                print('[MT] 当前 arc 不是 helm/hair：不写 CCL 条目（引擎只读该槽的 CCL）')
            if ctc_bytes:
                ctc_bytes, _nf = _CCL.enable_collision_flags(ctc_bytes)
                if _nf:
                    print('[MT] CTC 碰撞标志位已打开：%d 组 (+0x04)' % _nf)
        except Exception as _e_cc:
            print('[MT] CCL 写入失败:', _e_cc)

    try:
        _it = int(getattr(context.scene, 'MT_PhysIter', 1) or 1)
    except Exception:
        _it = 1
    if ctc_bytes and _it != 1 and ctc_bytes[:4] == b'CTC\x00' and len(ctc_bytes) >= 0x38:
        _it = max(1, min(3, _it))
        _hb = bytearray(ctc_bytes)
        _hb[52] = _it
        _hb[53] = _it
        ctc_bytes = bytes(_hb)
        print('[MT] CTC 解算迭代设为 %d（header +52/+53）' % _it)

    if bool(getattr(context.scene, 'MT_PhysSegment', False)):
        try:
            from .MTframework_MHGU_ctc import set_segment_shapes
            _seg_src = ctc_bytes
            _seg_entry = None
            if not _seg_src:
                _seg_entry = find_entry(entries, CTC_MAGIC)
                if _seg_entry is not None:
                    _seg_src = _seg_entry['body']
            if _seg_src:
                _seg, _sg, _sn, _sc = set_segment_shapes(_seg_src, True)
                if _sg:
                    if _seg_entry is not None:
                        _seg_entry['body'] = _seg
                        _seg_entry['raw'] = zlib.compress(_seg, 9)
                        _seg_entry['flag'] = ((_seg_entry['flag'] & 0xFF000000)
                                              | (len(_seg) & 0xFFFFFF))
                    else:
                        ctc_bytes = _seg
                    print('[MT] 骨段碰撞 ShapeObject=2：%d 组 / %d 节点，'
                          '%d 个节点 +6 改成 2，链尾保持 1；CTC 头 +54=3'
                          % (_sg, _sn, _sc))
                else:
                    print('[MT] 警告：骨段碰撞没生效（CTC 结构不认识）')
        except Exception as _e_seg:
            print('[MT] 骨段碰撞失败:', _e_seg)
    if ctc_bytes:
        ctc = find_entry(entries, CTC_MAGIC)
        if ctc is not None:

            ctc['body'] = ctc_bytes
            ctc['raw'] = zlib.compress(ctc_bytes, 9)
            ctc['flag'] = (ctc['flag'] & 0xFF000000) | (len(ctc_bytes) & 0xFFFFFF)
        else:
            entries.append(dict(name=mod['name'], hash=CTC_HASH,
                                flag=0x40000000 | (len(ctc_bytes) & 0xFFFFFF),
                                raw=zlib.compress(ctc_bytes, 9), body=ctc_bytes))
    out = arc_build(entries)
    if not dst:
        dst = arc_path + '.new'

    from .MTframework_MHGU_verify import write_arc_verified
    _dst2, _bak = write_arc_verified(
        dst, out,
        caps=_caps_written or None,
        want_ccl=True if _caps_written else None)
    print('[MT] 已校验并写入 %s%s'
          % (_dst2, ('（备份 %s）' % os.path.basename(_bak)) if _bak else ''))
    return _dst2

def remember_arc(context, arc_path, ctc_bytes):
    sc = context.scene
    sc['MT_ArcPath'] = arc_path or ''
    if arc_path:
        sc['MT_ArcPathLast'] = arc_path
    sc['MT_ArcCtc'] = base64.b64encode(ctc_bytes).decode('ascii') if ctc_bytes else ''

def recalled_arc(context):
    sc = context.scene
    path = sc.get('MT_ArcPath', '') or ''
    ctc_b64 = sc.get('MT_ArcCtc', '') or ''
    ctc = base64.b64decode(ctc_b64) if ctc_b64 else b''
    return path, ctc

try:
    import bpy
    from bpy.props import StringProperty
    from bpy.types import Operator
except Exception:
    bpy = None

def _apply(operator, context, filepath):
    sidecar_source = filepath
    low = filepath.lower()
    if low.endswith('.arc'):
        try:
            tmp, ctc, arc = import_arc_file(filepath)
        except Exception as e:
            operator.report({'ERROR'}, '解析 arc 失败: %s' % e)
            return False
        remember_arc(context, arc, ctc)
        filepath = tmp
    else:
        remember_arc(context, '', b'')

    from .MTframework_MHGU_export import _detect_mod_format
    if _detect_mod_format(filepath) is None:
        operator.report({'ERROR'}, '不支持的 .mod 版本 (本插件只支持 MHGU / Switch)')
        return False
    from .MTframework_MHGU_import import import_mod_file
    props = context.scene.MT_Framework_Props
    import_mod_file(filepath, props.game_fix, sidecar_source=sidecar_source)
    return True

def _phys_armature(context):
    import re as _re
    arms = [o for o in context.scene.objects if o.type == 'ARMATURE']
    best, best_n = None, 0
    for o in arms:
        n = 0
        for b in o.data.bones:
            m = _re.match(r'^b_(\d+)(?:\.[lr])?$', b.name)
            if m and int(m.group(1)) >= 20:
                n += 1
        if n > best_n:
            best, best_n = o, n
    if best is not None:
        return best
    for o in arms:
        if o.name.startswith('MT_Armature') or o.data.name.startswith('MT_Armature'):
            return o
    return arms[0] if arms else None

def _ensure_template(operator, context):
    try:
        from .MTframework_MHGU_physcustom import (
            template_needs_rebuild, rebuild_template_only,
            rebuild_template_from_armature, arm_physics_names,
            _rename_bones, _template_path)
        from .MTframework_MHGU import get_object_center_offset
        arm = _phys_armature(context)
        if arm is None:
            return
        try:
            from .MTframework_MHGU_tpl import sync as _tpl_sync
            tpl = _tpl_sync(context, verbose=False)
        except Exception:
            tpl = context.scene.get('MT_LastImportPath', '') or ''
        if not tpl or not os.path.exists(tpl):
            return
        with open(tpl, 'rb') as f:
            mod = f.read()
        if mod[:4] != b'MOD\x00':
            return
        n_tpl = struct.unpack_from('<H', mod, 6)[0]
        tpl_ptr = struct.unpack_from('<I', mod, 0x24)[0]
        tpl_phys = [mod[tpl_ptr + i * 24] for i in range(n_tpl)]
        tpl_phys = [i for i in tpl_phys if i >= 20]
        arm_phys = arm_physics_names(arm)
        need = template_needs_rebuild(mod, arm)
        mismatch = len(tpl_phys) != len(arm_phys)
        if not need and not mismatch:
            return
        off = get_object_center_offset(arm, context.scene)
        preset = ('auto' if getattr(context.scene, 'MT_PhysAutoInit', False)
                  else getattr(context.scene, 'MT_PhysPreset', 'auto_other'))
        renamed = ''
        if need and not mismatch:
            new_mod, _info = rebuild_template_only(mod, arm, off, preset)
        else:

            new_mod, _info = rebuild_template_from_armature(mod, arm, off, preset)
            rename = {k: v for k, v in (_info.get('rename') or {}).items() if k != v}
            if rename:
                _nb, _ng = _rename_bones(arm, rename)
                try:
                    arm['MT_PhysIdMap'] = {str(k): v for k, v in _info['names'].items()}
                except Exception:
                    pass
                renamed = '；骨名/顶点组按新槽位重命名 %d 骨 / %d 组' % (_nb, _ng)
        tmp = _template_path()
        with open(tmp, 'wb') as f:
            f.write(new_mod)
        context.scene['MT_LastImportPath'] = tmp
        try:
            from .MTframework_MHGU_tpl import store as _tpl_store
            _tpl_store(context, tmp)
        except Exception:
            pass
        try:
            import MT_Framework_Tools.MTframework_MHGU_import as _imp
            _imp._last_import_path = tmp
        except Exception:
            pass
        operator.report({'INFO'},
                        '模板与骨架不一致（模板 %d 骨 / 物理 %d，骨架物理 %d），'
                        '已按骨架重建为 %d 骨%s'
                        % (n_tpl, len(tpl_phys), len(arm_phys),
                           struct.unpack_from('<H', new_mod, 6)[0], renamed))
    except Exception as e:
        operator.report({'WARNING'}, '模板自动重建失败：%s（导出可能不完整）' % e)

def _export(operator, context, filepath):

    try:
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
    except Exception:
        pass

    try:
        from .MTframework_MHGU_tpl import sync as _tpl_sync
        _tpl_sync(context)
    except Exception:
        pass
    _ensure_template(operator, context)
    from .MTframework_MHGU_export import export_mod_file
    props = context.scene.MT_Framework_Props
    out = export_mod_file(filepath, props.game_fix)
    if not out:
        _tpl_now = context.scene.get('MT_LastImportPath', '') or ''
        if _tpl_now and os.path.exists(_tpl_now):
            operator.report(
                {'ERROR'},
                '导出失败（详见系统控制台的 [MT] 行；没选中网格是会导出空模型的，'
                '这条不是那个原因）')
        else:
            operator.report({'ERROR'}, '导出失败: 找不到模板文件 (请先导入一个 .mod)')
        return None
    arc_path, ctc_bytes = recalled_arc(context)
    _tail_target = None

    if not arc_path:
        _last = context.scene.get('MT_ArcPathLast', '') or ''
        if _last and os.path.exists(_last):
            arc_path = _last
            context.scene['MT_ArcPath'] = _last
            operator.report({'WARNING'},
                            '当前没有 arc 容器（刚导入过 .mod），改用上次用的：%s\n'
                            '如果不对，到「模型」区点「选择 arc 容器」重选' % _last)
    _ctc = ctc_bytes

    if not _ctc:
        try:
            from .MTframework_MHGU_physcustom import build_ctc_from_bones
            from .MTframework_MHGU import get_object_center_offset
            from .MTframework_MHGU_boneadd import bone_ids as _bids0
            _arm0 = _phys_armature(context)
            with open(out, 'rb') as _f0:
                _mb0x = _f0.read()
            _nphys0 = len([i for i in _bids0(_mb0x) if i >= 20])
            if _arm0 is not None and _nphys0:
                _b0 = build_ctc_from_bones(
                    _mb0x, _arm0,
                    get_object_center_offset(_arm0, context.scene),
                    getattr(context.scene, 'MT_PhysPreset', 'auto_other'))
                if _b0 and len(_b0) > 0x3C:
                    _ctc = _b0
                    ctc_bytes = _b0
                    remember_arc(context, arc_path, _b0)
                    _g0, _n0c = struct.unpack_from('<II', _b0, 0x10)
                    print('[MT] 工程里没有 CTC，已按骨架重建：%d 组 / %d 节点'
                          % (_g0, _n0c))
                    operator.report(
                        {'WARNING'},
                        '工程里没有物理 CTC，已按骨架自动重建（%d 组 / %d 节点）'
                        % (_g0, _n0c))
        except Exception as _e0:
            print('[MT] 自动生成 CTC 失败:', _e0)

    try:
        import re as _re
        _arm = _phys_armature(context)
        _tpl = context.scene.get('MT_LastImportPath', '') or ''
        if _arm is not None and _tpl and os.path.exists(_tpl):

            _arm_phys = []
            for _b in _arm.data.bones:
                _m = _re.match(r'^b_(\d+)(?:\.[lr])?$', _b.name)
                if _m and int(_m.group(1)) >= 20:
                    _arm_phys.append(_b.name)
            with open(out, 'rb') as _f:
                _mb0 = _f.read()
            _n0 = struct.unpack_from('<H', _mb0, 6)[0]
            _ptr0 = struct.unpack_from('<I', _mb0, 36)[0]
            _tpl_phys = [i for i in (_mb0[_ptr0 + k * 24] for k in range(_n0)) if i >= 20]
            if len(_tpl_phys) != len(_arm_phys):
                _msg = ('模板与骨架的物理骨数量不一致：模板 %d 根 %s，骨架 %d 根 %s。'
                        % (len(_tpl_phys), _tpl_phys, len(_arm_phys), _arm_phys))
                _healed = False
                try:
                    _strict = bool(getattr(props, 'strict_phys', False))
                except Exception:
                    _strict = False

                if len(_tpl_phys) < len(_arm_phys):

                    _tpl0 = _tpl
                    _fixed = None
                    try:
                        _ensure_template(operator, context)
                    except Exception as _e3:
                        print('[MT] 重建模板失败:', _e3)
                    _tpl1 = context.scene.get('MT_LastImportPath', '') or ''
                    if _tpl1 and _tpl1 != _tpl0 and os.path.exists(_tpl1):
                        try:
                            _fixed = export_mod_file(filepath, props.game_fix)
                        except Exception as _e4:
                            print('[MT] 重建模板后重导失败:', _e4)
                    if _fixed:
                        out = _fixed
                        with open(out, 'rb') as _f2:
                            _mb1 = _f2.read()
                        _n1 = struct.unpack_from('<H', _mb1, 6)[0]
                        _p1 = struct.unpack_from('<I', _mb1, 36)[0]
                        _ph1 = [i for i in (_mb1[_p1 + k * 24] for k in range(_n1))
                                if i >= 20]
                        if len(_ph1) >= len(_arm_phys):
                            _healed = True
                            operator.report(
                                {'WARNING'},
                                '模板比骨架少骨，已按骨架自动重建模板并重导'
                                '（物理骨 %d 根）。原模板：%s' % (len(_ph1), _tpl0))
                        else:
                            operator.report(
                                {'ERROR'},
                                _msg + '\n模板比骨架少骨，自动重建后仍不够（物理骨 %d）。'
                                '模板：%s\n请点「重建物理模板」或重新导入一次 .arc。'
                                % (len(_ph1), _tpl1))
                            return None
                    if not _healed:
                        operator.report(
                            {'ERROR'},
                            _msg + '\n模板比骨架少骨，导出的顶点会绑到不存在的骨上；'
                            '自动重建模板也没成功（详见系统控制台 [MT] 行）。'
                            '模板：%s\n请点「重建物理模板」或重新导入一次 .arc 再导出。'
                            % (_tpl1 or _tpl0))
                        return None
                if _strict and not _healed:
                    operator.report({'ERROR'}, _msg + '\n（严格模式已开，可在面板「导入设置」里关掉）')
                    return None
                operator.report({'WARNING'}, _msg + '\n已继续导出（关掉严格模式的结果）')
    except Exception:
        pass

    if _ctc:

        try:
            _ng = struct.unpack_from('<I', _ctc, 0x10)[0]
            _singles = 0
            for _g in range(_ng):
                if struct.unpack_from('<I', _ctc, 0x3C + _g * 80)[0] == 1:
                    _singles += 1
            if _singles:
                operator.report({'WARNING'},
                                'CTC 里有 %d 个「单节点组」：官方每组至少 2 个节点，'
                                '单骨链进游戏容易塌。导出后到「物理骨骼 → 自定义物理骨」'
                                '点 **补全单节点物理链**，再导出一次。' % _singles)
        except Exception:
            pass
        try:
            from .MTframework_MHGU_ctc import check_topology
            with open(out, 'rb') as _f:
                _mod_bytes = _f.read()
            _probs = check_topology(_mod_bytes, _ctc)
            if _probs:

                _built = None
                try:
                    from .MTframework_MHGU_physcustom import build_ctc_from_bones
                    from .MTframework_MHGU import get_object_center_offset
                    _arm2 = _phys_armature(context)
                    if _arm2 is not None:
                        _built = build_ctc_from_bones(
                            _mod_bytes, _arm2,
                            get_object_center_offset(_arm2, context.scene),
                            getattr(context.scene, 'MT_PhysPreset', 'auto_other'),
                            ctc_bytes=_ctc)
                except Exception as _e2:
                    print('[MT] 按模板重建 CTC 失败:', _e2)
                _fixed = None
                if _built and not check_topology(_mod_bytes, _built):
                    _fixed = _built
                if _fixed is None:
                    from .MTframework_MHGU_ctc import rebuild_from_bones
                    _r = rebuild_from_bones(_mod_bytes, _ctc)
                    if _r and not check_topology(_mod_bytes, _r):
                        _fixed = _r
                if _fixed is not None:
                    ctc_bytes = _fixed
                    _ctc = _fixed

                    remember_arc(context, arc_path, ctc_bytes)
                    _ng2, _nc2 = struct.unpack_from('<II', _fixed, 0x10)
                    print('[MT] CTC 已自动重建：%d 组 / %d 节点（原因：%s）'
                          % (_ng2, _nc2, _probs[0]))
                    operator.report(
                        {'INFO'},
                        'CTC 与骨骼链不一致（%s），已自动重建：%d 组 / %d 节点'
                        % (_probs[0], _ng2, _nc2))
                else:
                    _msg = ('CTC 与骨骼链不一致，且自动重建失败：\n  '
                            + '\n  '.join(_probs[:3])
                            + '\n导出会写出一个物理数据残缺的 arc，已中止。'
                              '请先点「重建物理模板」/「补全单节点物理链」，或重新导入一次 .arc。')
                    operator.report({'ERROR'}, _msg)
                    return None
        except Exception:
            pass

    if _ctc and context.scene.get('MT_CtcCustom'):
        try:
            from .MTframework_MHGU_physmat import rebuild_matrices
            _arm_c = _phys_armature(context)
            if _arm_c is not None:
                _cc, _rep_c = rebuild_matrices(_arm_c, _ctc)
                if _cc and _cc != _ctc:
                    ctc_bytes = _cc
                    _ctc = _cc
                    remember_arc(context, arc_path, ctc_bytes)
                    print('[MT] 自定义链矩阵规范化：%d 个节点' % len(_rep_c))
        except Exception:
            pass

    if _ctc:
        try:
            from .MTframework_MHGU_boneadd import bone_ids as _bids
            with open(out, 'rb') as _f:
                _mb_f = _f.read()
            _have = set(_bids(_mb_f))
            _ng = struct.unpack_from('<I', _ctc, 0x10)[0]
            _nc = struct.unpack_from('<I', _ctc, 0x14)[0]
            _no = 0x3C + 80 * _ng
            _missing = sorted({struct.unpack_from('<H', _ctc, _no + k * 96)[0]
                               for k in range(_nc)} - _have)
            if _missing:
                operator.report(
                    {'ERROR'},
                    'CTC 里有 %d 根骨在模型里不存在（id %s）；再导会把这些链裁掉。'
                    '请先点「重建物理模板」/「补全单节点物理链」，或重新导入一次 .arc。'
                    % (len(_missing), _missing[:8]))
                return None
        except Exception:
            pass
    want_arc = filepath.lower().endswith('.arc')

    try:
        from .MTframework_MHGU_matcheck import check as _mcheck, describe as _mdesc
        if arc_path and os.path.exists(arc_path):
            with open(out, 'rb') as f:
                _mb = f.read()
            with open(arc_path, 'rb') as f:
                _entries0 = arc_entries(f.read())
            _m0 = find_entry(_entries0, b'MRL\x00')
            if _m0 is not None:
                _r = _mcheck(_mb, _m0['body'])
                if _r is not None and _r['missing']:
                    operator.report({'WARNING'}, _mdesc(_r))
    except Exception:
        pass

    if not arc_path and want_arc and os.path.exists(filepath):
        try:
            with open(filepath, 'rb') as f:
                if f.read(4) == b'ARC\x00':
                    arc_path = filepath
                    context.scene['MT_ArcPath'] = filepath
        except Exception:
            pass
    if (arc_path and os.path.exists(arc_path)
            and not context.scene.get('MT_SkipArcBuild', False)):
        try:
            with open(out, 'rb') as f:
                mod_bytes = f.read()

            if want_arc:
                dst = filepath
            else:
                dst = os.path.splitext(filepath)[0] + '.arc'
            new_arc = export_arc(context, arc_path, out, mod_bytes, dst)
            _tail_target = new_arc
            if want_arc:

                try:
                    os.remove(out)
                except Exception:
                    pass
                operator.report({'INFO'}, '已导出 arc: %s' % new_arc)
            else:
                operator.report({'INFO'}, '已导出 .mod: %s ；arc: %s' % (out, new_arc))
        except Exception as e:
            operator.report({'WARNING'}, '.mod 已导出(%s)，但重建 arc 失败: %s' % (out, e))
    elif want_arc:
        operator.report({'ERROR'},
                        '要导出 .arc，但工程里没有记住 arc 容器。\n'
                        '解决：① 到「模型」区点「选择 arc 容器」，选原版 body.arc；'
                        '或 ② 把导出文件名填成一个已存在的 .arc 的完整路径。\n'
                        '（导入 .mod 会把容器清掉；重新导入原来的 .arc 也会恢复）')
        return None
    else:
        operator.report({'INFO'}, '已导出: %s' % out)
        _tail_target = out

    try:
        if _tail_target and os.path.exists(_tail_target):
            from .MTframework_MHGU_bontails import write as _tail_write
            _tail_write(_tail_target, _phys_armature(context))
    except Exception as _e_tail:
        print('[MT] 骨骼尾端 sidecar 跳过:', _e_tail)
    return out

if bpy is not None:

    class MT_OT_SetArcContainer(Operator):
        bl_idname = "mt_framework.set_arc_container"
        bl_label = "选择 arc 容器"
        bl_description = "选一个原版防具 .arc 当容器；导出时会替换里面的 .mod 并保留其它条目"

        filepath: StringProperty(subtype='FILE_PATH')
        filter_glob: StringProperty(default="*.arc", options={'HIDDEN'})

        def execute(self, context):
            if not self.filepath or not self.filepath.lower().endswith('.arc'):
                self.report({'ERROR'}, '请选择一个 .arc')
                return {'CANCELLED'}
            try:
                with open(self.filepath, 'rb') as f:
                    data = f.read()
                entries = arc_entries(data)
            except Exception as e:
                self.report({'ERROR'}, '读取失败: %s' % e)
                return {'CANCELLED'}
            if find_entry(entries, MOD_MAGIC) is None:
                self.report({'ERROR'}, '这个 arc 里没有 .mod')
                return {'CANCELLED'}
            _arc, ctc = recalled_arc(context)
            if not ctc:
                c = find_entry(entries, CTC_MAGIC)
                if c is not None:
                    ctc = c['body']
            remember_arc(context, self.filepath, ctc)
            self.report({'INFO'}, 'arc 容器已设置: %s' % os.path.basename(self.filepath))
            return {'FINISHED'}

        def invoke(self, context, event):
            context.window_manager.fileselect_add(self)
            return {'RUNNING_MODAL'}

    class MT_OT_ImportArc(Operator):
        bl_idname = "mt_framework.import_arc"
        bl_label = "导入 ARC"
        bl_description = "导入防具 .arc：自动解包 .mod，并保留物理数据 (CTC)"

        filepath: StringProperty(subtype='FILE_PATH')
        filter_glob: StringProperty(default="*.arc", options={'HIDDEN'})

        def execute(self, context):
            if not self.filepath:
                return {'CANCELLED'}
            if not _apply(self, context, self.filepath):
                return {'CANCELLED'}
            return {'FINISHED'}

        def invoke(self, context, event):
            context.window_manager.fileselect_add(self)
            return {'RUNNING_MODAL'}

    _classes = [MT_OT_ImportArc, MT_OT_SetArcContainer]

    def register():
        for c in _classes:
            bpy.utils.register_class(c)

    def unregister():
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
