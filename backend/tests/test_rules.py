"""Rule thresholds (boundary values for every band) and hand-computed ground truth."""
from __future__ import annotations

import pytest

from app.features.engineering import compute_features
from app.rules import policy as P
from app.rules.engine import evaluate, rule_3_4, rule_4_1, rule_4_2
from tests.conftest import AS_OF

# ---------------------------------------------------------------- band edges
# (factor, value, expected points) straight from the official scoring table.
EDGES = [
    ("1.1", 0, 0), ("1.1", 5, 0), ("1.1", 6, 50), ("1.1", 11, 50), ("1.1", 12, 100), ("1.1", 23, 100), ("1.1", 24, 150), ("1.1", 120, 150),
    ("1.3", 0.59, 0), ("1.3", 0.60, 20), ("1.3", 0.79, 20), ("1.3", 0.80, 45), ("1.3", 0.94, 45), ("1.3", 0.95, 70), ("1.3", 1.0, 70),
    ("2.1", 0.0, 120), ("2.1", 0.30, 120), ("2.1", 0.3001, 80), ("2.1", 0.50, 80), ("2.1", 0.5001, 40), ("2.1", 0.70, 40), ("2.1", 0.7001, 0), ("2.1", 2.0, 0),
    ("2.2", 0.39, 0), ("2.2", 0.40, 20), ("2.2", 0.54, 20), ("2.2", 0.55, 45), ("2.2", 0.69, 45), ("2.2", 0.70, 80), ("2.2", 1.0, 80),
    ("2.3", 0.0, 70), ("2.3", 0.05, 70), ("2.3", 0.0501, 40), ("2.3", 0.10, 40), ("2.3", 0.1001, 15), ("2.3", 0.20, 15), ("2.3", 0.2001, 0),
    ("2.4", 0, 0), ("2.4", 29, 0), ("2.4", 30, 20), ("2.4", 89, 20), ("2.4", 90, 50), ("2.4", 179, 50), ("2.4", 180, 80), ("2.4", 999, 80),
    ("3.1", 0.79, 0), ("3.1", 0.80, 50), ("3.1", 0.89, 50), ("3.1", 0.90, 100), ("3.1", 0.94, 100), ("3.1", 0.95, 150), ("3.1", 0.97, 150),
    ("3.1", 0.98, 200), ("3.1", 1.0, 200),
    ("3.2", 0.0, 120), ("3.2", 0.20, 120), ("3.2", 0.2001, 80), ("3.2", 0.35, 80), ("3.2", 0.3501, 40), ("3.2", 0.50, 40), ("3.2", 0.5001, 0),
    ("3.3", 0.0, 100), ("3.3", 0.10, 100), ("3.3", 0.1001, 70), ("3.3", 0.30, 70), ("3.3", 0.3001, 30), ("3.3", 0.50, 30), ("3.3", 0.5001, 0), ("3.3", 1.2, 0),
]


@pytest.mark.parametrize("fid,value,points", EDGES)
def test_band_edges(fid, value, points):
    assert P.BANDS[fid].evaluate(value)[0] == points


def test_housing_and_education_tables():
    assert P.HOUSING_POINTS == {"own": 80, "rent_12m_on_time": 60, "rent_short": 30, "rent_12m_broken_streak": 30, "family": 30, "none": 0}
    assert P.EDUCATION_POINTS == {"phd": 50, "master": 50, "bachelor": 40, "diploma_cert": 30, "high_school": 20, "below_hs": 0}


@pytest.mark.parametrize("events,worst,points", [(0, 0, 150), (1, 30, 100), (1, 59, 100), (1, 60, 50), (1, 89, 50), (1, 90, 0), (2, 35, 0), (5, 200, 0)])
def test_delinquency_severity(events, worst, points):
    f = {"value": events, "status": "ok", "evidence": {"worst_dpd": worst, "event_list": []}}
    assert rule_3_4(f)["points"] == points


@pytest.mark.parametrize("n,points", [(0, 0), (1, 20), (2, 40), (3, 50)])
def test_habits_cap(n, points):
    f = {"value": n, "evidence": {"habits": [{"name": "h", "evidence": "e"}] * n}}
    assert rule_4_1(f)["points"] == points


@pytest.mark.parametrize("n,points", [(0, 0), (1, -20), (2, -40), (3, -50), (4, -50)])
def test_flags_floor(n, points):
    f = {"value": n, "evidence": {"flags": [{"name": "f", "evidence": "e", "expires": "x"}] * n}}
    assert rule_4_2(f)["points"] == points


@pytest.mark.parametrize("score,tier", [(0, "T1"), (349, "T1"), (350, "T2"), (549, "T2"), (550, "T3"), (649, "T3"), (650, "T4"),
                                        (749, "T4"), (750, "T5"), (1000, "T5")])
def test_tier_edges(score, tier):
    assert P.tier_for(score).code == tier


@pytest.mark.parametrize("pd_value,band", [(0.0, "Low"), (0.0499, "Low"), (0.05, "Moderate"), (0.1199, "Moderate"), (0.12, "Elevated"),
                                           (0.2499, "Elevated"), (0.25, "High"), (1.0, "High")])
def test_ml_bands(pd_value, band):
    assert P.ml_band_for(pd_value) == band


def test_max_possible_points_is_1320_and_score_is_clamped():
    assert sum(P.FACTOR_MAX.values()) == 1320
    assert P.SCORE_MIN == 0 and P.SCORE_MAX == 1000


