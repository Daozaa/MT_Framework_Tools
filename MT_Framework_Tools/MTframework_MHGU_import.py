# -*- coding: utf-8 -*-

"""

MT Framework MHGU - MOD 文件导入逻辑

"""

import bpy

import os

import math

from mathutils import Vector, Quaternion

from .MTframework_MHGU import *

from . import compat

# Track last imported file path for export template

_last_import_path = None


def _decode_normal4(b):
    """4 字节 (x, z, -y, pad) -> Blender 法向, 与 MTframework_MHGU.read_normal 同序。"""
    def s(v):
        return v - 256 if v > 127 else v
    x = s(b[0]) / 127.0
    z = s(b[1]) / 127.0
    y = -s(b[2]) / 127.0
    return Vector((x, y, z))


def _looks_like_normals(raw_list):
    """判断一批 4 字节是不是真的法向: 单位长度命中率 >= 90%。

    为什么需要这个判据: 同一个 FVF 槽位, **原版文件**里这 4 字节不是法向
    (实测模长 0.12), 而**本插件导出的文件**里写的就是法向 (模长 1.0)。
    所以只能按数据判断, 不能按 FVF 写死 —— 否则要么读进垃圾法向,
    要么自己导出的模型再导入时丢法向 (实测踩过)。
    """
    if not raw_list:
        return False
    good = 0
    for b in raw_list:
        if b is None or len(b) < 4:
            continue
        n = _decode_normal4(b)
        if 0.5 <= n.length <= 1.5:
            good += 1
    return good >= 0.9 * len(raw_list)


