# -*- coding: utf-8 -*-
"""【模板】extract_speech.py —— 人物蒸馏工作流 · 台词归属分级器

★ 本文件是**技能包模板**，不是项目脚本。
  复制到 <项目>/02_核验/ 后改下面几个常量。

用途：把「这本书里属于主角说的话」单独摘出来，作为**一切统计的分母**。
      这是全工作流最关键的一步——分母错了，后面所有数字都错。

★ 为什么不能用"全书引号句"当分母：
  配角说的"什么！？"、"有道理！"会被算到主角头上。
  秦风项目实测：同一指标，全书统计 vs 台词集统计 **差 19 倍**。

★ 说话人锚定四级：
  | 级 | 判据 | 用途 |
  |---|---|---|
  | A  | 同行锚定（说话人同在引号行内） | 最可靠 |
  | B  | 引号倒装（引号在前，人名在后） | 可靠 |
  | C+ | 纯引号行 + 上下行首名 + **上下文主语校验通过** | 量大，需校验 |
  | C- | 同形态但主语校验不通过 | 排除，但单列说明 |
  可靠集 = A + B + C+

★ 必须设对照组：
  拿几个明确的配角跑同一套规则，看有多少被误挂进来
  → **真污染率** = 对照组命中率。再加人工抽检 30–40 条给准确率。
  两个数一起给（自动 + 人工），缺一不可。

用法：
    python extract_speech.py
    → 输出 _stats/<角色名>台词_分级.json

⚠️ 不要把 stdout 写成 `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, ...)`，
   那样被 import 时会关掉底层 buffer 导致后续 print 全炸。
   本脚本只用 sys.stdout.reconfigure()。
"""
import json
import os
import random
import re
import sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ===== 需要按项目修改的常量 =====
ROOT = os.environ.get('DISTILL_ROOT') or os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
SRC = os.environ.get('DISTILL_SRC') or os.path.join(ROOT, '01_语料', 'chapters')
OUT = os.environ.get('DISTILL_STATS') or os.path.join(ROOT, '02_核验', '_stats')
CHAR = os.environ.get('DISTILL_CHAR', '角色名')

# 所有会被识别为说话人的名字/别名（含主角）
# ★ 用环境变量 NAMES 传入，逗号分隔；不传则用下面的默认示例
# ★ 默认示例是秦风项目的配置（可直接跑通，换项目时改这里或用环境变量）
NAMES = [x for x in (os.environ.get('DISTILL_NAMES') or
                     '秦风,秦昊,小白,秦小白,林三,秦天,云汐月,紫鸢,于兰,叶辰,'
                     '方长,龙傲天,三弄大师,心颜,始祖,二祖,老祖,大长老,系统,'
                     '秦老六,千军,万马,木秀,三秋,太上皇,林渊,月神,白起,南风'
                     ).split(',') if x]
# 对照组：拿他们跑同一套规则量化污染率（**必填**）
CONTRAST_ROLES = [x for x in (os.environ.get('DISTILL_CONTRAST') or
                               '秦昊,小白,林三,紫鸢,叶辰,三弄大师'
                               ).split(',') if x]
# 排他称呼：某个称呼唯一属于某人（避免"二弟"被算给主角）
EXCLUSIVE = {
    '阿弥陀佛': '三弄大师', '佛祖': '三弄大师', '老衲': '三弄大师', '贫僧': '三弄大师',
    '主银': '小白', '兔兔': '小白',
    '陛下': '臣子', '圣上': '臣子', '皇上': '臣子', '吾皇': '臣子',
    '微臣': '臣子', '老臣': '臣子', '臣': '臣子',
    '欧豆豆': '秦昊', '二弟': '秦昊',
    '林兄': '林三',
    '傲天兄': '龙傲天', '龙傲天': '龙傲天',
    '兰宝宝': '于兰', '于兰': '于兰',
    '叮咚': '系统', '宿主': '系统',
}
# 主角的动作/情感动词（上下文里出现这些，说明主语是主角）
QF = (r'(说道|说|开口|笑道|喊道|叫道|应道|叹道|怒道|喝道|喃喃|嘀咕|嘟囔|反问|'
      r'急忙|赶忙|一脸|皱眉|叹气|叹息|摇头|点头|眼睛一亮|眼皮|声音|语气|表情|'
      r'轻声道|淡淡道|冷哼|调侃|笑|哭|叹|回|问)')
