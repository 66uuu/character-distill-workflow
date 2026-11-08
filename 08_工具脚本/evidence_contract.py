# -*- coding: utf-8 -*-
"""v3 角色级证据契约：验证台词属于目标角色，而不只是出现在原文。"""
from __future__ import annotations
import json, os, sys
from pathlib import Path
def _env(name, default=None): return os.environ.get(name) or default
def speech_path():
    root = Path(_env("DISTILL_ROOT", str(Path(__file__).resolve().parents[1]))); stats = Path(_env("DISTILL_STATS", str(root / "02_核验" / "_stats"))); char = _env("DISTILL_CHAR", "角色名")
    return Path(_env("DISTILL_SPEECH_JSON", str(stats / f"{char}台词_分级.json")))
def check(items, character):
    if not isinstance(items, list): return ["台词分级文件必须是数组"]
    errors = []
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict): errors.append(f"第 {index} 条不是对象"); continue
        if item.get("级") not in {"A", "B", "C+"}: continue
        if item.get("说话人") != character: errors.append(f"第 {index} 条说话人不是目标角色")
        if not str(item.get("台词", "")).strip(): errors.append(f"第 {index} 条台词为空")
        if not item.get("原文文件"): errors.append(f"第 {index} 条缺原文文件")
        if not isinstance(item.get("原文行"), int) or item["原文行"] < 1: errors.append(f"第 {index} 条缺有效原文行号")
        if ":" not in str(item.get("source_locator", "")): errors.append(f"第 {index} 条缺 source_locator")
        confidence = item.get("说话人置信度")
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1: errors.append(f"第 {index} 条说话人置信度非法")
    return errors
def selftest():
    good = [{"级": "A", "台词": "你好", "说话人": "秦风", "原文文件": "p1.txt", "原文行": 3, "source_locator": "p1.txt:3", "说话人置信度": 0.99}]
    assert not check(good, "秦风"); assert check([{**good[0], "说话人": "配角"}], "秦风")
    print("[selftest] PASS · 目标角色/文件/行号/定位符/置信度契约通过"); return 0
def main():
    if "--selftest" in sys.argv: return selftest()
    path = speech_path()
    if not path.is_file(): print("[FAIL] 找不到台词分级文件：", path); return 1
    try: items = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc: print("[FAIL] 台词分级 JSON 无法读取：", exc); return 1
    errors = check(items, _env("DISTILL_CHAR", "角色名"))
    for error in errors: print("[FAIL]", error)
    if errors: return 1
    print("[PASS] 角色级证据契约通过：", path); return 0
if __name__ == "__main__": raise SystemExit(main())
