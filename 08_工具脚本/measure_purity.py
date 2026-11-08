# -*- coding: utf-8 -*-
"""【模板】measure_purity.py —— 人物蒸馏工作流 · 污染率精确测量器

★ 本文件是**技能包模板**，不是项目脚本。
  复制到 <项目>/02_核验/ 后改 GENERIC 白名单。
  ⚠️ 必须和 extract_speech.py 放在**同一目录**（本脚本要 import 它的 collect()）。

用途：S2 的收尾——把"污染率"这个数字算准。

★ 为什么要有这个脚本：
  简单算重叠率会被**通用短句**污染——「卧槽！！」「什么！！」谁都能说，
  它们在主角和配角的台词集里都出现，导致重叠率虚高。
  本脚本用 GENERIC 白名单把这些通用短句排除，再算真实污染率。

★ ★ 铁律：对照组必须用**和主角完全同一套 collect() 规则**跑。
  宽松做法（"任意行含名字就算"）会让重叠率虚高好几倍：
    宽松版 → 26.59%
    同规则版 → 4.09%
  所以本脚本直接 import extract_speech 的 collect()，不重复实现。

★ 两个数字必须一起给（缺一不可）：
  1. **真污染率**（本脚本算的，自动）= 对照组与主角可靠集的重叠率（排除通用短句 + 长度≥4）
  2. **人工抽检准确率**（人抽 30–40 条核对）

用法：
    set DISTILL_ROOT=...
    set DISTILL_STATS=<项目>\\02_核验\\_stats
    set DISTILL_CHAR=<角色名>
    set DISTILL_CONTRAST=配角1,配角2,配角3
    python measure_purity.py
    → 输出 _stats/污染率测量.json

⚠️ 不要把 stdout 写成 `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, ...)`。
   本脚本只用 sys.stdout.reconfigure()。
"""
import importlib.util
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.environ.get('DISTILL_ROOT') or os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
STATS = os.environ.get('DISTILL_STATS') or os.path.join(ROOT, '02_核验', '_stats')
CHAR = os.environ.get('DISTILL_CHAR', '角色名')
RELIABLE_JSON = os.environ.get('DISTILL_RELIABLE', '%s台词_分级.json' % CHAR)
CONTRAST = [x for x in (os.environ.get('DISTILL_CONTRAST') or '').split(',') if x]

# 通用短句白名单：这些谁都能说，不算污染
GENERIC = {
    '卧槽', '卧槽！！', '什么', '什么！！', '什么！？', '哼', '哼！', '这……',
    '是啊', '是啊！', '哦？', '嗯！？', '好家伙', '好家伙！', '阿这！！',
    '哈哈哈', '什么情况！？', '闭嘴', '闭嘴！', '住口', '住口！', '滚', '滚！',
    '不行', '不行！', '我！？', '哎', '是', '是！', '好', '好！', '对', '对！',
    '不必', '不必！', '放肆', '放肆！', '大胆', '大胆！', '狂妄', '狂妄！',
    '不可能', '不可能！', '放屁', '放屁！', '神经病', '有病', '滚开',
}

# 重叠台词的最小长度（太短的多半是通用短语）
MIN_LEN = 4

OUTPATH = os.path.join(STATS, '污染率测量.json')


def load_extract_module():
    """import 同目录的 extract_speech.py，复用它的 collect() 与 load_books()。"""
    es_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'extract_speech.py')
    if not os.path.exists(es_path):
        return None, None
    spec = importlib.util.spec_from_file_location('es', es_path)
    es = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(es)
    return es, es.load_books()


def main():
    p = os.path.join(STATS, RELIABLE_JSON)
    if not os.path.exists(p):
        print('!! 找不到分级 JSON:', p, '（先跑 extract_speech.py）')
        return 1
    d = json.load(open(p, encoding='utf-8'))
    rel = [x for x in d if x.get('级') in ('A', 'B', 'C+')]
    if not rel:
        print('!! 可靠集为空')
        return 1

    res = {'可靠集条数': len(rel)}
    res['唯一台词数'] = len(set(x['台词'].strip() for x in rel))

    # 通用短句占比（角色辨识度反向指标）
    gen_in_main = [x for x in rel if x['台词'].strip() in GENERIC]
    res['通用短句条数'] = len(gen_in_main)
    res['通用短句占比%'] = round(len(gen_in_main) / len(rel) * 100, 2)

    es, books = load_extract_module()
    if es is None:
        print('!! 找不到 extract_speech.py（必须同目录，污染率测量依赖它的 collect()）')
        return 1

    def collect_for(name):
        """复用与主角完全一致的 collect() 规则。"""
        out = set()
        for t, q, g, ctx in es.collect(books, name):
            out.add(q.strip())
        return out

    qset = set(x['台词'].strip() for x in rel)
    allother = set()
    overlap_detail = {}
    for c in CONTRAST:
        if c == CHAR:
            continue
        cq = collect_for(c)
        allother |= cq
        ov = len(qset & set(q for q in cq if q not in GENERIC and len(q) >= MIN_LEN))
        overlap_detail[c] = {'对照组唯一台词数': len(cq), '与主角重叠(排通用短句)': ov}
        print('%-12s 唯一台词 %4d 条 | 与主角重叠 %d 条' % (c, len(cq), ov))

    overlap = qset & allother
    real_overlap = {x for x in overlap if x not in GENERIC and len(x) >= MIN_LEN}
    res['对照组'] = overlap_detail
    res['重叠总数'] = len(overlap)
    res['重叠_剔除通用短句后'] = len(real_overlap)
    res['重叠样例_真污染'] = sorted(real_overlap)[:40]
    res['重叠样例_通用'] = sorted(overlap - real_overlap)[:20]
    res['真污染率%'] = round(len(real_overlap) / len(qset) * 100, 2) if qset else 0
    res['_口径'] = ('对照组用与主角同一套 collect() 规则；重叠台词需长度≥%d 且非通用短句；'
                    '分母=主角可靠集唯一台词' % MIN_LEN)
    res['_注'] = '还需人工抽检 30–40 条给准确率，两个数一起给'

    os.makedirs(STATS, exist_ok=True)
    json.dump(res, open(OUTPATH, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    print('\n=== 污染率测量 ===')
    print('可靠集 %d 条 / 唯一台词 %d 条' % (res['可靠集条数'], res['唯一台词数']))
    print('通用短句 %d 条（占 %.2f%%）' % (res['通用短句条数'], res['通用短句占比%']))
    print('重叠总数 %d → 剔除通用短句后 %d' % (res['重叠总数'], res['重叠_剔除通用短句后']))
    print('真污染率: %s%%' % res['真污染率%'])
    print('\n写入:', OUTPATH)
    print('★ 还要人工抽检 30–40 条给准确率，两个数一起给。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
