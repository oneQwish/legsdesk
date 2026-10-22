import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Topbar, useSession } from "../App";
import { api, daysLeft, fmtDate, qs, type Deadline } from "../api";
import { ActiveChips, FilterButton, filterParams } from "../components/FilterPanel";
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
  const [sp] = useSearchParams();
  const fp = filterParams(sp);
  fp.set("limit", "2000");
  if (status) fp.set("status", status);
  if (kind) fp.set("kind", kind);
  const list = useLoad(() => api<Deadline[]>(`/deadlines${qs(fp)}`), [fp.toString()]);

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
      <Topbar title="Сроки" sub="По ГПК РФ из актов дела и производственному календарю 1С. «*» — календарь года не загружен.">
      <select value={kind} onChange={(e) => setKind(e.target.value)}>
        <option value="">Все виды</option>
        {Object.entries(KIND_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </select>
      <select value={status} onChange={(e) => setStatus(e.target.value)}>
        <option value="open">Открытые</option>
        <option value="done">Выполненные</option>
        <option value="cancelled">Снятые</option>
      </select>
        <FilterButton page="deadlines" />
      </Topbar>
      <ActiveChips />
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
                      <td className="small" style={{ maxWidth: 380 }}><details className="rule"><summary>{d.rule.split(":")[0]}{d.rule.includes("неизвестна") && " · уточните дату"}</summary><div>{d.rule}</div></details></td>
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
