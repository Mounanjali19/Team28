"""What-If directional behaviour, simulator immutability, and counterfactual verification."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from app.counterfactual.search import counterfactual
from app.features.engineering import compute_features
from app.rules.engine import evaluate
from app.simulator.whatif import PRESETS, Scenario, project, score_at, simulate
from tests.conftest import AS_OF

CATALOG = json.loads((Path(__file__).parent / "fixtures" / "product_catalog.json").read_text())
PRODUCTS = [{"product_id": p["product_id"], "product_name": p["product_name"], "min_score": p["min_score"]} for p in CATALOG]


def raw(ud, horizon, scen):
    return score_at(ud, AS_OF, horizon, scen)[0]["raw_score"]


def preset(key):
    p = PRESETS[key]
    return [Scenario(s["type"], s["params"]) for s in p["scenarios"]], p["horizon"]


def test_official_presets_exist():
    assert {"saving_boost", "autopay", "overspend", "delinquency"} <= set(PRESETS)


@pytest.mark.parametrize("key,direction", [("saving_boost", +1), ("autopay", +1), ("overspend", -1), ("delinquency", -1), ("new_debt", -1)])
@pytest.mark.parametrize("who", ["weak", "strong"])
def test_direction_vs_status_quo(key, direction, who, request):
    ud = request.getfixturevalue(who)
    scen, h = preset(key)
    delta = raw(ud, h, scen) - raw(ud, h, [])
    assert delta * direction >= 0, f"{key} moved the wrong way for {who}: {delta}"


def test_delinquency_hurts_clean_payer(strong):
    """Official scenario 4 on a clean payer: 3.4 and 3.1 must both drop (raw score, before the 1000 cap)."""
    scen, h = preset("delinquency")
    base, _ = score_at(strong, AS_OF, h, [])
    hit, _ = score_at(strong, AS_OF, h, scen)
    f0 = {f["id"]: f["points"] for f in base["factors"]}
    f1 = {f["id"]: f["points"] for f in hit["factors"]}
    assert f1["3.4"] < f0["3.4"] and f1["3.1"] < f0["3.1"]
    assert hit["raw_score"] < base["raw_score"]


def test_overspend_hurts_spend_ratio(strong):
    scen, h = preset("overspend")
    hit, _ = score_at(strong, AS_OF, h, scen)
    assert {f["id"]: f["points"] for f in hit["factors"]}["2.1"] < 120


def test_autopay_raises_on_time_rate(weak):
    scen = [Scenario("autopay", {"bill_types": ["rent", "utility", "telecom", "emi", "card_min"]})]
    base = compute_features(project(weak, AS_OF, 12, [])[0], np.datetime64("2027-06-01"))
    with_ap = compute_features(project(weak, AS_OF, 12, scen)[0], np.datetime64("2027-06-01"))
    assert with_ap["factors"]["3.1"]["value"] >= base["factors"]["3.1"]["value"]
    assert with_ap["factors"]["3.1"]["value"] == 1.0   # a full year of autopay -> every bill in the window on time


def test_simulation_never_modifies_history(weak):
    snap = copy.deepcopy(weak)
    before = evaluate(compute_features(weak, AS_OF))["score"]
    for key in PRESETS:
        scen, h = preset(key)
        simulate(weak, AS_OF, scen, h, PRODUCTS)
    counterfactual(weak, AS_OF, PRODUCTS[-1] | {"min_score": 750}, PRODUCTS)
    for table in ("txn", "obl", "stmt", "life"):
        for col, arr in getattr(snap, table).items():
            np.testing.assert_array_equal(getattr(weak, table)[col], arr, err_msg=f"{table}.{col} changed")
    assert weak.accounts == snap.accounts and weak.employment == snap.employment
    assert evaluate(compute_features(weak, AS_OF))["score"] == before


def test_simulated_rows_are_marked_hypothetical(weak):
    hyp, _, _ = project(weak, AS_OF, 3, [Scenario("saving_boost", {"amount": 1000, "months": 3})])
    assert hyp.txn["hyp"].any() and not hyp.txn["hyp"][hyp.txn["date"] < AS_OF].any()


def test_simulation_result_contract(weak):
    scen, h = preset("autopay")
    r = simulate(weak, AS_OF, scen, h, PRODUCTS)
    assert r["hypothetical"] is True
    assert r["delta_vs_current"] == r["simulated"]["score"] - r["current"]["score"]
    assert r["delta_vs_baseline"] == r["simulated"]["score"] - r["baseline"]["score"]
    assert len(r["factor_changes"]) == 14


def test_counterfactual_plan_is_verified(weak):
    target = {"product_id": "P_02", "product_name": "Micro-Loan Lite", "min_score": 550}
    cf = counterfactual(weak, AS_OF, target, PRODUCTS)
    assert cf["status"] in ("REACHABLE", "UNREACHABLE_12M")
    if cf["status"] == "REACHABLE":
        levers = [Scenario(s["lever"], s["params"]) for s in cf["steps"]]
        rescored, _ = score_at(weak, AS_OF, cf["horizon_months"], levers)
        assert rescored["score"] == cf["projected_score"] >= 550
        immutable = {"age", "city", "education", "employment_change"}
        assert not immutable & {s["lever"] for s in cf["steps"]}


def test_counterfactual_already_eligible(strong):
    cf = counterfactual(strong, AS_OF, {"product_id": "P_01", "product_name": "Starter", "min_score": 350}, PRODUCTS)
    assert cf["status"] == "ALREADY_ELIGIBLE" and cf["gap"] == 0
