#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GFAM GHA/Linux launcher.

This entry is intended for GHA/server environments where UID/SIGN are supplied
by environment variables or a local .env file.  It does not start the Windows
proxy/auth-capture flow and does not depend on Node.js.
"""
from __future__ import annotations

import argparse
import os
import shlex
import signal
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional

ROOT = Path(__file__).resolve().parent
MODULE_DIR = ROOT / "modules"
ZIRC_CORE = ROOT / "libs" / "ZIRC" / "src" / "core"
ENV_FILE = ROOT / ".env"

PROJECT_NAME = "少女全自动 / Girl Fully Automatic (GFAM) - GHA"
SERVERS = ("SOP", "RO635", "M4A1", "M16", "AR-15", "EN")

MODULES = [
    {"id": "epa", "title": "epa_plus（EPA 打捞）", "file": "epa_plus.py", "aliases": ["1", "epa", "epa_plus", "打捞"], "hidden": ["EN"]},
    {"id": "13-4", "title": "13-4（五战练级 / 四项基础资源打捞）", "file": "gfam_13_4.py", "aliases": ["2", "134", "13-4", "13_4", "资源", "练级"]},
    {"id": "pick", "title": "pick_and_train（获取训练资料 / 自动训练 / 自动循环）", "file": "pick_and_train.py", "aliases": ["3", "pick", "train", "pick_and_train", "自动训练"]},
    {"id": "f2p", "title": "零元购 f2p", "file": "f2p.py", "aliases": ["4", "f2p", "零元购"]},
    {"id": "f2p_pr", "title": "零元购 PR（额外核心）", "file": "f2p_pr.py", "aliases": ["5", "f2p_pr", "f2ppr", "pr", "零元购pr"]},
    {"id": "smart", "title": "教练の妙妙小巧思（一键打捞计划/装备一键打捞）", "file": "gfam_smart_epa.py", "aliases": ["6", "smart", "coach", "一键", "装备一键"], "hidden": ["EN"]},
    {"id": "greyzone", "title": "灰域自动彩蛋", "file": "gfam_greyzone_halloween.py", "aliases": ["7", "greyzone", "gz", "halloween", "灰域", "彩蛋"], "hidden": ["EN"]},
]

TRUE_VALUES = {"1", "true", "yes", "y", "on", "enable", "enabled", "开启"}
FALSE_VALUES = {"0", "false", "no", "n", "off", "disable", "disabled", "关闭"}


def normalize_server(value: str | None) -> Optional[str]:
    text = str(value or "").strip().upper().replace("_", "-")
    if not text:
        return None
    mapping = {
        "1": "SOP", "SOP": "SOP",
        "2": "RO635", "RO": "RO635", "RO635": "RO635",
        "3": "M4A1", "M4": "M4A1", "M4A1": "M4A1",
        "4": "M16", "M16": "M16",
        "5": "AR-15", "AR15": "AR-15", "AR-15": "AR-15",
        "6": "EN", "GLOBAL": "EN", "EN": "EN",
    }
    return mapping.get(text)


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    return default


def load_dotenv(path: Path = ENV_FILE) -> None:
    """Small .env loader; existing environment variables take precedence."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def current_server() -> str:
    return normalize_server(os.environ.get("GFAM_SELECTED_SERVER") or os.environ.get("GFAM_SERVER") or os.environ.get("GFL_SERVER")) or "SOP"


def current_uid() -> str:
    return str(os.environ.get("GFAM_USER_UID") or os.environ.get("GFL_USER_UID") or os.environ.get("GFL_USER_ID") or os.environ.get("USER_UID") or "").strip()


def current_sign() -> str:
    return str(os.environ.get("GFAM_SIGN_KEY") or os.environ.get("GFL_SIGN_KEY") or os.environ.get("SIGN_KEY") or "").strip()


def fairy_enabled() -> bool:
    return parse_bool(os.environ.get("GFAM_FAIRY_AUTO_ENABLED") or os.environ.get("GFAM_GHA_FAIRY"), False)


def build_env(server: str, fairy: Optional[bool] = None) -> Dict[str, str]:
    env = os.environ.copy()
    uid = current_uid()
    sign = current_sign()
    env["GFAM_SELECTED_SERVER"] = server
    env["GFAM_SERVER"] = server
    env["GFAM_SKIP_SERVER_MENU"] = "1"
    env["GFAM_AUTH_READY"] = "1" if uid and sign else "0"
    env["GFAM_USER_UID"] = uid
    env["GFAM_SIGN_KEY"] = sign
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = env.get("PYTHONUNBUFFERED", "1")
    old_path = env.get("PYTHONPATH", "")
    parts = [str(ZIRC_CORE), str(MODULE_DIR)]
    if old_path:
        parts.append(old_path)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    if fairy is not None:
        env["GFAM_FAIRY_AUTO_ENABLED"] = "1" if fairy else "0"
    return env


def module_hidden(item: dict, server: str) -> bool:
    return server in item.get("hidden", [])


def visible_modules(server: str):
    return [m for m in MODULES if not module_hidden(m, server)]


def resolve_module(value: str, server: str) -> Optional[dict]:
    text = str(value or "").strip().lower()
    if not text:
        return None
    for item in visible_modules(server):
        if text == item["id"].lower() or text in [str(a).lower() for a in item.get("aliases", [])]:
            return item
    return None


