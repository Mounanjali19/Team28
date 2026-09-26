"""What-If simulator and Target Achievement (counterfactual) endpoints."""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.counterfactual.search import counterfactual
from app.database.db import audit, get_conn, now_iso, one
from app.recommendations.products import catalog
from app.rules import policy as P
from app.schemas import CounterfactualIn, SimulateIn
from app.security.auth import assert_user_access, current_principal
from app.services import get_user_data, user_as_of
from app.simulator.whatif import PRESETS, Scenario, simulate

router = APIRouter(prefix="/api", tags=["what-if & counterfactual"])


@router.get("/simulator/presets", summary="The four official What-If scenarios plus the two 'good to have' ones")
def presets():
    return PRESETS


def _log_sim(con, user_id, event_type, scenario_type, target, delta, detail):
    con.execute("""INSERT INTO simulator_events (event_id, user_id, event_ts, session_id, event_type, scenario_type, target_product_id,
                   simulated_score_delta, source, detail_json) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                ("APP_" + uuid.uuid4().hex[:10], user_id, now_iso()[:10], "app", event_type, scenario_type, target, delta, "app",
                 json.dumps(detail, default=str)))


@router.post("/users/{user_id}/simulate", summary="Run a hypothetical scenario; history and the stored score are never changed")
def run_simulation(user_id: str, body: SimulateIn, p: dict = Depends(current_principal)):
    assert_user_access(p, user_id)
    con = get_conn()
    ud = get_user_data(con, user_id)
    if ud is None:
        raise HTTPException(404, "applicant not found")
    scen = [Scenario(s.type, s.params) for s in body.scenarios]
    try:
        result = simulate(ud, user_as_of(con, user_id), scen, body.horizon_months, catalog(con))
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(422, f"invalid scenario parameters: {e}")
    stype = body.preset or "+".join(s.type for s in body.scenarios)
    _log_sim(con, user_id, "simulate", stype, None, result["delta_vs_current"], {"horizon": result["horizon_months"]})
    audit(con, "simulation", p["sub"], "user", user_id, {"scenarios": result["scenarios"], "current": result["current"]["score"],
                                                         "simulated": result["simulated"]["score"], "horizon": result["horizon_months"]},
          rule_version=P.RULE_VERSION)
    con.commit()
    return result


@router.post("/users/{user_id}/counterfactual", summary="What is the minimum realistic change to qualify for a product?")
def run_counterfactual(user_id: str, body: CounterfactualIn, p: dict = Depends(current_principal)):
    assert_user_access(p, user_id)
    con = get_conn()
    ud = get_user_data(con, user_id)
    if ud is None:
        raise HTTPException(404, "applicant not found")
    products = catalog(con)
    prod = next((x for x in products if x["product_id"] == body.product_id), None)
    if not prod:
        raise HTTPException(404, "unknown product")
    result = counterfactual(ud, user_as_of(con, user_id), prod, products)
    con.execute("""INSERT INTO counterfactual_requests (user_id, product_id, current_score, target_score, reachable, result_json, created_at)
                   VALUES (?,?,?,?,?,?,?)""", (user_id, body.product_id, result["current_score"], result["target_score"],
                                               int(result["reachable"]), json.dumps(result, default=str), now_iso()))
    _log_sim(con, user_id, "catalog_view", "target_achievement", body.product_id, None, {"status": result["status"]})
    audit(con, "counterfactual", p["sub"], "user", user_id, {"product_id": body.product_id, "status": result["status"]},
          rule_version=P.RULE_VERSION)
    con.commit()
    return result
