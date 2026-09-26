# ML validation layer

The ML layer is **secondary**. It never changes the policy score, tier, eligibility or decision. It produces:

* **Case 1: PD.** The probability of 90+ days past due within 12 months, and from it the **ML Risk Score = round(1000 × (1 − PD))**. That number is always labelled "ML Risk Score (validation)" and is never called the credit score.
* **Agreement status and review flag.** These compare the rule tier with the ML band.
* **Case 2: propensity.** The probability that an applicant accepts an offer for a product. It is used only to order products the applicant is already eligible for, and as an optional lender sort.

Source: `backend/app/ml/` (`features.py`, `models.py`, `training.py`, `agreement.py`). Metrics: `models/*_metrics.json`, `GET /api/ml/metrics`, and the lender Analytics page.

## Models

| | Case 1 PD | Case 2 propensity |
|---|---|---|
| Algorithm | Logistic regression (L2, C=0.3), median impute + missing indicators, standardised | Logistic regression (L2, C=0.5) |
| Target | `default_12m` on approved historical applications | offer accepted vs declined/ignored |
| Features | 28 behavioural values + employment/housing one-hots (`PD_FEATURES`); **no rule score, points, tier or decision** | policy score recomputed at the offer month, margin over product minimum, product one-hots, simulator activity, … |
| Split | temporal: train `application_date < 2025-03-01` (n=3,076), test ≥ (n=1,525) | temporal: train offer date < 2025-12-01 (n=22,848), test ≥ (n=3,905) |
| Test AUC | **0.828** (train 0.840) | **0.617** |
| Comparison | random forest 0.807; policy score alone 0.686 | decision tree 0.612; top-decile lift 2.08× |
| Leakage check | shuffled labels → 0.429 (chance) | |
| Calibration | Brier 0.0745, ECE 0.018; base rate 9.6%, mean predicted 8.2% | Brier 0.101, ECE 0.016 |
| At threshold | 12%: precision 0.26, recall 0.62 (TP 91, FP 260, FN 55, TN 1,119) | 20%: precision 0.24, recall 0.12 |

After holdout evaluation the PD model is refit on all approved historical applications and saved. Deployed predictions use that refit. Models load at startup and are never retrained per request.

Features are computed with the same `compute_features` as the rules, at each application's own date, so nothing dated after the decision is visible. `tests/test_ml.py` checks this directly: appending future-dated records leaves every factor and every PD feature unchanged.

## Agreement matrix

ML bands (D7): Low <5%, Moderate 5–12%, Elevated 12–25%, High ≥25%. The rule side counts as "favourable" in tiers T4/T5.

| Rule | ML Low/Moderate | ML Elevated/High |
|---|---|---|
| T4/T5 | STRONG_AGREEMENT | RULE_ELIGIBLE_ML_ELEVATED → **ENHANCED_REVIEW** |
| T1–T3 | RULE_RISKY_ML_LOWER_RISK (Low; or T1 with Moderate) → **SECOND_LOOK**, otherwise AGREEMENT | STRONG_HIGH_RISK_AGREEMENT |

If the applicant has fewer than 6 months of transactions, or carries `INSUFFICIENT_HISTORY`, `WEAK_ID`, `INCOME_MISSING` or `THIN_REPAYMENT_HISTORY`, or falls outside the training support, the status is `INSUFFICIENT_ML_CONFIDENCE` and no agreement claim is made.

Live population (500 applicants, seeded run): STRONG_AGREEMENT 371, RULE_ELIGIBLE_ML_ELEVATED 91, STRONG_HIGH_RISK_AGREEMENT 28, INSUFFICIENT_ML_CONFIDENCE 8.

## Explanations

Per applicant, the top signals are coefficient × standardised value (log-odds contributions), split into "raises risk" and "lowers risk". They describe the model, not the policy.

## Known model behaviour (read before trusting a single PD)

* **Autopay dominates.** The largest coefficient is `autopay_share` (−1.31 standardised). In the synthetic training data, applicants who use autopay rarely default, so any applicant without autopay gets a large upward push. Two hand-built test applicants show this: a clean payer with no autopay gets a PD of about 30%, higher than a visibly weaker applicant. The rules are unaffected; this is why the ML output is only a review flag.
* **Collinear signs.** Several late-payment features overlap (`late_bills_12m`, `delinquency_events_24m`, `late_under_30_24m`, `on_time_rate`). Individually some coefficients have counter-intuitive signs (for example `late_bills_12m` is negative) while the group as a whole behaves sensibly. Read contributions as a group.
* **Propensity is weak** (AUC 0.62). It orders eligible products and never gates anything.

These are properties of the synthetic data and a deliberately simple interpretable model. They were found during self-testing and are left visible rather than tuned away.
