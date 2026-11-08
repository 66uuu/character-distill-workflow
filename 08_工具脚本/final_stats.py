# -*- coding: utf-8 -*-
"""【模板】final_stats.py —— 人物蒸馏工作流 · 语言指纹统计器

★ 本文件是**技能包模板**，不是项目脚本。
  复制到 <项目>/02_核验/ 后改下面的词表，或用环境变量指定路径。

用途：S4「挖掘语言指纹」的统计核心。
      产出 §4 语言指纹所需的**全部实测数字**：句式 / 标点 / 自称 / 粗口 /
      称呼体系 / 复用整句 / 句尾二字 / 高频短语（剔虚词）。

★ 分母铁律：一切统计的分母是**可靠集台词集**（A+B+C+），不是全书文本。
  拿全书统计会把配角金句算主角头上（实测差 19 倍）。

★ 高频短语必须剔虚词：
  「什么/你们/我们/就是」这类会霸榜，毫无辨识度。
  本脚本用两个机制剔除：
    ① 虚词黑名单（STOPWORDS）
    ② 子串包含过滤——若 A 是 B 的子串且 B 的次数 ≈ A 的次数，只留 B

用法：
    set DISTILL_ROOT=...
    set DISTILL_STATS=<项目>\\02_核验\\_stats
    set DISTILL_CHAR=<角色名>
    python final_stats.py
    → 输出 _stats/语言指纹.json

⚠️ 不要把 stdout 写成 `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, ...)`。
   本脚本只用 sys.stdout.reconfigure()。
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.environ.get('DISTILL_ROOT') or os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
SRC = os.environ.get('DISTILL_SRC') or os.path.join(ROOT, '01_语料', 'chapters')
STATS = os.environ.get('DISTILL_STATS') or os.path.join(ROOT, '02_核验', '_stats')
CHAR = os.environ.get('DISTILL_CHAR', '角色名')
RELIABLE_JSON = os.environ.get('DISTILL_RELIABLE', '%s台词_分级.json' % CHAR)
OUT_JSON = os.path.join(STATS, '语言指纹.json')

os.makedirs(STATS, exist_ok=True)

# ===== 词表：按项目改 =====
# 自称
SELFWORDS = ['我', '朕', '本王', '本少', '小爷', '爷', '老子', '咱', '本座',
             '在下', '老夫', '吾', '洒家', '本座', '老夫子']
# 粗口
SWEARS = ['卧槽', '操', 'tm', 'TM', 'Tm', '他妈', '妈的', '不要脸', '无耻', '靠',
          '废物', '滚', '牛逼', '放屁', '王八蛋', '傻逼', '有病', '狗屁', '去死',
          '神经病', '艹', '靠北']
# 称呼体系（对谁叫什么）
CALLS = ['老六', '哥', '姐', '兄', '弟', '妹', '师尊', '徒儿', '前辈', '小友',
         '爱卿', '陛下', '陛下', '系统', '宿主', '各位', '诸位', '道友', '师尊']
# 虚词黑名单（高频短语榜要剔掉这些）
STOPWORDS = set(
    '什么 怎么 这个 那个 什么 你们 我们 他们 咱们 就是 不是 没有 一个 可以 '
    '自己 知道 这么 那么 如果 因为 所以 但是 这个 那个 现在 已经 还是 一下 '
    '起来 出来 过去 这么 那么 一点 有些 这些 那些 大家 自己 东西 时候 现在 '
    '真的 怎么 不会 不能 不要 可能 应该 已经 一定 反正 其实 当然 于是 '
    '然后 最后 开始 继续 一直 只是 就算 即使 无论 不管 要是 假如 除非'.split())
# 短句白名单：谁都能说的通用短句，不算角色特征
GENERIC = {'卧槽', '什么', '哼', '是', '好', '对', '滚', '不行', '不必', '放肆',
           '大胆', '狂妄', '不可能', '闭嘴', '住口', '哎', '哦', '嗯', '啊', '呵',
           '哈哈', '喂', '去', '走', '好家伙', '什么情况'}
# ==================================

NOISE = re.compile(
    r"^(阅读模式|原网页|上一章|下一章|目录|返回|加入书架|举报|分享|APP|"
    r"番茄小说|正在加载|加入书签|字体|背景|章节报错|举报本章|"
    r"书页|首页|上一|下一|加入|字体大小|背景颜色|手机版|电脑版|"
    r"第[一二三四五六七八九十百千0-9]+章.*|.*本章.*|完结撒花.*|"
    r"请记住本书首发域名.*|.*首发域名.*|www\..*|.*笔趣阁.*)$")


def load_books():
    """★ 唯一口径：清洗后语料。所有统计都必须走这个函数。"""
    res = []
    if not os.path.isdir(SRC):
        print('!! 找不到语料目录:', SRC)
        return res
    fns = [f for f in os.listdir(SRC) if f.endswith('.txt')]
    fns.sort(key=lambda x: int(re.match(r'p(\d+)\.txt', x).group(1))
             if re.match(r'p(\d+)\.txt', x) else 0)
    for fn in fns:
        raw = open(os.path.join(SRC, fn), encoding='utf-8', errors='replace').read()
        lines = raw.split('\n')
        title = lines[0].strip() if lines else fn
        body = [l.strip() for l in lines[1:] if l.strip() and not NOISE.match(l.strip())]
        res.append((title, body, fn))
    return res


def load_reliable():
    p = os.path.join(STATS, RELIABLE_JSON)
    if not os.path.exists(p):
        print('!! 找不到分级 JSON:', p, '（先跑 extract_speech.py）')
        return []
    rel = json.load(open(p, encoding='utf-8'))
    return [x for x in rel if x.get('级') in ('A', 'B', 'C+')]


def main():
    books = load_books()
    if not books:
        return 1
    rel = load_reliable()
    if not rel:
        print('!! 可靠集为空，先跑 extract_speech.py')
        return 1

    total_chars = sum(len(''.join(b)) for _, b, _ in books)
    all_text = '\n'.join('\n'.join(b) for _, b, _ in books)
    quotes = [x['台词'] for x in rel]
    qt = ''.join(quotes)

    st = {'_口径': '分母=可靠集台词集(A+B+C+)；次数=可靠集整句相等；语料=清洗后',
          '_角色': CHAR}

    # ---- 句式 ----
    sents = []
    for q in quotes:
        for s in re.split(r'[。！？!?…]+', q):
            s = re.sub(r'\s', '', s)
            if s:
                sents.append(s)
    sl = sorted(len(re.sub(r'[^一-鿿A-Za-z0-9]', '', s)) for s in sents)
    sl = [x for x in sl if x > 0]
    if sl:
        st['句式'] = {
            '句数': len(sl),
            '均值': round(sum(sl) / len(sl), 2),
            '中位': sl[len(sl) // 2],
            'p90': sl[int(len(sl) * 0.9)],
            '最长': max(sl),
            '≤5字占比%': round(sum(1 for x in sl if x <= 5) / len(sl) * 100, 1),
            '≤10字占比%': round(sum(1 for x in sl if x <= 10) / len(sl) * 100, 1),
            '≤15字占比%': round(sum(1 for x in sl if x <= 15) / len(sl) * 100, 1),
        }

    # ---- 标点（每万字）----
    W = len(qt) / 10000 if qt else 1
    st['标点'] = {c: {'次数': qt.count(c), '每万字': round(qt.count(c) / W, 1)}
                  for c in '！？，。；…'}

    # ---- 自称 ----
    selfs = {}
    for w in SELFWORDS:
        c = qt.count(w)
        if c:
            selfs[w] = c
    selfs['我(独立)'] = len(re.findall(r'(?<![一-鿿])我(?![一-鿿])', qt))
    st['自称'] = dict(sorted(selfs.items(), key=lambda x: -x[1]))

    # ---- 粗口 ----
    st['粗口'] = {w: qt.count(w) for w in SWEARS if qt.count(w)}
    st['粗口'] = dict(sorted(st['粗口'].items(), key=lambda x: -x[1]))

    # ---- 称呼体系（台词集 + 全书 两列）----
    calls = {}
    for w in CALLS:
        cq, cb = qt.count(w), all_text.count(w)
        if cb:
            calls[w] = {'台词集': cq, '全书': cb}
    st['称呼'] = dict(sorted(calls.items(), key=lambda x: -x[1]['全书']))

    # ---- 复用整句（口头禅候选）----
    full, where = Counter(), defaultdict(list)
    for x in rel:
        q2 = x['台词'].strip()
        if 4 <= len(q2) <= 50 and q2 not in GENERIC:
            full[q2] += 1
            if len(where[q2]) < 6:
                where[q2].append(x.get('章', ''))
    st['复用整句'] = [
        {'句': s, '次数': c, '出处': where[s]}
        for s, c in sorted(full.items(), key=lambda x: -x[1]) if c >= 2
    ]

    # ---- 句尾二字（口头禅模式）----
    combo = Counter()
    for q in quotes:
        q2 = re.sub(r'[”"]', '', q).rstrip()
        if len(q2) >= 2:
            combo[q2[-2:]] += 1
    st['句尾二字'] = [{'尾': s, '次数': c} for s, c in combo.most_common(30)]

    # ---- 高频短语（★ 剔虚词 + 子串过滤）----
    phr = Counter()
    for q in quotes:
        q2 = re.sub(r'[^一-鿿A-Za-z0-9]', '', q)
        for n in (2, 3, 4, 5, 6, 7, 8):
            for i in range(len(q2) - n + 1):
                phr[q2[i:i + n]] += 1
    cands = [(s, c) for s, c in phr.items() if c >= 8]
    # 子串过滤：A 是 B 的子串且次数接近 → 只留 B
    fin = []
    for s, c in cands:
        if not any(t != s and len(t) > len(s) and s in t and ct >= c * 0.8
                   for t, ct in cands):
            fin.append((s, c))
    # 虚词黑名单过滤
    fin = [(s, c) for s, c in fin
           if s not in STOPWORDS and not all(ch in STOPWORDS for ch in s)]
    fin.sort(key=lambda x: -x[1])
    st['高频短语'] = [{'短语': s, '次数': c} for s, c in fin[:60]]

    # ---- 通用短句占比（角色辨识度反向指标）----
    gen_hits = sum(1 for q in quotes if q.strip() in GENERIC)
    st['通用短句占比%'] = round(gen_hits / len(quotes) * 100, 2) if quotes else 0

    json.dump(st, open(OUT_JSON, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    print('=== 语言指纹（%s）===' % CHAR)
    print('可靠集 %d 条 | 语料 %d 章 / %s 字' % (len(rel), len(books), format(total_chars, ',')))
    if '句式' in st:
        s = st['句式']
        print('句式: 均值 %s / 中位 %s / p90 %s / ≤5字 %s%%' %
              (s['均值'], s['中位'], s['p90'], s['≤5字占比%']))
    print('标点(每万字): ' + ' '.join('%s=%s' % (k, v['每万字']) for k, v in st['标点'].items()))
    print('自称 top5: ' + ' '.join('%s=%d' % (k, v) for k, v in list(st['自称'].items())[:5]))
    print('粗口 top5: ' + ' '.join('%s=%d' % (k, v) for k, v in list(st['粗口'].items())[:5]))
    print('复用整句 top5: ' + ' | '.join('%s×%d' % (r['句'], r['次数'])
                                        for r in st['复用整句'][:5]))
    print('高频短语 top10: ' + ' '.join('%s×%d' % (r['短语'], r['次数'])
                                        for r in st['高频短语'][:10]))
    print('通用短句占比: %s%%' % st['通用短句占比%'])
    print('\n写入:', OUT_JSON)
    print('★ 所有数字的分母都是可靠集，不要混用全书统计。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
