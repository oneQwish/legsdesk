import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Topbar, useSession } from "../App";
import { api, qs, shortCourt, type CaseBrief, type CaseValue, type Page } from "../api";
import { ActiveChips, FilterButton, filterParams } from "../components/FilterPanel";
import ResolvePanel from "../components/ResolvePanel";
import { BulkResolveModal } from "../components/Bulk";
import { ErrorBox, Pager, StatusBadge, clickable, useLoad } from "../components/ui";

type Item = { value: CaseValue; case: CaseBrief };

export default function ConflictsPage() {
  const { refreshStats, can } = useSession();
  const [bulk, setBulk] = useState(false);
  const [sp, setSp] = useSearchParams();
  const field = sp.get("field") ?? "";
  const page = Number(sp.get("page") ?? 1);
  const [sel, setSel] = useState(0);
  const fields = useLoad(() => api<{ key: string; label: string }[]>("/fields"), []);
  const fp = filterParams(sp);
  fp.set("page", String(page));
  fp.set("size", "25");
  if (field) fp.set("field", field);
  const list = useLoad(() => api<Page<Item>>(`/conflicts${qs(fp)}`), [fp.toString()]);
  const items = list.data?.items ?? [];
  const cur = items[sel];

  useEffect(() => setSel(0), [fp.toString()]); // eslint-disable-line react-hooks/exhaustive-deps

  // Разобраны все конфликты страницы, а в очереди ещё есть — подгрузить следующие, а не показывать «конфликтов нет»
  useEffect(() => {
    const d = list.data;
    if (!d || list.loading || items.length > 0 || d.total === 0) return;
    if (page > 1 && (page - 1) * d.size >= d.total) {
      const n = new URLSearchParams(sp);
      n.set("page", String(Math.ceil(d.total / d.size)));
      setSp(n, { replace: true });
    } else list.reload();
  }, [items.length, list.data?.total]); // eslint-disable-line react-hooks/exhaustive-deps

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
      <Topbar title="Очередь конфликтов" sub="Источники расходятся — выберите верное значение. Решение уходит в журнал и во внешние системы через коннекторы.">
      <select aria-label="Поле" value={field} onChange={(e) => { const n = new URLSearchParams(sp); n.delete("page"); if (e.target.value) n.set("field", e.target.value); else n.delete("field"); setSp(n); }}>
        <option value="">Все поля</option>
        {fields.data?.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
      </select>
        <FilterButton page="conflicts" />
        {can("lawyer") && <button onClick={() => setBulk(true)}>Массово…</button>}
      </Topbar>
      <ActiveChips />
      {bulk && <BulkResolveModal idsQuery={qs(new URLSearchParams([...filterParams(sp), ["has_conflicts", "true"]]))} field={field}
                                 onClose={() => setBulk(false)} onDone={() => { list.reload(); refreshStats(); }} />}
      <ErrorBox error={list.error} />
      {list.data && items.length === 0 && list.data.total === 0 ? (
        <div className="panel empty-state">Конфликтов нет 🎉</div>
      ) : (
        <div className="split">
          <div className="panel">
            {items.map((it, i) => (
              <div key={it.value.id} className={`queue-item ${i === sel ? "on" : ""}`} {...clickable(() => setSel(i))} aria-current={i === sel}>
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
                                 onPage={(p) => { const n = new URLSearchParams(sp); n.set("page", String(p)); setSp(n); }} />}
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
