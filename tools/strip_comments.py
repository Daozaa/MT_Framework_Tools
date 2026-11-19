import ast, io, os, sys, tokenize

SRC = sys.argv[1]
DST = sys.argv[2]
os.makedirs(DST, exist_ok=True)

def doc_lines(tree):
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, 'body', [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
               and isinstance(body[0].value.value, str):
                e = body[0]
                for n in range(e.lineno, getattr(e, 'end_lineno', e.lineno) + 1):
                    out.add(n)
    return out

def strip_file(path):
    raw = open(path, 'rb').read()
    src = raw.decode('utf-8')
    tree = ast.parse(src)
    drop = doc_lines(tree)
    toks = list(tokenize.tokenize(io.BytesIO(raw).readline))
    comment_cols = {}
    for t in toks:
        if t.type == tokenize.COMMENT:
            comment_cols.setdefault(t.start[0], []).append((t.start[1], t.end[1]))
    out = []
    for n, line in enumerate(src.split('\n'), start=1):
        if n in drop:
            continue
        for a, b in sorted(comment_cols.get(n, []), reverse=True):
            line = line[:a] + line[b:]
        out.append(line.rstrip())
    text, blank = [], 0
    for line in out:
        if line.strip() == '':
            blank += 1
            if blank > 1:
                continue
        else:
            blank = 0
        text.append(line)
    return '\n'.join(text).strip('\n') + '\n'

ta = tb = 0
for fn in sorted(os.listdir(SRC)):
    if not fn.endswith('.py'):
        continue
    code = strip_file(os.path.join(SRC, fn))
    open(os.path.join(DST, fn), 'w', encoding='utf-8', newline='\n').write(code)
    a, b = os.path.getsize(os.path.join(SRC, fn)), len(code.encode('utf-8'))
    ta += a; tb += b
print("合计 %d -> %d 字节（%.0f%%），文件 %d 个" % (ta, tb, tb * 100.0 / ta, len(os.listdir(DST))))
print("docstring 残留检查：", end=' ')
bad = 0
for fn in os.listdir(DST):
    txt = open(os.path.join(DST, fn), encoding='utf-8').read()
    if '"""' in txt:
        bad += 1
print(bad, "个文件仍含三引号")
