#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Non-interactive controller for GFAM GitHub Actions runs.

This helper is intentionally thin: it does not implement any game logic.
It starts the normal GHA launcher, sends menu commands through stdin, waits
for a bounded duration, then asks the module to stop safely.

For GitHub Actions, compact logging is enabled by default to avoid flooding
the Actions web log with fixed dashboard refresh blocks and high-frequency
macro/micro/step logs from every module. The full module output can be
restored by setting GFAM_GHA_COMPACT_LOG=0 in the workflow.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Iterable, List, Optional, Dict

ROOT = Path(__file__).resolve().parent
RUN_GHA = ROOT / "run_gha.sh"

ZIRC_CORE = ROOT / "libs" / "ZIRC" / "src" / "core"
if ZIRC_CORE.exists() and str(ZIRC_CORE) not in sys.path:
    sys.path.insert(0, str(ZIRC_CORE))

try:
    from gflzirc import GFLClient, SERVERS, API_INDEX_INDEX
except Exception:  # pragma: no cover - GitHub Actions will surface a warning instead of failing import-time
    GFLClient = None  # type: ignore[assignment]
    SERVERS = {}  # type: ignore[assignment]
    API_INDEX_INDEX = "Index/index"

DEFAULT_START_COMMANDS = {
    "greyzone": ["-r"],
    "f2p": ["-r"],
    "f2p_pr": ["-r"],
    "smart": ["-r"],
}

GHA_MODULE_TO_GFAM_MODULE = {
    "13-4-train": "13-4",
    "13-4-resource": "13-4",
    "134-train": "13-4",
    "134-resource": "13-4",
    "13-4": "13-4",
    "134": "13-4",
    "pick-and-train": "pick",
    "pick-data": "pick",
    "pick-train": "pick",
    "pick": "pick",
    # EPA 的参数链太长，GHA 中用 smart 一键打捞入口替代；保留 epa 作为兼容别名。
    "epa": "smart",
}

DEFAULT_STOP_COMMANDS = ["-q", "-E"]

RESOURCE_KEYS = ("mp", "ammo", "mre", "part")
RESOURCE_LABELS = {
    "mp": "人力",
    "ammo": "弹药",
    "mre": "口粮",
    "part": "零件",
}

# These modules already print their own resource summary at run end.  The GHA
# wrapper only supplements modules that do not have a built-in summary, so we
# avoid duplicating output.
MODULES_WITH_BUILTIN_RESOURCE_SUMMARY = {
    "13-4-train",
    "13-4-resource",
    "f2p",
    "f2p_pr",
}

# Fixed dashboard headers. In local Windows runs these are useful; in GHA they
# generate very long logs because every refresh becomes permanent text.
DASHBOARD_HEADER_RE = re.compile(r"^=+\s*.*运行状态.*=+\s*$")
DASHBOARD_FOOTER_RE = re.compile(r"^=+\s*$")

