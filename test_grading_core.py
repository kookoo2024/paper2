# -*- coding: utf-8 -*-
"""判分核心的离线测试（不调用模型）。用法：python test_grading_core.py"""

import json
import sys
import types
from pathlib import Path
from unittest import mock

# 没有图形界面的环境里也能导入主程序
for name in ("tkinter", "tkinter.ttk", "tkinter.messagebox", "tkinter.scrolledtext",
             "tkinter.simpledialog", "pyautogui"):
    sys.modules.setdefault(name, mock.MagicMock())
try:
    import PIL.ImageTk  # noqa: F401
except Exception:
    sys.modules["PIL.ImageTk"] = types.ModuleType("PIL.ImageTk")

import grading_core as gc
import zhixue_simple as z

BASE = Path(__file__).resolve().parent
FUNC = json.loads((BASE / "eval_cases/function-derivative/expected.json").read_text("utf-8"))["rubric"]

GEOM_ANSWER = """（1）证明：取PD中点N，连接MN、AN……所以BM∥平面PAD。
（2）建立空间直角坐标系……二面角的余弦值为 √6/3。"""
GEOM_RUBRIC = """（1）取PD中点N，证明四边形ABMN为平行四边形（3分）
得 BM∥AN（1分）
由线面平行判定定理得 BM∥平面PAD（2分）
（2）建系并写出点坐标（2分）
求出两个平面的法向量（4分）
求得余弦值 √6/3（2分）"""

PROBA_RUBRIC = """（1）写出X的所有可能取值0,1,2,3（1分）
求出各概率（3分）
列出分布列（1分）
（2）E(X)=3/2（2分）"""

failures = []


def check(name, cond, detail=""):
    print(("✓ " if cond else "✗ ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def full_result(card, scale=1.0):
    parts = []
    for part in card["parts"]:
        m = part["methods"][0]
        parts.append({"part_id": part["id"], "method_id": m["id"],
                      "points": [{"point_id": p["id"], "got": p["full"] * scale, "reason": ""}
                                 for p in m["points"]]})
    return {"reading": "", "parts": parts, "confidence": "高", "unclear": False, "analysis": ""}


def card_for(answer, rubric, mx):
    card = z.build_rubric_card(answer, rubric, "1", mx)
    if not card or z.validate_rubric_card(card, mx):
        pts, _s, _r = z.resolve_rubric_points(rubric, answer, mx)
        card = gc.single_part_card(pts, mx)
    return card


HARDCODED = ("PD", "BQ", "MN", "法向量", "平行四边形", "(2,-2,4)", "中点H")

for label, answer, rubric, mx in [("函数题（累计分）", "", FUNC, 10),
                                  ("立体几何题", GEOM_ANSWER, GEOM_RUBRIC, 14),
                                  ("概率题", "", PROBA_RUBRIC, 7)]:
    card = card_for(answer, rubric, mx)
    check(f"{label}：评分卡可用", not z.validate_rubric_card(card, mx),
          str(z.validate_rubric_card(card, mx)))
    prompt = gc.build_prompt("1", mx, answer or "略", card)
    own = answer + rubric
    leaked = [w for w in HARDCODED if w in prompt and w not in own]
    check(f"{label}：提示词里没有别的题目的字样", not leaked, str(leaked))
    check(f"{label}：提示词长度适中（{len(prompt)} 字）", len(prompt) < 3000)
    s, items, reasons, review = gc.settle(full_result(card), card, mx)
    check(f"{label}：模型全对 → 满分", s == mx and not review, f"{s} {reasons}")
    s, items, reasons, review = gc.settle(full_result(card, 0), card, mx)
    check(f"{label}：模型全错 → 0 分", s == 0 and not review, f"{s}")

# 模型给了分，程序不能因为别的字段没填就改成 0
card = card_for(GEOM_ANSWER, GEOM_RUBRIC, 14)
res = full_result(card)
for p in res["parts"]:
    for pt in p["points"]:
        pt.pop("reason")
s, _, _, review = gc.settle(res, card, 14)
check("没有 reason 也照常给分", s == 14 and not review, str(s))

# 缺一问：照算其它问，标记复核
res = full_result(card)
res["parts"] = res["parts"][:1]
s, _, reasons, review = gc.settle(res, card, 14)
first = card["parts"][0]["max_score"]
check("缺一问：其它问照算并要求复核", s == first and review, f"{s} {reasons}")

# 解法编号写错：按采分点编号找回，并提示
res = full_result(card)
res["parts"][0]["method_id"] = "A"
s, _, reasons, review = gc.settle(res, card, 14)
check("解法编号写错：分数照算并提示", s == 14 and review, f"{s} {reasons}")

# 小问编号写成（1）（2）也能对上
res = full_result(card)
for i, p in enumerate(res["parts"], 1):
    p["part_id"] = f"（{i}）"
s, _, _, _ = gc.settle(res, card, 14)
check("小问编号格式不同也能对上", s == 14, str(s))

# 四舍五入而不是向下取整
one = gc.single_part_card([("a", 3), ("b", 3)], 6)
res = {"parts": [{"part_id": "1", "method_id": "1-A",
                  "points": [{"point_id": "1-A-1", "got": 1.5}, {"point_id": "1-A-2", "got": 3}]}]}
s, _, _, _ = gc.settle(res, one, 6, half_point=True)
check("半分制保留 0.5", s == 4.5, str(s))
s, _, _, _ = gc.settle(res, one, 6, half_point=False)
check("整分制 1.5 → 2（四舍五入）", s == 5, str(s))

# 超过满分要限幅
res["parts"][0]["points"][1]["got"] = 9
s, _, _, _ = gc.settle(res, one, 6, half_point=True)
check("单点超满分被限到满分", s == 4.5, str(s))

# 分档点：不在档位里取最近档
band = {"parts": [{"id": "1", "title": "", "max_score": 6, "methods": [{"id": "1-A", "name": "",
         "points": [{"id": "1-A-1", "text": "", "full": 6, "band": True,
                     "levels": [{"score": 2, "text": ""}, {"score": 4, "text": ""}, {"score": 6, "text": ""}]}]}]}]}
for got, want in [(4, 4), (3.9, 4), (5, 4), (1, 0), (0, 0), (6, 6)]:
    r = {"parts": [{"part_id": "1", "method_id": "1-A", "points": [{"point_id": "1-A-1", "got": got}]}]}
    s, _, _, _ = gc.settle(r, band, 6)
    check(f"分档：模型给 {got} → {want}", s == want, str(s))

# 评分说明里的封顶
capped = dict(one, score_cap=4)
r = {"parts": [{"part_id": "1", "method_id": "1-A",
                "points": [{"point_id": "1-A-1", "got": 3}, {"point_id": "1-A-2", "got": 3}]}]}
s, _, reasons, _ = gc.settle(r, capped, 6)
check("评分说明封顶", s == 4, f"{s} {reasons}")

# 模型返回乱七八糟时不崩溃
for junk in (None, {}, {"parts": "x"}, {"parts": [None, 3]}):
    try:
        s, _, _, review = gc.settle(junk, card, 14)
        check(f"异常返回 {str(junk)[:12]} 不崩溃并要求复核", s == 0 and review)
    except Exception as e:
        check(f"异常返回 {junk} 不崩溃", False, repr(e))

print()
print("全部通过" if not failures else f"{len(failures)} 项失败")
sys.exit(1 if failures else 0)
