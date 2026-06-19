# ===== GFAM project-local dependency loader =====
# 优先加载项目内 ZIRC submodule 的 src/core，避免依赖 PyPI 或系统环境里的旧版本。
# gflzirc 位于：libs/ZIRC/src/core/gflzirc
import os as _gfam_os
import sys as _gfam_sys
_gfam_root = _gfam_os.path.abspath(_gfam_os.path.join(_gfam_os.path.dirname(__file__), ".."))
_gfam_zirc_core = _gfam_os.path.join(_gfam_root, "libs", "ZIRC", "src", "core")
if _gfam_zirc_core not in _gfam_sys.path:
    _gfam_sys.path.insert(0, _gfam_zirc_core)
# ===============================================

# src/demo/farm/resource/pick_coin.py
# Menu-polished version based on the EPA-style interactive flow.

import sys
import time
import json
import os
import threading
import traceback
try:
    import msvcrt
except Exception:
    msvcrt = None
from gflzirc import (
    GFLClient, GFLProxy, set_windows_proxy,
    SERVERS, STATIC_KEY, DEFAULT_SIGN,
    API_MISSION_COMBINFO, API_MISSION_START, API_INDEX_GUIDE,
    API_MISSION_TEAM_MOVE, API_MISSION_ABORT, API_GUN_RETIRE,
    GUIDE_COURSE_10352
)

# 技能训练接口名称不同版本的 gflzirc 可能尚未导出，因此这里先使用字符串兜底。
# 若后续抓包确认 endpoint 不同，只需要修改这两个常量。
try:
    from gflzirc import API_GUN_SKILL_UPGRADE
except ImportError:
    # gflzirc.send_request 通常传入的是业务路径。
    # 抓包文件名中的 3000_Gun_skillUpgrade 里的 3000 不一定应作为 URL/path 前缀。
    API_GUN_SKILL_UPGRADE = "Gun/skillUpgrade"

# 技能训练 endpoint 兼容候选。
# 若某个路径返回 plaintext / 404 类错误，会自动尝试下一个。
SKILL_UPGRADE_ENDPOINT_CANDIDATES = [
    API_GUN_SKILL_UPGRADE,
    "Gun/skillUpgrade",
    "3000/Gun/skillUpgrade",
]

try:
    from gflzirc import API_GUN_FINISH_SKILL_UPGRADE
except ImportError:
    API_GUN_FINISH_SKILL_UPGRADE = "3000/Gun/finish_skill_upgrade"

try:
    from gflzirc import API_INDEX_INDEX
except ImportError:
    API_INDEX_INDEX = "Index/index"

try:
    from gfam_index_cache import IndexCacheManager
except ImportError:
    IndexCacheManager = None

_pick_index_mgr = None  # IndexCacheManager 实例，延迟初始化

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

CONFIG = {
    # === Authentication & Connection ===
    "USER_UID": "_InputYourID_",
    "SIGN_KEY": DEFAULT_SIGN,
    "SERVER_NAME": "SOP",
    "BASE_URL": SERVERS["SOP"],
    # 避免占用常见 8080 端口。
    "PROXY_PORT": 12335,

    # === Farming Settings ===
    # 获取训练资料不再按固定最大轮次停止，而是一直运行到自动停止条件：
    # - 中级训练资料本次获得为 0；
    # - 用户手动 -q / -Q 中断；
    # - 自动循环结束或出现无法继续的错误。
    # 如需临时限制轮次，可改成正整数；0/None 表示不限制。
    "MACRO_LOOPS": 0,
    # 运行中 Micro 失败时，先尝试一次人形应急拆解并重试当前 Micro。
    "ENABLE_GUN_EXCEPTION_SELF_REPAIR": True,
    "MISSIONS_PER_RETIRE": 50,
    # 自适应间隔：默认保持原速度；连续遇到 plaintext / error:2 / error:3 / error:300 时自动放慢关键接口。
    "ADAPTIVE_TIMING_ENABLED": True,
    "ADAPTIVE_TIMING_MAX_LEVEL": 8,
    "ADAPTIVE_TIMING_TRIGGER_ERRORS": 1,
    "ADAPTIVE_TIMING_DECAY_SUCCESSES": 120,
    "ADAPTIVE_TIMING_STEP_EXTRA": 0.10,
    "ADAPTIVE_TIMING_STATE_EXTRA": 0.25,
    # 获取资料固定使用梯队 1，且要求梯队 1 为单人人形梯队。
    # 妖精可带可不带，不参与单人检测。
    "TEAM_ID": 1,
    "PICK_FIXED_TEAM_ID": 1,
    "PICK_REQUIRE_SINGLE_DOLL": True,
    "PICK_TEAM_VALIDATED": False,
    # Index/index 校验通过后自动写入，避免再手动修改梯队信息。
    "GUNS": [],
    # 获取资料不检测妖精；保留字段仅为兼容旧逻辑。
    "FAIRY_ID": 0,
    "FAIRY": None,

    # === Skill Training Settings / 技能训练设置 ===
    # 默认关闭旧式自动训练总开关；主菜单“自动训练”流程不依赖手动计划。
        # 预演模式已移除；自动训练会直接提交训练请求。
            # 每次尝试间隔，避免连续请求过快。
    "SKILL_TRAIN_COOLDOWN_SECONDS": 2,
    # 快速训练：使用快速训练契约直接完成训练。
    "SKILL_TRAIN_IF_QUICK": 1,
    "SKILL_TRAIN_DEFAULT_SLOT": 1,
    # 自动训练统一从仓库信息中判断候选，不再维护手动训练计划。
    # 自动训练：不再依赖手动填 UID，而是从 Index/index 的 gun_with_user_info 判断可训练人形。
    "AUTO_SKILL_FROM_INDEX": True,
    "AUTO_SKILL_TARGET_LEVEL": 10,
    # 默认 True：只扫描/训练已锁定人形，降低误训练风险。
    # 如需包含未锁定人形，可用 -skill locked 切换。
    "AUTO_SKILL_ONLY_LOCKED": True,
    # True = 只训练当前梯队人形；False = 全仓库扫描。
    "AUTO_SKILL_TEAM_ONLY": False,
    # 训练前检测后勤 / 作战 / 探索状态；忙碌人形只统计，不自动训练。
    "AUTO_SKILL_EXCLUDE_BUSY": True,
    # 单次触发最多训练几个技能，避免一次性消耗过多资料。
    "AUTO_SKILL_MAX_PER_TRIGGER": 1,
    # 自动训练固定面板。
    "TRAIN_PANEL_ENABLED": True,
    "TRAIN_FIXED_PANEL_MODE": True,
    "TRAIN_PANEL_LOG_LINES": 10,
    # 训练/获取资料自动循环：
    # 自动训练资源不足 -> 切换获取资料；
    # 获取资料 coin2+0 -> 停止获取资料并切回自动训练；
    # 直到没有可训练人形。
    "TRAIN_PICK_CYCLE_ENABLED": True,

    # === Skill Data / Coin Detection ===
    # 内部字段 coin1/coin2/coin3 分别对应初级/中级/高级训练资料。
    # 检测到中级训练资料本次获得为 0 时，暂停获取资料并尝试自动训练技能。
    "PAUSE_ON_MIDDLE_COIN_ZERO": True,
    "AUTO_TRAIN_ON_MIDDLE_COIN_ZERO": True,
    # 获取资料模式：中级资料 coin2 +0 后，是否自动训练并在训练后继续获取资料。
    # True：coin2+0 -> 自动训练 -> 资料被消耗后继续获取资料。
    # False：中级训练资料 +0 后停止；若开启暂停后自动训练，则停前尝试训练一次。
    "PICK_AUTO_TRAIN_AND_RESUME": False,
    # 获取训练资料显示上限：库存达到 9999 后，该资料继续获取资料的获得量会变为 0；
    # 这只是获取资料来源上限，通过其他方式超过 9999 属于正常情况。
    # 当前只把 coin2（中级资料）+0 作为停止条件，coin1/coin3 +0 忽略。
    "PICK_COIN_CAP": 9999,
    "PICK_PANEL_ENABLED": True,
    # True：像 epa_plus 一样刷新固定面板；False：按普通日志向下打印。
    "PICK_FIXED_PANEL_MODE": True,
    "PICK_PANEL_EVERY_MICRO": True,
    "PICK_PANEL_LOG_LINES": 10,

    # === Mission 10352 ===
    "MISSION_ID": 10352,
    "START_SPOT": 13280,
    "ROUTE": [13277, 13278],
}

current_worker_thread = None
worker_mode = None
proxy_instance = None

stop_macro_flag = False
stop_micro_flag = False

CURRENT_MENU = "main"

TRAINING_SESSION_LOG = []
TRAIN_LOG_BUFFER = []
TRAIN_SESSION_STATS = {
    "running": False,
    "start_time": 0,
    "attempted": 0,
    "success": 0,
    "failed": 0,
    "skipped": 0,
    "current": "",
    "last_cost": {},
}
AUTO_TRAIN_INTERRUPT_REQUESTED = False

CAPTURE_SUCCESS_EVENT = threading.Event()

TRAIN_INDEX_CACHE = None
TRAIN_COUNT_READY = False
AUTO_TRAIN_LAST_STOP_REASON = ""
AUTO_TRAIN_LAST_STOP_DETAIL = ""

PICK_LOG_BUFFER = []

PICK_SESSION_STATS = {
    "running": False,
    "start_time": 0,
    "macro": 0,
    "micro": 0,
    "run_count": 0,
    "zero_stop_coin": "",
    "last_panel_time": 0,
}

SKILL_DATA_STATS = {
    "coin1": 0,   # 低级资料
    "coin2": 0,   # 中级资料
    "coin3": 0,   # 高级资料
    "middle_zero_detected": False,
    "last_rewards": {},
    "start_inventory": {},
    "current_inventory": {},
}

SERVER_KEY_ALIASES = {
    "SOP": ["SOP"],
    "RO635": ["RO635"],
    "M4A1": ["M4A1"],
    "M16": ["M16"],
    "AR-15": ["AR-15", "AR15"],
}




def apply_gfam_auth_from_env():
    """从 GFAM 主启动器接收已经抓取好的 UID/SIGN。"""
    try:
        uid = str(os.environ.get("GFAM_USER_UID") or "").strip()
        sign = str(os.environ.get("GFAM_SIGN_KEY") or "").strip()
        if uid and sign and sign != DEFAULT_SIGN:
            CONFIG["USER_UID"] = uid
            CONFIG["SIGN_KEY"] = sign
            if "INDEX_FETCH_READY" in CONFIG:
                CONFIG["INDEX_FETCH_READY"] = True
            print("[+] 已沿用 GFAM 主菜单获取的 UID/SIGN。")
            return True
    except Exception:
        pass
    return False


def get_default_server_from_env():
    value = str(os.environ.get("GFAM_SELECTED_SERVER") or os.environ.get("GFAM_SERVER") or "SOP").strip().upper().replace("_", "-")
    if value in ("SOP", "RO635", "M4A1", "M16", "AR-15", "AR15"):
        return "AR-15" if value == "AR15" else value
    return "SOP"

def launched_from_gfam_main():
    return bool(os.environ.get("GFAM_SELECTED_SERVER") or os.environ.get("GFAM_SERVER") or os.environ.get("GFAM_SKIP_SERVER_MENU"))

def normalize_menu_input(cmd: str) -> str:
    return str(cmd or "").strip()


def normalize_server_input(cmd: str):
    cmd = str(cmd or "").strip()
    if not cmd:
        return get_default_server_from_env()

    cmd_norm = cmd.upper().replace("_", "-")
    if cmd_norm in ("1", "-1", "SOP"):
        return "SOP"
    if cmd_norm in ("2", "-2", "RO635"):
        return "RO635"
    if cmd_norm in ("3", "-3", "M4A1"):
        return "M4A1"
    if cmd_norm in ("4", "-4", "M16"):
        return "M16"
    if cmd_norm in ("5", "-5", "AR15", "AR-15"):
        return "AR-15"
    return None


def apply_server_selection(server_name: str) -> bool:
    server_name = normalize_server_input(server_name)
    if not server_name:
        return False

    candidates = SERVER_KEY_ALIASES.get(server_name, [server_name])
    for key in candidates:
        if key in SERVERS:
            CONFIG["SERVER_NAME"] = server_name
            CONFIG["BASE_URL"] = SERVERS[key]
            print("[+] 已选择服务器：%s" % server_name)
            return True

    print("[!] 当前 gflzirc 未找到服务器配置：%s" % server_name)
    print("[!] 可用服务器键：%s" % ", ".join(sorted(str(k) for k in SERVERS.keys())))
    return False


def print_server_menu():
    print("\n=========== 服务器选择 ===========")
    print("请选择服务器：")
    print("  -1 : SOP")
    print("  -2 : RO635")
    print("  -3 : M4A1")
    print("  -4 : M16")
    print("  -5 : AR-15")
    print("----------------------------------")
    print("提示：可输入编号或服务器名，直接回车默认 %s" % get_default_server_from_env())
    print("==================================\n")


def is_key_ready():
    return bool(CONFIG.get("USER_UID")) and CONFIG.get("USER_UID") != "_InputYourID_" and CONFIG.get("SIGN_KEY") != DEFAULT_SIGN


def invalidate_train_index_cache():
    global TRAIN_INDEX_CACHE, TRAIN_COUNT_READY
    TRAIN_INDEX_CACHE = None
    TRAIN_COUNT_READY = False


def print_capture_menu():
    print("\n================= 密钥抓取 =================")
    print("当前服务器：%s | 单独运行抓取端口：%s" % (
        CONFIG.get("SERVER_NAME", "SOP"),
        CONFIG.get("PROXY_PORT"),
    ))
    print("当前状态：%s" % get_status_text())
    print("--------------------------------------------------------")
    print(" -a        : 单独运行时启动代理并抓取 UID / SIGN")
    print(" -server   : 切换服务器")
    print(" -status   : 查看当前配置与运行状态")
    print(" -help / h : 重新显示当前菜单")
    print(" -E        : 退出程序")
    print("--------------------------------------------------------")
    print("提示：密钥抓取成功前，获取资料菜单和自动训练菜单不会开放。")
    print("========================================================\n")



def get_status_text():
    if worker_mode == "r":
        return "自动运行中"
    if proxy_instance:
        return "代理抓取中"
    if is_key_ready():
        return "密钥已就绪"
    return "等待抓取密钥"


def print_main_menu():
    print("\n================= 训练资料与技能训练主菜单 =================")
    print("当前服务器：%s | 梯队：%s" % (
        CONFIG.get("SERVER_NAME", "SOP"),
        CONFIG.get("TEAM_ID"),
    ))
    print("当前状态：%s" % get_status_text())
    print("------------------------------------------------------")
    print(" -1 / -pick  : 进入获取训练资料菜单")
    print(" -2 / -train : 进入自动训练菜单")
    print(" -server     : 切换服务器")
    print(" -status     : 查看当前配置与运行状态")
    print(" -help / h   : 重新显示当前菜单")
    print(" -E          : 返回少女全自动 GFAM 主菜单")
    print("======================================================\n")


def print_pick_menu():
    print("\n================= 获取训练资料菜单 =================")
    print("当前服务器：%s | 固定梯队：1（单人人形） | 状态：%s" % (
        CONFIG.get("SERVER_NAME", "SOP"),
        get_status_text(),
    ))
    print("------------------------------------------------------")
    print(" -r      : 开始自动获取训练资料（固定梯队1，要求单人人形）")
    print(" -auto   : 切换 中级资料到上限后自动训练并继续获取资料")
    print("           当前：%s" % ("开启" if CONFIG.get("PICK_AUTO_TRAIN_AND_RESUME", False) else "关闭"))
    print(" -coin   : 查看技能资料统计 / 检测设置")
    print(" -q      : 当前 Macro 结束后安全停止")
    print(" -Q      : 当前 Micro 结束后安全停止")
    print(" -back/b : 返回主菜单")
    print(" -help/h : 重新显示当前菜单")
    print(" -E      : 返回少女全自动 GFAM 主菜单")
    print("------------------------------------------------------")
    print("提示：UID/SIGN 已由 GFAM 主菜单统一获取，本菜单不再重复启动代理。")
    print("提示：面板显示使用默认固定模式；调试命令 -panel / -panelmode 仍兼容但不在常用菜单展示。")
    if CONFIG.get("PICK_AUTO_TRAIN_AND_RESUME", False):
        print("规则：任一中级资料本次获得为 0 -> 自动训练 -> 若训练成功/消耗资料则继续获取资料；无可训练项则停止。")
    else:
        print("规则：任一中级资料本次获得为 0 -> 自动停止；若开启暂停后自动训练，则停前尝试训练一次。")
    print("======================================================\n")


