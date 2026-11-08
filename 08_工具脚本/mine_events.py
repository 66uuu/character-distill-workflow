# -*- coding: utf-8 -*-
"""【模板】mine_events.py —— 人物蒸馏工作流 · 事件级履历挖掘器

★ 本文件是**技能包模板**，不是项目脚本。
  复制到 <项目>/02_核验/ 后改 EVENTS 锚点表。

用途：S4/S5 的 §12「亲身履历层」素材。
      把**梗概级履历**升级为**事件级记忆**——
      梗概级："从小被逐出家族"（不够）
      事件级："我八岁那年把至尊骨抽出来的时候，他才五岁。"（事件 + 章号 + 原话）

★ 方法：按关键词锚点扫描全书，找出主角的关键事件节点（章号 + 事件 + 原文证据）。
  锚点表必须**按本书重写**——这是本脚本唯一需要手工的部分。
  写锚点的方法：先扫一遍全书找出"转折性"的关键词
  （捡到/失去/背叛/觉醒/突破/死亡/离别…），再逐个看上下文确认是主角相关。

用法：
    set DISTILL_ROOT=...
    set DISTILL_STATS=<项目>\\02_核验\\_stats
    set DISTILL_CHAR=<角色名>
    python mine_events.py
    → 输出 _stats/事件级履历.json

⚠️ 不要把 stdout 写成 `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, ...)`。
   本脚本只用 sys.stdout.reconfigure()。
"""
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.environ.get('DISTILL_ROOT') or os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
SRC = os.environ.get('DISTILL_SRC') or os.path.join(ROOT, '01_语料', 'chapters')
STATS = os.environ.get('DISTILL_STATS') or os.path.join(ROOT, '02_核验', '_stats')
CHAR = os.environ.get('DISTILL_CHAR', '角色名')
RELIABLE_JSON = os.environ.get('DISTILL_RELIABLE', '%s台词_分级.json' % CHAR)

os.makedirs(STATS, exist_ok=True)

# ===== 事件锚点表：按本书重写 =====
# (事件名, 触发关键词列表)
EVENTS = [
    # ('穿越/重生', ['穿越', '重生', '回炉再造']),
    # ('绑定系统', ['系统', '叮咚']),
    # ('被逐出家族', ['逐出', '逐出家门', '赶出']),
]
# 每个事件最多取几条证据
MAX_PER_EVENT = 6
# ==================================

NOISE = re.compile(
    r"^(阅读模式|原网页|上一章|下一章|目录|返回|加入书架|举报|分享|APP|"
    r"番茄小说|正在加载|加入书签|字体|背景|章节报错|举报本章|"
    r"书页|首页|上一|下一|加入|字体大小|背景颜色|手机版|电脑版|"
    r"第[一二三四五六七八九十百千0-9]+章.*|.*本章.*|完结撒花.*|"
    r"请记住本书首发域名.*|.*首发域名.*|www\..*|.*笔趣阁.*)$")


def load_books():
    res = []
    if not os.path.isdir(SRC):
        print('!! 找不到语料目录:', SRC)
        return res
    fns = [f for f in os.listdir(SRC) if f.endswith('.txt')]
    fns.sort(key=lambda x: int(re.match(r'p(\d+)\.txt', x).group(1))
             if re.match(r'p(\d+)\.txt', x) else 0)
    for fn in fns:
        m = re.match(r'p(\d+)\.txt', fn)
        raw = open(os.path.join(SRC, fn), encoding='utf-8', errors='replace').read()
        lines = raw.split('\n')
        title = lines[0].strip() if lines else fn
        body = [l.strip() for l in lines[1:] if l.strip() and not NOISE.match(l.strip())]
        res.append((title, body, int(m.group(1)) if m else 0))
    return res


def main():
    books = load_books()
    if not books:
        return 1
    if not EVENTS:
        print('!! EVENTS 锚点表是空的——必须按本书重写后重跑。')
        print('   提示：先扫全书找"转折性"关键词（捡到/失去/背叛/觉醒/突破/死亡/离别…），')
        print('   再逐个看上下文确认是主角相关。')
        return 1

    # 主角台词集（用于判断证据是不是"他说出口的"）
    rel = []
    rp = os.path.join(STATS, RELIABLE_JSON)
    if os.path.exists(rp):
        rel = json.load(open(rp, encoding='utf-8'))
        rel = [x for x in rel if x.get('级') in ('A', 'B', 'C+')]
    rel_set = set(x['台词'].strip() for x in rel)

    out = []
    for ev_name, kws in EVENTS:
        hits = []
        for title, lines, pid in books:
            for i, l in enumerate(lines):
                if not any(k in l for k in kws):
                    continue
                # 优先取主角说出口的台词作为证据
                q = ''
                for j in (i, i + 1, i - 1):
                    if 0 <= j < len(lines):
                        m = re.search(r'[「"“]([^」"”]{4,80})[」"”]', lines[j])
                        if m and m.group(1).strip() in rel_set:
                            q = m.group(1).strip()
                            break
                if not q:
                    # 退而求其次：取含关键词的整行
                    q = l[:80]
                hits.append({'章号': pid, '章': title, '证据': q,
                             '是主角台词': bool(q in rel_set)})
                if len(hits) >= MAX_PER_EVENT:
                    break
            if len(hits) >= MAX_PER_EVENT:
                break
        if hits:
            out.append({'事件': ev_name, '关键词': kws,
                        '命中': len(hits), '条目': hits})
            print('%-16s 命中 %d 条' % (ev_name, len(hits)))

    path = os.path.join(STATS, '事件级履历.json')
    json.dump(out, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('\n事件数: %d' % len(out))
    print('写入:', path)
    print('★ 素材质量取决于锚点表质量——写完锚点要抽查 2–3 条看上下文对不对。')
    print('★ 优先用"是主角台词=True"的证据，那是他说出口的。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
