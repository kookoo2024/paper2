# -*- coding: utf-8 -*-
"""原卷存档：批改时把每份原始答卷和当时的评分规范存在本机，供离线批改测试用。

目录结构（全部在程序目录下的 paper_archive/，不入库）：
    paper_archive/
      20261117_q18/              一天一题一个文件夹
        spec_ab12cd34ef.json     当时的评分规范（题号、满分、参考答案、给分点、原题、指南、评分卡）
        0001.png                 原始答卷截图
        0001.json                这份卷子的记录：程序分、最终分、状态、用的哪一版规范
      我的试卷/                  老师自己放进来的卷子：只放图片也行

状态 status：
    auto      跳过确认，程序分直接提交（没人看过，不当标准分）
    reviewed  老师确认过，没改分
    changed   老师改过分
    manual    老师在离线测试里手动填的标准分
    skipped   老师点了跳过，没有提交分数
    pending   还没出结果（程序中途关掉）
本文件不依赖 tkinter，方便测试和 eval.py 复用。"""

import hashlib
import json
import os
import re
from datetime import datetime

ARCHIVE_DIRNAME = "paper_archive"
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
SPEC_KEYS = ("question_num", "max_score", "half_point", "answer", "rubric", "question", "guide")
REVIEWED = ("reviewed", "changed", "manual")
STATUS_TEXT = {
    "auto": "未复核", "reviewed": "已复核", "changed": "老师改分", "manual": "手填",
    "skipped": "跳过", "pending": "未完成", None: "无标准分",
}


def archive_root(app_dir):
    return os.path.join(app_dir, ARCHIVE_DIRNAME)


def _read_json(path):
    with open(path, "r", encoding="utf-8") as fp:
        return json.load(fp)


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _safe(text):
    text = re.sub(r'[\\/:*?"<>|\s]+', "_", str(text or "").strip())
    return text or "x"


def spec_fingerprint(spec):
    """规范的指纹：文字内容 + 评分卡的给分点，一样就算同一版。"""
    data = {k: spec.get(k) for k in SPEC_KEYS}
    card = spec.get("card") or {}
    data["parts"] = card.get("parts") if isinstance(card, dict) else None
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]


def batch_dir(root, question_num, day=None):
    day = day or datetime.now()
    return os.path.join(root, f"{day:%Y%m%d}_q{_safe(question_num)}")


def save_spec(bdir, spec):
    """同一版规范只存一次，返回它的编号。"""
    os.makedirs(bdir, exist_ok=True)
    sid = spec_fingerprint(spec)
    path = os.path.join(bdir, f"spec_{sid}.json")
    if not os.path.exists(path):
        data = {k: spec.get(k) for k in SPEC_KEYS}
        data["card"] = spec.get("card")
        data["created"] = datetime.now().isoformat(timespec="seconds")
        _write_json(path, data)
    return sid


def load_specs(bdir):
    specs = {}
    if not os.path.isdir(bdir):
        return specs
    for name in os.listdir(bdir):
        m = re.fullmatch(r"spec_([0-9a-f]+)\.json", name)
        if m:
            try:
                specs[m.group(1)] = _read_json(os.path.join(bdir, name))
            except Exception:
                pass
    return specs


def _images(bdir):
    if not os.path.isdir(bdir):
        return []
    return sorted(n for n in os.listdir(bdir)
                  if os.path.splitext(n)[1].lower() in IMAGE_SUFFIXES
                  and os.path.isfile(os.path.join(bdir, n)))


def next_name(bdir):
    nums = [int(os.path.splitext(n)[0]) for n in _images(bdir) if os.path.splitext(n)[0].isdigit()]
    return f"{(max(nums) + 1) if nums else 1:04d}"


def save_paper(bdir, image, record):
    """存一份原卷（PIL 图片）和它的记录，返回编号（不带扩展名）。"""
    os.makedirs(bdir, exist_ok=True)
    name = next_name(bdir)
    image.save(os.path.join(bdir, name + ".png"))
    data = dict(record or {})
    data.setdefault("status", "pending")
    data.setdefault("created", datetime.now().isoformat(timespec="seconds"))
    _write_json(os.path.join(bdir, name + ".json"), data)
    return name


def update_paper(bdir, name, **fields):
    path = os.path.join(bdir, name + ".json")
    data = {}
    if os.path.exists(path):
        try:
            data = _read_json(path)
        except Exception:
            data = {}
    data.update(fields)
    data["updated"] = datetime.now().isoformat(timespec="seconds")
    _write_json(path, data)
    return data


def list_papers(bdir):
    """[{name, image, record}]；老师自己放的图片没有记录时 record 为 {}。"""
    out = []
    for img in _images(bdir):
        stem = os.path.splitext(img)[0]
        rec = {}
        jp = os.path.join(bdir, stem + ".json")
        if os.path.exists(jp):
            try:
                rec = _read_json(jp)
            except Exception:
                rec = {}
        out.append({"name": stem, "image": os.path.join(bdir, img), "record": rec})
    return out


def reference(record):
    """标准分：(分数, 状态)。只有老师看过的才算标准分；未复核的另算。"""
    st = (record or {}).get("status")
    final = (record or {}).get("final_score")
    if st in REVIEWED and final is not None:
        return float(final), st
    if st == "auto" and final is not None:
        return float(final), st
    return None, st


def list_batches(root):
    out = []
    if not os.path.isdir(root):
        return out
    for name in sorted(os.listdir(root), reverse=True):
        bdir = os.path.join(root, name)
        if not os.path.isdir(bdir):
            continue
        papers = list_papers(bdir)
        reviewed = sum(1 for p in papers if reference(p["record"])[1] in REVIEWED)
        out.append({"name": name, "path": bdir, "count": len(papers), "reviewed": reviewed,
                    "specs": len(load_specs(bdir))})
    return out


def summarize(diffs):
    """diffs：重批分 - 标准分 的列表。返回 None 或统计字典。"""
    diffs = [float(d) for d in diffs]
    n = len(diffs)
    if not n:
        return None
    return {
        "n": n,
        "exact": sum(1 for d in diffs if abs(d) < 0.01),
        "within1": sum(1 for d in diffs if abs(d) <= 1.01),
        "bias": sum(diffs) / n,
        "mae": sum(abs(d) for d in diffs) / n,
    }


def summary_text(stats, label):
    if not stats:
        return f"{label}：没有可比的卷子"
    n = stats["n"]
    return (f"{label} {n} 份：完全一致 {stats['exact']}（{stats['exact'] / n:.0%}），"
            f"±1 分内 {stats['within1']}（{stats['within1'] / n:.0%}），"
            f"平均差 {stats['mae']:.2f}，整体{'偏高' if stats['bias'] > 0.005 else '偏低' if stats['bias'] < -0.005 else '不偏'}"
            f" {stats['bias']:+.2f}")
