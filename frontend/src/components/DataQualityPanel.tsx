import type { DataQuality } from "../types";
import { DQ_TONE } from "../utils/format";
import { Badge } from "./ui";

export function DataQualityPanel({ dq, weakId, blocked }: { dq: DataQuality; weakId?: boolean; blocked?: boolean }) {
  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h2>Data quality</h2>
          <p>How complete the data behind this score is. Missing data never earns points and is never invented.</p>
        </div>
        <Badge tone={DQ_TONE[dq.status]} dot>
          {dq.status}
        </Badge>
      </div>
      <div className="card-body stack">
        <div className="row">
          <div style={{ flex: 1 }}>
            <div className="xs muted">Feature coverage</div>
            <div className="bar" style={{ marginTop: 6 }}>
              <span style={{ width: `${dq.coverage * 100}%` }} />
            </div>
          </div>
          <span className="num small">{Math.round(dq.coverage * 100)}%</span>
          <span className="xs muted">confidence: {dq.confidence}</span>
        </div>
        {blocked && <div className="callout neg small">Identity match is too weak: no product can be offered until identity is confirmed.</div>}
        {weakId && !blocked && <div className="callout warn small">Identity match is weak: offers are withheld until identity is confirmed.</div>}
        {dq.flags.length > 0 ? (
          <ul className="list small">
            {dq.flags.map((f) => (
              <li key={f.code}>
                <span className="mono">{f.code}</span> {f.message}
              </li>
            ))}
          </ul>
        ) : (
          <div className="small muted">No data gaps found.</div>
        )}
        {dq.missing_features.length > 0 && (
          <div className="small">
            Missing inputs: <span className="muted">{dq.missing_features.join(", ")}</span>
          </div>
        )}
        {dq.warnings.map((w) => (
          <div key={w} className="callout warn small">
            {w}
          </div>
        ))}
      </div>
    </div>
  );
}
