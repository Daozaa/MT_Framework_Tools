import bpy
import numpy as np
from bpy.props import EnumProperty
from bpy.types import Operator

from .MTframework_MHGU_tex import image_to_rgba, resize_rgba, rgba_to_image

PADDING = 16
UV_NAME = 'MHGU_Atlas'

def atlas_for_export(scene, meshes):
    image = getattr(scene, 'MT_TexImage', None)
    objects = [obj for obj in meshes if obj.data.polygons]
    if image is None or not image.get('mt_atlas') or not objects:
        raise ValueError('请在 TEX 栏合并贴图，并选中使用当前图集的网格')
    for obj in objects:
        uv = obj.data.uv_layers.active
        if obj.get('MT_AtlasImage') != image or uv is None or uv.name != obj.get('MT_AtlasUv'):
            raise ValueError(f'「{obj.name}」没有使用当前图集的导出 UV')
    return image

def _source(socket):
    while socket is not None and socket.is_linked:
        link = socket.links[0]
        if link.from_node.type != 'REROUTE':
            return link.from_socket
        socket = link.from_node.inputs[0]
    return None

def _texture(material):
    if material is None or not material.use_nodes:
        raise ValueError('面没有使用节点材质')
    tree = material.node_tree
    outputs = [n for n in tree.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output]
    textures = set()
    for output in outputs:
        pending = [output.inputs.get('Surface')]
        seen = set()
        while pending:
            source = _source(pending.pop())
            if source is None or source.node in seen:
                continue
            node = source.node
            seen.add(node)
            color = node.inputs.get('Base Tex') if node.type == 'GROUP' else None
            if node.type in {'BSDF_PRINCIPLED', 'BSDF_DIFFUSE', 'EMISSION'}:
                color = node.inputs.get('Base Color') or node.inputs.get('Color')
            if color is None:
                pending.extend(s for s in node.inputs if s.type == 'SHADER')
                continue
            tex = _source(color)
            if tex is None or tex.node.type != 'TEX_IMAGE' or tex.name != 'Color':
                raise ValueError(f'「{material.name}」需要直接连接基础色图片')
            textures.add(tex.node)
    if len(textures) != 1:
        raise ValueError(f'「{material.name}」找不到唯一的基础色图片')
    node = textures.pop()
    img = node.image
    if img is None or not all(img.size):
        path = img.filepath if img else ''
        raise ValueError(f'「{material.name}」的基础贴图无法读取：{path or "未指定文件"}')
    if (img.source not in {'FILE', 'GENERATED'} or img.alpha_mode not in {'STRAIGHT', 'NONE'}
            or img.colorspace_settings.name != 'sRGB'):
        raise ValueError(f'「{material.name}」需要可读取的 sRGB 图片（直通 Alpha 或无 Alpha）')
    if img.get('mt_atlas'):
        raise ValueError(f'「{material.name}」已使用 MHGU 图集')
    if node.projection != 'FLAT' or node.extension not in {'REPEAT', 'EXTEND', 'CLIP'}:
        raise ValueError(f'「{material.name}」的图片投影或边界模式暂不支持')
    vector = _source(node.inputs['Vector'])
    if vector is None or (vector.node.type == 'TEX_COORD' and vector.name == 'UV'):
        return node, ''
    if vector.node.type == 'UVMAP' and not vector.node.from_instancer:
        return node, vector.node.uv_map
    if vector.node.type == 'GROUP' and vector.node.name == 'mmd_tex_uv' and vector.name == 'Base UV':
        return node, ''
    raise ValueError(f'「{material.name}」使用了自定义图片坐标，无法直接重排 UV')

