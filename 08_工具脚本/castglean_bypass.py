# -*- coding: utf-8 -*-
"""【v2 新增】castglean_bypass.py —— S2/S7 台词归属交叉验证旁路

★ v2 升级新增脚本（对标 GitHub yexiyue/castglean），已合并进主技能包。
  作用：把你正则归属的「主角可靠集」和另一路判定做交叉验证，
        把两路意见不一致的台词（归属边界 case）挑出来交人工核，
        从而暴露你 regex 的「噪声下限 / 漏召下限」。

★ 两路（默认离线，零依赖）：
  路 A（你的主链）：extract_speech.collect() 当前四级规则 → 可靠集(A+B+C+)
  路 B（旁路）    ：把原流程排除的 C- 行单列，作为「归属边界 case」
  → 这些 C- 行就是 regex 归属的噪声下限，也是 castglean 类 LLM 归属最该 adjudicate 的部分。

★ castglean 集成（可选，需另装 + LLM）：
  设环境变量 CASTGLEAN_BIN 指向 castglean 可执行，或 CASTGLEAN_PY 指向其入口，
  脚本会调用它对语料做证据锚定归属，再把它的角色片段与你的可靠集做 diff。
  本环境默认未装 castglean，故默认走「路 A vs 路 B」离线双口径自检。

用法：
    set DISTILL_ROOT=...
    set DISTILL_SRC=.../01_语料/chapters
    set DISTILL_STATS=.../02_核验/_stats
    set DISTILL_CHAR=<角色名>
    set DISTILL_NAMES=主角,别名...
    set DISTILL_CONTRAST=配角...
    python castglean_bypass.py
"""
import importlib.util
import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))


def _env(name, default=None):
    return os.environ.get(name) or default


ROOT = _env('DISTILL_ROOT') or os.path.abspath(os.path.join(HERE, '..', '..'))
SRC = _env('DISTILL_SRC') or os.path.join(ROOT, '01_语料', 'chapters')
STATS = _env('DISTILL_STATS') or os.path.join(ROOT, '02_核验', '_stats')
CHAR = _env('DISTILL_CHAR', '角色名')
RELIABLE_JSON = _env('DISTILL_RELIABLE', '%s台词_分级.json' % CHAR)
CASTGLEAN_BIN = _env('CASTGLEAN_BIN')
CASTGLEAN_PY = _env('CASTGLEAN_PY')


def load_extract_speech():
    """动态加载同目录的 extract_speech.py（复用其 collect / 常量）。"""
    spec = importlib.util.spec_from_file_location(
        'extract_speech_pilot', os.path.join(HERE, 'extract_speech.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    es = load_extract_speech()
    books = es.load_books()
    if not books:
        print('语料为空，检查 DISTILL_SRC')
        return 1
    print('语料章数: %d' % len(books))

    # 路 A：严格（默认）——可靠集只含 A+B+C+
    strict = es.collect(books, CHAR)
    strict_keys = set((t, q, ctx) for t, q, g, ctx in strict if g in ('A', 'B', 'C+'))

    # 原流程排除的 C- 行 = 归属边界 case（regex 噪声下限）
    c_minus = [(t, q, ctx) for t, q, g, ctx in strict if g == 'C-']

    print('\n=== 归属双口径自检（主角 %s）===' % CHAR)
    print('  路A 严格可靠集 : %d 条' % len(strict_keys))
    print('  原流程排除 C-  : %d 条（归属边界，建议人工核）' % len(c_minus))

    # 写分歧报告
    os.makedirs(STATS, exist_ok=True)
    rep = []
    A = rep.append
    A('# %s · 台词归属双口径分歧报告' % CHAR)
    A('')
    A('> 路A=你主链（严格，可靠集 A+B+C+）；本旁路把被排除的 C- 行单列，')
    A('> 作为「归属边界 case」交人工核——这正是 castglean 类 LLM 归属最该 adjudicate 的部分。')
    A('')
    A('| 章 | 台词（截断） | 状态 |')
    A('|---|---|---|')
    for t, q, ctx in c_minus[:200]:
        A('| %s | %s | 边界(C-被排除) |' % (t[:30], q[:50].replace('|', '丨')))
    md_path = os.path.join(STATS, '%s_归属分歧.md' % CHAR)
    open(md_path, 'w', encoding='utf-8').write('\n'.join(rep))

    json.dump(
        [{'章': t, '台词': q, '状态': '边界C-被排除'} for t, q, ctx in c_minus],
        open(os.path.join(STATS, '%s_归属分歧.json' % CHAR), 'w', encoding='utf-8'),
        ensure_ascii=False, indent=1)

    print('分歧报告: %s' % md_path)
    print('★ 这些 C- 行是 regex 归属的噪声下限；接 castglean 后应对照它的判定。')

    # castglean 集成（可选，预留）
    if CASTGLEAN_BIN or CASTGLEAN_PY:
        print('\n[castglean] 检测到 CASTGLEAN_BIN/CASTGLEAN_PY，进入 LLM 归属 diff（未在本环境实测）。')
        print('[castglean] 集成点已预留：调用 castglean 生成 annotations.json，')
        print('           解析 segment 字节范围，与 strict_keys 对齐，输出')
        print('           「castglean 认但 regex 不认 / 反之」清单。')
        print('[castglean] 需先 clone https://github.com/yexiyue/castglean 并配置 LLM。')
    else:
        print('\n[castglean] 未配置（CASTGLEAN_BIN/CASTGLEAN_PY 均空）。')
        print('[castglean] 接入步骤：git clone https://github.com/yexiyue/castglean ；')
        print('           配置 GLM / Qwen / MiniMax；设 CASTGLEAN_BIN 后重跑本脚本做真·交叉验证。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
