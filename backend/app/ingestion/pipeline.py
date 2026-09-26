"""Data ingestion: official formats, the generated v2 dataset, and user uploads.

Raw files are read, validated (``validation.py``), and written to SQLite with
provenance (``source``, ``ingestion_run_id``). Source files are never modified.
Scores are never read from input files: the rule engine computes them.

Supported inputs
* ``ingest_v2``      - Datasets_AltCredit_v2 (the expanded synthetic dataset)
* ``ingest_legacy``  - the official sample format (transactional_data.csv,
                       demographic_data.json, product_catalog.json)
* ``ingest_upload``  - one new applicant from the profile page (demographics
                       JSON + transactions CSV/JSON in either format, optional bills)
"""
from __future__ import annotations

import io
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from app.config import log
from app.database.db import audit, now_iso, rows
from app.features.builders import build_user, prepare_frames
from app.features.userdata import UserData
from app.ingestion.validation import check_id_mapping, validate
from app.rules import policy as P

# Legacy format carries only Completed/Late on bill payments, with no dates of
# payment. A 'Late' bill is taken as paid 15 days after its due date: late for
# 3.1/1.2/1.3, but not a 30+ day delinquency event for 3.4 (documented assumption).
LEGACY_LATE_DAYS = 15
LEGACY_BILL_CATEGORIES = {"Rent": "rent", "Utility Bill": "utility", "Telecom": "telecom", "Loan EMI": "emi"}
EMPLOYMENT_STATUS_MAP = {"employed": "salaried", "salaried": "salaried", "self-employed": "self_employed",
                         "self_employed": "self_employed", "student": "student", "unemployed": "unemployed",
                         "gig": "gig", "freelancer": "freelancer"}

TABLE_COLUMNS = {
    "transactions": ["transaction_id", "user_id", "date", "amount", "category", "type", "status", "balance_after", "subtype", "source", "ingestion_run_id"],
    "obligations": ["bill_id", "user_id", "obligation_type", "due_date", "amount_due", "paid_date", "amount_paid", "days_past_due",
                    "autopay", "status", "credit_account_id", "source", "ingestion_run_id"],
    "employment_spells": ["spell_id", "user_id", "employment_type", "employer_category", "start_date", "end_date", "declared_income"],
    "residence_spells": ["spell_id", "user_id", "housing_status", "city_tier", "monthly_rent", "start_date", "end_date"],
    "credit_accounts": ["credit_account_id", "user_id", "account_type", "lender_type", "limit_or_principal", "emi", "open_date", "close_date"],
    "card_statements": ["account_id", "user_id", "statement_month", "credit_limit", "opening_balance", "card_spend", "payment_amount",
                        "outstanding_balance", "minimum_due", "payment_status", "utilization"],
    "life_events": ["event_id", "user_id", "event_type", "event_date"],
}


def _clean(v):
    if v is None:
        return None
    if isinstance(v, (float, np.floating)) and np.isnan(v):
        return None
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return v


def bulk_insert(con, table: str, df: pd.DataFrame, columns: list, chunk: int = 200_000):
    cols = [c for c in columns if c in df.columns]
    sql = f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"
    data = df[cols].astype(object).where(df[cols].notna(), None)
    for start in range(0, len(data), chunk):
        con.executemany(sql, [tuple(_clean(v) for v in r) for r in data.iloc[start:start + chunk].itertuples(index=False, name=None)])


def _start_run(con, source):
    cur = con.execute("INSERT INTO ingestion_runs (source, started_at, status) VALUES (?,?,?)", (source, now_iso(), "running"))
    return cur.lastrowid


def _finish_run(con, run_id, issues, stats, status="completed"):
    for i in issues:
        con.execute("INSERT INTO ingestion_errors (run_id, file, check_code, severity, row_ref, message, count) VALUES (?,?,?,?,?,?,?)",
                    (run_id, i["file"], i["check_code"], i["severity"], i["row_ref"], i["message"], i["count"]))
    con.execute("UPDATE ingestion_runs SET finished_at=?, status=?, stats_json=? WHERE run_id=?",
                (now_iso(), status, json.dumps(stats, default=str), run_id))
    con.commit()


