import { Topbar } from "../App";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, fmtDate, qs, type DocumentBrief, type Page } from "../api";
import { ErrorBox, Pager, useLoad } from "../components/ui";

export default function DocumentsPage() {
  const nav = useNavigate();
  const [sp, setSp] = useSearchParams();
  const params = Object.fromEntries(sp.entries());
  const page = Number(params.page ?? 1);
  const unlinked = params.unlinked === "1";
  const list = useLoad(
    () => api<Page<DocumentBrief>>(`/documents${qs({ q: params.q, kind: params.kind, act_type: params.act_type, unlinked: unlinked || undefined, page, size: 50 })}`),
    [sp.toString()],
  );
  const set = (patch: Record<string, string>) =>
    setSp(Object.fromEntries(Object.entries({ ...params, page: "1", ...patch }).filter(([, v]) => v)));

  return (
    <>
      <Topbar title="Документы" sub="Сканы, цифровые оригиналы писем, иски и акты." />
      <div className="panel pad row" style={{ marginBottom: 12 }}>
        <input className="grow" placeholder="Имя файла, трек-номер или sha256" defaultValue={params.q ?? ""}
               onKeyDown={(e) => e.key === "Enter" && set({ q: (e.target as HTMLInputElement).value })} />
        <select value={params.kind ?? ""} onChange={(e) => set({ kind: e.target.value })}>
          <option value="">Все типы</option>
          <option>скан</option><option>письмо</option><option>иск</option><option>возражение</option><option>ФССП</option><option>прочее</option>
        </select>
        <select value={params.act_type ?? ""} onChange={(e) => set({ act_type: e.target.value })}>
          <option value="">Все виды актов</option>
          <option value="решение">решения</option>
          <option value="определение">определения</option>
          <option value="апелляционное">апелляционные</option>
          <option value="кассационное">кассационные</option>
        </select>
        <label className="row small"><input type="checkbox" checked={unlinked} onChange={(e) => set({ unlinked: e.target.checked ? "1" : "" })} /> не привязанные к делу</label>
      </div>
      <ErrorBox error={list.error} />
      <div className="panel">
        <div className="table-wrap">
          <table>
            <thead><tr><th>Дата акта</th><th>Вид акта</th><th>Тип</th><th>Файл</th><th>Дело</th><th>Хранилище</th></tr></thead>
            <tbody>
              {list.data?.items.map((d) => (
                <tr key={d.id} className="clickable" onClick={() => nav(`/documents/${d.id}`)}>
                  <td className="nowrap">{fmtDate(d.act_date)}</td>
                  <td>{d.act_type || <span className="muted">—</span>}<div className="muted small">{d.instance}</div></td>
                  <td>{d.kind}{d.track_no && <div className="mono muted">{d.track_no}</div>}</td>
                  <td className="small">{d.filename || <span className="mono muted">{d.sha256.slice(0, 12)}…</span>}</td>
                  <td>{d.case_id ? `#${d.case_id}` : <span className="badge appeal_possible">не привязан</span>}</td>
                  <td className="small muted">{d.storage_backend || "нет файла"}</td>
                </tr>
              ))}
              {list.data?.items.length === 0 && <tr><td colSpan={6} className="empty-state">Ничего не найдено</td></tr>}
            </tbody>
          </table>
        </div>
        {list.data && <Pager page={page} size={list.data.size} total={list.data.total} onPage={(p) => set({ page: String(p) })} />}
      </div>
    </>
  );
}
