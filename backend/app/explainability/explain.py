"""Explainability: natural-language summaries built only from rule reason records.

PRIMARY: policy reasons come from the rule engine's records (EX-01..EX-03).
SECONDARY: ML validation text comes from the PD model's own contributions and
is always labelled as a validation signal, never as a reason for the score.
"""
from __future__ import annotations


def policy_explanation(rule: dict) -> dict:
    f = [r for r in rule["factors"]]
    positives = sorted([r for r in f if r["effect"] == "positive"], key=lambda r: -r["points"])
    negatives = sorted([r for r in f if r["effect"] == "negative" or (r["id"] == "4.2" and r["points"] < 0)],
                       key=lambda r: -r["points_lost"])
    main_reasons = sorted([r for r in f if r["points_lost"] > 0], key=lambda r: (-r["points_lost"], r["id"]))[:3]
    up = [f"{r['name']}: {r['text']}" for r in positives[:4]]
    down = [f"{r['name']}: {r['text']}" for r in negatives[:4]]
    summary = (f"Your policy credit score is {rule['score']} / 1000 ({rule['tier']['name']}). "
               f"It is the sum of 14 published rules: {rule['positive_points']} points earned"
               + (f", {abs(rule['negative_points'])} points deducted for risk flags" if rule["negative_points"] else "")
               + (f"; the raw total of {rule['raw_score']} is capped at 1000." if rule["capped"] else "."))
    return {
        "summary": summary,
        "score_increased_because": up,
        "score_decreased_because": down,
        "main_reasons": [{"factor": r["id"], "name": r["name"], "points_lost": r["points_lost"], "text": r["text"]} for r in main_reasons],
        "top_positive": [{"factor": r["id"], "name": r["name"], "points": r["points"], "max": r["max"], "text": r["text"]} for r in positives[:3]],
        "top_negative": [{"factor": r["id"], "name": r["name"], "points": r["points"], "max": r["max"], "points_lost": r["points_lost"], "text": r["text"]}
                         for r in negatives[:3]],
        "label": "Rule-Based Policy Decision",
    }


def trace_lines(rule: dict) -> list[str]:
    lines = [f"{r['id']} {r['name']}: {r['value_display']} -> {r['points']:+d}" for r in rule["factors"]]
    lines.append(f"Raw total: {rule['raw_score']}" + (" (capped at 1000)" if rule["capped"] else ""))
    lines.append(f"Final: {rule['score']} / 1000 ({rule['tier']['name']})")
    return lines
