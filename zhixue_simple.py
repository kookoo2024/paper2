"""
知学网阅卷助手 - 简化版（大题批改）
一次只批改一道题，适合主观题详细批改
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, simpledialog
import pyautogui
from PIL import Image, ImageTk
import json
import copy
import os
import time
from datetime import datetime
import threading


import base64
import urllib.request
import urllib.error
import io

HTTP_TIMEOUT = 120  # 兜底超时（秒）；批改调用会传更短的 15 秒目标
GRADE_TIMEOUT = 15  # 单题批改硬上限：超过就中止，保证整体 <20 秒

GRADING_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "transcription": {"type": "STRING"},
        "symbol_map": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "student": {"type": "STRING"},
                    "standard": {"type": "STRING"},
                    "definition": {"type": "STRING"},
                },
                "required": ["student", "standard", "definition"],
            },
        },
        "parts": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "part_id": {"type": "STRING"},
                    "method_id": {"type": "STRING"},
                    "part_type": {"type": "STRING", "enum": ["proof", "calculation"]},
                    "complete_proof": {"type": "BOOLEAN"},
                    "proof_evidence": {"type": "STRING"},
                    "points": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "point_id": {"type": "STRING"},
                                "full": {"type": "NUMBER"},
                                "got": {"type": "NUMBER"},
                                "evidence": {"type": "STRING"},
                                "reason": {"type": "STRING"},
                                "equivalent": {"type": "BOOLEAN"},
                                "role": {"type": "STRING", "enum": ["process", "conclusion", "result"]},
                                "checks": {
                                    "type": "ARRAY",
                                    "items": {
                                        "type": "OBJECT",
                                        "properties": {
                                            "requirement": {"type": "STRING"},
                                            "shown": {"type": "BOOLEAN"},
                                            "evidence": {"type": "STRING"},
                                            "equivalent": {"type": "BOOLEAN"},
                                        },
                                        "required": ["requirement", "shown", "evidence", "equivalent"],
                                    },
                                },
                            },
                            "required": ["point_id", "full", "got", "evidence", "reason"],
                        },
                    },
                },
                "required": ["part_id", "method_id", "points"],
            },
        },
        "items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "point": {"type": "STRING"},
                    "full": {"type": "NUMBER"},
                    "got": {"type": "NUMBER"},
                    "evidence": {"type": "STRING"},
                    "reason": {"type": "STRING"},
                },
                "required": ["point", "full", "got", "evidence", "reason"],
            },
        },
        "score": {"type": "NUMBER"},
        "confidence": {"type": "STRING"},
        "unclear": {"type": "BOOLEAN"},
        "alt_method": {"type": "BOOLEAN"},
        "analysis": {"type": "STRING"},
    },
    "required": ["transcription", "score", "confidence", "unclear", "analysis"],
}

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
APP_VERSION = "1.10.1"
CARD_VERSION = 3
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


def image_to_data_url(image, max_side=2400):
    """答题截图转灰度 JPEG：小图适当放大，大图压缩，兼顾手写细节与上传速度。"""
    img = image.convert('L')
    w, h = img.size
    long_side = max(w, h)
    if long_side > max_side:
        k = max_side / long_side
        img = img.resize((max(1, int(w * k)), max(1, int(h * k))), Image.Resampling.LANCZOS)
    elif long_side < 1800:
        k = min(max_side / long_side, 2.5)
        if k > 1.05:
            img = img.resize((max(1, int(w * k)), max(1, int(h * k))), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=90)
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
    if not max_score:
        candidates = []
        for line in (answer or "").splitlines():
            if "扣" in line:
                continue
            match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*分\s*[)）】\]]?\s*$",
                              line.strip())
            if match:
                candidates.append(float(match.group(1)))
        if candidates:
            max_score = max(candidates)
    block_rules = parse_trailing_score_blocks(answer, max_score)
    if block_rules:
        deductions = {}
        for rule in block_rules.get("deduction_rules") or []:
            deductions.setdefault(int(rule.get("point_index", -1)), []).append(
                str(rule.get("text") or "").strip())
        rows = []
        for index, (point, value) in enumerate(block_rules["scored"]):
            rows.append(f"{point}｜{fmt_score(value)}")
            rows.extend(text for text in deductions.get(index, []) if text)
        return "\n".join(rows)

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


def is_cumulative_scale(values, max_score):
    """判断一组分值是不是「累计到该步的总分」，而不是「每一步的增量」。

    典型写法：1分、3分、4分、5分 … 17分（满分 17）。
    条件：严格递增、最后一项等于满分、直接求和明显超过满分。
    """
    try:
        vals = [float(v) for v in values]
        mx = float(max_score)
    except (TypeError, ValueError):
        return False
    if len(vals) < 3 or mx <= 0:
        return False
    if any(v <= 0 for v in vals):
        return False
    if abs(vals[-1] - mx) > 0.01:
        return False
    if any(b <= a + 1e-9 for a, b in zip(vals, vals[1:])):
        return False
    return abs(sum(vals) - mx) > 0.01


def cumulative_to_incremental(values):
    """把累计分值 [1,3,4,…] 换算成每步增量 [1,2,1,…]。"""
    prev = 0.0
    out = []
    for v in values:
        v = float(v)
        out.append(round(v - prev, 2))
        prev = v
    return out


def _clean_score_block(lines):
    """把一条评分标准的完整段落整理成一行，去掉题号/小问标题等外壳。"""
    import re
    text = " ".join(str(x).strip() for x in (lines or []) if str(x).strip())
    text = re.sub(
        r"^\s*(?:[0-9]{1,3}\s*[.、．]\s*)?【答案】\s*",
        "", text)
    text = re.sub(
        r"^\s*[（(]\s*(?:[0-9]+|[ivxlcdmIVXLCDM]+)\s*[）)]\s*"
        r"(?:【[^】]+】|解\s*[：:]?)\s*",
        "", text)
    text = re.sub(
        r"^\s*[（(]\s*(?:i{1,3}|iv|v|vi{0,3}|ix|x)\s*[）)]\s*",
        "", text, flags=re.I)
    text = re.sub(r"^\s*【[^】]+】\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.strip(" .…·")


def parse_trailing_score_blocks(text, max_score=None):
    """按句末的「(N分)」切完整评分段落，而不是只取分值所在那一行。

    标准里常见这种写法：
        ∵ PC²=PD²+CD²，∴ PD⊥CD。
        ∵ 平面PDC⊥平面ABCD，∴ PD⊥平面ABCD。
        又 AD,CD⊂平面ABCD，∴ PD⊥AD，PD⊥CD。 ......（5分）
    这整段都属于 5 分点，不能只剩最后一行。

    返回 None 表示这段文本不适合按“句末累计分”解析，交给原来的逐行解析。
    """
    import re
    lines = str(text or "").splitlines()
    blocks = []
    buffer = []
    deduction_rules = []
    zero_rules = []
    notes = []
    score_cap, cap_text = None, ""
    marker_re = re.compile(
        r"^(.*?)[\s…·.．]*[（(【\[]?\s*(?:得|给)?\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*分\s*[)）】\]]?[。；;]?\s*$")
    deduction_re = re.compile(r"扣\s*([0-9]+(?:\.[0-9]+)?)\s*分")
    rule_word_re = re.compile(
        r"(满分|总分|合计|共计|评分标准|评分要点|评分细则|参考答案|参考解答)")

    for raw in lines:
        line = str(raw or "").strip()
        if not line:
            continue
        if line.startswith("#"):
            if re.search(r"(参考解答|参考答案|解析|解法)", line):
                notes.append(line.lstrip("#").strip())
            continue

        cap = re.search(
            r"(?:最多|最高|至多|不超过|上限)\D{0,8}?"
            r"([0-9]+(?:\.[0-9]+)?)\s*分", line)
        if cap:
            value = float(cap.group(1))
            if max_score is None or value <= float(max_score) + 1e-9:
                if score_cap is None or value < score_cap:
                    score_cap, cap_text = value, line
            continue

        if re.search(r"(零分|0\s*分)", line) and re.search(
                r"(只|仅|若|如果|没有|未|不能|否则)", line):
            zero_rules.append(line)
            continue

        match = marker_re.match(line)
        is_header = bool(rule_word_re.search(line))
        if match and not is_header:
            deduction = deduction_re.search(line)
            is_deduction = bool(
                deduction and re.search(r"(如果|若|注意|说明|否则)", line))
            if is_deduction:
                deduction_rules.append({
                    "amount": float(deduction.group(1)),
                    "point_index": max(0, len(blocks) - 1),
                    "text": line,
                })
                continue

            point_text = match.group(1).strip()
            value = float(match.group(2))
            if point_text and not re.fullmatch(
                    r"[（(]?[0-9一二三四五六七八九十]+[)）]?[.、．]?\s*(解[:：]?)?",
                    point_text):
                buffer.append(point_text)
                cleaned = _clean_score_block(buffer)
                if cleaned:
                    blocks.append({"text": cleaned, "score": value})
                buffer = []
                continue
            # 只有「（10分）」这类标题行，不当作采分点。
            continue

        deduction = deduction_re.search(line)
        if deduction and re.search(r"(如果|若|注意|说明|否则)", line):
            deduction_rules.append({
                "amount": float(deduction.group(1)),
                "point_index": max(0, len(blocks) - 1),
                "text": line,
            })
            continue

        buffer.append(line)

    if buffer:
        notes.extend(buffer)
    if len(blocks) < 2:
        return None

    values = [float(block["score"]) for block in blocks]
    cumulative = False
    if max_score is not None:
        mx = float(max_score)
        if is_cumulative_scale(values, mx):
            increments = cumulative_to_incremental(values)
            cumulative = True
        elif abs(sum(values) - mx) <= 0.01:
            increments = values
        else:
            return None
    else:
        # 没有满分时无法可靠判断累计分，交给逐行解析。
        return None

    scored = [(block["text"], increment)
              for block, increment in zip(blocks, increments)]
    return {
        "scored": scored,
        "notes": notes,
        "score_cap": score_cap,
        "cap_text": cap_text,
        "zero_rules": zero_rules,
        "deduction_rules": deduction_rules,
        "cumulative": cumulative,
        "cumulative_raw": values if cumulative else [],
    }


def parse_rubric_rules(text, max_score=None):
    """把「给分点 + 评分说明」拆开，并识别可执行的硬规则。

    返回：
      scored: [(要点, 分值)]       真正参与合计的给分点
      notes: [说明]                普通评分说明
      score_cap: 12.0 / None       本题总分上限（如“最多只能得 12 分”）
      cap_text: str                触发上限的原始说明
      zero_rules: [说明]           “只对……得零分”这类零分规则
      deduction_rules: [dict]      “扣N分”及它所属的给分点序号

    关键：评分说明里的数字不能被当成给分点的分值。
    """
    import re
    block_rules = parse_trailing_score_blocks(text, max_score)
    if block_rules:
        return block_rules
    scored, notes, zero_rules, deduction_rules = [], [], [], []
    score_cap, cap_text = None, ""
    in_solution = False
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        # 0) 结构化标题不参与给分点（### （1）证明…（4分）这类是分块小计）
        if line.startswith("#"):
            if re.search(r"(给分点|评分标准|评分要点|评分细则)", line):
                in_solution = False
            elif re.search(r"(参考解答|参考答案|解析|解法)", line):
                in_solution = True
            continue
        # 0.1) 前缀式：1分：…… / - 3分：…… / 1分. ……
        m = re.match(r"^[-*•·]?\s*[（(【\[]?\s*([0-9]+(?:\.[0-9]+)?)\s*分\s*[)）】\]]?\s*[：:、.．\-—]\s*(.+)$", line)
        if in_solution and not m:
            notes.append(line)
            continue
        m_ded = re.search(r"扣\s*([0-9]+(?:\.[0-9]+)?)\s*分", line)
        if m_ded and scored:
            deduction_rules.append({
                "amount": float(m_ded.group(1)),
                "point_index": len(scored) - 1,
                "text": line,
            })
        if m and m.group(2).strip():
            in_solution = False
            scored.append((m.group(2).strip(" |｜:：,，"), float(m.group(1))))
            continue
        # 1) 明确写了分隔符：要点｜2分 / 要点：2 / 要点, 2分
        m = re.match(r"^(.*?)\s*[|｜:：,，]\s*([0-9]+(?:\.[0-9]+)?)\s*分?\s*$", line)
        if m and m.group(1).strip(" |｜:：,，"):
            scored.append((m.group(1).strip(" |｜:：,，"), float(m.group(2))))
            continue
        # 2) 没写分隔符：接受“要点……（2分）”。评分标准常用 LaTeX，
        # 一条要点可能很长，不能按普通短行截断。
        m = re.match(r"^(.+?)\s*[（(【\[]?\s*(?:得|给)?\s*([0-9]+(?:\.[0-9]+)?)\s*分\s*[)）】\]]?[。；;]?\s*$", line)
        if m and m.group(1).strip():
            point = m.group(1).strip()
            point = re.sub(r"[\s.…·]+$", "", point)
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
    cumulative = False
    raw_values = [v for _, v in scored]
    if max_score and is_cumulative_scale(raw_values, max_score):
        incs = cumulative_to_incremental(raw_values)
        scored = [(p, v) for (p, _), v in zip(scored, incs)]
        cumulative = True
    return {
        "scored": scored,
        "notes": notes,
        "score_cap": score_cap,
        "cap_text": cap_text,
        "zero_rules": zero_rules,
        "deduction_rules": deduction_rules,
        "cumulative": cumulative,
        "cumulative_raw": raw_values if cumulative else [],
    }


def resolve_rubric_points(rubric_text, standard_answer, max_score):
    """确定最终给分点：手填的 > 参考答案里写的评分标准 > 自动拆。

    返回 (points, source, rules)；source 为 rubric / answer / auto。
    """
    rules = parse_rubric_rules(rubric_text, max_score)
    answer_rules = parse_rubric_rules(standard_answer, max_score)

    def total_ok(points):
        if not points:
            return False
        if not max_score:
            return True
        return abs(sum(float(v) for _, v in points) - float(max_score)) <= 0.01

    if total_ok(rules["scored"]):
        return rules["scored"], "rubric", rules
    if total_ok(answer_rules["scored"]):
        if rules["scored"]:
            answer_rules["notes"] = list(answer_rules["notes"]) + [
                n for n in rules["notes"] if n not in answer_rules["notes"]
            ]
        return answer_rules["scored"], "answer", answer_rules
    if rules["scored"]:
        return rules["scored"], "rubric", rules
    return default_rubric(standard_answer, max_score), "auto", rules


def extract_deduction_values(rules):
    """提取评分标准里明确写出的扣分数额，只有这些部分分才允许保留。"""
    import re
    explicit = list((rules or {}).get("deduction_rules") or [])
    if explicit:
        return {round(float(r.get("amount", 0)), 2) for r in explicit}
    text = "\n".join(
        list((rules or {}).get("notes") or [])
        + list((rules or {}).get("zero_rules") or [])
        + [str((rules or {}).get("cap_text") or "")]
    )
    values = set()
    for m in re.finditer(r"扣\s*([0-9]+(?:\.[0-9]+)?)\s*分", text):
        values.add(round(float(m.group(1)), 2))
    return values


def deduction_allowed(item_index, deduction, rules):
    """只有扣分条款明确属于该给分点时，才允许保留部分分。"""
    explicit = (rules or {}).get("deduction_rules") if isinstance(rules, dict) else rules
    if not explicit:
        return False
    if isinstance(explicit, (set, list, tuple)) and all(
            not isinstance(x, dict) for x in explicit):
        return round(float(deduction), 2) in {round(float(x), 2) for x in explicit}
    for rule in explicit:
        if not isinstance(rule, dict):
            continue
        if rule.get("point_index") != item_index:
            continue
        if abs(float(rule.get("amount", 0)) - float(deduction)) <= 0.01:
            return True
    return False


def extract_equivalents(text):
    """从「（或 xxx、yyy）」里提取等价写法。"""
    import re
    m = re.search(r"[（(]\s*或\s*([^）)]+)[）)]", text or "")
    if not m:
        return []
    return [s.strip() for s in re.split(r"[、;；,，]", m.group(1)) if s.strip()]


def _new_card_point(text, full, point_id="", deductions=None):
    """评分卡 v2 的最小采分点：数学目标 + 必需要素 + 等价写法 + 明确扣分。"""
    text = str(text or "").strip()
    return {
        "id": str(point_id or ""),
        "text": text,
        "goal": text,
        "full": float(full or 0),
        "required": [text] if text else [],
        "equivalents": extract_equivalents(text),
        "notes": "",
        "aliases": {},
        "deductions": [float(x) for x in (deductions or [])],
        "zero_if": [],
        "shared": False,
        "result_only": False,
        "band": False,
        "levels": [],
    }


def _new_band_point(steps, full, point_id="", deductions=None):
    """把一个累计分制小问压成一个整问分档点。

    老师给出的标准常写成 1、3、4、5……分，这些是累计分，不是让模型逐句
    对齐的 11 个小点。整问只保留一个评分单元，并列出原标准允许的档位。
    """
    cumulative = 0.0
    levels = []
    source_steps = []
    for text, value in steps:
        value = float(value or 0)
        if value <= 0:
            continue
        text = str(text or "").strip()
        cumulative = round(cumulative + value, 2)
        levels.append({"score": cumulative, "text": text})
        source_steps.append({"score": value, "text": text})
    if not levels:
        return None
    point = _new_card_point("", float(full or cumulative), point_id, deductions)
    allowed = format_score_levels(levels)
    point.update({
        "text": f"整问按原标准分档（允许 {allowed} 分）",
        "goal": "按原标准判断学生完整达到的最高档位，不拆成逐句小点",
        "required": [],
        "equivalents": [],
        "band": True,
        "levels": levels,
        "steps": source_steps,
    })
    return point


def format_score_levels(levels):
    """把分档分数格式化成固定字符串，避免 join 收到整数。"""
    return "/".join(
        str(fmt_score(level.get("score", 0) or 0))
        for level in (levels or [])
        if isinstance(level, dict)
    ) or "无"


def format_band_card_summary(card):
    """返回“第1问（1/3/4）、第2问（…）”这样的分档摘要。"""
    summaries = []
    for part in (card or {}).get("parts") or []:
        methods = part.get("methods") or [{}]
        points = (methods[0] or {}).get("points") or [{}]
        levels = (points[0] or {}).get("levels") or []
        summaries.append(
            f"第{part.get('id')}问（{format_score_levels(levels)}）")
    return "、".join(summaries) or "无"


def norm_alias_object(obj):
    """统一“PD 的中点”“PD中点”“棱PD的中点”这类对象描述。"""
    s = str(obj or "").upper().replace(" ", "").replace("　", "")
    for word in ("的", "棱", "边", "线段", "直线"):
        s = s.replace(word, "")
    return s


def extract_aliases(text):
    """从“取PD中点H”“H为PD的中点”这类定义句提取学生自己的字母。"""
    import re
    s = str(text or "")
    # 参考答案常用 \(PD\) 这类 LaTeX 定界符，先去壳再识别几何对象。
    s = s.replace("\\(", "").replace("\\)", "").replace("$", "")
    out = {}
    patterns = (
        # 取 PD 的中点 N / 取PD中点N / 作PD中点N
        (r"(?:取|作|设|令|记)\s*([A-Z]{1,3})\s*的?\s*中点\s*(?:为|是|记作|记为)?\s*([A-Z])", 2, 1),
        # 设/令/记 N 为 PD 的中点
        (r"(?:设|令|记)\s*([A-Z])\s*(?:为|是)\s*(?:棱|边|线段|直线)?\s*([A-Z]{1,3})\s*的?\s*中点", 1, 2),
        # N 为棱 PD 的中点 / N是PD中点
        (r"([A-Z])\s*(?:为|是)\s*(?:棱|边|线段|直线)?\s*([A-Z]{1,3})\s*的?\s*中点", 1, 2),
        # PD 的中点为 N
        (r"([A-Z]{1,3})\s*的?\s*中点\s*(?:为|是|记作|记为)\s*([A-Z])", 2, 1),
    )
    for pattern, alias_group, obj_group in patterns:
        for match in re.finditer(pattern, s):
            alias = match.group(alias_group).upper()
            obj = norm_alias_object(match.group(obj_group))
            if not alias or not obj or alias == obj:
                continue
            out[alias] = f"{obj}中点"
    return out


def map_student_aliases(student_aliases, standard_aliases):
    """把学生字母映射到标准字母；只按“同一个几何对象”绑定。"""
    by_object = {}
    for std, obj in (standard_aliases or {}).items():
        by_object.setdefault(norm_alias_object(obj), std)
    mapping = {}
    for stu, obj in (student_aliases or {}).items():
        std = by_object.get(norm_alias_object(obj))
        if std and std != stu:
            mapping[stu] = std
    return mapping


def apply_aliases(text, alias_map):
    """按别名表替换学生字母。几何题的字母常相邻（MH、AH），不能按整词匹配。"""
    import re
    s = str(text or "")
    for src in sorted((alias_map or {}), key=len, reverse=True):
        dst = str(alias_map[src])
        if not src or not dst:
            continue
        # 允许前面是另一个大写字母（MH→MN、AH→AN），但不碰英文单词内部。
        s = re.sub(rf"(?<![a-z]){re.escape(src)}(?![a-z])", dst, s)
    return s


def _extract_part_headings(text, max_score):
    """从“### （1）…（4分）”“### （2）…（5→11分）”提取小问边界。"""
    import re
    parts = []
    prev_end = 0.0
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line.startswith("#"):
            continue
        if re.search(r"(评分标准|满分|参考答案|参考解答)", line):
            continue
        m_range = re.search(
            r"[（(]\s*([0-9]+(?:\.[0-9]+)?(?:\s*(?:→|->|—|–|-|~|～|至)\s*[0-9]+(?:\.[0-9]+)?)+)\s*分\s*[)）]\s*$",
            line)
        m_single = re.search(r"[（(]\s*([0-9]+(?:\.[0-9]+)?)\s*分\s*[)）]\s*$", line)
        if not m_range and not m_single:
            continue
        if m_range:
            nums = re.findall(r"[0-9]+(?:\.[0-9]+)?", m_range.group(1))
            end = float(nums[-1])
            part_max = round(end - prev_end, 2)
            prev_end = end
        else:
            part_max = float(m_single.group(1))
            prev_end = round(prev_end + part_max, 2)
        if part_max <= 0:
            return []
        title = re.sub(
            r"[（(]\s*[0-9]+(?:\.[0-9]+)?(?:\s*(?:→|->|—|–|-|~|～|至)\s*[0-9]+(?:\.[0-9]+)?)*\s*分\s*[)）]\s*$",
            "", line)
        title = title.lstrip("#").strip()
        parts.append({"title": title, "max_score": part_max})
    if not parts:
        return []
    if abs(sum(p["max_score"] for p in parts) - float(max_score or 0)) > 0.01:
        return []
    return parts


