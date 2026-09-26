import { useState } from "react";
import type { Factor, Policy } from "../types";
import { signed } from "../utils/format";

const ORDER = ["Lifestyle", "Spending Behaviour", "Repayment Discipline", "Bonus / Penalty"];

function FactorRow({ f, showEvidence }: { f: Factor; showEvidence: boolean }) {
  const [open, setOpen] = useState(false);
  const isPenalty = f.max === 0;
  const width = isPenalty ? (f.min ? (Math.abs(f.points) / Math.abs(f.min)) * 100 : 0) : f.max ? (Math.max(f.points, 0) / f.max) * 100 : 0;
  const tone = isPenalty ? (f.points < 0 ? "neg" : "neutral") : f.effect === "positive" ? "pos" : f.effect === "negative" ? "neg" : "";
  return (
    <div>
      <div className="factor">
        <div className="factor-name">
          {f.id} {f.name}
          <div className="xs muted">{f.value_display}</div>
        </div>
        <div>
          <div className={`bar ${tone}`}>
            <span style={{ width: `${Math.min(100, width)}%` }} />
          </div>
          <div className="xs muted" style={{ marginTop: 4 }}>
            {f.text}
            {showEvidence && (
              <>
                {" "}
                <button className="link-btn xs" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
                  {open ? "hide evidence" : "evidence"}
                </button>
              </>
            )}
          </div>
        </div>
        <div className="pts">
          <span className={f.points < 0 ? "neg" : ""}>{isPenalty ? signed(f.points) : f.points}</span>
          <div className="xs muted">{isPenalty ? `min ${f.min}` : `/ ${f.max}`}</div>
        </div>
      </div>
      {open && (
        <pre className="mono" style={{ background: "var(--sunk)", padding: 10, borderRadius: 6, overflowX: "auto", margin: "0 0 10px" }}>
          {JSON.stringify({ band: f.band, status: f.status, evidence: f.evidence, note: f.note }, null, 2)}
        </pre>
      )}
    </div>
  );
}

export function FactorBreakdown({ policy, showEvidence = true }: { policy: Policy; showEvidence?: boolean }) {
  const groups = ORDER.filter((c) => policy.components[c]);
  return (
    <div>
      {groups.map((c) => (
        <div key={c}>
          <div className="component-head">
            <h3>{c}</h3>
            <span className="num small">
              <b>{policy.components[c].points}</b> <span className="muted">/ {policy.components[c].max}</span>
            </span>
          </div>
          {policy.factors
            .filter((f) => f.component === c)
            .map((f) => (
              <FactorRow key={f.id} f={f} showEvidence={showEvidence} />
            ))}
        </div>
      ))}
    </div>
  );
}