def print_train_menu():
    print("\n================= 自动训练菜单 =================")
    print("当前服务器：%s | 目标Lv=%s | 循环=%s" % (
        CONFIG.get("SERVER_NAME", "SOP"),
        CONFIG.get("AUTO_SKILL_TARGET_LEVEL", 10),
        CONFIG.get("TRAIN_PICK_CYCLE_ENABLED", False),
    ))
    print("缓存状态：%s" % ("已缓存，进入 -count 后可 -run" if TRAIN_COUNT_READY and TRAIN_INDEX_CACHE is not None else "未缓存，请先 -count"))
    print("------------------------------------------------")
    print(" -count  : 获取 Index/index 并进入训练确认子菜单")
    print(" -cycle  : 切换训练/获取资料自动循环（默认开启）")
    print(" -panel  : 切换自动训练固定状态面板")
    print(" -target <等级> : 设置自动训练目标等级，默认 10")
    print(" -locked : 切换是否只训练已锁定人形")
    print(" -teamonly : 切换是否只扫描当前梯队")
    print(" -back/b : 返回主菜单")
    print(" -help/h : 重新显示当前菜单")
    print(" -E      : 返回少女全自动 GFAM 主菜单")
    print("================================================\n")


def print_status():
    print("\n============== 当前状态 ==============")
    print("服务器：%s" % CONFIG.get("SERVER_NAME", "SOP"))
    print("BASE_URL：%s" % CONFIG.get("BASE_URL"))
    print("代理端口：本模块不启动代理（UID/SIGN 由 GFAM 主菜单统一获取）")
    print("TEAM_ID：%s（获取资料固定使用梯队1，要求单人人形；妖精可带可不带）" % CONFIG.get("PICK_FIXED_TEAM_ID", 1))
    print("获取资料梯队校验：%s | GUNS=%s | 妖精：可带可不带，不检测" % (
        CONFIG.get("PICK_TEAM_VALIDATED", False),
        CONFIG.get("GUNS"),
    ))
    print("获取资料轮次：%s" % ("直到自动停止条件" if not int_safe(CONFIG.get("MACRO_LOOPS", 0), 0) else CONFIG.get("MACRO_LOOPS")))
    print("MISSIONS_PER_RETIRE：%s" % CONFIG.get("MISSIONS_PER_RETIRE"))
    print("UID：%s" % CONFIG.get("USER_UID"))
    print("SIGN 是否已配置：%s" % ("是" if CONFIG.get("SIGN_KEY") != DEFAULT_SIGN else "否"))
    print("代理状态：%s" % ("运行中" if proxy_instance else "未运行；本模块通常不需要代理"))
    print("运行模式：%s" % (worker_mode or "空闲"))
    print("停止标记：Macro=%s | Micro=%s" % (stop_macro_flag, stop_micro_flag))
    print("自动训练：Index自动=%s | 目标Lv=%s | 只训练锁定=%s | 只扫当前梯队=%s" % (
        CONFIG.get("AUTO_SKILL_FROM_INDEX", True),
        CONFIG.get("AUTO_SKILL_TARGET_LEVEL", 10),
        CONFIG.get("AUTO_SKILL_ONLY_LOCKED", True),
        CONFIG.get("AUTO_SKILL_TEAM_ONLY", False),
    ))
    print("资料统计：低级=%d | 中级=%d | 高级=%d | 中级0检测=%s" % (
        SKILL_DATA_STATS.get("coin1", 0),
        SKILL_DATA_STATS.get("coin2", 0),
        SKILL_DATA_STATS.get("coin3", 0),
        SKILL_DATA_STATS.get("middle_zero_detected", False),
    ))
    print("获取资料coin2+0自动训练并继续：%s" % CONFIG.get("PICK_AUTO_TRAIN_AND_RESUME", False))
    print("训练/获取资料自动循环：%s | 最近训练停止原因：%s %s" % (
        CONFIG.get("TRAIN_PICK_CYCLE_ENABLED", False),
        AUTO_TRAIN_LAST_STOP_REASON,
        AUTO_TRAIN_LAST_STOP_DETAIL,
    ))
    print("=====================================\n")


def on_traffic(event_type: str, url: str, data: dict):
    # 调试用：代理开启时若捕获到技能训练请求，会保存 skill_train_capture.json。
    try:
        url_l = str(url or "").lower()
        if ("skill" in url_l) and ("upgrade" in url_l or "train" in url_l):
            capture = {
                "event_type": event_type,
                "url": url,
                "data": data,
            }
            with open("skill_train_capture.json", "w", encoding="utf-8") as f:
                json.dump(capture, f, ensure_ascii=False, indent=4)
            print("\n[CAPTURE] 已保存技能训练请求到 skill_train_capture.json")
    except Exception as e:
        print("[CAPTURE] 保存技能训练抓包失败：%s" % e)

    if event_type == "SYS_KEY_UPGRADE":
        CONFIG["USER_UID"] = data.get("uid")
        CONFIG["SIGN_KEY"] = data.get("sign")
        print("\n[+] 成功！密钥已自动配置：")
        print("    UID  : %s" % CONFIG["USER_UID"])
        print("    SIGN : %s" % CONFIG["SIGN_KEY"])
        CAPTURE_SUCCESS_EVENT.set()
        print("\n[AUTO] 密钥抓取成功。")



ADAPTIVE_TIMING_STATE = {"level": 0, "timing_errors": 0, "stable_success": 0}


def gfam_resp_text(resp) -> str:
    try:
        if isinstance(resp, dict):
            return " | ".join("%s=%s" % (k, resp.get(k)) for k in ("error_local", "error", "raw", "message", "msg") if k in resp) or str(resp)
        return str(resp)
    except Exception:
        return ""


def gfam_is_timing_sync_error(resp) -> bool:
    text = gfam_resp_text(resp).lower()
    return (
        "unexpected plaintext response" in text
        or "error:300" in text or "error=300" in text
        or "error:2" in text or "error=2" in text
        or "error:3" in text or "error=3" in text
    )


def gfam_adaptive_level() -> int:
    try:
        return max(0, int(ADAPTIVE_TIMING_STATE.get("level", 0) or 0))
    except Exception:
        return 0


def gfam_adaptive_extra(kind="step") -> float:
    if not CONFIG.get("ADAPTIVE_TIMING_ENABLED", True):
        return 0.0
    level = gfam_adaptive_level()
    if level <= 0:
        return 0.0
    if str(kind).lower() in ("sync", "abort", "start", "comb", "micro"):
        unit = float(CONFIG.get("ADAPTIVE_TIMING_STATE_EXTRA", 0.60) or 0.60)
    else:
        unit = float(CONFIG.get("ADAPTIVE_TIMING_STEP_EXTRA", 0.25) or 0.25)
    return max(0.0, level * unit)


def gfam_adaptive_sleep(kind="step", base=0.0):
    try:
        total = max(0.0, float(base or 0.0) + gfam_adaptive_extra(kind))
    except Exception:
        total = float(base or 0.0)
    if total > 0:
        time.sleep(total)


def gfam_adaptive_note_timing_error(resp, step_name=""):
    if not CONFIG.get("ADAPTIVE_TIMING_ENABLED", True) or not gfam_is_timing_sync_error(resp):
        return
    max_level = max(0, int(CONFIG.get("ADAPTIVE_TIMING_MAX_LEVEL", 5) or 5))
    trigger = max(1, int(CONFIG.get("ADAPTIVE_TIMING_TRIGGER_ERRORS", 2) or 2))
    ADAPTIVE_TIMING_STATE["timing_errors"] = int(ADAPTIVE_TIMING_STATE.get("timing_errors", 0) or 0) + 1
    ADAPTIVE_TIMING_STATE["stable_success"] = 0
    count = int(ADAPTIVE_TIMING_STATE.get("timing_errors", 0) or 0)
    old = gfam_adaptive_level()
    if count % trigger == 0 and old < max_level:
        ADAPTIVE_TIMING_STATE["level"] = old + 1
        print("[自适应间隔] 检测到状态同步类错误 %d 次，间隔等级提升为 %d/%d。" % (count, old + 1, max_level))


def gfam_adaptive_note_success():
    if not CONFIG.get("ADAPTIVE_TIMING_ENABLED", True) or gfam_adaptive_level() <= 0:
        return
    ADAPTIVE_TIMING_STATE["stable_success"] = int(ADAPTIVE_TIMING_STATE.get("stable_success", 0) or 0) + 1
    decay = max(1, int(CONFIG.get("ADAPTIVE_TIMING_DECAY_SUCCESSES", 80) or 80))
    if ADAPTIVE_TIMING_STATE["stable_success"] >= decay:
        ADAPTIVE_TIMING_STATE["level"] = max(0, gfam_adaptive_level() - 1)
        ADAPTIVE_TIMING_STATE["stable_success"] = 0
        ADAPTIVE_TIMING_STATE["timing_errors"] = 0
        print("[自适应间隔] 已连续稳定 %d 个关键接口，间隔等级降低为 %d/%d。" % (decay, gfam_adaptive_level(), int(CONFIG.get("ADAPTIVE_TIMING_MAX_LEVEL", 5) or 5)))

def check_step_error_allow_list(resp, step_name: str) -> bool:
    """
    部分接口，例如 mission combinationInfo，正常返回可能是 list。
    原 check_step_error 只接受 dict，会把正常 list 误判为失败。
    """
    if isinstance(resp, list):
        gfam_adaptive_note_success()
        return False
    return check_step_error(resp, step_name)


def check_step_error(resp: dict, step_name: str) -> bool:
    if not isinstance(resp, dict):
        gfam_adaptive_note_timing_error(resp, step_name)
        print("[-] %s 返回格式异常：%s" % (step_name, type(resp).__name__))
        return True
    if "error_local" in resp:
        gfam_adaptive_note_timing_error(resp, step_name)
        print("[-] %s 本地错误：%s" % (step_name, resp["error_local"]))
        if "raw" in resp:
            print("    原始响应：'%s'" % resp.get("raw"))
        return True
    if "error" in resp:
        gfam_adaptive_note_timing_error(resp, step_name)
        print("[-] %s 服务器错误：%s" % (step_name, resp["error"]))
        return True
    gfam_adaptive_note_success()
    return False


def extract_coin_rewards(obj):
    """
    递归提取 coin1 / coin2 / coin3。
    coin1 = 低级资料，coin2 = 中级资料，coin3 = 高级资料。
    """
    found = {}

    def to_int(v):
        try:
            return int(v)
        except Exception:
            return None

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                key = str(k)
                if key in ("coin1", "coin2", "coin3"):
                    amount = to_int(v)
                    if amount is not None:
                        found[key] = found.get(key, 0) + amount
                else:
                    walk(v)
        elif isinstance(x, list):
            for item in x:
                walk(item)

    walk(obj)
    return found


def print_coin_stats():
    print("\n=========== 技能资料统计 ===========")
    print("低级资料 coin1：%d" % SKILL_DATA_STATS.get("coin1", 0))
    print("中级资料 coin2：%d" % SKILL_DATA_STATS.get("coin2", 0))
    print("高级资料 coin3：%d" % SKILL_DATA_STATS.get("coin3", 0))
    print("最近一次：%s" % (SKILL_DATA_STATS.get("last_rewards") or "无"))
    print("中级训练资料到上限检测：%s" % SKILL_DATA_STATS.get("middle_zero_detected", False))
    print("检测到 coin2+0 暂停：%s" % CONFIG.get("PAUSE_ON_MIDDLE_COIN_ZERO", True))
    print("暂停后自动训练：%s" % CONFIG.get("AUTO_TRAIN_ON_MIDDLE_COIN_ZERO", True))
    print("====================================\n")


def handle_coin_command(parts):
    if len(parts) == 1 or parts[1].lower() in ("show", "status"):
        print_coin_stats()
        return True

    sub = parts[1].lower()
    if sub == "reset":
        SKILL_DATA_STATS["coin1"] = 0
        SKILL_DATA_STATS["coin2"] = 0
        SKILL_DATA_STATS["coin3"] = 0
        SKILL_DATA_STATS["middle_zero_detected"] = False
        SKILL_DATA_STATS["last_rewards"] = {}
        print("[+] 已重置技能资料统计。")
        return True

    if sub == "pause":
        CONFIG["PAUSE_ON_MIDDLE_COIN_ZERO"] = not CONFIG.get("PAUSE_ON_MIDDLE_COIN_ZERO", True)
        print("[+] coin2=0 暂停检测：%s" % CONFIG["PAUSE_ON_MIDDLE_COIN_ZERO"])
        return True

    if sub == "train":
        CONFIG["AUTO_TRAIN_ON_MIDDLE_COIN_ZERO"] = not CONFIG.get("AUTO_TRAIN_ON_MIDDLE_COIN_ZERO", True)
        print("[+] 暂停后自动训练：%s" % CONFIG["AUTO_TRAIN_ON_MIDDLE_COIN_ZERO"])
        return True

    print("[!] 未知 -coin 子命令。可用：-coin / -coin reset / -coin pause / -coin train")
    return True


def format_seconds(seconds):
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return "%02d:%02d:%02d" % (h, m, s)
    return "%02d:%02d" % (m, s)


def get_pick_coin_inventory_from_payload(payload: dict):
    user_info = payload.get("user_info", {}) if isinstance(payload, dict) else {}
    return {
        "coin1": int_safe(user_info.get("coin1", 0), 0),
        "coin2": int_safe(user_info.get("coin2", 0), 0),
        "coin3": int_safe(user_info.get("coin3", 0), 0),
    }


def refresh_pick_coin_inventory_from_index(client: GFLClient=None, payload: dict=None):
    if payload is None:
        if client is None:
            return False
        payload = request_index_snapshot_for_skill(client)
    if not payload:
        return False

    inv = get_pick_coin_inventory_from_payload(payload)
    SKILL_DATA_STATS["current_inventory"] = dict(inv)
    if not SKILL_DATA_STATS.get("start_inventory"):
        SKILL_DATA_STATS["start_inventory"] = dict(inv)
    return True


def start_pick_session(client: GFLClient=None, *, index_payload=None):
    PICK_SESSION_STATS["running"] = True
    PICK_SESSION_STATS["start_time"] = time.time()
    PICK_SESSION_STATS["macro"] = 0
    PICK_SESSION_STATS["micro"] = 0
    PICK_SESSION_STATS["run_count"] = 0
    PICK_SESSION_STATS["zero_stop_coin"] = ""
    PICK_SESSION_STATS["last_panel_time"] = 0
    PICK_SESSION_STATS["fairy_auto_start_snapshot"] = read_fairy_snapshot()
    PICK_LOG_BUFFER.clear()

    SKILL_DATA_STATS["coin1"] = 0
    SKILL_DATA_STATS["coin2"] = 0
    SKILL_DATA_STATS["coin3"] = 0
    SKILL_DATA_STATS["middle_zero_detected"] = False
    SKILL_DATA_STATS["last_rewards"] = {}
    SKILL_DATA_STATS["start_inventory"] = {}
    SKILL_DATA_STATS["current_inventory"] = {}

    if client is not None:
        refresh_pick_coin_inventory_from_index(client, payload=index_payload)


def update_pick_inventory_by_rewards(rewards: dict):
    inv = SKILL_DATA_STATS.get("current_inventory") or {}
    if not inv:
        return
    for key in ("coin1", "coin2", "coin3"):
        inv[key] = int_safe(inv.get(key), 0) + int_safe(rewards.get(key), 0)
    SKILL_DATA_STATS["current_inventory"] = inv


def update_pick_inventory_by_training_cost(cost: dict):
    """自动训练消耗资料后，同步扣减获取资料面板的本地库存缓存。

    获取资料 -> 自动训练 -> 继续获取资料的循环中，Index/index 不会每次都重新请求；
    如果这里只更新 TRAIN_INDEX_CACHE，而不更新 SKILL_DATA_STATS.current_inventory，
    面板会继续显示训练前的资料数量，出现“资料明明被训练消耗了但仍显示 9999+”的假象。
    """
    inv = SKILL_DATA_STATS.get("current_inventory") or {}
    if not inv:
        return
    changed = False
    for key in ("coin1", "coin2", "coin3"):
        used = int_safe(cost.get(key), 0) if isinstance(cost, dict) else 0
        if used > 0:
            inv[key] = max(0, int_safe(inv.get(key), 0) - used)
            changed = True
    if changed:
        SKILL_DATA_STATS["current_inventory"] = inv


def sync_pick_inventory_from_train_cache():
    """用自动训练缓存中的最新 user_info 同步获取资料面板库存。"""
    if not TRAIN_INDEX_CACHE or not isinstance(TRAIN_INDEX_CACHE, dict):
        return False
    payload_inv = get_pick_coin_inventory_from_payload(TRAIN_INDEX_CACHE)
    if not payload_inv:
        return False
    SKILL_DATA_STATS["current_inventory"] = dict(payload_inv)
    return True


def get_pick_progress_text():
    cap = int_safe(CONFIG.get("PICK_COIN_CAP", 9999), 9999)
    inv = SKILL_DATA_STATS.get("current_inventory") or {}
    start_inv = SKILL_DATA_STATS.get("start_inventory") or {}
    gained = {
        "coin1": SKILL_DATA_STATS.get("coin1", 0),
        "coin2": SKILL_DATA_STATS.get("coin2", 0),
        "coin3": SKILL_DATA_STATS.get("coin3", 0),
    }

    def one_line(key, label):
        cur = int_safe(inv.get(key), 0)
        start = int_safe(start_inv.get(key), 0)
        gain = int_safe(gained.get(key), 0)
        capped = cur >= cap
        remain = max(0, cap - cur)

        if key == "coin2":
            if capped:
                state = "已到本模式获取上限；下一次中级资料+0时会停止"
            else:
                state = "距离本模式获取上限还差 %d" % remain
        else:
            if capped:
                state = "已到本模式获取上限；不会因此停止"
            else:
                state = "距离本模式获取上限还差 %d" % remain

        return "%s：当前 %d / %d+ | 本轮获得 +%d | 开始时 %d | %s" % (
            label, cur, cap, gain, start, state
        )

    return [
        one_line("coin1", "初级训练资料"),
        one_line("coin2", "中级训练资料"),
        one_line("coin3", "高级训练资料"),
    ]


