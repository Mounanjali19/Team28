import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Badge, ErrorBox, Loading, TierBadge } from "../../components/ui";
import { useUser } from "../../layouts/UserLayout";
import { api } from "../../services/api";
import type { Counterfactual } from "../../types";
import { date, signed } from "../../utils/format";

const EFFORT = ["none", "low", "medium", "high"];

export default function Target() {
  const { profile, userId } = useUser();
  const [params, setParams] = useSearchParams();
  const initial = params.get("product") ?? profile.next_locked_product?.product_id ?? profile.products[profile.products.length - 1]?.product_id ?? "";
  const [product, setProduct] = useState(initial);
  const [cf, setCf] = useState<Counterfactual | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const run = useCallback(
    async (pid: string) => {
      if (!pid) return;
      setBusy(true);
      setErr(null);
      try {
        setCf(await api<Counterfactual>(`/api/users/${userId}/counterfactual`, { body: { product_id: pid } }));
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    },
    [userId],
  );

  useEffect(() => {
    if (params.get("product")) void run(params.get("product")!);
    // run once for a deep link
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Reach a target product</h1>
          <p>
            We search for the smallest realistic change that gets your policy score to a product's minimum, and verify every plan by re-scoring it with the real rules.
            Past behaviour, age and location are never part of a plan.
          </p>
        </div>
      </div>
      <div className="card card-pad row">
        <label className="field" style={{ minWidth: 280, flex: 1 }}>
          Target product
          <select value={product} onChange={(e) => setProduct(e.target.value)}>
            {profile.products.map((p) => (
              <option key={p.product_id} value={p.product_id}>
                {p.product_name} ({p.lender_name}) · min {p.min_score}
                {p.eligible ? " · already eligible" : ` · ${p.gap} pts short`}
              </option>
            ))}
          </select>
        </label>
        <button
          className="btn btn-primary"
          style={{ alignSelf: "flex-end" }}
          disabled={busy || !product}
          onClick={() => {
            setParams({ product });
            void run(product);
          }}
        >
          {busy ? "Searching plans…" : "Find my plan"}
        </button>
      </div>
      {busy && <Loading label="Testing combinations of changes over 1–12 months…" />}
      {err && <ErrorBox error={err} />}
      {cf && !busy && <Plan cf={cf} />}
    </div>
  );
}

function Plan({ cf }: { cf: Counterfactual }) {
  const tone = cf.status === "REACHABLE" || cf.status === "ALREADY_ELIGIBLE" ? "pos" : cf.status === "BLOCKED" ? "neg" : "warn";
  return (
    <div className="stack">
      <div className="card">
        <div className="card-head">
          <div>
            <h2>{cf.product.product_name}</h2>
            <p>
              Your score {cf.current_score} · target {cf.target_score}
              {cf.gap > 0 ? ` · gap ${cf.gap} points` : ""}
            </p>
          </div>
          <Badge tone={tone} dot>
            {cf.status.replace(/_/g, " ").toLowerCase()}
          </Badge>
        </div>
        <div className="card-body stack">
          <p>{cf.message}</p>
          {cf.status === "REACHABLE" && (
            <>
              <div className="compare">
                <div>
                  <div className="eyebrow">Now</div>
                  <div className="big-num">{cf.current_score}</div>
                </div>
                <div className="delta-arrow">→</div>
                <div>
                  <div className="eyebrow">In {cf.horizon_months} month{cf.horizon_months === 1 ? "" : "s"}</div>
                  <div className="big-num pos">{cf.projected_score}</div>
                  {cf.projected_tier && <TierBadge tier={cf.projected_tier} />}
                </div>
              </div>
              {cf.steps && cf.steps.length > 0 ? (
                <ol className="steps">
                  {cf.steps.map((s) => (
                    <li key={s.lever}>
                      <div>
                        <b>{s.action}</b>
                        <div className="xs muted">effort: {EFFORT[s.effort] ?? s.effort}</div>
                      </div>
                      <span className="num pos">{signed(s.expected_points)}</span>
                    </li>
                  ))}
                </ol>
              ) : (
                <div className="callout pos">No action needed: keep your current habits.</div>
              )}
              {!!cf.time_effect_points && (
                <div className="small muted">
                  {signed(cf.time_effect_points)} points come from time passing alone (for example job tenure growing or an old late payment leaving the window).
                  Points per step are measured by removing that step from the plan.
                </div>
              )}
              {cf.factor_changes && cf.factor_changes.length > 0 && (
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr><th>Rule</th><th className="r">Now</th><th className="r">Then</th><th>Result</th></tr>
                    </thead>
                    <tbody>
                      {cf.factor_changes.map((f) => (
                        <tr key={f.id}>
                          <td><b>{f.id}</b> {f.name}</td>
                          <td className="r num">{f.from}</td>
                          <td className="r num">{f.to}</td>
                          <td className="small">{f.text}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <div className="xs muted">✓ {cf.verification} ({cf.evaluations} scenarios evaluated.)</div>
            </>
          )}
          {cf.status === "UNREACHABLE_12M" && cf.best_reachable_score !== undefined && (
            <div className="callout warn">
              Best score reachable within 12 months: <b>{cf.best_reachable_score}</b>
              {cf.best_reachable_product ? `, enough for ${cf.best_reachable_product.product_name}.` : "."}
            </div>
          )}
        </div>
      </div>
      <div className="grid g2">
        <div className="card card-pad stack" style={{ gap: 8 }}>
          <h3>Milestones that happen on their own</h3>
          {cf.milestones.length ? (
            <div className="timeline">
              {cf.milestones.map((m, i) => (
                <div key={i}>
                  <span className="num muted">{date(m.date)}</span>
                  <span>{m.what} <span className="xs muted">(rule {m.factor})</span></span>
                </div>
              ))}
            </div>
          ) : (
            <div className="small muted">No dated milestones ahead.</div>
          )}
          <div className="xs muted">Assumes bills keep being paid on time.</div>
        </div>
        <div className="card card-pad stack" style={{ gap: 8 }}>
          <h3>Never used in a plan</h3>
          <div className="small muted">{cf.immutable_never_changed.join(" · ")}</div>
          <div className="xs muted">Plans never ask you to earn more, buy a home or open new credit.</div>
        </div>
      </div>
    </div>
  );
}
