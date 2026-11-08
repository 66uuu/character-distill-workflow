# -*- coding: utf-8 -*-
"""【模板】style_fingerprint.py —— S4 语言指纹增强（对标 pystylometry）

★ 本文件是**技能包模板**，不是项目脚本。复制到 <项目>/02_核验/ 后改用。

为什么需要它：
    final_stats.py 已算 句式/标点/自称/粗口/称呼/口头禅/高频短语。
    本脚本补它没覆盖的**量化维度**，让"语言指纹"更可辩护（对应 pystylometry 的 50+ 指标里最稳的那批）：
      · 句长分布（均值/中位/p90/标准差，按字符）
      · 标点画像（每种标点的占比）
      · 词汇多样性（字元 TTR、二字符 bigram 的 Shannon 熵）
      · 功能词频率（的/了/是/我/你/他… 每千字）

纯标准库、零依赖、零成本。`--selftest` 反向验证：不同语料指纹可区分。

用法：
    set DISTILL_ROOT=<D盘>\\UserFiles\\Desktop\\<项目名>_人物蒸馏
    set DISTILL_SRC=<项目>\\01_语料\\chapters
    set DISTILL_STATS=<项目>\\02_核验\\_stats
    python style_fingerprint.py              # 算指纹 → _stats/style_fingerprint.json
    python style_fingerprint.py --selftest   # 反向验证
"""
import os
import re
import sys
import json
import math
import tempfile

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))


def _env(name, default=None):
    return os.environ.get(name) or default


ROOT = _env('DISTILL_ROOT') or os.path.abspath(os.path.join(HERE, '..', '..'))
SRC = _env('DISTILL_SRC') or os.path.join(ROOT, '01_语料', 'chapters')
STATS = _env('DISTILL_STATS') or os.path.join(ROOT, '02_核验', '_stats')
CHAR = _env('DISTILL_CHAR', '角色')

SENT_SPLIT = re.compile(r'[。！？!?；;]+')
PUNCT = list('，。！？、；：""\'\'（）()《》…—~·')
FUNC_WORDS = ['的', '了', '是', '我', '你', '他', '她', '们', '在', '有', '就',
               '都', '不', '也', '要', '会', '把', '被', '给', '和', '与', '而',
               '却', '但', '因为', '所以', '如果', '这', '那', '没', '又', '还']


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
    for p in (HERE, os.path.join(ROOT, '02_核验')):
        if os.path.exists(os.path.join(p, 'final_stats.py')):
            sys.path.insert(0, p)
            try:
                import final_stats
                return ['\n'.join(b) for _, b, _ in final_stats.load_books()]
            except Exception:
                pass
    return []


def _sent_lens(text):
    return [len(re.sub(r'\s', '', s)) for s in SENT_SPLIT.split(text)
            if re.sub(r'\s', '', s)]


def fingerprint(text):
    sents = [s for s in _sent_lens(text) if s > 0]
    n = len(sents) or 1
    lens = sorted(sents)
    mean = sum(sents) / n
    median = lens[n // 2] if n % 2 else (lens[n // 2 - 1] + lens[n // 2]) / 2
    p90 = lens[min(n - 1, int(n * 0.9))]
    std = math.sqrt(sum((x - mean) ** 2 for x in sents) / n)
    total = len(text)
    # 标点画像
    pc = {}
    for p in PUNCT:
        c = text.count(p)
        if c:
            pc[p] = round(c / total, 4) if total else 0
    # 二字符 bigram 熵
    body = re.sub(r'\s', '', text)
    bg = {}
    for i in range(len(body) - 1):
        bg[body[i:i + 2]] = bg.get(body[i:i + 2], 0) + 1
    tot = sum(bg.values())
    ent = -sum((v / tot) * math.log2(v / tot) for v in bg.values()) if tot else 0
    # 字元 TTR
    ttr = len(set(body)) / len(body) if body else 0
    # 功能词频率 / 千字
    per1k = {}
    for w in FUNC_WORDS:
        cnt = text.count(w)
        per1k[w] = round(cnt / (total / 1000), 2) if total else 0
    return {
        'char_total': total,
        'sentence_count': n,
        'len_mean': round(mean, 2), 'len_median': median,
        'len_p90': p90, 'len_std': round(std, 2),
        'punct_profile': pc,
        'bigram_entropy': round(ent, 3),
        'char_ttr': round(ttr, 4),
        'func_word_per1k': per1k,
    }


def run():
    corpus = load_corpus()
    if not corpus:
        print('[WARN] 未找到语料（DISTILL_SRC=%s），无法计算指纹。' % SRC)
        return 0
    fp = fingerprint('\n'.join(corpus))
    os.makedirs(STATS, exist_ok=True)
    out = os.path.join(STATS, 'style_fingerprint.json')
    try:
        json.dump(fp, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    except Exception as e:
        alt = os.path.join(tempfile.gettempdir(), '蒸馏style_%s.json' % CHAR)
        json.dump(fp, open(alt, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        out = alt
        print('[WARN] 默认目录不可写，报告降级到: %s (%s)' % (alt, e))
    print('=' * 50)
    print('S4 语言指纹增强（对标 pystylometry）')
    print('字符数: %d  句数: %d' % (fp['char_total'], fp['sentence_count']))
    print('句长 均值/中位/p90/标准差: %.2f / %s / %s / %.2f'
          % (fp['len_mean'], fp['len_median'], fp['len_p90'], fp['len_std']))
    print('二字符 bigram 熵: %.3f' % fp['bigram_entropy'])
    print('字元 TTR: %.4f' % fp['char_ttr'])
    print('标点画像: %s' % fp['punct_profile'])
    print('=' * 50)
    print('报告:', out)
    return 0


# ----------------------------------------------------------------------
ST_CORPUS = ("秦风冷冷地看了他一眼。他说：你走吧。风很大，街上没有人。"
             "老街尽头的便利店还亮着灯。你以为我会帮你？别做梦了。")
ST_CORPUS2 = ("这是一段完全不同的文字。它用了很多不同的字和标点，句子长短不一，语气柔和。"
              "春风拂过山坡，野花开了。他轻轻地笑了笑，没有说话。")


def selftest():
    print('=== style_fingerprint.py 反向验证 (--selftest) ===')
    fp = fingerprint(ST_CORPUS)
    ok = True
    if not (fp['len_mean'] > 0):
        print('[FAIL] 句长均值应>0'); ok = False
    if not (0 <= fp['bigram_entropy'] <= 8):
        print('[FAIL] bigram 熵应在[0,8]'); ok = False
    if not (0 <= fp['char_ttr'] <= 1):
        print('[FAIL] TTR 应在[0,1]'); ok = False
    fp2 = fingerprint(ST_CORPUS2)
    if (abs(fp['bigram_entropy'] - fp2['bigram_entropy']) < 1e-6
            and fp['len_mean'] == fp2['len_mean']):
        print('[FAIL] 不同语料指纹应可区分'); ok = False
    if ok:
        print('[PASS] 维度计算正常，且不同语料指纹可区分')
        print('  语料A 句长均值=%.2f 熵=%.3f' % (fp['len_mean'], fp['bigram_entropy']))
        print('  语料B 句长均值=%.2f 熵=%.3f' % (fp2['len_mean'], fp2['bigram_entropy']))
        return 0
    return 1


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()
    sys.exit(selftest() if a.selftest else run())
