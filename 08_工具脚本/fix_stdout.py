# -*- coding: utf-8 -*-
"""把全项目的 stdout 包装从 TextIOWrapper 换成 reconfigure。

根因：
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, ...)
换掉后，原 sys.stdout 失去最后一个引用 → CPython 立即 GC → TextIOWrapper.__del__
连带 close() 掉底层 buffer → 之后任何 print 抛 "I/O operation on closed file"。

被 import 时最致命：本脚本 import final_stats，final_stats 模块级又包一层，
selfcheck 自己的那层被 GC，buffer 当场关闭。

修法：
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
Python 3.7+ 内建，原地改编码，不换对象、不关 buffer，import 安全。

幂等：已改过的文件不含 TextIOWrapper，跳过。
"""
import os, re, sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))

RE_ASSIGN = re.compile(
    r'^[ \t]*sys\.stdout\s*=\s*io\.TextIOWrapper\([^\n]*\)\s*$', re.M)
RE_LOCAL = re.compile(
    r'^[ \t]*(_o|_out|_\w+)\s*=\s*io\.TextIOWrapper\([^\n]*\)\s*\n'
    r'^[ \t]*sys\.stdout\s*=\s*\1\s*$', re.M)

REPL = "sys.stdout.reconfigure(encoding='utf-8', errors='replace')"

changed = []
for fn in sorted(os.listdir(HERE)):
    if not fn.endswith('.py'):
        continue
    p = os.path.join(HERE, fn)
    src = open(p, encoding='utf-8').read()
    if 'TextIOWrapper' not in src:
        continue
    out = RE_LOCAL.sub(REPL, src)
    out = RE_ASSIGN.sub(REPL, out)
    if out != src:
        open(p, 'w', encoding='utf-8', newline='\n').write(out)
        changed.append(fn)

print('已改写 %d 个文件：' % len(changed))
for c in changed:
    print('  -', c)

# 复验：全目录不应再有 TextIOWrapper
left = [f for f in os.listdir(HERE)
        if f.endswith('.py') and 'TextIOWrapper' in open(os.path.join(HERE, f), encoding='utf-8').read()]
print('残留 TextIOWrapper：', left if left else '无')
