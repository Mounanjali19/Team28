import { useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Empty, ErrorBox, Loading, useToast } from "../../components/ui";
import { useApi } from "../../hooks/useApi";
import { api } from "../../services/api";
import type { BankApplication } from "../../types";
import { dateTime } from "../../utils/format";

const TONE: Record<string, string> = { APPROVED: "pos", PRE_APPROVED: "pos", DECLINED: "neg", MANUAL_REVIEW: "warn", UNDER_REVIEW: "brand", SUBMITTED: "brand", REFERRED: "warn" };

export default function Applications() {
  const { data, error, loading, reload } = useApi<BankApplication[]>("/api/applications");
  const toast = useToast();
  const [busy, setBusy] = useState<number | null>(null);

  const check = async (id: number) => {
    setBusy(id);
    try {
      const a = await api<BankApplication>(`/api/applications/${id}`);
      toast(`Bank status: ${a.status.replace("_", " ")}`);
      await reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Bank applications</h1>
          <p>AltCredit → POST /bank/preapproval → POST /bank/apply → GET /bank/application/&#123;id&#125; on the mock partner bank.</p>
        </div>
      </div>
      {error && <ErrorBox error={error} onRetry={reload} />}
      {loading && !data && <Loading />}
      {data && !data.length && (
        <div className="card">
          <Empty>
            No applications yet. <Link to="/app/products">Apply for an eligible product</Link>.
          </Empty>
        </div>
      )}
      {data && data.length > 0 && (
        <div className="card table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Product</th>
                <th>Bank reference</th>
                <th>Status</th>
                <th>Submitted</th>
                <th>Updated</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.map((a) => {
                const resp = a.response_json ? JSON.parse(a.response_json) : {};
                return (
                  <tr key={a.id}>
                    <td>
                      <b>{a.product_name}</b>
                      <div className="xs muted">{resp.preapproval?.message}</div>
                    </td>
                    <td className="mono">{a.bank_reference ?? "—"}</td>
                    <td><Badge tone={TONE[a.status] ?? ""} dot>{a.status.replace("_", " ")}</Badge></td>
                    <td className="small">{dateTime(a.created_at)}</td>
                    <td className="small">{dateTime(a.updated_at)}</td>
                    <td className="r">
                      {a.bank_reference && (
                        <button className="btn btn-sm" onClick={() => check(a.id)} disabled={busy === a.id}>
                          {busy === a.id ? "Checking…" : "Check status"}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
