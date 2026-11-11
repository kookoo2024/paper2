"""
知学网阅卷助手 - 简化版（大题批改）
一次只批改一道题，适合主观题详细批改
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import pyautogui
from PIL import Image, ImageTk
import json
import time
from datetime import datetime
import threading


import base64
import urllib.request
import urllib.error
import io

HTTP_TIMEOUT = 120  # 兜底超时（秒）；批改调用会传更短的 15 秒目标
GRADE_TIMEOUT = 15  # 单题批改硬上限：超过就中止，保证整体 <20 秒

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
    # base_url 已预设好，选好提供商后只需填 Key；key_url 是申请 Key 的网址
    "Gemini": {
        "base_url": "",
        "models": ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash"],
        "key_url": "https://aistudio.google.com/apikey",
        "note": "谷歌官方，需能访问谷歌",
    },
    "SiliconFlow": {
        "base_url": "https://api.siliconflow.cn/v1",
        "models": ["Qwen/Qwen2.5-VL-72B-Instruct", "Qwen/Qwen2.5-VL-32B-Instruct", "Qwen/Qwen3-VL-32B-Instruct", "Qwen/Qwen2-VL-72B-Instruct"],
        "key_url": "https://cloud.siliconflow.cn/account/ak",
        "note": "硅基流动，国内直连",
    },
    "阿里云百炼": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen-vl-max", "qwen-vl-plus", "qwen3-vl-plus", "qwen3-vl-flash", "qwen2.5-vl-72b-instruct"],
        "key_url": "https://bailian.console.aliyun.com/?apiKey=1",
        "note": "通义千问 VL，国内直连",
    },
    "智谱": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": ["glm-4.5v", "glm-4v-plus-0111", "glm-4v-flash"],
        "key_url": "https://bigmodel.cn/usercenter/proj-mgmt/apikeys",
        "note": "GLM 识图模型，glm-4v-flash 免费",
    },
    "火山方舟": {
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "models": ["doubao-seed-1-6-flash-250828", "doubao-seed-1-6-vision-250815", "doubao-1-5-vision-pro-32k-250115"],
        "key_url": "https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey",
        "note": "豆包识图模型，需先在控制台开通对应模型",
    },
    "Kimi": {
        "base_url": "https://api.moonshot.cn/v1",
        "models": ["moonshot-v1-8k-vision-preview", "moonshot-v1-32k-vision-preview", "kimi-latest"],
        "key_url": "https://platform.moonshot.cn/console/api-keys",
        "note": "月之暗面",
    },
    "DeepSeek": {
        "base_url": "https://api.deepseek.com",
        "models": ["deepseek-chat"],
        "key_url": "https://platform.deepseek.com/api_keys",
        "note": "官方模型只认文字、不能看图，阅卷请选其他家",
    },
    "OpenAI": {
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4.1-mini", "gpt-4o-mini", "gpt-5-mini", "gpt-4.1"],
        "key_url": "https://platform.openai.com/api-keys",
        "note": "需能访问 OpenAI",
    },
    "OpenRouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "models": ["google/gemini-2.5-flash", "qwen/qwen2.5-vl-72b-instruct", "openai/gpt-4.1-mini"],
        "key_url": "https://openrouter.ai/keys",
        "note": "一个 Key 用多家模型",
    },
    "Magpie": {
        # 本机 magpie 网关（https://usemagpie.ai），任意 key 均可，用 magpie-<应用名> 方便在 Usage 里区分
        "base_url": "http://127.0.0.1:3425/v1",
        "default_key": "magpie-zhixue",
        "models": [],  # 运行时从 /v1/models 获取
        "note": "本机 magpie 网关，Key 已默认填好",
    },
    "Custom": {
        "base_url": "http://localhost:11434/v1",
        "models": [],
        "note": "自定义（默认本机 Ollama），地址可改",
    },
}

GEMINI_OPENAI_URL = "https://generativelanguage.googleapis.com/v1beta/openai"

# ================= Gemini Key 池轮换（2026-11-11） =================
import os as _os  # 模块顶部可能尚未 import os，这里自备
KEYS_PATH = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "keys.json")

def _keys_load():
    try:
        with open(KEYS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def keys_status():
    """返回 (可用key列表, 池dict)——过滤掉冷却中的 key"""
    kp = _keys_load()
    if not kp:
        return [], None
    now = time.time()
    alive = [k for k in kp.get("pool", [])
             if kp.get("cooldown", {}).get(k, 0) <= now]
    return alive, kp

def keys_cooldown(kp, k, seconds=65):
    """把 key k 冷却 seconds 秒并落盘"""
    kp.setdefault("cooldown", {})[k] = time.time() + seconds
    try:
        json.dump(kp, open(KEYS_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception:
        pass

def gemini_request_raw(api_key, model_name, body_bytes, timeout):
    """单次 Gemini REST 调用，返回 (text, usage_dict)。供轮换循环调用。"""
    import urllib.request, urllib.error
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model_name or 'gemini-2.5-flash'}:generateContent")
    req = urllib.request.Request(url, data=body_bytes, headers={
        "Content-Type": "application/json", "x-goog-api-key": api_key})
    with http_open(req, timeout=timeout) as resp:
        rj = json.loads(resp.read().decode("utf-8"))
    text = rj["candidates"][0]["content"]["parts"][0]["text"]
    return text, rj.get("usageMetadata", {})

GEMINI_429_HINT = ("Gemini 额度用尽：免费档常见 20 次/天/项目，同一项目下多个 key 共用额度。"
                   "程序会自动改用本机 Magpie；也可在「模型」里换 SiliconFlow/智谱等。")
class QuotaError(Exception):
    """API 额度/限流错误：外层会自动尝试本机 Magpie。"""

# ================= 在线更新 =================
APP_VERSION = "1.7.3"
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


def image_to_data_url(image, max_side=1600):
    """答题截图压缩成灰度 JPEG：手写清晰度够用，体积通常只有 PNG 的 1/5，上传更快"""
    img = image.convert('L')
    w, h = img.size
    if max(w, h) > max_side:
        k = max_side / max(w, h)
        img = img.resize((int(w * k), int(h * k)))
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


STATS = {}   # 最近一次请求的耗时统计，用于日志诊断


def post_chat_plain(url, data, headers, timeout=HTTP_TIMEOUT):
    import json
    body = dict(data)
    body.pop('stream', None)
    req = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'), headers=headers)
    with http_open(req, timeout=timeout) as resp:
        j = json.loads(resp.read().decode('utf-8'))
    msg = j['choices'][0]['message']
    text = msg.get('content') or ''
    if not text.strip():
        if msg.get('reasoning_content'):
            raise Exception(REASONING_ONLY_MSG)
        raise Exception("模型没有返回内容")
    return text


REASONING_ONLY_MSG = ("模型只输出了思考过程、没给出结果（这是推理/思考型模型，太慢且容易超长）。"
                      "建议在「模型」里换一个不带 thinking/R1/推理 字样的识图模型")


def post_chat_stream(url, data, headers, log=None, timeout=HTTP_TIMEOUT):
    """以流式方式请求 chat/completions，边收边拼，并每 5 秒报一次进度；
    服务器不支持流式时按普通 JSON 解析；流式拿不到内容时再用普通方式请求一次。
    总耗时超过 timeout 秒会主动中止，保证单题不被慢模型拖住。"""
    import json
    body = dict(data, stream=True)
    req = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'), headers=headers)
    t0 = last_report = time.time()
    parts, think_chars, finish = [], 0, None
    STATS.update(first=None, think=0, chars=0, t0=t0)
    with http_open(req, timeout=timeout) as resp:
        ctype = resp.headers.get('Content-Type', '')
        if 'event-stream' not in ctype:
            j = json.loads(resp.read().decode('utf-8'))
            msg = j['choices'][0]['message']
            if not (msg.get('content') or '').strip():
                raise Exception(REASONING_ONLY_MSG if msg.get('reasoning_content') else "模型没有返回内容")
            return msg['content']
        for raw in resp:
            if time.time() - t0 > timeout:
                raise TimeoutError(f"模型超过 {timeout} 秒未完成")
            line = raw.decode('utf-8', 'ignore').strip()
            if not line.startswith('data:'):
                continue
            payload = line[5:].strip()
            if payload == '[DONE]':
                break
            try:
                j = json.loads(payload)
            except ValueError:
                continue
            if j.get('error'):
                raise Exception(str(j['error']))
            for ch in j.get('choices') or []:
                d = ch.get('delta') or ch.get('message') or {}
                c = d.get('content')
                if isinstance(c, list):   # 少数接口把内容拆成数组
                    c = ''.join(x.get('text', '') for x in c if isinstance(x, dict))
                if c:
                    if STATS['first'] is None:
                        STATS['first'] = time.time() - t0
                    parts.append(c)
                rc = d.get('reasoning_content') or d.get('reasoning')
                if rc:
                    think_chars += len(rc)
                finish = ch.get('finish_reason') or finish
            if log and time.time() - last_report >= 5:
                last_report = time.time()
                got = sum(len(x) for x in parts)
                if got:
                    log(f"  …已收到 {got} 字（{time.time() - t0:.0f} 秒）")
                elif think_chars:
                    log(f"  …模型思考中，已想了 {think_chars} 字（{time.time() - t0:.0f} 秒）")
                else:
                    log(f"  …等待模型回应（{time.time() - t0:.0f} 秒）")
    text = ''.join(parts)
    STATS.update(think=think_chars, chars=len(text))
    if text.strip():
        return text
    if time.time() - t0 > timeout:
        raise TimeoutError(f"模型超过 {timeout} 秒未完成")
    if think_chars:
        raise Exception(REASONING_ONLY_MSG)
    if log:
        log("  流式没拿到内容，改用普通方式再请求一次…")
    return post_chat_plain(url, data, headers, timeout=timeout)


def no_think_params(model_name, base_url):
    """尽量关掉模型的“思考”：阅卷是看图打分，不需要长推理，开着思考一份要几十秒甚至几分钟"""
    m = (model_name or '').lower()
    u = (base_url or '').lower()
    if 'deepseek-v4.1-flash' in m:
        return {"reasoning_effort": "none"}
    if 'siliconflow' in u:
        return {"enable_thinking": False}
    if 'bigmodel.cn' in u or 'volces.com' in u:
        return {"thinking": {"type": "disabled"}} if ('4.5v' in m or 'seed' in m or '4.1v' in m) else {}
    if 'gemini-2.5' in m or 'gemini-3' in m:
        return {"reasoning_effort": "none"} if 'pro' not in m else {"reasoning_effort": "low"}
    if m.startswith(('gpt-5', 'o3', 'o4')) or '/gpt-5' in m:
        return {"reasoning_effort": "minimal"}
    if 'qwen3' in m or 'glm-4.5v' in m or 'glm-4.1v' in m:
        return {"enable_thinking": False}
    return {}


def is_retryable(err):
    m = str(err).lower()
    return any(k in m for k in ('timed out', 'timeout', 'temporarily', 'connection reset', 'remote end closed',
                                'api error 429', 'api error 500', 'api error 502', 'api error 503', 'api error 504'))


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


def choose_magpie_model(models):
    """从 Magpie 模型里挑一个识图快、不会“只想不答”的。
    group/group 是路由组，容易走思考模型把 token 全花在 reasoning 上，放最后。"""
    preferred = [
        "workbuddy/deepseek-v4.1-flash",
        "auto/deepseek-v4.1-flash",
        "workbuddy/glm-5.3-flash",
        "auto/glm-5.3-flash",
        "zcode/GLM-5.3-Flash",
        "opencode-zen-free/step-5-preview-free",
    ]
    for name in preferred:
        if name in models:
            return name
    for name in models:
        if name != "group/group":
            return name
    return models[0] if models else ""


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


# ---------------- 评分辅助 ----------------
def fmt_score(x):
    """10.0 -> 10，7.5 -> 7.5"""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return x
    return int(x) if abs(x - round(x)) < 1e-9 else round(x, 2)


def parse_rubric(text):
    """兼容旧调用：返回 (给分点, 分值) + 未带分值的说明。"""
    rules = parse_rubric_rules(text)
    return rules["scored"] + [(n, None) for n in rules["notes"]]


def auto_rubric_from_answer(answer, max_score):
    """从参考答案末尾的「……5分」「……15分」自动拆给分点。
    若分值是累计分（常见写法），自动换算成每一步的增量，合计等于满分。"""
    import re
    rows = []
    for line in (answer or "").splitlines():
        line = line.strip()
        m = re.match(r"^(.*?)[\s…·.．]*[（(【\[]?\s*(?:得|给)?\s*([0-9]+(?:\.[0-9]+)?)\s*分\s*[)）】\]]?[。；;]?\s*$", line)
        if not m or not m.group(1).strip():
            continue
        point = m.group(1).strip().rstrip(" .…·")
        if point[:2] in ("所以", "因此"):
            point = point[2:].strip()
        rows.append((point, float(m.group(2))))
    if not rows:
        return ""

    vals = [v for _, v in rows]
    # 累计分：5、7、15 -> 5、2、8
    if len(vals) >= 2 and abs(vals[-1] - float(max_score)) <= 0.01 and all(
            vals[i] <= vals[i + 1] + 1e-9 for i in range(len(vals) - 1)):
        out, prev = [], 0.0
        for point, v in rows:
            inc = v - prev
            prev = v
            if inc > 0:
                out.append(f"{point}｜{fmt_score(inc)}")
        return "\n".join(out)

    # 单步分：直接相加必须等于满分
    if abs(sum(vals) - float(max_score)) <= 0.01:
        return "\n".join(f"{point}｜{fmt_score(v)}" for point, v in rows)
    return ""


def auto_part_rubric(answer, max_score):
    """按参考答案里的 (1)/(2) 分问，生成“大步骤”给分点。

    多问题目用大步骤判分更稳：参考解里的中间式（如先写圆方程再相减）
    不会被拆成独立小点，学生用等价解法时也不会因为没写某个中间式被误扣。
    """
    import re
    lines = (answer or "").splitlines()
    score_tail = (r"[\s…·.．]*[（(【\[]?\s*(?:得|给)?\s*"
                  r"[0-9]+(?:\.[0-9]+)?\s*分\s*[)）】\]]?[。；;]?\s*$")
    parts = []
    for i, line in enumerate(lines):
        m = re.search(r"(?:^|[：:。；;\s])[（(]\s*([0-9一二三四五六七八九十]+)\s*[）)]", line)
        if not m:
            continue
        num = m.group(1)
        if not (num.isdigit() or num in "一二三四五六七八九十"):
            continue
        desc = line[m.end():].strip(" ：:。；;")
        desc = re.sub(r"^解\s*[:：]?\s*", "", desc)
        desc = re.sub(score_tail, "", desc)
        parts.append((f"第({num})问", desc, i))
    # 同一个分问只取第一次出现
    seen, uniq = set(), []
    for p in parts:
        if p[0] not in seen:
            seen.add(p[0])
            uniq.append(p)
    parts = uniq
    if len(parts) < 2:
        return []

    scores, descs = [], []
    for idx, (label, desc, start) in enumerate(parts):
        end = parts[idx + 1][2] if idx + 1 < len(parts) else len(lines)
        last = None
        for line in lines[start:end]:
            m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*分\s*$", line.strip())
            if m:
                last = float(m.group(1))
        if last is None:
            return []
        scores.append(last)
        body = [ln.strip() for ln in lines[start:end] if ln.strip()]
        tail = re.sub(score_tail, "", body[-1]).strip(" ：:。；;") if body else ""
        tail = re.sub(r"^(综上所述|综上|所以|故|即|则)[，,：: ]*", "", tail)
        if tail and tail != desc:
            merged = f"{desc}……{tail}"
            if len(merged) <= 120:
                desc = merged
        descs.append(desc)

    if abs(scores[-1] - float(max_score)) > 0.01:
        return []
    if any(scores[i] > scores[i + 1] + 1e-9 for i in range(len(scores) - 1)):
        return []

    out, prev = [], 0.0
    for (label, _, _), score, desc in zip(parts, scores, descs):
        inc = score - prev
        prev = score
        if inc > 0:
            out.append((f"{label}：{desc}" if desc else label, inc))
    return out


def default_rubric(answer, max_score):
    """默认给分点：先按分问拆大步骤；拆不出再按答案末尾分值细分。"""
    parts = auto_part_rubric(answer, max_score)
    if parts:
        return parts
    derived = auto_rubric_from_answer(answer, max_score)
    if derived:
        return parse_rubric_rules(derived, max_score)["scored"]
    return []


RUBRIC_RULE_WORDS = ("如果", "若", "最多", "至少", "不得", "否则", "只对", "只做",
                     "没有", "未", "零分", "扣", "缺", "漏", "错", "不能", "只能", "注意", "说明",
                     "本题", "参考答案", "满分", "总分", "合计", "共计")


def parse_rubric_rules(text, max_score=None):
    """把「给分点 + 评分说明」拆开，并识别可执行的硬规则。

    返回：
      scored: [(要点, 分值)]       真正参与合计的给分点
      notes: [说明]                普通评分说明
      score_cap: 12.0 / None       本题总分上限（如“最多只能得 12 分”）
      cap_text: str                触发上限的原始说明
      zero_rules: [说明]           “只对……得零分”这类零分规则

    关键：评分说明里的数字不能被当成给分点的分值。
    """
    import re
    scored, notes, zero_rules = [], [], []
    score_cap, cap_text = None, ""
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        # 1) 明确写了分隔符：要点｜2分 / 要点：2 / 要点, 2分
        m = re.match(r"^(.*?)\s*[|｜:：,，]\s*([0-9]+(?:\.[0-9]+)?)\s*分?\s*$", line)
        if m and m.group(1).strip(" |｜:：,，"):
            scored.append((m.group(1).strip(" |｜:：,，"), float(m.group(2))))
            continue
        # 2) 没写分隔符：接受“要点（2分）”，但不能带条件/扣分/汇总说明
        m = re.match(r"^(.{1,80}?)\s*[（(【\[]?\s*(?:得|给)?\s*([0-9]+(?:\.[0-9]+)?)\s*分\s*[)）】\]]?[。；;]?\s*$", line)
        if m and m.group(1).strip():
            point = m.group(1).strip()
            if not any(w in point for w in RUBRIC_RULE_WORDS):
                scored.append((point, float(m.group(2))))
                continue
        # 3) 总分上限：“最多只能得 12 分”“最高 12 分”“不超过 12 分”
        cap = re.search(r"(?:最多|最高|至多|不超过|上限)\D{0,8}?([0-9]+(?:\.[0-9]+)?)\s*分", line)
        if cap:
            val = float(cap.group(1))
            if max_score is None or val <= float(max_score) + 1e-9:
                if score_cap is None or val < score_cap:
                    score_cap = val
                    cap_text = line
                continue
        # 4) 零分规则：“只对……得零分”“若……得 0 分”
        if re.search(r"(零分|0\s*分)", line) and re.search(r"(只|仅|若|如果|没有|未|不能|否则)", line):
            zero_rules.append(line)
            continue
        notes.append(line)
    return {
        "scored": scored,
        "notes": notes,
        "score_cap": score_cap,
        "cap_text": cap_text,
        "zero_rules": zero_rules,
    }


def build_grading_prompt(question_num, max_score, standard_answer, rubric_text, half_point):
    """批改提示词：一次请求，看图直接判分。写得短而明确，模型输出也短，一份几秒出结果。"""
    rules = parse_rubric_rules(rubric_text, max_score)
    scored = rules["scored"]
    if not scored:
        scored = default_rubric(standard_answer, max_score)
    if scored:
        rows = "\n".join(f"{i+1}. {p}（{fmt_score(v)}分）" for i, (p, v) in enumerate(scored))
        rubric_part = f"给分点（按此逐条判，不增不减）：\n{rows}"
    else:
        rubric_part = "给分点：按参考答案中标注的步骤分逐条判；没标分值的，按步骤合理分配，合计等于满分。"
    step = "0.5" if half_point else "1"
    return f"""你是高中数学阅卷老师。图片是学生第{question_num}题的作答，满分{fmt_score(max_score)}分。

