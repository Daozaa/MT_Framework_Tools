# -*- coding: utf-8 -*-
"""骨骼段回写 —— 为 MT_Framework_Tools 1.1.7 补齐导出侧实现。

1.1.7 原本**完全没有骨骼回写**: 导出时骨骼段原样照抄模板文件。所以你在
Blender 里怎么改骨骼, 文件里的骨架都不会变 —— 而游戏是按骨骼的 world 位置
给角色定位并做形变的 (实测: 只改根骨的 world, 模型立刻错位并被拉伸)。

段布局 (对 MHGU 实机文件实测确认)
---------------------------------
    ptr_Bone
      + 0                      BoneInfo[N]       每条 24 字节
      + N*24                   local 矩阵[N]      每个 64 字节 (4x4 float, 列主序)
      + N*24 + N*64            world 矩阵[N]      每个 64 字节
      + N*24 + N*128           LUT[256]           256 字节 (逻辑骨序号 -> 物理)

  BoneInfo 24 字节的字段 (实测, 与 1.3.0 的回写一致):
      +0  ID      u8
      +1  Parent  u8      (255 = 根; 也见过 Parent==自身)
      +2  Child   u8
      +3  uk1     u8
      +4  float   ??      (31.58 / 43.34 / 37.33 ... 语义未知, **原样保留**)
      +8  float   len     == |local.t|              <-- 不是平移分量!
      +12 float   t.x     local.t 的 X
      +16 float   t.y
      +20 float   t.z

  注意: 把 +4 起的三个 float 当成平移是**常见误读** —— 那会整整错开 8 字节。

  4x4 矩阵的平移分量在字节偏移 48 (列主序最后一列 = float 12,13,14)。
"""
from __future__ import annotations

import struct

BONE_INFO_SIZE = 24
BONE_MATRIX_SIZE = 64
BONE_LUT_SIZE = 256
BONE_MATRIX_TRANS_OFFSET = 48


def bone_section_offsets(ptr_bone, bone_count):
    """返回 (BoneInfo, local, world, LUT) 四个段的起始偏移。"""
    info_off = int(ptr_bone)
    local_off = info_off + bone_count * BONE_INFO_SIZE
    world_off = local_off + bone_count * BONE_MATRIX_SIZE
    lut_off = world_off + bone_count * BONE_MATRIX_SIZE
    return info_off, local_off, world_off, lut_off


def read_bone_section(data, ptr_bone, bone_count):
    """解析骨骼段。返回 dict: infos / local_t / world_t / scale / offsets。"""
    info_off, local_off, world_off, lut_off = bone_section_offsets(
        ptr_bone, bone_count)
    if lut_off + BONE_LUT_SIZE > len(data):
        raise ValueError(
            "骨骼段超出文件范围 (ptr_Bone=%d, N=%d, 需要到 %d, 文件 %d)"
            % (ptr_bone, bone_count, lut_off + BONE_LUT_SIZE, len(data)))

    infos = []
    local_t = []
    world_t = []
    for i in range(bone_count):
        o = info_off + i * BONE_INFO_SIZE
        infos.append({
            'ID': data[o],
            'Parent': data[o + 1],
            'Child': data[o + 2],
            'uk1': data[o + 3],
            # +4 的 float 语义未知 -> 原样保留
            'uk4': struct.unpack_from('<f', data, o + 4)[0],
            'len': struct.unpack_from('<f', data, o + 8)[0],
            't': list(struct.unpack_from('<3f', data, o + 12)),
        })
        local_t.append(tuple(struct.unpack_from(
            '<3f', data, local_off + i * BONE_MATRIX_SIZE
            + BONE_MATRIX_TRANS_OFFSET)))
        world_t.append(tuple(struct.unpack_from(
            '<3f', data, world_off + i * BONE_MATRIX_SIZE
            + BONE_MATRIX_TRANS_OFFSET)))

    # 去量化系数 S: .mod 把它**烘焙进世界矩阵的 3x3 部分**, 同一文件内所有
    # 骨骼一致 —— 实测 身体 193.4593 / 手臂 173.2272 / 头盔 79.0273。
    # 取 3x3 的 [0][0] 元素 (矩阵列主序, 所以就是矩阵起始处的那个 float)。
    #
    # **不是列长**: 按 sqrt(x²+y²+z²) 算会得到 1.0, 因为 3x3 的正交部分是
    # 单位化的, 只有 [0][0] 带着这个系数。
    scale = _scale_from_matrix(data, world_off)
    return {
        'infos': infos, 'local_t': local_t, 'world_t': world_t,
        'scale': scale,
        'offsets': (info_off, local_off, world_off, lut_off),
    }


