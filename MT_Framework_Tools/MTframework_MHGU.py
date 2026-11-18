# -*- coding: utf-8 -*-
"""
MT Framework MHGU Model Importer/Exporter for Blender
=====================================================
从 3ds Max 2010 脚本 MTframework_MHGU.ms 转换而来
支持 MT Framework 引擎的 .mod, .sbc, .adr, .ems 文件格式
游戏支持: MHGU(Switch), DMC4SE, Lost Planet 2, Dragon's Dogma,
          Resident Evil 0/1/2/6/7, RE Revelations 1/2

Blender 版本要求: 2.80+
"""

import bpy
import struct
import re
from mathutils import Vector, Matrix, Euler
from bpy.props import (
    StringProperty, BoolProperty, IntProperty, FloatProperty,
    EnumProperty, CollectionProperty
)

# ============================================================
# 全局变量
# ============================================================
mod_ver = 0
hidedege = False
hidelod0 = False

# ============================================================
# 数据结构体 (使用 dataclasses 或简单类)
# ============================================================
class Header:
    """MOD 文件头结构 (52 bytes)"""
    def __init__(self):
        self.BoneCount = 0
        self.MeshCount = 0
        self.MatCount = 0
        self.VertCount = 0
        self.TriangleCount = 0
        self.VertexIds = 0
        self.VertexBufferSize = 0
        self.Padding = 0
        self.BoneMapCount = 0
        self.ptr_Bone = 0
        self.ptr_BoneMap = 0
        self.ptr_MatID = 0
        self.ptr_Mesh = 0
        self.ptr_vertex = 0
        self.ptr_triangle = 0
        self.EndSize = 0

class BoneInfo:
    """骨骼信息结构 (16 bytes)"""
    def __init__(self):
        self.ID = 0
        self.Parent = 0
        self.Child = 0
        self.uk1 = 0
        self.Trans = [0.0, 0.0, 0.0]
        self.uk2 = 0.0
        self.uk3 = 0.0

class MeshHeader:
    """网格头结构 (48 bytes)"""
    def __init__(self):
        self.meshtype = 0
        self.vertCount = 0
        self.unk01 = 0
        self.MatId = 0
        self.lodLevel = 0
        self.unk04 = 0
        self.vertFlag = 0
        self.vertStride = 0
        self.unk05 = 0
        self.vertStart = 0
        self.vertBase = 0
        self.fvfInfo = 0
        self.faceStart = 0
        self.faceCount = 0
        self.faceBase = 0
        self.bonemapindex = 0
        self.weightmaps = 0
        self.unk07 = 0
        self.unk08 = 0
        self.min_index = 0
        self.max_index = 0
        self.unk09 = 0

class EMSEntryB:
    """EMS 条目 B 部分"""
    def __init__(self):
        self.name = ""
        self.offset = 0
        self.IDA = 0
        self.IDB = 0
        self.IDC = 0
        self.IDD = 0
        self.onea = 0
        self.px = 0.0
        self.py = 0.0
        self.pz = 0.0
        self.pw = 0.0
        self.oneb = 0
        self.rx = 0.0
        self.ry = 0.0
        self.rz = 0.0
        self.rw = 0.0
        self.onec = 0
        self.bdta = 0
        self.oned = 0
        self.bdtb = 0
        self.onee = 0
        self.bdtc = 0
        self.onef = 0
        self.bidtag = 0
        self.oneg = 0
        self.IDE = 0
        self.IDF = 0
        self.oneh = 0
        self.IDG = 0
        self.onei = 0
        self.IDH = 0
        self.onej = 0
        self.bingame = 0

# ============================================================
# 二进制读取工具函数
# ============================================================

def read_byte(f):
    """读取 1 字节 (unsigned)"""
    data = f.read(1)
    if not data:
        return 0
    return struct.unpack('<B', data)[0]

def read_short(f):
    """读取 2 字节 (unsigned short, little-endian)"""
    data = f.read(2)
    if not data or len(data) < 2:
        return 0
    return struct.unpack('<H', data)[0]

def read_short_signed(f):
    """读取 2 字节 (signed short, little-endian)"""
    data = f.read(2)
    if not data or len(data) < 2:
        return 0
    return struct.unpack('<h', data)[0]

def read_long(f):
    """读取 4 字节 (unsigned int, little-endian)"""
    data = f.read(4)
    if not data or len(data) < 4:
        return 0
    return struct.unpack('<I', data)[0]

def read_float(f):
    """读取 4 字节 (float, little-endian)"""
    data = f.read(4)
    if not data or len(data) < 4:
        return 0.0
    return struct.unpack('<f', data)[0]

# ============================================================
# 大端读取/写入函数
# ============================================================

# ============================================================
# 半精度浮点数 (float16) 转换
# ============================================================

def read_float16(f):
    """读取 2 字节半精度浮点数 (IEEE 754 half) 并转换为 float32.

    注意: 这里使用**标准** half 公式 ``(1 + frac/1024) * 2^(e-15)``.

    旧版本在末尾额外乘了 2.0 —— 那是从 3ds Max 脚本照搬过来的历史遗留:
    脚本里指数用的是 ``e - 16`` (比标准少 2 倍), 再乘 2.0 刚好抵消.
    移植到 Python 时指数已经改成标准的 ``e - 15``, 却把 ``* 2.0`` 一起带了过来,
    等于**放大了 2 倍**. 实测后果:
      * UV 变成 ``[0, 2]`` 区间 —— 这就是"UV 默认异常大"的原因;
      * 蒙皮权重 w2/w3 被放大, ``w4 = 1 - w1 - w2 - w3`` 变成负数
        (f_body001: 1847 个顶点里有 511 个权重溢出).
    去掉这个 2.0 后, UV 全部落回 ``[0, 1]``, 权重也全部合法.
    """
    hf = read_short(f)
    sign = (hf >> 15) & 1
    exponent = ((hf >> 10) & 0x1F) - 15
    fraction = hf & 0x03FF

    if exponent == -15:
        # 非规格化数 (原始指数为 0)
        if fraction == 0:
            return 0.0
        output = fraction / 1024.0 * (2 ** (-14))
    elif exponent == 16:
        return 0.0  # Inf / NaN → 0
    else:
        output = (1.0 + fraction / 1024.0) * (2 ** exponent)

    if sign:
        output = -output
    return output

