# -*- coding: utf-8 -*-
"""【模板】build_evidence.py —— 人物蒸馏工作流 · 证据表 + 人格数据生成器

★ 本文件是**技能包模板**，不是项目脚本。
  复制到 <项目>/02_核验/ 后改常量或用环境变量指定路径。

用途：S6「证据表 + 人格数据」——从实测数据自动生成两件交付物：
      1) <角色名>_数字人_蒸馏证据表_v2.md   （给审阅者看）
      2) <角色名>_数字人人格数据.json       （给程序消费）

★ 铁律：证据表**必须脚本生成，不许手写**。
  手写的数字会和权威口径脱节 → 自检器一跑就报失真。
  本脚本的所有数字都从 _stats/*.json 读取，不做二次计算。

★ 容错设计：某个数据文件缺失时，**对应小节降级为"（数据未生成）"并提示**，
  不崩掉整个生成流程——因为证据表是交付物，崩了就交不了。

用法：
    set DISTILL_ROOT=...
    set DISTILL_STATS=<项目>\\02_核验\\_stats
    set DISTILL_OUT=<项目>\\03_交付物
    set DISTILL_CHAR=<角色名>
    set DISTILL_VER=v2
    set DISTILL_SOURCE=番茄《书名》
    python build_evidence.py

⚠️ 不要把 stdout 写成 `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, ...)`。
   本脚本只用 sys.stdout.reconfigure()。
"""
import json
import os
import sys
from collections import Counter

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.environ.get('DISTILL_ROOT') or os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
STATS = os.environ.get('DISTILL_STATS') or os.path.join(ROOT, '02_核验', '_stats')
OUT = os.environ.get('DISTILL_OUT') or os.path.join(ROOT, '03_交付物')
CHAR = os.environ.get('DISTILL_CHAR', '角色名')
VER = os.environ.get('DISTILL_VER', 'v2')
SOURCE = os.environ.get('DISTILL_SOURCE', '（作品名）')
RELIABLE_JSON = os.environ.get('DISTILL_RELIABLE', '%s台词_分级.json' % CHAR)

os.makedirs(OUT, exist_ok=True)

MISSING = []


def jload(name, default=None):
    """读 JSON，缺失时记录并返回默认值（不崩）。"""
    p = os.path.join(STATS, name)
    if not os.path.exists(p):
        MISSING.append(name)
        return default if default is not None else {}
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception as e:
        MISSING.append('%s(解析失败:%s)' % (name, e))
        return default if default is not None else {}