def _group_points_into_parts(points, rules, part_specs):
    """把扁平的给分点按小问分值分组；分不齐就退回单小问。"""
    if not points:
        return []
    if not part_specs:
        return [{"title": "全题",
                 "max_score": round(sum(float(v) for _, v in points), 2),
                 "points": list(points)}]
    groups = []
    idx = 0
    running = 0.0
    cumulative = bool((rules or {}).get("cumulative"))
    raw = list((rules or {}).get("cumulative_raw") or [])
    for spec in part_specs:
        part_max = float(spec.get("max_score") or 0)
        target = round(running + part_max, 2)
        group = []
        while idx < len(points):
            if cumulative and raw:
                value = float(raw[idx])
                if value <= target + 1e-9:
                    group.append(points[idx])
                    idx += 1
                else:
                    break
            else:
                value = float(points[idx][1])
                if round(running + value, 2) <= target + 1e-9:
                    running = round(running + value, 2)
                    group.append(points[idx])
                    idx += 1
                else:
                    break
        if not group:
            return []
        groups.append({"title": spec.get("title") or f"第{len(groups) + 1}小问",
                       "max_score": part_max, "points": group})
        running = target
    if idx != len(points):
        return []
    return groups


def _groups_from_numbered_lines(text, points):
    """从普通的“（1）”“（2）”“(ii)”分节行恢复小问边界。

    许多老师粘贴的参考答案没有 Markdown 标题，只在正文里写“（1）”“（2）”
    或 “(ii)”。这里按这些分节行切段，再用每段实际包含的采分点数量分组。
    """
    import re
    lines = (text or "").splitlines()
    headers = []
    label_re = re.compile(
        r"^\s*[（(]\s*([0-9]+|[ivxlcdmIVXLCDM]+)\s*[）)]")
    for index, line in enumerate(lines):
        match = label_re.match(line)
        if match:
            headers.append((index, f"（{match.group(1)}）", match.group(1)))
            continue
        # 第一行常见“18.【答案】（1）【证明】…”这种写法
        if index == 0:
            match = re.search(
                r"(?:【答案】|【解】|解\s*[：:])\s*[（(]\s*"
                r"([0-9]+|[ivxlcdmIVXLCDM]+)\s*[）)]",
                line)
            if match:
                headers.append((0, f"（{match.group(1)}）", match.group(1)))
    if len(headers) < 2:
        return []

    segments = []
    for index, (start, title, label) in enumerate(headers):
        end = headers[index + 1][0] if index + 1 < len(headers) else len(lines)
        chunk = "\n".join(lines[start:end])
        count = len(parse_rubric_rules(chunk, None).get("scored") or [])
        segments.append((title, label, count))
    if sum(count for _, _, count in segments) != len(points):
        return []

    groups = []
    cursor = 0
    for title, _label, count in segments:
        if count <= 0:
            continue
        group_points = list(points[cursor:cursor + count])
        cursor += count
        groups.append({
            "title": title,
            "max_score": round(sum(float(v) for _, v in group_points), 2),
            "points": group_points,
        })
    return groups if cursor == len(points) else []


def _deductions_for_point(index, rules):
    """取某个给分点明确写出的扣分数额（按原始扁平顺序）。"""
    out = []
    for rule in (rules or {}).get("deduction_rules") or []:
        if isinstance(rule, dict) and rule.get("point_index") == index:
            out.append(float(rule.get("amount", 0) or 0))
    return out


def _is_independent_point(point):
    """老师显式标为共用或结果点的采分点。不要从题干文字猜。"""
    return bool((point or {}).get("shared") or (point or {}).get("result_only"))


def _result_role_allowed(point, method, raw_point, part_type=""):
    """结果点可由老师显式标记，或由模型标为该解法最后一步；中间点不能冒充结果点。"""
    if (point or {}).get("result_only"):
        return True
    if part_type != "calculation":
        return False
    if not raw_point or raw_point.get("role") != "result":
        return False
    points = (method or {}).get("points") or []
    return bool(points and str(point.get("id")) == str(points[-1].get("id")))


def _alternative_methods_from_notes(parts, *texts):
    """把“第一问也可以先证明面面平行…同样可以给4分”变成一套可选的解法。"""
    import re
    found = []
    seen = set()
    for text in texts:
        for raw in str(text or "").splitlines():
            line = raw.strip()
            if not line or not re.search(r"(也可以|同样可以|另一种|另解|其他解法)", line):
                continue
            if not re.search(r"[0-9]+\s*分", line):
                continue
            target = None
            if re.search(r"(第一问|第\s*[（(]?1[)）]?\s*问|（1）|\(1\))", line):
                target = 0
            elif re.search(r"(第二问|第\s*[（(]?2[)）]?\s*问|（2）|\(2\))", line):
                target = 1
            if target is None or target >= len(parts):
                continue
            desc = re.sub(
                r"[，,。；;]?\s*(?:同样|也)?可以给\s*[0-9]+(?:\.[0-9]+)?\s*分.*$",
                "", line).strip("。；; ")
            desc = re.sub(r"^第[一二三1-3]问\s*", "", desc).strip()
            desc = re.sub(r"^(?:也)?可以(?:先)?", "", desc).strip()
            key = (target, desc)
            if desc and key not in seen:
                seen.add(key)
                found.append((target, desc))
    return found


def upgrade_rubric_card(card, max_score=None):
    """旧版单层评分卡自动升级成 v2，保证已保存的配置还能用。"""
    if not isinstance(card, dict):
        return card
    if card.get("version", 1) >= 2 and card.get("parts"):
        cumulative = bool(card.get("cumulative"))
        if cumulative:
            for part in card.get("parts") or []:
                part_max = float(part.get("max_score", 0) or 0)
                for method in part.get("methods") or []:
                    points = method.get("points") or []
                    if not points or all(p.get("band") for p in points):
                        continue
                    steps = [
                        (str(p.get("text") or p.get("goal") or "").strip(),
                         float(p.get("full", 0) or 0))
                        for p in points
                    ]
                    deductions = []
                    for point in points:
                        deductions.extend(point.get("deductions") or [])
                    band = _new_band_point(
                        steps, part_max, str(points[0].get("id") or ""),
                        deductions)
                    if band:
                        method["points"] = [band]
            card["score_mode"] = "bands"
        else:
            card.setdefault("score_mode", "points")
        card["version"] = CARD_VERSION
        # 已保存的 v2 卡片可能来自更早的版本，补齐后来增加的字段，
        # 避免“共用采分点”被当成普通点或编辑窗口读不到 shared。
        for part in card.get("parts") or []:
            for method in part.get("methods") or []:
                method_points = method.get("points") or []
                for point in method_points:
                    point.setdefault("shared", False)
                    point.setdefault("deductions", [])
                    point.setdefault("result_only", False)
                    point.setdefault("band", False)
                    point.setdefault("levels", [])
        card.setdefault("aliases", {})
        return card
    points = card.get("points") or []
    if not points:
        return card
    mx = float(card.get("max_score") or max_score or 0)
    part_points = []
    for i, old in enumerate(points, 1):
        point = dict(old)
        text = str(point.get("text") or point.get("goal") or "").strip()
        point["id"] = str(point.get("id") or f"1-A-{i}")
        point["text"] = text
        point["goal"] = str(point.get("goal") or text)
        point["full"] = float(point.get("full", 0) or 0)
        point["required"] = list(point.get("required") or ([text] if text else []))
        point["equivalents"] = list(point.get("equivalents") or extract_equivalents(text))
        point["notes"] = str(point.get("notes") or "")
        point["aliases"] = dict(point.get("aliases") or {})
        point["deductions"] = list(point.get("deductions") or [])
        point["zero_if"] = list(point.get("zero_if") or [])
        point["shared"] = bool(point.get("shared"))
        point["result_only"] = bool(point.get("result_only"))
        part_points.append(point)
    out = dict(card)
    out["version"] = CARD_VERSION
    out["score_mode"] = "points"
    out["parts"] = [{
        "id": "1",
        "title": "全题",
        "max_score": mx,
        "methods": [{"id": "1-A", "name": "标准解法", "notes": "", "points": part_points}],
    }]
    out["points"] = part_points
    out.setdefault("aliases", {})
    return out


def card_flat_points(card):
    """默认解法（每小问第一套）的扁平给分点，供旧界面/日志复用。"""
    if not isinstance(card, dict):
        return []
    card = upgrade_rubric_card(card)
    parts = card.get("parts") or []
    if not parts:
        return list(card.get("points") or [])
    out = []
    for part in parts:
        methods = part.get("methods") or []
        if not methods:
            continue
        for point in methods[0].get("points") or []:
            item = dict(point)
            item["part_id"] = part.get("id")
            item["method_id"] = methods[0].get("id")
            out.append(item)
    return out


def card_part_summary(card):
    card = upgrade_rubric_card(card)
    return [(str(p.get("id")), str(p.get("title")), float(p.get("max_score", 0) or 0),
             len(p.get("methods") or [])) for p in (card.get("parts") or [])]


def missing_card_parts(result, card):
    """模型返回的 parts 里缺少哪些小问。"""
    expected = [str(p.get("id")) for p in (card or {}).get("parts") or []]
    got = {str(p.get("part_id")) for p in (result or {}).get("parts") or []
           if isinstance(p, dict)}
    return [part_id for part_id in expected if part_id not in got]


def merge_grading_results(first, second, card):
    """合并两次返回：同一小问优先用第二次，缺的小问从第一次补。"""
    first = first if isinstance(first, dict) else {}
    second = second if isinstance(second, dict) else {}
    by_id = {}
    for source in (first, second):
        for part in source.get("parts") or []:
            if isinstance(part, dict) and str(part.get("part_id", "")).strip():
                by_id[str(part.get("part_id")).strip()] = part
    merged = dict(second)
    merged["parts"] = [
        by_id[str(part.get("id"))]
        for part in (card or {}).get("parts") or []
        if str(part.get("id")) in by_id
    ]
    first_text = str(first.get("transcription") or "")
    second_text = str(second.get("transcription") or "")
    merged["transcription"] = second_text if len(second_text) >= len(first_text) else first_text
    symbols = []
    for source in (first, second):
        for symbol in source.get("symbol_map") or []:
            if symbol not in symbols:
                symbols.append(symbol)
    merged["symbol_map"] = symbols
    if not str(merged.get("analysis") or "").strip():
        merged["analysis"] = str(first.get("analysis") or "")
    return merged


def _point_deductions(point, fallback=None):
    values = []
    for value in (point or {}).get("deductions") or []:
        try:
            values.append(round(float(value), 2))
        except (TypeError, ValueError):
            pass
    if not values and fallback:
        for value in fallback:
            if isinstance(value, (int, float)):
                values.append(round(float(value), 2))
    return values


