import { useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Topbar } from "../App";
import { api, fmtDate, qs, shortCourt, type CaseBrief, type Page } from "../api";
import CaseCard, { caseTone } from "../components/CaseCard";
import FilterPanel, { ActiveChips, activeCount } from "../components/FilterPanel";
import { Icon } from "../components/icons";
import { DueBadge, ErrorBox, Pager, clickable, useLoad } from "../components/ui";

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
  const [drawer, setDrawer] = useState(false);
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

  const listParams = new URLSearchParams(sp);
  listParams.set("size", String(size));
  const list = useLoad(() => api<Page<CaseBrief>>(`/cases${qs(listParams)}`), [sp.toString(), size]);
  const nFilters = activeCount(sp);

  return (
    <>
      <Topbar title="Дела" sub="Фильтры слева можно комбинировать; набор сохраняется подборкой и выкладывается на стол.">
        <div className="seg" role="group" aria-label="Вид">
          <button className={mode === "cards" ? "on" : ""} aria-pressed={mode === "cards"} onClick={() => setMode("cards")}><Icon name="spread" size={14} /> Карточки</button>
          <button className={mode === "table" ? "on" : ""} aria-pressed={mode === "table"} onClick={() => setMode("table")}><Icon name="table" size={14} /> Таблица</button>
        </div>
      </Topbar>
      <div className="with-filters">
      <FilterPanel page="cases" />
      <div style={{ minWidth: 0 }}>
      <div className="results-bar">
        <button className="filters-btn" onClick={() => setDrawer(true)}>
          <Icon name="filter" size={15} /> Фильтры {nFilters > 0 && <span className="badge-count">{nFilters}</span>}
        </button>
        <span className="muted">{list.data ? <><b className="serif" style={{ color: "var(--ink)", fontSize: 16 }}>{list.data.total}</b> дел</> : " "}</span>
        <span className="spacer" />
        <select value={params.sort ?? "-updated_at"} onChange={(e) => set({ sort: e.target.value })} aria-label="Сортировка">
          <option value="-updated_at">Сначала изменённые</option>
          <option value="next_due">По ближайшему сроку</option>
          <option value="-conflicts">По числу конфликтов</option>
          <option value="case_number">По номеру</option>
        </select>
      </div>
      <ActiveChips />
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
                  <tr key={c.id} className={`clickable ${caseTone(c)}`} {...clickable(() => nav(`/cases/${c.id}`))}>
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
      </div>
      </div>
      {drawer && createPortal(
        <div className="fp-drawer-back" onMouseDown={(e) => e.target === e.currentTarget && setDrawer(false)}>
          <FilterPanel page="cases" onClose={() => setDrawer(false)} />
        </div>,
        document.body,
      )}
    </>
  );
}
