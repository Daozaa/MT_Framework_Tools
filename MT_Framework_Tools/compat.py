import bpy

def _ver():
    try:
        return tuple(bpy.app.version[:3])
    except Exception:
        return (3, 0, 0)

BLENDER_VERSION = _ver()

def iter_children(obj):
    out = []
    stack = list(getattr(obj, "children", ()) or ())
    seen = set()
    while stack:
        child = stack.pop()
        if child is None or child.name in seen:
            continue
        seen.add(child.name)
        out.append(child)
        stack.extend(list(getattr(child, "children", ()) or ()))
    return out

def calc_normals_split(mesh):
    try:
        mesh.calc_normals_split()
        return True
    except Exception:
        return False

def set_auto_smooth(mesh, value=True):
    try:
        mesh.use_auto_smooth = value
        return True
    except Exception:
        return False

def get_principled(material):
    if not material or not material.use_nodes or not material.node_tree:
        return None
    for node in material.node_tree.nodes:
        if node.type == 'BSDF_PRINCIPLED':
            return node

    try:
        return material.node_tree.nodes.get("Principled BSDF")
    except Exception:
        return None

def set_bsdf_input(bsdf, names, value):
    if bsdf is None:
        return False
    if isinstance(names, str):
        names = (names,)
    for name in names:
        try:
            sock = bsdf.inputs.get(name)
        except Exception:
            sock = None
        if sock is not None:
            try:
                sock.default_value = value
                return True
            except Exception:
                pass
    return False

def set_material_blend(material, alpha=None):
    if material is None:
        return
    if alpha is not None:
        bsdf = get_principled(material)
        set_bsdf_input(bsdf, ("Alpha",), float(alpha))

    try:
        material.blend_method = 'BLEND'
    except Exception:
        pass

    try:
        material.surface_render_method = 'BLENDED'
    except Exception:
        pass

def make_simple_material(name, rgba, alpha=None):
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = get_principled(mat)
    set_bsdf_input(bsdf, ("Base Color",), rgba)
    if alpha is not None:
        set_material_blend(mat, alpha)
    return mat, bsdf
