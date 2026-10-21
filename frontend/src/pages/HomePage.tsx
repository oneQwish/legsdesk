import { Link, useNavigate } from "react-router-dom";
import { useSession } from "../App";
import { api, fmtDate, type Deadline } from "../api";
import { DueBadge, useLoad } from "../components/ui";

const FIELD_LABELS: Record<string, string> = {};

export default function HomePage() {
  const { stats } = useSession();
  const nav = useNavigate();
  const soon = new Date();
  soon.setDate(soon.getDate() + 14);
  const deadlines = useLoad(
    () => api<Deadline[]>(`/deadlines?status=open&due_before=${soon.toISOString().slice(0, 10)}&limit=15`),
    [],
  );
  const summary = useLoad(() => api<{ field: string; status: string; count: number }[]>("/conflicts/summary"), []);
  const fields = useLoad(() => api<{ key: string; label: string }[]>("/fields"), []);
  for (const f of fields.data ?? []) FIELD_LABELS[f.key] = f.label;

  const byStatus = stats?.values_by_status ?? {};
  const conflicts = (byStatus.conflict ?? 0) + (byStatus.appeal_possible ?? 0);
  const byField = new Map<string, number>();
  for (const r of summary.data ?? []) byField.set(r.field, (byField.get(r.field) ?? 0) + r.count);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Сводка</h1>
          <div className="muted">Что требует внимания сегодня, {new Date().toLocaleDateString("ru-RU")}</div>
        </div>
      </div>
      <div className="kpis">
        <Link to="/deadlines" className="panel kpi alert" style={{ textDecoration: "none", color: "inherit" }}>
          <div className="v">{stats?.deadlines_overdue ?? "—"}</div>
          <div className="l">просроченных сроков</div>
        </Link>
        <Link to="/deadlines" className="panel kpi" style={{ textDecoration: "none", color: "inherit" }}>
          <div className="v">{stats?.deadlines_week ?? "—"}</div>
          <div className="l">сроков на 7 дней</div>
        </Link>
        <Link to="/conflicts" className={`panel kpi ${conflicts ? "alert" : ""}`} style={{ textDecoration: "none", color: "inherit" }}>
          <div className="v">{conflicts}</div>
          <div className="l">конфликтов источников</div>
        </Link>
        <Link to="/cases" className="panel kpi" style={{ textDecoration: "none", color: "inherit" }}>
          <div className="v">{stats?.cases ?? "—"}</div>
          <div className="l">дел, из них с УИД {stats?.cases_with_uid ?? "—"}</div>
        </Link>
        <Link to="/documents?unlinked=1" className="panel kpi" style={{ textDecoration: "none", color: "inherit" }}>
          <div className="v">{stats?.documents ?? "—"}</div>
          <div className="l">документов, не привязано {stats?.documents_unlinked ?? "—"}</div>
        </Link>
      </div>

      <div className="split" style={{ gridTemplateColumns: "1.4fr 1fr" }}>
        <div className="panel">
          <div className="pad panel" style={{ border: "none", boxShadow: "none" }}>
            <h2>Ближайшие сроки (14 дней)</h2>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Срок</th><th>Что</th><th>Дело</th><th></th></tr>
              </thead>
              <tbody>
                {(deadlines.data ?? []).map((d) => (
                  <tr key={d.id} className="clickable" onClick={() => nav(`/cases/${d.case_id}`)}>
                    <td className="nowrap">{fmtDate(d.due_date)}</td>
                    <td>{d.title}{!d.calendar_confirmed && <span className="muted small" title="Год не загружен из 1С"> *</span>}</td>
                    <td><span className="nowrap">{d.case_number}</span><div className="muted small">{d.plaintiffs}</div></td>
                    <td><DueBadge due={d.due_date} /></td>
                  </tr>
                ))}
                {deadlines.data?.length === 0 && <tr><td colSpan={4} className="empty-state">Сроков на две недели нет</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
        <div className="panel pad">
          <h2>Конфликты по полям</h2>
          {byField.size === 0 && <div className="muted">Конфликтов нет</div>}
          <table>
            <tbody>
              {[...byField.entries()].sort((a, b) => b[1] - a[1]).map(([f, n]) => (
                <tr key={f} className="clickable" onClick={() => nav(`/conflicts?field=${f}`)}>
                  <td>{FIELD_LABELS[f] ?? f}</td>
                  <td className="right"><span className="badge conflict">{n}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
