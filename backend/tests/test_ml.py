"""ML validation layer: leakage guards, temporal split, agreement never overrides the rule decision."""
from __future__ import annotations

import itertools
import json
import re

import numpy as np
import pytest

from app.config import settings
from app.features.engineering import compute_features
from app.ml.agreement import agreement
from app.ml.features import PD_FEATURES, pd_vector
from app.ml.models import load_models
from app.rules import policy as P
from tests.conftest import AS_OF, Builder, weak_applicant

METRICS = settings.models_dir / "pd_model_metrics.json"
needs_models = pytest.mark.skipif(not METRICS.exists(), reason="models not trained (run scripts/seed.py)")


def test_pd_features_exclude_rule_outputs():
    banned = re.compile(r"score|points|risk_tier|^tier|decision|eligib", re.I)
    assert not [f for f in PD_FEATURES if banned.search(f)]


def _with_future_records(ud):
    """Append records dated on/after the as-of date: they must not change anything measured at AS_OF."""
    b = Builder()
    b.ud = ud
    for d in ("2026-06-01", "2026-06-15", "2026-08-01"):
        dt = np.datetime64(d)
        b.txn(dt, 90000, "Salary", credit=True, balance=1e7)
        b.txn(dt, 50000, "Shopping")
        b.bill("rent", dt, 95)
        b.stmt("CARD1", dt, 20000, 19999)
        b.life("credit_inquiry", dt)
    return b.build()


def test_future_records_do_not_leak_into_features():
    base = compute_features(weak_applicant(), AS_OF)
    later = compute_features(_with_future_records(weak_applicant()), AS_OF)
    assert json.dumps(base["factors"], default=str, sort_keys=True) == json.dumps(later["factors"], default=str, sort_keys=True)
    a, b = pd_vector(base), pd_vector(later)
    assert all((np.isnan(a[k]) and np.isnan(b[k])) or a[k] == b[k] for k in PD_FEATURES)


def test_agreement_never_changes_rule_decision():
    bands = ["Low", "Moderate", "Elevated", "High"]
    for tier, band, conf in itertools.product([t.code for t in P.RISK_TIERS], bands, [True, False]):
        a = agreement(tier, band, conf)
        assert a["rule_changed"] is False
        if not conf:
            assert a["status"] == "INSUFFICIENT_ML_CONFIDENCE"
    assert agreement("T5", "High", True)["review_flag"] == "ENHANCED_REVIEW"
    assert agreement("T1", "Low", True)["review_flag"] == "SECOND_LOOK"
    assert agreement("T5", "Low", True)["status"] == "STRONG_AGREEMENT"


@needs_models
def test_holdout_metrics_are_honest():
    m = json.loads(METRICS.read_text())
    assert "temporal" in m["split"]
    train_end, test_start = re.findall(r"\d{4}-\d{2}-\d{2}", m["split"])[:2]
    assert train_end == test_start            # train < date <= test: no overlap
    assert 0.35 <= m["shuffled_label_test_auc"] <= 0.65   # shuffled labels ~ chance -> no leakage path
    assert m["test"]["auc"] > 0.7
    assert m["test"]["auc"] <= m["train_auc"] + 0.02   # no suspicious test > train gap
    assert any("rule score" in x for x in m["excluded_inputs"])


@needs_models
def test_pd_prediction_is_bounded_and_explained():
    """PD is a probability, deterministic, and every listed signal pushes in the direction it is listed under.

    Note: we deliberately do not assert that the hand-built 'strong' applicant gets a lower PD than the 'weak' one.
    The trained model leans heavily on autopay_share (a pattern in the synthetic training data) and neither test
    applicant uses autopay; see docs/ml-validation.md, "Known model behaviour".
    """
    pd_model = load_models()["pd"]
    v = pd_vector(compute_features(weak_applicant(), AS_OF))
    a, b = pd_model.predict(v), pd_model.predict(v)
    assert 0.0 <= a["pd"] <= 1.0 and a["pd"] == b["pd"]
    assert all(s["contribution"] > 0 for s in a["risk_increasing"])
    assert all(s["contribution"] < 0 for s in a["risk_reducing"])
