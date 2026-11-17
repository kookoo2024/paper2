# -*- coding: utf-8 -*-
"""评分卡回归测试：不调用模型，只验证分档、证据和计分。"""

import copy
import json
from pathlib import Path

import zhixue_simple as z


CONFIG = json.loads(Path("zhixue_simple_config.json").read_text(encoding="utf-8"))
MAX_SCORE = float(CONFIG["max_score"])


def load_card():
    card = z.build_rubric_card(
        CONFIG["answer"], CONFIG.get("rubric", ""),
        CONFIG["question_num"], MAX_SCORE)
    assert card, "build_rubric_card returned None"
    assert z.validate_rubric_card(card, MAX_SCORE) == [], \
        z.validate_rubric_card(card, MAX_SCORE)
    return card


def band_points(card):
    return [part["methods"][0]["points"][0] for part in card["parts"]]


def make_result(card, scores=None, alias=None, uncovered_parts=None,
                complete_proof=False):
    scores = list(scores or [point["full"] for point in band_points(card)])
    uncovered_parts = set(uncovered_parts or [])
    transcription_parts = []
    result_parts = []
    if alias:
        transcription_parts.append(f"取PD的中点{alias}，连接A{alias}、M{alias}。")

    for index, part in enumerate(card["parts"]):
        method = part["methods"][0]
        point = method["points"][0]
        evidence = point["levels"][-1]["text"]
        if alias:
            evidence = evidence.replace("N", alias)
        if evidence not in transcription_parts:
            transcription_parts.append(evidence)
        part_result = {
            "part_id": part["id"],
            "method_id": "uncovered" if part["id"] in uncovered_parts else method["id"],
            "part_type": "proof" if part["id"] == "1" else "calculation",
            "points": [{
                "point_id": point["id"],
                "full": point["full"],
                "got": float(scores[index]),
                "evidence": evidence,
                "reason": "测试",
                "equivalent": part["id"] in uncovered_parts,
            }],
        }
        if complete_proof and part["id"] == "1":
            part_result["complete_proof"] = True
            part_result["proof_evidence"] = evidence
            part_result["points"] = []
        result_parts.append(part_result)

    return {
        "transcription": "\n".join(transcription_parts),
        "parts": result_parts,
        "score": sum(scores),
        "confidence": "高",
        "unclear": False,
        "analysis": "测试",
    }


def test_structure():
    card = load_card()
    assert card["version"] == z.CARD_VERSION == 3
    assert card["score_mode"] == "bands"
    assert len(card["parts"]) == 3
    assert [part["max_score"] for part in card["parts"]] == [4, 7, 6]
    assert all(len(part["methods"][0]["points"]) == 1 for part in card["parts"])
    points = band_points(card)
    assert len(points) == 3, [point["id"] for point in points]
    assert [point["id"] for point in points] == ["1-A-1", "2-A-1", "3-A-1"]
    assert [[level["score"] for level in point["levels"]] for point in points] == [
        [1, 3, 4], [1, 2, 4, 5, 7], [2, 4, 6]]
    assert [point["deductions"] for point in points] == [[], [1.0], [2.0]]
    assert all(point["band"] and not point["required"] for point in points)
    assert z.format_score_levels([{"score": 1}, {"score": 3.0}]) == "1/3"
    assert z.format_band_card_summary(card) == (
        "第1问（1/3/4）、第2问（1/2/4/5/7）、第3问（2/4/6）")
    print("structure OK:", [(point["id"], [x["score"] for x in point["levels"]])
                            for point in points])


def test_saved_v2_migration():
    card = load_card()
    legacy = copy.deepcopy(card)
    legacy["version"] = 2
    legacy["score_mode"] = "points"
    for part in legacy["parts"]:
        old = part["methods"][0]["points"][0]
        prev = 0.0
        expanded = []
        for index, level in enumerate(old["levels"], 1):
            expanded.append(z._new_card_point(
                level["text"], float(level["score"]) - prev,
                f"{part['id']}-A-{index}", old.get("deductions") if index == len(old["levels"]) else []))
            prev = float(level["score"])
        part["methods"][0]["points"] = expanded
    upgraded = z.upgrade_rubric_card(legacy, MAX_SCORE)
    assert upgraded["version"] == 3
    assert upgraded["score_mode"] == "bands"
    assert len(band_points(upgraded)) == 3
    assert z.validate_rubric_card(upgraded, MAX_SCORE) == []
    print("saved v2 migration OK")


def test_prompt():
    card = load_card()
    prompt = z.build_grading_prompt(
        CONFIG["question_num"], MAX_SCORE, CONFIG["answer"],
        CONFIG.get("rubric", ""), bool(CONFIG.get("half_point", False)), card)
    assert "整问按原标准分档" in prompt
    assert "允许 1/3/4 分" in prompt
    assert "允许 1/2/4/5/7 分" in prompt
    assert "允许 2/4/6 分" in prompt
    assert '"checks":' not in prompt
    assert "核对项：" not in prompt
    assert "不要因为没照抄标准步骤" in prompt
    assert "等价方法" in prompt
    print("prompt OK:", len(prompt), "chars")


def test_alias():
    aliases = z.extract_aliases(
        "取PD的中点H，连接AH、MH。因为M为棱PC的中点，所以MH∥CD，MH=½CD。")
    assert aliases.get("H") == "PD中点", aliases
    mapping = z.map_student_aliases(aliases, {"N": "PD中点", "M": "PC中点"})
    assert mapping.get("H") == "N", mapping
    assert z.apply_aliases("MH∥CD，AH", mapping) == "MN∥CD，AN"
    print("alias OK:", aliases, mapping)


