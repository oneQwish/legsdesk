import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Topbar, useSession } from "../App";
import { api, daysLeft, DEADLINE_KIND, fmtDate, qs, settings, type Deadline } from "../api";
import { ActiveChips, FilterButton, filterParams } from "../components/FilterPanel";
import { DueBadge, ErrorBox, useAction, useLoad } from "../components/ui";

const KIND_LABEL: Record<string, string> = Object.fromEntries(Object.entries(DEADLINE_KIND).map(([k, v]) => [k, v.label]));

export default function DeadlinesPage() {
  const { can, refreshStats } = useSession();
  // вид и статус — в адресе: сохраняются в подборке и переживают «назад»
  const [sp, setSp] = useSearchParams();
  const status = sp.get("status") ?? "open";
  const kind = sp.get("kind") ?? "";
  const setParam = (k: string, v: string, def = "") =>
    setSp((prev) => {
      const n = new URLSearchParams(prev);
      if (v === def) n.delete(k);
      else n.set(k, v);
      return n;
    }, { replace: true });
  const [all, setAll] = useState<Record<string, boolean>>({});
  const { run, busy } = useAction();
  const fp = filterParams(sp);
  fp.set("limit", String(settings.deadlines_page_limit));
  const GROUP_LIMIT = settings.deadlines_group_limit; // строк в группе до «показать все» — длинная таблица тормозит
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
    groups[status !== "open" ? 3 : n < 0 ? 0 : n <= settings.soon_days ? 1 : n <= 30 ? 2 : 3][1].push(d);
  }

  const done = (d: Deadline) => run(async () => {
    await api(`/deadlines/${d.id}`, { method: "PATCH", json: { status: "done" } });
    list.reload();
    refreshStats();
  }, `«${d.title}» — выполнено`);

  return (
    <>
      <Topbar title="Сроки" sub="По ГПК РФ из актов дела и производственному календарю (из 1С или другой системы). «*» — календарь года не загружен.">
      <select aria-label="Вид срока" value={kind} onChange={(e) => setParam("kind", e.target.value)}>
        <option value="">Все виды</option>
        {Object.entries(KIND_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </select>
      <select aria-label="Статус срока" value={status} onChange={(e) => setParam("status", e.target.value, "open")}>
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
                  {(all[title] ? items : items.slice(0, GROUP_LIMIT)).map((d) => (
                    <tr key={d.id}>
                      <td className="nowrap">
                        <b>{fmtDate(d.due_date)}</b>{!d.calendar_confirmed && <span title="Календарь года не загружен"> *</span>}
                        <div><DueBadge due={d.due_date} status={d.status} /></div>
                      </td>
                      <td>{d.title}<div className="muted small">{KIND_LABEL[d.kind] ?? d.kind}{d.auto ? "" : " · вручную"}</div></td>
                      <td>
                        <Link to={`/cases/${d.case_id}`}>{d.case_number || `#${d.case_id}`}</Link>
                        <div className="small">{d.plaintiffs}</div>
                        <div className="muted small">{d.court_name}</div>
                      </td>
                      <td className="small" style={{ maxWidth: 380 }}><details className="rule"><summary>{d.rule.split(":")[0]}{d.rule.includes("неизвестна") && " · уточните дату"}</summary><div>{d.rule}</div></details></td>
                      <td>{can("lawyer") && d.status === "open" && <button disabled={busy} onClick={() => done(d)}>Выполнено</button>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {items.length > GROUP_LIMIT && !all[title] && (
                <div className="pad"><button className="link" onClick={() => setAll({ ...all, [title]: true })}>Показать все {items.length}</button></div>
              )}
            </div>
          </div>
        ))}
        {list.data?.length === 0 && <div className="panel empty-state">Сроков нет</div>}
      </div>
    </>
  );
}
