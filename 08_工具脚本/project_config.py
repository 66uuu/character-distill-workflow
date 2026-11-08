# -*- coding: utf-8 -*-
"""v3 项目配置读取器。统一读取 project.config.json，环境变量优先。"""
from __future__ import annotations
import json, os
from pathlib import Path
from typing import Any

def _root() -> Path:
    value = os.environ.get("DISTILL_ROOT")
    return Path(value) if value else Path(__file__).resolve().parent.parent

def config_path() -> Path:
    value = os.environ.get("DISTILL_CONFIG")
    return Path(value) if value else _root() / "project.config.json"

def load_config() -> dict[str, Any]:
    path = config_path()
    if not path.is_file(): return {}
    try: data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): return {}
    return data if isinstance(data, dict) else {}

def get_from(data: dict[str, Any], path: str, default: Any = None) -> Any:
    value: Any = data
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value: return default
        value = value[part]
    return value

def get(path: str, default: Any = None) -> Any: return get_from(load_config(), path, default)
def env_or_config(env_name: str, config_path_name: str, default: Any = None) -> Any: return os.environ.get(env_name) or get(config_path_name, default)

def validate(data: dict[str, Any] | None = None) -> list[str]:
    data = load_config() if data is None else data
    if not data: return ["找不到 project.config.json"]
    errors = []
    if data.get("schema_version") != 1: errors.append("schema_version 必须为 1")
    if not get_from(data, "project.character"): errors.append("缺少 project.character")
    if not get_from(data, "corpus.chapters_dir"): errors.append("缺少 corpus.chapters_dir")
    return errors

if __name__ == "__main__":
    errors = validate()
    if errors:
        print("\n".join("[FAIL] " + item for item in errors)); raise SystemExit(1)
    print("[PASS] project.config.json 有效：", config_path())