def clear_console_for_panel():
    # Windows Terminal / PowerShell 通常支持 ANSI 清屏。
    print("\033[2J\033[H", end="")


def pick_log(message):
    line = str(message)
    PICK_LOG_BUFFER.append(line)
    max_lines = max(5, int_safe(CONFIG.get("PICK_PANEL_LOG_LINES", 10), 10))
    if len(PICK_LOG_BUFFER) > max_lines:
        del PICK_LOG_BUFFER[:-max_lines]
    if not CONFIG.get("PICK_FIXED_PANEL_MODE", True):
        print(line)


def build_pick_panel_lines():
    now = time.time()
    elapsed = format_seconds(now - PICK_SESSION_STATS.get("start_time", now))
    lines = []
    lines.append("================= 获取训练资料状态 =================")
    lines.append("状态：%s | 已运行：%s | 第 %s 轮 | 本轮第 %s 次 | 累计执行 %s 次" % (
        "进行中" if PICK_SESSION_STATS.get("running") else "停止",
        elapsed,
        PICK_SESSION_STATS.get("macro", 0),
        PICK_SESSION_STATS.get("micro", 0),
        PICK_SESSION_STATS.get("run_count", 0),
    ))
    lines.extend(get_pick_progress_text())
    last = SKILL_DATA_STATS.get("last_rewards") or {}
    lines.append("最近一次获得：初级 +%d | 中级 +%d | 高级 +%d" % (
        int_safe(last.get("coin1"), 0),
        int_safe(last.get("coin2"), 0),
        int_safe(last.get("coin3"), 0),
    ))
    if PICK_SESSION_STATS.get("zero_stop_coin"):
        lines.append("停止原因：%s 已达到本模式获取上限，本次获得 +0" % PICK_SESSION_STATS.get("zero_stop_coin"))
    fairy_auto_line = fairy_runtime_status_line()
    if fairy_auto_line:
        lines.append(fairy_auto_line)
    lines.append("说明：9999 只是本模式继续获取训练资料的判断线；通过任务、礼包等其他方式超过 9999 是正常的。")
    lines.append("说明：只有“中级训练资料本次获得为 0”才会停止；初级/高级为 0 会继续运行。")
    lines.append("=================================================")
    return lines


def render_pick_fixed_panel(force=False):
    if not CONFIG.get("PICK_PANEL_ENABLED", True):
        return
    now = time.time()
    if not force and not CONFIG.get("PICK_PANEL_EVERY_MICRO", True):
        if now - PICK_SESSION_STATS.get("last_panel_time", 0) < 5:
            return
    PICK_SESSION_STATS["last_panel_time"] = now

    if CONFIG.get("PICK_FIXED_PANEL_MODE", True):
        clear_console_for_panel()
        print("============== 最近运行记录 ==============")
        if PICK_LOG_BUFFER:
            for line in PICK_LOG_BUFFER[-max(5, int_safe(CONFIG.get("PICK_PANEL_LOG_LINES", 10), 10)):]:
                print(line)
        else:
            print("暂无记录")
        print("")
        for line in build_pick_panel_lines():
            print(line)
        print("")
        print("提示：-q 本轮结束后停止 / -Q 本次行动结束后停止 / -E 退出程序")
    else:
        print("")
        for line in build_pick_panel_lines():
            print(line)
        print("")


def print_pick_panel(force=False):
    render_pick_fixed_panel(force=force)





def detect_zero_reward_stop(rewards: dict):
    """
    只用 coin2（中级资料）+0 作为获取资料停止条件。

    机制说明：
    - coin1 / coin3 达到 9999 后，本次获得也可能变为 0；
    - 但技能训练中 coin2 消耗量最大，当前最需要补的是 coin2；
    - 因此 coin1+0 / coin3+0 只在面板中提示，不触发停止；
    - 只有 coin2 出现在掉落包中且本次获得量为 0 时，才停止获取资料并转入自动训练。
    """
    if "coin2" in rewards and int_safe(rewards.get("coin2"), 0) <= 0:
        return "coin2", "中级资料"
    return "", ""





def update_coin_stats(rewards: dict):
    global stop_macro_flag, stop_micro_flag

    if not rewards:
        return False

    SKILL_DATA_STATS["last_rewards"] = dict(rewards)
    for key in ("coin1", "coin2", "coin3"):
        if key in rewards and rewards[key] > 0:
            SKILL_DATA_STATS[key] = int(SKILL_DATA_STATS.get(key, 0)) + int(rewards[key])

    update_pick_inventory_by_rewards(rewards)

    pick_log("[资料] 本次获得：初级 +%d | 中级 +%d | 高级 +%d；本轮累计：初级 %d | 中级 %d | 高级 %d" % (
        int_safe(rewards.get("coin1"), 0),
        int_safe(rewards.get("coin2"), 0),
        int_safe(rewards.get("coin3"), 0),
        SKILL_DATA_STATS.get("coin1", 0),
        SKILL_DATA_STATS.get("coin2", 0),
        SKILL_DATA_STATS.get("coin3", 0),
    ))

    zero_key, zero_label = detect_zero_reward_stop(rewards)
    if CONFIG.get("PAUSE_ON_MIDDLE_COIN_ZERO", True) and zero_key:
        SKILL_DATA_STATS["middle_zero_detected"] = True
        PICK_SESSION_STATS["zero_stop_coin"] = zero_label
        stop_macro_flag = True
        stop_micro_flag = True
        pick_log("[资料] 检测到中级训练资料本次获得为 0，说明本模式的中级资料已到获取上限，准备停止获取并进入自动训练。")
        print_pick_panel(force=True)
        return True

    print_pick_panel(force=False)
    return False


def parse_random_node_drop(resp_data: dict):
    keys = list(resp_data.keys())
    try:
        target_idx = keys.index("building_defender_change") - 1
        if target_idx >= 0:
            reward_key = keys[target_idx]
            if reward_key not in ["trigger_para", "mission_win_step_control_ids", "spot_act_info"]:
                reward_val = resp_data[reward_key]
                rewards = extract_coin_rewards({reward_key: reward_val})
                if rewards:
                    update_coin_stats(rewards)
                return rewards
    except ValueError:
        pass

    # 兜底：如果字段顺序变化，也递归扫一遍完整响应。
    rewards = extract_coin_rewards(resp_data)
    if rewards:
        update_coin_stats(rewards)
    return rewards



def get_guns_in_team_from_index(payload: dict, team_id: int):
    guns = payload.get("gun_with_user_info", []) if isinstance(payload, dict) else []
    if not isinstance(guns, list):
        return []
    result = []
    for gun in guns:
        if int_safe(gun.get("team_id"), 0) == int(team_id):
            result.append(gun)
    return result


def write_pick_team_config_from_index(payload: dict, team_id: int, guns: list):
    """
    Index/index 校验通过后，将梯队 1 的运行信息写入 CONFIG。
    这样后续运行不需要手动修改 TEAM_ID / GUNS / FAIRY_ID。
    """
    CONFIG["TEAM_ID"] = int(team_id)
    CONFIG["PICK_FIXED_TEAM_ID"] = int(team_id)

    gun_cfgs = []
    for gun in guns:
        gun_cfgs.append({
            "id": int_safe(gun.get("id"), 0),
            "gun_id": int_safe(gun.get("gun_id"), 0),
            "life": int_safe(gun.get("life"), 0),
            "level": int_safe(gun.get("gun_level", gun.get("level", 1)), 1),
        })
    CONFIG["GUNS"] = gun_cfgs

    # 获取资料不再抓取/显示妖精 UID。
    # 妖精可带可不带，不参与运行配置与校验。
    CONFIG["FAIRY"] = None
    CONFIG["FAIRY_ID"] = 0

    CONFIG["PICK_TEAM_VALIDATED"] = True


def confirm_pick_start():
    print("\n=========== 获取资料运行确认 ===========")
    print("固定梯队：%s" % CONFIG.get("PICK_FIXED_TEAM_ID", 1))
    print("人形配置：%s" % (CONFIG.get("GUNS") or "未写入"))
    print("妖精：可带可不带，不检测、不显示妖精 UID")
    print("--------------------------------------")
    print("输入 -y 或 y 确认开始获取资料")
    print("输入 -back / b / n 取消并返回菜单")
    print("======================================\n")

    cmd = normalize_menu_input(input("GFL-PICK(确认)> ")).lower()
    if cmd in ("-y", "y", "yes"):
        print("[+] 已确认，开始获取资料。")
        return True

    print("[*] 已取消本次获取资料运行。")
    return False


def validate_pick_team_single_from_index(client: GFLClient, ask_confirm=False):
    """
    获取资料固定使用梯队 1，并要求梯队 1 只有 1 名人形。
    妖精不影响判断：有无妖精都允许。

    校验通过后会立即把 Index/index 中的梯队信息写入 CONFIG。
    """
    if not CONFIG.get("PICK_REQUIRE_SINGLE_DOLL", True):
        CONFIG["TEAM_ID"] = int(CONFIG.get("PICK_FIXED_TEAM_ID", 1))
        CONFIG["PICK_TEAM_VALIDATED"] = True
        return confirm_pick_start() if ask_confirm else True

    team_id = int(CONFIG.get("PICK_FIXED_TEAM_ID", 1))
    CONFIG["TEAM_ID"] = team_id
    CONFIG["PICK_TEAM_VALIDATED"] = False

    payload = request_index_snapshot_for_skill(client)
    if not payload:
        print("[获取资料] 无法请求 Index/index 校验梯队，已取消获取资料运行。")
        return False

    guns = get_guns_in_team_from_index(payload, team_id)
    if len(guns) != 1:
        print("[获取资料] 梯队校验失败：获取资料固定使用梯队 %s，且必须为单人人形梯队。" % team_id)
        print("[获取资料] 当前梯队 %s 人形数量：%s" % (team_id, len(guns)))
        if guns:
            print("[获取资料] 当前梯队成员：")
            for gun in guns:
                print("  UID=%s | gun_id=%s | Lv.%s | life=%s" % (
                    gun.get("id"),
                    gun.get("gun_id"),
                    gun.get("gun_level", gun.get("level", "-")),
                    gun.get("life", "-"),
                ))
        print("[获取资料] 请在游戏中将梯队 1 调整为单人人形后，再重新运行 -r。")
        return False

    write_pick_team_config_from_index(payload, team_id, guns)

    gun = guns[0]
    print("[获取资料] 梯队校验通过：梯队 1 单人人形。")
    print("[获取资料] 已写入 CONFIG：TEAM_ID=%s | GUNS=%s" % (
        CONFIG.get("TEAM_ID"),
        CONFIG.get("GUNS"),
    ))
    print("[获取资料] 使用人形：UID=%s | gun_id=%s | Lv.%s" % (
        gun.get("id"),
        gun.get("gun_id"),
        gun.get("gun_level", gun.get("level", "-")),
    ))
    print("[获取资料] 妖精可带可不带，不参与本次校验。")

    if ask_confirm:
        return confirm_pick_start()
    return True


def farm_mission_10352(client: GFLClient, team_id: int):
    mission_id = CONFIG["MISSION_ID"]
    team_id = int(CONFIG.get("PICK_FIXED_TEAM_ID", 1))
    CONFIG["TEAM_ID"] = team_id

    combinfo_resp = client.send_request(API_MISSION_COMBINFO, {"mission_id": mission_id})
    if check_step_error_allow_list(combinfo_resp, "combinationInfo"):
        return None

    start_payload = {
        "mission_id": mission_id,
        "spots": [{"spot_id": CONFIG["START_SPOT"], "team_id": team_id}],
        "squad_spots": [],
        "sangvis_spots": [],
        "vehicle_spots": [],
        "ally_spots": [],
        "mission_ally_spots": [],
        "ally_id": int(time.time())
    }
    if check_step_error(client.send_request(API_MISSION_START, start_payload), "startMission"):
        return None

    guide_payload = {
        "guide": json.dumps({"course": GUIDE_COURSE_10352}, separators=(",", ":"))
    }
    if check_step_error(client.send_request(API_INDEX_GUIDE, guide_payload), "guide"):
        return None
    gfam_adaptive_sleep("step", 0.1)

    curr_spot = CONFIG["START_SPOT"]
    route = CONFIG["ROUTE"]
    for idx, next_spot in enumerate(route, start=1):
        move_payload = {
            "person_type": 1,
            "person_id": team_id,
            "from_spot_id": curr_spot,
            "to_spot_id": next_spot,
            "move_type": 1
        }
        move_resp = client.send_request(API_MISSION_TEAM_MOVE, move_payload)
        if check_step_error(move_resp, "teamMove%d" % idx):
            return None
        if idx == len(route):
            parse_random_node_drop(move_resp)
        curr_spot = next_spot
        gfam_adaptive_sleep("step", 0.1)

    client.send_request(API_MISSION_ABORT, {"mission_id": mission_id})
    gfam_adaptive_sleep("step", 0.1)

    return []



def gfam_is_gun_locked_for_emergency(gun):
    if not isinstance(gun, dict):
        return True
    for key in ("if_locked", "is_locked", "locked", "lock", "is_lock"):
        if key in gun:
            val = str(gun.get(key)).strip().lower()
            if val in ("1", "true", "yes", "y"):
                return True
    return False

def gfam_gun_team_id_for_emergency(gun):
    if not isinstance(gun, dict):
        return 0
    for key in ("team_id", "team", "location"):
        if key in gun:
            return int_safe(gun.get(key), 0)
    return 0

def gfam_gun_uid_for_emergency(gun):
    if not isinstance(gun, dict):
        return 0
    for key in ("gun_with_user_id", "id", "uid"):
        if key in gun:
            return int_safe(gun.get(key), 0)
    return 0

def gfam_collect_emergency_retire_uids_from_index(payload):
    guns = payload.get("gun_with_user_info", []) if isinstance(payload, dict) else []
    if isinstance(guns, dict):
        guns = list(guns.values())
    if not isinstance(guns, list):
        return []
    uids = []
    fixed_team = int_safe(CONFIG.get("PICK_FIXED_TEAM_ID", CONFIG.get("TEAM_ID", 1)), 1)
    running_uids = set()
    for gun in get_guns_in_team_from_index(payload, fixed_team):
        uid = gfam_gun_uid_for_emergency(gun)
        if uid > 0:
            running_uids.add(uid)
    for gun in guns:
        if not isinstance(gun, dict):
            continue
        if gfam_is_gun_locked_for_emergency(gun):
            continue
        if gfam_gun_team_id_for_emergency(gun) != 0:
            continue
        uid = gfam_gun_uid_for_emergency(gun)
        if uid > 0 and uid not in running_uids:
            uids.append(uid)
    return uids

def gfam_try_exception_self_repair(client, reason="获取资料 Micro Error Before Retry"):
    if not CONFIG.get("ENABLE_GUN_EXCEPTION_SELF_REPAIR", True):
        pick_log("[自修复] 人形异常自修复已关闭，跳过应急拆解。")
        return False
    payload = request_index_snapshot_for_skill(client, bypass_cache=True)
    if payload is None:
        pick_log("[自修复] 无法获取 Index/index，跳过人形应急拆解。")
        return False
    uids = gfam_collect_emergency_retire_uids_from_index(payload)
    if not uids:
        pick_log("[自修复] 当前没有可用于应急拆解的未上锁、未编队人形。")
        return False
    pick_log("[自修复] %s，正在尝试应急拆解 %d 名未上锁、未编队人形。" % (reason, len(uids)))
    resp = client.send_request(API_GUN_RETIRE, uids)
    if isinstance(resp, dict) and resp.get("success"):
        pick_log("[自修复] 应急拆解成功，准备重试当前 Micro。")
        time.sleep(0.8)
        return True
    pick_log("[自修复] 应急拆解失败：%s" % resp)
    return False



# v47：获取资料运行结束收尾拆解兜底。
# 只处理本次运行已经记录到的掉落 UID，不主动请求 Index/index 或扫描全仓库。
GFAM_FINAL_CLEANUP_PENDING_GUNS = []


def gfam_final_cleanup_note_guns(uids):
    try:
        for uid in uids or []:
            try:
                uid = int(uid)
            except Exception:
                continue
            if uid > 0 and uid not in GFAM_FINAL_CLEANUP_PENDING_GUNS:
                GFAM_FINAL_CLEANUP_PENDING_GUNS.append(uid)
    except Exception:
        pass


def gfam_final_cleanup_mark_retired(uids):
    try:
        for uid in uids or []:
            try:
                uid = int(uid)
            except Exception:
                continue
            while uid in GFAM_FINAL_CLEANUP_PENDING_GUNS:
                GFAM_FINAL_CLEANUP_PENDING_GUNS.remove(uid)
    except Exception:
        pass