def float_to_short(fValue):
    """将 float32 转换为半精度浮点数 (uint16)"""
    import struct as _struct

    # 将 float 打包为 uint32
    Src = _struct.unpack('<I', _struct.pack('<f', fValue))[0]

    Sign = (Src >> 31) & 1
    exponent = ((Src >> 23) & 0xFF) - 127 + 15
    Mantissa = Src & 0x007FFFFF

    if 0 <= exponent <= 30:
        Result = (Sign << 15) | (exponent << 10) | ((Mantissa + 0x00001000) >> 13)
    else:
        if Src == 0:
            Result = 0
        else:
            if exponent <= 0:
                if exponent <= -10:
                    Result = 0
                else:
                    Mantissa = (Mantissa | 0x00800000) >> (1 - exponent)
                    if (Mantissa & 0x00001000):
                        Mantissa = Mantissa + 0x00002000
                        Result = (Sign << 15) | (Mantissa >> 13)
                    else:
                        Result = 0
            else:
                if exponent == 255 - 127 + 15:
                    if Mantissa == 0:
                        Result = (Sign << 15) | 0x7C00
                    else:
                        Result = (Sign << 15) | 0x7C00 | (Mantissa >> 13)
                else:
                    if (Mantissa & 0x00001000):
                        Mantissa = Mantissa + 0x00002000
                        if (Mantissa & 0x00800000):
                            Mantissa = 0
                            exponent = exponent + 1
                    if exponent >= 30:
                        Result = (Sign << 15) | 0x7C00
                    else:
                        Result = (Sign << 15) | (exponent << 10) | (Mantissa >> 13)
    return Result

# ============================================================
# 权重比较函数 (用于排序)
# ============================================================
# ============================================================
# 字符串工具函数
# ============================================================

def read_fixed_string(f, fixed_len):
    """读取固定长度的 null-terminated 字符串"""
    s = b''
    length = 0
    finished = False
    for i in range(fixed_len):
        c = read_byte(f)
        if c == 0:
            finished = True
        if finished:
            continue
        s += bytes([c])
        if c != 32:
            length = i + 1
    return s[:length].decode('ascii', errors='replace')

def paddstring(length, instring):
    """用 0 填充字符串到指定长度"""
    s = str(instring)
    if len(s) <= length:
        return '0' * (length - len(s)) + s
    else:
        return s[:length]

# ============================================================
# 坐标/UV/顶点读取函数
# ============================================================

def read_vec3_pos(f):
    """读取 float3 位置 (坐标转换: x, z, -y)"""
    x = read_float(f)
    z = read_float(f)
    y = -read_float(f)
    return [x, y, z]

def read_vertex_pos(f):
    """读取 short3 位置 (归一化到 32767)"""
    x = read_short_signed(f) / 32767.0
    z = read_short_signed(f) / 32767.0
    y = -read_short_signed(f) / 32767.0
    return [x, y, z]

#: UV 允许的合理范围. MHGU 的 UV 基本落在 [0, 1]; 半精度解码若明显超出该范围,
#: 说明该字段不是 UV (个别 FVF 变体把其它数据放在同一位置), 此时回退为 (0,0),
#: 避免把乱码写进 UV 层导致"UV 变奇怪".
UV_SANE_LIMIT = 2.0

def read_byte_signed(f):
    """读取 1 个**有符号**字节 (-128..127)"""
    v = read_byte(f)
    return v - 256 if v > 127 else v


def read_normal(f):
    """读取 4 个有符号字节表示的法向 (xyz 各 /127, 第 4 字节忽略)。

    坐标转换必须与 `read_vertex_pos` 一致: 文件里是 (X, Z, Y) 顺序,
    Blender 用 (X, -Z, Y)。实测 f_body001 网格 0 按此解码后法向模长 0.992,
    单位长度命中率 100%。
    """
    x = read_byte_signed(f) / 127.0
    z = read_byte_signed(f) / 127.0
    y = -read_byte_signed(f) / 127.0
    read_byte(f)                      # 第 4 个字节, 通常为 0
    nx, ny, nz = x, y, z
    L = (nx * nx + ny * ny + nz * nz) ** 0.5
    if L > 1e-6:                      # 归一化, 避免编码误差带来的缩放
        nx, ny, nz = nx / L, ny / L, nz / L
    return [nx, ny, nz]

def read_uv_half(f):
    """读取半精度 UV (V 翻转).

    `.mod` 的 UV 是 2 个半精度浮点, 游戏使用左上原点, Blender 使用左下原点,
    因此 V 需要翻转: ``v = 1 - v``.

    若解码结果明显不是 UV (超出 ``UV_SANE_LIMIT``), 返回 (0, 0) 而不是乱码.
    """
    u = read_float16(f)
    v = read_float16(f) * -1.0 + 1.0
    if (u != u or v != v or abs(u) > UV_SANE_LIMIT or abs(v) > UV_SANE_LIMIT):
        return [0.0, 0.0, 0.0]
    return [u, v, 0.0]

def read_matrix(f):
    """读取骨骼 4x4 变换矩阵 (16 floats = 64 bytes), 返回 Blender 矩阵.

    16 个 float 按**列主序 (column-major)** 解释, 即:
        M[row][col] = floats[col*4 + row]
    平移位于**最后一列** ``M[0][3], M[1][3], M[2][3]`` (OpenGL 风格).

    验证依据 (实机 5 个文件 / 42 根骨骼, 零误差):
        world[i].translation == world[parent].translation - local[i].translation
    列主序解释通过 31/31 项检查; 行主序仅通过 12/33, 因此列主序是正确解释.

    注意: 3ds Max 脚本 ReadMatrix 的 row4 swizzle
    ``[-f13, f15, -f14, f16]`` 是历史遗留写法, 不要移植.
    """
    v = [read_float(f) for _ in range(16)]
    # 列主序: 每 4 个 float 是一列
    return Matrix((
        (v[0], v[4], v[8],  v[12]),
        (v[1], v[5], v[9],  v[13]),
        (v[2], v[6], v[10], v[14]),
        (v[3], v[7], v[11], v[15]),
    ))

def get_bound(f):
    """读取 4 个 float 边界"""
    return [read_float(f), read_float(f), read_float(f), read_float(f)]

# ============================================================
# 读取 Header
# ============================================================

def read_header(f):
    """读取 MOD 文件头 (52 bytes)"""
    h = Header()
    h.BoneCount = read_short(f)
    h.MeshCount = read_short(f)
    h.MatCount = read_short(f)
    h.VertCount = read_long(f)
    h.TriangleCount = read_long(f)
    h.VertexIds = read_long(f)
    h.VertexBufferSize = read_long(f)
    h.Padding = read_long(f)
    h.BoneMapCount = read_long(f)
    h.ptr_Bone = read_long(f)
    h.ptr_BoneMap = read_long(f)
    h.ptr_MatID = read_long(f)
    h.ptr_Mesh = read_long(f)
    h.ptr_vertex = read_long(f)
    h.ptr_triangle = read_long(f)
    h.EndSize = read_long(f)
    return h

