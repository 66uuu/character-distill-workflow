# -*- coding: utf-8 -*-
"""【模板】groundguard_check.py —— 人物蒸馏工作流 · S7 第 5 校验器（grounding 层）

★ 本文件是**技能包模板**，不是项目脚本。
  复制到 <项目>/02_核验/ 后改配置，或用环境变量指定路径。

--------------------------------------------------------------------------
它补的是哪一格？
--------------------------------------------------------------------------
已有的四个校验器：
    selfcheck.py         数字对账 / 口径 / 格式           —— 看数字和符号
    scan_fabrication.py  全文「」引号逐条回原文           —— 只验"引号原句"
    verify_citations.py  直引 → 章号定位（滑窗指纹）      —— 只验"直引章号"
    semantic_check.py    断言 ↔ 原文蕴含判定（NLI）       —— 验"意思反没反"

它们都漏掉一格：**非引号的事实型断言 + 数字量级矛盾**。
典型盲区：
  · §1 性格写成"秦风是个冷酷的人"——这句话没有引号、也不是直引，
    三个字面校验器完全看不见；semantic_check 要调模型才能验。
  · §4/§7 里写"全书 5000 次粗口"，但语料实测 ~50 次——量级差 100 倍，
    现有脚本只核对"口径是否统一"，不核对"这个数和语料事实是否冲突"。

本脚本专门补这两类：
  (1) **非引号事实断言的 grounding**：把事实型章节（§0/1/2/3/7/12/13）里
      每条陈述拿去和语料做支撑度匹配（离线 BM25 层 = 字符 bigram 重叠，
      不花一分钱；装了 groundguard 自动升级到 LLM 层）。
  (2) **数字量级矛盾**：抽事实章节里的数字+单位，和语料/权威统计做对照，
      抓"同单位、比值 >3 倍"的量级冲突，以及"语料里完全找不到"的孤立数字。

--------------------------------------------------------------------------
为什么默认离线零成本（呼应"省积分"铁律）
--------------------------------------------------------------------------
groundguard 自己也说"60–70% 的核查根本到不了 LLM，BM25 确定性解决"。
所以这个脚本的离线层是纯标准库实现，不联网、不调模型、不烧积分；
只有 `groundguard` 包已安装且显式 `--backend groundguard` 时才走 LLM 层。

--------------------------------------------------------------------------
用法
--------------------------------------------------------------------------
    set DISTILL_ROOT=<D盘>\\UserFiles\\Desktop\\<项目名>_人物蒸馏
    set DISTILL_SRC=<项目>\\01_语料\\chapters
    set DISTILL_V2=<项目>\\03_交付物\\<角色名>_数字人系统提示词_v2.md
    set DISTILL_STATS=<项目>\\02_核验\\_stats
    set DISTILL_CHAR=<角色名>
    set DISTILL_NAMES=主角名,别名1

    python groundguard_check.py                  # 全量 grounding 校验
    python groundguard_check.py --selftest       # 反向验证（先跑这个证明它能抓编造）
    python groundguard_check.py --backend groundguard   # 已装 groundguard 时走 LLM 层
    python groundguard_check.py --only-section 0,1,2
    python groundguard_check.py --limit 200

报告输出：默认 <DISTILL_STATS>/groundguard.json（不可写则降级 %TEMP%）。
退出码：发现 ungrounded / numeric 冲突时 1，否则 0（便于脚本串联）。
"""
import os
import re
import sys
import json
import math

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))


def _env(name, default=None):
    return os.environ.get(name) or default


ROOT = _env('DISTILL_ROOT') or os.path.abspath(os.path.join(HERE, '..', '..'))
SRC = _env('DISTILL_SRC') or os.path.join(ROOT, '01_语料', 'chapters')
V2 = _env('DISTILL_V2',
          os.path.join(ROOT, '03_交付物', '角色名_数字人系统提示词_v2.md'))
STATS = _env('DISTILL_STATS') or os.path.join(ROOT, '02_核验', '_stats')
CHAR = _env('DISTILL_CHAR', '角色')
NAMES = [x.strip() for x in _env('DISTILL_NAMES', '').split(',') if x.strip()]
NAMES = NAMES or [CHAR]

# 事实型章节（与 semantic_check 一致）：身份/公理/性格/准则/关系/履历/世界观。
DEF_SECTIONS = _env('DISTILL_GG_SECTIONS', '0,1,2,3,7,12,13')
# 负面清单行永远是指令不是事实，跳过。
NEG_MARK = ('❌', '⚠️', '🚫')
OUT = _env('DISTILL_GG_OUT') or STATS

