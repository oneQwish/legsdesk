import { useCallback, useEffect, useState } from "react";
import { STATUS_LABEL, daysLeft, fmtDate } from "../api";

export function useLoad<T>(load: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string>("");
  const [loading, setLoading] = useState(true);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(load, deps);
  const reload = useCallback(() => {
    setLoading(true);
    run()
      .then((d) => {
        setData(d);
        setError("");
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [run]);
  useEffect(reload, [reload]);
  return { data, error, loading, reload, setData };
}

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge ${status}`}>{STATUS_LABEL[status] ?? status}</span>;
}

export function DueBadge({ due, status }: { due: string; status?: string }) {
  if (status === "done") return <span className="badge done">выполнено</span>;
  if (status === "cancelled") return <span className="badge later">снят</span>;
  const n = daysLeft(due);
  const cls = n < 0 ? "overdue" : n <= 7 ? "soon" : "later";
  const text = n < 0 ? `просрочен ${-n} дн.` : n === 0 ? "сегодня" : `через ${n} дн.`;
  return (
    <span className={`badge ${cls}`} title={fmtDate(due)}>
      {text}
    </span>
  );
}

export function Pager({ page, size, total, onPage }: { page: number; size: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / size));
  return (
    <div className="pager">
      <span className="muted small">
        {total ? `${(page - 1) * size + 1}–${Math.min(page * size, total)} из ${total}` : "нет записей"}
      </span>
      <button disabled={page <= 1} onClick={() => onPage(page - 1)}>←</button>
      <button disabled={page >= pages} onClick={() => onPage(page + 1)}>→</button>
    </div>
  );
}

export function ErrorBox({ error }: { error: string }) {
  return error ? <div className="error">{error}</div> : null;
}
