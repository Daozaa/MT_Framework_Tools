# -*- coding: utf-8 -*-
r"""模板（.mod）随 .blend 走 —— 解决「另存工程做分支后导出不了」。

背景
----
导出的骨表是以「模板 .mod」为底子的，模板路径存在场景属性 MT_LastImportPath 里，
指向 %TEMP%\mt_template_*.mod。用户「另存为」做分支工程时：

  * 这条路径仍是**原工程**（甚至别的工程）的临时模板；
  * 临时文件被重建/清理/覆盖后，分支工程就变成「模板比骨架少骨」→ 导出被拦。

做法
----
1. 导入 / 重建模板后，把模板字节存进 .blend 的 Text 数据块 `MT_Template_mod`
   （latin-1 字符串，内容就是 .mod 原始字节），并记 sha1 到场景属性 MT_TemplateHash。
2. 导出前调用 :func:`sync`：若场景里的模板路径缺失、或内容与 .blend 内嵌的那份不一致，
   就把内嵌的那份重新落盘并指过去。

这样「另存工程」出来的分支自带模板快照，不再依赖 %TEMP% 里别人的文件。
"""
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
    """把模板字节存进 .blend（Text 数据块 + sha1）。返回 sha1，失败返回 ''。"""
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
        # ★ 不能直接写原始字节：Blender 的 Text 数据块是 C 字符串，
        #   遇到 \x00 就截断（实测写进去只剩 3 个字符 "MOD"）。
        #   所以 zlib 压缩 + base64，再带个前缀标记。
        blob = 'MTZ1:' + base64.b64encode(zlib.compress(data, 9)).decode('ascii')
        # ★ 必须按行折！Blender 的 Text 数据块是**按行**存的，单行超长时
        #   Text.from_string / write 是 O(n^2)：实测 800KB 单行要 65 秒（=导入卡死），
        #   76 字符一行则瞬间完成。
        blob = '\n'.join(blob[i:i + 76] for i in range(0, len(blob), 76))
        t.clear()
        t.write(blob)
        h = _sha1(data)
        sc[PROP_HASH] = h
        return h
    except Exception as exc:                                # noqa: BLE001
        print('[MT] 模板内嵌失败:', exc)
        return ''


def load_bytes(context=None):
    """取 .blend 内嵌的模板字节；没有/不是 .mod 返回 None。"""
    try:
        import bpy
        t = bpy.data.texts.get(TEXT_NAME)
        if t is None:
            return None
        txt = ''.join(t.as_string().split())          # 去掉折行/空白
        if not txt.startswith('MTZ1:'):
            return None
        try:
            data = zlib.decompress(base64.b64decode(txt[5:]))
        except Exception:                                   # noqa: BLE001
            return None
        return data if data[:4] == b'MOD\x00' else None
    except Exception:                                       # noqa: BLE001
        return None


def materialize(context=None, suffix=''):
    """把内嵌模板写回临时文件，并写进场景属性。返回路径（失败返回 ''）。"""
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
            except Exception:                               # noqa: BLE001
                need = True
        if need:
            with open(p, 'wb') as f:
                f.write(data)
        sc['MT_LastImportPath'] = p
        return p
    except Exception as exc:                                # noqa: BLE001
        print('[MT] 内嵌模板落盘失败:', exc)
        return ''


def sync(context=None, verbose=True):
    """导出前调用：让场景里的模板 = .blend 内嵌的那份。返回最终路径。"""
    try:
        import bpy
        ctx = context or bpy.context
        sc = ctx.scene
        cur = sc.get('MT_LastImportPath', '') or ''
        emb = load_bytes(ctx)
        if emb is None:
            # 老工程还没有内嵌副本：这次导出顺手存一份，下次保存/另存就带着了
            if cur and os.path.exists(cur):
                store(ctx, cur)
            return cur
        h = _sha1(emb)
        cur_h = ''
        if cur and os.path.exists(cur):
            try:
                with open(cur, 'rb') as f:
                    cur_h = _sha1(f.read())
            except Exception:                               # noqa: BLE001
                cur_h = ''
        if cur_h == h:
            return cur
        p = materialize(ctx)
        if p and verbose:
            print('[MT] 模板按 .blend 内嵌的版本恢复：%s → %s' % (cur or '（空）', p))
        return p or cur
    except Exception as exc:                                # noqa: BLE001
        print('[MT] 模板同步失败:', exc)
        return ''
