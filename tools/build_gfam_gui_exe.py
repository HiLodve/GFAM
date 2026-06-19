# -*- coding: utf-8 -*-
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
BUILD = ROOT / "build"


def add_data_arg(src: str, dst: str) -> str:
    return f"{src}{os.pathsep}{dst}"


def build():
    os.chdir(ROOT)
    for path in [DIST, BUILD]:
        if path.exists():
            shutil.rmtree(path)

    data_items = [
        ("main.js", "."),
        ("run_windows.bat", "."),
        ("run_windows_debug.bat", "."),
        ("setup_windows.ps1", "."),
        ("requirements.txt", "."),
        ("requirements-gha.txt", "."),
        ("modules", "modules"),
        ("data", "data"),
        ("libs", "libs"),
        ("tools/start_gfam_background.ps1", "tools"),
        ("assets", "assets"),
        ("docs", "docs"),
        ("examples", "examples"),
        ("README_便携包使用说明.txt", "."),
        ("LICENSE", "."),
        ("THIRD_PARTY_LICENSES.txt", "."),
    ]

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        "--name",
        "GFAM-GUI",
        "--icon",
        str(ROOT / "assets" / "gfam.ico"),
    ]
    for src, dst in data_items:
        src_path = ROOT / src
        if src_path.exists():
            cmd.extend(["--add-data", add_data_arg(str(src_path), dst)])
    cmd.append(str(ROOT / "tools" / "gfam_gui_launcher.py"))

    print("Running:")
    print(" ".join('"%s"' % x if " " in x else x for x in cmd))
    subprocess.run(cmd, check=True)

    # The PyInstaller build\GFAM-GUI folder is only an intermediate work tree.
    # Running build\GFAM-GUI\GFAM-GUI.exe can fail with
    # "Failed to load Python DLL ... build\GFAM-GUI\_internal\python311.dll".
    # Remove the intermediate build folder after a successful build so users only see
    # the valid dist\GFAM-GUI output.
    if BUILD.exists():
        try:
            shutil.rmtree(BUILD)
            print("Removed intermediate build folder:", BUILD)
        except Exception as exc:
            print("[WARN] Could not remove intermediate build folder:", exc)

    run_exe = DIST / "GFAM-GUI" / "GFAM-GUI.exe"
    print("\nBuild finished.")
    print("Executable folder:", DIST / "GFAM-GUI")
    print("Run:", run_exe)
    print("\nIMPORTANT: Run only the EXE under dist\\GFAM-GUI. Do not run any EXE under build\\.")


if __name__ == "__main__":
    build()
