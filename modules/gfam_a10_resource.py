# ===== GFAM project-local dependency loader =====
# 优先加载项目内 ZIRC submodule 的 src/core，避免依赖 PyPI 或系统环境里的旧版本。
import os as _gfam_os
import sys as _gfam_sys
_gfam_root = _gfam_os.path.abspath(_gfam_os.path.join(_gfam_os.path.dirname(__file__), ".."))
_gfam_zirc_core = _gfam_os.path.join(_gfam_root, "libs", "ZIRC", "src", "core")
if _gfam_zirc_core not in _gfam_sys.path:
    _gfam_sys.path.insert(0, _gfam_zirc_core)
# ===============================================

# -*- coding: utf-8 -*-
"""GFAM A-10 四项资源获取。

方案说明：
- 基于 EPA 普通 A-10（mission_id=144）。
- 只部署第一梯队，且运行前校验第一梯队必须为单人梯队。
- 开始战役后不移动、不 battleFinish，直接结束回合并结算。
- 运行前/结束后各请求一次 Index/index，用于四项资源统计。
- 本模块不启动代理，优先沿用 GFAM 主菜单 / GHA 环境中的 UID/SIGN。
"""

import os
import sys
import time
import json
import threading
import traceback
from typing import Dict, List, Optional, Tuple

from gflzirc import (
    GFLClient, GFLProxy, set_windows_proxy,
    SERVERS, STATIC_KEY, DEFAULT_SIGN,
    API_MISSION_START, API_MISSION_END_TURN,
    API_MISSION_START_ENEMY_TURN, API_MISSION_END_ENEMY_TURN,
    API_MISSION_START_TURN, API_MISSION_ABORT, API_GUN_RETIRE,
)

try:
    from gfam_api_lock import patch_gfl_client
    patch_gfl_client()
except Exception:
    pass

try:
    from gflzirc import API_INDEX_INDEX
except Exception:
    API_INDEX_INDEX = "Index/index"

try:
    from gfam_index_cache import IndexCacheManager
except ImportError:
    IndexCacheManager = None

try:
    from gfam_crossprocess_lock import RetireLock
except ImportError:
    RetireLock = None

_a10_index_mgr = None  # IndexCacheManager 实例，延迟初始化

try:
    from gfam_fairy_stats import read_fairy_snapshot, fairy_runtime_status_line, print_fairy_summary, update_fairy_cache_from_index_payload
except Exception:
    def read_fairy_snapshot():
        return {}
    def fairy_runtime_status_line():
        return ""
    def print_fairy_summary(start_snapshot=None):
        return None
    def update_fairy_cache_from_index_payload(payload, source="Index/index"):
        return False

MISSION_ID = 144
START_SPOT = 97026
TEAM_ID = 1
RESOURCE_KEYS = ("mp", "ammo", "mre", "part")
RESOURCE_LABELS = {
    "mp": "人力",
    "ammo": "弹药",
    "mre": "口粮",
    "part": "零件",
}

CONFIG = {
    "USER_UID": "_InputYourID_",
    "SIGN_KEY": DEFAULT_SIGN,
    "SERVER_NAME": "SOP",
    "BASE_URL": SERVERS.get("SOP"),
    "PROXY_PORT": 12335,
    "MACRO_LOOPS": 0,
    "MAX_CONSECUTIVE_FAILURES": 8,
}

# A-10 方案不移动、不进战斗，流程很短；本版为“极速测试版”。
# 默认不再主动按 2 RPS 节流，而是尽量压低本地等待，把速度交给服务器响应本身限制。
# 重要：上一版（GFAM_v1.0_A10_strict_stop_trace + 2rps）已作为稳定基准；
# 如本版出现 error:2 / plaintext response / 资源统计异常，可用下列环境变量回退：
#   GFAM_A10_TARGET_RPS=2
#   GFAM_A10_STEP_DELAY=0.01
#   GFAM_A10_ROUND_DELAY=0
#   GFAM_A10_FAILURE_DELAY=0.30
# 说明：GFAM_A10_TARGET_RPS=0 表示关闭目标 RPS 节流。
A10_TARGET_RPS = max(0.0, float(os.environ.get("GFAM_A10_TARGET_RPS", "0") or 0.0))
A10_MIN_ROUND_SECONDS = (1.0 / A10_TARGET_RPS) if A10_TARGET_RPS > 0 else 0.0
A10_STEP_DELAY = max(0.0, float(os.environ.get("GFAM_A10_STEP_DELAY", "0") or 0.0))
A10_ROUND_DELAY = max(0.0, float(os.environ.get("GFAM_A10_ROUND_DELAY", "0") or 0.0))
A10_FAILURE_DELAY = max(0.0, float(os.environ.get("GFAM_A10_FAILURE_DELAY", "0.20") or 0.20))
A10_TRACE_RESOURCE = str(os.environ.get("GFAM_A10_TRACE_RESOURCE", "0") or "0").strip().lower() in ("1", "true", "yes", "y", "on")
A10_EXIT_JOIN_SECONDS = max(0.0, float(os.environ.get("GFAM_A10_EXIT_JOIN_SECONDS", "30") or 30))

current_worker_thread = None
worker_mode = None
proxy_instance = None
stop_macro_flag = False

