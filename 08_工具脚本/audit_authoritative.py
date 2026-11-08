# -*- coding: utf-8 -*-
"""【模板】audit_authoritative.py —— 人物蒸馏工作流 · 统计口径固化器

★ 本文件是**技能包模板**，不是项目脚本。
  复制到 <项目>/02_核验/ 后改下面几个常量。

用途：把"文档里能写的数字"**锁死在一个地方**。

★ 为什么必须有这一步（最容易翻车的一步）：
  统计脚本产出的 JSON 和文档里写的数字，必须来自**同一个函数**。
  常见陷阱：清洗后语料（剔导航行/标题行/NOISE 行）vs 直接 count 原始文件
  → 同一指标差 1–2%（秦风实测：叶辰 4970 vs 4923、雕虫小技 47 vs 33、仙王 1404 vs 1399）。

★ 三口径铁律（差 8 倍，必须锁死一个并标出来）：
  整句相等（可靠集 ABC+）≠ 子串包含 ≠ 全书章数
  | 台词 | 整句相等 | 子串 | 全书章数 |
  | 「什么！？」 | 5 | 41 | 520 |
  | 「有道理！」 | 7 | 14 | 149 |

★ 口诀：别临时 count。所有写入文档的数字一律从这里取。

用法：
    python audit_authoritative.py
    → 输出 _stats/权威口径.json

⚠️ 不要把 stdout 写成 `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, ...)`，
   那样被 import 时会关掉底层 buffer 导致后续 print 全炸。
   本脚本只用 sys.stdout.reconfigure()。
"""
import json
import os
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ===== 需要按项目修改的常量 =====
ROOT = os.environ.get('DISTILL_ROOT') or os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
SRC = os.environ.get('DISTILL_SRC') or os.path.join(ROOT, '01_语料', 'chapters')
OUT = os.environ.get('DISTILL_STATS') or os.path.join(ROOT, '02_核验', '_stats')
CHAR = os.environ.get('DISTILL_CHAR', '角色名')

# 需要统计的高频短语（**剔虚词**，只留有辨识度的：专名、语气词组、句式模板）
PHRASES = [
    # '什么！？',
]
# 章名统计关键词
TITLE_KEYS = [
    # '老六',
]
# ================================

os.makedirs(OUT, exist_ok=True)

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
    """读 S2 产出的分级 JSON，取可靠集（A+B+C+）。"""
    p = os.path.join(OUT, '%s台词_分级.json' % CHAR)
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

    allt = '\n'.join('\n'.join(b) for _, b, _ in books)
    ch = {i: '\n'.join(b) for i, (_, b, _) in enumerate(books, 1)}
    titles = [t for t, _, _ in books]
    total_chars = len(allt.replace('\n', ''))

    # 句长分布（分母=可靠集台词）
    lens = [len(x['台词']) for x in rel]
    lens_sorted = sorted(lens)
    median = lens_sorted[len(lens) // 2] if lens_sorted else 0

    st = {
        '_口径说明': {
            '分母': '可靠集台词集（A+B+C+），不是全书文本',
            '语料': '清洗后语料（剔除导航行/标题行/NOISE 行）',
            '次数': '可靠集整句相等数（不是子串包含，不是全书章数）',
            '章数': '清洗后语料中该短语出现的章节数',
        },
        '语料': {
            '章数': len(books),
            '总字数': total_chars,
            '可靠集条数': len(rel),
            '唯一台词': len(set(x['台词'].strip() for x in rel)),
        },
        '句式': {
            '均值': round(sum(lens) / len(lens), 2) if lens else 0,
            '中位': median,
            '最长': max(lens) if lens else 0,
            '最短': min(lens) if lens else 0,
        },
        '分级': dict(Counter(x['级'] for x in rel)),
        '短语统计': {},
        '章名统计': {},
    }

    # 高频短语：三个口径全给出来，防止以后混淆
    for p in PHRASES:
        eq = sum(1 for x in rel if x['台词'].strip() == p)
        sub = sum(1 for x in rel if p in x['台词'])
        chap = sum(1 for i in sorted(ch) if p in ch[i])
        st['短语统计'][p] = {
            '整句相等': eq, '子串包含': sub, '全书章数': chap,
            '_建议写入文档的口径': '整句相等' if eq else ('子串包含' if sub else '全书章数'),
        }

    # 章名统计
    for k in TITLE_KEYS:
        st['章名统计'][k] = sum(1 for t in titles if k in t)

    path = os.path.join(OUT, '权威口径.json')
    json.dump(st, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    print('=== 权威口径 ===')
    print(json.dumps(st, ensure_ascii=False, indent=1))
    print('\n写入:', path)
    print('★ 所有写入文档的数字都要从这份 JSON 取，不要临时 count。')
    print('★ 短语的三个口径已并列输出，写作时必须标明用哪个。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
