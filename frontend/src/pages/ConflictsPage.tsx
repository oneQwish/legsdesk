import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Topbar, useSession } from "../App";
import { api, qs, shortCourt, type CaseBrief, type CaseValue, type Page } from "../api";
import ResolvePanel from "../components/ResolvePanel";
import { ErrorBox, Pager, StatusBadge, useLoad } from "../components/ui";

type Item = { value: CaseValue; case: CaseBrief };

export default function ConflictsPage() {
  const { refreshStats } = useSession();
  const [sp, setSp] = useSearchParams();
  const field = sp.get("field") ?? "";
  const page = Number(sp.get("page") ?? 1);
  const [sel, setSel] = useState(0);
  const fields = useLoad(() => api<{ key: string; label: string }[]>("/fields"), []);
  const list = useLoad(() => api<Page<Item>>(`/conflicts${qs({ field, page, size: 25 })}`), [field, page]);
  const items = list.data?.items ?? [];
  const cur = items[sel];

  useEffect(() => setSel(0), [field, page]);

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT") return;
      if (e.key === "j") setSel((s) => Math.min(s + 1, items.length - 1));
      if (e.key === "k") setSel((s) => Math.max(s - 1, 0));
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [items.length]);

  const done = (v: CaseValue) => {
    // Разрешённое уходит из очереди; остаёмся на той же позиции — там уже следующий
    list.setData((d) => d && { ...d, total: d.total - 1, items: d.items.filter((x) => x.value.id !== v.id) });
    setSel((s) => Math.min(s, Math.max(0, items.length - 2)));
    refreshStats();
  };

  return (
    <>
      <Topbar title="Очередь конфликтов" sub="Источники расходятся — выберите верное значение. Решение уходит в журнал и выгрузку для 1С.">
      <select value={field} onChange={(e) => setSp(e.target.value ? { field: e.target.value } : {})}>
        <option value="">Все поля</option>
        {fields.data?.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
      </select>
      </Topbar>
      <ErrorBox error={list.error} />
      {list.data && items.length === 0 ? (
        <div className="panel empty-state">Конфликтов нет 🎉</div>
      ) : (
        <div className="split">
          <div className="panel">
            {items.map((it, i) => (
              <div key={it.value.id} className={`queue-item ${i === sel ? "on" : ""}`} onClick={() => setSel(i)}>
                <div className="row">
                  <b>{it.value.label}</b>
                  <span className="spacer" />
                  <StatusBadge status={it.value.status} />
                </div>
                <div className="small">{it.case.case_number} · {it.case.plaintiffs}</div>
                <div className="muted small">{shortCourt(it.case.court_name)}</div>
              </div>
            ))}
            {list.data && <Pager page={page} size={list.data.size} total={list.data.total}
                                 onPage={(p) => setSp({ ...(field ? { field } : {}), page: String(p) })} />}
          </div>
          {cur && (
            <div className="panel pad stack">
              <div>
                <div className="row">
                  <h2 style={{ margin: 0 }}>{cur.value.label}</h2>
                  <span className="spacer" />
                  <Link to={`/cases/${cur.case.id}`}>Открыть дело →</Link>
                </div>
                <div className="muted">
                  {cur.case.case_number}{cur.case.uid && <> · <span className="mono">{cur.case.uid}</span></>} · {cur.case.court_name}
                </div>
                <div className="small">{cur.case.plaintiffs} · {cur.case.legal_entity}{cur.case.building && `, корп. ${cur.case.building}, кв. ${cur.case.flat}`}</div>
              </div>
              <ResolvePanel value={cur.value} onDone={done} hotkeys />
            </div>
          )}
        </div>
      )}
    </>
  );
}
