import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import type { Tier } from "../types";

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="loading" role="status">
      <span className="spinner" />
      {label}
    </div>
  );
}

export function ErrorBox({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div className="error-box row between" role="alert">
      <span>{error}</span>
      {onRetry && (
        <button className="btn btn-sm" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function Badge({ tone = "", children, dot = false, title }: { tone?: string; children: ReactNode; dot?: boolean; title?: string }) {
  return (
    <span className={`badge ${tone} ${dot ? "badge-dot" : ""}`} title={title}>
      {children}
    </span>
  );
}

export function TierBadge({ tier }: { tier: Tier | { code: string; name?: string; color?: string } | string }) {
  const t = typeof tier === "string" ? { code: tier } : tier;
  const color = "color" in t && t.color ? t.color : undefined;
  return (
    <span className="badge badge-dot" style={color ? { color, borderColor: color + "55", background: color + "12" } : undefined}>
      {t.code}
      {"name" in t && t.name ? ` · ${t.name}` : ""}
    </span>
  );
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: string }) {
  return (
    <div className="card card-pad stat">
      <div className="label">{label}</div>
      <div className={`value ${tone ?? ""}`}>{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Modal({ title, onClose, children, footer }: { title: string; onClose: () => void; children: ReactNode; footer?: ReactNode }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <div className="card-head">
          <h2>{title}</h2>
          <button className="btn btn-ghost btn-sm" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        <div className="card-body stack">{children}</div>
        {footer && <div className="card-head" style={{ borderTop: "1px solid var(--line)", borderBottom: 0, justifyContent: "flex-end" }}>{footer}</div>}
      </div>
    </div>
  );
}

const ToastCtx = createContext<(msg: string) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [msg, setMsg] = useState<string | null>(null);
  const show = useCallback((m: string) => setMsg(m), []);
  useEffect(() => {
    if (!msg) return;
    const t = setTimeout(() => setMsg(null), 4200);
    return () => clearTimeout(t);
  }, [msg]);
  return (
    <ToastCtx.Provider value={show}>
      {children}
      {msg && (
        <div className="toast" role="status">
          {msg}
        </div>
      )}
    </ToastCtx.Provider>
  );
}

export const useToast = () => useContext(ToastCtx);

export function PolicyLabel({ children = "Rule-Based Policy Decision" }: { children?: ReactNode }) {
  return <span className="policy-label">◆ {children}</span>;
}

export function MLLabel({ children = "ML Validation Signal" }: { children?: ReactNode }) {
  return <span className="ml-label">◇ {children}</span>;
}