def load_catalog(con, catalog: list, lenders: list | None = None, official_ids: set | None = None):
    df, issues = validate("product_catalog", pd.DataFrame(catalog))
    for l in lenders or []:
        con.execute("INSERT OR REPLACE INTO lenders VALUES (?,?,?)", (l["lender_id"], l["lender_name"], l.get("lender_type")))
    for r in df.to_dict("records"):
        rate_pct = r.get("interest_rate_pct")
        if rate_pct is None or (isinstance(rate_pct, float) and np.isnan(rate_pct)):
            try:
                rate_pct = float(str(r["interest_rate"]).split("%")[0])
            except ValueError:
                rate_pct = None
        con.execute("INSERT OR REPLACE INTO products VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            r["product_id"], r["product_name"], r["type"], int(r["min_score"]), r["interest_rate"], rate_pct,
            _clean(r.get("amount_or_limit_min")), _clean(r.get("amount_or_limit_max")), _clean(r.get("tenure_months")),
            _clean(r.get("annual_fee")), r.get("segment"), r.get("lender_id"),
            1 if (official_ids is None or r["product_id"] in official_ids) else 0))
    return issues


# ---------------------------------------------------------------------------
# v2 dataset
# ---------------------------------------------------------------------------
def read_v2(dataset_dir: Path) -> dict:
    d = Path(dataset_dir)
    log.info("reading v2 dataset from %s", d)
    frames = {
        "demographics": pd.read_json(d / "demographics.json"),
        "id_mapping": pd.read_json(d / "id_mapping.json"),
        "user_contacts": pd.read_json(d / "user_contacts.json"),
        "transactions": pd.read_csv(d / "transactions.csv"),
        "obligations": pd.read_csv(d / "obligations.csv"),
        "card_statements": pd.read_csv(d / "card_statements.csv"),
        "credit_accounts": pd.read_csv(d / "credit_accounts.csv"),
        "employment_spells": pd.read_csv(d / "employment_spells.csv"),
        "residence_spells": pd.read_csv(d / "residence_spells.csv"),
        "life_events": pd.read_csv(d / "life_events.csv"),
        "applications": pd.read_csv(d / "applications.csv"),
        "offers": pd.read_csv(d / "offers.csv"),
        "simulator_events": pd.read_csv(d / "simulator_events.csv"),
        "product_catalog": json.loads((d / "product_catalog.json").read_text()),
        "lenders": json.loads((d / "lenders.json").read_text()),
    }
    return frames


def ingest_v2(con, dataset_dir: Path, legacy_catalog_ids: set | None = None) -> dict:
    run_id = _start_run(con, f"v2:{dataset_dir}")
    f = read_v2(dataset_dir)
    issues = []
    demo, iss = validate("demographics", f["demographics"])
    issues += iss
    issues += check_id_mapping(demo, f["id_mapping"], f["transactions"].head(200_000))
    users = set(demo.user_id)
    cleaned = {}
    for t in ("transactions", "obligations", "card_statements", "credit_accounts", "employment_spells", "residence_spells", "life_events"):
        cleaned[t], iss = validate(t, f[t], users)
        issues += iss
        log.info("validated %s: %d rows kept of %d", t, len(cleaned[t]), len(f[t]))

    # as-of per applicant (T-01)
    apps = f["applications"]
    hist_asof = apps.set_index("user_id")["application_date"].to_dict()
    idmap = f["id_mapping"].set_index("user_id")["match_confidence"].to_dict()
    created = now_iso()
    user_rows = []
    for r in demo.to_dict("records"):
        as_of = hist_asof.get(r["user_id"]) if r.get("cohort") == "historical" else P.LIVE_AS_OF.isoformat()
        user_rows.append((r["user_id"], r.get("applicant_id"), _clean(r.get("age")), r.get("education_level"), r.get("employment_status"),
                          _clean(r.get("monthly_income")), _clean(r.get("city_tier")), r.get("housing_status"), r.get("cohort") or "live",
                          "altcredit_v2", float(idmap.get(r["user_id"], 1.0)), as_of or P.LIVE_AS_OF.isoformat(), None, run_id, created))
    con.executemany("INSERT INTO users VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", user_rows)
    con.executemany("INSERT INTO contacts VALUES (?,?,?,?)",
                    [(c["user_id"], c["display_name"], c["phone"], c["locality"]) for c in f["user_contacts"].to_dict("records") if c["user_id"] in users])
    cleaned["transactions"]["source"] = "altcredit_v2"
    cleaned["transactions"]["ingestion_run_id"] = run_id
    cleaned["obligations"]["source"] = "altcredit_v2"
    cleaned["obligations"]["ingestion_run_id"] = run_id
    cleaned["obligations"]["autopay"] = cleaned["obligations"]["autopay"].astype(str).str.lower().isin(["true", "1"]).astype(int)
    for t, cols in TABLE_COLUMNS.items():
        log.info("writing %s (%d rows)", t, len(cleaned[t]))
        bulk_insert(con, t, cleaned[t], cols)
    issues += load_catalog(con, f["product_catalog"], f["lenders"], legacy_catalog_ids)
    bulk_insert(con, "historical_applications", apps, list(apps.columns))
    bulk_insert(con, "historical_offers", f["offers"], list(f["offers"].columns))
    sim = f["simulator_events"].copy()
    sim["source"] = "dataset"
    bulk_insert(con, "simulator_events", sim, list(sim.columns))
    stats = {"users": len(demo), "rows": {t: len(cleaned[t]) for t in cleaned}, "issues": len(issues),
             "historical_applications": len(apps), "historical_offers": len(f["offers"])}
    audit(con, "ingestion", "system", "ingestion_run", str(run_id), stats)
    _finish_run(con, run_id, issues, stats)
    return {"run_id": run_id, "stats": stats, "issues": issues}


