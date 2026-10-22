import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Topbar } from "../App";
import { api, fmtDate, qs, shortCourt, type CaseBrief, type Page } from "../api";
import CaseCard, { caseTone } from "../components/CaseCard";
import { Icon } from "../components/icons";
import { DueBadge, ErrorBox, Pager, useLoad } from "../components/ui";

type Facets = { legal_entity: string[]; stage: string[]; responsible: string[]; building: string[] };
type Mode = "cards" | "table";

function savedMode(): Mode {
  try {
    return (localStorage.getItem("lawdesk.cases.mode") as Mode) || "cards";
  } catch {
    return "cards";
  }
}

export default function CasesPage() {
  const nav = useNavigate();
  const [sp, setSp] = useSearchParams();
  const [q, setQ] = useState(sp.get("q") ?? "");
  const [mode, setModeState] = useState<Mode>(savedMode);
  const params = Object.fromEntries(sp.entries());
  const page = Number(params.page ?? 1);
  const size = mode === "cards" ? 24 : 50;

  const setMode = (m: Mode) => {
    setModeState(m);
    try {
      localStorage.setItem("lawdesk.cases.mode", m);
    } catch {
      /* без сохранения — не страшно */
    }
  };

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
  const list = useLoad(() => api<Page<CaseBrief>>(`/cases${qs({ ...params, size })}`), [sp.toString(), size]);

  return (
    <>
      <Topbar title="Дела" sub={list.data ? `${list.data.total} дел` : " "}>
        <div className="seg" role="tablist" aria-label="Вид">
          <button className={mode === "cards" ? "on" : ""} onClick={() => setMode("cards")}><Icon name="spread" size={14} /> Карточки</button>
          <button className={mode === "table" ? "on" : ""} onClick={() => setMode("table")}><Icon name="table" size={14} /> Таблица</button>
        </div>
      </Topbar>
      <div className="filters">
        <input className="q" placeholder="УИД, номер (2-…, М-…, 33-…), истец, договор, суд" value={q} onChange={(e) => setQ(e.target.value)} />
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

      {mode === "cards" ? (
        <>
          <div className="cards-grid">
            {list.data?.items.map((c) => <CaseCard key={c.id} c={c} />)}
          </div>
          {list.data?.items.length === 0 && <div className="panel empty-state">Ничего не найдено</div>}
        </>
      ) : (
        <div className="panel">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th style={{ width: 4, padding: 0 }}></th>
                  <th>Дело</th>
                  <th>Истцы</th>
                  <th>Суд</th>
                  <th>Объект</th>
                  <th>Юрлицо</th>
                  <th className="right">Конфл.</th>
                  <th>Ближайший срок</th>
                </tr>
              </thead>
              <tbody>
                {list.data?.items.map((c) => (
                  <tr key={c.id} className={`clickable ${caseTone(c)}`} onClick={() => nav(`/cases/${c.id}`)}>
                    <td style={{ padding: 0, background: "var(--tone)" }}></td>
                    <td className="nowrap">
                      <b className="serif" style={{ fontSize: 15 }}>{c.case_number || "без номера"}</b>
                      <span className="mono muted" style={{ marginLeft: 8 }}>{c.uid ?? "нет УИД"}</span>
                    </td>
                    <td className="ellipsis" style={{ maxWidth: 260 }} title={c.plaintiffs}>{c.plaintiffs || <span className="muted">—</span>}</td>
                    <td className="nowrap small" title={c.court_name}>{shortCourt(c.court_name)}</td>
                    <td className="nowrap small">{c.building ? `корп. ${c.building}, кв. ${c.flat}` : "—"}</td>
                    <td className="nowrap small">{c.legal_entity}</td>
                    <td className="right">{c.conflicts > 0 ? <span className="badge conflict">{c.conflicts}</span> : <span className="muted">·</span>}</td>
                    <td className="nowrap small">
                      {c.next_due ? (<>{fmtDate(c.next_due)} <DueBadge due={c.next_due} /> <span className="muted">{c.next_title}</span></>) : <span className="muted">—</span>}
                    </td>
                  </tr>
                ))}
                {list.data?.items.length === 0 && <tr><td colSpan={8} className="empty-state">Ничего не найдено</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {list.data && <Pager page={page} size={list.data.size} total={list.data.total} onPage={(p) => set({ page: String(p) })} />}
    </>
  );
}