CN_UNIT = {'十': 10, '百': 100, '千': 1000, '万': 1e4, '亿': 1e8}
# 统计型单位：出现即视为"像一条统计数字"，要做语料 corroboration。
STAT_UNITS = ('次', '个', '章', '岁', '元', '块', '万', '亿', '%', '人', '名',
              '条', '句', '字', '年', '天', '月', '处', '件', '位', '倍')
# 中文数字字形
_CN_DIGIT = {'零': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
             '六': 6, '七': 7, '八': 8, '九': 9}
_CN_UNIT = {'十': 10, '百': 100, '千': 1000, '万': 1e4, '亿': 1e8}
CN_NUM_RE = re.compile(r'[零一二两三四五六七八九十百千万亿]+')


def cn_to_int(s):
    """把中文数字串转成整数/浮点。覆盖 五十/三百/两千/一万/十二/二十 等常见形态。"""
    total = 0.0
    section = 0.0
    current = 0
    for ch in s:
        if ch in _CN_DIGIT:
            current = _CN_DIGIT[ch]
        elif ch in _CN_UNIT:
            u = _CN_UNIT[ch]
            if u >= 1e4:  # 万 / 亿：进位
                section = (section + current) * u
                total += section
                section = 0.0
                current = 0
            else:
                section += (current if current else 1) * u
                current = 0
        else:
            break
    return int(total + section + current)


# --------------------------------------------------------------------------
# 语料加载（尽量复用 final_stats，否则退化为直接扫 chapters 目录）
# --------------------------------------------------------------------------
def load_corpus():
    chunks = []
    if os.path.isdir(SRC):
        for fn in sorted(os.listdir(SRC)):
            if fn.lower().endswith('.txt'):
                try:
                    chunks.append(open(os.path.join(SRC, fn), encoding='utf-8',
                                       errors='replace').read())
                except Exception:
                    pass
    if chunks:
        return chunks
    # 退化路径：复用 final_stats.load_books()
    for p in (HERE, os.path.join(ROOT, '02_核验')):
        if os.path.exists(os.path.join(p, 'final_stats.py')):
            sys.path.insert(0, p)
            try:
                import final_stats
                books = final_stats.load_books()
                return ['\n'.join(b) for _, b, _ in books]
            except Exception:
                pass
    return []


# --------------------------------------------------------------------------
# 事实型章节抽取
# --------------------------------------------------------------------------
SEC_RE = re.compile(r'^#{2,4}\s*.*?§\s*(\d{1,2})', re.M)


def extract_fact_sections(md, only=None):
    """返回 [(sec_no, text)]，仅事实型章节，跳过负面清单行。"""
    allowed = set(int(x) for x in DEF_SECTIONS.split(',') if x.strip())
    if only:
        allowed = set(int(x) for x in only.split(',') if x.strip())
    # 按章节切分
    parts = re.split(r'(?m)^(#{2,4}\s+.*)$', md)
    sections = []
    cur_no = None
    cur_txt = []
    for seg in parts:
        m = SEC_RE.match(seg.strip()) if seg.strip().startswith('#') else None
        if m:
            if cur_no is not None:
                sections.append((cur_no, '\n'.join(cur_txt)))
            cur_no = int(m.group(1))
            cur_txt = [seg]
        else:
            cur_txt.append(seg)
    if cur_no is not None:
        sections.append((cur_no, '\n'.join(cur_txt)))
    out = []
    for no, txt in sections:
        if no not in allowed:
            continue
        kept = []
        for line in txt.splitlines():
            if line.lstrip().startswith(NEG_MARK):
                continue
            kept.append(line)
        out.append((no, '\n'.join(kept)))
    return out


# --------------------------------------------------------------------------
# 数字抽取 + 量级矛盾 / 孤立数字检测
# --------------------------------------------------------------------------
NUM_RE = re.compile(r'(\d[\d,]*(?:\.\d+)?)\s*(%|percent|十|百|千|万|亿)?', re.I)


def to_float(num, suf):
    v = float(num.replace(',', ''))
    if suf:
        suf = suf.lower()
        if suf in CN_UNIT:
            v *= CN_UNIT[suf]
        elif suf == '%' or suf == 'percent':
            v = ('pct', v)  # 用特殊标记区分百分比
    return v


