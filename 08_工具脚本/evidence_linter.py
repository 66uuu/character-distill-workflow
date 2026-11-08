# -*- coding: utf-8 -*-
"""【模板】evidence_linter.py —— S6 证据表质量门（对标 SetCardGenerator / character-evidence-profiler）

★ 本文件是**技能包模板**，不是项目脚本。复制到 <项目>/02_核验/ 后改用。

为什么需要它：
    build_evidence.py 生成「证据表」+「人格数据 JSON」。本脚本是 S6 的**质量门**，
    把"零编造"在证据层落死：
      · 每条【推断】级结论必须带「置信度(高/中/低)」**且**「出处/章号」，否则判 ungraded_inference；
      · 必须存在「未溯源推测」区块，且要么列项、要么显式写"无"——杜绝"推断级混进直陈"；
      · 人格数据 JSON 必须是合法 JSON 且含预期顶层键（身份/性格/关系 至少其一）。

对应 SetCardGenerator 的「⚠️未溯源推测内容」区块 与 character-evidence-profiler 的
「置信度分级 + 源引用」思想。纯标准库。`--selftest` 反向验证。

用法：
    set DISTILL_ROOT=<D盘>\\UserFiles\\Desktop\\<项目名>_人物蒸馏
    set DISTILL_CHAR=<角色名>
    set DISTILL_EVIDENCE=<项目>\\03_交付物\\<角色名>_数字人_蒸馏证据表_v2.md
    set DISTILL_PERSONA=<项目>\\03_交付物\\<角色名>_数字人人格数据.json
    set DISTILL_STATS=<项目>\\02_核验\\_stats
    python evidence_linter.py
    python evidence_linter.py --selftest
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
CHAR = _env('DISTILL_CHAR', '角色')
EVID = _env('DISTILL_EVIDENCE') or os.path.join(
    ROOT, '03_交付物', '%s_数字人_蒸馏证据表_v2.md' % CHAR)
JSONF = _env('DISTILL_PERSONA') or os.path.join(
    ROOT, '03_交付物', '%s_数字人人格数据.json' % CHAR)
STATS = _env('DISTILL_STATS') or os.path.join(ROOT, '02_核验', '_stats')

CONF_MARK = ('置信度', '高', '中', '低', 'confidence', 'CONF')
INFER_RE = re.compile(r'【?推断】?|推断级', re.I)


def lint_evidence(md):
    issues = []
    # 1) 未溯源推测区块
    m = re.search(r'未溯源推测', md)
    if not m:
        issues.append({'type': 'missing_block',
                       'msg': '证据表缺"未溯源推测"区块'})
    else:
        end = md.find('\n##', m.start() + 1)
        seg = md[m.start(): end if end > 0 else m.start() + 600]
        has_wu = '无' in seg
        has_item = bool(re.search(r'^\s*[-*]|\n\s*[-*]|\n\s*\d+[.、]', seg, re.M))
        if not (has_wu or has_item):
            issues.append({'type': 'empty_block',
                           'msg': '"未溯源推测"区块存在但未列项也未写"无"'})
    # 2) 每条推断级必须带置信度 + 出处
    for i, line in enumerate(md.splitlines(), 1):
        if INFER_RE.search(line):
            has_conf = any(k in line for k in CONF_MARK)
            has_src = bool(re.search(
                r'p\s*\d+|章\s*\d+|第\s*\d+\s*章|出处|来源|依据|原文', line))
            if not (has_conf and has_src):
                miss = '置信度' if not has_conf else '出处'
                issues.append({'type': 'ungraded_inference', 'line': i,
                               'msg': '推断级结论缺%s：%s'
                               % (miss, line.strip()[:80])})
    return issues


def lint_json(path):
    if not os.path.exists(path):
        return [{'type': 'missing_json',
                 'msg': '人格数据 JSON 不存在: %s' % path}]
    try:
        d = json.load(open(path, encoding='utf-8'))
    except Exception as e:
        return [{'type': 'json_error', 'msg': '人格数据 JSON 解析失败: %s' % e}]
    if not isinstance(d, dict):
        return [{'type': 'json_shape', 'msg': '人格数据 JSON 顶层应为对象'}]
    if not any(k in d for k in ('身份', '性格', '关系')):
        return [{'type': 'json_keys',
                 'msg': '人格数据 JSON 缺预期顶层键(身份/性格/关系)'}]
    return []


def run():
    issues = []
    if os.path.exists(EVID):
        issues += lint_evidence(open(EVID, encoding='utf-8').read())
    else:
        print('[WARN] 证据表不存在: %s（跳过证据表检查）' % EVID)
    issues += lint_json(JSONF)
    payload = {'issue_count': len(issues), 'issues': issues}
    try:
        os.makedirs(STATS, exist_ok=True)
        out = os.path.join(STATS, 'evidence_lint.json')
        json.dump(payload, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    except Exception as e:  # noqa: BLE001
        out = os.path.join(tempfile.gettempdir(), '蒸馏evidence_lint_%s.json' % CHAR)
        json.dump(payload, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('[WARN] 默认目录不可写，报告降级到: %s (%s)' % (out, e))
    print('=' * 50)
    print('S6 证据表质量门')
    print('问题: %d' % len(issues))
    for x in issues:
        print('  [%s] %s' % (x['type'], x['msg']))
    print('=' * 50)
    print('报告:', out)
    return 1 if issues else 0


# ----------------------------------------------------------------------
GOOD_MD = """# 证据表
## 一、身份
秦风是反派。【直引】p12 原文"秦风冷笑"。
## 八、未溯源推测
- 秦风可能童年受创。【推断】置信度:中 出处 p120 提及"他从不提家人"
"""

BAD_MD = """# 证据表
## 一、身份
秦风是反派。【直引】p12
## 八、性格
秦风内心柔软。【推断】他其实很善良。
"""


def selftest():
    print('=== evidence_linter.py 反向验证 (--selftest) ===')
    ok = True
    g = lint_evidence(GOOD_MD)
    b = lint_evidence(BAD_MD)
    if g:
        print('[FAIL] 合规证据表不应有问题: %s' % g)
        ok = False
    if not any(x['type'] == 'ungraded_inference' for x in b):
        print('[FAIL] 未分级推断未被抓出')
        ok = False
    if not any(x['type'] == 'missing_block' for x in b):
        print('[FAIL] 缺未溯源推测区块未被抓出')
        ok = False
    if ok:
        print('[PASS] 合规表放行；违规表抓出(未分级推断 + 缺区块)')
        for x in b:
            print('   · [%s] %s' % (x['type'], x['msg']))
        return 0
    return 1


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()
    sys.exit(selftest() if a.selftest else run())