def _scale_from_matrix(data, world_off):
    """从**世界**矩阵取去量化系数: 3x3 的 [0][0] (列主序 = 第一个 float)。"""
    s = abs(struct.unpack_from('<f', data, world_off)[0])
    if s < 1e-6:
        s = 1.0
    return s


def bone_head_to_file_translation(p, scale):
    """Blender 骨骼头 -> 文件里世界矩阵的平移分量 (与导入互为逆)。

    导入用 ``convert_bone_position(t) = (-t.x, t.z, -t.y)``,
    所以反向是 ``t = (-p.x*S, -p.z*S, p.y*S)``。
    """
    return (-p[0] * scale, -p[2] * scale, p[1] * scale)


def root_record(infos):
    """找出根骨的记录号 (Parent 越界或指向自己)。找不到返回 None。"""
    n = len(infos)
    for i, inf in enumerate(infos):
        par = inf['Parent']
        if par == i or not (0 <= par < n):
            return i
    return None


def plan_bone_write(data, ptr_bone, bone_count, arm_obj, name_map=None,
                    offset=None, anchor=True, template_bytes=None,
                    cur_mesh_min_y=None):
    """算出回写方案, **不改 data**。

    ``name_map``: {骨骼名: 记录号} —— 由调用方从导入时记录的对照表取得;
                  给了就用它, 否则按 Blender 骨骼的 ``b_N`` 名字自己推。
    ``offset``:   Blender 世界 -> 文件坐标要减掉的居中平移量。

    **不做"整体平移补偿"。** 网格和骨架都来自同一个 Blender 场景, 本来就一致;
    只补偿骨架会把两者拆开 (实测过: 脚贴地了但骨骼与网格错位)。
    """
    import bpy  # noqa: F401
    from mathutils import Matrix, Vector

    if bone_count <= 0 or arm_obj is None:
        return None
    sec = read_bone_section(data, ptr_bone, bone_count)
    infos = sec['infos']
    scale = sec['scale']
    off = Vector(offset) if offset is not None else Vector((0.0, 0.0, 0.0))

    # 记录号 -> Blender 骨骼
    rec_of = {}
    for b in arm_obj.data.bones:
        idx = None
        if name_map:
            idx = name_map.get(b.name)
        if idx is None:
            idx = _record_from_name(b.name)
        if idx is None or not (0 <= idx < bone_count):
            continue
        rec_of.setdefault(idx, b)
    if not rec_of:
        raise ValueError("骨架 %s 里没有一根骨骼能对上骨序号 (b_N)" % arm_obj.name)

    # ---- 1d) 父子级: 以 Blender 骨架为准（以前**完全没写** Parent） ----
    #
    # 现象: 在 Blender 里把物理骨的父级改成腿，导出后游戏里还挂在腰上。
    # 原因: 导出只回写 local/world 平移，BoneInfo+1 的 Parent 永远照抄模板。
    # 这里把"骨架里的父子关系"和文件里的 Parent 对一遍，不一样的记下来，
    # 顺便把该骨的 local.t 按**新父骨**重算（local.t = -(world_i - world_parent)）。
    rec_by_name = {b.name: i for i, b in rec_of.items()}
    new_parent = {}
    _par_skipped = 0
    for idx, b in rec_of.items():
        p = getattr(b, 'parent', None)
        if p is None:
            continue                       # 骨架根: 根骨语义特殊, 保持原样
        pid = rec_by_name.get(p.name)
        if pid is None or not (0 <= pid < bone_count) or pid == idx:
            _par_skipped += 1              # 父骨不在骨表里 -> 不敢猜, 不动
            continue
        if pid != infos[idx]['Parent']:
            new_parent[idx] = pid
    for idx, pid in new_parent.items():
        infos[idx]['Parent'] = pid

    rel = Matrix.Translation(-off) @ arm_obj.matrix_world

    # ---- 1) 新的 world 平移 ----
    new_world = [tuple(v) for v in sec['world_t']]
    for idx, b in rec_of.items():
        new_world[idx] = bone_head_to_file_translation(rel @ b.head_local, scale)

    # ---- 1b) 容差吸附 ----
    #
    # 上面这个值是把文件里的数绕 Blender 走一圈再算回来的, 单精度往返会带出
    # ~1e-7 量级的噪声。若直接与旧值比"是否相等", 未改动的模型也会被判成
    # "19/19 根都动了", 于是每根骨骼都被重写 —— 逐字节一致就没了。
    #
    # 所以: 差值小于容差就**吸附回原值**。容差跟着该文件骨骼坐标的量级走
    # (近零分量用固定阈值挡不住)。
    magnitude = 1.0
    for w in list(new_world) + list(sec['world_t']):
        for v in w:
            if abs(v) > magnitude:
                magnitude = abs(v)
    tol = 1e-5 * magnitude
    _snapped = 0
    for idx in list(rec_of.keys()):
        ow = sec['world_t'][idx]
        nw = new_world[idx]
        if max(abs(nw[k] - ow[k]) for k in range(3)) <= tol:
            new_world[idx] = ow
            _snapped += 1

    # ---- 1c) 锚定: 把整副骨架**刚性平移**回模板的绝对位置 ----
    #
    # 为什么需要这一步 (实测确认的机制):
    #   在编辑模式挪骨骼 **不会**让网格形变 —— Blender 的骨架修改器算的是
    #   "姿态相对静止姿态", 你改静止姿态时姿态跟着变, 形变恒等。
    #   (实测: 逐根骨骼上移 0.05, 网格形变量全部 0.000000, 连有 497 个加权
    #    顶点的 b_9 也是 0。)
    #   于是导出的文件里: 网格还在原处、骨骼跑到新位置 -> **两者相对关系变了**
    #   -> 游戏按骨架给角色定位 -> 模型落点跟着变 -> 脚陷进地面。
    #
    #   而用户挪骨骼的**本意**是"把骨架适配到我的模型" —— 模型该待在原地,
    #   骨架去适应它。所以这里把骨架整体平移回去, 只保留**形状**上的改动。
    #
    # 这是**刚性平移**: 每根骨骼减同一个向量 ->
    #   * 父子差值不变 -> local.t 完全不受影响 ✔
    #   * 骨架的形状 (各骨骼相对位置) 完整保留 ✔
    #   * 网格不需要动 -> 相对关系回到模板的样子 ✔
    #
    # 根骨的 local.t 是游戏的类型标志 (实测 400 个文件里只有 0 和 15.4),
    # 而且它推不出来, 所以第 2 步里一律原样保留 —— 刚性平移不会碰它。
    _anchor_delta = None
    _anchor_dbg = None
    if anchor:
        _r = root_record(infos)
        if _r is not None:
            # ★ 判据不是"根骨动没动", 而是**网格↔根骨的相对高度变没变**。
            #
            #   移动骨架对象  -> 网格是子级, 一起动 -> 相对高度**不变** -> 不锚定
            #   编辑模式挪根骨 -> 网格不动, 根骨动 -> 相对高度**变了** -> 锚定回去
            #   编辑模式挪肢体骨 -> 根骨没动 -> 相对高度不变 -> 不锚定
            #     (那种改动是用户想要的, 不该被抹掉)
            #
            # 第一版只看"根骨动没动", 于是用户平移整副骨架时也被锚定,
            # 网格跟着走了、骨架被拉回来 -> 相对关系反而被扯开 0.10 (实测)。
            _tpl_root_wz = -sec['world_t'][_r][1] / (scale or 1.0)
            _cur_root_wz = -new_world[_r][1] / (scale or 1.0)
            _tpl_mesh = mesh_min_y(template_bytes) if template_bytes is not None \
                else None
            _cur_mesh = cur_mesh_min_y
            _anchor_dbg = {
                'tpl_mesh': _tpl_mesh, 'cur_mesh': _cur_mesh,
                'tpl_root_wz': _tpl_root_wz, 'cur_root_wz': _cur_root_wz,
                'has_tpl_bytes': template_bytes is not None,
                'gap': None, 'threshold': None,
            }
            if _tpl_mesh is not None and _cur_mesh is not None:
                _tpl_rel = _tpl_mesh - _tpl_root_wz
                _cur_rel = _cur_mesh - _cur_root_wz
                _gap = _cur_rel - _tpl_rel
                _anchor_dbg['gap'] = _gap
                _anchor_dbg['tpl_rel'] = _tpl_rel
                _anchor_dbg['cur_rel'] = _cur_rel
                _anchor_dbg['threshold'] = tol / max(scale or 1.0, 1e-9)
                if abs(_gap) > tol / max(scale or 1.0, 1e-9):
                    # 要把相对高度补回 _gap, 需要把整副骨架沿世界 Z 平移 -_gap。
                    # ★ 符号: world_z = -file_y / S  ->  世界 Z 变化 -_gap 对应
                    #   file_y 变化 **+_gap * S**。
                    #   第一版写成 `_dy = _gap * S`, 结果骨架被推到反方向
                    #   (实测 d4: 该 +19.346 却给了 -19.346, 相对关系反而差更多)。
                    _dy = -_gap * (scale or 1.0)
                    _anchor_delta = (0.0, _dy, 0.0)
                    for _i in range(bone_count):
                        _w = list(new_world[_i])
                        _w[1] += _dy
                        new_world[_i] = tuple(_w)
                    for _i in range(bone_count):
                        if max(abs(new_world[_i][k] - sec['world_t'][_i][k])
                               for k in range(3)) <= tol:
                            new_world[_i] = sec['world_t'][_i]

    # ---- 2) 由父子差反推 local ----
    # 子骨的 local.t = -(world[child] - world[parent])  (实测确认)
    # 根骨没有父级, 它的 local.t 是独立偏移 -> 只在根骨**真的动过**时按
    # "相对文件原点"重算, 否则原样保留。
    #
    # 实测: 400 个真实文件里根骨的 local.t 只有两个取值 (0 和 15.4), 而且与
    # 去量化系数 S 无关 —— 它是游戏的**类型标志**, 绝不是能自己编的数。
    root = root_record(infos)
    new_local = [list(v) for v in sec['local_t']]
    for i in range(bone_count):
        par = infos[i]['Parent']
        if not (0 <= par < bone_count) or par == i:
            # ★★ 根骨 (可能不止一根 —— 实测 wst 部件有两个根): local.t **永不重算**。
            #
            # 这里曾经写的是"动过就按 -world 重算", 那是**错的** ——
            # 实测 GUGU18 导出后根骨 local.t 从 (0,0,0) 变成了
            # (+86.458, +113.488, +18.720), 进游戏脚直接穿到地下。
            #
            # 为什么不能重算:
            #   1. 它是游戏的**类型标志**, 400 个真实文件里只有 0 和 15.4 两个取值;
            #   2. 它与去量化系数 S 无关, 量和 world 完全不是一回事;
            #   3. 根骨没有父级, 这个值**推不出来** (1.3.0 的注释也这么说)。
            # 所以: 原样保留。它动了也不管 —— 游戏定位用的是 world_t (实机验证过)。
            continue
        parent_moved = max(abs(new_world[par][k] - sec['world_t'][par][k])
                           for k in range(3)) > tol
        self_moved = max(abs(new_world[i][k] - sec['world_t'][i][k])
                         for k in range(3)) > tol
        if not (parent_moved or self_moved) and i not in new_parent:
            continue                       # 没动过 -> 原样保留, 保证字节一致
        new_local[i] = [-(new_world[i][k] - new_world[par][k]) for k in range(3)]

    # 局部偏移也做一次吸附 (同样的浮点噪声问题)
    for i in range(bone_count):
        ol = sec['local_t'][i]
        nl = new_local[i]
        if max(abs(nl[k] - ol[k]) for k in range(3)) <= tol:
            new_local[i] = list(ol)

    return {
        'sec': sec,
        'new_local': [tuple(v) for v in new_local],
        'new_world': new_world,
        'unmapped': bone_count - len(rec_of),
        'root': root,
        'snapped': _snapped,
        'anchor_delta': _anchor_delta,
        'anchor_dbg': _anchor_dbg,
        'tol': tol,
        'scale': scale,
        'offsets': sec['offsets'],
        'new_parent': new_parent,
        'parent_skipped': _par_skipped,
    }