def import_mod_file(filepath, game_fix="mhgu"):

    """

    导入 .mod 文件�?Blender

    参数:

        filepath: .mod 文件路径

        game_fix: 游戏修复模式 ("mhgu", "dmc4se", "lp2", "dd", "re0", "re2")

    """

    global mod_ver, hidedege, hidelod0, _last_import_path

    _last_import_path = filepath

    # 记录导入前已有的对象名, 便于导入结束后只对本次新建的对象做居中
    _pre_import_names = set(o.name for o in bpy.data.objects)

    # 保存到场景以便跨会话使用

    try:

        bpy.context.scene['MT_LastImportPath'] = filepath

        # ★ 1.2.185：把模板字节存进 .blend，「另存工程」分支也会带着自己的模板
        try:
            from .MTframework_MHGU_tpl import store as _tpl_store
            _tpl_store(bpy.context, filepath)
        except Exception:                               # noqa: BLE001
            pass

    except Exception:

        pass

    is_mhgu = (game_fix == "mhgu")

    is_dmc4se = (game_fix == "dmc4se")

    is_lp2 = (game_fix == "lp2")

    is_dd = (game_fix == "dd")

    is_re0 = (game_fix == "re0")

    is_re2 = (game_fix == "re2")

    # 确保�?OBJECT 模式�?

    if bpy.context.mode != 'OBJECT':

        try:

            bpy.ops.object.mode_set(mode='OBJECT')

        except Exception:

            pass

    f = open(filepath, 'rb')

    if f is None:

        return {'CANCELLED'}

    # 读取 "MOD" 魔数

    magic = read_fixed_string(f, 4)

    if magic != "MOD":

        f.close()

        raise ValueError("不是有效�?MOD 文件")

    mod_ver = read_short(f)

    # 读取文件�?

    hdr = read_header(f)

    bCount = hdr.BoneCount

    MeshScale = [1.0, 1.0, 1.0]

    # 边界球体和边界盒

    BoundingSphere = get_bound(f)

    BoundingBoxMin = get_bound(f)

    BoundingBoxMax = get_bound(f)

    # 创建边界球体 (Empty) - 使用直接 API 避免 bpy.ops 崩溃

    bound_sphere = bpy.data.objects.new("BoundSphere", None)

    bound_sphere.empty_display_type = 'SPHERE'

    bound_sphere.location = (BoundingSphere[0], BoundingSphere[1], BoundingSphere[2])

    bound_sphere.empty_display_size = BoundingSphere[3]

    bpy.context.collection.objects.link(bound_sphere)

    bound_sphere.hide_set(True)

    # 创建边界盒最小点

    bound_box_min = bpy.data.objects.new("BoundBoxMin", None)

    bound_box_min.empty_display_type = 'SPHERE'

    bound_box_min.location = (BoundingBoxMin[0], BoundingBoxMin[1], BoundingBoxMin[2])

    bound_box_min.empty_display_size = 10.0

    bpy.context.collection.objects.link(bound_box_min)

    bound_box_min.hide_set(True)

    # 创建边界盒最大点

    bound_box_max = bpy.data.objects.new("BoundBoxMax", None)

    bound_box_max.empty_display_type = 'SPHERE'

    bound_box_max.location = (BoundingBoxMax[0], BoundingBoxMax[1], BoundingBoxMax[2])

    bound_box_max.empty_display_size = 10.0

    bpy.context.collection.objects.link(bound_box_max)

    bound_box_max.hide_set(True)

    # 读取 LOD 数据

    lodzero = read_long(f)

    lodone = read_long(f)

    LDC = read_long(f)

    pad = read_long(f)

    entrycount = read_long(f)

    # ---- 读取骨骼 ----
    # 骨骼段布局 (已用实机文件验证, LUT 正好结束于 ptr_BoneMap):
    #   bone infos : BoneCount * 24 字节
    #   local mats : BoneCount * 64 字节
    #   world mats : BoneCount * 64 字节
    #   bone LUT   : 256 字节
    f.seek(hdr.ptr_Bone, os.SEEK_SET)

    BoneArray = []
    BoneLocalMatrices = []
    BoneWorldMatrices = []
    Mtp = []
    Armature = None

    if bCount != 0:

        # 1) 骨骼信息 (24 字节/根)
        for i in range(bCount):
            BoneArray.append(read_bone_info(f))

        # 2) 局部矩阵 (每根 64 字节)
        for i in range(bCount):
            BoneLocalMatrices.append(read_matrix(f))

        # 3) 世界矩阵 (每根 64 字节) —— 骨骼的实际摆放位置
        for i in range(bCount):
            BoneWorldMatrices.append(read_matrix(f))

        # 4) 骨骼查找表 (256 字节, 0xFF 表示未使用)
        Mtp = [read_byte(f) + 1 for _ in range(256)]

        # 5) 骨架的**创建**延后到顶点解析之后 (见下方 "创建骨架"),
        #    因为需要实测网格包围盒才能把骨骼对齐到网格坐标系.
        #    旧版本创建 b_* Empty 空物体, 无法蒙皮/无法用于动画,
        #    这正是"导入后没有骨骼"的原因.
        _dequant = get_dequant_scale(BoneWorldMatrices, bCount)

    else:
        Mtp = [1] * 256

    # 网格对象缩放: 顶点已是 0..1 归一化区间, 与 (已反量化的) 骨骼位置同量级,
    # 因此网格缩放保持 1.0. 旧版本套用世界矩阵的 3x3 系数 (约 193 倍)
    # 导致模型巨大.
    MeshScale = compute_mesh_scale(BoneWorldMatrices, bCount)
    if bCount != 0:
        print("文件反量化系数 = {:.5f}; 网格对象缩放 = {}".format(_dequant, MeshScale))

    if bCount == 0:

        MeshScale = [1.0, 1.0, 1.0]

    # ---- 骨骼映射 ----
    # MHGU 顶点数据里的骨骼索引直接就是骨架骨骼索引 (1 基),
    # 不需要额外映射表; 仅 256 (即 0 基 255+1) 表示"无骨骼"。
    _bone_maps = []

    # ---- 构建 LOD/FVF/MAT ID 列表 ----

    LODIDS = []

    LODNAMES = []

    f.seek(hdr.ptr_Mesh, os.SEEK_SET)

    mc = hdr.MeshCount

    for i in range(mc):

        f.seek(7, os.SEEK_CUR)

        lvl = read_byte(f)

        if is_dmc4se:

            lvl = lvl - 1

        if is_lp2:

            lvl = lvl + 7

        f.seek(40, os.SEEK_CUR)

        if lvl != 0:

            if i == 0:

                LODIDS.append(lvl)

                LODNAMES.append(str(lvl))

            else:

                if lvl not in LODIDS:

                    LODIDS.append(lvl)

                    LODNAMES.append(str(lvl))

    LODNAMES.append("All")

    # 构建 FVF ID 列表

    FVFIDS = []

    FVFNAMES = []

    f.seek(hdr.ptr_Mesh, os.SEEK_SET)

    for i in range(mc):

        f.seek(20, os.SEEK_CUR)

        lvl = read_long(f)

        f.seek(24, os.SEEK_CUR)

        if i == 0:

            FVFIDS.append(lvl)

            FVFNAMES.append(hex(lvl))

        else:

            if lvl not in FVFIDS:

                FVFIDS.append(lvl)

                FVFNAMES.append(hex(lvl))

    FVFNAMES.append("All")

    # 构建材质 ID 列表

    MATIDS = []

    MATNAMES = []

    f.seek(hdr.ptr_Mesh, os.SEEK_SET)

    for i in range(mc):

        f.seek(5, os.SEEK_CUR)

        lvl = read_short(f) // 16

        f.seek(41, os.SEEK_CUR)

        if i == 0:

            MATIDS.append(lvl)

            MATNAMES.append(str(lvl))

        else:

            if lvl not in MATIDS:

                MATIDS.append(lvl)

                MATNAMES.append(str(lvl))

    MATNAMES.append("All")

    # ---- 读取网格信息 ----

    f.seek(hdr.ptr_Mesh, os.SEEK_SET)

    mc = hdr.MeshCount

    MeshInfo_array = []

    for i in range(mc):

        mhdr = read_mesh_header(f)

        MeshInfo_array.append([

            mhdr.vertCount, mhdr.vertStride, mhdr.vertStart,

            mhdr.vertBase, mhdr.faceStart, mhdr.faceCount,

            mhdr.faceBase, mhdr.lodLevel, mhdr.fvfInfo,

            mhdr.MatId, mhdr.unk01, mhdr.unk05, mhdr.meshtype

        ])

    # ---- 读取顶点数据 ----

    MeshVertex_array = [None] * mc

    MeshUV_array = [None] * mc

    MeshUV_arrayb = [None] * mc

    MeshNormal_array = [None] * mc

    MeshBoneID_array = [None] * mc

    MeshBoneWeight_array = [None] * mc

    MeshBoneLimit = [0] * mc

    for i in range(mc):

        f.seek(hdr.ptr_vertex + MeshInfo_array[i][3], os.SEEK_SET)

        f.seek(MeshInfo_array[i][1] * MeshInfo_array[i][2], os.SEEK_CUR)

        vc = MeshInfo_array[i][0]

        VertexPos_array = [None] * vc

        UV_array = [None] * vc

        UV_arrayb = [None] * vc

        Normal_array = [None] * vc

        BoneID_array = [None] * vc

        BoneWeight_array = [None] * vc

        b1 = b2 = b3 = b4 = b5 = b6 = b7 = b8 = 0

        w1 = w2 = w3 = w4 = w5 = w6 = w7 = w8 = wa = 0.0

        # LP2/DMC4SE FVF 修复

        if is_lp2:

            MeshInfo_array[i][8] = MeshInfo_array[i][8] + 7

        if is_dmc4se:

            MeshInfo_array[i][8] = MeshInfo_array[i][8] - 1

        fvf = MeshInfo_array[i][8]

        # ---- 根据 FVF 格式读取顶点 ----

        if fvf == 0x9399C037:

            # 24 bytes: short3 pos, 4 bytes normal, 4 bytes ?, half2 uv, half2 uv2, 4 bytes color

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)  # ?

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = read_uv_half(f)

                f.seek(4, os.SEEK_CUR)  # color

        elif fvf == 0xAFA63031:

            # 20 bytes: short3 pos, 4 bytes normal, 4 bytes ?, half2 uv, half2 uv2

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)  # ?

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = read_uv_half(f)

        elif fvf == 0xC66FA03E:

            # 16 bytes: short3 pos, 4 bytes ?, half2 uv, half2 uv2

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                f.seek(4, os.SEEK_CUR)

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = read_uv_half(f)

        elif fvf == 0xB3921020:

            # 24 bytes: short3 pos, short w, 4 bytes normal, 4 bytes ?, half2 bone, half2 uv, half2 uv2, 8 bytes ?

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                w1 = read_short_signed(f) / 32767.0

                w2 = 1.0 - w1

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)  # ?

                v = read_float16(f); b1 = int(v) + 1 if not math.isnan(v) else 0 

                v = read_float16(f); b2 = int(v) + 1 if not math.isnan(v) else 0 

                if b1 == b2:

                    BoneID_array[c] = [b1, b1]

                    BoneWeight_array[c] = [w1, w1]

                else:

                    BoneID_array[c] = [b1, b2]

                    BoneWeight_array[c] = [w1, w2]

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = read_uv_half(f)

                f.seek(8, os.SEEK_CUR)

            MeshBoneLimit[i] = 2

        elif fvf == 0x64593025:

            # 40 bytes: short3 pos, short w, 8 bytes normal/tangent, 4 bytes bone ids, half2 uv, half2 w2/w3, 4 bytes ?, half2 uv2, 4 bytes ?

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                w1 = read_short_signed(f) / 32767.0

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)  # tangent

                b1 = read_byte(f) + 1

                b2 = read_byte(f) + 1

                b3 = read_byte(f) + 1

                b4 = read_byte(f) + 1

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

                w2 = read_float16(f)

                w3 = read_float16(f)

                w4 = 1.0 - (w1 + w2 + w3)

                f.seek(4, os.SEEK_CUR)  # zeros

                UV_arrayb[c] = read_uv_half(f)  # UV2

                f.seek(4, os.SEEK_CUR)  # zeros

                # 重新分配权重

                wt = w1 + w2 + w3 + w4

                if wt > 0:

                    w1 /= wt

                    w2 /= wt

                    w3 /= wt

                    w4 /= wt

                b = [b1]

                w = [w1]

                if b2 not in b:

                    b.append(b2)

                    w.append(w2)

                if b3 not in b:

                    b.append(b3)

                    w.append(w3)

                if b4 not in b:

                    b.append(b4)

                    w.append(w4)

                wa = sum(w)

                if wa != 1.0:

                    w[0] += 1.0 - wa

                # 3ds Max 兼容性修�?- 填充�?4 个骨�?

                if len(b) == 1:

                    BoneID_array[c] = [b1, b1, b1, b1]

                    BoneWeight_array[c] = [w1, w1, w1, w1]

                elif len(b) == 2:

                    BoneID_array[c] = [b1, b[1], b1, b1]

                    BoneWeight_array[c] = [w1, w[1], w1, w1]

                elif len(b) == 3:

                    BoneID_array[c] = [b1, b[1], b[2], b1]

                    BoneWeight_array[c] = [w1, w[1], w[2], w1]

                else:

                    BoneID_array[c] = [b1, b[1], b[2], b[3]]

                    BoneWeight_array[c] = [w1, w[1], w[2], w[3]]

            MeshBoneLimit[i] = 4

        elif fvf == 0xB0983013 or fvf == 0xB0983014:

            # 12 bytes: short3 pos, byte bone, byte weight, UNORM16 uv

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                b1 = read_byte(f) + 1

                w1 = read_byte(f) / 255.0

                BoneID_array[c] = [b1]

                BoneWeight_array[c] = [1.0]

                u = read_short(f) / 65535.0

                v = read_short(f) / 65535.0

                UV_array[c] = [u, v * -1.0 + 1.0, 0.0]

                UV_arrayb[c] = [0, 0, 0]

            MeshBoneLimit[i] = 1
        
        elif fvf == 0xDB7DA014 or fvf == 0xDB7DA015:

            # 16 bytes: short3 pos, 2 bytes ?, 4 bytes(法向+填充), half2 uv
            #
            # ★ 这 4 字节在**原版文件**里不是法向（实测模长 0.77），但本插件
            #   导出时写的就是法向。按数据判断，别按 FVF 写死 —— 否则自己
            #   导出的模型再导入时会丢法向（用户报的 bug）。

            _nraw = []

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                f.seek(2, os.SEEK_CUR)

                _nraw.append(f.read(4))

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

            if _looks_like_normals(_nraw):

                for c in range(vc):

                    Normal_array[c] = _decode_normal4(_nraw[c])

        elif fvf == 0xB6681034:

            # 16 bytes: short3 pos, 6 bytes ?, half2 uv

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                f.seek(6, os.SEEK_CUR)

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

        elif fvf == 0x0CB6800E:

            # 20 bytes: short3 pos, 2 bytes bone/weight, 4 bytes normal, 4 bytes tangent, half2 uv

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                f.seek(2, os.SEEK_CUR)  # bone id + weight

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)  # tangent

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

        elif fvf == 0x0CB68015 or fvf == 0x0CB68016:

            # 20 bytes: short3 pos, byte bone, byte weight, 4 bytes normal, 4 bytes tangent, half2 uv
            #
            # ★ 这 4 字节在**原版文件**里不是法向（实测模长 0.12），但本插件
            #   导出时写的就是法向。按数据判断，见 _looks_like_normals。

            _nraw = []

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                b1 = read_byte(f) + 1

                w1 = read_byte(f) / 255.0

                BoneID_array[c] = [b1]

                BoneWeight_array[c] = [1.0]

                _nraw.append(f.read(4))  # 可能是法向, 见 _looks_like_normals

                f.seek(4, os.SEEK_CUR)  # tangent

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

            if _looks_like_normals(_nraw):

                for c in range(vc):

                    Normal_array[c] = _decode_normal4(_nraw[c])

            MeshBoneLimit[i] = 1

        elif fvf == 0xA8FAB018 or fvf == 0xA8FAB019:

            # 20 bytes: short3 pos, byte bone, byte weight, 8 bytes normal/tangent, half2 uv

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                b1 = read_byte(f) + 1

                w1 = read_byte(f) / 255.0

                BoneID_array[c] = [b1]

                BoneWeight_array[c] = [1.0]

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)  # tangent

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

            MeshBoneLimit[i] = 1

        elif fvf == 0xA7D7D036:

            # 20 bytes: float3 pos, 4 bytes normal, 2 shorts uv

            for c in range(vc):

                VertexPos_array[c] = read_vec3_pos(f)

                Normal_array[c] = read_normal(f)

                w6 = read_short(f) / 65535.0

                w7 = read_short(f) / 65535.0

                UV_array[c] = [w6, w7, 0]

                UV_arrayb[c] = [0, 0, 0]

            MeshBoneLimit[i] = 0

        elif fvf == 0xC31F201C or fvf == 0xC31F201D:

            # 24 bytes: short3 pos, short w, 8 bytes normal/tangent, half2 uv, half2 bone ids

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                w1 = read_short_signed(f) / 32767.0

                w2 = 1.0 - w1

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)  # tangent

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

                v = read_float16(f); b1 = int(v) + 1 if not math.isnan(v) else 0 

                v = read_float16(f); b2 = int(v) + 1 if not math.isnan(v) else 0 

                if b1 == b2:

                    BoneID_array[c] = [b1, b1]

                    BoneWeight_array[c] = [w1, w1]

                else:

                    BoneID_array[c] = [b1, b2]

                    BoneWeight_array[c] = [w1, w2]

            MeshBoneLimit[i] = 2

        elif fvf == 0xCBF6C01A:

            # 24 bytes: short3 pos, byte weight, byte bone, 4 bytes normal, 4 bytes tangent, half2 uv, 4 bytes color

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                w1 = read_byte(f) / 255.0

                b1 = read_byte(f) + 1

                BoneID_array[c] = [b1]

                BoneWeight_array[c] = [1.0]

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)  # tangent

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

                f.seek(4, os.SEEK_CUR)  # color

            MeshBoneLimit[i] = 1

        elif fvf == 0x207D6037:

            # 24 bytes: float3 pos, 4 bytes normal, half2 uv, 4 bytes color

            for c in range(vc):

                VertexPos_array[c] = read_vec3_pos(f)

                Normal_array[c] = read_normal(f)

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

                f.seek(4, os.SEEK_CUR)  # color

            MeshBoneLimit[i] = 0

        elif fvf == 0xD1A47038:

            # 24 bytes: float3 pos, 4 bytes normal, half2 uv, half2 uv2

            for c in range(vc):

                VertexPos_array[c] = read_vec3_pos(f)

                Normal_array[c] = read_normal(f)

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = read_uv_half(f)  # uv2 LM

            MeshBoneLimit[i] = 0

        elif fvf == 0xD8297028:

            # 24 bytes: float3 pos, 4 bytes normal, 4 bytes color, half2 uv

            for c in range(vc):

                VertexPos_array[c] = read_vec3_pos(f)

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)  # color

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

            MeshBoneLimit[i] = 0

        elif fvf == 0xC66FA03A:

            # 24 bytes: float3 pos, 4 bytes normal, half2 uv, half2 uv2

            for c in range(vc):

                VertexPos_array[c] = read_vec3_pos(f)

                Normal_array[c] = read_normal(f)

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

                UV_arrayb[c] = read_uv_half(f)  # uv2 LM

            MeshBoneLimit[i] = 0

        elif fvf == 0x667B1019:

            # 28 bytes: short3 pos, 10 bytes ?, half2 uv, half2 uv2

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                f.seek(10, os.SEEK_CUR)

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

                UV_arrayb[c] = read_uv_half(f)  # uv2 LM

            MeshBoneLimit[i] = 1

        elif fvf in (0x14D40019, 0x14D40020, 0x14D40021, 0x14D40022):

            # 28 bytes: short3 pos, short w, 8 bytes normal/tangent, 4 bytes bone ids, half2 uv, half2 w2/w3

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                w1 = read_short_signed(f) / 32767.0

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)  # tangent

                b1 = read_byte(f) + 1

                b2 = read_byte(f) + 1

                b3 = read_byte(f) + 1

                b4 = read_byte(f) + 1

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

                w2 = read_float16(f)

                w3 = read_float16(f)

                w4 = 1.0 - (w1 + w2 + w3)

                wt = w1 + w2 + w3 + w4

                if wt > 0:

                    w1 /= wt

                    w2 /= wt

                    w3 /= wt

                    w4 /= wt

                b = [b1]

                w = [w1]

                if b2 not in b:

                    b.append(b2)

                    w.append(w2)

                if b3 not in b:

                    b.append(b3)

                    w.append(w3)

                if b4 not in b:

                    b.append(b4)

                    w.append(w4)

                if len(b) == 1:

                    BoneID_array[c] = [b1, b1, b1, b1]

                    BoneWeight_array[c] = [w1, w1, w1, w1]

                elif len(b) == 2:

                    BoneID_array[c] = [b1, b[1], b1, b1]

                    BoneWeight_array[c] = [w1, w[1], w1, w1]

                elif len(b) == 3:

                    BoneID_array[c] = [b1, b[1], b[2], b1]

                    BoneWeight_array[c] = [w1, w[1], w[2], w1]

                else:

                    BoneID_array[c] = [b1, b[1], b[2], b[3]]

                    BoneWeight_array[c] = [w1, w[1], w[2], w[3]]

            MeshBoneLimit[i] = 4

        elif fvf == 0x5E7F202C:

            # 28 bytes: float3 pos, 4 bytes normal, 4 bytes tangent, half2 uv, half2 uv2

            for c in range(vc):

                VertexPos_array[c] = read_vec3_pos(f)

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)  # tangent

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = read_uv_half(f)  # lightmap uv

            MeshBoneLimit[i] = 0

        elif fvf in (0x2BE814D4, 0x7CD414D4):

            # 28 bytes: short3 pos, 22 bytes ?

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                f.seek(22, os.SEEK_CUR)

                UV_array[c] = [0, 0, 0]

                UV_arrayb[c] = [0, 0, 0]

        elif fvf in (0xA320C016, 0xA320C017):

            # 28 bytes: short3 pos, 2 bytes ?, 4 bytes normal, 4 bytes tangent, 4 bytes binormal, half2 uv, half2 uv2

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                f.seek(2, os.SEEK_CUR)

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)  # tangent

                f.seek(4, os.SEEK_CUR)  # binormal

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = read_uv_half(f)

        elif fvf == 0x49B4F029:

            # 28 bytes: float3 pos, 4 bytes normal, 4 bytes tangent, half2 uv, half2 uv2

            for c in range(vc):

                VertexPos_array[c] = read_vec3_pos(f)

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)  # tangent

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = read_uv_half(f)

        elif fvf == 0x0D9E801D:

            # 28 bytes: short3 pos, 22 bytes ?

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                f.seek(22, os.SEEK_CUR)

                UV_array[c] = [0, 0, 0]

                UV_arrayb[c] = [0, 0, 0]

            MeshBoneLimit[i] = 2

        elif fvf == 0xA013501E:

            # 28 bytes: short3 pos, short w, 4 bytes normal, 4 bytes tangent, half2 uv, half2 bone ids, 4 bytes color

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                w1 = read_short_signed(f) / 32767.0

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)  # tangent

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

                v = read_float16(f); b1 = int(v) + 1 if not math.isnan(v) else 0 

                v = read_float16(f); b2 = int(v) + 1 if not math.isnan(v) else 0 

                w2 = 1.0 - w1

                f.seek(4, os.SEEK_CUR)  # color

                BoneID_array[c] = [b1, b2]

                BoneWeight_array[c] = [w1, w2]

            MeshBoneLimit[i] = 2

        elif fvf == 0xD877801B:

            # 32 bytes: short3 pos, byte bone, byte 0, 4 bytes normal, 4 bytes tangent, half2 uv, 4 bytes zero, half2 uv2, 4 bytes zero
            # （游戏数据实测: +6 = 骨骼索引 0 基、+7 恒 0；旧版按「权重, 骨骼」读反了）

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                b1 = read_byte(f) + 1

                read_byte(f)  # +7：官方恒 0，忽略

                BoneID_array[c] = [b1]

                BoneWeight_array[c] = [1.0]

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)  # tangent

                UV_array[c] = read_uv_half(f)

                f.seek(4, os.SEEK_CUR)  # zero

                UV_arrayb[c] = read_uv_half(f)  # UV2

                f.seek(4, os.SEEK_CUR)  # zero

            MeshBoneLimit[i] = 1

        elif fvf in (0x747D1031, 0x9399C033, 0xB86DE02A, 0x12553032, 0x926FD02E):

            # 32 bytes: float3 pos, 4 bytes normal, 4 bytes tangent, half2 uv, half2 uv2, 4 bytes color/uv3

            for c in range(vc):

                VertexPos_array[c] = read_vec3_pos(f)

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)  # tangent

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = read_uv_half(f)  # uv2 LM

                f.seek(4, os.SEEK_CUR)  # color/uv3

        elif fvf == 0xA14E003C:

            # 32 bytes: short3 pos, 26 bytes ?

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                f.seek(26, os.SEEK_CUR)

                UV_array[c] = [0, 0, 0]

                UV_arrayb[c] = [0, 0, 0]

        elif fvf == 0xDA55A021:

            # 36 bytes: short3 pos, 2 bytes ?, 4 bytes normal, 4 bytes tangent, 4 bytes bone ids, half2 uv, 4 bytes weights, half2 uv2

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                f.seek(2, os.SEEK_CUR)

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)  # tangent

                b1 = read_byte(f) + 1

                b2 = read_byte(f) + 1

                b3 = read_byte(f) + 1

                b4 = read_byte(f) + 1

                UV_array[c] = read_uv_half(f)

                w1 = read_byte(f) / 255.0

                w2 = read_byte(f) / 255.0

                w3 = read_byte(f) / 255.0

                w4 = read_byte(f) / 255.0

                UV_arrayb[c] = [0, 0, 0]

                UV_arrayb[c] = read_uv_half(f)  # UV2

                BoneID_array[c] = [b1, b2, b3, b4]

                BoneWeight_array[c] = [w1, w2, w3, w4]

            MeshBoneLimit[i] = 4

        elif fvf == 0xB392101F:

            # 36 bytes: short3 pos, 2 bytes ?, 4 bytes normal, 4 bytes tangent, half2 uv, half2 uv2, 4 bytes uv3, 4 bytes ?, 4 bytes ?

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                f.seek(2, os.SEEK_CUR)

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)  # tangent/weights/bone ids

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

                UV_arrayb[c] = read_uv_half(f)  # UV2

                f.seek(4, os.SEEK_CUR)  # uv3

                f.seek(4, os.SEEK_CUR)  #

                f.seek(4, os.SEEK_CUR)  #

        elif fvf == 0xBB424024 or fvf == 0xBB424025:

            # 36 bytes: 8-bone skin for facial animation

            # short3 pos, short w1, 4 bytes normal, 4 bytes w2-w5 (bytes), 8 bytes bone ids (b1-b8), half2 uv, 2 half-floats w6/w7, 4 bytes tangent

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                w1 = read_short_signed(f) / 32767.0

                Normal_array[c] = read_normal(f)

                w2 = read_byte(f) / 255.0

                w3 = read_byte(f) / 255.0

                w4 = read_byte(f) / 255.0

                w5 = read_byte(f) / 255.0

                b1 = read_byte(f) + 1

                b2 = read_byte(f) + 1

                b3 = read_byte(f) + 1

                b4 = read_byte(f) + 1

                b5 = read_byte(f) + 1

                b6 = read_byte(f) + 1

                b7 = read_byte(f) + 1

                b8 = read_byte(f) + 1

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

                w6 = read_float16(f)

                w7 = read_float16(f)

                w8 = 1.0 - (w1 + w2 + w3 + w4 + w5 + w6 + w7)

                f.seek(4, os.SEEK_CUR)  # tangent

                # 8 bones, sort by weight, keep top 4

                b_list = [b1, b2, b3, b4, b5, b6, b7, b8]

                w_list = [w1, w2, w3, w4, w5, w6, w7, w8]

                # Pair and sort by weight (descending)

                pairs = list(zip(w_list, b_list))

                pairs.sort(key=lambda x: x[0], reverse=True)

                # Take top 4

                top4 = pairs[:4]

                top4_b = [p[1] for p in top4]

                top4_w = [p[0] for p in top4]

                # Re-distribute weights

                wt = sum(top4_w)

                if wt > 0:

                    top4_w = [w / wt for w in top4_w]

                # Deduplicate bones (Blender vertex groups)

                b = [top4_b[0]]

                w = [top4_w[0]]

                for j in range(1, 4):

                    if top4_b[j] not in b:

                        b.append(top4_b[j])

                        w.append(top4_w[j])

                wa = sum(w)

                if wa != 1.0:

                    w[0] += 1.0 - wa

                # Pad to 4 bones

                if len(b) == 1:

                    BoneID_array[c] = [b[0], b[0], b[0], b[0]]

                    BoneWeight_array[c] = [w[0], w[0], w[0], w[0]]

                elif len(b) == 2:

                    BoneID_array[c] = [b[0], b[1], b[0], b[0]]

                    BoneWeight_array[c] = [w[0], w[1], w[0], w[0]]

                elif len(b) == 3:

                    BoneID_array[c] = [b[0], b[1], b[2], b[0]]

                    BoneWeight_array[c] = [w[0], w[1], w[2], w[0]]

                else:

                    BoneID_array[c] = [b[0], b[1], b[2], b[3]]

                    BoneWeight_array[c] = [w[0], w[1], w[2], w[3]]

            MeshBoneLimit[i] = 4

        elif fvf == 0x63B6C02F:

            # 36 bytes: float3 pos, half2 uv2, 4 bytes normal, half2 uv, 4 bytes uv3, 4 bytes uv4, 4 bytes bone id=255

            for c in range(vc):

                VertexPos_array[c] = read_vec3_pos(f)

                UV_arrayb[c] = [0, 0, 0]

                UV_arrayb[c] = read_uv_half(f)  # UV2

                Normal_array[c] = read_normal(f)

                UV_array[c] = read_uv_half(f)

                f.seek(4, os.SEEK_CUR)  # UV3 ?

                f.seek(4, os.SEEK_CUR)  # UV4 ?

                f.seek(4, os.SEEK_CUR)  # bone id = 255 ?

        elif fvf == 0x64593023:

            # 40 bytes: short3 pos, short w1, 8 bytes normal/tangent, 4 bytes bone ids, half2 uv, half2 w2/w3, 4 bytes zeros, half2 uv2, 4 bytes zeros

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                w1 = read_short_signed(f) / 32767.0

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)  # tangent

                b1 = read_byte(f) + 1

                b2 = read_byte(f) + 1

                b3 = read_byte(f) + 1

                b4 = read_byte(f) + 1

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

                w2 = read_float16(f)

                w3 = read_float16(f)

                w4 = 1.0 - (w1 + w2 + w3)

                f.seek(4, os.SEEK_CUR)  # zeros

                UV_arrayb[c] = [0, 0, 0]

                UV_arrayb[c] = read_uv_half(f)  # UV2

                f.seek(4, os.SEEK_CUR)  # zeros

                wt = w1 + w2 + w3 + w4

                if wt > 0:

                    w1 /= wt

                    w2 /= wt

                    w3 /= wt

                    w4 /= wt

                b = [b1]

                w = [w1]

                if b2 not in b:

                    b.append(b2)

                    w.append(w2)

                if b3 not in b:

                    b.append(b3)

                    w.append(w3)

                if b4 not in b:

                    b.append(b4)

                    w.append(w4)

                wa = sum(w)

                if wa != 1.0:

                    w[0] += 1.0 - wa

                if len(b) == 1:

                    BoneID_array[c] = [b1, b1, b1, b1]

                    BoneWeight_array[c] = [w1, w1, w1, w1]

                elif len(b) == 2:

                    BoneID_array[c] = [b1, b[1], b1, b1]

                    BoneWeight_array[c] = [w1, w[1], w1, w1]

                elif len(b) == 3:

                    BoneID_array[c] = [b1, b[1], b[2], b1]

                    BoneWeight_array[c] = [w1, w[1], w[2], w1]

                else:

                    BoneID_array[c] = [b1, b[1], b[2], b[3]]

                    BoneWeight_array[c] = [w1, w[1], w[2], w[3]]

            MeshBoneLimit[i] = 4

        elif fvf == 0x75C3E025:

            # 36 bytes: short3 pos, 14 bytes ?, half2 uv, 16 bytes ?

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                f.seek(14, os.SEEK_CUR)

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

                f.seek(16, os.SEEK_CUR)

        elif fvf == 0xD84E3026:

            # 36 bytes: short3 pos, 14 bytes ?, half2 uv, 16 bytes ?

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                f.seek(14, os.SEEK_CUR)

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

                f.seek(16, os.SEEK_CUR)

        elif fvf == 0xCBCF7027:

            # 48 bytes: 8-bone skin

            # short3 pos, short w1, 4 bytes normal, 4 bytes w2-w5 (bytes), 8 bytes bone ids (b1-b8), half2 uv, short w6, short w7, 4 bytes tangent, 4 bytes zero, half2 uv2, 4 bytes zero

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                w1 = read_short_signed(f) / 32767.0

                Normal_array[c] = read_normal(f)

                w2 = read_byte(f) / 255.0

                w3 = read_byte(f) / 255.0

                w4 = read_byte(f) / 255.0

                w5 = read_byte(f) / 255.0

                b1 = read_byte(f) + 1

                b2 = read_byte(f) + 1

                b3 = read_byte(f) + 1

                b4 = read_byte(f) + 1

                b5 = read_byte(f) + 1

                b6 = read_byte(f) + 1

                b7 = read_byte(f) + 1

                b8 = read_byte(f) + 1

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

                w6 = read_short(f) / 32767.0

                w7 = read_short(f) / 32767.0

                w8 = 1.0 - (w1 + w2 + w3 + w4 + w5 + w6 + w7)

                # 8 bones, sort by weight, keep top 4

                b_list = [b1, b2, b3, b4, b5, b6, b7, b8]

                w_list = [w1, w2, w3, w4, w5, w6, w7, w8]

                pairs = list(zip(w_list, b_list))

                pairs.sort(key=lambda x: x[0], reverse=True)

                top4 = pairs[:4]

                top4_b = [p[1] for p in top4]

                top4_w = [p[0] for p in top4]

                wt = sum(top4_w)

                if wt > 0:

                    top4_w = [w / wt for w in top4_w]

                b = [top4_b[0]]

                w = [top4_w[0]]

                for j in range(1, 4):

                    if top4_b[j] not in b:

                        b.append(top4_b[j])

                        w.append(top4_w[j])

                wa = sum(w)

                if wa != 1.0:

                    w[0] += 1.0 - wa

                if len(b) == 1:

                    BoneID_array[c] = [b[0], b[0], b[0], b[0]]

                    BoneWeight_array[c] = [w[0], w[0], w[0], w[0]]

                elif len(b) == 2:

                    BoneID_array[c] = [b[0], b[1], b[0], b[0]]

                    BoneWeight_array[c] = [w[0], w[1], w[0], w[0]]

                elif len(b) == 3:

                    BoneID_array[c] = [b[0], b[1], b[2], b[0]]

                    BoneWeight_array[c] = [w[0], w[1], w[2], w[0]]

                else:

                    BoneID_array[c] = [b[0], b[1], b[2], b[3]]

                    BoneWeight_array[c] = [w[0], w[1], w[2], w[3]]

                f.seek(4, os.SEEK_CUR)  # tangent

                f.seek(4, os.SEEK_CUR)  # zero

                UV_arrayb[c] = read_uv_half(f)  # UV2

                f.seek(4, os.SEEK_CUR)  # zero

            MeshBoneLimit[i] = 4

        elif fvf == 0x2F55C03D:

            # 64 bytes: short3 pos, short w1, 4 bytes normal (signed bytes), 4 bytes tangent (signed bytes), 4 bytes bone ids, half2 uv, half2 w2/w3, ... padding

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                w1 = read_short_signed(f) / 32767.0

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)  # tangent as signed bytes *4

                b1 = read_byte(f) + 1

                b2 = read_byte(f) + 1

                b3 = read_byte(f) + 1

                b4 = read_byte(f) + 1

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

                w2 = read_float16(f)

                w3 = read_float16(f)

                wa = w1 + w2 + w3

                w4 = 1.0 - wa

                f.seek(4, os.SEEK_CUR)  # zero

                f.seek(4, os.SEEK_CUR)  # zero or 2 short

                f.seek(4, os.SEEK_CUR)  # zero or 2 short

                f.seek(4, os.SEEK_CUR)  # zero

                f.seek(4, os.SEEK_CUR)  # zero

                f.seek(4, os.SEEK_CUR)  # color ?

                f.seek(4, os.SEEK_CUR)  # ?

                f.seek(4, os.SEEK_CUR)  # ?

                b = [b1]

                w = [w1]

                if b2 not in b:

                    b.append(b2)

                    w.append(w2)

                if b3 not in b:

                    b.append(b3)

                    w.append(w3)

                if b4 not in b:

                    b.append(b4)

                    w.append(w4)

                wt = sum(w)

                if wt > 0:

                    w = [x / wt for x in w]

                wa = sum(w)

                if wa != 1.0:

                    w[0] += 1.0 - wa

                if len(b) == 1:

                    BoneID_array[c] = [b[0], b[0], b[0], b[0]]

                    BoneWeight_array[c] = [w[0], w[0], w[0], w[0]]

                elif len(b) == 2:

                    BoneID_array[c] = [b[0], b[1], b[0], b[0]]

                    BoneWeight_array[c] = [w[0], w[1], w[0], w[0]]

                elif len(b) == 3:

                    BoneID_array[c] = [b[0], b[1], b[2], b[0]]

                    BoneWeight_array[c] = [w[0], w[1], w[2], w[0]]

                else:

                    BoneID_array[c] = [b[0], b[1], b[2], b[3]]

                    BoneWeight_array[c] = [w[0], w[1], w[2], w[3]]

            MeshBoneLimit[i] = 4

        else:

            # 未知 FVF 格式 - 默认处理

            print("未知 FVF = {} 在偏�? {}".format(hex(fvf), f.tell()))

            stride = MeshInfo_array[i][1]

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                f.seek(6, os.SEEK_CUR)

                f.seek(stride - 20, os.SEEK_CUR)

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

                f.seek(4, os.SEEK_CUR)

        # 存储顶点数据

        MeshVertex_array[i] = VertexPos_array

        MeshUV_array[i] = UV_array

        MeshUV_arrayb[i] = UV_arrayb

        MeshNormal_array[i] = Normal_array

        MeshBoneID_array[i] = BoneID_array

        MeshBoneWeight_array[i] = BoneWeight_array

    # ---- 创建骨架 (Armature) ----
    # 放在顶点解析之后, 这样可以实测网格包围盒并把骨骼对齐到网格坐标系.
    if bCount != 0 and BoneWorldMatrices:
        try:
            Armature = build_armature(
                "MT_Armature", BoneArray, BoneWorldMatrices, Mtp, _dequant)
            print("骨架已创建: {} 根骨骼 (反量化系数 {:.5f})".format(bCount, _dequant))
        except Exception as _e:
            print("创建骨架失败, 退回空物体表示: {}".format(_e))
            import traceback
            traceback.print_exc()
            Armature = None
            for i in range(bCount):
                cBone = bpy.data.objects.new("b_{}".format(i + 1), None)
                cBone.empty_display_size = 1.5
                cBone.empty_display_type = 'ARROWS'
                bpy.context.collection.objects.link(cBone)
                cBone.matrix_world = BoneWorldMatrices[i]

    # ---- 读取面索引 ----

    f.seek(hdr.ptr_triangle, os.SEEK_SET)

    MeshFace_array = [None] * mc

    vc_limits = [MeshInfo_array[i][0] for i in range(mc)]

    for i in range(mc):

        fc = MeshInfo_array[i][5]

        vstart = MeshInfo_array[i][2]

        vlimit = vc_limits[i]

        # 一次性读入该网格的全部索引
        f.seek(hdr.ptr_triangle + MeshInfo_array[i][4] * 2, os.SEEK_SET)

        raw = [read_short(f) for _ in range(fc)]

        def _loc_tri(a, b, c):
            """转成网格内局部索引; 过滤越界与退化三角形 (含重复顶点)."""
            a -= vstart
            b -= vstart
            c -= vstart
            if not (0 <= a < vlimit and 0 <= b < vlimit and 0 <= c < vlimit):
                return None
            if a == b or b == c or c == a:
                return None
            return [int(a), int(b), int(c)]

        Face_array = []

        use_strip = (0xFFFF in raw) or (fc % 3 != 0)

        if use_strip:

            # 三角条带 (Triangle Strip).
            # 关键: 0xFFFF 是重启标记, 其后**两个**索引用于重新预热条带;
            # 缠绕方向 (reverse) 每生成一个三角形翻转一次, 并在重启时复位.
            # 旧实现把文件指针重新定位后仍从第 0 个索引开始读, 相当于把前
            # 两个索引重复当成第三个顶点, 于是每个条带开头都会多出
            # [0,1,0] 之类的退化三角形 —— 这正是"编辑模式卡死"的根源.
            k = 0
            n = len(raw)

            while k < n:

                if raw[k] == 0xFFFF:

                    k += 1

                    continue

                if k + 2 >= n:

                    break

                f1 = raw[k]

                f2 = raw[k + 1]

                if f1 == 0xFFFF or f2 == 0xFFFF:

                    k += 1

                    continue

                k += 2

                reverse = False

                while k < n and raw[k] != 0xFFFF:

                    f3 = raw[k]

                    k += 1

                    reverse = not reverse

                    # 缠绕方向 (v1.3 修正):
                    # 用文件自带的顶点法向当判据逐面验证过 —— 原来的写法解出来的
                    # 三角形, 几何法向与顶点法向 **96.9% 相反**, 也就是整体绕反了。
                    # 于是 Blender 里看起来正常(默认不背面剔除), 进游戏(有背面剔除)
                    # 就变成内外翻转, 用户只能手动 Flip Normals 才能正常显示。
                    # 这里把两种缠绕对调即可。
                    t = _loc_tri(f1, f2, f3) if reverse else _loc_tri(f1, f3, f2)

                    if t:

                        Face_array.append(t)

                    f1, f2 = f2, f3

        else:

            # 三角列表
            for k in range(0, fc - 2, 3):

                t = _loc_tri(raw[k], raw[k + 1], raw[k + 2])

                if t:

                    Face_array.append(t)

        MeshFace_array[i] = Face_array

    # ---- 构建网格 ----

    # 创建 LOD 空对象组 - 使用直接 API 避免崩溃

    LodEmpties = {}

    lod_levels = [1, 2, 3, 4, 5, 6, 249, 252, 254, 255]

    for lod in lod_levels:

        empty = bpy.data.objects.new("LodGroup_{}".format(lod), None)

        empty.empty_display_type = 'PLAIN_AXES'

        empty.empty_display_size = 10.0

        bpy.context.collection.objects.link(empty)

        LodEmpties[lod] = empty

    other_mesh = bpy.data.objects.new("OtherMesh", None)

    other_mesh.empty_display_type = 'PLAIN_AXES'

    other_mesh.empty_display_size = 10.0

    bpy.context.collection.objects.link(other_mesh)

    # 创建网格

    for i in range(mc):

        verts = MeshVertex_array[i]

        faces = MeshFace_array[i]

        if verts is None or faces is None or len(verts) == 0 or len(faces) == 0:

            continue

        # 创建网格数据

        mesh_data = bpy.data.meshes.new("temp_mesh")

        mesh_data.from_pydata(verts, [], faces)

        # validate() 修复可能的拓扑不一致 (重复索引/悬空边等),
        # 避免进入编辑模式时 BMesh 卡死; 之后必须再 update().
        mesh_data.validate(verbose=False)

        mesh_data.update()

        # ---- 写入自定义法向 ----
        # 从 .mod 读出的法向 (4 个有符号字节) 必须写进 Blender, 否则
        # from_pydata 之后只有按面重算的默认法向, 表现为"法向是默认的"。
        nd = MeshNormal_array[i] if i < len(MeshNormal_array) else None

        _fill = (sum(1 for v in nd if v is not None) / len(nd)) if nd else 0.0

        # 填充率不足时不要写 —— 否则会用垃圾数据覆盖 Blender 自己算的合理法向

        if nd and _fill >= 0.9:

            try:

                mesh_data.use_auto_smooth = True

                mesh_data.normals_split_custom_set_from_vertices(

                    [tuple(v) if v is not None else (0.0, 0.0, 1.0) for v in nd]

                )

            except Exception as e:

                print("  [MT] 写入自定义法向失败: %s" % e)


        # 创建网格对象

        mesh_obj = bpy.data.objects.new("Mesh", mesh_data)

        bpy.context.collection.objects.link(mesh_obj)

        # 命名

        fvf_hex = hex(MeshInfo_array[i][8])

        lod_lvl = MeshInfo_array[i][7]

        mat_id = MeshInfo_array[i][9]

        unk05 = MeshInfo_array[i][10]

        unk01 = MeshInfo_array[i][11]

        meshtype = MeshInfo_array[i][12]

        mesh_obj.name = "Mesh_{}_{}_LODx{}_MatID:{}_Group:{}_DisplayMode:{}_Type:{}".format(

            paddstring(3, str(i + 1)),

            paddstring(10, fvf_hex),

            lod_lvl, mat_id, unk05, unk01, meshtype

        )

        mesh_obj.scale = (MeshScale[0], MeshScale[1], MeshScale[2])

        vc = MeshInfo_array[i][0]

        # 构建 UV - 修复：按 loop �?vertex_index 映射，而非直接�?loop 索引

        uv_data = MeshUV_array[i]

        if uv_data and len(uv_data) > 0 and any(u is not None for u in uv_data):

            uv_layer = mesh_data.uv_layers.new(name="UVMap")

            if uv_layer:

                for loop_idx, loop_vert in enumerate(mesh_data.loops):

                    vi = loop_vert.vertex_index

                    if vi < len(uv_data) and uv_data[vi] is not None:

                        uv_layer.data[loop_idx].uv = (uv_data[vi][0], uv_data[vi][1])

        # 构建 UV2 (lightmap)

        uv2_data = MeshUV_arrayb[i]

        if uv2_data and len(uv2_data) > 0 and any(u is not None and u != [0, 0, 0] for u in uv2_data):

            uv2_layer = mesh_data.uv_layers.new(name="UVMap_Lightmap")

            if uv2_layer:

                # 与 UV1 一样按 loop 的 vertex_index 映射.
                # 旧代码把顶点索引直接当成 loop 索引写入, 面数一多就会错位,
                # 表现为"UV 变奇怪". 这里修正为按 loop 映射.
                for loop_idx, loop_vert in enumerate(mesh_data.loops):

                    vi = loop_vert.vertex_index

                    if vi < len(uv2_data) and uv2_data[vi] is not None:

                        uv2_layer.data[loop_idx].uv = (uv2_data[vi][0], uv2_data[vi][1])

        # 蒙皮 (Vertex Groups) + 骨架修改器

        bone_ids = MeshBoneID_array[i]

        bone_weights = MeshBoneWeight_array[i]

        has_skin = (bone_ids is not None and len(bone_ids) > 0

                    and bone_ids[0] is not None and Armature is not None)

        if has_skin:

            # 该网格的骨骼映射表 (bonemapindex 指向 bone map)
            bone_map = None

            bmi = getattr(mhdr, 'bonemapindex', 0)

            if _bone_maps:

                if 0 <= bmi < len(_bone_maps):

                    bone_map = _bone_maps[bmi]

                else:

                    bone_map = _bone_maps[0]

            def _resolve(bid, _bm=bone_map):

                """顶点中的 1 基骨骼索引 -> 1 基骨架骨骼索引; 0 表示无骨骼."""

                idx = bid - 1

                if idx < 0:

                    return 0

                if _bm and idx < len(_bm):

                    idx = _bm[idx]

                if idx < 0 or idx >= bCount:

                    return 0

                return idx + 1

            # 1) 建立用到的顶点组

            used = {}

            for c in range(vc):

                if c < len(bone_ids) and bone_ids[c] is not None:

                    for bid in bone_ids[c]:

                        r = _resolve(bid)

                        if r > 0:

                            used[r] = bone_name_for(r)

            for r in sorted(used):

                name = used[r]

                if name not in mesh_obj.vertex_groups:

                    mesh_obj.vertex_groups.new(name=name)

            # 2) 写入权重 (跳过无骨骼哨兵, 合并同一骨骼的权重)

            for c in range(vc):

                if (c < len(bone_ids) and bone_ids[c] is not None

                        and c < len(bone_weights) and bone_weights[c] is not None):

                    acc = {}

                    for j in range(len(bone_ids[c])):

                        r = _resolve(bone_ids[c][j])

                        w = bone_weights[c][j]

                        if r > 0 and w > 0:

                            # 同一个骨骼可能在 4 个槽位里被重复填充
                            # (解析器为保证 3ds Max 兼容会复制权重),
                            # 重复槽位代表同一份权重, 必须取最大值而不是相加,
                            # 否则权重会被放大数倍.
                            if w > acc.get(r, 0.0):

                                acc[r] = w

                    # 归一化, 保证权重和恰好为 1 (Blender 骨架变形要求)
                    total = sum(acc.values())

                    if total > 0:

                        for r, w in acc.items():

                            name = used.get(r) or bone_name_for(r)

                            vg = mesh_obj.vertex_groups.get(name)

                            if vg is None:

                                vg = mesh_obj.vertex_groups.new(name=name)

                            vg.add([c], w / total, 'REPLACE')

            # 3) 骨架修改器: 让网格真正随骨骼变形

            if mesh_obj.vertex_groups:

                mod = mesh_obj.modifiers.new(name="Armature", type='ARMATURE')

                mod.object = Armature

                mod.use_vertex_groups = True

        # 父子关系: 有骨架的挂到骨架上, 其余挂到 OtherMesh

        if has_skin and mesh_obj.vertex_groups:

            mesh_obj.parent = Armature

            mesh_obj.matrix_parent_inverse = Armature.matrix_world.inverted()

        else:

            mesh_obj.parent = other_mesh

    # ---- 记录顶点指纹 ----
    # 导出时用它判断用户是否改过顶点(法向/位置/UV/权重)。没有它, 导出器只能靠
    # "顶点数没变"来猜测, 会把用户改过的法向丢掉。
    for _o in bpy.context.scene.objects:
        if _o.type == 'MESH':
            try:
                # 先确保法向已算好, 否则同样的网格在导入时/导出时会算出
                # 不同的法向指纹 -> 被误判成"用户改过" -> 白白重新编码。
                _o.data.update()
                compat.calc_normals_split(_o.data)
                remember_vertex_fingerprint(_o)
                # 追加上 FVF 的可读类名 (取自原版 3ds Max 插件的对照表),
                # 例如 ..._Type:61439_SkinnedCharacter011_U1NS
                # 注意加在**末尾**, 这样名字里的 parts[2] 仍是 FVF, 过滤功能不受影响。
                _p = _o.name.split('_')
                if len(_p) > 2 and _p[2].startswith('0x'):
                    try:
                        from .MTframework_FVF import fvf_name as _fvf_name
                        _lbl = _fvf_name(int(_p[2], 16))
                        if _lbl and _lbl not in _o.name:
                            _o.name = _o.name + '_' + _lbl
                    except Exception:
                        pass
                # 数据块也起个有意义的名字, 否则全是 temp_mesh,
                # "替换主体"时复制过去的数据块名就没有任何信息量。
                if _o.data is not None and _o.data.name != _o.name:
                    _o.data.name = _o.name
            except Exception as _e:
                print("记录顶点指纹跳过 %s: %s" % (_o.name, _e))

    # ---- 对称骨骼命名 (.l / .r) ----
    # 让 Blender 的 X 轴镜像/对称化工具能识别左右骨骼; 导出时会用记录下来的
    # 对照表换算回原本的骨序号, 因此导出的 .mod 不受影响。
    try:
        _sym = bpy.context.scene.MT_Framework_Props.sym_bone_names
    except Exception:
        _sym = True
    if _sym:
        try:
            _meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
            _npair, _nmap = apply_symmetric_bone_names(Armature, _meshes)
            if _npair:
                print("骨骼对称命名: %d 对 (例: %s)" % (
                    _npair, ", ".join("%s / %s" % (n, m)
                                      for n, m in list(_nmap.items())[:2])))
        except Exception as _e:
            print("对称命名跳过:", _e)

    # ---- 导入后居中 (便于与第三方模型对齐) ----
    # 只修改对象变换, 不改顶点/骨骼数据, 因此导出时写回的位置仍与文件一致.
    try:
        _mode = bpy.context.scene.MT_Framework_Props.auto_center
    except Exception:
        _mode = 'XY_GROUND'
    if _mode and _mode != 'NONE':
        imported_objs = list(bpy.context.scene.objects)
        # 只处理本次导入新建的对象: 用导入开始时的集合做差
        imported_objs = [o for o in imported_objs if o.name not in _pre_import_names]
        _off = center_objects(imported_objs, _mode)
        if _off.length > 1e-12:
            print("模型已居中 ({}) 平移 = ({:.4f}, {:.4f}, {:.4f})".format(
                _mode, _off.x, _off.y, _off.z))
            print("  平移量已记录到场景 MT_CenterOffset; 导出时会自动换算回文件坐标,"
                  " 不会造成进游戏后整体偏移")

    print("MOD 文件导入完成: {}".format(filepath))

    f.close()

    return {'FINISHED'}