参考答案：
{standard_answer}

{rubric_part}

重要：给分点里的中间式只是参考路径，不是必须逐字出现的得分条件。先整体看学生怎么做的；只要方法成立、能推出同一结论，就给该点满分。例如圆外一点作两条切线，直接写 (x₀−a)(x−a)+(y₀−b)(y−b)=r² 求切点弦，是完全正确的方法，不能因为没写“四点共圆、两圆相减”而扣分。

判分要求：
1. 只按图片里看得到的内容判，不替学生补步骤；字迹看不清影响判分时 unclear 填 true。
2. 每个给分点必须严格对照该点文字：写出该点要求的公式、方程或结论才给分；只写相关思路、没算出该点结果，最多给该点一半；该点结论错误不得给满；不因“思路对”给满，不补跳步，最小单位{step}分。
3. 先判断学生实际用了什么方法，再逐点判。方法和参考答案不同但推理和结论正确，照样给满分，alt_method 填 true；不要因为没出现参考答案的中间式、或步骤顺序不同而扣分。求弦所在直线时，用极点极线、代入消元、两点式等都可以。
4. 前一步错导致后面数值错、但后面方法对，后面按写出的步骤给分；只有结果没有过程，最多给该点满分的一半；有过程但跳步，按写出的步骤给分，不补跳步。
5. 不因书写潦草（能看清的）或格式扣分。
6. items 只列最终给分点，禁止输出“第(1)问合计”“小计”“总分”这类汇总行。
7. 所有 full 相加必须正好等于 {fmt_score(max_score)} 分；拆不准就少拆几条，绝不能超过满分。
8. 拿不准是否算完成该点时，按未完成处理；但已经明确写出的正确结论不能被否定。同一处错误只扣一次，不重复扣分。

