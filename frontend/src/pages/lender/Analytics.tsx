import { useState } from "react";
import { HBars, Histogram } from "../../components/Charts";
import { ErrorBox, Loading, Stat } from "../../components/ui";
import { useApi } from "../../hooks/useApi";
import { AGREEMENT_LABEL, pct } from "../../utils/format";

interface A {
  population: string;
  n: number;
  score_distribution: { from: number; to: number; count: number }[];
  tier_distribution: { tier: string; name: string; color: string; count: number }[];
  product_eligibility: { product_id: string; product_name: string; min_score: number; eligible: number }[];
  ml_pd_distribution: { from: number; to: number; count: number }[];
  agreement: Record<string, number>;
  agreement_rate: number | null;
  propensity_mean: Record<string, number>;
  offer_acceptance_historical: { product_id: string; offers: number; acceptance_rate: number }[];
  offers_in_app: Record<string, number>;
  simulator_usage: { scenario_type: string; source: string; n: number }[];
  historical_default_rate_by_tier: { tier: string; n: number; default_rate: number }[];
  data_quality: Record<string, number>;
}

interface ModelTest {
  auc: number;
  brier: number;
  threshold: number;
  precision: number;
  recall: number;
  confusion_matrix: { tn: number; fp: number; fn: number; tp: number };
  calibration_deciles: { decile: number; n: number; mean_predicted: number; observed_rate: number }[];
  expected_calibration_error: number;
  base_rate: number;
  n: number;
}
interface ModelMetrics {
  model_version: string;
  algorithm: string;
  target: string;
  split: string;
  test: ModelTest;
  train_auc?: number;
  comparison_random_forest_test_auc?: number;
  comparison_decision_tree_test_auc?: number;
  shuffled_label_test_auc?: number;
  rule_score_test_auc?: number;
  lift_top_decile?: number;
  coefficients: { feature: string; label?: string; coef: number }[];
}
interface Metrics {
  pd_model: ModelMetrics | null;
  propensity_model: ModelMetrics | null;
  loaded: { pd: boolean; propensity: boolean };
}

export default function Analytics() {
  const [pop, setPop] = useState<"live" | "historical" | "all_pool">("live");
  const { data: a, error, loading, reload } = useApi<A>(`/api/lenders/analytics?population=${pop}`);
  const m = useApi<Metrics>("/api/ml/metrics");
  const products = Object.fromEntries((a?.product_eligibility ?? []).map((p) => [p.product_id, p.product_name]));
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Analytics</h1>
          <p>Portfolio view of the synthetic population: policy scores, ML validation, product reach and offer behaviour.</p>
        </div>
        <div className="tabs" style={{ margin: 0, border: 0 }}>
          {([["live", "Live applicants"], ["historical", "Historical (with outcomes)"], ["all_pool", "Whole candidate pool"]] as const).map(([k, l]) => (
            <button key={k} className={pop === k ? "active" : ""} onClick={() => setPop(k)}>{l}</button>
          ))}
        </div>
      </div>
      {error && <ErrorBox error={error} onRetry={reload} />}
      {loading && <Loading />}
      {a && !loading && (
        <>
          <div className="grid g4">
            <Stat label="Applicants" value={a.n.toLocaleString("en-IN")} />
            <Stat label="Rule–ML agreement" value={a.agreement_rate === null ? "—" : pct(a.agreement_rate, 0)} sub="among ML-confident applicants" />
            <Stat label="Data quality GOOD" value={pct((a.data_quality.GOOD ?? 0) / Math.max(a.n, 1), 0)} sub={`${a.data_quality.LIMITED ?? 0} limited · ${a.data_quality.POOR ?? 0} poor`} />
            <Stat label="Offers in app" value={Object.values(a.offers_in_app).reduce((x, y) => x + y, 0)} sub={Object.entries(a.offers_in_app).map(([k, v]) => `${v} ${k}`).join(" · ")} />
          </div>
          <div className="grid g2">
            <div className="card">
              <div className="card-head"><div><h2>Policy score distribution</h2><p>50-point bins, 0–1000</p></div></div>
              <div className="card-body"><Histogram bins={a.score_distribution} /></div>
            </div>
            <div className="card">
              <div className="card-head"><h2>Risk tiers</h2></div>
              <div className="card-body">
                <HBars items={a.tier_distribution.map((t) => ({ label: `${t.tier} ${t.name}`, value: t.count, color: t.color }))} format={(v) => v.toLocaleString("en-IN")} />
              </div>
            </div>
            <div className="card">
              <div className="card-head"><h2>Product reach</h2></div>
              <div className="card-body">
                <HBars items={a.product_eligibility.map((p) => ({ label: p.product_name, sub: `≥${p.min_score}`, value: p.eligible }))} format={(v) => `${v.toLocaleString("en-IN")} (${pct(v / Math.max(a.n, 1), 0)})`} />
              </div>
            </div>
            <div className="card ml-card">
              <div className="card-head"><div><h2>ML default probability</h2><p>Validation layer only</p></div></div>
              <div className="card-body stack">
                <Histogram bins={a.ml_pd_distribution} color="var(--ml)" format={(b) => `${pct(b.from, 0)}–${pct(b.to, 0)}`} />
                <HBars items={Object.entries(a.agreement).map(([k, v]) => ({ label: AGREEMENT_LABEL[k] ?? k, value: v, color: "var(--ml)" }))} format={(v) => v.toLocaleString("en-IN")} />
              </div>
            </div>
            {a.historical_default_rate_by_tier.length > 0 && (
              <div className="card">
                <div className="card-head"><div><h2>Observed 12-month default rate by tier</h2><p>Historical applicants, scored as of their application date</p></div></div>
                <div className="card-body">
                  <HBars items={a.historical_default_rate_by_tier.map((h) => ({ label: h.tier, sub: `n=${h.n}`, value: h.default_rate, color: "var(--neg)" }))} format={(v) => pct(v)} />
                </div>
              </div>
            )}
            <div className="card">
              <div className="card-head"><h2>Offer acceptance (historical campaigns)</h2></div>
              <div className="card-body">
                <HBars items={a.offer_acceptance_historical.map((h) => ({ label: products[h.product_id] ?? h.product_id, sub: `${h.offers} offers`, value: h.acceptance_rate, color: "var(--pos)" }))} format={(v) => pct(v)} />
                <div className="divider" />
                <div className="small muted">Mean predicted acceptance (Case 2 model): {Object.entries(a.propensity_mean).map(([k, v]) => `${products[k] ?? k} ${pct(v)}`).join(" · ")}</div>
              </div>
            </div>
            <div className="card">
              <div className="card-head"><h2>What-If simulator usage</h2></div>
              <div className="card-body">
                <HBars items={a.simulator_usage.map((s) => ({ label: s.scenario_type, sub: s.source, value: s.n }))} format={(v) => v.toLocaleString("en-IN")} />
              </div>
            </div>
          </div>
        </>
      )}
      {m.data && <ModelCard m={m.data} />}
    </div>
  );
}

