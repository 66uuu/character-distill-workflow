# -*- coding: utf-8 -*-
"""【模板】verify_citations.py —— 人物蒸馏工作流 · 引用回原文定位器

用途：核验系统提示词里每一条【直引·第N章】「引文」是否真的出现在原书第 N 章。

★ 本文件是**技能包模板**，不是项目脚本。
  用法：复制到 <项目>/02_核验/ 后再改，或用环境变量指定路径：

    set DISTILL_ROOT=<D盘>\\UserFiles\\Desktop\\<项目名>_人物蒸馏
    set DISTILL_SRC=<项目>\\01_语料\\chapters
    set DISTILL_V2=<项目>\\03_交付物\\<角色名>_数字人系统提示词_v2.md
    set DISTILL_STATS=<项目>\\02_核验\\_stats
    set DISTILL_CHAR=<角色名>          # 用于统计文件名
    set DISTILL_CHAPTERS=2085          # 用于报告里写章数
    set DISTILL_VER=v2

  然后：python verify_citations.py

核验原理（滑窗指纹法）：
  1. 按【】块解析文档
  2. 取该块内、第N章标记**之后**、下一个标记**之前**的第一个引号
  3. 归一化（去标点空白）后取长度-10 连续子串为指纹
  4. 在标注章内命中率 ≥34% 记通过；否则全书扫描定位真实出处

为什么用滑窗不用精确匹配：原文常有省略号、多字、错字、标点差异。

⚠️ 不要把 stdout 写成 `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, ...)`，
   那样被 import 时会关掉底层 buffer 导致后续 print 全炸。
   本脚本只用 sys.stdout.reconfigure()。
"""
import os
import re
import sys
import json

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))


def _env(name, default=None):
    return os.environ.get(name) or default


ROOT = _env('DISTILL_ROOT') or os.path.abspath(os.path.join(HERE, '..', '..'))
SRC = _env('DISTILL_SRC') or os.path.join(ROOT, '01_语料', 'chapters')
V2 = _env('DISTILL_V2') or os.path.join(ROOT, '03_交付物', '角色名_数字人系统提示词_v2.md')
OUT = _env('DISTILL_STATS') or os.path.join(ROOT, '02_核验', '_stats')
CHAR = _env('DISTILL_CHAR', '角色')
CHAPTERS = _env('DISTILL_CHAPTERS', 'N')
VER = _env('DISTILL_VER', 'v2')

BLOCK = re.compile(r'【([^】]*)】')
MARK = re.compile(r'第\s*(\d+)\s*章')
QUOTE = re.compile(r'[「"]([^」"]{4,300})[」"]')
EDGE = re.compile(r"[\s，。！？、；：\"'「」…—·\\-]+")


def load_books():
    """读 01_语料/chapters/p*.txt → {章号: (标题, 正文)}。"""
    res = {}
    if not os.path.isdir(SRC):
        print('!! 找不到语料目录:', SRC)
        return res
    fns = [f for f in os.listdir(SRC) if f.endswith('.txt')]
    fns.sort(key=lambda x: int(re.match(r'p(\d+)\.txt', x).group(1))
             if re.match(r'p(\d+)\.txt', x) else 0)
    for fn in fns:
        m = re.match(r'p(\d+)\.txt', fn)
        if not m:
            continue
        raw = open(os.path.join(SRC, fn), encoding='utf-8', errors='replace').read()
        lines = [l.strip() for l in raw.split('\n') if l.strip()]
        res[int(m.group(1))] = (lines[0] if lines else fn, '\n'.join(lines))
    return res


def parse_items(md):
    """从文档里抽出所有【…第N章…「引文」】配对。"""
    items = []
    for bm in BLOCK.finditer(md):
        inner = bm.group(1)
        if '第' not in inner:
            continue
        marks = [(m.start(), int(m.group(1))) for m in MARK.finditer(inner)]
        if not marks:
            continue
        quotes = [(q.start(), q.group(1)) for q in QUOTE.finditer(inner)]
        for i, (mp, chap) in enumerate(marks):
            limit = marks[i + 1][0] if i + 1 < len(marks) else len(inner)
            cand = [q for q in quotes if mp < q[0] < limit]
            if not cand:
                continue
            items.append({'chap': chap, 'quote': cand[0][1],
                          'block': bm.group(1)[:110].replace('\n', ' ')})
    return items


def norm(s):
    return EDGE.sub('', s)