def split_requirement_units(text):
    """把一条采分点拆成给模型看的核对提示（程序不按条数机械卡人）。

    只按评分标准里的通用逻辑连接词拆分，不依赖题号、字母或题型。
    """
    import re
    source = str(text or "").strip()
    if not source:
        return []
    chunks = re.split(
        r"[；;]|→|->|\\therefore|∴|"
        r"。\s*(?=(?:又|而|则|即|所以|因此|故|由|设|取|作|令|记))|"
        r"，(?=(?:得|求出|解得|证出|推出|所以|进而|写出|得到|可得))",
        source,
    )
    out = []
    for chunk in chunks:
        value = chunk.strip(" ，,。；;")
        value = re.sub(
            r"^(?:得|求出|解得|证出|推出|所以|进而|写出|得到|可得)\s*",
            "", value,
        ).strip()
        if len(norm_math_text(value)) >= 3 and value not in out:
            out.append(value)
    return out or [source]


def _point_checks(raw):
    """读取模型返回的分项核对；旧响应没有 checks 时返回空列表。"""
    checks = (raw or {}).get("checks")
    if not isinstance(checks, list):
        return []
    out = []
    for check in checks:
        if not isinstance(check, dict):
            continue
        out.append({
            "requirement": str(check.get("requirement") or "").strip(),
            "shown": check.get("shown") is True,
            "evidence": str(check.get("evidence") or "").strip(),
            "equivalent": check.get("equivalent") is True,
        })
    return out


def _v2_item(part, method, point, got, evidence, reason):
    return {
        "point": str(point.get("text", "") or point.get("goal", "")),
        "full": float(point.get("full", 0) or 0),
        "got": float(got),
        "reason": str(reason or ""),
        "evidence": str(evidence or ""),
        "part_id": str(part.get("id", "")),
        "part_title": str(part.get("title", "")),
        "method_id": str(method.get("id", "")),
        "method_name": str(method.get("name", "")),
        "point_id": str(point.get("id", "")),
        "role": str(point.get("role", "") or ""),
    }


def save_result_debug(result, card, score):
    """把最近一次原始判分写到 %TEMP%，方便复现“模型说满分、程序算0分”这类问题。"""
    try:
        path = os.path.join(os.environ.get("TEMP", "."), "paper2_last_result.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"score": score, "card": card, "result": result},
                      handle, ensure_ascii=False, indent=2)
    except Exception:
        pass


def rubric_fingerprint(answer_text, rubric_text, max_score):
    """标准指纹：答案/给分点/满分任一改动，评分卡即失效。"""
    import hashlib
    def clean(value):
        return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    raw = f"{clean(answer_text)}\n::\n{clean(rubric_text)}\n::\n{fmt_score(max_score)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_rubric_card(answer_text, rubric_text, question_num, max_score):
    """把评分标准整理成 v2 评分卡：小问 → 多套解法 → 采分点。"""
    points, source, rules = resolve_rubric_points(rubric_text, answer_text, max_score)
    if not points:
        return None

    groups = _groups_from_numbered_lines(answer_text, points)
    if not groups:
        part_specs = _extract_part_headings(answer_text, max_score)
        if not part_specs:
            part_specs = _extract_part_headings(rubric_text, max_score)
        groups = _group_points_into_parts(points, rules, part_specs)
    if not groups:
        groups = [{"title": "全题",
                   "max_score": round(sum(float(v) for _, v in points), 2),
                   "points": list(points)}]

    band_mode = bool(rules.get("cumulative"))
    parts = []
    flat_index = 0
    for i, group in enumerate(groups, 1):
        part_id = str(i)
        group_points = list(group["points"])
        group_deductions = []
        for offset in range(len(group_points)):
            group_deductions.extend(_deductions_for_point(flat_index + offset, rules))
        method_points = []
        for j, (text, full) in enumerate(group["points"], 1):
            point = _new_card_point(
                text, full, f"{part_id}-A-{j}", _deductions_for_point(flat_index, rules))
            method_points.append(point)
            flat_index += 1
        if band_mode:
            band = _new_band_point(
                group_points, float(group["max_score"]), f"{part_id}-A-1",
                group_deductions)
            if band:
                method_points = [band]
        parts.append({
            "id": part_id,
            "title": group["title"],
            "max_score": float(group["max_score"]),
            "methods": [{
                "id": f"{part_id}-A",
                "name": "标准解法",
                "notes": "",
                "points": method_points,
            }],
        })

    # 标准说明里明确写了“也可以……”的，自动生成一套可选解法；
    # 老师可在评分卡里继续补充必需要素。
    for target, desc in _alternative_methods_from_notes(parts, answer_text, rubric_text):
        part = parts[target]
        used = {m.get("id") for m in part["methods"]}
        suffix = 66
        method_id = f"{part['id']}-{chr(suffix)}"
        while method_id in used and suffix < 90:
            suffix += 1
            method_id = f"{part['id']}-{chr(suffix)}"
        alt_points = [_new_card_point(desc, float(part["max_score"]), f"{method_id}-1")]
        if band_mode:
            alt = _new_band_point(
                [(desc, float(part["max_score"]))],
                float(part["max_score"]), f"{method_id}-1")
            if alt:
                alt_points = [alt]
        part["methods"].append({
            "id": method_id,
            "name": "说明中的其他解法",
            "notes": "来自评分标准说明，建议补充必需要素",
            "points": alt_points,
        })

    card_points = []
    for part in parts:
        for point in part["methods"][0]["points"]:
            item = dict(point)
            item["part_id"] = part["id"]
            item["method_id"] = part["methods"][0]["id"]
            card_points.append(item)

    return {
        "version": CARD_VERSION,
        "score_mode": "bands" if band_mode else "points",
        "question_num": str(question_num or ""),
        "max_score": float(max_score or 0),
        "source": source,
        "cumulative": bool(rules.get("cumulative")),
        "cumulative_raw": list(rules.get("cumulative_raw") or []),
        "parts": parts,
        "points": card_points,
        "aliases": extract_aliases(answer_text),
        "rules": list(rules.get("notes") or [])[:12],
        "score_cap": rules.get("score_cap"),
        "cap_text": rules.get("cap_text", ""),
        "zero_rules": list(rules.get("zero_rules") or [])[:12],
        "deduction_rules": list(rules.get("deduction_rules") or [])[:12],
        "fingerprint": rubric_fingerprint(answer_text, rubric_text, max_score),
        "updated": datetime.now().isoformat(timespec="seconds"),
    }


def validate_rubric_card(card, max_score=None):
    """返回问题列表；空列表表示可用。每套解法的合计都必须等于小问满分。"""
    issues = []
    if not isinstance(card, dict):
        return ["评分卡为空"]
    card = upgrade_rubric_card(card, max_score)
    parts = card.get("parts") or []
    if not parts:
        return ["评分卡没有小问"]
    mx = float(max_score if max_score is not None else card.get("max_score", 0) or 0)
    part_total = 0.0
    seen_methods = set()
    seen_points = set()
    for part in parts:
        part_id = str(part.get("id", "?"))
        try:
            part_max = float(part.get("max_score", 0) or 0)
        except (TypeError, ValueError):
            issues.append(f"第 {part_id} 小问满分无效")
            continue
        part_total += part_max
        methods = part.get("methods") or []
        if not methods:
            issues.append(f"第 {part_id} 小问没有解法")
            continue
        for method in methods:
            method_id = str(method.get("id", "?"))
            if method_id in seen_methods:
                issues.append(f"解法编号重复：{method_id}")
            seen_methods.add(method_id)
            points = method.get("points") or []
            if not points:
                issues.append(f"解法 {method_id} 没有得分点")
                continue
            method_total = 0.0
            for point in points:
                point_id = str(point.get("id", "?"))
                if point_id in seen_points:
                    issues.append(f"得分点编号重复：{point_id}")
                seen_points.add(point_id)
                try:
                    full = float(point.get("full", 0) or 0)
                except (TypeError, ValueError):
                    issues.append(f"得分点 {point_id} 分值无效")
                    continue
                if full <= 0:
                    issues.append(f"得分点 {point_id} 分值必须大于 0")
                if point.get("band"):
                    levels = point.get("levels") or []
                    scores = []
                    for level in levels:
                        try:
                            score = float(level.get("score", 0) or 0)
                        except (TypeError, ValueError, AttributeError):
                            score = 0.0
                        if score <= 0 or score > full + 0.01:
                            issues.append(f"分档点 {point_id} 的档位分值无效")
                            break
                        scores.append(score)
                    else:
                        if not scores:
                            issues.append(f"分档点 {point_id} 没有档位")
                        elif any(b <= a + 1e-9 for a, b in zip(scores, scores[1:])):
                            issues.append(f"分档点 {point_id} 的档位必须递增")
                        elif abs(scores[-1] - full) > 0.01:
                            issues.append(
                                f"分档点 {point_id} 最高档 {fmt_score(scores[-1])} "
                                f"与满分 {fmt_score(full)} 不一致")
                method_total += full
            if abs(method_total - part_max) > 0.01:
                issues.append(
                    f"解法 {method_id} 合计 {fmt_score(method_total)} 分，"
                    f"与第 {part_id} 小问满分 {fmt_score(part_max)} 不一致")
    if mx and abs(part_total - mx) > 0.01:
        issues.append(f"各小问满分合计 {fmt_score(part_total)} 分，与满分 {fmt_score(mx)} 不一致")
    return issues


def card_is_fresh(card, answer_text, rubric_text, max_score):
    if not isinstance(card, dict) or not card.get("points"):
        return False
    return card.get("fingerprint") == rubric_fingerprint(answer_text, rubric_text, max_score)


def rules_from_card(card):
    """从评分卡还原给分点之外的硬规则，保证卡片模式与文本模式一致。"""
    return {
        "cumulative": bool(card.get("cumulative")),
        "cumulative_raw": list(card.get("cumulative_raw") or []),
        "notes": list(card.get("rules") or []),
        "score_cap": card.get("score_cap"),
        "cap_text": card.get("cap_text", ""),
        "zero_rules": list(card.get("zero_rules") or []),
        "deduction_rules": list(card.get("deduction_rules") or []),
    }


def build_grading_prompt_v2(question_num, max_score, standard_answer, rubric_text,
                            half_point, card):
    """v2 提示词：按小问列多套解法，模型选一套并逐点找证据。"""
    lines = []
    for part in card.get("parts") or []:
        lines.append(f"【第{part.get('id')}小问】{part.get('title')}  "
                     f"满分{fmt_score(part.get('max_score', 0))}分")
        for method in part.get("methods") or []:
            method_total = sum(float(p.get("full", 0) or 0)
                               for p in (method.get("points") or []))
            lines.append(f"  解法 {method.get('id')}「{method.get('name')}」"
                         f"合计{fmt_score(method_total)}分")
            if method.get("notes"):
                lines.append(f"    说明：{method['notes']}")
            for point in method.get("points") or []:
                if point.get("result_only"):
                    shared_tag = "【结果】"
                elif point.get("shared"):
                    shared_tag = "【共用】"
                else:
                    shared_tag = ""
                line = (f"    {shared_tag}{point.get('id')}（{fmt_score(point.get('full', 0))}分）："
                        f"{point.get('text', '')}")
                if point.get("band"):
                    levels = point.get("levels") or []
                    allowed = format_score_levels(levels)
                    line += f"；只允许 0 或 {allowed} 分，不得自行拆成其他分"
                    lines.append(line)
                    for index, level in enumerate(levels, 1):
                        prefix = ("达到本档还须在完成前面各档的基础上做到"
                                  if index > 1 else "本档要求")
                        lines.append(
                            f"      {fmt_score(level.get('score', 0))}分档："
                            f"{prefix}：{level.get('text', '')}")
                    if point.get("deductions"):
                        lines.append(
                            "      明确扣分："
                            + "、".join(f"扣{fmt_score(x)}分"
                                        for x in point["deductions"]))
                    continue
                equivalents = [str(x).strip() for x in (point.get("equivalents") or [])
                               if str(x).strip()]
                if equivalents:
                    line += "；等价写法：" + "、".join(equivalents)
                if point.get("notes"):
                    line += "；" + str(point["notes"])
                lines.append(line)
    card_text = "\n".join(lines)
    answer_note = ""
    if card.get("source") == "answer":
        answer_note = ("\n（注意：上面『参考答案』里若带有分值，可能是累计分或原卷标注，"
                       "一律不作为计分依据；只按下面『评分卡』的分值判。）")
    return f"""你是高中数学阅卷老师。图片是学生第{question_num}题的作答，满分{fmt_score(max_score)}分。

参考答案：
{standard_answer}{answer_note}

评分卡（唯一评分依据；每个小问只能选一套解法，不得跨解法凑分）：
{card_text}

判分要求（严格执行，不得放宽）：
前置原则：证明题先看逻辑链条是否完整，不要因为没用标准辅助线/标准方法就判低；计算题先看最终结果是否正确，结果对的结果点必须给分。两种判断都只能依据学生原文，不能替学生补步骤。
0. 先把图片里学生的关键步骤和结论完整转写（数学式用普通写法或 LaTeX，看不清写【看不清】），放在 transcription，控制在 600 字以内；后续判分只能依据这份转写，不许凭印象补。尤其不要漏掉每一问的最后结论、负号、两个解和最终数值。
1. 每个小问先判断学生用的是哪一套解法，method_id 只能填该小问下面列出的解法编号；选了哪套就只按那套的采分点判，不能把两套解法的分拼在一起。若学生用了未列出的方法，method_id 填 "uncovered"，不要硬套某一套。
1b. 每个 part 填 part_type："proof" 表示证明题，"calculation" 表示计算/求值题。每个 point 填 role："process"（中间过程）、"conclusion"（几何/逻辑结论）或 "result"（最终数值/结果）。角色由你按数学内容判断，不要按题号或字母猜。
1b2. role="result" 只能用于 calculation 小问的最后一个结果点，或评分卡明确标了【结果】的点；中间步骤、证明题的步骤都不能标 result。
1c. 评分卡里写“整问按原标准分档”的小问只有一个评分单元，不再逐句拆分小点，也不需要输出 checks。先整体看学生数学上完成到原标准的哪一档，不要因为没照抄标准步骤、辅助线、字母或写法就判低。
2. 分档描述是判断数学完成度的依据，不是要求学生逐字出现的“关键词清单”。学生用另一种正确方法，只要该档要求的数学结论、证明链条或计算结果实际上已经完成，就应当给该档；只有该档确有内容缺失、跳步、错误或尚未完成时，才落到前面已经完整达到的最高档。严禁按“像不像标准答案”酌情给分，也不要自行创造评分卡之外的分数。
3. 每个分档点的 full 就是该小问满分；got 只能填 0、该点列出的某个档位分，或标准明确写明的“满分−扣分数”。不得自行给 1.5、3.5 等卡外分数。若学生只完成某档的一部分，只能取前面已经完整达到的最高档；一档都没完整达到就是 0 分。
4. 学生用不同字母表示同一个几何对象时，先建立别名，再判分。例如“取 PD 的中点 H”表示 H 就是标准解法里的 N，后面 MH∥CD 等价于 MN∥CD。别名必须有学生原文里的定义句，不能猜；没有定义句的字母不要自行绑定。
4b. 学生写“∥=”“平行且等于”“平行且相等”时，表示同时平行且相等；不要只按平行处理。像“MH∥=½CD∥=AB”已经推出 MH∥AB 且 MH=AB，平行四边形条件完整，不要因为没单独再写“AB=MN”而扣分。
5. 如果学生的方法不在任何一套解法里，method_id 填 "uncovered"。仍然按分档内容整体判断数学上是否达到各档；标了【共用】或【结果】的点照常判断。给分时把该 point 的 "equivalent" 填 true，表示学生用等价方法完成。不要把“方法不同”本身当成扣分理由，也不要因为没出现标准辅助线或字母就压档。
5b. 计算题若原标准的某一档明确只要求最终结论/数值，看到正确结果即可给到该档；若该档还要求推导、方程或过程，则不能只凭最终结果跳到该档。正确结果不能被漏掉，也不能用它倒推学生没写出的更高档过程。
5c. 证明小问如果学生用了任何方法（包括未列出的方法），但证明过程完整、逻辑正确，并且明确写出了该结论所需的条件，则按该小问所有采分点满分处理。此时填 "part_type":"proof" 和 "complete_proof":true，并在 "proof_evidence" 中引用覆盖证明链条的原文；points 可以按标准点返回，也可以留空，程序会按该小问满分。证明不完整、跳步或只写结论的，complete_proof 填 false，不能虚报。
6. 每个得到分的分档点都要填 evidence：从 transcription 里摘录最能证明“为什么达到这一档”的连续学生原文，可包含多个式子，控制在 100 字以内。got 为 0 时 evidence 可以留空。got 大于 0 却没有 evidence，或 evidence 在 transcription 里找不到，程序会改判 0 分。不要再输出 checks。
7. 每个小问的得分不能超过该小问满分；score 必须等于各小问得分之和，绝不能超过 {fmt_score(max_score)} 分。
8. 拿不准是否完成该点时按未完成处理（记 0 分）；但已经明确写出的正确结论不能被否定。同一处错误只扣一次。
9. 不要输出“小计”“合计”这类汇总行；points 只列该小问评分卡里的那一个分档点，point_id 必须使用卡里的编号。method_id=uncovered 时，请在得分的 point 里填 "equivalent":true；没有填或填 false 的程序按 0 分处理。

证据要求（硬性）：
- got 大于 0 的每个点都必须有 evidence，而且 evidence 必须能在 transcription 里找到。
- evidence 要能说明该档位所需的数学完成度，不能只写“会做”“正确”等空话；但也不要要求逐字包含分档描述。
- reason 写清这一分给在哪一步、为什么，不超过 16 字。

等价判定（双向严格，必须照做）：
- 等价指学生写出的内容与给分点要求的是同一个数学对象或同一个结论，能通过移项、恒等变形、代入、参数化互相得到。例如：15x−8y−55=0 与 8y=15x−55、y=(15/8)x−55/8 等价；法向量 (2,-2,4) 与 (1,-1,2) 等价；换原点后坐标不同但二面角余弦相同，等价。
- 等价写法必须按该给分点给满分，不得因形式不同、步骤顺序不同、字母符号不同而扣分或记 0 分。
- 以下一律不算等价、记 0 分：只写了相关公式或概念但没写出该点结果；只写“由…可得”后面没有结果；结果数值、符号或范围错误；推导与结论无关。

直接输出 JSON，不要任何别的文字。transcription 和 evidence 都写成一行，不要换行，不要出现英文双引号（需要引用时用「」），否则 JSON 会解析失败：
{{"transcription":"学生答卷原文（逐行）","symbol_map":[{{"student":"H","standard":"N","definition":"取PD中点H"}}],"parts":[{{"part_id":"1","method_id":"1-A","part_type":"proof","complete_proof":false,"proof_evidence":"","points":[{{"point_id":"1-A-1","full":4,"got":3,"evidence":"学生原文摘录","reason":"达到3分档","equivalent":false}}]}}],"score":总分,"confidence":"高/中/低","unclear":false,"analysis":"一句话评语"}}"""


