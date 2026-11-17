# -*- coding: utf-8 -*-
"""通用判分核心（v1.11 起）。

设计原则：
1. 一份答卷只调用一次模型：截图 + 评分卡 + 通用判分要求 → 每个采分点的得分。
2. 提示词里没有任何具体题目的例子、字母或题型关键词，换题不用改代码。
3. 程序只做算术和格式校验：限幅、分档取整、封顶、加总、四舍五入到计分单位。
   程序从不因为"证据对不上""字段没填"把模型给的分改成 0；
   拿不准的地方只写进提示，交给老师决定。

本文件只依赖评分卡的数据结构（parts → methods → points），不依赖界面。
"""

import math
import re

# 评分卡结构（由 zhixue_simple.build_rubric_card 生成，老师可在评分卡窗口修改）：
# card = {"parts": [{"id": "1", "title": "...", "max_score": 6,
#                    "methods": [{"id": "1-A", "name": "标准解法", "notes": "",
#                                 "points": [{"id": "1-A-1", "text": "...", "full": 2,
#                                             "band": False, "levels": [],
#                                             "result_only": False, "shared": False,
#                                             "equivalents": [], "notes": "",
#                                             "deductions": []}]}]}],
#         "score_cap": None, "cap_text": "", "zero_rules": [], "deduction_rules": [],
#         "rules": [], "source": "rubric"}

GRADING_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "reading": {"type": "STRING"},
        "parts": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "part_id": {"type": "STRING"},
                    "method_id": {"type": "STRING"},
                    "points": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "point_id": {"type": "STRING"},
                                "got": {"type": "NUMBER"},
                                "reason": {"type": "STRING"},
                            },
                            "required": ["point_id", "got", "reason"],
                        },
                    },
                },
                "required": ["part_id", "method_id", "points"],
            },
        },
        "confidence": {"type": "STRING"},
        "unclear": {"type": "BOOLEAN"},
        "alt_method": {"type": "BOOLEAN"},
        "analysis": {"type": "STRING"},
    },
    "required": ["reading", "parts", "confidence", "unclear", "analysis"],
}


def fmt(x):
    """3.0 → 3，2.5 → 2.5"""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return 0
    x = round(x, 2)
    return int(x) if abs(x - round(x)) < 1e-9 else x


