// Response shapes of the AltCredit API (see backend/app/services.py and docs/api.md).

export interface Tier {
  code: string;
  name: string;
  color: string;
  meaning: string;
  min: number;
  max: number;
}

export interface Factor {
  id: string;
  name: string;
  component: string;
  points: number;
  max: number;
  min: number;
  band: string | null;
  value: unknown;
  value_display: string;
  status: string;
  text: string;
  evidence: Record<string, unknown>;
  note: string | null;
  effect: "positive" | "negative" | "neutral";
  points_lost: number;
}

export interface DataQuality {
  status: "GOOD" | "LIMITED" | "POOR";
  coverage: number;
  missing_features: string[];
  warnings: string[];
  flags: { code: string; message?: string; severity?: string }[];
  confidence: string;
}

export interface Policy {
  label: string;
  rule_version: string;
  as_of: string;
  score: number;
  raw_score: number;
  capped: boolean;
  floored: boolean;
  tier: Tier;
  positive_points: number;
  negative_points: number;
  points_lost: number;
  components: Record<string, { points: number; max: number }>;
  factors: Factor[];
  income: { value: number | null; source: string; declared: number | null; verified: number | null };
  data_quality: DataQuality;
  identity_blocked: boolean;
  weak_id: boolean;
  open_decisions: Record<string, string | number>;
  decision: { code: string; label: string; text: string };
  trace: string[];
}

export interface Product {
  product_id: string;
  product_name: string;
  type: string;
  min_score: number;
  applicant_score: number;
  eligible: boolean;
  gap: number;
  interest_rate: string;
  interest_rate_pct: number;
  amount_min: number | null;
  amount_max: number | null;
  tenure_months: number | null;
  annual_fee: number | null;
  segment: string;
  lender_id: string;
  lender_name: string;
  official: boolean;
  reason: string;
  propensity?: number | null;
  rank?: number;
  why_recommended?: string;
  ordering_basis?: string;
}

export interface Signal {
  feature: string;
  label: string;
  contribution: number;
  value: number | null;
}

export interface MLValidation {
  available: boolean;
  label: string;
  model_version?: string;
  pd?: number;
  pd_pct?: number;
  ml_risk_score?: number;
  ml_risk_score_label?: string;
  band?: string;
  confident?: boolean;
  confidence?: string;
  confidence_reasons?: string[];
  agreement?: { status: string; label: string; text: string; review_flag: string; rule_changed: boolean };
  risk_increasing_signals?: Signal[];
  risk_reducing_signals?: Signal[];
  text?: string;
  holdout_auc?: number;
  reason?: string;
}

export interface Contact {
  display_name: string;
  phone: string;
  locality: string;
  masked: boolean;
}

export interface Profile {
  user_id: string;
  cohort: string;
  as_of: string;
  demo_label: string | null;
  policy: Policy;
  explanation: {
    summary: string;
    label: string;
    score_increased_because: string[];
    score_decreased_because: string[];
    main_reasons: { factor: string; name: string; points_lost: number; text: string }[];
    top_positive: { factor: string; name: string; points: number; max: number; text: string }[];
    top_negative: { factor: string; name: string; points: number; max: number; points_lost: number; text: string }[];
  };
  products: Product[];
  recommendations: Product[];
  next_locked_product: Product | null;
  ml: MLValidation;
  propensity: Record<string, number>;
  timing_ms: Record<string, number>;
  generated_at: string;
  contact?: Contact;
  offers_from_you?: Offer[];
  own_products?: Product[];
}

export interface FactorChange {
  id: string;
  name: string;
  current_points: number;
  baseline_points: number;
  simulated_points: number;
  delta_vs_current: number;
  delta_vs_baseline: number;
  current_value: string;
  simulated_value: string;
  simulated_text: string;
}

export interface ScoreAt {
  score: number;
  raw_score?: number;
  tier: Tier;
  eligible_products: string[];
  label?: string;
}