def mesh_min_y(data, on_error=None):
    """从 .mod 字节里读**顶点文件坐标的 Y 最低点**。纯 Python, 不依赖 Blender。

    定位公式逐字抄自插件自己的导入器 (MTframework_MHGU_import.py:372-374):
        base = ptr_vertex + vertBase + vertStride * vertStart
        第 i 个顶点的位置 = base + i*vertStride 的头 6 字节 (3 x int16 / 32767)
    MeshHeader 的字段偏移也按 read_mesh_header 的真实顺序 (见 _mesh_headers)。

    实测校验: 对 f_body001.mod.new 给出 [+0.00018, +0.93332],
    与插件导入同一文件后量到的值完全一致。

    ``on_error``: 传一个 list, 失败原因会 append 进去。
    **不要静默返回 None** —— 我第一版就是这样, 结果"模板网格最低 None"查了半天
    才知道是异常被吞了。
    """
    h = None
    try:
        import struct as _s
        h = _header_of(data)
        pv = int(getattr(h, 'ptr_vertex', 0) or 0)
        pm = int(getattr(h, 'ptr_Mesh', 0) or 0)
        mc = int(getattr(h, 'MeshCount', 0) or 0)
        if not (pv and pm and mc):
            if on_error is not None:
                on_error.append('头部指针为空 pv=%s pm=%s mc=%s' % (pv, pm, mc))
            return None
        lo = 1e30
        found = False
        skipped = 0
        for i in range(mc):
            o = pm + i * 48
            if o + 48 > len(data):
                skipped += 1
                continue
            vc = _s.unpack_from('<h', data, o + 2)[0]
            st = data[o + 10]
            vs = _s.unpack_from('<i', data, o + 12)[0]
            vb = _s.unpack_from('<i', data, o + 16)[0]
            if not vc or st <= 0:
                skipped += 1
                continue
            base = pv + vb + st * vs
            if base < 0 or base + vc * st > len(data):
                skipped += 1
                continue
            for k in range(vc):
                _x, y, _z = _s.unpack_from('<3h', data, base + k * st)
                y = y / 32767.0
                if y < lo:
                    lo = y
                found = True
        if not found and on_error is not None:
            on_error.append('没有可读的子网格 (跳过 %d/%d, ptr_vertex=%d)'
                            % (skipped, mc, pv))
        return lo if found else None
    except Exception as e:
        if on_error is not None:
            on_error.append('%s: %s' % (type(e).__name__, str(e)[:70]))
        return None


