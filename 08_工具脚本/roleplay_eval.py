# -*- coding: utf-8 -*-
"""S10 角色扮演回归评测器，不调用模型，只消费结构化评分。"""
from __future__ import annotations
import json, os, sys
from pathlib import Path
DIMENSIONS = ["identity", "memory", "reasoning", "voice", "relationship", "boundary"]
def evaluate(results):
    rows = []
    for row in results:
        scores = row.get("scores", {})
        try: clean = {key: float(scores[key]) for key in DIMENSIONS if key in scores}
        except (TypeError, ValueError): clean = {}
        if set(clean) != set(DIMENSIONS) or any(v < 0 or v > 5 for v in clean.values()): rows.append({"case_id": row.get("case_id"), "status": "invalid", "scores": clean}); continue
        average = sum(clean.values()) / len(DIMENSIONS); rows.append({"case_id": row.get("case_id"), "status": "pass" if average >= 4 else "fail", "average": round(average, 3), "scores": clean})
    valid = [row for row in rows if row["status"] != "invalid"]
    averages = {key: round(sum(row["scores"][key] for row in valid) / len(valid), 3) for key in DIMENSIONS} if valid else {}
    total = round(sum(averages.values()) / len(averages), 3) if averages else 0; passed = bool(valid) and len(valid) == len(rows) and total >= 4 and all(v >= 3 for v in averages.values())
    return {"verdict": "PASS" if passed else "FAIL", "cases": len(rows), "valid_cases": len(valid), "dimension_average": averages, "macro_average": total, "rows": rows}
def selftest():
    good = [{"case_id": "x", "scores": {key: 4 for key in DIMENSIONS}}]; assert evaluate(good)["verdict"] == "PASS"
    bad = [{"case_id": "x", "scores": {**{key: 4 for key in DIMENSIONS}, "voice": 2}}]; assert evaluate(bad)["verdict"] == "FAIL"
    print("[selftest] PASS · 六维评分/缺字段/阈值/总分聚合通过"); return 0
def main():
    if "--selftest" in sys.argv: return selftest()
    value = os.environ.get("DISTILL_EVAL_RESULTS")
    if not value:
        root = Path(os.environ.get("DISTILL_ROOT", Path(__file__).resolve().parents[1])); value = str(root / "03_交付物" / f"{os.environ.get('DISTILL_CHAR', '角色名')}_角色扮演评测结果.json")
    path = Path(value)
    if not path.is_file(): print("[WARN] 尚未提供角色扮演评测结果：", path); return 1
    try: data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc: print("[FAIL] 评测结果无法读取：", exc); return 1
    results = data.get("results") if isinstance(data, dict) else data
    if not isinstance(results, list): print("[FAIL] 评测结果必须是数组，或包含 results 数组"); return 1
    report = evaluate(results); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0 if report["verdict"] == "PASS" else 1
if __name__ == "__main__": raise SystemExit(main())