def gfam_run_final_cleanup(client, label="运行结束"):
    guns = list(dict.fromkeys(GFAM_FINAL_CLEANUP_PENDING_GUNS))
    if not guns:
        return
    pick_log("[收尾拆解] %s：检测到本次获取资料仍有未处理人形掉落 %d 只，将最后拆解一次。" % (label, len(guns)))
    retire_guns(client, guns)
    if GFAM_FINAL_CLEANUP_PENDING_GUNS:
        pick_log("[收尾拆解] 仍有 %d 只人形未确认拆解，请手动检查仓库。" % len(GFAM_FINAL_CLEANUP_PENDING_GUNS))

def retire_guns(client: GFLClient, gun_uids: list):
    if not gun_uids:
        return
    msg = "[*] 正在提交 %d 名人形进行自动拆解……" % len(gun_uids)
    if PICK_SESSION_STATS.get("running"):
        pick_log(msg)
    else:
        print(msg)
    resp = client.send_request(API_GUN_RETIRE, gun_uids)
    if isinstance(resp, dict) and resp.get("success"):
        gfam_final_cleanup_mark_retired(gun_uids)
        msg = "[+] 自动拆解成功！"
    else:
        msg = "[-] 拆解失败：%s" % resp
    if PICK_SESSION_STATS.get("running"):
        pick_log(msg)
        print_pick_panel(force=True)
    else:
        print(msg)


def stop_proxy_only():
    global proxy_instance, worker_mode
    if proxy_instance:
        print("[*] 正在停止代理并恢复 Windows 代理……")
        try:
            proxy_instance.stop()
        except Exception:
            pass
        try:
            set_windows_proxy(False)
        except Exception:
            pass
        proxy_instance = None
        if worker_mode == "c":
            worker_mode = None
        print("[+] 代理已停止。")
    else:
        print("[*] 当前没有运行中的代理，无需恢复 Windows 代理。")


def start_capture_proxy():
    global proxy_instance, worker_mode, CURRENT_MENU

    if launched_from_gfam_main():
        print("[!] pick_and_train 由 GFAM 主菜单统一提供 UID/SIGN，本模块不再启动代理。")
        print("[*] 如需重新获取 UID/SIGN，请返回 GFAM 主菜单使用 auth。")
        return

    if proxy_instance:
        print("[!] 代理已经在运行中。")
        return

    print_server_menu()
    server_cmd = normalize_menu_input(input("GFL-COIN(服务器, 默认%s)> " % get_default_server_from_env()))
    if not apply_server_selection(server_cmd):
        print("[!] 服务器选择无效，已取消启动代理。")
        return

    CAPTURE_SUCCESS_EVENT.clear()

    proxy_instance = GFLProxy(CONFIG["PROXY_PORT"], STATIC_KEY, on_traffic)
    proxy_instance.start()
    set_windows_proxy(True, "127.0.0.1:%d" % CONFIG["PROXY_PORT"])
    worker_mode = "c"

    print("[*] 代理已启动，端口 %d。Windows 代理已设置。" % CONFIG["PROXY_PORT"])
    print("[*] 当前服务器：%s" % CONFIG.get("SERVER_NAME", "SOP"))
    print("[AUTO] 正在等待 UID / SIGN 自动抓取。")
    print("[AUTO] 抓取期间禁止其他操作，请在游戏内完成登录。")
    print("[AUTO] 抓取成功后，程序会自动停止代理并弹出后续操作菜单。")

    try:
        while not CAPTURE_SUCCESS_EVENT.is_set():
            gfam_adaptive_sleep("step", 0.2)
    except KeyboardInterrupt:
        print("\n[!] 抓取过程被中断，正在停止代理。")
        stop_proxy_only()
        return

    print("[AUTO] 正在停止代理并恢复 Windows 代理……")
    stop_proxy_only()

    CURRENT_MENU = "main"
    print_main_menu()





# 人形 1~100 与 100~120 经验表。
# 用于判断二技能开放条件：心智二扩后等级上限达到 115，
# 可通过当前经验总量是否达到 1->115 的累计经验下限来判断。
GUN_EXP_1_TO_100 = {
    1:100, 2:200, 3:300, 4:400, 5:500, 6:600, 7:700, 8:800, 9:900, 10:1000,
    11:1100, 12:1200, 13:1300, 14:1400, 15:1500, 16:1600, 17:1700, 18:1800, 19:1900, 20:2000,
    21:2100, 22:2200, 23:2300, 24:2400, 25:2500, 26:2600, 27:2800, 28:3100, 29:3400, 30:4200,
    31:4600, 32:5000, 33:5400, 34:5800, 35:6300, 36:6700, 37:7200, 38:7700, 39:8200, 40:8800,
    41:9300, 42:9900, 43:10500, 44:11100, 45:11800, 46:12500, 47:13100, 48:13900, 49:14600, 50:15400,
    51:16100, 52:16900, 53:17800, 54:18600, 55:19500, 56:20400, 57:21300, 58:22300, 59:23300, 60:24300,
    61:25300, 62:26300, 63:27400, 64:28500, 65:29600, 66:30800, 67:32000, 68:33200, 69:34400, 70:45100,
    71:46800, 72:48600, 73:50400, 74:52200, 75:54000, 76:55900, 77:57900, 78:59800, 79:61800, 80:63900,
    81:66000, 82:68100, 83:70300, 84:72600, 85:74800, 86:77100, 87:79500, 88:81900, 89:84300, 90:112600,
    91:116100, 92:119500, 93:123100, 94:126700, 95:130400, 96:134100, 97:137900, 98:141800, 99:145700,
}

GUN_EXP_100_TO_120 = {
    100:100000, 101:120000, 102:140000, 103:160000, 104:180000,
    105:200000, 106:220000, 107:240000, 108:280000, 109:360000,
    110:480000, 111:640000, 112:900000, 113:1200000, 114:1600000,
    115:2200000, 116:3000000, 117:4000000, 118:5000000, 119:6000000,
}


def sum_exp_range(exp_table, start_level, end_level):
    """
    累计从 start_level 升到 end_level 所需经验。
    例如 sum_exp_range(table, 1, 100) = 1->100 总经验。
    """
    total = 0
    for lv in range(int(start_level), int(end_level)):
        total += int(exp_table.get(lv, 0) or 0)
    return total


GUN_TOTAL_EXP_TO_100 = sum_exp_range(GUN_EXP_1_TO_100, 1, 100)
GUN_TOTAL_EXP_TO_110 = GUN_TOTAL_EXP_TO_100 + sum_exp_range(GUN_EXP_100_TO_120, 100, 110)
GUN_TOTAL_EXP_TO_115 = GUN_TOTAL_EXP_TO_100 + sum_exp_range(GUN_EXP_100_TO_120, 100, 115)
GUN_TOTAL_EXP_TO_120 = GUN_TOTAL_EXP_TO_100 + sum_exp_range(GUN_EXP_100_TO_120, 100, 120)


def gun_next_level_required_exp(level):
    level = int_safe(level, 1)
    if 1 <= level < 100:
        return int(GUN_EXP_1_TO_100.get(level, 0) or 0)
    if 100 <= level < 120:
        return int(GUN_EXP_100_TO_120.get(level, 0) or 0)
    return 0


def gun_total_exp_for_level(level, intra_exp=0):
    """
    根据“等级 + 当前等级内经验”计算累计总经验。
    """
    level = max(1, min(int_safe(level, 1), 120))
    intra_exp = max(0, int_safe(intra_exp, 0))
    total = 0
    if level <= 100:
        total = sum_exp_range(GUN_EXP_1_TO_100, 1, level)
    else:
        total = GUN_TOTAL_EXP_TO_100 + sum_exp_range(GUN_EXP_100_TO_120, 100, level)
    return total + intra_exp


def gun_total_exp_from_index_gun(gun: dict):
    """
    兼容 Index/index 中 gun_exp 可能是“累计总经验”或“当前等级内经验”的两种情况。
    用等级边界判断：
    - 若 raw_exp 落在当前等级累计区间内，按累计总经验处理；
    - 若 raw_exp <= 当前等级升下一级所需经验，按等级内经验处理；
    - 否则保守使用等级下限。
    """
    level = max(1, min(int_safe(gun.get("gun_level", gun.get("level", 1)), 1), 120))
    raw_exp = max(0, int_safe(gun.get("gun_exp", gun.get("exp", 0)), 0))

    if level <= 100:
        floor = sum_exp_range(GUN_EXP_1_TO_100, 1, level)
    else:
        floor = GUN_TOTAL_EXP_TO_100 + sum_exp_range(GUN_EXP_100_TO_120, 100, level)

    next_need = gun_next_level_required_exp(level)
    next_floor = floor + next_need if next_need > 0 else floor

    if floor <= raw_exp < next_floor:
        return raw_exp
    if 0 <= raw_exp <= next_need:
        return floor + raw_exp
    return floor


def gun_has_second_skill_by_exp(gun: dict):
    """
    二技能开放判断：
    不能只看 skill2 字段，因为实测所有人形都可能带有 skill2 字段。
    用户确认应按“是否二改 / 等级上限是否已到 115”判断，也就是 Index 中
    if_modification >= 2 时才视为二技能实际开放。

    兼容兜底：如果极少数 Index 缺少 if_modification，则退回到累计经验已经达到
    115 级下限的判断，避免旧缓存完全无法识别。
    """
    mod_stage = int_safe(gun.get("if_modification", gun.get("mod", gun.get("mod_level", 0))), 0)
    if mod_stage >= 2:
        return True
    # 兜底仅用于缺字段的旧缓存；如果明确是 0/1 改，不应因为 skill2 字段存在而开放二技能。
    if "if_modification" not in gun and "mod" not in gun and "mod_level" not in gun:
        return gun_total_exp_from_index_gun(gun) >= GUN_TOTAL_EXP_TO_115
    return False



SKILL_TRAIN_COST_TABLE = {
    1: {"to": 2, "coin": "coin1", "amount": 100, "hours": 1},
    2: {"to": 3, "coin": "coin1", "amount": 200, "hours": 2},
    3: {"to": 4, "coin": "coin1", "amount": 300, "hours": 3},
    4: {"to": 5, "coin": "coin2", "amount": 120, "hours": 4},
    5: {"to": 6, "coin": "coin2", "amount": 200, "hours": 6},
    6: {"to": 7, "coin": "coin2", "amount": 300, "hours": 9},
    7: {"to": 8, "coin": "coin2", "amount": 400, "hours": 12},
    8: {"to": 9, "coin": "coin3", "amount": 200, "hours": 18},
    9: {"to": 10, "coin": "coin3", "amount": 300, "hours": 24},
}


