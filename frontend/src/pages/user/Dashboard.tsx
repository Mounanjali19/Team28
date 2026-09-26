import { useState } from "react";
import { Link } from "react-router-dom";
import { ScoreGauge } from "../../components/ScoreGauge";
import { Badge, MLLabel, PolicyLabel, TierBadge, useToast } from "../../components/ui";
import { useUser } from "../../layouts/UserLayout";
import { api } from "../../services/api";
import type { Profile } from "../../types";
import { AGREEMENT_TONE, date, DQ_TONE } from "../../utils/format";

export default function Dashboard() {
  const { profile: p, userId, setProfile } = useUser();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const pol = p.policy;
  const eligible = p.products.filter((x) => x.eligible);

  const refresh = async () => {
    setBusy(true);
    try {
      const np = await api<Profile>(`/api/users/${userId}/score`, { method: "POST" });
      setProfile(np);
      toast(`Recomputed from your raw data: ${np.policy.score} (stored in score history).`);
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Hello, {p.contact?.display_name ?? "there"}</h1>
          <p>
            Score as of {date(pol.as_of)} · {pol.rule_version}
          </p>
        </div>
        <button className="btn" onClick={refresh} disabled={busy}>
          {busy ? "Recomputing…" : "Recompute score"}
        </button>
      </div>

      <div className="card hero">
        <div className="hero-score">
          <PolicyLabel />
          <ScoreGauge score={pol.score} tier={pol.tier} />
          <TierBadge tier={pol.tier} />
          {pol.capped && <div className="xs muted">Raw total {pol.raw_score}, capped at 1000</div>}
        </div>
        <div className="hero-detail">
          <div className="row">
            <Badge tone={pol.decision.code === "ACCEPT" ? "pos" : pol.decision.code === "REJECT" ? "neg" : "warn"} dot>
              {pol.decision.label}
            </Badge>
            <Badge tone={DQ_TONE[pol.data_quality.status]}>Data quality: {pol.data_quality.status}</Badge>
          </div>
          <p>{p.explanation.summary}</p>
          <p className="small">{pol.decision.text}</p>
          <div className="grid g2">
            <div>
              <h3 style={{ marginBottom: 6 }}>Helping your score</h3>
              <ul className="list small">
                {p.explanation.top_positive.map((x) => (
                  <li key={x.factor}>
                    <b>{x.name}</b> <span className="pos num">+{x.points}</span>/{x.max}
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h3 style={{ marginBottom: 6 }}>Costing you the most</h3>
              <ul className="list small">
                {p.explanation.main_reasons.map((x) => (
                  <li key={x.factor}>
                    <b>{x.name}</b> <span className="neg num">−{x.points_lost}</span> possible points
                  </li>
                ))}
              </ul>
            </div>
          </div>
          <div className="row">
            <Link className="btn btn-primary" to="/app/score">See every rule</Link>
            <Link className="btn" to="/app/what-if">Try the What-If simulator</Link>
          </div>
        </div>
      </div>

      <div className="grid g3">
        <div className="card card-pad stack" style={{ gap: 8 }}>
          <div className="eyebrow">Products you qualify for</div>
          <div className="big-num" style={{ fontSize: 30 }}>{eligible.length} <span className="small muted">of {p.products.length}</span></div>
          <div className="small muted">{eligible.map((x) => x.product_name).join(", ") || "None yet"}</div>
          <Link to="/app/products">View products</Link>
        </div>
        <div className="card card-pad stack" style={{ gap: 8 }}>
          <div className="eyebrow">Next product to unlock</div>
          {p.next_locked_product ? (
            <>
              <div style={{ fontWeight: 650 }}>{p.next_locked_product.product_name}</div>
              <div className="small muted">
                Needs {p.next_locked_product.min_score}; you are {p.next_locked_product.gap} points short.
              </div>
              <Link to={`/app/target?product=${p.next_locked_product.product_id}`}>Show me how to get there</Link>
            </>
          ) : (
            <div className="small">You qualify for every product in the catalog.</div>
          )}
        </div>
        <div className="card card-pad stack ml-card" style={{ gap: 8 }}>
          <MLLabel />
          {p.ml.available && p.ml.agreement ? (
            <>
              <div className="row">
                <span className="num" style={{ fontWeight: 650, color: "var(--ml)" }}>ML Risk Score {p.ml.ml_risk_score}</span>
                <Badge tone={AGREEMENT_TONE[p.ml.agreement.status]}>{p.ml.agreement.label}</Badge>
              </div>
              <div className="small muted">{p.ml.agreement.text} It does not change your policy score.</div>
              <Link to="/app/score#ml">How the ML check works</Link>
            </>
          ) : (
            <div className="small muted">ML validation unavailable. Your policy score stands on its own.</div>
          )}
        </div>
      </div>
    </div>
  );
}
