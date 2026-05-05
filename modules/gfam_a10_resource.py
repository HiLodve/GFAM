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
import threading
import traceback
from typing import Dict, List, Optional, Tuple

from gflzirc import (
    GFLClient, GFLProxy, set_windows_proxy,
    SERVERS, STATIC_KEY, DEFAULT_SIGN,
    API_MISSION_COMBINFO, API_MISSION_START, API_MISSION_END_TURN,
    API_MISSION_START_ENEMY_TURN, API_MISSION_END_ENEMY_TURN,
    API_MISSION_START_TURN, API_MISSION_ABORT, API_GUN_RETIRE,
)

try:
    from gflzirc import API_INDEX_INDEX
except Exception:
    API_INDEX_INDEX = "Index/index"

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


def request_index(client: GFLClient, label: str = "Index/index") -> Optional[dict]:
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


def retire_guns(client: GFLClient, gun_uids: List[int], reason: str = "人形自动拆解") -> int:
    if gun_uids is None:
        return 0
    print("[*] %s：提交 %d 名人形。" % (reason, len(gun_uids)))
    try:
        resp = client.send_request(API_GUN_RETIRE, list(gun_uids))
    except Exception as exc:
        print("[-] 自动拆解请求失败：%s" % exc)
        return 0
    if isinstance(resp, dict) and resp.get("success"):
        print("[+] 自动拆解成功。")
        return len(gun_uids)
    if isinstance(resp, dict) and not resp.get("error") and not resp.get("error_local") and not gun_uids:
        print("[+] 空掉落拆解确认完成。")
        return 0
    print("[-] 自动拆解返回异常：%s" % str(resp))
    return 0


def abort_current_mission(client: GFLClient, source: str = "abort") -> None:
    try:
        print("[*] %s：尝试 abortMission 清理当前 A-10 状态。" % source)
        client.send_request(API_MISSION_ABORT, {"mission_id": MISSION_ID})
    except Exception as exc:
        print("[!] abortMission 失败：%s" % exc)


def run_one_a10_resource(client: GFLClient) -> Optional[dict]:
    """Run one A-10 no-move resource attempt.

    Return {'guns': [...]} on success, None on protocol/flow failure.
    """
    if check_step_error(client.send_request(API_MISSION_COMBINFO, {"mission_id": MISSION_ID}), "combInfo"):
        return None

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
    if check_step_error(client.send_request(API_MISSION_START, start_payload), "startMission"):
        return None

    # 本方案不移动、不 battleFinish。直接结束回合，进入结算。
    if check_step_error(client.send_request(API_MISSION_END_TURN, {}), "endTurn"):
        return None
    time.sleep(0.15)
    if check_step_error(client.send_request(API_MISSION_START_ENEMY_TURN, {}), "startEnemyTurn"):
        return None
    time.sleep(0.15)
    if check_step_error(client.send_request(API_MISSION_END_ENEMY_TURN, {}), "endEnemyTurn"):
        return None
    time.sleep(0.15)
    win_resp = client.send_request(API_MISSION_START_TURN, {})
    if check_step_error(win_resp, "startTurn"):
        return None

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
    try:
        print_fairy_summary(start_snapshot=None)
    except Exception:
        pass
    print("==========================================\n")


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
        "resource_start": None,
        "resource_end": None,
        "resource_cache_source": "-",
    })

    print("=== A-10 四项资源获取 Started ===")
    print("[*] 本方案只部署第一梯队；第一梯队必须为单人梯队；不移动、不 battleFinish，直接结束回合并结算。")
    index_payload = request_index(client, "运行前 Index/index")
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
    print("[*] 起始四项资源：%s" % fmt_resources(RUN_STATS.get("resource_start")))

    consecutive_failures = 0
    while not stop_macro_flag:
        RUN_STATS["macro"] = int(RUN_STATS.get("macro", 0) or 0) + 1
        macro = RUN_STATS["macro"]
        print("=== A-10 RESOURCE MACRO %d / 直到手动停止 ===" % macro)
        result = run_one_a10_resource(client)
        if result is None:
            consecutive_failures += 1
            RUN_STATS["failures"] = consecutive_failures
            print("[-] 本轮 A-10 直接结算失败，正在 abortMission 后继续/停止判断。")
            abort_current_mission(client, "A-10失败自清理")
            if consecutive_failures >= int(CONFIG.get("MAX_CONSECUTIVE_FAILURES", 8)):
                print("[!] 连续失败达到上限，已停止。")
                break
            time.sleep(2)
            continue

        consecutive_failures = 0
        RUN_STATS["failures"] = 0
        RUN_STATS["success"] = int(RUN_STATS.get("success", 0) or 0) + 1
        guns = list(result.get("guns") or [])
        RUN_STATS["dropped_gun_count"] = int(RUN_STATS.get("dropped_gun_count", 0) or 0) + len(guns)
        RUN_STATS["last_drop"] = "无" if not guns else "UID " + ", ".join(str(x) for x in guns)
        retired = retire_guns(client, guns, reason="A-10 胜利结算后人形拆解") if guns else retire_guns(client, [], reason="A-10 空掉落拆解确认")
        RUN_STATS["retired_gun_count"] = int(RUN_STATS.get("retired_gun_count", 0) or 0) + int(retired or 0)
        print("[A-10] 第 %d 轮完成；本轮掉落：%s" % (macro, RUN_STATS["last_drop"]))
        time.sleep(1)

    print("[*] A-10 四项资源获取正在结束，申请一次 Index/index 统计资源变化……")
    end_payload = request_index(client, "结束 Index/index")
    if end_payload is not None:
        RUN_STATS["resource_end"] = extract_resources_from_index(end_payload)
    RUN_STATS["running"] = False
    print_status()
    print_resource_summary()
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
    print("说明：运行中不移动、不 battleFinish；结束时再次请求 Index/index 统计四项变化。")
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