def import_sbc_file(filepath):

    """

    导入 .sbc 碰撞文件�?Blender

    对应原始脚本 ImportsbcButton (lines 801-911)

    参数:

        filepath: .sbc 文件路径

    """

    fname = os.path.splitext(os.path.basename(filepath))[0]

    with open(filepath, "rb") as f:

        # "SBC" magic

        magic = read_fixed_string(f, 3)

        version = read_byte(f)

        if magic != "SBC":

            print("错误: 不是有效�?SBC 文件")

            return

        f.seek(16, 1)  # skip unknown

        unkcounta = read_long(f)

        ncounta = read_long(f)

        vtcount = read_long(f)

        f.seek(212, 0)  # seek_set

        fcountA = read_long(f)  # group1 face count

        f.seek(12, 1)  # seek_cur

        faceArray = []

        # 读取 group1 面数�?(112 bytes each)

        for i in range(fcountA):

            color_val = read_long(f)

            p1 = read_short(f) + 1

            p2 = read_short(f) + 1

            p3 = read_short(f) + 1

            p4 = read_short(f) + 1

            f.seek(100, 1)  # 0xCDCDCDCD then floats

        f.seek(8, 1)   # ???

        f.seek(40, 1)  # ???

        f.seek(32, 1)  # ???

        f.seek(96, 1)  # ???

        # 读取 group2 面数�?

        for i in range(ncounta):

            f.seek(12, 1)  # face normal?

            p1 = read_short(f) + 1

            p2 = read_short(f) + 1

            p3 = read_short(f) + 1

            p4 = read_short(f) + 1  # groupid?

            f.seek(12, 1)  # int zero, 4 bytes flags, int zero

            faceArray.append((p1, p2, p3))

        # 读取顶点

        vertArray = []

        for i in range(vtcount):

            vx = read_float(f)

            vy = read_float(f)

            vz = read_float(f)

            vw = read_float(f)

            # 坐标转换: [vx, -vz, vy] (�?.mod 导入)

            vertArray.append(Vector((vx, -vz, vy)))

        # 创建 Blender 网格

        mesh_data = bpy.data.meshes.new(name=fname)

        mesh_obj = bpy.data.objects.new(name=fname, object_data=mesh_data)

        # 添加到场�?

        bpy.context.collection.objects.link(mesh_obj)

        # 构建网格

        mesh_data.from_pydata(vertArray, [], faceArray)

        mesh_data.update()

        # 设置半透明材质颜色 (灰色, 半透明) —— 跨版本安全写法
        from . import compat

        mat, bsdf = compat.make_simple_material(
            fname + "_collision", (0.5, 0.5, 0.5, 1.0), alpha=0.5)

        if mesh_obj.data.materials:

            mesh_obj.data.materials[0] = mat

        else:

            mesh_obj.data.materials.append(mat)

        mesh_obj.show_wire = True

        print("SBC 碰撞文件导入完成: {}".format(filepath))