def int_safe(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def get_skill_cost_between(current_level, target_level):
    current_level = int_safe(current_level, 1)
    target_level = int_safe(target_level, 10)
    target_level = max(2, min(10, target_level))

    cost = {"coin1": 0, "coin2": 0, "coin3": 0, "hours": 0}
    if current_level >= target_level:
        return cost

    for lv in range(current_level, target_level):
        row = SKILL_TRAIN_COST_TABLE.get(lv)
        if not row:
            continue
        cost[row["coin"]] += int(row["amount"])
        cost["hours"] += int(row["hours"])
    return cost


def get_quick_training_contract_need(current_level, target_level):
    """
    快速训练契约消耗规则：
    - Lv.1 -> Lv.4 只消耗训练资料，不消耗时间，因此不需要快速训练契约；
    - 从 Lv.4 往上，每升一级需要 1 张快速训练契约。
    例如：
        Lv.1 -> Lv.10 需要 6 张，分别对应 4->5,5->6,6->7,7->8,8->9,9->10。
        Lv.4 -> Lv.10 需要 6 张。
        Lv.8 -> Lv.10 需要 2 张。
    """
    current_level = int_safe(current_level, 1)
    target_level = int_safe(target_level, 10)
    target_level = max(2, min(10, target_level))

    if current_level >= target_level:
        return 0

    need = 0
    for lv in range(current_level, target_level):
        if lv >= 4:
            need += 1
    return need


def has_enough_training_resource(resources, cost):
    if not resources:
        return False
    for key in ("coin1", "coin2", "coin3"):
        if int_safe(resources.get(key), 0) < int_safe(cost.get(key), 0):
            return False

    quick_need = int_safe(cost.get("quick_training", 0), 0)
    if quick_need > 0 and int_safe(resources.get("quick_training"), 0) < quick_need:
        return False

    return True


def extract_training_resources_from_index(payload: dict):
    user_info = payload.get("user_info", {}) if isinstance(payload, dict) else {}
    item_list = payload.get("item_with_user_info", []) if isinstance(payload, dict) else []

    result = {
        "coin1": int_safe(user_info.get("coin1", 0), 0),
        "coin2": int_safe(user_info.get("coin2", 0), 0),
        "coin3": int_safe(user_info.get("coin3", 0), 0),
        "quick_training": 0,
    }

    if isinstance(item_list, list):
        for item in item_list:
            if str(item.get("item_id")) == "8":
                result["quick_training"] = int_safe(item.get("number", 0), 0)
                break

    return result


def get_active_upgrade_slot_count(payload: dict):
    info = payload.get("upgrade_act_info", []) if isinstance(payload, dict) else []
    if isinstance(info, list):
        return len(info)
    if isinstance(info, dict):
        return len(info)
    return 0


def get_max_upgrade_slot(payload: dict):
    user_info = payload.get("user_info", {}) if isinstance(payload, dict) else {}
    return max(1, int_safe(user_info.get("max_upgrade_slot", 1), 1))


def get_first_available_upgrade_slot(payload: dict):
    max_slot = get_max_upgrade_slot(payload)
    active = get_active_upgrade_slot_count(payload)
    if active >= max_slot:
        return None

    # 目前没有确认 upgrade_act_info 中槽位字段名，先按第一个空位兜底。
    # 快速训练通常会立即完成，占用槽位时间极短；如果服务器仍要求 slot，这里默认从 1 开始。
    return min(max_slot, active + 1)


def request_index_snapshot_for_skill(client: GFLClient, *, force: bool = False,
                                      bypass_cache: bool = False):
    global _pick_index_mgr
    if _pick_index_mgr is None and IndexCacheManager is not None:
        _pick_index_mgr = IndexCacheManager(client, ttl=30, label="Pick",
                                             shared_file=None)
    if _pick_index_mgr is not None:
        if bypass_cache:
            resp = _pick_index_mgr.bypass(client, reason="bypass_request")
        elif force:
            resp = _pick_index_mgr.get(force=True, reason="force_request")
        else:
            resp = _pick_index_mgr.get(reason="normal_request")
    else:
        payload = {"time": int(time.time()), "furniture_data": False}
        resp = client.send_request(API_INDEX_INDEX, payload)
        if check_step_error(resp, "Index/index"):
            return None
        if not isinstance(resp, dict):
            print("[SKILL] Index/index 返回格式异常，无法自动判断训练条件。")
            return None
        update_fairy_cache_from_index_payload(resp, source="pick_and_train Index/index")
    try:
        with open("index_skill_debug.json", "w", encoding="utf-8") as f:
            json.dump(resp, f, ensure_ascii=False, indent=4)
    except Exception:
        pass
    return resp


def get_effective_skill_target_level():
    return int_safe(CONFIG.get("AUTO_SKILL_TARGET_LEVEL", 10), 10)


def is_skill_allowed_by_test_mode(skill_lv):
    return True

def collect_int_set_from_nested(obj, key_names):
    result = set()
    key_names = set(key_names)

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if str(k) in key_names:
                    iv = int_safe(v, None)
                    if iv is not None:
                        result.add(iv)
                walk(v)
        elif isinstance(x, list):
            for item in x:
                walk(item)

    walk(obj)
    return result


def build_busy_gun_index(payload: dict):
    """
    根据 Index/index 识别人形不可训练状态。

    判断规则：
    - 后勤中：operation_act_info 中出现的梯队；
    - 作战中：mission_act_info / auto_mission_act_info 中出现的梯队，
      以及 team_in_coin_mission_info 中出现的人形 UID；
    - 探索中：当前探索记录存在时，用 team_id=101 标记实际探索队成员。

    注意：
    explore_info 里的 gun_ids 是图鉴 ID，不是实例 UID。
    因此这里只把它们用于调试显示，不直接用 gun_id 匹配仓库复制体。
    """
    busy_team_reasons = {}
    busy_uid_reasons = {}
    busy_gun_id_reasons = {}

    operation_info = payload.get("operation_act_info", [])
    if isinstance(operation_info, list):
        for op in operation_info:
            if not isinstance(op, dict):
                continue
            team_id = int_safe(op.get("team_id"), 0)
            if team_id > 0:
                busy_team_reasons[team_id] = "后勤中"

    for key in ("mission_act_info", "auto_mission_act_info"):
        info = payload.get(key)
        for team_id in collect_int_set_from_nested(info, ("team_id",)):
            if team_id > 0:
                busy_team_reasons[team_id] = "作战中"

    coin_info = payload.get("team_in_coin_mission_info", {})
    if isinstance(coin_info, dict):
        for item in coin_info.values():
            if not isinstance(item, dict):
                continue
            uid = int_safe(item.get("gun_with_user_id"), 0)
            if uid > 0:
                busy_uid_reasons[uid] = "作战中"

    explore_info = payload.get("explore_info", {})
    current_explore_gun_ids = set()
    if isinstance(explore_info, dict):
        explore_end_time = int_safe(explore_info.get("end_time"), 0)
        explore_list = explore_info.get("list", [])
        if isinstance(explore_list, list):
            current_records = []
            for item in explore_list:
                if not isinstance(item, dict):
                    continue

                item_end = int_safe(item.get("end_time"), 0)
                draw_event_prize = int_safe(item.get("draw_event_prize"), 1)
                cancel_time = int_safe(item.get("cancel_time"), 0)

                if cancel_time == 0 and (
                    (explore_end_time > 0 and item_end == explore_end_time)
                    or draw_event_prize == 0
                ):
                    current_records.append(item)

            if not current_records and explore_list:
                last_item = explore_list[-1]
                if isinstance(last_item, dict):
                    current_records = [last_item]

            for item in current_records:
                for gid in item.get("gun_ids", []) or []:
                    gid = int_safe(gid, 0)
                    if gid > 0:
                        current_explore_gun_ids.add(gid)

    if current_explore_gun_ids:
        busy_team_reasons[101] = "探索中"

    return {
        "team": busy_team_reasons,
        "uid": busy_uid_reasons,
        "gun_id": busy_gun_id_reasons,
        "debug": {
            "operation_team_ids": sorted([
                int_safe(op.get("team_id"), 0)
                for op in operation_info
                if isinstance(op, dict) and int_safe(op.get("team_id"), 0) > 0
            ]) if isinstance(operation_info, list) else [],
            "current_explore_gun_ids": sorted(current_explore_gun_ids),
        },
    }


def get_gun_busy_reason(gun: dict, busy_index: dict):
    uid = int_safe(gun.get("id"), 0)
    gun_id = int_safe(gun.get("gun_id"), 0)
    team_id = int_safe(gun.get("team_id"), 0)

    if uid in busy_index.get("uid", {}):
        return busy_index["uid"][uid]
    if team_id in busy_index.get("team", {}):
        return busy_index["team"][team_id]
    if gun_id in busy_index.get("gun_id", {}):
        return busy_index["gun_id"][gun_id]
    return None



def build_auto_skill_candidates_from_index(payload: dict):
    """按“逐个人形完成”的顺序生成自动训练候选。

    规则：
    1. 先按仓库/等级顺序生成人形队列：等级高优先，等级相同按 UID 稳定排序；
    2. 对队列中的同一个人形，先训练一技能，再训练二技能；
    3. 该人形两个可训练技能都达到目标等级后，才轮到下一个人形。

    这样可以避免旧逻辑把一技能、二技能拆成全局候选后按技能等级跳选，导致仓库里
    一批二技能未训练的人形顺序混乱。
    """
    resources = extract_training_resources_from_index(payload)
    target_level = get_effective_skill_target_level()
    only_locked = bool(CONFIG.get("AUTO_SKILL_ONLY_LOCKED", True))
    team_only = bool(CONFIG.get("AUTO_SKILL_TEAM_ONLY", False))
    busy_index = build_busy_gun_index(payload)

    guns = payload.get("gun_with_user_info", []) if isinstance(payload, dict) else []
    if not isinstance(guns, list):
        return []

    gun_queue = []
    for source_order, gun in enumerate(guns):
        gun_uid = int_safe(gun.get("id"), 0)
        gun_id = int_safe(gun.get("gun_id"), 0)
        team_id = int_safe(gun.get("team_id"), 0)
        locked = str(gun.get("is_locked", "0")) == "1"

        if gun_uid <= 0:
            continue
        if only_locked and not locked:
            continue
        if team_only and team_id <= 0:
            continue

        busy_reason = get_gun_busy_reason(gun, busy_index)
        # 忙碌人形不加入实际自动训练候选，只在 -skill count 中单独统计。
        if CONFIG.get("AUTO_SKILL_EXCLUDE_BUSY", True) and busy_reason:
            continue

        total_exp = gun_total_exp_from_index_gun(gun)
        gun_level = int_safe(gun.get("gun_level", gun.get("level", 1)), 1)
        has_second_skill = gun_has_second_skill_by_exp(gun)
        mod_stage = int_safe(gun.get("if_modification", gun.get("mod", gun.get("mod_level", 0))), 0)

        skill_items = []
        for skill_no in (1, 2):
            field = "skill%d" % skill_no
            skill_lv = int_safe(gun.get(field), 0)

            # 一技能正常读取 skill1。
            # 二技能是否开放通过累计经验是否达到 115 级判断；部分 Index 中 skill2 可能缺失或为 0。
            if skill_no == 2 and not has_second_skill:
                continue

            # 二技能已开放但字段缺失/为 0 时，按 Lv.1 作为训练起点。
            if skill_lv <= 0:
                if skill_no == 2 and has_second_skill:
                    skill_lv = 1
                else:
                    continue

            if skill_lv >= target_level:
                continue

            if not is_skill_allowed_by_test_mode(skill_lv):
                continue

            cost = get_skill_cost_between(skill_lv, target_level)
            cost["quick_training"] = get_quick_training_contract_need(skill_lv, target_level)

            skill_items.append({
                "gun_uid": gun_uid,
                "gun_id": gun_id,
                "team_id": team_id,
                "gun_level": gun_level,
                "skill": skill_no,
                "current_level": skill_lv,
                "target_level": target_level,
                "cost": cost,
                "locked": locked,
                "total_exp": total_exp,
                "has_second_skill": has_second_skill,
                "mod_stage": mod_stage,
                "busy_reason": busy_reason,
                "source_order": source_order,
            })

        if skill_items:
            # 同一人形内部固定：一技能 -> 二技能。
            skill_items.sort(key=lambda x: int_safe(x.get("skill"), 1))
            gun_queue.append({
                "gun_uid": gun_uid,
                "gun_id": gun_id,
                "gun_level": gun_level,
                "total_exp": total_exp,
                "mod_stage": mod_stage,
                "source_order": source_order,
                "skills": skill_items,
            })

    # 仓库/等级队列：等级高优先；等级相同按 UID 稳定排序，再按 Index 原始顺序兜底。
    gun_queue.sort(key=lambda x: (-int_safe(x.get("gun_level"), 0), int_safe(x.get("gun_uid"), 0), int_safe(x.get("source_order"), 0)))

    candidates = []
    for gun_item in gun_queue:
        candidates.extend(gun_item.get("skills", []))
    return candidates

def print_auto_skill_candidates(candidates, limit=10):
    print("\n=========== 自动技能训练队列 ===========")
    print("规则：按人形等级队列逐个完成；同一人形先一技能、再二技能，完成后才进入下一个。")
    if not candidates:
        print("未找到满足条件的候选。")
    else:
        for idx, item in enumerate(candidates[:limit], start=1):
            cost = item.get("cost", {})
            print("%02d. UID=%s | gun_id=%s | 人形Lv.%s | MOD%s | skill=%s | Lv.%s -> Lv.%s | 二技能=%s | 总经验=%s | 消耗 coin1=%s coin2=%s coin3=%s | team=%s" % (
                idx,
                item.get("gun_uid"),
                item.get("gun_id"),
                item.get("gun_level", "-"),
                item.get("mod_stage", 0),
                item.get("skill"),
                item.get("current_level"),
                item.get("target_level"),
                item.get("has_second_skill", False),
                item.get("total_exp", "-"),
                cost.get("coin1", 0),
                cost.get("coin2", 0),
                cost.get("coin3", 0),
                item.get("team_id"),
            ))
    print("========================================\n")


def count_trainable_skills_from_index(payload: dict):
    """
    统计仓库内可训练技能数量：
    - 一技能：skill1 > 0 且 skill1 < 目标等级
    - 二技能：必须 if_modification >= 2（二改 / 等级上限 115）且 skill2 < 目标等级
      注意：即使 Index 中所有人形都有 skill2 字段，未二改也不算实际拥有二技能。
    """
    target_level = get_effective_skill_target_level()
    only_locked = bool(CONFIG.get("AUTO_SKILL_ONLY_LOCKED", True))
    team_only = bool(CONFIG.get("AUTO_SKILL_TEAM_ONLY", False))

    guns = payload.get("gun_with_user_info", []) if isinstance(payload, dict) else []
    if not isinstance(guns, list):
        return {
            "skill1_count": 0,
            "skill2_count": 0,
            "second_skill_unlocked_count": 0,
            "checked_gun_count": 0,
            "examples_skill1": [],
            "examples_skill2": [],
        }

    busy_index = build_busy_gun_index(payload)

    skill1_count = 0
    skill2_count = 0
    busy_skill1_count = 0
    busy_skill2_count = 0
    # 可训练技能里的忙碌人形：按 UID 去重。
    busy_reason_counts = {}
    busy_reason_uid_seen = {}
    # 当前仓库/扫描范围内所有忙碌人形：按 UID 去重，用于和游戏仓库截图对照。
    all_busy_reason_uid_seen = {}
    second_skill_unlocked_count = 0
    checked_gun_count = 0
    examples_skill1 = []
    examples_skill2 = []
    examples_busy = []

    for gun in guns:
        gun_uid = int_safe(gun.get("id"), 0)
        gun_id = int_safe(gun.get("gun_id"), 0)
        team_id = int_safe(gun.get("team_id"), 0)
        locked = str(gun.get("is_locked", "0")) == "1"

        if gun_uid <= 0:
            continue
        if only_locked and not locked:
            continue
        if team_only and team_id <= 0:
            continue

        checked_gun_count += 1
        total_exp = gun_total_exp_from_index_gun(gun)
        has_second_skill = gun_has_second_skill_by_exp(gun)
        mod_stage = int_safe(gun.get("if_modification", gun.get("mod", gun.get("mod_level", 0))), 0)
        busy_reason = get_gun_busy_reason(gun, busy_index)
        if busy_reason:
            all_busy_reason_uid_seen.setdefault(busy_reason, set()).add(gun_uid)

        skill1_lv = int_safe(gun.get("skill1"), 0)
        if 0 < skill1_lv < target_level and is_skill_allowed_by_test_mode(skill1_lv):
            if busy_reason:
                busy_skill1_count += 1
                busy_reason_uid_seen.setdefault(busy_reason, set()).add(gun_uid)
                if len(examples_busy) < 12:
                    examples_busy.append({
                        "uid": gun_uid,
                        "gun_id": gun_id,
                        "skill": 1,
                        "skill_lv": skill1_lv,
                        "team_id": team_id,
                        "reason": busy_reason,
                    })
            else:
                skill1_count += 1
                if len(examples_skill1) < 5:
                    examples_skill1.append({
                        "uid": gun_uid,
                        "gun_id": gun_id,
                        "skill_lv": skill1_lv,
                        "team_id": team_id,
                    })

        if has_second_skill:
            second_skill_unlocked_count += 1
            skill2_lv = int_safe(gun.get("skill2"), 0)
            # 达到 115 级但 skill2 字段为 0 / 缺失时，按 Lv.1 作为可训练起点。
            if skill2_lv <= 0:
                skill2_lv = 1
            if skill2_lv < target_level and is_skill_allowed_by_test_mode(skill2_lv):
                if busy_reason:
                    busy_skill2_count += 1
                    busy_reason_uid_seen.setdefault(busy_reason, set()).add(gun_uid)
                    if len(examples_busy) < 12:
                        examples_busy.append({
                            "uid": gun_uid,
                            "gun_id": gun_id,
                            "skill": 2,
                            "skill_lv": skill2_lv,
                            "team_id": team_id,
                            "reason": busy_reason,
                            "total_exp": total_exp,
                            "mod_stage": mod_stage,
                        })
                else:
                    skill2_count += 1
                    if len(examples_skill2) < 5:
                        examples_skill2.append({
                            "uid": gun_uid,
                            "gun_id": gun_id,
                            "skill_lv": skill2_lv,
                            "team_id": team_id,
                            "total_exp": total_exp,
                            "mod_stage": mod_stage,
                        })

    busy_reason_counts = {
        reason: len(uid_set)
        for reason, uid_set in busy_reason_uid_seen.items()
    }
    all_busy_reason_counts = {
        reason: len(uid_set)
        for reason, uid_set in all_busy_reason_uid_seen.items()
    }

    return {
        "skill1_count": skill1_count,
        "skill2_count": skill2_count,
        "busy_skill1_count": busy_skill1_count,
        "busy_skill2_count": busy_skill2_count,
        "busy_reason_counts": busy_reason_counts,
        "all_busy_reason_counts": all_busy_reason_counts,
        "all_busy_doll_count": sum(all_busy_reason_counts.values()),
        "second_skill_unlocked_count": second_skill_unlocked_count,
        "checked_gun_count": checked_gun_count,
        "examples_skill1": examples_skill1,
        "examples_skill2": examples_skill2,
        "examples_busy": examples_busy,
        "busy_debug": busy_index.get("debug", {}),
    }


def calc_total_trainable_skill_cost_from_index(payload: dict):
    """
    计算当前扫描范围内，所有未满级技能训练到目标等级需要的资料总量。
    规则：
    - skill1：skill1 > 0 且低于目标等级即可统计；
    - skill2：必须 if_modification >= 2（二改 / 等级上限 115），才视为实际存在；
    - 所有未满级技能都符合自动训练候选，是否能执行再由库存判断。
    """
    target_level = get_effective_skill_target_level()
    only_locked = bool(CONFIG.get("AUTO_SKILL_ONLY_LOCKED", True))
    team_only = bool(CONFIG.get("AUTO_SKILL_TEAM_ONLY", False))
    busy_index = build_busy_gun_index(payload)

    guns = payload.get("gun_with_user_info", []) if isinstance(payload, dict) else []
    if not isinstance(guns, list):
        guns = []

    total_cost = {"coin1": 0, "coin2": 0, "coin3": 0, "hours": 0, "quick_training": 0}
    skill1_cost = {"coin1": 0, "coin2": 0, "coin3": 0, "hours": 0, "quick_training": 0}
    skill2_cost = {"coin1": 0, "coin2": 0, "coin3": 0, "hours": 0, "quick_training": 0}

    for gun in guns:
        gun_uid = int_safe(gun.get("id"), 0)
        team_id = int_safe(gun.get("team_id"), 0)
        locked = str(gun.get("is_locked", "0")) == "1"

        if gun_uid <= 0:
            continue
        if only_locked and not locked:
            continue
        if team_only and team_id <= 0:
            continue
        if get_gun_busy_reason(gun, busy_index):
            continue

        has_second_skill = gun_has_second_skill_by_exp(gun)

        for skill_no in (1, 2):
            if skill_no == 2 and not has_second_skill:
                continue

            field = "skill%d" % skill_no
            skill_lv = int_safe(gun.get(field), 0)

            if skill_lv <= 0:
                if skill_no == 2 and has_second_skill:
                    skill_lv = 1
                else:
                    continue

            if skill_lv >= target_level:
                continue

            if not is_skill_allowed_by_test_mode(skill_lv):
                continue

            cost = get_skill_cost_between(skill_lv, target_level)
            bucket = skill1_cost if skill_no == 1 else skill2_cost

            quick_need = get_quick_training_contract_need(skill_lv, target_level)
            cost["quick_training"] = quick_need

            for k in ("coin1", "coin2", "coin3", "hours", "quick_training"):
                bucket[k] += int_safe(cost.get(k), 0)
                total_cost[k] += int_safe(cost.get(k), 0)

    return {
        "total": total_cost,
        "skill1": skill1_cost,
        "skill2": skill2_cost,
    }


def format_cost(cost: dict):
    return "初级=%s | 中级=%s | 高级=%s | 快速契约=%s | 原始时间=%sh" % (
        cost.get("coin1", 0),
        cost.get("coin2", 0),
        cost.get("coin3", 0),
        cost.get("quick_training", 0),
        cost.get("hours", 0),
    )



def print_trainable_skill_count(summary: dict, cost_summary=None, resources=None):
    print("\n=========== 可训练技能统计 ===========")
    print("扫描范围：%s | %s" % (
        "仅当前梯队" if CONFIG.get("AUTO_SKILL_TEAM_ONLY", False) else "全仓库",
        "仅锁定人形" if CONFIG.get("AUTO_SKILL_ONLY_LOCKED", False) else "包含未锁定人形",
    ))
    print("目标等级：Lv.%s" % get_effective_skill_target_level())
    print("已扫描人形数：%s" % summary.get("checked_gun_count", 0))
    if summary.get("busy_debug"):
        debug = summary.get("busy_debug") or {}
        print("后勤梯队：%s" % (debug.get("operation_team_ids") or []))
        print("当前探索 gun_id（仅调试，不按 gun_id 直接判定）：%s" % (debug.get("current_explore_gun_ids") or []))
    print("--------------------------------------")
    print("当前忙碌人形总数（按 UID 去重）：%s" % summary.get("all_busy_doll_count", 0))
    if summary.get("all_busy_reason_counts"):
        print("当前忙碌来源（按 UID 去重）：%s" % " | ".join(
            "%s=%s" % (k, v) for k, v in summary.get("all_busy_reason_counts", {}).items()
        ))
    print("--------------------------------------")
    print("可训练一技能数量：%s" % summary.get("skill1_count", 0))
    print("可训练一技能但忙碌数量：%s" % summary.get("busy_skill1_count", 0))
    print("已开放二技能人形数量：%s" % summary.get("second_skill_unlocked_count", 0))
    print("可训练二技能数量：%s" % summary.get("skill2_count", 0))
    print("可训练二技能但忙碌数量：%s" % summary.get("busy_skill2_count", 0))
    if summary.get("busy_reason_counts"):
        print("可训练但忙碌原因统计（按 UID 去重）：%s" % " | ".join("%s=%s" % (k, v) for k, v in summary.get("busy_reason_counts", {}).items()))
    if resources:
        print("--------------------------------------")
        print("当前库存：初级=%s | 中级=%s | 高级=%s | 快速契约=%s" % (
            resources.get("coin1", 0),
            resources.get("coin2", 0),
            resources.get("coin3", 0),
            resources.get("quick_training", 0),
        ))
    if cost_summary:
        print("--------------------------------------")
        print("训练到目标等级所需资料：")
        print("  一技能：%s" % format_cost(cost_summary.get("skill1", {})))
        print("  二技能：%s" % format_cost(cost_summary.get("skill2", {})))
        print("  合计：%s" % format_cost(cost_summary.get("total", {})))
    print("--------------------------------------")
    if summary.get("examples_skill1"):
        print("一技能候选示例：")
        for item in summary["examples_skill1"]:
            print("  UID=%s | gun_id=%s | skill1 Lv.%s | team=%s" % (
                item["uid"], item["gun_id"], item["skill_lv"], item["team_id"]
            ))
    if summary.get("examples_skill2"):
        print("二技能候选示例：")
        for item in summary["examples_skill2"]:
            print("  UID=%s | gun_id=%s | skill2 Lv.%s | team=%s | MOD%s | total_exp=%s" % (
                item["uid"], item["gun_id"], item["skill_lv"], item["team_id"], item.get("mod_stage", 0), item["total_exp"]
            ))
    if summary.get("examples_busy"):
        print("可训练但忙碌示例：")
        for item in summary["examples_busy"]:
            print("  UID=%s | gun_id=%s | skill%s Lv.%s | team=%s | 状态=%s" % (
                item["uid"], item["gun_id"], item["skill"], item["skill_lv"], item["team_id"], item["reason"]
            ))
    print("======================================\n")


def show_trainable_skill_count_from_index(client: GFLClient):
    global TRAIN_INDEX_CACHE, TRAIN_COUNT_READY

    payload = request_index_snapshot_for_skill(client, force=True)
    if not payload:
        TRAIN_INDEX_CACHE = None
        TRAIN_COUNT_READY = False
        return False

    summary = count_trainable_skills_from_index(payload)
    cost_summary = calc_total_trainable_skill_cost_from_index(payload)
    resources = extract_training_resources_from_index(payload)
    print_trainable_skill_count(summary, cost_summary, resources)

    TRAIN_INDEX_CACHE = payload
    TRAIN_COUNT_READY = True
    print("[TRAIN] 已缓存本次 Index/index。确认仓库信息无误后，输入 -run 开始自动训练。")
    return True



def reset_training_session_log():
    TRAINING_SESSION_LOG.clear()


def train_log(message):
    line = str(message)
    TRAIN_LOG_BUFFER.append(line)
    max_lines = max(5, int_safe(CONFIG.get("TRAIN_PANEL_LOG_LINES", 10), 10))
    if len(TRAIN_LOG_BUFFER) > max_lines:
        del TRAIN_LOG_BUFFER[:-max_lines]
    if not CONFIG.get("TRAIN_FIXED_PANEL_MODE", True):
        print(line)


def start_train_session_panel():
    TRAIN_LOG_BUFFER.clear()
    TRAIN_SESSION_STATS["running"] = True
    TRAIN_SESSION_STATS["start_time"] = time.time()
    TRAIN_SESSION_STATS["attempted"] = 0
    TRAIN_SESSION_STATS["success"] = 0
    TRAIN_SESSION_STATS["failed"] = 0
    TRAIN_SESSION_STATS["skipped"] = 0
    TRAIN_SESSION_STATS["current"] = ""
    TRAIN_SESSION_STATS["last_cost"] = {}
    TRAIN_SESSION_STATS["fairy_auto_start_snapshot"] = read_fairy_snapshot()
    reset_auto_train_interrupt()


def stop_train_session_panel():
    TRAIN_SESSION_STATS["running"] = False
    render_train_fixed_panel(force=True)


def build_train_panel_lines():
    now = time.time()
    elapsed = format_seconds(now - TRAIN_SESSION_STATS.get("start_time", now))
    resources = get_train_cache_resources() or {}
    lines = []
    lines.append("================= 自动训练状态 =================")
    lines.append("状态：%s | 已运行：%s | 成功 %s | 失败 %s | 跳过 %s | 已尝试 %s" % (
        "进行中" if TRAIN_SESSION_STATS.get("running") else "停止",
        elapsed,
        TRAIN_SESSION_STATS.get("success", 0),
        TRAIN_SESSION_STATS.get("failed", 0),
        TRAIN_SESSION_STATS.get("skipped", 0),
        TRAIN_SESSION_STATS.get("attempted", 0),
    ))
    lines.append("当前缓存资料：初级 %s | 中级 %s | 高级 %s | 快速训练契约 %s" % (
        resources.get("coin1", "-"),
        resources.get("coin2", "-"),
        resources.get("coin3", "-"),
        resources.get("quick_training", "-"),
    ))
    if TRAIN_SESSION_STATS.get("current"):
        lines.append("当前处理：%s" % TRAIN_SESSION_STATS.get("current"))
    if TRAIN_SESSION_STATS.get("last_cost"):
        lines.append("最近一次消耗：%s" % format_cost(TRAIN_SESSION_STATS.get("last_cost") or {}))
    if AUTO_TRAIN_LAST_STOP_REASON:
        lines.append("最近停止原因：%s %s" % (AUTO_TRAIN_LAST_STOP_REASON, AUTO_TRAIN_LAST_STOP_DETAIL))
    fairy_auto_line = fairy_runtime_status_line()
    if fairy_auto_line:
        lines.append(fairy_auto_line)
    lines.append("说明：自动训练会根据缓存资料判断是否足够，不足时会切换到获取训练资料。")
    lines.append("提示：训练中按 q 可请求中断；按 Ctrl+C 也会尝试安全中断。")
    lines.append("=================================================")
    return lines


def render_train_fixed_panel(force=False):
    if not CONFIG.get("TRAIN_PANEL_ENABLED", True):
        return
    if CONFIG.get("TRAIN_FIXED_PANEL_MODE", True):
        clear_console_for_panel()
        print("============== 最近训练记录 ==============")
        if TRAIN_LOG_BUFFER:
            for line in TRAIN_LOG_BUFFER[-max(5, int_safe(CONFIG.get("TRAIN_PANEL_LOG_LINES", 10), 10)):]:
                print(line)
        else:
            print("暂无记录")
        print("")
        for line in build_train_panel_lines():
            print(line)
        print("")
    else:
        print("")
        for line in build_train_panel_lines():
            print(line)
        print("")


def reset_auto_train_interrupt():
    global AUTO_TRAIN_INTERRUPT_REQUESTED, stop_macro_flag, stop_micro_flag
    AUTO_TRAIN_INTERRUPT_REQUESTED = False
    stop_macro_flag = False
    stop_micro_flag = False


def request_auto_train_interrupt(reason="用户请求中断"):
    global AUTO_TRAIN_INTERRUPT_REQUESTED, stop_macro_flag, stop_micro_flag
    AUTO_TRAIN_INTERRUPT_REQUESTED = True
    stop_macro_flag = True
    stop_micro_flag = True
    set_auto_train_stop_reason("interrupted", reason)
    train_log("[TRAIN] 已收到中断请求：%s" % reason)
    render_train_fixed_panel(force=True)


def check_auto_train_interrupt():
    if AUTO_TRAIN_INTERRUPT_REQUESTED:
        return True
    if msvcrt is None:
        return False
    try:
        if msvcrt.kbhit():
            ch = msvcrt.getwch()
            if str(ch).lower() == "q":
                request_auto_train_interrupt("用户按下 q")
                return True
    except Exception:
        return False
    return AUTO_TRAIN_INTERRUPT_REQUESTED



def append_training_log(item, status, resp=None, reason=""):
    TRAINING_SESSION_LOG.append({
        "status": status,
        "reason": reason,
        "uid": item.get("gun_uid") if isinstance(item, dict) else None,
        "gun_id": item.get("gun_id") if isinstance(item, dict) else None,
        "gun_level": item.get("gun_level") if isinstance(item, dict) else None,
        "skill": item.get("skill") if isinstance(item, dict) else None,
        "from_level": item.get("current_level") if isinstance(item, dict) else None,
        "to_level": item.get("target_level") if isinstance(item, dict) else None,
        "resp": resp,
    })

    if status == "success":
        TRAIN_SESSION_STATS["success"] = int_safe(TRAIN_SESSION_STATS.get("success"), 0) + 1
    elif status == "failed":
        TRAIN_SESSION_STATS["failed"] = int_safe(TRAIN_SESSION_STATS.get("failed"), 0) + 1
    elif status == "skipped":
        TRAIN_SESSION_STATS["skipped"] = int_safe(TRAIN_SESSION_STATS.get("skipped"), 0) + 1

    if isinstance(item, dict):
        train_log("UID=%s | gun_id=%s | skill%s Lv.%s -> Lv.%s | %s%s" % (
            item.get("gun_uid"),
            item.get("gun_id"),
            item.get("skill"),
            item.get("current_level"),
            item.get("target_level"),
            status,
            (" | %s" % reason) if reason else "",
        ))



def print_training_session_summary():
    print("\n=========== 自动训练结果 ===========")
    if not TRAINING_SESSION_LOG:
        print("本次没有执行任何训练请求。")
        print_fairy_summary(TRAIN_SESSION_STATS.get("fairy_auto_start_snapshot"))
        print("==================================\n")
        return

    success = [x for x in TRAINING_SESSION_LOG if x.get("status") == "success"]
    failed = [x for x in TRAINING_SESSION_LOG if x.get("status") == "failed"]
    skipped = [x for x in TRAINING_SESSION_LOG if x.get("status") == "skipped"]

    print("成功：%d | 失败：%d | 跳过：%d" % (
        len(success), len(failed), len(skipped)
    ))

    for title, rows in (
        ("成功训练", success),
        ("失败跳过", failed),
        ("跳过", skipped),
    ):
        if rows:
            print("%s：" % title)
            for item in rows:
                print("  UID=%s | gun_id=%s | 人形Lv.%s | skill%s Lv.%s -> Lv.%s%s" % (
                    item.get("uid"),
                    item.get("gun_id"),
                    item.get("gun_level"),
                    item.get("skill"),
                    item.get("from_level"),
                    item.get("to_level"),
                    (" | %s" % item.get("reason")) if item.get("reason") else "",
                ))
    print("==================================\n")



def is_unexpected_plaintext_response(resp):
    if not isinstance(resp, dict):
        return False
    err = str(resp.get("error_local", "") or resp.get("error", ""))
    return "Unexpected plaintext response" in err


def build_skill_train_payload(plan_item: dict):
    """
    构造技能快速训练请求。
    plan_item:
      gun_uid      人形实例 UID
      skill        1=一技能，2=二技能
      target_level 目标技能等级
      upgrade_slot 技能训练槽
    """
    return {
        "skill": int_safe(plan_item.get("skill"), 1),
        "if_quick": int_safe(CONFIG.get("SKILL_TRAIN_IF_QUICK", 1), 1),
        "gun_with_user_id": int_safe(plan_item.get("gun_uid"), 0),
        "upgrade_slot": int_safe(plan_item.get("upgrade_slot"), CONFIG.get("SKILL_TRAIN_DEFAULT_SLOT", 1)),
        "to_level": int_safe(plan_item.get("target_level"), CONFIG.get("AUTO_SKILL_TARGET_LEVEL", 10)),
    }



def send_skill_upgrade_request(client: GFLClient, payload: dict):
    """
    技能训练接口兼容发送。
    当前日志中的 Unexpected plaintext response 通常说明 endpoint/path 不匹配，
    因此这里按候选 endpoint 依次尝试。
    """
    tried = []
    last_resp = None

    for endpoint in SKILL_UPGRADE_ENDPOINT_CANDIDATES:
        if endpoint in tried:
            continue
        tried.append(endpoint)

        resp = client.send_request(endpoint, payload)
        last_resp = resp

        if is_unexpected_plaintext_response(resp):
            continue

        return resp

    return last_resp



def update_cached_training_resources(cost: dict):
    """
    自动训练成功后，本地更新缓存中的资料和快速训练契约数量。
    这样连续训练时可以先用缓存判断材料是否足够，减少无效请求。

    同时也要同步扣减获取资料面板使用的 SKILL_DATA_STATS.current_inventory，
    否则“获取资料 -> 自动训练 -> 继续获取资料”跳转回来后会显示训练前库存。
    """
    global TRAIN_INDEX_CACHE

    update_pick_inventory_by_training_cost(cost)

    if not TRAIN_INDEX_CACHE or not isinstance(TRAIN_INDEX_CACHE, dict):
        return

    user_info = TRAIN_INDEX_CACHE.get("user_info", {})
    if isinstance(user_info, dict):
        for key in ("coin1", "coin2", "coin3"):
            old_val = int_safe(user_info.get(key), 0)
            user_info[key] = str(max(0, old_val - int_safe(cost.get(key), 0)))

    items = TRAIN_INDEX_CACHE.get("item_with_user_info", [])
    if isinstance(items, list):
        for item in items:
            if str(item.get("item_id")) == "8":
                old_val = int_safe(item.get("number"), 0)
                item["number"] = str(max(0, old_val - int_safe(cost.get("quick_training", 0), 0)))
                break

    sync_pick_inventory_from_train_cache()


def update_cached_skill_level_after_success(item: dict):
    """
    自动训练成功后同步更新缓存中的 skill1 / skill2，避免同一次缓存内重复选择。
    """
    global TRAIN_INDEX_CACHE
    if not TRAIN_INDEX_CACHE or not isinstance(TRAIN_INDEX_CACHE, dict) or not isinstance(item, dict):
        return

    guns = TRAIN_INDEX_CACHE.get("gun_with_user_info", [])
    if not isinstance(guns, list):
        return

    target_uid = int_safe(item.get("gun_uid"), 0)
    skill_no = int_safe(item.get("skill"), 1)
    target_level = int_safe(item.get("target_level"), 10)
    field = "skill%d" % skill_no

    for gun in guns:
        if int_safe(gun.get("id"), 0) == target_uid:
            gun[field] = str(target_level)
            break



def set_auto_train_stop_reason(reason, detail=""):
    global AUTO_TRAIN_LAST_STOP_REASON, AUTO_TRAIN_LAST_STOP_DETAIL
    AUTO_TRAIN_LAST_STOP_REASON = reason
    AUTO_TRAIN_LAST_STOP_DETAIL = detail


def get_train_cache_resources():
    if not TRAIN_INDEX_CACHE:
        return None
    return extract_training_resources_from_index(TRAIN_INDEX_CACHE)


def find_first_train_candidate_from_cache():
    if not TRAIN_INDEX_CACHE:
        return None
    candidates = build_auto_skill_candidates_from_index(TRAIN_INDEX_CACHE)
    if not candidates:
        return None
    return candidates[0]


def is_first_candidate_affordable_from_cache():
    resources = get_train_cache_resources()
    item = find_first_train_candidate_from_cache()
    if not resources or not item:
        return False, item, resources, None

    cost = dict(item.get("cost", {}))
    cost["quick_training"] = get_quick_training_contract_need(item["current_level"], item["target_level"])
    return has_enough_training_resource(resources, cost), item, resources, cost


def print_cycle_status(prefix="[循环]"):
    resources = get_train_cache_resources()
    if resources:
        print("%s 缓存库存：初级=%s | 中级=%s | 高级=%s | 快速契约=%s" % (
            prefix,
            resources.get("coin1"),
            resources.get("coin2"),
            resources.get("coin3"),
            resources.get("quick_training"),
        ))



def run_auto_skill_training_from_index(client: GFLClient, reset_log=True, preloaded_payload=None):
    set_auto_train_stop_reason("", "")
    if reset_log:
        reset_training_session_log()

    if not CONFIG.get("AUTO_SKILL_FROM_INDEX", True):
        set_auto_train_stop_reason("disabled", "自动 Index 判断已关闭")
        train_log("[TRAIN] 自动训练判断已关闭。")
        render_train_fixed_panel(force=True)
        return False

    if preloaded_payload is not None:
        payload = preloaded_payload
        train_log("[TRAIN] 使用缓存仓库信息进行训练判断。")
    else:
        payload = request_index_snapshot_for_skill(client, force=True)

    if not payload:
        set_auto_train_stop_reason("index_failed", "Index/index 请求失败")
        return False

    resources = extract_training_resources_from_index(payload)
    train_log("[TRAIN] 当前缓存资料：初级=%s | 中级=%s | 高级=%s | 快速训练契约=%s" % (
        resources.get("coin1"), resources.get("coin2"), resources.get("coin3"), resources.get("quick_training")
    ))
    render_train_fixed_panel(force=True)

    slot = get_first_available_upgrade_slot(payload)
    if slot is None:
        set_auto_train_stop_reason("no_slot", "当前没有空闲技能训练槽")
        train_log("[TRAIN] 当前没有空闲技能训练槽，跳过自动训练。")
        render_train_fixed_panel(force=True)
        return False

    candidates = build_auto_skill_candidates_from_index(payload)
    print_auto_skill_candidates(candidates, limit=5)

    if not candidates:
        set_auto_train_stop_reason("done", "仓库中没有可训练的人形")
        train_log("[TRAIN] 仓库中没有可训练技能的人形。")
        render_train_fixed_panel(force=True)
        return False

    max_count = max(1, int_safe(CONFIG.get("AUTO_SKILL_MAX_PER_TRIGGER", 1), 1))
    trained = 0
    attempted = 0

    for item in candidates:
        if check_auto_train_interrupt():
            set_auto_train_stop_reason("interrupted", "用户请求中断")
            break
        if trained >= max_count:
            break
        cost = item.get("cost", {})
        cost["quick_training"] = get_quick_training_contract_need(item["current_level"], item["target_level"])

        if int_safe(resources.get("quick_training"), 0) < int_safe(cost.get("quick_training", 0), 0):
            reason = "快速训练契约不足，需要 %s，当前 %s" % (
                cost.get("quick_training", 0),
                resources.get("quick_training", 0),
            )
            set_auto_train_stop_reason("need_pick", reason)
            train_log("[TRAIN] %s，停止自动训练。" % reason)
            render_train_fixed_panel(force=True)
            append_training_log(item, "skipped", None, reason)
            break

        if not has_enough_training_resource(resources, cost):
            reason = "训练资料不足，下一候选 UID=%s skill%s Lv.%s->Lv.%s 需要：%s" % (
                item.get("gun_uid"),
                item.get("skill"),
                item.get("current_level"),
                item.get("target_level"),
                format_cost(cost),
            )
            set_auto_train_stop_reason("need_pick", reason)
            train_log("[TRAIN] %s，停止自动训练并准备获取资料。" % reason)
            render_train_fixed_panel(force=True)
            append_training_log(item, "skipped", None, reason)
            break

        plan_item = {
            "gun_uid": item["gun_uid"],
            "skill": item["skill"],
            "target_level": item["target_level"],
            "upgrade_slot": slot,
            "done": False,
        }

        TRAIN_SESSION_STATS["current"] = "UID=%s | gun_id=%s | 人形Lv.%s | skill%s Lv.%s -> Lv.%s" % (
            item["gun_uid"], item["gun_id"], item.get("gun_level", "-"), item["skill"], item["current_level"], item["target_level"]
        )
        train_log("[TRAIN] 队列选择：" + TRAIN_SESSION_STATS["current"])
        quick_need = get_quick_training_contract_need(item["current_level"], item["target_level"])
        cost["quick_training"] = quick_need
        TRAIN_SESSION_STATS["last_cost"] = {
            "coin1": cost.get("coin1", 0),
            "coin2": cost.get("coin2", 0),
            "coin3": cost.get("coin3", 0),
            "hours": cost.get("hours", 0),
            "quick_training": quick_need,
        }
        train_log("[TRAIN] 本次训练所需：" + format_cost(TRAIN_SESSION_STATS["last_cost"]))
        render_train_fixed_panel(force=True)

        resp = send_skill_upgrade_request(client, build_skill_train_payload(plan_item))
        attempted += 1
        TRAIN_SESSION_STATS["attempted"] = int_safe(TRAIN_SESSION_STATS.get("attempted"), 0) + 1

        if check_step_error(resp, "skillUpgrade"):
            train_log("[TRAIN] 当前人形训练失败，已跳过并继续下一个候选。")
            render_train_fixed_panel(force=True)
            item["failed"] = True
            item["last_resp"] = resp
            append_training_log(item, "failed", resp, "请求失败")
            for _ in range(max(1, int(float(CONFIG.get("SKILL_TRAIN_COOLDOWN_SECONDS", 2)) * 10))):
                if check_auto_train_interrupt():
                    break
                gfam_adaptive_sleep("step", 0.1)
            continue

        train_log("[TRAIN] 自动快速训练请求已发送。")
        render_train_fixed_panel(force=True)
        append_training_log(item, "success", resp, "")
        trained += 1

        # 本地扣减，用于同一轮连续训练以及后续使用缓存时避免提交无效申请。
        for k in ("coin1", "coin2", "coin3"):
            resources[k] = int_safe(resources.get(k), 0) - int_safe(cost.get(k), 0)
        resources["quick_training"] = int_safe(resources.get("quick_training"), 0) - int_safe(cost.get("quick_training", 0), 0)
        update_cached_training_resources(cost)
        update_cached_skill_level_after_success(item)
        set_auto_train_stop_reason("trained", "")

        for _ in range(max(1, int(float(CONFIG.get("SKILL_TRAIN_COOLDOWN_SECONDS", 2)) * 10))):
            if check_auto_train_interrupt():
                break
            gfam_adaptive_sleep("step", 0.1)

    if trained <= 0:
        train_log("[TRAIN] 本轮没有成功执行的自动训练。")
        render_train_fixed_panel(force=True)
    elif not AUTO_TRAIN_LAST_STOP_REASON:
        set_auto_train_stop_reason("trained", "")
    return trained > 0



def run_skill_training_after_coin_pause(client: GFLClient):
    if not SKILL_DATA_STATS.get("middle_zero_detected", False):
        return False
    if not CONFIG.get("AUTO_TRAIN_ON_MIDDLE_COIN_ZERO", True):
        print("[TRAIN] 已检测到中级训练资料 +0，但暂停后自动训练已关闭。")
        return False

    print("[TRAIN] 中级训练资料 +0 暂停触发，开始自动判断训练条件。")
    payload = request_index_snapshot_for_skill(client, force=True)
    if payload:
        global TRAIN_INDEX_CACHE, TRAIN_COUNT_READY
        TRAIN_INDEX_CACHE = payload
        TRAIN_COUNT_READY = True
        ok = run_train_until_blocked(client, use_cache=True)
        sync_pick_inventory_from_train_cache()
        print_training_session_summary()
        return ok

    print("[TRAIN] 无法获取仓库信息，自动训练取消。")
    return False

def get_pick_macro_limit():
    limit = CONFIG.get("MACRO_LOOPS", 0)
    limit = int_safe(limit, 0)
    return limit if limit > 0 else None


def format_pick_macro_title(macro, macro_limit):
    if macro_limit:
        return "=== 第 %d / %d 轮 ===" % (macro, macro_limit)
    return "=== 第 %d 轮 / 直到自动停止条件 ===" % macro





def farm_worker():
    global stop_macro_flag, stop_micro_flag, worker_mode, current_worker_thread, CURRENT_MENU
    try:
        _farm_worker_impl()
    except Exception:
        stop_macro_flag = True
        stop_micro_flag = True
        worker_mode = None
        current_worker_thread = None
        CURRENT_MENU = "main"
        try:
            PICK_SESSION_STATS["running"] = False
        except Exception:
            pass
        print("\n[异常保护] 运行线程发生未处理异常，已自动终止当前运行，避免异常进程继续执行。")
        print(traceback.format_exc())
        try:
            print_pick_panel(force=True)
        except Exception:
            pass
        try:
            print_main_menu()
        except Exception:
            pass

def gfam_pre_run_abort_once(client, reason="正式运行前状态清理"):
    """运行前轻量 abortMission 一次，清理上次异常残留的获取资料关卡状态。"""
    if not CONFIG.get("ENABLE_PRE_RUN_ABORT", True):
        return False
    mission_id = CONFIG.get("MISSION_ID")
    if not mission_id:
        return False
    try:
        pick_log("[状态清理] %s：尝试 abortMission mission_id=%s。" % (reason, mission_id))
        client.send_request(API_MISSION_ABORT, {"mission_id": int(mission_id)})
        return True
    except Exception:
        return False


def _farm_worker_impl():
    global stop_macro_flag, stop_micro_flag, worker_mode, current_worker_thread, CURRENT_MENU, TRAIN_INDEX_CACHE, TRAIN_COUNT_READY

    if CONFIG["SIGN_KEY"] == DEFAULT_SIGN:
        print("[!] UID/SIGN 未就绪。请返回 GFAM 主菜单使用 auth 重新获取 UID/SIGN。")
        worker_mode, current_worker_thread = None, None
        return

    client = GFLClient(CONFIG["USER_UID"], CONFIG["SIGN_KEY"], CONFIG["BASE_URL"])
    gfam_pre_run_abort_once(client, reason="运行前状态清理")

    if not CONFIG.get("PICK_TEAM_VALIDATED", False):
        print("[获取资料] 梯队尚未完成校验，请从获取资料菜单重新输入 -r。")
        worker_mode, current_worker_thread = None, None
        return

    _cached_idx = request_index_snapshot_for_skill(client)  # P2 缓存种子
    start_pick_session(client, index_payload=_cached_idx)
    pick_log("=== GFL Protocol Auto-Farming Started (Mission 10352) ===")
    pick_log("[*] 当前服务器：%s" % CONFIG.get("SERVER_NAME", "SOP"))
    pick_log("[*] 当前梯队：%s（固定单人人形梯队）" % CONFIG.get("TEAM_ID"))
    print_pick_panel(force=True)

    macro_limit = get_pick_macro_limit()
    macro = 1
    consecutive_failures = 0
    max_consecutive_failures = max(1, int(CONFIG.get("MAX_CONSECUTIVE_FAILURES", 10) or 10))
    while True:
        if macro_limit and macro > macro_limit:
            pick_log("[获取资料] 已达到手动设置的最大轮次：%d。" % macro_limit)
            break

        PICK_SESSION_STATS["macro"] = macro
        if stop_macro_flag:
            break

        pick_log(format_pick_macro_title(macro, macro_limit))
        print_pick_panel(force=True)

        batch_guns = []
        for micro in range(1, CONFIG["MISSIONS_PER_RETIRE"] + 1):
            if stop_micro_flag or stop_macro_flag:
                break

            PICK_SESSION_STATS["micro"] = micro
            PICK_SESSION_STATS["run_count"] = int_safe(PICK_SESSION_STATS.get("run_count"), 0) + 1
            pick_log("[*] Micro %d / %d" % (micro, CONFIG["MISSIONS_PER_RETIRE"]))
            print_pick_panel(force=False)
            dropped = farm_mission_10352(client, CONFIG["TEAM_ID"])

            if dropped is None:
                consecutive_failures += 1
                pick_log("[-] 本轮失败，正在放弃关卡并稍后继续……")
                pick_log("[异常保护] 当前 Micro 失败，连续失败 %d / %d。" % (consecutive_failures, max_consecutive_failures))
                print_pick_panel(force=True)
                try:
                    client.send_request(API_MISSION_ABORT, {"mission_id": CONFIG["MISSION_ID"]})
                except Exception:
                    pass
                failure_limit_reached = consecutive_failures >= max_consecutive_failures
                if failure_limit_reached:
                    pick_log("[异常保护] 连续失败已达到上限，但会先执行本次自修复；若自修复成功将重新计数。")
                if CONFIG.get("ENABLE_GUN_EXCEPTION_SELF_REPAIR", True):
                    pick_log("[自修复] 当前 Micro 失败，尝试人形应急拆解后重试当前 Micro 一次。")
                    if gfam_try_exception_self_repair(client, reason="获取资料 Micro Error Before Retry"):
                        retry_drop = farm_mission_10352(client, CONFIG["TEAM_ID"])
                        if retry_drop is not None:
                            consecutive_failures = 0
                            pick_log("[自修复] 重试成功，连续失败计数已清零，继续运行。")
                            dropped = retry_drop
                        else:
                            try:
                                client.send_request(API_MISSION_ABORT, {"mission_id": CONFIG["MISSION_ID"]})
                            except Exception:
                                pass
                            pick_log("[自修复] 重试后仍失败，本次 Micro 跳过，继续观察后续运行。")
                            time.sleep(3)
                            continue
                    else:
                        if failure_limit_reached:
                            pick_log("[自修复] 连续失败达到上限且本次未能完成自修复，已自动终止当前运行。")
                            stop_macro_flag = True
                            stop_micro_flag = True
                            break
                        pick_log("[自修复] 人形应急拆解未完成，本次 Micro 跳过。")
                        time.sleep(3)
                        continue
                else:
                    if failure_limit_reached:
                        pick_log("[异常保护] 连续失败达到上限且自修复已关闭，已自动终止当前运行。")
                        stop_macro_flag = True
                        stop_micro_flag = True
                        break
                    time.sleep(3)
                    continue

            if consecutive_failures:
                consecutive_failures = 0
            batch_guns.extend(dropped)
            gfam_final_cleanup_note_guns(dropped)

        if (stop_micro_flag or stop_macro_flag) and batch_guns:
            pick_log("[安全停止] 已收到 -q/-Q，将先自动拆解本轮已记录掉落，再结束当前获取资料流程。")
        retire_guns(client, batch_guns)

        if SKILL_DATA_STATS.get("middle_zero_detected", False):
            if CONFIG.get("TRAIN_PICK_CYCLE_ENABLED", False):
                pick_log("[循环] 中级训练资料本次获得为 0，停止获取资料并切回自动训练。")
                print_pick_panel(force=True)
                payload = request_index_snapshot_for_skill(client, force=True)
                if payload:
                    TRAIN_INDEX_CACHE = payload
                    TRAIN_COUNT_READY = True
                    run_train_until_blocked(client, use_cache=True)
                    sync_pick_inventory_from_train_cache()
                    print_training_session_summary()

                    if AUTO_TRAIN_LAST_STOP_REASON == "need_pick":
                        pick_log("[循环] 训练后仍然缺少训练资料，继续获取资料。")
                        print_pick_panel(force=True)
                        SKILL_DATA_STATS["middle_zero_detected"] = False
                        stop_macro_flag = False
                        stop_micro_flag = False
                        gfam_adaptive_sleep("step", 0.1)
                        continue

                    if AUTO_TRAIN_LAST_STOP_REASON == "done":
                        pick_log("[循环] 仓库中没有可训练技能的人形，自动循环结束。")
                        print_pick_panel(force=True)
                        break

                pick_log("[循环] 自动训练无法继续，获取资料停止。")
                print_pick_panel(force=True)
                break

            trained_ok = run_skill_training_after_coin_pause(client)

            if CONFIG.get("PICK_AUTO_TRAIN_AND_RESUME", False) and trained_ok:
                pick_log("[获取资料] 自动训练已执行，重置 coin2+0 暂停标记并继续获取资料。")
                print_pick_panel(force=True)
                SKILL_DATA_STATS["middle_zero_detected"] = False
                stop_macro_flag = False
                stop_micro_flag = False
                gfam_adaptive_sleep("micro", 1)
                continue

            pick_log("[获取资料] coin2+0 后自动训练流程结束，获取资料停止。")
            print_pick_panel(force=True)
            break
        gfam_adaptive_sleep("micro", 1)

        if stop_micro_flag:
            break

        macro += 1

    gfam_run_final_cleanup(client, label="运行结束前")
    PICK_SESSION_STATS["running"] = False
    print_pick_panel(force=True)
    pick_log("[*] Farming runs ended.")
    print_pick_panel(force=True)
    print("\n[*] Farming runs ended.")
    print_fairy_summary(PICK_SESSION_STATS.get("fairy_auto_start_snapshot"))
    worker_mode, current_worker_thread = None, None
    CURRENT_MENU = "main"
    print_main_menu()


def run_train_until_blocked(client: GFLClient, use_cache=True):
    """
    自动训练循环：
    - 使用缓存判断下一个候选是否材料足够；
    - 能训练就继续；
    - 不够下一次升到目标等级时停止，交给获取资料；
    - 没有候选则结束整个循环。
    """
    global TRAIN_INDEX_CACHE, TRAIN_COUNT_READY

    if not TRAIN_COUNT_READY or TRAIN_INDEX_CACHE is None:
        payload = request_index_snapshot_for_skill(client, force=True)
        if not payload:
            set_auto_train_stop_reason("index_failed", "Index/index 请求失败")
            return False
        TRAIN_INDEX_CACHE = payload
        TRAIN_COUNT_READY = True

    reset_training_session_log()
    start_train_session_panel()
    any_trained = False

    while not stop_macro_flag and not stop_micro_flag and not AUTO_TRAIN_INTERRUPT_REQUESTED:
        if check_auto_train_interrupt():
            break
        ok = run_auto_skill_training_from_index(
            client,
            reset_log=False,
            preloaded_payload=TRAIN_INDEX_CACHE if use_cache else None,
        )

        if ok:
            any_trained = True
            # 训练成功后继续使用本地更新后的缓存检查下一个候选。
            affordable, item, resources, cost = is_first_candidate_affordable_from_cache()
            if item is None:
                set_auto_train_stop_reason("done", "仓库中没有可训练的人形")
                break
            if not affordable:
                set_auto_train_stop_reason("need_pick", "缓存材料不足，下一候选需要：%s" % format_cost(cost or {}))
                break
            continue

        # 没训练成功，按原因退出。
        break

    stop_train_session_panel()
    return any_trained


def start_farming_from_cycle():
    print("[循环] 训练资料不足，切换到获取训练资料。")
    CONFIG["PICK_AUTO_TRAIN_AND_RESUME"] = True
    start_farming(auto_confirm=True, from_cycle=True)



def train_count_submenu():
    """
    -count 后的确认子菜单。
    用户必须先查看仓库统计，再在这里输入 -run 执行训练。
    """
    global CURRENT_MENU

    print("\n============= 自动训练确认子菜单 =============")
    print("已获取并缓存 Index/index。")
    print(" -run     : 使用当前缓存开始自动训练")
    print(" -refresh : 重新获取 Index/index 并刷新统计")
    print(" -stop/q  : 请求中断正在进行的自动训练")
    print(" -back/b  : 返回自动训练菜单")
    print(" -E       : 返回少女全自动 GFAM 主菜单")
    print("============================================\n")

    while True:
        cmd = normalize_menu_input(input("GFL-TRAIN-COUNT> "))
        if not cmd:
            continue
        parts = cmd.split()
        prefix = parts[0]

        if prefix == "-E":
            exit_program()

        if prefix in ("-back", "b", "back"):
            CURRENT_MENU = "train"
            print_train_menu()
            return

        if prefix in ("-refresh", "refresh", "-count", "count"):
            if CONFIG["SIGN_KEY"] == DEFAULT_SIGN:
                print("[!] UID/SIGN 未就绪。请返回 GFAM 主菜单使用 auth 重新获取 UID/SIGN。")
            else:
                client = GFLClient(CONFIG["USER_UID"], CONFIG["SIGN_KEY"], CONFIG["BASE_URL"])
                show_trainable_skill_count_from_index(client)
            continue

        if prefix in ("-run", "run"):
            try:
                run_train_menu_auto_once()
            except KeyboardInterrupt:
                request_auto_train_interrupt("用户按下 Ctrl+C")
            return

        if prefix in ("-stop", "stop", "-q", "q", "-Q"):
            request_auto_train_interrupt("用户在确认子菜单输入停止命令")
            continue

        if prefix in ("-help", "h", "help"):
            print("可用命令：-run / -refresh / -stop / -back / -E")
            continue

        print("[!] 自动训练确认子菜单未知命令：%s" % prefix)
        print("[*] 输入 -run 开始训练，或输入 -back 返回。")



def run_train_menu_auto_once():
    global TRAIN_INDEX_CACHE, TRAIN_COUNT_READY, CURRENT_MENU

    if CONFIG["SIGN_KEY"] == DEFAULT_SIGN:
        print("[!] UID/SIGN 未就绪。请返回 GFAM 主菜单使用 auth 重新获取 UID/SIGN。")
        return False

    if not TRAIN_COUNT_READY or TRAIN_INDEX_CACHE is None:
        print("[TRAIN] 请先输入 -count 获取 Index/index 并确认仓库可训练信息，再输入 -run 开始训练。")
        return False

    client = GFLClient(CONFIG["USER_UID"], CONFIG["SIGN_KEY"], CONFIG["BASE_URL"])

    if CONFIG.get("TRAIN_PICK_CYCLE_ENABLED", False):
        ok = run_train_until_blocked(client, use_cache=True)
    else:
        start_train_session_panel()
        ok = run_auto_skill_training_from_index(client, reset_log=True, preloaded_payload=TRAIN_INDEX_CACHE)
        stop_train_session_panel()

    print_training_session_summary()
    print("[TRAIN] 自动训练菜单任务已结束。")
    print("[TRAIN] 本次 Index 缓存已保留，并已根据成功训练结果本地扣减资料/契约。")
    print("[TRAIN] 可继续输入 -run 使用缓存训练；如需刷新仓库状态，请重新输入 -count。")

    if CONFIG.get("TRAIN_PICK_CYCLE_ENABLED", False):
        if AUTO_TRAIN_LAST_STOP_REASON == "need_pick":
            print("[循环] %s" % (AUTO_TRAIN_LAST_STOP_DETAIL or "材料不足，准备获取资料。"))
            CURRENT_MENU = "pick"
            start_farming_from_cycle()
        elif AUTO_TRAIN_LAST_STOP_REASON == "done":
            print("[循环] 仓库中没有可训练技能的人形，自动循环结束。")
        elif stop_macro_flag or stop_micro_flag:
            print("[循环] 已收到中断标记，自动循环停止。")

    return ok



def start_farming(auto_confirm=False, from_cycle=False):
    global proxy_instance, stop_macro_flag, stop_micro_flag, worker_mode, current_worker_thread

    if worker_mode == "r":
        print("[!] 当前已经在运行中。")
        return

    if worker_mode == "c" and proxy_instance:
        stop_proxy_only()
        gfam_adaptive_sleep("micro", 1)

    CONFIG["TEAM_ID"] = int(CONFIG.get("PICK_FIXED_TEAM_ID", 1))
    CONFIG["PICK_TEAM_VALIDATED"] = False

    if CONFIG["SIGN_KEY"] == DEFAULT_SIGN:
        print("[!] UID/SIGN 未就绪。请返回 GFAM 主菜单使用 auth 重新获取 UID/SIGN。")
        worker_mode, current_worker_thread = None, None
        return

    client = GFLClient(CONFIG["USER_UID"], CONFIG["SIGN_KEY"], CONFIG["BASE_URL"])
    if not validate_pick_team_single_from_index(client, ask_confirm=(not auto_confirm)):
        worker_mode, current_worker_thread = None, None
        return

    stop_macro_flag = False
    stop_micro_flag = False
    worker_mode = "r"
    current_worker_thread = threading.Thread(target=farm_worker)
    current_worker_thread.daemon = True
    current_worker_thread.start()


def exit_program():
    global stop_macro_flag, stop_micro_flag
    if proxy_instance:
        proxy_instance.stop()
        set_windows_proxy(False)
        print("[*] 已退出。Windows 代理已恢复。")
    else:
        print("[*] 已退出，未启动本模块代理。")
    stop_macro_flag, stop_micro_flag = True, True
    sys.exit(0)


def get_menu_prompt():
    if CURRENT_MENU == "capture":
        return "GFL-CAPTURE> "
    if CURRENT_MENU == "pick":
        return "GFL-PICK> "
    if CURRENT_MENU == "train":
        return "GFL-TRAIN> "
    return "GFL-MAIN> "


if __name__ == "__main__":
    # 从 GFAM 主菜单启动时，先套用服务器再沿用 UID/SIGN，避免非 SOP 服务器沿用默认 SOP BASE_URL。
    if launched_from_gfam_main():
        apply_server_selection(get_default_server_from_env())
    apply_gfam_auth_from_env()
    if is_key_ready():
        print_main_menu()
    elif launched_from_gfam_main():
        print("[!] 未检测到 GFAM 主菜单提供的有效 UID/SIGN。")
        print("[*] 本模块不会自行启动代理；请返回 GFAM 主菜单使用 auth 重新获取。")
        CURRENT_MENU = "main"
        print_main_menu()
    else:
        CURRENT_MENU = "capture"
        print_capture_menu()

    while True:
        try:
            cmd = normalize_menu_input(input(get_menu_prompt()))
            if not cmd:
                continue

            parts = cmd.split()
            cmd_prefix = parts[0]

            # Global commands
            if cmd_prefix == "-E":
                exit_program()

            if cmd_prefix in ("-help", "h", "help"):
                if CURRENT_MENU == "capture":
                    print_capture_menu()
                elif CURRENT_MENU == "pick":
                    print_pick_menu()
                elif CURRENT_MENU == "train":
                    print_train_menu()
                else:
                    print_main_menu()
                continue

            if cmd_prefix in ("-back", "b", "back"):
                if is_key_ready():
                    CURRENT_MENU = "main"
                    print_main_menu()
                else:
                    CURRENT_MENU = "capture"
                    print_capture_menu()
                continue

            if cmd_prefix == "-status":
                print_status()
                continue

            if cmd_prefix == "-server":
                print_server_menu()
                server_cmd = normalize_menu_input(input("GFL-COIN(服务器, 默认%s)> " % get_default_server_from_env()))
                apply_server_selection(server_cmd)
                continue

            # Before key capture, only capture-related commands are allowed.
            if not is_key_ready():
                if launched_from_gfam_main():
                    print("[!] 未检测到 GFAM 主菜单提供的有效 UID/SIGN。")
                    print("[*] 本模块不会自行启动代理；请返回 GFAM 主菜单使用 auth 重新获取。")
                    continue
                if cmd_prefix in ("-a", "-c"):
                    start_capture_proxy()
                    continue
                if cmd_prefix in ("-1", "1", "-pick", "pick", "-2", "2", "-train", "train", "-r", "-run", "run", "-count", "count"):
                    print("[!] 密钥尚未抓取成功。单独运行本模块时，请先输入 -a 抓取 UID / SIGN。")
                    print("[*] 从 GFAM 主菜单进入时，请返回主菜单使用 auth 重新获取 UID/SIGN。")
                    CURRENT_MENU = "capture"
                    print_capture_menu()
                    continue
                if CURRENT_MENU != "capture":
                    CURRENT_MENU = "capture"
                    print_capture_menu()
                    continue

            # Allow direct menu switching from any submenu.
            if cmd_prefix in ("-1", "1", "-pick", "pick"):
                CURRENT_MENU = "pick"
                print_pick_menu()
                continue

            if cmd_prefix in ("-2", "2", "-train", "train"):
                CURRENT_MENU = "train"
                print_train_menu()
                continue

            # Capture menu
            if CURRENT_MENU == "capture":
                if cmd_prefix in ("-a", "-c"):
                    start_capture_proxy()
                    continue

                print("[!] 密钥抓取菜单未知命令：%s" % cmd_prefix)
                print("[*] 请返回 GFAM 主菜单使用 auth 重新获取 UID/SIGN，或输入 -help 查看菜单。")
                continue

            # Main menu
            if CURRENT_MENU == "main":
                if cmd_prefix in ("-1", "1", "-pick", "pick"):
                    CURRENT_MENU = "pick"
                    print_pick_menu()
                    continue

                if cmd_prefix in ("-2", "2", "-train", "train"):
                    CURRENT_MENU = "train"
                    print_train_menu()
                    continue

                # 兼容旧命令：只把获取资料/统计/停止类命令导向 pick；不再用 -a/-c 重新启动代理。
                if cmd_prefix in ("-r", "-run", "run", "-q", "-Q", "-coin"):
                    CURRENT_MENU = "pick"
                    print_pick_menu()
                    # fall through into pick by not continuing
                elif cmd_prefix in ("-a", "-c", "-s"):
                    print("[!] 当前 UID/SIGN 已由 GFAM 主菜单统一获取，本菜单不再重复启动代理。")
                    print("[*] 请选择 -1 / -pick 获取资料，或 -2 / -train 自动训练。")
                    continue
                elif cmd_prefix == "-skill":
                    CURRENT_MENU = "train"
                    print_train_menu()
                    # fall through into train
                else:
                    print("[!] 未知命令：%s" % cmd_prefix)
                    print("[*] 输入 -help 或 h 查看菜单。")
                    continue

            # Pick menu
            if CURRENT_MENU == "pick":
                if cmd_prefix in ("-a", "-c"):
                    print("[!] 获取训练资料菜单不再重复启动代理；UID/SIGN 已由 GFAM 主菜单统一获取。")
                    print("[*] 如确实需要重新获取 UID/SIGN，请返回 GFAM 主菜单使用 auth。")
                    continue

                if cmd_prefix == "-r":
                    start_farming()
                    continue

                if cmd_prefix == "-s":
                    if proxy_instance:
                        stop_proxy_only()
                    else:
                        print("[*] 当前没有运行中的代理；获取资料流程不需要启动代理。")
                    continue

                if cmd_prefix == "-auto":
                    CONFIG["PICK_AUTO_TRAIN_AND_RESUME"] = not CONFIG.get("PICK_AUTO_TRAIN_AND_RESUME", False)
                    print("[+] 中级资料到上限后自动训练并继续获取资料：%s" % CONFIG["PICK_AUTO_TRAIN_AND_RESUME"])
                    print_pick_menu()
                    continue

                if cmd_prefix == "-panel":
                    CONFIG["PICK_PANEL_ENABLED"] = not CONFIG.get("PICK_PANEL_ENABLED", True)
                    print("[+] 获取训练资料状态：%s" % CONFIG["PICK_PANEL_ENABLED"])
                    print_pick_menu()
                    continue

                if cmd_prefix == "-panelmode":
                    CONFIG["PICK_FIXED_PANEL_MODE"] = not CONFIG.get("PICK_FIXED_PANEL_MODE", True)
                    print("[+] 状态面板显示模式：%s" % ("固定在下方刷新" if CONFIG["PICK_FIXED_PANEL_MODE"] else "普通连续打印"))
                    print_pick_menu()
                    continue

                if cmd_prefix == "-coin":
                    handle_coin_command(parts)
                    continue

                if cmd_prefix == "-q":
                    stop_macro_flag = True
                    print("[*] 将在当前 MACRO 结束后安全停止。")
                    continue

                if cmd_prefix == "-Q":
                    stop_micro_flag = True
                    print("[*] 将在当前 MICRO 结束后安全停止。")
                    continue

                print("[!] 获取资料菜单未知命令：%s" % cmd_prefix)
                print("[*] 输入 -help 或 h 查看当前菜单。")
                continue

            # Train menu
            if CURRENT_MENU == "train":
                if cmd_prefix in ("-stop", "stop", "-q", "q", "-Q"):
                    request_auto_train_interrupt("用户在自动训练菜单输入停止命令")
                    continue

                if cmd_prefix in ("-count", "count"):
                    if CONFIG["SIGN_KEY"] == DEFAULT_SIGN:
                        print("[!] UID/SIGN 未就绪。请返回 GFAM 主菜单使用 auth 重新获取 UID/SIGN。")
                    else:
                        client = GFLClient(CONFIG["USER_UID"], CONFIG["SIGN_KEY"], CONFIG["BASE_URL"])
                        if show_trainable_skill_count_from_index(client):
                            train_count_submenu()
                    continue

                if cmd_prefix in ("-run", "run"):
                    print("[TRAIN] 请先输入 -count 查看仓库统计，然后在确认子菜单中输入 -run。")
                    continue

                if cmd_prefix in ("-panel", "panel"):
                    CONFIG["TRAIN_PANEL_ENABLED"] = not CONFIG.get("TRAIN_PANEL_ENABLED", True)
                    print("[+] 自动训练状态面板：%s" % CONFIG["TRAIN_PANEL_ENABLED"])
                    continue

                if cmd_prefix in ("-cycle", "cycle"):
                    CONFIG["TRAIN_PICK_CYCLE_ENABLED"] = not CONFIG.get("TRAIN_PICK_CYCLE_ENABLED", True)
                    print("[+] 训练/获取资料自动循环：%s" % CONFIG["TRAIN_PICK_CYCLE_ENABLED"])
                    if CONFIG["TRAIN_PICK_CYCLE_ENABLED"]:
                        print("[循环] 流程：训练到材料不足 -> 获取资料到 coin2+0 -> 自动训练，如此循环直到无可训练人形。")
                        print("[循环] 自动循环需要先 -count；训练中可按 q 请求中断。")
                    continue

                if cmd_prefix in ("-target", "target"):
                    if len(parts) < 2:
                        print("[!] 用法：-target <目标等级>")
                        continue
                    target = int_safe(parts[1], 10)
                    if target < 2 or target > 10:
                        print("[!] 目标等级必须为 2~10。")
                        continue
                    CONFIG["AUTO_SKILL_TARGET_LEVEL"] = target
                    invalidate_train_index_cache()
                    print("[+] 自动训练目标等级已设置为：%s" % target)
                    continue

                if cmd_prefix in ("-locked", "locked"):
                    CONFIG["AUTO_SKILL_ONLY_LOCKED"] = not CONFIG.get("AUTO_SKILL_ONLY_LOCKED", True)
                    invalidate_train_index_cache()
                    print("[+] 只训练已锁定人形：%s" % CONFIG["AUTO_SKILL_ONLY_LOCKED"])
                    continue

                if cmd_prefix in ("-teamonly", "teamonly"):
                    CONFIG["AUTO_SKILL_TEAM_ONLY"] = not CONFIG.get("AUTO_SKILL_TEAM_ONLY", False)
                    invalidate_train_index_cache()
                    print("[+] 只扫描当前梯队：%s" % CONFIG["AUTO_SKILL_TEAM_ONLY"])
                    continue

                print("[!] 自动训练菜单未知命令：%s" % cmd_prefix)
                print("[*] 输入 -help 或 h 查看当前菜单。")
                continue

        except KeyboardInterrupt:
            print("\n[!] 请使用 -E 安全退出。")
