"""Policy, rule catalog, product catalog, ML metrics, ingestion and audit endpoints."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.config import settings
from app.database.db import get_conn, rows
from app.features.engineering import FEATURE_CATALOG
from app.ingestion.pipeline import ingest_upload, parse_uploaded_table
from app.ml.models import load_models
from app.recommendations.products import catalog
from app.rules import policy as P
from app.rules.engine import RULE_CATALOG
from app.security.auth import current_principal, require_role
from app.services import build_profile

router = APIRouter(prefix="/api", tags=["platform"])


@router.get("/policy", summary="Central rule policy: bands, tiers, open decisions, ML bands, lender defaults")
def policy():
    return P.policy_snapshot()


@router.get("/rules", summary="Rule catalog (rule id, input feature, thresholds, points, edge cases)")
def rules():
    return {"rule_version": P.RULE_VERSION, "rules": RULE_CATALOG, "open_decisions": P.OPEN_DECISIONS}


@router.get("/features/catalog", summary="Feature definitions, sources, formulas, windows and missing-data behaviour")
def features():
    return FEATURE_CATALOG


@router.get("/products", summary="Product catalog (read from the ingested JSON, never hard-coded in the UI)")
def products():
    return catalog(get_conn())


@router.get("/ml/metrics", tags=["ml"], summary="Case 1 and Case 2 model evaluation (holdout AUC, calibration, confusion matrix)")
def ml_metrics():
    out = {}
    for name in ("pd_model", "propensity_model"):
        f = Path(settings.models_dir) / f"{name}_metrics.json"
        out[name] = json.loads(f.read_text()) if f.exists() else None
    m = load_models()
    out["loaded"] = {"pd": m["pd"] is not None, "propensity": m["propensity"] is not None}
    return out


@router.post("/ingestion", summary="Admin: ingest one applicant (profile JSON + transactions CSV/JSON + optional bills) and score it")
async def ingestion(user_id: str = Form(..., pattern=r"^[A-Za-z0-9_\-]{3,40}$"), profile: str = Form(...),
                    transactions: UploadFile = File(...), bills: UploadFile | None = File(default=None),
                    p: dict = Depends(require_role("admin"))):
    con = get_conn()
    if rows(con, "SELECT 1 FROM users WHERE user_id=?", (user_id,)):
        raise HTTPException(409, "user_id already exists")
    try:
        prof = json.loads(profile)
        txn = parse_uploaded_table(await transactions.read(), transactions.filename or "upload.csv")
        bl = parse_uploaded_table(await bills.read(), bills.filename or "bills.csv") if bills is not None else None
        result = ingest_upload(con, user_id, prof, txn, bl)
    except (ValueError, json.JSONDecodeError) as e:
        con.rollback()
        raise HTTPException(422, str(e))
    con.commit()
    prof_out = build_profile(con, user_id, persist=True, trigger="ingestion", actor=p["sub"])
    return {"ingestion": result, "score": prof_out["policy"]["score"], "tier": prof_out["policy"]["tier"],
            "data_quality": prof_out["policy"]["data_quality"], "timing_ms": prof_out["timing_ms"]}


@router.get("/admin/ingestion-runs", summary="Ingestion runs and validation findings")
def ingestion_runs(p: dict = Depends(require_role("admin", "lender"))):
    con = get_conn()
    runs = rows(con, "SELECT * FROM ingestion_runs ORDER BY run_id DESC LIMIT 20")
    for r in runs:
        r["stats"] = json.loads(r.pop("stats_json") or "{}")
        r["issues"] = rows(con, "SELECT file, check_code, severity, count, row_ref, message FROM ingestion_errors WHERE run_id=?", (r["run_id"],))
    return runs


@router.get("/admin/audit", summary="Audit trail (score calculations, simulations, offers, decisions)")
def audit_log(entity_id: str | None = None, limit: int = 100, p: dict = Depends(current_principal)):
    con = get_conn()
    if p["role"] == "user":
        entity_id = p["user_id"]
    if entity_id:
        return rows(con, "SELECT * FROM audit_logs WHERE entity_id=? OR actor=? ORDER BY id DESC LIMIT ?", (entity_id, entity_id, limit))
    if p["role"] != "admin":
        raise HTTPException(403, "admin only")
    return rows(con, "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,))
