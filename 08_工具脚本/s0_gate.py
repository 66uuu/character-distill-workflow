# -*- coding: utf-8 -*-
"""S0 专业透视档案完成门：只验结构、证据和非诊断边界。"""
from __future__ import annotations
import json, os, re, sys
from pathlib import Path
LENSES = ["逻辑学", "心理学", "犯罪学", "病理学", "刑侦学", "测写师", "经济学"]
REQUIRED = ["核心驱动力", "典型情境默认反应", "盲点与脆弱点"]
DIAGNOSIS_WORDS = ("患有", "诊断为", "临床诊断", "DSM-", "人格障碍")
def _path():
    if os.environ.get("DISTILL_S0_JSON"): return Path(os.environ["DISTILL_S0_JSON"])
    root = Path(os.environ.get("DISTILL_ROOT", Path(__file__).resolve().parents[1]))
    return root / "03_交付物" / f"{os.environ.get('DISTILL_CHAR', '角色名')}_专业透视档案.json"
def validate(data):
    errors = []; lenses = data.get("镜头") if isinstance(data, dict) else None
    if not isinstance(lenses, list): return ["缺少镜头数组"]
    found = {x.get("镜头") for x in lenses if isinstance(x, dict)}
    for name in LENSES:
        if name not in found: errors.append(f"缺少镜头：{name}")
    for item in lenses:
        if not isinstance(item, dict) or item.get("镜头") not in LENSES: continue
        name = item["镜头"]; usable = False
        for dim in item.get("分析维度") or []:
            if not isinstance(dim, dict): errors.append(f"{name} 存在非法分析维度"); continue
            conclusion = str(dim.get("结论", "")).strip(); status = str(dim.get("证据状态", "")).strip(); evidence = str(dim.get("证据标注", "")).strip()
            if conclusion or status == "不适用": usable = True
            if conclusion and not re.search(r"【(直引|统计|推断)", evidence): errors.append(f"{name}/{dim.get('维度', '未命名')} 缺证据标注")
        if not usable: errors.append(f"{name} 没有已填写结论或不适用裁定")
    summary = data.get("综合侧写") or {}
    for key in REQUIRED:
        if not str(summary.get(key, "")).strip(): errors.append(f"综合侧写缺少：{key}")
    raw = json.dumps(data, ensure_ascii=False)
    if "病理学" in found and ("非真实" not in raw or "诊断" not in raw): errors.append("病理学镜头缺少非真实诊断声明")
    for word in DIAGNOSIS_WORDS:
        if word in raw: errors.append(f"疑似真实诊断用语：{word}")
    return errors
def selftest():
    good = {"镜头": [{"镜头": n, "分析维度": [{"维度": "x", "结论": "事实", "证据状态": "已填", "证据标注": "【推断】"}]} for n in LENSES], "综合侧写": {"核心驱动力": "a", "典型情境默认反应": "b", "盲点与脆弱点": "c", "非诊断声明": "非真实诊断"}}
    assert not validate(good); assert validate({**good, "镜头": good["镜头"][:-1]})
    print("[selftest] PASS · 七镜头/证据/综合侧写/非诊断规则通过"); return 0
def main():
    if "--selftest" in sys.argv: return selftest()
    path = _path()
    if not path.is_file(): print("[FAIL] 找不到 S0 档案：", path); return 1
    try: data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc: print("[FAIL] S0 JSON 无法读取：", exc); return 1
    errors = validate(data)
    for error in errors: print("[FAIL]", error)
    if errors: return 1
    print("[PASS] S0 专业透视档案通过：", path); return 0
if __name__ == "__main__": raise SystemExit(main())
