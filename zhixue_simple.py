"""
知学网阅卷助手 - 简化版（大题批改）
一次只批改一道题，适合主观题详细批改
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import google.generativeai as genai
import pyautogui
from PIL import Image, ImageTk, ImageDraw, ImageFont
import json
import time
from datetime import datetime
import threading


import base64
import io

# 配置 Gemini API

# 配置默认 Gemini API (用户可修改)

# 默认配置
DEFAULT_CONFIG = {
    "provider": "DeepSeek",  # Gemini, DeepSeek, Custom
    "api_key": "",
    "base_url": "https://api.deepseek.com",
    "model_name": "deepseek-chat"
}

# 预设提供商配置
PROVIDERS = {
    "Gemini": {
        "base_url": "",
        "models": ["gemini-2.5-flash", "gemini-1.5-pro", "gemini-1.5-flash", "gemini-pro"]
    },

    "DeepSeek": {
        "base_url": "https://api.siliconflow.cn/v1",
        "models": ["deepseek-ai/DeepSeek-V3", "deepseek-ai/DeepSeek-V2.5", "deepseek-ai/Janus-Pro-7B"]
    },
    "SiliconFlow": {
        "base_url": "https://api.siliconflow.cn/v1",
        "models": ["Qwen/Qwen2-VL-72B-Instruct", "Qwen/Qwen2-VL-7B-Instruct", "Qwen/Qwen3-VL-32B-Instruct", "Qwen/Qwen3-VL-32B-Thinking"]
    },
    "Magpie": {
        # 本机 magpie 网关（https://usemagpie.ai），任意 key 均可，用 magpie-<应用名> 方便在 Usage 里区分
        "base_url": "http://127.0.0.1:3425/v1",
        "default_key": "magpie-zhixue",
        "models": []  # 运行时从 /v1/models 获取
    },
    "Custom": {
        "base_url": "http://localhost:11434/v1",
        "models": []
    }
}

HTTP_TIMEOUT = 120  # 秒，防止网络卡住时程序假死

# ================= 在线更新 =================
APP_VERSION = "1.2.0"
UPDATE_REPO = "kookoo2024/paper2"   # 从这个 GitHub 仓库拉新版本
UPDATE_BRANCH = "main"
# 依次尝试：GitHub 原始地址 → jsDelivr 镜像（国内直连更稳，但可能有几小时缓存）
UPDATE_SOURCES = [
    "https://raw.githubusercontent.com/{repo}/{branch}/",
    "https://cdn.jsdelivr.net/gh/{repo}@{branch}/",
]


def _ver_tuple(v):
    out = []
    for part in str(v).strip().lstrip("vV").split("."):
        num = "".join(ch for ch in part if ch.isdigit())
        out.append(int(num) if num else 0)
    return tuple(out + [0] * (3 - len(out)))


def check_update(custom_base=""):
    """返回 (有新版本?, 远程信息dict, 使用的base地址)。远程 version.json 格式：
    {"version": "1.2.0", "notes": "更新说明", "files": {"zhixue_simple.py": "<sha256>", ...}}"""
    import urllib.request
    bases = [custom_base] if custom_base else [b.format(repo=UPDATE_REPO, branch=UPDATE_BRANCH) for b in UPDATE_SOURCES]
    last_err = None
    for base in bases:
        try:
            url = base.rstrip("/") + "/version.json?t=" + str(int(time.time()))
            req = urllib.request.Request(url, headers={"User-Agent": f"ZhixueGrader/{APP_VERSION}", "Cache-Control": "no-cache"})
            with urllib.request.urlopen(req, timeout=10) as r:
                info = json.loads(r.read().decode("utf-8-sig"))
            return _ver_tuple(info.get("version", "0")) > _ver_tuple(APP_VERSION), info, base
        except Exception as e:
            last_err = e
    raise Exception(f"无法连接更新服务器：{last_err}")


def apply_update(info, base):
    """下载 version.json 列出的文件，校验后替换；旧文件备份到 backup/ 目录。返回更新的文件列表"""
    import os, hashlib, shutil, urllib.request, urllib.parse
    app_dir = os.path.dirname(os.path.abspath(__file__))
    files = info.get("files") or {"zhixue_simple.py": ""}
    if isinstance(files, list):
        files = {f: "" for f in files}
    staged = {}
    for name, sha in files.items():
        if ".." in name or os.path.isabs(name) or name.endswith("config.json"):
            continue  # 安全：不允许写到程序目录之外，也绝不覆盖用户配置
        req = urllib.request.Request(base.rstrip("/") + "/" + urllib.parse.quote(name) + "?t=" + str(int(time.time())),
                                     headers={"User-Agent": f"ZhixueGrader/{APP_VERSION}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        if sha and hashlib.sha256(data).hexdigest().lower() != sha.lower():
            raise Exception(f"{name} 校验失败（可能镜像还没同步），已取消更新，原文件未改动")
        if name.endswith((".py", ".pyw")):
            compile(data.decode("utf-8"), name, "exec")  # 语法检查，坏文件不替换
        staged[name] = data
    if not staged:
        raise Exception("更新清单为空")
    bdir = os.path.join(app_dir, "backup", f"v{APP_VERSION}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(bdir, exist_ok=True)
    for name, data in staged.items():
        dst = os.path.join(app_dir, name)
        if os.path.exists(dst):
            os.makedirs(os.path.dirname(os.path.join(bdir, name)), exist_ok=True)
            shutil.copy2(dst, os.path.join(bdir, name))
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        tmp = dst + ".new"
        with open(tmp, "wb") as fp:
            fp.write(data)
        os.replace(tmp, dst)  # 原子替换
    return list(staged), bdir


def http_open(req, timeout=HTTP_TIMEOUT):
    """本机地址（magpie/Ollama）绕过系统代理，避免 v2rayN 等全局代理把 127.0.0.1 也转发出去"""
    import urllib.request
    from urllib.parse import urlparse
    url = req.full_url if hasattr(req, "full_url") else req
    if urlparse(url).hostname in ("127.0.0.1", "localhost", "::1"):
        return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout)


def _magpie_port():
    """读取 magpie settings.json 里的端口（只读），找不到返回 3425"""
    import os
    for base in (os.environ.get("XDG_CONFIG_HOME"), os.path.join(os.path.expanduser("~"), ".config")):
        if not base:
            continue
        f = os.path.join(base, "magpie", "settings.json")
        try:
            with open(f, encoding="utf-8") as fp:
                return int(json.load(fp).get("port", 3425))
        except Exception:
            pass
    return 3425


def magpie_detect(timeout=2):
    """检测本机 magpie 是否在运行；在运行返回 (base_url, version)，否则 (None, None)"""
    import urllib.request
    port = _magpie_port()
    try:
        with http_open(f"http://127.0.0.1:{port}/api/hello", timeout=timeout) as r:
            info = json.loads(r.read().decode("utf-8"))
            if info.get("name") == "magpie":
                return f"http://127.0.0.1:{port}/v1", info.get("version", "")
    except Exception:
        pass
    return None, None


def fetch_models(base_url, api_key, vision_only=True, timeout=10):
    """从 OpenAI 兼容接口 /models 拉取模型列表（magpie / Ollama / LM Studio 等通用）。
    vision_only=True 时优先返回能看图的模型（magpie 会在 modalities 里标注）。"""
    import urllib.request
    req = urllib.request.Request(f"{base_url.rstrip('/')}/models",
                                 headers={"Authorization": f"Bearer {api_key or 'magpie-zhixue'}"})
    with http_open(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8")).get("data", [])
    ids = [m.get("id") for m in data if m.get("id")]
    if vision_only:
        vis = []
        for m in data:
            mods = m.get("modalities")
            inputs = mods.get("input", []) if isinstance(mods, dict) else (mods or [])
            if "image" in inputs:
                vis.append(m["id"])
        if vis:  # 有标注才过滤，否则全部返回
            return vis
    return ids


# 配置 PyAutoGUI
pyautogui.FAILSAFE = True  # 鼠标甩到屏幕左上角可紧急中止（全自动模式下务必保留）
pyautogui.PAUSE = 0.1  # 每次操作后暂停0.1秒


class ScreenshotSelector:
    """可视化截图选择器"""
    def __init__(self, callback):
        self.callback = callback
        self.start_x = None
        self.start_y = None
        self.rect = None
        
    def start(self):
        """开始截图选择"""
        self.top = tk.Toplevel()
        self.top.attributes('-fullscreen', True)
        self.top.attributes('-alpha', 0.3)
        self.top.attributes('-topmost', True)
        self.top.configure(bg='black')
        
        self.canvas = tk.Canvas(self.top, cursor='cross', bg='black', highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        self.canvas.create_text(
            self.top.winfo_screenwidth() // 2,
            50,
            text="拖动鼠标框选区域，按ESC取消",
            fill='white',
            font=('微软雅黑', 16, 'bold')
        )
        
        self.canvas.bind('<Button-1>', self.on_press)
        self.canvas.bind('<B1-Motion>', self.on_drag)
        self.canvas.bind('<ButtonRelease-1>', self.on_release)
        self.top.bind('<Escape>', lambda e: self.cancel())
        
    def on_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        
    def on_drag(self, event):
        if self.rect:
            self.canvas.delete(self.rect)
        
        self.rect = self.canvas.create_rectangle(
            self.start_x, self.start_y, event.x, event.y,
            outline='red', width=3
        )
        
        width = abs(event.x - self.start_x)
        height = abs(event.y - self.start_y)
        if hasattr(self, 'size_text'):
            self.canvas.delete(self.size_text)
        self.size_text = self.canvas.create_text(
            event.x, event.y - 20,
            text=f"{width} x {height}",
            fill='yellow',
            font=('微软雅黑', 12, 'bold')
        )
        
    def on_release(self, event):
        if self.start_x and self.start_y:
            x1 = min(self.start_x, event.x)
            y1 = min(self.start_y, event.y)
            x2 = max(self.start_x, event.x)
            y2 = max(self.start_y, event.y)
            
            width = x2 - x1
            height = y2 - y1
            
            if width > 10 and height > 10:
                self.top.destroy()
                self.callback((x1, y1, width, height))
            else:
                messagebox.showwarning("提示", "选择区域太小")
                self.cancel()
    
    def cancel(self):
        self.top.destroy()


class SimpleGradingUI:
    def __init__(self, root):
        self.root = root
        # 线程安全的界面更新队列：后台线程只往队列里放函数，由主线程执行
        import queue
        self._uiq = queue.Queue()
        self._main_thread = threading.current_thread()
        self.root.title(f"阅卷 V{APP_VERSION}")
        
        self.root.geometry("290x720")
        self.root.resizable(False, False)  # 固定大小
        self.root.attributes('-topmost', True)  # 窗口置顶

        
        # 配置文件固定放在程序目录（双击运行或从别的目录启动都能找到）
        import os
        self.config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'zhixue_simple_config.json')

        self.answer_region = None
        self.grading_count = 0
        self.total_time = 0
        self.is_grading = False
        self.auto_continue = False
        self.is_paused = False  # 暂停状态
        self.score_buttons = {}  # 分数按钮位置 {分数: (x, y)}
        self.next_button_pos = None  # 下一份按钮位置
        self.waiting_for_confirm = False  # 等待用户确认
        self.pending_score = None  # 待确认的分数
        self.score_input_box = None  # 分数输入框位置
        self.submit_button_pos = None  # 提交按钮位置
        
        # 题目数据（记忆功能）
        self.saved_question_num = ""
        self.saved_max_score = "10"
        self.saved_answer = ""
        
        self.save_timer = None # 自动保存定时器

        self.load_config()  # 加载配置 (必须在初始化变量之后)
        self.init_model()


        self.create_widgets()  # 创建界面
        self.update_ui_from_config()  # 更新界面显示
        
        self.root.after(50, self._drain_ui_queue)

        # 启动 3 秒后静默检查更新（有新版本才提示）
        if self.config.get('auto_check_update', True):
            self.root.after(3000, lambda: self.check_update_ui(silent=True))

        self.root.bind('<space>', lambda e: self.grade_answer())
        self.root.bind('<Escape>', lambda e: self.stop_grading())
        
        # 绑定关闭事件，确保存储
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
    
    def on_closing(self):
        """窗口关闭时调用"""
        self.save_config()
        self.root.destroy()
    
    # ---------- 界面样式 ----------
    THEME = {
        'bg': '#F3F5F9',        # 窗口底色
        'card': '#FFFFFF',      # 卡片
        'line': '#E2E8F0',      # 描边
        'text': '#1E293B',      # 正文
        'sub': '#64748B',       # 次要文字
        'head': '#0F172A',      # 顶栏
        'head2': '#1E293B',     # 顶栏按钮
        'primary': '#2563EB',   # 主色
        'primary_d': '#1D4ED8',
        'ok': '#059669',
        'ok_bg': '#ECFDF5',
        'warn': '#D97706',
        'danger': '#DC2626',
        'slate': '#475569',
        'tint': '#EFF4FF',      # 浅蓝底
    }
    FONT = '微软雅黑'
    GRADE_TEXT = "▶ 批改  (空格)"

    def _btn(self, parent, text, cmd, bg, fg='white', size=8, bold=False, active=None, **kw):
        return tk.Button(
            parent, text=text, command=cmd, bg=bg, fg=fg,
            activebackground=active or bg, activeforeground=fg,
            font=(self.FONT, size, 'bold' if bold else 'normal'),
            relief=tk.FLAT, bd=0, cursor='hand2', padx=kw.pop('padx', 6), pady=kw.pop('pady', 1), **kw)

    def _entry(self, parent, width):
        T = self.THEME
        return tk.Entry(parent, width=width, font=(self.FONT, 9), relief=tk.FLAT, bg='#F8FAFC', fg=T['text'],
                        highlightthickness=1, highlightbackground=T['line'], highlightcolor=T['primary'],
                        insertbackground=T['text'])

    def _card(self, parent, title, hint=None, expand=False):
        """卡片式分组：白底细边框 + 小标题，返回内容区"""
        T = self.THEME
        outer = tk.Frame(parent, bg=T['card'], highlightthickness=1, highlightbackground=T['line'])
        outer.pack(fill=tk.BOTH if expand else tk.X, expand=expand, pady=(0, 6))
        head = tk.Frame(outer, bg=T['card'])
        head.pack(fill=tk.X, padx=8, pady=(5, 2))
        tk.Frame(head, bg=T['primary'], width=3, height=12).pack(side=tk.LEFT, padx=(0, 5))
        tk.Label(head, text=title, font=(self.FONT, 8, 'bold'), bg=T['card'], fg=T['text']).pack(side=tk.LEFT)
        if hint:
            tk.Label(head, text=hint, font=(self.FONT, 7), bg=T['card'], fg=T['sub']).pack(side=tk.LEFT, padx=(5, 0))
        body = tk.Frame(outer, bg=T['card'])
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 7))
        return head, body

    def create_widgets(self):
        """创建界面（紧凑卡片式）"""
        T, F = self.THEME, self.FONT
        self.root.configure(bg=T['bg'])

        # ===== 顶栏：标题 + 版本 + 工具按钮 =====
        bar = tk.Frame(self.root, bg=T['head'], height=40)
        bar.pack(fill=tk.X)
        bar.pack_propagate(False)
        tk.Label(bar, text="阅卷", font=(F, 13, 'bold'), bg=T['head'], fg='white').pack(side=tk.LEFT, padx=(12, 4))
        tk.Label(bar, text=f"V{APP_VERSION}", font=('Consolas', 7, 'bold'), bg=T['head2'], fg='#93C5FD',
                 padx=4, pady=1).pack(side=tk.LEFT, pady=(4, 0))

        tools = tk.Frame(bar, bg=T['head'])
        tools.pack(side=tk.RIGHT, padx=8)
        self.update_btn = self._btn(tools, "更新", lambda: self.check_update_ui(silent=False), T['head2'],
                                    active=T['primary'], padx=7, pady=3)
        self.update_btn.pack(side=tk.RIGHT)
        self._btn(tools, "笔记", self.setup_obsidian_path, T['head2'], active=T['primary'],
                  padx=7, pady=3).pack(side=tk.RIGHT, padx=(0, 3))
        self._btn(tools, "模型", self.setup_model, T['head2'], active=T['primary'],
                  padx=7, pady=3).pack(side=tk.RIGHT, padx=(0, 3))

        # ===== 底部状态栏 =====
        status = tk.Frame(self.root, bg=T['head'])
        status.pack(fill=tk.X, side=tk.BOTTOM)
        self.stats_label = tk.Label(status, text="已批 0 · 用时 0s · 均 0s · 0/h", font=(F, 7),
                                    fg='#CBD5E1', bg=T['head'])
        self.stats_label.pack(pady=2)

        main_frame = tk.Frame(self.root, bg=T['bg'], padx=8, pady=8)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # ===== ① 答题区域 =====
        _, body = self._card(main_frame, "① 答题区域")
        self.region_preview = tk.Label(body, text="未框选", bg=T['tint'], fg=T['sub'], font=(F, 8),
                                       anchor='w', padx=6, pady=2)
        self.region_preview.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._btn(body, "框选", self.setup_region, T['primary'], active=T['primary_d'],
                  padx=10, pady=2).pack(side=tk.RIGHT, padx=(6, 0))

        # ===== ② 题目 =====
        _, body = self._card(main_frame, "② 题目", hint="自动保存", expand=True)
        row = tk.Frame(body, bg=T['card'])
        row.pack(fill=tk.X, pady=(0, 4))
        tk.Label(row, text="题号", font=(F, 8), bg=T['card'], fg=T['sub']).pack(side=tk.LEFT)
        self.question_num_entry = self._entry(row, 6)
        self.question_num_entry.pack(side=tk.LEFT, padx=(3, 8), ipady=1)
        tk.Label(row, text="满分", font=(F, 8), bg=T['card'], fg=T['sub']).pack(side=tk.LEFT)
        self.max_score_entry = self._entry(row, 4)
        self.max_score_entry.pack(side=tk.LEFT, padx=3, ipady=1)

        row2 = tk.Frame(body, bg=T['card'])
        row2.pack(fill=tk.X, pady=(0, 2))
        tk.Label(row2, text="参考答案", font=(F, 8), bg=T['card'], fg=T['sub']).pack(side=tk.LEFT)
        self._btn(row2, "清空", lambda: (self.answer_text.delete('1.0', tk.END), self.save_question_data()),
                  '#F1F5F9', fg=T['slate'], size=7, active=T['line']).pack(side=tk.RIGHT)
        self._btn(row2, "截图识别", self.capture_standard_answer, T['tint'], fg=T['primary'], size=7,
                  active='#DBEAFE').pack(side=tk.RIGHT, padx=(0, 4))

        self.answer_text = scrolledtext.ScrolledText(body, height=3, font=(F, 8), wrap=tk.WORD, relief=tk.FLAT,
                                                     bg='#F8FAFC', fg=T['text'], highlightthickness=1,
                                                     highlightbackground=T['line'], highlightcolor=T['primary'])
        self.answer_text.pack(fill=tk.BOTH, expand=True)

        for w in (self.question_num_entry, self.max_score_entry, self.answer_text):
            w.bind('<FocusOut>', lambda e: self.save_question_data())
            w.bind('<KeyRelease>', lambda e: self.save_question_data())

        # ===== ③ 批改控制 =====
        _, body = self._card(main_frame, "③ 批改")
        btns = tk.Frame(body, bg=T['card'])
        btns.pack(fill=tk.X, pady=(0, 5))
        self.grade_btn = self._btn(btns, self.GRADE_TEXT, self.grade_answer, T['primary'], size=10, bold=True,
                                   active=T['primary_d'], pady=4)
        self.grade_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self.pause_btn = self._btn(btns, "⏸ 暂停", self.toggle_pause, T['slate'], size=9, bold=True,
                                   pady=4, state=tk.DISABLED, disabledforeground='#CBD5E1')
        self.pause_btn.pack(side=tk.LEFT, ipadx=4)

        checks = tk.Frame(body, bg=T['card'])
        checks.pack(fill=tk.X, pady=(0, 3))
        ck = dict(font=(F, 8), bg=T['card'], fg=T['text'], activebackground=T['card'],
                  selectcolor='white', bd=0, highlightthickness=0)
        self.auto_var = tk.BooleanVar(value=False)
        tk.Checkbutton(checks, text="连续", variable=self.auto_var, command=self.on_checkbox_changed, **ck).pack(side=tk.LEFT)
        self.auto_click_var = tk.BooleanVar(value=False)
        tk.Checkbutton(checks, text="自动填分", variable=self.auto_click_var, command=self.save_config, **ck).pack(side=tk.LEFT, padx=(6, 0))
        self.skip_confirm_var = tk.BooleanVar(value=False)
        ck_skip = dict(ck, fg=T['warn'])
        tk.Checkbutton(checks, text="跳过确认", variable=self.skip_confirm_var, command=self.save_config, **ck_skip).pack(side=tk.LEFT, padx=(6, 0))

        opts = tk.Frame(body, bg=T['card'])
        opts.pack(fill=tk.X)
        tk.Label(opts, text="间隔", font=(F, 8), bg=T['card'], fg=T['sub']).pack(side=tk.LEFT)
        self.delay_entry = self._entry(opts, 3)
        self.delay_entry.insert(0, "3")
        self.delay_entry.pack(side=tk.LEFT, padx=2)
        self.delay_entry.bind('<FocusOut>', lambda e: self.save_config())
        tk.Label(opts, text="秒", font=(F, 8), bg=T['card'], fg=T['sub']).pack(side=tk.LEFT)
        self.setup_status_label = tk.Label(opts, text="● 未定位", font=(F, 7), bg=T['card'], fg=T['danger'])
        self.setup_status_label.pack(side=tk.RIGHT)
        self._btn(opts, "测试", self.test_auto_click, '#F1F5F9', fg=T['slate'], size=7,
                  active=T['line']).pack(side=tk.RIGHT, padx=(0, 6))
        self._btn(opts, "定位", self.setup_score_buttons, '#F1F5F9', fg=T['slate'], size=7,
                  active=T['line']).pack(side=tk.RIGHT, padx=(0, 3))

        # ===== ④ 结果 =====
        _, body = self._card(main_frame, "④ 结果", expand=True)
        self.current_result_frame = tk.Frame(body, bg=T['tint'])
        self.current_result_frame.pack(fill=tk.X, pady=(0, 4))
        self.current_score_label = tk.Label(self.current_result_frame, text="建议分数  --", font=(F, 13, 'bold'),
                                            bg=T['tint'], fg=T['primary_d'])
        self.current_score_label.pack(pady=(4, 0))
        self.current_analysis_label = tk.Label(self.current_result_frame, text="", font=(F, 7), bg=T['tint'],
                                               fg=T['slate'], wraplength=232, justify=tk.LEFT)
        self.current_analysis_label.pack(pady=(0, 4), padx=6)

        self.result_text = scrolledtext.ScrolledText(body, height=8, font=(F, 7), wrap=tk.WORD, relief=tk.FLAT,
                                                     bg='#F8FAFC', fg=T['slate'], highlightthickness=1,
                                                     highlightbackground=T['line'])
        self.result_text.pack(fill=tk.BOTH, expand=True)

        # 初始提示（精简）
        self.log("快速开始：")
        self.log("1 框选答题区域  2 填题号/满分/参考答案")
        self.log("3 定位输入框和提交按钮  4 点测试验证")
        self.log("5 勾选连续+自动填分，按空格开始")
        self.log("不勾跳过确认＝每份弹窗确认（安全）；勾上＝直接提交（高效）。")
        self.log("鼠标甩到屏幕左上角 = 紧急停止；Esc = 停止。\n")

    def update_ui_from_config(self):
        """从配置更新界面显示"""
        # 1. 题目数据
        if self.saved_question_num:
            self.question_num_entry.delete(0, tk.END)
            self.question_num_entry.insert(0, self.saved_question_num)
            
        if self.saved_max_score:
            self.max_score_entry.delete(0, tk.END)
            self.max_score_entry.insert(0, self.saved_max_score)
            
        if self.saved_answer:
            self.answer_text.delete('1.0', tk.END)
            self.answer_text.insert('1.0', self.saved_answer)
            
        # 2. 复选框状态
        if hasattr(self, 'auto_var'):
            self.auto_var.set(self.saved_auto_continue)
        if hasattr(self, 'auto_click_var'):
            self.auto_click_var.set(self.saved_auto_click)
        if hasattr(self, 'skip_confirm_var'):
            self.skip_confirm_var.set(self.saved_skip_confirm)
        
        # 3. 延时设置
        if self.saved_delay and hasattr(self, 'delay_entry'):
            self.delay_entry.delete(0, tk.END)
            self.delay_entry.insert(0, self.saved_delay)
            
        # 4. 区域设置状态
        self.update_region_preview()
        
        # 5. 自动提交设置状态
        if self.score_input_box and self.submit_button_pos:
            self.setup_status_label.config(text="● 已定位", fg=self.THEME['ok'])
        else:
            self.setup_status_label.config(text="● 未定位", fg=self.THEME['danger'])
            
        # 最后触发复选框回调(会触发保存)，确保所有UI都已更新
        self.on_checkbox_changed()
    
    def setup_region(self):
        """设置答案区域"""
        self.root.iconify()
        time.sleep(0.3)
        
        def on_region_selected(region):
            self.answer_region = region
            self.save_config()
            self.update_region_preview()
            self.root.deiconify()
            self.log(f"✓ 答案区域已设置: {region[2]}x{region[3]}")
            messagebox.showinfo("成功", "答案区域设置成功！")
        
        selector = ScreenshotSelector(on_region_selected)
        selector.start()
    
    def capture_standard_answer(self):
        """截图参考答案并识别文字"""
        self.root.iconify()
        time.sleep(0.3)
        
        def on_captured(region):
            x, y, w, h = region
            img = pyautogui.screenshot(region=(x, y, w, h))
            self.root.deiconify()
            
            # 识别文字
            try:
                self.log("正在识别参考答案...")
                prompt = "请识别图片中的文字内容，直接返回文字，不要添加任何说明。"
                
                # 使用统一接口调用 (支持所有模型)
                answer_text = self.call_ai_api(prompt, img, need_json=False)
                answer_text = answer_text.strip()
                
                # 填入文本框
                self.answer_text.delete('1.0', tk.END)
                self.answer_text.insert('1.0', answer_text)
                self.log("✓ 参考答案已识别并填入")
            except Exception as e:
                self.log(f"⚠ 识别失败: {str(e)}")
                messagebox.showerror("错误", f"识别失败：{str(e)}")
        
        selector = ScreenshotSelector(on_captured)
        selector.start()
    
    def update_region_preview(self):
        """更新区域预览"""
        if self.answer_region:
            x, y, w, h = self.answer_region
            self.region_preview.config(text=f"✓ 已框选  {w}×{h}", fg=self.THEME['ok'], bg=self.THEME['ok_bg'])
    
    def grade_answer(self):
        """批改答案"""
        if self.is_grading:
            self.log("⚠ 正在批改中，请稍候...")
            return
        
        if not self.answer_region:
            messagebox.showwarning("提示", "请先设置答案区域")
            return
        
        if not self.question_num_entry.get().strip():
            messagebox.showwarning("提示", "请输入题号")
            return
        
        answer_text = self.answer_text.get('1.0', tk.END).strip()
        if not answer_text:
            messagebox.showwarning("提示", "请输入或截图参考答案")
            return
        
        # 自动保存题目数据（每次批改时）
        self.saved_question_num = self.question_num_entry.get().strip()
        self.saved_max_score = self.max_score_entry.get().strip()
        self.saved_answer = answer_text
        self.save_config()
        
        self.is_grading = True
        self.is_paused = False
        self.grade_btn.config(state=tk.DISABLED, text="批改中...")
        
        # 启用暂停按钮
        if self.auto_continue:
            self.pause_btn.config(state=tk.NORMAL)
        
        thread = threading.Thread(target=self._grade_thread)
        thread.daemon = True
        thread.start()
    
    def _grade_thread(self):
        """批改线程"""
        try:
            start_time = time.time()
            
            question_num = self.question_num_entry.get().strip()
            max_score = int(self.max_score_entry.get().strip() or "10")
            standard_answer = self.answer_text.get('1.0', tk.END).strip()
            
            self.root.after(0, lambda: self.log(f"\n[{datetime.now().strftime('%H:%M:%S')}] 批改题号{question_num}..."))
            
            # 截取学生答案
            x, y, w, h = self.answer_region
            student_img = pyautogui.screenshot(region=(x, y, w, h))
            # 防重复：页面没翻到下一份时截图会和上一张一样，自动模式下直接停，避免同一份卷子重复提交
            import hashlib
            img_hash = hashlib.md5(student_img.tobytes()).hexdigest()
            if self.auto_continue and img_hash == getattr(self, 'last_img_hash', None):
                self.auto_continue = False
                raise Exception("答案区域和上一份完全相同（可能没翻页或已批完），已停止自动连续批改")
            self.last_img_hash = img_hash
            self.current_student_img = student_img # 保存引用以供导出
            
            # 构建提示
            prompt = f"""你是严谨的判卷老师，请严格按照【参考答案】中的评分标准（步骤分）批改这道题。

