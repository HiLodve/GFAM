# -*- coding: utf-8 -*-
import os
import sys
import time
import json
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
GFLZIRC_CORE_DIR = ROOT_DIR / "libs" / "ZIRC" / "src" / "core"
if str(GFLZIRC_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(GFLZIRC_CORE_DIR))

from gflzirc import GFLProxy, set_windows_proxy, STATIC_KEY, SERVERS, DEFAULT_SIGN

AUTH_FILE = ROOT_DIR / ".gfam_auth.json"
PROXY_PORT = 12335
CAPTURED = {"uid": "", "sign": ""}

def normalize_server(value):
    cmd = str(value or "SOP").strip().upper().replace("_", "-")
    if cmd in ("1", "-1", "SOP"):
        return "SOP"
    if cmd in ("2", "-2", "RO635", "RO"):
        return "RO635"
    if cmd in ("3", "-3", "M4A1", "M4"):
        return "M4A1"
    if cmd in ("4", "-4", "M16"):
        return "M16"
    if cmd in ("5", "-5", "AR15", "AR-15"):
        return "AR-15"
    if cmd in ("6", "-6", "EN", "GLOBAL"):
        return "EN"
    return "SOP"

def on_traffic(event_type, url, data):
    if str(event_type).upper() == "SYS_KEY_UPGRADE":
        CAPTURED["uid"] = str(data.get("uid") or "").strip()
        CAPTURED["sign"] = str(data.get("sign") or "").strip()
        print("\n[+] 已成功获取 UID / SIGN：")
        print("    UID  : %s" % CAPTURED["uid"])
        print("    SIGN : %s" % CAPTURED["sign"])

def main():
    server = normalize_server(os.environ.get("GFAM_SELECTED_SERVER") or os.environ.get("GFAM_SERVER") or "SOP")
    print("\n=========== 少女全自动 UID/SIGN 获取 ===========")
    print("当前服务器：%s" % server)
    print("说明：本步骤只负责获取 UID/SIGN，不会请求 Index/index。")
    print("请在代理启动后登录游戏，并等待进入指挥官主界面。")
    print("==============================================\n")
    if server not in SERVERS:
        print("[!] 当前 gflzirc 未找到服务器配置：%s" % server)
        print("[!] 可用服务器键：%s" % ", ".join(sorted(str(k) for k in SERVERS.keys())))
        return 1
    proxy = None
    try:
        proxy = GFLProxy(PROXY_PORT, STATIC_KEY, on_traffic)
        proxy.start()
        set_windows_proxy(True, "127.0.0.1:%d" % PROXY_PORT)
        print("[*] 代理已启动，端口 %d。Windows 代理已设置。" % PROXY_PORT)
        print("[*] 请现在登录游戏。成功获取 UID/SIGN 后会自动保存。")
        print("[*] 按 Ctrl+C 可取消。")
        while not (CAPTURED.get("uid") and CAPTURED.get("sign") and CAPTURED.get("sign") != DEFAULT_SIGN):
            time.sleep(0.2)
        data = {"server": server, "uid": CAPTURED["uid"], "sign": CAPTURED["sign"], "captured_at": int(time.time())}
        AUTH_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print("[+] UID/SIGN 已保存到 GFAM 本地会话文件。")
        print("[+] 请确认游戏已进入指挥官主界面，返回 GFAM 菜单后即可选择功能模块。")
        return 0
    except KeyboardInterrupt:
        print("\n[!] 已取消 UID/SIGN 获取。")
        return 2
    finally:
        try:
            if proxy:
                proxy.stop()
        except Exception:
            pass
        try:
            set_windows_proxy(False)
        except Exception:
            pass
        print("[*] 代理已停止，Windows 代理已恢复。")

if __name__ == "__main__":
    sys.exit(main())