# ============================================================
# 读取 BoneInfo
# ============================================================

def read_bone_info(f):
    """读取骨骼信息 (24 bytes)

    布局 (已对 MHGU 实机文件验证, 与 3ds Max 脚本 struct BoneInfo 一致):
        ID u8, Parent u8, Child u8, uk1 u8,
        TransX f32, TransY f32, TransZ f32, uk2 f32, uk3 f32
    共 4 + 5*4 = 24 字节.

    注意: 旧版本错误地按 16 字节读取, 导致骨骼矩阵数组整体错位,
    这是"导入后没有骨骼 / 模型巨大"的根因之一.
    """
    info = BoneInfo()
    info.ID = read_byte(f)
    info.Parent = read_byte(f)
    info.Child = read_byte(f)
    info.uk1 = read_byte(f)
    info.Trans = [read_float(f), read_float(f), read_float(f)]
    info.uk2 = read_float(f)
    info.uk3 = read_float(f)
    return info

# ============================================================
# 读取 MeshHeader
# ============================================================

def read_mesh_header(f):
    """读取网格头 (48 bytes)"""
    m = MeshHeader()
    m.meshtype = read_short(f)
    m.vertCount = read_short(f)
    m.unk01 = read_byte(f)
    m.MatId = read_short(f)
    m.lodLevel = read_byte(f)
    m.unk04 = read_byte(f)
    m.vertFlag = read_byte(f)
    m.vertStride = read_byte(f)
    m.unk05 = read_byte(f)
    m.vertStart = read_long(f)
    m.vertBase = read_long(f)
    m.fvfInfo = read_long(f)
    m.faceStart = read_long(f)
    m.faceCount = read_long(f)
    m.faceBase = read_long(f)
    m.bonemapindex = read_byte(f)
    m.weightmaps = read_byte(f)
    m.unk07 = read_byte(f)
    m.unk08 = read_byte(f)
    m.min_index = read_short(f)
    m.max_index = read_short(f)
    m.unk09 = read_long(f)
    return m

def get_skin_weights(obj, vertex_index):
    """Get skin weights for a vertex from Blender vertex groups.
    Returns (bone_indices_list, weights_list) where bone_indices are 0-based.

    使用顶点自己的 ``v.groups`` 读取 (而不是遍历所有顶点组调用
    ``vg.weight(index)``): 后者是 O(组数) 的慢写法, 而且 Blender 3.0 会对
    "不在该组里的顶点"往控制台刷 ``Error: Vertex not in group``.
    """
    bones = []
    weights = []

    mesh = getattr(obj, "data", None)
    verts = getattr(mesh, "vertices", None) if mesh is not None else None
    if verts is not None and 0 <= vertex_index < len(verts):
        for g in verts[vertex_index].groups:
            if g.weight > 0.001:
                bones.append(g.group)
                weights.append(g.weight)

    combined = list(zip(bones, weights))
    combined.sort(key=lambda x: -x[1])
    
    if combined:
        bones = [b for b, w in combined]
        weights = [w for b, w in combined]
    else:
        bones = [0]
        weights = [1.0]
    
    return bones, weights

# ============================================================
# 骨骼 / 骨架
# ============================================================

#: 顶点权重中表示"无骨骼"(绑定到根/静态)的哨兵值.
#: 顶点数据里的骨骼索引是 0 基, 加 1 后落到这个值, 意味着该顶点不绑定任何骨骼.
NO_BONE_SENTINEL = 256

def bone_name_for(index):
    """骨骼显示名. index 为 1 基 (.mod 内部编号)."""
    if index >= NO_BONE_SENTINEL or index <= 0:
        return "b_root"
    return "b_{}".format(index)

def convert_bone_position(trans):
    """把骨骼世界矩阵的平移分量转换为 Blender 坐标.

    .mod 里存的是**逆绑定 (inverse bind)** 风格的矩阵: 平移分量是
    骨骼位置取负后的结果, 且分量顺序为 (X, Z, Y). 因此需要:

        Blender = (-v12, v14, -v13)

    即对 (x, y, z) 施加 ``(-x, z, -y)`` —— 等价于把旧移植代码的
    ``(x, -z, y)`` 取反 (点反射). 旧代码少取了这个反号, 导致整副骨架
    相对模型发生 180° 点反射, 位置完全错乱.

    验证依据 (f_body001, 单位 /S, 修正后):
        骨盆 (0.4469, -0.0910, 0.5531)      居中
        左腿 髋0.457 → 膝0.250 → 脚0.064   沿 -Z 向下, 长度合理
        脊柱 0.553 → 胸0.633 → 颈0.750 → 头0.816
        双臂 肩(0.431/0.462) → 肘 → 腕 → 手(0.085/0.809), Z≈0.744
    19/19 根骨骼落在网格包围盒内, 平均"到最近顶点"距离 0.031 (对角线归一化).
    """
    x, y, z = trans[0], trans[1], trans[2]
    return Vector((-x, z, -y))