def test_full_and_alias_full():
    card = load_card()
    score, items, reasons = z.settle_score_v2(make_result(card), card, MAX_SCORE)
    assert score == 17, (score, reasons, items)
    assert len(items) == 3

    score, items, reasons = z.settle_score_v2(
        make_result(card, alias="H"), card, MAX_SCORE)
    assert score == 17, (score, reasons, items)
    assert any("别名" in reason for reason in reasons), reasons
    print("full and alias full OK:", score, len(items))


def test_standard_bands_and_deductions():
    card = load_card()
    cases = [
        ([3, 7, 6], 16),
        ([1, 7, 6], 14),
        ([4, 6, 6], 16),
        ([4, 7, 4], 15),
    ]
    for scores, expected in cases:
        score, items, reasons = z.settle_score_v2(
            make_result(card, scores=scores), card, MAX_SCORE)
        assert score == expected, (scores, score, reasons, items)
    print("standard bands and deductions OK")


def test_invalid_or_no_evidence_is_zero():
    card = load_card()
    result = make_result(card, scores=[2, 7, 6])
    score, items, reasons = z.settle_score_v2(result, card, MAX_SCORE)
    assert score == 13, (score, reasons, items)
    assert any("未列出的档位分" in reason for reason in reasons), reasons

    result = make_result(card)
    result["parts"][0]["points"][0]["evidence"] = ""
    score, items, reasons = z.settle_score_v2(result, card, MAX_SCORE)
    assert score == 13, (score, reasons, items)
    assert any("没有引用学生原文" in reason for reason in reasons), reasons
    print("invalid/no evidence OK")


def test_uncovered_and_complete_proof():
    card = load_card()
    result = make_result(card, uncovered_parts={"1"})
    score, items, reasons = z.settle_score_v2(result, card, MAX_SCORE)
    assert score == 17, (score, reasons, items)

    result = make_result(card, uncovered_parts={"1"})
    result["parts"][0]["points"][0]["equivalent"] = False
    score, items, reasons = z.settle_score_v2(result, card, MAX_SCORE)
    assert score == 13, (score, reasons, items)

    result = make_result(card, complete_proof=True)
    result["parts"][0]["method_id"] = "uncovered"
    score, items, reasons = z.settle_score_v2(result, card, MAX_SCORE)
    assert score == 17, (score, reasons, items)
    assert any("完整正确证明" in reason for reason in reasons), reasons
    print("uncovered/complete proof OK")


def test_missing_and_merge():
    card = load_card()
    first = make_result(card)
    first["parts"] = [part for part in first["parts"] if part["part_id"] == "1"]
    second = make_result(card)
    second["parts"] = [part for part in second["parts"] if part["part_id"] in ("2", "3")]
    merged = z.merge_grading_results(first, second, card)
    score, items, reasons = z.settle_score_v2(merged, card, MAX_SCORE)
    assert score == 17, (score, reasons, items)

    missing = make_result(card)
    missing["parts"] = [part for part in missing["parts"] if part["part_id"] != "2"]
    score, items, reasons = z.settle_score_v2(missing, card, MAX_SCORE)
    assert score == 10, (score, reasons, items)
    assert any("第2小问没有返回" in reason for reason in reasons), reasons
    print("missing and merge OK")


def test_model_one_point_scale_and_checks_ignored():
    card = load_card()
    result = make_result(card)
    point = result["parts"][1]["points"][0]
    point["full"] = 1
    point["got"] = 1
    point["reason"] = "完整达到7分档"
    point["checks"] = [{
        "requirement": "旧版核对项", "shown": False,
        "evidence": "", "equivalent": False,
    }]
    score, items, reasons = z.settle_score_v2(result, card, MAX_SCORE)
    assert score == 17, (score, reasons, items)
    assert any("按模型自己的满分" in reason for reason in reasons), reasons
    print("model one-point scale/checks ignored OK")


def test_direct_point_mode_still_supported():
    answer = "（1）由条件得 x=1。……（2分）\n（2）所以 x+y=3。……（2分）"
    card = z.build_rubric_card(answer, "", "1", 4)
    assert card and card["score_mode"] == "points"
    assert z.validate_rubric_card(card, 4) == []
    points = [p for part in card["parts"] for p in part["methods"][0]["points"]]
    assert len(points) == 2
    print("direct point mode OK")


def test_truncated_json_repair():
    raw = (
        '{"transcription":"最大值为3","parts":[{"part_id":"1","method_id":"1-A",'
        '"points":[{"point_id":"1-A-1","full":4,"got":4,'
        '"evidence":"最大值为3","reason":"达到4分档"}'
    )
    fixed = z.close_truncated_json(raw)
    data = json.loads(fixed)
    assert data["parts"][0]["points"][0]["got"] == 4, fixed
    print("truncated JSON repair OK")


if __name__ == "__main__":
    test_structure()
    test_saved_v2_migration()
    test_prompt()
    test_alias()
    test_full_and_alias_full()
    test_standard_bands_and_deductions()
    test_invalid_or_no_evidence_is_zero()
    test_uncovered_and_complete_proof()
    test_missing_and_merge()
    test_model_one_point_scale_and_checks_ignored()
    test_direct_point_mode_still_supported()
    test_truncated_json_repair()
    print("ALL OK")