def _header_of(data):
    """只取 Header; 不依赖插件的解析器 (那份要 bpy)。"""
    return _MiniHeader(data)


class _MiniHeader(object):
    """Header 里本模块用得到的字段。

    偏移**按 1.1.7 的 read_header 的读取顺序累加**(从文件 offset 6 起):
        +0  BoneCount short   +2  MeshCount short   +4  MatCount  short
        +6  VertCount long    +10 TriangleCount     +14 VertexIds
        +18 VertexBufferSize  +22 Padding           +26 BoneMapCount
        +30 ptr_Bone          +34 ptr_BoneMap       +38 ptr_MatID
        +42 ptr_Mesh          +46 ptr_vertex        +50 ptr_triangle
    换算成文件绝对偏移 = 上面各值 + 6。
    """

    def __init__(self, data):
        import struct as _s
        self.BoneCount = _s.unpack_from('<h', data, 6)[0]
        self.MeshCount = _s.unpack_from('<h', data, 8)[0]
        self.VertCount = _s.unpack_from('<i', data, 12)[0]
        self.ptr_Bone = _s.unpack_from('<i', data, 36)[0]
        self.ptr_Mesh = _s.unpack_from('<i', data, 48)[0]
        self.ptr_vertex = _s.unpack_from('<i', data, 52)[0]
        self.ptr_triangle = _s.unpack_from('<i', data, 56)[0]


