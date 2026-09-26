"""AltCredit API (FastAPI). Run: uvicorn app.main:app --port 8000 (from backend/)."""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import applications, auth, lenders, meta, offers, reports, simulation, users
from app.config import REPO_ROOT, log, settings
from app.database.db import get_conn, init_schema
from app.ml.models import load_models
from app.rules import policy as P

@asynccontextmanager
async def lifespan(_app):
    """Open the database and load the ML models once, at startup (never per request)."""
    con = get_conn()
    init_schema(con)
    n = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    models = load_models()
    log.info("AltCredit API ready: %d applicants, rule version %s, PD model %s, propensity model %s", n, P.RULE_VERSION,
             models["pd"].version if models["pd"] else "missing", models["propensity"].version if models["propensity"] else "missing")
    if n == 0:
        log.warning("database is empty: run `python scripts/seed.py` first")
    yield


app = FastAPI(
    lifespan=lifespan,
    title="AltCredit API",
    version="1.0.0",
    description=("Rule-first alternative credit scoring. The deterministic rule engine produces the authoritative 0-1000 "
                 "policy score; ML (Case 1 PD, Case 2 propensity) is a separately labelled validation layer that never "
                 "changes the policy decision. All data is synthetic."),
)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# meta first: its fixed paths (/api/ml/metrics) must win over /api/ml/{user_id}
for r in (meta.router, auth.router, users.router, simulation.router, reports.router, offers.router, applications.router, lenders.router):
    app.include_router(r)


@app.middleware("http")
async def timing(request: Request, call_next):
    t = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:  # noqa: BLE001 - last-resort handler: log and return a clean 500
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse({"detail": "internal error; see server log"}, status_code=500)
    ms = (time.perf_counter() - t) * 1000
    response.headers["X-Response-Time-ms"] = f"{ms:.1f}"
    if request.url.path.startswith("/api"):
        log.info("%s %s -> %s (%.0f ms)", request.method, request.url.path, response.status_code, ms)
    return response


@app.get("/api/health", tags=["platform"])
def health():
    con = get_conn()
    models = load_models()
    return {"status": "ok", "rule_version": P.RULE_VERSION, "applicants": con.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            "pd_model": models["pd"].version if models["pd"] else None,
            "propensity_model": models["propensity"].version if models["propensity"] else None}


# Serve the built frontend (frontend/dist) when present, so one process can run the whole demo.
DIST = Path(REPO_ROOT) / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "not found")
        f = (DIST / path).resolve()
        if path and f.is_file() and f.is_relative_to(DIST.resolve()):
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
