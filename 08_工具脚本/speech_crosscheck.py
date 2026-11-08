# -*- coding: utf-8 -*-
"""【模板】speech_crosscheck.py —— S2 台词归属第二口径（对标 speaker-recognition 离线口径）

★ 本文件是**技能包模板**，不是项目脚本。复制到 <项目>/02_核验/ 后改用。

为什么需要它：
    extract_speech.py 用规则做 A/B/C 分级 + 对照组。本脚本提供**第二套独立口径**
    （倒装/冠名启发式），和它交叉验证，暴露规则归属的**噪声下限**：
    两套口径不一致的台词 = "不确定区"，必须人工抽检，否则污染率数字不可信。
    （思路对标 speaker-recognition-in-literature 的"第二归属器" + castglean_bypass 的离线双口径。）

纯标准库。`--selftest` 反向验证：能正确归属倒装句、并标记真正不确定的句。

用法：
    set DISTILL_ROOT=<D盘>\\UserFiles\\Desktop\\<项目名>_人物蒸馏
    set DISTILL_SRC=<项目>\\01_语料\\chapters
    set DISTILL_STATS=<项目>\\02_核验\\_stats
    set DISTILL_SPEECH_JSON=<项目>\\02_核验\\<角色>台词_分级.json   # 第一口径(可选)
    python speech_crosscheck.py
    python speech_crosscheck.py --selftest
"""
import os
import re
import sys
import json
import tempfile

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))


def _env(name, default=None):
    return os.environ.get(name) or default


ROOT = _env('DISTILL_ROOT') or os.path.abspath(os.path.join(HERE, '..', '..'))
SRC = _env('DISTILL_SRC') or os.path.join(ROOT, '01_语料', 'chapters')
STATS = _env('DISTILL_STATS') or os.path.join(ROOT, '02_核验', '_stats')
CHAR = _env('DISTILL_CHAR', '角色')
SPEECH_JSON = _env('DISTILL_SPEECH_JSON')  # 第一口径(extract_speech 产物)

NAME_RE = re.compile(r'^([一-龥A-Za-z]{1,8})[：:]')
NAME_ONLY_RE = re.compile(r'^([一-龥A-Za-z]{1,6})')
EXPLICIT_RE = re.compile(r'「([^」]{1,80})」\s*([一-龥]{1,6}?)(说|道|问|答|喊|骂|笑|回)')
INVERT_RE = re.compile(r'「([^」]{1,80})」')


def attr_heuristic(lines):
    """返回 [(idx, speaker, method)]。speaker=None 表示不确定(unassigned)。

    三种归属口径（按优先级）：
      explicit —— 「quote」名字 说/道…
      invert   —— 本行有「quote」且下一行**以已知名字开头**（倒装句式："台词" 换行 名字冷笑）
      leading  —— 行首 名字：
    其余（无引号、无冠名）一律 unassigned（叙述/不确定），不向后 carry，
    避免把叙事行误归因成上一说话人。

    关键修复：倒装口径不再贪婪抓取下一整行（会把"秦风冷笑"整段当名字），
    而是先收集语料中**已出现的名字集合**，倒装时按最长前缀匹配，
    既能正确取到"秦风/林晚"，又不会被动词（冷笑/转身）污染。
    """
    raw = [ln.strip() for ln in lines]
    # 第一遍：收集候选名字（显式/冠名口径都记下来，作为倒装前缀匹配的字典）
    name_set = set()
    for ln in raw:
        m = EXPLICIT_RE.search(ln)
        if m and m.group(2):
            name_set.add(m.group(2))
        nm = NAME_RE.match(ln)
        if nm and any(k in ln for k in ('说', '道', '问', '：', ':')):
            name_set.add(nm.group(1))
    candidates = sorted(name_set, key=len, reverse=True)  # 最长优先，避免"锋"抢"欧阳锋"

    res = []
    for i, ln in enumerate(raw):
        sp = None
        mt = None
        if sp is None and INVERT_RE.search(ln) and i + 1 < len(raw):
            nxt = raw[i + 1]
            hit = None
            for cand in candidates:  # 已知名字最长前缀匹配
                if nxt.startswith(cand):
                    hit = cand
                    break
            if hit is None:  # 兜底：未见过的名字，贪心取前 1~4 字
                nm = NAME_ONLY_RE.match(nxt)
                if nm:
                    hit = nm.group(1)
            if hit:
                sp, mt = hit, 'invert'
        if sp is None:
            m = EXPLICIT_RE.search(ln)
            if m:
                sp, mt = m.group(2), 'explicit'
        if sp is None:
            nm = NAME_RE.match(ln)
            if nm and any(k in ln for k in ('说', '道', '问', '：', ':')):
                sp, mt = nm.group(1), 'leading'
        if sp is None:
            mt = 'unassigned'
        res.append((i, sp, mt))
    return res


QUOTE_MAP = {'“': '「', '”': '」', '‘': '「', '’': '」'}


def normalize_quotes(s):
    """把 “”‘’ 统一成「」，否则启发式在起点/番茄语料上一句都匹配不到。"""
    for a, b in QUOTE_MAP.items():
        s = s.replace(a, b)
    return s


