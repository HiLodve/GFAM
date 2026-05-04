# -*- coding: utf-8 -*-
"""GFAM shared runtime utilities.

This module intentionally stays small: it only centralizes paths, debug logging,
and optional debug JSON saving, so the standalone farming modules keep their
original business logic and can still run independently.
"""
import json
import os
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
DOCS_DIR = PROJECT_ROOT / "docs"

_TRUE_VALUES = {"1", "true", "yes", "y", "on"}

def gfam_env_enabled(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return bool(default)
    return str(value).strip().lower() in _TRUE_VALUES

def gfam_debug_enabled():
    return gfam_env_enabled("GFAM_DEBUG", False)

def gfam_debug_log(message):
    if gfam_debug_enabled():
        print(str(message))

def gfam_data_candidates(*names):
    """Return data-file candidates in stable order.

Order keeps compatibility with old layouts while preferring the new data/ dir:
1. GFAM/data
2. GFAM root
3. current process working directory
4. GFAM/modules
    """
    paths = []
    for name in names:
        if not name:
            continue
        paths.extend([DATA_DIR / name, PROJECT_ROOT / name, Path.cwd() / name, MODULE_DIR / name])
    seen = set()
    out = []
    for path in paths:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out

def gfam_find_data_file(*names):
    for path in gfam_data_candidates(*names):
        if path.exists():
            return path
    return None

def gfam_write_debug_json(filename, payload, label="debug"):
    """Save debug JSON only when explicitly enabled.

Set GFAM_SAVE_DEBUG_JSON=1 or GFAM_DEBUG=1 to keep Index/index snapshots.
Normal runs stay clean and do not create index_debug.json repeatedly.
    """
    if not (gfam_env_enabled("GFAM_SAVE_DEBUG_JSON", False) or gfam_debug_enabled()):
        return False
    try:
        path = PROJECT_ROOT / filename
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=4, ensure_ascii=False)
        gfam_debug_log("[*] 已保存 %s 调试响应到 %s" % (label, path))
        return True
    except Exception as exc:
        gfam_debug_log("[!] 保存 %s 调试响应失败：%s" % (label, exc))
        return False
