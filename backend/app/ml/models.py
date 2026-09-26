"""Case 1 (PD) and Case 2 (propensity) models: training, evaluation and serving.

Both models are interpretable logistic regressions (scaled inputs, median
imputation with missing-indicators). A shallow random forest / decision tree
is trained alongside purely as a comparison and reported in the metrics; it is
not served. Models are trained once (``scripts/train_ml.py``) and loaded at
API start-up; nothing is retrained per request.
"""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (brier_score_loss, confusion_matrix, precision_score, recall_score, roc_auc_score)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

from app.config import settings
from app.ml.features import FRIENDLY, PD_FEATURES, PROPENSITY_FEATURES

PD_MODEL_VERSION = "pd-logreg-1.0"
PROP_MODEL_VERSION = "propensity-logreg-1.0"


def make_logreg(C=0.3):
    return Pipeline([
        ("impute", SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True)),
        ("scale", StandardScaler()),
        ("clf", LogisticRegression(C=C, max_iter=2000)),
    ])


def calibration_table(y, p, bins=10) -> list[dict]:
    df = pd.DataFrame({"y": y, "p": p})
    df["bin"] = pd.qcut(df.p.rank(method="first"), bins, labels=False)
    out = []
    for b, g in df.groupby("bin"):
        out.append({"decile": int(b) + 1, "n": int(len(g)), "mean_predicted": round(float(g.p.mean()), 4),
                    "observed_rate": round(float(g.y.mean()), 4)})
    return out


def evaluate(y, p, threshold) -> dict:
    pred = (p >= threshold).astype(int)
    cal = calibration_table(y, p)
    ece = float(np.average([abs(c["mean_predicted"] - c["observed_rate"]) for c in cal], weights=[c["n"] for c in cal]))
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    return {"auc": round(float(roc_auc_score(y, p)), 4), "brier": round(float(brier_score_loss(y, p)), 4),
            "threshold": threshold, "precision": round(float(precision_score(y, pred, zero_division=0)), 4),
            "recall": round(float(recall_score(y, pred, zero_division=0)), 4),
            "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
            "calibration_deciles": cal, "expected_calibration_error": round(ece, 4),
            "base_rate": round(float(np.mean(y)), 4), "mean_predicted": round(float(np.mean(p)), 4), "n": int(len(y))}


def _contributions(pipe: Pipeline, X: pd.DataFrame, names: list) -> np.ndarray:
    Z = pipe.named_steps["scale"].transform(pipe.named_steps["impute"].transform(X))
    coef = pipe.named_steps["clf"].coef_[0]
    return Z * coef


class PDModel:
    def __init__(self, bundle: dict):
        self.pipe = bundle["pipe"]
        self.version = bundle["version"]
        self.metrics = bundle["metrics"]
        self.support = bundle.get("support", {})
        imp = self.pipe.named_steps["impute"]
        self.transformed_names = list(PD_FEATURES) + [f"missing:{PD_FEATURES[i]}" for i in imp.indicator_.features_]

    def predict(self, vec: dict) -> dict:
        X = pd.DataFrame([vec])[PD_FEATURES]
        p = float(self.pipe.predict_proba(X)[0, 1])
        contrib = _contributions(self.pipe, X, PD_FEATURES)[0]
        order = np.argsort(-contrib)
        up = [{"feature": self.transformed_names[i], "label": FRIENDLY.get(self.transformed_names[i], self.transformed_names[i]),
               "contribution": round(float(contrib[i]), 3), "value": _fmt(vec.get(self.transformed_names[i]))}
              for i in order[:4] if contrib[i] > 0.05]
        down = [{"feature": self.transformed_names[i], "label": FRIENDLY.get(self.transformed_names[i], self.transformed_names[i]),
                 "contribution": round(float(contrib[i]), 3), "value": _fmt(vec.get(self.transformed_names[i]))}
                for i in order[::-1][:4] if contrib[i] < -0.05]
        return {"pd": p, "risk_increasing": up, "risk_reducing": down}