def build_armature(name, bone_infos, world_matrices, bone_lut=None, dequant=None,
                   bbox_min=None, bbox_max=None, mesh_min=None, mesh_max=None):
    """根据 .mod 骨骼数据创建 Blender 骨架 (Armature).

    参数:
        name:           骨架对象名
        bone_infos:     BoneInfo 列表 (长度 = BoneCount)
        world_matrices: 每个骨骼的世界矩阵 (mathutils.Matrix 列表)
        bone_lut:       256 长度查找表 (逻辑->物理), 可为 None
        dequant:        反量化系数 (世界矩阵 3x3 的对角值) —— 必须传入,
                        否则骨架会比网格大约 193 倍.
        bbox_min/max:   文件包围盒 (原始值), 备用.
        mesh_min/max:   实际导入网格顶点的包围盒 (Blender 空间).
                        传入后骨架会被平移到与该包围盒对齐.

    返回 armature 对象.
    """
    arm_data = bpy.data.armatures.new(name)
    arm_obj = bpy.data.objects.new(name, arm_data)
    bpy.context.collection.objects.link(arm_obj)
    arm_obj.show_in_front = True

    count = len(bone_infos)
    if not dequant or dequant <= 1e-9:
        dequant = 1.0

    # 先把骨骼放到 Blender 坐标系 (反量化 + 轴变换), 但尚未平移
    raw_heads = []
    for i in range(count):
        m = world_matrices[i]
        # 平移位于矩阵最后一列 (列主序解释)
        t = (m[0][3] / dequant, m[1][3] / dequant, m[2][3] / dequant)
        raw_heads.append(convert_bone_position(t))

    # 修正后的轴变换已经把骨骼放到与网格完全相同的坐标系里
    # (顶点 = short/32767, 骨骼 = 矩阵平移/S, 两者同一个空间),
    # 因此**不需要任何额外平移**。旧版本用包围盒强行对齐反而会把骨架推歪.
    heads = list(raw_heads)

    # 建立父子关系.
    # 注意: BoneInfo.Parent 存的是**记录下标 (record index)**, 不是逻辑 ID!
    # 实测 (42 根骨骼 / 5 个文件): 按记录下标解释时
    #     world[i].translation == world[Parent].translation - local[i].translation
    # 误差为 0.000; 若按逻辑 ID 查找, 误差高达 131.6 并产生错乱的层级
    # (这正是旧版本"骨骼混乱"的原因). 255 表示根骨骼.
    parents = []
    for i, info in enumerate(bone_infos):
        p = info.Parent
        if p is None or p >= 254 or p < 0 or p == i:
            parents.append(-1)
        else:
            parents.append(int(p))

    prev_active = bpy.context.view_layer.objects.active
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode='EDIT')

    edit_bones = []
    for i in range(count):
        eb = arm_data.edit_bones.new(bone_name_for(i + 1))
        eb.head = heads[i]
        eb.tail = heads[i] + Vector((0.0, 0.0, 1e-4))
        edit_bones.append(eb)

    for i in range(count):
        p = parents[i]
        if 0 <= p < count and p != i:
            edit_bones[i].parent = edit_bones[p]

    # ---- 骨骼长度 (tail) ----
    # 单一子骨骼 -> tail 指向子骨骼头部 (标准的链式骨骼, 长度自然正确);
    # 多子骨骼   -> 指向各子骨骼方向的平均;
    # 叶子骨骼   -> 沿"父->自身"方向延伸一小段 (游戏骨架没有显式长度).
    size = 1.0
    if heads:
        size = max(
            max(h.x for h in heads) - min(h.x for h in heads),
            max(h.y for h in heads) - min(h.y for h in heads),
            max(h.z for h in heads) - min(h.z for h in heads),
        ) or 1.0
    default_len = size * 0.06

    for i in range(count):
        children = [j for j in range(count) if parents[j] == i]
        h = heads[i]
        if len(children) == 1:
            tail = heads[children[0]]
            if (tail - h).length > 1e-6:
                edit_bones[i].tail = tail
                continue
        if children:
            acc = Vector((0.0, 0.0, 0.0))
            for j in children:
                d = heads[j] - h
                if d.length > 1e-6:
                    acc += d.normalized()
            if acc.length > 1e-6:
                L = sum((heads[j] - h).length for j in children) / len(children)
                edit_bones[i].tail = h + acc.normalized() * max(L * 0.6, default_len)
                continue
        # 叶子骨骼: 沿父->自身方向延伸
        p = parents[i]
        if 0 <= p < count:
            d = h - heads[p]
            if d.length > 1e-6:
                edit_bones[i].tail = h + d.normalized() * max(d.length * 0.5, default_len)
                continue
        edit_bones[i].tail = h + Vector((0.0, 0.0, default_len))

    bpy.ops.object.mode_set(mode='OBJECT')

    if prev_active is not None:
        bpy.context.view_layer.objects.active = prev_active

    arm_obj["mt_bone_count"] = count
    if bone_lut:
        arm_obj["mt_bone_lut"] = list(bone_lut[:256])
    return arm_obj

def compute_mesh_scale(world_matrices, bone_count):
    """返回网格对象应使用的缩放.

    .mod 顶点位置是 ±32767 归一化的 short, 骨骼/包围盒使用"游戏单位".
    世界矩阵左上 3x3 的对角值 = short -> 游戏单位 的反量化系数
    (例如 193.459 = 32768/169.38).

    顶点导入后已处于 0..1 归一化区间, 与骨骼位置同量级,
    所以网格对象缩放必须为 1.0; 直接套用该系数会把模型放大约 193 倍
    (这正是旧版本"模型默认会很大"的原因).
    """
    return (1.0, 1.0, 1.0)

def get_dequant_scale(world_matrices, bone_count):
    """提取文件中的反量化系数 (仅用于诊断).

    .mod 把反量化系数烘焙进世界矩阵的 3x3 部分, 同一文件内所有骨骼一致:
    例如身体 193.4593, 手臂 173.2272, 头盔 79.0273.
    """
    if bone_count <= 0 or not world_matrices:
        return 1.0
    m = world_matrices[0]
    s = abs(m[0][0])
    if s < 1e-6:
        s = 1.0
    return s

# ============================================================
# 骨骼对称命名 (.l / .r)
# ============================================================
#
# GU 防具的骨骼原本只有序号名 (b_1 … b_N), Blender 的对称工具
# (X 轴镜像 / 对称化 / 镜像修改器) 都依赖 **同名 + .L/.R 后缀** 才能配对。
# 这里按几何镜像关系自动找出成对的骨骼并改名:
#     -X 一侧 -> <base>.r      +X 一侧 -> <base>.l
# (Blender 中角色朝向 -Y, 所以 +X 是角色的**左**侧)
# base 取配对中较小的那个序号, 例如 b_12 / b_16 这一对 -> b_12.r / b_12.l。
#
# 顶点组同步改名, 因此骨架与网格的绑定不受影响。
# 改名只是"显示名": 导出时用记录下来的对照表换算回原本的骨序号,
# 所以导出的 .mod 与不改名时**完全一致**。

SYM_NAME_MAP_KEY = "MT_BoneNameMap"

def get_armature_bone_name_map(arm_obj):
    """读**某副骨架自己**的骨骼名对照表。

    为什么需要它 (v1.2.6 修正):
      对照表原来是**场景级**的 (``scene[SYM_NAME_MAP_KEY]``), 每次导入都覆盖。
      实测: 导入 body (19 条目) 后再导入 leg, 场景里只剩 leg 的 7 条目 ——
      body 那副骨架的对照表被冲掉了。
      后果不是"名字对错", 而是**带 .l/.r 后缀的骨骼再也解析不出记录号**:
      那种名字里同一个数字对应两个不同记录 (b_2.r -> 1, b_2.l -> 4),
      光看名字推不出来, 只能靠对照表。表没了 -> 解析成 None -> **该骨骼的
      编辑被静默丢弃**, 导出文件里它还是模板原值。
      所以对照表必须跟骨架走, 和"居中平移量跟对象走"是同一个道理。
    """
    if arm_obj is None:
        return {}
    try:
        m = arm_obj.get(SYM_NAME_MAP_KEY)
    except Exception:
        m = None
    if not m:
        return {}
    out = {}
    try:
        for k in m.keys():
            out[str(k)] = int(m[k])
    except Exception:
        return {}
    return out

