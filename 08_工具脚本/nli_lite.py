# -*- coding: utf-8 -*-
"""【模板】nli_lite.py —— 离线语义矛盾预筛（对标 selfcheckgpt NLI variant 的离线版）

★ 本文件是**技能包模板**，不是项目脚本。复制到 <项目>/02_核验/ 后改用。

为什么需要它：
    semantic_check.py 的 LLM / NLI 后端要模型或 API（本机没有、且烧积分）。
    本脚本用**纯词典**做"否定翻转 / 反义对立"检测，作为 semantic_check 的
    **离线预筛**：不调模型就能先抓出一批明确极性反转的断言，把"要调模型的"压到最小。

纯标准库。`--selftest` 反向验证：明确矛盾(反义/否定)能抓，中性对不误报。

用法：
    set DISTILL_ROOT=<D盘>\\UserFiles\\Desktop\\<项目名>_人物蒸馏
    python nli_lite.py --pairs pairs.json        # pairs: [{"claim":..,"evidence":..}]
    python nli_lite.py --selftest
"""

import os
import re
import sys
import json

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))

# 否定标记（含于 claim 即视为"否定翻转"候选）
NEG = ['没有', '不愿', '不想', '不让', '不', '没', '无', '非', '未', '别', '勿']

# 反义对立词表（a / b 互为相反；claim 含 a 且 evidence 含 b 即矛盾，反之亦然）
ANTI = [
    ('帮', '害'), ('好', '坏'), ('善', '恶'), ('生', '死'), ('爱', '恨'),
    ('真', '假'), ('正派', '反派'), ('冷', '暖'), ('喜', '悲'), ('赢', '输'),
    ('对', '错'), ('是', '否'), ('来', '走'), ('开', '关'), ('上', '下'),
    ('进', '退'), ('得', '失'), ('成', '败'), ('信', '疑'), ('笑', '哭'),
]

DEFAULT_NAMES = ['秦风', '林晚']


def _clean(text, names):
    t = text
    for n in names:
        t = t.replace(n, '')
    t = re.sub(r'[，。、！？；：“”‘’\s「」【】\-—\.\,\!\?\;\:\(\)]', '', t)
    return t


def contradicts(claim, evidence, names=None):
    """返回 (bool_矛盾, reason)。纯词典启发式，离线可用。

    两类矛盾：
      1) 反义对立：claim 与 evidence 各含一对反义词（同主语前提由上游保证）。
      2) 否定翻转：claim 含否定词，去掉否定+人名后的核心谓语仍出现在 evidence 中
         → 说明证据是肯定、断言是否定，极性反转。
    """
    names = names or DEFAULT_NAMES
    # 1) 反义对立
    for a, b in ANTI:
        if a in claim and b in evidence:
            return True, '反义对立: %s/%s' % (a, b)
        if b in claim and a in evidence:
            return True, '反义对立: %s/%s' % (a, b)
    # 2) 否定翻转
    for neg in NEG:
        if neg in claim:
            core = _clean(claim.replace(neg, ''), names)
            if core:
                ev_clean = _clean(evidence, names)
                if core in ev_clean:
                    return True, '否定翻转: 删"%s"后核心"%s"仍与证据同向' % (neg, core)
    return False, ''


def load_pairs(path):
    data = json.load(open(path, encoding='utf-8'))
    if isinstance(data, dict):
        data = data.get('pairs', [])
    return data


def run(pairs_path):
    pairs = load_pairs(pairs_path)
    hits = []
    for i, p in enumerate(pairs):
        c = p.get('claim', '')
        e = p.get('evidence', '')
        ok, reason = contradicts(c, e)
        if ok:
            hits.append({'idx': i, 'claim': c, 'evidence': e, 'reason': reason})
    report = {'total': len(pairs), 'contradictions': len(hits), 'hits': hits}
    print(json.dumps(report, ensure_ascii=False, indent=1))
    # 有矛盾→退出 1 提示人工复核（像语义层一样是"待复核线索"不是判决）
    return 1 if hits else 0


# ----------------------------------------------------------------------
CASES = [
    ("秦风帮了林晚。", "秦风害了林晚。", True, '反义对立'),
    ("秦风没有帮林晚。", "秦风帮了林晚。", True, '否定翻转'),
    ("秦风是好人。", "秦风是坏人。", True, '反义对立'),
    ("秦风笑了。", "秦风冷笑。", False, '中性不误报'),
]


def selftest():
    print('=== nli_lite.py 反向验证 (--selftest) ===')
    ok = True
    for claim, ev, expect, label in CASES:
        got, reason = contradicts(claim, ev)
        if got != expect:
            ok = False
            print('[FAIL] %s: 期望%s 实得%s (%s)' % (label, expect, got, reason))
        else:
            print('  · %s → %s  %s' % (label, got, reason))
    if ok:
        print('[PASS] 明确矛盾(反义/否定)能抓，中性对不误报')
        return 0
    return 1


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--pairs', default=None)
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    if a.pairs:
        sys.exit(run(a.pairs))
    print('用法: python nli_lite.py --pairs x.json  或  python nli_lite.py --selftest')
    sys.exit(0)
