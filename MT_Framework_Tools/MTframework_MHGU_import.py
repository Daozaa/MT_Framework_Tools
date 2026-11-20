import bpy

import os

import math

from mathutils import Vector, Quaternion

from .MTframework_MHGU import *

from . import compat

_last_import_path = None

def _decode_normal4(b):
    def s(v):
        return v - 256 if v > 127 else v
    x = s(b[0]) / 127.0
    z = s(b[1]) / 127.0
    y = -s(b[2]) / 127.0
    return Vector((x, y, z))

def _looks_like_normals(raw_list):
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

def _store_influences(bone_id_array, bone_weight_array, index, pairs, max_slots=4):
    acc = {}
    for bid, w in pairs:
        try:
            bw = float(w)
        except (TypeError, ValueError):
            continue
        if bid is None or int(bid) <= 0 or bw <= 0.0:
            continue
        key = int(bid)
        acc[key] = acc.get(key, 0.0) + bw
    if not acc:
        bone_id_array[index] = []
        bone_weight_array[index] = []
        return
    items = sorted(acc.items(), key=lambda kv: (-kv[1], kv[0]))[:max_slots]
    total = sum(w for _, w in items)
    if total <= 0.0:
        bone_id_array[index] = []
        bone_weight_array[index] = []
        return
    bone_id_array[index] = [bid for bid, _ in items]
    bone_weight_array[index] = [w / total for _, w in items]