def get_bone_name_map(scene=None, arm_obj=None):
    """读"骨骼名 -> 0 基骨序号"对照表 (导出用)。

    ``arm_obj`` 给了就优先用**该骨架自己**的那份; 没有再退回场景级
    (兼容旧工程里只写了场景的那一份)。
    """
    if arm_obj is not None:
        m = get_armature_bone_name_map(arm_obj)
        if m:
            return m
    sc = scene or bpy.context.scene
    try:
        m = sc.get(SYM_NAME_MAP_KEY)
    except Exception:
        m = None
    if not m:
        return {}
    out = {}
    try:
        for k in m.keys():
            out[str(k)] = int(m[k])
    except Exception:
        return {}
    return out

#: 顶点数据指纹 (导入时记录, 导出时用来判断用户是否改过顶点)
VERT_FP_KEY = "mt_vert_fp"

def _q(v, lo, hi):
    """量化并夹紧, 避免 struct.pack 溢出 (坐标/法向偶尔会略微超出 ±1)."""
    i = int(round(v))
    return lo if i < lo else (hi if i > hi else i)

def vertex_normals_file_space(mesh_obj):
    """返回每个顶点的法向 (已转成文件坐标: (x, z, -y)), 长度 = 顶点数.

    **必须优先用拆分法线 (loop normal)**: 用户在 Blender 里用"自定义法线 /
    法向编辑 / 从面重算法线"改的法向只体现在 ``loop.normal`` 上;
    ``vertex.normal`` 是按几何重新算出来的顶点法线, **读不到用户的自定义法线**。
    注意: 顶点格式里每个顶点只存一个法向, 所以这里把同一顶点的所有 loop 法向
    求平均。
    """
    md = getattr(mesh_obj, "data", None)
    if md is None:
        return []
    verts = md.vertices
    n = len(verts)
    out = [Vector((0.0, 0.0, 0.0)) for _ in range(n)]

    got = False
    try:
        from . import compat
        compat.calc_normals_split(md)      # 3.x 需要先算; 4.1+ 直接可用
    except Exception:
        pass
    try:
        for loop in md.loops:
            ln = loop.normal
            if ln.length_squared > 0.0:
                out[loop.vertex_index] += Vector(ln)
                got = True
    except Exception:
        got = False

    if got:
        for i in range(n):
            v = out[i]
            if v.length_squared < 1e-12:
                out[i] = Vector(verts[i].normal)
            else:
                out[i] = v.normalized()
    else:
        for i in range(n):
            out[i] = Vector(verts[i].normal)

    # Blender (x,y,z) -> 文件 (x, z, -y)
    return [Vector((v.x, v.z, -v.y)) for v in out]

def vertex_tangents_file_space(obj, uv_index=0):
    """逐顶点切线, **文件坐标系** (和 vertex_normals_file_space 同一空间)。

    用 UV 导数累积标准 tangent space, 再对法线做正交化 —— 这样切线在整个网格上
    是连续的。旧代码用 "随便叉一个垂直轴" 造切线, 相邻顶点可能选到不同的轴,
    切线帧跳变, 游戏里表现就是光照/法线贴图花掉。

    解析不出 UV 时返回空列表, 调用方自行退化处理。
    """
    from mathutils import Vector
    me = obj.data
    if not me.uv_layers or len(me.vertices) == 0:
        return []
    uvl = me.uv_layers[min(uv_index, len(me.uv_layers) - 1)].data

    n_v = len(me.vertices)
    tan = [Vector((0.0, 0.0, 0.0)) for _ in range(n_v)]
    bit = [Vector((0.0, 0.0, 0.0)) for _ in range(n_v)]
    co = [v.co.copy() for v in me.vertices]

    for poly in me.polygons:
        lt = poly.loop_total
        if lt < 3:
            continue
        li = poly.loop_start
        vs = [me.loops[li + k].vertex_index for k in range(lt)]
        uvs = [uvl[li + k].uv for k in range(lt)]
        for k in range(1, lt - 1):
            i0, i1, i2 = vs[0], vs[k], vs[k + 1]
            w0, w1, w2 = uvs[0], uvs[k], uvs[k + 1]
            e1 = co[i1] - co[i0]
            e2 = co[i2] - co[i0]
            d1x, d1y = w1.x - w0.x, w1.y - w0.y
            d2x, d2y = w2.x - w0.x, w2.y - w0.y
            r = d1x * d2y - d2x * d1y
            if abs(r) < 1e-12:
                continue
            r = 1.0 / r
            sdir = (e1 * d2y - e2 * d1y) * r
            tdir = (e2 * d1x - e1 * d2x) * r
            tan[i0] += sdir; bit[i0] += tdir
            tan[i1] += sdir; bit[i1] += tdir
            tan[i2] += sdir; bit[i2] += tdir

    # 法线 (blender 空间) 用于正交化
    nrm_bl = [v.normal.copy() for v in me.vertices]
    out = []
    for i in range(n_v):
        n = nrm_bl[i]
        t = tan[i]
        if t.length < 1e-9:
            t = Vector((1.0, 0.0, 0.0))
            if abs(n.x) > 0.9:
                t = Vector((0.0, 1.0, 0.0))
        t = t - n * t.dot(n)
        if t.length < 1e-9:
            t = Vector((1.0, 0.0, 0.0))
            if abs(n.x) > 0.9:
                t = Vector((0.0, 1.0, 0.0))
            t = t - n * t.dot(n)
        t.normalize()
        # blender 空间 -> 文件空间: (x, y, z) -> (x, z, -y)
        out.append(Vector((t.x, t.z, -t.y)))
    return out