# 明确指向别人的模式（出现则该 C 级台词不归主角）
OTHER_SUBJ = re.compile(r'(众人|弟子|侍卫|长老|老祖|大家|两人|他|她)')
# ================================

os.makedirs(OUT, exist_ok=True)
NAME_ALT = '|'.join(sorted(NAMES, key=len, reverse=True))

NOISE = re.compile(
    r"^(阅读模式|原网页|上一章|下一章|目录|返回|加入书架|举报|分享|APP|"
    r"番茄小说|正在加载|加入书签|字体|背景|章节报错|举报本章|"
    r"书页|首页|上一|下一|加入|字体大小|背景颜色|手机版|电脑版|"
    r"第[一二三四五六七八九十百千0-9]+章.*|.*本章.*|完结撒花.*|"
    r"请记住本书首发域名.*|.*首发域名.*|www\..*|.*笔趣阁.*)$")

SPK_A = re.compile(r'(?P<name>' + NAME_ALT + r')(?:[^，。！？“”\n]{0,30})?[：:]\s*[“"](?P<q>[^“”\n]{1,400})[”"]')
SPK_B = re.compile(r'[“"](?P<q>[^“”\n]{1,400})[”"]\s*(?:[^“”\n]{0,10})?(?P<name>' + NAME_ALT + r')(?:[^“”\n]{0,12})')
PURE_Q = re.compile(r'^[“"](?P<q>[^“”]{1,400})[”"]')
AFTER = re.compile(r'^[^“”\n]{0,12}?(?P<name>' + NAME_ALT + r')[^“”\n]{0,12}?(说|道|开口|笑|喊|叫|应|回|低声|朗声|沉声|冷声|叹|怒|喝|喃喃|嘀咕|嘟囔)')


def load_books():
    """读 chapters/p*.txt → [(标题, 正文行列表, 文件名)]，并剔除 NOISE 行。"""
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


def belongs_other(q):
    """排他称呼检查：句子里有明确属于别人的称呼 → 归别人。"""
    for w, owner in EXCLUSIVE.items():
        if w in q and owner != CHAR:
            return owner
    return None


def qf_context(ctx):
    """上下文主语校验：'C+' 高可信 / 'C-' 不可信 / None 无线索。"""
    if CHAR not in ctx:
        return None
    if re.search(re.escape(CHAR) + r'[^。！？\n]{0,12}(' + QF + r')', ctx) or \
       re.search(r'(' + QF + r')[^。！？\n]{0,12}' + re.escape(CHAR), ctx):
        return 'C+'
    return 'C-'


def collect(books, target):
    """按四级规则抽取某角色的台词，并保留角色级证据定位。"""
    out = []
    for title, lines, fn in books:
        n = len(lines)
        for i, l in enumerate(lines):
            speech_line = i + 2
            def emit(q, grade, anchor_text, anchor_line, evidence_type):
                confidence = {'A': 0.99, 'B': 0.95, 'C+': 0.78, 'C-': 0.20}.get(grade, 0.50)
                out.append({'章': title, '台词': q, '级': grade, '说话人': target, '原文文件': fn, '原文行': anchor_line, '台词行': speech_line, 'source_locator': f'{fn}:{speech_line}', '锚点文本': anchor_text, '证据类型': evidence_type, '说话人置信度': confidence})
            m = SPK_A.search(l)
            if m and m.group('name') == target:
                emit(m.group('q'), 'A', l, speech_line, '同行锚定'); continue
            m2 = SPK_B.search(l)
            if m2 and m2.group('name') == target:
                emit(m2.group('q'), 'B', l, speech_line, '引号倒装'); continue
            mm = PURE_Q.match(l)
            if not mm: continue
            q = mm.group('q'); ctx = None; anchor_line = None
            if i + 1 < n:
                m3 = re.match(r'^(?P<name>' + NAME_ALT + r')(?:[^，。！？“”\n]{0,20})?[：:]', lines[i + 1])
                if m3:
                    if m3.group('name') == target: ctx, anchor_line = lines[i + 1], i + 3
                    else: continue
                else:
                    m4 = AFTER.match(lines[i + 1])
                    if m4:
                        if m4.group('name') == target: ctx, anchor_line = lines[i + 1], i + 3
                        else: continue
            if ctx is None and i > 0:
                m5 = re.match(r'^(?P<name>' + NAME_ALT + r')(?:[^，。！？“”\n]{0,20})?[：:]', lines[i - 1])
                if m5:
                    if m5.group('name') == target: ctx, anchor_line = lines[i - 1], i + 1
                    else: continue
                else:
                    m6 = AFTER.match(lines[i - 1])
                    if m6 and m6.group('name') == target: ctx, anchor_line = lines[i - 1], i + 1
            if ctx is None: continue
            emit(q, 'C', ctx, anchor_line, '上下文主语校验')
    return out


