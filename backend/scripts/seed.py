"""Build the AltCredit SQLite database end to end.

    python scripts/seed.py            # ingest -> train ML -> score everyone -> demo accounts
    python scripts/seed.py --skip-ml  # reuse existing models/ (faster)

Steps
 1. create schema (drops an existing database file)
 2. ingest Datasets_AltCredit_v2 (validated, provenance recorded)
 3. ingest the official sample format (Datasets_AltCredit) through the same validators
 4. train the Case 1 PD and Case 2 propensity models (unless --skip-ml)
 5. compute and store the rule score + ML validation for every applicant
 6. create demo user/lender/admin logins and a few seed offers
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from app.config import log, settings  # noqa: E402
from app.database.db import connect, init_schema, now_iso, rows  # noqa: E402
from app.features.builders import build_user  # noqa: E402
from app.ingestion.pipeline import ingest_legacy, ingest_v2, load_all_users  # noqa: E402
from app.ml.models import load_models  # noqa: E402
from app.recommendations.products import catalog  # noqa: E402
from app.security.auth import hash_password  # noqa: E402
from app.services import build_profile  # noqa: E402

LENDER_LOGINS = {
    "LND_X9XMLL": "anchorline", "LND_6YSQL6": "northbridge", "LND_L1386O": "pinewood",
    "LND_DVNXKW": "suryoday", "LND_3LEP0T": "kestrel", "LND_XMGD46": "vantage",
}


def score_everyone(con):
    products = catalog(con)
    load_models.__globals__["_CACHE"].clear()
    total = 0
    for cohorts in (("live", "official_sample", "uploaded"), ("historical",)):
        prep, users = load_all_users(con, cohorts)
        t = time.time()
        for i, uid in enumerate(users.user_id):
            build_profile(con, uid, persist="nocommit", trigger="seed", ud=build_user(prep, uid), products=products)
            if i % 1000 == 999:
                con.commit()
                log.info("scored %d %s applicants (%.1f ms each)", i + 1, cohorts[0], (time.time() - t) / (i + 1) * 1000)
        con.commit()
        total += len(users)
        del prep
    return total


def pick_demo_users(con) -> dict:
    live = pd.read_sql_query("""SELECT u.user_id, s.score, s.tier, s.data_quality, s.result_json, m.pd, m.agreement_status
                                FROM users u JOIN scores s ON s.user_id=u.user_id AND s.is_current=1
                                LEFT JOIN ml_predictions m ON m.user_id=u.user_id AND m.is_current=1
                                WHERE u.cohort='live' AND u.match_confidence >= 0.8""", con)
    flags = live.result_json.map(lambda j: {f["code"] for f in json.loads(j)["policy"]["data_quality"]["flags"]})
    live["no_line"] = flags.map(lambda f: "NO_CREDIT_LINE" in f)
    gaps = {"INCOME_MISSING", "INCOME_VERIFIED", "EMPLOYMENT_MISSING", "UTILITY_HISTORY_MISSING", "HOUSING_MISSING",
            "TELECOM_INSUFFICIENT", "BILLS_INSUFFICIENT", "INSUFFICIENT_HISTORY", "PARTIAL_WINDOW"}
    live["n_gaps"] = flags.map(lambda f: len(f & gaps))
    chosen, used = {}, set()

    def take(label, df, sort, asc):
        df = df[~df.user_id.isin(used)].sort_values(sort, ascending=asc)
        if len(df):
            chosen[label] = df.iloc[0].user_id
            used.add(df.iloc[0].user_id)

    good = live[(live.data_quality == "GOOD")]
    take("strong", good[(good.tier == "T5") & (good.agreement_status == "STRONG_AGREEMENT") & (good.score < 1000)], ["pd"], [True])
    take("moderate", live[(live.tier == "T3") & (live.agreement_status.isin(["AGREEMENT", "STRONG_HIGH_RISK_AGREEMENT"]))], ["pd"], [True])
    take("borderline", live[(live.score >= 740) & (live.score < 750) & (live.data_quality != "POOR")], ["score"], [False])
    take("high_risk", live[live.tier.isin(["T1", "T2"]) & (live.agreement_status == "STRONG_HIGH_RISK_AGREEMENT")], ["score"], [True])
    take("no_credit_history", live[live.no_line & live.tier.isin(["T4", "T5"]) & (live.agreement_status == "STRONG_AGREEMENT")], ["score"], [False])
    take("missing_data", live[(live.n_gaps >= 2) & (live.data_quality != "GOOD")], ["n_gaps", "score"], [False, False])
    if "missing_data" not in chosen:
        take("missing_data", live[live.n_gaps >= 1], ["n_gaps", "score"], [False, False])
    take("disagreement", live[live.agreement_status == "RULE_ELIGIBLE_ML_ELEVATED"], ["pd"], [False])
    sample = rows(con, """SELECT u.user_id FROM users u JOIN scores s ON s.user_id=u.user_id AND s.is_current=1
                          WHERE u.cohort='official_sample' ORDER BY s.score DESC LIMIT 1""")
    if sample:
        chosen["official_sample"] = sample[0]["user_id"]
    return chosen


def create_accounts(con, demo_users: dict, password: str):
    ts = now_iso()
    pw = hash_password(password)
    con.execute("INSERT OR REPLACE INTO auth_accounts VALUES (?,?,?,?,?,?,?)", ("admin", pw, "admin", None, None, "AltCredit Admin", ts))
    for label, uid in demo_users.items():
        con.execute("UPDATE users SET demo_label=? WHERE user_id=?", (label, uid))
        con.execute("INSERT OR REPLACE INTO auth_accounts VALUES (?,?,?,?,?,?,?)",
                    (f"demo.{label.replace('_', '')}", pw, "user", uid, None, label.replace("_", " ").title(), ts))
    for lid, name in LENDER_LOGINS.items():
        lname = rows(con, "SELECT lender_name FROM lenders WHERE lender_id=?", (lid,))
        con.execute("INSERT OR REPLACE INTO auth_accounts VALUES (?,?,?,?,?,?,?)",
                    (name, pw, "lender", None, lid, lname[0]["lender_name"] if lname else name, ts))
    con.commit()


def seed_offers(con, demo_users: dict):
    """Two example offers so the user Offers page has content before a lender acts."""
    from app.api.offers_logic import create_offer
    for label, product, lender in (("strong", "P_04", "LND_6YSQL6"), ("no_credit_history", "P_03", "LND_L1386O")):
        uid = demo_users.get(label)
        if uid:
            try:
                create_offer(con, lender, uid, product, None, None, "Pre-approved offer based on your AltCredit policy score (seed data).",
                             actor="seed")
            except ValueError as e:
                log.warning("seed offer skipped: %s", e)
    con.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-ml", action="store_true")
    ap.add_argument("--db", default=None)
    ap.add_argument("--accounts-only", action="store_true", help="re-pick demo applicants and recreate logins on an existing database")
    args = ap.parse_args()
    if args.db:
        settings.db_path = Path(args.db).resolve()
    t0 = time.time()
    db = Path(settings.db_path)
    if args.accounts_only:
        con = connect(db)
        con.execute("DELETE FROM auth_accounts")
        con.execute("UPDATE users SET demo_label=NULL")
        demo = pick_demo_users(con)
        create_accounts(con, demo, os.environ.get("ALTCREDIT_DEMO_PASSWORD", "AltCredit#2026"))
        (settings.db_path.parent / "demo_accounts.json").write_text(json.dumps(demo, indent=2))
        log.info("demo applicants: %s", demo)
        return
    for p in (db, db.with_suffix(".db-wal"), db.with_suffix(".db-shm")):
        if p.exists():
            p.unlink()
    con = connect(db)
    init_schema(con)
    log.info("dataset dir: %s", settings.dataset_dir)
    r = ingest_v2(con, settings.dataset_dir, legacy_catalog_ids={"P_01", "P_02", "P_03", "P_04"})
    log.info("v2 ingested: %s", r["stats"])
    if settings.legacy_dataset_dir.exists():
        r2 = ingest_legacy(con, settings.legacy_dataset_dir)
        log.info("official sample ingested: %s", r2["stats"])
    if not args.skip_ml:
        from app.ml.training import train_all
        m = train_all(con)
        log.info("ML trained: PD test AUC %s, propensity test AUC %s (%ss)", m["pd"]["test"]["auc"], m["propensity"]["test"]["auc"], m["seconds"])
    n = score_everyone(con)
    log.info("scored %d applicants", n)
    demo = pick_demo_users(con)
    log.info("demo applicants: %s", demo)
    create_accounts(con, demo, os.environ.get("ALTCREDIT_DEMO_PASSWORD", "AltCredit#2026"))
    seed_offers(con, demo)
    (settings.db_path.parent / "demo_accounts.json").write_text(json.dumps(demo, indent=2))
    log.info("seed complete in %.0fs -> %s", time.time() - t0, db)


if __name__ == "__main__":
    main()