# Repetitive step-level lines that are useful locally but too noisy in Actions.
NOISY_LINE_PATTERNS = [
    # Greyzone reset / movement details
    re.compile(r"^\s*\[-\]\s*当前地图未发现有效彩蛋，继续重置。"),
    re.compile(r"^\s*\[>\]\s*Step\s+\d+[:：]"),
    re.compile(r"^\s*\[>\]\s*移动\s+\d+\s*->\s*\d+"),
    re.compile(r"^\s*\[!\]\s*触发战斗"),
    re.compile(r"^\s*\[!\]\s*执行\s*BuildingSkill", re.IGNORECASE),
    re.compile(r"^\s*\[>\]\s*触发友方移动"),

    # EPA / 13-4 / smart / f2p routine macro-micro noise
    re.compile(r"^\s*=+\s*MACRO\s+\d+", re.IGNORECASE),
    re.compile(r"^\s*=+\s*MICRO\s+\d+", re.IGNORECASE),
    re.compile(r"^\s*\[MACRO\s+\d+\]", re.IGNORECASE),
    re.compile(r"^\s*\[MICRO\s+\d+\]", re.IGNORECASE),
    re.compile(r"^\s*\[\*\]\s*Micro Run", re.IGNORECASE),
    re.compile(r"^\s*当前\s*MACRO[:：]"),
    re.compile(r"^\s*当前\s*MICRO[:：]"),
    re.compile(r"^\s*当前\s*Step[:：]"),
    re.compile(r"^\s*最近一轮经验[:：]"),
    re.compile(r"^\s*本梯队已运行[:：]"),
    re.compile(r"^\s*预计完成[:：]"),
    re.compile(r"^\s*总运行时间[:：]"),
    re.compile(r"^\s*停止[:：]"),

    # Fairy auto routine dashboard/status refreshes. Keep real action/error
    # lines via IMPORTANT_KEYWORDS, but suppress repeated counters such as
    # "妖精自动：操作 建造启动 0/0，领取 0/1，强化 0/0；状态 ..."
    re.compile(r"^\s*妖精自动[:：]\s*操作\s*"),
    re.compile(r"^\s*妖精自动[:：].*状态\s*仓库"),
    re.compile(r"^\s*妖精自动[:：].*栏位"),
    re.compile(r"^\s*妖精自动[:：].*本地倒计时"),
    re.compile(r"^\s*妖精进度[:：]"),
    re.compile(r"^\s*当前妖精仓库[:：]"),
    re.compile(r"^\s*当前妖精.*倒计时"),

    re.compile(r"^\s*[-=]{8,}\s*$"),
]

# Lines that should always survive compact filtering.
IMPORTANT_KEYWORDS = (
    "[GHA]",
    "Started",
    "启动",
    "开始",
    "发现",
    "完成",
    "结束",
    "统计",
    "成功",
    "失败",
    "错误",
    "异常",
    "中断",
    "停止",
    "退出",
    "abort",
    "Abort",
    "error",
    "Error",
    "Index/index 已完成",
    "当前灰域积分",
    "票券缓存",
    "四项缓存",
    "掉落",
    "拆解",
    "应急",
    "仓库不足",
    "满级",
    "切换",
    "目标",
    "达成",
    "领取",
    "建造",
    "强化",
)


def is_truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def parse_lines(text: str | None) -> List[str]:
    if not text:
        return []
    lines: List[str] = []
    for raw in str(text).replace("\\r\\n", "\\n").split("\\n"):
        line = raw.strip()
        if line:
            lines.append(line)
    return lines


def clamp_train_team_count(value: str | int | None) -> int:
    try:
        count = int(str(value or "1").strip())
    except Exception:
        count = 1
    # 13-4 练级固定梯队1为单人占位，实际从梯队2开始；最多可到梯队14。
    return max(1, min(13, count))


def normalize_gha_module(value: str | None) -> str:
    text = str(value or "greyzone").strip().lower().replace("_", "-")
    aliases = {
        "13-4-level": "13-4-train",
        "13-4-training": "13-4-train",
        "134train": "13-4-train",
        "134-train": "13-4-train",
        "train134": "13-4-train",
        "13-4-train": "13-4-train",
        "13-4resource": "13-4-resource",
        "13-4-resource": "13-4-resource",
        "134-resource": "13-4-resource",
        "resource134": "13-4-resource",
        "res134": "13-4-resource",
        "13-4": "13-4-train",
        "134": "13-4-train",
        "pick-and-train": "pick-and-train",
        "pickandtrain": "pick-and-train",
        "pick-data": "pick-and-train",
        "pick-train": "pick-and-train",
        "pick-resource": "pick-and-train",
        "pick-coin": "pick-and-train",
        "pick": "pick-and-train",
        "train": "pick-and-train",
        "auto-train": "pick-and-train",
        "epa": "smart",
        "epa-plus": "smart",
    }
    return aliases.get(text, text)


def child_module_id(module_key: str) -> str:
    return GHA_MODULE_TO_GFAM_MODULE.get(module_key, module_key)


