import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Badge, Empty, ErrorBox, Loading, Modal, TierBadge, useToast } from "../../components/ui";
import { useApi } from "../../hooks/useApi";
import { useAuth } from "../../hooks/useAuth";
import { api } from "../../services/api";
import type { Candidate, CatalogProduct, PolicySnapshot } from "../../types";
import { AGREEMENT_LABEL, AGREEMENT_TONE, DQ_TONE, inr, pct, titleCase } from "../../utils/format";

interface Page {
  total: number;
  page: number;
  page_size: number;
  items: Candidate[];
}


function Chips({ options, value, onChange, labels }: { options: string[]; value: string[]; onChange: (v: string[]) => void; labels?: Record<string, string> }) {
  return (
    <div className="chip-select">
      {options.map((o) => (
        <button
          type="button"
          key={o}
          className={value.includes(o) ? "on" : ""}
          onClick={() => onChange(value.includes(o) ? value.filter((x) => x !== o) : [...value, o])}
        >
          {labels?.[o] ?? o}
        </button>
      ))}
    </div>
  );
}

export default function Candidates({ base = "/lender" }: { base?: string }) {
  const { session } = useAuth();
  const [sp, setSp] = useSearchParams();
  const nav = useNavigate();
  const toast = useToast();
  const policy = useApi<PolicySnapshot>("/api/policy");
  const catalog = useApi<CatalogProduct[]>("/api/products");
  const [defLo, defHi] = policy.data?.lender_default_score_range ?? [650, 1000];

  const query = useMemo(() => {
    const q = new URLSearchParams(sp);
    if (!q.has("score_min")) q.set("score_min", String(defLo));
    if (!q.has("score_max")) q.set("score_max", String(defHi));
    if (!q.has("page_size")) q.set("page_size", "25");
    return q;
  }, [sp, defLo, defHi]);
  const { data, error, loading, reload } = useApi<Page>(policy.data ? `/api/lenders/candidates?${query.toString()}` : null);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [bulk, setBulk] = useState(false);

  const get = (k: string) => query.get(k) ?? "";
  const getAll = (k: string) => query.getAll(k);
  const update = (patch: Record<string, string | string[] | null>) => {
    const q = new URLSearchParams(sp);
    for (const [k, v] of Object.entries(patch)) {
      q.delete(k);
      if (Array.isArray(v)) v.forEach((x) => q.append(k, x));
      else if (v !== null && v !== "") q.set(k, v);
    }
    if (!("page" in patch)) q.delete("page");
    setSp(q, { replace: true });
    setSel(new Set());
  };
  const reset = () => {
    setSp(new URLSearchParams(), { replace: true });
    setSel(new Set());
  };

  const tiers = policy.data?.tiers ?? [];
  const ownProducts = (catalog.data ?? []).filter((p) => p.lender_id === session?.lender_id);
  const page = Number(get("page") || 1);
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  const isLender = session?.role === "lender";
  const allOnPage = data?.items.length ? data.items.every((c) => sel.has(c.user_id)) : false;

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Candidates</h1>
          <p>
            Ranked by rule-based policy score (default range {defLo}–{defHi}). ML default probability is shown as a validation column; it never re-ranks or filters
            anyone unless you ask it to.
          </p>
        </div>
        {isLender && (
          <button className="btn btn-primary" disabled={!sel.size || !ownProducts.length} onClick={() => setBulk(true)}>
            Send offer to {sel.size || ""} selected
          </button>
        )}
      </div>

      <div className="card card-body stack">
        <div className="grid g4">
          <label className="field">Min policy score<input type="number" min={0} max={1000} value={get("score_min")} onChange={(e) => update({ score_min: e.target.value })} /></label>
          <label className="field">Max policy score<input type="number" min={0} max={1000} value={get("score_max")} onChange={(e) => update({ score_max: e.target.value })} /></label>
          <label className="field">
            Eligible for product
            <select value={get("eligible_for")} onChange={(e) => update({ eligible_for: e.target.value })}>
              <option value="">Any</option>
              {(catalog.data ?? []).map((p) => (
                <option key={p.product_id} value={p.product_id}>{p.product_name} (min {p.min_score}){p.lender_id === session?.lender_id ? " · yours" : ""}</option>
              ))}
            </select>
          </label>
          <label className="field">
            Sort by
            <select value={`${get("sort") || "score"}:${get("order") || "desc"}`} onChange={(e) => { const [s, o] = e.target.value.split(":"); update({ sort: s, order: o }); }}>
              <option value="score:desc">Policy score (high → low)</option>
              <option value="score:asc">Policy score (low → high)</option>
              <option value="pd:asc">ML default probability (low → high)</option>
              <option value="propensity:desc">Predicted acceptance of your products</option>
              <option value="income:desc">Income (high → low)</option>
            </select>
          </label>
        </div>
        <div className="grid g2">
          <div className="field">
            Risk tier
            <Chips options={tiers.map((t) => t.code)} labels={Object.fromEntries(tiers.map((t) => [t.code, `${t.code} ${t.name}`]))} value={getAll("tiers")} onChange={(v) => update({ tiers: v })} />
          </div>
          <div className="field">
            Rule vs ML validation
            <Chips options={Object.keys(AGREEMENT_LABEL)} labels={AGREEMENT_LABEL} value={getAll("validation")} onChange={(v) => update({ validation: v })} />
          </div>
          <div className="field">
            Employment
            <Chips options={["salaried", "self_employed", "gig", "freelancer", "student", "unemployed"]} labels={{ self_employed: "self-employed" }} value={getAll("employment")} onChange={(v) => update({ employment: v })} />
          </div>
          <div className="field">
            Data quality · City tier
            <div className="row">
              <Chips options={["GOOD", "LIMITED", "POOR"]} value={getAll("data_quality")} onChange={(v) => update({ data_quality: v })} />
              <Chips options={["1", "2", "3"]} labels={{ 1: "Tier 1", 2: "Tier 2", 3: "Tier 3" }} value={getAll("city_tier")} onChange={(v) => update({ city_tier: v })} />
            </div>
          </div>
        </div>
        <div className="grid g4">
          <label className="field">Min monthly income (₹)<input type="number" min={0} value={get("income_min")} onChange={(e) => update({ income_min: e.target.value })} /></label>
          <label className="field">
            Max ML default probability
            <select value={get("pd_max")} onChange={(e) => update({ pd_max: e.target.value })}>
              <option value="">No limit</option>
              {[0.05, 0.12, 0.25].map((v) => <option key={v} value={v}>{pct(v, 0)}</option>)}
            </select>
          </label>
          <label className="field">
            Review flag
            <select value={get("review_flag")} onChange={(e) => update({ review_flag: e.target.value })}>
              <option value="">Any</option>
              <option value="NONE">None</option>
              <option value="ENHANCED_REVIEW">Enhanced review</option>
              <option value="SECOND_LOOK">Second look</option>
            </select>
          </label>
          <div className="stack" style={{ gap: 6, justifyContent: "flex-end" }}>
            <label className="checkbox"><input type="checkbox" checked={get("exclude_offered") === "true"} onChange={(e) => update({ exclude_offered: e.target.checked ? "true" : null })} /> Hide candidates I already made an offer to</label>
            <button className="btn btn-sm" onClick={reset}>Reset filters</button>
          </div>
        </div>
      </div>

      {error && <ErrorBox error={error} onRetry={reload} />}
      {(loading || policy.loading) && !data && <Loading />}
      {data && (
        <div className="card">
          <div className="card-head">
            <span><b>{data.total.toLocaleString("en-IN")}</b> candidates match{sel.size ? ` · ${sel.size} selected` : ""}</span>
            <div className="row">
              <button className="btn btn-sm" disabled={page <= 1} onClick={() => update({ page: String(page - 1) })}>Previous</button>
              <span className="small">Page {page} of {pages}</span>
              <button className="btn btn-sm" disabled={page >= pages} onClick={() => update({ page: String(page + 1) })}>Next</button>
            </div>
          </div>
          {!data.items.length ? (
            <Empty>No candidates match these filters.</Empty>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    {isLender && (
                      <th>
                        <input type="checkbox" aria-label="select page" checked={allOnPage} onChange={(e) => {
                          const s = new Set(sel);
                          data.items.forEach((c) => (e.target.checked ? s.add(c.user_id) : s.delete(c.user_id)));
                          setSel(s);
                        }} />
                      </th>
                    )}
                    <th>Applicant</th>
                    <th className="r">Policy score</th>
                    <th>Tier</th>
                    <th>Profile</th>
                    <th className="r">ML PD</th>
                    <th>Validation</th>
                    <th>Data</th>
                    <th>Your offer</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((c) => (
                    <tr key={c.user_id} className="clickable" onClick={() => nav(`${base}/candidates/${c.user_id}`)}>
                      {isLender && (
                        <td onClick={(e) => e.stopPropagation()}>
                          <input type="checkbox" aria-label={`select ${c.user_id}`} checked={sel.has(c.user_id)} onChange={(e) => {
                            const s = new Set(sel);
                            if (e.target.checked) s.add(c.user_id);
                            else s.delete(c.user_id);
                            setSel(s);
                          }} />
                        </td>
                      )}
                      <td>
                        <b>{c.contact.display_name}</b>
                        <div className="xs muted mono">{c.user_id}{c.weak_id ? " · weak ID" : ""}</div>
                      </td>
                      <td className="r num"><b>{c.score}</b></td>
                      <td><TierBadge tier={c.tier} /></td>
                      <td className="small">
                        {titleCase(c.employment_status)} · {inr(c.monthly_income)}/mo
                        <div className="xs muted">age {c.age ?? "—"} · city tier {c.city_tier ?? "—"} · {titleCase(c.housing_status)}</div>
                      </td>
                      <td className="r num" style={{ color: "var(--ml)" }}>{pct(c.pd)}</td>
                      <td>{c.agreement_status && <Badge tone={AGREEMENT_TONE[c.agreement_status]}>{AGREEMENT_LABEL[c.agreement_status]}</Badge>}</td>
                      <td><Badge tone={DQ_TONE[c.data_quality]}>{c.data_quality}</Badge></td>
                      <td className="small">{c.offer_status ?? <span className="muted">—</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
      {bulk && (
        <BulkOffer
          userIds={[...sel]}
          products={ownProducts}
          onClose={() => setBulk(false)}
          onDone={(msg) => {
            setBulk(false);
            setSel(new Set());
            toast(msg);
            void reload();
          }}
        />
      )}
    </div>
  );
}

export function OfferForm({ products, value, onChange }: {
  products: CatalogProduct[];
  value: { product_id: string; interest_rate: string; amount: string; expiry_days: string; message: string };
  onChange: (v: { product_id: string; interest_rate: string; amount: string; expiry_days: string; message: string }) => void;
}) {
  const prod = products.find((p) => p.product_id === value.product_id);
  const set = (k: keyof typeof value) => (e: { target: { value: string } }) => onChange({ ...value, [k]: e.target.value });
  return (
    <>
      <label className="field">
        Product
        <select value={value.product_id} onChange={(e) => {
          const p = products.find((x) => x.product_id === e.target.value);
          onChange({ ...value, product_id: e.target.value, interest_rate: String(p?.interest_rate_pct ?? ""), amount: String(p?.amount_min ?? "") });
        }}>
          {products.map((p) => <option key={p.product_id} value={p.product_id}>{p.product_name} (min score {p.min_score})</option>)}
        </select>
      </label>
      <div className="grid g3">
        <label className="field">Rate (% p.a.)<input type="number" step="0.1" min={0.1} max={59} value={value.interest_rate} onChange={set("interest_rate")} /></label>
        <label className="field">Amount (₹)<input type="number" min={prod?.amount_min ?? 0} max={prod?.amount_max ?? undefined} value={value.amount} onChange={set("amount")} /></label>
        <label className="field">Valid for (days)<input type="number" min={1} max={90} value={value.expiry_days} onChange={set("expiry_days")} /></label>
      </div>
      {prod && <div className="xs muted">Catalog amount range {inr(prod.amount_min)} – {inr(prod.amount_max)}; catalog rate {prod.interest_rate}.</div>}
      <label className="field">Message to applicant<textarea rows={3} maxLength={500} value={value.message} onChange={set("message")} /></label>
    </>
  );
}

export const offerDefaults = (products: CatalogProduct[]) => ({
  product_id: products[0]?.product_id ?? "",
  interest_rate: String(products[0]?.interest_rate_pct ?? ""),
  amount: String(products[0]?.amount_min ?? ""),
  expiry_days: "30",
  message: "You are pre-approved based on your AltCredit policy score.",
});

export const offerBody = (v: ReturnType<typeof offerDefaults>) => ({
  product_id: v.product_id,
  interest_rate: v.interest_rate ? Number(v.interest_rate) : null,
  amount: v.amount ? Number(v.amount) : null,
  expiry_days: v.expiry_days ? Number(v.expiry_days) : null,
  message: v.message || null,
});

function BulkOffer({ userIds, products, onClose, onDone }: { userIds: string[]; products: CatalogProduct[]; onClose: () => void; onDone: (m: string) => void }) {
  const [v, setV] = useState(() => offerDefaults(products));
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [res, setRes] = useState<{ campaign_id: string; sent: number; skipped: { user_id: string; reason: string }[] } | null>(null);
  const send = async () => {
    setBusy(true);
    setErr(null);
    try {
      setRes(await api("/api/offers/bulk", { body: { ...offerBody(v), user_ids: userIds, campaign_name: name || null } }));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  if (res)
    return (
      <Modal title="Campaign sent" onClose={() => onDone(`Campaign ${res.campaign_id}: ${res.sent} offers sent, ${res.skipped.length} skipped.`)}
        footer={<button className="btn btn-primary" onClick={() => onDone(`Campaign ${res.campaign_id}: ${res.sent} offers sent.`)}>Done</button>}>
        <p><b>{res.sent}</b> offers sent. {res.skipped.length} skipped by the eligibility checks:</p>
        {res.skipped.length > 0 && (
          <ul className="list small">
            {res.skipped.slice(0, 20).map((s) => <li key={s.user_id}><span className="mono">{s.user_id}</span>: {s.reason}</li>)}
          </ul>
        )}
      </Modal>
    );
  return (
    <Modal title={`Send offer to ${userIds.length} candidate${userIds.length === 1 ? "" : "s"}`} onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" onClick={send} disabled={busy || !v.product_id}>{busy ? "Sending…" : "Send campaign"}</button></>}>
      <label className="field">Campaign name<input value={name} onChange={(e) => setName(e.target.value)} placeholder="optional" /></label>
      <OfferForm products={products} value={v} onChange={setV} />
      <div className="xs muted">Each candidate is re-checked against the product minimum; candidates with POOR data quality or a weak identity match are skipped.</div>
      {err && <ErrorBox error={err} />}
    </Modal>
  );
}