def build_grading_prompt(question_num, max_score, standard_answer, rubric_text, half_point, card=None):
    """批改提示词：一次请求，看图直接判分。严格按给定给分点，不自行加码。"""
    card_ok = card and not validate_rubric_card(card, max_score)
    if card_ok:
        card = upgrade_rubric_card(card, max_score)
        if card.get("parts"):
            return build_grading_prompt_v2(
                question_num, max_score, standard_answer, rubric_text, half_point, card)
        scored = [(p["text"], float(p["full"])) for p in card["points"]]
        source, rules = "card", rules_from_card(card)
    else:
        scored, source, rules = resolve_rubric_points(rubric_text, standard_answer, max_score)
    if scored:
        if card_ok:
            lines = []
            for i, p in enumerate(card["points"], 1):
                line = f"{i}. {p['text']}（{fmt_score(p['full'])}分）"
                eq = [e for e in (p.get("equivalents") or []) if e]
                if eq:
                    line += "；等价写法：" + "、".join(eq)
                if p.get("notes"):
                    line += "；" + str(p["notes"])
                lines.append(line)
            rows = "\n".join(lines)
        else:
            rows = "\n".join(f"{i+1}. {p}（{fmt_score(v)}分）" for i, (p, v) in enumerate(scored))
        origin = {"rubric": "", "answer": "（取自参考答案中的评分标准）",
                  "card": "（评分卡，已确认）"}.get(source, "")
        rubric_part = f"给分点{origin}（唯一评分依据，不增不减、不改分值）：\n{rows}"
        if rules["cumulative"]:
            raw = "、".join(str(fmt_score(v)) for v in rules["cumulative_raw"])
            rubric_part += (f"\n（原标准写作累计分 {raw}，已换算为每步增量；"
                            f"full 一律填增量分，不得填累计分）")
        import re as _re
        rule_lines = [n for n in rules.get("notes", [])
                      if len(n) <= 120 and
                      _re.search(r"(扣|零分|不得|最多|至少|必须|同时|分别|关键|采分点|注意|若|如果)", n)]
        if rule_lines:
            rubric_part += "\n评分说明（与给分点同等约束）：\n" + "\n".join(
                f"- {n.lstrip('-*•· ')}" for n in rule_lines[:10])
    else:
        rubric_part = ("给分点：未提供。按参考答案的解题步骤逐条给分：每条分值按参考答案标注的步骤分，"
                       "没标注的按步骤在满分内拆分；只给完成了该步骤的分数，不得给步骤之外的分数。")
    answer_note = ""
    if source == "answer":
        answer_note = ("\n（注意：上面『参考答案』里若带有分值，可能是累计分或原卷标注，"
                       "一律不作为计分依据；只按下面『给分点』的分值判。）")
    return f"""你是高中数学阅卷老师。图片是学生第{question_num}题的作答，满分{fmt_score(max_score)}分。

参考答案：
{standard_answer}{answer_note}

{rubric_part}

判分要求（严格执行，不得放宽）：
0. 先把图片里学生的关键步骤和结论完整转写（数学式用普通写法或 LaTeX，看不清写【看不清】），放在 transcription，控制在 600 字以内；后续判分只能依据这份转写，不许凭印象补。尤其不要漏掉每一问的最后结论、负号、两个解和最终数值。
1. 只按图片里看得到的内容判，不替学生补步骤；字迹看不清影响判分时 unclear 填 true。
2. 逐条对照给分点：学生答案里必须明确写出该点要求的公式、方程或结论（或数学上等价的正确表达），才给该点满分；没看到该得分点、也没有等价表达，或只写相关思路、跳步、该点结论写错的，该点一律记 0 分。严禁酌情给分，不给“思路分”“步骤分”“同情分”，不凑分。
2b. 每个给分点的 got 只能是 0、full，或评分标准明确写明的 full−N；标准没有写明扣分数额的，一律只能是 0 分或满分，不许自行估扣、不许按比例给分，也不许因为“写了一半”给一半。
2c. 给分点里的“且”“同时”“分别”“必须交代”“并且”都是并列必要条件，缺一项该点就是 0 分；写“或”的地方任一形式成立即可。
2d. 同一个给分点里用顿号列出的多个结果，也属于该点的全部要求。evidence 必须覆盖这些要求；覆盖了就必须填 full，不能因为学生写得简略、没有重复展开或步骤顺序不同而给部分分。只有 2b 明确允许的扣分才能低于 full。
2e. 计算题的最后结果点独立核对：只要最终结果/数值正确，即使中间步骤没写、写得简略或方法不同，也给该结果点的满分；不能因为前面步骤没写而把结果点判 0。其他过程点仍必须看到对应过程或等价过程。
3. 不得新增、拆分、合并给分点，不得改动每条给分点的分值，也不得在给分点之外额外给分。
4. 学生用等价解法（如用极点极线直接写切点弦方程），只要确实完成了该给分点要求，按该点给分，alt_method 填 true；等价解法不是加分理由，也不改变分值。
4b. 证明题如果学生用未列出的方法，但证明完整、逻辑正确并写出了结论所需条件，按该小问满分处理，items 中每个点填 full；如果证明不完整、跳步或只写结论，只按实际完成点给分，不能按满分。
5. 前一步算错导致后面数值错、但后面步骤本身写对，按该给分点给分；除 2e 明确规定的最终结果点外，只有结果没有过程的过程点记 0 分。
6. 不因书写潦草（能看清的）或格式扣分。
7. items 只列上面的给分点，顺序和分值保持原样，禁止输出“第(1)问合计”“小计”“总分”这类汇总行。
8. full 必须是「这一步新增的分值」，不是累计到这一步的总分；所有 full 相加必须正好等于 {fmt_score(max_score)} 分；score 必须等于 items 中 got 之和，绝不能超过满分。got 不是 0/full 时，必须在 reason 里说明评分标准哪一条明确允许这个扣分；否则程序会改判 0。
9. 拿不准是否完成该点时按未完成处理（记 0 分）；但已经明确写出的正确结论不能被否定。同一处错误只扣一次。

证据要求（硬性）：
- 每个给分点都要填 evidence：从 transcription 里摘录支持该点得分的那一小段学生原文（一两个式子即可，不超过 40 字）。got 为 0 时 evidence 留空字符串。
- got 大于 0 却没有 evidence，程序会直接把该点改判 0 分；所以没看到、只是觉得“应该会”的，一律不要给分。
- reason 写清这一分给在哪一步、为什么，不超过 12 字。

等价判定（双向严格，必须照做）：
- 等价指学生写出的内容与给分点要求的是同一个数学对象或同一个结论，能通过移项、恒等变形、代入、参数化互相得到。例如：15x−8y−55=0 与 8y=15x−55、y=(15/8)x−55/8 等价；(x−3/2)²+(y+3)²=17/4 与 x²+y²−3x+6y+7=0 等价；用极点极线直接写切点弦，与四点共圆、两圆相减得到同一条直线等价；向量法、坐标法、几何法得到同一结论等价。
- 等价写法必须按该给分点给满分，不得因形式不同、步骤顺序不同、字母符号不同而扣分或记 0 分。
- 以下一律不算等价、记 0 分：只写了相关公式或概念但没写出该点结果；只写“由…可得”后面没有结果；结果数值、符号或范围错误；推导与结论无关。
- 判定方法：先在学生答卷里找到该点要求的最终结果（公式/方程/数值/结论），再判断是否等价；找不到就记 0 分，不要用“他应该会”“思路对”来补。

直接输出 JSON，不要任何别的文字。transcription 和 evidence 都写成一行，不要换行，不要出现英文双引号（需要引用时用「」），否则 JSON 会解析失败：
{{"transcription":"学生答卷原文（逐行）","items":[{{"point":"给分点","full":分值,"got":得分,"evidence":"学生原文摘录","reason":"理由"}}],"score":总分,"confidence":"高/中/低","unclear":false,"alt_method":false,"analysis":"一句话评语"}}"""