export interface SimulationResult {
  hypothetical: boolean;
  scenarios: { type: string; params: Record<string, unknown> }[];
  horizon_months: number;
  as_of: string;
  simulated_as_of: string;
  current: ScoreAt;
  baseline: ScoreAt;
  simulated: ScoreAt;
  delta_vs_current: number;
  delta_vs_baseline: number;
  raw_delta_vs_current: number;
  tier_change: string | null;
  products_gained: { product_id: string; product_name: string }[];
  products_lost: { product_id: string; product_name: string }[];
  factor_changes: FactorChange[];
  changed_factors: FactorChange[];
  notes: string[];
  rule_version: string;
}

export interface Preset {
  title: string;
  description: string;
  scenarios: { type: string; params: Record<string, unknown> }[];
  horizon: number;
  official_example: string | null;
  factors: string[];
}

export interface Counterfactual {
  product: { product_id: string; product_name: string; min_score: number };
  current_score: number;
  target_score: number;
  gap: number;
  status: "ALREADY_ELIGIBLE" | "BLOCKED" | "REACHABLE" | "UNREACHABLE_12M";
  reachable: boolean;
  message: string;
  immutable_never_changed: string[];
  milestones: { date: string; what: string; factor: string }[];
  horizon_months?: number;
  projected_score?: number;
  projected_tier?: Tier;
  baseline_score_at_horizon?: number;
  time_effect_points?: number;
  steps?: { lever: string; params: Record<string, unknown>; action: string; expected_points: number; effort: number }[];
  factor_changes?: { id: string; name: string; from: number; to: number; delta: number; text: string }[];
  evaluations?: number;
  verification?: string;
  best_reachable_score?: number;
  best_reachable_product?: { product_id: string; product_name: string } | null;
}

export interface Offer {
  offer_id: string;
  user_id: string;
  lender_id: string;
  product_id: string;
  interest_rate: number | null;
  amount: number | null;
  message: string | null;
  status: "sent" | "viewed" | "accepted" | "rejected" | "expired" | "withdrawn";
  campaign_id: string | null;
  score_at_offer: number | null;
  propensity: number | null;
  created_at: string;
  expires_at: string | null;
  responded_at: string | null;
  product_name?: string;
  product_type?: string;
  min_score?: number;
  lender_name?: string;
  tier?: string;
  contact?: Contact;
}

export interface BankApplication {
  id: number;
  user_id: string;
  product_id: string;
  product_name?: string;
  offer_id: string | null;
  bank_reference: string | null;
  status: string;
  preapproval_id: string | null;
  created_at: string;
  updated_at: string;
  response_json?: string;
  bank?: Record<string, unknown>;
}

export interface Candidate {
  user_id: string;
  age: number | null;
  employment_status: string | null;
  monthly_income: number | null;
  city_tier: number | null;
  housing_status: string | null;
  cohort: string;
  match_confidence: number;
  score: number;
  raw_score: number;
  tier: string;
  decision: string;
  data_quality: string;
  pd: number | null;
  ml_band: string | null;
  agreement_status: string | null;
  review_flag: string | null;
  ml_confidence: string | null;
  offer_status: string | null;
  eligible_products: string[];
  propensity_own_products: Record<string, number>;
  best_propensity: number | null;
  weak_id: boolean;
  contact: Contact;
}

export interface Bin {
  from: number;
  to: number;
  count: number;
}

export interface PolicySnapshot {
  rule_version: string;
  open_decisions: Record<string, string | number>;
  tiers: { code: string; name: string; min_score: number; max_score: number; color: string; meaning: string }[];
  ml_pd_bands: [number, string][];
  lender_default_score_range: [number, number];
  factor_names: Record<string, string>;
  factor_max: Record<string, number>;
}

export interface CatalogProduct {
  product_id: string;
  product_name: string;
  type: string;
  min_score: number;
  interest_rate: string;
  interest_rate_pct: number;
  amount_min: number | null;
  amount_max: number | null;
  lender_id: string;
  lender_name: string;
  segment: string;
  official: boolean;
  annual_fee: number | null;
  tenure_months: number | null;
}
