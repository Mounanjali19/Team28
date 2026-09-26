export const inr = (v: number | null | undefined, digits = 0) =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : "₹" + v.toLocaleString("en-IN", { maximumFractionDigits: digits });

export const pct = (v: number | null | undefined, digits = 1) =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : `${(v * 100).toFixed(digits)}%`;

export const signed = (v: number) => (v > 0 ? `+${v}` : `${v}`);

export const date = (s: string | null | undefined) => {
  if (!s) return "—";
  const d = new Date(s.length === 10 ? s + "T00:00:00" : s);
  return Number.isNaN(d.getTime()) ? s : d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
};

export const dateTime = (s: string | null | undefined) => {
  if (!s) return "—";
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? s : d.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
};

export const titleCase = (s: string | null | undefined) =>
  (s ?? "—").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export const AGREEMENT_TONE: Record<string, string> = {
  STRONG_AGREEMENT: "pos",
  AGREEMENT: "pos",
  STRONG_HIGH_RISK_AGREEMENT: "neg",
  RULE_ELIGIBLE_ML_ELEVATED: "warn",
  RULE_RISKY_ML_LOWER_RISK: "brand",
  INSUFFICIENT_ML_CONFIDENCE: "",
};

export const AGREEMENT_LABEL: Record<string, string> = {
  STRONG_AGREEMENT: "Strong agreement",
  AGREEMENT: "Agreement",
  STRONG_HIGH_RISK_AGREEMENT: "Agrees: higher risk",
  RULE_ELIGIBLE_ML_ELEVATED: "ML elevated: enhanced review",
  RULE_RISKY_ML_LOWER_RISK: "ML lower risk: second look",
  INSUFFICIENT_ML_CONFIDENCE: "ML not confident",
};

export const OFFER_TONE: Record<string, string> = {
  sent: "brand",
  viewed: "brand",
  accepted: "pos",
  rejected: "neg",
  expired: "",
  withdrawn: "warn",
};

export const DQ_TONE: Record<string, string> = { GOOD: "pos", LIMITED: "warn", POOR: "neg" };