def windows(s, w=10):
    # 先按省略号切段（norm 会把「…」当标点抹掉，所以必须先切）
    segs = [x for x in re.split(r'…+|\.{3,}', s) if x.strip()]
    frs = []
    for seg in segs:
        t = norm(seg)
        if len(t) < w:
            if t:
                frs.append(t)
            continue
        frs.extend(t[i:i + w] for i in range(len(t) - w + 1))
    return frs


def hit_rate(chap_text, quote):
    frs = windows(quote)
    if not frs:
        return 0.0
    hit = sum(1 for f in frs if f in chap_text)
    return hit / len(frs)


def run(md=None, quiet=False):
    """核验文档里的全部直引。返回 (通过数, 总数, 问题列表)。"""
    if md is None:
        md = open(V2, encoding='utf-8').read().replace('\r\n', '\n')
    books = load_books()
    nb = {pid: norm(txt) for pid, (_, txt) in books.items()}
    items = parse_items(md)
    ok, bad_list = 0, []
    for it in items:
        chap, q = it['chap'], it['quote']
        if hit_rate(nb.get(chap, ''), q) >= 0.34:
            ok += 1
            continue
        real = [pid for pid, t in nb.items() if hit_rate(t, q) >= 0.34][:5]
        bad_list.append({'chap': chap, 'quote': q[:60], 'real': real})
    if not quiet:
        print('直引核验 %d/%d 通过' % (ok, len(items)))
    return ok, len(items), bad_list


def main():
    books = load_books()
    if not books:
        print('语料为空，检查 DISTILL_SRC 路径')
        return 1
    nb = {pid: norm(txt) for pid, (_, txt) in books.items()}
    md = open(V2, encoding='utf-8').read().replace('\r\n', '\n')

    items = parse_items(md)
    print('【】块内可配对引用 %d 条' % len(items))

    report = []
    ok = mism = nf = 0
    for it in items:
        chap, q = it['chap'], it['quote']
        rate = hit_rate(nb.get(chap, ''), q)
        if rate >= 0.34:
            ok += 1
            report.append({**it, 'status': 'OK', 'real': [chap], 'rate': round(rate, 2)})
            continue
        real = [pid for pid, t in nb.items() if hit_rate(t, q) >= 0.34][:5]
        if real:
            mism += 1
            report.append({**it, 'status': '章号不符', 'real': real, 'rate': round(rate, 2)})
        else:
            nf += 1
            report.append({**it, 'status': '未找到原文', 'real': [], 'rate': round(rate, 2)})

    print('✅ 章号正确 %d | ⚠️ 章号不符 %d | ❌ 未找到 %d' % (ok, mism, nf))

    os.makedirs(OUT, exist_ok=True)
    json.dump(report, open(os.path.join(OUT, '%s引用核验.json' % VER), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)

    L = []
    A = L.append
    A('# %s %s · 引用核验报告' % (CHAR, VER))
    A('')
    A('> 核验方式：按【…】块解析文档，取每个「第N章」标记之后、下一个标记之前的第一个引号，')
    A('> 以归一化后的长度-10 滑窗子串为指纹，在标注章内命中率 ≥34%% 记为通过；')
    A('> 未通过则全书 %s 章扫描定位真实出处。' % CHAPTERS)
    A('')
    A('| 统计 | 数量 |')
    A('|---|---|')
    A('| ✅ 标注章号与原文一致 | %d |' % ok)
    A('| ⚠️ 章号不符 | %d |' % mism)
    A('| ❌ 未能在原书定位 | %d |' % nf)
    A('')
    if mism or nf:
        A('## 需要修正的条目')
        A('')
        A('| 标注章 | 引用片段 | 状态 | 实际所在章 |')
        A('|---|---|---|---|')
        for r in report:
            if r['status'] != 'OK':
                A('| 第%s章 | %s | %s | %s |' % (
                    r['chap'], r['quote'][:44].replace('|', '丨'), r['status'],
                    ', '.join(str(x) for x in r['real']) or '全书未定位'))
        A('')
    open(os.path.join(OUT, '%s引用核验报告.md' % VER), 'w', encoding='utf-8').write('\n'.join(L))
    print('报告:', os.path.join(OUT, '%s引用核验报告.md' % VER))
    return 0 if (mism == 0 and nf == 0) else 1


if __name__ == '__main__':
    sys.exit(main())
