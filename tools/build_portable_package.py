#!/usr/bin/env python3
"""Build a cleaned GFAM portable zip from the current project folder."""
from __future__ import annotations

import os
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT.parent
OUT_NAME = "GFAM_portable_user_bundle.zip"
EXCLUDE_DIRS = {".git", "__pycache__", ".pytest_cache", "build", "dist"}
EXCLUDE_FILES = {
    ".env", ".gfam_auth.json", ".gfam_state.json", ".gfam_factory_state.json",
    ".gfam_next_module.cmd", ".gfam_factory_auto.pid", ".gfam_fairy_auto.pid",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".log"}


def should_skip(path: Path) -> bool:
    rel_parts = path.relative_to(ROOT).parts
    if any(part in EXCLUDE_DIRS for part in rel_parts):
        return True
    if path.name in EXCLUDE_FILES:
        return True
    if path.suffix.lower() in EXCLUDE_SUFFIXES:
        return True
    name = path.name.lower()
    if "index_index" in name and name.endswith(".json"):
        return True
    if "index_debug" in name and name.endswith(".json"):
        return True
    return False


def main() -> None:
    out_path = OUT_DIR / OUT_NAME
    if out_path.exists():
        out_path.unlink()
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in ROOT.rglob("*"):
            if should_skip(path):
                continue
            if path.is_file():
                arc = Path("GFAM") / path.relative_to(ROOT)
                zf.write(path, arc.as_posix())
    print(f"built: {out_path}")


if __name__ == "__main__":
    main()