def norm_math_text(s):
    """归一化数学文本：去空白/标点/LaTeX 符号差异，便于比对依据。"""
    import re
    s = str(s or "")
    s = s.replace("$", "")
    s = s.replace("−", "-").replace("–", "-").replace("—", "-")
    s = s.replace("∥", "//").replace("／", "/").replace("∕", "/")
    commands = {
        "parallel": "//", "perp": "⊥", "angle": "∠", "triangle": "△",
        "because": "∵", "therefore": "∴", "cdot": "*", "times": "*", "div": "÷",
        "pm": "±", "mp": "∓", "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥",
        "neq": "≠", "ne": "≠", "approx": "≈", "equiv": "≡",
        "Rightarrow": "⇒", "Leftrightarrow": "⇔", "rightarrow": "→", "to": "→",
        "in": "∈", "notin": "∉", "subseteq": "⊆", "subset": "⊂",
        "cup": "∪", "cap": "∩",
        "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ",
        "theta": "θ", "lambda": "λ", "mu": "μ", "pi": "π",
        "rho": "ρ", "sigma": "σ", "phi": "φ", "omega": "ω",
        "Delta": "Δ", "Sigma": "Σ", "Omega": "Ω",
    }
    for name in sorted(commands, key=len, reverse=True):
        s = re.sub(r"\\" + re.escape(name) + r"(?![A-Za-z])", commands[name], s)
    s = re.sub(r"\\(?:left|right|big|Big|bigg|Bigg)\b", "", s)
    s = re.sub(r"\\[,;:!]", "", s)
    for _ in range(3):
        s = re.sub(r"\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"(\1)/(\2)", s)
        s = re.sub(r"\\sqrt\s*\{([^{}]*)\}", r"√(\1)", s)
        s = re.sub(r"\\sqrt\s*([0-9A-Za-z])", r"√\1", s)
        s = re.sub(r"\\(?:mathrm|mathbf|mathit|text|operatorname)\s*\{([^{}]*)\}", r"\1", s)
        s = re.sub(r"\\(?:vec|overrightarrow|overline|underline)\s*\{([^{}]*)\}", r"\1", s)
    s = s.replace("\\", "")
    s = s.replace("平行", "//").replace("垂直", "⊥").replace("三角形", "△")
    s = s.replace("因为", "∵").replace("所以", "∴").replace("根号", "√")
    s = re.sub(r"[\s，,。；;：:、（）()\[\]{}【】“”\"'']", "", s)
    return s.lower()


def evidence_supported(evidence, transcription):
    """依据是否真能在答卷原文里找到（容忍 OCR 小差异）。"""
    ev = norm_math_text(evidence)
    tr = norm_math_text(transcription)
    if len(ev) < 3 or not tr:
        return True
    if ev in tr:
        return True
    import difflib
    m = difflib.SequenceMatcher(None, ev, tr).find_longest_match(0, len(ev), 0, len(tr))
    if len(ev) <= 12:
        return m.size / len(ev) >= 0.95
    if m.size / len(ev) >= 0.7:
        return True
    from collections import Counter
    ce, ct = Counter(ev), Counter(tr)
    hit = sum(min(v, ct[k]) for k, v in ce.items())
    return hit / len(ev) >= 0.85


def repair_json_latex(text):
    """把 JSON 字符串里未转义的 LaTeX 命令补成双反斜杠。"""
    import re
    commands = (
        "frac|sqrt|left|right|big|Big|bigg|Bigg|cdot|times|div|pm|mp|"
        "leq|le|geq|ge|neq|ne|approx|equiv|parallel|perp|angle|triangle|"
        "because|therefore|alpha|beta|gamma|delta|theta|lambda|mu|pi|rho|"
        "sigma|phi|omega|Delta|Sigma|Omega|text|mathrm|mathbf|mathit|"
        "operatorname|vec|overrightarrow|overline|underline|begin|end|"
        "sum|int|lim|log|ln|sin|cos|tan|cot|sec|csc|arcsin|arccos|arctan|"
        "infty|partial|nabla|forall|exists|neg|land|lor|implies|iff|"
        "quad|qquad|subseteq|subset|cup|cap|in|notin|to|rightarrow|"
        "Rightarrow|Leftrightarrow"
    )
    pattern = r"(?<!\\)\\(?=(?:" + commands + r")\b)"
    return re.sub(pattern, lambda _m: "\\\\", str(text or ""))


def close_truncated_json(text):
    """给被模型截断的 JSON 补上字符串和括号，尽量恢复最后一个完整对象。"""
    import re
    source = str(text or "").strip()
    if not source:
        return source
    in_string = escaped = False
    stack = []
    for char in source:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append(char)
        elif char in "}]" and stack:
            stack.pop()
    fixed = source
    if in_string:
        fixed += '"'
    fixed = fixed.rstrip()
    fixed = re.sub(r",\s*$", "", fixed)
    for opener in reversed(stack):
        fixed += "}" if opener == "{" else "]"
    return fixed


def iter_balanced_json_objects(text):
    """按括号层级找出文本中的完整 JSON 对象，忽略字符串里的括号。"""
    source = str(text or "")
    depth = 0
    start = None
    in_string = escaped = False
    for index, char in enumerate(source):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                yield source[start:index + 1]
                start = None


def _goal_text(text):
    """把评分点/证据整理成便于检查关键步骤的普通数学文本。"""
    import re
    s = str(text or "")
    s = s.replace("\\not\\subset", "⊄").replace("\\not\\in", "∉")
    replacements = (
        ("\\perp", "⊥"), ("\\parallel", "∥"), ("\\subset", "⊂"),
        ("\\cos", "cos"), ("\\sqrt", "√"), ("\\overrightarrow", ""),
        ("\\vec", ""), ("\\because", "∵"), ("\\therefore", "∴"),
        ("垂直于", "⊥"), ("平行于", "∥"),
    )
    for old, new in replacements:
        s = s.replace(old, new)
    s = s.replace("\\(", "").replace("\\)", "").replace("$", "")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _point_goal_covered(text, evidence, alias_map):
    """用通用“关键步骤”检查证据，避免把正确的计算结果误判成 0。

    只拦明显的结果倒灌，例如只写 λ 的值、没有写距离公式；
    不要求模型把每一个推导小句都拆成独立 check。
    """
    import re
    t = _goal_text(apply_aliases(text, alias_map))
    e = _goal_text(apply_aliases(evidence, alias_map))
    if not e:
        return False

    # “BM 不在平面内 + AN 在平面内”这类必须同时交代的条件。
    if "⊄" in t and "⊂" in t:
        left = re.findall(r"([A-Z]{1,4})\s*[，,]?\s*⊄", t)
        right = re.findall(r"([A-Z]{1,4})\s*[，,]?\s*⊂", t)
        if left and right:
            if not all(label in e for label in left + right):
                return False

    # 证明“取 PD 的中点 N”这类构造，证据里必须出现该对象和中点。
    construct = re.match(
        r"^\s*(?:取|作|设|令|记)\s*([A-Z]{1,4})\s*的?\s*中点", t)
    if construct:
        obj = construct.group(1)
        if "中点" not in e or obj not in e:
            return False

    if "平行四边形" in t:
        if not any(word in e for word in (
                "平行四边形", "矩形", "平行且相等", "∥=")):
            return False

    if "⊥平面" in t or "⊥ 平面" in t:
        if "⊥" not in e or not any(word in e for word in ("平面", "底面")):
            return False

    if "法向量" in t and "cos" not in t.lower() and "距离" not in t:
        if not re.search(r"\([^()]*,[^()]*,[^()]*\)", e):
            return False

    if "cos" in t.lower():
        if "cos" not in e.lower():
            return False

    if "坐标" in t:
        if len(re.findall(r"\([^()]*,[^()]*,[^()]*\)", e)) < 3:
            return False

    if "距离" in t or "公式" in t:
        if not any(mark in e for mark in ("距离", "公式", "√", "|")):
            return False

    if "BQ" in t and "BQ" not in e:
        return False

    return True


def _score_point_v2(point, raw, transcription, alias_map, normalized_transcription,
                    allowed_deductions=None, allow_result_role=True):
    """按一个采分点判分，返回 (got, evidence, reason, program_note)。"""
    try:
        full = float(point.get("full", 0) or 0)
    except (TypeError, ValueError):
        full = 0.0
    got = 0.0
    evidence = ""
    reason = "未返回该得分点"
    note = ""
    if not raw:
        return got, evidence, reason, note
    try:
        got = float(raw.get("got", 0) or 0)
    except (TypeError, ValueError):
        got = 0.0
    got = max(0.0, min(got, full))
    evidence = str(raw.get("evidence", "") or "").strip()
    reason = str(raw.get("reason", "") or "")
    role = str(raw.get("role", "") or "").strip().lower()
    if not role:
        role = "result" if point.get("result_only") else "process"
    if role == "result" and not allow_result_role:
        role = "process"

    # 模型偶尔把 2 分点也按“1 分制”返回：它自己的 full=1、got=1，
    # 说明它判的是“这一点完整”，应换算成卡里的满分；若理由里有
    # 未/缺/错/少/仅/漏等否定词，则不换算，避免把半对判成满分。
    model_full = raw.get("full")
    try:
        model_full = float(model_full) if model_full is not None else None
    except (TypeError, ValueError):
        model_full = None
    if model_full is not None and model_full > 0 \
            and abs(model_full - full) > 0.01 \
            and abs(got - model_full) <= 0.01:
        negative_words = ("未", "缺", "错", "少", "仅", "只", "漏",
                          "不完整", "不成立", "不对")
        if not any(word in reason for word in negative_words):
            got = full
            note = (f"{point.get('id')}按模型自己的满分判为完整，"
                    f"已换算为卡里的 {fmt_score(full)} 分")

    band_levels = []
    for level in point.get("levels") or []:
        try:
            band_levels.append(round(float(level.get("score", 0) or 0), 2))
        except (TypeError, ValueError, AttributeError):
            continue
    is_band = bool(point.get("band") or band_levels)

    if is_band:
        # 整问分档：只接受原标准列出的档位，或明确写出的“满分−扣分”。
        allowed_scores = set(band_levels)
        for deduction in _point_deductions(point, allowed_deductions):
            allowed_scores.add(round(max(0.0, full - float(deduction)), 2))
        if got > 0 and not any(abs(got - value) <= 0.01
                               for value in allowed_scores):
            got = 0.0
            note = f"{point.get('id')}给了原标准未列出的档位分，已按 0 分"
    else:
        checks = _point_checks(raw)
        shown_evidence = []
        invalid_check = ""
        for check in checks:
            if not check["shown"]:
                continue
            check_evidence = check["evidence"]
            if not check_evidence or not evidence_supported(
                    apply_aliases(check_evidence, alias_map),
                    normalized_transcription):
                invalid_check = check["requirement"] or "未命名核对项"
                break
            if check_evidence not in shown_evidence:
                shown_evidence.append(check_evidence)
        if shown_evidence:
            evidence = "；".join(shown_evidence) if not evidence else evidence
        if invalid_check and got > 0:
            got = 0.0
            note = f"{point.get('id')}的核对项「{invalid_check}」没有对应原文，已按 0 分"

        # 旧式逐点卡仍防“结果倒灌过程”；整问分档由档位整体判断。
        if got >= full - 1e-6 and role != "result":
            if not _point_goal_covered(point.get("text", ""), evidence, alias_map):
                got = 0.0
                note = (f"{point.get('id')}只写了结果，"
                        f"没有覆盖该点要求的关键步骤，已按 0 分")

        if 0 < got < full - 1e-6:
            deduction = round(full - got, 2)
            if deduction not in _point_deductions(point, allowed_deductions):
                got = 0.0
                note = f"{point.get('id')}给了标准未写明的部分分，已按 0 分"
    if got > 0:
        if not transcription.strip() or not evidence:
            got = 0.0
            note = f"{point.get('id')}没有引用学生原文，已按 0 分"
        elif not evidence_supported(
                apply_aliases(evidence, alias_map), normalized_transcription):
            got = 0.0
            note = f"{point.get('id')}的依据在答卷原文中找不到，已按 0 分"
    return got, evidence, reason, note


def settle_score_v2(result, card, max_score, half_point=False, score_cap=None,
                    allowed_deductions=None):
    """按 v2 评分卡逐小问、逐解法、逐点合成分数。"""
    import math
    reasons = []
    items = []
    parts = (card or {}).get("parts") or []
    transcription = str(result.get("transcription", "") or "")
    standard_aliases = dict((card or {}).get("aliases") or {})
    student_aliases = extract_aliases(transcription)

    # 模型给的别名只有在转写里找得到定义句时才采信。
    for symbol in result.get("symbol_map") or []:
        if not isinstance(symbol, dict):
            continue
        student = str(symbol.get("student") or "").strip().upper()
        standard = str(symbol.get("standard") or "").strip().upper()
        definition = str(symbol.get("definition") or "").strip()
        if not student or not standard or student in student_aliases:
            continue
        if definition and evidence_supported(definition, transcription):
            obj = standard_aliases.get(standard)
            if obj:
                student_aliases[student] = obj

    alias_map = map_student_aliases(student_aliases, standard_aliases)
    normalized_transcription = apply_aliases(transcription, alias_map)
    if alias_map:
        reasons.append("已识别学生字母别名：" + "、".join(
            f"{k}→{v}" for k, v in sorted(alias_map.items())))

    model_parts = {}
    for model_part in result.get("parts") or []:
        if isinstance(model_part, dict):
            model_parts[str(model_part.get("part_id", "")).strip()] = model_part

    total = 0.0
    uncovered = False
    for part in parts:
        part_id = str(part.get("id", "")).strip()
        try:
            part_max = float(part.get("max_score", 0) or 0)
        except (TypeError, ValueError):
            part_max = 0.0
        methods = {str(m.get("id", "")).strip(): m
                   for m in (part.get("methods") or [])}
        model_part = model_parts.get(part_id)
        if not model_part:
            reasons.append(f"第{part_id}小问没有返回判分结果，已按 0 分")
            for method in part.get("methods") or []:
                for point in method.get("points") or []:
                    items.append(_v2_item(part, method, point, 0.0, "", "未返回该小问"))
            continue

        proof_evidence = str(model_part.get("proof_evidence") or "").strip()
        part_type = str(model_part.get("part_type") or part.get("type") or "").strip()
        if (model_part.get("complete_proof") is True
                and part_type == "proof"
                and proof_evidence
                and evidence_supported(
                    apply_aliases(proof_evidence, alias_map),
                    normalized_transcription)):
            default_method = (part.get("methods") or [None])[0]
            default_points = (default_method or {}).get("points") or []
            part_total = 0.0
            for point in default_points:
                got = float(point.get("full", 0) or 0)
                part_total += got
                items.append(_v2_item(
                    part, default_method or {"id": "uncovered"},
                    point, got, proof_evidence, "完整等价证明"))
            part_total = min(part_total, part_max)
            total += part_total
            reasons.append(
                f"第{part_id}小问为完整正确证明，已按本小问"
                f" {fmt_score(part_total)} 分计")
            continue

        method_id = str(model_part.get("method_id", "")).strip()
        if method_id != "uncovered" and method_id not in methods:
            if len(methods) == 1 and not method_id:
                method_id = next(iter(methods))
            else:
                method_id = "uncovered"
        if method_id == "uncovered":
            uncovered = True
            # 未覆盖解法时，展示默认解法的点，再补上其他解法里
            # 标为共用/结果的点；不能把所有解法的点重复列一遍。
            unique_points = []
            seen_points = set()
            for method_index, method in enumerate(part.get("methods") or []):
                for point in method.get("points") or []:
                    point_id = str(point.get("id", "")).strip()
                    if point_id and point_id not in seen_points \
                            and (method_index == 0 or _is_independent_point(point)):
                        unique_points.append((method, point))
                        seen_points.add(point_id)
            model_points = {}
            for raw_point in model_part.get("points") or []:
                if isinstance(raw_point, dict):
                    model_points[str(raw_point.get("point_id", "")).strip()] = raw_point
            part_total = 0.0
            for method, point in unique_points:
                point_id = str(point.get("id", "")).strip()
                raw_point = model_points.get(point_id)
                # 共用点和结果点天然独立于具体解法；其他点必须由
                # 模型明确标出“等价方法”，再由程序做原文证据校验。
                allowed = _is_independent_point(point) or bool(
                    raw_point and (raw_point.get("equivalent") is True
                                    or _result_role_allowed(
                                        point, method, raw_point, part_type)))
                if not allowed:
                    items.append(_v2_item(part, method, point, 0.0, "", "未覆盖解法"))
                    continue
                got, evidence, reason, note = _score_point_v2(
                    point, raw_point, transcription, alias_map,
                    normalized_transcription, allowed_deductions,
                    allow_result_role=_result_role_allowed(
                        point, method, raw_point, part_type))
                if note:
                    reasons.append(note)
                part_total += got
                items.append(_v2_item(part, method, point, got, evidence, reason))
            if part_total > 0:
                reasons.append(f"第{part_id}小问用了未覆盖解法，"
                               f"按共用/结果/等价采分点计 {fmt_score(part_total)} 分")
            elif any(_is_independent_point(point) for _, point in unique_points):
                reasons.append(f"第{part_id}小问用了未覆盖解法，"
                               f"共用/结果采分点未完成，已按 0 分")
            else:
                reasons.append(f"第{part_id}小问：学生解法未覆盖评分卡中的任何一套，已按 0 分")
            total += part_total
            continue

        method = methods[method_id]
        point_map = {str(p.get("id", "")).strip(): p
                     for p in (method.get("points") or [])}
        model_points = {}
        for raw_point in model_part.get("points") or []:
            if isinstance(raw_point, dict):
                model_points[str(raw_point.get("point_id", "")).strip()] = raw_point
        if not model_points and isinstance(model_part.get("points"), list) \
                and len(model_part["points"]) == len(point_map):
            model_points = {key: value for key, value in zip(point_map, model_part["points"])
                            if isinstance(value, dict)}

        part_total = 0.0
        for point_id, point in point_map.items():
            got, evidence, reason, note = _score_point_v2(
                point, model_points.get(point_id), transcription, alias_map,
                normalized_transcription, allowed_deductions,
                allow_result_role=_result_role_allowed(
                    point, method, model_points.get(point_id), part_type))
            if note:
                reasons.append(note)
            part_total += got
            items.append(_v2_item(part, method, point, got, evidence, reason))

        if part_total > part_max + 0.01:
            reasons.append(f"第{part_id}小问逐点合计 {fmt_score(part_total)} 分，"
                           f"超过小问满分，已封顶")
            part_total = part_max
        total += part_total

    total = max(0.0, min(total, float(max_score)))
    unit = 0.5 if half_point else 1.0
    total = math.floor(total / unit + 1e-9) * unit
    if score_cap is not None:
        cap = max(0.0, min(float(score_cap), float(max_score)))
        if total > cap + 1e-9:
            reasons.append(f"按评分说明，本题最多 {fmt_score(cap)} 分"
                           f"（逐点合计 {fmt_score(total)}）")
            total = math.floor(cap / unit + 1e-9) * unit

    confidence = str(result.get("confidence", "")).strip()
    if confidence.startswith("低") or confidence.lower().startswith("low"):
        reasons.append("模型把握度低")
    if result.get("unclear") is True or "【看不清】" in transcription:
        reasons.append("有看不清的地方")
    if uncovered:
        reasons.append("有未覆盖解法，已按共用、结果和等价采分点计分")
    return fmt_score(total), items, reasons


def settle_score(result, max_score, half_point, score_cap=None, expected=None,
                 allowed_deductions=None, card=None):
    """按给分点加总得到最终分，并返回需要人工复核的原因列表"""
    import math
    import re
    if isinstance(card, dict) and card.get("parts"):
        return settle_score_v2(result, card, max_score, half_point, score_cap,
                               allowed_deductions)
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
        items.append({"point": str(it.get("point", "")), "full": full, "got": got,
                      "reason": str(it.get("reason", "") or ""),
                      "evidence": str(it.get("evidence", "") or "").strip()})

    if result.get("blank"):
        return 0, items, reasons

    # 给分点分值以评分标准为准：模型改了分值就强制回填，确保不擅自加码
    expected = [(str(p), float(v)) for p, v in (expected or [])]
    # 没有可对照的标准时，模型偶尔会把「累计分」当成各点满分（如 1/3/4 … 17 合计 92）
    if not expected and len(items) >= 3:
        vals = [it["full"] for it in items]
        if is_cumulative_scale(vals, max_score):
            prev_full = prev_got = 0.0
            for it in items:
                f, g = it["full"], it["got"]
                it["full"] = max(0.0, round(f - prev_full, 2))
                it["got"] = max(0.0, min(round(g - prev_got, 2), it["full"]))
                prev_full, prev_got = f, g
            reasons.append("模型返回的是累计分，已换算为每步增量")
    if expected and items:
        if len(items) == len(expected):
            model_cumulative = is_cumulative_scale([it["full"] for it in items], max_score)
            if model_cumulative:
                prev_got = 0.0
                for it in items:
                    g = it["got"]
                    it["got"] = max(0.0, round(g - prev_got, 2))
                    prev_got = g
                reasons.append("模型按累计分返回，已换算为每步增量并对照标准")
            for it, (_, val) in zip(items, expected):
                if abs(it["full"] - val) > 1e-9 and not model_cumulative:
                    reasons.append(f"模型改了给分点分值，已按标准回填 {fmt_score(val)} 分")
                it["full"] = val
                it["got"] = max(0.0, min(it["got"], val))
        else:
            reasons.append("模型返回的给分点条数与评分标准不一致，请复核")

    # 除了标准明确写出的“扣 N 分”，每个给分点只能是 0 或满分，禁止模型自行给部分分
    partial_items = []
    score_adjusted = False
    for item_index, it in enumerate(items):
        if it["got"] <= 0 or it["full"] <= 0:
            continue
        if it["got"] >= it["full"] - 1e-6:
            it["got"] = it["full"]
            continue
        deduction = round(it["full"] - it["got"], 2)
        if not deduction_allowed(item_index, deduction, allowed_deductions):
            reason = str(it.get("reason", "") or "")
            complete_words = ("完整", "齐全", "均正确", "全部正确", "两解均", "两解都")
            bad_words = ("漏", "缺", "未", "错", "不完整", "少")
            if it["evidence"] and any(w in reason for w in complete_words) \
                    and not any(w in reason for w in bad_words):
                it["got"] = it["full"]
                reasons.append(f"{it['point'][:12]}理由写明完整，已按满分")
                score_adjusted = True
                continue
            partial_items.append(it)
            it["got"] = 0.0
            score_adjusted = True
    if partial_items:
        names = "、".join(it["point"][:12] for it in partial_items[:3])
        more = f" 等 {len(partial_items)} 处" if len(partial_items) > 3 else ""
        reasons.append(f"{names}{more}给了标准未写明的部分分，已按 0 分")

    # 证据制：没引用学生原文的得分一律作废，杜绝“凭印象给分”
    raw_items = [it for it in (result.get("items") or []) if isinstance(it, dict)]
    has_evidence_field = any("evidence" in it for it in raw_items)
    evidence_enforced = False
    if has_evidence_field:
        no_evidence = [it for it in items if it["got"] > 0 and not it["evidence"]]
        for it in no_evidence:
            it["got"] = 0.0
        evidence_enforced = bool(no_evidence)
        if no_evidence:
            names = "、".join(it["point"][:12] for it in no_evidence[:3])
            more = f" 等 {len(no_evidence)} 处" if len(no_evidence) > 3 else ""
            reasons.append(f"{names}{more}没有引用学生原文，已按 0 分")
        transcription = str(result.get("transcription", "") or "")
        if transcription:
            unmatched = [it for it in items if it["got"] > 0
                         and not evidence_supported(it["evidence"], transcription)]
            for it in unmatched:
                it["got"] = 0.0
            if unmatched:
                names = "、".join(it["point"][:12] for it in unmatched[:3])
                more = f" 等 {len(unmatched)} 处" if len(unmatched) > 3 else ""
                reasons.append(f"{names}{more}的依据在答卷原文中找不到，已按 0 分")
                evidence_enforced = True
        else:
            positives = [it for it in items if it["got"] > 0]
            for it in positives:
                it["got"] = 0.0
            if positives:
                reasons.append("模型没有提供学生原文转写，无法校验依据，相关得分已按 0 分")
                evidence_enforced = True
    elif items:
        positives = [it for it in items if it["got"] > 0]
        for it in positives:
            it["got"] = 0.0
        if positives:
            reasons.append("模型未附学生原文依据，相关得分已按 0 分")
            evidence_enforced = True

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
        if full_sum > max_score + 0.01:
            reasons.append(f"给分点合计 {fmt_score(full_sum)} 分超过满分 {fmt_score(max_score)}，已按满分封顶；"
                           f"请核对评分标准是否写成了累计分")
        elif abs(full_sum - max_score) > 0.01:
            reasons.append(f"给分点合计 {fmt_score(full_sum)} 分≠满分")
        try:
            claimed = float(result.get("score"))
            if abs(claimed - total) > 0.01 and not evidence_enforced and not score_adjusted:
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
    total = math.floor(total / unit + 1e-9) * unit   # 向下取整到最小单位，绝不多给
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
        self.grade_times = []       # 每份的判分耗时（不含空白卷）
        self.api_times = []         # 仅模型请求耗时（不含截图、结算）
        self.cycle_times = []       # 连续批改时相邻两份的真实节奏（含提交、间隔）
        self._last_grade_start = None
        self.rubric_card = None     # 已确认的结构化评分卡
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
        self.grade_samples = 1        # 已废弃：固定单次判分（字段保留兼容旧配置）
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

        head, inner = panel(0, "参考答案", T['teal'], "含评分标准")
        head_btn(head, "清空", lambda: (self.answer_text.delete('1.0', tk.END), self._editor_changed()), False)
        head_btn(head, "粘贴", self.paste_standard_answer, False)
        head_btn(head, "截图识别", self.capture_standard_answer, True)
        self.answer_text = text_box(inner)

        head, inner = panel(1, "给分点", T['orange'], "每行：要点｜分值")
        head_btn(head, "清空", lambda: (self.rubric_text.delete('1.0', tk.END), self._editor_changed()), False)
        head_btn(head, "评分卡", self.open_rubric_card, False)
        head_btn(head, "从答案提取", self.extract_rubric_from_answer, True)
        self.rubric_text = text_box(inner)
        self.rubric_status = tk.Label(inner, text="", font=(F, 10, 'bold'), bg=T['card'], anchor='w', pady=6)
        self.rubric_status.pack(fill=tk.X)
        tk.Label(inner, text="每步增量分：求出斜率 k=2｜2分；累计分（1分、3分、4分…）会自动换算\n"
                             "不填也行：优先从参考答案里的评分标准取，再自动拆",
                 font=(F, 8), bg=T['card'], fg=T['sub'], justify=tk.LEFT, anchor='w').pack(fill=tk.X)

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
        try:
            mx_val = float(self.max_score_entry.get().strip())
        except ValueError:
            mx_val = None
        answer = self.answer_text.get('1.0', tk.END)
        rubric_text = auto_rubric_from_answer(answer, mx_val)
        found = [line for line in rubric_text.splitlines() if line.strip()]
        if not found:
            messagebox.showinfo("从答案提取", "参考答案里没找到写了分值的行（如「……（2分）」）。\n可以手动填，或者不填让 AI 自己拆。", parent=self.editor)
            return
        if self.rubric_text.get('1.0', tk.END).strip():
            if not messagebox.askyesno("从答案提取", f"找到 {len(found)} 条，要替换现有的给分点吗？", parent=self.editor):
                return
        self.rubric_text.delete('1.0', tk.END)
        self.rubric_text.insert('1.0', "\n".join(found))
        self._editor_changed()

    # ---------- 评分卡 ----------
    def _current_max_score(self):
        try:
            return float(self.max_score_entry.get().strip() or 0)
        except ValueError:
            return 0.0

    def open_rubric_card(self):
        T, F = self.THEME, self.FONT
        win = getattr(self, 'card_win', None)
        if win and win.winfo_exists():
            win.deiconify(); win.lift(); win.focus_force()
            self._card_load_working(); self._card_render()
            return
        win = tk.Toplevel(self.root)
        self.card_win = win
        win.title("评分卡 · 确认后按此判分")
        win.geometry("960x760")
        win.transient(self.root)
        win.configure(bg=T['bg'])
        win.protocol("WM_DELETE_WINDOW", win.withdraw)
        win.bind('<Escape>', lambda e: win.withdraw())

        top = tk.Frame(win, bg=T['orange'], height=44)
        top.pack(fill=tk.X); top.pack_propagate(False)
        tk.Label(top, text="评分卡", font=(F, 13, 'bold'), bg=T['orange'], fg='white').pack(side=tk.LEFT, padx=14)
        self.card_title = tk.Label(top, text="", font=(F, 10), bg=T['orange'], fg='#FFE8DE')
        self.card_title.pack(side=tk.LEFT)
        slot = tk.Frame(top, bg=T['orange'], width=112, height=28)
        slot.pack_propagate(False); slot.pack(side=tk.RIGHT, padx=10, pady=8)
        self._btn(slot, "保存并应用", self._card_save, 'white', fg=T['primary_d'],
                  active=T['tint'], bold=True).pack(fill=tk.BOTH, expand=True)

        bar = tk.Frame(win, bg=T['card'], padx=10, pady=8)
        bar.pack(fill=tk.X)

        def tb(text, cmd, primary=False):
            b = tk.Button(bar, text=text, command=cmd, font=(F, 9, 'bold' if primary else 'normal'),
                          bg=T['orange'] if primary else T['bg'], fg='white' if primary else T['text'],
                          activebackground=T['primary_d'] if primary else T['line'],
                          relief=tk.FLAT, padx=10, pady=4, cursor='hand2')
            b.pack(side=tk.LEFT, padx=(0, 6))
            return b

        tb("从标准生成", self._card_generate, True)
        tb("新增得分点", self._card_add)
        tb("新增解法", self._card_add_method)
        tb("编辑", self._card_edit)
        tb("删除", self._card_delete)
        tb("上移", lambda: self._card_move(-1))
        tb("下移", lambda: self._card_move(1))

        body = tk.Frame(win, bg=T['bg'], padx=10)
        body.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
        tree = ttk.Treeview(body, columns=("id", "text", "full", "eq"), show="headings", height=20)
        for c, txt, w, anchor in (("id", "#", 85, 'center'), ("text", "小问 / 解法 / 得分点", 520, 'w'),
                                  ("full", "分值", 60, 'center'), ("eq", "备注 / 等价写法", 230, 'w')):
            tree.heading(c, text=txt)
            tree.column(c, width=w, anchor=anchor)
        vs = ttk.Scrollbar(body, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=vs.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vs.pack(side=tk.RIGHT, fill=tk.Y)
        tree.bind('<Double-1>', lambda e: self._card_edit())
        self.card_tree = tree

        self.card_status = tk.Label(win, text="", font=(F, 10, 'bold'), bg=T['bg'], anchor='w', padx=12)
        self.card_status.pack(fill=tk.X)
        tk.Label(win, text="每个小问可有多套解法；每套解法的分值合计必须等于该小问满分。双击得分点编辑，双击解法改名。",
                 font=(F, 8), bg=T['bg'], fg=T['sub'], anchor='w', padx=12).pack(fill=tk.X, pady=(2, 8))

        self._card_load_working()
        self._card_render()
        win.lift(); win.focus_force()

    def _card_load_working(self):
        ans = self.answer_text.get('1.0', tk.END).strip()
        rubric = self.rubric_text.get('1.0', tk.END).strip()
        mx = self._current_max_score()
        card = getattr(self, 'rubric_card', None)
        if card and card_is_fresh(card, ans, rubric, mx):
            card = upgrade_rubric_card(card, mx)
            if not validate_rubric_card(card, mx):
                self.card_parts = copy.deepcopy(card.get('parts') or [])
                self._card_load_rules(card)
                return
        fresh = build_rubric_card(ans, rubric, self.question_num_entry.get().strip(), mx)
        self.card_parts = copy.deepcopy(fresh.get('parts') or []) if fresh else []
        self._card_load_rules(fresh or {})

    def _card_load_rules(self, card):
        self.card_rules = list(card.get('rules') or [])
        self.card_cumulative = bool(card.get('cumulative'))
        self.card_cumulative_raw = list(card.get('cumulative_raw') or [])
        self.card_aliases = dict(card.get('aliases') or {})
        self.card_source = card.get('source') or 'card'
        self.card_score_cap = card.get('score_cap')
        self.card_cap_text = card.get('cap_text', '')
        self.card_zero_rules = list(card.get('zero_rules') or [])
        self.card_deduction_rules = list(card.get('deduction_rules') or [])

    def _card_render(self):
        tree = getattr(self, 'card_tree', None)
        if not tree:
            return
        selected = tree.selection()
        tree.delete(*tree.get_children())
        try:
            tree.tag_configure('part', background='#FFF1E6', font=(self.FONT, 9, 'bold'))
            tree.tag_configure('method', background='#F4F7FB', font=(self.FONT, 9, 'bold'))
        except Exception:
            pass
        for part in self.card_parts:
            part_id = str(part.get('id'))
            part_iid = f"part:{part_id}"
            tree.insert('', tk.END, iid=part_iid, open=True, tags=('part',), values=(
                '', f"第{part_id}小问  {part.get('title', '')}",
                fmt_score(part.get('max_score', 0)), ''))
            for method in part.get('methods') or []:
                method_id = str(method.get('id'))
                method_iid = f"method:{part_id}:{method_id}"
                method_total = sum(float(p.get('full', 0) or 0)
                                   for p in (method.get('points') or []))
                tree.insert(part_iid, tk.END, iid=method_iid, open=True, tags=('method',), values=(
                    method_id, f"解法：{method.get('name', '')}",
                    fmt_score(method_total), method.get('notes', '')))
                for point in method.get('points') or []:
                    point_id = str(point.get('id'))
                    if point.get('result_only'):
                        point_tag = "【结果】"
                    elif point.get('shared'):
                        point_tag = "【共用】"
                    else:
                        point_tag = ""
                    point_text = point_tag + point.get('text', '')
                    tree.insert(method_iid, tk.END,
                                iid=f"point:{part_id}:{method_id}:{point_id}",
                                values=(point_id, point_text,
                                        fmt_score(point.get('full', 0)),
                                        '、'.join(point.get('equivalents') or [])))
        for iid in selected:
            if tree.exists(iid):
                tree.selection_set(iid)
                break
        mx = self._current_max_score()
        parts = len(self.card_parts)
        methods = sum(len(p.get('methods') or []) for p in self.card_parts)
        points = sum(len(m.get('points') or []) for p in self.card_parts
                     for m in (p.get('methods') or []))
        default_total = sum(float(p.get('full', 0) or 0) for p in self._card_default_points())
        bad = []
        for part in self.card_parts:
            part_max = float(part.get('max_score', 0) or 0)
            for method in part.get('methods') or []:
                method_total = sum(float(p.get('full', 0) or 0)
                                   for p in (method.get('points') or []))
                if abs(method_total - part_max) > 0.01:
                    bad.append(f"{method.get('id')}={fmt_score(method_total)}/{fmt_score(part_max)}")
        ok = bool(mx) and abs(default_total - mx) < 0.01 and not bad
        txt = (f"{parts} 小问 · {methods} 套解法 · {points} 个得分点 · "
               f"默认合计 {fmt_score(default_total)}/{fmt_score(mx)} 分")
        if bad:
            txt += "  ✗ " + "、".join(bad[:4])
        else:
            txt += "  ✓ 可用" if ok else "  ✗ 与满分不一致"
        if self.card_cumulative:
            txt += " · 累计分已换算"
        self.card_status.config(text=txt, fg=self.THEME['ok'] if ok else self.THEME['danger'])
        self.card_title.config(text=f"第 {self.question_num_entry.get().strip() or '?'} 题")

    def _card_selected(self):
        tree = getattr(self, 'card_tree', None)
        sel = tree.selection() if tree else ()
        if not sel:
            return None
        parts = str(sel[0]).split(':')
        if parts[0] == 'point' and len(parts) >= 4:
            return {'kind': 'point', 'part_id': parts[1],
                    'method_id': parts[2], 'point_id': parts[3]}
        if parts[0] == 'method' and len(parts) >= 3:
            return {'kind': 'method', 'part_id': parts[1], 'method_id': parts[2]}
        if parts[0] == 'part' and len(parts) >= 2:
            return {'kind': 'part', 'part_id': parts[1]}
        return None

    def _card_find_part(self, part_id):
        for part in self.card_parts:
            if str(part.get('id')) == str(part_id):
                return part
        return None

    def _card_find_method(self, part_id, method_id):
        part = self._card_find_part(part_id)
        if not part:
            return None
        for method in part.get('methods') or []:
            if str(method.get('id')) == str(method_id):
                return method
        return None

    def _card_find_point(self, part_id, method_id, point_id):
        method = self._card_find_method(part_id, method_id)
        if not method:
            return None
        for point in method.get('points') or []:
            if str(point.get('id')) == str(point_id):
                return point
        return None

    def _card_part_of_method(self, method):
        for part in self.card_parts:
            if any(m is method for m in (part.get('methods') or [])):
                return part
        return None

    def _card_normalize_ids(self):
        for i, part in enumerate(self.card_parts, 1):
            part['id'] = str(i)
            part['max_score'] = float(part.get('max_score', 0) or 0)
            methods = part.get('methods') or []
            for j, method in enumerate(methods):
                suffix = chr(65 + j) if j < 26 else f"M{j + 1}"
                method['id'] = f"{part['id']}-{suffix}"
                for k, point in enumerate(method.get('points') or [], 1):
                    point['id'] = f"{method['id']}-{k}"

    def _card_default_points(self):
        points = []
        for part in self.card_parts:
            methods = part.get('methods') or []
            if not methods:
                continue
            for point in methods[0].get('points') or []:
                item = copy.deepcopy(point)
                item['part_id'] = part.get('id')
                item['method_id'] = methods[0].get('id')
                points.append(item)
        return points

    def _card_generate(self):
        ans = self.answer_text.get('1.0', tk.END).strip()
        rubric = self.rubric_text.get('1.0', tk.END).strip()
        card = build_rubric_card(ans, rubric, self.question_num_entry.get().strip(),
                                 self._current_max_score())
        if not card:
            messagebox.showwarning("评分卡", "当前参考答案/给分点里没有可识别的得分点。\n"
                                             "请写成「1分：……」「要求（2分）」或「要求｜2分」。",
                                   parent=self.card_win)
            return
        self.card_parts = copy.deepcopy(card.get('parts') or [])
        self._card_load_rules(card)
        self._card_normalize_ids()
        self._card_render()
        methods = sum(len(p.get('methods') or []) for p in self.card_parts)
        self.log(f"评分卡：{len(self.card_parts)} 个小问，{methods} 套解法")

    def _card_add(self):
        selected = self._card_selected()
        method = None
        if selected and selected.get('kind') in ('point', 'method'):
            method = self._card_find_method(selected['part_id'], selected['method_id'])
        if method is None:
            for part in self.card_parts:
                methods = part.get('methods') or []
                if methods:
                    method = methods[0]
                    break
        if method is None:
            messagebox.showinfo("评分卡", "先点「从标准生成」建立评分卡。", parent=self.card_win)
            return

        def apply(point):
            method.setdefault('points', []).append(point)
            self._card_normalize_ids()
            self._card_render()
            part = self._card_part_of_method(method)
            if part and method.get('points'):
                self.card_tree.selection_set(
                    f"point:{part['id']}:{method['id']}:{method['points'][-1]['id']}")

        self._card_edit_dialog(None, apply)

    def _card_add_method(self):
        selected = self._card_selected()
        part = None
        source = None
        if selected:
            part = self._card_find_part(selected['part_id'])
            if selected.get('kind') in ('method', 'point'):
                source = self._card_find_method(selected['part_id'], selected['method_id'])
        if part is None and self.card_parts:
            part = self.card_parts[0]
        if part is None:
            messagebox.showinfo("评分卡", "先点「从标准生成」建立评分卡。", parent=self.card_win)
            return
        source = source or (part.get('methods') or [None])[0]
        if not source:
            return
        new_method = copy.deepcopy(source)
        new_method['id'] = ''
        new_method['name'] = f"解法{len(part.get('methods') or []) + 1}"
        new_method['notes'] = "请修改为本套解法的必需要素；合计必须等于小问满分"
        for point in new_method.get('points') or []:
            point['id'] = ''
        part.setdefault('methods', []).append(new_method)
        self._card_normalize_ids()
        self._card_render()
        self.card_tree.selection_set(f"method:{part['id']}:{new_method['id']}")
        messagebox.showinfo(
            "评分卡",
            "已复制一套解法。请双击修改解法名称和每个采分点；\n"
            "这套解法的分值合计必须等于该小问满分，否则不能保存。",
            parent=self.card_win)

    def _card_edit(self):
        selected = self._card_selected()
        if not selected:
            messagebox.showinfo("评分卡", "先选中一行。", parent=self.card_win)
            return
        if selected['kind'] == 'point':
            point = self._card_find_point(
                selected['part_id'], selected['method_id'], selected['point_id'])
            if point is None:
                return

            def apply(new_point):
                point.clear()
                point.update(new_point)
                self._card_normalize_ids()
                self._card_render()

            self._card_edit_dialog(point, apply)
            return
        if selected['kind'] == 'method':
            method = self._card_find_method(selected['part_id'], selected['method_id'])
            if method is None:
                return
            name = simpledialog.askstring(
                "解法名称", "这套解法的名称：", initialvalue=method.get('name', ''),
                parent=self.card_win)
            if name is not None and name.strip():
                method['name'] = name.strip()
                self._card_render()
            return
        part = self._card_find_part(selected['part_id'])
        if part is None:
            return
        title = simpledialog.askstring(
            "小问标题", "这个小问的标题：", initialvalue=part.get('title', ''),
            parent=self.card_win)
        if title is not None and title.strip():
            part['title'] = title.strip()
            self._card_render()

    def _card_delete(self):
        selected = self._card_selected()
        if not selected:
            return
        if selected['kind'] == 'point':
            method = self._card_find_method(selected['part_id'], selected['method_id'])
            point = self._card_find_point(
                selected['part_id'], selected['method_id'], selected['point_id'])
            if method and point and messagebox.askyesno(
                    "评分卡", "删除这个得分点？", parent=self.card_win):
                method['points'].remove(point)
                self._card_normalize_ids()
                self._card_render()
            return
        if selected['kind'] == 'method':
            part = self._card_find_part(selected['part_id'])
            methods = (part.get('methods') or []) if part else []
            if len(methods) <= 1:
                messagebox.showinfo("评分卡", "每个小问至少要保留一套解法。", parent=self.card_win)
                return
            method = self._card_find_method(selected['part_id'], selected['method_id'])
            if method and messagebox.askyesno(
                    "评分卡", f"删除解法「{method.get('name', '')}」及其全部得分点？",
                    parent=self.card_win):
                methods.remove(method)
                self._card_normalize_ids()
                self._card_render()
            return
        messagebox.showinfo("评分卡", "小问不能删除；可以双击修改标题。", parent=self.card_win)

    def _card_move(self, delta):
        selected = self._card_selected()
        if not selected:
            return
        if selected['kind'] == 'point':
            method = self._card_find_method(selected['part_id'], selected['method_id'])
            point = self._card_find_point(
                selected['part_id'], selected['method_id'], selected['point_id'])
            points = method.get('points') or [] if method else []
            if point not in points:
                return
            idx = points.index(point)
            j = idx + delta
            if 0 <= j < len(points):
                points[idx], points[j] = points[j], points[idx]
                self._card_normalize_ids()
                self._card_render()
                self.card_tree.selection_set(
                    f"point:{selected['part_id']}:{method['id']}:{points[j]['id']}")
            return
        if selected['kind'] == 'method':
            part = self._card_find_part(selected['part_id'])
            methods = (part.get('methods') or []) if part else []
            method = self._card_find_method(selected['part_id'], selected['method_id'])
            if method not in methods:
                return
            idx = methods.index(method)
            j = idx + delta
            if 0 <= j < len(methods):
                methods[idx], methods[j] = methods[j], methods[idx]
                self._card_normalize_ids()
                self._card_render()
                self.card_tree.selection_set(
                    f"method:{selected['part_id']}:{methods[j]['id']}")
            return
        part = self._card_find_part(selected['part_id'])
        if part not in self.card_parts:
            return
        idx = self.card_parts.index(part)
        j = idx + delta
        if 0 <= j < len(self.card_parts):
            self.card_parts[idx], self.card_parts[j] = self.card_parts[j], self.card_parts[idx]
            self._card_normalize_ids()
            self._card_render()
            self.card_tree.selection_set(f"part:{self.card_parts[j]['id']}")

    def _card_edit_dialog(self, point, on_ok):
        T, F = self.THEME, self.FONT
        p = copy.deepcopy(point) if point else {
            'id': '', 'text': '', 'goal': '', 'full': 1,
            'required': [], 'equivalents': [], 'notes': '',
            'deductions': [], 'zero_if': [], 'aliases': {},
            'shared': False, 'result_only': False,
            'band': False, 'levels': [],
        }
        dlg = tk.Toplevel(self.card_win)
        dlg.title("编辑得分点")
        dlg.geometry("620x650")
        dlg.transient(self.card_win)
        dlg.grab_set()
        box = tk.Frame(dlg, padx=14, pady=12)
        box.pack(fill=tk.BOTH, expand=True)

        tk.Label(box, text="得分点要求", font=(F, 9, 'bold'), anchor='w').pack(fill=tk.X)
        text = tk.Text(box, height=4, font=(F, 10), wrap=tk.WORD, relief=tk.FLAT,
                       highlightthickness=1, highlightbackground=T['line'])
        text.pack(fill=tk.X, pady=(2, 8))
        text.insert('1.0', p.get('text', ''))

        row = tk.Frame(box); row.pack(fill=tk.X, pady=(0, 8))
        tk.Label(row, text="分值", font=(F, 9, 'bold')).pack(side=tk.LEFT)
        full_var = tk.StringVar(value=str(fmt_score(p.get('full', 1))))
        tk.Entry(row, textvariable=full_var, width=8, justify=tk.CENTER, font=(F, 11)).pack(side=tk.LEFT, padx=8)
        tk.Label(row, text="分值必须和本小问其他得分点配平", font=(F, 9)).pack(side=tk.LEFT, padx=(10, 0))

        tk.Label(box, text="必需要素（每行一个；留空则按上面的目标整体核对）",
                 font=(F, 9, 'bold'), anchor='w').pack(fill=tk.X)
        required = tk.Text(box, height=3, font=(F, 9), wrap=tk.WORD, relief=tk.FLAT,
                           highlightthickness=1, highlightbackground=T['line'])
        required.pack(fill=tk.X, pady=(2, 8))
        required.insert('1.0', "\n".join(p.get('required') or []))

        tk.Label(box, text="等价写法（每行一个，可留空）",
                 font=(F, 9, 'bold'), anchor='w').pack(fill=tk.X)
        eq = tk.Text(box, height=3, font=(F, 9), wrap=tk.WORD, relief=tk.FLAT,
                     highlightthickness=1, highlightbackground=T['line'])
        eq.pack(fill=tk.X, pady=(2, 8))
        eq.insert('1.0', "\n".join(p.get('equivalents') or []))

        tk.Label(box, text="额外说明（可留空）", font=(F, 9, 'bold'), anchor='w').pack(fill=tk.X)
        note_var = tk.StringVar(value=str(p.get('notes', '') or ''))
        tk.Entry(box, textvariable=note_var, font=(F, 9), relief=tk.FLAT,
                 highlightthickness=1, highlightbackground=T['line']).pack(fill=tk.X, pady=(2, 10))

        shared_var = tk.BooleanVar(value=bool(p.get('shared')))
        tk.Checkbutton(
            box, text="所有解法共用这个采分点（未覆盖解法时也按此点给分）",
            variable=shared_var, font=(F, 9), bg=T['bg'], anchor='w'
        ).pack(fill=tk.X, pady=(0, 8))
        result_var = tk.BooleanVar(value=bool(p.get('result_only')))
        tk.Checkbutton(
            box, text="结果点（只核对最终结论；结果正确即可给分）",
            variable=result_var, font=(F, 9), bg=T['bg'], anchor='w'
        ).pack(fill=tk.X, pady=(0, 8))

        btns = tk.Frame(box); btns.pack(fill=tk.X)

        def ok():
            t = text.get('1.0', tk.END).strip()
            if not t:
                messagebox.showwarning("评分卡", "得分点要求不能为空。", parent=dlg)
                return
            try:
                v = float(full_var.get().strip())
            except ValueError:
                messagebox.showwarning("评分卡", "分值要填数字。", parent=dlg)
                return
            if v <= 0:
                messagebox.showwarning("评分卡", "分值必须大于 0。", parent=dlg)
                return
            required_lines = [x.strip() for x in required.get('1.0', tk.END).splitlines()
                              if x.strip()]
            new = copy.deepcopy(p)
            new.update({
                'id': p.get('id'),
                'text': t,
                'goal': t,
                'full': v,
                'required': required_lines or [t],
                'equivalents': [x.strip() for x in eq.get('1.0', tk.END).splitlines()
                                if x.strip()],
                'notes': note_var.get().strip(),
                'shared': bool(shared_var.get()),
                'result_only': bool(result_var.get()),
            })
            dlg.destroy()
            on_ok(new)

        tk.Button(btns, text="取消", command=dlg.destroy, font=(F, 9), relief=tk.FLAT,
                  bg=T['bg'], padx=12, pady=4).pack(side=tk.RIGHT)
        tk.Button(btns, text="保存", command=ok, font=(F, 9, 'bold'), relief=tk.FLAT,
                  bg=T['orange'], fg='white', padx=14, pady=4).pack(side=tk.RIGHT, padx=6)

    def _card_save(self):
        ans = self.answer_text.get('1.0', tk.END).strip()
        rubric = self.rubric_text.get('1.0', tk.END).strip()
        mx = self._current_max_score()
        self._card_normalize_ids()
        card = {
            'version': CARD_VERSION,
            'score_mode': 'bands' if bool(getattr(self, 'card_cumulative', False))
            else 'points',
            'question_num': self.question_num_entry.get().strip(),
            'max_score': mx,
            'source': getattr(self, 'card_source', 'card'),
            'cumulative': bool(getattr(self, 'card_cumulative', False)),
            'cumulative_raw': list(getattr(self, 'card_cumulative_raw', [])),
            'parts': copy.deepcopy(self.card_parts),
            'points': self._card_default_points(),
            'aliases': dict(getattr(self, 'card_aliases', {})),
            'rules': list(getattr(self, 'card_rules', [])),
            'score_cap': getattr(self, 'card_score_cap', None),
            'cap_text': getattr(self, 'card_cap_text', ''),
            'zero_rules': list(getattr(self, 'card_zero_rules', [])),
            'deduction_rules': list(getattr(self, 'card_deduction_rules', [])),
            'fingerprint': rubric_fingerprint(ans, rubric, mx),
            'updated': datetime.now().isoformat(timespec='seconds'),
        }
        issues = validate_rubric_card(card, mx)
        if issues:
            messagebox.showwarning("评分卡", "还不能应用：\n\n" + "\n".join(f"• {i}" for i in issues),
                                   parent=self.card_win)
            return
        self.rubric_card = card
        self.save_config()
        self.refresh_answer_summary()
        methods = sum(len(p.get('methods') or []) for p in card['parts'])
        points = sum(len(m.get('points') or []) for p in card['parts']
                     for m in (p.get('methods') or []))
        total = sum(float(p.get('full', 0) or 0) for p in card['points'])
        self.log(f"✓ 评分卡已启用：{len(card['parts'])} 个小问 / {methods} 套解法 / "
                 f"{points} 个得分点，默认合计 {fmt_score(total)} 分")
        messagebox.showinfo(
            "评分卡",
            f"已保存并启用：{len(card['parts'])} 个小问、{methods} 套解法。\n"
            "每套解法都已校验合计等于小问满分。",
            parent=self.card_win)

    def refresh_answer_summary(self):
        if not hasattr(self, 'answer_summary'):
            return
        T = self.THEME
        ans = self.answer_text.get('1.0', tk.END).strip()
        try:
            mx = float(self.max_score_entry.get().strip() or 0)
        except ValueError:
            mx = 0
        rubric_now = self.rubric_text.get('1.0', tk.END)
        card = getattr(self, 'rubric_card', None)
        if card and card_is_fresh(card, ans, rubric_now, mx or 0) and not validate_rubric_card(card, mx or 0):
            card = upgrade_rubric_card(card, mx or 0)
            scored = [(p["text"], float(p["full"])) for p in card_flat_points(card)]
            source, rules = "card", rules_from_card(card)
        else:
            scored, source, rules = resolve_rubric_points(rubric_now, ans, mx or None)
        total = sum(v for _, v in scored)
        line1 = f"参考答案 {len(ans)} 字" if ans else "参考答案：未填写"
        if scored:
            ok = abs(total - mx) < 0.01
            line2 = f"给分点 {len(scored)} 条 {fmt_score(total)} 分" + (" ✓" if ok else f" ≠ 满分{fmt_score(mx)}")
            if source == "auto":
                line2 += "（从答案自动拆）"
            elif source == "answer":
                line2 += "（取自参考答案标准）"
            elif source == "card":
                part_count = len(card.get("parts") or []) if isinstance(card, dict) else 0
                method_count = sum(len(p.get("methods") or [])
                                   for p in (card.get("parts") or [])) if isinstance(card, dict) else 0
                line2 += f"（评分卡：{part_count}小问/{method_count}套解法）"
        else:
            ok = True
            line2 = "给分点：未填，由 AI 拆分"
        if rules["score_cap"] is not None:
            line2 += f" · 上限{fmt_score(rules['score_cap'])}分"
        if rules.get("cumulative"):
            if isinstance(card, dict) and card.get("score_mode") == "bands":
                line2 += " · 已按原标准整问分档"
            else:
                line2 += " · 已按累计分换算"
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
        self.stats_label = tk.Label(status, text="已批 0 · 单份 0s · 接口 0s · 节奏 0s · 0/h", font=(F, 8),
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
        self.skip_confirm_var = tk.BooleanVar(value=True)
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
        self.current_analysis_label = tk.Label(self.current_result_frame, text="", font=(F, 9), bg=T['tint'],
                                               fg=T['sub'], wraplength=330, justify=tk.LEFT)
        self.current_analysis_label.pack(pady=(2, 6), padx=8)

        self.result_text = scrolledtext.ScrolledText(body, height=10, font=(F, 9), wrap=tk.WORD, relief=tk.FLAT,
                                                     bg=T['input'], fg=T['sub'], highlightthickness=1,
                                                     highlightbackground=T['line'])
        self.result_text.pack(fill=tk.BOTH, expand=True)

        # 初始提示（精简）
        self.log("快速开始：")
        self.log("1 框选答题区域  2 填题号/满分/参考答案")
        self.log("3 定位输入框和提交按钮  4 点测试验证")
        self.log("5 勾选连续+自动填分，按空格开始")
        self.log("默认跳过确认、判完直接提交；需要人工把关时可取消勾选。")
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
            self.skip_confirm_var.set(getattr(self, 'saved_skip_confirm', True))
        
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
    
    def paste_standard_answer(self):
        """把剪贴板里的文字粘贴到参考答案末尾（图片请用「截图识别」）"""
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            text = ""
        text = (text or "").strip()
        if not text:
            messagebox.showinfo("粘贴", "剪贴板里没有文字。\n如果是图片，请用「截图识别」。", parent=self.editor)
            return
        cur = self.answer_text.get('1.0', tk.END).strip()
        if cur:
            self.answer_text.insert(tk.END, "\n" + text)
        else:
            self.answer_text.insert('1.0', text)
        self.answer_text.see(tk.END)
        self._editor_changed()
        self.log(f"✓ 已粘贴参考答案 {len(text)} 字" + ("（追加）" if cur else ""))

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
        scored, _src, rules = resolve_rubric_points(
            self.rubric_text.get('1.0', tk.END), answer_text, mx)
        if scored and not self.auto_continue and mx is not None:
            total = sum(v for _, v in scored)
            if abs(total - mx) > 0.01:
                if messagebox.askyesno("给分点和满分对不上",
                                       f"给分点合计 {fmt_score(total)} 分，满分是 {fmt_score(mx)} 分。\n\n"
                                       "点「是」打开编辑窗口修改；点「否」照样批改（按现有给分点严格判分，不再逐份确认）。"):
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
            if self.auto_continue and self._last_grade_start:
                cycle = start_time - self._last_grade_start
                if 0 < cycle < 600:
                    self.cycle_times.append(cycle)
            self._last_grade_start = start_time
            
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
                card = getattr(self, 'rubric_card', None)
                if card:
                    card = upgrade_rubric_card(card, max_score_f)
                card_ok = bool(card) and card_is_fresh(card, standard_answer, rubric, max_score_f) \
                    and not validate_rubric_card(card, max_score_f)
                if card_ok:
                    expected_points = [(p["text"], float(p["full"]))
                                       for p in card_flat_points(card)]
                    rubric_source = "card"
                    rules = rules_from_card(card)
                else:
                    # 评分卡可能因为换行符、答案恢复或旧版本字段而失效。
                    # 不能直接退回扁平给分点，否则会丢掉小问/结果点/等价解法；
                    # 先按当前标准自动重建一张卡，重建失败才退回文本模式。
                    rebuilt = build_rubric_card(
                        standard_answer, rubric, question_num, max_score_f)
                    if rebuilt and not validate_rubric_card(rebuilt, max_score_f):
                        card = rebuilt
                        self.rubric_card = rebuilt
                        card_ok = True
                        rubric_source = "card"
                        rules = rules_from_card(rebuilt)
                        expected_points = [(p["text"], float(p["full"]))
                                           for p in card_flat_points(rebuilt)]
                        self.log("  🔄 评分卡已按当前标准自动重建，按小问/结果点判分")
                        self.root.after(0, self.save_config)
                        self.root.after(0, self.refresh_answer_summary)
                    else:
                        if card:
                            self.log("  ⚠ 评分卡重建失败，已按最新文本判分")
                        expected_points, rubric_source, rules = resolve_rubric_points(
                            rubric, standard_answer, max_score_f)
                source_name = {"rubric": "手填给分点", "answer": "参考答案中的评分标准",
                               "auto": "从参考答案自动拆分",
                               "card": "评分卡（已确认）"}.get(rubric_source, "")
                if expected_points:
                    self.log(f"  📋 {source_name}：{len(expected_points)} 条，合计 "
                             f"{fmt_score(sum(v for _, v in expected_points))} 分")
                if rules["cumulative"]:
                    raw = "、".join(str(fmt_score(v)) for v in rules["cumulative_raw"])
                    if card_ok and card.get("score_mode") == "bands":
                        bands = format_band_card_summary(card)
                        self.log(f"  📋 原标准累计分（{raw}），已按小问合并为 {len(expected_points)} "
                                 f"个分档评分单元：{bands}；不再拆成逐句小点")
                    else:
                        incs = " + ".join(str(fmt_score(v)) for _, v in expected_points)
                        self.log(f"  📋 标准写作累计分（{raw}），已换算为每步增量：{incs} = "
                                 f"{fmt_score(sum(v for _, v in expected_points))} 分")
                if rules["score_cap"] is not None:
                    self.log(f"  📏 评分规则：本题最多 {fmt_score(rules['score_cap'])} 分（程序强制）"
                             f"（{rules['cap_text'][:50]}）")
                if rules["zero_rules"]:
                    self.log(f"  📏 零分规则 {len(rules['zero_rules'])} 条（请人工复核对应步骤）")
                prompt = build_grading_prompt(question_num, max_score, standard_answer, rubric,
                                              self.half_point, card if card_ok else None)
                # 单次判分：严格按评分标准只判一次，不做多次采样
                api_elapsed = 0.0
                try:
                    api_start = time.time()
                    result = self.call_ai_api(prompt, grade_img, need_json=True)
                    api_elapsed += time.time() - api_start
                except Exception as e:
                    api_elapsed += time.time() - api_start
                    msg = str(e)
                    if any(k in msg for k in ("Expecting", "delimiter", "JSON", "control character",
                                              "Unterminated", "Invalid")):
                        self.log(f"  ⚠ 模型返回的 JSON 不完整（{msg[:60]}），重试一次…")
                        api_start = time.time()
                        result = self.call_ai_api(
                            prompt + "\n\n严格要求：只输出一个 JSON 对象；transcription 和 evidence 都写成一行，"
                                     "不要换行，不要出现英文双引号（需要引用时用「」）；不要输出任何解释。",
                            grade_img, need_json=True)
                        api_elapsed += time.time() - api_start
                    else:
                        raise
                if card_ok and card.get("parts"):
                    missing_parts = missing_card_parts(result, card)
                    if missing_parts:
                        self.log(f"  ⚠ 模型缺少第{'、'.join(missing_parts)}小问，重试一次…")
                        try:
                            api_start = time.time()
                            retry_result = self.call_ai_api(
                                prompt + "\n\n严格要求：上一次返回缺少第"
                                         + "、".join(missing_parts) + "小问。"
                                         "必须为评分卡里的每一个小问各返回一个 parts 对象，"
                                         "part_id 分别为 "
                                         + "、".join(str(p.get("id")) for p in card.get("parts") or [])
                                         + "；没有覆盖的也要返回 method_id=uncovered 和 points=[]，"
                                           "共用点仍按【共用】规则返回。"
                                           "不能只返回有分的小问，不能合并小问。",
                                grade_img, need_json=True)
                            api_elapsed += time.time() - api_start
                            result = merge_grading_results(result, retry_result, card)
                        except Exception as retry_error:
                            api_elapsed += time.time() - api_start
                            self.log(f"  ⚠ 多解法格式重试失败：{str(retry_error)[:80]}")
                if result.get('_salvaged'):
                    self.log("  ⚠ 模型 JSON 有残缺，已尽力抢救出给分点，建议核对原文")
                score, items, reasons = settle_score(result, max_score_f, self.half_point,
                                                     rules["score_cap"], expected_points,
                                                     rules.get("deduction_rules"),
                                                     card=card if card_ok else None)
                if card_ok and card.get("parts"):
                    still_missing = missing_card_parts(result, card)
                    if still_missing:
                        reasons.append(
                            f"模型没有返回第{'、'.join(still_missing)}小问，"
                            f"相关分数按 0 分，建议重新批改")
                self.log(f"  🧪 判分结果：{fmt_score(score)} 分")
                result['score'] = score
                result['items'] = items
                save_result_debug(result, card if card_ok else None, score)
                if ink > 0.90:
                    reasons.append(f"截图墨迹占比很高（{ink:.2f}），请确认不是黑屏/遮挡")

            result['_reasons'] = (reasons or []) + extra_reasons
            result['_ink'] = round(ink, 4)
            result['_color'] = round(color, 3)

            elapsed = time.time() - start_time
            self.grading_count += 1
            self.total_time += elapsed
            if not result.get('blank'):
                self.grade_times.append(elapsed)
                if api_elapsed:
                    self.api_times.append(api_elapsed)

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
        part_scores = {}
        uncovered_parts = set()
        for item in items:
            part_id = str(item.get("part_id") or "").strip()
            if not part_id:
                continue
            part_scores.setdefault(part_id, [0.0, 0.0])
            part_scores[part_id][0] += float(item.get("got", 0) or 0)
            part_scores[part_id][1] += float(item.get("full", 0) or 0)
            if "未覆盖" in str(item.get("reason", "") or ""):
                uncovered_parts.add(part_id)
        if part_scores:
            parts_text = []
            for part_id in sorted(part_scores, key=lambda x: (len(x), x)):
                got, full = part_scores[part_id]
                label = f"第{part_id}问 {fmt_score(got)}/{fmt_score(full)}"
                if part_id in uncovered_parts:
                    label += "【未覆盖解法】"
                parts_text.append(label)
            detail_text += "分问得分: " + " · ".join(parts_text) + "\n"

        # 结果卡上直接列出每个给分点的得分，按小问分组。
        point_score_lines = []
        grouped = []
        group_index = {}
        for item in items:
            part_id = str(item.get("part_id") or "").strip() or "本题"
            if part_id not in group_index:
                group_index[part_id] = len(grouped)
                grouped.append((part_id, []))
            grouped[group_index[part_id]][1].append(item)
        marks = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
        for part_id, part_items in grouped:
            got_sum = sum(float(it.get("got", 0) or 0) for it in part_items)
            full_sum = sum(float(it.get("full", 0) or 0) for it in part_items)
            label = f"第{part_id}问" if part_id != "本题" else "本题"
            pieces = []
            for index, item in enumerate(part_items, 1):
                mark = marks[index - 1] if index <= len(marks) else f"{index}."
                pieces.append(
                    f"{mark}{fmt_score(item.get('got', 0))}/"
                    f"{fmt_score(item.get('full', 0))}")
            point_score_lines.append(
                f"{label} {fmt_score(got_sum)}/{fmt_score(full_sum)}："
                + " · ".join(pieces))
        point_score_text = "\n".join(point_score_lines)

        transcription = str(result.get("transcription", "") or "").strip()
        if transcription:
            shown = transcription if len(transcription) <= 600 else transcription[:600] + "…"
            detail_text += f"\n学生原文: {shown}\n"
        if items:
            detail_text += "\n给分点:\n"
            for it in items:
                got, full = it.get('got', 0), it.get('full', 0)
                reason = str(it.get('reason', '') or '').strip()
                detail_text += f"  • {it.get('point', '')}  {fmt_score(got)}/{fmt_score(full)}"
                if reason:
                    detail_text += f"  {reason}"
                detail_text += "\n"
                ev = str(it.get('evidence', '') or '').strip()
                if ev and float(got) > 0:
                    ev_show = ev if len(ev) <= 60 else ev[:60] + "…"
                    detail_text += f"      ↳ {ev_show}\n"
        elif deductions:
            detail_text += "\n扣分详情:\n"
            for d in deductions:
                if isinstance(d, dict):
                    detail_text += f"  • {d.get('point', '未命名扣分点')}: -{d.get('deduction', 0)}分\n"
        if reasons:
            detail_text += "\n提示:\n" + "\n".join(f"  • {r}" for r in reasons)

        analysis_text = f"评语: {analysis}" if str(analysis or "").strip() else "评语:"
        if point_score_text:
            analysis_text += "\n" + point_score_text
        self.current_analysis_label.config(text=analysis_text)
        self.log(detail_text)

        self.log(f"  得分: {score}/{max_score} 用时: {elapsed:.1f}s ({model_name})")
        self.log(f"\n💡 建议分数: {score} 分")

        self.update_stats()
        avg_time = self.avg_grade_time()
        self._record = (result, max_score, model_name, elapsed, avg_time)

        self.waiting_for_confirm = True
        self.pending_score = score
        self._raise_window()
        self.show_confirm_dialog(score, max_score, detail_text)

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
            if need_json:
                gen_cfg["responseSchema"] = GRADING_SCHEMA
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
        """解析模型返回的 JSON：容忍代码块、尾逗号、LaTeX 反斜杠、字符串内换行。"""
        import re
        original = (text or "").strip()
        raw = original
        m = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
        if m:
            raw = m.group(1).strip()
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end > start:
            raw = raw[start:end + 1]

        attempts = [raw]
        if raw != original:
            attempts.append(original)
        no_trailing = re.sub(r",\s*([}\]])", r"\1", raw)
        if no_trailing != raw:
            attempts.append(no_trailing)
        closed = close_truncated_json(raw)
        if closed != raw:
            attempts.append(closed)
        for base in list(attempts):
            latex_fixed = repair_json_latex(base)
            if latex_fixed != base:
                attempts.append(latex_fixed)
            fixed = re.sub(r'\\(?![/bfnrtu"\\])', r'\\\\', base)
            if fixed != base:
                attempts.append(fixed)

        last_err = None
        for cand in attempts:
            for strict in (True, False):
                try:
                    return json.loads(cand, strict=strict)
                except json.JSONDecodeError as e:
                    last_err = e

        # 最后兜底：按字段抢救出 items / score，避免整份卷子直接失败
        salvaged = self.salvage_json_result(original or raw)
        if salvaged and (salvaged.get("items") or salvaged.get("parts")):
            salvaged["_salvaged"] = True
            return salvaged
        raise ValueError(f"模型返回内容不是合法 JSON：{last_err}")

    def salvage_json_result(self, raw):
        """JSON 残缺时用正则捞出关键字段。"""
        import re
        out = {}
        m = re.search(r'"score"\s*:\s*(-?[0-9]+(?:\.[0-9]+)?)', raw)
        if m:
            out["score"] = float(m.group(1))
        m = re.search(r'"transcription"\s*:\s*"(.*?)"\s*,\s*"(?:items|parts)"', raw, re.S)
        if m:
            out["transcription"] = m.group(1).replace("\\n", "\n")
        items = []
        m = re.search(r'"items"\s*:\s*\[(.*)', raw, re.S)
        if m:
            for obj in re.finditer(r"\{[^{}]*\}", m.group(1), re.S):
                body = obj.group(0)
                try:
                    items.append(json.loads(repair_json_latex(body), strict=False))
                    continue
                except Exception:
                    pass
                item = {}
                for key in ("point", "evidence", "reason"):
                    mm = re.search(rf'"{key}"\s*:\s*"(.*?)"\s*(?:,\s*"[a-z_]+"\s*:|}})', body, re.S)
                    if mm:
                        item[key] = mm.group(1).replace("\\n", "\n")
                for key in ("full", "got"):
                    mm = re.search(rf'"{key}"\s*:\s*(-?[0-9]+(?:\.[0-9]+)?)', body)
                    if mm:
                        item[key] = float(mm.group(1))
                if "point" in item:
                    items.append(item)
        if items:
            out["items"] = items
        parts = []
        m = re.search(r'"parts"\s*:\s*\[(.*)', raw, re.S)
        if m:
            for body in iter_balanced_json_objects(m.group(1)):
                if '"part_id"' not in body:
                    continue
                try:
                    part = json.loads(repair_json_latex(body), strict=False)
                except Exception:
                    continue
                if isinstance(part, dict) and part.get("part_id"):
                    parts.append(part)
        if parts:
            out["parts"] = parts
        for key in ("confidence", "analysis"):
            mm = re.search(rf'"{key}"\s*:\s*"(.*?)"', raw, re.S)
            if mm:
                out[key] = mm.group(1)
        return out

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
        self._last_grade_start = None   # 重新开始计节奏，避免把停顿时长算进去
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
        self._last_grade_start = None
        
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
        self._last_grade_start = None
        self._raise_window()
        self.auto_var.set(False)
        self.pause_btn.config(state=tk.DISABLED, text="⏸ 暂停", bg=self.THEME['slate'])
        self.grade_btn.config(state=tk.NORMAL, text=self.GRADE_TEXT)
        self.log("\n⏹ 批改已停止")
    
    def update_stats(self):
        """更新统计：单份含截图与结算，接口只算模型请求，节奏含提交与间隔。"""
        single_avg = self.avg_grade_time()
        api_avg = self.avg_api_time()
        cyc_avg = sum(self.cycle_times) / len(self.cycle_times) if self.cycle_times else 0
        pace = cyc_avg or single_avg
        eff = int(3600 / pace) if pace > 0 else 0
        parts = [f"已批 {self.grading_count}"]
        if single_avg:
            parts.append(f"单份 {single_avg:.1f}s")
        if api_avg:
            parts.append(f"接口 {api_avg:.1f}s")
        if cyc_avg:
            parts.append(f"节奏 {cyc_avg:.1f}s")
        if eff:
            parts.append(f"{eff}/h")
        self.stats_label.config(text=" · ".join(parts))

    def avg_grade_time(self):
        """单份平均处理耗时（截图 + 模型 + 结算，不含空白卷）。"""
        return sum(self.grade_times) / len(self.grade_times) if self.grade_times else 0

    def avg_api_time(self):
        """模型接口的平均耗时（不含截图、提交和结算）。"""
        return sum(self.api_times) / len(self.api_times) if self.api_times else 0
    
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
                'rubric_card': getattr(self, 'rubric_card', None),
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
                self.rubric_card = config.get('rubric_card') or None
                if self.rubric_card:
                    try:
                        saved_mx = float(self.saved_max_score)
                    except (TypeError, ValueError):
                        saved_mx = None
                    self.rubric_card = upgrade_rubric_card(
                        self.rubric_card, saved_mx)
                self.half_point = bool(config.get('half_point', False))
                self.blank_threshold = float(config.get('blank_threshold', 0.0015))
                self.grade_samples = int(config.get('grade_samples', 0) or 0)
                self.keep_topmost = bool(config.get('keep_topmost', True))
                
                # 加载复选框状态
                self.saved_auto_continue = config.get('auto_continue', False)
                self.saved_auto_click = config.get('auto_click', False)
                self.saved_skip_confirm = True   # 固定跳过确认：不再逐份人工复核
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
            self.saved_skip_confirm = True
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
                    ev = str(it.get('evidence', '') or '').strip()
                    if ev and float(it.get('got', 0) or 0) > 0:
                        content += f"        - 依据：{ev}\n"
            elif deductions:
                content += "- **扣分详情**:\n"
                for d in deductions:
                    content += f"    - {d['point']}: -{d['deduction']}\n"

            reasons = result.get('_reasons') or []
            if reasons:
                content += "- **提示**: " + "；".join(str(r) for r in reasons) + "\n"
            
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
                card_html += "<div class='review'>⚠ 提示：" + escape("；".join(str(r) for r in reasons)) + "</div>"
            
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