def _f(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def round_to_unit(value, unit):
    """四舍五入到计分单位（0.5 或 1），0.5 进位。"""
    return math.floor(value / unit + 0.5 + 1e-9) * unit


def point_levels(point):
    """分档点允许的分数（升序，含 0）。非分档点返回 None。"""
    if not point.get("band"):
        return None
    scores = sorted({_f(lv.get("score")) for lv in (point.get("levels") or [])
                     if isinstance(lv, dict) and _f(lv.get("score")) > 0})
    return [0.0] + scores if scores else None


def single_part_card(points, max_score):
    """评分卡生成失败时的兜底：整题一个小问；没有给分点就整题一个点。"""
    mx = _f(max_score)
    pts = [(str(t or "").strip(), _f(v)) for t, v in (points or []) if _f(v) > 0]
    if not pts or abs(sum(v for _, v in pts) - mx) > 0.01:
        pts = [("按参考答案整体判断完成程度", mx)]
    return {
        "version": 3, "score_mode": "points", "source": "fallback",
        "max_score": mx,
        "parts": [{
            "id": "1", "title": "全题", "max_score": mx,
            "methods": [{
                "id": "1-A", "name": "标准解法", "notes": "",
                "points": [{"id": f"1-A-{i}", "text": t, "goal": t, "full": v,
                            "band": False, "levels": [], "result_only": False,
                            "shared": False, "equivalents": [], "notes": "",
                            "deductions": []}
                           for i, (t, v) in enumerate(pts, 1)],
            }],
        }],
        "score_cap": None, "cap_text": "", "zero_rules": [],
        "deduction_rules": [], "rules": [],
    }



# ---------------------------------------------------------------- 统一格式 / 批改指南（v1.12）

# 参考答案、原题的统一书写格式。截图识别、整理格式都按这个要求输出。
FORMAT_SPEC = """【统一格式】
1. 文字用中文；所有数学式、字母、数字式子一律写成 LaTeX，并用 $...$ 包起来，例如 $\\frac{1}{2}$、$\\sqrt{3}$、$\\vec{AB}$、$x^2+y^2=1$。不要用 Unicode 上下标或 √、½ 这类符号。
2. 小问单独起一行，写成（1）（2）（3）。
3. 每个得分步骤单独一行，分值写在行尾，写成“（N分）”，N 是这一步自己的分值。
4. 有多种解法时，单独一行写“解法二：”“解法三：”。
5. 评分说明放在最后，单独一行写“评分说明：”，下面每条一行。
6. 原文的内容、式子、分值一个都不能改、不能删、不能补；看不清的写【?】。"""


def capture_prompt(kind="answer"):
    """截图识别的提示词：原题 / 参考答案。"""
    if kind == "question":
        head = "请把图片中的数学题目原样转写成文字（只转写题目，不要解答）。"
    else:
        head = "请把图片中的参考答案和评分标准原样转写成文字，保留每一步标注的分值。"
    return head + "\n" + FORMAT_SPEC + "\n只输出转写结果，不要任何说明。"


def build_guide_prompt(question_num, max_score, question_text, standard_answer, rubric_text=""):
    """生成「统一格式的参考答案 + 批改指南」。只在备课时调用一次，图片是原题截图。"""
    rubric_block = f"\n【给分点（老师填写）】\n{rubric_text.strip()}\n" if rubric_text.strip() else ""
    q_block = f"\n【原题文字】\n{question_text.strip()}\n" if question_text.strip() else ""
    return f"""你是高中数学阅卷组长。图片是第{question_num}题的原题（满分{fmt(max_score)}分）。下面是老师给的参考答案和评分标准。请做两件事。
{q_block}
【参考答案（老师提供）】
{standard_answer.strip()}
{rubric_block}
任务一：把参考答案整理成统一格式。只改写法和排版，内容、式子、步骤、分值一个都不能改、不能删、不能补。
{FORMAT_SPEC}

任务二：写一份批改指南，告诉阅卷老师每个得分步骤到底看什么。按参考答案的得分步骤顺序，每步一段，格式：
【第几问 · 这一步要点的简短描述】
必须看到：学生写出什么才给这一步的分（关键式子或结论）
等价也对：哪些不同写法、不同设法、化简前的形式也算对
部分给分：评分标准写了怎么扣就照写；没写就写“按评分标准”
常见错误：看起来像对、其实不给分的写法（没有就写“无”）

指南要求：
- 不能出现任何新的分值，不能改分值，不能新增或合并得分步骤；分值只认参考答案和给分点。
- 每段不超过 5 行，每行不超过 50 字；数学式同样用 $...$。
- 只根据题目和参考答案写，不要编造评分标准里没有的扣分规则。

严格按下面的格式输出，不要输出其他内容：
===参考答案===
（整理后的参考答案）
===批改指南===
（批改指南）"""


def parse_guide_output(text):
    """解析生成结果，返回 (answer, guide)。缺哪段就是空串。"""
    text = (text or "").replace("\r\n", "\n")
    text = re.sub(r"^```[a-zA-Z]*\n|\n```\s*$", "", text.strip())
    m_a = re.search(r"={2,}\s*参考答案\s*={2,}", text)
    m_g = re.search(r"={2,}\s*批改指南\s*={2,}", text)
    answer = guide = ""
    if m_a and m_g and m_a.start() < m_g.start():
        answer = text[m_a.end():m_g.start()].strip()
        guide = text[m_g.end():].strip()
    elif m_g:
        guide = text[m_g.end():].strip()
    elif m_a:
        answer = text[m_a.end():].strip()
    return answer, guide


_SCORE_RE = re.compile(r"(?<![0-9.])([0-9]+(?:\.[0-9]+)?)\s*分(?![析别类数母子钟])")


def score_numbers(text):
    """文本里所有“N分”的数字，排好序。用来核对整理前后分值没有变。"""
    vals = []
    for m in _SCORE_RE.finditer(text or ""):
        try:
            vals.append(float(m.group(1)))
        except ValueError:
            pass
    return sorted(vals)


def check_scores_kept(original, normalized):
    """返回 (是否一致, 说明)。分值多了、少了、变了都算不一致。"""
    a, b = score_numbers(original), score_numbers(normalized)
    if a == b:
        return True, f"分值核对一致（共 {len(a)} 处，合计 {fmt(sum(a))} 分）" if a else "原答案没有标分值，整理后也没有"
    from collections import Counter
    ca, cb = Counter(a), Counter(b)
    lost = list((ca - cb).elements())
    extra = list((cb - ca).elements())
    parts = []
    if lost:
        parts.append("少了 " + "、".join(f"{fmt(x)}分" for x in lost))
    if extra:
        parts.append("多了 " + "、".join(f"{fmt(x)}分" for x in extra))
    return False, "分值和原答案对不上：" + "；".join(parts)


def guide_new_scores(guide, original_texts, max_score=None):
    """指南里出现、但原答案/给分点里没有的分值（指南不应引入新分值）。"""
    allowed = set()
    for t in original_texts:
        allowed.update(score_numbers(t))
    if max_score:
        allowed.add(float(max_score))
    return sorted({x for x in score_numbers(guide) if x not in allowed})


# ---------------------------------------------------------------- 给分点文本 ⇄ 评分卡（v1.13）
#
# 给分点框就是评分卡，老师直接看、直接改。格式：
#   （1）满分 6 分
#   解法一：设点法
#   求得 $k=2$｜2
#   写出直线方程 $y=2x+1$｜4
#   解法二：参数法
#   ……｜6
#   （2）满分 6 分
#   ……
#   评分说明：
#   最多得 12 分
# 没有小问的题写“全题 满分 12 分”。分值后面带“（AI拟分）”表示是 AI 提议、老师还没确认。

POINTS_FORMAT = """【给分点格式】
（1）满分 N 分          ← 每个小问一行；没有小问写“全题 满分 N 分”
解法一：解法名称        ← 每种解法一行，只有一种解法也要写“解法一：”
得分步骤要点｜分值      ← 每个得分步骤一行，竖线后面只写数字
评分说明：              ← 可选，放最后，下面每条一行"""

AI_MARK = "（AI拟分）"
_PART_RE = re.compile(r"^\s*(?:[（(]\s*([0-9]+|[ⅠⅡⅢⅣⅤ]|[一二三四五])\s*[)）]|第\s*([0-9]+|[一二三四五])\s*问|(全题))"
                      r"\s*[：:]?\s*满分\s*([0-9]+(?:\.[0-9]+)?)\s*分?\s*$")
_METHOD_RE = re.compile(r"^\s*解法\s*([一二三四五六七八九十0-9]+)\s*[：:]?\s*(.*)$")
_POINT_RE = re.compile(r"^\s*(.+?)\s*[|｜]\s*([0-9]+(?:\.[0-9]+)?)\s*分?\s*((?:[（(]\s*AI\s*拟分\s*[)）])?)\s*$")
_CAP_RE = re.compile(r"(?:最多|最高|至多|不超过|上限)\D{0,8}?([0-9]+(?:\.[0-9]+)?)\s*分")


def is_points_text(text):
    """给分点框是不是新格式（至少有一行“（1）满分 N 分”或“全题 满分 N 分”）。"""
    return any(_PART_RE.match(line) for line in (text or "").splitlines())


def card_from_points_text(text, max_score=None):
    """把给分点文本解析成评分卡。返回 (card, issues, ai_lines)。
    issues 非空表示不能用；ai_lines 是带“AI拟分”标记、还要老师确认的行。"""
    parts, rules, issues, ai_lines = [], [], [], []
    part = method = None
    in_rules = False
    for n, raw in enumerate((text or "").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if re.match(r"^评分说明\s*[：:]?\s*$", line):
            in_rules = True
            continue
        if in_rules:
            rules.append(line)
            continue
        m = _PART_RE.match(line)
        if m:
            pid = str(len(parts) + 1)
            title = "全题" if m.group(3) else f"第{pid}问"
            part = {"id": pid, "title": title, "max_score": float(m.group(4)), "methods": []}
            parts.append(part)
            method = None
            continue
        m = _METHOD_RE.match(line)
        if m:
            if part is None:
                issues.append(f"第{n}行“{line[:12]}”前面缺少“（1）满分 N 分”这样的小问行")
                continue
            mid = f"{part['id']}-{chr(65 + len(part['methods']))}"
            method = {"id": mid, "name": (m.group(2) or f"解法{m.group(1)}").strip(), "notes": "", "points": []}
            part["methods"].append(method)
            continue
        m = _POINT_RE.match(line)
        if m:
            if part is None:
                issues.append(f"第{n}行“{line[:12]}”前面缺少“（1）满分 N 分”这样的小问行")
                continue
            if method is None:
                method = {"id": f"{part['id']}-A", "name": "解法一", "notes": "", "points": []}
                part["methods"].append(method)
            if m.group(3):
                ai_lines.append(line)
            pt_text = m.group(1).strip()
            method["points"].append({
                "id": f"{method['id']}-{len(method['points']) + 1}",
                "text": pt_text, "goal": pt_text, "full": float(m.group(2)),
                "band": False, "levels": [], "result_only": False, "shared": False,
                "equivalents": [], "notes": "", "deductions": [], "required": [pt_text],
                "aliases": {}, "zero_if": [],
            })
            continue
        issues.append(f"第{n}行看不懂：“{line[:20]}”（得分步骤要写成“要点｜分值”）")

    if not parts:
        issues.append("没有找到“（1）满分 N 分”或“全题 满分 N 分”")
    total = 0.0
    for part in parts:
        total += part["max_score"]
        if not part["methods"]:
            issues.append(f"{part['title']}没有得分步骤")
        for method in part["methods"]:
            if not method["points"]:
                issues.append(f"{part['title']} {method['name']} 没有得分步骤")
                continue
            got = sum(p["full"] for p in method["points"])
            if abs(got - part["max_score"]) > 0.01:
                issues.append(f"{part['title']} {method['name']} 合计 {fmt(got)} 分，和这一问满分 {fmt(part['max_score'])} 分不一致")
    if max_score and parts and abs(total - float(max_score)) > 0.01:
        issues.append(f"各小问满分合计 {fmt(total)} 分，和本题满分 {fmt(max_score)} 分不一致")

    cap, cap_text = None, ""
    for r in rules:
        m = _CAP_RE.search(r)
        if m and (not max_score or float(m.group(1)) <= float(max_score) + 1e-9):
            cap, cap_text = float(m.group(1)), r
    flat = []
    for part in parts:
        if part["methods"]:
            for p in part["methods"][0]["points"]:
                item = dict(p)
                item["part_id"] = part["id"]
                item["method_id"] = part["methods"][0]["id"]
                flat.append(item)
    card = {
        "version": 3, "score_mode": "points", "source": "points_text", "cumulative": False, "cumulative_raw": [],
        "max_score": float(max_score or total or 0), "parts": parts, "points": flat, "aliases": {},
        "rules": [r for r in rules if r != cap_text][:12], "score_cap": cap, "cap_text": cap_text,
        "zero_rules": [], "deduction_rules": [],
    }
    return card, issues, ai_lines


def strip_ai_marks(text):
    return re.sub(r"\s*[（(]\s*AI\s*拟分\s*[)）]", "", text or "")


def build_materials_prompt(question_num, max_score, text_materials="", n_images=1):
    """材料箱：原题、官方答案、老师手写的其他解法等一起给模型，一次生成
    原题文字 + 统一格式参考答案 + 给分点 + 批改指南。"""
    txt = f"\n【老师粘贴的文字材料】\n{text_materials.strip()}\n" if (text_materials or "").strip() else ""
    img = (f"图片是老师给的材料（{n_images} 张截图从上到下拼在一起，用分隔线隔开），"
           "可能有原题、官方参考答案和评分标准、老师手写的其他解法。") if n_images else "老师没有给图片。"
    return f"""你是高中数学阅卷组长，要为第{question_num}题（满分{fmt(max_score)}分）准备阅卷材料。{img}
{txt}
请先认清每份材料是什么，再输出四部分。

一、原题：把题目原样转写（只要题目，不要解答）。

二、参考答案：把官方答案和老师给的其他解法整理成统一格式。官方答案排“解法一”，老师的其他解法依次排“解法二”“解法三”……内容和式子照抄，不能改、不能删、不能补。
{FORMAT_SPEC}

三、给分点：按下面的格式写。
{POINTS_FORMAT}
规则：
- 官方答案和老师标了分的步骤，分值照抄，一分不能改。
- 某种解法没有标分值时，参照解法一相同作用的步骤给出分值，并在这一行最后加“{AI_MARK}”，等老师确认。
- 每种解法的分值合计必须等于这一问的满分；各问满分合计必须等于 {fmt(max_score)} 分。
- 要点写成能判断的数学结果，例如“求得 $k=2$”，不要只写“计算”“证明”。

四、批改指南：按给分点的顺序，每个得分步骤一段：
【第几问 · 解法几 · 要点】
必须看到：……
等价也对：……
部分给分：评分标准写了就照写，没写就写“按评分标准”
常见错误：……（没有就写“无”）
指南里不能出现任何新的分值；每段不超过 5 行。

严格按下面的格式输出，不要输出其他内容：
===原题===
（原题）
===参考答案===
（参考答案）
===给分点===
（给分点）
===批改指南===
（批改指南）"""


def parse_sections(text, names=("原题", "参考答案", "给分点", "批改指南")):
    """按 ===名称=== 切分模型输出，返回 {名称: 内容}，缺的为空串。"""
    text = (text or "").replace("\r\n", "\n").strip()
    text = re.sub(r"^```[a-zA-Z]*\n|\n```\s*$", "", text)
    marks = []
    for name in names:
        m = re.search(r"={2,}\s*" + name + r"\s*={2,}", text)
        if m:
            marks.append((m.start(), m.end(), name))
    marks.sort()
    out = {name: "" for name in names}
    for i, (_s, e, name) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        out[name] = text[e:end].strip()
    return out


def build_revise_prompt(question_num, max_score, question, answer, points, guide,
                        new_opinions, old_opinions=(), n_images=0):
    """老师批改中途提的意见 → 整体修订给分点和批改指南（一次调用）。"""
    new_txt = "\n".join(f"{i}. {t}" for i, t in enumerate(new_opinions, 1))
    old_txt = "\n".join(f"- {t}" for t in old_opinions) or "无"
    img = (f"图片是老师提意见时对应的学生答卷（{n_images} 张，从上到下拼在一起，用分隔线隔开，按意见顺序）。"
           if n_images else "")
    return f"""你是高中数学阅卷组长。第{question_num}题（满分{fmt(max_score)}分）已经在批改，老师中途提出了新意见，请据此把评分规范整体修订一遍，供后面的试卷使用。{img}

【原题】
{question or "（无）"}

【现在的参考答案】
{answer or "（无）"}

【现在的给分点】
{points or "（无）"}

【现在的批改指南】
{guide or "（无）"}

【之前已经合并过的意见（必须继续遵守）】
{old_txt}

【老师的新意见（必须全部落实）】
{new_txt}

修订要求：
- 只改意见涉及的地方，其他内容原样保留；意见与原规范冲突时，以老师意见为准。
- 意见说的是一种新解法时，在参考答案和给分点里加一套“解法N：”；说的是等价写法、部分给分或常见错误时，写进批改指南对应的那一段；说的是分值时，改给分点。
- 参考答案原有的式子和分值不能改，除非意见明确要求。
- 给分点格式不变：
{POINTS_FORMAT}
- 每种解法的分值合计必须等于这一问的满分；各问满分合计必须等于 {fmt(max_score)} 分。老师意见没有给出、由你拟定的分值，行尾加“{AI_MARK}”。
- 批改指南里不能出现给分点以外的新分值。

严格按下面的格式输出完整的修订结果，不要输出其他内容：
===参考答案===
（修订后的完整参考答案）
===给分点===
（修订后的完整给分点）
===批改指南===
（修订后的完整批改指南）
===调整说明===
（每条意见改了哪里，一条一行）"""

# ---------------------------------------------------------------- 提示词

def _card_text(card):
    lines = []
    for part in card.get("parts") or []:
        lines.append(f"第{part.get('id')}问 {part.get('title') or ''}（满分{fmt(part.get('max_score'))}分）")
        methods = part.get("methods") or []
        for method in methods:
            if len(methods) > 1 or method.get("notes"):
                head = f"  解法 {method.get('id')}：{method.get('name') or ''}"
                if method.get("notes"):
                    head += f"（{method['notes']}）"
                lines.append(head)
            for point in method.get("points") or []:
                tag = "【结果】" if point.get("result_only") else ""
                text = str(point.get("text") or point.get("goal") or "").strip()
                levels = point_levels(point)
                if levels:
                    lines.append(f"    [{point.get('id')}] {tag}分档，满分{fmt(point.get('full'))}分，"
                                 f"只能给 {'/'.join(str(fmt(s)) for s in levels)} 分：")
                    for lv in point.get("levels") or []:
                        lines.append(f"        {fmt(lv.get('score'))}分：{lv.get('text') or ''}")
                else:
                    line = f"    [{point.get('id')}] {tag}{fmt(point.get('full'))}分：{text}"
                    eq = [str(x).strip() for x in (point.get("equivalents") or []) if str(x).strip()]
                    if eq:
                        line += f"（等价写法：{'、'.join(eq)}）"
                    if point.get("notes"):
                        line += f"（{point['notes']}）"
                    lines.append(line)
                if point.get("deductions"):
                    lines.append("        标准写明可扣："
                                 + "、".join(f"{fmt(d)}分" for d in point["deductions"]))
    return "\n".join(lines)


def _rules_text(card):
    out = []
    if card.get("score_cap") is not None:
        out.append(f"本题最多给 {fmt(card['score_cap'])} 分（{card.get('cap_text') or '评分说明'}）")
    for key in ("zero_rules", "deduction_rules", "rules"):
        for rule in card.get(key) or []:
            text = rule.get("text") if isinstance(rule, dict) else rule
            text = str(text or "").strip()
            if text and text not in out:
                out.append(text)
    return out[:12]


def build_prompt(question_num, max_score, standard_answer, card, half_point=False,
                 question_text="", guide=""):
    """通用判分提示词。不含任何具体题目的示例。
    question_text / guide：老师确认过的原题与批改指南，没有就不出现。"""
    unit = "0.5" if half_point else "1"
    q_block = f"【原题】\n{question_text.strip()}\n\n" if (question_text or "").strip() else ""
    guide_block = (f"\n【批改指南（老师确认过）：说明每个得分步骤看什么、哪些写法等价；分值仍以评分卡为准】\n{guide.strip()}\n"
                   if (guide or "").strip() else "")
    rules = _rules_text(card)
    rules_block = ("\n【评分说明（老师写的，必须遵守）】\n" + "\n".join(f"- {r}" for r in rules)) if rules else ""
    example_parts = []
    for part in card.get("parts") or []:
        method = (part.get("methods") or [{}])[0]
        pts = ",".join('{"point_id":"%s","got":0,"reason":"..."}' % p.get("id")
                       for p in (method.get("points") or [])[:2])
        example_parts.append('{"part_id":"%s","method_id":"%s","points":[%s]}'
                             % (part.get("id"), method.get("id"), pts))
    example = ('{"reading":"...","parts":[' + ",".join(example_parts)
               + '],"confidence":"高","unclear":false,"alt_method":false,"analysis":"..."}')

    return f"""你是高中数学阅卷老师。图片是学生第{question_num}题的作答，满分{fmt(max_score)}分。请对照参考答案，按评分卡逐个采分点判分。

{q_block}【参考答案】
{standard_answer.strip()}

【评分卡】（方括号里是采分点编号，后面是分值和要求）
{_card_text(card)}{rules_block}
{guide_block}
【判分要求】
1. 先看清学生写了什么，再判分。只依据图片里学生实际写出的内容，参考答案只用来对照，不能替学生补步骤。
2. 每一问先选一套解法：选与学生思路最接近的那一套，只按这套的采分点判。学生用了评分卡没列的正确方法，也选最接近的一套，按"是否达到该点要求的数学结果"判，并把 alt_method 填 true。
3. 采分点看数学实质（有批改指南时，按指南里“必须看到/等价也对/常见错误”判断），不看字面：学生写出了该点要求的式子、结论或步骤，或与它数学上等价的写法（变形、化简、换字母、换坐标系、不同但正确的推理），就给满分；没写、写错就给 0。
4. 只完成一部分：标准写了扣分办法就照办；没写就按完成的比例给分，分数是 {unit} 的整数倍，并在 reason 里说明缺了什么。
5. 分档点只能给列出的分数：给学生完整达到的最高一档，一档都没达到给 0。
6. 前面算错：错误那一步不给分；后面方法对、只是沿用了错误数据的过程点可以给分，结果点不给分。评分说明另有规定的，按评分说明。
7. 只写最终答案、没有必要过程：结果点按答案对错判，过程点不给分。
8. 看不清的字不要猜，按看到的判，并把 unclear 填 true。
9. reading：用一两句话写出学生每一问的关键式子和最终结论（不超过 150 字），写成一行。
10. reason：每点一句话，不超过 20 字，写清"写了什么"或"缺了什么"。
11. confidence 填 高/中/低：字迹清楚、每点都有把握填 高。

只输出一个 JSON 对象，不要其他文字；每一问、每个采分点都要返回，point_id 用评分卡上的编号；字符串里不要换行，不要用英文双引号。格式：
{example}"""


# ---------------------------------------------------------------- 计分

def _item(part, method, point, got, reason, note=""):
    return {
        "point": str(point.get("text") or point.get("goal") or ""),
        "full": _f(point.get("full")),
        "got": float(got),
        "reason": str(reason or ""),
        "evidence": "",
        "note": note,
        "part_id": str(part.get("id", "")),
        "part_title": str(part.get("title", "")),
        "method_id": str(method.get("id", "")),
        "method_name": str(method.get("name", "")),
        "point_id": str(point.get("id", "")),
    }


def _norm_id(x):
    return str(x if x is not None else "").strip().replace("（", "(").replace("）", ")")


def _pick_method(part, model_part):
    """按模型返回的 method_id 找解法；找不到就看哪套解法的采分点编号匹配最多。"""
    methods = part.get("methods") or []
    if not methods:
        return None, False
    wanted = _norm_id(model_part.get("method_id")) if model_part else ""
    for m in methods:
        if _norm_id(m.get("id")) == wanted:
            return m, True
    if model_part:
        ids = {_norm_id(p.get("point_id")) for p in (model_part.get("points") or [])
               if isinstance(p, dict)}
        best = max(methods, key=lambda m: sum(_norm_id(p.get("id")) in ids
                                              for p in (m.get("points") or [])))
        if any(_norm_id(p.get("id")) in ids for p in (best.get("points") or [])):
            return best, False
    return methods[0], False


def _score_point(point, raw, unit):
    """把模型给的分规范化。返回 (分数, 说明)。只做限幅和取整，不改判。"""
    full = _f(point.get("full"))
    if raw is None:
        return 0.0, "模型没有返回该点"
    got = _f(raw.get("got"), None)
    if got is None:
        return 0.0, "模型给分不是数字"
    got = max(0.0, min(got, full))
    levels = point_levels(point)
    if levels:
        if not any(abs(got - s) < 0.01 for s in levels):
            snapped = min(levels, key=lambda s: (abs(s - got), s))
            return snapped, f"模型给 {fmt(got)} 分不在档位里，已取最近档 {fmt(snapped)}"
        return got, ""
    rounded = round_to_unit(got, unit)
    if abs(rounded - got) > 0.01:
        return min(rounded, full), f"模型给 {fmt(got)} 分，已按计分单位取 {fmt(min(rounded, full))}"
    return got, ""


def settle(result, card, max_score, half_point=False):
    """把模型返回的逐点得分合成总分。

    返回 (总分, 逐点明细, 提示列表, 是否需要人工复核)。
    需要人工复核 = 模型输出结构有缺漏（缺小问、缺采分点、解法编号对不上），
    这时分数仍照算，只是要老师看一眼。
    """
    unit = 0.5 if half_point else 1.0
    result = result if isinstance(result, dict) else {}
    reasons, items = [], []
    review = False

    model_parts = {}
    raw_parts = [p for p in (result.get("parts") or []) if isinstance(p, dict)]
    for mp in raw_parts:
        model_parts[_norm_id(mp.get("part_id"))] = mp
    parts = card.get("parts") or []
    # 只有一问且模型返回的编号不对时，按顺序对上
    if len(parts) == len(raw_parts) and not any(_norm_id(p.get("id")) in model_parts for p in parts):
        model_parts = {_norm_id(p.get("id")): mp for p, mp in zip(parts, raw_parts)}

    total = 0.0
    for part in parts:
        pid = _norm_id(part.get("id"))
        mp = model_parts.get(pid)
        method, exact = _pick_method(part, mp)
        if method is None:
            continue
        if mp is None:
            review = True
            reasons.append(f"模型没有返回第{pid}问，该问暂按 0 分，请核对")
        elif not exact:
            review = True
            reasons.append(f"第{pid}问的解法编号「{mp.get('method_id')}」对不上，已按 {method.get('id')} 计分")
        raw_points = {}
        raw_list = [p for p in ((mp or {}).get("points") or []) if isinstance(p, dict)]
        for rp in raw_list:
            raw_points[_norm_id(rp.get("point_id"))] = rp
        card_points = method.get("points") or []
        if raw_list and not any(_norm_id(p.get("id")) in raw_points for p in card_points) \
                and len(raw_list) == len(card_points):
            raw_points = {_norm_id(p.get("id")): rp for p, rp in zip(card_points, raw_list)}
        part_total = 0.0
        missing = []
        for point in card_points:
            raw = raw_points.get(_norm_id(point.get("id")))
            if mp is not None and raw is None:
                missing.append(str(point.get("id")))
            got, note = _score_point(point, raw, unit)
            if note and raw is not None:
                reasons.append(f"{point.get('id')}：{note}")
            part_total += got
            items.append(_item(part, method, point, got, (raw or {}).get("reason", ""), note))
        if missing:
            review = True
            reasons.append(f"第{pid}问缺少采分点 {'、'.join(missing)} 的判分，暂按 0 分")
        part_max = _f(part.get("max_score"))
        if part_max and part_total > part_max + 0.01:
            reasons.append(f"第{pid}问逐点合计 {fmt(part_total)} 超过满分，按 {fmt(part_max)} 计")
            part_total = part_max
        total += part_total

    mx = _f(max_score)
    total = max(0.0, min(total, mx))
    cap = card.get("score_cap")
    if cap is not None and total > _f(cap) + 1e-9:
        reasons.append(f"评分说明规定本题最多 {fmt(cap)} 分（逐点合计 {fmt(total)}）")
        total = _f(cap)
    rounded = round_to_unit(total, unit)
    if abs(rounded - total) > 1e-6:
        reasons.append(f"逐点合计 {fmt(total)} 分，按计分单位四舍五入为 {fmt(rounded)}")
    total = min(rounded, mx)

    conf = str(result.get("confidence", "")).strip()
    if conf.startswith(("低", "中")) or conf.lower().startswith(("low", "med")):
        reasons.append(f"模型把握度：{conf}")
    if result.get("unclear") is True:
        reasons.append("模型说有看不清的地方")
    if result.get("alt_method") is True:
        reasons.append("学生用了评分卡以外的方法，建议看一眼")
    return fmt(total), items, reasons, review