def load_corpus_lines():
    lines = []
    if os.path.isdir(SRC):
        for fn in sorted(os.listdir(SRC)):
            if fn.lower().endswith('.txt'):
                try:
                    lines += open(os.path.join(SRC, fn),
                                  encoding='utf-8', errors='replace').read().splitlines()
                except Exception:
                    pass
    return lines


def run():
    lines = load_corpus_lines()
    if not lines:
        print('[WARN] 未找到语料（DISTILL_SRC=%s）。' % SRC)
        return 0
    # 语料引号常是 “”（起点/番茄），启发式只认「」——先归一化再归属。
    norm_lines = [normalize_quotes(ln) for ln in lines]
    res = attr_heuristic(norm_lines)
    # 分母只算**含引号的台词行**：原先把整本正文（含叙述行）都算进分母，
    # 导致 unassigned 恒在 97% 左右、退出码永远是 1，指标就没意义了。
    # 倒装口径依赖"下一行"是谁，所以 attr_heuristic 必须吃全文，只在统计时筛。
    dlg = set(i for i, ln in enumerate(norm_lines) if '「' in ln or '」' in ln)
    res = [(i, sp, mt) for i, sp, mt in res if i in dlg]
    methods = {}
    for _, sp, mt in res:
        methods[mt] = methods.get(mt, 0) + 1
    report = {
        'total_lines': len(res),
        'attributed': sum(v for k, v in methods.items() if k != 'unassigned'),
        'unassigned': methods.get('unassigned', 0),
        'by_method': methods,
    }
    # 与第一口径交叉（若有）
    if SPEECH_JSON and os.path.exists(SPEECH_JSON):
        try:
            gold = json.load(open(SPEECH_JSON, encoding='utf-8'))
            # gold: list of {text, speaker, 级}
            agree = disagree = 0
            for g in gold:
                for idx, sp, _ in res:
                    if g.get('text') and g['text'] in lines[idx] if idx < len(lines) else False:
                        if sp == g.get('speaker'):
                            agree += 1
                        else:
                            disagree += 1
                        break
            report['crosscheck'] = {'agree': agree, 'disagree': disagree,
                                   'disagree_rate': round(disagree / (agree + disagree), 3)
                                   if (agree + disagree) else None}
        except Exception as e:
            print('[WARN] 第一口径 JSON 读取失败: %s' % e)
    try:
        os.makedirs(STATS, exist_ok=True)
        out = os.path.join(STATS, 'speech_crosscheck.json')
        json.dump(report, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    except Exception as e:  # noqa: BLE001
        out = os.path.join(tempfile.gettempdir(), '蒸馏speech_crosscheck_%s.json' % CHAR)
        json.dump(report, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('[WARN] 默认目录不可写，报告降级到: %s (%s)' % (out, e))
    print('=' * 50)
    print('S2 台词归属第二口径（交叉验证）')
    print('语料行数: %d  已归属: %d  不确定(unassigned): %d'
          % (report['total_lines'], report['attributed'], report['unassigned']))
    print('口径分布: %s' % methods)
    if 'crosscheck' in report:
        print('与第一口径交叉: 一致 %d / 冲突 %d / 冲突率 %s'
              % (report['crosscheck']['agree'], report['crosscheck']['disagree'],
                 report['crosscheck']['disagree_rate']))
    print('=' * 50)
    print('报告:', out)
    # 诊断工具：不确定率>阈值时退出 1 提示人工抽检
    if report['unassigned'] > report['total_lines'] * 0.5:
        return 1
    return 0


# ----------------------------------------------------------------------
FIX = [
    "「你走吧。」秦风说道。",
    "「我不会帮你的。」",
    "秦风冷笑。",
    "林晚：「你凭什么？」",
    "「这笔账我们慢慢算。」",
    "林晚转身离开。",
    "风把门吹开了。",
]


def selftest():
    print('=== speech_crosscheck.py 反向验证 (--selftest) ===')
    res = attr_heuristic(FIX)
    by_idx = {i: (sp, mt) for i, sp, mt in res}
    ok = True
    # line0 显式 → 秦风
    if by_idx[0] != ('秦风', 'explicit'):
        print('[FAIL] 显式归属失败: %s' % (by_idx[0],)); ok = False
    # line1 倒装 → 下一行"秦风冷笑" → 秦风 invert
    if by_idx[1] != ('秦风', 'invert'):
        print('[FAIL] 倒装归属失败: %s' % (by_idx[1],)); ok = False
    # line3 冠名 → 林晚
    if by_idx[3] != ('林晚', 'leading'):
        print('[FAIL] 冠名归属失败: %s' % (by_idx[3],)); ok = False
    # line4 倒装 → 下一行"林晚转身" → 林晚 invert
    if by_idx[4] != ('林晚', 'invert'):
        print('[FAIL] 倒装归属2失败: %s' % (by_idx[4],)); ok = False
    # line6 无引号无冠名 → 不确定
    if by_idx[6][0] is not None:
        print('[FAIL] 真不确定句应标 unassigned: %s' % (by_idx[6],)); ok = False
    if ok:
        print('[PASS] 显式/倒装/冠名均正确归属，真不确定句标记 unassigned')
        for i, (sp, mt) in sorted(by_idx.items()):
            print('   · 行%-2d %-8s %s' % (i, mt, sp))
        return 0
    return 1


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()
    sys.exit(selftest() if a.selftest else run())