def mesh_vertex_fingerprint(mesh_obj):
    """给网格的顶点数据算一个指纹 (位置 / 法向 / UV / 权重).

    用途: 导出时判断"用户到底改没改顶点"。

    旧版导出器只看**顶点数有没有变** —— 顶点数没变就直接把原始顶点字节整段抄回去,
    于是用户改过的法向(以及位置、UV)全部被丢掉, 游戏里看到的还是原版法向。
    """
    import hashlib
    import struct as _struct

    md = getattr(mesh_obj, "data", None)
    if md is None:
        return None
    h = hashlib.md5()

    # ★★ 对象变换必须计入指纹 (v1.2.3 修正)。
    #
    # 这是个**设计缺陷**, 不是小 bug:
    #   指纹原来只算 `v.co` (网格**局部**坐标), 而导出写文件用的是
    #   `matrix_world @ v.co - 居中平移量`。
    #   于是只要用户**只移动对象**(没动局部顶点) —— 例如移动骨架 (网格是它的
    #   子级) 或直接移动网格 —— 指纹就判定"没改过", 导出**整段抄模板的顶点
    #   字节**, 那次位移被**静默丢掉**。
    #   而骨骼段是按 Blender 实际位置重算的 -> 一个动了、一个没动,
    #   相对关系被扯开 -> 游戏里模型整体偏高/偏低。
    #   实测: 骨架对象上移 0.10 -> 导出再导入, 网格位移 -0.10000 完全丢失,
    #   相对关系从 -0.06410 变成 -0.16410。
    #
    # 折进指纹的是 `matrix_world` 与**该对象自己的居中平移量之差** ——
    # 也就是"相对文件坐标的有效变换"。刚导入时两者相等、差为 0,
    # 所以导入->导出仍然逐字节一致 (不会破坏那条保证)。
    try:
        from mathutils import Vector as _V
        _c = get_object_center_offset(mesh_obj)
        _m = mesh_obj.matrix_world
        _d = _m.translation - _V((_c[0], _c[1], _c[2]))
        # 平移按 1e-4 量化 (浮点噪声不该触发重新编码)
        h.update(_struct.pack("<iii",
                              int(round(_d.x * 10000)),
                              int(round(_d.y * 10000)),
                              int(round(_d.z * 10000))))
        # 旋转/缩放也计入 (用户可能整体旋转或缩放网格)
        for _r in range(3):
            for _cc in range(3):
                h.update(_struct.pack(
                    "<i", int(round(_m.to_3x3()[_r][_cc] * 100000))))
    except Exception:
        # 拿不到变换时不要静默 —— 直接判定"改过了", 走重新编码 (结果正确)
        h.update(b"\xffNOXFORM")

    # 位置
    for v in md.vertices:
        co = v.co
        h.update(_struct.pack("<hhh", _q(co.x * 32767, -32767, 32767),
                              _q(co.z * 32767, -32767, 32767),
                              _q(-co.y * 32767, -32767, 32767)))

    # 法向 (用拆分法线, 才读得到用户的自定义法线)
    for nrm in vertex_normals_file_space(mesh_obj):
        h.update(_struct.pack("<bbb", _q(nrm.x * 127, -127, 127),
                              _q(nrm.y * 127, -127, 127),
                              _q(nrm.z * 127, -127, 127)))

    # UV: 每个顶点取第一条 loop 的 UV (与导出器一致)
    if md.uv_layers and len(md.loops) and len(md.uv_layers.active.data) >= len(md.loops):
        ul = md.uv_layers.active.data
        first = {}
        for loop in md.loops:
            if loop.vertex_index not in first:
                first[loop.vertex_index] = ul[loop.index].uv
        for i in range(len(md.vertices)):
            uv = first.get(i)
            if uv is None:
                h.update(b"\x00\x00\x00\x00")
            else:
                h.update(_struct.pack("<hh", _q(uv.x * 32767, -32767, 32767),
                                      _q(uv.y * 32767, -32767, 32767)))

    # 权重 (组序号 + 量化权重)
    for v in md.vertices:
        ent = sorted((g.group, _q(g.weight * 255, 0, 255))
                     for g in v.groups if g.weight > 0.0)
        h.update(_struct.pack("<H", len(ent)))
        for gi, w in ent:
            h.update(_struct.pack("<HB", min(65535, gi), w))

    # Blender 自定义属性是**有符号 63 位**, 所以取 63 位
    return int.from_bytes(h.digest()[:8], "little") & ((1 << 63) - 1)

def remember_vertex_fingerprint(mesh_obj):
    """把当前顶点指纹记录到网格对象上 (导入结束时调用).

    以**十六进制字符串**保存: 有些 Blender 版本对写入大整数 ID 属性会静默失败,
    字符串最稳妥。同时把失败原因打印出来, 不再静默吞掉。
    """
    fp = mesh_vertex_fingerprint(mesh_obj)
    if fp is None:
        return None
    text = "%016x" % fp
    try:
        mesh_obj[VERT_FP_KEY] = text
    except Exception as exc:
        print("记录顶点指纹失败: %s" % exc)
    if mesh_obj.get(VERT_FP_KEY) is None:
        print("警告: 顶点指纹没能写入 %s, 导出时会保守地重新编码顶点" % mesh_obj.name)
    return fp

def vertex_data_modified(mesh_obj):
    """顶点数据是否与导入时不同. 没有记录过指纹时返回 True (保守起见重新编码)."""
    fp = mesh_vertex_fingerprint(mesh_obj)
    if fp is None:
        return True
    stored = mesh_obj.get(VERT_FP_KEY)
    if stored is not None:
        try:
            return int(str(stored), 16) != fp
        except Exception:
            pass
    stored = mesh_obj.get(VERT_FP_KEY + "_int")
    if stored is not None:
        try:
            return int(stored) != fp
        except Exception:
            pass
    return True

def _bone_index_from_name(name):
    """从 ``b_12`` 这类名字取 0 基骨序号; 不匹配返回 None."""
    if not name or not name.startswith("b_"):
        return None
    rest = name[2:]
    if rest.isdigit():
        return int(rest) - 1
    return None

def build_mirror_pairs(arm_obj, tol=0.004):
    """找出绕 X 轴镜像成对的骨骼.

    返回 ``[(right_name, left_name, base), ...]``, right = -X 侧, left = +X 侧.

    注意: 镜像面不一定在 X=0 —— 未做居中的 .mod, 骨架整体位于 X 正半轴。
    因此这里先按骨架自身的 X 范围求出对称面 ``cx``, 再以 ``cx`` 为基准判断。
    """
    entries = []
    for b in arm_obj.data.bones:
        idx = _bone_index_from_name(b.name)
        if idx is not None:
            entries.append((idx, b))
    entries.sort(key=lambda e: e[0])
    if not entries:
        return []

    mw = arm_obj.matrix_world
    heads = {idx: (mw @ b.head_local) for idx, b in entries}

    # 对称面 = 骨骼 X 范围的中点
    xs = [h.x for h in heads.values()]
    cx = (min(xs) + max(xs)) * 0.5

    pairs = []
    used = set()
    for idx_a, bone_a in entries:
        if idx_a in used:
            continue
        ha = heads[idx_a]
        da = ha.x - cx
        if abs(da) <= tol:
            continue                     # 中线骨骼没有左右之分
        partner = None
        for idx_b, bone_b in entries:
            if idx_b == idx_a or idx_b in used:
                continue
            hb = heads[idx_b]
            db = hb.x - cx
            if abs(db) <= tol:
                continue
            if abs(da + db) > tol:       # 关于 cx 镜像
                continue
            if abs(ha.y - hb.y) > tol or abs(ha.z - hb.z) > tol:
                continue
            partner = (idx_b, bone_b)
            break
        if partner is None:
            continue
        idx_b, bone_b = partner
        if da < 0:
            right, left = (idx_a, bone_a), (idx_b, bone_b)
        else:
            right, left = (idx_b, bone_b), (idx_a, bone_a)
        # 名字是 b_<0基序号+1>; 用配对中较小序号那条的名字当基础名。
        # 该名字会随改名一起释放, 因此不会和"没配对的骨骼"撞名。
        base = "b_%d" % (min(idx_a, idx_b) + 1)
        pairs.append((right[1].name, left[1].name, base))
        used.add(idx_a)
        used.add(idx_b)
    return pairs