def build_default_start_commands(module_key: str, train_team_count: int) -> List[str]:
    if module_key == "13-4-train":
        # 13-4 GHA 自动流程：选择练级模式 -> 默认整队练满 -> 输入练级梯队数量 ->
        # 请求一次 Index/index 解析梯队 -> 默认不满级停机 -> 确认 -> 开跑。
        return ["-134train", "-full", str(train_team_count), "-a", "-keepmax", "-y", "-r"]
    if module_key == "13-4-resource":
        # 13-4 四项资源模式：选择资源模式 -> 请求一次 Index/index -> 默认不满级停机 -> 确认 -> 开跑。
        return ["-134", "-a", "-keepmax", "-y", "-r"]
    if module_key == "pick-and-train":
        # 自动训练/获取资料循环：先进入自动训练并 -count，再 -run。
        # pick_and_train 模块内部默认开启 TRAIN_PICK_CYCLE_ENABLED：
        # 训练材料不足 -> 自动切换获取训练资料；中级资料达到本模式上限/coin2+0 -> 回到训练。
        return ["-2", "-count", "-run"]
    return list(DEFAULT_START_COMMANDS.get(module_key, []))


def should_collect_resource_summary(module_key: str) -> bool:
    """Return whether the GHA wrapper should add a resource summary.

    13-4/f2p/f2p_pr already have module-side resource statistics, so the
    wrapper does not print a duplicate summary for them.  Other GHA modules are
    supplemented by a start/end Index/index comparison.
    """
    if not is_truthy(os.environ.get("GFAM_GHA_RESOURCE_SUMMARY", "1"), default=True):
        return False
    return module_key not in MODULES_WITH_BUILTIN_RESOURCE_SUMMARY


def normalize_server_for_zirc(server: str | None) -> str:
    text = str(server or "SOP").strip()
    aliases = {
        "AR-15": "AR15",
        "AR_15": "AR15",
        "AR15": "AR15",
    }
    return aliases.get(text, text)