def check_export(data, ptr_bone, bone_count, plan, mesh_objs, coff=None,
                 template_bytes=None, arm_obj=None):
    """导出后的一致性校验。**只返回告警文本, 不改任何数据。**

    为什么需要: 前面踩过的每一个坑, 导出时都是**静默**的 ——
      * 顶点超出 ±1.0   -> 被 int16 钳位压扁/截断, 插件不吭声
      * 骨架整体挪了     -> 相对网格的位置变了, 插件不吭声
    两项都在这里报出来。返回 (告警 list, 详情 dict)。
    """
    msgs = []
    info = {}
    _arm_for_check = arm_obj

    # ★ 拿不到网格就退回"场景里全部网格"。
    # 校验**绝不能因为参数为空而静默通过** —— 实测踩过: 传进来的列表是空的,
    # 顶点最大值报 0.00000, 看上去"没发现问题", 实际上一个顶点都没查。
    _objs = [o for o in (mesh_objs or []) if o is not None and o.type == 'MESH']
    if not _objs:
        try:
            import bpy as _bpy
            _objs = [o for o in _bpy.context.scene.objects if o.type == 'MESH']
            info['mesh_source'] = '场景全部网格 (调用方没给)'
        except Exception:
            _objs = []
    else:
        info['mesh_source'] = '导出实际写入的网格'
    info['mesh_checked'] = len(_objs)

    # ---- 1) 顶点范围 vs ±1.0 ----
    lim = 0.98
    mx = 0.0
    worst = None
    for o in _objs:
        if o is None or o.type != 'MESH':
            continue
        mw = o.matrix_world
        c = coff
        try:
            from .MTframework_MHGU import get_object_center_offset as _g
            c = _g(o)
        except Exception:
            pass
        try:
            for v in o.data.vertices:
                w = (mw @ v.co) - c
                m = max(abs(w.x), abs(w.z), abs(w.y))
                if m > mx:
                    mx = m
                    worst = o.name
        except Exception as e:
            msgs.append("顶点范围检查失败: %s" % e)
            break
    info['vert_max'] = mx
    info['vert_worst'] = worst
    if mx > 1.0:
        msgs.append(
            "顶点超出 ±1.0 (最大 %.4f, 在 %s) —— 超出部分会被 int16 钳位"
            "**压扁/截断**。把模型整体挪进 ±1.0 范围内再导出。"
            % (mx, worst))
    elif mx > lim:
        msgs.append("顶点接近上限 (最大 %.4f, 在 %s), 余量很小。"
                    % (mx, worst))

    # ---- 1a2) 骨骼段三份同步: amat_t + p_world == C ----
    #
    # 这条不变量的来源是第三方改模 skill 包（mhgu-armor-swap /
    # references/retarget.md §2.3）的独立实测结论，和本插件自己的实现互相印证：
    # 同一根骨的平移在文件里存三份 ——
    #     ① BoneInfo+12（rest）② lmat+48 ③ amat+48（绑定逆矩阵）
    # 且满足 amat_t = C − p_world（C = 该文件的顶点量化参考点）。
    # 蒙皮时 (C − p_world) + p_world = C 精确抵消 ⇒ bind pose 不随骨位漂移；
    # 漏改 ③ 会让绑该骨的几何**整体平移**（表象是"模型被拉长/下沉"）。
    #
    # 这里用**即将写出的** new_local / new_world 复算，不重读文件：
    # p_world 由 new_local 沿父链累加（bind pose 下 3×3 是单位阵）。
    if plan is not None and bone_count > 0:
        try:
            infos = plan['sec']['infos']
            nl = plan['new_local']
            nw = plan['new_world']
            pw = [None] * bone_count
            for _ in range(bone_count * 4):
                for i in range(bone_count):
                    if pw[i] is not None:
                        continue
                    par = infos[i]['Parent']
                    if par == i or not (0 <= par < bone_count):
                        pw[i] = tuple(nl[i])
                    elif pw[par] is not None:
                        pw[i] = tuple(pw[par][k] + nl[i][k] for k in range(3))
            if all(v is not None for v in pw):
                cs = [tuple(nw[i][k] + pw[i][k] for k in range(3))
                      for i in range(bone_count)]
                c0 = cs[0]
                spread = max(max(abs(cs[i][k] - c0[k]) for k in range(3))
                             for i in range(bone_count))
                mag = max(1.0, max(abs(v) for c in cs for v in c))
                info['amat_c'] = c0
                info['amat_spread'] = spread
                if spread > 1e-3 * mag:
                    msgs.append(
                        "骨骼段三份不同步: amat_t + p_world 在各槽位不是同一个常量 C "
                        "(最大偏差 %.5f)。绑到这些骨上的几何会在游戏里整体平移。"
                        "检查写入时 BoneInfo / lmat / amat 三份是否都更新了。"
                        % spread)
        except Exception as e:
            msgs.append("骨骼段不变量检查失败: %s" % e)

    # ---- 1b) 网格最低点必须落在文件 Y = 0 ----
    #
    # 这是**逆向 500 个官方 .mod 得到的硬约定**: 每一个文件的网格最低点都
    # 恰好是 +0.00000 (标准差 0)。也就是说游戏期望"脚底在文件坐标 Y=0"。
    # 偏离它, 模型在游戏里就会整体偏高或偏低 —— 这正是"脚悬空/陷地"的直接量。
    _mesh_lo = None
    try:
        _lo = 1e30
        for o in _objs:
            mw = o.matrix_world
            c = coff
            try:
                from .MTframework_MHGU import get_object_center_offset as _g3
                c = _g3(o)
            except Exception:
                pass
            for v in o.data.vertices:
                z = (mw @ v.co).z - c.z
                if z < _lo:
                    _lo = z
        if _lo < 1e29:
            _mesh_lo = _lo
    except Exception:
        pass
    info['mesh_min'] = _mesh_lo
    if _mesh_lo is not None:
        # 容差 = 几个 int16 量化步长 (1/32767 ≈ 3.05e-5)
        _tol0 = 1e-3
        if _mesh_lo > _tol0:
            msgs.append(
                "网格最低点在文件 Y = %+.5f, 而官方 500 个文件**全部**是 0.00000。"
                "模型在游戏里会整体**悬空** %.5f (文件单位约 %.2f)。"
                "把模型下移 %.5f 再导出。" % (_mesh_lo, _mesh_lo, _mesh_lo * 100,
                                            _mesh_lo))
        elif _mesh_lo < -_tol0:
            msgs.append(
                "网格最低点在文件 Y = %+.5f, 而官方 500 个文件**全部**是 0.00000。"
                "模型在游戏里会整体**陷进地面** %.5f (文件单位约 %.2f)。"
                "把模型上移 %.5f 再导出。" % (_mesh_lo, _mesh_lo, -_mesh_lo * 100,
                                            -_mesh_lo))

    # ---- 1c) 骨架对象有没有被挪过 ----
    #
    # 干净导入时, 骨架对象的 location **恰好等于** 场景的 MT_CenterOffset ——
    # 因为"导入后居中"只移动根级对象, 而骨架没有父级 (网格是它的子级, 跟着走)。
    # 这条是个简单可靠的自查判据:
    #     location == 自身偏移记录  -> 没被人动过
    #     不相等                     -> 骨架被移动过, 差值就是移动量
    # 用户"对准根骨"那一步就是在这里留下痕迹的。
    if _arm_for_check is not None:
        try:
            _rec = _arm_for_check.get('MT_CenterOffsetObj')
            _loc = _arm_for_check.location
            if _rec:
                _dv = (_loc[0] - float(_rec[0]),
                       _loc[1] - float(_rec[1]),
                       _loc[2] - float(_rec[2]))
                info['arm_moved'] = _dv
                if max(abs(x) for x in _dv) > 1e-4:
                    msgs.append(
                        "骨架对象被移动过: location %s, 而导入时记录的是 %s, "
                        "差 %s。干净导入时两者应当相等。"
                        "如果你是想让模型适配骨架, 应该移动**模型**而不是骨架。"
                        % (tuple(round(x, 5) for x in _loc),
                           tuple(round(float(x), 5) for x in _rec),
                           tuple(round(x, 5) for x in _dv)))
        except Exception:
            pass

    # ---- 2) 骨架整体挪动了多少 ----
    if plan is not None:
        sec = plan['sec']
        n = bone_count
        dw = 0.0
        for i in range(n):
            o = sec['world_t'][i]
            v = plan['new_world'][i]
            dw = max(dw, max(abs(v[k] - o[k]) for k in range(3)))
        info['bone_delta'] = dw
        mag = max(1.0, max(max(abs(x) for x in w) for w in sec['world_t']))
        if dw > 1e-4 * mag + 1e-4:
            msgs.append(
                "骨架相对模板挪动了 (最大 %.4f 文件单位)。如果这**不是**你有意"
                "移动的, 角色在游戏里的落点会跟着变 —— 请把骨架对回原位再导出。"
                % dw)
        r = plan.get('root')
        info['root_old'] = sec['world_t'][r] if r is not None else None
        info['root_new'] = plan['new_world'][r] if r is not None else None
        info['moved_bones'] = sum(
            1 for i in range(n)
            if plan['new_world'][i] != sec['world_t'][i]
            or plan['new_local'][i] != sec['local_t'][i])

        # ---- 3) 网格 ↔ 骨架 的**相对关系**有没有变 ----
        #
        # 这是最要紧的一条。骨架的位置和网格的位置各自都可能合理地变, 但
        # 「网格最低点 相对于 最低骨骼」这个量**必须保持** —— 它变了就说明
        # 两者被调脱节了, 进游戏表现为模型整体偏高/偏低。
        #
        # 换算: 顶点 file_y = 世界 Z; 骨骼 file_y = -(世界Z) * S。
        # 所以 **世界 Z 最低的骨骼 = file_y 最大的那个** (负得最少)。
        # 第一版写成 min() 取到了头骨 (file_y=-157.9 -> 世界Z=0.816), 那是反的。
        S = sec['scale'] or 1.0
        # ★ 必须用**原始模板字节**读网格范围, 不能用 data ——
        # 导出在校验之前已经改写过 MeshHeader (重打包), 从 data 读会失败。
        _err = []
        tpl_mesh = mesh_min_y(
            template_bytes if template_bytes is not None else data, _err)
        info['tpl_mesh_err'] = _err[0] if _err else None
        tpl_bone = max(sec['world_t'][i][1] for i in range(n))
        tpl_bone_wz = -tpl_bone / S
        cur_bone = max(plan['new_world'][i][1] for i in range(n))
        cur_bone_wz = -cur_bone / S
        cur_mesh = None
        if _objs:
            lo = 1e30
            for o in _objs:
                mw = o.matrix_world
                c = coff
                try:
                    from .MTframework_MHGU import get_object_center_offset as _g2
                    c = _g2(o)
                except Exception:
                    pass
                for v in o.data.vertices:
                    z = (mw @ v.co).z - c.z
                    if z < lo:
                        lo = z
            if lo < 1e29:
                cur_mesh = lo
        if tpl_mesh is not None and cur_mesh is not None:
            rel_t = tpl_mesh - tpl_bone_wz
            rel_c = cur_mesh - cur_bone_wz
            d = rel_c - rel_t
            info['rel_template'] = rel_t
            info['rel_current'] = rel_c
            info['rel_delta'] = d
            info['rel_delta_file'] = d * S
        info['tpl_mesh'] = tpl_mesh
        info['cur_mesh'] = cur_mesh
        info['tpl_bone_wz'] = tpl_bone_wz
        info['cur_bone_wz'] = cur_bone_wz
        if info.get('rel_delta') is not None and abs(info['rel_delta']) > 2e-3:
            msgs.append(
                "网格与骨架的相对关系变了 %.5f (文件单位约 %.2f)。"
                "模板里「网格最低点 - 最低骨骼」= %.5f, 现在是 %.5f。"
                "这会让模型在游戏里整体%s。"
                % (info['rel_delta'], info['rel_delta'] * S,
                   info['rel_template'], info['rel_current'],
                   '偏高' if info['rel_delta'] > 0 else '偏低'))
    return msgs, info