# ---------------------------------------------------------------------------
# Official sample (legacy) format
# ---------------------------------------------------------------------------
def normalize_demographics(records: list, cohort: str, source: str) -> pd.DataFrame:
    df = pd.DataFrame(records)
    if "employment_status" in df:
        df["employment_status"] = df["employment_status"].astype(str).str.strip().str.lower().map(EMPLOYMENT_STATUS_MAP).fillna(df["employment_status"])
    if "education_level" in df:
        df["education_level"] = df["education_level"].astype(str).str.strip().str.lower().map(P.EDUCATION_ALIASES).fillna(df["education_level"])
    for c in ("applicant_id", "housing_status"):
        if c not in df:
            df[c] = None
    df["cohort"] = cohort
    df["source"] = source
    return df


def normalize_transactions(df: pd.DataFrame, source: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Accept either the official sample columns or the v2 columns.

    Returns (transactions, derived_obligations). When the file has no separate
    bill table, bill payments (Rent/Utility Bill/Telecom/Loan EMI debits) are
    turned into obligations using the payment status marker.
    """
    t = df.copy()
    t.columns = [c.strip() for c in t.columns]
    t["date"] = pd.to_datetime(t["date"], errors="coerce", format="mixed").dt.strftime("%Y-%m-%d")
    t["type"] = t["type"].astype(str).str.upper().str.strip()
    if "status" not in t:
        t["status"] = "Completed"
    if "balance_after" not in t:
        t["balance_after"] = np.nan
    if "subtype" not in t:
        t["subtype"] = None
    t["source"] = source
    bills = t[t["category"].isin(LEGACY_BILL_CATEGORIES) & (t["type"] == "DEBIT") & t["date"].notna()].copy()
    due = pd.to_datetime(bills["date"])
    late = bills["status"].astype(str).str.lower() == "late"
    paid = due + pd.to_timedelta(np.where(late, LEGACY_LATE_DAYS, 0), unit="D")
    obl = pd.DataFrame({
        "bill_id": "BILL_" + bills["transaction_id"].astype(str), "user_id": bills["user_id"].values,
        "obligation_type": bills["category"].map(LEGACY_BILL_CATEGORIES).values, "due_date": due.dt.strftime("%Y-%m-%d").values,
        "amount_due": pd.to_numeric(bills["amount"], errors="coerce").values, "paid_date": paid.dt.strftime("%Y-%m-%d").values,
        "amount_paid": pd.to_numeric(bills["amount"], errors="coerce").values,
        "days_past_due": np.where(late, LEGACY_LATE_DAYS, 0), "autopay": 0,
        "status": np.where(late, "Late", "Completed"), "credit_account_id": None, "source": source + ":derived_from_transactions",
    })
    return t, obl


def month_after(last_date: str | None) -> str:
    if not last_date:
        return P.LIVE_AS_OF.isoformat()
    d = pd.Timestamp(last_date)
    return (d + pd.offsets.MonthBegin(1)).strftime("%Y-%m-%d")


def ingest_legacy(con, legacy_dir: Path) -> dict:
    """Ingest the official sample files exactly as provided (no manual preprocessing)."""
    d = Path(legacy_dir)
    run_id = _start_run(con, f"official_sample:{d}")
    demo_raw = json.loads((d / "demographic_data.json").read_text())
    txn_raw = pd.read_csv(d / "transactional_data.csv")
    demo = normalize_demographics(demo_raw, "official_sample", "official_sample")
    demo, issues = validate("demographics", demo)
    users = set(demo.user_id)
    existing = {r["user_id"] for r in rows(con, "SELECT user_id FROM users")}
    clash = users & existing
    if clash:
        issues.append({"file": "demographic_data.json", "check_code": "DQ-04_USER_EXISTS", "severity": "error", "count": len(clash),
                       "row_ref": ",".join(sorted(clash)[:5]), "message": "user_id already ingested; skipped"})
        demo = demo[~demo.user_id.isin(clash)]
        users -= clash
    txn, obl = normalize_transactions(txn_raw, "official_sample")
    txn, iss = validate("transactions", txn, users)
    issues += iss
    obl, iss = validate("obligations", obl, users)
    issues += iss
    last_dates = txn.groupby("user_id")["date"].max().to_dict()
    created = now_iso()
    con.executemany("INSERT INTO users VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        (r["user_id"], r.get("applicant_id"), _clean(r.get("age")), r.get("education_level"), r.get("employment_status"),
         _clean(r.get("monthly_income")), _clean(r.get("city_tier")), None, "official_sample", "official_sample", 1.0,
         month_after(last_dates.get(r["user_id"])), None, run_id, created) for r in demo.to_dict("records")])
    # synthetic, clearly-fake contact placeholders so the anonymisation demo works for this cohort too
    con.executemany("INSERT INTO contacts VALUES (?,?,?,?)", [
        (u, f"Sample Applicant {u[-3:]}", f"+91-00000-{u[-5:].replace('_', '0')}", "Sample city (synthetic)") for u in demo.user_id])
    txn["ingestion_run_id"] = run_id
    obl["ingestion_run_id"] = run_id
    bulk_insert(con, "transactions", txn, TABLE_COLUMNS["transactions"])
    bulk_insert(con, "obligations", obl, TABLE_COLUMNS["obligations"])
    catalog = json.loads((d / "product_catalog.json").read_text())
    issues += load_catalog(con, catalog, None, {p["product_id"] for p in catalog}) if not rows(con, "SELECT 1 FROM products LIMIT 1") else []
    stats = {"users": len(demo), "transactions": len(txn), "derived_obligations": len(obl), "issues": len(issues),
             "assumption": f"Late bill payments treated as paid {LEGACY_LATE_DAYS} days after the transaction date"}
    audit(con, "ingestion", "system", "ingestion_run", str(run_id), stats)
    _finish_run(con, run_id, issues, stats)
    return {"run_id": run_id, "stats": stats, "issues": issues}


# ---------------------------------------------------------------------------
# Single applicant upload (profile creation page)
# ---------------------------------------------------------------------------
def ingest_upload(con, user_id: str, profile: dict, transactions: pd.DataFrame, obligations: pd.DataFrame | None = None) -> dict:
    """Create one applicant from a profile form and an uploaded statement."""
    run_id = _start_run(con, f"upload:{user_id}")
    rec = {"user_id": user_id, "age": profile.get("age"), "education_level": profile.get("education_level"),
           "employment_status": profile.get("employment_status"), "monthly_income": profile.get("monthly_income"),
           "city_tier": profile.get("city_tier"), "applicant_id": profile.get("applicant_id")}
    demo = normalize_demographics([rec], "uploaded", "upload")
    demo, issues = validate("demographics", demo)
    if demo.empty:
        _finish_run(con, run_id, issues, {}, "failed")
        raise ValueError("profile failed validation: " + "; ".join(i["message"] for i in issues))
    transactions = transactions.copy()
    transactions["user_id"] = user_id
    if "transaction_id" not in transactions:
        transactions["transaction_id"] = [f"UPL_{user_id}_{i}" for i in range(len(transactions))]
    else:
        transactions["transaction_id"] = user_id + ":" + transactions["transaction_id"].astype(str)
    txn, derived = normalize_transactions(transactions, "upload")
    txn, iss = validate("transactions", txn, {user_id})
    issues += iss
    if obligations is not None and not obligations.empty:
        obligations = obligations.copy()
        obligations["user_id"] = user_id
        obligations["bill_id"] = user_id + ":" + obligations.get("bill_id", pd.Series(range(len(obligations)))).astype(str)
        obligations["source"] = "upload"
        obl, iss = validate("obligations", obligations, {user_id})
    else:
        obl, iss = validate("obligations", derived, {user_id})
    issues += iss
    errors = [i for i in issues if i["severity"] == "error" and i["check_code"] == "SCHEMA_MISSING_COLUMNS"]
    if errors:
        _finish_run(con, run_id, issues, {}, "failed")
        raise ValueError("; ".join(i["message"] for i in errors))
    as_of = month_after(txn["date"].max() if len(txn) else None)
    r = demo.iloc[0].to_dict()
    con.execute("INSERT INTO users VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        user_id, r.get("applicant_id"), _clean(r.get("age")), r.get("education_level"), r.get("employment_status"),
        _clean(r.get("monthly_income")), _clean(r.get("city_tier")), profile.get("housing_status"), "uploaded", "upload", 1.0,
        as_of, None, run_id, now_iso()))
    con.execute("INSERT INTO contacts VALUES (?,?,?,?)", (user_id, profile.get("display_name") or f"Applicant {user_id[-4:]}",
                                                          profile.get("phone") or "+91-00000-00000", profile.get("locality") or "Synthetic locality"))
    months_job = profile.get("months_in_current_job")
    if profile.get("employment_status") and months_job is not None:
        start = (pd.Timestamp(as_of) - pd.DateOffset(months=int(months_job))).strftime("%Y-%m-%d")
        con.execute("INSERT INTO employment_spells VALUES (?,?,?,?,?,?,?)", (f"SPL_{user_id}", user_id,
                    EMPLOYMENT_STATUS_MAP.get(str(profile["employment_status"]).lower(), profile["employment_status"]), "declared", start, None,
                    _clean(r.get("monthly_income"))))
    if profile.get("housing_status"):
        months_res = int(profile.get("months_at_address") or 0)
        start = (pd.Timestamp(as_of) - pd.DateOffset(months=months_res)).strftime("%Y-%m-%d")
        con.execute("INSERT INTO residence_spells VALUES (?,?,?,?,?,?,?)", (f"RES_{user_id}", user_id, profile["housing_status"],
                    _clean(r.get("city_tier")), profile.get("monthly_rent"), start, None))
    txn["ingestion_run_id"] = run_id
    obl["ingestion_run_id"] = run_id
    bulk_insert(con, "transactions", txn, TABLE_COLUMNS["transactions"])
    bulk_insert(con, "obligations", obl, TABLE_COLUMNS["obligations"])
    stats = {"user_id": user_id, "transactions": len(txn), "obligations": len(obl), "as_of": as_of, "issues": len(issues)}
    audit(con, "ingestion", user_id, "user", user_id, stats)
    _finish_run(con, run_id, issues, stats)
    return {"run_id": run_id, "stats": stats, "issues": issues}


def parse_uploaded_table(content: bytes, filename: str) -> pd.DataFrame:
    name = filename.lower()
    if name.endswith(".json"):
        data = json.loads(content.decode("utf-8"))
        return pd.DataFrame(data if isinstance(data, list) else data.get("transactions", []))
    if name.endswith(".csv"):
        return pd.read_csv(io.BytesIO(content))
    raise ValueError("unsupported file type: upload CSV or JSON (PDF/OCR statements are not supported in this prototype)")


# ---------------------------------------------------------------------------
# SQLite -> UserData (request path)
# ---------------------------------------------------------------------------
def load_user(con, user_id: str) -> UserData | None:
    u = rows(con, "SELECT * FROM users WHERE user_id=?", (user_id,))
    if not u:
        return None
    q = lambda t, extra="": pd.read_sql_query(f"SELECT * FROM {t} WHERE user_id=? {extra}", con, params=(user_id,))
    frames = {
        "demographics": pd.DataFrame(u),
        "transactions": q("transactions", "ORDER BY date, rowid"),
        "obligations": q("obligations", "ORDER BY due_date, rowid"),
        "card_statements": q("card_statements"),
        "credit_accounts": q("credit_accounts"),
        "employment_spells": q("employment_spells"),
        "residence_spells": q("residence_spells"),
        "life_events": q("life_events"),
        "id_mapping": pd.DataFrame([{"user_id": user_id, "match_confidence": u[0]["match_confidence"]}]),
    }
    return build_user(prepare_frames(frames), user_id)


def load_all_users(con, cohorts: tuple | None = None) -> tuple[dict, pd.DataFrame]:
    """Batch path: prepare every applicant from SQLite in one pass."""
    where = f"WHERE cohort IN ({','.join('?' * len(cohorts))})" if cohorts else ""
    params = cohorts or ()
    users = pd.read_sql_query(f"SELECT * FROM users {where}", con, params=params)
    sub = f"WHERE user_id IN (SELECT user_id FROM users {where})" if cohorts else ""
    q = lambda t, order="": pd.read_sql_query(f"SELECT * FROM {t} {sub} {order}", con, params=params)
    frames = {
        "demographics": users,
        "transactions": q("transactions", "ORDER BY user_id, date, rowid"),
        "obligations": q("obligations", "ORDER BY user_id, due_date, rowid"),
        "card_statements": q("card_statements"), "credit_accounts": q("credit_accounts"),
        "employment_spells": q("employment_spells"), "residence_spells": q("residence_spells"), "life_events": q("life_events"),
        "id_mapping": users[["user_id", "match_confidence"]],
    }
    return prepare_frames(frames), users