def import_mod_file(filepath, game_fix="mhgu", sidecar_source=None):

    global mod_ver, hidedege, hidelod0, _last_import_path

    _last_import_path = filepath

    _pre_import_names = set(o.name for o in bpy.data.objects)

    try:

        bpy.context.scene['MT_LastImportPath'] = filepath

        try:
            from .MTframework_MHGU_tpl import store as _tpl_store, materialize as _tpl_mat
            _tpl_hash = _tpl_store(bpy.context, filepath)

            if _tpl_hash:
                _tpl_path = _tpl_mat(bpy.context)
                if _tpl_path:
                    _last_import_path = _tpl_path
                    bpy.context.scene['MT_LastImportPath'] = _tpl_path
        except Exception:
            pass

    except Exception:

        pass

    is_mhgu = (game_fix == "mhgu")

    is_dmc4se = (game_fix == "dmc4se")

    is_lp2 = (game_fix == "lp2")

    is_dd = (game_fix == "dd")

    is_re0 = (game_fix == "re0")

    is_re2 = (game_fix == "re2")

    if bpy.context.mode != 'OBJECT':

        try:

            bpy.ops.object.mode_set(mode='OBJECT')

        except Exception:

            pass

    f = open(filepath, 'rb')

    if f is None:

        return {'CANCELLED'}

    magic = read_fixed_string(f, 4)

    if magic != "MOD":

        f.close()

        raise ValueError("不是有效�?MOD 文件")

    mod_ver = read_short(f)

    hdr = read_header(f)

    bCount = hdr.BoneCount

    MeshScale = [1.0, 1.0, 1.0]

    BoundingSphere = get_bound(f)

    BoundingBoxMin = get_bound(f)

    BoundingBoxMax = get_bound(f)

    bound_sphere = bpy.data.objects.new("BoundSphere", None)

    bound_sphere.empty_display_type = 'SPHERE'

    bound_sphere.location = (BoundingSphere[0], BoundingSphere[1], BoundingSphere[2])

    bound_sphere.empty_display_size = BoundingSphere[3]

    bpy.context.collection.objects.link(bound_sphere)

    bound_sphere.hide_set(True)

    bound_box_min = bpy.data.objects.new("BoundBoxMin", None)

    bound_box_min.empty_display_type = 'SPHERE'

    bound_box_min.location = (BoundingBoxMin[0], BoundingBoxMin[1], BoundingBoxMin[2])

    bound_box_min.empty_display_size = 10.0

    bpy.context.collection.objects.link(bound_box_min)

    bound_box_min.hide_set(True)

    bound_box_max = bpy.data.objects.new("BoundBoxMax", None)

    bound_box_max.empty_display_type = 'SPHERE'

    bound_box_max.location = (BoundingBoxMax[0], BoundingBoxMax[1], BoundingBoxMax[2])

    bound_box_max.empty_display_size = 10.0

    bpy.context.collection.objects.link(bound_box_max)

    bound_box_max.hide_set(True)

    lodzero = read_long(f)

    lodone = read_long(f)

    LDC = read_long(f)

    pad = read_long(f)

    entrycount = read_long(f)

    f.seek(hdr.ptr_Bone, os.SEEK_SET)

    BoneArray = []
    BoneLocalMatrices = []
    BoneWorldMatrices = []
    Mtp = []
    Armature = None

    if bCount != 0:

        for i in range(bCount):
            BoneArray.append(read_bone_info(f))

        for i in range(bCount):
            BoneLocalMatrices.append(read_matrix(f))

        for i in range(bCount):
            BoneWorldMatrices.append(read_matrix(f))

        Mtp = [read_byte(f) + 1 for _ in range(256)]

        _dequant = get_dequant_scale(BoneWorldMatrices, bCount)

    else:
        Mtp = [1] * 256

    MeshScale = compute_mesh_scale(BoneWorldMatrices, bCount)
    if bCount != 0:
        print("文件反量化系数 = {:.5f}; 网格对象缩放 = {}".format(_dequant, MeshScale))

    if bCount == 0:

        MeshScale = [1.0, 1.0, 1.0]

    _bone_maps = []

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

        if is_lp2:

            MeshInfo_array[i][8] = MeshInfo_array[i][8] + 7

        if is_dmc4se:

            MeshInfo_array[i][8] = MeshInfo_array[i][8] - 1

        fvf = MeshInfo_array[i][8]

        if fvf == 0x9399C037:

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = read_uv_half(f)

                f.seek(4, os.SEEK_CUR)

        elif fvf == 0xAFA63031:

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = read_uv_half(f)

        elif fvf == 0xC66FA03E:

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                f.seek(4, os.SEEK_CUR)

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = read_uv_half(f)

        elif fvf == 0xB3921020:

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                w1 = read_short_signed(f) / 32767.0

                w2 = 1.0 - w1

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)

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

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                w1 = read_short_signed(f) / 32767.0

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)

                b1 = read_byte(f) + 1

                b2 = read_byte(f) + 1

                b3 = read_byte(f) + 1

                b4 = read_byte(f) + 1

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

                w2 = read_float16(f)

                w3 = read_float16(f)

                w4 = 1.0 - (w1 + w2 + w3)

                f.seek(4, os.SEEK_CUR)

                UV_arrayb[c] = read_uv_half(f)

                f.seek(4, os.SEEK_CUR)

                wt = w1 + w2 + w3 + w4

                if wt > 0:

                    w1 /= wt

                    w2 /= wt

                    w3 /= wt

                    w4 /= wt

                _store_influences(
                    BoneID_array, BoneWeight_array, c,
                    [(b1, w1), (b2, w2), (b3, w3), (b4, w4)])

            MeshBoneLimit[i] = 4

        elif fvf == 0xB0983013 or fvf == 0xB0983014:

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

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                f.seek(6, os.SEEK_CUR)

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

        elif fvf == 0x0CB6800E:

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                f.seek(2, os.SEEK_CUR)

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

        elif fvf == 0x0CB68015 or fvf == 0x0CB68016:

            _nraw = []

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                b1 = read_byte(f) + 1

                w1 = read_byte(f) / 255.0

                BoneID_array[c] = [b1]

                BoneWeight_array[c] = [1.0]

                _nraw.append(f.read(4))

                f.seek(4, os.SEEK_CUR)

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

            if _looks_like_normals(_nraw):

                for c in range(vc):

                    Normal_array[c] = _decode_normal4(_nraw[c])

            MeshBoneLimit[i] = 1

        elif fvf == 0xA8FAB018 or fvf == 0xA8FAB019:

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                b1 = read_byte(f) + 1

                w1 = read_byte(f) / 255.0

                BoneID_array[c] = [b1]

                BoneWeight_array[c] = [1.0]

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

            MeshBoneLimit[i] = 1

        elif fvf == 0xA7D7D036:

            for c in range(vc):

                VertexPos_array[c] = read_vec3_pos(f)

                Normal_array[c] = read_normal(f)

                w6 = read_short(f) / 65535.0

                w7 = read_short(f) / 65535.0

                UV_array[c] = [w6, w7, 0]

                UV_arrayb[c] = [0, 0, 0]

            MeshBoneLimit[i] = 0

        elif fvf == 0xC31F201C or fvf == 0xC31F201D:

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                w1 = read_short_signed(f) / 32767.0

                w2 = 1.0 - w1

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)

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

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                w1 = read_byte(f) / 255.0

                b1 = read_byte(f) + 1

                BoneID_array[c] = [b1]

                BoneWeight_array[c] = [1.0]

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

                f.seek(4, os.SEEK_CUR)

            MeshBoneLimit[i] = 1

        elif fvf == 0x207D6037:

            for c in range(vc):

                VertexPos_array[c] = read_vec3_pos(f)

                Normal_array[c] = read_normal(f)

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

                f.seek(4, os.SEEK_CUR)

            MeshBoneLimit[i] = 0

        elif fvf == 0xD1A47038:

            for c in range(vc):

                VertexPos_array[c] = read_vec3_pos(f)

                Normal_array[c] = read_normal(f)

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = read_uv_half(f)

            MeshBoneLimit[i] = 0

        elif fvf == 0xD8297028:

            for c in range(vc):

                VertexPos_array[c] = read_vec3_pos(f)

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

            MeshBoneLimit[i] = 0

        elif fvf == 0xC66FA03A:

            for c in range(vc):

                VertexPos_array[c] = read_vec3_pos(f)

                Normal_array[c] = read_normal(f)

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

                UV_arrayb[c] = read_uv_half(f)

            MeshBoneLimit[i] = 0

        elif fvf == 0x667B1019:

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                f.seek(10, os.SEEK_CUR)

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

                UV_arrayb[c] = read_uv_half(f)

            MeshBoneLimit[i] = 1

        elif fvf in (0x14D40019, 0x14D40020, 0x14D40021, 0x14D40022):

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                w1 = read_short_signed(f) / 32767.0

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)

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

                _store_influences(
                    BoneID_array, BoneWeight_array, c,
                    [(b1, w1), (b2, w2), (b3, w3), (b4, w4)])

            MeshBoneLimit[i] = 4

        elif fvf == 0x5E7F202C:

            for c in range(vc):

                VertexPos_array[c] = read_vec3_pos(f)

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = read_uv_half(f)

            MeshBoneLimit[i] = 0

        elif fvf in (0x2BE814D4, 0x7CD414D4):

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                f.seek(22, os.SEEK_CUR)

                UV_array[c] = [0, 0, 0]

                UV_arrayb[c] = [0, 0, 0]

        elif fvf in (0xA320C016, 0xA320C017):

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                f.seek(2, os.SEEK_CUR)

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)

                f.seek(4, os.SEEK_CUR)

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = read_uv_half(f)

        elif fvf == 0x49B4F029:

            for c in range(vc):

                VertexPos_array[c] = read_vec3_pos(f)

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = read_uv_half(f)

        elif fvf == 0x0D9E801D:

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                f.seek(22, os.SEEK_CUR)

                UV_array[c] = [0, 0, 0]

                UV_arrayb[c] = [0, 0, 0]

            MeshBoneLimit[i] = 2

        elif fvf == 0xA013501E:

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                w1 = read_short_signed(f) / 32767.0

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

                v = read_float16(f); b1 = int(v) + 1 if not math.isnan(v) else 0

                v = read_float16(f); b2 = int(v) + 1 if not math.isnan(v) else 0

                w2 = 1.0 - w1

                f.seek(4, os.SEEK_CUR)

                BoneID_array[c] = [b1, b2]

                BoneWeight_array[c] = [w1, w2]

            MeshBoneLimit[i] = 2

        elif fvf == 0xD877801B:

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                b1 = read_byte(f) + 1

                read_byte(f)

                BoneID_array[c] = [b1]

                BoneWeight_array[c] = [1.0]

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)

                UV_array[c] = read_uv_half(f)

                f.seek(4, os.SEEK_CUR)

                UV_arrayb[c] = read_uv_half(f)

                f.seek(4, os.SEEK_CUR)

            MeshBoneLimit[i] = 1

        elif fvf in (0x747D1031, 0x9399C033, 0xB86DE02A, 0x12553032, 0x926FD02E):

            for c in range(vc):

                VertexPos_array[c] = read_vec3_pos(f)

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = read_uv_half(f)

                f.seek(4, os.SEEK_CUR)

        elif fvf == 0xA14E003C:

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                f.seek(26, os.SEEK_CUR)

                UV_array[c] = [0, 0, 0]

                UV_arrayb[c] = [0, 0, 0]

        elif fvf == 0xDA55A021:

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                f.seek(2, os.SEEK_CUR)

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)

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

                UV_arrayb[c] = read_uv_half(f)

                BoneID_array[c] = [b1, b2, b3, b4]

                BoneWeight_array[c] = [w1, w2, w3, w4]

            MeshBoneLimit[i] = 4

        elif fvf == 0xB392101F:

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                f.seek(2, os.SEEK_CUR)

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

                UV_arrayb[c] = read_uv_half(f)

                f.seek(4, os.SEEK_CUR)

                f.seek(4, os.SEEK_CUR)

                f.seek(4, os.SEEK_CUR)

        elif fvf == 0xBB424024 or fvf == 0xBB424025:

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

                f.seek(4, os.SEEK_CUR)

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

                _store_influences(
                    BoneID_array, BoneWeight_array, c,
                    [(top4_b[j], top4_w[j]) for j in range(4)])

            MeshBoneLimit[i] = 4

        elif fvf == 0x63B6C02F:

            for c in range(vc):

                VertexPos_array[c] = read_vec3_pos(f)

                UV_arrayb[c] = [0, 0, 0]

                UV_arrayb[c] = read_uv_half(f)

                Normal_array[c] = read_normal(f)

                UV_array[c] = read_uv_half(f)

                f.seek(4, os.SEEK_CUR)

                f.seek(4, os.SEEK_CUR)

                f.seek(4, os.SEEK_CUR)

        elif fvf == 0x64593023:

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                w1 = read_short_signed(f) / 32767.0

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)

                b1 = read_byte(f) + 1

                b2 = read_byte(f) + 1

                b3 = read_byte(f) + 1

                b4 = read_byte(f) + 1

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

                w2 = read_float16(f)

                w3 = read_float16(f)

                w4 = 1.0 - (w1 + w2 + w3)

                f.seek(4, os.SEEK_CUR)

                UV_arrayb[c] = [0, 0, 0]

                UV_arrayb[c] = read_uv_half(f)

                f.seek(4, os.SEEK_CUR)

                wt = w1 + w2 + w3 + w4

                if wt > 0:

                    w1 /= wt

                    w2 /= wt

                    w3 /= wt

                    w4 /= wt

                _store_influences(
                    BoneID_array, BoneWeight_array, c,
                    [(b1, w1), (b2, w2), (b3, w3), (b4, w4)])

            MeshBoneLimit[i] = 4

        elif fvf == 0x75C3E025:

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                f.seek(14, os.SEEK_CUR)

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

                f.seek(16, os.SEEK_CUR)

        elif fvf == 0xD84E3026:

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                f.seek(14, os.SEEK_CUR)

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

                f.seek(16, os.SEEK_CUR)

        elif fvf == 0xCBCF7027:

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

                _store_influences(
                    BoneID_array, BoneWeight_array, c,
                    [(top4_b[j], top4_w[j]) for j in range(4)])

                f.seek(4, os.SEEK_CUR)

                f.seek(4, os.SEEK_CUR)

                UV_arrayb[c] = read_uv_half(f)

                f.seek(4, os.SEEK_CUR)

            MeshBoneLimit[i] = 4

        elif fvf == 0x2F55C03D:

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                w1 = read_short_signed(f) / 32767.0

                Normal_array[c] = read_normal(f)

                f.seek(4, os.SEEK_CUR)

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

                f.seek(4, os.SEEK_CUR)

                f.seek(4, os.SEEK_CUR)

                f.seek(4, os.SEEK_CUR)

                f.seek(4, os.SEEK_CUR)

                f.seek(4, os.SEEK_CUR)

                f.seek(4, os.SEEK_CUR)

                f.seek(4, os.SEEK_CUR)

                f.seek(4, os.SEEK_CUR)

                _store_influences(
                    BoneID_array, BoneWeight_array, c,
                    [(b1, w1), (b2, w2), (b3, w3), (b4, w4)])

            MeshBoneLimit[i] = 4

        else:

            print("未知 FVF = {} 在偏�? {}".format(hex(fvf), f.tell()))

            stride = MeshInfo_array[i][1]

            for c in range(vc):

                VertexPos_array[c] = read_vertex_pos(f)

                f.seek(6, os.SEEK_CUR)

                f.seek(stride - 20, os.SEEK_CUR)

                UV_array[c] = read_uv_half(f)

                UV_arrayb[c] = [0, 0, 0]

                f.seek(4, os.SEEK_CUR)

        MeshVertex_array[i] = VertexPos_array

        MeshUV_array[i] = UV_array

        MeshUV_arrayb[i] = UV_arrayb

        MeshNormal_array[i] = Normal_array

        MeshBoneID_array[i] = BoneID_array

        MeshBoneWeight_array[i] = BoneWeight_array

    if bCount != 0 and BoneWorldMatrices:
        try:
            Armature = build_armature(
                "MT_Armature", BoneArray, BoneWorldMatrices, Mtp, _dequant)
            print("骨架已创建: {} 根骨骼 (反量化系数 {:.5f})".format(bCount, _dequant))

            if sidecar_source:
                try:
                    from . import MTframework_MHGU_bontails as _bontails
                    _bontails.apply(Armature, sidecar_source)
                except Exception as _e_tail:
                    print("骨骼尾端 sidecar 应用失败: {}".format(_e_tail))
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

    f.seek(hdr.ptr_triangle, os.SEEK_SET)

    MeshFace_array = [None] * mc

    vc_limits = [MeshInfo_array[i][0] for i in range(mc)]

    for i in range(mc):

        fc = MeshInfo_array[i][5]

        vstart = MeshInfo_array[i][2]

        vlimit = vc_limits[i]

        f.seek(hdr.ptr_triangle + MeshInfo_array[i][4] * 2, os.SEEK_SET)

        raw = [read_short(f) for _ in range(fc)]

        def _loc_tri(a, b, c):
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

                    t = _loc_tri(f1, f2, f3) if reverse else _loc_tri(f1, f3, f2)

                    if t:

                        Face_array.append(t)

                    f1, f2 = f2, f3

        else:

            for k in range(0, fc - 2, 3):

                t = _loc_tri(raw[k], raw[k + 1], raw[k + 2])

                if t:

                    Face_array.append(t)

        MeshFace_array[i] = Face_array

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

    for i in range(mc):

        verts = MeshVertex_array[i]

        faces = MeshFace_array[i]

        if verts is None or faces is None or len(verts) == 0 or len(faces) == 0:

            continue

        mesh_data = bpy.data.meshes.new("temp_mesh")

        mesh_data.from_pydata(verts, [], faces)

        mesh_data.validate(verbose=False)

        mesh_data.update()

        nd = MeshNormal_array[i] if i < len(MeshNormal_array) else None

        _fill = (sum(1 for v in nd if v is not None) / len(nd)) if nd else 0.0

        if nd and _fill >= 0.9:

            try:

                mesh_data.use_auto_smooth = True

                mesh_data.normals_split_custom_set_from_vertices(

                    [tuple(v) if v is not None else (0.0, 0.0, 1.0) for v in nd]

                )

            except Exception as e:

                print("  [MT] 写入自定义法向失败: %s" % e)

        mesh_obj = bpy.data.objects.new("Mesh", mesh_data)

        bpy.context.collection.objects.link(mesh_obj)

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

        uv_data = MeshUV_array[i]

        if uv_data and len(uv_data) > 0 and any(u is not None for u in uv_data):

            uv_layer = mesh_data.uv_layers.new(name="UVMap")

            if uv_layer:

                for loop_idx, loop_vert in enumerate(mesh_data.loops):

                    vi = loop_vert.vertex_index

                    if vi < len(uv_data) and uv_data[vi] is not None:

                        uv_layer.data[loop_idx].uv = (uv_data[vi][0], uv_data[vi][1])

        uv2_data = MeshUV_arrayb[i]

        if uv2_data and len(uv2_data) > 0 and any(u is not None and u != [0, 0, 0] for u in uv2_data):

            uv2_layer = mesh_data.uv_layers.new(name="UVMap_Lightmap")

            if uv2_layer:

                for loop_idx, loop_vert in enumerate(mesh_data.loops):

                    vi = loop_vert.vertex_index

                    if vi < len(uv2_data) and uv2_data[vi] is not None:

                        uv2_layer.data[loop_idx].uv = (uv2_data[vi][0], uv2_data[vi][1])

        bone_ids = MeshBoneID_array[i]

        bone_weights = MeshBoneWeight_array[i]

        has_skin = (bone_ids is not None and len(bone_ids) > 0

                    and bone_ids[0] is not None and Armature is not None)

        if has_skin:

            bone_map = None

            bmi = getattr(mhdr, 'bonemapindex', 0)

            if _bone_maps:

                if 0 <= bmi < len(_bone_maps):

                    bone_map = _bone_maps[bmi]

                else:

                    bone_map = _bone_maps[0]

            def _resolve(bid, _bm=bone_map):

                idx = bid - 1

                if idx < 0:

                    return 0

                if _bm and idx < len(_bm):

                    idx = _bm[idx]

                if idx < 0 or idx >= bCount:

                    return 0

                return idx + 1

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

            for c in range(vc):

                if (c < len(bone_ids) and bone_ids[c] is not None

                        and c < len(bone_weights) and bone_weights[c] is not None):

                    acc = {}

                    for j in range(len(bone_ids[c])):

                        r = _resolve(bone_ids[c][j])

                        w = bone_weights[c][j]

                        if r > 0 and w > 0:

                            if w > acc.get(r, 0.0):

                                acc[r] = w

                    total = sum(acc.values())

                    if total > 0:

                        for r, w in acc.items():

                            name = used.get(r) or bone_name_for(r)

                            vg = mesh_obj.vertex_groups.get(name)

                            if vg is None:

                                vg = mesh_obj.vertex_groups.new(name=name)

                            vg.add([c], w / total, 'REPLACE')

            if mesh_obj.vertex_groups:

                mod = mesh_obj.modifiers.new(name="Armature", type='ARMATURE')

                mod.object = Armature

                mod.use_vertex_groups = True

        if has_skin and mesh_obj.vertex_groups:

            mesh_obj.parent = Armature

            mesh_obj.matrix_parent_inverse = Armature.matrix_world.inverted()

        else:

            mesh_obj.parent = other_mesh

    for _o in bpy.context.scene.objects:
        if _o.type == 'MESH':
            try:

                _o.data.update()
                compat.calc_normals_split(_o.data)
                remember_vertex_fingerprint(_o)

                _p = _o.name.split('_')
                if len(_p) > 2 and _p[2].startswith('0x'):
                    try:
                        from .MTframework_FVF import fvf_name as _fvf_name
                        _lbl = _fvf_name(int(_p[2], 16))
                        if _lbl and _lbl not in _o.name:
                            _o.name = _o.name + '_' + _lbl
                    except Exception:
                        pass

                if _o.data is not None and _o.data.name != _o.name:
                    _o.data.name = _o.name
            except Exception as _e:
                print("记录顶点指纹跳过 %s: %s" % (_o.name, _e))

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

    try:
        _mode = bpy.context.scene.MT_Framework_Props.auto_center
    except Exception:
        _mode = 'XY_GROUND'
    if _mode and _mode != 'NONE':
        imported_objs = list(bpy.context.scene.objects)

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

    fname = os.path.splitext(os.path.basename(filepath))[0]

    with open(filepath, "rb") as f:

        magic = read_fixed_string(f, 3)

        version = read_byte(f)

        if magic != "SBC":

            print("错误: 不是有效�?SBC 文件")

            return

        f.seek(16, 1)

        unkcounta = read_long(f)

        ncounta = read_long(f)

        vtcount = read_long(f)

        f.seek(212, 0)

        fcountA = read_long(f)

        f.seek(12, 1)

        faceArray = []

        for i in range(fcountA):

            color_val = read_long(f)

            p1 = read_short(f) + 1

            p2 = read_short(f) + 1

            p3 = read_short(f) + 1

            p4 = read_short(f) + 1

            f.seek(100, 1)

        f.seek(8, 1)

        f.seek(40, 1)

        f.seek(32, 1)

        f.seek(96, 1)

        for i in range(ncounta):

            f.seek(12, 1)

            p1 = read_short(f) + 1

            p2 = read_short(f) + 1

            p3 = read_short(f) + 1

            p4 = read_short(f) + 1

            f.seek(12, 1)

            faceArray.append((p1, p2, p3))

        vertArray = []

        for i in range(vtcount):

            vx = read_float(f)

            vy = read_float(f)

            vz = read_float(f)

            vw = read_float(f)

            vertArray.append(Vector((vx, -vz, vy)))

        mesh_data = bpy.data.meshes.new(name=fname)

        mesh_obj = bpy.data.objects.new(name=fname, object_data=mesh_data)

        bpy.context.collection.objects.link(mesh_obj)

        mesh_data.from_pydata(vertArray, [], faceArray)

        mesh_data.update()

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

    fname = os.path.splitext(os.path.basename(filepath))[0]

    with open(filepath, "rb") as f:

        f.seek(536, 0)

        f.seek(4, 1)

        blocksize = read_long(f)

        f.seek(4, 1)

        mAutodelete = read_byte(f)

        vtcount = read_long(f)

        for i in range(vtcount):

            ida = read_short(f)

            idb = read_short(f)

            idc = read_short(f)

            idd = read_short(f)

            f.seek(4, 1)

            ide = read_short(f)

            idf = read_short(f)

            idg = read_short(f)

            idh = read_short(f)

            f.seek(4, 1)

            bdata = read_byte(f)

            f.seek(4, 1)

            bdatb = read_byte(f)

            f.seek(4, 1)

            bdatc = read_byte(f)

            f.seek(4, 1)

            bdatd = read_byte(f)

            pointcount = read_long(f)

            pxa = read_float(f)

            pza = read_float(f)

            pxb = read_float(f)

            pzb = read_float(f)

            pxc = read_float(f)

            pzc = read_float(f)

            pxd = read_float(f)

            pzd = read_float(f)

            f.seek(4, 1)

            x = read_float(f)

            y = read_float(f)

            z = read_float(f)

            w = read_float(f)

            vertArray = [

                Vector((pxa, -pza, y)),

                Vector((pxb, -pzb, y)),

                Vector((pxc, -pzc, y)),

                Vector((pxd, -pzd, y)),

            ]

            faceArray = [(1, 2, 3), (1, 3, 4)]

            f.seek(4, 1)

            mstage = read_byte(f)

            f.seek(4, 1)

            mroom = read_byte(f)

            f.seek(4, 1)

            mCut = read_byte(f)

            f.seek(4, 1)

            mKey = read_byte(f)

            f.seek(4, 1)

            mPage = read_long(f)

            f.seek(4, 1)

            ry = read_float(f)

            ppd = (pzb - pza)

            ppw = (pxd - pxa)

            ppcx = (pxa + pxd) / 2

            ppcz = (pza + pzb) / 2

            bpy.ops.mesh.primitive_cube_add(size=1, location=(x, -z, y))

            box_obj = bpy.context.active_object

            box_obj.scale = (10, 10, 100)

            box_obj.name = "DoorWrapPOS_{}".format(i + 1)

            q1 = Quaternion((0, 0, ry, 0))

            box_obj.rotation_euler = q1.to_euler()

            from . import compat

            mat, _bsdf = compat.make_simple_material(

                "DoorWrapPOS_{}_mat".format(i + 1), (0.0, i * 0.1, 1.0, 1.0))

            if box_obj.data.materials:

                box_obj.data.materials[0] = mat

            else:

                box_obj.data.materials.append(mat)

            mesh_data = bpy.data.meshes.new(name="DoorWrapZONE_{}".format(i + 1))

            mesh_obj = bpy.data.objects.new(name="DoorWrapZONE_{}".format(i + 1), object_data=mesh_data)

            bpy.context.collection.objects.link(mesh_obj)

            mesh_data.from_pydata(vertArray, [], faceArray)

            mesh_data.update()

            mat2, _bsdf2 = compat.make_simple_material(

                "DoorWrapZONE_{}_mat".format(i + 1), (1.0, 0.0, i * 0.1, 1.0))

            if mesh_obj.data.materials:

                mesh_obj.data.materials[0] = mat2

            else:

                mesh_obj.data.materials.append(mat2)

            mesh_obj.show_wire = True

            print("Door {}: Stage={}, Room={}, Cut={}, Key={}, Page={}".format(

                i + 1, mstage, mroom, mCut, mKey, mPage))

        print("ADR 门数据文件导入完�? {}".format(filepath))

