import type { Bin } from "../types";

export function Histogram({ bins, color = "var(--brand)", format = (b: Bin) => `${b.from}–${b.to}`, highlightFrom }: {
  bins: Bin[];
  color?: string;
  format?: (b: Bin) => string;
  highlightFrom?: number;
}) {
  const max = Math.max(...bins.map((b) => b.count), 1);
  return (
    <div>
      <div className="hist" role="img" aria-label="histogram">
        {bins.map((b) => (
          <div
            key={b.from}
            title={`${format(b)}: ${b.count}`}
            style={{ height: `${(b.count / max) * 100}%`, background: highlightFrom !== undefined && b.from < highlightFrom ? "#c3cfdd" : color }}
          />
        ))}
      </div>
      <div className="hist-axis">
        <span>{format(bins[0] ?? { from: 0, to: 0, count: 0 }).split("–")[0]}</span>
        <span>{bins.length ? format(bins[bins.length - 1]).split("–")[1] : ""}</span>
      </div>
    </div>
  );
}

export function HBars({ items, color, format = (v: number) => String(v) }: {
  items: { label: string; value: number; color?: string; sub?: string }[];
  color?: string;
  format?: (v: number) => string;
}) {
  const max = Math.max(...items.map((i) => i.value), 1e-9);
  return (
    <div>
      {items.map((i) => (
        <div className="hbar" key={i.label}>
          <span title={i.sub}>
            {i.label}
            {i.sub && <span className="xs muted"> {i.sub}</span>}
          </span>
          <div className="bar">
            <span style={{ width: `${(i.value / max) * 100}%`, background: i.color ?? color }} />
          </div>
          <span className="num r small">{format(i.value)}</span>
        </div>
      ))}
    </div>
  );
}

/** Monthly income vs spend bars (from /data-summary). */
export function CashflowChart({ months }: { months: { month: string; income: number; spend: number; discretionary: number }[] }) {
  if (!months.length) return <div className="small muted">No transactions in the last 12 months.</div>;
  const max = Math.max(...months.flatMap((m) => [m.income, m.spend]), 1);
  return (
    <div>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 6, height: 150 }} role="img" aria-label="monthly income and spend">
        {months.map((m) => (
          <div key={m.month} style={{ flex: 1, display: "flex", gap: 2, alignItems: "flex-end", height: "100%" }}
               title={`${m.month}: income ₹${m.income.toLocaleString("en-IN")}, spend ₹${m.spend.toLocaleString("en-IN")}`}>
            <div style={{ flex: 1, height: `${(m.income / max) * 100}%`, background: "var(--pos)", borderRadius: "3px 3px 0 0", minHeight: 1 }} />
            <div style={{ flex: 1, height: `${(m.spend / max) * 100}%`, background: "var(--brand)", borderRadius: "3px 3px 0 0", minHeight: 1, position: "relative" }}>
              <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, height: `${m.spend ? (m.discretionary / m.spend) * 100 : 0}%`, background: "#e0a43a", borderRadius: 0 }} />
            </div>
          </div>
        ))}
      </div>
      <div className="hist-axis">
        <span>{months[0].month}</span>
        <span>{months[months.length - 1].month}</span>
      </div>
      <div className="row xs muted" style={{ marginTop: 6 }}>
        <span><span style={{ display: "inline-block", width: 10, height: 10, background: "var(--pos)", borderRadius: 2 }} /> income</span>
        <span><span style={{ display: "inline-block", width: 10, height: 10, background: "var(--brand)", borderRadius: 2 }} /> spend</span>
        <span><span style={{ display: "inline-block", width: 10, height: 10, background: "#e0a43a", borderRadius: 2 }} /> dining + shopping</span>
      </div>
    </div>
  );
}
