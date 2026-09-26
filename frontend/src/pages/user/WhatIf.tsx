import { useState } from "react";
import { Badge, ErrorBox, Loading, TierBadge } from "../../components/ui";
import { useApi } from "../../hooks/useApi";
import { useUser } from "../../layouts/UserLayout";
import { api } from "../../services/api";
import type { Preset, SimulationResult } from "../../types";
import { date, signed } from "../../utils/format";

type Params = Record<string, unknown>;

interface Custom {
  on: boolean;
  params: Params;
}

const CUSTOM_DEFS: { type: string; label: string; help: string; defaults: Params }[] = [
  { type: "saving_boost", label: "Save more each month", help: "Keep extra money in your account instead of spending it.", defaults: { amount: 1000, months: 3 } },
  { type: "autopay", label: "Turn on autopay", help: "Every selected bill is paid on its due date.", defaults: { bill_types: ["rent", "utility", "telecom"] } },
  { type: "spend_cut", label: "Cut dining & shopping", help: "Reduce discretionary spend by a percentage.", defaults: { pct: 0.2 } },
  { type: "smooth_cashflow", label: "Keep spending steady", help: "Spread large purchases so each month looks similar.", defaults: {} },
  { type: "card_paydown", label: "Pay down card balance", help: "Bring card utilisation down to a target.", defaults: { target_utilization: 0.3 } },
  { type: "recurring_investment", label: "Start a SIP / RD", help: "A monthly recurring investment.", defaults: { amount: 1000 } },
  { type: "overspend", label: "Overspend on lifestyle", help: "Dining + shopping take a share of income.", defaults: { share: 0.75, months: 2 } },
  { type: "delinquency", label: "Pay bills late", help: "A utility bill and rent paid late next month.", defaults: { utility_days: 45, rent_days: 15 } },
  { type: "new_debt", label: "Take a new loan", help: "Adds an EMI and a credit inquiry.", defaults: { emi: 5000 } },
  { type: "employment_change", label: "Start a salaried job", help: "Tenure builds from zero.", defaults: { employment_type: "salaried" } },
];

function NumField({ label, value, onChange, min, max, step = 1, suffix }: { label: string; value: number; onChange: (v: number) => void; min: number; max: number; step?: number; suffix?: string }) {
  return (
    <label className="field xs">
      <span className="row between">
        <span>{label}</span>
        <span className="num">{value.toLocaleString("en-IN")}{suffix}</span>
      </span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  );
}

function ParamEditor({ type, params, set }: { type: string; params: Params; set: (p: Params) => void }) {
  const n = (k: string) => Number(params[k]);
  const upd = (k: string) => (v: number) => set({ ...params, [k]: v });
  switch (type) {
    case "saving_boost":
      return (
        <>
          <NumField label="Extra per month (₹)" value={n("amount")} onChange={upd("amount")} min={500} max={20000} step={500} />
          <NumField label="For months" value={n("months")} onChange={upd("months")} min={1} max={12} />
        </>
      );
    case "autopay": {
      const on = new Set(params.bill_types as string[]);
      return (
        <div className="chip-select">
          {["rent", "utility", "telecom", "emi", "card_min"].map((b) => (
            <button
              type="button"
              key={b}
              className={on.has(b) ? "on" : ""}
              onClick={() => {
                const s = new Set(on);
                if (s.has(b)) s.delete(b);
                else s.add(b);
                set({ bill_types: [...s] });
              }}
            >
              {b === "card_min" ? "card minimum" : b}
            </button>
          ))}
        </div>
      );
    }
    case "spend_cut":
      return <NumField label="Cut" value={Math.round(n("pct") * 100)} onChange={(v) => set({ pct: v / 100 })} min={5} max={50} step={5} suffix="%" />;
    case "card_paydown":
      return <NumField label="Target utilisation" value={Math.round(n("target_utilization") * 100)} onChange={(v) => set({ target_utilization: v / 100 })} min={0} max={90} step={5} suffix="%" />;
    case "recurring_investment":
      return <NumField label="Monthly amount (₹)" value={n("amount")} onChange={upd("amount")} min={500} max={20000} step={500} />;
    case "overspend":
      return (
        <>
          <NumField label="Share of income" value={Math.round(n("share") * 100)} onChange={(v) => set({ ...params, share: v / 100 })} min={30} max={100} step={5} suffix="%" />
          <NumField label="For months" value={n("months")} onChange={upd("months")} min={1} max={6} />
        </>
      );
    case "delinquency":
      return (
        <>
          <NumField label="Utility bill days late" value={n("utility_days")} onChange={upd("utility_days")} min={0} max={120} step={5} />
          <NumField label="Rent days late" value={n("rent_days")} onChange={upd("rent_days")} min={0} max={120} step={5} />
        </>
      );
    case "new_debt":
      return <NumField label="Monthly EMI (₹)" value={n("emi")} onChange={upd("emi")} min={500} max={50000} step={500} />;
    default:
      return null;
  }
}

