#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""评分标准回归测试。

用例目录结构：
    eval_cases/<用例名>/answer.png
    eval_cases/<用例名>/expected.json

expected.json 示例：
    {
      "question_num": "18",
      "max_score": 17,
      "expected_total": 17,
      "items": [
        {"point": "取PD中点N…", "full": 1, "got": 1},
        {"point": "证AB∥MN…", "full": 2, "got": 2}
      ]
    }

items 可以省略；省略时只比较总分。answer / rubric 省略时使用
zhixue_simple_config.json 里的当前标准。

用法：
    .\venv\Scripts\python.exe eval.py --dry-run
    .\venv\Scripts\python.exe eval.py
    .\venv\Scripts\python.exe eval.py --cases eval_cases --limit 5
"""

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from PIL import Image

import zhixue_simple as z


IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def find_answer_image(case_dir):
    preferred = ("answer.png", "answer.jpg", "answer.jpeg",
                 "student.png", "student.jpg", "student.jpeg")
    for name in preferred:
        p = Path(case_dir) / name
        if p.is_file():
            return p
    for p in sorted(Path(case_dir).iterdir()):
        if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES:
            return p
    return None


def make_headless_grader(config):
    """复用正式程序的调用链，但不创建 Tk 窗口。"""
    app = object.__new__(z.SimpleGradingUI)
    app.config = {
        "provider": config.get("provider", "Magpie"),
        "api_key": config.get("api_key", ""),
        "base_url": config.get("base_url", ""),
        "model_name": config.get("model_name", ""),
    }
    app.provider_settings = config.get("provider_settings") or {}
    app._last_model_used = None
    app.log = lambda message: print("    " + str(message), flush=True)
    return app


def text_value(value, default=""):
    if value is None:
        return default
    return str(value)


def build_case(case_dir, base_config, use_card=True):
    expected_path = Path(case_dir) / "expected.json"
    if not expected_path.is_file():
        raise ValueError("缺少 expected.json")
    expected = read_json(expected_path)
    image_path = find_answer_image(case_dir)
    if image_path is None:
        raise ValueError("缺少答卷图片（answer.png / answer.jpg）")

    answer = text_value(expected.get("answer"), base_config.get("answer", ""))
    rubric = text_value(expected.get("rubric"), base_config.get("rubric", ""))
    max_score = float(expected.get("max_score", base_config.get("max_score", 10)) or 10)
    question_num = text_value(expected.get("question_num"), base_config.get("question_num", ""))
    half_point = bool(expected.get("half_point", base_config.get("half_point", False)))

    card = z.build_rubric_card(answer, rubric, question_num, max_score) if use_card else None
    if card and not z.validate_rubric_card(card, max_score):
        source = "评分卡"
    else:
        points, _src, _rules = z.resolve_rubric_points(rubric, answer, max_score)
        card = z.gc.single_part_card(points, max_score)
        source = "整题兜底卡"
    expected_points = [(p["text"], float(p["full"])) for p in z.card_flat_points(card)]

    expected_items = expected.get("items") or []
    if expected_items:
        expected_total = float(expected.get("expected_total",
            sum(float(it.get("got", 0) or 0) for it in expected_items)))
    else:
        if "expected_total" not in expected:
            raise ValueError("没有 items 时必须提供 expected_total")
        expected_total = float(expected["expected_total"])

    prompt = z.gc.build_prompt(question_num, max_score, answer, card, half_point)
    return {
        "name": Path(case_dir).name,
        "dir": Path(case_dir),
        "image_path": image_path,
        "expected": expected,
        "expected_items": expected_items,
        "expected_total": expected_total,
        "expected_points": expected_points,
        "max_score": max_score,
        "question_num": question_num,
        "half_point": half_point,
        "prompt": prompt,
        "source": source,
        "card": card,
    }


def compare_result(case, result):
    predicted_items = result.get("items") or []
    expected_items = case["expected_items"]
    expected_points = case["expected_points"]
    max_score = case["max_score"]
    expected_total = case["expected_total"]
    try:
        predicted_total = float(result.get("score", 0) or 0)
    except (TypeError, ValueError):
        predicted_total = 0.0

    point_rows = []
    if expected_items:
        for i, item in enumerate(expected_items):
            pred = predicted_items[i] if i < len(predicted_items) else {}
            expected_got = float(item.get("got", 0) or 0)
            predicted_got = float(pred.get("got", 0) or 0)
            full = float(item.get("full", expected_points[i][1]
                                  if i < len(expected_points) else 0) or 0)
            point_rows.append({
                "index": i + 1,
                "point": str(item.get("point", "")),
                "full": full,
                "expected_got": expected_got,
                "predicted_got": predicted_got,
                "exact": abs(expected_got - predicted_got) <= 0.01,
            })

    exact_count = sum(1 for row in point_rows if row["exact"])
    point_accuracy = exact_count / len(point_rows) if point_rows else None
    over_points = sum(max(0.0, row["predicted_got"] - row["expected_got"])
                      for row in point_rows)
    under_points = sum(max(0.0, row["expected_got"] - row["predicted_got"])
                       for row in point_rows)
    earnable_gap = max(0.0, max_score - expected_total)
    false_positive_rate = (
        over_points / earnable_gap if earnable_gap > 0
        else (1.0 if over_points > 0 else 0.0)
    )
    false_negative_rate = under_points / max(1.0, expected_total)
    return {
        "predicted_total": predicted_total,
        "total_error": predicted_total - expected_total,
        "point_rows": point_rows,
        "point_accuracy": point_accuracy,
        "over_points": over_points,
        "under_points": under_points,
        "false_positive_rate": false_positive_rate,
        "false_negative_rate": false_negative_rate,
    }


def run_case(case, config, dry_run=False):
    print("\n[{name}] {q}题，满分 {mx:g}，{n} 个给分点，标准来源：{source}".format(
        name=case["name"], q=case["question_num"], mx=case["max_score"],
        n=len(case["expected_points"]), source=case["source"]))
    if dry_run:
        print("  图片：{}".format(case["image_path"]))
        print("  期望总分：{}".format(case["expected_total"]))
        return None

    image = Image.open(case["image_path"]).convert("RGB")
    grader = make_headless_grader(config)
    started = time.time()
    try:
        result = grader.call_ai_api(case["prompt"], image, need_json=True)
        elapsed = time.time() - started
        score, items, reasons, _review = z.gc.settle(
            result, case["card"], case["max_score"], case["half_point"])
        result["score"] = score
        result["items"] = items
        result["_reasons"] = reasons
        metrics = compare_result(case, result)
        print("  预测 {}/{}，期望 {}/{}，误差 {:+g}，用时 {:.1f}s".format(
            z.fmt_score(metrics["predicted_total"]), z.fmt_score(case["max_score"]),
            z.fmt_score(case["expected_total"]), z.fmt_score(case["max_score"]),
            metrics["total_error"], elapsed))
        if metrics["point_accuracy"] is not None:
            print("  逐点一致 {:.0%}，误给分 {:.2f}，漏给分 {:.2f}".format(
                metrics["point_accuracy"], metrics["over_points"], metrics["under_points"]))
        if reasons:
            print("  提示：" + "；".join(str(r) for r in reasons[:3]))
        print("  模型：{}".format(getattr(grader, "_last_model_used", "") or config.get("model_name", "")))
        return {
            "case": case,
            "result": result,
            "metrics": metrics,
            "elapsed": elapsed,
            "status": "ok",
            "error": "",
        }
    except Exception as exc:
        elapsed = time.time() - started
        print("  [失败] {}（{:.1f}s）".format(exc, elapsed))
        return {
            "case": case,
            "result": {},
            "metrics": None,
            "elapsed": elapsed,
            "status": "error",
            "error": str(exc),
        }


def write_reports(records, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    md_path = out / ("eval-{}.md".format(stamp))
    csv_path = out / ("eval-{}.csv".format(stamp))
    json_path = out / ("eval-{}.json".format(stamp))

    lines = [
        "# 评分标准回归测试",
        "",
        "- 时间：{}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        "- 用例数：{}".format(len(records)),
        "",
        "| 用例 | 预测 | 期望 | 误差 | 逐点一致 | 误给分 | 漏给分 | 用时 | 状态 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for rec in records:
        case = rec["case"]
        metrics = rec["metrics"] or {}
        point_acc = metrics.get("point_accuracy")
        lines.append(
            "| {name} | {pred} | {exp} | {err} | {acc} | {over} | {under} | {sec:.1f}s | {status} |".format(
                name=case["name"],
                pred=z.fmt_score(metrics.get("predicted_total", 0)),
                exp=z.fmt_score(case["expected_total"]),
                err="{:+.2f}".format(metrics.get("total_error", 0)),
                acc=("{:.0%}".format(point_acc) if point_acc is not None else "-"),
                over=("{:.2f}".format(metrics.get("over_points", 0)) if metrics else "-"),
                under=("{:.2f}".format(metrics.get("under_points", 0)) if metrics else "-"),
                sec=rec["elapsed"],
                status=rec["status"],
            ))
    if records:
        ok = [r for r in records if r["status"] == "ok"]
        if ok:
            errs = [r["metrics"]["total_error"] for r in ok]
            avg_err = sum(abs(x) for x in errs) / len(ok)
            exact = sum(1 for x in errs if abs(x) < 0.01) / len(ok)
            within1 = sum(1 for x in errs if abs(x) <= 1.01) / len(ok)
            bias = sum(errs) / len(ok)
            lines += ["",
                      "- 总分完全一致：{:.0%}".format(exact),
                      "- 误差在 ±1 分以内：{:.0%}".format(within1),
                      "- 平均总分绝对误差：{:.2f}".format(avg_err),
                      "- 平均偏差：{:+.2f}（正数=程序偏高，负数=偏低）".format(bias)]
            print("\n完全一致 {:.0%}，±1 分内 {:.0%}，平均绝对误差 {:.2f}，平均偏差 {:+.2f}".format(
                exact, within1, avg_err, bias))
        errors = [r for r in records if r["status"] != "ok"]
        if errors:
            lines += ["", "## 失败用例", ""]
            for rec in errors:
                lines.append("- {}：{}".format(rec["case"]["name"], rec["error"]))
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["case", "pred_total", "expected_total", "total_error",
                         "point_accuracy", "over_points", "under_points",
                         "elapsed_sec", "status", "error"])
        for rec in records:
            metrics = rec["metrics"] or {}
            writer.writerow([
                rec["case"]["name"],
                metrics.get("predicted_total", ""),
                rec["case"]["expected_total"],
                metrics.get("total_error", ""),
                metrics.get("point_accuracy", ""),
                metrics.get("over_points", ""),
                metrics.get("under_points", ""),
                "{:.2f}".format(rec["elapsed"]),
                rec["status"],
                rec["error"],
            ])
    payload = []
    for rec in records:
        payload.append({
            "case": rec["case"]["name"],
            "status": rec["status"],
            "error": rec["error"],
            "elapsed": rec["elapsed"],
            "metrics": rec["metrics"],
            "result": rec["result"],
        })
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return md_path, csv_path, json_path


def main():
    parser = argparse.ArgumentParser(description="评分标准回归测试")
    parser.add_argument("--cases", default="eval_cases", help="用例目录")
    parser.add_argument("--config", default="zhixue_simple_config.json", help="配置文件")
    parser.add_argument("--out", default="eval_reports", help="报告目录")
    parser.add_argument("--limit", type=int, default=0, help="最多跑几个用例")
    parser.add_argument("--dry-run", action="store_true", help="只检查用例和评分卡，不调用模型")
    parser.add_argument("--no-card", action="store_true", help="不使用评分卡，直接按文本标准")
    args = parser.parse_args()

    base = Path(__file__).resolve().parent
    cases_dir = (base / args.cases).resolve() if not Path(args.cases).is_absolute() else Path(args.cases)
    config_path = (base / args.config).resolve() if not Path(args.config).is_absolute() else Path(args.config)
    if not cases_dir.is_dir():
        print("用例目录不存在：{}".format(cases_dir))
        return 2
    if not config_path.is_file():
        print("配置文件不存在：{}".format(config_path))
        return 2
    config = read_json(config_path)

    # 递归查找，老师改分自动存的用例在 eval_cases/corrections/ 下面
    case_dirs = sorted(p.parent for p in cases_dir.rglob("expected.json"))
    if args.limit:
        case_dirs = case_dirs[:args.limit]
    if not case_dirs:
        print("没有找到用例。请按 eval_cases/用例名/answer.png + expected.json 放置。")
        return 2

    cases = []
    for case_dir in case_dirs:
        try:
            cases.append(build_case(case_dir, config, use_card=not args.no_card))
        except Exception as exc:
            print("[跳过] {}：{}".format(case_dir.name, exc))
    if not cases:
        return 2

    records = []
    for case in cases:
        record = run_case(case, config, dry_run=args.dry_run)
        if record is not None:
            records.append(record)
    if args.dry_run:
        print("\n检查完成，共 {} 个用例。".format(len(cases)))
        return 0
    md_path, csv_path, json_path = write_reports(records, base / args.out)
    print("\n报告：")
    print("  {}".format(md_path))
    print("  {}".format(csv_path))
    print("  {}".format(json_path))
    return 0 if all(r["status"] == "ok" for r in records) else 1


if __name__ == "__main__":
    sys.exit(main())