# ---------------------------------------------------------------- ground truth
def points(rule):
    return {f["id"]: f["points"] for f in rule["factors"]}


def test_ground_truth_strong(strong):
    r = evaluate(compute_features(strong, AS_OF))
    # Hand-computed from conftest.strong_applicant:
    # 1.1 salaried since 2023-01-15 -> 40 full months -> 150      1.2 owns -> 80
    # 1.3 12/12 telecom months on time -> 70                       1.4 Master -> 50
    # 2.1 ~13.5k / 50k = 27% -> 120   2.2 essentials ~78% -> 80   2.3 sigma ~0.1% -> 70   2.4 4,00,000/(50,000/30)=240 days -> 80
    # 3.1 24/24 bills on time -> 200  3.2 no debt -> 120          3.3 no credit line -> neutral 70   3.4 no events -> 150
    # 4.1 micro-savings 12/12 months -> +20                       4.2 no flags -> 0
    expected = {"1.1": 150, "1.2": 80, "1.3": 70, "1.4": 50, "2.1": 120, "2.2": 80, "2.3": 70, "2.4": 80,
                "3.1": 200, "3.2": 120, "3.3": 70, "3.4": 150, "4.1": 20, "4.2": 0}
    assert points(r) == expected
    assert r["raw_score"] == 1260 and r["score"] == 1000 and r["capped"]
    assert r["tier"]["code"] == "T5"
    assert any(f["code"] == "NO_CREDIT_LINE" for f in r["data_quality"]["flags"])


def test_ground_truth_weak(weak):
    r = evaluate(compute_features(weak, AS_OF))
    # 1.1 gig: spell 6 months, 13 consecutive income months -> min = 6 -> 50
    # 1.2 renter 29 months, rent paid 40 days late in Feb 2026 -> broken streak -> 30 (D3)
    # 1.3 telecom on time in 9 of 12 months = 75% -> 20             1.4 High school -> 20
    # 2.1 ~19.4k / 20k = 97% -> 0   2.2 13,400 / 19,400 = 69.1% -> 45
    # 2.3 net flow alternates -2,400 / +3,600 -> sigma ~3,000 = 15% -> 15   2.4 15,000/(20,000/30) = 22 days -> 0
    # 3.1 43 of 48 bills on time = 89.6% -> 50   3.2 EMI 6,000 / 20,000 = 30% -> 80
    # 3.3 15,000 / 20,000 = 75% -> 0            3.4 two bills 30+ days late (40 and 70 dpd) -> 0
    # 4.1 no habits -> 0                         4.2 address change + 2 inquiries in 6 months -> -40
    expected = {"1.1": 50, "1.2": 30, "1.3": 20, "1.4": 20, "2.1": 0, "2.2": 45, "2.3": 15, "2.4": 0,
                "3.1": 50, "3.2": 80, "3.3": 0, "3.4": 0, "4.1": 0, "4.2": -40}
    assert points(r) == expected
    assert r["score"] == 270 and r["tier"]["code"] == "T1"
    fx = compute_features(weak, AS_OF)["factors"]
    assert fx["1.1"]["value"] == 6
    assert fx["3.1"]["evidence"]["bills_due"] == 48 and fx["3.1"]["evidence"]["bills_on_time"] == 43
    assert fx["3.4"]["value"] == 2 and fx["3.4"]["evidence"]["worst_dpd"] == 70


def test_ground_truth_missing_data(missing):
    r = evaluate(compute_features(missing, AS_OF))
    # Nothing measurable earns points; only the neutral no-line 70 and the no-delinquency 150 remain.
    expected = {"1.1": 0, "1.2": 0, "1.3": 0, "1.4": 0, "2.1": 0, "2.2": 0, "2.3": 0, "2.4": 0,
                "3.1": 0, "3.2": 0, "3.3": 70, "3.4": 150, "4.1": 0, "4.2": 0}
    assert points(r) == expected
    assert r["score"] == 220
    assert r["data_quality"]["status"] == "POOR"
    codes = {f["code"] for f in r["data_quality"]["flags"]}
    assert {"INCOME_MISSING", "EMPLOYMENT_MISSING", "INSUFFICIENT_HISTORY", "BILLS_INSUFFICIENT"} <= codes


def test_trace_sums_to_score(weak):
    r = evaluate(compute_features(weak, AS_OF))
    assert sum(f["points"] for f in r["factors"]) == r["raw_score"]
    assert sum(c["points"] for c in r["components"].values()) == r["raw_score"]


def test_deterministic(weak):
    a = evaluate(compute_features(weak, AS_OF))
    b = evaluate(compute_features(weak, AS_OF))
    assert a["score"] == b["score"] and points(a) == points(b)


def test_one_band_crossing_changes_only_that_rule(strong):
    """Education master->bachelor moves 1.4 by exactly -10 and nothing else."""
    base = evaluate(compute_features(strong, AS_OF))
    strong.education_level = "Bachelor"
    moved = evaluate(compute_features(strong, AS_OF))
    diff = {k: v - points(base)[k] for k, v in points(moved).items() if v != points(base)[k]}
    assert diff == {"1.4": -10}


def test_weak_identity_blocks_offers_but_scores(weak):
    weak.match_confidence = 0.7
    r = evaluate(compute_features(weak, AS_OF))
    assert r["weak_id"] and not r["identity_blocked"] and r["score"] == 270
    weak.match_confidence = 0.5
    assert evaluate(compute_features(weak, AS_OF))["identity_blocked"]
