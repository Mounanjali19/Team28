"""Build ML training tables from raw data and train the Case 1 / Case 2 models.

Case 1 rows: one per approved historical application, features computed as of
the application date (strictly earlier records only), label default_12m.
Case 2 rows: one per historical offer, features and the recomputed policy score
as of the first day of the offer month (PP-06), label accepted.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from app.config import log
from app.features.builders import build_user
from app.features.engineering import compute_features
from app.features.userdata import d64, month_start
from app.ingestion.pipeline import load_all_users
from app.ml.features import PD_FEATURES, PROPENSITY_FEATURES, pd_vector, propensity_vector
from app.ml.models import save_bundle, train_pd, train_propensity
from app.rules import policy as P
from app.rules.engine import evaluate

PD_SPLIT_DATE = "2025-03-01"          # train 2024-07..2025-02 vintages, test 2025-03..2025-06
PROPENSITY_SPLIT_DATE = "2025-12-01"


def build_pd_table(con, prep) -> pd.DataFrame:
    apps = pd.read_sql_query("""SELECT application_id, user_id, application_date, default_12m, decision
                                FROM historical_applications WHERE decision='approved' AND default_12m IS NOT NULL""", con)
    out = []
    for r in apps.itertuples():
        ud = build_user(prep, r.user_id)
        feats = compute_features(ud, r.application_date)
        rule = evaluate(feats)
        v = pd_vector(feats)
        v.update({"user_id": r.user_id, "application_date": r.application_date, "default_12m": int(r.default_12m),
                  "rule_score": rule["score"]})
        out.append(v)
    return pd.DataFrame(out).set_index("user_id", drop=False)


def build_propensity_table(con, prep) -> pd.DataFrame:
    offers = pd.read_sql_query("SELECT * FROM historical_offers", con)
    products = pd.read_sql_query("SELECT * FROM products", con).set_index("product_id")
    sims = pd.read_sql_query("SELECT user_id, event_ts, event_type, scenario_type, target_product_id FROM simulator_events WHERE source='dataset'", con)
    sims["ts"] = pd.to_datetime(sims.event_ts)
    sims_by_user = {u: g for u, g in sims.groupby("user_id")}
    offers["as_of"] = offers.offer_date.str[:7] + "-01"
    cache = {}
    rows_ = []
    for r in offers.itertuples():
        key = (r.user_id, r.as_of)
        if key not in cache:
            ud = build_user(prep, r.user_id)
            feats = compute_features(ud, r.as_of)
            cache[key] = (feats, evaluate(feats)["score"])
        feats, score = cache[key]
        g = sims_by_user.get(r.user_id)
        od = pd.Timestamp(r.offer_date)
        if g is not None:
            w = g[(g.ts < od) & (g.ts >= od - pd.Timedelta(days=90))]
            intent = {"simulate": int((w.event_type == "simulate").sum()), "catalog_view": int((w.event_type == "catalog_view").sum()),
                      "target_match": int((w.target_product_id == r.product_id).sum()), "scenarios": int(w.scenario_type.nunique())}
        else:
            intent = {}
        prod = products.loc[r.product_id].to_dict() | {"product_id": r.product_id}
        v = propensity_vector(score, prod, feats, {"rate": r.offered_rate, "amount": r.offered_amount, "channel": r.channel,
                                                   "campaign_type": r.campaign_type}, intent)
        v.update({"offer_id": r.offer_id, "user_id": r.user_id, "offer_date": r.offer_date, "accepted": int(r.response == "accepted")})
        rows_.append(v)
    log.info("propensity table: %d offers, %d distinct (user, month) scorings", len(rows_), len(cache))
    return pd.DataFrame(rows_)


def train_all(con, models_dir=None) -> dict:
    t = time.time()
    prep, users = load_all_users(con, ("historical",))
    log.info("loaded historical applicants in %.1fs", time.time() - t)
    pd_df = build_pd_table(con, prep)
    log.info("PD table %s built in %.1fs", pd_df.shape, time.time() - t)
    threshold = P.ML_PD_BANDS[1][0]   # 'Elevated' band edge used for precision/recall reporting
    bundle, pd_metrics = train_pd(pd_df, PD_SPLIT_DATE, threshold, pd_df["rule_score"])
    save_bundle(bundle, "pd_model", models_dir)
    prop_df = build_propensity_table(con, prep)
    log.info("propensity table %s built in %.1fs", prop_df.shape, time.time() - t)
    pbundle, prop_metrics = train_propensity(prop_df, PROPENSITY_SPLIT_DATE)
    save_bundle(pbundle, "propensity_model", models_dir)
    return {"pd": pd_metrics, "propensity": prop_metrics, "pd_rows": len(pd_df), "propensity_rows": len(prop_df),
            "seconds": round(time.time() - t, 1)}
