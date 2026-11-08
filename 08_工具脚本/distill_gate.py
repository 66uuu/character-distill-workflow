# -*- coding: utf-8 -*-
"""【模板】distill_gate.py —— 统一质量门（一键串起全部离线校验器/模板）

★ 本文件是**技能包模板**，不是项目脚本。复制到 <项目>/02_核验/ 后改用。

为什么需要它：
    本工作流现在有 5 个校验器 + 3 套 S2/S4/S6 模板 + 2 套离线增强(nli_lite / character_drift)。
    散着跑容易漏、难验收。本脚本是"总闸"：把能在本机离线跑的校验一次性全跑，
    按七条铁律汇总成单一 PASS/FAIL + 风险清单，改完文档一键验收。

    分类逻辑：
      · 硬阻断(critical)：失败 → 整体 FAIL（selfcheck / scan_fabrication /
        verify_citations / evidence_linter——这几道漏了就是"零编造"破防）。
      · 旁路(non-critical)：失败 → 仅告警，不阻断（semantic_check / groundguard_check /
        speech_crosscheck / style_fingerprint / nli_lite / character_drift——
        它们是"待人工复核线索"，报线索不判决）。

纯标准库。`--selftest` 反向验证：① 聚合逻辑单测 ② 集成跑全部组件的 --selftest 全绿。

用法：
    set DISTILL_ROOT=<D盘>\\UserFiles\\Desktop\\<项目名>_人物蒸馏
    python distill_gate.py            # 跑全部离线校验，出总报告
    python distill_gate.py --selftest # 验证总闸自身健康
"""

import os
import sys
import json
import subprocess

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))

# 注册表：脚本名, 阶段, 是否硬阻断(失败→整体 FAIL)
CHECKERS = [
    ("selfcheck.py",         "S7", True),
    ("scan_fabrication.py",  "S7", True),
    ("verify_citations.py",  "S7", True),
    ("evidence_linter.py",   "S6", True),
    ("s0_gate.py",            "S0", True),
    ("evidence_contract.py",  "S2", True),
    ("semantic_check.py",    "S7", False),
    ("groundguard_check.py", "S7", False),
    ("speech_crosscheck.py", "S2", False),
    ("style_fingerprint.py", "S4", False),
    ("nli_lite.py",          "S7", False),
    ("character_drift.py",   "S2/S7", False),
    ("roleplay_eval.py",      "S10", False),
]

# 支持 --selftest 的组件（用于总闸自身健康检查）。
# 注意：semantic_check.py 的 --selftest 要调模型、且依赖项目语料，
# 不塞进总闸自检（在项目里单独跑 --selftest）。
_SELFTEST_SET = {
    'groundguard_check.py', 'speech_crosscheck.py',
    's0_gate.py', 'evidence_contract.py', 'roleplay_eval.py',
    'style_fingerprint.py', 'evidence_linter.py', 'nli_lite.py', 'character_drift.py',
}
SELFTEST_CAPABLE = [n for n, _, _ in CHECKERS if n in _SELFTEST_SET]


def _run_script(name, selftest=False):
    path = os.path.join(HERE, name)
    if not os.path.exists(path):
        return (2, '脚本缺失: ' + name, '')
    cmd = [sys.executable, path] + (['--selftest'] if selftest else [])
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=180)
        return (p.returncode, p.stdout.strip()[-200:], p.stderr.strip()[-120:])
    except Exception as e:  # noqa: BLE001
        return (2, '', str(e)[:120])


def aggregate(results):
    """results: list of dict(name,stage,critical,status,detail)。
    status∈{pass,fail,warn,missing,error}。返回 (verdict, fails, warns)。"""
    fails = [r for r in results if r['status'] in ('fail', 'missing', 'error') and r['critical']]
    warns = [r for r in results if r['status'] in ('fail', 'warn') and not r['critical']]
    return ('FAIL' if fails else 'PASS'), fails, warns


def run():
    results = []
    for name, stage, crit in CHECKERS:
        rc, out, err = _run_script(name, selftest=False)
        if rc == 0:
            status = 'pass'
        elif rc == 1:
            status = 'fail' if crit else 'warn'
        else:
            status = 'missing' if '缺失' in out else 'error'
        results.append({
            'name': name, 'stage': stage, 'critical': crit,
            'status': status, 'detail': (out or err)[:100],
        })
    verdict, fails, warns = aggregate(results)
    report = {
        'verdict': verdict,
        'critical_fail': [r['name'] for r in fails],
        'warnings': [r['name'] for r in warns],
        'results': results,
    }
    out_dir = os.environ.get('DISTILL_STATS') or HERE
    try:
        os.makedirs(out_dir, exist_ok=True)
        json.dump(report, open(os.path.join(out_dir, 'gate_report.json'), 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
    except Exception:  # noqa: BLE001
        pass
    print('=' * 50)
    print('统一质量门 distill_gate · 总 verdict = %s' % verdict)
    for r in results:
        print('  [%-5s] %-22s %-7s %s' % (r['status'].upper(), r['name'], r['stage'],
              '关键' if r['critical'] else '旁路'))
    if fails:
        print('关键失败: %s' % ', '.join(report['critical_fail']))
    if warns:
        print('旁路告警(需人工复核): %s' % ', '.join(report['warnings']))
    print('=' * 50)
    print('报告:', os.path.join(out_dir, 'gate_report.json'))
    return 0 if verdict == 'PASS' else 1


def selftest():
    print('=== distill_gate.py 反向验证 (--selftest) ===')
    ok = True
    # 1) 全绿→PASS（含旁路告警不阻断）
    v, _, _ = aggregate([
        {'name': 'a', 'stage': 'S7', 'critical': True, 'status': 'pass'},
        {'name': 'b', 'stage': 'S7', 'critical': False, 'status': 'warn'},
    ])
    if v != 'PASS':
        print('[FAIL] 全绿应 PASS: %s' % v); ok = False
    # 2) 关键失败→FAIL
    v, _, _ = aggregate([
        {'name': 'a', 'stage': 'S7', 'critical': True, 'status': 'pass'},
        {'name': 'c', 'stage': 'S7', 'critical': True, 'status': 'fail'},
    ])
    if v != 'FAIL':
        print('[FAIL] 关键失败应 FAIL: %s' % v); ok = False
    # 3) 非关键失败→仍 PASS（仅告警）
    v, _, _ = aggregate([
        {'name': 'a', 'stage': 'S7', 'critical': True, 'status': 'pass'},
        {'name': 'b', 'stage': 'S7', 'critical': False, 'status': 'fail'},
    ])
    if v != 'PASS':
        print('[FAIL] 非关键失败应仍 PASS: %s' % v); ok = False
    # 4) 集成：组件 --selftest 全绿
    comp_ok = True
    for name in SELFTEST_CAPABLE:
        rc, out, err = _run_script(name, selftest=True)
        if rc != 0:
            comp_ok = False
            print('  [组件未通过] %s rc=%s' % (name, rc))
    if not comp_ok:
        print('[FAIL] 组件 selftest 未全绿'); ok = False
    if ok:
        print('[PASS] 聚合逻辑正确 + 全部组件 selftest 绿 (%d 个)' % len(SELFTEST_CAPABLE))
        return 0
    return 1


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()
    sys.exit(selftest() if a.selftest else run())