export default function WhatIf() {
  const { profile, userId } = useUser();
  const presets = useApi<Record<string, Preset>>("/api/simulator/presets");
  const [custom, setCustom] = useState<Record<string, Custom>>(() =>
    Object.fromEntries(CUSTOM_DEFS.map((d) => [d.type, { on: false, params: d.defaults }])),
  );
  const [horizon, setHorizon] = useState(3);
  const [result, setResult] = useState<SimulationResult | null>(null);
  const [running, setRunning] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [title, setTitle] = useState("");

  const run = async (key: string, label: string, scenarios: { type: string; params: Params }[], h: number, preset?: string) => {
    setRunning(key);
    setErr(null);
    try {
      const r = await api<SimulationResult>(`/api/users/${userId}/simulate`, { body: { scenarios, horizon_months: h, preset } });
      setResult(r);
      setTitle(label);
      setTimeout(() => document.getElementById("sim-result")?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(null);
    }
  };

  const selected = Object.entries(custom).filter(([, c]) => c.on);

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>What-If simulator</h1>
          <p>
            Try a change and see how the same 14 rules would score you in the future. Simulations are hypothetical: your history and your stored score are never
            modified. Current policy score: <b className="num">{profile.policy.score}</b>.
          </p>
        </div>
      </div>

      <h2>Official scenarios</h2>
      {presets.error && <ErrorBox error={presets.error} onRetry={presets.reload} />}
      {presets.loading && <Loading />}
      {presets.data && (
        <div className="grid g3">
          {Object.entries(presets.data).map(([k, ps]) => (
            <div key={k} className="card card-pad stack" style={{ gap: 8 }}>
              <div className="row between">
                <h3>{ps.title}</h3>
                <span className="xs muted">{ps.horizon} mo</span>
              </div>
              <p className="small">{ps.description}</p>
              <div className="xs muted">
                Rules affected: {ps.factors.join(", ")}
                {ps.official_example && <> · Use-case example: {ps.official_example}</>}
              </div>
              <div>
                <button className="btn btn-sm btn-primary" disabled={running !== null} onClick={() => run(k, ps.title, ps.scenarios, ps.horizon, k)}>
                  {running === k ? "Simulating…" : "Simulate for me"}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="card">
        <div className="card-head">
          <div>
            <h2>Build your own scenario</h2>
            <p>Combine up to six changes and choose how far ahead to look.</p>
          </div>
        </div>
        <div className="card-body stack">
          <div className="grid g2">
            {CUSTOM_DEFS.map((d) => {
              const c = custom[d.type];
              return (
                <div key={d.type} className="card card-pad stack" style={{ gap: 8, boxShadow: "none", borderColor: c.on ? "var(--brand)" : undefined }}>
                  <label className="checkbox">
                    <input type="checkbox" checked={c.on} onChange={(e) => setCustom({ ...custom, [d.type]: { ...c, on: e.target.checked } })} />
                    <b>{d.label}</b>
                  </label>
                  <div className="xs muted">{d.help}</div>
                  {c.on && <ParamEditor type={d.type} params={c.params} set={(p) => setCustom({ ...custom, [d.type]: { ...c, params: p } })} />}
                </div>
              );
            })}
          </div>
          <div className="row">
            <div style={{ width: 260 }}>
              <NumField label="Look ahead" value={horizon} onChange={setHorizon} min={1} max={12} suffix=" months" />
            </div>
            <button
              className="btn btn-primary"
              disabled={!selected.length || selected.length > 6 || running !== null}
              onClick={() => run("custom", "Your custom scenario", selected.map(([type, c]) => ({ type, params: c.params })), horizon)}
            >
              {running === "custom" ? "Simulating…" : `Simulate ${selected.length || ""} change${selected.length === 1 ? "" : "s"}`}
            </button>
            {selected.length > 6 && <span className="small neg">Pick at most six changes.</span>}
          </div>
        </div>
      </div>

      {err && <ErrorBox error={err} />}
      {result && <SimResult r={result} title={title} />}
    </div>
  );
}

function SimResult({ r, title }: { r: SimulationResult; title: string }) {
  const tone = (d: number) => (d > 0 ? "pos" : d < 0 ? "neg" : "muted");
  return (
    <div className="card" id="sim-result">
      <div className="card-head">
        <div>
          <h2>{title}</h2>
          <p>
            Hypothetical projection to {date(r.simulated_as_of)} ({r.horizon_months} month{r.horizon_months === 1 ? "" : "s"}). Nothing was saved to your history.
          </p>
        </div>
        <Badge tone="brand">Simulation</Badge>
      </div>
      <div className="card-body stack">
        <div className="grid g3">
          <div className="card card-pad" style={{ boxShadow: "none", textAlign: "center" }}>
            <div className="eyebrow">Today</div>
            <div className="big-num">{r.current.score}</div>
            <TierBadge tier={r.current.tier} />
          </div>
          <div className="card card-pad" style={{ boxShadow: "none", textAlign: "center" }}>
            <div className="eyebrow">{r.baseline.label ?? "If nothing changes"}</div>
            <div className="big-num muted">{r.baseline.score}</div>
            <TierBadge tier={r.baseline.tier} />
          </div>
          <div className="card card-pad" style={{ boxShadow: "none", textAlign: "center", borderColor: "var(--brand)" }}>
            <div className="eyebrow">With this change</div>
            <div className="big-num">{r.simulated.score}</div>
            <TierBadge tier={r.simulated.tier} />
          </div>
        </div>
        <div className="row">
          <span>
            Change vs today: <b className={`num ${tone(r.delta_vs_current)}`}>{signed(r.delta_vs_current)}</b>
          </span>
          <span>
            Effect of the change itself (vs doing nothing): <b className={`num ${tone(r.delta_vs_baseline)}`}>{signed(r.delta_vs_baseline)}</b>
          </span>
          {r.raw_delta_vs_current !== r.delta_vs_current && <span className="xs muted">raw change {signed(r.raw_delta_vs_current)} before the 0–1000 cap</span>}
        </div>
        {r.tier_change && <div className="callout">Risk tier: {r.tier_change}</div>}
        {r.products_gained.length > 0 && <div className="callout pos">Unlocks: {r.products_gained.map((p) => p.product_name).join(", ")}</div>}
        {r.products_lost.length > 0 && <div className="callout neg">Would lose eligibility for: {r.products_lost.map((p) => p.product_name).join(", ")}</div>}
        {r.changed_factors.length ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Rule</th>
                  <th className="r">Today</th>
                  <th className="r">No change</th>
                  <th className="r">Scenario</th>
                  <th className="r">Δ vs no change</th>
                  <th>Why</th>
                </tr>
              </thead>
              <tbody>
                {r.changed_factors.map((f) => (
                  <tr key={f.id}>
                    <td>
                      <b>{f.id}</b> {f.name}
                    </td>
                    <td className="r num">{f.current_points}</td>
                    <td className="r num muted">{f.baseline_points}</td>
                    <td className="r num">{f.simulated_points}</td>
                    <td className={`r num ${tone(f.delta_vs_baseline)}`}>{signed(f.delta_vs_baseline)}</td>
                    <td className="small">{f.simulated_text}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="small muted">No rule changes band under this scenario.</div>
        )}
        {r.notes.length > 0 && (
          <ul className="list small muted">
            {r.notes.map((n) => <li key={n}>{n}</li>)}
          </ul>
        )}
        <div className="xs muted">
          Your projected score depends on where you start: rules are banded, so a change moves your score only when it crosses a band edge, and the 0–1000 cap applies.
          This is why results can differ from the use-case's illustrative figures.
        </div>
      </div>
    </div>
  );
}
