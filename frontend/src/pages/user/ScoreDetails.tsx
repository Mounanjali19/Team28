import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { DataQualityPanel } from "../../components/DataQualityPanel";
import { FactorBreakdown } from "../../components/FactorBreakdown";
import { MLValidationPanel } from "../../components/MLValidationPanel";
import { PolicyLabel, TierBadge } from "../../components/ui";
import { useUser } from "../../layouts/UserLayout";

export default function ScoreDetails() {
  const { profile: p } = useUser();
  const pol = p.policy;
  const loc = useLocation();
  const [tab, setTab] = useState<"factors" | "trace" | "ml" | "quality">(loc.hash === "#ml" ? "ml" : "factors");
  useEffect(() => {
    if (loc.hash === "#ml") setTab("ml");
  }, [loc.hash]);

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <PolicyLabel />
          <h1 style={{ marginTop: 4 }}>
            Your score: <span className="num">{pol.score}</span> / 1000
          </h1>
          <p>
            Sum of 14 published rules. Positive points {pol.positive_points}, penalties {pol.negative_points}, raw total {pol.raw_score}
            {pol.capped ? " (capped at 1000)" : pol.floored ? " (floored at 0)" : ""}.
          </p>
        </div>
        <TierBadge tier={pol.tier} />
      </div>

      <div className="tabs" role="tablist">
        {([
          ["factors", "Factor analysis"],
          ["trace", "Score trace"],
          ["ml", "ML validation"],
          ["quality", "Data quality"],
        ] as const).map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "active" : ""} onClick={() => setTab(k)}>
            {l}
          </button>
        ))}
      </div>

      {tab === "factors" && (
        <div className="grid" style={{ gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr)" }}>
          <div className="card card-body">
            <FactorBreakdown policy={pol} />
          </div>
          <div className="stack">
            <div className="card card-pad stack" style={{ gap: 8 }}>
              <h3>Why your score went up</h3>
              <ul className="list small">
                {p.explanation.score_increased_because.map((t) => <li key={t}>{t}</li>)}
              </ul>
            </div>
            <div className="card card-pad stack" style={{ gap: 8 }}>
              <h3>Why it is not higher</h3>
              <ul className="list small">
                {p.explanation.score_decreased_because.length
                  ? p.explanation.score_decreased_because.map((t) => <li key={t}>{t}</li>)
                  : <li>Nothing is holding your score back.</li>}
              </ul>
            </div>
            <div className="callout small">
              Rules follow the official AltCredit scoring table. Where the table was silent, the defaults recorded in rulebook v0.1 apply (for example: no grace
              days on bills, each late bill counted separately). See the Profile page for the full list.
            </div>
          </div>
        </div>
      )}

      {tab === "trace" && (
        <div className="card">
          <div className="card-head">
            <div>
              <h2>Score trace</h2>
              <p>Exactly how the engine added up your score. Re-running the same data always gives the same result.</p>
            </div>
          </div>
          <div className="card-body">
            <ol className="mono" style={{ margin: 0, paddingLeft: 22, lineHeight: 1.9 }}>
              {pol.trace.map((l, i) => <li key={i}>{l}</li>)}
            </ol>
            <div className="divider" />
            <div className="xs muted">
              Computed in {p.timing_ms.rule_engine} ms (rules) / {p.timing_ms.total} ms (total) · generated {p.generated_at}
            </div>
          </div>
        </div>
      )}

      {tab === "ml" && (
        <div id="ml" className="stack">
          <MLValidationPanel ml={p.ml} policy={pol} />
          <div className="callout small">
            The <b>policy score</b> above decides eligibility. The <b>ML Risk Score</b> comes from a separate statistical model trained on past repayment outcomes.
            When the two disagree, a lender may review your application more closely, but the model cannot raise or lower your score.
          </div>
        </div>
      )}

      {tab === "quality" && <DataQualityPanel dq={pol.data_quality} weakId={pol.weak_id} blocked={pol.identity_blocked} />}
    </div>
  );
}
