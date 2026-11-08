# -*- coding: utf-8 -*-
"""【模板】selfcheck.py —— 人物蒸馏工作流 · 自检器

★ 本文件是**技能包模板**，不是项目脚本。
  复制到 <项目>/02_核验/ 后改下面几个常量，或用环境变量指定路径。

用法：
    cd <项目根>/02_核验 && python selfcheck.py

改这几处：
  ROOT / V2 / STATS / SRC / VERIFY_DIR  —— 路径（环境变量可覆盖）
  COUNT_CLAIMS        —— §4.6「次数」列 → (完整台词, 声称次数)
  FULL_CHAP_CLAIMS    —— §4.6「全书 N 章」→ (完整台词, 声称章数)
  ALLOW               —— §9 编排型台词白名单
  STAT_CHECKS         —— 数字对账项
  CHAPTER_MAX         —— 一级章节号上限
  SECTION_ORDER       —— 是否检查二级编号顺序

★ 断言口径铁律：写断言前**先确认文档自身用的口径**。
  三个口径差 8 倍：整句相等 / 子串包含 / 全书章数。
  秦风项目曾因口径写错报出 19 条**假失真**——文档本来是对的，是验证器错了。
  报出大量失真时，先怀疑验证器。

⚠️ 不要把 stdout 写成 `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, ...)`，
   那样被 import 时会关掉底层 buffer 导致后续 print 全炸。
   本脚本只用 sys.stdout.reconfigure()。
"""
import os
import re
import sys
import json
from collections import Counter

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))


def _env(name, default=None):
    return os.environ.get(name) or default


ROOT = _env('DISTILL_ROOT') or os.path.abspath(os.path.join(HERE, '..', '..'))
V2 = _env('DISTILL_V2') or os.path.join(ROOT, '03_交付物', '角色名_数字人系统提示词_v2.md')
STATS = _env('DISTILL_STATS') or os.path.join(ROOT, '02_核验', '_stats')
CHAR = _env('DISTILL_CHAR', '角色')
VER = _env('DISTILL_VER', 'v2')
# 台词分级 JSON 的文件名（放在 _stats/ 下）
RELIABLE_JSON = _env('DISTILL_RELIABLE', '%s台词_分级.json' % CHAR)
# final_stats.py 所在目录（提供 load_books()）
VERIFY_DIR = _env('DISTILL_VERIFY_DIR') or os.path.join(ROOT, '02_核验')

sys.path.insert(0, VERIFY_DIR)
sys.path.insert(0, os.path.join(ROOT, '02_核验', '_stats'))
sys.path.insert(0, HERE)

# --- 需要按项目修改的断言清单 ---

# §4.6 表「次数」列 → (完整台词, 声称次数)
# 口径：可靠集 ABC+ 中「整句相等」的条数
COUNT_CLAIMS = [
    # ('某句台词', 次数),
]

# §4.6 表里带「全书 N 章」标注的行 → (完整台词, 声称章数)
FULL_CHAP_CLAIMS = [
    # ('某句台词', 章数),
]

# §9 里「编排型」台词白名单：不是原文原句，但是对原文真实短句的合规编排。
# 每条都必须在可靠集或原文中能找到对应素材，否则算编造。
ALLOW = {
    # '某句编排台词',
}

# 数字对账：(显示名, 文档里应出现的串, 权威 JSON 里的取数函数)
# 权威 JSON 由 <项目>/02_核验/audit_authoritative.py 生成
STAT_CHECKS = [
    # ('可靠集条数', '5039', lambda st: st['语料']['可靠集条数']),
]

# 旧版错误数字黑名单（命中即报）
OLD_NUM = []

# 占位符
PLACEHOLDER = ['TODO', 'XXX', '待补', 'TBD', '待定', '占位']

# AI 腔禁用词（§4.9 禁用词表 + §10 OOC 清单所在行要豁免）
BAN = ['综上所述', '值得注意的是', '星辰大海', '岁月静好', 'yyds', '破防了',
       '嘴角勾起一抹弧度', '深邃的眼眸']