def find_armature(armatures, bone_count, name_map=None):
    """挑出要回写的骨架。返回 ``(armature, 原因)``; 找不到返回 ``(None, 原因)``。

    1.1.7 原本没有这个函数 (它根本没有骨骼回写)。判据:
      骨骼数必须吻合 (这是硬条件, 否则骨序号对不上);
      再优先名字能对上 ``b_N`` 的根数最多的那副。
    """
    if not armatures:
        return None, "场景里没有骨架 (Armature)"
    cands = []
    for a in armatures:
        try:
            if a is None or a.type != 'ARMATURE':
                continue
            nb = len(a.data.bones)
        except Exception:
            continue
        if nb != bone_count:
            continue
        # 优先用这副骨架自己的对照表; 调用方给的次之
        m = None
        try:
            from .MTframework_MHGU import get_armature_bone_name_map as _g
            m = _g(a)
        except Exception:
            m = None
        if not m:
            m = name_map or {}
        named = 0
        for b in a.data.bones:
            idx = m.get(b.name)
            if idx is None:
                idx = _record_from_name(b.name)
            if idx is not None:
                named += 1
        cands.append((named, a))
    if not cands:
        return None, "没有骨骼数 = %d 的骨架" % bone_count
    cands.sort(key=lambda x: -x[0])
    return cands[0][1], ""