def import_adr_file(filepath):

    """

    导入 .adr 门数据文件到 Blender

    对应原始脚本 ImportadrButton (lines 501-647)

    参数:

        filepath: .adr 文件路径

    """

    fname = os.path.splitext(os.path.basename(filepath))[0]

    with open(filepath, "rb") as f:

        f.seek(536, 0)  # start of header

        f.seek(4, 1)  # seek_cur

        blocksize = read_long(f)

        f.seek(4, 1)  # seek_cur

        mAutodelete = read_byte(f)

        vtcount = read_long(f)

        for i in range(vtcount):  # 132 byte data per entry

            ida = read_short(f)

            idb = read_short(f)

            idc = read_short(f)

            idd = read_short(f)

            f.seek(4, 1)  # seek_cur

            ide = read_short(f)

            idf = read_short(f)

            idg = read_short(f)

            idh = read_short(f)

            f.seek(4, 1)  # seek_cur

            bdata = read_byte(f)

            f.seek(4, 1)  # seek_cur

            bdatb = read_byte(f)

            f.seek(4, 1)  # seek_cur

            bdatc = read_byte(f)

            f.seek(4, 1)  # seek_cur

            bdatd = read_byte(f)

            # Read mAreahitData (4 points)

            pointcount = read_long(f)  # always 4

            pxa = read_float(f)

            pza = read_float(f)

            pxb = read_float(f)

            pzb = read_float(f)

            pxc = read_float(f)

            pzc = read_float(f)

            pxd = read_float(f)

            pzd = read_float(f)

            # read mPos

            f.seek(4, 1)  # seek_cur

            x = read_float(f)

            y = read_float(f)

            z = read_float(f)

            w = read_float(f)

            # 构建碰撞平面顶点 (坐标转换: [x, -z, y])

            vertArray = [

                Vector((pxa, -pza, y)),

                Vector((pxb, -pzb, y)),

                Vector((pxc, -pzc, y)),

                Vector((pxd, -pzd, y)),

            ]

            faceArray = [(1, 2, 3), (1, 3, 4)]

            # read mStage

            f.seek(4, 1)

            mstage = read_byte(f)

            # read mRoom

            f.seek(4, 1)

            mroom = read_byte(f)

            # read mCut (door animation)

            f.seek(4, 1)

            mCut = read_byte(f)

            # read mKey (door key needed)

            f.seek(4, 1)

            mKey = read_byte(f)

            # read mPage

            f.seek(4, 1)

            mPage = read_long(f)

            # read mYAngle

            f.seek(4, 1)

            ry = read_float(f)

            # 计算宽度和深�?

            ppd = (pzb - pza)

            ppw = (pxd - pxa)

            # 计算中心

            ppcx = (pxa + pxd) / 2

            ppcz = (pza + pzb) / 2

            # 创建门碰撞盒 (Box)
            # 注意: bpy.ops.mesh.primitive_box_add 在任何 Blender 版本里都不存在
            # (正确的是 primitive_cube_add), 旧代码在这里会直接抛异常.
            bpy.ops.mesh.primitive_cube_add(size=1, location=(x, -z, y))

            box_obj = bpy.context.active_object

            box_obj.scale = (10, 10, 100)

            box_obj.name = "DoorWrapPOS_{}".format(i + 1)

            # 应用旋转 (Y 轴)

            q1 = Quaternion((0, 0, ry, 0))

            box_obj.rotation_euler = q1.to_euler()

            # 设置线框颜色 (蓝色) —— 跨版本安全写法

            from . import compat

            mat, _bsdf = compat.make_simple_material(

                "DoorWrapPOS_{}_mat".format(i + 1), (0.0, i * 0.1, 1.0, 1.0))

            if box_obj.data.materials:

                box_obj.data.materials[0] = mat

            else:

                box_obj.data.materials.append(mat)

            # 创建门区域网�?(DoorWrapZONE)

            mesh_data = bpy.data.meshes.new(name="DoorWrapZONE_{}".format(i + 1))

            mesh_obj = bpy.data.objects.new(name="DoorWrapZONE_{}".format(i + 1), object_data=mesh_data)

            bpy.context.collection.objects.link(mesh_obj)

            mesh_data.from_pydata(vertArray, [], faceArray)

            mesh_data.update()

            # 设置材质 (红色) —— 跨版本安全写法

            mat2, _bsdf2 = compat.make_simple_material(

                "DoorWrapZONE_{}_mat".format(i + 1), (1.0, 0.0, i * 0.1, 1.0))

            if mesh_obj.data.materials:

                mesh_obj.data.materials[0] = mat2

            else:

                mesh_obj.data.materials.append(mat2)

            mesh_obj.show_wire = True

            # 打印元数�?

            print("Door {}: Stage={}, Room={}, Cut={}, Key={}, Page={}".format(

                i + 1, mstage, mroom, mCut, mKey, mPage))

        print("ADR 门数据文件导入完�? {}".format(filepath))

