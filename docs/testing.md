# Testing

```bash
cd backend && ../.venv/bin/python -m pytest -q
```

Result in the build environment: **143 passed** in about 5 s.

| File | What it proves |
|---|---|
| `tests/test_rules.py` (113) | every band edge for all banded rules; housing, education, delinquency, habit cap, flag floor, tier and ML-band edges; max 1320 and clamping. **Independent ground truth**: three applicants built by hand from raw records in `conftest.py`, with every rule's points worked out in comments from the official table (strong: raw 1260 → 1000 capped; weak: 270 T1; missing data: 220, POOR). Also: trace sums to the score, determinism, a single band change moves exactly one rule, identity gates. |
| `tests/test_whatif.py` (19) | direction of all official scenarios (+ new debt) vs the status-quo baseline, for both a strong and a weak applicant; delinquency lowers 3.4 and 3.1 on a clean payer; overspend lowers 2.1; a year of autopay makes 3.1 = 100%; **simulation and counterfactual leave every raw array unchanged**; simulated rows are marked hypothetical; result contract; every counterfactual plan re-scores to its claimed score and uses no immutable lever. |
| `tests/test_ml.py` (5) | PD features contain no rule outputs; future-dated records change no factor and no PD feature; agreement never changes the rule decision for any tier × band × confidence; holdout metrics are temporal, shuffled-label AUC is at chance, test AUC is not above train; PD is a bounded, deterministic probability and its explanations point the right way. |
| `tests/test_api.py` (6) | against a fresh temporary database and the mock bank in-process: health and catalog; authentication, forged token, role separation; bad upload rejected; the **full flow**: register + upload → score (14 records sum to raw score, eligibility = score ≥ minimum, ML Risk Score = 1000 × (1 − PD), `rule_changed` false) → cross-user access blocked → simulation leaves history unchanged → invalid scenario rejected → counterfactual → PDF and JSON → lender sees a masked candidate → cannot push another lender's product → offer → duplicate refused → applicant accepts → contact revealed → bank pre-approval + application without user id or name in the payload → status → audit trail. Bulk offer skips an ineligible applicant; the bank refuses calls without its key. |

## Frontend

```bash
cd frontend && npx tsc --noEmit -p . && npm run build
bash scripts/run.sh &   # from the repo root
cd frontend && PW_CHROMIUM=/opt/pw-browsers/chromium npx playwright test
```

`e2e/critical-flow.spec.ts` (2 tests, passing) drives a real browser against the running stack:

1. As an applicant: dashboard score, factor list, trace, ML tab, an official What-If scenario, a target plan, profile, PDF download, with no console errors.
2. As a lender and an applicant in parallel: masked candidate list, send offer, applicant accepts, the lender now sees the unmasked name, the applicant applies to the bank and checks status.

Every page was also screenshotted at desktop width and one at phone width during the self-audit, and each was checked for console errors.

## Not covered by automated tests

* Visual regression (screens were inspected manually).
* The full seed (`scripts/seed.py`, about 6 minutes on the full datasets). It was run end to end in the build environment; its outputs (row counts, AUCs, demo applicants) are recorded in `data/seed.log` and the README.
