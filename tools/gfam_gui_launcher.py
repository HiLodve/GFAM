# -*- coding: utf-8 -*-
"""GFAM staged graphical launcher with anime-style UI.

This launcher keeps GFAM's original command-line workflow, hides the backend
console window, and provides a two-stage GUI:
1) a compact startup/server window;
2) a full control panel after GFAM reaches the main menu.
"""
from __future__ import annotations

import os
import ast
import json
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

APP_TITLE = "少女全自动 GFAM - GUI Launcher"
START_TITLE = "GFAM 启动与服务器"
SERVERS = ["SOP", "RO635", "M4A1", "M16", "AR-15", "EN"]

MODULE_BUTTONS = [
    ("EPA 打捞", "epa"),
    ("13-4", "13-4"),
    ("A-10资源", "a10-resource"),
    ("训练资料/自动训练", "pick"),
    ("零元购 f2p", "f2p"),
    ("零元购 PR", "f2p_pr"),
    ("一键打捞 smart", "smart"),
    ("制造 factory", "factory"),
    ("灰域彩蛋", "greyzone"),
]

FACTORY_BUTTONS = [
    ("跟随模块制造", "__follow_factory_settings__"),
    ("查看/修改制造设置", "__factory_settings__"),
    ("人形自动快速建造", "__quick_doll__"),
    ("装备自动快速建造", "__quick_equip__"),
    ("人形词典 / 查保护ID", "__gun_dict__"),
]

# GUI-side summary for factory settings popup.  The backend module remains the
# source of truth; this only mirrors labels/resources so the settings can be
# shown in a structured popup instead of dumping -show output into the log.
FACTORY_STATE_FILE = ".gfam_factory_state.json"
EPA_STATE_FILE = ".gfam_epa_settings.json"
FACTORY_DOLL_FORMULAS_GUI = {
    "handgun": {"name": "手枪", "resources": {"mp": 130, "ammo": 130, "mre": 130, "part": 30}},
    "smg": {"name": "冲锋枪", "resources": {"mp": 400, "ammo": 400, "mre": 100, "part": 200}},
    "rifle": {"name": "步枪", "resources": {"mp": 400, "ammo": 100, "mre": 400, "part": 200}},
    "ar": {"name": "突击步枪", "resources": {"mp": 100, "ammo": 400, "mre": 400, "part": 200}},
    "mg": {"name": "机枪", "resources": {"mp": 800, "ammo": 800, "mre": 100, "part": 400}},
}
FACTORY_EQUIP_FORMULAS_GUI = {
    "optic": {"name": "光学瞄具", "resources": {"mp": 140, "ammo": 10, "mre": 110, "part": 10}},
    "holo": {"name": "全息瞄具", "resources": {"mp": 140, "ammo": 10, "mre": 110, "part": 10}},
    "red_dot": {"name": "红点瞄具", "resources": {"mp": 140, "ammo": 10, "mre": 110, "part": 10}},
    "night": {"name": "夜战装备", "resources": {"mp": 70, "ammo": 10, "mre": 150, "part": 30}},
    "suppressor": {"name": "消音器", "resources": {"mp": 150, "ammo": 50, "mre": 50, "part": 50}},
    "ap": {"name": "穿甲弹", "resources": {"mp": 10, "ammo": 150, "mre": 90, "part": 100}},
    "status": {"name": "状态弹", "resources": {"mp": 180, "ammo": 180, "mre": 10, "part": 50}},
    "hv": {"name": "高速弹", "resources": {"mp": 10, "ammo": 230, "mre": 120, "part": 80}},
    "shotgun": {"name": "散弹", "resources": {"mp": 30, "ammo": 150, "mre": 30, "part": 130}},
    "exo": {"name": "外骨骼", "resources": {"mp": 100, "ammo": 80, "mre": 10, "part": 100}},
    "armor": {"name": "防弹插板", "resources": {"mp": 50, "ammo": 50, "mre": 100, "part": 100}},
    "ammo_box": {"name": "弹链箱", "resources": {"mp": 30, "ammo": 30, "mre": 30, "part": 200}},
    "cape": {"name": "伪装披风", "resources": {"mp": 180, "ammo": 20, "mre": 200, "part": 20}},
    "mixed": {"name": "装备混合", "resources": {"mp": 150, "ammo": 150, "mre": 150, "part": 150}},
    "backup_sight": {"name": "备用瞄具", "resources": {"mp": 180, "ammo": 65, "mre": 65, "part": 65}},
    "chip": {"name": "芯片", "resources": {"mp": 170, "ammo": 120, "mre": 50, "part": 50}},
    "special_ap": {"name": "特殊穿甲弹", "resources": {"mp": 10, "ammo": 300, "mre": 10, "part": 10}},
    "bipod": {"name": "固定脚架", "resources": {"mp": 300, "ammo": 10, "mre": 10, "part": 200}},
    "tube": {"name": "收缩管", "resources": {"mp": 80, "ammo": 220, "mre": 80, "part": 80}},
    "rangefinder": {"name": "测距仪", "resources": {"mp": 100, "ammo": 250, "mre": 150, "part": 170}},
}
FACTORY_RESOURCE_LABELS_GUI = {"mp": "人力", "ammo": "弹药", "mre": "口粮", "part": "零件"}


MODULE_WINDOWS = {
    "epa": {
        "entry": "1",
        "title": "EPA 打捞",
        "desc": "EPA 打捞/练级模块窗口。快捷项已收敛到一个设置弹窗，减少误触与命令冗余。",
        "commands": [
            ("EPA 设置", "__epa_settings__"), ("安全停止 -q", "-q"),
        ],
    },
    "13-4": {
        "entry": "2",
        "title": "13-4",
        "desc": "13-4 练级/资源模块窗口。可选择五战练级或双单人四项资源模式；返回请使用下方返回主界面。",
        "commands": [
            ("13-4 设置", "__134_settings__"), ("运行 -r", "-r"), ("安全停止 -q", "-q"), ("返回主菜单", "-E"),
        ],
    },
    "a10-resource": {
        "entry": "3",
        "title": "A-10 资源",
        "desc": "A-10 四项资源模块窗口。当前基准保留 pending80 分批拆解修复。",
        "commands": [
            ("重新进入 A-10", "3"), ("开始获取 -r", "-r"), ("当前轮后停 -q", "-q"), ("清理战役 -abort", "-abort"),
            ("发送回车", "\n"), ("返回主菜单", "-E"),
        ],
    },
    "pick": {
        "entry": "4",
        "title": "训练资料 / 自动训练",
        "desc": "训练资料与自动训练模块窗口。可进入获取资料或自动训练子菜单。",
        "commands": [
            ("重新进入 pick", "4"), ("获取资料菜单 -pick", "-pick"), ("自动训练菜单 -train", "-train"), ("状态 -status", "-status"),
            ("获取资料运行 -r", "-r"), ("自动训练统计 -count", "-count"), ("训练运行 -run", "-run"), ("刷新统计 -refresh", "-refresh"),
            ("安全停止 -q", "-q"), ("Micro停止 -Q", "-Q"), ("发送回车", "\n"), ("返回主菜单", "-E"),
        ],
    },
    "f2p": {
        "entry": "5",
        "title": "零元购 f2p",
        "desc": "零元购 f2p 模块窗口。",
        "commands": [("重新进入 f2p", "5"), ("运行 -r", "-r"), ("Macro停止 -q", "-q"), ("Micro停止 -Q", "-Q"), ("发送回车", "\n"), ("返回主菜单", "-E")],
    },
    "f2p_pr": {
        "entry": "6",
        "title": "零元购 PR",
        "desc": "零元购 PR 模块窗口。",
        "commands": [("重新进入 PR", "6"), ("运行 -r", "-r"), ("Macro停止 -q", "-q"), ("Micro停止 -Q", "-Q"), ("发送回车", "\n"), ("返回主菜单", "-E")],
    },
    "smart": {
        "entry": "7",
        "title": "一键打捞 smart",
        "desc": "smart 一键打捞模块窗口。先设置计划类型，自动生成计划后再运行。",
        "commands": [
            ("Smart 设置", "__smart_settings__"), ("安全停止 -q", "-q"),
        ],
    },
    "factory": {
        "entry": "8",
        "title": "制造 factory",
        "desc": "制造自动化模块窗口。跟随其它模块自动制造、保护开关和自动快速建造都在这里操作。",
        "commands": [("重新进入 factory", "8")] + FACTORY_BUTTONS,
    },
    "greyzone": {
        "entry": "9",
        "title": "灰域彩蛋",
        "desc": "灰域彩蛋模块窗口。",
        "commands": [
            ("重新进入灰域", "9"), ("开始 -r", "-r"), ("安全停止 -q", "-q"), ("四项票券 -ticket2", "-ticket2"),
            ("探查票券 -ticket1", "-ticket1"), ("清理战役 -abort", "-abort"), ("发送回车", "\n"), ("返回主菜单", "-E"),
        ],
    },
}

MODULE_READY_MARKERS_BY_KEY = {
    # Use module-menu/prompt-specific markers.  Do not use generic names like
    # "13-4" because those also appear in the GFAM main menu and caused shortcut
    # commands to be sent to the wrong menu context.
    "epa": ["GFAM-EPA>", "EPA MENU", "编队模式", "-team", "-single", "GFL-EPA>", "GFL-EPA(模式)>"],
    "13-4": ["GFAM-13", "13-4 MENU", "13-4 模式选择", "-134train", "-134      :", "GFL-13-4>", "GFL-13-4(模式)>"],
    "a10-resource": ["GFAM-A10>", "A-10 RESOURCE", "A-10 四项资源获取状态", "-abort"],
    "pick": ["pick_and_train", "训练资料 MENU", "自动训练 MENU", "GFL-PICK", "GFL-TRAIN", "GFL-MAIN>", "GFL-CAPTURE>"],
    "f2p": ["GFAM-F2P>", "f2p MENU", "零元购 f2p", "GFL-零元购>"],
    "f2p_pr": ["GFAM-F2P-PR>", "f2p_pr MENU", "零元购 PR", "GFL-零元购>"],
    "smart": ["GFAM-SMART>", "smart MENU", "一键打捞 MENU", "GFL-EPA>", "一键打捞计划", "SMART_EPA_PLAN_MODE"],
    "factory": ["制造自动化 MENU", "gfam_factory_config", "-testdoll", "-testequip", "-testdollgui", "-testequipgui", "GFAM-制造>"],
    "greyzone": ["GFAM-GREY", "greyzone MENU", "灰域自动"],
}


# Module-specific sequence used when the user clicks "返回主界面" from a module
# window.  Long-running modules need a safe stop command first; otherwise the UI
# can return to the main window while the backend module is still farming.
MODULE_EXIT_SEQUENCES_BY_KEY = {
    "epa": ["-q", "-E"],
    "13-4": ["-q", "-E"],
    "a10-resource": ["-q", "-E"],
    "pick": ["-q", "-E"],
    "f2p": ["-q", "-E"],
    "f2p_pr": ["-q", "-E"],
    "smart": ["-q", "-E"],
    "factory": ["-E"],
    "greyzone": ["-q", "-E"],
}
MODULE_EXIT_STEP_DELAY_MS = 450

MODULE_ENTRY_DELAY_MS = 2200
MODULE_SWITCH_BACK_DELAY_MS = 900


MENU_READY_MARKERS = [
    "提示：选择服务器后会先统一获取 UID/SIGN",
    "提示：进入某个模块后，该模块会接管命令行",
    "制造自动化：",
]

# Visual palette: close to the purple/white anime mockup the user liked.
BG = "#F7F2FF"
BG2 = "#EEE6FF"
CARD = "#FFFFFF"
CARD_BORDER = "#D8CCF5"
TEXT = "#251D3A"
MUTED = "#6F6685"
ACCENT = "#6E47C7"
ACCENT_DARK = "#4D32A0"
ACCENT_SOFT = "#BFA8FF"
SUCCESS = "#25A45A"
WARN = "#D58A00"
DANGER = "#D94A4A"
LOG_BG = "#FBFAFF"
LOG_FG = "#241B35"

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
ANSI_SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")
ANSI_NON_SGR_RE = re.compile(r"\x1b\[(?![0-9;]*m)[0-?]*[ -/]*[@-~]")
ANSI_TAG_COLORS = {
    "ansi_30": "#5A5368",
    "ansi_31": DANGER,
    "ansi_32": SUCCESS,
    "ansi_33": WARN,
    "ansi_34": "#336DCC",
    "ansi_35": ACCENT_DARK,
    "ansi_36": "#008C95",
    "ansi_37": LOG_FG,
    "ansi_90": "#8A8399",
    "ansi_91": DANGER,
    "ansi_92": SUCCESS,
    "ansi_93": WARN,
    "ansi_94": "#2F73E0",
    "ansi_95": ACCENT,
    "ansi_96": "#0099A8",
    "ansi_97": TEXT,
    "log_gui": ACCENT_DARK,
    "log_success": SUCCESS,
    "log_warn": WARN,
    "log_error": DANGER,
    "log_muted": MUTED,
}


def find_root() -> Path:
    """Return the directory that contains GFAM runtime files."""
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates = [
            exe_dir,
            Path(getattr(sys, "_MEIPASS", exe_dir)).resolve(),
            exe_dir / "_internal",
        ]
        for cand in candidates:
            if (cand / "run_windows.bat").exists() or (cand / "main.js").exists():
                return cand
        return exe_dir
    return Path(__file__).resolve().parents[1]


def find_resource_file(root_dir: Path, *parts: str) -> Path | None:
    """Find an included resource from either the GFAM root or PyInstaller _MEIPASS."""
    candidates = [root_dir]
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.extend([
            Path(getattr(sys, "_MEIPASS", exe_dir)).resolve(),
            exe_dir / "_internal",
            exe_dir,
        ])
    for base in candidates:
        path = base.joinpath(*parts)
        if path.exists():
            return path
    return None


def set_windows_app_id() -> None:
    """Make Windows taskbar/titlebar consistently use GFAM's icon when possible."""
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("GFAM.GUI.Launcher.v15.clean")
    except Exception:
        pass


class GFAMGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.root_dir = find_root()
        self.process: subprocess.Popen[str] | None = None
        self.reader_threads: list[threading.Thread] = []
        self.output_queue: queue.Queue[str] = queue.Queue()
        self.server_var = tk.StringVar(value="SOP")
        self.command_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="未启动")
        self.start_status_var = tk.StringVar(value="选择服务器后点击启动")
        self.autoscroll_var = tk.BooleanVar(value=True)
        self.compact_log_var = tk.BooleanVar(value=True)
        self.log_color_var = tk.BooleanVar(value=True)
        self._last_log_separator = False
        # Lightweight GUI-side EPA prompt phase.  This is used only to route
        # button click command sequences safely; backend EPA remains the source
        # of truth for actual run state.
        self.epa_gui_phase = "unknown"
        self.main_ui_shown = False
        self.auto_server_sent = False
        self.log_history: list[str] = []
        self.log_history_segments: list[tuple[str, str | None]] = []
        self.log_text: tk.Text | None = None
        self.step_labels: dict[str, tk.Label] = {}
        self.module_window: tk.Toplevel | None = None
        self.current_module_key: str | None = None
        self.current_module_title: str | None = None
        self.module_entering = False
        self.module_ready = False
        self.pending_module_cmds: list[str] = []
        self.module_command_buttons: list[ttk.Button] = []
        self.module_status_var = tk.StringVar(value="模块未进入")
        self._smart_settings_applied = False
        # Factory quick-build prompt state.  Clicking the quick-build button asks
        # the user to type a count into the normal command box, then the GUI sends
        # -testdoll N or -testequip N to the factory module.
        self.pending_factory_quick_cmd: str | None = None
        self.gun_dict_window: tk.Toplevel | None = None
        self.gun_dict_entries: list[dict[str, object]] | None = None
        self.factory_settings_window: tk.Toplevel | None = None
        self.factory_settings_body: tk.Frame | None = None
        self.follow_factory_window: tk.Toplevel | None = None
        self.follow_factory_body: tk.Frame | None = None
        self.quick_build_window: tk.Toplevel | None = None
        # Backend context tracking.  Module entry commands must only be sent when
        # the underlying GFAM process is actually waiting at the main menu.  Some
        # modules print "Press any key to return..." after they exit; if a module
        # number is sent at that point it is consumed as the "any key" instead of
        # selecting the next module.
        self.backend_menu_ready = False
        self.pending_module_to_open: str | None = None
        self.waiting_press_any_key = False
        self.auto_press_any_key_armed = False
        self._mascot_img: tk.PhotoImage | None = None
        self._mascot_small: tk.PhotoImage | None = None
        self._gfam_icon_img: tk.PhotoImage | None = None
        self._start_mascot_img: tk.PhotoImage | None = None
        self._header_icon_img: tk.PhotoImage | None = None
        self._icon_card_img: tk.PhotoImage | None = None

        set_windows_app_id()
        self._setup_style()
        self._load_images()
        self.title(START_TITLE)
        self.geometry("640x420")
        self.minsize(600, 390)
        self.configure(bg=BG)
        self._apply_icon()
        self._build_start_ui()
        self.after(30, self._drain_output)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- style / images ----------
    def _setup_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        default_font = ("Microsoft YaHei UI", 10)
        title_font = ("Microsoft YaHei UI", 16, "bold")
        self.option_add("*Font", default_font)
        style.configure("GFAM.TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("GFAM.TLabel", background=BG, foreground=TEXT)
        style.configure("Card.TLabel", background=CARD, foreground=TEXT)
        style.configure("Muted.TLabel", background=CARD, foreground=MUTED)
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=title_font)
        style.configure("Subtitle.TLabel", background=BG, foreground=MUTED)
        style.configure("GFAM.TLabelframe", background=BG, bordercolor=CARD_BORDER, relief="solid")
        style.configure("GFAM.TLabelframe.Label", background=BG, foreground=ACCENT_DARK, font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Card.TLabelframe", background=CARD, bordercolor=CARD_BORDER, relief="solid")
        style.configure("Card.TLabelframe.Label", background=CARD, foreground=ACCENT_DARK, font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Accent.TButton", background=ACCENT, foreground="white", bordercolor=ACCENT_DARK, focusthickness=1, focuscolor=ACCENT_DARK, padding=(12, 6))
        style.map("Accent.TButton", background=[("active", ACCENT_DARK), ("disabled", "#BEB6CC")], foreground=[("disabled", "#F2F2F2")])
        style.configure("Soft.TButton", background="#EFE8FF", foreground=ACCENT_DARK, bordercolor=CARD_BORDER, padding=(10, 5))
        style.map("Soft.TButton", background=[("active", "#E3D7FF")])
        style.configure("Danger.TButton", background="#FFEDED", foreground=DANGER, bordercolor="#F0B5B5", padding=(10, 5))
        style.map("Danger.TButton", background=[("active", "#FFD9D9")])
        style.configure("GFAM.TCheckbutton", background=BG, foreground=TEXT)
        style.configure("GFAM.TRadiobutton", background=CARD, foreground=TEXT)
        style.map("GFAM.TRadiobutton", background=[("active", CARD)])
        style.configure("GFAM.TCombobox", padding=(5, 4))

    def _load_images(self) -> None:
        """Load pre-resized UI images.

        Avoid PhotoImage.subsample for the large mascot because nearest-neighbor
        scaling makes the anime artwork look pixelated. The build pack includes
        smooth pre-rendered PNGs created from the approved poster/icon style.
        """
        def load_png(name: str) -> tk.PhotoImage | None:
            path = find_resource_file(self.root_dir, "assets", name)
            if not path:
                return None
            try:
                return tk.PhotoImage(file=str(path))
            except Exception:
                return None

        self._start_mascot_img = load_png("gfam_start_mascot.png")
        self._header_icon_img = load_png("gfam_header_icon.png")
        self._icon_card_img = load_png("gfam_icon_card.png")
        self._mascot_small = load_png("gfam_icon_48.png")
        self._mascot_img = self._start_mascot_img or self._icon_card_img or self._mascot_small

    def _apply_icon(self) -> None:
        icon_path = find_resource_file(self.root_dir, "assets", "gfam.ico")
        preview_path = find_resource_file(self.root_dir, "assets", "gfam_icon_32.png") or find_resource_file(self.root_dir, "assets", "gfam_taskbar_256.png") or find_resource_file(self.root_dir, "assets", "gfam_icon_256.png") or find_resource_file(self.root_dir, "assets", "gfam_icon_preview.png")
        try:
            if icon_path:
                self.iconbitmap(default=str(icon_path))
        except Exception:
            pass
        try:
            if preview_path:
                self._gfam_icon_img = tk.PhotoImage(file=str(preview_path))
                self.iconphoto(True, self._gfam_icon_img)
        except Exception:
            pass

    def _apply_window_icon(self, win) -> None:
        try:
            icon_path = find_resource_file(self.root_dir, "assets", "gfam.ico")
            if icon_path:
                win.iconbitmap(default=str(icon_path))
            if self._gfam_icon_img:
                win.iconphoto(True, self._gfam_icon_img)
        except Exception:
            pass

    def _card(self, parent: tk.Widget, **pack_kwargs) -> tk.Frame:
        frame = tk.Frame(parent, bg=CARD, highlightbackground=CARD_BORDER, highlightcolor=CARD_BORDER, highlightthickness=1, bd=0)
        if pack_kwargs:
            frame.pack(**pack_kwargs)
        return frame

    def _pill_label(self, parent: tk.Widget, text: str, bg: str = ACCENT, fg: str = "white") -> tk.Label:
        label = tk.Label(parent, text=text, bg=bg, fg=fg, font=("Microsoft YaHei UI", 10, "bold"), padx=12, pady=4)
        return label

    def _section_title(self, parent: tk.Widget, text: str) -> tk.Label:
        label = tk.Label(parent, text=text, bg=CARD, fg=ACCENT_DARK, font=("Microsoft YaHei UI", 10, "bold"))
        label.pack(anchor=tk.W, padx=10, pady=(8, 4))
        return label

    def _poster_feature(self, parent: tk.Widget, icon: str, title: str, desc: str) -> None:
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill=tk.X, padx=14, pady=5)
        tk.Label(row, text=icon, bg=CARD, fg=ACCENT_DARK, font=("Segoe UI Emoji", 16)).pack(side=tk.LEFT, padx=(0, 10))
        col = tk.Frame(row, bg=CARD)
        col.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(col, text=title, bg=CARD, fg=ACCENT_DARK, font=("Microsoft YaHei UI", 10, "bold")).pack(anchor=tk.W)
        tk.Label(col, text=desc, bg=CARD, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(anchor=tk.W)

    # ---------- UI ----------
    def _clear_widgets(self) -> None:
        for child in list(self.winfo_children()):
            child.destroy()
        self.log_text = None
        self.step_labels = {}

    def _build_start_ui(self) -> None:
        self._clear_widgets()
        self.main_ui_shown = False
        self.title(START_TITLE)
        self.geometry("860x500")
        self.minsize(820, 470)
        self.configure(bg=BG)

        outer = tk.Frame(self, bg=BG, padx=18, pady=16)
        outer.pack(fill=tk.BOTH, expand=True)

        header = tk.Frame(outer, bg=BG)
        header.pack(fill=tk.X, pady=(0, 12))
        if self._header_icon_img:
            tk.Label(header, image=self._header_icon_img, bg=BG).pack(side=tk.LEFT, padx=(0, 12))
        title_box = tk.Frame(header, bg=BG)
        title_box.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(title_box, text="GFAM 启动与服务器", bg=BG, fg=TEXT, font=("Microsoft YaHei UI", 22, "bold")).pack(anchor=tk.W)
        tk.Label(title_box, text="先完成服务器与环境准备，完成后自动进入完整主界面", bg=BG, fg=MUTED, font=("Microsoft YaHei UI", 10)).pack(anchor=tk.W, pady=(2, 0))

        body = tk.Frame(outer, bg=BG)
        body.pack(fill=tk.BOTH, expand=True)

        left = self._card(body)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=(0, 12))
        left.configure(width=310)
        mascot_wrap = tk.Frame(left, bg=CARD)
        mascot_wrap.pack(fill=tk.X, padx=12, pady=(12, 6))
        if self._start_mascot_img:
            tk.Label(mascot_wrap, image=self._start_mascot_img, bg=CARD).pack(anchor=tk.CENTER)
        elif self._icon_card_img:
            tk.Label(mascot_wrap, image=self._icon_card_img, bg=CARD).pack(anchor=tk.CENTER, pady=18)
        tk.Label(left, text="少女全自动 GFAM", bg=CARD, fg=ACCENT_DARK, font=("Microsoft YaHei UI", 13, "bold")).pack(pady=(0, 2))
        tk.Label(left, text="选择服务器并完成准备后进入主界面", bg=CARD, fg=MUTED, justify=tk.CENTER, font=("Microsoft YaHei UI", 9)).pack(padx=12, pady=(0, 14))

        right = tk.Frame(body, bg=BG)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        server_card = self._card(right, fill=tk.X, pady=(0, 10))
        self._section_title(server_card, "选择服务器")
        row = tk.Frame(server_card, bg=CARD)
        row.pack(fill=tk.X, padx=14, pady=(2, 12))
        tk.Label(row, text="服务器", bg=CARD, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(anchor=tk.W)
        input_row = tk.Frame(row, bg=CARD)
        input_row.pack(fill=tk.X, pady=(4, 0))
        server_box = ttk.Combobox(input_row, textvariable=self.server_var, values=SERVERS, width=18, state="readonly", style="GFAM.TCombobox")
        server_box.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10), ipady=2)
        ttk.Button(input_row, text="启动 GFAM", style="Accent.TButton", command=lambda: self.start_gfam(auto_send_server=True)).pack(side=tk.LEFT)
        row2 = tk.Frame(server_card, bg=CARD)
        row2.pack(fill=tk.X, padx=14, pady=(0, 14))
        ttk.Button(row2, text="发送服务器", style="Soft.TButton", command=lambda: self.send_command(self.server_var.get())).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(row2, text="获取 UID/SIGN", style="Soft.TButton", command=lambda: self.send_command("auth")).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(row2, text="退出", style="Danger.TButton", command=self.on_close).pack(side=tk.RIGHT)

        status_card = self._card(right, fill=tk.X, pady=(0, 10))
        self._section_title(status_card, "服务器状态")
        steps = [
            ("server", "等待服务器选择"),
            ("process", "等待后台进程启动"),
            ("auth", "等待 UID/SIGN 准备"),
            ("ready", "等待进入 GFAM 主菜单"),
        ]
        for key, text in steps:
            lbl = tk.Label(status_card, text=f"○ {text}", bg=CARD, fg=MUTED, anchor=tk.W, font=("Microsoft YaHei UI", 10))
            lbl.pack(fill=tk.X, padx=18, pady=3)
            self.step_labels[key] = lbl
        tk.Label(status_card, textvariable=self.start_status_var, bg=CARD, fg=SUCCESS, font=("Microsoft YaHei UI", 10, "bold")).pack(anchor=tk.W, padx=18, pady=(8, 14))

        log_card = self._card(right, fill=tk.BOTH, expand=True)
        self._section_title(log_card, "启动日志")
        log_inner = tk.Frame(log_card, bg=CARD)
        log_inner.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))
        self.log_text = tk.Text(log_inner, wrap=tk.WORD, font=("Consolas", 9), undo=False, height=5, bg=LOG_BG, fg=LOG_FG, relief=tk.FLAT)
        yscroll = ttk.Scrollbar(log_inner, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=yscroll.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._restore_log_text()

        bottom = tk.Frame(outer, bg=BG)
        bottom.pack(fill=tk.X, pady=(12, 0))
        self.command_entry = ttk.Entry(bottom, textvariable=self.command_var)
        self.command_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8), ipady=2)
        self.command_entry.bind("<Return>", lambda _e: self.send_entry())
        ttk.Button(bottom, text="发送", style="Accent.TButton", command=self.send_entry).pack(side=tk.LEFT, padx=3)
        ttk.Button(bottom, text="完整界面", style="Soft.TButton", command=self._show_main_ui).pack(side=tk.LEFT, padx=3)
        ttk.Button(bottom, text="打开目录", style="Soft.TButton", command=self.open_root_dir).pack(side=tk.LEFT, padx=3)

        if not self.log_history:
            self._append_log("[GUI] GFAM 分级启动器已打开。\n")
            self._append_log(f"[GUI] Project folder: {self.root_dir}\n")
            self._append_log("[GUI] 请选择服务器后点击“启动 GFAM”。\n")

    def _mark_step(self, key: str, text: str | None = None, ok: bool = True) -> None:
        lbl = self.step_labels.get(key)
        if not lbl:
            return
        if text is None:
            text = lbl.cget("text").lstrip("○●✓ ")
        prefix = "✓" if ok else "●"
        lbl.configure(text=f"{prefix} {text}", fg=SUCCESS if ok else ACCENT_DARK, font=("Microsoft YaHei UI", 10, "bold"))

    def _show_main_ui(self) -> None:
        if self.main_ui_shown:
            return
        self.main_ui_shown = True
        self.title(APP_TITLE)
        self.geometry("1160x760")
        self.minsize(980, 620)
        self.configure(bg=BG)
        self._clear_widgets()
        self._build_main_ui()
        self._append_log("\n[GUI] 已切换到 GFAM 完整操作界面。\n")

    def _make_button_grid(self, parent: tk.Widget, buttons: list[tuple[str, str]], columns: int) -> None:
        for i, (label, cmd) in enumerate(buttons):
            ttk.Button(parent, text=label, style="Soft.TButton", command=lambda c=cmd: self.send_command(c)).grid(row=i // columns, column=i % columns, sticky="ew", padx=4, pady=4)
        for i in range(columns):
            parent.columnconfigure(i, weight=1)

    def _make_module_grid(self, parent: tk.Widget, buttons: list[tuple[str, str]], columns: int) -> None:
        for i, (label, cmd) in enumerate(buttons):
            ttk.Button(parent, text=label, style="Soft.TButton", command=lambda c=cmd: self._open_module_window(c)).grid(row=i // columns, column=i % columns, sticky="ew", padx=4, pady=4)
        for i in range(columns):
            parent.columnconfigure(i, weight=1)

    def _open_module_window(self, module_cmd: str) -> None:
        """Open a module window and enter the corresponding GFAM module safely.

        The backend GFAM process has several intermediate states: module running,
        module final statistics, "Press any key" wrapper prompt, and finally the
        GFAM main menu.  Module entry numbers must be sent only after the main
        menu is ready; otherwise the number can be consumed by the wrapper prompt
        and following shortcut commands will land in the wrong menu.
        """
        spec = MODULE_WINDOWS.get(module_cmd, {"title": module_cmd, "entry": module_cmd, "desc": "GFAM 模块窗口。", "commands": [("发送回车", "\n"), ("返回主菜单", "-E")]})

        # Switching from one module to another: request a safe return first, then
        # wait for the real GFAM main menu before sending the new entry number.
        if self.module_window and self.module_window.winfo_exists() and self.current_module_key and self.current_module_key != module_cmd:
            old_key = self.current_module_key
            old_title = self.current_module_title or old_key
            seq = MODULE_EXIT_SEQUENCES_BY_KEY.get(old_key, ["-E"])
            self.pending_module_to_open = module_cmd
            self.backend_menu_ready = False
            self._append_log(f"\n[GUI] 正在从 {old_title} 切换到 {spec.get('title', module_cmd)}，先安全退出当前模块：{' -> '.join(seq)}。\n")
            if self.waiting_press_any_key:
                self._append_log("[GUI] 当前模块已在等待返回主菜单，发送回车完成返回。\n")
                self.send_raw("\n")
            else:
                for i, cmd in enumerate(seq):
                    self.after(i * MODULE_EXIT_STEP_DELAY_MS, lambda c=cmd: self._send_command_if_running(c))
            try:
                self.module_window.destroy()
            except Exception:
                pass
            self.module_window = None
            self.current_module_key = None
            self.current_module_title = None
            self.module_entering = False
            self.module_ready = False
            self.pending_module_cmds.clear()
            # Keep the main window hidden while waiting; it will re-open the target
            # module automatically after the main-menu marker is detected.
            return

        self.current_module_key = module_cmd
        self.current_module_title = spec.get("title", module_cmd)
        if module_cmd == "epa":
            self.epa_gui_phase = "unknown"
        self.module_entering = True
        self.module_ready = False
        self._smart_settings_applied = False
        self.pending_module_cmds.clear()
        self.module_status_var.set("正在进入模块，请稍候...")
        self._show_module_window(module_cmd)
        self.withdraw()
        self.after(150, lambda m=module_cmd: self._send_module_entry_command(m))

    def _send_module_entry_command(self, module_cmd: str) -> None:
        spec = MODULE_WINDOWS.get(module_cmd, {})
        entry_cmd = str(spec.get("entry") or module_cmd)
        title = spec.get("title", module_cmd)
        self.module_entering = True
        self.module_ready = False
        self._set_module_buttons_enabled(False)
        self.module_status_var.set(f"等待 GFAM 主菜单就绪后进入 {title}...")

        if not self.process or self.process.poll() is not None:
            self.pending_module_to_open = module_cmd
            self._append_log(f"\n[GUI] GFAM 未运行，已暂存模块入口：{title}。\n")
            return

        if not self.backend_menu_ready:
            self.pending_module_to_open = module_cmd
            self._append_log(f"\n[GUI] 正在等待 GFAM 主菜单就绪，再进入模块：{title}。\n")
            return

        self.pending_module_to_open = None
        self.backend_menu_ready = False
        self.waiting_press_any_key = False
        self.auto_press_any_key_armed = False
        self.module_status_var.set(f"正在进入 {title}，等待模块菜单准备...")
        self._append_log(f"\n[GUI] 正在进入模块：{title}，发送入口命令 {entry_cmd}。\n")
        self.send_command(entry_cmd, auto_start=False)
        # Fallback: some modules do not print a distinctive ready marker quickly.
        self.after(MODULE_ENTRY_DELAY_MS, lambda m=module_cmd: self._mark_module_ready(m, reason="timeout"))

    def _mark_module_ready(self, module_cmd: str | None = None, reason: str = "detected") -> None:
        if module_cmd and self.current_module_key and module_cmd != self.current_module_key:
            return
        if not self.current_module_key:
            return
        if self.module_ready:
            return
        self.module_entering = False
        self.module_ready = True
        title = self.current_module_title or self.current_module_key
        if reason == "timeout":
            self.module_status_var.set(f"{title} 已进入或等待输入（延时放行）")
            self._append_log(f"[GUI] 模块 {title} 未检测到明确菜单标记，已按延时放行快捷按钮。\n")
        else:
            self.module_status_var.set(f"{title} 已准备")
            self._append_log(f"[GUI] 已检测到 {title} 模块输出，快捷按钮已启用。\n")
        self._set_module_buttons_enabled(True)
        self._flush_pending_module_cmds()

    def _set_module_buttons_enabled(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        for btn in list(getattr(self, "module_command_buttons", [])):
            try:
                btn.configure(state=state)
            except Exception:
                pass

    def _flush_pending_module_cmds(self) -> None:
        if not self.pending_module_cmds:
            return
        queued = list(self.pending_module_cmds)
        self.pending_module_cmds.clear()
        self._append_log(f"[GUI] 正在发送进入模块期间排队的 {len(queued)} 条命令。\n")
        delay = 0
        for cmd in queued:
            delay += 180
            self.after(delay, lambda c=cmd: self.send_command(c, auto_start=False))

    def _show_module_window(self, module_cmd: str) -> None:
        spec = MODULE_WINDOWS.get(module_cmd, {"title": module_cmd, "desc": "GFAM 模块窗口。", "commands": [("发送回车", "\n"), ("返回主菜单", "-E")]})
        title = spec.get("title", module_cmd)
        if self.module_window and self.module_window.winfo_exists():
            self.module_window.destroy()
        try:
            self.withdraw()
        except Exception:
            pass
        win = tk.Toplevel(self)
        self.module_window = win
        win.title(f"GFAM - {title}")
        # 模块窗口需要给“手动命令输入区”保留固定高度，避免日志区挤压底部按钮。
        win.geometry("1120x760")
        win.minsize(960, 660)
        win.configure(bg=BG)
        self._apply_window_icon(win)
        win.protocol("WM_DELETE_WINDOW", self._return_from_module)

        outer = tk.Frame(win, bg=BG, padx=12, pady=12)
        outer.pack(fill=tk.BOTH, expand=True)

        header = self._card(outer, fill=tk.X, pady=(0, 10))
        hrow = tk.Frame(header, bg=CARD)
        hrow.pack(fill=tk.X, padx=12, pady=10)
        if self._mascot_small:
            tk.Label(hrow, image=self._mascot_small, bg=CARD).pack(side=tk.LEFT, padx=(0, 10))
        title_col = tk.Frame(hrow, bg=CARD)
        title_col.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(title_col, text=title, bg=CARD, fg=TEXT, font=("Microsoft YaHei UI", 17, "bold")).pack(anchor=tk.W)
        tk.Label(title_col, text=spec.get("desc", "GFAM 模块窗口。"), bg=CARD, fg=MUTED).pack(anchor=tk.W)
        tk.Label(hrow, textvariable=self.status_var, bg=CARD, fg=SUCCESS, font=("Microsoft YaHei UI", 10, "bold")).pack(side=tk.RIGHT, padx=10)
        tk.Label(hrow, textvariable=self.module_status_var, bg=CARD, fg=ACCENT_DARK, font=("Microsoft YaHei UI", 10, "bold")).pack(side=tk.RIGHT, padx=10)
        tk.Checkbutton(hrow, text="彩色日志", variable=self.log_color_var, bg=CARD, fg=TEXT, selectcolor=CARD, activebackground=CARD, activeforeground=TEXT, command=self._restore_log_text).pack(side=tk.RIGHT, padx=(0, 8))
        tk.Checkbutton(hrow, text="精简日志", variable=self.compact_log_var, bg=CARD, fg=TEXT, selectcolor=CARD, activebackground=CARD, activeforeground=TEXT).pack(side=tk.RIGHT, padx=(0, 8))

        quick = self._card(outer, fill=tk.X, pady=(0, 8))
        self._section_title(quick, f"{title} 快捷命令")
        qgrid = tk.Frame(quick, bg=CARD)
        qgrid.pack(fill=tk.X, padx=10, pady=(0, 10))
        raw_commands = list(spec.get("commands", []))
        # The module window has a dedicated "返回主界面" button below.  Do not
        # duplicate return-to-main buttons in the shortcut grid; direct -E is
        # unsafe for long-running modules because the backend may keep farming.
        commands = [(label, cmd) for (label, cmd) in raw_commands if cmd != "-E"]
        self.module_command_buttons = []
        for i, (label, cmd) in enumerate(commands):
            style = "Danger.TButton" if "关闭" in label else "Soft.TButton"
            btn = ttk.Button(qgrid, text=label, style=style, command=lambda c=cmd: self._module_send_command(c))
            btn.grid(row=i // 4, column=i % 4, sticky="ew", padx=4, pady=4)
            if cmd != "\n":
                try:
                    btn.configure(state=tk.DISABLED)
                except Exception:
                    pass
                self.module_command_buttons.append(btn)
        for i in range(4):
            qgrid.columnconfigure(i, weight=1)

        # 手动命令输入区放在日志区上方，固定显示，不再放在窗口最底部被挤压。
        command_card = self._card(outer, fill=tk.X, pady=(0, 8))
        cmd_row = tk.Frame(command_card, bg=CARD)
        cmd_row.pack(fill=tk.X, padx=10, pady=10)
        tk.Label(cmd_row, text="手动命令：", bg=CARD, fg=ACCENT_DARK, font=("Microsoft YaHei UI", 10, "bold")).pack(side=tk.LEFT, padx=(0, 6))
        self.command_entry = ttk.Entry(cmd_row, textvariable=self.command_var)
        self.command_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6), ipady=2)
        self.command_entry.bind("<Return>", lambda _e: self.send_entry())
        ttk.Button(cmd_row, text="发送", style="Accent.TButton", command=self.send_entry).pack(side=tk.LEFT, padx=3)
        ttk.Button(cmd_row, text="发送回车", style="Soft.TButton", command=lambda: self.send_raw("\n")).pack(side=tk.LEFT, padx=3)
        ttk.Button(cmd_row, text="返回主界面", style="Soft.TButton", command=self._return_from_module).pack(side=tk.LEFT, padx=3)
        ttk.Button(cmd_row, text="打开目录", style="Soft.TButton", command=self.open_root_dir).pack(side=tk.LEFT, padx=3)

        tips = self._card(outer, fill=tk.X, pady=(0, 8))
        tk.Label(tips, text="说明：该窗口会接管当前模块交互；上方可手动输入模块命令。点击“返回主界面”会先尝试安全停止当前模块，再返回 GFAM 主界面。", bg=CARD, fg=MUTED, anchor=tk.W).pack(fill=tk.X, padx=12, pady=8)

        log_card = self._card(outer, fill=tk.BOTH, expand=True, pady=(0, 0))
        self._section_title(log_card, "模块日志 / 交互输出")
        log_inner = tk.Frame(log_card, bg=CARD)
        log_inner.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        self.log_text = tk.Text(log_inner, wrap=tk.WORD, font=("Consolas", 10), undo=False, bg=LOG_BG, fg=LOG_FG, relief=tk.FLAT, height=14)
        yscroll = ttk.Scrollbar(log_inner, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=yscroll.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._restore_log_text()

        self._append_log(f"\n[GUI] 已打开 {title} 模块窗口。\n")

    def _send_command_if_running(self, text: str, *, log_send: bool = True) -> bool:
        """Send a command only when the backend process is already alive.

        This is used by module return/exit paths.  It deliberately does not
        auto-start GFAM; otherwise pressing return after a stopped backend can
        relaunch GFAM and feed -E into the server selection prompt.
        """
        text = str(text or "").strip()
        if not text:
            return False
        if not self.process or self.process.poll() is not None:
            self._append_log(f"\n[GUI] GFAM 未运行，未发送命令：{text}\n")
            return False
        self.send_raw(text + "\n")
        if log_send:
            self._append_log(f"\n[GUI -> GFAM] {text}\n")
        return True

    def _return_from_module(self) -> None:
        """Safely leave the current module window and return to the main GUI.

        If a module has already printed its final statistics and is waiting at
        the wrapper's "Press any key" prompt, sending -q / -E is wrong: those
        commands are consumed as the key press or arrive at the next menu.  In
        that state we only send Enter and wait for the real main-menu marker.
        """
        key = self.current_module_key
        title = self.current_module_title or key or "当前模块"
        seq = MODULE_EXIT_SEQUENCES_BY_KEY.get(key or "", ["-E"])
        self.pending_module_to_open = None
        self.backend_menu_ready = False
        if self.process and self.process.poll() is None:
            if self.waiting_press_any_key:
                self._append_log(f"\n[GUI] {title} 已等待返回主菜单，发送回车完成返回。\n")
                self.send_raw("\n")
            else:
                self._append_log(f"\n[GUI] 正在返回主界面：{title}，将按顺序发送 {' -> '.join(seq)}。\n")
                for i, cmd in enumerate(seq):
                    self.after(i * MODULE_EXIT_STEP_DELAY_MS, lambda c=cmd: self._send_command_if_running(c))
            # Do not immediately assume the backend is at the main menu.  Close the
            # module UI now, but backend_menu_ready will only become true after the
            # actual GFAM main-menu output is detected.
            self.after(max(1, len(seq)) * MODULE_EXIT_STEP_DELAY_MS + 250, lambda: self._close_module_window(send_back=False))
        else:
            self._append_log("\n[GUI] GFAM 未运行，直接返回主界面窗口。\n")
            self._close_module_window(send_back=False)

    def _factory_resource_text(self, resources: dict[str, object] | None) -> str:
        if not isinstance(resources, dict):
            return "-"
        parts = []
        for key in ("mp", "ammo", "mre", "part"):
            parts.append(f"{FACTORY_RESOURCE_LABELS_GUI.get(key, key)} {resources.get(key, 0)}")
        return " / ".join(parts)

    def _factory_default_state(self) -> dict[str, object]:
        return {
            "doll_enabled": False,
            "doll_formula": "handgun",
            "doll_protect_mode": "retire_all_outputs",
            "doll_protect_ids": [],
            "doll_target_count": 1,
            "doll_target_scope": "total_outputs",
            "equip_enabled": False,
            "equip_formula": "optic",
            "equip_protect_mode": "auto_5star_outputs",
            "equip_protect_ids": [],
            "equip_protect_holo_red_dot": False,
            "equip_target_count": 1,
            "equip_target_scope": "total_outputs",
        }

    def _load_factory_state_for_gui(self) -> tuple[dict[str, object], Path, bool]:
        state_path = self.root_dir / FACTORY_STATE_FILE
        if not state_path.exists():
            alt = find_resource_file(self.root_dir, FACTORY_STATE_FILE)
            if alt:
                state_path = alt
        st = self._factory_default_state()
        loaded = False
        try:
            if state_path.exists():
                raw = json.loads(state_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    st.update(raw)
                    loaded = True
        except Exception as exc:
            self._append_log(f"\n[GUI] 读取制造设置文件失败：{exc}\n")
        return st, state_path, loaded


    def _save_factory_state_for_gui(self, state: dict[str, object], state_path: Path | None = None) -> Path:
        """Persist follow-module factory settings edited from the GUI popup."""
        if state_path is None:
            state_path = self.root_dir / FACTORY_STATE_FILE
        state = dict(state)
        state["updated_at"] = int(time.time())
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        return state_path

    # ── EPA series settings helpers ──────────────────────────────────

    def _epa_default_state(self) -> dict[str, object]:
        """Default values for the EPA / 13-4 / Smart shared settings file."""
        return {
            "module": "epa",
            "mode": "single",
            "mode_134": "-134train",
            "smart_plan_type": "gun",
            "schedule": "full",
            "train_count": 1,
            "stop_on_max": False,
            "stop_on_drop": False,
            "filter_protection": True,
            "equip_auto_lock": True,
            "difficulty": "普通",
            "stage": "A-10",
            "target": "-1",
            "auto_stop_minutes": 0,
            "enable_equip_retire": True,
            "equip_retire_max_rank": 4,
            "updated_at": 0,
        }

    def _load_epa_state_for_gui(self) -> tuple[dict[str, object], Path, bool]:
        """Read the shared EPA settings JSON.  Returns (state, path, loaded)."""
        state_path = self.root_dir / EPA_STATE_FILE
        if not state_path.exists():
            alt = find_resource_file(self.root_dir, EPA_STATE_FILE)
            if alt:
                state_path = alt
        st = self._epa_default_state()
        loaded = False
        try:
            if state_path.exists():
                raw = json.loads(state_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    st.update(raw)
                    loaded = True
        except Exception as exc:
            self._append_log(f"\n[GUI] 读取 EPA 设置文件失败：{exc}\n")
        return st, state_path, loaded

    def _save_epa_state_for_gui(self, state: dict[str, object], state_path: Path | None = None) -> Path:
        """Persist the shared EPA settings JSON."""
        if state_path is None:
            state_path = self.root_dir / EPA_STATE_FILE
        state = dict(state)
        state["updated_at"] = int(time.time())
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        return state_path

    def _factory_formula_label(self, key: object, formulas: dict[str, dict[str, object]]) -> str:
        key = str(key or "")
        info = formulas.get(key) or {}
        name = str(info.get("name") or key)
        res = self._factory_resource_text(info.get("resources")) if info else ""
        return f"{name}（{res}）" if res else name

    def _factory_formula_options(self, formulas: dict[str, dict[str, object]]) -> tuple[list[str], dict[str, str], dict[str, str]]:
        labels: list[str] = []
        label_to_key: dict[str, str] = {}
        key_to_label: dict[str, str] = {}
        for key, info in formulas.items():
            label = self._factory_formula_label(key, formulas)
            labels.append(label)
            label_to_key[label] = key
            key_to_label[key] = label
        return labels, label_to_key, key_to_label

    def _parse_id_list_for_gui(self, raw: object) -> list[int]:
        """Parse comma/space separated IDs; also accepts text like 233（Px4）."""
        nums = re.findall(r"\d+", str(raw or ""))
        result: list[int] = []
        seen: set[int] = set()
        for item in nums:
            try:
                value = int(item)
            except Exception:
                continue
            if value > 0 and value not in seen:
                result.append(value)
                seen.add(value)
        return result

    def _auto_doll_protect_ids_for_gui(self, formula_key: str) -> list[int]:
        """Mirror factory_config.py's default five-star protection list for GUI saves."""
        type_map = {"handgun": 1, "smg": 2, "rifle": 3, "ar": 4, "mg": 5}
        recommended = {"handgun": [233], "smg": [115]}
        target_type = type_map.get(str(formula_key), 0)
        ids: set[int] = set()
        for row in self._load_gun_dictionary_entries():
            try:
                gid = int(row.get("id") or 0)
                gtype = int(row.get("type") or 0)
                rank = max(int(row.get("rank") or 0), int(row.get("rank_display") or 0))
            except Exception:
                continue
            if gid > 0 and target_type and gtype == target_type and rank >= 5:
                ids.add(gid)
        for gid in recommended.get(str(formula_key), []):
            ids.add(gid)
        return sorted(ids)

    def _load_equip_dictionary_for_gui(self) -> dict[int, dict[str, object]]:
        merged: dict[int, dict[str, object]] = {}
        for filename in ("equip.json", "equip1.json", "equipment.json"):
            path = self.root_dir / "data" / filename
            if not path.exists():
                alt = find_resource_file(self.root_dir, "data", filename)
                if alt:
                    path = alt
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, list):
                continue
            for row in data:
                if not isinstance(row, dict):
                    continue
                try:
                    eid = int(row.get("id") or row.get("equip_id"))
                except Exception:
                    continue
                old = merged.get(eid, {})
                old.update(row)
                merged[eid] = old
        return merged

    def _display_name_from_catalog_row(self, row: object, fallback: str) -> str:
        if isinstance(row, dict):
            for key in ("name", "en_name", "code"):
                val = str(row.get(key) or "").strip()
                if val and not val.startswith("gun-") and not val.startswith("equip-"):
                    return val
        return fallback

    def _gun_name_by_id_for_gui(self, gid: object) -> str:
        try:
            target = int(gid)
        except Exception:
            return str(gid)
        for row in self._load_gun_dictionary_entries():
            try:
                if int(row.get("id") or 0) == target:
                    return self._display_name_from_catalog_row(row, str(target))
            except Exception:
                continue
        return str(target)

    def _format_factory_ids_for_popup(self, ids: object, kind: str) -> str:
        if not isinstance(ids, list) or not ids:
            return "未配置"
        shown: list[str] = []
        equip_catalog = self._load_equip_dictionary_for_gui() if kind == "equip" else {}
        for value in ids[:20]:
            try:
                item_id = int(value)
            except Exception:
                continue
            if kind == "equip":
                row = equip_catalog.get(item_id, {})
                name = self._display_name_from_catalog_row(row, str(item_id))
            else:
                name = self._gun_name_by_id_for_gui(item_id)
            shown.append(f"{item_id}（{name}）")
        if not shown:
            return "未配置"
        suffix = "" if len(ids) <= 20 else f" 等 {len(ids)} 个"
        return "、".join(shown) + suffix

    def _factory_scope_text(self, value: object) -> str:
        return "保护目标累计" if value == "protected_hits" else "总制造产物"

    def _factory_protect_mode_text(self, mode: object, kind: str, state: dict[str, object]) -> str:
        mode = str(mode or "-")
        if kind == "equip" and mode in ("auto_5star_outputs", "protect_all_5star", "auto_5star", "protect_5star"):
            sight = "开启" if state.get("equip_protect_holo_red_dot") else "关闭"
            return f"自动保护五星装备；全息/红点保护：{sight}"
        if kind == "doll":
            mapping = {
                "retire_all_outputs": "无指定保护时拆解全部产物 / 按公式默认五星保护逻辑处理",
                "manual_ids": "手动保护指定人形 ID",
                "formula_5star": "保护当前公式对应枪种五星人形",
            }
            return mapping.get(mode, mode)
        return mode

    def _factory_status_badge(self, enabled: object) -> tuple[str, str]:
        return ("已开启", SUCCESS) if enabled else ("已关闭", MUTED)

    def _open_factory_settings_window(self) -> None:
        """Show follow-module factory settings in a popup instead of dumping -show output."""
        if self.factory_settings_window and self.factory_settings_window.winfo_exists():
            self.factory_settings_window.lift()
            self._refresh_factory_settings_window()
            return

        win = tk.Toplevel(self.module_window or self)
        self.factory_settings_window = win
        win.title("GFAM - 制造设置")
        win.geometry("980x840")
        win.minsize(860, 740)
        win.configure(bg=BG)
        self._apply_window_icon(win)
        win.protocol("WM_DELETE_WINDOW", win.destroy)

        outer = tk.Frame(win, bg=BG, padx=12, pady=12)
        outer.pack(fill=tk.BOTH, expand=True)

        header = self._card(outer, fill=tk.X, pady=(0, 8))
        hrow = tk.Frame(header, bg=CARD)
        hrow.pack(fill=tk.X, padx=12, pady=10)
        if self._mascot_small:
            tk.Label(hrow, image=self._mascot_small, bg=CARD).pack(side=tk.LEFT, padx=(0, 10))
        title_col = tk.Frame(hrow, bg=CARD)
        title_col.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(title_col, text="制造设置", bg=CARD, fg=TEXT, font=("Microsoft YaHei UI", 16, "bold")).pack(anchor=tk.W)
        tk.Label(title_col, text="这里显示“跟随模块制造”的保存配置；自动快速建造会单独选择公式与保护规则。", bg=CARD, fg=MUTED).pack(anchor=tk.W)
        ttk.Button(hrow, text="刷新", style="Soft.TButton", command=self._refresh_factory_settings_window).pack(side=tk.RIGHT, padx=4)
        ttk.Button(hrow, text="关闭", style="Danger.TButton", command=win.destroy).pack(side=tk.RIGHT, padx=4)

        self.factory_settings_body = tk.Frame(outer, bg=BG)
        self.factory_settings_body.pack(fill=tk.BOTH, expand=True)
        self._refresh_factory_settings_window()

    def _add_factory_setting_row(self, parent: tk.Frame, label: str, value: str, value_fg: str = TEXT) -> None:
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill=tk.X, padx=12, pady=3)
        tk.Label(row, text=label, bg=CARD, fg=MUTED, width=16, anchor=tk.W).pack(side=tk.LEFT)
        tk.Label(row, text=value, bg=CARD, fg=value_fg, anchor=tk.W, justify=tk.LEFT, wraplength=560).pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _refresh_factory_settings_window(self) -> None:
        body = getattr(self, "factory_settings_body", None)
        if body is None or not body.winfo_exists():
            return
        for child in body.winfo_children():
            child.destroy()

        st, state_path, loaded = self._load_factory_state_for_gui()
        self.factory_settings_vars = {}

        doll_labels, doll_label_to_key, doll_key_to_label = self._factory_formula_options(FACTORY_DOLL_FORMULAS_GUI)
        equip_labels, equip_label_to_key, equip_key_to_label = self._factory_formula_options(FACTORY_EQUIP_FORMULAS_GUI)
        scope_values = ["总制造产物", "保护目标累计"]
        scope_to_key = {"总制造产物": "total_outputs", "保护目标累计": "protected_hits"}
        key_to_scope = {v: k for k, v in scope_to_key.items()}
        doll_mode_values = ["默认五星保护（按公式枪种）", "手动保护指定 ID", "不保护，按总产物计数"]
        doll_mode_to_key = {
            "默认五星保护（按公式枪种）": "auto_5star_by_formula",
            "手动保护指定 ID": "manual",
            "不保护，按总产物计数": "retire_all_outputs",
        }
        mode_raw = str(st.get("doll_protect_mode") or "retire_all_outputs")
        if mode_raw in ("manual_ids", "manual"):
            mode_label = "手动保护指定 ID"
        elif mode_raw in ("auto_5star_by_formula", "formula_5star"):
            mode_label = "默认五星保护（按公式枪种）"
        else:
            mode_label = "不保护，按总产物计数"

        vars_: dict[str, tk.Variable] = {
            "doll_enabled": tk.BooleanVar(value=bool(st.get("doll_enabled"))),
            "doll_formula": tk.StringVar(value=doll_key_to_label.get(str(st.get("doll_formula") or "handgun"), doll_labels[0] if doll_labels else "handgun")),
            "doll_mode": tk.StringVar(value=mode_label),
            "doll_ids": tk.StringVar(value=", ".join(str(x) for x in (st.get("doll_protect_ids") or []))),
            "doll_target_count": tk.StringVar(value=str(st.get("doll_target_count", 1))),
            "doll_target_scope": tk.StringVar(value=key_to_scope.get(str(st.get("doll_target_scope") or "total_outputs"), "总制造产物")),
            "equip_enabled": tk.BooleanVar(value=bool(st.get("equip_enabled"))),
            "equip_formula": tk.StringVar(value=equip_key_to_label.get(str(st.get("equip_formula") or "optic"), equip_labels[0] if equip_labels else "optic")),
            "equip_protect_holo_red_dot": tk.BooleanVar(value=bool(st.get("equip_protect_holo_red_dot"))),
            "equip_ids": tk.StringVar(value=", ".join(str(x) for x in (st.get("equip_protect_ids") or []))),
            "equip_target_count": tk.StringVar(value=str(st.get("equip_target_count", 1))),
            "equip_target_scope": tk.StringVar(value=key_to_scope.get(str(st.get("equip_target_scope") or "total_outputs"), "总制造产物")),
        }
        self.factory_settings_vars = vars_

        def add_combo(parent: tk.Frame, label: str, var: tk.StringVar, values: list[str], width: int = 36) -> ttk.Combobox:
            row = tk.Frame(parent, bg=CARD)
            row.pack(fill=tk.X, padx=12, pady=4)
            tk.Label(row, text=label, bg=CARD, fg=MUTED, width=16, anchor=tk.W).pack(side=tk.LEFT)
            cb = ttk.Combobox(row, textvariable=var, values=values, state="readonly", width=width)
            cb.pack(side=tk.LEFT, fill=tk.X, expand=True)
            return cb

        def add_entry(parent: tk.Frame, label: str, var: tk.StringVar, width: int = 36) -> ttk.Entry:
            row = tk.Frame(parent, bg=CARD)
            row.pack(fill=tk.X, padx=12, pady=4)
            tk.Label(row, text=label, bg=CARD, fg=MUTED, width=16, anchor=tk.W).pack(side=tk.LEFT)
            ent = ttk.Entry(row, textvariable=var, width=width)
            ent.pack(side=tk.LEFT, fill=tk.X, expand=True)
            return ent

        def add_check(parent: tk.Frame, text: str, var: tk.BooleanVar) -> None:
            row = tk.Frame(parent, bg=CARD)
            row.pack(fill=tk.X, padx=12, pady=4)
            tk.Checkbutton(row, text=text, variable=var, bg=CARD, fg=TEXT,
                           selectcolor=CARD, activebackground=CARD,
                           activeforeground=TEXT).pack(side=tk.LEFT)

        meta = self._card(body, fill=tk.X, pady=(0, 8))
        self._section_title(meta, "配置来源")
        self._add_factory_setting_row(meta, "状态", "已读取保存配置，可在下方修改" if loaded else "尚无保存配置，正在编辑默认值", SUCCESS if loaded else WARN)
        self._add_factory_setting_row(meta, "配置文件", str(state_path))

        cards = tk.Frame(body, bg=BG)
        cards.pack(fill=tk.BOTH, expand=True)
        left = self._card(cards, side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))
        right = self._card(cards, side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0))

        self._section_title(left, "跟随模块人形制造")
        add_check(left, "开启跟随模块人形制造", vars_["doll_enabled"])  # type: ignore[arg-type]
        add_combo(left, "制造公式", vars_["doll_formula"], doll_labels)  # type: ignore[arg-type]
        add_combo(left, "保护模式", vars_["doll_mode"], doll_mode_values)  # type: ignore[arg-type]
        add_entry(left, "保护人形 ID", vars_["doll_ids"])  # type: ignore[arg-type]
        row = tk.Frame(left, bg=CARD)
        row.pack(fill=tk.X, padx=12, pady=2)
        tk.Label(row, text="", bg=CARD, width=16).pack(side=tk.LEFT)
        ttk.Button(row, text="打开人形词典查询 ID", style="Soft.TButton", command=self._open_gun_dictionary_window).pack(side=tk.LEFT)
        add_entry(left, "目标数量", vars_["doll_target_count"], width=12)  # type: ignore[arg-type]
        add_combo(left, "目标口径", vars_["doll_target_scope"], scope_values, width=18)  # type: ignore[arg-type]

        self._section_title(right, "跟随模块装备制造")
        add_check(right, "开启跟随模块装备制造", vars_["equip_enabled"])  # type: ignore[arg-type]
        add_combo(right, "制造公式", vars_["equip_formula"], equip_labels)  # type: ignore[arg-type]
        add_check(right, "保护全息 / 红点 / ACOG 瞄具", vars_["equip_protect_holo_red_dot"])  # type: ignore[arg-type]
        add_entry(right, "额外保护装备 ID", vars_["equip_ids"])  # type: ignore[arg-type]
        add_entry(right, "目标数量", vars_["equip_target_count"], width=12)  # type: ignore[arg-type]
        add_combo(right, "目标口径", vars_["equip_target_scope"], scope_values, width=18)  # type: ignore[arg-type]
        self._add_factory_setting_row(right, "默认装备保护", "自动保护五星装备；普通全息/红点默认不保护，除非上方开关开启。", MUTED)

        def save_from_form() -> None:
            try:
                doll_count = int(str(vars_["doll_target_count"].get()).strip() or "1")  # type: ignore[index]
                equip_count = int(str(vars_["equip_target_count"].get()).strip() or "1")  # type: ignore[index]
                if doll_count < 0 or equip_count < 0:
                    raise ValueError("目标数量不能为负数")
            except Exception as exc:
                messagebox.showerror("制造设置", f"目标数量输入无效：{exc}", parent=self.factory_settings_window or self)
                return

            new_state = dict(st)
            doll_formula_key = doll_label_to_key.get(str(vars_["doll_formula"].get()), "handgun")  # type: ignore[index]
            equip_formula_key = equip_label_to_key.get(str(vars_["equip_formula"].get()), "optic")  # type: ignore[index]
            doll_mode_key = doll_mode_to_key.get(str(vars_["doll_mode"].get()), "retire_all_outputs")  # type: ignore[index]

            new_state["doll_enabled"] = bool(vars_["doll_enabled"].get())  # type: ignore[index]
            new_state["doll_formula"] = doll_formula_key
            if doll_mode_key == "auto_5star_by_formula":
                auto_ids = self._auto_doll_protect_ids_for_gui(doll_formula_key)
                new_state["doll_protect_mode"] = "auto_5star_by_formula"
                new_state["doll_protect_ids"] = auto_ids
                if auto_ids and str(vars_["doll_target_scope"].get()) == "总制造产物":  # type: ignore[index]
                    # Default five-star protection usually makes more sense as protected-hit quota.
                    pass
            elif doll_mode_key == "manual":
                ids = self._parse_id_list_for_gui(vars_["doll_ids"].get())  # type: ignore[index]
                if not ids and bool(vars_["doll_enabled"].get()):  # type: ignore[index]
                    if not messagebox.askyesno("制造设置", "已选择手动保护，但没有填写人形 ID。仍要保存吗？", parent=self.factory_settings_window or self):
                        return
                new_state["doll_protect_mode"] = "manual"
                new_state["doll_protect_ids"] = ids
            else:
                new_state["doll_protect_mode"] = "retire_all_outputs"
                new_state["doll_protect_ids"] = []

            if doll_mode_key == "retire_all_outputs":
                new_state["doll_target_scope"] = "total_outputs"
            else:
                new_state["doll_target_scope"] = scope_to_key.get(str(vars_["doll_target_scope"].get()), "protected_hits")  # type: ignore[index]
            new_state["doll_target_count"] = doll_count
            new_state["doll_retire_non_protected"] = True

            new_state["equip_enabled"] = bool(vars_["equip_enabled"].get())  # type: ignore[index]
            new_state["equip_formula"] = equip_formula_key
            new_state["equip_protect_mode"] = "auto_5star_outputs"
            new_state["equip_protect_holo_red_dot"] = bool(vars_["equip_protect_holo_red_dot"].get())  # type: ignore[index]
            new_state["equip_protect_ids"] = self._parse_id_list_for_gui(vars_["equip_ids"].get())  # type: ignore[index]
            new_state["equip_target_count"] = equip_count
            new_state["equip_target_scope"] = scope_to_key.get(str(vars_["equip_target_scope"].get()), "total_outputs")  # type: ignore[index]
            new_state["equip_retire_non_protected"] = True

            try:
                saved_path = self._save_factory_state_for_gui(new_state, state_path)
            except Exception as exc:
                messagebox.showerror("制造设置", f"保存失败：{exc}", parent=self.factory_settings_window or self)
                return
            self._append_log(f"\n[GUI] 制造设置已保存：{saved_path}\n")
            messagebox.showinfo("制造设置", "已保存跟随模块制造设置。\n下次模块运行时会按新设置启动后台制造。", parent=self.factory_settings_window or self)
            self._refresh_factory_settings_window()

        actions = self._card(body, fill=tk.X, pady=(8, 0))
        row = tk.Frame(actions, bg=CARD)
        row.pack(fill=tk.X, padx=12, pady=10)
        ttk.Button(row, text="保存修改", style="Accent.TButton", command=save_from_form).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(row, text="刷新当前保存值", style="Soft.TButton", command=self._refresh_factory_settings_window).pack(side=tk.LEFT, padx=8)
        ttk.Button(row, text="关闭", style="Danger.TButton", command=lambda: self.factory_settings_window.destroy() if self.factory_settings_window else None).pack(side=tk.RIGHT, padx=4)
        tk.Label(
            actions,
            text="说明：本页修改的是“跟随模块制造”的保存配置；人形/装备自动快速建造仍会在 factory 交互中单独选择本次公式和保护规则，不覆盖这里的设置。",
            bg=CARD,
            fg=MUTED,
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=880,
        ).pack(fill=tk.X, padx=12, pady=(0, 10))

    # ── Quick build settings popup ────────────────────────────────────

    def _open_quick_build_settings_window(self, kind: str) -> None:
        """Popup for selecting formula, count, and protection before starting quick build."""
        if self.quick_build_window and self.quick_build_window.winfo_exists():
            self.quick_build_window.destroy()
            self.quick_build_window = None

        win = tk.Toplevel(self.module_window or self)
        self.quick_build_window = win
        is_doll = (kind == "doll")
        label = "人形自动快速建造" if is_doll else "装备自动快速建造"
        win.title("GFAM - %s" % label)
        win.geometry("680x540")
        win.minsize(560, 440)
        win.configure(bg=BG)
        try:
            if self._gfam_icon_img:
                win.iconphoto(True, self._gfam_icon_img)
        except Exception:
            pass
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        try:
            parent_win = self.module_window or self
            if parent_win and parent_win.winfo_exists():
                win.transient(parent_win)
        except Exception:
            pass
        win.lift()
        try:
            win.focus_force()
        except Exception:
            pass

        outer = tk.Frame(win, bg=BG, padx=12, pady=12)
        outer.pack(fill=tk.BOTH, expand=True)

        header = self._card(outer, fill=tk.X, pady=(0, 8))
        hrow = tk.Frame(header, bg=CARD)
        hrow.pack(fill=tk.X, padx=12, pady=10)
        if self._mascot_small:
            tk.Label(hrow, image=self._mascot_small, bg=CARD).pack(side=tk.LEFT, padx=(0, 10))
        title_col = tk.Frame(hrow, bg=CARD)
        title_col.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(title_col, text=label, bg=CARD, fg=TEXT, font=("Microsoft YaHei UI", 14, "bold")).pack(anchor=tk.W)
        tk.Label(title_col, text="选择本次快速建造的公式、数量和保护规则，确认后即开始建造。", bg=CARD, fg=MUTED).pack(anchor=tk.W)
        ttk.Button(hrow, text="关闭", style="Danger.TButton", command=win.destroy).pack(side=tk.RIGHT, padx=4)

        body = self._card(outer, fill=tk.BOTH, expand=True, pady=(0, 8))
        self._section_title(body, "快速建造设置")

        formulas = FACTORY_DOLL_FORMULAS_GUI if is_doll else FACTORY_EQUIP_FORMULAS_GUI
        f_labels, f_label_to_key, _f_key_to_label = self._factory_formula_options(formulas)

        # Add "custom formula" option
        custom_label = "自定义公式（手动输入资源）"
        f_labels.append(custom_label)

        # Formula dropdown
        formula_var = tk.StringVar(value=f_labels[0] if f_labels else "")
        frow = tk.Frame(body, bg=CARD)
        frow.pack(fill=tk.X, padx=12, pady=4)
        tk.Label(frow, text="制造公式", bg=CARD, fg=MUTED, width=12, anchor=tk.W).pack(side=tk.LEFT)
        formula_combo = ttk.Combobox(frow, textvariable=formula_var, values=f_labels, state="readonly", width=30)
        formula_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Custom resource inputs (hidden by default)
        custom_frame = tk.Frame(body, bg=CARD)
        custom_vars = {}
        for rk, rl in [("mp", "人力"), ("ammo", "弹药"), ("mre", "口粮"), ("part", "零件")]:
            row = tk.Frame(custom_frame, bg=CARD)
            row.pack(fill=tk.X, padx=(24, 0), pady=1)
            tk.Label(row, text=rl, bg=CARD, fg=MUTED, width=8, anchor=tk.W).pack(side=tk.LEFT)
            var = tk.StringVar(value="0")
            custom_vars[rk] = var
            ttk.Entry(row, textvariable=var, width=10).pack(side=tk.LEFT)

        def _toggle_custom_fields(*_args):
            is_custom = (formula_var.get() == custom_label)
            if is_custom:
                custom_frame.pack(fill=tk.X, padx=12, pady=2)
            else:
                custom_frame.pack_forget()

        formula_var.trace_add("write", _toggle_custom_fields)

        # Count input
        count_var = tk.StringVar(value="1")
        crow = tk.Frame(body, bg=CARD)
        crow.pack(fill=tk.X, padx=12, pady=4)
        tk.Label(crow, text="建造次数", bg=CARD, fg=MUTED, width=12, anchor=tk.W).pack(side=tk.LEFT)
        ttk.Entry(crow, textvariable=count_var, width=12).pack(side=tk.LEFT)

        # Resource preview label
        res_var = tk.StringVar(value="")
        rrow = tk.Frame(body, bg=CARD)
        rrow.pack(fill=tk.X, padx=12, pady=2)
        tk.Label(rrow, text="", bg=CARD, width=12).pack(side=tk.LEFT)
        tk.Label(rrow, textvariable=res_var, bg=CARD, fg=MUTED, anchor=tk.W, wraplength=500).pack(side=tk.LEFT, fill=tk.X, expand=True)

        def _update_res_preview(*_args):
            lbl = formula_var.get()
            if lbl == custom_label:
                # Show custom resource values
                parts = []
                for k in ("mp", "ammo", "mre", "part"):
                    try:
                        v = int(custom_vars[k].get().strip())
                    except Exception:
                        v = 0
                    if v > 0:
                        parts.append("%s:%d" % (FACTORY_RESOURCE_LABELS_GUI.get(k, k), v))
                res_var.set("自定义消耗：" + " ".join(parts) if parts else "自定义消耗：请输入资源数值")
            else:
                key = f_label_to_key.get(lbl, "")
                info = formulas.get(key, {})
                res = info.get("resources", {})
                parts = ["%s:%d" % (FACTORY_RESOURCE_LABELS_GUI.get(k, k), v) for k, v in res.items() if v > 0]
                res_var.set("单次消耗：" + " ".join(parts))

        formula_var.trace_add("write", _update_res_preview)
        for _cv in custom_vars.values():
            _cv.trace_add("write", _update_res_preview)
        _update_res_preview()

        # Protection settings
        if is_doll:
            doll_mode_values = ["默认五星保护（按公式枪种）", "手动保护指定 ID", "不保护，按总产物计数"]
            mode_var = tk.StringVar(value=doll_mode_values[0])
            mrow = tk.Frame(body, bg=CARD)
            mrow.pack(fill=tk.X, padx=12, pady=4)
            tk.Label(mrow, text="保护模式", bg=CARD, fg=MUTED, width=12, anchor=tk.W).pack(side=tk.LEFT)
            ttk.Combobox(mrow, textvariable=mode_var, values=doll_mode_values, state="readonly", width=30).pack(side=tk.LEFT, fill=tk.X, expand=True)

            ids_var = tk.StringVar(value="")
            irow = tk.Frame(body, bg=CARD)
            irow.pack(fill=tk.X, padx=12, pady=4)
            tk.Label(irow, text="保护人形 ID", bg=CARD, fg=MUTED, width=12, anchor=tk.W).pack(side=tk.LEFT)
            ttk.Entry(irow, textvariable=ids_var, width=36).pack(side=tk.LEFT, fill=tk.X, expand=True)
            brow = tk.Frame(body, bg=CARD)
            brow.pack(fill=tk.X, padx=12, pady=2)
            tk.Label(brow, text="", bg=CARD, width=12).pack(side=tk.LEFT)
            ttk.Button(brow, text="打开人形词典查询 ID", style="Soft.TButton", command=self._open_gun_dictionary_window).pack(side=tk.LEFT)
        else:
            holo_var = tk.BooleanVar(value=False)
            hrow2 = tk.Frame(body, bg=CARD)
            hrow2.pack(fill=tk.X, padx=12, pady=4)
            tk.Label(hrow2, text="", bg=CARD, width=12).pack(side=tk.LEFT)
            tk.Checkbutton(hrow2, text="保护全息 / 红点 / ACOG 瞄具", variable=holo_var,
                           bg=CARD, fg=TEXT, selectcolor=CARD, activebackground=CARD, activeforeground=TEXT).pack(side=tk.LEFT)

        # Confirm action
        def _confirm():
            try:
                count = int(count_var.get().strip())
            except Exception:
                messagebox.showerror(label, "建造次数无效，请输入正整数。", parent=win)
                return
            if count <= 0:
                messagebox.showerror(label, "建造次数必须大于 0。", parent=win)
                return

            formula_key = f_label_to_key.get(formula_var.get(), "")
            is_custom = (formula_var.get() == custom_label)
            custom_res = {}
            if is_custom:
                formula_key = "custom"
                for k in ("mp", "ammo", "mre", "part"):
                    try:
                        v = int(custom_vars[k].get().strip())
                    except Exception:
                        v = 0
                    if v < 0:
                        messagebox.showerror(label, "资源数值不能为负数：%s" % FACTORY_RESOURCE_LABELS_GUI.get(k, k), parent=win)
                        return
                    custom_res[k] = max(0, v)
                if sum(custom_res.values()) <= 0:
                    messagebox.showerror(label, "自定义公式至少需要一种资源大于 0。", parent=win)
                    return
            elif not formula_key:
                messagebox.showerror(label, "请选择制造公式。", parent=win)
                return

            # Build GUI config dict
            cfg: dict[str, object] = {"kind": kind, "formula_key": formula_key, "count": count}
            if is_custom:
                cfg["custom_resources"] = custom_res
            if is_doll:
                mode_text = mode_var.get()
                if "手动" in mode_text:
                    cfg["protect_mode"] = "manual"
                    cfg["protect_ids"] = self._parse_id_list_for_gui(ids_var.get())
                    cfg["target_scope"] = "protected_hits"
                elif "默认" in mode_text:
                    cfg["protect_mode"] = "auto_5star_by_formula"
                    cfg["protect_ids"] = []
                    cfg["target_scope"] = "protected_hits"
                else:
                    cfg["protect_mode"] = "retire_all_outputs"
                    cfg["protect_ids"] = []
                    cfg["target_scope"] = "total_outputs"
            else:
                cfg["protect_holo_red_dot"] = bool(holo_var.get())

            # Write config file for backend
            try:
                config_path = self.root_dir / ".gfam_quick_build_gui.json"
                config_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as exc:
                messagebox.showerror(label, "写入配置文件失败：%s" % exc, parent=win)
                return

            # Send command
            cmd_prefix = "-testdollgui" if is_doll else "-testequipgui"
            cmd = "%s %d" % (cmd_prefix, count)
            win.destroy()
            self.quick_build_window = None
            if is_custom:
                res_parts = ["%s:%d" % (FACTORY_RESOURCE_LABELS_GUI.get(k, k), v) for k, v in custom_res.items() if v > 0]
                self._append_log("\n[GUI] %s：自定义公式（%s），次数 %d。\n" % (label, " ".join(res_parts), count))
            else:
                self._append_log("\n[GUI] %s：公式 %s，次数 %d。\n" % (label, formula_key, count))
            self.send_command(cmd)

        actions = self._card(outer, fill=tk.X, pady=(0, 0))
        arow = tk.Frame(actions, bg=CARD)
        arow.pack(fill=tk.X, padx=12, pady=10)
        ttk.Button(arow, text="确认并开始建造", style="Accent.TButton", command=_confirm).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(arow, text="取消", style="Soft.TButton", command=win.destroy).pack(side=tk.LEFT, padx=8)
        tk.Label(
            actions,
            text="说明：快速建造配置只在当前流程生效，不会覆盖跟随模块制造设置。",
            bg=CARD, fg=MUTED, anchor=tk.W, justify=tk.LEFT, wraplength=600,
        ).pack(fill=tk.X, padx=12, pady=(0, 10))

    def _begin_factory_quick_build(self, kind: str) -> None:
        """Ask the user to enter a quick-build count for factory test commands."""
        if kind == "doll":
            self.pending_factory_quick_cmd = "-testdoll"
            label = "人形自动快速建造"
        else:
            self.pending_factory_quick_cmd = "-testequip"
            label = "装备自动快速建造"
        self.command_var.set("")
        self._append_log(f"\n[GUI] {label}：请先在手动命令框输入建造次数，例如 1 / 5 / 10，然后点击发送。\n")
        self._append_log("[GUI] 发送后会在 factory 窗口内单独选择本次公式和保护规则；不会套用或覆盖 -show 中的跟随模块制造设置。\n")
        try:
            if self.command_entry is not None:
                self.command_entry.focus_set()
        except Exception:
            pass

    def _show_quick_build_summary_window(self) -> None:
        """Read the quick build summary JSON and display a statistics popup."""
        summary_path = self.root_dir / ".gfam_quick_build_summary.json"
        if not summary_path.exists():
            return
        try:
            data = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception:
            return
        kind = data.get("kind", "doll")
        title = "人形快速建造统计" if kind == "doll" else "装备快速建造统计"
        win = tk.Toplevel(self.module_window or self)
        win.title("GFAM - %s" % title)
        win.geometry("480x560")
        win.minsize(460, 540)
        win.configure(bg=BG)
        win.resizable(True, True)
        self._apply_window_icon(win)

        outer = tk.Frame(win, bg=BG, padx=16, pady=16)
        outer.pack(fill=tk.BOTH, expand=True)

        # Header
        header = self._card(outer, fill=tk.X, pady=(0, 10))
        hrow = tk.Frame(header, bg=CARD)
        hrow.pack(fill=tk.X, padx=12, pady=10)
        tk.Label(hrow, text=title, bg=CARD, fg=TEXT,
                 font=("Microsoft YaHei UI", 15, "bold")).pack(anchor=tk.W)
        tk.Label(hrow, text="公式：%s" % data.get("formula", ""), bg=CARD, fg=MUTED,
                 font=("Microsoft YaHei UI", 10)).pack(anchor=tk.W, pady=(2, 0))

        # Stats grid
        body = self._card(outer, fill=tk.BOTH, expand=True, pady=(0, 10))
        stats = [
            ("请求建造数", str(data.get("count_requested", 0))),
            ("实际完成数", str(data.get("count_completed", 0))),
            ("建造轮次", str(data.get("rounds", 0))),
            ("快速契约消耗", str(data.get("quick_contracts_used", 0))),
            ("目标命中（保留）", str(data.get("protected", 0))),
            ("非目标拆解", str(data.get("retired", 0))),
        ]
        for i, (label, value) in enumerate(stats):
            row = tk.Frame(body, bg=CARD)
            row.pack(fill=tk.X, padx=12, pady=(6 if i == 0 else 4, 4))
            tk.Label(row, text=label, bg=CARD, fg=MUTED,
                     font=("Microsoft YaHei UI", 11), anchor=tk.W, width=16).pack(side=tk.LEFT)
            color = SUCCESS if "完成" in label or "命中" in label else (WARN if "拆解" in label else TEXT)
            tk.Label(row, text=value, bg=CARD, fg=color,
                     font=("Microsoft YaHei UI", 13, "bold")).pack(side=tk.RIGHT)

        # Completion bar
        requested = max(1, data.get("count_requested", 1))
        completed = data.get("count_completed", 0)
        pct = min(100, completed * 100 // requested)
        bar_frame = tk.Frame(body, bg=CARD)
        bar_frame.pack(fill=tk.X, padx=12, pady=(8, 12))
        tk.Label(bar_frame, text="完成率 %d%%" % pct, bg=CARD, fg=ACCENT,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor=tk.W)
        bar_canvas = tk.Canvas(bar_frame, bg=BG2, height=10, highlightthickness=0)
        bar_canvas.pack(fill=tk.X, pady=(4, 0))
        bar_canvas.update_idletasks()
        cw = bar_canvas.winfo_width() or 400
        bar_canvas.create_rectangle(0, 0, cw * pct / 100, 10,
                                    fill=ACCENT if pct < 100 else SUCCESS, width=0)

        # Close button
        btn_row = tk.Frame(outer, bg=BG)
        btn_row.pack(fill=tk.X, pady=(4, 0))
        ttk.Button(btn_row, text="确认", style="Accent.TButton",
                   command=win.destroy).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="详细信息", style="Soft.TButton",
                   command=lambda: self._show_quick_build_detail_window(data)).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="关闭", style="Soft.TButton",
                   command=win.destroy).pack(side=tk.LEFT)

    def _show_quick_build_detail_window(self, data: dict) -> None:
        """Show a scrollable per-round detail popup for quick build results."""
        from collections import Counter
        rounds_detail = data.get("rounds_detail", [])
        if not rounds_detail:
            return
        kind = data.get("kind", "doll")
        type_label = "人形" if kind == "doll" else "装备"

        win = tk.Toplevel(self.module_window or self)
        win.title("GFAM - %s建造详细产出" % type_label)
        win.geometry("560x640")
        win.minsize(480, 480)
        win.configure(bg=BG)
        win.resizable(True, True)
        self._apply_window_icon(win)

        outer = tk.Frame(win, bg=BG, padx=16, pady=16)
        outer.pack(fill=tk.BOTH, expand=True)

        # Header
        header = self._card(outer, fill=tk.X, pady=(0, 10))
        hrow = tk.Frame(header, bg=CARD)
        hrow.pack(fill=tk.X, padx=12, pady=10)
        tk.Label(hrow, text="%s建造详细产出" % type_label, bg=CARD, fg=TEXT,
                 font=("Microsoft YaHei UI", 14, "bold")).pack(anchor=tk.W)
        tk.Label(hrow, text="共 %d 轮" % len(rounds_detail), bg=CARD, fg=MUTED,
                 font=("Microsoft YaHei UI", 10)).pack(anchor=tk.W, pady=(2, 0))

        # Scrollable area
        card = self._card(outer, fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(card, bg=CARD, highlightthickness=0)
        scrollbar = ttk.Scrollbar(card, orient=tk.VERTICAL, command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg=CARD)

        scroll_frame.bind("<Configure>",
                          lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Mouse wheel
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # Destroy handler to unbind mousewheel
        def _on_detail_close():
            canvas.unbind_all("<MouseWheel>")
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", _on_detail_close)

        # Per-round content
        for i, rd in enumerate(rounds_detail):
            rd_frame = tk.Frame(scroll_frame, bg=CARD)
            rd_frame.pack(fill=tk.X, padx=12, pady=(8 if i == 0 else 6, 6))

            # Round header with separator
            if i > 0:
                sep = tk.Frame(scroll_frame, bg=BG2, height=1)
                sep.pack(fill=tk.X, padx=12, pady=(2, 2))

            tk.Label(rd_frame, text="第 %d 轮" % (i + 1), bg=CARD, fg=ACCENT_DARK,
                     font=("Microsoft YaHei UI", 11, "bold")).pack(anchor=tk.W)

            # Stats line
            stats_line = tk.Frame(rd_frame, bg=CARD)
            stats_line.pack(fill=tk.X, pady=(2, 4))
            tk.Label(stats_line,
                     text="建造 %d 个  |  快速契约 %d" % (rd.get("built", 0), rd.get("quick_used", 0)),
                     bg=CARD, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(anchor=tk.W)

            # Protected items
            protected = rd.get("protected", [])
            if protected:
                p_header = tk.Frame(rd_frame, bg=CARD)
                p_header.pack(fill=tk.X, pady=(2, 0))
                tk.Label(p_header, text="保留（%d）" % len(protected), bg=CARD, fg=SUCCESS,
                         font=("Microsoft YaHei UI", 10, "bold")).pack(anchor=tk.W)
                names = []
                for item in protected:
                    name = item.get("name", "未知")
                    names.append(name)
                # Group by name with counts
                name_counts = Counter(names)
                p_text = tk.Frame(rd_frame, bg=CARD)
                p_text.pack(fill=tk.X, padx=(12, 0), pady=(1, 2))
                display_parts = []
                for name, cnt in name_counts.most_common():
                    display_parts.append("%s x%d" % (name, cnt) if cnt > 1 else name)
                tk.Label(p_text, text="  ".join(display_parts), bg=CARD, fg=TEXT,
                         font=("Microsoft YaHei UI", 9), anchor=tk.W, justify=tk.LEFT,
                         wraplength=480).pack(anchor=tk.W)

            # Retired items
            retired = rd.get("retired", [])
            if retired:
                r_header = tk.Frame(rd_frame, bg=CARD)
                r_header.pack(fill=tk.X, pady=(2, 0))
                tk.Label(r_header, text="拆解（%d）" % len(retired), bg=CARD, fg=WARN,
                         font=("Microsoft YaHei UI", 10, "bold")).pack(anchor=tk.W)
                names = []
                for item in retired:
                    name = item.get("name", "未知")
                    names.append(name)
                name_counts = Counter(names)
                r_text = tk.Frame(rd_frame, bg=CARD)
                r_text.pack(fill=tk.X, padx=(12, 0), pady=(1, 2))
                display_parts = []
                for name, cnt in name_counts.most_common():
                    display_parts.append("%s x%d" % (name, cnt) if cnt > 1 else name)
                tk.Label(r_text, text="  ".join(display_parts), bg=CARD, fg=TEXT,
                         font=("Microsoft YaHei UI", 9), anchor=tk.W, justify=tk.LEFT,
                         wraplength=480).pack(anchor=tk.W)

            # Fallback: handle legacy format (protected_uids / retired_uids without names)
            if not protected and not retired:
                legacy_p = rd.get("protected_uids", [])
                legacy_r = rd.get("retired_uids", [])
                if legacy_p:
                    tk.Label(rd_frame, text="保留 %d 个（UID: %s）" % (len(legacy_p), ", ".join(str(u) for u in legacy_p[:10])),
                             bg=CARD, fg=SUCCESS, font=("Microsoft YaHei UI", 9),
                             anchor=tk.W, wraplength=480).pack(anchor=tk.W, padx=(12, 0))
                if legacy_r:
                    tk.Label(rd_frame, text="拆解 %d 个（UID: %s）" % (len(legacy_r), ", ".join(str(u) for u in legacy_r[:10])),
                             bg=CARD, fg=WARN, font=("Microsoft YaHei UI", 9),
                             anchor=tk.W, wraplength=480).pack(anchor=tk.W, padx=(12, 0))

        # Close button
        btn_row = tk.Frame(outer, bg=BG)
        btn_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btn_row, text="关闭", style="Soft.TButton",
                   command=_on_detail_close).pack(side=tk.LEFT)

    # ── A-10 resource farming summary popup ──────────────────────────

    def _show_a10_summary_window(self) -> None:
        """Read the A-10 summary JSON and display a statistics popup."""
        summary_path = self.root_dir / ".gfam_a10_summary.json"
        if not summary_path.exists():
            return
        try:
            data = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception:
            return

        win = tk.Toplevel(self.module_window or self)
        win.title("GFAM - A-10 资源获取统计")
        win.geometry("520x680")
        win.minsize(480, 600)
        win.configure(bg=BG)
        win.resizable(True, True)
        self._apply_window_icon(win)

        outer = tk.Frame(win, bg=BG, padx=16, pady=16)
        outer.pack(fill=tk.BOTH, expand=True)

        # Header
        header = self._card(outer, fill=tk.X, pady=(0, 10))
        hrow = tk.Frame(header, bg=CARD)
        hrow.pack(fill=tk.X, padx=12, pady=10)
        tk.Label(hrow, text="A-10 四项资源获取统计", bg=CARD, fg=TEXT,
                 font=("Microsoft YaHei UI", 15, "bold")).pack(anchor=tk.W)
        tk.Label(hrow, text="服务器：%s    运行时长：%s" % (data.get("server", ""), data.get("elapsed_text", "")),
                 bg=CARD, fg=MUTED, font=("Microsoft YaHei UI", 10)).pack(anchor=tk.W, pady=(2, 0))

        # Rounds & guns card
        card1 = self._card(outer, fill=tk.X, pady=(0, 10))
        stats1 = [
            ("完成轮数", str(data.get("success", 0)), SUCCESS),
            ("总 MACRO", str(data.get("macro", 0)), TEXT),
            ("失败次数", str(data.get("failures", 0)), WARN if data.get("failures", 0) > 0 else TEXT),
            ("人形掉落", str(data.get("dropped_gun_count", 0)), TEXT),
            ("人形拆解", str(data.get("retired_gun_count", 0)), TEXT),
            ("待拆解缓存", str(data.get("pending_gun_count", 0)),
             WARN if data.get("pending_gun_count", 0) > 0 else TEXT),
        ]
        for i, (label, value, color) in enumerate(stats1):
            row = tk.Frame(card1, bg=CARD)
            row.pack(fill=tk.X, padx=12, pady=(6 if i == 0 else 3, 3))
            tk.Label(row, text=label, bg=CARD, fg=MUTED,
                     font=("Microsoft YaHei UI", 10), anchor=tk.W, width=14).pack(side=tk.LEFT)
            tk.Label(row, text=value, bg=CARD, fg=color,
                     font=("Microsoft YaHei UI", 12, "bold")).pack(side=tk.RIGHT)

        # Resource changes card
        RES_LABELS = {"mp": "人力", "ammo": "弹药", "mre": "口粮", "part": "零件"}
        diff = data.get("resource_diff") or {}
        per_hour = data.get("resource_per_hour") or {}
        start_res = data.get("resource_start") or {}
        end_res = data.get("resource_end") or {}

        card2 = self._card(outer, fill=tk.BOTH, expand=True, pady=(0, 10))
        tk.Label(card2, text="资源变化", bg=CARD, fg=ACCENT_DARK,
                 font=("Microsoft YaHei UI", 11, "bold")).pack(anchor=tk.W, padx=12, pady=(10, 6))

        # Table header
        thead = tk.Frame(card2, bg=CARD)
        thead.pack(fill=tk.X, padx=12, pady=(0, 2))
        for col_text, col_w in [("", 6), ("起始", 10), ("结束", 10), ("变化", 10), ("/小时", 10)]:
            tk.Label(thead, text=col_text, bg=CARD, fg=MUTED,
                     font=("Microsoft YaHei UI", 9), width=col_w, anchor=tk.E).pack(side=tk.LEFT)

        for key in ("mp", "ammo", "mre", "part"):
            trow = tk.Frame(card2, bg=CARD)
            trow.pack(fill=tk.X, padx=12, pady=2)
            _diff_val = int(diff.get(key, 0) or 0)
            _ph_val = int(per_hour.get(key, 0) or 0)
            _diff_text = "%+d" % _diff_val
            _ph_text = "%+d" % _ph_val
            _diff_color = SUCCESS if _diff_val > 0 else (WARN if _diff_val < 0 else TEXT)
            _ph_color = SUCCESS if _ph_val > 0 else (WARN if _ph_val < 0 else TEXT)
            tk.Label(trow, text=RES_LABELS.get(key, key), bg=CARD, fg=TEXT,
                     font=("Microsoft YaHei UI", 10), width=6, anchor=tk.W).pack(side=tk.LEFT)
            tk.Label(trow, text=str(int(start_res.get(key, 0) or 0)), bg=CARD, fg=MUTED,
                     font=("Microsoft YaHei UI", 10), width=10, anchor=tk.E).pack(side=tk.LEFT)
            tk.Label(trow, text=str(int(end_res.get(key, 0) or 0)), bg=CARD, fg=TEXT,
                     font=("Microsoft YaHei UI", 10), width=10, anchor=tk.E).pack(side=tk.LEFT)
            tk.Label(trow, text=_diff_text, bg=CARD, fg=_diff_color,
                     font=("Microsoft YaHei UI", 10, "bold"), width=10, anchor=tk.E).pack(side=tk.LEFT)
            tk.Label(trow, text=_ph_text, bg=CARD, fg=_ph_color,
                     font=("Microsoft YaHei UI", 10, "bold"), width=10, anchor=tk.E).pack(side=tk.LEFT)

        # Fairy stats section (optional)
        fairy = data.get("fairy")
        if fairy and isinstance(fairy, dict):
            fairy_card = self._card(outer, fill=tk.X, pady=(0, 10))
            tk.Label(fairy_card, text="妖精自动", bg=CARD, fg=ACCENT_DARK,
                     font=("Microsoft YaHei UI", 11, "bold")).pack(anchor=tk.W, padx=12, pady=(10, 4))
            _fairy_stats = [
                ("建造启动", "%d / %d" % (int(fairy.get("build_success", 0) or 0), int(fairy.get("build_attempts", 0) or 0))),
                ("领取完成", "%d / %d" % (int(fairy.get("finish_success", 0) or 0), int(fairy.get("finish_attempts", 0) or 0))),
                ("强化", "%d / %d" % (int(fairy.get("strengthen_success", 0) or 0), int(fairy.get("strengthen_attempts", 0) or 0))),
            ]
            inv = fairy.get("fairy_inventory") or {}
            if inv:
                _fairy_stats.append(("仓库", "%d / %d（空位 %d）" % (
                    int(inv.get("count", 0) or 0), int(inv.get("max", 0) or 0), int(inv.get("free", 0) or 0))))
            for i, (label, value) in enumerate(_fairy_stats):
                row = tk.Frame(fairy_card, bg=CARD)
                row.pack(fill=tk.X, padx=12, pady=(2 if i > 0 else 0, 2))
                tk.Label(row, text=label, bg=CARD, fg=MUTED,
                         font=("Microsoft YaHei UI", 10), anchor=tk.W, width=10).pack(side=tk.LEFT)
                tk.Label(row, text=value, bg=CARD, fg=TEXT,
                         font=("Microsoft YaHei UI", 10)).pack(side=tk.RIGHT)
            tk.Frame(fairy_card, bg=CARD, height=8).pack()

        # Close button
        btn_row = tk.Frame(outer, bg=BG)
        btn_row.pack(fill=tk.X, pady=(4, 0))
        ttk.Button(btn_row, text="确认", style="Accent.TButton",
                   command=win.destroy).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="关闭", style="Soft.TButton",
                   command=win.destroy).pack(side=tk.LEFT)

    # ── Generic module summary popup ──────────────────────────────────

    def _show_module_summary_window(self, json_filename: str) -> None:
        """Read a generic module summary JSON and display a statistics popup."""
        summary_path = self.root_dir / json_filename
        if not summary_path.exists():
            return
        try:
            data = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception:
            return

        title_text = data.get("title") or "统计报告"
        win = tk.Toplevel(self.module_window or self)
        win.title("GFAM - %s" % title_text)
        win.geometry("500x620")
        win.minsize(440, 400)
        win.configure(bg=BG)
        win.resizable(True, True)
        self._apply_window_icon(win)

        # Use scrollable canvas for flexible content
        canvas = tk.Canvas(win, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(win, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        outer = tk.Frame(canvas, bg=BG, padx=16, pady=16)
        canvas.create_window((0, 0), window=outer, anchor=tk.NW, tags="inner")

        def _on_cfg(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        outer.bind("<Configure>", _on_cfg)
        def _on_canvas_cfg(e):
            canvas.itemconfigure("inner", width=e.width)
        canvas.bind("<Configure>", _on_canvas_cfg)

        # Header card
        header = self._card(outer, fill=tk.X, pady=(0, 10))
        hrow = tk.Frame(header, bg=CARD)
        hrow.pack(fill=tk.X, padx=12, pady=10)
        tk.Label(hrow, text=title_text, bg=CARD, fg=TEXT,
                 font=("Microsoft YaHei UI", 15, "bold")).pack(anchor=tk.W)
        subtitle_parts = []
        if data.get("server"):
            subtitle_parts.append("服务器：%s" % data["server"])
        if data.get("elapsed_text"):
            subtitle_parts.append("运行时长：%s" % data["elapsed_text"])
        if subtitle_parts:
            tk.Label(hrow, text="    ".join(subtitle_parts), bg=CARD, fg=MUTED,
                     font=("Microsoft YaHei UI", 10)).pack(anchor=tk.W, pady=(2, 0))

        # Stats section
        stats_list = data.get("stats") or []
        if stats_list:
            stats_card = self._card(outer, fill=tk.X, pady=(0, 10))
            for i, item in enumerate(stats_list):
                row = tk.Frame(stats_card, bg=CARD)
                row.pack(fill=tk.X, padx=12, pady=(6 if i == 0 else 3, 3))
                tk.Label(row, text=item.get("label", ""), bg=CARD, fg=MUTED,
                         font=("Microsoft YaHei UI", 10), anchor=tk.W, width=14).pack(side=tk.LEFT)
                tk.Label(row, text=str(item.get("value", "")), bg=CARD, fg=TEXT,
                         font=("Microsoft YaHei UI", 12, "bold")).pack(side=tk.RIGHT)

        # Resource table (if present)
        RES_LABELS = {"mp": "人力", "ammo": "弹药", "mre": "口粮", "part": "零件"}
        diff = data.get("resource_diff") or {}
        per_hour = data.get("resource_per_hour") or {}
        start_res = data.get("resource_start") or {}
        end_res = data.get("resource_end") or {}
        if diff:
            res_card = self._card(outer, fill=tk.X, pady=(0, 10))
            tk.Label(res_card, text="资源变化", bg=CARD, fg=ACCENT_DARK,
                     font=("Microsoft YaHei UI", 11, "bold")).pack(anchor=tk.W, padx=12, pady=(10, 6))
            thead = tk.Frame(res_card, bg=CARD)
            thead.pack(fill=tk.X, padx=12, pady=(0, 2))
            has_start = bool(start_res)
            has_end = bool(end_res)
            cols = [("", 6)]
            if has_start:
                cols.append(("起始", 10))
            if has_end:
                cols.append(("结束", 10))
            cols.append(("变化", 10))
            cols.append(("/小时", 10))
            for col_text, col_w in cols:
                tk.Label(thead, text=col_text, bg=CARD, fg=MUTED,
                         font=("Microsoft YaHei UI", 9), width=col_w, anchor=tk.E).pack(side=tk.LEFT)
            for key in ("mp", "ammo", "mre", "part"):
                trow = tk.Frame(res_card, bg=CARD)
                trow.pack(fill=tk.X, padx=12, pady=2)
                _diff_val = int(diff.get(key, 0) or 0)
                _ph_val = int(per_hour.get(key, 0) or 0)
                _diff_color = SUCCESS if _diff_val > 0 else (WARN if _diff_val < 0 else TEXT)
                _ph_color = SUCCESS if _ph_val > 0 else (WARN if _ph_val < 0 else TEXT)
                tk.Label(trow, text=RES_LABELS.get(key, key), bg=CARD, fg=TEXT,
                         font=("Microsoft YaHei UI", 10), width=6, anchor=tk.W).pack(side=tk.LEFT)
                if has_start:
                    tk.Label(trow, text=str(int(start_res.get(key, 0) or 0)), bg=CARD, fg=MUTED,
                             font=("Microsoft YaHei UI", 10), width=10, anchor=tk.E).pack(side=tk.LEFT)
                if has_end:
                    tk.Label(trow, text=str(int(end_res.get(key, 0) or 0)), bg=CARD, fg=TEXT,
                             font=("Microsoft YaHei UI", 10), width=10, anchor=tk.E).pack(side=tk.LEFT)
                tk.Label(trow, text="%+d" % _diff_val, bg=CARD, fg=_diff_color,
                         font=("Microsoft YaHei UI", 10, "bold"), width=10, anchor=tk.E).pack(side=tk.LEFT)
                tk.Label(trow, text="%+d" % _ph_val, bg=CARD, fg=_ph_color,
                         font=("Microsoft YaHei UI", 10, "bold"), width=10, anchor=tk.E).pack(side=tk.LEFT)
            tk.Frame(res_card, bg=CARD, height=8).pack()

        # Resource cost (for greyzone: ticket_cost + resource_cost dict)
        rc = data.get("resource_cost")
        if rc and isinstance(rc, dict) and not diff:
            rc_card = self._card(outer, fill=tk.X, pady=(0, 10))
            tk.Label(rc_card, text="资源消耗", bg=CARD, fg=ACCENT_DARK,
                     font=("Microsoft YaHei UI", 11, "bold")).pack(anchor=tk.W, padx=12, pady=(10, 6))
            for i, key in enumerate(("mp", "ammo", "mre", "part")):
                row = tk.Frame(rc_card, bg=CARD)
                row.pack(fill=tk.X, padx=12, pady=(2 if i > 0 else 0, 2))
                val = int(rc.get(key, 0) or 0)
                tk.Label(row, text=RES_LABELS.get(key, key), bg=CARD, fg=MUTED,
                         font=("Microsoft YaHei UI", 10), anchor=tk.W, width=10).pack(side=tk.LEFT)
                tk.Label(row, text="-%d" % val, bg=CARD, fg=WARN if val > 0 else TEXT,
                         font=("Microsoft YaHei UI", 10)).pack(side=tk.RIGHT)
            tk.Frame(rc_card, bg=CARD, height=8).pack()

        # Follow-module factory stats section (optional)
        factory = data.get("factory")
        if factory and isinstance(factory, dict):
            factory_card = self._card(outer, fill=tk.X, pady=(0, 10))
            tk.Label(factory_card, text="跟随模块制造", bg=CARD, fg=ACCENT_DARK,
                     font=("Microsoft YaHei UI", 11, "bold")).pack(anchor=tk.W, padx=12, pady=(10, 4))
            _has_any_factory = False
            for _fk, _flabel in [("doll", "人形制造"), ("equip", "装备制造")]:
                _fdata = factory.get(_fk)
                if not _fdata or not isinstance(_fdata, dict):
                    continue
                _fstats = _fdata.get("stats") or {}
                _ba = int(_fstats.get("build_attempts", 0) or 0)
                _to = int(_fstats.get("total_outputs", 0) or 0)
                if _ba == 0 and _to == 0:
                    continue
                _has_any_factory = True
                _formula = _fdata.get("formula_name") or ""
                _sub_label = "%s%s" % (_flabel, ("（%s）" % _formula) if _formula else "")
                tk.Label(factory_card, text=_sub_label, bg=CARD, fg=TEXT,
                         font=("Microsoft YaHei UI", 10, "bold")).pack(anchor=tk.W, padx=12, pady=(4, 0))
                _rows = [
                    ("建造", "%d / %d" % (int(_fstats.get("build_success", 0) or 0), _ba)),
                    ("领取", "%d / %d" % (int(_fstats.get("finish_success", 0) or 0), int(_fstats.get("finish_attempts", 0) or 0))),
                    ("命中目标", str(int(_fstats.get("target_kept", 0) or 0))),
                    ("产出总数", str(_to)),
                ]
                for _ri, (_rl, _rv) in enumerate(_rows):
                    row = tk.Frame(factory_card, bg=CARD)
                    row.pack(fill=tk.X, padx=20, pady=(1 if _ri > 0 else 0, 1))
                    tk.Label(row, text=_rl, bg=CARD, fg=MUTED,
                             font=("Microsoft YaHei UI", 10), anchor=tk.W, width=10).pack(side=tk.LEFT)
                    tk.Label(row, text=_rv, bg=CARD, fg=TEXT,
                             font=("Microsoft YaHei UI", 10)).pack(side=tk.RIGHT)
            if _has_any_factory:
                tk.Frame(factory_card, bg=CARD, height=8).pack()
            else:
                factory_card.destroy()

        # Fairy stats section (optional)
        fairy = data.get("fairy")
        if fairy and isinstance(fairy, dict):
            fairy_card = self._card(outer, fill=tk.X, pady=(0, 10))
            tk.Label(fairy_card, text="妖精自动", bg=CARD, fg=ACCENT_DARK,
                     font=("Microsoft YaHei UI", 11, "bold")).pack(anchor=tk.W, padx=12, pady=(10, 4))
            _fairy_stats = [
                ("建造启动", "%d / %d" % (int(fairy.get("build_success", 0) or 0), int(fairy.get("build_attempts", 0) or 0))),
                ("领取完成", "%d / %d" % (int(fairy.get("finish_success", 0) or 0), int(fairy.get("finish_attempts", 0) or 0))),
                ("强化", "%d / %d" % (int(fairy.get("strengthen_success", 0) or 0), int(fairy.get("strengthen_attempts", 0) or 0))),
            ]
            inv = fairy.get("fairy_inventory") or {}
            if inv:
                _fairy_stats.append(("仓库", "%d / %d（空位 %d）" % (
                    int(inv.get("count", 0) or 0), int(inv.get("max", 0) or 0), int(inv.get("free", 0) or 0))))
            for i, (label, value) in enumerate(_fairy_stats):
                row = tk.Frame(fairy_card, bg=CARD)
                row.pack(fill=tk.X, padx=12, pady=(2 if i > 0 else 0, 2))
                tk.Label(row, text=label, bg=CARD, fg=MUTED,
                         font=("Microsoft YaHei UI", 10), anchor=tk.W, width=10).pack(side=tk.LEFT)
                tk.Label(row, text=value, bg=CARD, fg=TEXT,
                         font=("Microsoft YaHei UI", 10)).pack(side=tk.RIGHT)
            tk.Frame(fairy_card, bg=CARD, height=8).pack()

        # Close button
        btn_row = tk.Frame(outer, bg=BG)
        btn_row.pack(fill=tk.X, pady=(4, 0))
        ttk.Button(btn_row, text="确认", style="Accent.TButton",
                   command=win.destroy).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="关闭", style="Soft.TButton",
                   command=win.destroy).pack(side=tk.LEFT)

    def _route_summary_popup(self, text: str) -> None:
        """Route a [SUMMARY] line to the correct summary popup based on content."""
        # A-10 has its own dedicated window
        if "A-10" in text:
            self.after(200, self._show_a10_summary_window)
        elif "零元购PR" in text or "f2p_pr" in text:
            self.after(200, lambda: self._show_module_summary_window(".gfam_f2p_pr_summary.json"))
        elif "零元购" in text:
            self.after(200, lambda: self._show_module_summary_window(".gfam_f2p_summary.json"))
        elif "灰域" in text or "彩蛋" in text:
            self.after(200, lambda: self._show_module_summary_window(".gfam_greyzone_summary.json"))
        elif "13-4" in text or "13_4" in text:
            self.after(200, lambda: self._show_module_summary_window(".gfam_13_4_summary.json"))
        elif "EPA" in text:
            self.after(200, lambda: self._show_module_summary_window(".gfam_epa_summary.json"))
        else:
            # Fallback: quick build
            self.after(200, self._show_quick_build_summary_window)

    # ── Follow-module factory control popup ──────────────────────────

    def _open_follow_factory_settings_window(self) -> None:
        """Simple on/off control popup for follow-module manufacturing.

        Reads the persistent JSON state and lets the user toggle doll/equip
        manufacturing on or off.  Detailed formula/protection editing stays
        in the existing *制造设置* popup (``_open_factory_settings_window``).
        """
        if self.follow_factory_window and self.follow_factory_window.winfo_exists():
            self.follow_factory_window.lift()
            self._refresh_follow_factory_settings_window()
            return

        win = tk.Toplevel(self.module_window or self)
        self.follow_factory_window = win
        win.title("GFAM - 跟随模块制造")
        win.geometry("1080x640")
        win.minsize(960, 560)
        win.configure(bg=BG)
        self._apply_window_icon(win)
        win.protocol("WM_DELETE_WINDOW", win.destroy)

        outer = tk.Frame(win, bg=BG, padx=12, pady=12)
        outer.pack(fill=tk.BOTH, expand=True)

        # ── header card ──
        header = self._card(outer, fill=tk.X, pady=(0, 8))
        hrow = tk.Frame(header, bg=CARD)
        hrow.pack(fill=tk.X, padx=12, pady=10)
        if self._mascot_small:
            tk.Label(hrow, image=self._mascot_small, bg=CARD).pack(side=tk.LEFT, padx=(0, 10))
        title_col = tk.Frame(hrow, bg=CARD)
        title_col.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(title_col, text="跟随模块制造", bg=CARD, fg=TEXT,
                 font=("Microsoft YaHei UI", 16, "bold")).pack(anchor=tk.W)
        tk.Label(title_col,
                 text="开启后，后台守护进程会跟随其他模块自动制造人形/装备。",
                 bg=CARD, fg=MUTED).pack(anchor=tk.W)
        ttk.Button(hrow, text="刷新", style="Soft.TButton",
                   command=self._refresh_follow_factory_settings_window).pack(side=tk.RIGHT, padx=4)
        ttk.Button(hrow, text="关闭", style="Danger.TButton",
                   command=win.destroy).pack(side=tk.RIGHT, padx=4)

        self.follow_factory_body = tk.Frame(outer, bg=BG)
        self.follow_factory_body.pack(fill=tk.BOTH, expand=True)
        self._refresh_follow_factory_settings_window()

    def _refresh_follow_factory_settings_window(self) -> None:
        body = getattr(self, "follow_factory_body", None)
        if body is None or not body.winfo_exists():
            return
        for child in body.winfo_children():
            child.destroy()

        st, state_path, loaded = self._load_factory_state_for_gui()

        # Build formula label helpers (reuse existing logic).
        doll_labels, _, doll_key_to_label = self._factory_formula_options(FACTORY_DOLL_FORMULAS_GUI)
        equip_labels, _, equip_key_to_label = self._factory_formula_options(FACTORY_EQUIP_FORMULAS_GUI)

        # ── variables ──
        vars_: dict[str, tk.Variable] = {
            "doll_enabled": tk.BooleanVar(value=bool(st.get("doll_enabled"))),
            "equip_enabled": tk.BooleanVar(value=bool(st.get("equip_enabled"))),
            "equip_protect_holo_red_dot": tk.BooleanVar(
                value=bool(st.get("equip_protect_holo_red_dot"))),
        }

        def add_check(parent: tk.Frame, text: str, var: tk.BooleanVar) -> None:
            row = tk.Frame(parent, bg=CARD)
            row.pack(fill=tk.X, padx=12, pady=4)
            tk.Checkbutton(row, text=text, variable=var, bg=CARD, fg=TEXT,
                           selectcolor=CARD, activebackground=CARD,
                           activeforeground=TEXT,
                           font=("Microsoft YaHei UI", 11, "bold")).pack(side=tk.LEFT)

        # ── Status line ──
        meta = self._card(body, fill=tk.X, pady=(0, 8))
        self._add_factory_setting_row(
            meta, "配置来源",
            "已读取保存配置" if loaded else "尚无保存配置（使用默认值）",
            SUCCESS if loaded else WARN,
        )

        # ── Two side-by-side cards ──
        cards = tk.Frame(body, bg=BG)
        cards.pack(fill=tk.BOTH, expand=True)
        left = self._card(cards, side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))
        right = self._card(cards, side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0))

        # ── Left card: doll manufacturing ──
        self._section_title(left, "跟随模块人形制造")
        add_check(left, "开启人形制造", vars_["doll_enabled"])

        doll_badge, doll_colour = self._factory_status_badge(st.get("doll_enabled"))
        self._add_factory_setting_row(left, "当前状态", doll_badge, doll_colour)
        self._add_factory_setting_row(
            left, "制造公式",
            self._factory_formula_label(st.get("doll_formula") or "handgun",
                                        FACTORY_DOLL_FORMULAS_GUI))
        protect_mode_raw = str(st.get("doll_protect_mode") or "retire_all_outputs")
        if protect_mode_raw in ("manual_ids", "manual"):
            protect_mode_label = "手动保护指定 ID"
        elif protect_mode_raw in ("auto_5star_by_formula", "formula_5star"):
            protect_mode_label = "默认五星保护"
        else:
            protect_mode_label = "不保护（全部拆解）"
        self._add_factory_setting_row(left, "保护模式", protect_mode_label)
        self._add_factory_setting_row(
            left, "目标数量",
            f"{st.get('doll_target_count', 1)}（{'保护目标累计' if st.get('doll_target_scope') == 'protected_hits' else '总制造产物'}）")
        disabled_reason = st.get("doll_disabled_reason")
        if disabled_reason:
            self._add_factory_setting_row(left, "自动关闭原因", str(disabled_reason), WARN)

        # ── Right card: equip manufacturing ──
        self._section_title(right, "跟随模块装备制造")
        add_check(right, "开启装备制造", vars_["equip_enabled"])

        equip_badge, equip_colour = self._factory_status_badge(st.get("equip_enabled"))
        self._add_factory_setting_row(right, "当前状态", equip_badge, equip_colour)
        self._add_factory_setting_row(
            right, "制造公式",
            self._factory_formula_label(st.get("equip_formula") or "optic",
                                        FACTORY_EQUIP_FORMULAS_GUI))
        self._add_factory_setting_row(
            right, "五星保护", "自动保护五星装备")
        add_check(right, "保护全息 / 红点 / ACOG", vars_["equip_protect_holo_red_dot"])
        self._add_factory_setting_row(
            right, "目标数量",
            f"{st.get('equip_target_count', 1)}（{'保护目标累计' if st.get('equip_target_scope') == 'protected_hits' else '总制造产物'}）")
        disabled_reason_e = st.get("equip_disabled_reason")
        if disabled_reason_e:
            self._add_factory_setting_row(right, "自动关闭原因", str(disabled_reason_e), WARN)

        # ── Save / close actions ──
        def save_toggles() -> None:
            new_state = dict(st)
            new_state["doll_enabled"] = bool(vars_["doll_enabled"].get())
            new_state["equip_enabled"] = bool(vars_["equip_enabled"].get())
            new_state["equip_protect_holo_red_dot"] = bool(
                vars_["equip_protect_holo_red_dot"].get())
            # Clear auto-disable reasons when user manually re-enables.
            if new_state["doll_enabled"]:
                new_state.pop("doll_disabled_reason", None)
            if new_state["equip_enabled"]:
                new_state.pop("equip_disabled_reason", None)
            try:
                saved_path = self._save_factory_state_for_gui(new_state, state_path)
            except Exception as exc:
                messagebox.showerror("跟随模块制造", f"保存失败：{exc}",
                                     parent=self.follow_factory_window or self)
                return
            self._append_log(f"\n[GUI] 跟随模块制造设置已保存：{saved_path}\n")
            changes = []
            if new_state["doll_enabled"] != bool(st.get("doll_enabled")):
                changes.append(f"人形制造 → {'开启' if new_state['doll_enabled'] else '关闭'}")
            if new_state["equip_enabled"] != bool(st.get("equip_enabled")):
                changes.append(f"装备制造 → {'开启' if new_state['equip_enabled'] else '关闭'}")
            if new_state["equip_protect_holo_red_dot"] != bool(st.get("equip_protect_holo_red_dot")):
                changes.append(
                    f"全息/红点保护 → {'开启' if new_state['equip_protect_holo_red_dot'] else '关闭'}")
            summary = "；".join(changes) if changes else "无变化"
            messagebox.showinfo(
                "跟随模块制造",
                f"已保存。\n变更：{summary}\n\n后台守护进程会在下一次轮询时（约 45 秒内）读取新设置。",
                parent=self.follow_factory_window or self)
            self._refresh_follow_factory_settings_window()

        actions = self._card(body, fill=tk.X, pady=(8, 0))
        row = tk.Frame(actions, bg=CARD)
        row.pack(fill=tk.X, padx=12, pady=10)
        ttk.Button(row, text="保存修改", style="Accent.TButton",
                   command=save_toggles).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(row, text="刷新", style="Soft.TButton",
                   command=self._refresh_follow_factory_settings_window).pack(side=tk.LEFT, padx=8)
        ttk.Button(row, text="详细设置", style="Soft.TButton",
                   command=self._open_factory_settings_window).pack(side=tk.LEFT, padx=8)
        ttk.Button(row, text="关闭", style="Danger.TButton",
                   command=lambda: (self.follow_factory_window.destroy()
                                    if self.follow_factory_window else None)
                   ).pack(side=tk.RIGHT, padx=4)
        tk.Label(
            actions,
            text="说明：开启/关闭会直接写入配置文件，后台守护进程每 45 秒轮询一次。"
                 "如需修改公式、保护 ID 等详细参数，请点击【详细设置】或在 factory 模块内使用 -doll / -equip 命令。",
            bg=CARD, fg=MUTED, anchor=tk.W, justify=tk.LEFT,
            wraplength=840,
        ).pack(fill=tk.X, padx=12, pady=(0, 10))

    def _gun_type_name(self, type_id: object) -> str:
        mapping = {
            1: "HG 手枪",
            2: "SMG 冲锋枪",
            3: "RF 步枪",
            4: "AR 突击步枪",
            5: "MG 机枪",
            6: "SG 霰弹枪",
        }
        try:
            return mapping.get(int(type_id), str(type_id))
        except Exception:
            return str(type_id)

    def _load_gun_dictionary_entries(self) -> list[dict[str, object]]:
        """Load and merge gun.json / gun1.json for the factory protection dictionary.

        gun1.json often contains friendlier display names, while gun.json can contain
        a newer or larger set of rows.  Merge them by ID and keep both name/code fields
        searchable.
        """
        if self.gun_dict_entries is not None:
            return self.gun_dict_entries
        merged: dict[int, dict[str, object]] = {}
        for filename in ("gun.json", "gun1.json"):
            path = self.root_dir / "data" / filename
            if not path.exists():
                alt = find_resource_file(self.root_dir, "data", filename)
                if alt:
                    path = alt
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                self._append_log(f"\n[GUI] 读取 {filename} 失败：{exc}\n")
                continue
            if not isinstance(data, list):
                continue
            for row in data:
                if not isinstance(row, dict):
                    continue
                try:
                    gid = int(row.get("id"))
                except Exception:
                    continue
                old = merged.setdefault(gid, {"id": gid})
                # Prefer non-placeholder names from later files, but keep all values searchable.
                for key in ("en_name", "code", "name", "rank", "rank_display", "type", "develop_duration", "obtain_ids"):
                    val = row.get(key)
                    if val not in (None, ""):
                        old[key] = val
                names = set(str(old.get("_search_names", "")).split("\u0001")) if old.get("_search_names") else set()
                for key in ("id", "en_name", "code", "name"):
                    val = row.get(key)
                    if val not in (None, ""):
                        names.add(str(val))
                # A few common aliases used by the current factory defaults.
                alias_map = {
                    233: ["Px4", "Px4风暴", "Px4 Storm", "风暴"],
                    115: ["Suomi", "索米", "KP31", "索米 KP31"],
                }
                for alias in alias_map.get(gid, []):
                    names.add(alias)
                old["_search_names"] = "\u0001".join(sorted(n for n in names if n))
        entries = list(merged.values())
        entries.sort(key=lambda r: (int(r.get("type") or 99), -(int(r.get("rank_display") or r.get("rank") or 0)), int(r.get("id") or 0)))
        self.gun_dict_entries = entries
        return entries

    def _open_gun_dictionary_window(self) -> None:
        """Open a searchable T-Doll dictionary for finding protection IDs."""
        if self.gun_dict_window and self.gun_dict_window.winfo_exists():
            self.gun_dict_window.lift()
            return

        win = tk.Toplevel(self.module_window or self)
        self.gun_dict_window = win
        win.title("GFAM - 人形词典 / 保护 ID 查询")
        win.geometry("900x620")
        win.minsize(760, 500)
        win.configure(bg=BG)
        self._apply_window_icon(win)

        outer = tk.Frame(win, bg=BG, padx=12, pady=12)
        outer.pack(fill=tk.BOTH, expand=True)

        header = self._card(outer, fill=tk.X, pady=(0, 8))
        row = tk.Frame(header, bg=CARD)
        row.pack(fill=tk.X, padx=12, pady=10)
        if self._mascot_small:
            tk.Label(row, image=self._mascot_small, bg=CARD).pack(side=tk.LEFT, padx=(0, 8))
        title_col = tk.Frame(row, bg=CARD)
        title_col.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(title_col, text="人形词典 / 保护 ID 查询", bg=CARD, fg=TEXT, font=("Microsoft YaHei UI", 16, "bold")).pack(anchor=tk.W)
        tk.Label(title_col, text="支持按 ID、英文名、代号、常用别名模糊搜索；双击结果可复制 ID。", bg=CARD, fg=MUTED).pack(anchor=tk.W)

        search_card = self._card(outer, fill=tk.X, pady=(0, 8))
        srow = tk.Frame(search_card, bg=CARD)
        srow.pack(fill=tk.X, padx=12, pady=10)
        tk.Label(srow, text="搜索：", bg=CARD, fg=ACCENT_DARK, font=("Microsoft YaHei UI", 10, "bold")).pack(side=tk.LEFT, padx=(0, 6))
        search_var = tk.StringVar()
        search_entry = ttk.Entry(srow, textvariable=search_var)
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6), ipady=2)
        rank_var = tk.StringVar(value="全部星级")
        ttk.Combobox(srow, textvariable=rank_var, values=["全部星级", "6星", "5星", "4星", "3星", "2星"], width=10, state="readonly").pack(side=tk.LEFT, padx=4)
        type_var = tk.StringVar(value="全部枪种")
        ttk.Combobox(srow, textvariable=type_var, values=["全部枪种", "HG 手枪", "SMG 冲锋枪", "RF 步枪", "AR 突击步枪", "MG 机枪", "SG 霰弹枪"], width=14, state="readonly").pack(side=tk.LEFT, padx=4)

        table_card = self._card(outer, fill=tk.BOTH, expand=True, pady=(0, 8))
        self._section_title(table_card, "查询结果")
        table_inner = tk.Frame(table_card, bg=CARD)
        table_inner.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        columns = ("id", "name", "code", "rank", "type", "duration")
        tree = ttk.Treeview(table_inner, columns=columns, show="headings", selectmode="browse")
        headings = {
            "id": "保护ID",
            "name": "名称",
            "code": "代号",
            "rank": "星级",
            "type": "枪种",
            "duration": "建造时间",
        }
        widths = {"id": 90, "name": 210, "code": 160, "rank": 70, "type": 120, "duration": 100}
        for col in columns:
            tree.heading(col, text=headings[col])
            tree.column(col, width=widths[col], anchor=tk.CENTER if col in ("id", "rank", "duration") else tk.W)
        yscroll = ttk.Scrollbar(table_inner, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=yscroll.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)

        info_var = tk.StringVar(value="")
        info = tk.Label(outer, textvariable=info_var, bg=BG, fg=MUTED, anchor=tk.W)
        info.pack(fill=tk.X, pady=(0, 6))

        entries = self._load_gun_dictionary_entries()

        def fmt_duration(sec: object) -> str:
            try:
                v = int(sec)
            except Exception:
                return ""
            if v <= 0:
                return ""
            h, rem = divmod(v, 3600)
            m, _s = divmod(rem, 60)
            if h:
                return f"{h}:{m:02d}"
            return f"{m}分"

        def match(row: dict[str, object], q: str) -> bool:
            if not q:
                return True
            ql = q.lower().replace(" ", "")
            hay = " ".join(str(row.get(k, "")) for k in ("id", "en_name", "code", "name", "_search_names"))
            hay2 = hay.lower().replace(" ", "")
            return ql in hay2

        def refresh(*_args: object) -> None:
            q = search_var.get().strip()
            rank_filter = rank_var.get()
            type_filter = type_var.get()
            for item in tree.get_children():
                tree.delete(item)
            shown = 0
            for row in entries:
                rank = int(row.get("rank_display") or row.get("rank") or 0)
                type_name = self._gun_type_name(row.get("type"))
                if rank_filter != "全部星级":
                    try:
                        if rank != int(rank_filter.rstrip("星")):
                            continue
                    except Exception:
                        pass
                if type_filter != "全部枪种" and type_filter != type_name:
                    continue
                if not match(row, q):
                    continue
                name = str(row.get("en_name") or row.get("code") or row.get("name") or "")
                code = str(row.get("code") or "")
                tree.insert("", tk.END, values=(row.get("id", ""), name, code, f"{rank}星" if rank else "", type_name, fmt_duration(row.get("develop_duration"))))
                shown += 1
                if shown >= 500:
                    break
            info_var.set(f"共载入 {len(entries)} 条；当前显示 {shown} 条。提示：输入 Px4 / 风暴 / 索米 / Suomi / G11 / 233 等均可查询。")

        def copy_selected() -> None:
            sel = tree.selection()
            if not sel:
                messagebox.showinfo("人形词典", "请先选择一行。", parent=win)
                return
            values = tree.item(sel[0], "values")
            if not values:
                return
            gid = str(values[0])
            name = str(values[1]) if len(values) > 1 else ""
            win.clipboard_clear()
            win.clipboard_append(gid)
            self._append_log(f"\n[GUI] 已复制人形保护 ID：{gid}（{name}）。\n")
            info_var.set(f"已复制保护 ID：{gid}（{name}）")

        def insert_to_command_box() -> None:
            sel = tree.selection()
            if not sel:
                messagebox.showinfo("人形词典", "请先选择一行。", parent=win)
                return
            gid = str(tree.item(sel[0], "values")[0])
            self.command_var.set(gid)
            self._append_log(f"\n[GUI] 已将人形保护 ID {gid} 填入当前模块命令框。\n")
            try:
                self.command_entry.focus_set()
            except Exception:
                pass

        tree.bind("<Double-1>", lambda _e: copy_selected())
        search_var.trace_add("write", refresh)
        rank_var.trace_add("write", refresh)
        type_var.trace_add("write", refresh)

        btn_row = tk.Frame(outer, bg=BG)
        btn_row.pack(fill=tk.X)
        ttk.Button(btn_row, text="复制选中 ID", style="Accent.TButton", command=copy_selected).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_row, text="填入命令框", style="Soft.TButton", command=insert_to_command_box).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_row, text="关闭", style="Soft.TButton", command=win.destroy).pack(side=tk.RIGHT, padx=6)

        refresh()
        search_entry.focus_set()

    def _send_module_command_sequence(self, commands: list[str], delay_ms: int = 180, summary: str | None = None) -> None:
        """Send a short UI command sequence with one compact GUI log line.

        The backend still receives the same commands. GUI-level command echo is
        collapsed so EPA setting/stage operations do not flood the log with one
        line per tiny option.
        """
        clean = [str(cmd) for cmd in commands if str(cmd or "")]
        if not clean:
            return
        readable = " -> ".join("<ENTER>" if c == "\n" else c for c in clean)
        if summary:
            self._append_log(f"\n[GUI] {summary}：{readable}\n")

        _epa_seq_aborted = [False]  # mutable flag for closure

        def _epa_phase_ok(cmd_index: int) -> bool:
            """Return False if EPA backend is in an unexpected phase (error/retry state)."""
            if getattr(self, "current_module_key", None) != "epa":
                return True
            phase = getattr(self, "epa_gui_phase", "unknown")
            # Commands after -a (index 1+) expect the module to have progressed
            # past need_index. If still at need_index or mode_prompt, the -a
            # likely failed (e.g. team composition mismatch) and remaining
            # commands would land on the wrong prompt.
            if cmd_index >= 2 and phase in ("need_index", "mode_prompt"):
                if not _epa_seq_aborted[0]:
                    _epa_seq_aborted[0] = True
                    self._append_log(
                        f"\n[GUI] EPA 后端处于 {phase} 状态，已中止剩余命令序列。"
                        f"请修正问题后重新操作。\n"
                    )
                return False
            return True

        for i, cmd in enumerate(clean):
            self.after(i * delay_ms, lambda c=cmd, idx=i: (
                _epa_phase_ok(idx) and self._module_send_command(c, log_send=False)
            ))

    def _set_epa_gui_phase(self, phase: str) -> None:
        """Remember the current EPA prompt phase for safe GUI command routing.

        This is intentionally lightweight and GUI-only.  It prevents the settings
        popup from sending stage commands into the earlier mode prompt, which can
        otherwise make the backend start with the default mission and an empty
        dashboard target.
        """
        if self.current_module_key != "epa":
            return
        if phase and phase != self.epa_gui_phase:
            self.epa_gui_phase = phase
            labels = {
                "mode_prompt": "等待模式设置",
                "need_index": "等待获取/配置 -a",
                "indexing": "正在解析 Index",
                "stage_difficulty": "等待选择难度",
                "stage_stage": "等待选择关卡",
                "stage_target": "等待选择目标",
                "run_options": "等待运行选项",
                "running": "EPA 运行中",
                "main_menu": "EPA 菜单",
            }
            self.module_status_var.set(labels.get(phase, phase))

    def _epa_smart_stage_sequence(self, mode_seq: list[str], stage_seq: list[str], with_go: bool) -> tuple[list[str], str]:
        """Build a safe EPA sequence from the current observed prompt phase."""
        phase = getattr(self, "epa_gui_phase", "unknown")
        if phase == "mode_prompt":
            return mode_seq + ["-a"] + stage_seq, "EPA 模式+Index+关卡一键序列已发送"
        if phase in ("need_index", "main_menu", "unknown"):
            return ["-a"] + stage_seq, "EPA Index+关卡一键序列已发送"
        if phase == "stage_difficulty":
            return stage_seq, "EPA 关卡一键序列已发送"
        if phase == "stage_stage":
            return stage_seq[1:], "EPA 关卡一键序列已发送"
        if phase == "stage_target":
            return stage_seq[2:], "EPA 目标一键序列已发送"
        if phase == "run_options":
            return (["-go"] if with_go else []), "EPA 使用当前目标一键运行"
        if phase == "running":
            return [], "EPA 正在运行，未发送关卡切换命令"
        return ["-a"] + stage_seq, "EPA Index+关卡一键序列已发送"

    def _load_epa_stage_catalog_for_gui(self) -> dict[str, dict[str, dict[str, str]]]:
        """Load EPA stage/target labels from the local epa_plus.py source.

        This is GUI-only display data. It reads the local module file and does
        not import or execute the EPA backend, so it cannot start proxies or run
        network logic. If parsing fails, the dialog falls back to the stable
        A-10 baseline target list.
        """
        fallback = {
            "普通": {
                "A-10": {
                    "-1": "SL8&K3",
                    "-2": "韦伯利&T-CMS",
                    "-3": "R5&MP41",
                    "-4": "M82&CPS-12",
                    "-5": "CF05&VP70",
                }
            }
        }
        path = find_resource_file(self.root_dir, "modules", "epa_plus.py")
        if not path:
            return fallback
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            return fallback
        raw_tables: dict[str, object] = {}
        wanted = {"NORMAL_STAGE_DATA", "EMERGENCY_STAGE_DATA", "NIGHT_STAGE_DATA"}
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in wanted:
                    try:
                        raw_tables[target.id] = ast.literal_eval(node.value)
                    except Exception:
                        pass
        name_map = {
            "普通": raw_tables.get("NORMAL_STAGE_DATA"),
            "紧急": raw_tables.get("EMERGENCY_STAGE_DATA"),
            "夜战": raw_tables.get("NIGHT_STAGE_DATA"),
        }
        catalog: dict[str, dict[str, dict[str, str]]] = {}
        for difficulty, table in name_map.items():
            if not isinstance(table, dict):
                continue
            stage_map: dict[str, dict[str, str]] = {}
            for stage, stage_data in table.items():
                if not isinstance(stage, str) or not isinstance(stage_data, dict):
                    continue
                options = stage_data.get("OPTIONS")
                if not isinstance(options, dict):
                    continue
                targets: dict[str, str] = {}
                for key, item in options.items():
                    if not isinstance(key, str) or not isinstance(item, dict):
                        continue
                    label = str(item.get("label", key))
                    targets[key] = label
                if targets:
                    stage_map[stage] = targets
            if stage_map:
                catalog[difficulty] = stage_map
        return catalog or fallback

    def _open_epa_settings_window(self, module_key: str = "epa") -> None:
        """Unified EPA / 13-4 settings popup with JSON persistence.

        The same popup adapts to *module_key* so each module window gets a
        tailored settings page while sharing one JSON file for persistence.
        """
        parent = self.module_window if self.module_window and self.module_window.winfo_exists() else self
        win = tk.Toplevel(parent)

        _titles = {"epa": "EPA 设置", "13-4": "13-4 设置"}
        win.title(_titles.get(module_key, "设置"))
        win.geometry("720x860")
        win.minsize(660, 720)
        win.configure(bg=BG)
        self._apply_window_icon(win)
        try:
            win.transient(parent)
            win.grab_set()
        except Exception:
            pass

        # ── Load persisted settings ──────────────────────────────────
        st, state_path, _loaded = self._load_epa_state_for_gui()

        outer = tk.Frame(win, bg=BG, padx=12, pady=12)
        outer.pack(fill=tk.BOTH, expand=True)

        # ── Header ───────────────────────────────────────────────────
        header = self._card(outer, fill=tk.X, pady=(0, 10))
        tk.Label(
            header, text=_titles.get(module_key, "设置"),
            bg=CARD, fg=TEXT, font=("Microsoft YaHei UI", 15, "bold"),
        ).pack(anchor=tk.W, padx=12, pady=(10, 2))
        _descs = {
            "epa": "EPA 打捞/练级运行参数，保存后下次启动自动加载。",
            "13-4": "13-4 练级/资源模式运行参数，保存后下次启动自动加载。",
        }
        tk.Label(
            header, text=_descs.get(module_key, ""),
            bg=CARD, fg=MUTED, anchor=tk.W,
        ).pack(fill=tk.X, padx=12, pady=(0, 10))

        # ── Mode options card ────────────────────────────────────────
        mode_card = self._card(outer, fill=tk.X, pady=(0, 10))
        self._section_title(mode_card, "运行模式")
        form = tk.Frame(mode_card, bg=CARD)
        form.pack(fill=tk.X, padx=12, pady=(0, 8))

        def option_row(row, title, var, options):
            tk.Label(form, text=title, bg=CARD, fg=ACCENT_DARK,
                     font=("Microsoft YaHei UI", 10, "bold")).grid(row=row, column=0, sticky="w", pady=6)
            box = tk.Frame(form, bg=CARD)
            box.grid(row=row, column=1, sticky="ew", pady=6)
            for lbl, val in options:
                ttk.Radiobutton(box, text=lbl, value=val, variable=var,
                                style="GFAM.TRadiobutton").pack(side=tk.LEFT, padx=(0, 12))

        schedule_var = tk.StringVar(value=str(st.get("schedule", "full")))
        train_count_var = tk.StringVar(value=str(st.get("train_count", 1)))
        max_var = tk.StringVar(
            value="-stopmax" if st.get("stop_on_max", False) else "-keepmax")

        _current_row = 0
        if module_key == "epa":
            team_var = tk.StringVar(
                value="-team" if st.get("mode", "single") == "team" else "-single")
            option_row(_current_row, "编队模式", team_var,
                       [("练级五人 -team", "-team"), ("打捞单人 -single", "-single")])
            _current_row += 1
            option_row(_current_row, "调度方式", schedule_var,
                       [("调度 -full", "-full"), ("均衡 -equal", "-equal")])
            _current_row += 1
        elif module_key == "13-4":
            mode_134_var = tk.StringVar(
                value=str(st.get("mode_134", "-134train")))
            option_row(_current_row, "运行模式", mode_134_var,
                       [("五战练级 -134train", "-134train"),
                        ("资源打捞 -134", "-134")])
            _current_row += 1
            option_row(_current_row, "调度方式", schedule_var,
                       [("调度 -full", "-full"), ("均衡 -equal", "-equal")])
            _current_row += 1

        option_row(_current_row, "满级策略", max_var,
                   [("满级不停 -keepmax", "-keepmax"),
                    ("满级停机 -stopmax", "-stopmax")])
        _current_row += 1

        # Train count row (only for EPA / 13-4)
        if module_key in ("epa", "13-4"):
            tk.Label(form, text="练级队数", bg=CARD, fg=ACCENT_DARK,
                     font=("Microsoft YaHei UI", 10, "bold")).grid(
                row=_current_row, column=0, sticky="w", pady=4)
            count_box = tk.Frame(form, bg=CARD)
            count_box.grid(row=_current_row, column=1, sticky="w", pady=4)
            ttk.Spinbox(count_box, from_=1, to=10,
                        textvariable=train_count_var, width=6).pack(side=tk.LEFT)
            _hint = ("仅 -team 模式会发送；single 模式忽略" if module_key == "epa"
                     else "仅练级模式有效；资源模式固定 2 队")
            tk.Label(count_box, text=_hint, bg=CARD, fg=MUTED).pack(
                side=tk.LEFT, padx=8)
            _current_row += 1

        # Run options that only matter for EPA / 13-4
        if module_key in ("epa", "13-4"):
            drop_var = tk.BooleanVar(value=bool(st.get("stop_on_drop", False)))
            prot_var = tk.BooleanVar(value=bool(st.get("filter_protection", True)))
            chk_box = tk.Frame(form, bg=CARD)
            chk_box.grid(row=_current_row, column=0, columnspan=2,
                         sticky="w", pady=4)
            tk.Checkbutton(chk_box, text="目标达成停机 (-stopdrop)",
                            variable=drop_var, bg=CARD, fg=TEXT,
                            selectcolor=CARD, activebackground=CARD,
                            activeforeground=TEXT).pack(side=tk.LEFT, padx=(0, 16))
            tk.Checkbutton(chk_box, text="过滤保护 (-protecton)",
                            variable=prot_var, bg=CARD, fg=TEXT,
                            selectcolor=CARD, activebackground=CARD,
                            activeforeground=TEXT).pack(side=tk.LEFT)
            _current_row += 1

        # Equip auto-lock only for EPA night battle
        equip_lock_var = tk.BooleanVar(
            value=bool(st.get("equip_auto_lock", True)))
        if module_key == "epa":
            chk_box2 = tk.Frame(form, bg=CARD)
            chk_box2.grid(row=_current_row, column=0, columnspan=2,
                          sticky="w", pady=2)
            tk.Checkbutton(chk_box2, text="夜战目标装备自动上锁",
                            variable=equip_lock_var, bg=CARD, fg=TEXT,
                            selectcolor=CARD, activebackground=CARD,
                            activeforeground=TEXT).pack(side=tk.LEFT)
            _current_row += 1

        form.columnconfigure(1, weight=1)

        # ── Stage selection card (EPA only) ─────────────────────────
        difficulty_var = tk.StringVar(value=str(st.get("difficulty", "普通")))
        stage_var = tk.StringVar(value=str(st.get("stage", "A-10")))
        target_var = tk.StringVar(value="")
        stage_combo = None
        target_combo = None

        if module_key == "epa":
            stage_card = self._card(outer, fill=tk.X, pady=(0, 10))
            self._section_title(stage_card, "关卡选择")
            stage_form = tk.Frame(stage_card, bg=CARD)
            stage_form.pack(fill=tk.X, padx=12, pady=(0, 10))

            catalog = self._load_epa_stage_catalog_for_gui()
            difficulty_order = ([x for x in ("普通", "紧急", "夜战")
                                 if x in catalog]
                                or list(catalog.keys()))
            if difficulty_var.get() not in difficulty_order and difficulty_order:
                difficulty_var.set(difficulty_order[0])

            def target_display(cmd: str, label: str) -> str:
                return f"{cmd} : {label}"

            def selected_target_cmd() -> str:
                text = target_var.get().strip()
                if not text:
                    return ""
                return text.split()[0]

            def refresh_targets() -> None:
                stage = stage_var.get()
                targets = catalog.get(difficulty_var.get(), {}).get(stage, {})
                values = [target_display(k, v) for k, v in targets.items()]
                if target_combo is not None:
                    target_combo.configure(values=values)
                if values:
                    saved_target = st.get("target", "")
                    match = [v for v in values
                             if v.startswith(str(saved_target) + " ")]
                    if match and target_var.get() not in values:
                        target_var.set(match[0])
                    elif target_var.get() not in values:
                        target_var.set(values[0])
                elif not values:
                    target_var.set("")

            def refresh_stages(*_args: object) -> None:
                stages = list(catalog.get(difficulty_var.get(), {}).keys())
                if stage_combo is not None:
                    stage_combo.configure(values=stages)
                preferred = ("A-10"
                             if difficulty_var.get() == "普通" and "A-10" in stages
                             else (stages[0] if stages else ""))
                if stage_var.get() not in stages:
                    stage_var.set(preferred)
                refresh_targets()

            tk.Label(stage_form, text="难度", bg=CARD, fg=ACCENT_DARK,
                     font=("Microsoft YaHei UI", 10, "bold")).grid(
                row=0, column=0, sticky="w", pady=5)
            diff_combo = ttk.Combobox(
                stage_form, textvariable=difficulty_var,
                values=difficulty_order, state="readonly", width=12)
            diff_combo.grid(row=0, column=1, sticky="ew", padx=(8, 16), pady=5)
            diff_combo.bind("<<ComboboxSelected>>", refresh_stages)

            tk.Label(stage_form, text="关卡", bg=CARD, fg=ACCENT_DARK,
                     font=("Microsoft YaHei UI", 10, "bold")).grid(
                row=0, column=2, sticky="w", pady=5)
            stage_combo = ttk.Combobox(
                stage_form, textvariable=stage_var,
                state="readonly", width=12)
            stage_combo.grid(row=0, column=3, sticky="ew", padx=(8, 0), pady=5)
            stage_combo.bind("<<ComboboxSelected>>",
                             lambda _e: refresh_targets())

            tk.Label(stage_form, text="目标", bg=CARD, fg=ACCENT_DARK,
                     font=("Microsoft YaHei UI", 10, "bold")).grid(
                row=1, column=0, sticky="w", pady=5)
            target_combo = ttk.Combobox(
                stage_form, textvariable=target_var, state="readonly")
            target_combo.grid(row=1, column=1, columnspan=3,
                              sticky="ew", padx=(8, 0), pady=5)
            for i in (1, 3):
                stage_form.columnconfigure(i, weight=1)
            refresh_stages()
        else:
            # 13-4 has no stage selection; keep a dummy selected_target_cmd
            def selected_target_cmd() -> str:
                return ""

        # ── Advanced settings card ──────────────────────────────────
        adv_card = self._card(outer, fill=tk.X, pady=(0, 10))
        self._section_title(adv_card, "高级参数")
        adv_form = tk.Frame(adv_card, bg=CARD)
        adv_form.pack(fill=tk.X, padx=12, pady=(0, 8))

        auto_stop_var = tk.StringVar(
            value=str(st.get("auto_stop_minutes", 0)))

        tk.Label(adv_form, text="运行时长限制", bg=CARD, fg=ACCENT_DARK,
                 font=("Microsoft YaHei UI", 10, "bold")).grid(
            row=0, column=0, sticky="w", pady=4)
        t_box = tk.Frame(adv_form, bg=CARD)
        t_box.grid(row=0, column=1, sticky="w", pady=4)
        ttk.Spinbox(t_box, from_=0, to=1440,
                    textvariable=auto_stop_var, width=6).pack(side=tk.LEFT)
        tk.Label(t_box, text="分钟（0 = 不限制，到时自动安全停止）",
                 bg=CARD, fg=MUTED).pack(side=tk.LEFT, padx=8)

        if module_key == "epa":
            equip_retire_var = tk.BooleanVar(
                value=bool(st.get("enable_equip_retire", True)))
            tk.Checkbutton(adv_form, text="装备自动拆解",
                            variable=equip_retire_var, bg=CARD, fg=TEXT,
                            selectcolor=CARD, activebackground=CARD,
                            activeforeground=TEXT).grid(
                row=1, column=0, columnspan=2, sticky="w", pady=2)
            rank_var = tk.StringVar(
                value=str(st.get("equip_retire_max_rank", 4)))
            tk.Label(adv_form, text="拆解星级上限", bg=CARD, fg=ACCENT_DARK,
                     font=("Microsoft YaHei UI", 10, "bold")).grid(
                row=2, column=0, sticky="w", pady=4)
            r_box = tk.Frame(adv_form, bg=CARD)
            r_box.grid(row=2, column=1, sticky="w", pady=4)
            ttk.Spinbox(r_box, from_=2, to=5,
                        textvariable=rank_var, width=4).pack(side=tk.LEFT)
            tk.Label(r_box, text="≤ 此星级的装备可自动拆解",
                     bg=CARD, fg=MUTED).pack(side=tk.LEFT, padx=8)

        adv_form.columnconfigure(1, weight=1)

        # ── Save helper & action buttons ─────────────────────────────
        action_card = self._card(outer, fill=tk.X, pady=(0, 10))
        self._section_title(action_card, "常用动作")
        actions = tk.Frame(action_card, bg=CARD)
        actions.pack(fill=tk.X, padx=10, pady=(0, 10))

        def save_settings() -> None:
            new_st: dict[str, object] = {
                "module": module_key,
                "schedule": schedule_var.get().lstrip("-"),
                "train_count": int(train_count_var.get() or 1),
                "stop_on_max": max_var.get() == "-stopmax",
                "filter_protection": prot_var.get()
                    if module_key in ("epa", "13-4") else True,
                "equip_auto_lock": equip_lock_var.get(),
                "auto_stop_minutes": int(auto_stop_var.get() or 0),
            }
            if module_key == "epa":
                new_st["mode"] = team_var.get().lstrip("-")
                new_st["difficulty"] = difficulty_var.get()
                new_st["stage"] = stage_var.get()
                new_st["target"] = selected_target_cmd()
                new_st["stop_on_drop"] = drop_var.get()
                new_st["enable_equip_retire"] = equip_retire_var.get()
                new_st["equip_retire_max_rank"] = int(rank_var.get() or 4)
            elif module_key == "13-4":
                new_st["mode_134"] = mode_134_var.get()
                new_st["stop_on_drop"] = drop_var.get()
            path = self._save_epa_state_for_gui(new_st, state_path)
            self._append_log(
                f"\n[GUI] 设置已保存到 {path.name}\n")

        def mode_sequence() -> list[str]:
            if module_key == "epa":
                if team_var.get() == "-team":
                    count = train_count_var.get().strip() or "1"
                    try:
                        count_i = max(1, min(10, int(count)))
                        count = str(count_i)
                        train_count_var.set(count)
                    except Exception:
                        count = "1"
                        train_count_var.set(count)
                    return ["-team", schedule_var.get(), count]
                return ["-single"]
            elif module_key == "13-4":
                if mode_134_var.get() == "-134train":
                    count = train_count_var.get().strip() or "1"
                    return [mode_134_var.get(), schedule_var.get(), count]
                return [mode_134_var.get()]
            return []

        def stage_sequence(with_go: bool = False) -> list[str]:
            if module_key == "13-4":
                return []
            seq = [difficulty_var.get(), stage_var.get(),
                   selected_target_cmd()]
            if with_go:
                seq.append("-go")
            return [x for x in seq if x]

        def send_stage(with_go: bool = False) -> None:
            stage_seq = stage_sequence(with_go)
            if with_go:
                seq, summary = self._epa_smart_stage_sequence(
                    mode_sequence(), stage_seq, with_go=True)
                if not seq:
                    self._append_log(f"\n[GUI] {summary}。\n")
                    return
                self._send_module_command_sequence(
                    seq, delay_ms=220, summary=summary)
                try:
                    win.destroy()
                except Exception:
                    pass
                return
            self._send_module_command_sequence(
                stage_seq, summary="关卡选择已发送")

        _entry_map = {"epa": "1", "13-4": "2"}

        def apply_epa_config(run_after=False):
            save_settings()
            mode_seq = mode_sequence()
            stage_seq = stage_sequence(False)
            max_seq = [max_var.get()]

            if run_after:
                if module_key == "13-4":
                    seq = mode_seq + max_seq + ["-keepdrop", "-y", "-r"]
                    self._send_module_command_sequence(
                        seq, delay_ms=220,
                        summary="13-4 当前配置已发送并启动运行")
                else:
                    seq, summary = self._epa_smart_stage_sequence(
                        mode_seq, stage_seq, with_go=False)
                    seq = list(seq) + max_seq + ["-keepdrop", "-y", "-r"]
                    self._send_module_command_sequence(
                        seq, delay_ms=220,
                        summary="EPA 当前配置已发送并启动运行")
                try:
                    win.destroy()
                except Exception:
                    pass
            else:
                self._send_module_command_sequence(
                    mode_seq,
                    summary=f"{_titles.get(module_key, '')} 模式设置已发送")

        primary_buttons = [
            ("保存设置", save_settings, "Accent.TButton"),
            ("应用当前配置", lambda: apply_epa_config(False),
             "Accent.TButton"),
            ("按当前配置运行", lambda: apply_epa_config(True),
             "Accent.TButton"),
            ("重新进入",
             lambda: self._module_send_command(_entry_map.get(module_key, "1")),
             "Soft.TButton"),
        ]
        for i, (label, cb, style) in enumerate(primary_buttons):
            ttk.Button(actions, text=label, style=style, command=cb).grid(
                row=i // 4, column=i % 4, sticky="ew", padx=4, pady=4)
        for i in range(4):
            actions.columnconfigure(i, weight=1)

        # ── Hint card ────────────────────────────────────────────────
        hint = self._card(outer, fill=tk.X, pady=(0, 8))
        _hints = {
            "epa": "保存设置：写入 JSON 文件供下次启动自动加载。按当前配置运行：自动适配 EPA 状态机并启动。",
            "13-4": "保存设置：写入 JSON 文件供下次启动自动加载。按当前配置运行：发送 13-4 配置并启动。",
        }
        tk.Label(
            hint, text=_hints.get(module_key, ""),
            bg=CARD, fg=MUTED, anchor=tk.W, wraplength=660,
        ).pack(fill=tk.X, padx=12, pady=8)

        # ── Bottom bar ───────────────────────────────────────────────
        bottom = tk.Frame(outer, bg=BG)
        bottom.pack(fill=tk.X)
        ttk.Button(bottom, text="获取/配置 -a", style="Soft.TButton",
                   command=lambda: self._module_send_command("-a")).pack(
            side=tk.LEFT, padx=(0, 6))
        ttk.Button(bottom, text="发送回车", style="Soft.TButton",
                   command=lambda: self._module_send_command("\n")).pack(
            side=tk.LEFT, padx=(0, 6))
        ttk.Button(bottom, text="关闭", style="Soft.TButton",
                   command=win.destroy).pack(side=tk.RIGHT)

    def _open_smart_settings_window(self) -> None:
        """Smart 一键打捞设置弹窗：选择计划类型，保存后自动生成计划。"""
        parent = self.module_window if self.module_window and self.module_window.winfo_exists() else self
        win = tk.Toplevel(parent)
        win.title("Smart 设置")
        win.geometry("480x340")
        win.minsize(420, 300)
        win.configure(bg=BG)
        self._apply_window_icon(win)
        try:
            win.transient(parent)
            win.grab_set()
        except Exception:
            pass

        # Load current plan type from EPA state file
        st, state_path, _loaded = self._load_epa_state_for_gui()
        current_plan = str(st.get("smart_plan_type", "gun"))

        outer = tk.Frame(win, bg=BG, padx=12, pady=12)
        outer.pack(fill=tk.BOTH, expand=True)

        header = self._card(outer, fill=tk.X, pady=(0, 10))
        tk.Label(header, text="Smart 设置", bg=CARD, fg=TEXT,
                 font=("Microsoft YaHei UI", 15, "bold")).pack(anchor=tk.W, padx=12, pady=(10, 2))
        tk.Label(header, text="选择一键打捞计划类型，保存后自动生成计划。",
                 bg=CARD, fg=MUTED, anchor=tk.W).pack(fill=tk.X, padx=12, pady=(0, 10))

        body = self._card(outer, fill=tk.X, pady=(0, 10))
        self._section_title(body, "计划类型")
        form = tk.Frame(body, bg=CARD)
        form.pack(fill=tk.X, padx=12, pady=(0, 10))

        plan_var = tk.StringVar(value=current_plan)
        tk.Label(form, text="打捞类型", bg=CARD, fg=ACCENT_DARK,
                 font=("Microsoft YaHei UI", 10, "bold")).grid(row=0, column=0, sticky="w", pady=6)
        radio_box = tk.Frame(form, bg=CARD)
        radio_box.grid(row=0, column=1, sticky="ew", pady=6)
        ttk.Radiobutton(radio_box, text="人形一键 -gun（普通/紧急）", value="gun",
                        variable=plan_var, style="GFAM.TRadiobutton").pack(side=tk.LEFT, padx=(0, 12))
        ttk.Radiobutton(radio_box, text="装备一键 -equip（夜战）", value="equip",
                        variable=plan_var, style="GFAM.TRadiobutton").pack(side=tk.LEFT)
        form.columnconfigure(1, weight=1)

        hint = self._card(outer, fill=tk.X, pady=(0, 10))
        tk.Label(hint, text="保存后会自动选择计划类型、生成计划（-r）、确认执行（-run）并开始运行（-go），全流程一键完成。",
                 bg=CARD, fg=MUTED, anchor=tk.W, wraplength=440).pack(fill=tk.X, padx=12, pady=8)

        bottom = tk.Frame(outer, bg=BG)
        bottom.pack(fill=tk.X)

        def save_and_generate():
            chosen = plan_var.get()
            # Persist plan type to EPA state file
            new_st = dict(st)
            new_st["module"] = "smart"
            new_st["smart_plan_type"] = chosen
            self._save_epa_state_for_gui(new_st, state_path)
            # Mark settings as applied
            self._smart_settings_applied = True
            # Full sequence: plan type → generate plan → confirm execution → skip menus & run
            plan_cmd = "-gun" if chosen == "gun" else "-equip"
            seq = [plan_cmd, "-r", "-run", "-go"]
            label = "人形一键" if chosen == "gun" else "装备一键"
            self._send_module_command_sequence(
                seq, delay_ms=350,
                summary=f"Smart 设置已保存（{label}），正在生成计划并启动运行")
            self._append_log(f"\n[GUI] Smart 计划类型已保存为 {label}，已发送 -r → -run → -go 全流程。\n")
            try:
                win.destroy()
            except Exception:
                pass

        ttk.Button(bottom, text="保存并一键运行", style="Accent.TButton",
                   command=save_and_generate).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(bottom, text="关闭", style="Soft.TButton",
                   command=win.destroy).pack(side=tk.RIGHT)

    def _module_send_command(self, cmd: str, log_send: bool = True) -> None:
        if cmd == "__epa_settings__":
            self._open_epa_settings_window("epa")
            return
        if cmd == "__134_settings__":
            self._open_epa_settings_window("13-4")
            return
        if cmd == "__smart_settings__":
            self._open_smart_settings_window()
            return
        if cmd == "__quick_doll__":
            self._open_quick_build_settings_window("doll")
            return
        if cmd == "__quick_equip__":
            self._open_quick_build_settings_window("equip")
            return
        if cmd == "__gun_dict__":
            self._open_gun_dictionary_window()
            return
        if cmd == "__factory_settings__":
            self._open_factory_settings_window()
            return
        if cmd == "__follow_factory_settings__":
            self._open_follow_factory_settings_window()
            return
        # Avoid unsafe generic "-back" shortcuts.  Several GFAM modules only accept
        # -back in a specific submenu; when sent from the top-level module prompt it
        # becomes an invalid input and can desynchronize the GUI state.  Keep manual
        # input available for advanced use, but do not send it from shortcut buttons.
        if str(cmd).strip() == "-back":
            if log_send:
                self._append_log("\n[GUI] 已取消发送快捷 -back：该命令只在部分子菜单有效。需要时请在手动命令框确认当前提示符后自行输入。\n")
            return
        # Enter means send a raw newline instead of stripping it to empty.
        if cmd == "\n":
            self.send_raw("\n")
            if log_send:
                self._append_log("\n[GUI -> GFAM] <ENTER>\n")
            return
        if cmd == "-E":
            self._return_from_module()
            return
        if self.module_entering and not self.module_ready:
            self.pending_module_cmds.append(cmd)
            if log_send:
                self._append_log(f"\n[GUI] 模块仍在进入中，命令已排队：{cmd}\n")
            return
        self.send_command(cmd, log_send=log_send)

    def _close_module_window(self, send_back: bool = False) -> None:
        if send_back:
            self._send_command_if_running("-E")
        if self.module_window and self.module_window.winfo_exists():
            try:
                self.module_window.destroy()
            except Exception:
                pass
        self.module_window = None
        self.current_module_key = None
        self.current_module_title = None
        self.module_entering = False
        self.module_ready = False
        self.pending_module_cmds.clear()
        self.module_command_buttons = []
        self.module_status_var.set("模块未进入")
        self.deiconify()
        if not self.main_ui_shown:
            self._show_main_ui()
        else:
            # Rebuild the main window so its log widget becomes active again.
            self._clear_widgets()
            self._build_main_ui()
        self._append_log("\n[GUI] 已返回 GFAM 主界面窗口。\n")

    def _build_main_ui(self) -> None:
        outer = tk.Frame(self, bg=BG, padx=12, pady=12)
        outer.pack(fill=tk.BOTH, expand=True)

        header = self._card(outer, fill=tk.X, pady=(0, 10))
        hrow = tk.Frame(header, bg=CARD)
        hrow.pack(fill=tk.X, padx=12, pady=10)
        if self._mascot_small:
            tk.Label(hrow, image=self._mascot_small, bg=CARD).pack(side=tk.LEFT, padx=(0, 10))
        title_col = tk.Frame(hrow, bg=CARD)
        title_col.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(title_col, text="少女全自动 GFAM", bg=CARD, fg=TEXT, font=("Microsoft YaHei UI", 17, "bold")).pack(anchor=tk.W)
        tk.Label(title_col, text="GUI Launcher · 后台运行 · 模块快捷入口", bg=CARD, fg=MUTED).pack(anchor=tk.W)
        tk.Label(hrow, textvariable=self.status_var, bg=CARD, fg=SUCCESS, font=("Microsoft YaHei UI", 10, "bold")).pack(side=tk.RIGHT, padx=10)
        tk.Checkbutton(hrow, text="自动滚动", variable=self.autoscroll_var, bg=CARD, fg=TEXT, selectcolor=CARD, activebackground=CARD, activeforeground=TEXT).pack(side=tk.RIGHT)
        tk.Checkbutton(hrow, text="彩色日志", variable=self.log_color_var, bg=CARD, fg=TEXT, selectcolor=CARD, activebackground=CARD, activeforeground=TEXT, command=self._restore_log_text).pack(side=tk.RIGHT, padx=(0, 8))
        tk.Checkbutton(hrow, text="精简日志", variable=self.compact_log_var, bg=CARD, fg=TEXT, selectcolor=CARD, activebackground=CARD, activeforeground=TEXT).pack(side=tk.RIGHT, padx=(0, 8))

        modules = self._card(outer, fill=tk.X, pady=(0, 10))
        self._section_title(modules, "功能模块快捷入口（点击后会打开对应模块窗口）")
        grid = tk.Frame(modules, bg=CARD)
        grid.pack(fill=tk.X, padx=10, pady=(0, 10))
        self._make_module_grid(grid, MODULE_BUTTONS, 5)

        log_card = self._card(outer, fill=tk.BOTH, expand=True, pady=(0, 8))
        self._section_title(log_card, "日志区 / 交互输出")
        log_inner = tk.Frame(log_card, bg=CARD)
        log_inner.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        self.log_text = tk.Text(log_inner, wrap=tk.WORD, font=("Consolas", 10), undo=False, bg=LOG_BG, fg=LOG_FG, relief=tk.FLAT)
        yscroll = ttk.Scrollbar(log_inner, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=yscroll.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._restore_log_text()

        bottom = tk.Frame(outer, bg=BG)
        bottom.pack(fill=tk.X)
        self.command_entry = ttk.Entry(bottom, textvariable=self.command_var)
        self.command_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.command_entry.bind("<Return>", lambda _e: self.send_entry())
        ttk.Button(bottom, text="发送", style="Accent.TButton", command=self.send_entry).pack(side=tk.LEFT, padx=3)
        ttk.Button(bottom, text="发送回车", style="Soft.TButton", command=lambda: self.send_raw("\n")).pack(side=tk.LEFT, padx=3)
        ttk.Button(bottom, text="清空日志", style="Soft.TButton", command=self.clear_log).pack(side=tk.LEFT, padx=3)
        ttk.Button(bottom, text="保存日志", style="Soft.TButton", command=self.save_log).pack(side=tk.LEFT, padx=3)
        ttk.Button(bottom, text="打开目录", style="Soft.TButton", command=self.open_root_dir).pack(side=tk.LEFT, padx=3)
        ttk.Button(bottom, text="停止进程", style="Danger.TButton", command=self.stop_process).pack(side=tk.LEFT, padx=3)

    def _configure_log_tags(self) -> None:
        if not self.log_text:
            return
        if getattr(self, '_tags_configured', False):
            return
        self.log_text.tag_configure("default", foreground=LOG_FG)
        for tag, color in ANSI_TAG_COLORS.items():
            self.log_text.tag_configure(tag, foreground=color)
        self.log_text.tag_configure("log_bold", font=("Consolas", 10, "bold"))
        self._tags_configured = True

    def _restore_log_text(self) -> None:
        if not self.log_text:
            return
        self._configure_log_tags()
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        if self.log_color_var.get() and self.log_history_segments:
            for part, tag in self.log_history_segments:
                if not part:
                    continue
                if tag:
                    self.log_text.insert(tk.END, part, tag)
                else:
                    self.log_text.insert(tk.END, part)
        else:
            self.log_text.insert(tk.END, "".join(self.log_history))
        if self.autoscroll_var.get():
            self.log_text.see(tk.END)
        self.log_text.configure(state=tk.NORMAL)

    # ---------- process ----------
    def _has_cmd(self, name: str) -> bool:
        """Check if a command is available in PATH (PyInstaller-safe)."""
        try:
            return shutil.which(name) is not None
        except Exception:
            return False

    def _get_missing_deps(self) -> list:
        """Return list of (label, winget_pkg_id) for missing runtime deps."""
        missing = []
        if not self._has_cmd("node"):
            missing.append(("Node.js", "OpenJS.NodeJS.LTS"))
        if not (self._has_cmd("python") or self._has_cmd("py")):
            missing.append(("Python 3", "Python.Python.3.11"))
        return missing

    def _prompt_install_deps(self, missing: list) -> bool:
        """Show popup for missing deps. Returns True if user wants to install."""
        has_winget = self._has_cmd("winget")
        names = "、".join(m[0] for m in missing)
        if not has_winget:
            messagebox.showwarning(
                "缺少运行环境",
                f"GFAM 需要以下运行环境，但当前未安装：\n\n"
                f"  {names}\n\n"
                f"同时未检测到 winget，无法自动安装。\n"
                f"请手动安装上述软件后重新运行。"
            )
            return False

        pkg_list = "\n".join(f"  • {m[0]}（winget 包名：{m[1]}）" for m in missing)
        return messagebox.askyesno(
            "缺少运行环境",
            f"GFAM 需要以下运行环境，但当前未安装：\n\n"
            f"{pkg_list}\n\n"
            f"是否使用 winget 自动安装？\n"
            f"（安装过程中可能会弹出额外确认窗口）"
        )

    def _install_deps_background(self, missing: list, auto_send_server: bool) -> None:
        """Install missing deps in a background thread, then launch backend."""
        try:
            for label, pkg_id in missing:
                self.after(0, lambda l=label: self.start_status_var.set(f"正在安装 {l}，请稍候..."))
                self.after(0, lambda l=label, p=pkg_id: self._append_log(f"[GUI] 正在安装 {l}（{p}）...\n"))
                try:
                    result = subprocess.run(
                        ["winget", "install", "--id", pkg_id, "-e", "--source", "winget",
                         "--accept-package-agreements", "--accept-source-agreements"],
                        capture_output=True, text=True, encoding="utf-8", errors="replace",
                        timeout=300
                    )
                    if result.stdout:
                        self.after(0, lambda t=result.stdout[-500:]: self._append_log(t + "\n"))
                    if result.returncode != 0 and result.stderr:
                        self.after(0, lambda e=result.stderr[-300:]: self._append_log(f"[GUI] winget 输出：{e}\n"))
                except subprocess.TimeoutExpired:
                    self.after(0, lambda l=label: self._append_log(f"[GUI] {l} 安装超时（5分钟）。\n"))
                except Exception as exc:
                    self.after(0, lambda e=str(exc): self._append_log(f"[GUI] 安装异常：{e}\n"))

            # Re-check after install
            still_missing = self._get_missing_deps()
            if still_missing:
                names = "、".join(m[0] for m in still_missing)
                self.after(0, lambda n=names: messagebox.showwarning(
                    "安装未生效",
                    f"winget 安装后仍缺少：{n}\n请关闭本程序后重新运行，或手动安装。"
                ))
                self.after(0, lambda: self.start_status_var.set("安装未生效，请手动安装"))
                return

            # All deps ready — launch backend on main thread
            self.after(0, lambda: self._launch_gfam_backend(auto_send_server))
        except Exception as exc:
            self.after(0, lambda e=str(exc): self._append_log(f"[GUI] 安装线程异常：{e}\n"))
            self.after(0, lambda: self.start_status_var.set("安装失败"))

    def _launch_gfam_backend(self, auto_send_server: bool) -> None:
        """Actually launch run_windows.bat (called on main thread)."""
        run_bat = self.root_dir / "run_windows.bat"
        if not run_bat.exists():
            messagebox.showerror("缺少文件", f"未找到 run_windows.bat：\n{run_bat}")
            return
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        env["GFAM_GUI_LAUNCHER"] = "1"
        # ── Prevent PyInstaller DLL leak ──
        # When frozen, the exe directory contains pythonXXX.dll.  If the child
        # process (a separate Python install) inherits this directory in PATH,
        # Windows may load the exe's DLL instead of the system Python's DLL,
        # causing "Module use of pythonXXX.dll conflicts with this version".
        if getattr(sys, "frozen", False):
            exe_dir = os.path.dirname(sys.executable)
            path_dirs = [d for d in env.get("PATH", "").split(os.pathsep) if d]
            path_dirs = [d for d in path_dirs if os.path.normcase(os.path.abspath(d)) != os.path.normcase(os.path.abspath(exe_dir))]
            env["PATH"] = os.pathsep.join(path_dirs)
            # Also strip PyInstaller's _MEIPASS and other internal vars
            for key in list(env):
                if key.startswith("_MEIPASS") or key == "_MEIPASS2":
                    del env[key]
        if os.name == "nt":
            cmd = ["cmd.exe", "/d", "/c", "chcp 65001>nul & call run_windows.bat"]
        else:
            cmd = ["bash", "-lc", "./run_windows.bat"]
        try:
            popen_kwargs = dict(
                cwd=str(self.root_dir),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
            )
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0
                popen_kwargs["startupinfo"] = startupinfo
                popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            self.process = subprocess.Popen(cmd, **popen_kwargs)
        except Exception as exc:
            messagebox.showerror("启动失败", str(exc))
            self.process = None
            return
        self.backend_menu_ready = False
        self.waiting_press_any_key = False
        self.auto_press_any_key_armed = False
        self.status_var.set(f"运行中 PID={self.process.pid}")
        self.start_status_var.set("GFAM 正在后台启动...")
        self._mark_step("process", "后台进程已启动")
        self._append_log("\n[GUI] 已启动 GFAM 后台进程。\n")
        if auto_send_server:
            self.auto_server_sent = False
            self._append_log(f"[GUI] 等待后端服务器提示后自动发送：{self.server_var.get()}\n")
            self._auto_server_fallback = self.after(15000, self._auto_server_fallback_send)
        else:
            self.auto_server_sent = False
        t = threading.Thread(target=self._reader_loop, daemon=True)
        t.start()
        self.reader_threads = [t]
        threading.Thread(target=self._waiter_loop, daemon=True).start()

    def start_gfam(self, auto_send_server: bool = False) -> None:
        if self.process and self.process.poll() is None:
            self._append_log("[GUI] GFAM 已在运行中。\n")
            if auto_send_server and not self.auto_server_sent:
                self.after(300, lambda: self.send_command(self.server_var.get()))
                self.auto_server_sent = True
            return
        # Pre-check Node.js and Python
        missing = self._get_missing_deps()
        if missing:
            if not self._prompt_install_deps(missing):
                self.start_status_var.set("缺少运行环境，已取消启动")
                return
            # Launch install in background thread, then start backend
            self.start_status_var.set("正在准备安装...")
            threading.Thread(
                target=self._install_deps_background,
                args=(missing, auto_send_server),
                daemon=True,
            ).start()
            return
        # All deps ready — launch directly
        self._launch_gfam_backend(auto_send_server)

    def _auto_server_fallback_send(self) -> None:
        """Fallback timer: send server after 15s if prompt was never detected."""
        if not self.auto_server_sent:
            self.auto_server_sent = True
            self._append_log("[GUI] 等待超时，尝试直接发送服务器选择。\n")
            self.send_command(self.server_var.get())

    def _auto_send_server_if_pending(self) -> None:
        """Send the server selection if we were waiting for the prompt."""
        if self.auto_server_sent:
            return
        self.auto_server_sent = True
        # Cancel the fallback timer if still pending
        fallback = getattr(self, '_auto_server_fallback', None)
        if fallback is not None:
            try:
                self.after_cancel(fallback)
            except Exception:
                pass
            self._auto_server_fallback = None
        self._append_log(f"[GUI] 检测到服务器提示，自动发送：{self.server_var.get()}\n")
        self.send_command(self.server_var.get())

    def _reader_loop(self) -> None:
        proc = self.process
        if not proc or not proc.stdout:
            return
        try:
            for line in proc.stdout:
                self.output_queue.put(line)
        except Exception as exc:
            self.output_queue.put(f"\n[GUI] 输出读取异常：{exc}\n")

    def _waiter_loop(self) -> None:
        proc = self.process
        if not proc:
            return
        code = proc.wait()
        self.output_queue.put(f"\n[GUI] GFAM 进程已退出，退出码：{code}\n")
        self.after(0, lambda: self.status_var.set("未启动"))
        self.after(0, lambda: self.start_status_var.set("GFAM 已退出"))
        # Cancel pending auto-server timer and mark server step as failed
        if not self.auto_server_sent:
            self.auto_server_sent = True
            fallback = getattr(self, '_auto_server_fallback', None)
            if fallback is not None:
                try:
                    self.after_cancel(fallback)
                except Exception:
                    pass
            if code != 0:
                self.after(0, lambda c=code: self._mark_step(
                    "server", f"环境检查失败（退出码 {c}），请查看日志", ok=False))

    def _drain_output(self) -> None:
        try:
            chunks = []
            while True:
                chunks.append(self.output_queue.get_nowait())
        except queue.Empty:
            pass
        if chunks:
            text = "".join(chunks)
            display_text = self._format_log_text(text) if self.compact_log_var.get() else text
            if display_text:
                self._append_log(display_text)
            self._inspect_output_for_stage(text)
        self.after(30, self._drain_output)

    def _inspect_output_for_stage(self, text: str) -> None:
        # GFAM module wrappers commonly print this after a module exits.  The next
        # byte sent to stdin is consumed as the "any key".  Therefore module entry
        # numbers must wait until the real main menu appears again.
        if "Press any key to return to GFAM main menu" in text or "按任意键返回 GFAM 主菜单" in text:
            self.waiting_press_any_key = True
            self.backend_menu_ready = False
            if not self.auto_press_any_key_armed:
                self.auto_press_any_key_armed = True
                self._append_log("[GUI] 检测到模块等待按键返回主菜单，自动发送回车。\n")
                self.after(120, lambda: self.send_raw("\n"))

        # Module-ready detection must use module-specific markers only.  Generic
        # main-menu text is ignored here to prevent false readiness.
        if self.current_module_key and self.module_entering:
            markers = MODULE_READY_MARKERS_BY_KEY.get(self.current_module_key, [])
            if any(marker in text for marker in markers):
                self._mark_module_ready(self.current_module_key, reason="detected")

        if self.current_module_key == "epa":
            # EPA prompt phase tracking for the settings popup.  This prevents
            # a one-click stage sequence from being injected into the earlier
            # -team/-single mode prompt.
            if "GFL-EPA(模式)>" in text or "=========== 编队模式 ===========" in text:
                self._set_epa_gui_phase("mode_prompt")
            if "运行配置已保存" in text or "epa_plus 运行配置已保存" in text:
                self._set_epa_gui_phase("need_index")
            if "正在请求 Index/index" in text or "主动请求并解析 Index/index" in text:
                self._set_epa_gui_phase("indexing")
            if "=========== 打捞关卡菜单 ===========" in text or "请选择你要打捞的关卡难度" in text:
                self._set_epa_gui_phase("stage_difficulty")
            if "关卡列表 ===========" in text or "请选择关卡：" in text:
                self._set_epa_gui_phase("stage_stage")
            if "请选择你要打捞的目标" in text:
                self._set_epa_gui_phase("stage_target")
            if ("满级停机" in text and "检测到满级" not in text) \
               or "目标达成停机" in text or "运行前确认" in text:
                self._set_epa_gui_phase("run_options")
            if "GFL Protocol Auto-Farming Started (EPA)" in text or "EPA 运行状态" in text:
                self._set_epa_gui_phase("running")
            if "本次运行结束" in text or "================= EPA MENU =================" in text:
                self._set_epa_gui_phase("main_menu")

        # Detect server prompt from main.js and auto-send selection
        if "服务器选择" in text or "GFAM(服务器" in text:
            self._auto_send_server_if_pending()

        if "已选择服务器" in text or "当前服务器" in text:
            self.start_status_var.set("服务器已选择，正在准备 UID/SIGN / 主菜单...")
            self._mark_step("server", f"服务器：{self.server_var.get()}")

        # Summary popup detection
        if "[SUMMARY]" in text and ("报告已生成" in text or "统计报告已生成" in text):
            self._route_summary_popup(text)
        if "UID/SIGN" in text and ("已读取" in text or "获取成功" in text or "captured" in text.lower()):
            self.start_status_var.set("UID/SIGN 已准备")
            self._mark_step("auth", "UID/SIGN 已准备")
        if "当前服务器尚未获取 UID/SIGN" in text or "需要先完成一次登录抓取" in text:
            self.start_status_var.set("需要获取 UID/SIGN，请按日志提示在游戏内登录")
            self._mark_step("auth", "需要获取 UID/SIGN", ok=False)

        # Stronger GFAM main-menu detection.  The old implementation used broad
        # markers that also appeared inside module output.  Here we require the
        # main menu's command list / prompt style.
        main_menu_ready = (
            ("GFAM[" in text and ">" in text)
            or ("0 / exit" in text and "提示：进入某个模块后，该模块会接管命令行" in text)
            or ("提示：选择服务器后会先统一获取 UID/SIGN" in text and "factory" in text and "greyzone" in text)
        )
        if main_menu_ready:
            self.backend_menu_ready = True
            self.waiting_press_any_key = False
            self.auto_press_any_key_armed = False
            self.start_status_var.set("已进入 GFAM 主菜单")
            self._mark_step("ready", "已进入 GFAM 主菜单")
            pending = self.pending_module_to_open
            if pending:
                self.pending_module_to_open = None
                self._append_log(f"[GUI] GFAM 主菜单已就绪，继续进入待跳转模块：{MODULE_WINDOWS.get(pending, {}).get('title', pending)}。\n")
                # If a placeholder module window is already open for the same target,
                # send the entry command directly; otherwise open the target window.
                if self.current_module_key == pending and self.module_window and self.module_window.winfo_exists():
                    self.after(250, lambda m=pending: self._send_module_entry_command(m))
                else:
                    self.after(250, lambda m=pending: self._open_module_window(m))
            elif not self.main_ui_shown and not (self.module_window and self.module_window.winfo_exists()):
                self.after(250, self._show_main_ui)

    def send_entry(self) -> None:
        text = self.command_var.get().strip()
        self.command_var.set("")
        if self.pending_factory_quick_cmd:
            if not text:
                self._append_log("\n[GUI] 已选择自动快速建造，但没有输入次数；已取消。\n")
                self.pending_factory_quick_cmd = None
                return
            try:
                count = int(text)
            except Exception:
                self._append_log(f"\n[GUI] 自动快速建造次数无效：{text}。请输入正整数。\n")
                return
            if count <= 0:
                self._append_log(f"\n[GUI] 自动快速建造次数无效：{count}。请输入大于 0 的数字。\n")
                return
            cmd = f"{self.pending_factory_quick_cmd} {count}"
            self.pending_factory_quick_cmd = None
            self.send_command(cmd)
            return
        self.send_command(text)

    def send_command(self, text: str, auto_start: bool = True, log_send: bool = True) -> None:
        text = str(text or "").strip()
        if not text:
            return
        if not self.process or self.process.poll() is not None:
            if auto_start:
                self.start_gfam(auto_send_server=False)
                self.after(800, lambda: self.send_command(text, auto_start=auto_start, log_send=log_send))
            else:
                self._append_log(f"\n[GUI] GFAM 未运行，未发送命令：{text}\n")
            return
        self.send_raw(text + "\n")
        if log_send:
            self._append_log(f"\n[GUI -> GFAM] {text}\n")

    def send_raw(self, text: str) -> None:
        if not self.process or self.process.poll() is not None or not self.process.stdin:
            self._append_log("[GUI] 当前没有运行中的 GFAM 进程。\n")
            return
        try:
            self.process.stdin.write(text)
            self.process.stdin.flush()
        except Exception as exc:
            self._append_log(f"[GUI] 发送失败：{exc}\n")

    def stop_process(self) -> None:
        if self.process and self.process.poll() is None:
            self._append_log("\n[GUI] 正在停止 GFAM 进程。\n")
            pid = self.process.pid
            self.process = None  # 提前置空，防止重复操作
            # 将耗时的 taskkill 和清理工作移到后台线程，避免阻塞 GUI
            threading.Thread(
                target=self._async_stop_and_cleanup,
                args=(pid,), daemon=True,
            ).start()
            self.after(200, self._update_status_stopped)
            return
        # 无活跃进程，直接清理后台任务和代理
        threading.Thread(
            target=self._async_cleanup_only, daemon=True,
        ).start()
        self._update_status_stopped()

    def _check_process_killed(self) -> None:
        # 已被 _async_stop_and_cleanup 取代，保留方法签名以防其他调用
        pass

    def _async_stop_and_cleanup(self, pid: int) -> None:
        """后台线程：杀进程树 + 清理 PID + 恢复代理。"""
        no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        # 1. 杀进程树
        if os.name == "nt" and pid:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=no_window, timeout=5,
                )
            except Exception:
                pass
        # 2. 等待进程退出
        time.sleep(0.3)
        # 3. 清理后台 PID 文件
        for name in (".gfam_auth_capture.pid", ".gfam_factory_auto.pid", ".gfam_fairy_auto.pid"):
            self._kill_pid_file(self.root_dir / name)
        # 4. 安全网：恢复系统代理
        self._cleanup_system_proxy()

    def _async_cleanup_only(self) -> None:
        """后台线程：仅清理 PID 文件和代理（无活跃进程时）。"""
        for name in (".gfam_auth_capture.pid", ".gfam_factory_auto.pid", ".gfam_fairy_auto.pid"):
            self._kill_pid_file(self.root_dir / name)
        self._cleanup_system_proxy()

    def _kill_pid_file(self, pid_file: Path) -> None:
        """在后台线程中杀死指定 PID 文件对应的进程。"""
        try:
            if not pid_file.exists():
                return
            raw = pid_file.read_text(encoding="utf-8", errors="ignore").strip()
            if not raw:
                pid_file.unlink(missing_ok=True)
                return
            pid = raw.split()[0]
            if not pid.isdigit():
                pid_file.unlink(missing_ok=True)
                return
            no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", pid, "/F", "/T"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=no_window, timeout=5,
                )
            else:
                subprocess.run(
                    ["kill", "-9", pid],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=5,
                )
            pid_file.unlink(missing_ok=True)
        except Exception:
            pass

    def _update_status_stopped(self) -> None:
        """在主线程中更新 GUI 状态（通过 after 调度，线程安全）。"""
        try:
            self.status_var.set("未启动")
            self.start_status_var.set("未启动")
        except Exception:
            pass

    def _stop_background_pid(self, pid_file: Path) -> None:
        """兼容方法：供外部调用，内部转发到 _kill_pid_file。"""
        self._kill_pid_file(pid_file)

    def _cleanup_system_proxy(self) -> None:
        """安全网：关闭 Windows 系统代理，防止孤儿进程遗留代理设置。"""
        try:
            import winreg
            reg_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_WRITE)
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
            winreg.CloseKey(key)
            try:
                import ctypes
                internet_set_option = ctypes.windll.wininet.InternetSetOptionW
                internet_set_option(0, 39, 0, 0)  # INTERNET_OPTION_SETTINGS_CHANGED
                internet_set_option(0, 37, 0, 0)  # INTERNET_OPTION_REFRESH
            except Exception:
                pass
        except Exception:
            pass

    # ---------- utilities ----------
    def _remove_non_sgr_ansi(self, text: str) -> str:
        """Remove cursor/clear-screen escape codes while preserving SGR colors."""
        return ANSI_NON_SGR_RE.sub("", text or "")

    def _strip_ansi(self, text: str) -> str:
        """Return plain visible text for saved logs and GUI state checks."""
        return ANSI_RE.sub("", text or "")

    def _format_log_text(self, text: str) -> str:
        """Display-only log compaction; never used for state decisions."""
        text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
        # Keep ANSI SGR color sequences for the Tk Text tag renderer, but drop
        # clear-screen/cursor movement sequences such as \x1b[2J\x1b[H.
        text = self._remove_non_sgr_ansi(text)
        out: list[str] = []
        blank_count = 0
        for raw_line in text.splitlines(keepends=True):
            line = raw_line.rstrip("\n")
            visible = self._strip_ansi(line)
            stripped = visible.strip()
            if not stripped:
                blank_count += 1
                if blank_count <= 1:
                    out.append("\n")
                continue
            blank_count = 0
            if re.fullmatch(r"[=\-─]{10,}", stripped):
                if not self._last_log_separator:
                    out.append("────────────────────────\n")
                    self._last_log_separator = True
                continue
            self._last_log_separator = False
            # Keep the useful module path while reducing visual noise.
            if stripped.startswith("Module file:"):
                out.append("[backend] " + visible.strip() + "\n")
                continue
            out.append(raw_line)
        return "".join(out)

    def _ansi_code_to_tag(self, code: int) -> str | None:
        if code in ANSI_TAG_COLORS:
            # Defensive; currently keys are strings, kept for readability.
            return str(code)
        if 30 <= code <= 37:
            return f"ansi_{code}"
        if 90 <= code <= 97:
            return f"ansi_{code}"
        return None

    def _parse_ansi_segments(self, text: str) -> list[tuple[str, str | None]]:
        """Convert ANSI SGR foreground colors into Tk Text tag segments."""
        text = self._remove_non_sgr_ansi(text)
        segments: list[tuple[str, str | None]] = []
        pos = 0
        current_tag: str | None = None
        for match in ANSI_SGR_RE.finditer(text):
            if match.start() > pos:
                segments.append((text[pos:match.start()], current_tag))
            raw_codes = match.group(1)
            codes = [0] if raw_codes == "" else []
            for item in raw_codes.split(";"):
                if item == "":
                    continue
                try:
                    codes.append(int(item))
                except ValueError:
                    pass
            if not codes:
                codes = [0]
            for code in codes:
                if code == 0:
                    current_tag = None
                elif code in (1, 22):
                    # Bold is intentionally ignored for backend ANSI, because a
                    # foreground tag is enough and avoids mixed-font jitter.
                    continue
                else:
                    tag = self._ansi_code_to_tag(code)
                    if tag:
                        current_tag = tag
            pos = match.end()
        if pos < len(text):
            segments.append((text[pos:], current_tag))
        return self._expand_semantic_log_tags(segments)

    def _semantic_log_tag_for_line(self, line: str) -> str | None:
        stripped = line.strip()
        if not stripped:
            return None
        lower = stripped.lower()
        if stripped.startswith("[GUI") or stripped.startswith("GFL-EPA"):
            return "log_gui"
        if stripped.startswith("[+]") or stripped.startswith("[*]") or "成功" in stripped or "完成" in stripped:
            return "log_success"
        if stripped.startswith("[!]") or "警告" in stripped or "无效输入" in stripped or "未知命令" in stripped:
            return "log_warn"
        if stripped.startswith("[-]") or "错误" in stripped or "失败" in stripped or "error:" in lower or "exception" in lower:
            return "log_error"
        if "停止" in stripped or "清理" in stripped or stripped.startswith("提示："):
            return "log_muted"
        return None

    def _expand_semantic_log_tags(self, segments: list[tuple[str, str | None]]) -> list[tuple[str, str | None]]:
        expanded: list[tuple[str, str | None]] = []
        for part, tag in segments:
            if not part:
                continue
            if tag:
                expanded.append((part, tag))
                continue
            pieces = re.findall(r".*?\n|.+$", part)
            for piece in pieces:
                expanded.append((piece, self._semantic_log_tag_for_line(piece)))
        return expanded

    def _append_log(self, text: str) -> None:
        text = self._remove_non_sgr_ansi(text or "")
        plain_text = self._strip_ansi(text)
        self.log_history.append(plain_text)
        if len(self.log_history) > 5000:
            self.log_history = self.log_history[-4000:]
        segments = self._parse_ansi_segments(text)
        self.log_history_segments.extend(segments)
        if len(self.log_history_segments) > 18000:
            self.log_history_segments = self.log_history_segments[-14000:]
        if self.log_text:
            self._configure_log_tags()
            self.log_text.configure(state=tk.NORMAL)
            if self.log_color_var.get():
                for part, tag in segments:
                    if not part:
                        continue
                    if tag:
                        self.log_text.insert(tk.END, part, tag)
                    else:
                        self.log_text.insert(tk.END, part)
            else:
                self.log_text.insert(tk.END, plain_text)
            # Trim Text widget if too long (keep last ~5000 lines)
            line_count = int(self.log_text.index("end-1c").split(".")[0])
            if line_count > 6000:
                self.log_text.configure(state=tk.NORMAL)
                self.log_text.delete("1.0", f"{line_count - 4000}.0")
            if self.autoscroll_var.get():
                self.log_text.see(tk.END)
            self.log_text.configure(state=tk.NORMAL)

    def clear_log(self) -> None:
        self.log_history.clear()
        self.log_history_segments.clear()
        if self.log_text:
            self.log_text.delete("1.0", tk.END)

    def save_log(self) -> None:
        default = f"gfam_gui_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        path = filedialog.asksaveasfilename(title="保存日志", initialfile=default, defaultextension=".txt", filetypes=[("Text", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        Path(path).write_text("".join(self.log_history), encoding="utf-8")
        self._append_log(f"[GUI] 日志已保存：{path}\n")

    def open_root_dir(self) -> None:
        try:
            if os.name == "nt":
                os.startfile(str(self.root_dir))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(self.root_dir)])
            else:
                subprocess.Popen(["xdg-open", str(self.root_dir)])
        except Exception as exc:
            messagebox.showerror("打开目录失败", str(exc))

    def on_close(self) -> None:
        if self.module_window and self.module_window.winfo_exists():
            try:
                self.module_window.destroy()
            except Exception:
                pass
        if self.process and self.process.poll() is None:
            if messagebox.askyesno("退出", "GFAM 仍在运行，是否停止进程并退出？"):
                self.stop_process()
            else:
                return
        try:
            (self.root_dir / ".gfam_auth.json").unlink(missing_ok=True)
        except Exception:
            pass
        # 安全网：后台线程恢复系统代理（不阻塞 GUI 关闭）
        if not getattr(self, '_proxy_cleanup_done', False):
            self._proxy_cleanup_done = True
            threading.Thread(target=self._cleanup_system_proxy, daemon=True).start()
        self.destroy()


if __name__ == "__main__":
    app = GFAMGui()
    app.mainloop()
