# -*- coding: utf-8 -*-
"""【模板】scan_fabrication.py —— 人物蒸馏工作流 · 全文编造句扫描器

★ 本文件是**技能包模板**，不是项目脚本。
  复制到 <项目>/02_核验/ 后改白名单，或用环境变量指定路径。

为什么必须有这个脚本：
  selfcheck 的断言 (d) 只覆盖 §9 示例区，
  但 system prompt 里**全文每一处「」引号**都是模型可能学的东西。
  秦风项目用本脚本扫出全文 174 处引号，抓出 21 条无法自动溯源的，
  最严重的是**语义反转**（原文「想让我不抓你回去」被写成「想让我帮你」）。

用法：
    set DISTILL_ROOT=<D盘>\\UserFiles\\Desktop\\<项目名>_人物蒸馏
    set DISTILL_V2=<项目>\\03_交付物\\<角色名>_数字人系统提示词_v2.md
    set DISTILL_RELIABLE=<角色名>台词_分级.json
    set DISTILL_VERIFY_DIR=<项目>\\02_核验
    python scan_fabrication.py

★ 白名单纪律：
  STRUCT   —— 格言/标签/清单类结构化内容，不要求逐字对应原文
  ARRANGED —— 编排型内容（不是原句但由原文素材合理编排），
              **每条必须注明原文出处**，否则不许加白名单
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
V2 = _env('DISTILL_V2') or os.path.join(ROOT, '03_交付物', '角色名_数字人系统提示词_v2.md')
STATS = _env('DISTILL_STATS') or os.path.join(ROOT, '02_核验', '_stats')
CHAR = _env('DISTILL_CHAR', '角色')
RELIABLE_JSON = _env('DISTILL_RELIABLE', '%s台词_分级.json' % CHAR)
VERIFY_DIR = _env('DISTILL_VERIFY_DIR') or os.path.join(ROOT, '02_核验')

sys.path.insert(0, HERE)
sys.path.insert(0, VERIFY_DIR)
sys.path.insert(0, os.path.join(ROOT, '02_核验', '_stats'))

import final_stats as FS
books = FS.load_books()
allt = '\n'.join('\n'.join(b) for _, b, _ in books)
rel = json.load(open(os.path.join(STATS, RELIABLE_JSON), encoding='utf-8'))
rel = [x for x in rel if x.get('级') in ('A', 'B', 'C+')]

md = open(V2, encoding='utf-8').read().replace('\r\n', '\n')


def nrm(s):
    return re.sub(r'[\s，。！？、；：""\'「」…—·\\-]+', '', s)


allt_n = nrm(allt)
rel_eq = set(x['台词'].strip() for x in rel)

# --- 需要按项目修改的白名单 ---

# 人工确认过的结构化内容（格言、模板、清单、标签类，不要求逐字对应原文）
STRUCT = {
    # '字段标签',
}

# 编排型内容：不是原文原句，但由原文素材合理编排而成（逐条人工确认）
# key → 理由（**必须写理由和原文出处**）
ARRANGED = {
    # '某句编排台词': '在哪一节 + 原文 pN 的出处 + 为什么这么改',
}


def traceable(q):
    """判定一个引号内容是否可溯源。返回 (是否通过, 原因)。"""
    if q in rel_eq:
        return True, '可靠集整句命中'
    if any(q in x['台词'] for x in rel):
        return True, '可靠集子串命中'
    # v3 默认严格要求引号来自目标角色可靠台词集；关闭严格模式才回退到全书命中。
    if os.environ.get('DISTILL_STRICT_SPEAKER', '1') != '1' and q in allt:
        return True, '原书原样出现（非严格模式）'
    q2 = re.sub(r'…+$', '', q).rstrip('…')
    if q2 and any(x['台词'].strip().startswith(q2) for x in rel):
        return True, '可靠集前缀命中'
    if q2 and q2 in allt:
        return True, '去省略号后原书命中'
    for cand in (nrm(q2 or q), nrm(q2 or q).replace('！？', '？')):
        if len(cand) >= 6 and cand in allt_n:
            return True, '归一化后原书命中'
    segs = [s for s in re.split(r'…+|\.{3,}', q2 or q) if len(nrm(s)) >= 6]
    if segs and all(any(nrm(sg) in allt_n for sg in [s]) for s in segs):
        return True, '省略号分段全部命中'
    # markdown 加粗标记会打断匹配 → 去掉 ** 再试
    q_nb = q.replace('**', '')
    # 嵌套引号：『…』 里的内容才是真正的台词
    inner = re.findall(r'『([^』]+)』', q_nb)
    if inner:
        q_nb = inner[-1].strip()
    if q_nb != q:
        if q_nb in rel_eq or any(q_nb in x['台词'] for x in rel) or q_nb in allt:
            return True, '去加粗/取嵌套引号后命中'
        if len(nrm(q_nb)) >= 6 and nrm(q_nb) in allt_n:
            return True, '去加粗/取嵌套引号后归一化命中'
    return False, '无法溯源'


cands = []
for m in re.finditer(r'「([^」]{2,200})」', md):
    q = m.group(1).strip()
    ln = md[:m.start()].count('\n') + 1
    cands.append((ln, q))

unmatched = []
for ln, q in cands:
    ok, why = traceable(q)
    if ok:
        continue
    if q in STRUCT:
        continue
    if q in ARRANGED:
        continue
    unmatched.append((ln, q))

print('全文「」引号总数: %d' % len(cands))
print('无法自动溯源: %d' % len(unmatched))
print('=' * 60)
for ln, q in unmatched:
    print('  行%-5d 「%s」' % (ln, q[:100]))

os.makedirs(STATS, exist_ok=True)
json.dump([{'行': ln, '引号': q} for ln, q in unmatched],
          open(os.path.join(STATS, '编造句扫描.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
print('\n报告:', os.path.join(STATS, '编造句扫描.json'))
sys.exit(0 if not unmatched else 1)