function ModelBlock({ title, m, extra }: { title: string; m: ModelMetrics; extra: [string, number | undefined, number?][] }) {
  const t = m.test;
  const cm = t.confusion_matrix;
  return (
    <div className="stack" style={{ gap: 8 }}>
      <h3>{title} ({m.model_version})</h3>
      <div className="xs muted">{m.algorithm}. Target: {m.target}. Split: {m.split}.</div>
      <dl className="kv small">
        <dt>Holdout AUC</dt><dd>{t.auc.toFixed(3)}{m.train_auc !== undefined && ` (train ${m.train_auc.toFixed(3)})`}</dd>
        {extra.filter(([, v]) => v !== undefined).map(([k, v, d]) => (
          <div key={k} style={{ display: "contents" }}><dt>{k}</dt><dd>{(v as number).toFixed(d ?? 3)}</dd></div>
        ))}
        <dt>Brier · ECE</dt><dd>{t.brier.toFixed(4)} · {t.expected_calibration_error.toFixed(3)}</dd>
        <dt>At threshold {pct(t.threshold, 0)}</dt><dd>precision {t.precision.toFixed(2)} · recall {t.recall.toFixed(2)}</dd>
        <dt>Confusion matrix</dt><dd className="mono">TP {cm.tp} · FP {cm.fp} · FN {cm.fn} · TN {cm.tn}</dd>
        <dt>Base rate · n</dt><dd>{pct(t.base_rate)} · {t.n.toLocaleString("en-IN")}</dd>
      </dl>
      <div className="xs muted">Calibration by decile: observed rate (bar) vs mean predicted (label)</div>
      <HBars items={t.calibration_deciles.map((c) => ({ label: `D${c.decile} · pred ${pct(c.mean_predicted)}`, value: c.observed_rate, color: "var(--ml)" }))} format={(v) => pct(v)} />
      <div className="xs muted">Largest coefficients (standardised): {m.coefficients.slice(0, 5).map((c) => `${c.label ?? c.feature} ${c.coef > 0 ? "+" : ""}${c.coef.toFixed(2)}`).join(" · ")}</div>
    </div>
  );
}

function ModelCard({ m }: { m: Metrics }) {
  return (
    <div className="card ml-card">
      <div className="card-head">
        <div>
          <h2>Model validation</h2>
          <p>Interpretable logistic regressions evaluated on a temporal holdout. Loaded at startup; never retrained per request.</p>
        </div>
      </div>
      <div className="card-body grid g2">
        {m.pd_model ? (
          <ModelBlock title="Case 1 · probability of default" m={m.pd_model} extra={[
            ["Random forest (comparison)", m.pd_model.comparison_random_forest_test_auc],
            ["Shuffled labels (leakage check)", m.pd_model.shuffled_label_test_auc],
            ["Policy score alone", m.pd_model.rule_score_test_auc],
          ]} />
        ) : <div className="small muted">PD model not trained.</div>}
        {m.propensity_model ? (
          <ModelBlock title="Case 2 · offer acceptance" m={m.propensity_model} extra={[
            ["Decision tree (comparison)", m.propensity_model.comparison_decision_tree_test_auc],
            ["Top-decile lift", m.propensity_model.lift_top_decile, 2],
          ]} />
        ) : <div className="small muted">Propensity model not trained.</div>}
      </div>
    </div>
  );
}