RUN_STATS = {
    "running": False,
    "start_time": 0.0,
    "macro": 0,
    "success": 0,
    "failures": 0,
    "last_points": "-",
    "last_drop": "无",
    "dropped_gun_count": 0,
    "retired_gun_count": 0,
    "resource_start": None,
    "resource_end": None,
    "resource_cache_source": "-",
}


def _safe_int(value, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(float(str(value).strip()))
    except Exception:
        return default


def _normalize_server_name(server):
    server = str(server or "").strip().upper().replace("_", "-")
    if server == "AR15":
        server = "AR-15"
    return server


def apply_gfam_selected_server() -> bool:
    server = _normalize_server_name(os.environ.get("GFAM_SELECTED_SERVER") or os.environ.get("GFAM_SERVER") or CONFIG.get("SERVER_NAME") or "SOP")
    aliases = [server]
    if server == "AR-15":
        aliases.append("AR15")
    for key in aliases:
        if key in SERVERS:
            CONFIG["SERVER_NAME"] = server
            CONFIG["BASE_URL"] = SERVERS[key]
            return True
    print("[!] 当前 gflzirc 未找到服务器配置：%s" % server)
    print("[!] 可用服务器键：%s" % ", ".join(sorted(str(k) for k in SERVERS.keys())))
    return False


def apply_gfam_auth_from_env() -> bool:
    uid = str(os.environ.get("GFAM_USER_UID") or "").strip()
    sign = str(os.environ.get("GFAM_SIGN_KEY") or "").strip()
    if uid and sign and sign != DEFAULT_SIGN:
        CONFIG["USER_UID"] = uid
        CONFIG["SIGN_KEY"] = sign
        print("[+] 已沿用 GFAM 主菜单/GHA 获取的 UID/SIGN。")
        return True
    print("[!] UID/SIGN 未就绪，本模块不会自行启动代理。")
    return False


def make_client() -> GFLClient:
    return GFLClient(CONFIG["USER_UID"], CONFIG["SIGN_KEY"], CONFIG["BASE_URL"])


def check_step_error(resp: dict, step_name: str) -> bool:
    if not isinstance(resp, dict):
        print("[-] %s 本地错误：响应格式无效。" % step_name)
        return True
    if "error_local" in resp:
        print("[-] %s 本地错误：%s" % (step_name, resp.get("error_local")))
        preview = resp.get("raw_preview")
        if preview:
            print("    响应预览：%s" % preview)
        return True
    if "error" in resp:
        print("[-] %s 服务器错误：%s" % (step_name, resp.get("error")))
        return True
    return False


def request_index(client: GFLClient, label: str = "Index/index",
                  *, bypass: bool = False) -> Optional[dict]:
    global _a10_index_mgr
    if _a10_index_mgr is None and IndexCacheManager is not None:
        _a10_index_mgr = IndexCacheManager(client, ttl=120, label="A10",
                                           shared_file=".gfam_index_cache.json")
    if _a10_index_mgr is not None:
        if bypass:
            return _a10_index_mgr.bypass(client, reason=label)
        return _a10_index_mgr.get(reason=label)
    # 降级：原始逻辑
    try:
        resp = client.send_request(API_INDEX_INDEX, {"time": int(time.time()), "furniture_data": False}, max_retries=2, timeout=20)
    except TypeError:
        resp = client.send_request(API_INDEX_INDEX, {"time": int(time.time()), "furniture_data": False})
    except Exception as exc:
        print("[!] %s 请求失败：%s" % (label, exc))
        return None
    if check_step_error(resp, label):
        return None
    try:
        from gfam_fairy_stats import update_fairy_cache_from_index_payload
        update_fairy_cache_from_index_payload(resp, source=label)
    except Exception:
        pass
    return resp


def extract_resources_from_index(payload: Optional[dict]) -> Optional[Dict[str, int]]:
    if not isinstance(payload, dict):
        return None
    user_info = payload.get("user_info")
    if not isinstance(user_info, dict):
        return None
    return {key: _safe_int(user_info.get(key), 0) for key in RESOURCE_KEYS}


def fmt_resources(inv: Optional[Dict[str, int]], signed: bool = False) -> str:
    inv = inv or {key: 0 for key in RESOURCE_KEYS}
    parts = []
    for key in RESOURCE_KEYS:
        value = _safe_int(inv.get(key), 0)
        text = ("%+d" % value) if signed else str(value)
        parts.append("%s %s" % (RESOURCE_LABELS[key], text))
    return " / ".join(parts)


def diff_resources(start: Optional[Dict[str, int]], end: Optional[Dict[str, int]]) -> Dict[str, int]:
    start = start or {key: 0 for key in RESOURCE_KEYS}
    end = end or {key: 0 for key in RESOURCE_KEYS}
    return {key: _safe_int(end.get(key), 0) - _safe_int(start.get(key), 0) for key in RESOURCE_KEYS}


def trace_resource_snapshot(client: GFLClient, label: str) -> None:
    """Optional resource tracing for A-10 debugging.

    Disabled by default because it requests Index/index at extra points.
    Enable with GFAM_A10_TRACE_RESOURCE=1 when verifying exactly which step
    changes the four basic resources.
    """
    if not A10_TRACE_RESOURCE:
        return
    payload = request_index(client, "A10 TRACE %s" % label)
    inv = extract_resources_from_index(payload)
    if inv is None:
        print("[A10-TRACE][资源] %s：Index 解析失败。" % label)
    else:
        print("[A10-TRACE][资源] %s：%s" % (label, fmt_resources(inv)))


def team1_guns_from_index(payload: Optional[dict]) -> List[dict]:
    if not isinstance(payload, dict):
        return []
    gun_list = payload.get("gun_with_user_info", [])
    if not isinstance(gun_list, list):
        return []
    result = []
    for gun in gun_list:
        if not isinstance(gun, dict):
            continue
        try:
            team_id = int(gun.get("team_id", 0) or 0)
        except Exception:
            team_id = 0
        if team_id == TEAM_ID:
            result.append(gun)
    return result


def validate_team1_single(payload: Optional[dict]) -> bool:
    guns = team1_guns_from_index(payload)
    if len(guns) != 1:
        print("[!] A-10 四项资源获取要求第一梯队为单人梯队。")
        print("[!] 当前 Index 解析到第一梯队人数：%d。请回游戏调整后再运行。" % len(guns))
        return False
    gun = guns[0]
    print("[+] 第一梯队单人校验通过：UID=%s gun_id=%s life=%s" % (
        str(gun.get("id") or gun.get("gun_with_user_id") or "-"),
        str(gun.get("gun_id") or "-"),
        str(gun.get("life") or "-"),
    ))
    return True


def parse_gun_storage_from_index(payload: Optional[dict]) -> dict:
    """从 Index/index 中读取人形仓库本地缓存。

    仅用于 A-10 运行中本地估算，不主动全仓库扫描拆解。
    """
    if not isinstance(payload, dict):
        return {"used": None, "max": None, "free": None}
    user_info = payload.get("user_info") if isinstance(payload.get("user_info"), dict) else {}
    max_gun = _safe_int(user_info.get("maxgun"), 0)
    guns = payload.get("gun_with_user_info")
    used = len(guns) if isinstance(guns, list) else 0
    if max_gun <= 0:
        return {"used": used or None, "max": None, "free": None}
    free = max(0, max_gun - used)
    return {"used": used, "max": max_gun, "free": free}


_FACTORY_WH_CACHE = os.path.join(_gfam_root, ".gfam_factory_warehouse_cache.json")
_A10_SUMMARY_FILE = os.path.join(_gfam_root, ".gfam_a10_summary.json")


def _read_factory_gun_free():
    """Read gun_free from the factory auto warehouse cache, or None if unavailable."""
    try:
        if not os.path.isfile(_FACTORY_WH_CACHE):
            return None
        raw = open(_FACTORY_WH_CACHE, "r", encoding="utf-8").read()
        data = json.loads(raw)
        val = data.get("gun_free")
        if val is not None:
            return max(0, int(val))
        return None
    except Exception:
        return None


def add_unique_pending_guns(pending: List[int], gun_uids: List[int]) -> None:
    seen = set(pending)
    for uid in gun_uids or []:
        try:
            uid = int(uid)
        except Exception:
            continue
        if uid > 0 and uid not in seen:
            seen.add(uid)
            pending.append(uid)


def parse_win_gun_drops(resp: Optional[dict]) -> List[int]:
    if not isinstance(resp, dict):
        return []
    win_result = resp.get("mission_win_result")
    if not isinstance(win_result, dict):
        return []
    reward_gun = win_result.get("reward_gun", [])
    if not isinstance(reward_gun, list):
        return []
    out = []
    for gun in reward_gun:
        if not isinstance(gun, dict):
            continue
        uid = gun.get("gun_with_user_id") or gun.get("id") or gun.get("uid")
        try:
            uid = int(uid)
        except Exception:
            continue
        if uid > 0:
            out.append(uid)
    return out


# 官方服务器处理大批量拆解时可能响应较慢，延长单次请求超时时间避免误判为 plaintext 错误。
A10_RETIRE_BATCH_SIZE = max(20, int(os.environ.get("GFAM_A10_RETIRE_BATCH_SIZE", str(CONFIG.get("A10_RETIRE_BATCH_SIZE", 80))) or 80))
A10_RETIRE_BATCH_DELAY = max(0.0, float(os.environ.get("GFAM_A10_RETIRE_BATCH_DELAY", str(CONFIG.get("A10_RETIRE_BATCH_DELAY", 0.25))) or 0.25))
# A-10 会持续获得结算人形；每累计 10 个待拆 UID 就提交一次拆解，避免仓库空位耗尽。
A10_PENDING_RETIRE_LIMIT = max(1, int(os.environ.get("GFAM_A10_PENDING_RETIRE_LIMIT", "10") or "10"))
# 按仓库剩余空位提前拆解：空位充足时留 5 个缓冲，空位紧张（≤10）时留 2 个。
A10_RETIRE_FREE_NORMAL = max(1, int(os.environ.get("GFAM_A10_RETIRE_FREE_NORMAL", "5") or "5"))
A10_RETIRE_FREE_TIGHT = max(1, int(os.environ.get("GFAM_A10_RETIRE_FREE_TIGHT", "2") or "2"))
# 拆解请求的 HTTP 超时时间（秒），默认 30s 比常规 API 的 15s 更宽松。
A10_RETIRE_TIMEOUT = max(10, int(os.environ.get("GFAM_A10_RETIRE_TIMEOUT", "30") or "30"))
A10_RETIRE_UNKNOWN_KEYWORDS = (
    "unexpected plaintext response", "plaintext response", "timed out", "timeout",
    "read timed", "connection aborted", "remote end closed", "error:2",
)


def _a10_chunked(values, size):
    size = max(1, int(size or 80))
    for i in range(0, len(values), size):
        yield values[i:i + size]


def _a10_compact_error(resp):
    if isinstance(resp, dict):
        for key in ("error_local", "error", "raw", "raw_preview", "message"):
            if resp.get(key):
                return str(resp.get(key))
        return str(resp)
    return str(resp)


def _a10_retire_response_unknown(resp) -> bool:
    text = _a10_compact_error(resp).lower()
    return any(k in text for k in A10_RETIRE_UNKNOWN_KEYWORDS)


def retire_guns(client: GFLClient, gun_uids: List[int], reason: str = "人形自动拆解") -> int:
    """Batch-retire dropped dolls for A-10.

    The old implementation submitted hundreds of UIDs in one request.  On the
    official server, a 350+ UID request can take long enough that gflzirc sees
    an Unexpected plaintext response even though the server may still process
    the request.  Submit conservative batches and mark unknown responses so the
    caller does not repeatedly re-submit the same giant pending list.
    """
    retire_guns.last_unknown = False
    if gun_uids is None:
        return 0

    clean = []
    seen = set()
    for uid in gun_uids:
        try:
            uid = int(uid)
        except Exception:
            continue
        if uid > 0 and uid not in seen:
            seen.add(uid)
            clean.append(uid)
    if not clean:
        return 0

    total_ok = 0
    total = len(clean)
    print("[*] %s：准备拆解 %d 名人形；按每批最多 %d 分批提交。" % (reason, total, A10_RETIRE_BATCH_SIZE))

    # Acquire cross-process lock to avoid concurrent Gun/retireGun with factory auto
    _lock = RetireLock() if RetireLock else None
    if _lock and not _lock.acquire(timeout=10):
        print("[!] 未能获取跨进程拆解锁（跟随模块制造可能正在拆解），本轮跳过拆解。")
        retire_guns.last_unknown = True
        return 0

    try:
        for batch_no, batch in enumerate(_a10_chunked(clean, A10_RETIRE_BATCH_SIZE), start=1):
            print("[*] %s：提交人形拆解批次 %d，数量 %d/%d。" % (reason, batch_no, len(batch), total))
            try:
                resp = client.send_request(API_GUN_RETIRE, list(batch), timeout=A10_RETIRE_TIMEOUT)
            except Exception as exc:
                resp = {"error_local": str(exc)}

            if isinstance(resp, dict) and resp.get("success"):
                total_ok += len(batch)
                print("[+] 人形拆解批次成功：%d。" % len(batch))
                if A10_RETIRE_BATCH_DELAY > 0:
                    time.sleep(A10_RETIRE_BATCH_DELAY)
                continue

            if _a10_retire_response_unknown(resp):
                retire_guns.last_unknown = True
                print("[!] 人形拆解批次响应状态未知：%s" % _a10_compact_error(resp))
                _raw = resp.get("raw") if isinstance(resp, dict) else None
                _status = resp.get("status_code") if isinstance(resp, dict) else None
                if _raw or _status:
                    print("[!] 拆解原始响应：status_code=%s，raw=%s" % (_status, repr(_raw)[:300] if _raw else "None"))
                print("[!] 已停止后续拆解批次，避免重复提交同一批 UID；下轮将重试未确认的 UID。")
                return total_ok

            print("[-] 自动拆解返回异常：%s" % str(resp))
            return total_ok
    finally:
        if _lock:
            _lock.release()

    print("[+] 自动拆解完成：%d/%d。" % (total_ok, total))
    return total_ok


def abort_current_mission(client: GFLClient, source: str = "abort") -> None:
    try:
        print("[*] %s：尝试 abortMission 清理当前 A-10 状态。" % source)
        client.send_request(API_MISSION_ABORT, {"mission_id": MISSION_ID})
    except Exception as exc:
        print("[!] abortMission 失败：%s" % exc)


def throttle_a10_round(round_started_at: float) -> None:
    """按目标 RPS 轻量节流，默认约 2 次结算/秒。

    如果服务器请求本身已经超过目标周期，则不额外等待；
    如果请求过快，则补足到 A10_MIN_ROUND_SECONDS。
    A10_ROUND_DELAY 作为额外保守等待，默认 0。
    """
    elapsed = max(0.0, time.time() - float(round_started_at or time.time()))
    target_wait = max(0.0, A10_MIN_ROUND_SECONDS - elapsed)
    extra_wait = max(0.0, A10_ROUND_DELAY)
    wait_time = max(target_wait, extra_wait)
    if wait_time > 0:
        time.sleep(wait_time)


def run_one_a10_resource(client: GFLClient) -> Optional[dict]:
    """Run one A-10 no-move resource attempt.

    Return {'guns': [...]} on success, None on protocol/flow failure.

    抓包确认 A-10 单人不移动方案没有 Mission/combInfo 前置请求；
    成功流程应直接 startMission -> endTurn -> startEnemyTurn ->
    endEnemyTurn -> startTurn，并在 startTurn 响应中读取 mission_win_result。
    """
    start_payload = {
        "mission_id": MISSION_ID,
        "spots": [{"spot_id": START_SPOT, "team_id": TEAM_ID}],
        "squad_spots": [],
        "sangvis_spots": [],
        "vehicle_spots": [],
        "ally_spots": [],
        "mission_ally_spots": [],
        "ally_id": int(time.time()),
    }
    trace_resource_snapshot(client, "startMission 前")
    if check_step_error(client.send_request(API_MISSION_START, start_payload), "startMission"):
        return None
    trace_resource_snapshot(client, "startMission 后")

    # 本方案不移动、不 battleFinish。直接结束回合，进入结算。
    # startMission 后的中间回合响应不会携带有效 mission_win_result；
    # 最终以 startTurn 响应里的 mission_win_result 作为胜利结算来源。
    if check_step_error(client.send_request(API_MISSION_END_TURN, {}), "endTurn"):
        return None
    if A10_STEP_DELAY:
        time.sleep(A10_STEP_DELAY)
    if check_step_error(client.send_request(API_MISSION_START_ENEMY_TURN, {}), "startEnemyTurn"):
        return None
    if A10_STEP_DELAY:
        time.sleep(A10_STEP_DELAY)
    if check_step_error(client.send_request(API_MISSION_END_ENEMY_TURN, {}), "endEnemyTurn"):
        return None
    if A10_STEP_DELAY:
        time.sleep(A10_STEP_DELAY)
    win_resp = client.send_request(API_MISSION_START_TURN, {})
    if check_step_error(win_resp, "startTurn"):
        return None
    trace_resource_snapshot(client, "startTurn 结算后")

    guns = parse_win_gun_drops(win_resp)
    return {"guns": guns}


def print_resource_summary() -> None:
    start = RUN_STATS.get("resource_start")
    end = RUN_STATS.get("resource_end")
    diff = diff_resources(start, end)
    elapsed = max(1, int(time.time() - float(RUN_STATS.get("start_time") or time.time())))
    per_hour = {key: int(round(_safe_int(diff.get(key), 0) * 3600 / elapsed)) for key in RESOURCE_KEYS}
    print("\n=========== A-10 四项资源获取统计 ===========")
    print("运行总时长：%s" % format_duration(elapsed))
    print("完成轮数：%d" % int(RUN_STATS.get("success", 0) or 0))
    print("失败次数：%d" % int(RUN_STATS.get("failures", 0) or 0))
    print("起始库存：%s" % fmt_resources(start))
    print("结束库存：%s" % fmt_resources(end))
    print("本次变化：%s" % fmt_resources(diff, signed=True))
    print("每小时效率：%s" % fmt_resources(per_hour, signed=True))
    print("人形掉落/拆解：%d / %d" % (int(RUN_STATS.get("dropped_gun_count", 0) or 0), int(RUN_STATS.get("retired_gun_count", 0) or 0)))
    print("结束待拆解缓存：%d" % int(RUN_STATS.get("pending_gun_count", 0) or 0))
    try:
        print_fairy_summary(start_snapshot=None)
    except Exception:
        pass
    print("==========================================\n")

    # Write JSON summary for GUI popup
    _summary = {
        "kind": "a10",
        "server": CONFIG.get("SERVER_NAME", ""),
        "elapsed_seconds": elapsed,
        "elapsed_text": format_duration(elapsed),
        "success": int(RUN_STATS.get("success", 0) or 0),
        "failures": int(RUN_STATS.get("failures", 0) or 0),
        "macro": int(RUN_STATS.get("macro", 0) or 0),
        "resource_start": start,
        "resource_end": end,
        "resource_diff": diff,
        "resource_per_hour": per_hour,
        "dropped_gun_count": int(RUN_STATS.get("dropped_gun_count", 0) or 0),
        "retired_gun_count": int(RUN_STATS.get("retired_gun_count", 0) or 0),
        "pending_gun_count": int(RUN_STATS.get("pending_gun_count", 0) or 0),
        "gun_storage_free": RUN_STATS.get("gun_storage_free"),
        "gun_storage_max": RUN_STATS.get("gun_storage_max"),
    }
    # Include fairy stats if available
    try:
        _fairy_snap = read_fairy_snapshot()
        if _fairy_snap:
            _summary["fairy"] = _fairy_snap
    except Exception:
        pass
    try:
        with open(_A10_SUMMARY_FILE, "w", encoding="utf-8") as _f:
            json.dump(_summary, _f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    print("[SUMMARY] A-10 四项资源统计报告已生成。")


def format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return "%d小时%d分%d秒" % (h, m, s)
    if m:
        return "%d分%d秒" % (m, s)
    return "%d秒" % s


def print_status() -> None:
    elapsed = 0
    if RUN_STATS.get("start_time"):
        elapsed = int(time.time() - float(RUN_STATS["start_time"]))
    print("\n============= A-10 四项资源获取状态 =============")
    print("服务器：%s    关卡：普通 A-10    方案：第一梯队单人 / 不移动直接结算" % CONFIG.get("SERVER_NAME"))
    print("状态：%s    当前 MACRO：%d" % ("运行中" if RUN_STATS.get("running") else "待机", int(RUN_STATS.get("macro", 0) or 0)))
    print("成功轮数：%d    连续失败：%d / %d" % (int(RUN_STATS.get("success", 0) or 0), int(RUN_STATS.get("failures", 0) or 0), int(CONFIG.get("MAX_CONSECUTIVE_FAILURES", 8))))
    print("起始资源：%s" % fmt_resources(RUN_STATS.get("resource_start")))
    print("当前/结束资源：%s" % fmt_resources(RUN_STATS.get("resource_end")))
    print("最近掉落：%s" % RUN_STATS.get("last_drop", "无"))
    if RUN_STATS.get("gun_storage_free") is not None:
        print("人形仓库缓存空位：%s；待批量拆解：%d" % (RUN_STATS.get("gun_storage_free"), int(RUN_STATS.get("pending_gun_count", 0) or 0)))
    fairy_line = fairy_runtime_status_line()
    if fairy_line:
        print(fairy_line)
    print("本次运行：%s" % format_duration(elapsed))
    print("停止：-q 当前轮后停 / -E 返回 GFAM 主菜单")
    print("================================================\n")


def a10_resource_worker() -> None:
    global stop_macro_flag, worker_mode, current_worker_thread
    client = make_client()
    RUN_STATS.update({
        "running": True,
        "start_time": time.time(),
        "macro": 0,
        "success": 0,
        "failures": 0,
        "last_drop": "无",
        "dropped_gun_count": 0,
        "retired_gun_count": 0,
        "pending_gun_count": 0,
        "gun_storage_free": None,
        "gun_storage_max": None,
        "resource_start": None,
        "resource_end": None,
        "resource_cache_source": "-",
    })

    print("=== A-10 四项资源获取 Started ===")
    print("[*] 本方案只部署第一梯队；第一梯队必须为单人梯队；不移动、不 battleFinish，直接结束回合并结算。")
    if A10_TARGET_RPS > 0:
        print("[*] A-10 快速间隔：目标 %.2f 轮/秒（最小轮期 %.2fs），步骤 %.2fs / 额外轮间 %.2fs / 失败 %.2fs。" % (A10_TARGET_RPS, A10_MIN_ROUND_SECONDS, A10_STEP_DELAY, A10_ROUND_DELAY, A10_FAILURE_DELAY))
    else:
        print("[*] A-10 极速测试：已关闭目标 RPS 节流，步骤 %.2fs / 额外轮间 %.2fs / 失败 %.2fs。" % (A10_STEP_DELAY, A10_ROUND_DELAY, A10_FAILURE_DELAY))
    abort_current_mission(client, "正式运行前状态清理")
    index_payload = request_index(client, "运行前 Index/index", bypass=True)
    if index_payload is None:
        print("[!] 运行前 Index/index 失败，已停止。")
        RUN_STATS["running"] = False
        worker_mode, current_worker_thread = None, None
        return
    if not validate_team1_single(index_payload):
        RUN_STATS["running"] = False
        worker_mode, current_worker_thread = None, None
        return
    RUN_STATS["resource_start"] = extract_resources_from_index(index_payload)
    RUN_STATS["resource_end"] = RUN_STATS["resource_start"]
    storage = parse_gun_storage_from_index(index_payload)
    RUN_STATS["gun_storage_free"] = storage.get("free")
    RUN_STATS["gun_storage_max"] = storage.get("max")
    print("[*] 起始四项资源：%s" % fmt_resources(RUN_STATS.get("resource_start")))
    if storage.get("free") is not None:
        print("[*] 人形仓库缓存：%s/%s，空位 %s；A-10 将在待拆累计 %d 个或仓库耗尽时批量拆解。" % (storage.get("used"), storage.get("max"), storage.get("free"), A10_PENDING_RETIRE_LIMIT))
    else:
        print("[*] 人形仓库缓存未能完整解析；A-10 将按待拆累计 %d 个的阈值拆解。" % A10_PENDING_RETIRE_LIMIT)

    pending_guns: List[int] = []
    consecutive_failures = 0
    while not stop_macro_flag:
        RUN_STATS["macro"] = int(RUN_STATS.get("macro", 0) or 0) + 1
        macro = RUN_STATS["macro"]
        print("=== A-10 RESOURCE MACRO %d / 直到手动停止 ===" % macro)
        round_started_at = time.time()
        result = run_one_a10_resource(client)
        if result is None:
            consecutive_failures += 1
            RUN_STATS["failures"] = consecutive_failures
            print("[-] 本轮 A-10 直接结算失败，正在 abortMission 后继续/停止判断。")
            abort_current_mission(client, "A-10失败自清理")
            # 仓库已满且有未拆解人形时，尝试紧急拆解以恢复出击能力。
            if pending_guns and RUN_STATS.get("gun_storage_free") is not None and int(RUN_STATS.get("gun_storage_free") or 0) <= 0:
                print("[*] A-10 失败后紧急拆解：仓库已满且有 %d 个待拆人形，尝试释放空间。" % len(pending_guns))
                retired = retire_guns(client, pending_guns, reason="A-10 失败后紧急拆解")
                if retired > 0:
                    if RUN_STATS.get("gun_storage_free") is not None:
                        RUN_STATS["gun_storage_free"] = int(RUN_STATS.get("gun_storage_free") or 0) + int(retired)
                    del pending_guns[:int(retired)]
                    RUN_STATS["pending_gun_count"] = len(pending_guns)
                    print("[+] 紧急拆解成功 %d 个，仓库空位恢复至 %s，重置连续失败计数。" % (retired, RUN_STATS.get("gun_storage_free")))
                    consecutive_failures = 0
                    RUN_STATS["failures"] = 0
            if consecutive_failures >= int(CONFIG.get("MAX_CONSECUTIVE_FAILURES", 8)):
                print("[!] 连续失败达到上限，已停止。")
                break
            if A10_FAILURE_DELAY:
                time.sleep(A10_FAILURE_DELAY)
            continue

        consecutive_failures = 0
        RUN_STATS["failures"] = 0
        RUN_STATS["success"] = int(RUN_STATS.get("success", 0) or 0) + 1
        guns = list(result.get("guns") or [])
        RUN_STATS["dropped_gun_count"] = int(RUN_STATS.get("dropped_gun_count", 0) or 0) + len(guns)
        RUN_STATS["last_drop"] = "无" if not guns else "UID " + ", ".join(str(x) for x in guns)
        add_unique_pending_guns(pending_guns, guns)
        RUN_STATS["pending_gun_count"] = len(pending_guns)
        if guns and RUN_STATS.get("gun_storage_free") is not None:
            RUN_STATS["gun_storage_free"] = max(0, int(RUN_STATS.get("gun_storage_free") or 0) - len(guns))
        should_retire_now = False
        retire_reason = "A-10 批量拆解"
        if pending_guns:
            _free = int(RUN_STATS.get("gun_storage_free") or 0) if RUN_STATS.get("gun_storage_free") is not None else None
            # 条件1：待拆数量达到固定阈值。
            if len(pending_guns) >= A10_PENDING_RETIRE_LIMIT:
                should_retire_now = True
                retire_reason = "A-10 待拆人形达到 %d 个，批量拆解" % A10_PENDING_RETIRE_LIMIT
            # 条件2：仓库空位充足时，剩余空位 ≤ 5 则提前拆解。
            elif _free is not None and _free > 0 and _free <= A10_RETIRE_FREE_NORMAL:
                should_retire_now = True
                retire_reason = "A-10 仓库空位不足（剩余 %d ≤ %d），提前拆解" % (_free, A10_RETIRE_FREE_NORMAL)
            # 条件3：仓库初始就很紧张（≤10空位）时，剩余 ≤ 2 就拆解。
            elif _free is not None and _free > 0 and _free <= A10_RETIRE_FREE_TIGHT:
                should_retire_now = True
                retire_reason = "A-10 仓库空位紧张（剩余 %d ≤ %d），紧急拆解" % (_free, A10_RETIRE_FREE_TIGHT)
            # 条件4：仓库完全耗尽，兜底拆解。
            elif _free is not None and _free <= 0:
                should_retire_now = True
                retire_reason = "A-10 人形仓库缓存耗尽，批量拆解"
        if should_retire_now:
            retired = retire_guns(client, pending_guns, reason=retire_reason)
            RUN_STATS["retired_gun_count"] = int(RUN_STATS.get("retired_gun_count", 0) or 0) + int(retired or 0)
            if retired > 0:
                trace_resource_snapshot(client, "批量拆解后")
                if RUN_STATS.get("gun_storage_free") is not None:
                    RUN_STATS["gun_storage_free"] = int(RUN_STATS.get("gun_storage_free") or 0) + int(retired)
                del pending_guns[:int(retired)]
                RUN_STATS["pending_gun_count"] = len(pending_guns)
            if getattr(retire_guns, "last_unknown", False):
                print("[!] A-10 拆解响应状态未知或拆解锁被占用，未确认的 UID 已保留在待拆队列；%d 秒后继续刷取，下轮重试。" % 5)
                time.sleep(5)
                # Do NOT break – continue farming and retry retirement next cycle
        # Periodically sync gun_storage_free from factory auto warehouse cache
        if macro % 300 == 0:
            _factory_free = _read_factory_gun_free()
            if _factory_free is not None and RUN_STATS.get("gun_storage_free") is not None:
                _old_free = int(RUN_STATS.get("gun_storage_free") or 0)
                # Use the factory's value minus A-10's own pending guns that factory doesn't know about
                _adjusted_free = max(0, _factory_free - len(pending_guns))
                RUN_STATS["gun_storage_free"] = _adjusted_free
                if _old_free != _adjusted_free:
                    print("[*] 人形仓库缓存已同步跟随模块：空位 %d → %d（工厂缓存 %d - 本地待拆 %d）。" % (
                        _old_free, _adjusted_free, _factory_free, len(pending_guns)))
        print("[A-10] 第 %d 轮完成；本轮掉落：%s；待批量拆解 %d" % (macro, RUN_STATS["last_drop"], len(pending_guns)))
        throttle_a10_round(round_started_at)

    if pending_guns:
        retired = retire_guns(client, pending_guns, reason="A-10 运行结束收尾批量拆解")
        RUN_STATS["retired_gun_count"] = int(RUN_STATS.get("retired_gun_count", 0) or 0) + int(retired or 0)
        if retired > 0:
            trace_resource_snapshot(client, "收尾批量拆解后")
            del pending_guns[:int(retired)]
            RUN_STATS["pending_gun_count"] = len(pending_guns)
        if getattr(retire_guns, "last_unknown", False):
            print("[!] 收尾拆解响应状态未知，未确认的待拆 UID 已保留在日志中；请回游戏确认仓库状态后再继续。")
    print("[*] A-10 四项资源获取正在结束，申请一次 Index/index 统计资源变化……")
    end_payload = request_index(client, "结束 Index/index", bypass=True)
    if end_payload is not None:
        RUN_STATS["resource_end"] = extract_resources_from_index(end_payload)
    RUN_STATS["running"] = False
    print_status()
    print_resource_summary()
    print("[A10-FINAL-STATS-DONE] A-10 收尾完成，可以退出。")
    worker_mode, current_worker_thread = None, None


def print_menu() -> None:
    print("\n================= A-10 四项资源获取 MENU =================")
    print(" 当前服务器：%s" % CONFIG.get("SERVER_NAME"))
    print(" 方案：普通 A-10 / 第一梯队单人 / 不移动直接结束回合结算")
    print(" -r      : 开始 A-10 四项资源获取")
    print(" -q      : 当前轮结束后安全停止")
    print(" -abort  : 发送 abortMission 清理当前 A-10 战役状态")
    print(" -E      : 返回少女全自动 GFAM 主菜单")
    print("----------------------------------------------------------")
    print("说明：运行前会请求一次 Index/index 校验第一梯队是否为单人，并记录四项起始库存。")
    print("说明：运行中不移动、不 battleFinish；待拆人形默认累计 %d 个就拆解；结束时再次请求 Index/index 统计四项变化。" % A10_PENDING_RETIRE_LIMIT)
    if A10_TARGET_RPS > 0:
        print("说明：默认尝试 %.2f 轮/秒；步骤 %.2fs / 额外轮间 %.2fs，可用 GFAM_A10_TARGET_RPS 等环境变量覆盖。" % (A10_TARGET_RPS, A10_STEP_DELAY, A10_ROUND_DELAY))
    else:
        print("说明：当前为极速测试版，默认关闭目标 RPS 节流；步骤 %.2fs / 额外轮间 %.2fs，可用 GFAM_A10_TARGET_RPS 等环境变量回退。" % (A10_STEP_DELAY, A10_ROUND_DELAY))
    print("说明：如需排查资源变化，可临时设置 GFAM_A10_TRACE_RESOURCE=1 进行分段 Index 追踪。")
    print("==========================================================\n")


def shutdown_proxy_if_running() -> None:
    global proxy_instance
    if proxy_instance:
        try:
            proxy_instance.stop()
        except Exception:
            pass
        try:
            set_windows_proxy(False)
        except Exception:
            pass
        proxy_instance = None


def main() -> int:
    global stop_macro_flag, worker_mode, current_worker_thread
    apply_gfam_selected_server()
    apply_gfam_auth_from_env()
    print("[+] A-10 四项资源获取配置已就绪。")
    print_menu()
    while True:
        try:
            cmd = input("GFAM-A10> ").strip()
            if not cmd:
                continue
            cmd_prefix = cmd.split()[0]
            low = cmd_prefix.lower()
            if low == "-r":
                if current_worker_thread and current_worker_thread.is_alive():
                    print("[!] 当前已有运行线程。")
                    continue
                if CONFIG.get("SIGN_KEY") == DEFAULT_SIGN:
                    print("[!] UID/SIGN 未就绪，请从 GFAM 主菜单进入本模块。")
                    continue
                stop_macro_flag = False
                worker_mode = "run"
                current_worker_thread = threading.Thread(target=a10_resource_worker, daemon=True)
                current_worker_thread.start()
            elif low in ("-q", "-qnow"):
                stop_macro_flag = True
                print("[*] 将在当前 A-10 轮次结束后停止……")
            elif low == "-abort":
                if CONFIG.get("SIGN_KEY") == DEFAULT_SIGN:
                    print("[!] UID/SIGN 未就绪，无法 abortMission。")
                    continue
                abort_current_mission(make_client(), "手动")
            elif low in ("-e", "-exit", "-quit") or cmd_prefix == "-E":
                stop_macro_flag = True
                if current_worker_thread and current_worker_thread.is_alive():
                    print("[*] 正在等待 A-10 当前轮/收尾统计完成后返回主菜单……")
                    current_worker_thread.join(timeout=A10_EXIT_JOIN_SECONDS)
                    if current_worker_thread.is_alive():
                        print("[!] A-10 收尾等待超时，将返回主菜单；如需完整统计请优先使用 -q。")
                shutdown_proxy_if_running()
                print("[*] 已返回少女全自动 GFAM 主菜单。")
                return 0
            elif low in ("-status", "status"):
                print_status()
            else:
                print("[!] 未识别命令：%s" % cmd_prefix)
                print_menu()
        except KeyboardInterrupt:
            stop_macro_flag = True
            print("\n[*] 收到中断，将安全停止。再次输入 -E 返回主菜单。")
        except EOFError:
            stop_macro_flag = True
            return 0
        except Exception:
            print("[!] A-10 模块主循环异常：")
            traceback.print_exc()
            stop_macro_flag = True
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