def import_ems_file(filepath):

    fname = os.path.splitext(os.path.basename(filepath))[0]

    with open(filepath, "rb") as f:

        f.seek(949, 0)

        magic = read_fixed_string(f, 3)

        if magic != "SME":

            print("错误: 不是有效�?EMS 文件")

            return

        f.seek(18, 1)

        vtcount = read_short(f)

        f.seek(2104, 0)

        ncount = read_long(f)

        objArrayB_entries = []

        for i in range(vtcount):

            entry = EMSEntryB()

            entry.offset = f.tell()

            entry.IDA = read_short(f)

            entry.IDB = read_short(f)

            entry.IDC = read_short(f)

            entry.IDD = read_short(f)

            entry.onea = read_long(f)

            entry.px = read_float(f)

            entry.py = read_float(f)

            entry.pz = read_float(f)

            entry.pw = read_float(f)

            entry.oneb = read_long(f)

            entry.rx = read_float(f)

            entry.ry = read_float(f)

            entry.rz = read_float(f)

            entry.rw = read_float(f)

            q1 = Quaternion((entry.rw, entry.rx, -entry.rz, entry.ry))

            entry.onec = read_long(f)

            entry.bdta = read_byte(f)

            entry.oned = read_long(f)

            entry.bdtb = read_byte(f)

            entry.onee = read_long(f)

            entry.bdtc = read_byte(f)

            entry.onef = read_long(f)

            entry.bidtag = read_byte(f)

            entry.oneg = read_long(f)

            entry.IDE = read_short(f)

            entry.IDF = read_short(f)

            entry.oneh = read_long(f)

            entry.IDG = read_short(f)

            entry.onei = read_long(f)

            entry.IDH = read_short(f)

            entry.onej = read_long(f)

            entry.bingame = read_byte(f)

            objArrayB_entries.append(entry)

            bpy.ops.mesh.primitive_cone_add(

                vertices=4,

                radius1=10,

                radius2=0,

                depth=100,

                location=(entry.px, -entry.pz, entry.py)

            )

            pyramid_obj = bpy.context.active_object

            pyramid_obj.name = "EnemySpawn_{}".format(i + 1)

            pyramid_obj.rotation_euler = q1.to_euler()

            mat, _bsdf = compat.make_simple_material(

                "EnemySpawn_{}_mat".format(i + 1), (0.0, 1.0, (i + 1) * 0.1, 1.0))

            if pyramid_obj.data.materials:

                pyramid_obj.data.materials[0] = mat

            else:

                pyramid_obj.data.materials.append(mat)

            print("EnemySpawn {}: IDA={}, IDB={}, IDC={}, IDD={}, "

                  "Pos=({:.2f}, {:.2f}, {:.2f}), "

                  "Rot=({:.2f}, {:.2f}, {:.2f}, {:.2f}), "

                  "BoneIDTag={}, InGame={}".format(

                i + 1, entry.IDA, entry.IDB, entry.IDC, entry.IDD,

                entry.px, entry.py, entry.pz,

                entry.rx, entry.ry, entry.rz, entry.rw,

                entry.bidtag, entry.bingame))

        print("EMS 敌人出生数据文件导入完成: {}".format(filepath))
