"""API integration: onboarding upload -> score -> simulate -> counterfactual -> lender offer -> accept -> bank.

Runs against a fresh temporary SQLite database (never the demo database) and the
mock bank mounted in-process, so it needs no running servers.
"""
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).parent / "fixtures"
SAMPLE = ROOT / "frontend" / "public" / "sample_transactions.csv"
PASSWORD = "test-password-1"
LENDER = ("LND_L1386O", "pinewood")        # Pinewood Fintech: P_03 Standard Credit Card, min 650


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("api")
    os.environ["MOCKBANK_API_KEY"] = "k-test"
    os.environ["MOCKBANK_DB"] = str(tmp / "bank.db")
    os.environ["MOCKBANK_REVIEW_SECONDS"] = "0"
    sys.path.insert(0, str(ROOT))
    from app.config import settings
    settings.db_path = tmp / "t.db"
    settings.bank_api_key = "k-test"
    settings.reports_dir = tmp
    from app.database.db import connect, init_schema, now_iso
    from app.ingestion.pipeline import load_catalog
    from app.security.auth import hash_password
    con = connect(settings.db_path)
    init_schema(con)
    load_catalog(con, json.loads((FIX / "product_catalog.json").read_text()), json.loads((FIX / "lenders.json").read_text()),
                 {"P_01", "P_02", "P_03", "P_04"})
    con.execute("INSERT INTO auth_accounts VALUES (?,?,?,?,?,?,?)", (LENDER[1], hash_password(PASSWORD), "lender", None, LENDER[0], "Pinewood", now_iso()))
    con.execute("INSERT INTO auth_accounts VALUES (?,?,?,?,?,?,?)", ("admin", hash_password(PASSWORD), "admin", None, None, "Admin", now_iso()))
    con.commit()
    bank_mod = importlib.import_module("mockbank.app")
    from app.bank import client as bank
    bank._transport = TestClient(bank_mod.app)._transport
    from app.main import app
    yield TestClient(app)
    bank._transport = None


def auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def register(c, username, profile, csv_bytes):
    r = c.post("/api/auth/register", data={"username": username, "password": PASSWORD, "profile": json.dumps(profile)},
               files={"transactions": ("t.csv", csv_bytes, "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()


PROFILE = {"display_name": "Test Person", "age": 30, "education_level": "Master", "employment_status": "salaried",
           "monthly_income": 32000, "city_tier": 1, "housing_status": "own", "months_in_current_job": 30, "months_at_address": 40}


def test_health_and_catalog(env):
    assert env.get("/api/health").json()["status"] == "ok"
    prods = env.get("/api/products").json()
    assert {p["product_id"] for p in prods} >= {"P_01", "P_02", "P_03", "P_04"}
    assert env.get("/api/policy").json()["lender_default_score_range"] == [650, 1000]


def test_auth_required_and_role_separation(env):
    assert env.get("/api/users/X/score").status_code == 401
    assert env.post("/api/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 401
    tok = env.post("/api/auth/login", json={"username": LENDER[1], "password": PASSWORD}).json()["token"]
    assert env.post("/api/offers/OFF_X/respond", json={"action": "accept"}, headers=auth(tok)).status_code == 403
    assert env.get("/api/auth/me", headers={"Authorization": "Bearer forged.token"}).status_code == 401


def test_register_rejects_bad_upload(env):
    r = env.post("/api/auth/register", data={"username": "bad1", "password": PASSWORD, "profile": json.dumps(PROFILE)},
                 files={"transactions": ("t.pdf", b"%PDF", "application/pdf")})
    assert r.status_code == 422


def test_end_to_end_flow(env):
    c = env
    out = register(c, "applicant1", PROFILE, SAMPLE.read_bytes())
    s = out["session"]
    uid, tok = s["user_id"], s["token"]
    assert 0 <= out["score"] <= 1000

    prof = c.get(f"/api/users/{uid}/score", headers=auth(tok)).json()
    pol = prof["policy"]
    assert pol["label"] == "Rule-Based Policy Decision" and len(pol["factors"]) == 14
    assert sum(f["points"] for f in pol["factors"]) == pol["raw_score"]
    assert prof["ml"]["label"] == "ML Validation Signal"
    if prof["ml"]["available"]:
        assert prof["ml"]["ml_risk_score"] == round(1000 * (1 - prof["ml"]["pd"]))
        assert prof["ml"]["agreement"]["rule_changed"] is False
    for p in prof["products"]:
        assert p["eligible"] == (pol["score"] >= p["min_score"])

    # another user's data is not reachable
    other = register(c, "applicant2", PROFILE | {"display_name": "Other"}, SAMPLE.read_bytes())["session"]
    assert c.get(f"/api/users/{other['user_id']}/score", headers=auth(tok)).status_code == 403

    # simulation leaves stored history untouched
    hist_before = c.get(f"/api/users/{uid}/history", headers=auth(tok)).json()
    sim = c.post(f"/api/users/{uid}/simulate", headers=auth(tok),
                 json={"scenarios": [{"type": "delinquency", "params": {"utility_days": 45, "rent_days": 15}}], "horizon_months": 2}).json()
    assert sim["hypothetical"] is True and sim["current"]["score"] == pol["score"]
    assert c.get(f"/api/users/{uid}/history", headers=auth(tok)).json() == hist_before
    assert c.post(f"/api/users/{uid}/simulate", headers=auth(tok), json={"scenarios": [{"type": "rob_a_bank"}]}).status_code == 422

    cf = c.post(f"/api/users/{uid}/counterfactual", headers=auth(tok), json={"product_id": "P_04"}).json()
    assert cf["status"] in ("ALREADY_ELIGIBLE", "REACHABLE", "UNREACHABLE_12M", "BLOCKED")

    pdf = c.get(f"/api/reports/{uid}", headers=auth(tok))
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    assert c.get(f"/api/users/{uid}/export", headers=auth(tok)).json()["policy"]["score"] == pol["score"]

    # lender: masked candidate list, offer only if eligible
    ltok = c.post("/api/auth/login", json={"username": LENDER[1], "password": PASSWORD}).json()["token"]
    cands = c.get("/api/lenders/candidates?score_min=0", headers=auth(ltok)).json()
    me = next(x for x in cands["items"] if x["user_id"] == uid)
    assert me["contact"]["masked"] and "Test Person" not in json.dumps(cands)
    r = c.post("/api/offers", headers=auth(ltok), json={"user_id": uid, "product_id": "P_04"})
    assert r.status_code == 422      # not Pinewood's product (LP-06)
    r = c.post("/api/offers", headers=auth(ltok), json={"user_id": uid, "product_id": "P_03"})
    assert pol["score"] >= 650, "the sample upload is meant to qualify for P_03; see test_bulk_offer_skips_ineligible for the other path"
    assert r.status_code == 200, r.text
    offer = r.json()
    assert c.post("/api/offers", headers=auth(ltok), json={"user_id": uid, "product_id": "P_03"}).status_code == 422   # duplicate

    # applicant accepts -> contact revealed to that lender only
    acc = c.post(f"/api/offers/{offer['offer_id']}/respond", headers=auth(tok), json={"action": "accept"})
    assert acc.status_code == 200 and acc.json()["status"] == "accepted"
    detail = c.get(f"/api/lenders/candidates/{uid}", headers=auth(ltok)).json()
    assert detail["contact"]["masked"] is False and detail["contact"]["display_name"] == "Test Person"

    # bank: preapproval + apply through the mock bank; the bank never receives the name or user id
    app_r = c.post("/api/applications", headers=auth(tok), json={"product_id": "P_03", "offer_id": offer["offer_id"]})
    assert app_r.status_code == 200, app_r.text
    body = app_r.json()
    assert uid not in json.dumps(body["sent_to_bank"]) and "Test Person" not in json.dumps(body["sent_to_bank"])
    st = c.get(f"/api/applications/{body['id']}", headers=auth(tok)).json()
    assert st["status"] in ("APPROVED", "MANUAL_REVIEW", "UNDER_REVIEW", "SUBMITTED")

    # audit trail recorded the key actions
    actions = {a["action"] for a in c.get(f"/api/admin/audit?entity_id={uid}", headers=auth(tok)).json()}
    assert {"simulation", "counterfactual"} <= actions


def test_bulk_offer_skips_ineligible(env):
    c = env
    weak_csv = b"date,amount,category,type\n2026-01-01,1000,Gig Payout,CREDIT\n2026-01-05,5000,Shopping,DEBIT\n"
    w = register(c, "weakling", PROFILE | {"employment_status": "student", "monthly_income": 1000, "education_level": "High School",
                                           "housing_status": "family"}, weak_csv)["session"]
    ltok = c.post("/api/auth/login", json={"username": LENDER[1], "password": PASSWORD}).json()["token"]
    r = c.post("/api/offers/bulk", headers=auth(ltok), json={"user_ids": [w["user_id"]], "product_id": "P_03"}).json()
    assert r["sent"] == 0 and r["skipped"][0]["user_id"] == w["user_id"]


def test_bank_rejects_missing_key(env):
    import mockbank.app as bank_mod
    bc = TestClient(bank_mod.app)
    assert bc.post("/bank/preapproval", json={}).status_code in (401, 403)
