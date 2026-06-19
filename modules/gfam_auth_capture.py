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
SHARED_INDEX_FILE = ROOT_DIR / ".gfam_index_cache.json"
PID_FILE = ROOT_DIR / ".gfam_auth_capture.pid"
PROXY_PORT = 12335
CAPTURED = {"uid": "", "sign": ""}
INDEX_CACHED = {"ok": False}

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

def save_shared_index_cache(server, payload, source="auth_capture_game_Index/index"):
    if not isinstance(payload, dict) or not isinstance(payload.get("user_info"), dict):
        return
    try:
        SHARED_INDEX_FILE.write_text(json.dumps({
            "schema": "gfam_shared_index_cache_v1",
            "source": source,
            "server": server,
            "saved_at": int(time.time()),
            "payload": payload,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        if not INDEX_CACHED.get("ok"):
            print("[+] 已缓存游戏登录过程中返回的 Index/index，后续 factory/后台制造可优先复用。")
        INDEX_CACHED["ok"] = True
    except Exception:
        pass


def on_traffic(event_type, url, data):
    if str(event_type).upper() == "SYS_KEY_UPGRADE":
        CAPTURED["uid"] = str(data.get("uid") or "").strip()
        CAPTURED["sign"] = str(data.get("sign") or "").strip()
        print("\n[+] 已成功获取 UID / SIGN：")
        print("    UID  : %s" % CAPTURED["uid"])
        print("    SIGN : %s" % CAPTURED["sign"])
    if "Index/index" in str(url or "") and isinstance(data, dict) and isinstance(data.get("user_info"), dict):
        server = normalize_server(os.environ.get("GFAM_SELECTED_SERVER") or os.environ.get("GFAM_SERVER") or "SOP")
        save_shared_index_cache(server, data)

def main():
    server = normalize_server(os.environ.get("GFAM_SELECTED_SERVER") or os.environ.get("GFAM_SERVER") or "SOP")
    print("\n=========== 少女全自动 UID/SIGN 获取 ===========")
    print("当前服务器：%s" % server)
    print("说明：本步骤不主动请求 Index/index；若游戏登录过程自身返回 Index/index，会顺手缓存供后续模块复用。")
    print("请在代理启动后登录游戏，并等待进入指挥官主界面。")
    print("==============================================\n")
    if server not in SERVERS:
        print("[!] 当前 gflzirc 未找到服务器配置：%s" % server)
        print("[!] 可用服务器键：%s" % ", ".join(sorted(str(k) for k in SERVERS.keys())))
        return 1
    proxy = None
    try:
        # 写入 PID 文件，供 GUI 关闭时追踪并杀死此进程（包括子进程树）
        try:
            PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
        except Exception:
            pass
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
        try:
            PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        print("[*] 代理已停止，Windows 代理已恢复。")

if __name__ == "__main__":
    sys.exit(main())