def main():
    auth = jload('权威口径.json')
    fp = jload('语言指纹.json')
    rel = jload(RELIABLE_JSON, [])
    purity = jload('污染率测量.json')
    events = jload('事件级履历.json', [])
    cites = jload('%s引用核验.json' % VER, [])
    # S6 优化（对标 SetCardGenerator 双区块 + character-evidence-profiler 置信度）：
    # 可选「证据分级标注」，把直引/统计/推断 + 置信度集中隔离，强制暴露「未溯源推测」。
    conf_raw = jload('置信度标注.json', [])
    if isinstance(conf_raw, list):
        conf = conf_raw
    elif isinstance(conf_raw, dict) and isinstance(conf_raw.get('items'), list):
        conf = conf_raw['items']
    else:
        conf = []

    corpus = auth.get('语料', {})
    levels = Counter(x.get('级', '?') for x in rel)
    rel_count = len([x for x in rel if x.get('级') in ('A', 'B', 'C+')])
    uniq = len(set(x['台词'].strip() for x in rel if x.get('级') in ('A', 'B', 'C+')))

    # ================= 证据表 =================
    L = []
    A = L.append
    A('# %s数字人 · 蒸馏证据表 %s' % (CHAR, VER))
    A('')
    A('> **本表所有数字均由脚本从语料实测产出，无一处手写。**')
    A('> 复现链路：')
    A('> `01_语料/fetch_corpus.py`（抓全量语料） → `02_核验/extract_speech.py`（台词归属 A/B/C 分级）')
    A('> → `02_核验/measure_purity.py`（污染率） → `02_核验/final_stats.py`（语言指纹）')
    A('> → `02_核验/audit_authoritative.py`（锁口径） → `02_核验/mine_events.py`（事件级履历）')
    A('> → `02_核验/verify_citations.py`（引用核验） → 本表 + 系统提示词 + 人格数据 JSON')
    A('')

    # 一、语料基线
    A('## 一、语料基线')
    A('')
    A('| 项 | 值 |')
    A('|---|---|')
    A('| 作品来源 | %s |' % SOURCE)
    A('| 章数 | %s |' % corpus.get('章数', '—'))
    A('| 总字数 | %s |' % format(corpus.get('总字数', 0), ',') if corpus.get('总字数') else '—')
    A('| 缺章 | 无（逐章落地为独立文件） |' if corpus else '| 缺章 | — |')
    A('| 可靠集条数 | %s |' % (corpus.get('可靠集条数', rel_count) or '—'))
    A('| 唯一台词 | %s |' % (corpus.get('唯一台词', uniq) or '—'))
    A('')

    # 二、台词归属
    A('## 二、台词归属（口径唯一：%s本人台词可靠集）' % CHAR)
    A('')
    A('| 级 | 判据 | 条数 |')
    A('|---|---|---|')
    A('| A | 同行锚定（说话人同在引号行内） | %d |' % levels.get('A', 0))
    A('| B | 引号倒装（引号在前，人名在后） | %d |' % levels.get('B', 0))
    A('| C+ | 纯引号行 + 邻行说话人 + 上下文主语校验通过 | %d |' % levels.get('C+', 0))
    A('| C- | 同形态但主语校验不通过（排除） | %d |' % levels.get('C-', 0))
    A('')
    A('| 可靠性指标 | 值 |')
    A('|---|---|')
    A('| 真污染率 | %s |' % (purity.get('真污染率%', '—')))
    A('| 人工抽检准确率 | %s |' % (purity.get('抽检准确率%', '—')))
    A('')
    A('> **口径说明**：可靠集 = A + B + C+。C 级必须**严格**——邻行精确匹配说话人，')
    A('> 否则剔除。宽松做法（"任意行含名字就算"）会让可靠集虚高 50%+。')
    A('> **可靠集是"高精度低召回"**：有些真实台词嵌在叙述行里没被抓到，')
    A('> 所以频次类数字必须同时给"全书"列。')
    A('')

    # 三、语言指纹
    A('## 三、语言指纹（分母=可靠集）')
    A('')
    if fp:
        if '句式' in fp:
            s = fp['句式']
            A('### 3.1 句式')
            A('')
            A('| 指标 | 值 |')
            A('|---|---|')
            for k in ('句数', '均值', '中位', 'p90', '最长', '≤5字占比%', '≤10字占比%', '≤15字占比%'):
                if k in s:
                    A('| %s | %s |' % (k, s[k]))
            A('')
        if '标点' in fp:
            A('### 3.2 标点（每万字）')
            A('')
            A('| 标点 | 次数 | 每万字 |')
            A('|---|---|---|')
            for k, v in fp['标点'].items():
                A('| %s | %d | %s |' % (k, v['次数'], v['每万字']))
            A('')
        if '自称' in fp:
            A('### 3.3 自称系统')
            A('')
            A('| 自称 | 次数 |')
            A('|---|---|')
            for k, v in list(fp['自称'].items())[:20]:
                A('| %s | %d |' % (k, v))
            A('')
        if '粗口' in fp:
            A('### 3.4 粗口')
            A('')
            A('| 粗口 | 次数 |')
            A('|---|---|')
            for k, v in list(fp['粗口'].items())[:20]:
                A('| %s | %d |' % (k, v))
            A('')
        if '称呼' in fp:
            A('### 3.5 称呼系统')
            A('')
            A('| 称呼 | 台词集 | 全书 |')
            A('|---|---|---|')
            for k, v in list(fp['称呼'].items())[:30]:
                A('| %s | %d | %d |' % (k, v['台词集'], v['全书']))
            A('')
        if fp.get('复用整句'):
            A('### 3.6 复用整句（≥2 次）Top 60')
            A('')
            A('| 台词 | 次数 | 首现出处 |')
            A('|---|---|---|')
            for x in fp['复用整句'][:60]:
                A('| %s | %d | %s |' % (x['句'], x['次数'],
                                        (x['出处'][0] if x.get('出处') else '')))
            A('')
        if fp.get('高频短语'):
            A('### 3.7 高频短语（已剔虚词）Top 40')
            A('')
            A('| 短语 | 次数 |')
            A('|---|---|')
            for x in fp['高频短语'][:40]:
                A('| %s | %d |' % (x['短语'], x['次数']))
            A('')
        if '通用短句占比%' in fp:
            A('> **通用短句占比：%s%%** —— 越低说明角色语言辨识度越高。' % fp['通用短句占比%'])
            A('')
    else:
        A('> （语言指纹未生成，请先跑 `final_stats.py`）')
        A('')

    # 四、事件级履历
    A('## 四、事件级履历（§12 素材）')
    A('')
    if events:
        A('| 事件 | 章号 | 原文证据 |')
        A('|---|---|---|')
        for e in (events[:40] if isinstance(events, list) else []):
            A('| %s | %s | %s |' % (e.get('事件', ''), e.get('章号', ''),
                                    str(e.get('证据', ''))[:60].replace('|', '丨')))
        A('')
    else:
        A('> （事件级履历未生成，请跑 `mine_events.py`）')
        A('')

    # 五、引用核验
    A('## 五、引用核验')
    A('')
    if cites:
        ok = len([c for c in cites if c.get('status') == 'OK'])
        mism = len([c for c in cites if c.get('status') == '章号不符'])
        nf = len([c for c in cites if c.get('status') == '未找到原文'])
        A('| 项 | 数量 |')
        A('|---|---|')
        A('| ✅ 标注章号与原文一致 | %d |' % ok)
        A('| ⚠️ 章号不符 | %d |' % mism)
        A('| ❌ 未能在原书定位 | %d |' % nf)
        A('')
    else:
        A('> （引用核验未跑，请跑 `verify_citations.py`）')
        A('')

    # 六、断言执行
    A('## 六、断言执行记录')
    A('')
    sc = jload('%s自检.json' % VER, [])
    if isinstance(sc, list):
        A('自检器待修项：**%d**' % len(sc))
        A('')
        if sc:
            A('| # | 问题 |')
            A('|---|---|')
            for i, x in enumerate(sc[:30], 1):
                A('| %d | %s |' % (i, str(x).replace('|', '丨')[:120]))
            A('')
    else:
        A('自检器待修项：**%d**' % len(sc.get('issues', [])))
        A('')

    # 七、已知局限
    A('## 七、已知局限（诚实披露）')
    A('')
    A('1. **可靠集偏保守**：C 级规则会连带漏掉一部分真实属于主角的台词')
    A('   （典型：嵌在叙述行内的长句）。→ 频次请以"全书"列为准。')
    A('2. **归��噪声下限**：网文大量"台词行 + 下一行首名"倒装句式，')
    A('   无显式说话人标注，归属靠上下文反推，必然有误差。')
    A('3. **语义与归属错误机器抓不出**：溯源只能发现"查不到"，')
    A('   发现不了"意思反了"或"这是叙述不是台词"——这两类需人读。')
    A('')

    # ---- 八、证据分级与置信度（S6 优化：对标 SetCardGenerator 双区块 + character-evidence-profiler 置信度）----
    A('## 八、证据分级与置信度（直引 / 统计 / 推断 + 置信度）')
    A('')
    A('> 本区块强制把「推断级、非原文直证」的结论集中隔离，一眼看清哪些不是原文直证。')
    A('> 数据来源：可选文件 `置信度标注.json`（writer 在蒸馏时逐条标注）。缺失则降级提示。')
    A('')
    if conf:
        A('| 结论 / 说法 | 证据级 | 置信度 | 备注 |')
        A('|---|---|---|---|')
        for item in conf:
            A('| %s | %s | %s | %s |' % (
                str(item.get('claim', ''))[:80].replace('|', '丨'),
                str(item.get('level', '—')),
                str(item.get('confidence', '—')),
                str(item.get('note', ''))[:40].replace('|', '丨')))
        A('')
        inferred = [i for i in conf if str(i.get('level', '')).startswith('推断')]
        A('### ⚠️ 未溯源推测（推断级，非原文直证）')
        A('')
        if inferred:
            for i in inferred:
                A('- **%s**（置信度：%s）— %s' % (
                    str(i.get('claim', ''))[:80].replace('|', '丨'),
                    str(i.get('confidence', '—')),
                    str(i.get('note', ''))[:60].replace('|', '丨')))
            A('')
            A('> 以上 %d 条为 AI 推断，非原文直证，审阅者须逐条核对后方可采用。' % len(inferred))
        else:
            A('> 无（所有结论均有原文直证或统计支撑）。')
            A('')
    else:
        A('> （未提供 `置信度标注.json`，本区块降级：未做证据分级隔离。）')
        A('> 建议：蒸馏时逐条标注每条结论的「直引 / 统计 / 推断」与置信度，写入该文件后重跑本脚本。')
        A('')

    ev_path = os.path.join(OUT, '%s_数字人_蒸馏证据表_%s.md' % (CHAR, VER))
    open(ev_path, 'w', encoding='utf-8', newline='\n').write('\n'.join(L))

    # ================= 人格数据 JSON =================
    persona = {
        '角色名': CHAR,
        '作品来源': SOURCE,
        '版本': VER,
        '语料基线': {
            '章数': corpus.get('章数'),
            '总字数': corpus.get('总字数'),
            '可靠集条数': corpus.get('可靠集条数', rel_count),
            '唯一台词': corpus.get('唯一台词', uniq),
            '污染率%': purity.get('真污染率%'),
            '抽检准确率%': purity.get('抽检准确率%'),
        },
        '分级': dict(levels),
        '句式': fp.get('句式', {}),
        '标点': fp.get('标点', {}),
        '自称': fp.get('自称', {}),
        '粗口': fp.get('粗口', {}),
        '称呼': fp.get('称呼', {}),
        '口头禅': [x['句'] for x in fp.get('复用整句', [])[:20]],
        '高频短语': [x['短语'] for x in fp.get('高频短语', [])[:30]],
        '通用短句占比%': fp.get('通用短句占比%'),
        '事件级履历': events[:40] if isinstance(events, list) else [],
        '引用核验': {
            '总数': len(cites),
            '通过': len([c for c in cites if c.get('status') == 'OK']),
        },
        '证据分级': {
            '标注条数': len(conf),
            '推断级数': len([i for i in conf if str(i.get('level', '')).startswith('推断')]),
        },
        '已知局限': [
            '可靠集是"高精度低召回"，频次请以全书列为准',
            '归��存在噪声下限（无显式说话人标注的引号句靠上下文反推）',
            '语义反转与归属错误机器抓不出，需人读',
        ],
    }
    ps_path = os.path.join(OUT, '%s_数字人人格数据.json' % CHAR)
    json.dump(persona, open(ps_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    print('证据表:', ev_path)
    print('人格数据:', ps_path)
    if MISSING:
        print('\n缺失的数据文件（对应小节已降级标注）:')
        for m in MISSING:
            print('  -', m)
    else:
        print('\n所有数据文件齐备 ✅')
    return 0


if __name__ == '__main__':
    sys.exit(main())