def print_menu(server: str) -> None:
    print(f"\n================ {PROJECT_NAME} ================")
    print(f"当前服务器：{server}")
    uid = current_uid()
    sign = current_sign()
    print("UID/SIGN：%s" % ("已配置" if uid and sign else "未配置（请检查 .env 或环境变量）"))
    print("妖精自动：%s" % ("开启" if fairy_enabled() else "关闭"))
    print("------------------------------------------------")
    for index, item in enumerate(visible_modules(server), 1):
        print("  %d / %-9s : %s" % (index, item["id"], item["title"]))
    print("  fairy       : 切换妖精自动建造 / 自动强化")
    print("  server      : 切换服务器")
    print("  0 / exit    : 退出")
    print("------------------------------------------------")
    print("提示：GHA 版不启动代理，不抓取 UID/SIGN；请在 .env 或环境变量中提前填写。")
    print("提示：模块运行期间仍由模块本身接管命令行。")
    print("================================================\n")


def start_fairy(env: Dict[str, str]) -> Optional[subprocess.Popen]:
    script = MODULE_DIR / "gfam_fairy_auto.py"
    if not script.exists():
        print("[!] 妖精自动模块不存在，跳过后台妖精循环。")
        return None
    print("[*] 妖精自动建造 / 自动强化已开启，将随当前模块后台运行。")
    # Keep stdout/stderr inherited so server logs can capture fairy status.
    return subprocess.Popen([sys.executable, str(script)], cwd=str(ROOT), env=env)


def stop_fairy(proc: Optional[subprocess.Popen]) -> None:
    if not proc or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    print("[*] 妖精自动建造 / 自动强化后台循环已停止。")


def run_module(item: dict, server: str, fairy: Optional[bool] = None) -> int:
    script = MODULE_DIR / item["file"]
    if not script.exists():
        print(f"[!] 模块文件不存在：{script}")
        return 1
    env = build_env(server, fairy=fairy_enabled() if fairy is None else fairy)
    if not env.get("GFAM_USER_UID") or not env.get("GFAM_SIGN_KEY"):
        print("[!] 缺少 UID/SIGN。请复制 examples/gha.env.example 为 .env 后填写 GFAM_USER_UID 与 GFAM_SIGN_KEY。")
        return 1
    print("\n================================================")
    print("正在启动模块：%s" % item["title"])
    print("当前服务器：%s" % server)
    print("模块文件：%s" % script.relative_to(ROOT))
    print("GHA模式：不启动代理，沿用 .env / 环境变量中的 UID/SIGN。")
    print("================================================\n")
    fairy_proc = start_fairy(env) if parse_bool(env.get("GFAM_FAIRY_AUTO_ENABLED"), False) else None
    try:
        return subprocess.run([sys.executable, str(script)], cwd=str(ROOT), env=env).returncode
    finally:
        stop_fairy(fairy_proc)


def interactive_loop() -> int:
    server = current_server()
    while True:
        print_menu(server)
        choice = input(f"GFAM-GHA[{server}]> ").strip()
        low = choice.lower()
        if low in ("0", "exit", "quit", "q", "退出"):
            print("[*] 已退出 GFAM GHA。")
            return 0
        if low in ("server", "-server", "服务器", "切换服务器"):
            answer = input("请选择服务器（SOP/RO635/M4A1/M16/AR-15/EN）：").strip()
            new_server = normalize_server(answer)
            if new_server:
                server = new_server
                os.environ["GFAM_SERVER"] = server
                os.environ["GFAM_SELECTED_SERVER"] = server
                print("[+] 已切换服务器：%s" % server)
            else:
                print("[!] 未识别服务器。")
            continue
        if low in ("fairy", "-fairy", "妖精", "妖精自动"):
            next_value = not fairy_enabled()
            os.environ["GFAM_FAIRY_AUTO_ENABLED"] = "1" if next_value else "0"
            os.environ["GFAM_GHA_FAIRY"] = "1" if next_value else "0"
            print("[+] 妖精自动：%s" % ("开启" if next_value else "关闭"))
            continue
        item = resolve_module(choice, server)
        if not item:
            print("[!] 未识别输入，请重新选择。")
            continue
        run_module(item, server)
        input("\n[*] 模块已退出，按回车返回 GHA 菜单。")


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="GFAM GHA/Linux launcher")
    parser.add_argument("-m", "--module", help="直接启动模块，如 greyzone / epa / 13-4 / f2p")
    parser.add_argument("-s", "--server", help="服务器：SOP/RO635/M4A1/M16/AR-15/EN")
    parser.add_argument("--fairy", action="store_true", help="本次运行开启妖精自动")
    parser.add_argument("--no-fairy", action="store_true", help="本次运行关闭妖精自动")
    parser.add_argument("--list", action="store_true", help="列出可用模块")
    args = parser.parse_args(argv)

    server = normalize_server(args.server) or current_server()
    os.environ["GFAM_SERVER"] = server
    os.environ["GFAM_SELECTED_SERVER"] = server
    if args.fairy:
        os.environ["GFAM_FAIRY_AUTO_ENABLED"] = "1"
    if args.no_fairy:
        os.environ["GFAM_FAIRY_AUTO_ENABLED"] = "0"

    if args.list:
        print_menu(server)
        return 0

    direct = args.module or os.environ.get("GFAM_GHA_MODULE")
    if direct:
        item = resolve_module(direct, server)
        if not item:
            print("[!] 未识别模块：%s" % direct)
            return 1
        return run_module(item, server)
    return interactive_loop()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n[*] 已中断 GFAM GHA。")
        raise SystemExit(130)