def safe_int(value, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(float(str(value).strip()))
    except Exception:
        return default


def extract_resources_from_index(payload: dict | None) -> Optional[Dict[str, int]]:
    if not isinstance(payload, dict):
        return None
    user_info = payload.get("user_info")
    if not isinstance(user_info, dict):
        return None
    return {key: safe_int(user_info.get(key), 0) for key in RESOURCE_KEYS}


def format_resource_inventory(inv: Dict[str, int] | None, signed: bool = False) -> str:
    inv = inv or {key: 0 for key in RESOURCE_KEYS}
    parts = []
    for key in RESOURCE_KEYS:
        value = safe_int(inv.get(key), 0)
        text = f"{value:+d}" if signed else str(value)
        parts.append(f"{RESOURCE_LABELS[key]} {text}")
    return " / ".join(parts)


def request_resource_snapshot(uid: str, sign: str, server: str, label: str) -> Optional[Dict[str, int]]:
    if GFLClient is None or not SERVERS:
        print(f"[GHA][资源] {label}：无法导入 gflzirc，跳过 GHA 资源统计。", flush=True)
        return None

    server_key = normalize_server_for_zirc(server)
    base_url = SERVERS.get(server_key)
    if not base_url:
        print(f"[GHA][资源] {label}：未知服务器 {server}，跳过 GHA 资源统计。", flush=True)
        return None

    try:
        client = GFLClient(uid, sign, base_url)
        payload = {"time": int(time.time()), "furniture_data": False}
        resp = client.send_request(API_INDEX_INDEX, payload, max_retries=2, timeout=20)
    except Exception as exc:
        print(f"[GHA][资源] {label}：请求 Index/index 失败：{exc}", flush=True)
        return None

    if not isinstance(resp, dict) or resp.get("error_local") or resp.get("error"):
        preview = resp.get("raw_preview") if isinstance(resp, dict) else None
        print(f"[GHA][资源] {label}：Index/index 返回异常，跳过本次 GHA 资源统计。{(' 预览：' + str(preview)) if preview else ''}", flush=True)
        return None

    inv = extract_resources_from_index(resp)
    if inv is None:
        print(f"[GHA][资源] {label}：未能从 Index/index 解析 user_info 四项资源。", flush=True)
        return None

    print(f"[GHA][资源] {label}：{format_resource_inventory(inv)}", flush=True)
    return inv


def print_resource_summary_if_needed(
    module_key: str,
    uid: str,
    sign: str,
    server: str,
    start_inv: Optional[Dict[str, int]],
    start_time: float,
) -> None:
    if start_inv is None:
        return

    end_inv = request_resource_snapshot(uid, sign, server, "结束库存")
    if end_inv is None:
        print("[GHA][资源] 结束库存获取失败，无法计算本次四项变化。", flush=True)
        return

    diff = {key: safe_int(end_inv.get(key), 0) - safe_int(start_inv.get(key), 0) for key in RESOURCE_KEYS}
    elapsed = max(1, int(time.time() - start_time))
    per_hour = {key: int(round(safe_int(diff.get(key), 0) * 3600 / elapsed)) for key in RESOURCE_KEYS}

    print("", flush=True)
    print("=========== GHA 四项基础资源统计 ===========", flush=True)
    print(f"模块：{module_key}    服务器：{server}", flush=True)
    print(f"运行总时长：{elapsed} 秒", flush=True)
    print(f"起始库存：{format_resource_inventory(start_inv)}", flush=True)
    print(f"结束库存：{format_resource_inventory(end_inv)}", flush=True)
    print(f"本次变化：{format_resource_inventory(diff, signed=True)}", flush=True)
    print(f"每小时效率：{format_resource_inventory(per_hour, signed=True)}", flush=True)
    print("说明：该统计由 GHA runner 在运行前后各请求一次 Index/index 计算；13-4/f2p/f2p_pr 已有模块内统计时不会重复打印。", flush=True)
    print("===========================================", flush=True)


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


class OutputFilter:
    """Stream child output while suppressing dashboard refresh blocks."""

    def __init__(self, compact: bool = True, reset_log_every: int = 10) -> None:
        self.compact = compact
        self.reset_log_every = max(1, int(reset_log_every or 10))
        self._in_dashboard = False
        self._suppressed_dashboard_blocks = 0
        self._reset_attempts_seen = 0
        self._reset_suppressed = 0
        self._last_reset_heartbeat = 0.0
        self._suppressed_general = 0
        self._last_general_heartbeat = 0.0
        self._in_stats_block = False
        self._stats_lines_seen = 0
        self._recent_lines: dict[str, float] = {}
        self._duplicate_suppressed = 0
        self._last_duplicate_heartbeat = 0.0

    def _should_emit_deduped(self, stripped: str) -> bool:
        """Suppress identical key lines replayed by fixed-dashboard recent logs."""
        if not stripped or stripped.startswith("[GHA]"):
            return True

        now = time.time()
        window = 180.0
        last = self._recent_lines.get(stripped)
        self._recent_lines[stripped] = now

        if len(self._recent_lines) > 1200:
            cutoff = now - window
            self._recent_lines = {k: v for k, v in self._recent_lines.items() if v >= cutoff}

        if last is not None and now - last < window:
            self._duplicate_suppressed += 1
            if self._last_duplicate_heartbeat <= 0 or now - self._last_duplicate_heartbeat >= 60:
                skipped = self._duplicate_suppressed
                self._duplicate_suppressed = 0
                self._last_duplicate_heartbeat = now
                print(f"[GHA] 已省略 {skipped} 条重复关键日志。", flush=True)
            return False
        return True

    def _should_keep_reset_line(self, line: str) -> bool:
        if "重置灰域地图" not in line or "尝试" not in line:
            return True
        self._reset_attempts_seen += 1
        self._reset_suppressed += 1

        # In compact mode, do not print every reset attempt. GitHub Actions
        # logs are permanent text, so repeated "no candy found" lines quickly
        # bury the useful information. Keep only a low-frequency heartbeat.
        now = time.time()
        if self._last_reset_heartbeat <= 0 or now - self._last_reset_heartbeat >= 60:
            self._last_reset_heartbeat = now
            skipped = self._reset_suppressed
            self._reset_suppressed = 0
            print(f"[GHA] 灰域重置中：已尝试 {self._reset_attempts_seen} 次，最近省略 {skipped} 条重置日志。", flush=True)
        return False

    def _maybe_general_heartbeat(self) -> str | None:
        self._suppressed_general += 1
        now = time.time()
        if self._last_general_heartbeat <= 0 or now - self._last_general_heartbeat >= 60:
            skipped = self._suppressed_general
            self._suppressed_general = 0
            self._last_general_heartbeat = now
            return f"[GHA] 运行中：已省略 {skipped} 条常规模块日志。"
        return None

    def _is_stats_header(self, stripped: str) -> bool:
        return "统计" in stripped and (stripped.startswith("=") or stripped.startswith("-"))

    def _filter_stats_block(self, line: str, stripped: str) -> str | None:
        if self._is_stats_header(stripped):
            self._in_stats_block = True
            self._stats_lines_seen = 1
            return line
        if self._in_stats_block:
            self._stats_lines_seen += 1
            if self._stats_lines_seen > 1 and DASHBOARD_FOOTER_RE.match(stripped):
                self._in_stats_block = False
                self._stats_lines_seen = 0
            return line
        return None

    def filter_line(self, raw_line: str) -> str | None:
        if not self.compact:
            return raw_line.rstrip("\n")

        line = raw_line.rstrip("\n")
        stripped = line.strip()

        if self._in_dashboard:
            if DASHBOARD_FOOTER_RE.match(stripped):
                self._in_dashboard = False
                self._suppressed_dashboard_blocks += 1
                if self._suppressed_dashboard_blocks in {1, 5, 20} or self._suppressed_dashboard_blocks % 100 == 0:
                    return f"[GHA] 已省略固定仪表盘刷新 {self._suppressed_dashboard_blocks} 次。"
            return None

        if DASHBOARD_HEADER_RE.match(stripped):
            self._in_dashboard = True
            return None

        if not stripped:
            return None

        stats_line = self._filter_stats_block(line, stripped)
        if stats_line is not None:
            return stats_line

        # Greyzone repeated reset messages are especially noisy and contain
        # words such as "发现" that would otherwise look important, so filter
        # them before keyword matching.
        if not self._should_keep_reset_line(stripped):
            return None

        if any(pattern.search(stripped) for pattern in NOISY_LINE_PATTERNS):
            return None

        if any(keyword in stripped for keyword in IMPORTANT_KEYWORDS):
            return line if self._should_emit_deduped(stripped) else None

        # In compact mode, suppress ordinary progress chatter from all modules
        # (EPA/13-4/smart/f2p/pick/greyzone) and emit a low-frequency heartbeat
        # so the Actions log still proves the process is alive.
        return self._maybe_general_heartbeat()

    def drain(self) -> None:
        if self.compact and self._reset_suppressed:
            print(f"[GHA] 灰域重置日志结束：最后省略 {self._reset_suppressed} 条重置日志。", flush=True)
            self._reset_suppressed = 0
        if self.compact and self._suppressed_general:
            print(f"[GHA] 常规模块日志结束：最后省略 {self._suppressed_general} 条。", flush=True)
            self._suppressed_general = 0
        if self.compact and self._duplicate_suppressed:
            print(f"[GHA] 重复关键日志结束：最后省略 {self._duplicate_suppressed} 条。", flush=True)
            self._duplicate_suppressed = 0


def stream_output(proc: subprocess.Popen, output_filter: OutputFilter) -> threading.Thread:
    def _worker() -> None:
        if not proc.stdout:
            return
        try:
            for raw in proc.stdout:
                text = output_filter.filter_line(raw)
                if text is not None:
                    print(text, flush=True)
        finally:
            output_filter.drain()

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return thread


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
    parser.add_argument("--module", default=os.environ.get("GFAM_GHA_MODULE", "greyzone"), help="GFAM module id, e.g. greyzone / f2p / 13-4-train / 13-4-resource / pick_and_train / smart")
    parser.add_argument("--server", default=os.environ.get("GFAM_SERVER", "SOP"), help="Server: SOP/RO635/M4A1/M16/AR-15/EN")
    parser.add_argument("--fairy", action="store_true", help="Enable fairy automation for this run")
    parser.add_argument("--no-fairy", action="store_true", help="Disable fairy automation for this run")
    parser.add_argument("--ticket-type", choices=["default", "ticket1", "ticket2"], default="default", help="Greyzone ticket command to send before start")
    parser.add_argument("--train-team-count", default=os.environ.get("GFAM_GHA_13_4_TRAIN_TEAM_COUNT", "1"), help="13-4 training team count, starting from team 2")
    parser.add_argument("--run-minutes", type=int, default=30, help="Minutes to let the module run before safe-stop commands")
    parser.add_argument("--startup-commands", default="", help="Commands sent before the default start command, separated by newlines")
    parser.add_argument("--start-commands", default="", help="Commands used to start the module. If empty, defaults are used for known modules")
    parser.add_argument("--stop-commands", default="", help="Commands sent at the end. If empty: -q then -E")
    parser.add_argument("--compact-log", choices=["default", "on", "off"], default="default", help="Suppress fixed dashboards and noisy step logs in GitHub Actions")
    args = parser.parse_args(argv)

    module_key = normalize_gha_module(args.module)
    child_module = child_module_id(module_key)
    train_team_count = clamp_train_team_count(args.train_team_count)

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

    cmd = [str(RUN_GHA), "--module", child_module, "--server", args.server]
    if args.fairy:
        cmd.append("--fairy")
    if args.no_fairy:
        cmd.append("--no-fairy")

    compact = is_truthy(os.environ.get("GFAM_GHA_COMPACT_LOG"), default=True)
    if args.compact_log == "on":
        compact = True
    elif args.compact_log == "off":
        compact = False
    reset_log_every = int(os.environ.get("GFAM_GHA_RESET_LOG_EVERY", "10") or "10")

    print("[GHA] 启动 GFAM 模块。", flush=True)
    print(f"[GHA] module={module_key} child_module={child_module} server={args.server} fairy={'on' if env.get('GFAM_FAIRY_AUTO_ENABLED') == '1' else 'off'}", flush=True)
    if module_key == "13-4-train":
        print(f"[GHA] 13-4 练级梯队数量={train_team_count}（从梯队2开始）", flush=True)
    if module_key == "pick-and-train":
        print("[GHA] pick_and_train：先自动训练；资料不足时切换获取资料，达到模块内条件后返回训练。", flush=True)
    print(f"[GHA] compact_log={'on' if compact else 'off'}", flush=True)

    resource_start_time = time.time()
    resource_start_inv: Optional[Dict[str, int]] = None
    if should_collect_resource_summary(module_key):
        resource_start_inv = request_resource_snapshot(uid, sign, args.server, "起始库存")
    else:
        print("[GHA][资源] 当前模块已有运行结束资源统计，GHA wrapper 不重复打印。", flush=True)

    proc = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    output_filter = OutputFilter(compact=compact, reset_log_every=reset_log_every)
    output_thread = stream_output(proc, output_filter)

    def finish(exit_code: int) -> int:
        print_resource_summary_if_needed(module_key, uid, sign, args.server, resource_start_inv, resource_start_time)
        return exit_code

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
            commands.extend(build_default_start_commands(module_key, train_team_count))

        send_commands(proc, commands)

        run_seconds = max(1, int(args.run_minutes) * 60)
        print(f"[GHA] 运行窗口：{args.run_minutes} 分钟。", flush=True)
        if wait_until(proc, run_seconds):
            output_thread.join(timeout=5)
            return finish(proc.returncode or 0)

        stop_commands = parse_lines(args.stop_commands) or DEFAULT_STOP_COMMANDS
        print("[GHA] 到达运行窗口，发送安全停止命令。", flush=True)
        send_commands(proc, stop_commands, delay=2.0)
        if wait_until(proc, 180):
            output_thread.join(timeout=5)
            return finish(proc.returncode or 0)
        terminate_process(proc)
        output_thread.join(timeout=5)
        return finish(proc.returncode if proc.returncode is not None else 124)
    except KeyboardInterrupt:
        print("[GHA] 收到中断，发送安全停止。", flush=True)
        send_commands(proc, DEFAULT_STOP_COMMANDS, delay=1.0)
        terminate_process(proc)
        output_thread.join(timeout=5)
        return finish(130)


if __name__ == "__main__":
    raise SystemExit(main())