直接输出 JSON，不要任何别的文字，reason 不超过12字：
{{"items":[{{"point":"给分点","full":分值,"got":得分,"reason":"理由"}}],"score":总分,"confidence":"高/中/低","unclear":false,"alt_method":false,"analysis":"一句话评语"}}"""


def settle_score(result, max_score, half_point, score_cap=None):
    """按给分点加总得到最终分，并返回需要人工复核的原因列表"""
    import math
    import re
    reasons = []
    items = []
    for it in result.get("items") or []:
        if not isinstance(it, dict):
            continue
        try:
            full = float(it.get("full", 0) or 0)
            got = float(it.get("got", 0) or 0)
        except (TypeError, ValueError):
            reasons.append("给分点数据异常")
            continue
        got = max(0.0, min(got, full)) if full > 0 else max(0.0, got)
        items.append({"point": str(it.get("point", "")), "full": full, "got": got, "reason": str(it.get("reason", "") or "")})

    if result.get("blank"):
        return 0, items, reasons

    if items:
        sub_re = re.compile(r"(合计|小计|总分|总计|第\s*[（(]?[一二三1-3][)）]?\s*问\s*合计)")
        subtotals = [i for i in items if sub_re.search(i["point"])]
        sub_ids = {id(i) for i in subtotals}
        details = [i for i in items if id(i) not in sub_ids]
        scoring = items
        if subtotals and abs(sum(i["full"] for i in subtotals) - float(max_score)) <= 0.01:
            scoring = subtotals
            reasons.append("模型给了小计行，已按小计计分")
        elif details and abs(sum(i["full"] for i in details) - float(max_score)) <= 0.01:
            scoring = details
            if subtotals:
                reasons.append("小计行合计≠满分，已忽略小计行")
        elif subtotals:
            scoring = details or items
            reasons.append("小计行合计≠满分，请核对给分点")

        total = sum(i["got"] for i in scoring)
        full_sum = sum(i["full"] for i in scoring)
        if abs(full_sum - max_score) > 0.01:
            reasons.append(f"给分点合计 {fmt_score(full_sum)} 分≠满分")
        try:
            claimed = float(result.get("score"))
            if abs(claimed - total) > 0.01:
                reasons.append(f"模型总分 {fmt_score(claimed)} 与逐点相加 {fmt_score(total)} 不一致")
        except (TypeError, ValueError):
            pass
    else:
        reasons.append("模型没有给出逐点得分")
        try:
            total = float(result.get("score", 0))
        except (TypeError, ValueError):
            total = 0.0

    total = max(0.0, min(total, float(max_score)))
    unit = 0.5 if half_point else 1.0
    total = math.floor(total / unit + 0.5 + 1e-9) * unit   # 四舍五入到最小单位
    if score_cap is not None:
        cap = max(0.0, min(float(score_cap), float(max_score)))
        if total > cap + 1e-9:
            reasons.append(f"按评分说明，本题最多 {fmt_score(cap)} 分（逐点合计 {fmt_score(total)}）")
            total = math.floor(cap / unit + 1e-9) * unit   # 上限向下取整，绝不超上限

    conf = str(result.get("confidence", "")).strip()
    if conf.startswith("低") or conf.lower().startswith("low"):
        reasons.append("模型把握度低")
    if result.get("unclear") is True or "【看不清】" in str(result.get("transcription", "")):
        reasons.append("有看不清的地方")
    if result.get("alt_method") is True:
        reasons.append("学生用了其他解法")
    return fmt_score(total), items, reasons


def choose_consensus(samples):
    """多次判分里选一次采用：3 次取中位数；2 次优先高把握，把握相同取较低分。"""
    if not samples:
        raise ValueError("没有可用的判分结果")

    def conf_rank(sample):
        c = str(sample[1].get("confidence", "")).strip()
        return {"高": 2, "中": 1, "低": 0}.get(c[:1], 1)

    if len(samples) >= 3:
        ordered = sorted(samples, key=lambda x: (float(x[0]), -conf_rank(x)))
        return ordered[len(ordered) // 2]
    if len(samples) == 2:
        r0, r1 = conf_rank(samples[0]), conf_rank(samples[1])
        if r0 != r1:
            return samples[0] if r0 > r1 else samples[1]
        return min(samples, key=lambda x: float(x[0]))
    return samples[0]


def ink_ratio(img):
    """答题区域里“墨迹”像素的占比，用来判断空白卷"""
    try:
        g = img.convert("L")
        g.thumbnail((400, 400))
        hist = g.histogram()
        dark = sum(hist[:140])
        return dark / max(1, sum(hist))
    except Exception:
        return 1.0  # 算不出来就当有内容，交给模型


def color_ratio(img):
    """彩色像素占比：课程表/网页通常很高，白底手写答卷很低。"""
    try:
        im = img.convert('HSV')
        im.thumbnail((240, 240))
        px = list(im.getdata())
        colored = sum(1 for _, s, v in px if s > 70 and v > 60)
        return colored / max(1, len(px))
    except Exception:
        return 0.0


def trim_bottom_taskbar(img, max_ratio=0.18, min_px=24):
    """裁掉答题截图底部的任务栏/浏览器工具栏。

    只裁“又暗又彩”的连续底边：整行平均亮度明显低于卷面，且彩色像素较多。
    学生手写是灰黑墨迹，不会让整行变暗，也不会让整行变彩，所以不会误裁。
    返回 (裁剪后的图, 裁掉的像素高度)。
    """
    try:
        h, w = img.height, img.width
        if h < min_px * 3 or w < 20:
            return img, 0
        limit = max(min_px, int(h * max_ratio))
        small = img.convert("HSV")
        if small.width > 260:
            nh = max(1, int(small.height * 260 / small.width))
            small = small.resize((260, nh))
        sw, sh = small.size
        px = small.load()
        row_v, row_c = [], []
        for yy in range(sh):
            vsum = colored = 0
            for xx in range(sw):
                _, s, v = px[xx, yy]
                vsum += v
                if s > 70 and v > 60:
                    colored += 1
            row_v.append(vsum / sw)
            row_c.append(colored / sw)

        upper = row_v[:max(1, int(sh * 0.7))]
        upper_sorted = sorted(upper)
        med_v = upper_sorted[len(upper_sorted) // 2]
        dark_limit = min(190.0, med_v * 0.85)
        start = max(0, sh - int(sh * max_ratio))
        min_band = max(8, int(sh * 0.03))
        cut_y = None
        for y in range(start, max(start, sh - min_band + 1)):
            n = sh - y
            dark_frac = sum(1 for v in row_v[y:] if v < dark_limit) / n
            color_frac = sum(1 for c in row_c[y:] if c > 0.02) / n
            if dark_frac >= 0.90 and color_frac >= 0.05:
                cut_y = y
                break
        if cut_y is None:
            return img, 0
        keep_h = int(round(cut_y * h / sh))
        cut = h - keep_h
        if cut < min_px or keep_h < min_px:
            return img, 0
        return img.crop((0, 0, w, keep_h)), cut
    except Exception:
        return img, 0



class SimpleGradingUI:
    def __init__(self, root):
        self.root = root
        self.provider_settings = {}   # 各提供商各自的 Key / 模型（没有配置文件时也要有）
        # 线程安全的界面更新队列：后台线程只往队列里放函数，由主线程执行
        import queue
        self._uiq = queue.Queue()
        self._main_thread = threading.current_thread()
        self.root.title(f"阅卷 V{APP_VERSION}")
        
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"380x{min(820, max(620, sh - 90))}+20+10")
        self.root.minsize(340, 620)
        self.root.resizable(True, True)

        
        # 配置文件固定放在程序目录（双击运行或从别的目录启动都能找到）
        import os
        self.config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'zhixue_simple_config.json')

        self.answer_region = None
        self.region_verified = False
        self.grading_count = 0
        self.total_time = 0
        self.is_grading = False
        self.auto_continue = False
        self.is_paused = False  # 暂停状态
        self.score_buttons = {}  # 分数按钮位置 {分数: (x, y)}
        self.next_button_pos = None  # 下一份按钮位置
        self.waiting_for_confirm = False  # 等待用户确认
        self.pending_score = None  # 待确认的分数
        self._record = None
        self.score_input_box = None  # 分数输入框位置
        self.submit_button_pos = None  # 提交按钮位置
        
        # 题目数据（记忆功能）
        self.saved_question_num = ""
        self.saved_max_score = "10"
        self.saved_answer = ""
        self.saved_rubric = ""        # 给分点（每行：要点｜分值）
        self.half_point = False       # 是否允许 0.5 分
        self.blank_threshold = 0.0015 # 墨迹占比低于此值视为空白卷
        self.grade_samples = 0        # 0=自动：Magpie/Custom 取 3 次，其它 1 次
        self.keep_topmost = True      # 是否置顶（批改时可自动临时取消）
        
        self.save_timer = None # 自动保存定时器

        self.load_config()  # 加载配置 (必须在初始化变量之后)
        self.init_model()
        self.root.attributes('-topmost', self.keep_topmost)


        self.create_widgets()  # 创建界面
        self.update_ui_from_config()  # 更新界面显示
        
        self.root.after(50, self._drain_ui_queue)

        # 启动 3 秒后静默检查更新（有新版本才提示）
        if self.config.get('auto_check_update', True):
            self.root.after(3000, lambda: self.check_update_ui(silent=True))

        self.root.bind('<space>', self._on_space)
        self.root.bind('<Escape>', lambda e: self.stop_grading())
        
        # 绑定关闭事件，确保存储
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
    
    def _on_space(self, event):
        # 在输入框里打空格时不触发批改
        if isinstance(event.widget, (tk.Entry, tk.Text)):
            return
        self.grade_answer()
        return "break"

    def on_closing(self):
        """窗口关闭时调用"""
        if getattr(self, '_record', None):
            self._save_record()
        self.save_config()
        self.root.destroy()
    
    # ---------- 界面样式 ----------
    THEME = {
        'bg': '#EEF6FB',        # 窗口底色（淡天蓝）
        'card': '#FFFFFF',
        'line': '#D9E6EF',
        'text': '#1F2D3A',
        'sub': '#5F7385',
        'head': '#1C7ED6',      # 顶栏 / 底栏（亮蓝）
        'head2': '#4DABF7',     # 顶栏按钮
        'head_a': '#1971C2',    # 顶栏按钮按下
        'badge': '#FFD43B',     # 版本标签（明黄）
        'primary': '#FF6B35',   # 批改主按钮（活力橙）
        'primary_d': '#E8551F',
        'cyan': '#15AABF',      # ① 答题区域
        'teal': '#12B886',      # ② 题目（翠绿）
        'teal_d': '#0CA678',
        'teal_bg': '#E6FCF5',
        'orange': '#FF6B35',    # ③ 批改
        'green': '#228BE6',     # ④ 结果（蓝）
        'ok': '#2FB344',
        'ok_bg': '#EBFBEE',
        'warn': '#FD7E14',
        'danger': '#FA5252',
        'slate': '#12B886',     # 暂停按钮（翠绿）
        'tint': '#FFF4E6',      # 分数卡底色（浅橙）
        'input': '#F8FBFD',
    }
    FONT = '微软雅黑'
    GRADE_TEXT = "▶ 开始批改"

    # 统一尺寸：所有小按钮、输入行同高；主按钮同高
    ROW_H = 26      # 普通一行（输入框、小按钮）
    BIG_H = 38      # 批改 / 暂停
    BAR_H = 44      # 顶栏
    SMALL_W = 64    # 小按钮统一宽度

    def _btn(self, parent, text, cmd, bg, fg='white', size=8, bold=False, active=None, **kw):
        return tk.Button(
            parent, text=text, command=cmd, bg=bg, fg=fg,
            activebackground=active or bg, activeforeground=fg,
            font=(self.FONT, size, 'bold' if bold else 'normal'),
            relief=tk.FLAT, bd=0, cursor='hand2', padx=kw.pop('padx', 6), pady=kw.pop('pady', 0), **kw)

    def _slot(self, parent, width=None, height=None, side=tk.LEFT, padx=0, expand=False):
        """固定尺寸的格子：放进去的控件撑满格子，保证同一行控件一样高、一样宽"""
        f = tk.Frame(parent, bg=parent.cget('bg'), width=width or 1, height=height or self.ROW_H)
        f.pack_propagate(False)
        f.pack(side=side, padx=padx, fill=tk.X if expand else None, expand=expand)
        return f

    def _small(self, parent, text, cmd, bg, fg, active, side=tk.RIGHT, padx=0, width=None):
        slot = self._slot(parent, width=width or self.SMALL_W, side=side, padx=padx)
        b = self._btn(slot, text, cmd, bg, fg=fg, active=active)
        b.pack(fill=tk.BOTH, expand=True)
        return b

    def _row(self, parent, gap=6):
        r = tk.Frame(parent, bg=self.THEME['card'], height=self.ROW_H)
        r.pack_propagate(False)
        r.pack(fill=tk.X, pady=(0, gap))
        return r

    def _entry(self, parent, width):
        T = self.THEME
        return tk.Entry(parent, width=width, font=(self.FONT, 9), relief=tk.FLAT, bg=T['input'], fg=T['text'],
                        highlightthickness=1, highlightbackground=T['line'], highlightcolor=T['primary'],
                        insertbackground=T['text'], justify=tk.CENTER)

    def _label(self, parent, text, **kw):
        T = self.THEME
        return tk.Label(parent, text=text, font=(self.FONT, 8), bg=T['card'], fg=kw.pop('fg', T['sub']), **kw)

    def _card(self, parent, title, hint=None, expand=False, color=None):
        """卡片式分组：白底细边框 + 彩色小标题，返回内容区"""
        T = self.THEME
        outer = tk.Frame(parent, bg=T['card'], highlightthickness=1, highlightbackground=T['line'])
        outer.pack(fill=tk.BOTH if expand else tk.X, expand=expand, pady=(0, 8))
        head = tk.Frame(outer, bg=T['card'], height=24)
        head.pack_propagate(False)
        head.pack(fill=tk.X, padx=10, pady=(4, 2))
        tk.Frame(head, bg=color or T['primary'], width=4, height=14).pack(side=tk.LEFT, padx=(0, 6))
        tk.Label(head, text=title, font=(self.FONT, 9, 'bold'), bg=T['card'], fg=color or T['text']).pack(side=tk.LEFT)
        if hint:
            tk.Label(head, text=hint, font=(self.FONT, 7), bg=T['card'], fg=T['sub']).pack(side=tk.RIGHT)
        body = tk.Frame(outer, bg=T['card'])
        body.pack(fill=tk.BOTH, expand=True, padx=10, pady=(2, 10))
        return head, body

    # ---------- 参考答案 / 给分点 编辑窗口 ----------
    def build_answer_editor(self):
        T, F = self.THEME, self.FONT
        win = tk.Toplevel(self.root)
        self.editor = win
        win.withdraw()
        win.title("参考答案与给分点")
        win.configure(bg=T['bg'])
        win.minsize(760, 520)
        win.protocol("WM_DELETE_WINDOW", self.close_answer_editor)
        win.bind('<Escape>', lambda e: self.close_answer_editor())
        win.bind('<Control-s>', lambda e: self.close_answer_editor())

        top = tk.Frame(win, bg=T['teal'], height=46)
        top.pack(fill=tk.X)
        top.pack_propagate(False)
        self.editor_title = tk.Label(top, text="", font=(F, 13, 'bold'), bg=T['teal'], fg='white')
        self.editor_title.pack(side=tk.LEFT, padx=16)
        s = tk.Frame(top, bg=T['teal'], width=120, height=30)
        s.pack_propagate(False)
        s.pack(side=tk.RIGHT, padx=12)
        self._btn(s, "保存并关闭", self.close_answer_editor, 'white', fg=T['teal_d'], active=T['teal_bg'],
                  bold=True).pack(fill=tk.BOTH, expand=True)
        tk.Label(top, text="Ctrl+S 保存 · Esc 关闭 · 改动自动保存", font=(F, 8), bg=T['teal'],
                 fg='#E6FCF5').pack(side=tk.RIGHT, padx=6)

        body = tk.Frame(win, bg=T['bg'], padx=12, pady=12)
        body.pack(fill=tk.BOTH, expand=True)
        body.grid_columnconfigure(0, weight=3, uniform='ed')
        body.grid_columnconfigure(1, weight=2, uniform='ed')
        body.grid_rowconfigure(0, weight=1)

        def panel(col, title, color, hint):
            outer = tk.Frame(body, bg=T['card'], highlightthickness=1, highlightbackground=T['line'])
            outer.grid(row=0, column=col, sticky='nsew', padx=(0, 10) if col == 0 else 0)
            head = tk.Frame(outer, bg=T['card'], height=34)
            head.pack_propagate(False)
            head.pack(fill=tk.X, padx=12, pady=(6, 0))
            tk.Frame(head, bg=color, width=5, height=16).pack(side=tk.LEFT, padx=(0, 8))
            tk.Label(head, text=title, font=(F, 11, 'bold'), bg=T['card'], fg=color).pack(side=tk.LEFT)
            tk.Label(head, text=hint, font=(F, 8), bg=T['card'], fg=T['sub']).pack(side=tk.LEFT, padx=(8, 0))
            inner = tk.Frame(outer, bg=T['card'])
            inner.pack(fill=tk.BOTH, expand=True, padx=12, pady=(4, 12))
            return head, inner

        def text_box(parent):
            t = scrolledtext.ScrolledText(parent, font=(F, 12), wrap=tk.WORD, relief=tk.FLAT, bg=T['input'],
                                          fg=T['text'], highlightthickness=1, highlightbackground=T['line'],
                                          highlightcolor=T['teal'], insertbackground=T['text'], padx=8, pady=6,
                                          undo=True)
            t.pack(fill=tk.BOTH, expand=True)
            return t

        def head_btn(head, text, cmd, solid):
            slot = tk.Frame(head, bg=T['card'], width=72, height=26)
            slot.pack_propagate(False)
            slot.pack(side=tk.RIGHT, padx=(6, 0))
            if solid:
                b = self._btn(slot, text, cmd, T['teal'], active=T['teal_d'])
            else:
                b = self._btn(slot, text, cmd, T['teal_bg'], fg=T['teal_d'], active='#C3FAE8')
            b.pack(fill=tk.BOTH, expand=True)

        head, inner = panel(0, "参考答案", T['teal'], "含评分标准，可截图识别")
        head_btn(head, "清空", lambda: (self.answer_text.delete('1.0', tk.END), self._editor_changed()), False)
        head_btn(head, "截图识别", self.capture_standard_answer, True)
        self.answer_text = text_box(inner)

        head, inner = panel(1, "给分点", T['orange'], "每行：要点｜分值")
        head_btn(head, "清空", lambda: (self.rubric_text.delete('1.0', tk.END), self._editor_changed()), False)
        head_btn(head, "从答案提取", self.extract_rubric_from_answer, True)
        self.rubric_text = text_box(inner)
        self.rubric_status = tk.Label(inner, text="", font=(F, 10, 'bold'), bg=T['card'], anchor='w', pady=6)
        self.rubric_status.pack(fill=tk.X)
        tk.Label(inner, text="不填也行：AI 会先从参考答案里拆出给分点。\n例：求出斜率 k=2｜2分", font=(F, 8),
                 bg=T['card'], fg=T['sub'], justify=tk.LEFT, anchor='w').pack(fill=tk.X)

        for w in (self.answer_text, self.rubric_text):
            w.bind('<KeyRelease>', lambda e: self._editor_changed())
            w.bind('<FocusOut>', lambda e: self._editor_changed())

    def _editor_changed(self):
        self.save_question_data()
        self.refresh_answer_summary()

    def open_answer_editor(self):
        win = self.editor
        self.refresh_answer_summary()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        w, h = min(1100, int(sw * 0.75)), min(760, int(sh * 0.8))
        if not getattr(self, '_editor_placed', False):
            win.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 2 - 30)}")
            self._editor_placed = True
        win.deiconify()
        win.attributes('-topmost', True)
        win.lift()
        win.focus_force()
        self.answer_text.focus_set()

    def close_answer_editor(self):
        self.save_config()
        self.refresh_answer_summary()
        self.editor.withdraw()

    def extract_rubric_from_answer(self):
        """从参考答案里把「……（2分）」这类写了分值的行提取成给分点"""
        import re
        found = []
        try:
            mx_val = float(self.max_score_entry.get().strip())
        except ValueError:
            mx_val = None
        for line in self.answer_text.get('1.0', tk.END).splitlines():
            line = line.strip()
            m = re.search(r"^(.*?)[\s，,。；;]*[（(【\[]?\s*(?:得|给)?\s*([0-9]+(?:\.[0-9]+)?)\s*分\s*[)）】\]]?[。；;]?$", line)
            if m and m.group(1).strip():
                point = m.group(1).strip().rstrip(" .…·")
                if re.fullmatch(r"[（(]?[0-9一二三四五六七八九十]+[)）]?[.、．]?\s*(解[:：]?)?", point):
                    continue   # 题号行，如「16.（15分）」，不是给分点
                try:
                    if mx_val and float(m.group(2)) >= mx_val:
                        continue  # 和满分一样大，多半是整题总分
                except ValueError:
                    pass
                if len(point) > 40:
                    point = point[:40] + "…"
                found.append(f"{point}｜{m.group(2)}")
        if not found:
            messagebox.showinfo("从答案提取", "参考答案里没找到写了分值的行（如「……（2分）」）。\n可以手动填，或者不填让 AI 自己拆。", parent=self.editor)
            return
        if self.rubric_text.get('1.0', tk.END).strip():
            if not messagebox.askyesno("从答案提取", f"找到 {len(found)} 条，要替换现有的给分点吗？", parent=self.editor):
                return
        self.rubric_text.delete('1.0', tk.END)
        self.rubric_text.insert('1.0', "\n".join(found))
        self._editor_changed()

    def refresh_answer_summary(self):
        if not hasattr(self, 'answer_summary'):
            return
        T = self.THEME
        ans = self.answer_text.get('1.0', tk.END).strip()
        try:
            mx = float(self.max_score_entry.get().strip() or 0)
        except ValueError:
            mx = 0
        rules = parse_rubric_rules(self.rubric_text.get('1.0', tk.END), mx)
        scored = rules["scored"]
        source = "manual"
        if not scored and mx:
            scored = default_rubric(ans, mx)
            if scored:
                source = "auto"
        total = sum(v for _, v in scored)
        line1 = f"参考答案 {len(ans)} 字" if ans else "参考答案：未填写"
        if scored:
            ok = abs(total - mx) < 0.01
            line2 = f"给分点 {len(scored)} 条 {fmt_score(total)} 分" + (" ✓" if ok else f" ≠ 满分{fmt_score(mx)}")
            if source == "auto":
                line2 += "（从答案自动拆）"
        else:
            ok = True
            line2 = "给分点：未填，由 AI 拆分"
        if rules["score_cap"] is not None:
            line2 += f" · 上限{fmt_score(rules['score_cap'])}分"
        if rules["zero_rules"]:
            line2 += f" · 零分规则{len(rules['zero_rules'])}条"
        if rules["notes"]:
            line2 += f" · 说明{len(rules['notes'])}条"
        self.answer_summary.config(text=line1 + "\n" + line2, fg=T['text'] if (ans and ok) else T['danger'])
        if hasattr(self, 'editor_title'):
            q = self.question_num_entry.get().strip() or "?"
            self.editor_title.config(text=f"第 {q} 题 · 满分 {fmt_score(mx) if mx else '?'} 分")
        if hasattr(self, 'rubric_status'):
            if scored:
                status_text = f"合计 {fmt_score(total)} / {fmt_score(mx)} 分  " + ("✓ 与满分一致" if ok else "✗ 与满分不一致")
                if source == "auto":
                    status_text += "（从答案自动拆）"
                if rules["score_cap"] is not None:
                    status_text += f" · 总分上限 {fmt_score(rules['score_cap'])} 分"
                self.rubric_status.config(text=status_text,
                                          fg=T['ok'] if ok else T['danger'])
            else:
                self.rubric_status.config(text="", fg=T['sub'])


    def create_widgets(self):
        """创建界面（紧凑卡片式，统一行高）"""
        T, F = self.THEME, self.FONT
        self.root.configure(bg=T['bg'])

        # ===== 顶栏：标题 + 版本 + 工具按钮（三个按钮同宽同高）=====
        bar = tk.Frame(self.root, bg=T['head'], height=self.BAR_H)
        bar.pack(fill=tk.X)
        bar.pack_propagate(False)
        tk.Label(bar, text="阅卷", font=(F, 14, 'bold'), bg=T['head'], fg='white').pack(side=tk.LEFT, padx=(12, 6))
        tk.Label(bar, text=f"V{APP_VERSION}", font=('Consolas', 7, 'bold'), bg=T['badge'], fg=T['text'],
                 padx=5, pady=1).pack(side=tk.LEFT)

        tools = tk.Frame(bar, bg=T['head'], height=self.ROW_H)
        tools.pack(side=tk.RIGHT, padx=10)
        self.topmost_btn = self._small(tools, "置顶", self.toggle_topmost,
                                       T['head2'], 'white', T['head_a'], width=42)
        self.update_btn = self._small(tools, "更新", lambda: self.check_update_ui(silent=False),
                                      T['head2'], 'white', T['head_a'], width=42)
        self._small(tools, "笔记", self.setup_obsidian_path, T['head2'], 'white', T['head_a'], padx=4, width=42)
        self._small(tools, "模型", self.setup_model, T['head2'], 'white', T['head_a'], width=42)

        # ===== 底部状态栏 =====
        status = tk.Frame(self.root, bg=T['head'], height=22)
        status.pack_propagate(False)
        status.pack(fill=tk.X, side=tk.BOTTOM)
        self.stats_label = tk.Label(status, text="已批 0 · 用时 0s · 均 0s · 0/h", font=(F, 8),
                                    fg='white', bg=T['head'])
        self.stats_label.pack(expand=True)

        main_frame = tk.Frame(self.root, bg=T['bg'], padx=10, pady=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # ===== ① 答题区域 =====
        _, body = self._card(main_frame, "① 答题区域", color=T['cyan'])
        r = self._row(body, gap=0)
        self._small(r, "框选", self.setup_region, T['cyan'], 'white', '#0097B2')
        self._small(r, "预览", self.preview_region, T['cyan'], 'white', '#0097B2', padx=(0, 6))
        slot = self._slot(r, side=tk.LEFT, padx=(0, 6), expand=True)
        self.region_preview = tk.Label(slot, text="未框选", bg='#E6F9FD', fg=T['sub'], font=(F, 8), anchor='w', padx=8)
        self.region_preview.pack(fill=tk.BOTH, expand=True)

        # ===== ② 题目（参考答案、给分点在大窗口里编辑）=====
        _, body = self._card(main_frame, "② 题目", hint="自动保存", color=T['teal'])
        r = self._row(body)
        self._label(r, "题号").pack(side=tk.LEFT)
        s = self._slot(r, width=52, padx=(4, 10))
        self.question_num_entry = self._entry(s, 6)
        self.question_num_entry.pack(fill=tk.BOTH, expand=True)
        self._label(r, "满分").pack(side=tk.LEFT)
        s = self._slot(r, width=44, padx=(4, 0))
        self.max_score_entry = self._entry(s, 4)
        self.max_score_entry.pack(fill=tk.BOTH, expand=True)
        self.half_var = tk.BooleanVar(value=False)
        tk.Checkbutton(r, text="半分", variable=self.half_var, command=self.save_config, font=(F, 8),
                       bg=T['card'], fg=T['text'], activebackground=T['card'], selectcolor=T['teal_bg'],
                       bd=0, highlightthickness=0).pack(side=tk.RIGHT)

        # 摘要 + 打开编辑窗口
        sm = tk.Frame(body, bg=T['teal_bg'], highlightthickness=1, highlightbackground='#C3FAE8')
        sm.pack(fill=tk.X)
        btn_slot = self._slot(sm, width=self.SMALL_W + 8, height=44, side=tk.RIGHT, padx=6)
        self._btn(btn_slot, "编辑\n答案", self.open_answer_editor, T['teal'], active=T['teal_d'],
                  bold=True).pack(fill=tk.BOTH, expand=True, pady=6)
        self.answer_summary = tk.Label(sm, text="", font=(F, 8), bg=T['teal_bg'], fg=T['text'],
                                       anchor='w', justify=tk.LEFT, padx=8, pady=6)
        self.answer_summary.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.answer_summary.bind('<Button-1>', lambda e: self.open_answer_editor())

        # 参考答案 / 给分点 的大编辑窗口（启动时建好、先隐藏）
        self.build_answer_editor()

        for w in (self.question_num_entry, self.max_score_entry):
            w.bind('<FocusOut>', lambda e: self.save_question_data())
            w.bind('<KeyRelease>', lambda e: (self.save_question_data(), self.refresh_answer_summary()))

        # ===== ③ 批改控制 =====
        _, body = self._card(main_frame, "③ 批改", hint="空格 开始 · Esc 停止 · 目标<20秒", color=T['orange'])
        big = tk.Frame(body, bg=T['card'], height=self.BIG_H)
        big.pack_propagate(False)
        big.pack(fill=tk.X, pady=(0, 8))
        s = self._slot(big, width=84, height=self.BIG_H, side=tk.RIGHT)
        self.pause_btn = self._btn(s, "⏸ 暂停", self.toggle_pause, T['slate'], size=10, bold=True,
                                   state=tk.DISABLED, disabledforeground='#C3FAE8')
        self.pause_btn.pack(fill=tk.BOTH, expand=True)
        s = self._slot(big, height=self.BIG_H, side=tk.LEFT, padx=(0, 6), expand=True)
        self.grade_btn = self._btn(s, self.GRADE_TEXT, self.grade_answer, T['primary'], size=10, bold=True,
                                   active=T['primary_d'])
        self.grade_btn.pack(fill=tk.BOTH, expand=True)

        r = self._row(body)
        for i in range(3):
            r.grid_columnconfigure(i, weight=1, uniform='ck')
        r.grid_rowconfigure(0, weight=1)
        ck = dict(font=(F, 8), bg=T['card'], fg=T['text'], activebackground=T['card'],
                  selectcolor='#FFF3EC', bd=0, highlightthickness=0, anchor='w')
        self.auto_var = tk.BooleanVar(value=False)
        tk.Checkbutton(r, text="连续", variable=self.auto_var, command=self.on_checkbox_changed, **ck).grid(row=0, column=0, sticky='w')
        self.auto_click_var = tk.BooleanVar(value=False)
        tk.Checkbutton(r, text="自动填分", variable=self.auto_click_var, command=self.save_config, **ck).grid(row=0, column=1, sticky='w')
        self.skip_confirm_var = tk.BooleanVar(value=False)
        tk.Checkbutton(r, text="跳过确认", variable=self.skip_confirm_var, command=self.save_config,
                       **dict(ck, fg=T['warn'])).grid(row=0, column=2, sticky='w')

        r = self._row(body, gap=0)
        self._label(r, "间隔").pack(side=tk.LEFT)
        s = self._slot(r, width=36, padx=(6, 4))
        self.delay_entry = self._entry(s, 3)
        self.delay_entry.insert(0, "3")
        self.delay_entry.pack(fill=tk.BOTH, expand=True)
        self.delay_entry.bind('<FocusOut>', lambda e: self.save_config())
        self._label(r, "秒").pack(side=tk.LEFT)
        self._small(r, "测试", self.test_auto_click, '#FFF0E8', T['orange'], '#FFE0D0', width=48)
        self._small(r, "定位", self.setup_score_buttons, '#FFF0E8', T['orange'], '#FFE0D0', padx=(0, 6), width=48)
        self.setup_status_label = tk.Label(r, text="● 未定位", font=(F, 8), bg=T['card'], fg=T['danger'])
        self.setup_status_label.pack(side=tk.RIGHT, padx=(0, 8))

        # ===== ④ 结果 =====
        _, body = self._card(main_frame, "④ 结果", expand=True, color=T['green'])
        self.current_result_frame = tk.Frame(body, bg=T['tint'])
        self.current_result_frame.pack(fill=tk.X, pady=(0, 8))
        self.current_score_label = tk.Label(self.current_result_frame, text="建议分数  --", font=(F, 12, 'bold'),
                                            bg=T['tint'], fg=T['primary'])
        self.current_score_label.pack(pady=(4, 0))
        self.current_analysis_label = tk.Label(self.current_result_frame, text="", font=(F, 8), bg=T['tint'],
                                               fg=T['sub'], wraplength=330, justify=tk.LEFT)
        self.current_analysis_label.pack(pady=(2, 6), padx=8)
        self.capture_thumb = tk.Label(self.current_result_frame, text="截图预览", font=(F, 7),
                                      bg=T['tint'], fg=T['sub'], cursor='hand2')
        self.capture_thumb.pack(pady=(0, 6))
        self.capture_thumb.bind('<Button-1>', lambda e: self.preview_region())

        self.result_text = scrolledtext.ScrolledText(body, height=10, font=(F, 9), wrap=tk.WORD, relief=tk.FLAT,
                                                     bg=T['input'], fg=T['sub'], highlightthickness=1,
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
        if self.saved_rubric:
            self.rubric_text.delete('1.0', tk.END)
            self.rubric_text.insert('1.0', self.saved_rubric)
        self.half_var.set(self.half_point)
        self.refresh_answer_summary()
            
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
        if hasattr(self, 'topmost_btn'):
            self.topmost_btn.config(
                text="置顶" if self.keep_topmost else "不置顶",
                bg=self.THEME['head2'] if self.keep_topmost else self.THEME['head_a'])
        
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
            self.region_verified = False
            self.save_config()
            self.update_region_preview()
            self.root.deiconify()
            self.log(f"✓ 答案区域已设置: {region[2]}x{region[3]}")
            self.preview_region()
        
        selector = ScreenshotSelector(on_region_selected)
        selector.start()
    
    def capture_standard_answer(self):
        """截图参考答案并识别文字（追加到参考答案末尾）"""
        editor_open = self.editor.winfo_viewable()
        self.editor.withdraw()
        self.root.iconify()
        time.sleep(0.3)

        def on_captured(region):
            x, y, w, h = region
            img = pyautogui.screenshot(region=(x, y, w, h))
            self.root.deiconify()
            self.open_answer_editor() if editor_open else None
            self.log("正在识别参考答案...")

            def worker():
                try:
                    prompt = ("请把图片中的参考答案和评分标准原样转写成文字。数学式用常见写法或 LaTeX，"
                              "保留每一步后面标注的分值（如“（2分）”），不要添加任何说明。")
                    text = self.call_ai_api(prompt, img, need_json=False).strip()

                    def fill():
                        cur = self.answer_text.get('1.0', tk.END).strip()
                        if cur:
                            self.answer_text.insert(tk.END, "\n" + text)
                        else:
                            self.answer_text.insert('1.0', text)
                        self._editor_changed()
                        self.log("✓ 参考答案已识别" + ("并追加" if cur else "并填入"))
                    self.ui(fill)
                except Exception as e:
                    err = str(e)
                    self.log(f"⚠ 识别失败: {err}")
                    self.ui(lambda: messagebox.showerror("错误", f"识别失败：{err}"))
            threading.Thread(target=worker, daemon=True).start()

        selector = ScreenshotSelector(on_captured)
        selector.start()

    def update_region_preview(self):
        """更新区域预览"""
        if self.answer_region:
            x, y, w, h = self.answer_region
            if self.region_verified:
                self.region_preview.config(text=f"✓ 已预览  {w}×{h}", fg=self.THEME['ok'], bg=self.THEME['ok_bg'])
            else:
                self.region_preview.config(text=f"⚠ 已框选 {w}×{h} · 点「预览」检查",
                                           fg=self.THEME['warn'], bg='#FFF4E6')

    def toggle_topmost(self):
        """置顶开关：开启后批改、提交、连续批改都保持在其他窗口上方。"""
        self.keep_topmost = not self.keep_topmost
        self.root.attributes('-topmost', self.keep_topmost)
        self.topmost_btn.config(
            text="置顶" if self.keep_topmost else "不置顶",
            bg=self.THEME['head2'] if self.keep_topmost else self.THEME['head_a'])
        self.save_config()

    def preview_region(self):
        """预览当前框选的答题区域，防止截到课程表或黑屏。"""
        if not self.answer_region:
            messagebox.showwarning("预览", "请先点「框选」设置答题区域")
            return
        x, y, w, h = self.answer_region
        pad = 6
        sw, sh = pyautogui.size()
        self.root.withdraw()
        self.root.update()
        time.sleep(0.35)
        try:
            img = pyautogui.screenshot(region=(
                max(0, x - pad), max(0, y - pad),
                min(sw, x + w + pad) - max(0, x - pad),
                min(sh, y + h + pad) - max(0, y - pad)))
        finally:
            self.root.deiconify()
        self.region_verified = True
        self.update_region_preview()

        win = tk.Toplevel(self.root)
        win.title("答题区域预览")
        win.configure(bg=self.THEME['bg'])
        win.attributes('-topmost', True)
        win.geometry("760x640")

        show = img.copy()
        show.thumbnail((720, 520))
        self._preview_img = ImageTk.PhotoImage(show)
        tk.Label(win, image=self._preview_img, bg=self.THEME['bg']).pack(padx=12, pady=(12, 6))
        color = color_ratio(img)
        warn = color > 0.25
        tk.Label(win, text=(f"区域 {w}×{h} · 墨迹 {ink_ratio(img):.3f} · 彩色 {color:.0%}"
                            + ("　⚠ 这看起来像课程表/网页，不是答卷！" if warn else "")
                            + "\n如果这里看到课程表、黑屏或被遮挡，请重新框选"),
                 font=(self.FONT, 9), bg=self.THEME['bg'],
                 fg=self.THEME['danger'] if warn else self.THEME['sub']).pack(pady=(0, 8))

        row = tk.Frame(win, bg=self.THEME['bg'])
        row.pack(pady=(0, 12))
        tk.Button(row, text="重新框选", command=lambda: (win.destroy(), self.setup_region()),
                  bg=self.THEME['cyan'], fg='white', relief=tk.FLAT, padx=18, pady=6).pack(side=tk.LEFT, padx=8)
        tk.Button(row, text="关闭", command=win.destroy,
                  bg=self.THEME['line'], fg=self.THEME['text'], relief=tk.FLAT, padx=24, pady=6).pack(side=tk.LEFT, padx=8)
    
    def grade_answer(self):
        """批改答案"""
        self._raise_window()
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
        
        # 给分点合计和满分对不上：先提醒（只在手动点开始时问，连续批改时不打断）
        try:
            mx = float(self.max_score_entry.get().strip())
        except ValueError:
            mx = None
        rules = parse_rubric_rules(self.rubric_text.get('1.0', tk.END), mx)
        scored = rules["scored"]
        if not scored and mx:
            scored = default_rubric(answer_text, mx)
        if scored and not self.auto_continue and mx is not None:
            total = sum(v for _, v in scored)
            if abs(total - mx) > 0.01:
                if messagebox.askyesno("给分点和满分对不上",
                                       f"给分点合计 {fmt_score(total)} 分，满分是 {fmt_score(mx)} 分。\n\n"
                                       "点「是」打开编辑窗口修改；点「否」照样批改（每份都会要求人工确认）。"):
                    self.open_answer_editor()
                    return

        # 编辑窗口开着会挡住答卷，截图前先收起来
        if self.editor.winfo_viewable():
            self.close_answer_editor()
            self.root.update()
            time.sleep(0.15)

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
            max_score_f = float(self.max_score_entry.get().strip() or "10")
            max_score = int(max_score_f) if max_score_f == int(max_score_f) else max_score_f
            standard_answer = self.answer_text.get('1.0', tk.END).strip()
            
            self.root.after(0, lambda: self.log(f"\n[{datetime.now().strftime('%H:%M:%S')}] 批改题号{question_num}..."))
            
            # 截取学生答案
            x, y, w, h = self.answer_region
            if w < 40 or h < 40:
                raise Exception(f"答题区域太小（{w}×{h}），请重新框选")
            # 四周多留 6 像素，避免切掉最后一行或边上的字
            sw, sh = pyautogui.size()
            pad = 6
            x0, y0 = max(0, x - pad), max(0, y - pad)
            x1, y1 = min(sw, x + w + pad), min(sh, y + h + pad)
            student_img = pyautogui.screenshot(region=(x0, y0, x1 - x0, y1 - y0))
            # 防重复：页面没翻到下一份时截图会和上一张一样，自动模式下直接停，避免同一份卷子重复提交
            import hashlib
            img_hash = hashlib.md5(student_img.tobytes()).hexdigest()
            if self.auto_continue and img_hash == getattr(self, 'last_img_hash', None):
                self.auto_continue = False
                raise Exception("答案区域和上一份完全相同（可能没翻页或已批完），已停止自动连续批改")
            self.last_img_hash = img_hash
            self.current_student_img = student_img # 保存引用以供导出
            grade_img, trimmed = trim_bottom_taskbar(student_img)
            if trimmed:
                self.log(f"  ✂ 已裁掉底部任务栏 {trimmed}px，避免干扰识图")

            ink = ink_ratio(grade_img)
            color = color_ratio(grade_img)
            if ink > 0.97:
                raise Exception(f"截图几乎全黑（墨迹占比 {ink:.2f}），可能答题区域被遮挡或没翻页")
            if color > 0.25:
                raise Exception(f"截图看起来是彩色页面（彩色像素 {color:.0%}），不是学生答卷；请点「预览」重新框选")
            extra_reasons = []
            if color > 0.10:
                extra_reasons.append(f"截图彩色像素较多（{color:.0%}），请确认不是课程表/网页")

            # 空白卷直接 0 分，不浪费 API 额度
            if ink < self.blank_threshold:
                result = {
                    "score": 0, "items": [], "blank": True, "confidence": "高",
                    "unclear": False, "alt_method": False,
                    "analysis": f"答题区域几乎是空白（墨迹占比 {ink:.4f}），按 0 分。",
                }
                score, items, reasons = settle_score(result, max_score_f, self.half_point)
                self.log(f"  ⚪ 空白卷，直接记 0 分（墨迹 {ink:.4f}）")
            else:
                rubric = self.rubric_text.get('1.0', tk.END).strip()
                rules = parse_rubric_rules(rubric, max_score_f)
                if rules["scored"]:
                    self.log(f"  📋 给分点 {len(rules['scored'])} 条，合计 "
                             f"{fmt_score(sum(v for _, v in rules['scored']))} 分")
                else:
                    derived_scored = default_rubric(standard_answer, max_score_f)
                    if derived_scored:
                        vals = [v for _, v in derived_scored]
                        self.log(f"  📋 已从参考答案自动拆出给分点：{' + '.join(str(fmt_score(v)) for v in vals)}")
                if rules["score_cap"] is not None:
                    self.log(f"  📏 评分规则：本题最多 {fmt_score(rules['score_cap'])} 分（程序强制）"
                             f"（{rules['cap_text'][:50]}）")
                if rules["zero_rules"]:
                    self.log(f"  📏 零分规则 {len(rules['zero_rules'])} 条（请人工复核对应步骤）")
                prompt = build_grading_prompt(question_num, max_score, standard_answer, rubric,
                                              self.half_point)
                # 多次取样：单次判分波动大，固定取 3 次，按中位数采用，避免取最高分导致偏松
                provider = str(self.config.get('provider', '')).lower()
                default_samples = 3 if provider in ('magpie', 'custom') else 1
                max_samples = int(getattr(self, 'grade_samples', 0) or default_samples)
                max_samples = max(1, min(3, max_samples))
                samples = []
                target = max_samples
                deadline = start_time + 18
                while len(samples) < target:
                    if samples and time.time() > deadline - 4:
                        break
                    try:
                        r = self.call_ai_api(prompt, grade_img, need_json=True)
                    except Exception as e:
                        if samples:
                            self.log(f"  ⚠ 第 {len(samples) + 1} 次判分失败：{str(e)[:80]}，使用已有结果")
                            break
                        raise
                    s, its, rs = settle_score(r, max_score_f, self.half_point, rules["score_cap"])
                    r['score'] = s
                    r['items'] = its
                    samples.append((s, r, its, rs))
                    self.log(f"  🧪 第 {len(samples)} 次判分：{fmt_score(s)} 分")
                if not samples:
                    raise Exception("模型没有返回可用分数")
                totals = [x[0] for x in samples]
                chosen = choose_consensus(samples)
                score, result, items, reasons = chosen
                if len(samples) > 1:
                    method = "中位数" if len(samples) >= 3 else "把握度优先/较低分"
                    self.log(f"  🧪 多次判分：{'/'.join(str(fmt_score(t)) for t in totals)}"
                             f" → 采用{method} {fmt_score(score)} 分")
                    if max(totals) - min(totals) >= 2:
                        reasons.append(f"多次判分差异较大（{'/'.join(str(fmt_score(t)) for t in totals)}），"
                                       f"取中位数 {fmt_score(score)}，请复核")
                if ink > 0.90:
                    reasons.append(f"截图墨迹占比很高（{ink:.2f}），请确认不是黑屏/遮挡")
                result['score'] = score
                result['items'] = items

            result['_reasons'] = (reasons or []) + extra_reasons
            result['_ink'] = round(ink, 4)
            result['_color'] = round(color, 3)

            elapsed = time.time() - start_time
            self.grading_count += 1
            self.total_time += elapsed

            model_name = getattr(self, '_last_model_used', None) or self.config.get('model_name', 'Unknown')
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
        """显示结果：逐给分点得分 + 需复核原因"""
        try:
            score = float(result.get('score', 0))
        except (TypeError, ValueError):
            score = 0
        score = fmt_score(max(0, min(score, float(max_score))))   # 不超过满分、不低于 0
        result['score'] = score
        analysis = result.get('analysis', '')
        items = result.get('items') or []
        reasons = result.get('_reasons') or []
        deductions = result.get('deduction_details', []) or []

        self.current_score_label.config(text=f"建议分数  {score} / {max_score}")

        detail_text = f"评语: {analysis}\n"
        if items:
            detail_text += "\n给分点:\n"
            for it in items:
                got, full = it.get('got', 0), it.get('full', 0)
                reason = str(it.get('reason', '') or '').strip()
                detail_text += f"  • {it.get('point', '')}  {fmt_score(got)}/{fmt_score(full)}"
                if reason:
                    detail_text += f"  {reason}"
                detail_text += "\n"
        elif deductions:
            detail_text += "\n扣分详情:\n"
            for d in deductions:
                if isinstance(d, dict):
                    detail_text += f"  • {d.get('point', '未命名扣分点')}: -{d.get('deduction', 0)}分\n"
        if reasons:
            detail_text += "\n⚠ 需人工复核:\n" + "\n".join(f"  • {r}" for r in reasons)

        self.current_analysis_label.config(text=f"评语: {analysis}")
        self.log(detail_text)
        try:
            thumb = self.current_student_img.copy()
            thumb.thumbnail((110, 66))
            self._thumb_img = ImageTk.PhotoImage(thumb)
            self.capture_thumb.config(image=self._thumb_img, text="")
        except Exception:
            pass

        self.log(f"  得分: {score}/{max_score} 用时: {elapsed:.1f}s ({model_name})")
        self.log(f"\n💡 建议分数: {score} 分")

        self.update_stats()
        avg_time = self.total_time / self.grading_count if self.grading_count > 0 else 0
        self._record = (result, max_score, model_name, elapsed, avg_time)

        self.waiting_for_confirm = True
        self.pending_score = score
        self._raise_window()
        self.show_confirm_dialog(score, max_score, detail_text, force=bool(reasons))

    def _save_record(self):
        """在用户确认/改分后保存记录，保证 HTML/笔记里的分数是最终提交分。"""
        rec = getattr(self, '_record', None)
        if not rec:
            return
        self._record = None
        result, max_score, model_name, elapsed, avg_time = rec
        try:
            if hasattr(self, 'obsidian_path') and self.obsidian_path:
                self.save_to_obsidian(result, max_score, self.current_student_img, model_name, elapsed, avg_time)
            self.save_to_html(result, max_score, self.current_student_img, model_name, elapsed, avg_time)
        except Exception as e:
            self.log(f"⚠ 保存记录失败: {e}")

    def init_model(self):
        """REST 直连，不再依赖已停止维护的 google.generativeai SDK。"""
        self.model = None

    def call_ai_api(self, prompt, image, need_json=True):
        """调用当前提供商；额度/限流时自动回退到本机 Magpie。"""
        try:
            return self._call_ai_api_once(prompt, image, need_json)
        except Exception as e:
            m = str(e).lower()
            if 'timed out' in m or 'timeout' in m or '超过' in m:
                raise Exception(f"单题超过 {GRADE_TIMEOUT} 秒，已中止（请换更快的模型或检查网络）") from e
            if self.config.get('provider') == 'Magpie':
                gs = (self.provider_settings or {}).get('Gemini', {})
                if gs.get('api_key'):
                    self.log(f"  ↪ Magpie 不可用（{str(e).splitlines()[0][:60]}）；改用 Gemini…")
                    return self._call_provider_with_settings('Gemini', gs, prompt, image, need_json)
                raise
            if not self._should_fallback(e):
                raise
            self.log(f"  ↪ {str(e).splitlines()[0][:80]}；自动改用本机 Magpie…")
            try:
                return self._call_magpie_fallback(prompt, image, need_json)
            except Exception as e2:
                raise Exception(f"{e}\n\n本机 Magpie 回退也失败：{e2}") from e2

    def _call_provider_with_settings(self, provider, settings, prompt, image, need_json):
        """临时切换到另一个提供商调用，结束后恢复原配置。"""
        old = dict(self.config)
        try:
            self.config.update(
                provider=provider,
                api_key=settings.get('api_key', ''),
                base_url=settings.get('base_url', '') or PROVIDERS.get(provider, {}).get('base_url', ''),
                model_name=settings.get('model_name', '')
                or (PROVIDERS.get(provider, {}).get('models') or [''])[0],
            )
            return self._call_ai_api_once(prompt, image, need_json)
        finally:
            self.config = old

    @staticmethod
    def _should_fallback(err):
        m = str(err).lower()
        return any(k in m for k in (
            "quota", "429", "exceeded", "rate limit", "resource_exhausted",
            "额度", "key 池全部不可用", "no available key", "unavailable",
        ))

    def _call_magpie_fallback(self, prompt, image, need_json):
        base, ver = magpie_detect()
        if not base:
            raise Exception("本机 Magpie 未运行（127.0.0.1:3425）。请打开 magpie，或在「模型」里换一个可用提供商")
        key = PROVIDERS['Magpie']['default_key']
        models = fetch_models(base, key)
        model = choose_magpie_model(models)
        if not model:
            raise Exception("Magpie 没有可用模型")
        self.log(f"  ↪ 本机 Magpie：{model}")
        self._last_model_used = f"Magpie/{model}"
        return self._openai_vision_call(base, key, model, prompt, image, need_json)

    def _openai_vision_call(self, base_url, api_key, model, prompt, image, need_json):
        """OpenAI 兼容的识图调用：灰度压缩 + 流式 + 自动关思考。"""
        if not base_url or not model:
            raise Exception("API 地址或模型名为空")
        data_url = image_to_data_url(image, max_side=1600)
        data = {
            "model": model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]}],
            "max_tokens": 4096,
            "temperature": 0.1,
        }
        data.update(no_think_params(model, base_url))
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        url = f"{base_url.rstrip('/')}/chat/completions"
        text = post_chat_stream(url, data, headers, log=self.log, timeout=GRADE_TIMEOUT)
        return self.parse_json_result(text) if need_json else text
        
    def _call_ai_api_once(self, prompt, image, need_json=True):
        """单次调用当前提供商（内部方法）。"""
        provider = self.config.get('provider', 'Gemini')
        api_key = self.config.get('api_key', '')
        base_url = self.config.get('base_url', '')
        model_name = self.config.get('model_name', '')
        
        if not api_key and provider != 'Custom': # Custom might not need key
             # 尝试使用默认key
             if provider == 'Gemini' and not api_key:
                 api_key = DEFAULT_CONFIG['api_key']
        
        if provider == 'Gemini':
            # 2026-11-11 v2：key 池轮换 + 熔断。keys.json 里有池就用池；没有则回退单 key + 重试
            import urllib.request
            import json as _json
            img_io = io.BytesIO()
            im = image.convert("RGB")
            im.thumbnail((1600, 1600))
            im.save(img_io, format="JPEG", quality=88)
            img_b64 = base64.b64encode(img_io.getvalue()).decode()
            gen_cfg = {"temperature": 0.1,
                       "responseMimeType": "application/json" if need_json else "text/plain"}
            if 'gemini-2.5' in (model_name or '') and 'pro' not in (model_name or ''):
                gen_cfg["thinkingConfig"] = {"thinkingBudget": 0}
            body = _json.dumps({
                "contents": [{"parts": [
                    {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}},
                    {"text": prompt}]}],
                "generationConfig": gen_cfg,
            }).encode("utf-8")

            alive, kp = keys_status()
            if kp is not None and not alive:
                # 池存在但全冷却：等最近恢复的那个 key（最多90秒），这比回退到已耗尽的旧单key强
                wait = min(kp.get("cooldown", {}).values()) - time.time()
                if 0 < wait <= 90:
                    self.log(f"  [key池] 全部冷却中，等待最近恢复 {wait:.0f}s…")
                    time.sleep(wait + 1)
                    alive, kp = keys_status()
            if not kp or not alive:
                # 无池或池全部冷却：先用配置里的单 key 试一次；429 立即交给外层回退 Magpie
                if not api_key:
                    raise QuotaError("Gemini 未填 API Key，且 keys.json 无可用 key")
                last_err = None
                for attempt in range(3):
                    try:
                        text, usage = gemini_request_raw(api_key, model_name, body, GRADE_TIMEOUT)
                        self._last_model_used = f"Gemini/{model_name or 'gemini-2.5-flash'}"
                        return self.parse_json_result(text) if need_json else text
                    except urllib.error.HTTPError as e:
                        error_body = e.read().decode("utf-8", "ignore")
                        last_err = f"Gemini API Error {e.code}: {error_body[:200]}"
                        if e.code == 429:
                            raise QuotaError(last_err)
                        if e.code in (500, 503):
                            time.sleep(2 * (attempt + 1)); continue
                        raise Exception(last_err)
                    except Exception as e:
                        last_err = f"Gemini Call Failed: {str(e)[:200]}"
                        time.sleep(2 * (attempt + 1))
                raise QuotaError(last_err or "Gemini 调用失败")

            # —— 有池：轮换 + 熔断，不 sleep 干等 ——
            tried = 0; last_err = None
            while alive and tried < len(alive) + 2:
                k = alive[tried % len(alive)]
                tried += 1
                try:
                    text, usage = gemini_request_raw(k, model_name, body, GRADE_TIMEOUT)
                    self._last_model_used = f"Gemini/{model_name or 'gemini-2.5-flash'}"
                    self.log(f"  [key池] 本次使用 #{(kp.get('pool',[]).index(k)+1) if k in kp.get('pool',[]) else '?'} 号key")
                    return self.parse_json_result(text) if need_json else text
                except urllib.error.HTTPError as e:
                    error_body = e.read().decode("utf-8", "ignore")
                    if e.code == 429:
                        # 区分分钟限流(RPM,冷却65s)和日限流(RPD,冷却到明早)：按 retryDelay 精确冷却
                        import re as _re
                        mm = _re.search(r'"retryDelay":\s*"(\d+)s"', error_body)
                        delay = int(mm.group(1)) if mm else 65
                        if delay > 3600:   # 日额度用尽，冷却到明天重置（约8小时后），不再无谓重试
                            keys_cooldown(kp, k, min(delay + 60, 8 * 3600))
                            self.log(f"  [key池] #{kp.get('pool',[]).index(k)+1} 日额度用尽，冷却到明早")
                        else:
                            keys_cooldown(kp, k, delay + 5)
                        alive, kp = keys_status()
                        last_err = GEMINI_429_HINT
                        continue
                    elif e.code in (401, 403, 404):
                        # key 失效：拉黑（写入 banned，本次运行不再用）
                        kp.setdefault("banned", []).append(k)
                        kp["pool"] = [x for x in kp.get("pool", []) if x != k]
                        try:
                            json.dump(kp, open(KEYS_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                        except Exception:
                            pass
                        alive, kp = keys_status()
                        last_err = f"key 失效({e.code})已拉黑: {k[:10]}***"
                        continue
                    else:
                        last_err = f"Gemini API Error {e.code}: {error_body[:200]}"
                        time.sleep(1.5)
                        continue
                except Exception as e:
                    last_err = f"Gemini Call Failed: {str(e)[:200]}"
                    time.sleep(1.5)
                    continue
            raise QuotaError(f"Gemini key 池全部不可用。{last_err or GEMINI_429_HINT}")

        if True:
            # 智能检测：如果模型不支持 Vision (如 DeepSeek-V3/Chat)，且在 SiliconFlow，则使用 Qwen-VL "借眼"
            is_text_model = any(k in model_name for k in ['DeepSeek-V3', 'DeepSeek-V2', 'chat', 'coder'])
            is_siliconflow = 'silicon' in base_url and provider not in ('Magpie', 'Gemini')
            
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
            if not base_url:
                raise Exception(f"{provider} 未设置 API 地址")
            self._last_model_used = f"{provider}/{model_name}"
            return self._openai_vision_call(base_url, api_key, model_name, prompt, image, need_json)

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
        dialog.geometry("340x660")
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
        initial_url = (initial_settings.get('base_url') or self.config.get('base_url', '')
                       or PROVIDERS.get(current_provider, {}).get('base_url', ''))
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

        info_lbl = tk.Label(frame, text="", font=('微软雅黑', 8), fg='#5F7385', justify=tk.LEFT, wraplength=290, anchor='w')
        info_lbl.pack(fill=tk.X, pady=(0, 2))
        link_lbl = tk.Label(frame, text="", font=('微软雅黑', 8, 'underline'), fg='#1C7ED6', cursor='hand2', anchor='w')
        link_lbl.pack(fill=tk.X, pady=(0, 10))

        def show_info(p):
            info = PROVIDERS.get(p, {})
            info_lbl.config(text=info.get('note', ''))
            link_lbl.config(text="→ 去申请 Key" if info.get('key_url') else "")
        def open_key_page(_e=None):
            u = PROVIDERS.get(provider_combo.get(), {}).get('key_url')
            if u:
                import webbrowser
                webbrowser.open(u)
        link_lbl.bind('<Button-1>', open_key_page)
        show_info(current_provider)
        
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
            if p == 'Magpie':
                preferred = choose_magpie_model(models)
                if preferred and (not model_combo.get() or model_combo.get() == 'group/group'):
                    model_combo.set(preferred)
            elif models and model_combo.get() not in models:
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
            new_url = settings.get('base_url') or default_url   # 没改过就用预设地址
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
            show_info(new_p)

            # Magpie / Custom 自动拉取模型
            if new_p in ('Magpie', 'Custom'):
                dialog.after(50, refresh_models)
                
        provider_combo.bind("<<ComboboxSelected>>", on_provider_change)
        
        # 说明
        tk.Label(frame, text="说明：选提供商后地址自动填好，只需填 Key\n模型可从下拉选，也可点“获取模型”\n切换时会自动暂存各家的 Key", 
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
        
        tk.Button(frame, text="保存配置", command=save, bg=self.THEME['head'], fg='white', activebackground=self.THEME['head_a'], activeforeground='white', relief=tk.FLAT, bd=0, cursor='hand2', width=15, pady=3).pack(pady=5)
    
    def setup_score_buttons(self):
        """设置自动提交位置"""
        msg = "即将设置自动提交位置\n\n"
        msg += "需要设置2个位置：\n"
        msg += "1. 分数输入框\n"
        msg += "2. 提交分数按钮\n\n"
        msg += "主窗口会先隐藏，屏幕顶部会出现倒计时小条。\n每个位置 5 秒。"
        
        if not messagebox.askokcancel("设置自动提交", msg):
            return
        
        self.log("\n开始设置自动提交位置...")

        self.root.withdraw()
        tip = tk.Toplevel(self.root)
        tip.overrideredirect(True)
        tip.attributes('-topmost', True)
        tip.configure(bg=self.THEME['head'])
        sw, sh = pyautogui.size()
        tip.geometry(f"460x92+{max(0, sw // 2 - 230)}+40")
        label = tk.Label(tip, text="", font=(self.FONT, 11, 'bold'), bg=self.THEME['head'], fg='white')
        label.pack(fill=tk.BOTH, expand=True)

        def countdown(text, seconds=5):
            for i in range(seconds, 0, -1):
                label.config(text=f"{text}\n{i} 秒后记录鼠标位置")
                self.root.update()
                time.sleep(1)

        countdown("把鼠标移到【分数输入框】")
        self.score_input_box = tuple(pyautogui.position())
        self.log(f"✓ 分数输入框位置: {self.score_input_box}")

        countdown("把鼠标移到【提交分数按钮】")
        self.submit_button_pos = tuple(pyautogui.position())
        self.log(f"✓ 提交按钮位置: {self.submit_button_pos}")
        tip.destroy()
        self.root.deiconify()

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
        msg += "注意：测试会真的输入并提交 10 分，请拿一份测试卷/空白卷试。\n"
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
            self.grade_btn.config(text="▶ 连续批改")
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
            self._save_record()
            self._raise_window()
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
        dialog.geometry("520x560")
        dialog.transient(self.root)
        dialog.attributes('-topmost', True)
        dialog.grab_set()
        
        # 居中显示
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")
        
        # 内容框架
        content_frame = tk.Frame(dialog, padx=20, pady=20)
        content_frame.pack(fill=tk.BOTH, expand=True)
        
        if force:
            tk.Label(content_frame, text="⚠ 有需要人工复核的地方，请确认或直接改分",
                     font=('微软雅黑', 9, 'bold'), fg='#c92a2a').pack(pady=(0, 8))

        # 分数可编辑：AI 给错时直接在这里改，不用拒绝后手输
        score_row = tk.Frame(content_frame)
        score_row.pack(pady=(0, 12))
        tk.Label(score_row, text="分数", font=('微软雅黑', 12)).pack(side=tk.LEFT, padx=(0, 8))
        score_var = tk.StringVar(value=str(score))
        score_entry = tk.Entry(score_row, textvariable=score_var, width=6, justify=tk.CENTER,
                               font=('微软雅黑', 16, 'bold'), fg='#ff6b00',
                               relief=tk.FLAT, highlightthickness=1, highlightcolor='#ff6b00')
        score_entry.pack(side=tk.LEFT, ipady=3)
        tk.Label(score_row, text=f"/ {max_score} 分", font=('微软雅黑', 11)).pack(side=tk.LEFT, padx=(6, 0))

        # 详情显示
        detail_frame = tk.Frame(content_frame, relief=tk.SUNKEN, bd=1)
        detail_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        detail_scroll = scrolledtext.ScrolledText(
            detail_frame,
            height=12,
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
            try:
                final_score = float(score_var.get().strip())
            except ValueError:
                messagebox.showwarning("分数格式", "请输入数字，例如 12 或 10.5", parent=dialog)
                return
            final_score = fmt_score(max(0, min(final_score, float(max_score))))
            if final_score != score:
                self.log(f"✏ 人工改分: {score} → {final_score}")
            self.pending_score = final_score
            if self._record:
                self._record[0]['score'] = final_score
            self._save_record()
            dialog.destroy()
            self._raise_window()
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
            self._save_record()
            dialog.destroy()
            self._raise_window()
            self.log(f"\n❌ 用户拒绝分数: {self.pending_score}")
            self.log("请手动在平台输入正确分数")
            self.waiting_for_confirm = False
            self.pending_score = None
            self.is_grading = False
            self.grade_btn.config(state=tk.NORMAL, text=self.GRADE_TEXT)

        dialog.protocol("WM_DELETE_WINDOW", on_reject)
        
        # 接受按钮
        accept_btn = tk.Button(
            btn_frame,
            text="✓ 提交 (Enter)",
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
            text="✗ 跳过 (Esc)",
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
        
        # 聚焦分数输入框，方便直接改分；回车提交
        score_entry.focus_set()
        score_entry.select_range(0, tk.END)
    
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

            # 全程保持置顶，提交后主动抬回最前面
            self.ui(self._raise_window)
            
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
            
            # 3. 输入分数：优先剪贴板粘贴，避免中文输入法/小数点问题
            self.log(f"→ 输入分数 {score}...")
            score_str = str(score)
            try:
                clip_ready = threading.Event()

                def _set_clipboard():
                    try:
                        self.root.clipboard_clear()
                        self.root.clipboard_append(score_str)
                        self.root.update()
                    finally:
                        clip_ready.set()

                self.ui(_set_clipboard)
                if not clip_ready.wait(2):
                    raise TimeoutError("设置剪贴板超时")
                pyautogui.hotkey('ctrl', 'v')
                self.log("✓ 使用粘贴输入")
            except Exception:
                self.log("→ 粘贴失败，改用键盘输入")
                pyautogui.typewrite(score_str, interval=0.1)
            
            time.sleep(0.3)
            self.log(f"✓ 已输入分数: {score}")
            
            # 4. 点击提交按钮（只点一次，避免重复提交）
            self.log(f"→ 点击提交按钮...")
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
                self.ui(self._raise_window)
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
        self._raise_window()
        self.auto_var.set(False)
        self.pause_btn.config(state=tk.DISABLED, text="⏸ 暂停", bg=self.THEME['slate'])
        self.grade_btn.config(state=tk.NORMAL, text=self.GRADE_TEXT)
        self.log("\n⏹ 批改已停止")
    
    def update_stats(self):
        """更新统计"""
        avg = self.total_time / self.grading_count if self.grading_count > 0 else 0
        eff = int(3600 / avg) if avg > 0 else 0
        self.stats_label.config(text=f"已批 {self.grading_count} · 用时 {self.total_time:.0f}s · 均 {avg:.1f}s · {eff}/h")
    
    def _raise_window(self):
        """保持置顶，并在批改/提交后把窗口抬回最前面。"""
        try:
            if self.keep_topmost:
                self.root.attributes('-topmost', True)
            self.root.lift()
        except Exception:
            pass

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
            if hasattr(self, 'rubric_text'):
                self.saved_rubric = self.rubric_text.get('1.0', tk.END).strip()
            if hasattr(self, 'half_var'):
                self.half_point = bool(self.half_var.get())

            config = {
                'answer_region': self.answer_region,
                'score_input_box': list(self.score_input_box) if self.score_input_box else None,
                'submit_button_pos': list(self.submit_button_pos) if self.submit_button_pos else None,
                'question_num': self.saved_question_num,
                'max_score': self.saved_max_score,
                'answer': self.saved_answer,
                'rubric': self.saved_rubric,
                'half_point': self.half_point,
                'blank_threshold': self.blank_threshold,
                'grade_samples': getattr(self, 'grade_samples', 0),
                'keep_topmost': self.keep_topmost,
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
                self.saved_rubric = config.get('rubric', '')
                self.half_point = bool(config.get('half_point', False))
                self.blank_threshold = float(config.get('blank_threshold', 0.0015))
                self.grade_samples = int(config.get('grade_samples', 0) or 0)
                self.keep_topmost = bool(config.get('keep_topmost', True))
                
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
                        "api_key": "",
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
            items = result.get('items') or []
            
            content = f"\n\n## 📝 题号 {question_num} ({datetime.now().strftime('%H:%M')})\n"
            content += f"- **模型**: {model_name}\n"
            content += f"- **耗时**: {elapsed:.2f}s (Avg: {avg_time:.1f}s)\n"
            content += f"- **得分**: {score}/{max_score}\n"
            content += f"- **评语**: {analysis}\n"
            
            if items:
                content += "- **给分点**:\n"
                for it in items:
                    reason = str(it.get('reason', '') or '')
                    content += f"    - {it.get('point', '')}: {fmt_score(it.get('got', 0))}/{fmt_score(it.get('full', 0))} {reason}\n"
            elif deductions:
                content += "- **扣分详情**:\n"
                for d in deductions:
                    content += f"    - {d['point']}: -{d['deduction']}\n"

            reasons = result.get('_reasons') or []
            if reasons:
                content += "- **需人工复核**: " + "；".join(str(r) for r in reasons) + "\n"
            
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
            
            from html import escape
            question_num = escape(self.question_num_entry.get().strip())
            score = result.get('score', 0)
            analysis = escape(str(result.get('analysis', '')))
            deductions = result.get('deduction_details', []) # 修正变量名
            items = result.get('items') or []
            reasons = result.get('_reasons') or []
            time_str = datetime.now().strftime('%H:%M:%S')
            
            # 构造单个卡片 HTML
            card_html = f"""
            <div class="card">
                <div class="header">
                    <span class="title">题号: {question_num}</span>
                    <span class="model-tag">{escape(str(model_name))}</span>
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
            
            if items:
                card_html += "<ul class='items'>"
                for it in items:
                    reason = escape(str(it.get('reason', '') or ''))
                    card_html += (f"<li>{escape(str(it.get('point', '')))}："
                                  f"<b>{fmt_score(it.get('got', 0))}/{fmt_score(it.get('full', 0))}</b>"
                                  f"{('　' + reason) if reason else ''}</li>")
                card_html += "</ul>"
            elif deductions:
                card_html += "<ul>"
                for d in deductions:
                    card_html += f"<li>{d['point']}: <span class='deduction'>-{d['deduction']}</span></li>"
                card_html += "</ul>"
            if reasons:
                card_html += "<div class='review'>⚠ 需人工复核：" + escape("；".join(str(r) for r in reasons)) + "</div>"
            
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
        .items li {{ margin: 4px 0; }}
        .review {{ background: #fff5f5; color: #c92a2a; border: 1px solid #ffc9c9; padding: 8px 12px; border-radius: 6px; margin-top: 10px; }}
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
