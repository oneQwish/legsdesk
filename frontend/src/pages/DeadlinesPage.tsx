import { useState } from "react";
import { Link } from "react-router-dom";
import { useSession } from "../App";
import { api, daysLeft, fmtDate, qs, type Deadline } from "../api";
import { DueBadge, ErrorBox, useLoad } from "../components/ui";

const KIND_LABEL: Record<string, string> = {
  appeal: "апелляция",
  effective: "вступление в силу",
  cassation: "кассация",
  private_complaint: "частная жалоба",
  default_cancel: "отмена заочного",
  hearing: "заседание",
  custom: "свой",
};

export default function DeadlinesPage() {
  const { can, refreshStats } = useSession();
  const [status, setStatus] = useState("open");
  const [kind, setKind] = useState("");
  const list = useLoad(() => api<Deadline[]>(`/deadlines${qs({ status, kind, limit: 2000 })}`), [status, kind]);

  const groups: [string, Deadline[]][] = [
    ["Просрочено", []],
    ["Сегодня и 7 дней", []],
    ["8–30 дней", []],
    ["Позже", []],
  ];
  for (const d of list.data ?? []) {
    const n = daysLeft(d.due_date);
    groups[status !== "open" ? 3 : n < 0 ? 0 : n <= 7 ? 1 : n <= 30 ? 2 : 3][1].push(d);
  }

  const done = async (d: Deadline) => {
    await api(`/deadlines/${d.id}`, { method: "PATCH", json: { status: "done" } });
    list.reload();
    refreshStats();
  };

  return (
    <>
      <div className="page-head">
        <div className="grow">
          <h1>Процессуальные сроки</h1>
          <div className="muted">
            Считаются по ГПК РФ из актов дела (ст. 107–108, 209, 237, 321, 332, 376.1) по производственному календарю из 1С. «*» — год календаря не загружен.
          </div>
        </div>
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">Все виды</option>
          {Object.entries(KIND_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="open">Открытые</option>
          <option value="done">Выполненные</option>
          <option value="cancelled">Снятые</option>
        </select>
      </div>
      <ErrorBox error={list.error} />
      <div className="stack">
        {groups.filter(([, items]) => items.length).map(([title, items]) => (
          <div key={title}>
            <div className="group-title">{title} · {items.length}</div>
            <div className="panel table-wrap">
              <table>
                <thead><tr><th style={{ width: 120 }}>Срок</th><th>Что</th><th>Дело</th><th>Как посчитано</th><th></th></tr></thead>
                <tbody>
                  {items.map((d) => (
                    <tr key={d.id}>
                      <td className="nowrap">
                        <b>{fmtDate(d.due_date)}</b>{!d.calendar_confirmed && <span title="Год календаря не загружен из 1С"> *</span>}
                        <div><DueBadge due={d.due_date} status={d.status} /></div>
                      </td>
                      <td>{d.title}<div className="muted small">{KIND_LABEL[d.kind] ?? d.kind}{d.auto ? "" : " · вручную"}</div></td>
                      <td>
                        <Link to={`/cases/${d.case_id}`}>{d.case_number || `#${d.case_id}`}</Link>
                        <div className="small">{d.plaintiffs}</div>
                        <div className="muted small">{d.court_name}</div>
                      </td>
                      <td className="small" style={{ maxWidth: 380, whiteSpace: "pre-wrap" }}>{d.rule}</td>
                      <td>{can("lawyer") && d.status === "open" && <button onClick={() => done(d)}>Выполнено</button>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ))}
        {list.data?.length === 0 && <div className="panel empty-state">Сроков нет</div>}
      </div>
    </>
  );
}