# 一级章节号 0..N
CHAPTER_MAX = 14

# 是否检查二级编号顺序（防 5.6 排在 5.5 前）
SECTION_ORDER = True


def load():
    """返回 (全书文本, {章号: 正文}, 可靠集台词列表)。"""
    import final_stats as FS
    books = FS.load_books()
    allt = '\n'.join('\n'.join(b) for _, b, _ in books)
    ch = {i: '\n'.join(b) for i, (_, b, _) in enumerate(books, 1)}
    rel = json.load(open(os.path.join(STATS, RELIABLE_JSON), encoding='utf-8'))
    rel = [x for x in rel if x.get('级') in ('A', 'B', 'C+')]
    return allt, ch, rel


def nrm(s):
    return re.sub(r'[\s，。！？、；：""\'「」…—·\\-]+', '', s)


def main():
    md = open(V2, encoding='utf-8').read().replace('\r\n', '\n')
    lines = md.split('\n')
    issues = []

    # ---------- 1. 【】配对 + 标注统计 ----------
    n_stat = md.count('【统计')
    n_direct = md.count('【直引')
    n_infer = md.count('【推断')
    n_plain = len(re.findall(r'【[^】]*】', md))
    print('【统计】%d  【直引】%d  【推断】%d  【】块总数 %d' % (n_stat, n_direct, n_infer, n_plain))
    if md.count('【') != md.count('】'):
        issues.append('【】不配对: %d vs %d' % (md.count('【'), md.count('】')))

    # ---------- 2. 章节编号 + 顺序 ----------
    secs = re.findall(r'^#{2,3} (\d+)(?:\.(\d+))?\.? ', md, re.M)
    top = [int(a) for a, b in secs if not b]
    sub = [(int(a), b) for a, b in secs if b]
    print('一级章节:', top)
    missing = [i for i in range(0, CHAPTER_MAX + 1) if i not in top]
    if missing:
        issues.append('缺失章节号: %s' % missing)
    dup = [k for k, v in Counter(top).items() if v > 1 and k != 0]
    if dup:
        issues.append('重复章节号: %s' % dup)
    for a in sorted(set(x[0] for x in sub)):
        if a == 0:
            continue                      # §0.5 / §0.6 是特例，豁免
        subs = sorted(int(b) for x, b in sub if x == a)
        exp = list(range(1, len(subs) + 1))
        if subs != exp:
            issues.append('§%d 二级编号不连续: %s (应为 %s)' % (a, subs, exp))
    if SECTION_ORDER:
        order = [(int(a), int(b)) for a, b in secs if b]
        for i in range(1, len(order)):
            if order[i][0] == order[i - 1][0] and order[i][1] < order[i - 1][1]:
                issues.append('§%d.%d 出现在 §%d.%d 之后（顺序错乱）' %
                              (order[i][0], order[i][1], order[i - 1][0], order[i - 1][1]))

    # ---------- 3. 表格列数一致 ----------
    tbl_bad = []
    i = 0
    while i < len(lines):
        if lines[i].strip().startswith('|') and i + 1 < len(lines) and \
                re.match(r'^\|[\s\-:|]+\|$', lines[i + 1].strip()):
            ncol = len(lines[i].strip().strip('|').split('|'))
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith('|'):
                cols = len(lines[j].strip().strip('|').split('|'))
                if cols != ncol:
                    tbl_bad.append((j + 1, ncol, cols, lines[j][:60]))
                j += 1
            i = j
        else:
            i += 1
    print('表格列数不一致行数:', len(tbl_bad))
    for b in tbl_bad[:10]:
        issues.append('表格列数不一致 行%d: 表头%d列 / 实际%d列 | %s' % b)

    # ---------- 4. 旧数字残留 ----------
    n_old = 0
    for k in OLD_NUM:
        for m in re.finditer(re.escape(k), md):
            n_old += 1
            issues.append('旧数字残留 行%d: 「%s」' % (md[:m.start()].count('\n') + 1, k))
    print('旧数字残留:', n_old)

    # ---------- 5. 占位符 ----------
    for k in PLACEHOLDER:
        for m in re.finditer(re.escape(k), md):
            issues.append('占位符 行%d: 「%s」' % (md[:m.start()].count('\n') + 1, k))

    # ---------- 6. 禁用词自打脸（§4.9 / §10 所在行豁免）----------
    ban_lines = set()
    for anchor in ('### 4.9 禁用词表', '## 10. OOC 负面清单', '## 4.9 禁用词表', '## 10. OOC'):
        m49 = md.find(anchor)
        if m49 > 0:
            end = md.find('\n#', m49 + 10)
            for i2 in range(m49, end if end > 0 else len(md)):
                ban_lines.add(md[:i2].count('\n') + 1)
    for b in BAN:
        for m in re.finditer(re.escape(b), md):
            ln = md[:m.start()].count('\n') + 1
            if ln in ban_lines:
                continue
            issues.append('禁用词出现在正文 行%d: 「%s」' % (ln, b))

    # ---------- 7. 数字对账（文档 vs 权威 JSON）----------
    if STAT_CHECKS:
        print('\n--- 数字对账 ---')
        st_path = os.path.join(STATS, '权威口径.json')
        if not os.path.exists(st_path):
            issues.append('找不到权威口径.json: %s' % st_path)
        else:
            st = json.load(open(st_path, encoding='utf-8'))
            for name, token, getter in STAT_CHECKS:
                in_md = token in md
                try:
                    in_json = str(getter(st)) == token.replace(',', '')
                except Exception as e:
                    in_json = False
                mark = 'OK ' if (in_md and in_json) else ('✗ ' if not in_json else '! ')
                if not (in_md and in_json):
                    issues.append('数字对账 %s: %s (文中%s/JSON%s)' % (name, mark, in_md, in_json))
                print('  %s %-22s 文中=%s JSON=%s' % (mark, name, in_md, in_json))

    allt, ch, rel = load()

    # ---------- 8. 断言 (a)：次数列 vs 可靠集整句相等 ----------
    if COUNT_CLAIMS:
        print('\n--- 断言 (a)：次数列 vs 可靠集整句相等 ---')
        bad_a = 0
        for kw, expect in COUNT_CLAIMS:
            real = sum(1 for x in rel if x['台词'].strip() == kw)
            if real != expect:
                bad_a += 1
                issues.append('次数失真 「%s」：文档写 %d，实测 %d（可靠集整句相等）'
                              % (kw, expect, real))
                print('  ✗ %-26s 文档 %d / 实测 %d' % (kw[:26], expect, real))
        print('  检查 %d 条，失真 %d 条' % (len(COUNT_CLAIMS), bad_a))

    # ---------- 8b. 断言 (a2)：「全书 N 章」vs 实测 ----------
    if FULL_CHAP_CLAIMS:
        print('\n--- 断言 (a2)：「全书 N 章」vs 清洗后实测 ---')
        bad_a2 = 0
        for kw, expect in FULL_CHAP_CLAIMS:
            real = sum(1 for i in sorted(ch) if kw in ch[i])
            if real != expect:
                bad_a2 += 1
                issues.append('章数失真 「%s」：文档写 %d 章，实测 %d 章' % (kw, expect, real))
                print('  ✗ %-26s 文档 %d / 实测 %d' % (kw[:26], expect, real))
        print('  检查 %d 条，失真 %d 条' % (len(FULL_CHAP_CLAIMS), bad_a2))

    # ---------- 9. 断言 (b)：直引回原文定位 ----------
    print('\n--- 断言 (b)：【直引】逐条回原文定位 ---')
    import verify_citations as VC
    ok, tot, bad_list = VC.run(md, quiet=True)
    print('  直引核验 %d/%d 通过' % (ok, tot))
    if ok != tot:
        for b in bad_list[:12]:
            issues.append('直引核验失败: 第%s章「%s」实际在 %s'
                          % (b['chap'], b['quote'][:44], b['real'] or '全书未定位'))

    # ---------- 10. 断言 (c)：§9 角色台词格式 ----------
    i9 = md.find('## 9. 示例对话')
    i10 = md.find('## 10. OOC')
    seg = md[i9:i10] if i9 > 0 and i10 > i9 else ''
    seg_lines = seg.split('\n')
    role = None
    bad_q, bad_p, bad_ascii = [], [], []
    for n, l in enumerate(seg_lines, 1):
        if l.startswith('**用户**'):
            role = 'user'
            continue
        if l.startswith('**你**'):
            role = 'you'
            continue
        if role != 'you':
            continue
        # 📌 说明行 / 引用行 / 表格行 / 标题行 不是角色台词，不参与格式检查
        if l.startswith('>') or l.startswith('|') or l.startswith('#'):
            continue
        if '"' in l or "'" in l:
            bad_ascii.append((n, l))
        if re.search(r'[（(][^）)]*[）)]', l):
            bad_p.append((n, l))
        if l.rstrip().endswith('？') and not l.rstrip().endswith('！？'):
            bad_q.append((n, l))
    print('\n--- 断言 (c)：§9 角色台词格式 ---')
    print('  裸问号 %d | 括号动作 %d | ASCII引号 %d' % (len(bad_q), len(bad_p), len(bad_ascii)))
    for n, l in bad_q:
        issues.append('§9 裸问号 L%d: %s' % (n, l[:70]))
    for n, l in bad_p:
        issues.append('§9 括号动作 L%d: %s' % (n, l[:70]))
    for n, l in bad_ascii:
        issues.append('§9 ASCII引号 L%d: %s' % (n, l[:70]))

    # ---------- 11. 断言 (d)：§9 引号台词可溯源 ----------
    print('\n--- 断言 (d)：§9 引号台词可溯源 ---')
    rel_eq = set(x['台词'].strip() for x in rel)
    allt_n = nrm(allt)
    allt_n2 = allt_n

    def nrm2(s):
        return nrm(s).replace('！？', '？')

    quoted = []
    for m in re.finditer(r'「([^」]{4,})」', seg):
        ls = seg[:m.start()].rfind('\n') + 1
        line = seg[ls:seg.find('\n', m.start())]
        if line.lstrip().startswith('>'):
            continue
        quoted.append(m.group(1).strip())
    bad_fab = 0
    for q in quoted:
        if q in ALLOW or q in rel_eq:
            continue
        if any(q in x['台词'] for x in rel):
            continue
        if q in allt:
            continue
        q2 = re.sub(r'…+$', '', q).rstrip('…')
        if q2 and any(x['台词'].strip().startswith(q2) for x in rel):
            continue
        if q2 and q2 in allt:
            continue
        hit = False
        for cand in (nrm(q2 or q), nrm2(q2 or q)):
            if len(cand) >= 8 and cand in allt_n2:
                hit = True
                break
        if not hit:
            segs = [s for s in re.split(r'…+|\.{3,}', q2 or q) if len(nrm(s)) >= 6]
            if segs:
                hit = all(any(nrm(sg) in allt_n2 or nrm2(sg) in allt_n2 for sg in [sg]) for sg in segs)
        if not hit:
            bad_fab += 1
            issues.append('§9 台词无法溯源: 「%s」' % q[:70])
    print('  检查 %d 条引号台词，无法溯源 %d 条' % (len(quoted), bad_fab))

    # ---------- 12. 半角括号（会造成跨块错配）----------
    half = [i for i, l in enumerate(lines, 1) if ']' in l or '[' in l]
    for i in half:
        issues.append('半角括号 行%d: %s' % (i, lines[i - 1][:70]))
    print('\n半角括号残留行:', len(half))

    print('\n=== 全部自检项 (%d) ===' % len(issues))
    for x in issues:
        print('  -', x)
    if not issues:
        print('  ✅ 全绿')

    os.makedirs(STATS, exist_ok=True)
    json.dump(issues, open(os.path.join(STATS, '%s自检.json' % VER), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('\n写入:', os.path.join(STATS, '%s自检.json' % VER))
    return 0 if not issues else 1


if __name__ == '__main__':
    sys.exit(main())