def extract_numbers(text):
    """返回 [(value, raw, unit)]，unit 为紧跟的数字单位（统计型）。
    同时支持阿拉伯数字与中文数字（五十 / 三百 / 两千）。"""
    res = []
    seen = set()
    # 阿拉伯数字
    for m in NUM_RE.finditer(text):
        num, suf = m.group(1), m.group(2)
        after = text[m.end():m.end() + 2]
        unit = ''
        for u in STAT_UNITS:
            if after.startswith(u):
                unit = u
                break
        val = to_float(num, suf)
        key = (str(val), unit)
        if key not in seen:
            seen.add(key)
            res.append((val, m.group(0), unit))
    # 中文数字（仅接受长度>=2 的串，避免把"一个"当成统计数字）
    for m in CN_NUM_RE.finditer(text):
        raw = m.group(0)
        if len(raw) < 2:
            continue
        val = cn_to_int(raw)
        if val <= 0:
            continue
        after = text[m.end():m.end() + 2]
        unit = ''
        for u in STAT_UNITS:
            if after.startswith(u):
                unit = u
                break
        if not unit:
            continue
        key = (str(val), unit)
        if key not in seen:
            seen.add(key)
            res.append((val, raw, unit))  # raw 不含单位，单位单独存
    return res


def numeric_check(claims_text, corpus_text):
    """返回数字相关的问题列表。"""
    issues = []
    corpus_nums = extract_numbers(corpus_text)
    for ci in extract_numbers(claims_text):
        val, raw, unit = ci
        if not unit:
            continue  # 非统计型数字（如"给我5块钱"）不强制核查
        # 1) 同单位、同值 → 语料 corroborated
        found_same = False
        for cv, craw, cu in corpus_nums:
            if cu == unit and _eq(val, cv):
                found_same = True
                break
        if found_same:
            continue
        # 2) 同单位、比值 >3 倍 → 量级冲突
        conflict = None
        for cv, craw, cu in corpus_nums:
            if cu == unit and isinstance(val, (int, float)) and isinstance(cv, (int, float)):
                if min(val, cv) > 0 and max(val, cv) / min(val, cv) > 3:
                    conflict = craw
                    break
        if conflict:
            issues.append({
                'type': 'numeric_magnitude',
                'claim_num': raw,
                'unit': unit,
                'corpus_num': conflict,
                'msg': '数字量级冲突：提示词写 %s%s，语料出现 %s%s（比值>3倍）'
                       % (raw, unit, conflict, unit),
            })
            continue
        # 3) 同单位完全找不到 → 孤立数字，需人工核实
        any_unit = any(cu == unit for _, _, cu in corpus_nums)
        if not any_unit:
            issues.append({
                'type': 'numeric_orphan',
                'claim_num': raw,
                'unit': unit,
                'msg': '孤立数字：提示词写 %s%s，语料中找不到同单位数字，需人工核实来源'
                       % (raw, unit),
            })
    return issues


def _eq(a, b):
    if isinstance(a, tuple) or isinstance(b, tuple):
        return a == b
    if a == 0 or b == 0:
        return a == b
    return abs(a - b) / max(abs(a), abs(b)) < 0.01


# --------------------------------------------------------------------------
# 离线 grounding（字符 bigram Jaccard）—— 零依赖、零成本
# --------------------------------------------------------------------------
def bigrams(s):
    s = re.sub(r'\s+', '', s)
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _strip_names(s, names):
    for n in names:
        if n and len(n) >= 2:
            s = s.replace(n, '')
    # 剥句首系词/指代词标记，只对真正的谓语名词打分
    s = re.sub(r'^(?:是个|是一名|是一位|是一个|这种|这个|那个|那样|一位|一名)+', '', s)
    return _strip(s)


def ground_offline(claim, corpus_chunks, names=None):
    """返回 (score, best_chunk_idx)。score 用 overlap coefficient（= |A∩B|/min(|A|,|B|)），
    对"短断言 vs 长语料"的长度错配比 Jaccard 稳健；且先剥掉角色名与句首系词，
    只对谓语打分，避免"秦风是…"这种人人共享的前缀污染区分度。"""
    names = names or []
    claim_bg = bigrams(_strip_names(claim, names))
    if not claim_bg:
        return 1.0, -1
    best = 0.0
    best_i = -1
    for i, ch in enumerate(corpus_chunks):
        cb = bigrams(ch)
        if not cb:
            continue
        inter = len(claim_bg & cb)
        # overlap coefficient：只看"断言里有多少 bigram 在语料出现"
        score = inter / min(len(claim_bg), len(cb))
        if score > best:
            best, best_i = score, i
    return best, best_i


def _strip(s):
    return re.sub(r'[「」『』""\'\'【】()（）\s，。！？、；：…—·\-—~*]', '', s)


# 把事实章节拆成"陈述句"用于 grounding
SENT_SPLIT = re.compile(r'[。！？!?；;\n]+')