def apply_symmetric_bone_names(arm_obj, mesh_objs, scene=None, tol=0.004):
    """把镜像成对的骨骼与顶点组改名为 ``<base>.l`` / ``<base>.r``.

    返回 ``(改名的骨骼对数, 名字→骨序号 对照表)``。
    """
    scene = scene or bpy.context.scene
    pairs = build_mirror_pairs(arm_obj, tol)
    if not pairs:
        return 0, {}

    ren = {}
    for rname, lname, base in pairs:
        ren[rname] = base + ".r"
        ren[lname] = base + ".l"

    # ---- 1) 骨骼改名 ----
    prev = bpy.context.view_layer.objects.active
    try:
        bpy.context.view_layer.objects.active = arm_obj
        bpy.ops.object.mode_set(mode='EDIT')
        ebs = arm_obj.data.edit_bones
        for old, new in ren.items():
            eb = ebs.get(old)
            if eb is not None:
                eb.name = new
        bpy.ops.object.mode_set(mode='OBJECT')
    finally:
        if prev is not None:
            bpy.context.view_layer.objects.active = prev

    # ---- 2) 顶点组同步改名 (只改名, 不改顺序 → 导出映射不受影响) ----
    for obj in mesh_objs:
        if obj is None or obj.type != 'MESH':
            continue
        for old, new in ren.items():
            vg = obj.vertex_groups.get(old)
            if vg is not None:
                vg.name = new

    # ---- 3) 记录"名字 → 原骨序号"对照表, 供导出使用 ----
    name_map = {}
    for b in arm_obj.data.bones:
        idx = _bone_index_from_name(b.name)
        if idx is None:
            for old, new in ren.items():
                if new == b.name:
                    idx = _bone_index_from_name(old)
                    break
        if idx is not None:
            name_map[b.name] = idx
    try:
        scene[SYM_NAME_MAP_KEY] = name_map
    except Exception:
        pass
    # ★ 同时写到**这副骨架自己**身上。
    # 场景级那份会被下一次导入覆盖 (实测 19 条目 -> 7 条目), 而带 .l/.r 后缀的
    # 骨骼名离开对照表就解析不出记录号 -> 编辑被静默丢弃。
    # 写到骨架上是为了让每副骨架都留着自己那份。
    try:
        arm_obj[SYM_NAME_MAP_KEY] = dict(name_map)
    except Exception:
        pass
    return len(pairs), name_map

def _deprecated_get_bone_name_map(scene=None):
    """已废弃 —— 见上面的 ``get_bone_name_map(scene, arm_obj)``。

    保留这个名字只为兼容外部调用, 不要使用。
    """
    return get_bone_name_map(scene)

# ============================================================
# 模型居中 (便于与第三方模型对齐)
# ============================================================

#: 居中模式
CENTER_NONE = 'NONE'            # 不处理
CENTER_XY_GROUND = 'XY_GROUND'  # X/Y 居中, Z 贴地 (默认, 最适合与 MMD 等第三方模型对齐)
CENTER_ALL = 'CENTER'           # 包围盒正中心移到原点

def compute_world_bounds(objects):
    """计算一组对象中所有网格顶点的世界坐标包围盒.

    返回 (min, max) 两个 Vector; 若没有网格顶点则返回 (None, None).
    """
    mn = None
    mx = None
    for obj in objects:
        if obj is None or obj.type != 'MESH':
            continue
        mw = obj.matrix_world
        for v in obj.data.vertices:
            p = mw @ v.co
            if mn is None:
                mn = Vector((p.x, p.y, p.z))
                mx = Vector((p.x, p.y, p.z))
            else:
                if p.x < mn.x: mn.x = p.x
                if p.y < mn.y: mn.y = p.y
                if p.z < mn.z: mn.z = p.z
                if p.x > mx.x: mx.x = p.x
                if p.y > mx.y: mx.y = p.y
                if p.z > mx.z: mx.z = p.z
    return mn, mx

def centering_offset(mn, mx, mode):
    """根据包围盒和模式计算需要施加的世界平移量."""
    if mn is None or mx is None or mode == CENTER_NONE:
        return Vector((0.0, 0.0, 0.0))
    cx = (mn.x + mx.x) * 0.5
    cy = (mn.y + mx.y) * 0.5
    cz = (mn.z + mx.z) * 0.5
    if mode == CENTER_XY_GROUND:
        # X/Y 居中, 最低点落到 Z=0
        return Vector((-cx, -cy, -mn.z))
    if mode == CENTER_ALL:
        return Vector((-cx, -cy, -cz))
    return Vector((0.0, 0.0, 0.0))

def center_objects(objects, mode=CENTER_XY_GROUND):
    """把一组对象整体平移, 使模型居中 (只改对象变换, 不动网格数据).

    只移动顶层对象 (没有父级, 或父级不在本组内), 子对象会跟随父级一起移动.

    **重要 (v1.2 修正)**: 居中会改变「Blender 世界坐标」与「文件坐标」的对应关系。
    `.mod` 里的顶点是按**文件坐标**写的, 而导出时顶点取自网格数据 ——
    如果被导出的网格不是导入时那一份 (例如你另外导入了一个 MMD 模型、
    再绑到这套骨架上), 它的局部坐标位于 Blender 原点, 直接导出就会与文件里的
    骨骼错开半个身位, 进游戏后表现为**整体偏移**。

    因此这里会把累计的居中平移量记录到场景 (`MT_CenterOffset`),
    导出时用它把顶点换算回文件坐标; 记录后导出不会偏移。

    返回实际施加的平移量.
    """
    objs = [o for o in objects if o is not None]
    if not objs or mode == CENTER_NONE:
        return Vector((0.0, 0.0, 0.0))

    mn, mx = compute_world_bounds(objs)
    offset = centering_offset(mn, mx, mode)
    if offset.length < 1e-12:
        return offset

    group = set(objs)
    roots = [o for o in objs if o.parent is None or o.parent not in group]
    if not roots:
        roots = objs
    for obj in roots:
        obj.matrix_world = Matrix.Translation(offset) @ obj.matrix_world
    # 让子对象的 matrix_world 立即反映父级位移 (否则调用方读到的还是旧值)
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    # ★ 除了场景级的累计值, **每个被移动的对象各自记一份**。
    # 原因见 get_object_center_offset 的说明。
    #
    # 注意: 这里取 prev 必须读**对象自己的**记录, 默认 0 ——
    # **不能**用 get_object_center_offset(), 那个在对象没记录时会退回场景值,
    # 于是第二次导入时会把第一次的量也加进来 (实测: leg 被记成 -0.61516,
    # 而它自己只该是 -0.16826), 导致骨骼整体偏 73 文件单位。
    for obj in objs:
        try:
            _raw = obj.get(CENTER_OFFSET_OBJ_KEY)
            if _raw:
                prev = Vector((float(_raw[0]), float(_raw[1]), float(_raw[2])))
            else:
                prev = Vector((0.0, 0.0, 0.0))
            obj[CENTER_OFFSET_OBJ_KEY] = [float(prev[0] + offset[0]),
                                          float(prev[1] + offset[1]),
                                          float(prev[2] + offset[2])]
        except Exception:
            pass
    add_center_offset(offset)
    return offset