def main():
    books = load_books()
    if not books:
        print('语料为空，检查 DISTILL_SRC'); return 1
    print('语料章数: %d' % len(books))
    raw = collect(books, CHAR)
    print('\n=== 主角 %s ===' % CHAR)
    print('  原始归属: %d 条 | %s' % (len(raw), dict(Counter(x['级'] for x in raw))))
    step1 = []; moved = Counter()
    for item in raw:
        owner = belongs_other(item['台词'])
        if owner: moved[owner] += 1; continue
        step1.append(item)
    print('  排他称呼排除 %d 条 -> %s' % (len(raw) - len(step1), dict(moved)))
    final = []
    for item in step1:
        if item['级'] == 'C':
            grade = qf_context(item['锚点文本'])
            if grade is None: continue
            item['级'] = grade; item['说话人置信度'] = 0.78 if grade == 'C+' else 0.20
        final.append(item)
    cnt = Counter(x['级'] for x in final); rel = [x for x in final if x['级'] in ('A', 'B', 'C+')]
    print('  A   %d 条' % cnt.get('A', 0)); print('  B   %d 条' % cnt.get('B', 0)); print('  C+  %d 条' % cnt.get('C+', 0)); print('  C-  %d 条' % cnt.get('C-', 0))
    print('  可靠集(A+B+C+) : %d 条' % len(rel)); print('  唯一台词       : %d 条' % len(set(x['台词'].strip() for x in rel)))
    print('\n=== 对照组（量化污染率）==='); qset = set(x['台词'].strip() for x in rel); overlap_total = 0
    for role in CONTRAST_ROLES:
        if role == CHAR: continue
        rl = [x for x in collect(books, role) if x['级'] in ('A', 'B', 'C+')]; oq = set(x['台词'].strip() for x in rl); ov = len(qset & oq); overlap_total += ov
        print('  %-12s 可靠集 %5d 条 | 与主角重叠 %d 条' % (role, len(rl), ov))
    pollution = (overlap_total / len(rel) * 100) if rel else 0
    print('  主角可靠集与对照组重叠 : %d 条' % overlap_total); print('  估算真污染率           : %.2f%%' % pollution); print('  ★ 还要人工抽检 30–40 条给准确率，两个数一起给')
    sample_n = min(40, len(rel)); random.seed(42); sample = random.sample(rel, sample_n) if rel else []
    print('\n=== 人工抽检样本（%d 条，请逐条核对是不是他说的）===' % sample_n)
    for i, item in enumerate(sample, 1): print('%3d. [%s] %s (%s)' % (i, item['级'], item['台词'][:60], item['source_locator']))
    path = os.path.join(OUT, '%s台词_分级.json' % CHAR); json.dump(final, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1); print('\n写入:', path); print('★ 可靠集 = A + B + C+；C- 单列说明，不进统计。'); print('★ v3 已写入角色级证据：说话人、原文文件、原文行、台词行、source_locator、置信度。'); return 0


if __name__ == '__main__':
    sys.exit(main())
