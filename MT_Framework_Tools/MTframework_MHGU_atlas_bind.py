import struct
import zlib

from .MTframework_MHGU_verify import (
    MAT_NAME_SZ, MESH_SZ, MOD_VER, MRL_MAT_SZ, MRL_TEX_SZ, MRL_VER,
    _mat_hash, _mesh_info, _read_mod_mat_names, _tex_key, _u16, _u32,
)

TEX_MAGIC = b'TEX\0'
TEX_HASH = 0x241F5DEB
BASE_COLOR_SAMPLER = 0x371

def _used_material_names(mod):
    if len(mod) < 64 or _u16(mod, 4) != MOD_VER:
        raise ValueError('图集绑定需要 MHGU Switch 模型')
    mesh_count, mat_count = struct.unpack_from('<HH', mod, 8)
    name_off, mesh_off = struct.unpack_from('<II', mod, 44)
    if not (64 <= name_off <= name_off + MAT_NAME_SZ * mat_count <= mesh_off
            <= mesh_off + MESH_SZ * mesh_count <= len(mod)):
        raise ValueError('模型材质表或分件表越界')
    names = _read_mod_mat_names(mod)
    meshes = (_mesh_info(mod, mesh_off, index) for index in range(mesh_count))
    slots = sorted({mesh['mat_slot'] for mesh in meshes if mesh['vert_count']})
    if not slots or any(slot >= len(names) or not names[slot] for slot in slots):
        raise ValueError('选择的模型没有可绑定的材质')
    return [names[slot] for slot in slots]

def _atlas_path(model_path, paths):
    folder, _, stem = model_path.rpartition('\\')
    prefix = folder + '\\' if folder else ''
    room = 63 - len(prefix.encode('utf-8')) - len('_atlas_BM_999')
    if room < 1:
        raise ValueError('部位资源路径太长，无法为图集分配 TEX 条目')
    for number in range(1000):
        suffix = f'_{number}' if number else ''
        name = prefix + stem[:room] + '_atlas_BM' + suffix
        if _tex_key(name) not in paths:
            return name
    raise ValueError('找不到可用的图集 TEX 条目名')

def _replace_body(entry, body):
    entry.update(body=body, raw=zlib.compress(body, 9),
                 flag=0x40000000 | (len(body) & 0xFFFFFF))

def bind_atlas(entries, texture):
    models = [entry for entry in entries if entry['body'].startswith(b'MOD\0')]
    materials = [entry for entry in entries if entry['body'].startswith(b'MRL\0')]
    if len(models) != 1 or len(materials) != 1:
        raise ValueError('带图集导出需要容器里有一组 MOD 和 MRL')
    model, material = models[0], materials[0]
    names = _used_material_names(model['body'])
    mrl = bytearray(material['body'])
    if len(mrl) < 28:
        raise ValueError('MRL 文件头不完整')
    ver, mat_count, tex_count, _, tex_off, desc = struct.unpack_from('<6I', mrl, 4)
    insertion = tex_off + tex_count * MRL_TEX_SZ
    desc_end = desc + mat_count * MRL_MAT_SZ
    if ver != MRL_VER or not (28 <= tex_off <= insertion <= desc <= desc_end <= len(mrl)):
        raise ValueError('MRL 贴图表或材质表格式不支持')

    texture_paths = [_tex_key(mrl[pos + 12:pos + MRL_TEX_SZ].split(b'\0', 1)[0].decode('ascii', 'replace'))
                     for pos in range(tex_off, insertion, MRL_TEX_SZ)]
    by_hash = {}
    descriptors = range(desc, desc_end, MRL_MAT_SZ)
    for offset in descriptors:
        by_hash.setdefault(_u32(mrl, offset + 4), []).append(offset)
    references = {}
    for name in names:
        matches = by_hash.get(_mat_hash(name), ())
        if len(matches) != 1:
            raise ValueError(f'材质「{name}」在 MRL 里没有唯一对应项')
        offset = matches[0]
        size = _u32(mrl, offset + 8)
        count = _u32(mrl, offset + 24) & 0xFFF
        start = _u32(mrl, offset + 52)
        if not (desc_end <= start <= start + count * 12 <= start + size <= len(mrl)):
            raise ValueError(f'材质「{name}」的 MRL 指令块越界')
        base = []
        for pos in range(start, start + count * 12, 12):
            kind, slot, sampler = struct.unpack_from('<3I', mrl, pos)
            if kind & 15 == 3 and sampler & 0xFFF == BASE_COLOR_SAMPLER:
                base.append((pos + 4, slot))
        if len(base) != 1 or base[0][1] > tex_count:
            raise ValueError(f'材质「{name}」没有可识别的基础贴图槽')
        references.update(base)

    canonical = _tex_key(model['name'] + '_BM')
    local = [entry for entry in entries if entry['body'].startswith(TEX_MAGIC)
             and _tex_key(entry['name']) == canonical]
    if texture_paths.count(canonical) == 1 and len(local) == 1:
        slot = texture_paths.index(canonical) + 1
        for pos in references:
            struct.pack_into('<I', mrl, pos, slot)
        _replace_body(local[0], texture)
        if any(value != slot for value in references.values()):
            _replace_body(material, bytes(mrl))
        return local[0]['name']

    original_slots = set(references.values())
    if len(original_slots) == 1 and 0 not in original_slots:
        key = texture_paths[next(iter(original_slots)) - 1]
        if key.startswith(_tex_key(model['name']) + '_'):
            existing = [entry for entry in entries if entry['body'].startswith(TEX_MAGIC)
                        and _tex_key(entry['name']) == key]
            if len(existing) == 1:

                _replace_body(existing[0], texture)
                return existing[0]['name']

    if tex_count >= 64:
        raise ValueError('MRL 没有可追加的图集槽，请先在工坊整理贴图表')
    paths = set(texture_paths) | {_tex_key(entry['name']) for entry in entries}
    path = _atlas_path(model['name'], paths)
    slot = tex_count + 1
    for pos in references:
        struct.pack_into('<I', mrl, pos, slot)

    row = struct.pack('<III', TEX_HASH, 0, 0) + path.encode('ascii').ljust(64, b'\0')
    struct.pack_into('<I', mrl, 12, slot)
    struct.pack_into('<I', mrl, 24, desc + MRL_TEX_SZ)
    for offset in descriptors:
        for field in (offset + 52, offset + 56):
            value = _u32(mrl, field)
            if value >= insertion:
                struct.pack_into('<I', mrl, field, value + MRL_TEX_SZ)
    mrl[insertion:insertion] = row
    _replace_body(material, bytes(mrl))
    entry = {'name': path, 'hash': TEX_HASH}
    _replace_body(entry, texture)
    entries.insert(entries.index(material), entry)
    return path