def _measure(objects):
    plans = []
    bounds = {}
    textures = {}
    for obj in objects:
        mesh = obj.data
        if not mesh.uv_layers.active:
            raise ValueError(f'「{obj.name}」没有 UV')
        counts = np.empty(len(mesh.polygons), dtype=np.int32)
        slots = np.empty_like(counts)
        mesh.polygons.foreach_get('loop_total', counts)
        mesh.polygons.foreach_get('material_index', slots)
        loop_slots = np.repeat(slots, counts)
        layers = {}
        patches = []
        for slot in np.unique(slots):
            if slot >= len(obj.material_slots):
                raise ValueError(f'「{obj.name}」的面缺少材质')
            material = obj.material_slots[int(slot)].material
            if material not in textures:
                textures[material] = _texture(material)
            node, uv_name = textures[material]
            uv_layer = mesh.uv_layers.get(uv_name) if uv_name else next(
                (uv for uv in mesh.uv_layers if uv.active_render), mesh.uv_layers.active)
            if uv_layer is None:
                raise ValueError(f'「{obj.name}」找不到 UV「{uv_name}」')
            if uv_layer.name not in layers:
                coords = np.empty((len(mesh.loops), 2), dtype=np.float32)
                uv_layer.data.foreach_get('uv', coords.reshape(-1))
                layers[uv_layer.name] = coords
            indices = np.flatnonzero(loop_slots == slot)
            uv = layers[uv_layer.name][indices]
            if not np.isfinite(uv).all():
                raise ValueError(f'「{obj.name}」含无效的 UV 坐标')
            low, high = uv.min(axis=0), uv.max(axis=0)
            if node.extension == 'CLIP' and (np.any(low < -1e-6) or np.any(high > 1 + 1e-6)):
                raise ValueError(f'「{material.name}」使用裁切模式且 UV 超出 0–1')
            if node.extension == 'REPEAT':

                starts = np.cumsum(counts[slots == slot]) - counts[slots == slot]
                offsets = np.floor(np.minimum.reduceat(uv, starts, axis=0) + 1e-6)
                uv -= np.repeat(offsets, counts[slots == slot], axis=0)
                low, high = uv.min(axis=0), uv.max(axis=0)
            key = (node.image, node.extension)
            lo, hi = tuple(low), tuple(high)
            if np.any(np.abs(uv) > 32768) or any(b - a > 16 for a, b in zip(lo, hi)):
                raise ValueError(f'「{material.name}」UV 跨过的贴图格数过多')
            if key in bounds:
                old_lo, old_hi = bounds[key]
                lo = tuple(map(min, lo, old_lo))
                hi = tuple(map(max, hi, old_hi))
            bounds[key] = lo, hi
            patches.append((int(slot), material, node.name, key, indices, uv))
        plans.append((obj, patches))
    return plans, bounds

def _pack(bounds, limit):
    for step in range(55):
        scale = 0.9 ** step
        rects = []
        for key, (lo, hi) in bounds.items():
            unit = tuple(max(1, round(d * scale)) for d in key[0].size)
            start = tuple(int(np.floor(a * u)) for a, u in zip(lo, unit))
            end = tuple(int(np.ceil(b * u)) for b, u in zip(hi, unit))
            w, h = (max(1, b - a) + 2 * PADDING for a, b in zip(start, end))
            rects.append((w, h, key, unit, start))
        rects.sort(key=lambda r: (-r[1], -r[0], r[2][0].name, r[2][1]))
        for side in (256, 512, 1024, 2048, 4096):
            if side > limit:
                break
            x = y = row_height = 0
            placed = {}
            for w, h, key, unit, start in rects:
                if w > side or h > side:
                    break
                if x + w > side:
                    x, y, row_height = 0, y + row_height, 0
                if y + h > side:
                    break
                placed[key] = (x, y, w, h, unit, start)
                x += w
                row_height = max(row_height, h)
            else:
                return side, placed, scale
    raise ValueError('图集放不下，请增大上限或减少选中材质')

def _compose(side, placed):
    atlas = np.zeros((side, side, 4), dtype=np.uint8)

    for key, (x, y, w, h, (tw, th), start) in placed.items():
        img, extension = key
        rgba = image_to_rgba(img)
        if img.alpha_mode == 'NONE':
            rgba[:, :, 3] = 255
        tile = resize_rgba(rgba, tw, th)[::-1]
        ix = np.arange(w) - PADDING + start[0]
        iy = np.arange(h) - PADDING + start[1]
        if extension == 'REPEAT':
            atlas[y:y+h, x:x+w] = tile[iy[:, None] % th, ix % tw]
        else:
            area = atlas[y:y+h, x:x+w]
            area[:] = tile[iy[:, None].clip(0, th-1), ix.clip(0, tw-1)]
            if extension == 'CLIP':
                area[(iy < 0) | (iy >= th), :] = 0
                area[:, (ix < 0) | (ix >= tw)] = 0
    return atlas[::-1]

