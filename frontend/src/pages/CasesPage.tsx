import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, fmtDate, qs, type CaseBrief, type Page } from "../api";
import { DueBadge, ErrorBox, Pager, useLoad } from "../components/ui";

type Facets = { legal_entity: string[]; stage: string[]; responsible: string[]; building: string[] };

export default function CasesPage() {
  const nav = useNavigate();
  const [sp, setSp] = useSearchParams();
  const [q, setQ] = useState(sp.get("q") ?? "");
  const params = Object.fromEntries(sp.entries());
  const page = Number(params.page ?? 1);

  const set = (patch: Record<string, string>) => {
    const next = { ...params, ...patch };
    if (!("page" in patch)) next.page = "1";
    setSp(Object.fromEntries(Object.entries(next).filter(([, v]) => v)));
  };

  useEffect(() => {
    const t = setTimeout(() => q !== (params.q ?? "") && set({ q }), 350);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  const facets = useLoad(() => api<Facets>("/cases/facets"), []);
  const list = useLoad(() => api<Page<CaseBrief>>(`/cases${qs({ ...params, size: 50 })}`), [sp.toString()]);

  return (
    <>
      <div className="page-head">
        <div className="grow">
          <h1>Дела</h1>
          <div className="muted">Поиск по УИД, номеру (включая М-, прежние и 33-/88-), истцу, договору, суду</div>
        </div>
      </div>
      <div className="panel pad row" style={{ marginBottom: 12 }}>
        <input className="grow" placeholder="Поиск…" value={q} onChange={(e) => setQ(e.target.value)} style={{ minWidth: 220 }} />
        <select value={params.legal_entity ?? ""} onChange={(e) => set({ legal_entity: e.target.value })}>
          <option value="">Все юрлица</option>
          {facets.data?.legal_entity.map((x) => <option key={x}>{x}</option>)}
        </select>
        <select value={params.building ?? ""} onChange={(e) => set({ building: e.target.value })}>
          <option value="">Все корпуса</option>
          {facets.data?.building.map((x) => <option key={x}>{x}</option>)}
        </select>
        <select value={params.has_conflicts ?? ""} onChange={(e) => set({ has_conflicts: e.target.value })}>
          <option value="">Конфликты: все</option>
          <option value="true">есть конфликты</option>
          <option value="false">без конфликтов</option>
        </select>
        <select value={params.has_uid ?? ""} onChange={(e) => set({ has_uid: e.target.value })}>
          <option value="">УИД: все</option>
          <option value="true">с УИД</option>
          <option value="false">без УИД</option>
        </select>
        <select value={params.sort ?? "-updated_at"} onChange={(e) => set({ sort: e.target.value })}>
          <option value="-updated_at">Сначала изменённые</option>
          <option value="next_due">По ближайшему сроку</option>
          <option value="-conflicts">По числу конфликтов</option>
          <option value="case_number">По номеру</option>
        </select>
      </div>
      <ErrorBox error={list.error} />
      <div className="panel">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Номер / УИД</th>
                <th>Суд</th>
                <th>Истцы</th>
                <th>Объект</th>
                <th>Юрлицо</th>
                <th>Конфликты</th>
                <th>Ближайший срок</th>
              </tr>
            </thead>
            <tbody>
              {list.data?.items.map((c) => (
                <tr key={c.id} className="clickable" onClick={() => nav(`/cases/${c.id}`)}>
                  <td>
                    <b className="nowrap">{c.case_number || "без номера"}</b>
                    <div className="mono muted">{c.uid ?? "УИД нет"}</div>
                  </td>
                  <td className="small">{c.court_name}</td>
                  <td>{c.plaintiffs || <span className="muted">—</span>}</td>
                  <td className="nowrap small">
                    {c.complex}
                    {c.building && <div className="muted">корп. {c.building}{c.flat && `, кв. ${c.flat}`}</div>}
                  </td>
                  <td className="small">{c.legal_entity}</td>
                  <td>{c.conflicts > 0 ? <span className="badge conflict">{c.conflicts}</span> : <span className="muted">—</span>}</td>
                  <td className="nowrap">
                    {c.next_due ? (<>{fmtDate(c.next_due)} <DueBadge due={c.next_due} /></>) : <span className="muted">—</span>}
                  </td>
                </tr>
              ))}
              {list.data?.items.length === 0 && <tr><td colSpan={7} className="empty-state">Ничего не найдено</td></tr>}
            </tbody>
          </table>
        </div>
        {list.data && <Pager page={page} size={list.data.size} total={list.data.total} onPage={(p) => set({ page: String(p) })} />}
      </div>
    </>
  );
}
