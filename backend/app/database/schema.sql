-- AltCredit SQLite schema. Raw source tables keep their original columns plus
-- provenance (source, ingestion_run_id). Derived tables (scores, factors, ML
-- predictions) are append-only so score history is retained.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    source        TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    status        TEXT NOT NULL,
    stats_json    TEXT
);
CREATE TABLE IF NOT EXISTS ingestion_errors (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        INTEGER REFERENCES ingestion_runs(run_id),
    file          TEXT, check_code TEXT, severity TEXT, row_ref TEXT, message TEXT, count INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS users (
    user_id            TEXT PRIMARY KEY,
    applicant_id       TEXT,
    age                INTEGER,
    education_level    TEXT,
    employment_status  TEXT,
    monthly_income     REAL,
    city_tier          INTEGER,
    housing_status     TEXT,
    cohort             TEXT NOT NULL,      -- historical | live | official_sample | uploaded
    source             TEXT NOT NULL,
    match_confidence   REAL DEFAULT 1.0,
    as_of_date         TEXT NOT NULL,      -- scoring date convention (T-01)
    demo_label         TEXT,
    ingestion_run_id   INTEGER,
    created_at         TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS contacts (
    user_id       TEXT PRIMARY KEY REFERENCES users(user_id),
    display_name  TEXT, phone TEXT, locality TEXT
);
CREATE TABLE IF NOT EXISTS employment_spells (
    spell_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(user_id), employment_type TEXT, employer_category TEXT,
    start_date TEXT, end_date TEXT, declared_income REAL
);
CREATE TABLE IF NOT EXISTS residence_spells (
    spell_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(user_id), housing_status TEXT, city_tier INTEGER,
    monthly_rent REAL, start_date TEXT, end_date TEXT
);
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id TEXT, user_id TEXT NOT NULL, date TEXT NOT NULL, amount REAL NOT NULL, category TEXT NOT NULL,
    type TEXT NOT NULL, status TEXT, balance_after REAL, subtype TEXT, source TEXT, ingestion_run_id INTEGER
);
CREATE INDEX IF NOT EXISTS ix_txn_user_date ON transactions(user_id, date);
CREATE TABLE IF NOT EXISTS obligations (
    bill_id TEXT, user_id TEXT NOT NULL, obligation_type TEXT NOT NULL, due_date TEXT NOT NULL, amount_due REAL,
    paid_date TEXT, amount_paid REAL, days_past_due INTEGER, autopay INTEGER, status TEXT, credit_account_id TEXT,
    source TEXT, ingestion_run_id INTEGER
);
CREATE INDEX IF NOT EXISTS ix_obl_user_due ON obligations(user_id, due_date);
CREATE TABLE IF NOT EXISTS credit_accounts (
    credit_account_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, account_type TEXT, lender_type TEXT,
    limit_or_principal REAL, emi REAL, open_date TEXT, close_date TEXT
);
CREATE INDEX IF NOT EXISTS ix_acc_user ON credit_accounts(user_id);
CREATE TABLE IF NOT EXISTS card_statements (
    account_id TEXT, user_id TEXT NOT NULL, statement_month TEXT, credit_limit REAL, opening_balance REAL, card_spend REAL,
    payment_amount REAL, outstanding_balance REAL, minimum_due REAL, payment_status TEXT, utilization REAL
);
CREATE INDEX IF NOT EXISTS ix_stmt_user ON card_statements(user_id);
CREATE TABLE IF NOT EXISTS life_events (
    event_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, event_type TEXT, event_date TEXT
);
CREATE INDEX IF NOT EXISTS ix_life_user ON life_events(user_id);

CREATE TABLE IF NOT EXISTS lenders (
    lender_id TEXT PRIMARY KEY, lender_name TEXT NOT NULL, lender_type TEXT
);
CREATE TABLE IF NOT EXISTS products (
    product_id TEXT PRIMARY KEY, product_name TEXT NOT NULL, type TEXT NOT NULL, min_score INTEGER NOT NULL,
    interest_rate TEXT, interest_rate_pct REAL, amount_min REAL, amount_max REAL, tenure_months REAL,
    annual_fee REAL, segment TEXT, lender_id TEXT REFERENCES lenders(lender_id), official INTEGER DEFAULT 1
);

-- Historical outcome data (Case 1 / Case 2 training only)
CREATE TABLE IF NOT EXISTS historical_applications (
    application_id TEXT PRIMARY KEY, user_id TEXT, application_date TEXT, requested_product_id TEXT, booked_product_id TEXT,
    decision TEXT, decline_reason TEXT, booked_amount REAL, tenure_months REAL, default_12m REAL, default_month REAL,
    observation_end_date TEXT
);
CREATE TABLE IF NOT EXISTS historical_offers (
    offer_id TEXT PRIMARY KEY, user_id TEXT, product_id TEXT, lender_id TEXT, offer_date TEXT, expiry_date TEXT, channel TEXT,
    campaign_type TEXT, offered_rate REAL, offered_amount REAL, score_at_offer REAL, eligible TEXT, response TEXT,
    response_date TEXT, time_to_accept_days REAL, booked TEXT
);
CREATE INDEX IF NOT EXISTS ix_hoff_user ON historical_offers(user_id);
CREATE TABLE IF NOT EXISTS simulator_events (
    event_id TEXT PRIMARY KEY, user_id TEXT, event_ts TEXT, session_id TEXT, event_type TEXT, scenario_type TEXT,
    target_product_id TEXT, simulated_score_delta REAL, source TEXT DEFAULT 'dataset', detail_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_sim_user ON simulator_events(user_id);

-- Derived: rule scores (authoritative) and ML predictions (secondary)
CREATE TABLE IF NOT EXISTS scores (
    score_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL REFERENCES users(user_id), as_of TEXT NOT NULL,
    score INTEGER NOT NULL, raw_score INTEGER NOT NULL, tier TEXT NOT NULL, decision TEXT NOT NULL,
    data_quality TEXT, rule_version TEXT NOT NULL, trigger TEXT, computed_at TEXT NOT NULL, latency_ms REAL,
    is_current INTEGER DEFAULT 1, result_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_scores_user ON scores(user_id, is_current);
CREATE TABLE IF NOT EXISTS score_factors (
    score_id INTEGER REFERENCES scores(score_id), factor_id TEXT, points INTEGER, max_points INTEGER, band TEXT,
    value_display TEXT, status TEXT
);
CREATE INDEX IF NOT EXISTS ix_sf_score ON score_factors(score_id);
CREATE TABLE IF NOT EXISTS ml_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, score_id INTEGER, model_version TEXT NOT NULL,
    pd REAL, ml_risk_score INTEGER, ml_band TEXT, confidence TEXT, agreement_status TEXT, review_flag TEXT,
    detail_json TEXT, computed_at TEXT NOT NULL, is_current INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_ml_user ON ml_predictions(user_id, is_current);

-- Lender offers and the offer lifecycle
CREATE TABLE IF NOT EXISTS campaigns (
    campaign_id TEXT PRIMARY KEY, lender_id TEXT, name TEXT, product_id TEXT, created_at TEXT, n_targeted INTEGER, n_sent INTEGER
);
CREATE TABLE IF NOT EXISTS offers (
    offer_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(user_id), lender_id TEXT NOT NULL, product_id TEXT NOT NULL,
    interest_rate REAL, amount REAL, message TEXT, status TEXT NOT NULL, campaign_id TEXT,
    score_at_offer INTEGER, propensity REAL, created_at TEXT NOT NULL, expires_at TEXT, responded_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_offers_user ON offers(user_id);
CREATE INDEX IF NOT EXISTS ix_offers_lender ON offers(lender_id);
CREATE TABLE IF NOT EXISTS offer_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, offer_id TEXT, event TEXT, actor TEXT, ts TEXT, detail_json TEXT
);
CREATE TABLE IF NOT EXISTS bank_applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, product_id TEXT, offer_id TEXT, bank_reference TEXT,
    status TEXT, preapproval_id TEXT, created_at TEXT, updated_at TEXT, response_json TEXT
);
CREATE TABLE IF NOT EXISTS counterfactual_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, product_id TEXT, current_score INTEGER, target_score INTEGER,
    reachable INTEGER, result_json TEXT, created_at TEXT
);

-- Auth and audit
CREATE TABLE IF NOT EXISTS auth_accounts (
    username TEXT PRIMARY KEY, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK (role IN ('user','lender','admin')),
    user_id TEXT, lender_id TEXT, display_name TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, actor TEXT, action TEXT NOT NULL, entity TEXT, entity_id TEXT,
    rule_version TEXT, model_version TEXT, detail_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_audit_entity ON audit_logs(entity, entity_id);
CREATE TABLE IF NOT EXISTS reveals (
    user_id TEXT, lender_id TEXT, offer_id TEXT, revealed_at TEXT, PRIMARY KEY (user_id, lender_id)
);
