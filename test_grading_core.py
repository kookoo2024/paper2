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

# ---- v1.12 统一格式 / 批改指南 ----
orig = "（1）求得 k=2 （2分）\n所以直线方程 y=2x+1（2分）\n（2）联立得 x^2-4x+3=0（3分）\n评分说明：最多得 7 分"
norm = "（1）求得 $k=2$（2分）\n所以直线方程 $y=2x+1$（2分）\n（2）联立得 $x^2-4x+3=0$（3分）\n评分说明：\n最多得 7 分"
ok, msg = gc.check_scores_kept(orig, norm)
check("整理前后分值一致", ok, msg)
ok, msg = gc.check_scores_kept(orig, norm.replace("（3分）", "（2分）"))
check("分值被改能查出来", (not ok) and "少了 3分" in msg and "多了 2分" in msg, msg)
ok, msg = gc.check_scores_kept(orig, norm.replace("\n（2）联立得 $x^2-4x+3=0$（3分）", ""))
check("步骤被删能查出来", not ok, msg)
check("“充分”“部分”“分析”不算分值", gc.score_numbers("充分性 部分 分析 2分析 3 分") == [3.0])
a2, g2 = gc.parse_guide_output("```\n===参考答案===\nAAA\n=== 批改指南 ===\nGGG\n```")
check("解析指南输出（带代码块）", a2 == "AAA" and g2 == "GGG", repr((a2, g2)))
check("只有指南也能解析", gc.parse_guide_output("===批改指南===\nG") == ("", "G"))
check("没按格式返回 → 两段都空", gc.parse_guide_output("随便说点") == ("", ""))
check("指南出现新分值能查出来", gc.guide_new_scores("必须看到 k，给 1分", [orig], 7) == [1.0])
check("指南引用原有分值不报", gc.guide_new_scores("这一步 2分", [orig], 7) == [])
gp = gc.build_guide_prompt("18", 12, "已知…", orig, "")
check("指南提示词包含统一格式和两段标记", "===参考答案===" in gp and "===批改指南===" in gp and "$...$" in gp)
c1 = gc.single_part_card([("整题", 7)], 7)
p0 = gc.build_prompt("3", 7, orig, c1)
p1 = gc.build_prompt("3", 7, orig, c1, question_text="题目原文QQ", guide="指南GG")
check("没有指南时提示词不出现指南段", "【批改指南" not in p0 and "【原题】" not in p0)
check("有指南时带原题和指南", "题目原文QQ" in p1 and "指南GG" in p1)
check("识别提示词要求 LaTeX", "LaTeX" in gc.capture_prompt("answer") and "不要解答" in gc.capture_prompt("question"))

# ---- v1.13 给分点格式 / 材料箱 ----
pt = """（1）满分 6 分
解法一：设点法
求得 $k=2$｜2
写出直线方程 $y=2x+1$｜4
解法二：参数法
设参数并联立｜3（AI拟分）
得出结论｜3 (AI拟分)
（2）满分 6 分
联立得 $x^2-4x+3=0$｜6
评分说明：
最多得 11 分"""
c, iss, ai = gc.card_from_points_text(pt, 12)
check("新格式解析：2 问，第 1 问 2 套解法", not iss and len(c["parts"]) == 2 and len(c["parts"][0]["methods"]) == 2, str(iss))
check("AI 拟分的行能找出来", len(ai) == 2)
check("评分说明里的封顶", c["score_cap"] == 11)
check("去掉 AI 拟分标记", "AI" not in gc.strip_ai_marks(pt))
_, iss2, _ = gc.card_from_points_text(pt.replace("｜4", "｜3"), 12)
check("解法合计≠小问满分能查出来", any("合计" in x for x in iss2), str(iss2))
_, iss3, _ = gc.card_from_points_text(pt.replace("（2）满分 6 分", "（2）满分 5 分").replace("｜6", "｜5"), 12)
check("各问合计≠本题满分能查出来", any("本题满分" in x for x in iss3), str(iss3))
_, iss4, _ = gc.card_from_points_text("（1）满分 2 分\n乱写一行\nx｜2", 2)
check("看不懂的行会报出来", any("看不懂" in x for x in iss4), str(iss4))
check("旧写法不算新格式", not gc.is_points_text("求得 k=2｜2\n直线方程｜4"))
check("全题写法", not gc.card_from_points_text("全题 满分 5 分\na｜2\nb｜3", 5)[1])
r = {"parts": [{"part_id": "1", "method_id": "1-B", "points": [{"point_id": "1-B-1", "got": 3}, {"point_id": "1-B-2", "got": 0}]},
               {"part_id": "2", "method_id": "2-A", "points": [{"point_id": "2-A-1", "got": 6}]}]}
s13, _, _, rv = gc.settle(r, c, 12)
check("按解法二判分并加总", s13 == 9 and not rv, f"{s13} {rv}")
p13 = gc.build_prompt("18", 12, "ans", c)
check("提示词里列出两套解法", "1-B" in p13 and "设参数并联立" in p13)
sec = gc.parse_sections("```\n===原题===\nQ\n===参考答案===\nA\n===给分点===\nP\n===批改指南===\nG\n```")
check("四段输出解析", sec == {"原题": "Q", "参考答案": "A", "给分点": "P", "批改指南": "G"}, str(sec))
mp = gc.build_materials_prompt("18", 12, "老师的文字", 3)
check("材料箱提示词", "3 张截图" in mp and "老师的文字" in mp and "===给分点===" in mp and gc.AI_MARK in mp)

rp = gc.build_revise_prompt("18", 12, "原题Q", "答案A", "（1）满分 12 分\nx｜12", "指南G", ["新意见1"], ["旧意见0"], 2)
check("意见修订提示词", all(k in rp for k in ("新意见1", "旧意见0", "答案A", "指南G", "===调整说明===", "2 张")))
check("四段解析含调整说明", gc.parse_sections("===给分点===\nP\n===调整说明===\nN", ("参考答案", "给分点", "批改指南", "调整说明"))["调整说明"] == "N")

print()
print("全部通过" if not failures else f"{len(failures)} 项失败")
sys.exit(1 if failures else 0)