def make_atlas(objects, limit):
    objects = sorted((o for o in objects if o.type == 'MESH' and len(o.data.polygons)
                      and getattr(o, 'mmd_type', 'NONE') == 'NONE'),
                     key=lambda o: o.name)
    if not objects:
        raise ValueError('先选中带材质和 UV 的网格')
    if any(obj.library or obj.override_library for obj in objects):
        raise ValueError('请先把选中的链接对象转为本地对象')
    plans, bounds = _measure(objects)
    side, placed, scale = _pack(bounds, limit)
    pixels = _compose(side, placed)
    image = rgba_to_image(pixels, 'MHGU_Atlas.png', 'sRGB')
    materials = {}
    staged = []
    try:
        image['mt_atlas'] = True
        image.pack()
        for obj, patches in plans:
            mesh = obj.data.copy()
            object_slots = []
            staged.append((obj, mesh, object_slots))
            render_uv = next((uv.name for uv in mesh.uv_layers if uv.active_render), None)
            layer = mesh.uv_layers.new(name=UV_NAME, do_init=False)
            if layer is None:
                raise ValueError(f'「{obj.name}」没有空闲 UV 层')
            result = np.empty((len(mesh.loops), 2), dtype=np.float32)
            for slot, original, node_name, key, indices, uv in patches:
                x, y, _w, _h, unit, start = placed[key]
                result[indices] = (uv * unit - start + (x + PADDING, y + PADDING)) / side
                mat_key = original, layer.name
                if mat_key not in materials:
                    mat = materials[mat_key] = original.copy()
                    mat.name = original.name + ' · MHGU'
                    tree = mat.node_tree
                    node = tree.nodes[node_name]
                    node.image = image
                    node.extension = 'EXTEND'
                    coords = tree.nodes.new('ShaderNodeUVMap')
                    coords.uv_map = layer.name
                    coords.location = (node.location.x - 200, node.location.y)
                    tree.links.new(coords.outputs['UV'], node.inputs['Vector'])
                if obj.material_slots[slot].link == 'OBJECT':
                    object_slots.append((slot, materials[mat_key]))
                else:
                    mesh.materials[slot] = materials[mat_key]
            layer.data.foreach_set('uv', result.reshape(-1))
            mesh.uv_layers.active = layer
            if render_uv is not None:
                mesh.uv_layers[render_uv].active_render = True
        for obj, mesh, object_slots in staged:
            obj.data = mesh
            for slot, mat in object_slots:
                obj.material_slots[slot].material = mat
            obj['MT_AtlasImage'] = image
            obj['MT_AtlasUv'] = mesh.uv_layers.active.name
    except Exception:
        for _obj, mesh, _slots in staged:
            if not mesh.users:
                bpy.data.meshes.remove(mesh)
        for mat in materials.values():
            if not mat.users:
                bpy.data.materials.remove(mat)
        if not image.users:
            bpy.data.images.remove(image)
        raise
    return image, len({img for img, _ in bounds}), scale

class MT_OT_MakeAtlas(Operator):
    bl_idname = 'mt_framework.make_atlas'
    bl_label = '合并选中网格贴图'
    bl_description = '把选中网格的 MMD 基础贴图合成图集并重排导出 UV，保留对象和原 UV 层'
    bl_options = {'REGISTER', 'UNDO'}

    size: EnumProperty(name='图集上限', items=[(str(n), str(n), '') for n in (1024, 2048)],
                       default='2048')

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and any(o.type == 'MESH' for o in context.selected_objects)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        try:
            img, count, scale = make_atlas(context.selected_objects, int(self.size))
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        context.scene.MT_TexImage = img
        note = f'已合并 {count} 张贴图，图集 {img.size[0]} × {img.size[1]}'
        if scale < 1:
            note += f'，源图缩至约 {scale:.0%}'
        self.report({'INFO'}, note)
        return {'FINISHED'}
