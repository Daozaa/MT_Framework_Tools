import base64
import hashlib
import os
import tempfile
import zlib

TEXT_NAME = 'MT_Template_mod'
PROP_HASH = 'MT_TemplateHash'

def _sha1(b):
    return hashlib.sha1(b).hexdigest()

def store(context, path=None):
    try:
        import bpy
        sc = context.scene
        p = path or sc.get('MT_LastImportPath', '') or ''
        if not p or not os.path.exists(p):
            return ''
        with open(p, 'rb') as f:
            data = f.read()
        if data[:4] != b'MOD\x00':
            return ''
        t = bpy.data.texts.get(TEXT_NAME)
        if t is None:
            t = bpy.data.texts.new(TEXT_NAME)

        blob = 'MTZ1:' + base64.b64encode(zlib.compress(data, 9)).decode('ascii')

        blob = '\n'.join(blob[i:i + 76] for i in range(0, len(blob), 76))
        t.clear()
        t.write(blob)
        h = _sha1(data)
        sc[PROP_HASH] = h
        return h
    except Exception as exc:
        print('[MT] 模板内嵌失败:', exc)
        return ''

def load_bytes(context=None):
    try:
        import bpy
        t = bpy.data.texts.get(TEXT_NAME)
        if t is None:
            return None
        txt = ''.join(t.as_string().split())
        if not txt.startswith('MTZ1:'):
            return None
        try:
            data = zlib.decompress(base64.b64decode(txt[5:]))
        except Exception:
            return None
        return data if data[:4] == b'MOD\x00' else None
    except Exception:
        return None

def materialize(context=None, suffix=''):
    try:
        import bpy
        data = load_bytes(context)
        if not data:
            return ''
        ctx = context or bpy.context
        sc = ctx.scene
        name = os.path.splitext(os.path.basename(bpy.data.filepath or 'project'))[0]
        name = ''.join(ch for ch in name if ch.isalnum() or ch in '_-') or 'project'
        p = os.path.join(tempfile.gettempdir(),
                         'mt_template_%s_%s%s.mod' % (name, _sha1(data)[:6], suffix))
        need = True
        if os.path.exists(p):
            try:
                with open(p, 'rb') as f:
                    need = f.read() != data
            except Exception:
                need = True
        if need:
            with open(p, 'wb') as f:
                f.write(data)
        sc['MT_LastImportPath'] = p
        return p
    except Exception as exc:
        print('[MT] 内嵌模板落盘失败:', exc)
        return ''

def sync(context=None, verbose=True):
    try:
        import bpy
        ctx = context or bpy.context
        sc = ctx.scene
        cur = sc.get('MT_LastImportPath', '') or ''
        emb = load_bytes(ctx)
        if emb is None:

            if cur and os.path.exists(cur):
                store(ctx, cur)
            return cur
        h = _sha1(emb)
        cur_h = ''
        if cur and os.path.exists(cur):
            try:
                with open(cur, 'rb') as f:
                    cur_h = _sha1(f.read())
            except Exception:
                cur_h = ''
        if cur_h == h:
            return cur
        p = materialize(ctx)
        if p and verbose:
            print('[MT] 模板按 .blend 内嵌的版本恢复：%s → %s' % (cur or '（空）', p))
        return p or cur
    except Exception as exc:
        print('[MT] 模板同步失败:', exc)
        return ''
