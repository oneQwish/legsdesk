import { useCallback, useEffect, useRef, useState } from "react";
import { STATUS_LABEL, daysLeft, fmtDate, settings } from "../api";
import { useToast } from "./overlay";

/** Загрузка данных страницы. Ответ на устаревший запрос (фильтры успели смениться) отбрасывается,
 *  иначе медленный старый ответ мог прийти последним и показать список не по выбранным фильтрам. */
export function useLoad<T>(load: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const gen = useRef(0);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(load, deps);
  const reload = useCallback(() => {
    const my = ++gen.current;
    setLoading(true);
    run()
      .then((d) => {
        if (my !== gen.current) return;
        setData(d);
        setError("");
      })
      .catch((e: Error) => my === gen.current && setError(e.message))
      .finally(() => my === gen.current && setLoading(false));
  }, [run]);
  useEffect(reload, [reload]);
  useEffect(() => () => void (gen.current = -1), []); // после ухода со страницы ответы не применяются
  return { data, error, loading, reload, setData };
}

/** Действие по кнопке: пока выполняется — busy (повторный клик/Enter игнорируется),
 *  ошибка — уведомлением, а не молчаливым «ничего не произошло». */
export function useAction() {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const running = useRef(false);
  const run = useCallback(async <R,>(fn: () => Promise<R>, okText?: string): Promise<R | undefined> => {
    if (running.current) return undefined;
    running.current = true;
    setBusy(true);
    try {
      const r = await fn();
      if (okText) toast(okText);
      return r;
    } catch (e) {
      toast((e as Error).message || "Не удалось выполнить действие", "err");
      return undefined;
    } finally {
      running.current = false;
      setBusy(false);
    }
  }, [toast]);
  return { run, busy };
}

/** Свойства для строки/плитки, которая открывает что-то по клику: доступна и с клавиатуры (Tab + Enter). */
export function clickable(open: () => void) {
  return {
    tabIndex: 0,
    role: "link",
    onClick: open,
    onKeyDown: (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && e.target === e.currentTarget) open();
    },
  };
}

/** Значение, которое обновляется не чаще, чем раз в ms (для полей поиска). */
export function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge ${status}`}>{STATUS_LABEL[status] ?? status}</span>;
}

export function DueBadge({ due, status }: { due: string; status?: string }) {
  if (status === "done") return <span className="badge done">выполнено</span>;
  if (status === "cancelled") return <span className="badge later">снят</span>;
  const n = daysLeft(due);
  const cls = n < 0 ? "overdue" : n <= settings.soon_days ? "soon" : "later";
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
      <button disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Предыдущая страница">←</button>
      <button disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="Следующая страница">→</button>
    </div>
  );
}

export function ErrorBox({ error }: { error: string }) {
  return error ? <div className="error">{error}</div> : null;
}