题号：{question_num}
满分：{max_score}分
参考答案：
{standard_answer}

图片是学生的答案。

请仔细对比学生答案与参考答案，严格判定每一步是否正确。如果是步骤给分题，必须检查学生是否写出了关键步骤。
如果学生答案与参考答案不仅仅是格式不同，而是逻辑或数值错误，必须扣分。

按以下JSON格式返回：
{{
    "student_answer": "学生写的答案内容（简述）",
    "score": 得分数字,
    "deduction_details": [
        {{"point": "具体扣分原因（如：未化简、计算错误、步骤缺失）", "deduction": 扣分值}}
    ],
    "analysis": "详细评语（指出哪里错了，为什么扣分）"
}}

严厉评分规则：
1. 总分不能超过满分，不能低于0分。
2. 必须严格执行参考答案中的给分点，步骤缺失扣步骤分。
3. 严格计算最终得分 = 满分 - 扣分总和。

只返回JSON，不要其他内容。"""
            
            try:
                # 使用统一接口，强制 JSON
                result = self.call_ai_api(prompt, student_img, need_json=True)
            except Exception as e:
                # 备用：如果是Gemini，尝试备用（其实统一接口已经处理了，这里可能不需要了，但由于有fallback逻辑，保留一点容错?）
                # 由于 call_ai_api 已经封装，这里主要捕获最终错误
                raise e
            
            elapsed = time.time() - start_time
            self.grading_count += 1
            self.total_time += elapsed
            
            model_name = self.config.get('model_name', 'Unknown')
            self.root.after(0, lambda: self.display_result(result, max_score, elapsed, model_name))
            
        except Exception as e:
            err = str(e)
            self.log(f"❌ 批改失败: {err}")
            self.ui(self.stop_grading)  # 自动连续模式下出错要停下，不能卡在“批改中”
            self.ui(lambda: messagebox.showerror("错误", f"批改失败：{err}"))
        
        finally:
            # 只在非自动连续模式下重置状态
            if not self.auto_continue:
                self.is_grading = False
                self.root.after(0, lambda: self.grade_btn.config(state=tk.NORMAL, text=self.GRADE_TEXT))
    
    def display_result(self, result, max_score, elapsed, model_name="Unknown"):
        """显示结果"""
        try:
            score = float(result.get('score', 0))
        except (TypeError, ValueError):
            score = 0
        score = max(0, min(score, max_score))  # 防止模型给出超过满分或负分
        if score == int(score):
            score = int(score)
        analysis = result.get('analysis', '')
        deductions = result.get('deduction_details', [])
        
        # 更新显示 (包含模型名称)
        self.current_score_label.config(text=f"建议分数  {score} / {max_score}")
        
        detail_text = f"评语: {analysis}\n"
        if deductions:
            detail_text += "\n扣分详情:\n"
            for d in deductions:
                detail_text += f"  • {d.get('point', '未命名扣分点')}: -{d.get('deduction', 0)}分\n"
        
        self.current_analysis_label.config(text=detail_text)
        
        self.log(f"  得分: {score}/{max_score} 用时: {elapsed:.1f}s ({model_name})")
        self.log(f"\n💡 建议分数: {score} 分")
        
        self.update_stats()
        
        # 计算当前统计数据供保存使用
        avg_time = self.total_time / self.grading_count if self.grading_count > 0 else 0
        
        # 自动保存到 Obsidian
        if hasattr(self, 'obsidian_path') and self.obsidian_path:
            self.save_to_obsidian(result, max_score, self.current_student_img, model_name, elapsed, avg_time)
        
        # 自动保存为 HTML
        self.save_to_html(result, max_score, self.current_student_img, model_name, elapsed, avg_time)
        
        # 自检：扣分合计应等于 满分-得分；对不上说明模型自相矛盾，强制人工确认
        try:
            ded_sum = sum(float(d.get('deduction', 0) or 0) for d in deductions)
        except (TypeError, ValueError, AttributeError):
            ded_sum = None
        need_review = ded_sum is None or abs((max_score - ded_sum) - score) > 0.01
        if need_review:
            detail_text = f"⚠ 扣分合计({ded_sum})与得分对不上，请人工核对！\n\n" + detail_text
            self.log("⚠ 扣分合计与得分不一致，本份强制人工确认")

        # 设置等待确认状态
        self.waiting_for_confirm = True
        self.pending_score = score
        
        # 弹出确认对话框
        self.show_confirm_dialog(score, max_score, detail_text, force=need_review)

    def init_model(self):
        """初始化模型"""
        provider = self.config.get('provider', 'Gemini')
        api_key = self.config.get('api_key', '')
        
        if provider == 'Gemini':
            if api_key:
                genai.configure(api_key=api_key)
            try:
                self.model = genai.GenerativeModel(self.config.get('model_name', 'gemini-2.5-flash'))
            except:
                pass
        
    def call_ai_api(self, prompt, image, need_json=True):
        """统一调用AI接口"""
        provider = self.config.get('provider', 'Gemini')
        api_key = self.config.get('api_key', '')
        base_url = self.config.get('base_url', '')
        model_name = self.config.get('model_name', '')
        
        if not api_key and provider != 'Custom': # Custom might not need key
             # 尝试使用默认key
             if provider == 'Gemini' and not api_key:
                 api_key = DEFAULT_CONFIG['api_key']
        
        if provider == 'Gemini':
            # Gemini 必须先初始化 self.model
            if not hasattr(self, 'model'):
                self.init_model()
                
            response = self.model.generate_content([prompt, image])
            text = response.text
            if need_json:
                return self.parse_json_result(text)
            else:
                return text
            
        if provider != 'Gemini':
            # 智能检测：如果模型不支持 Vision (如 DeepSeek-V3/Chat)，且在 SiliconFlow，则使用 Qwen-VL "借眼"
            is_text_model = any(k in model_name for k in ['DeepSeek-V3', 'DeepSeek-V2', 'chat', 'coder'])
            is_siliconflow = 'silicon' in base_url and provider != 'Magpie'
            
            if is_text_model and is_siliconflow:
                # 尝试 Vision Relay (OCR -> Text Model)
                try:
                    self.log(f"⚡ 模型 {model_name} 不支持直接识图，正在调用 Qwen-VL 辅助识别...")
                    
                    # 1. 使用 Qwen-VL 识别图片内容
                    ocr_prompt = "请详细描述图片中的学生手写答案内容。直接输出答案文字，不要加任何修饰。"
                    ocr_model = "Qwen/Qwen2-VL-72B-Instruct"
                    
                    # 临时调用 Qwen
                    ocr_result = self._call_siliconflow_vision(api_key, ocr_model, ocr_prompt, image)
                    self.log(f"✓ 识别成功，正在请求 {model_name} 批改...")
                    
                    # 2. 将识别的文本发送给目标模型
                    new_prompt = f"{prompt}\n\n【学生答案文本内容】:\n{ocr_result}"
                    return self._call_text_api(base_url, api_key, model_name, new_prompt, need_json)
                    
                except Exception as e:
                    self.log(f"⚠ 辅助识别失败，尝试直接调用: {e}")
                    # Fallback to direct call (will likely fail if model is text only)
            
            # 常规 Vision 调用 (OpenAI Compatible)
            if not base_url and provider in PROVIDERS:
                base_url = PROVIDERS[provider]['base_url']
            if provider == 'Magpie':
                if not api_key:
                    api_key = PROVIDERS['Magpie']['default_key']
                if not model_name:
                    raise Exception("Magpie 未选择模型：请在“模型设置”里点“获取模型”并选一个能识图的模型")
            
            import urllib.request
            import urllib.error
            import json
            
            # 转换图片为Base64
            buffered = io.BytesIO()
            image.save(buffered, format="PNG")
            img_str = base64.b64encode(buffered.getvalue()).decode()
            
            # 构造 Vision 请求
            url = f"{base_url.rstrip('/')}/chat/completions"
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{img_str}"
                            },
                        },
                    ],
                }
            ]
            
            data = {
                "model": model_name,
                "messages": messages,
                "max_tokens": 4096,
                "temperature": 0  # 阅卷要稳定，同一份卷子多次评分应一致
            }
            
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "ZhixueGrader/1.0"
            }
            
            try:
                req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers=headers)
                with http_open(req) as response:
                    result_str = response.read().decode('utf-8')
                    result_json = json.loads(result_str)
                    content = result_json['choices'][0]['message']['content']
                    
                    if need_json:
                        return self.parse_json_result(content)
                    else:
                        return content
                        
            except urllib.error.HTTPError as e:
                error_body = e.read().decode()
                raise Exception(f"API Error {e.code}: {error_body}")
            except Exception as e:
                raise Exception(f"API Call Failed: {str(e)}")

    def _call_siliconflow_vision(self, api_key, model, prompt, image):
        """内部辅助：调用 SiliconFlow 的 Vision 模型进行 OCR"""
        import urllib.request
        import json
        
        url = "https://api.siliconflow.cn/v1/chat/completions"
        buffered = io.BytesIO()
        image.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        
        data = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_str}"}}
                    ]
                }
            ]
        }
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers=headers)
        with http_open(req) as response:
            res = json.loads(response.read().decode('utf-8'))
            return res['choices'][0]['message']['content']

    def _call_text_api(self, base_url, api_key, model, prompt, need_json):
        """内部辅助：调用纯文本 API"""
        import urllib.request
        import json
        
        url = f"{base_url.rstrip('/')}/chat/completions"
        data = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}]
        }
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers=headers)
        with http_open(req) as response:
            res = json.loads(response.read().decode('utf-8'))
            content = res['choices'][0]['message']['content']
            if need_json:
                return self.parse_json_result(content)
            return content

    def parse_json_result(self, text):
        """解析JSON结果"""
        import re
        text = text.strip()
        if '```json' in text:
            text = text.split('```json')[1].split('```')[0]
        elif '```' in text:
            text = text.split('```')[1].split('```')[0]
        
        text = text.strip()
        
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            # 尝试修复常见的反斜杠转义问题 (特别是 LaTeX)
            # 匹配所有反斜杠，排除合法的转义字符 (", \, /, b, f, n, r, t, uXXXX)
            # 如果反斜杠后面不是这些字符，说明它是非法转义，需要变成双反斜杠
            try:
                # 简单的修复：将所有单个反斜杠替换为双反斜杠（排除已经是双的）
                # 更精细的正则：(?<!\\)\\(?![\\/bfnrtu"'])
                # 这里使用一个比较通用的修复方法
                fixed_text = re.sub(r'\\(?![/bfnrtu"\\{])', r'\\\\', text)
                return json.loads(fixed_text)
            except:
                # 如果还是失败，抛出原始异常或尝试更暴力的修复
                pass
            raise e

    def setup_model(self):
        """设置模型和API"""
        dialog = tk.Toplevel(self.root)
        dialog.title("模型设置")
        dialog.geometry("320x600")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # 居中显示
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")
        
        frame = tk.Frame(dialog, padx=15, pady=15)
        frame.pack(fill=tk.BOTH, expand=True)

        # 获取当前状态和初始数据
        current_provider = self.config.get('provider', 'Gemini')
        
        # 优先使用 stored settings，如果不存在则使用 active config
        # 这解决了"用户修改配置文件但未生效"或"配置不同步"的问题
        initial_settings = self.provider_settings.get(current_provider, {})
        initial_url = initial_settings.get('base_url', self.config.get('base_url', ''))
        initial_key = initial_settings.get('api_key', self.config.get('api_key', ''))
        initial_model = initial_settings.get('model_name', self.config.get('model_name', ''))
        
        # 使用列表存储上一次的provider，以便在闭包中修改
        last_provider_ref = [current_provider]

        # 1. 提供商选择
        tk.Label(frame, text="AI 提供商:", font=('微软雅黑', 9, 'bold')).pack(anchor='w')
        provider_combo = ttk.Combobox(frame, values=list(PROVIDERS.keys()), state="readonly")
        provider_combo.pack(fill=tk.X, pady=(2, 10))
        provider_combo.set(current_provider)
        
        # 2. Base URL
        tk.Label(frame, text="API 地址 (Base URL):", font=('微软雅黑', 9)).pack(anchor='w')
        url_entry = tk.Entry(frame, font=('Consolas', 9))
        url_entry.pack(fill=tk.X, pady=(2, 10))
        url_entry.insert(0, initial_url)
        
        # 3. API Key
        tk.Label(frame, text="API Key:", font=('微软雅黑', 9)).pack(anchor='w')
        key_entry = tk.Entry(frame, font=('Consolas', 9), show="*")
        key_entry.pack(fill=tk.X, pady=(2, 10))
        key_entry.insert(0, initial_key)
        
        # 4. 模型名称
        tk.Label(frame, text="模型名称:", font=('微软雅黑', 9)).pack(anchor='w')
        model_combo = ttk.Combobox(frame, font=('Consolas', 9))
        model_combo.pack(fill=tk.X, pady=(2, 10))
        
        # 初始化模型列表
        current_models = PROVIDERS.get(current_provider, {}).get("models", [])
        model_combo['values'] = current_models
        model_combo.set(initial_model)

        status_lbl = tk.Label(frame, text="", font=('微软雅黑', 8), fg='#666', justify=tk.LEFT, wraplength=260)

        def refresh_models():
            """从当前 Base URL 拉取模型（Magpie / Custom 等 OpenAI 兼容接口）"""
            p = provider_combo.get()
            url = url_entry.get().strip()
            if p == 'Magpie':
                found, ver = magpie_detect()
                if not found:
                    status_lbl.config(text="❌ 没检测到 magpie，请先打开 magpie 应用或运行 magpie serve", fg='#c00')
                    return
                if not url:
                    url = found
                    url_entry.insert(0, url)
            if not url:
                status_lbl.config(text="请先填写 Base URL", fg='#c00')
                return
            try:
                models = fetch_models(url, key_entry.get().strip())
            except Exception as e:
                status_lbl.config(text=f"❌ 获取失败：{e}", fg='#c00')
                return
            model_combo['values'] = models
            if models and model_combo.get() not in models:
                model_combo.set(models[0])
            status_lbl.config(text=f"✓ 获取到 {len(models)} 个模型（批改需选能识图的模型）", fg='#2e7d32')

        tk.Button(frame, text="🔄 获取模型", command=refresh_models).pack(anchor='w', pady=(0, 4))
        status_lbl.pack(anchor='w', pady=(0, 8))
        
        # 联动更新逻辑
        def on_provider_change(event):
            new_p = provider_combo.get()
            old_p = last_provider_ref[0]
            
            if new_p == old_p:
                return

            # 1. 保存旧 Provider 的当前输入状态 (防止切换丢失数据)
            if old_p:
                if old_p not in self.provider_settings:
                    self.provider_settings[old_p] = {}
                self.provider_settings[old_p]['base_url'] = url_entry.get().strip()
                self.provider_settings[old_p]['api_key'] = key_entry.get().strip()
                self.provider_settings[old_p]['model_name'] = model_combo.get().strip()
            
            # 2. 加载新 Provider 的配置
            settings = self.provider_settings.get(new_p, {})
            
            # URL
            default_url = PROVIDERS.get(new_p, {}).get("base_url", "")
            new_url = settings.get('base_url', default_url)
            url_entry.delete(0, tk.END)
            url_entry.insert(0, new_url)
            
            # Key（Magpie 本机任意 key 都行，默认填 magpie-zhixue）
            new_key = settings.get('api_key', '') or PROVIDERS.get(new_p, {}).get('default_key', '')
            key_entry.delete(0, tk.END)
            key_entry.insert(0, new_key)
            
            # Model List & Selection
            models = PROVIDERS.get(new_p, {}).get("models", [])
            model_combo['values'] = models
            
            saved_model = settings.get('model_name', '')
            if saved_model and saved_model in models:
                model_combo.set(saved_model)
            elif models:
                model_combo.set(models[0])
            else:
                model_combo.set('')
            
            # 更新引用
            last_provider_ref[0] = new_p

            # Magpie / Custom 自动拉取模型
            if new_p in ('Magpie', 'Custom'):
                dialog.after(50, refresh_models)
                
        provider_combo.bind("<<ComboboxSelected>>", on_provider_change)
        
        # 说明
        tk.Label(frame, text="说明：\nGemini无需Base URL\nMagpie：先打开本机 magpie，选它后点“获取模型”\n切换时会自动暂存当前输入", 
                 font=('微软雅黑', 8), fg='#666', justify=tk.LEFT).pack(anchor='w', pady=(0, 15))
        
        def save():
            p = provider_combo.get()
            
            # 保存最终状态到 config (Active)
            self.config['provider'] = p
            self.config['base_url'] = url_entry.get().strip()
            self.config['api_key'] = key_entry.get().strip()
            self.config['model_name'] = model_combo.get().strip()
            
            # 同时更新 provider_settings
            if p not in self.provider_settings:
                self.provider_settings[p] = {}
            
            self.provider_settings[p] = {
                'base_url': self.config['base_url'],
                'api_key': self.config['api_key'],
                'model_name': self.config['model_name']
            }
            
            self.save_config()
            try:
                self.init_model() # 重新初始化
                messagebox.showinfo("成功", "设置已保存！")
                dialog.destroy()
            except Exception as e:
                messagebox.showerror("错误", f"模型初始化失败: {str(e)}\n请检查Key或网络设置")
        
        tk.Button(frame, text="保存配置", command=save, bg=self.THEME['primary'], fg='white', activebackground=self.THEME['primary_d'], activeforeground='white', relief=tk.FLAT, bd=0, cursor='hand2', width=15, pady=3).pack(pady=5)
    
    def setup_score_buttons(self):
        """设置自动提交位置"""
        msg = "即将设置自动提交位置\n\n"
        msg += "需要设置2个位置：\n"
        msg += "1. 红色框内的分数输入框\n"
        msg += "2. 绿色的'提交分数'按钮\n\n"
        msg += "每个位置设置时间：5秒"
        
        if not messagebox.askokcancel("设置自动提交", msg):
            return
        
        self.log("\n开始设置自动提交位置...")
        
        # 设置分数输入框
        self.log("\n5秒后，请将鼠标移到【红色框内的分数输入框】")
        for i in range(5, 0, -1):
            self.log(f"{i}...")
            self.root.update()
            time.sleep(1)
        
        self.score_input_box = pyautogui.position()
        self.log(f"✓ 分数输入框位置: {self.score_input_box}")
        
        # 设置提交按钮
        self.log("\n5秒后，请将鼠标移到【绿色的提交分数按钮】")
        for i in range(5, 0, -1):
            self.log(f"{i}...")
            self.root.update()
            time.sleep(1)
        
        self.submit_button_pos = pyautogui.position()
        self.log(f"✓ 提交按钮位置: {self.submit_button_pos}")
        
        self.save_config()
        self.setup_status_label.config(text="● 已定位", fg=self.THEME['ok'])
        self.log("\n✓ 自动提交位置设置完成！")
        messagebox.showinfo("成功", "自动提交位置设置完成！\n\n建议点击'🧪 测试'按钮测试功能")
    
    def test_auto_click(self):
        """测试自动点击功能"""
        if not self.score_input_box or not self.submit_button_pos:
            messagebox.showwarning("提示", "请先设置自动提交位置")
            return
        
        test_score = 10
        msg = f"即将测试自动点击功能\n\n"
        msg += f"测试分数: {test_score}\n"
        msg += f"输入框位置: {self.score_input_box}\n"
        msg += f"提交按钮位置: {self.submit_button_pos}\n\n"
        msg += "请确保阅卷窗口可见\n"
        msg += "3秒后开始测试"
        
        if not messagebox.askokcancel("测试自动点击", msg):
            return
        
        self.log("\n🧪 3秒后开始测试自动点击...")

        def worker():
            time.sleep(3)
            ok = self.auto_click_score(test_score)
            self.ui(lambda: self._test_done(ok))
        threading.Thread(target=worker, daemon=True).start()

    def _test_done(self, result):
        if result:
            messagebox.showinfo("测试成功", f"自动点击测试成功！\n\n请检查：\n1. 分数是否输入到输入框\n2. 提交按钮是否被点击\n\n如果成功，可以开始使用自动批改功能")
        else:
            messagebox.showerror("测试失败", "自动点击测试失败\n\n请检查日志查看详细错误信息")
    
    def on_checkbox_changed(self):
        """复选框改变时的回调"""
        self.auto_continue = self.auto_var.get()
        if self.auto_continue:
            self.log("✓ 已开启自动连续批改")
            self.grade_btn.config(text="▶ 开始连续批改")
        else:
            self.log("⏸ 已关闭自动连续批改")
            self.grade_btn.config(text=self.GRADE_TEXT)
            # 关闭自动模式时禁用暂停按钮
            self.pause_btn.config(state=tk.DISABLED)
        
        # 保存配置
        self.save_config()
    
    def toggle_pause(self):
        """切换暂停/继续"""
        self.is_paused = not self.is_paused
        
        if self.is_paused:
            self.pause_btn.config(text="▶ 继续", bg=self.THEME['ok'], activebackground=self.THEME['ok'])
            self.log("\n⏸ 已暂停批改")
        else:
            self.pause_btn.config(text="⏸ 暂停", bg=self.THEME['slate'], activebackground=self.THEME['slate'])
            self.log("▶ 继续批改\n")
    
    def show_confirm_dialog(self, score, max_score, detail_text, force=False):
        """显示确认对话框；force=True 时即使勾选了“跳过确认”也要人工确认"""
        # 如果勾选了跳过确认，直接自动提交
        if self.skip_confirm_var.get() and not force:
            self.log(f"⚡ 跳过确认，直接提交分数: {score}")
            if self.auto_click_var.get():
                self.submit_score_async(score)
            else:
                self.log(f"⚠ 自动点击未开启，请手动输入分数")
                self.is_grading = False
                self.grade_btn.config(state=tk.NORMAL, text=self.GRADE_TEXT)
            self.waiting_for_confirm = False
            self.pending_score = None
            return
        
        # 构建对话框消息
        msg = f"建议分数: {score}/{max_score} 分\n\n"
        msg += detail_text
        msg += "\n\n是否接受此分数？"
        
        # 创建自定义对话框
        dialog = tk.Toplevel(self.root)
        dialog.title("确认分数")
        dialog.geometry("400x350")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # 居中显示
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")
        
        # 内容框架
        content_frame = tk.Frame(dialog, padx=20, pady=20)
        content_frame.pack(fill=tk.BOTH, expand=True)
        
        # 分数显示（大字体）
        score_label = tk.Label(
            content_frame,
            text=f"建议分数: {score}/{max_score} 分",
            font=('微软雅黑', 16, 'bold'),
            fg='#ff6b00'
        )
        score_label.pack(pady=(0, 15))
        
        # 详情显示
        detail_frame = tk.Frame(content_frame, relief=tk.SUNKEN, bd=1)
        detail_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        detail_scroll = scrolledtext.ScrolledText(
            detail_frame,
            height=8,
            font=('微软雅黑', 9),
            wrap=tk.WORD
        )
        detail_scroll.pack(fill=tk.BOTH, expand=True)
        detail_scroll.insert('1.0', detail_text)
        detail_scroll.config(state=tk.DISABLED)
        
        # 按钮框架
        btn_frame = tk.Frame(content_frame)
        btn_frame.pack(fill=tk.X)
        
        def on_accept():
            """接受分数"""
            dialog.destroy()
            self.log(f"\n✅ 用户确认分数: {self.pending_score}")
            
            # 如果开启自动点击
            if self.auto_click_var.get():
                self.log(f"🤖 自动点击已开启，开始自动提交...")
                self.submit_score_async(self.pending_score)
            else:
                self.log(f"⚠ 自动点击未开启，请手动输入分数")
                self.is_grading = False
                self.grade_btn.config(state=tk.NORMAL, text=self.GRADE_TEXT)
            
            self.waiting_for_confirm = False
            self.pending_score = None
        
        def on_reject():
            """拒绝分数"""
            dialog.destroy()
            self.log(f"\n❌ 用户拒绝分数: {self.pending_score}")
            self.log("请手动在平台输入正确分数")
            self.waiting_for_confirm = False
            self.pending_score = None
            self.is_grading = False
            self.grade_btn.config(state=tk.NORMAL, text=self.GRADE_TEXT)
        
        # 接受按钮
        accept_btn = tk.Button(
            btn_frame,
            text="✓ 接受 (Enter)",
            command=on_accept,
            bg=self.THEME['ok'], relief=tk.FLAT, bd=0,
            fg='white',
            font=('微软雅黑', 11, 'bold'),
            height=2,
            cursor='hand2'
        )
        accept_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        # 拒绝按钮
        reject_btn = tk.Button(
            btn_frame,
            text="✗ 拒绝 (Esc)",
            command=on_reject,
            bg=self.THEME['danger'], relief=tk.FLAT, bd=0,
            fg='white',
            font=('微软雅黑', 11, 'bold'),
            height=2,
            cursor='hand2'
        )
        reject_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))
        
        # 绑定快捷键
        dialog.bind('<Return>', lambda e: on_accept())
        dialog.bind('<Escape>', lambda e: on_reject())
        
        # 聚焦到接受按钮
        accept_btn.focus_set()
    
    def submit_score_async(self, score):
        """在后台线程里自动输入分数并提交，界面不再卡住，暂停/停止按钮随时可点"""
        threading.Thread(target=self.auto_click_score, args=(score,), daemon=True).start()

    def auto_click_score(self, score):
        """自动输入分数并提交（在后台线程运行）"""
        score = float(score)
        score = int(score) if score == int(score) else score  # 支持 0.5 分
        
        if not self.score_input_box or not self.submit_button_pos:
            self.log("⚠ 未设置自动提交位置")
            self.ui(lambda: messagebox.showwarning("提示", "未设置自动提交位置\n请点击'⚙ 设置按钮'"))
            self.ui(self.stop_grading)
            return False
        
        try:
            self.log(f"\n🤖 开始自动提交...")
            self.log(f"分数: {score}")
            self.log(f"输入框位置: {self.score_input_box}")
            self.log(f"提交按钮位置: {self.submit_button_pos}")
            
            # 1. 三次点击分数输入框（确保选中）
            self.log(f"→ 点击分数输入框...")
            for i in range(3):
                pyautogui.click(self.score_input_box[0], self.score_input_box[1])
                time.sleep(0.1)
            time.sleep(0.3)
            self.log(f"✓ 已点击分数输入框")
            
            # 2. 多次清空输入框（确保清空）
            self.log(f"→ 清空输入框...")
            for i in range(3):
                pyautogui.hotkey('ctrl', 'a')
                time.sleep(0.05)
                pyautogui.press('backspace')
                time.sleep(0.05)
            time.sleep(0.2)
            self.log(f"✓ 已清空")
            
            # 3. 输入分数（使用多种方法）
            self.log(f"→ 输入分数 {score}...")
            score_str = str(score)
            
            # 方法1: 尝试typewrite
            try:
                pyautogui.typewrite(score_str, interval=0.1)
                self.log(f"✓ 使用typewrite输入")
            except:
                # 方法2: 逐个按键
                self.log(f"→ typewrite失败，使用press方法...")
                for char in score_str:
                    pyautogui.press(char)
                    time.sleep(0.1)
                self.log(f"✓ 使用press输入")
            
            time.sleep(0.3)
            self.log(f"✓ 已输入分数: {score}")
            
            # 4. 点击提交按钮（多次点击确保成功）
            self.log(f"→ 点击提交按钮...")
            pyautogui.click(self.submit_button_pos[0], self.submit_button_pos[1])
            time.sleep(0.2)
            pyautogui.click(self.submit_button_pos[0], self.submit_button_pos[1])
            time.sleep(0.5)
            self.log(f"✓ 已点击提交按钮")
            
            # 5. 等待系统处理（缩短等待时间）
            wait_time = 1.5 if self.skip_confirm_var.get() else 2
            self.log(f"⏱ 等待{wait_time}秒让系统处理...")
            time.sleep(wait_time)
            
            # 6. 如果是自动连续模式，继续批改
            if self.auto_continue:
                # 跳过确认模式下缩短等待时间
                next_delay = 1 if self.skip_confirm_var.get() else 2
                self.log(f"⏱ {next_delay}秒后批改下一个学生...")
                
                # 等待时检查暂停状态（后台线程里等，界面照常响应）
                for i in range(int(next_delay * 10)):
                    if self.is_paused:
                        self.log(f"⏸ 已暂停，等待继续...")
                        while self.is_paused and self.auto_continue:
                            time.sleep(0.1)
                        self.log(f"▶ 继续批改...")
                        break
                    if not self.auto_continue:
                        break
                    time.sleep(0.1)
                
                # 重置状态后再批改
                self.is_grading = False
                self.waiting_for_confirm = False
                self.pending_score = None
                if self.auto_continue:  # 等待期间可能按了停止
                    self.log(f"✓ 开始批改下一个...\n")
                    self.ui(self.grade_answer)
            else:
                self.log(f"✓ 自动提交完成\n")
                self.is_grading = False
                self.ui(lambda: self.pause_btn.config(state=tk.DISABLED))
                self.ui(lambda: self.grade_btn.config(state=tk.NORMAL, text=self.GRADE_TEXT))
            
            return True
        except Exception as e:
            self.log(f"❌ 自动提交失败: {str(e)}")
            import traceback
            self.log(traceback.format_exc())
            err = str(e)
            self.ui(self.stop_grading)
            self.ui(lambda: messagebox.showerror("错误", f"自动提交失败：{err}\n\n请检查：\n1. 是否正确设置了位置\n2. 阅卷窗口是否可见\n3. 输入框是否可编辑\n（鼠标甩到屏幕左上角会触发紧急停止）"))
            return False
    
    def stop_grading(self):
        """停止批改"""
        self.is_grading = False
        self.auto_continue = False
        self.is_paused = False
        self.auto_var.set(False)
        self.pause_btn.config(state=tk.DISABLED, text="⏸ 暂停", bg=self.THEME['slate'])
        self.grade_btn.config(state=tk.NORMAL, text=self.GRADE_TEXT)
        self.log("\n⏹ 批改已停止")
    
    def update_stats(self):
        """更新统计"""
        avg = self.total_time / self.grading_count if self.grading_count > 0 else 0
        eff = int(3600 / avg) if avg > 0 else 0
        self.stats_label.config(text=f"已批 {self.grading_count} · 用时 {self.total_time:.0f}s · 均 {avg:.1f}s · {eff}/h")
    
    def ui(self, fn):
        """在主线程执行 fn（后台线程调用界面一律走这里）"""
        if threading.current_thread() is self._main_thread:
            fn()
        else:
            self._uiq.put(fn)

    def _drain_ui_queue(self):
        try:
            while True:
                fn = self._uiq.get_nowait()
                try:
                    fn()
                except Exception as e:
                    print("UI 回调出错:", e)
        except Exception:
            pass
        self.root.after(50, self._drain_ui_queue)

    def log(self, message):
        """输出日志（任何线程都可以调用）"""
        def _do():
            if not hasattr(self, 'result_text'):
                print(message)
                return
            self.result_text.insert(tk.END, message + "\n")
            self.result_text.see(tk.END)
        self.ui(_do)

    # ================= 在线更新 =================
    def check_update_ui(self, silent=False):
        import sys
        if getattr(sys, 'frozen', False):
            if not silent:
                messagebox.showinfo("在线更新", "当前是打包版 exe，请到 GitHub 下载新版本。")
            return
        if self.is_grading and not silent:
            messagebox.showwarning("在线更新", "正在批改，请先停止再更新")
            return
        self.ui(lambda: self.update_btn.config(state=tk.DISABLED, text="检查中"))

        def worker():
            try:
                has_new, info, base = check_update(self.config.get('update_url', ''))
            except Exception as e:
                if not silent:
                    err = str(e)
                    self.ui(lambda: messagebox.showerror("在线更新", err))
                else:
                    self.log(f"（检查更新失败：{e}）")
                self.ui(lambda: self.update_btn.config(state=tk.NORMAL, text="更新"))
                return
            self.ui(lambda: self.update_btn.config(state=tk.NORMAL, text="更新"))
            if not has_new:
                if not silent:
                    self.ui(lambda: messagebox.showinfo("在线更新", f"已是最新版本 v{APP_VERSION}"))
                return
            if silent:
                self.ui(lambda: self.update_btn.config(text="有新版", bg=self.THEME['danger'], activebackground=self.THEME['danger']))
            self.ui(lambda: self._ask_and_update(info, base))

        threading.Thread(target=worker, daemon=True).start()

    def _ask_and_update(self, info, base):
        if self.is_grading:
            self.log(f"🔔 发现新版本 v{info.get('version')}，批改结束后点 ⬆ 更新")
            return
        msg = f"发现新版本 v{info.get('version')}（当前 v{APP_VERSION}）\n\n{info.get('notes', '')}\n\n现在更新并重启？\n（旧文件会备份到 backup 文件夹，配置不受影响）"
        if not messagebox.askyesno("在线更新", msg):
            return
        self.log("⬇ 正在下载更新...")

        def worker():
            try:
                files, bdir = apply_update(info, base)
            except Exception as e:
                err = str(e)
                self.ui(lambda: messagebox.showerror("更新失败", err))
                return
            self.log(f"✓ 已更新 {', '.join(files)}，备份在 {bdir}")
            self.ui(self._restart)

        threading.Thread(target=worker, daemon=True).start()

    def _restart(self):
        import sys, os, subprocess
        self.save_config()
        messagebox.showinfo("更新完成", "更新完成，程序将重新启动。")
        subprocess.Popen([sys.executable] + sys.argv, cwd=os.getcwd())
        self.root.destroy()
    
    def schedule_save(self, event=None):
        """防抖自动保存"""
        if self.save_timer:
            self.root.after_cancel(self.save_timer)
        self.save_timer = self.root.after(500, self.save_config)
        
    def save_question_data(self):
        """保存题目数据（触发防抖保存）"""
        self.schedule_save()

    def save_config(self):
        """保存配置"""
        try:
            # 主动从UI获取最新值 (防止FocusOut未触发)
            if hasattr(self, 'question_num_entry'):
                self.saved_question_num = self.question_num_entry.get().strip()
            if hasattr(self, 'max_score_entry'):
                self.saved_max_score = self.max_score_entry.get().strip()
            if hasattr(self, 'answer_text'):
                self.saved_answer = self.answer_text.get('1.0', tk.END).strip()
            if hasattr(self, 'delay_entry'):
                self.saved_delay = self.delay_entry.get().strip()

            config = {
                'answer_region': self.answer_region,
                'score_input_box': list(self.score_input_box) if self.score_input_box else None,
                'submit_button_pos': list(self.submit_button_pos) if self.submit_button_pos else None,
                'question_num': self.saved_question_num,
                'max_score': self.saved_max_score,
                'answer': self.saved_answer,
                'auto_continue': self.auto_var.get() if hasattr(self, 'auto_var') else False,
                'auto_click': self.auto_click_var.get() if hasattr(self, 'auto_click_var') else False,
                'skip_confirm': self.skip_confirm_var.get() if hasattr(self, 'skip_confirm_var') else False,
                'delay': self.saved_delay,
                'api_key': self.config.get('api_key', ''),
                'model_name': self.config.get('model_name', ''),
                'provider': self.config.get('provider', 'Gemini'),
                'base_url': self.config.get('base_url', ''),
                'provider_settings': getattr(self, 'provider_settings', {}),
                'obsidian_path': getattr(self, 'obsidian_path', ''),
                'last_updated': datetime.now().isoformat()
            }
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            print("配置已保存")
        except Exception as e:
            print(f"保存配置失败: {e}")
    
    def load_config(self):
        """加载配置"""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
                self.answer_region = tuple(config['answer_region']) if config.get('answer_region') else None
                
                # 加载自动提交位置
                self.score_input_box = tuple(config['score_input_box']) if config.get('score_input_box') else None
                self.submit_button_pos = tuple(config['submit_button_pos']) if config.get('submit_button_pos') else None
                
                # 加载题目数据
                self.saved_question_num = config.get('question_num', '')
                self.saved_max_score = config.get('max_score', '10')
                self.saved_answer = config.get('answer', '')
                
                # 加载复选框状态
                self.saved_auto_continue = config.get('auto_continue', False)
                self.saved_auto_click = config.get('auto_click', False)
                self.saved_skip_confirm = config.get('skip_confirm', False)
                self.saved_delay = config.get('delay', '3')
                
                # 加载模型配置
                self.config = {
                    'provider': config.get('provider', 'Gemini'),
                    'api_key': config.get('api_key', ''),
                    'base_url': config.get('base_url', ''),
                    'model_name': config.get('model_name', DEFAULT_CONFIG['model_name'])
                }
                
                # 加载多提供商配置
                self.provider_settings = config.get('provider_settings', {})
                
                # SiliconFlow 默认配置 (如果不存在)
                if "SiliconFlow" not in self.provider_settings:
                    self.provider_settings["SiliconFlow"] = {
                        "base_url": "https://api.siliconflow.cn/v1",
                        "api_key": "sk-lyngjsmigyodfmdwvmzyzishmwhfeaownhghkyjsryosvluk",
                        "model_name": "Qwen/Qwen2-VL-72B-Instruct"
                    }
                
                # 如果没有 provider_settings，尝试从当前的 config 初始化一个（针对旧版本配置文件）
                if not self.provider_settings:
                    current_provider = self.config['provider']
                    self.provider_settings[current_provider] = {
                        'api_key': self.config['api_key'],
                        'base_url': self.config['base_url'],
                        'model_name': self.config['model_name']
                    }
                
                # 修复: 同步 Active Config 到 Provider Settings (优先信任 Root Config)
                # 这确保了手动修改配置文件(Root层级)能正确更新到 Provider Settings
                current_provider = self.config['provider']
                
                # 初始化该 Provider 的设置 (如果不存在)
                if current_provider not in self.provider_settings:
                    self.provider_settings[current_provider] = {}
                
                # 更新 Provider Settings (强制同步 Root Config 到 Settings)
                self.provider_settings[current_provider]['api_key'] = self.config['api_key']
                self.provider_settings[current_provider]['base_url'] = self.config['base_url']
                self.provider_settings[current_provider]['model_name'] = self.config['model_name']
                
                self.obsidian_path = config.get('obsidian_path', '')
                
        except Exception as e:
            print(f"配置文件加载失败: {e}")
            import traceback
            traceback.print_exc()
            # 设置默认值
            self.saved_auto_continue = False
            self.saved_auto_click = False
            self.saved_skip_confirm = False
            self.saved_delay = '3'
            self.config = DEFAULT_CONFIG.copy()

    def setup_obsidian_path(self):
        """设置 Obsidian 路径"""
        from tkinter import filedialog
        path = filedialog.askdirectory(title="选择 Obsidian 仓库根目录 (Vault)")
        if path:
            self.obsidian_path = path
            self.save_config()
            messagebox.showinfo("成功", f"已设置笔记路径：\n{path}\n\n批改结果将自动追加到当天的日记中。")

    def save_to_obsidian(self, result, max_score, image, model_name="Unknown", elapsed=0, avg_time=0):
        """保存结果到 Obsidian"""
        if not self.obsidian_path:
            return
            
        try:
            import os
            
            # 1. 准备目录
            # 默认保存到 'Grading' 文件夹，图片保存到 'attachments'
            note_dir = os.path.join(self.obsidian_path, "Grading")
            attach_dir = os.path.join(self.obsidian_path, "attachments")
            
            if not os.path.exists(note_dir):
                os.makedirs(note_dir)
            if not os.path.exists(attach_dir):
                os.makedirs(attach_dir)
                
            # 2. 保存图片
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            img_filename = f"grading_{timestamp}.png"
            img_path = os.path.join(attach_dir, img_filename)
            image.save(img_path)
            
            # 3. 准备笔记内容
            today = datetime.now().strftime("%Y-%m-%d")
            note_file = os.path.join(note_dir, f"{today}.md")
            
            question_num = self.question_num_entry.get().strip()
            score = result.get('score', 0)
            analysis = result.get('analysis', '')
            deductions = result.get('deduction_details', [])
            
            content = f"\n\n## 📝 题号 {question_num} ({datetime.now().strftime('%H:%M')})\n"
            content += f"- **模型**: {model_name}\n"
            content += f"- **耗时**: {elapsed:.2f}s (Avg: {avg_time:.1f}s)\n"
            content += f"- **得分**: {score}/{max_score}\n"
            content += f"- **评语**: {analysis}\n"
            
            if deductions:
                content += "- **扣分详情**:\n"
                for d in deductions:
                    content += f"    - {d['point']}: -{d['deduction']}\n"
            
            content += f"\n![[{img_filename}]]\n"
            content += "---\n"
            
            # 4. 追加写入
            with open(note_file, 'a', encoding='utf-8') as f:
                f.write(content)
                
            self.log(f"✓ 已保存笔记到 Obsidian")
            
        except Exception as e:
            self.log(f"⚠ 保存笔记失败: {str(e)}")

    def save_to_html(self, result, max_score, image, model_name="Unknown", elapsed=0, avg_time=0):
        """保存结果为 HTML"""
        try:
            import os
            
            # 确定保存目录 (如果有 Obsidian 路径，存在那里，否则存在当前目录下)
            base_dir = self.obsidian_path if (hasattr(self, 'obsidian_path') and self.obsidian_path) else os.getcwd()
            html_dir = os.path.join(base_dir, "Grading_HTML")
            img_dir = os.path.join(html_dir, "images")
            
            if not os.path.exists(html_dir):
                os.makedirs(html_dir)
            if not os.path.exists(img_dir):
                os.makedirs(img_dir)
            
            # 1. 保存图片
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            img_filename = f"img_{timestamp}.png"
            img_path = os.path.join(img_dir, img_filename)
            image.save(img_path)
            
            # 2. 准备 HTML 内容
            today = datetime.now().strftime("%Y-%m-%d")
            html_file = os.path.join(html_dir, f"{today}.html")
            
            question_num = self.question_num_entry.get().strip()
            score = result.get('score', 0)
            analysis = result.get('analysis', '')
            deductions = result.get('deduction_details', []) # 修正变量名
            time_str = datetime.now().strftime('%H:%M:%S')
            
            # 构造单个卡片 HTML
            card_html = f"""
            <div class="card">
                <div class="header">
                    <span class="title">题号: {question_num}</span>
                    <span class="model-tag">{model_name}</span>
                    <span class="time">⏱ {elapsed:.1f}s</span>
                    <span class="time" style="font-size: 0.8em; opacity: 0.7;">(Avg: {avg_time:.1f}s)</span>
                    <span class="time">{time_str}</span>
                </div>
                <div class="content">
                    <div class="score-box">
                        得分: <span class="score">{score}</span> / {max_score}
                    </div>
                    <div class="analysis-box">
                        <p><strong>评语:</strong> {analysis}</p>
            """
            
            if deductions:
                card_html += "<ul>"
                for d in deductions:
                    card_html += f"<li>{d['point']}: <span class='deduction'>-{d['deduction']}</span></li>"
                card_html += "</ul>"
            
            card_html += f"""
                    </div>
                    <div class="img-box">
                        <img src="images/{img_filename}" alt="Student Answer" onclick="window.open(this.src)">
                    </div>
                </div>
            </div>
            """
            
            # 如果文件不存在，写入头部
            if not os.path.exists(html_file):
                with open(html_file, 'w', encoding='utf-8') as f:
                    f.write(f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>阅卷记录 - {today}</title>
    <style>
        body {{ font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; background-color: #f5f5f5; }}
        .card {{ background: white; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin-bottom: 24px; overflow: hidden; border: 1px solid #e0e0e0; }}
        .header {{ background: #2196F3; color: white; padding: 12px 20px; display: flex; justify-content: space-between; align-items: center; }}
        .title {{ font-size: 1.1em; font-weight: bold; }}
        .time {{ font-size: 0.9em; opacity: 0.9; }}
        .content {{ padding: 20px; }}
        .score-box {{ font-size: 1.4em; font-weight: bold; color: #333; margin-bottom: 15px; border-bottom: 2px solid #eee; padding-bottom: 10px; }}
        .score {{ color: #d32f2f; font-size: 1.5em; }}
        .analysis-box {{ color: #555; line-height: 1.6; margin-bottom: 20px; }}
        .deduction {{ color: #f44336; font-weight: bold; }}
        .img-box img {{ max-width: 100%; border-radius: 8px; border: 1px solid #eee; cursor: pointer; transition: transform 0.2s; }}
        .img-box img:hover {{ transform: scale(1.01); }}
        ul {{ background: #fff3e0; padding: 10px 10px 10px 30px; border-radius: 6px; }}
    </style>
</head>
<body>
    <h1>📅 阅卷记录: {today}</h1>
""")
            
            # 追加内容 (注意：追加在 </body> 之前)
            # 简单的追加方式：读取最后几行，如果是 </body></html> 则移除，追加新内容，再加回去
            # 或者直接追加，浏览器通常能容忍即使在 </body> 后追加，但为了规范，我们尝试简单处理
            
            # 读取当前文件内容
            with open(html_file, 'r+', encoding='utf-8') as f:
                content = f.read()
                if "</body>" in content:
                    # 插入到 </body> 之前
                    new_content = content.replace("</body>", f"{card_html}\n</body>")
                    f.seek(0)
                    f.truncate()
                    f.write(new_content)
                else:
                    # 如果格式不标准，直接追加
                    f.seek(0, 2)
                    f.write(card_html)
            
            self.log(f"✓ 已导出 HTML 记录")
            
        except Exception as e:
            self.log(f"⚠ 导出 HTML 失败: {str(e)}")




def main():
    root = tk.Tk()
    app = SimpleGradingUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
