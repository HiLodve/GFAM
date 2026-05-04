#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Non-interactive controller for GFAM GitHub Actions runs.

This helper is intentionally thin: it does not implement any game logic.
It starts the normal GHA launcher, sends menu commands through stdin, waits
for a bounded duration, then asks the module to stop safely.
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable, List

ROOT = Path(__file__).resolve().parent
RUN_GHA = ROOT / "run_gha.sh"

DEFAULT_START_COMMANDS = {
    "greyzone": ["-r"],
    "f2p": ["-r"],
    "f2p_pr": ["-r"],
    "13-4": ["-r"],
    "134": ["-r"],
    "smart": ["-r"],
    "pick": [],
    "epa": [],
}

DEFAULT_STOP_COMMANDS = ["-q", "-E"]


def parse_lines(text: str | None) -> List[str]:
    if not text:
        return []
    lines: List[str] = []
    for raw in str(text).replace("\\r\\n", "\\n").split("\\n"):
        line = raw.strip()
        if line:
            lines.append(line)
    return lines


def send_commands(proc: subprocess.Popen, commands: Iterable[str], delay: float = 0.6) -> None:
    if not proc.stdin:
        return
    for cmd in commands:
        if proc.poll() is not None:
            return
        print(f"[GHA] >>> {cmd}", flush=True)
        try:
            proc.stdin.write(cmd + "\n")
            proc.stdin.flush()
        except BrokenPipeError:
            return
        time.sleep(delay)


def wait_until(proc: subprocess.Popen, seconds: int) -> bool:
    """Return True if process exited during the wait."""
    deadline = time.time() + max(0, seconds)
    while time.time() < deadline:
        if proc.poll() is not None:
            return True
        time.sleep(1)
    return proc.poll() is not None


def terminate_process(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    print("[GHA] 模块仍未退出，发送 terminate。", flush=True)
    try:
        proc.terminate()
        proc.wait(timeout=20)
        return
    except Exception:
        pass
    if proc.poll() is None:
        print("[GHA] terminate 后仍未退出，强制 kill。", flush=True)
        try:
            proc.kill()
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run GFAM module from GitHub Actions with scripted commands.")
    parser.add_argument("--module", default=os.environ.get("GFAM_GHA_MODULE", "greyzone"), help="GFAM module id, e.g. greyzone / f2p / 13-4")
    parser.add_argument("--server", default=os.environ.get("GFAM_SERVER", "SOP"), help="Server: SOP/RO635/M4A1/M16/AR-15/EN")
    parser.add_argument("--fairy", action="store_true", help="Enable fairy automation for this run")
    parser.add_argument("--no-fairy", action="store_true", help="Disable fairy automation for this run")
    parser.add_argument("--ticket-type", choices=["default", "ticket1", "ticket2"], default="default", help="Greyzone ticket command to send before start")
    parser.add_argument("--run-minutes", type=int, default=30, help="Minutes to let the module run before safe-stop commands")
    parser.add_argument("--startup-commands", default="", help="Commands sent before the default start command, separated by newlines")
    parser.add_argument("--start-commands", default="", help="Commands used to start the module. If empty, defaults are used for known modules")
    parser.add_argument("--stop-commands", default="", help="Commands sent at the end. If empty: -q then -E")
    args = parser.parse_args(argv)

    if not RUN_GHA.exists():
        print("[GHA] 找不到 run_gha.sh。", file=sys.stderr)
        return 1

    env = os.environ.copy()
    env["GFAM_SERVER"] = args.server
    env["GFAM_SELECTED_SERVER"] = args.server
    if args.fairy:
        env["GFAM_FAIRY_AUTO_ENABLED"] = "1"
    if args.no_fairy:
        env["GFAM_FAIRY_AUTO_ENABLED"] = "0"

    uid = env.get("GFAM_USER_UID", "").strip()
    sign = env.get("GFAM_SIGN_KEY", "").strip()
    if not uid or not sign:
        print("[GHA] 缺少 GFAM_USER_UID / GFAM_SIGN_KEY。请在仓库 Settings -> Secrets and variables -> Actions 中配置。", file=sys.stderr)
        return 1

    cmd = [str(RUN_GHA), "--module", args.module, "--server", args.server]
    if args.fairy:
        cmd.append("--fairy")
    if args.no_fairy:
        cmd.append("--no-fairy")

    print("[GHA] 启动 GFAM 模块。", flush=True)
    print(f"[GHA] module={args.module} server={args.server} fairy={'on' if env.get('GFAM_FAIRY_AUTO_ENABLED') == '1' else 'off'}", flush=True)
    proc = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        env=env,
        stdin=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    try:
        # Give the child process time to print menus and start reading input.
        time.sleep(3)
        commands: List[str] = []
        commands.extend(parse_lines(args.startup_commands))
        if args.ticket_type == "ticket1":
            commands.append("-ticket1")
        elif args.ticket_type == "ticket2":
            commands.append("-ticket2")

        explicit_start = parse_lines(args.start_commands)
        if explicit_start:
            commands.extend(explicit_start)
        else:
            commands.extend(DEFAULT_START_COMMANDS.get(args.module.lower(), []))

        send_commands(proc, commands)

        run_seconds = max(1, int(args.run_minutes) * 60)
        print(f"[GHA] 运行窗口：{args.run_minutes} 分钟。", flush=True)
        if wait_until(proc, run_seconds):
            return proc.returncode or 0

        stop_commands = parse_lines(args.stop_commands) or DEFAULT_STOP_COMMANDS
        print("[GHA] 到达运行窗口，发送安全停止命令。", flush=True)
        send_commands(proc, stop_commands, delay=2.0)
        if wait_until(proc, 180):
            return proc.returncode or 0
        terminate_process(proc)
        return proc.returncode if proc.returncode is not None else 124
    except KeyboardInterrupt:
        print("[GHA] 收到中断，发送安全停止。", flush=True)
        send_commands(proc, DEFAULT_STOP_COMMANDS, delay=1.0)
        terminate_process(proc)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