def _fmt(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    return round(float(v), 4)


class PropensityModel:
    def __init__(self, bundle: dict):
        self.pipe = bundle["pipe"]
        self.version = bundle["version"]
        self.metrics = bundle["metrics"]

    def predict_many(self, vecs: list[dict]) -> list[float]:
        if not vecs:
            return []
        X = pd.DataFrame(vecs)[PROPENSITY_FEATURES]
        return [float(x) for x in self.pipe.predict_proba(X)[:, 1]]


def train_pd(df: pd.DataFrame, split_date: str, band_threshold: float, rule_scores: pd.Series | None = None) -> tuple[dict, dict]:
    """df: one row per historical approved application with PD_FEATURES, default_12m, application_date."""
    train = df[df.application_date < split_date]
    test = df[df.application_date >= split_date]
    Xtr, ytr, Xte, yte = train[PD_FEATURES], train.default_12m.astype(int), test[PD_FEATURES], test.default_12m.astype(int)
    lr = make_logreg().fit(Xtr, ytr)
    p_te = lr.predict_proba(Xte)[:, 1]
    rf = Pipeline([("impute", SimpleImputer(strategy="median", keep_empty_features=True)),
                   ("clf", RandomForestClassifier(n_estimators=300, min_samples_leaf=40, max_depth=8, random_state=7, n_jobs=-1))]).fit(Xtr, ytr)
    p_rf = rf.predict_proba(Xte)[:, 1]
    rng = np.random.default_rng(11)
    shuffled = make_logreg().fit(Xtr, rng.permutation(ytr.values))
    metrics = {
        "model_version": PD_MODEL_VERSION, "algorithm": "LogisticRegression (L2, C=0.3) on standardized, median-imputed features",
        "target": "default_12m (90+ dpd within 12 months of booking), approved historical applications only",
        "split": f"temporal: train application_date < {split_date} (n={len(train)}), test >= {split_date} (n={len(test)})",
        "features": PD_FEATURES, "excluded_inputs": ["rule score", "rule points", "tier", "any post-decision record", "generator latent truth"],
        "test": evaluate(yte.values, p_te, band_threshold),
        "train_auc": round(float(roc_auc_score(ytr, lr.predict_proba(Xtr)[:, 1])), 4),
        "comparison_random_forest_test_auc": round(float(roc_auc_score(yte, p_rf)), 4),
        "shuffled_label_test_auc": round(float(roc_auc_score(yte, shuffled.predict_proba(Xte)[:, 1])), 4),
    }
    if rule_scores is not None:
        rs = rule_scores.reindex(test.index)
        metrics["rule_score_test_auc"] = round(float(roc_auc_score(yte, -rs.values)), 4)
    coef = lr.named_steps["clf"].coef_[0]
    names = list(PD_FEATURES) + [f"missing:{PD_FEATURES[i]}" for i in lr.named_steps["impute"].indicator_.features_]
    metrics["coefficients"] = sorted([{"feature": n, "label": FRIENDLY.get(n, n), "coef": round(float(c), 4)} for n, c in zip(names, coef)],
                                     key=lambda x: -abs(x["coef"]))
    final = make_logreg().fit(df[PD_FEATURES], df.default_12m.astype(int))
    metrics["deployed_model"] = "refit on all approved historical applications after holdout evaluation"
    support = {"min_txn_months": 6}
    return {"pipe": final, "version": PD_MODEL_VERSION, "metrics": metrics, "support": support}, metrics


def train_propensity(df: pd.DataFrame, split_date: str) -> tuple[dict, dict]:
    train = df[df.offer_date < split_date]
    test = df[df.offer_date >= split_date]
    Xtr, ytr, Xte, yte = train[PROPENSITY_FEATURES], train.accepted.astype(int), test[PROPENSITY_FEATURES], test.accepted.astype(int)
    lr = make_logreg(C=0.5).fit(Xtr, ytr)
    p = lr.predict_proba(Xte)[:, 1]
    tree = Pipeline([("impute", SimpleImputer(strategy="median", keep_empty_features=True)),
                     ("clf", DecisionTreeClassifier(max_depth=4, min_samples_leaf=200, random_state=3))]).fit(Xtr, ytr)
    top_decile = pd.Series(p).rank(pct=True) >= 0.9
    metrics = {
        "model_version": PROP_MODEL_VERSION, "algorithm": "LogisticRegression (L2, C=0.5)",
        "target": "offer accepted (1) vs declined/ignored (0)",
        "split": f"temporal: train offer_date < {split_date} (n={len(train)}), test >= {split_date} (n={len(test)})",
        "features": PROPENSITY_FEATURES,
        "note": "Policy score is recomputed by the rule engine as of each offer month (PP-06); the dataset's score_at_offer proxy is not used.",
        "test": evaluate(yte.values, p, 0.2),
        "comparison_decision_tree_test_auc": round(float(roc_auc_score(yte, tree.predict_proba(Xte)[:, 1])), 4),
        "lift_top_decile": round(float(yte.values[top_decile.values].mean() / max(yte.mean(), 1e-9)), 3),
    }
    coef = lr.named_steps["clf"].coef_[0]
    names = list(PROPENSITY_FEATURES) + [f"missing:{PROPENSITY_FEATURES[i]}" for i in lr.named_steps["impute"].indicator_.features_]
    metrics["coefficients"] = sorted([{"feature": n, "coef": round(float(c), 4)} for n, c in zip(names, coef)], key=lambda x: -abs(x["coef"]))
    final = make_logreg(C=0.5).fit(df[PROPENSITY_FEATURES], df.accepted.astype(int))
    return {"pipe": final, "version": PROP_MODEL_VERSION, "metrics": metrics}, metrics


_CACHE: dict = {}


def load_models(models_dir: Path | None = None) -> dict:
    d = Path(models_dir or settings.models_dir)
    key = str(d)
    if key in _CACHE:
        return _CACHE[key]
    out = {"pd": None, "propensity": None}
    if (d / "pd_model.joblib").exists():
        out["pd"] = PDModel(joblib.load(d / "pd_model.joblib"))
    if (d / "propensity_model.joblib").exists():
        out["propensity"] = PropensityModel(joblib.load(d / "propensity_model.joblib"))
    _CACHE[key] = out
    return out


def save_bundle(bundle: dict, name: str, models_dir: Path | None = None):
    d = Path(models_dir or settings.models_dir)
    d.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, d / f"{name}.joblib")
    (d / f"{name}_metrics.json").write_text(json.dumps(bundle["metrics"], indent=2, default=str))
    _CACHE.clear()