def split_claims(text):
    out = []
    for seg in SENT_SPLIT.split(text):
        seg = seg.strip()
        if not seg or seg.lstrip().startswith('#'):  # 跳过 markdown 章节标题
            continue
        if len(_strip(seg)) >= 6:  # 太短的碎片无意义
            out.append(seg)
    return out


# --------------------------------------------------------------------------
# groundguard 可选 LLM 层
# --------------------------------------------------------------------------
def has_groundguard():
    try:
        import groundguard  # noqa
        return True
    except Exception:
        return False


def ground_with_gg(claims_text, corpus_chunks, model=None):
    """若 groundguard 可用，逐句 verify；返回 dict claim->verdict。"""
    import groundguard
    from groundguard import Source, verify
    sources = [Source(content=c, source_id='corpus_%d' % i)
               for i, c in enumerate(corpus_chunks)]
    results = {}
    for claim in split_claims(claims_text):
        try:
            r = verify(claim=claim, sources=sources, model=model or 'auto')
            results[claim] = getattr(r, 'status', str(r))
        except Exception as e:
            results[claim] = 'error:%s' % e
    return results


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def run(backend='auto', only=None, limit=200):
    md = open(V2, encoding='utf-8', errors='replace').read().replace('\r\n', '\n')
    corpus = load_corpus()
    if not corpus:
        print('[WARN] 未找到语料（DISTILL_SRC=%s / final_stats 也不可用），'
              'grounding 与数字核查将无法对照原文。' % SRC)
    corpus_text = '\n'.join(corpus)

    fact = extract_fact_sections(md, only=only)
    fact_text = '\n'.join(t for _, t in fact)
    if not fact_text.strip():
        print('[WARN] 事实型章节（%s）未抽取到内容，检查 DISTILL_V2 与章节标题格式（需含 §N）。'
              % DEF_SECTIONS)

    issues = []
    grounded_summary = []

    # (1) 数字层级：作用域**额外包含 §4/§7/§12**（统计/履历里的数字正是要核对的），
    #     不能沿用 semantic_check 把 §4 排除的那套——否则数字检查会空跑。
    num_secs = extract_fact_sections(md, only='0,1,2,3,4,7,12,13')
    num_text = '\n'.join(t for _, t in num_secs)
    num_issues = numeric_check(num_text, corpus_text)
    issues.extend(num_issues)

    # (2) grounding 层
    use_gg = (backend == 'groundguard') or (backend == 'auto' and has_groundguard())
    claims = split_claims(fact_text)
    if limit:
        claims = claims[:limit]
    if use_gg:
        print('[INFO] 使用 groundguard LLM 层（backend=%s）' % backend)
        res = ground_with_gg(fact_text, corpus, _env('DISTILL_GG_MODEL'))
        for claim, verdict in res.items():
            grounded_summary.append({'claim': claim, 'verdict': str(verdict)})
            if str(verdict).upper() not in ('SUPPORTED', 'APPROVED', 'REVISE'):
                issues.append({'type': 'ungrounded', 'claim': claim,
                               'msg': 'groundguard 判定未充分支撑: %s' % verdict})
    else:
        if backend == 'auto':
            print('[INFO] groundguard 未安装，使用离线 grounding 层（零成本）。'
                  '装了 groundguard 后加 --backend groundguard 可升级到 LLM 层。')
        for claim in claims:
            score, _ = ground_offline(claim, corpus, names=NAMES)
            verdict = 'grounded' if score >= 0.5 else (
                'weak' if score >= 0.2 else 'ungrounded')
            grounded_summary.append({'claim': claim, 'score': round(score, 3),
                                     'verdict': verdict})
            if verdict == 'ungrounded':
                issues.append({'type': 'ungrounded', 'claim': claim,
                               'score': round(score, 3),
                               'msg': '离线 grounding 弱支撑(%.2f)，语料中找不到对应事实，需人工核实'
                                      % score})

    # 输出
    os.makedirs(OUT, exist_ok=True)
    rep = os.path.join(OUT, 'groundguard.json')
    payload = {
        'backend': ('groundguard' if use_gg else 'offline_bm25'),
        'sections': [s for s, _ in fact],
        'numeric_issues': num_issues,
        'grounding': grounded_summary,
        'issue_count': len(issues),
    }
    try:
        json.dump(payload, open(rep, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
    except Exception as e:
        alt = os.path.join(tempfile.gettempdir(), '蒸馏grounding_%s.json' % CHAR)
        json.dump(payload, open(alt, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        rep = alt
        print('[WARN] 默认目录不可写，报告降级到: %s (%s)' % (alt, e))

    # 打印
    print('=' * 60)
    print('第5校验器 grounding 层 · 后端=%s' % ('groundguard' if use_gg else 'offline_bm25'))
    print('事实章节: %s' % ','.join('§%d' % s for s, _ in fact) or '(无)')
    print('数字问题: %d' % len(num_issues))
    for n in num_issues:
        print('  [数字] %s' % n['msg'])
    ug = [g for g in grounded_summary if g['verdict'] == 'ungrounded']
    print('弱/无支撑断言: %d / 共 %d 条' % (len(ug), len(grounded_summary)))
    for g in ug:
        print('  [支撑] (%.2f) %s' % (g.get('score', 0), g['claim'][:80]))
    print('=' * 60)
    print('问题合计: %d' % len(issues))
    print('报告:', rep)
    return 1 if issues else 0


# --------------------------------------------------------------------------
# 自测（反向验证，铁律 6：自检器要做反向验证否则是假绿）
# --------------------------------------------------------------------------
SELFTEST_CORPUS = [
    "秦风是这本小说里的头号反派，心思缜密，嘴上不饶人。",
    "他经营着一家位于老街尽头的便利店，白天睡觉晚上营业。",
    "秦风说话刻薄，一生大约说了五十次粗口，多数在被人惹毛的时候。",
    "他对外人冷若冰霜，唯独对店里的那只橘猫还算温和。",
    "第300章里秦风说：想让我不抓你回去也不是不可以，不过你得加钱！",
]

SELFTEST_PROMPT_FACT = """## §0 身份卡
秦风是个反派。

## §1 性格与行为模式
秦风是个冷酷的人。
秦风是一名医生，专门给人做手术。
秦风对外人冷淡，对橘猫温和。

## §4 统计
秦风全书说了 5000 次粗口。
秦风活了 999 岁。

## §10 负面清单
❌ 不要写文艺腔。
"""


def selftest():
    print('=== groundguard_check.py 反向验证 (--selftest) ===')
    corpus = SELFTEST_CORPUS
    corpus_text = '\n'.join(corpus)
    fact_text = SELFTEST_PROMPT_FACT
    ok = True

    # 数字层级
    num = numeric_check(fact_text, corpus_text)
    msgs = [n['msg'] for n in num]
    # 期望抓到：5000次 vs 50次 量级冲突；999岁 孤立数字
    if not any('5000' in m and '量级' in m for m in msgs):
        print('[FAIL] 未抓到 5000次粗口 的量级冲突'); ok = False
    if not any('999' in m for m in msgs):
        print('[FAIL] 未抓到 999岁 孤立数字'); ok = False
    else:
        print('[PASS] 数字层级抓到 %d 个问题：' % len(num))
        for m in msgs:
            print('        · ' + m)

    # grounding 层（剥掉角色名"秦风"后只对谓语打分）
    claims = split_claims(fact_text)
    scored = []
    for c in claims:
        s, _ = ground_offline(c, corpus, names=['秦风'])
        scored.append((s, c))
    # 期望："秦风是个反派" 高支撑(>=0.5)；"秦风是一名医生" 低支撑(<0.2)
    anti = [c for s, c in scored if '反派' in c and s >= 0.5]
    doc = [c for s, c in scored if '医生' in c and s < 0.2]
    if not anti:
        print('[FAIL] 有语料支持的"秦风是个反派"未被判定为 grounded'); ok = False
    if not doc:
        print('[FAIL] 无语料支持的"秦风是一名医生"未被判定为 ungrounded'); ok = False
    if anti and doc:
        print('[PASS] grounding 层：有语料支持的断言获高支撑，'
              '无支撑断言(医生)被标记需核实')
        for s, c in scored:
            print('        · (%.2f) %s' % (s, c[:50]))

    print('=' * 60)
    if ok:
        print('反向验证 PASS：本校验器能抓出"数字量级矛盾 + 非引号事实断言无支撑"，'
              '而这三个盲区是 scan_fabrication / verify_citations / selfcheck 都看不见的。')
        return 0
    print('反向验证 FAIL：逻辑有缺口，需修复。')
    return 1


# --------------------------------------------------------------------------
if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--selftest', action='store_true', help='反向验证（不依赖项目）')
    ap.add_argument('--backend', default='auto',
                    choices=['auto', 'local', 'groundguard'])
    ap.add_argument('--only-section', default=None, help='只查指定章节, 如 0,1,2')
    ap.add_argument('--limit', type=int, default=200)
    args = ap.parse_args()

    if args.selftest:
        sys.exit(selftest())

    # backend=local 强制离线
    backend = 'local' if args.backend == 'local' else args.backend
    sys.exit(run(backend=backend, only=args.only_section, limit=args.limit))
