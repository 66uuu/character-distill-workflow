# -*- coding: utf-8 -*-
"""【模板】character_drift.py —— 出场权重统计 + 人设漂移监控（对标 dsh-character-profiler）

★ 本文件是**技能包模板**，不是项目脚本。复制到 <项目>/02_核验/ 后改用。

为什么需要它：
    七条铁律管的是"静态正确"（分母=主角台词集、引号可溯源、证据分级）。
    本脚本管"动态一致"：主角**出场是否过疏/过密**（出场权重统计），
    以及**人设关键词是否前高后崩**（漂移监控）——写进成品投喂对话后也能定期复跑，
    当"人设漂移监控"，抓"前期冷酷、后期突然圣母"这类 OOC。

纯标准库。`--selftest` 反向验证：造"秦风前段高频'冷笑'后段突变成'温柔'"的 mock，
断言能抓出冷笑衰减漂移 + 出场统计正确 + 温柔不误报。

用法：
    set DISTILL_ROOT=<D盘>\\UserFiles\\Desktop\\<项目名>_人物蒸馏
    python character_drift.py --corpus chapters.txt --name 秦风 --traits traits.json
    python character_drift.py --selftest
"""

import os
import re
import sys
import json

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))

CHAPTER_RE = re.compile(r'第[一二三四五六七八九十百千0-9]+[章回节卷]')


def split_chapters(lines):
    """按'第X章'标题切分；无标题则整体为单章。返回 [(idx, [lines])]。"""
    chapters = []
    cur = []
    ci = 0
    for ln in lines:
        if CHAPTER_RE.search(ln):
            if cur:
                chapters.append((ci, cur))
                ci += 1
                cur = []
            cur.append(ln)
        else:
            cur.append(ln)
    if cur:
        chapters.append((ci, cur))
    return chapters


def _has_name(ln, name):
    return name in ln


def _is_dialogue(ln):
    return '「' in ln or '」' in ln


def appearance_stats(lines, name):
    """出场权重统计：章节数、总提及行数、含主角对话行数、各章提及行数。"""
    chapters = split_chapters(lines)
    per_chapter = []
    total = 0
    dialogue = 0
    for _, cls in chapters:
        m = sum(1 for l in cls if _has_name(l, name))
        per_chapter.append(m)
        total += m
        dialogue += sum(1 for l in cls if _is_dialogue(l) and _has_name(l, name))
    return {
        'name': name,
        'chapters': len(chapters),
        'total_mention_lines': total,
        'dialogue_lines': dialogue,
        'per_chapter_mention_lines': per_chapter,
    }


def drift_scan(lines, name, trait_words, decay_ratio=0.5):
    """人设漂移扫描：对每个 trait 词统计前/后半段频率，
    前段高、后段骤降(<= 前段*(1-decay_ratio)) → 衰减漂移。
    返回 list of drift records。"""
    chapters = split_chapters(lines)
    n = len(chapters)
    if n < 2:
        return []
    half = n // 2
    early = [l for _, cls in chapters[:half] for l in cls]
    late = [l for _, cls in chapters[half:] for l in cls]
    records = []
    for tw in trait_words:
        e_cnt = sum(l.count(tw) for l in early)
        l_cnt = sum(l.count(tw) for l in late)
        e_norm = e_cnt / max(1, len(early))
        l_norm = l_cnt / max(1, len(late))
        if e_norm > 0 and l_norm <= e_norm * (1 - decay_ratio):
            records.append({
                'trait': tw,
                'early_rate': round(e_norm, 4),
                'late_rate': round(l_norm, 4),
                'type': '衰减漂移',
            })
    return records


def run(corpus_path, name, traits_path=None):
    lines = open(corpus_path, encoding='utf-8', errors='replace').read().splitlines()
    traits = json.load(open(traits_path, encoding='utf-8')) if traits_path else []
    st = appearance_stats(lines, name)
    dr = drift_scan(lines, name, traits) if traits else []
    print(json.dumps({'appearance': st, 'drift': dr}, ensure_ascii=False, indent=1))
    return 1 if dr else 0


# ----------------------------------------------------------------------
FIX_LINES = [
    "第一章 初遇",
    "秦风冷笑。秦风说：「滚。」",
    "秦风冷笑地看着林晚。",
    "第二章 交锋",
    "秦风冷笑。秦风：「别烦我。」",
    "第三章 转折",
    "秦风温柔。秦风说：「留下吧。」",
    "秦风温柔地笑了。",
    "第四章 结局",
    "秦风温柔。秦风温柔地牵起她的手。",
]


def selftest():
    print('=== character_drift.py 反向验证 (--selftest) ===')
    ok = True
    st = appearance_stats(FIX_LINES, '秦风')
    if st['chapters'] != 4:
        print('[FAIL] 章节数应为4 实得%d' % st['chapters']); ok = False
    if st['total_mention_lines'] != 6:
        print('[FAIL] 出场提及行数应为6 实得%d' % st['total_mention_lines']); ok = False
    if st['dialogue_lines'] != 3:
        print('[FAIL] 含主角对话行数应为3 实得%d' % st['dialogue_lines']); ok = False
    dr = drift_scan(FIX_LINES, '秦风', ['冷笑', '温柔'])
    traits = [d['trait'] for d in dr]
    if '冷笑' not in traits:
        print('[FAIL] 未抓出 冷笑 衰减漂移: %s' % dr); ok = False
    if '温柔' in traits:
        print('[FAIL] 温柔后段才高不应报衰减: %s' % dr); ok = False
    if ok:
        print('[PASS] 出场统计正确(章节4/提及6/对话3) + 冷笑前高后崩被抓、温柔不误报')
        print('   · 漂移: %s' % dr)
        return 0
    return 1


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--corpus', default=None)
    ap.add_argument('--name', default='角色')
    ap.add_argument('--traits', default=None)
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    if a.corpus:
        sys.exit(run(a.corpus, a.name, a.traits))
    print('用法: python character_drift.py --corpus x.txt --name 角色 --traits traits.json  或 --selftest')
    sys.exit(0)