# ------------------------------------------------------------
# 居中平移量的记录 (导出时用它把顶点换算回文件坐标)
# ------------------------------------------------------------

CENTER_OFFSET_KEY = "MT_CenterOffset"

#: 每个对象各自记录的居中平移量。
#:
#: 为什么需要它 (v1.2.1 修正):
#:   场景级的 MT_CenterOffset 是**累加**的, 而导出时每个对象都减同一个值。
#:   于是只要场景里的对象不是"同一批一起居中的", 就会错 ——
#:   典型两种:
#:     * 导入第二个 .mod  -> 场景值变成两次之和, 第一个模型的导出被整体平移;
#:     * 后来新建/额外导入的网格 (没参与过居中) -> 也被减掉那个值, 整体偏掉。
#:   实测 (用户工程): 7 个网格里 6 个 matrix_world == coff, 1 个 == (0,0,0) ——
#:   那一个在导出时会被平移 -coff。
#:   改成"每个对象记自己那次的量"后, 上面两种都不会错。
CENTER_OFFSET_OBJ_KEY = "MT_CenterOffsetObj"

def get_object_center_offset(obj, scene=None):
    """读某个对象**自己**的居中平移量。

    优先用对象上记录的; 没有就退回场景级值 (兼容旧工程和没被居中过的对象)。
    """
    sc = scene or bpy.context.scene
    try:
        v = obj.get(CENTER_OFFSET_OBJ_KEY)
    except Exception:
        v = None
    if v:
        try:
            return Vector((float(v[0]), float(v[1]), float(v[2])))
        except Exception:
            pass
    return get_center_offset(sc)

def get_center_offset(scene=None):
    """读取累计的居中平移量 (Blender 空间, Vector).

    注意: 这是**场景级累加值**。判断"某个对象该减多少"请用
    ``get_object_center_offset(obj)`` —— 那才是每个对象自己的量。
    """
    sc = scene or bpy.context.scene
    try:
        v = sc.get(CENTER_OFFSET_KEY)
    except Exception:
        v = None
    if not v:
        return Vector((0.0, 0.0, 0.0))
    try:
        return Vector((float(v[0]), float(v[1]), float(v[2])))
    except Exception:
        return Vector((0.0, 0.0, 0.0))

def set_center_offset(vec, scene=None):
    """设置累计的居中平移量."""
    sc = scene or bpy.context.scene
    try:
        sc[CENTER_OFFSET_KEY] = [float(vec[0]), float(vec[1]), float(vec[2])]
        return True
    except Exception:
        return False

def add_center_offset(vec, scene=None):
    """累加居中平移量."""
    return set_center_offset(get_center_offset(scene) + Vector(vec), scene)

# ============================================================
# 注册 / 注销
# ============================================================

def register():
    """注册所有 MT Framework 模块"""
    from . import MTframework_MHGU_ui
    MTframework_MHGU_ui.register()
    from . import MTframework_MMD
    MTframework_MMD.register()
    # 贴图 (.tex) 读写 —— 几何之外的功能，独立模块，缺 numpy 时自己跳过
    try:
        from . import MTframework_MHGU_matcheck
        MTframework_MHGU_matcheck.register()
    except Exception as _e:
        print("NOTE: 材质名检查未启用 (%s)" % _e)
    try:
        from . import MTframework_MHGU_helmd
        MTframework_MHGU_helmd.register()
    except Exception as _e:
        print("NOTE: 头盔显示开关未启用 (%s)" % _e)
    try:
        from . import MTframework_MHGU_physparams
        MTframework_MHGU_physparams.register()
    except Exception as _e:
        print("NOTE: 物理参数编辑未启用 (%s)" % _e)
    try:
        from . import MTframework_MHGU_physmat
        MTframework_MHGU_physmat.register()
    except Exception as _e:
        print("NOTE: 物理矩阵自适应未启用 (%s)" % _e)
    try:
        from . import MTframework_MHGU_physcustom
        MTframework_MHGU_physcustom.register()
    except Exception as _e:
        print("NOTE: 自定义物理骨未启用 (%s)" % _e)
    try:
        from . import MTframework_MHGU_phys
        MTframework_MHGU_phys.register()
    except Exception as _e:
        print("NOTE: .arc/物理模块未启用 (%s)" % _e)
    try:
        from . import MTframework_MHGU_tex
        MTframework_MHGU_tex.register()
    except Exception as _e:
        print("NOTE: .tex 贴图模块未启用 (%s)" % _e)

def unregister():
    """注销所有 MT Framework 模块"""
    try:
        from . import MTframework_MHGU_matcheck
        MTframework_MHGU_matcheck.unregister()
    except Exception:
        pass
    try:
        from . import MTframework_MHGU_helmd
        MTframework_MHGU_helmd.unregister()
    except Exception:
        pass
    try:
        from . import MTframework_MHGU_physparams
        MTframework_MHGU_physparams.unregister()
    except Exception:
        pass
    try:
        from . import MTframework_MHGU_physmat
        MTframework_MHGU_physmat.unregister()
    except Exception:
        pass
    try:
        from . import MTframework_MHGU_physcustom
        MTframework_MHGU_physcustom.unregister()
    except Exception:
        pass
    try:
        from . import MTframework_MHGU_phys
        MTframework_MHGU_phys.unregister()
    except Exception:
        pass
    try:
        from . import MTframework_MHGU_tex
        MTframework_MHGU_tex.unregister()
    except Exception:
        pass
    from . import MTframework_MMD
    MTframework_MMD.unregister()
    from . import MTframework_MHGU_ui
    MTframework_MHGU_ui.unregister()

if __name__ == "__main__":
    register()