def _record_from_name(name):
    """从 ``b_12`` 这类名字取 **0 基**骨序号; 取不到返回 None。

    ★ 两个坑, 都实测踩过:

    1. **必须减 1 (0 基)。** 这要和 name_map (`'b_1' -> 0`) 以及插件自己的
       ``_bone_index_from_name`` (``return int(rest) - 1``) 一致。
       我第一版返回 ``int('1') = 1``, 于是凡是不在 name_map 里的骨骼
       全部错开一根 —— 实测: 双臂场景下 name_map 被后一次导入覆盖成 7 条目,
       第 8~19 根走回退, 骨架整体偏了 73 文件单位。

    2. **带 ``.l`` / ``.r`` 后缀的名字**返回 None。因为 ``b_2.r`` 的记录号是 1、
       ``b_2.l`` 是 4 —— 同一个数字 2 对应两个不同记录, 从名字推不出来。
       这种情况**必须**靠 name_map; 猜错比不猜更糟 (会写坏骨骼段)。
    """
    if not name or not name.startswith('b_'):
        return None
    rest = name[2:]
    if not rest.isdigit():
        return None                    # 带后缀 -> 无法从名字推出记录号
    try:
        return int(rest) - 1
    except ValueError:
        return None


def write_bone_section(data, ptr_bone, bone_count, arm_obj, name_map=None,
                       offset=None, anchor=True, template_bytes=None,
                       cur_mesh_min_y=None):
    """把方案写进 ``bytearray`` data (就地)。返回 plan (便于报告改动量)。"""
    plan = plan_bone_write(data, ptr_bone, bone_count, arm_obj,
                           name_map=name_map, offset=offset, anchor=anchor,
                           template_bytes=template_bytes,
                           cur_mesh_min_y=cur_mesh_min_y)
    if plan is None:
        return None
    info_off, local_off, world_off, lut_off = plan['offsets']
    sec = plan['sec']

    for i in range(bone_count):
        o = info_off + i * BONE_INFO_SIZE
        t = plan['new_local'][i]
        w = plan['new_world'][i]
        old_t = sec['local_t'][i]
        old_w = sec['world_t'][i]

        # **没变就一个字节都不碰。**
        # `len` 字段虽然数值上等于 |local.t|, 但它是**独立存的 float** ——
        # 用 sqrt() 重算会差 1 ulp, 于是"原样重写"会出现 1 字节差异,
        # 破坏"未改动模型导出与原件逐字节一致"这条保证 (实测 arm/body 命中)。
        _np = (plan.get('new_parent') or {}).get(i)
        if t == old_t and w == old_w and _np is None:
            continue
        if _np is not None:
            # +1 = Parent (u8)；改父级后物理链就会挂到新父骨上
            data[o + 1] = _np

        if t != old_t:
            ln = (t[0] ** 2 + t[1] ** 2 + t[2] ** 2) ** 0.5
            # +4 的未知 float **不动**; 只更新 len 与 t
            struct.pack_into('<f', data, o + 8, ln)
            struct.pack_into('<3f', data, o + 12, t[0], t[1], t[2])
            struct.pack_into('<3f', data,
                             local_off + i * BONE_MATRIX_SIZE
                             + BONE_MATRIX_TRANS_OFFSET, t[0], t[1], t[2])
        if w != old_w:
            struct.pack_into('<3f', data,
                             world_off + i * BONE_MATRIX_SIZE
                             + BONE_MATRIX_TRANS_OFFSET, w[0], w[1], w[2])
    return plan