def import_ems_file(filepath):

    """

    导入 .ems 敌人出生数据文件�?Blender

    对应原始脚本 ImportemsButton (lines 649-786)

    参数:

        filepath: .ems 文件路径

    """

    fname = os.path.splitext(os.path.basename(filepath))[0]

    with open(filepath, "rb") as f:

        f.seek(949, 0)  # start of ems header

        # "SME" magic

        magic = read_fixed_string(f, 3)

        if magic != "SME":

            print("错误: 不是有效�?EMS 文件")

            return

        f.seek(18, 1)  # seek_cur

        vtcount = read_short(f)

        # skip xfs header

        f.seek(2104, 0)  # seek_set

        # objArrayB Part

        ncount = read_long(f)  # must be same as vtcount

        objArrayB_entries = []

        for i in range(vtcount):

            entry = EMSEntryB()

            entry.offset = f.tell()

            entry.IDA = read_short(f)  # 8

            entry.IDB = read_short(f)

            entry.IDC = read_short(f)

            entry.IDD = read_short(f)

            # read position

            entry.onea = read_long(f)  # 16

            entry.px = read_float(f)

            entry.py = read_float(f)

            entry.pz = read_float(f)

            entry.pw = read_float(f)

            # read rotation

            entry.oneb = read_long(f)  # 16

            entry.rx = read_float(f)

            entry.ry = read_float(f)

            entry.rz = read_float(f)

            entry.rw = read_float(f)

            # 四元数坐标转�? (rx, -rz, ry, rw)

            q1 = Quaternion((entry.rw, entry.rx, -entry.rz, entry.ry))

            entry.onec = read_long(f)  # 5

            entry.bdta = read_byte(f)

            entry.oned = read_long(f)  # 5

            entry.bdtb = read_byte(f)

            entry.onee = read_long(f)  # 5

            entry.bdtc = read_byte(f)

            entry.onef = read_long(f)  # 5

            entry.bidtag = read_byte(f)  # id tag: 03=jill, 0c=zombie

            entry.oneg = read_long(f)  # 8

            entry.IDE = read_short(f)

            entry.IDF = read_short(f)

            entry.oneh = read_long(f)  # 6

            entry.IDG = read_short(f)

            entry.onei = read_long(f)  # 6

            entry.IDH = read_short(f)

            entry.onej = read_long(f)  # 5

            entry.bingame = read_byte(f)  # cutscene flag=02, ingame=00

            objArrayB_entries.append(entry)

            # 创建金字塔对象表示敌人出生点

            bpy.ops.mesh.primitive_cone_add(

                vertices=4,

                radius1=10,

                radius2=0,

                depth=100,

                location=(entry.px, -entry.pz, entry.py)

            )

            pyramid_obj = bpy.context.active_object

            pyramid_obj.name = "EnemySpawn_{}".format(i + 1)

            # 应用旋转

            pyramid_obj.rotation_euler = q1.to_euler()

            # 设置材质 (绿色) —— 跨版本安全写法

            mat, _bsdf = compat.make_simple_material(

                "EnemySpawn_{}_mat".format(i + 1), (0.0, 1.0, (i + 1) * 0.1, 1.0))

            if pyramid_obj.data.materials:

                pyramid_obj.data.materials[0] = mat

            else:

                pyramid_obj.data.materials.append(mat)

            # 打印条目信息

            print("EnemySpawn {}: IDA={}, IDB={}, IDC={}, IDD={}, "

                  "Pos=({:.2f}, {:.2f}, {:.2f}), "

                  "Rot=({:.2f}, {:.2f}, {:.2f}, {:.2f}), "

                  "BoneIDTag={}, InGame={}".format(

                i + 1, entry.IDA, entry.IDB, entry.IDC, entry.IDD,

                entry.px, entry.py, entry.pz,

                entry.rx, entry.ry, entry.rz, entry.rw,

                entry.bidtag, entry.bingame))

        print("EMS 敌人出生数据文件导入完成: {}".format(filepath))

