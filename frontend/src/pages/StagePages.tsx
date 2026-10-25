import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Topbar, useSession } from "../App";
import { api, fmtDate, fmtDateTime, fmtShortMoney, qs } from "../api";
import { ActiveChips, FilterButton, filterParams } from "../components/FilterPanel";
import { Modal } from "../components/overlay";
import { ErrorBox, useAction, useLoad } from "../components/ui";

// ------------------------------------------------------------------------------------------
// Аналитика
// ------------------------------------------------------------------------------------------

type ARow = { key: string; cases: number; with_award: number; claimed: number; awarded: number; awarded_pct: number | null;
  appeal_pct: number; conflicts: number; open_deadlines: number; overdue: number };
type AResp = { group: string; group_label: string; rows: ARow[]; groups: Record<string, string>;
  total: { cases: number; awarded: number; claimed: number; overdue: number } };
type Load = { login: string; name: string; cases: number; open_deadlines: number; week: number; overdue: number; conflicts: number; assignments: number };
type Rep = { id: number; kind: string; title: string; file: string; created_at: string };

function Bar({ value, max, tone = "var(--ink)" }: { value: number; max: number; tone?: string }) {
  return <span className="mini-bar"><span style={{ width: `${max ? Math.max(2, (100 * value) / max) : 0}%`, background: tone }} /></span>;
}

export function AnalyticsPage() {
  const { can } = useSession();
  const [sp, setSp] = useSearchParams();
  const tab = sp.get("tab") ?? "summary";
  const group = sp.get("group") ?? "complex";
  const fp = filterParams(sp);
  const set = (k: string, v: string) => setSp((p) => { const n = new URLSearchParams(p); n.set(k, v); return n; }, { replace: true });
  const a = useLoad(() => (tab === "summary" ? api<AResp>(`/analytics${qs(new URLSearchParams([...fp, ["group", group]]))}`) : Promise.resolve(null)),
                    [tab, group, fp.toString()]);
  const load = useLoad(() => (tab === "load" ? api<Load[]>("/analytics/load") : Promise.resolve(null)), [tab]);
  const reps = useLoad(() => (tab === "reports" ? api<Rep[]>("/reports") : Promise.resolve(null)), [tab]);
  const { run, busy } = useAction();
  const maxCases = Math.max(1, ...(a.data?.rows ?? []).map((r) => r.cases));
  const maxAw = Math.max(1, ...(a.data?.rows ?? []).map((r) => r.awarded));
  return (
    <>
      <Topbar title="Аналитика" sub="Сколько дел, сколько присуждено от заявленного, где обжалуют и кто перегружен. Фильтры — как в реестре.">
        <div className="seg" role="group" aria-label="Раздел">
          {[["summary", "Сводка"], ["load", "Нагрузка юристов"], ["reports", "Отчёты"]].map(([k, l]) => (
            <button key={k} className={tab === k ? "on" : ""} aria-pressed={tab === k} onClick={() => set("tab", k)}>{l}</button>
          ))}
        </div>
        <a className="btn" href={`/api/v1/reports/analytics.xlsx${qs(fp)}`}>Скачать XLSX</a>
      </Topbar>
      {tab === "summary" && (
        <>
          <div className="row" style={{ marginBottom: 8 }}>
            <span className="muted small">Группировать по</span>
            <select aria-label="Группировка" value={group} onChange={(e) => set("group", e.target.value)}>
              {Object.entries(a.data?.groups ?? { complex: "ЖК" }).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
            <FilterButton page="cases" />
          </div>
          <ActiveChips />
          <ErrorBox error={a.error} />
          {a.data && (
            <div className="panel table-wrap">
              <table>
                <thead><tr><th>{a.data.group_label}</th><th>Дел</th><th>Присуждено</th><th className="right">% от заявленного</th>
                  <th className="right">Обжалование</th><th className="right">Конфликты</th><th className="right">Сроки / просрочено</th></tr></thead>
                <tbody>
                  {a.data.rows.map((r) => (
                    <tr key={r.key}>
                      <td>{r.key}</td>
                      <td className="nowrap"><Bar value={r.cases} max={maxCases} /> {r.cases}</td>
                      <td className="nowrap"><Bar value={r.awarded} max={maxAw} tone="var(--ok)" /> {fmtShortMoney(r.awarded)}
                        <div className="muted small">по {r.with_award} делам</div></td>
                      <td className="right">{r.awarded_pct != null ? `${r.awarded_pct}%` : <span className="muted">—</span>}</td>
                      <td className="right">{r.appeal_pct}%</td>
                      <td className="right">{r.conflicts || ""}</td>
                      <td className="right">{r.open_deadlines}{r.overdue > 0 && <span className="badge overdue" style={{ marginLeft: 6 }}>{r.overdue}</span>}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot><tr><th>Итого</th><th>{a.data.total.cases}</th><th>{fmtShortMoney(a.data.total.awarded)}</th>
                  <th className="right">{a.data.total.claimed ? `${Math.round((1000 * a.data.total.awarded) / a.data.total.claimed) / 10}%` : "—"}</th>
                  <th /><th /><th className="right">{a.data.total.overdue ? `просрочено ${a.data.total.overdue}` : ""}</th></tr></tfoot>
              </table>
            </div>
          )}
          <div className="muted small" style={{ marginTop: 6 }}>% от заявленного — по делам, где известны обе суммы; спорные значения не учитываются.</div>
        </>
      )}
      {tab === "load" && load.data && (
        <div className="panel table-wrap">
          <table>
            <thead><tr><th>Юрист</th><th className="right">Дел</th><th className="right">Открытые сроки</th><th className="right">На неделе</th>
              <th className="right">Просрочено</th><th className="right">Конфликты</th><th className="right">Поручения</th></tr></thead>
            <tbody>
              {load.data.map((r) => (
                <tr key={r.login}>
                  <td><Link to={`/cases?responsible=${encodeURIComponent(r.login)}`}>{r.name}</Link> <span className="muted small">{r.login}</span></td>
                  <td className="right">{r.cases}</td><td className="right">{r.open_deadlines}</td><td className="right">{r.week}</td>
                  <td className="right">{r.overdue > 0 ? <span className="badge overdue">{r.overdue}</span> : 0}</td>
                  <td className="right">{r.conflicts}</td><td className="right">{r.assignments}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {tab === "reports" && (
        <div className="stack">
          <div className="row">
            <span className="muted small">Еженедельный отчёт формируется сам (день и час — в настройках [documents]); администраторы получают уведомление.</span>
            <span className="spacer" />
            {can("admin") && <button disabled={busy} onClick={() => run(async () => { await api("/reports/weekly", { method: "POST" }); reps.reload(); }, "Отчёт сформирован")}>Сформировать сейчас</button>}
          </div>
          <div className="panel table-wrap"><table>
            <thead><tr><th>Отчёт</th><th>Когда</th><th></th></tr></thead>
            <tbody>
              {reps.data?.map((r) => (
                <tr key={r.id}><td>{r.title} <span className="muted small">{r.kind === "weekly" ? "по расписанию" : "вручную"}</span></td>
                  <td className="small">{fmtDateTime(r.created_at)}</td>
                  <td><a href={`/api/v1/reports/${r.id}/file`}>{r.file}</a></td></tr>
              ))}
              {reps.data?.length === 0 && <tr><td colSpan={3} className="empty-state">Отчётов пока нет</td></tr>}
            </tbody>
          </table></div>
        </div>
      )}
    </>
  );
}

// ------------------------------------------------------------------------------------------
// Исполнение
// ------------------------------------------------------------------------------------------

export type Enf = { id: number; case_id: number; side: string; writ_number: string; writ_date: string | null; effective_date: string | null;
  presentation_until: string | null; ip_number: string; fssp_department: string; bailiff: string; start_date: string | null;
  received_date: string | null; status: string; amount: string | null; recovered: string | null; end_date: string | null; notes: string;
  case_number?: string | null; plaintiffs?: string | null };

const STATUSES = ["лист получен", "лист предъявлен", "возбуждено", "окончено", "прекращено", "отозвано", "возвращено"];
const ENF_FIELDS: [keyof Enf, string, string?][] = [
  ["writ_number", "Исполнительный лист (серия, номер)"], ["writ_date", "Выдан", "date"], ["effective_date", "Решение вступило в силу", "date"],
  ["presentation_until", "Предъявить до (если пусто — посчитается)", "date"], ["ip_number", "Номер ИП"], ["fssp_department", "Отдел ФССП"],
  ["bailiff", "Пристав"], ["start_date", "Возбуждено", "date"], ["received_date", "Получено постановление", "date"],
  ["amount", "Сумма по листу, ₽"], ["recovered", "Взыскано / уплачено, ₽"], ["end_date", "Окончено", "date"],
];

export function EnforcementForm({ caseId, e, onClose, onDone }: { caseId: number; e?: Enf; onClose: () => void; onDone: () => void }) {
  const [f, setF] = useState<Partial<Enf>>(e ?? { side: "debtor", status: "лист получен" });
  const { run, busy } = useAction();
  const save = () => run(async () => {
    const body = Object.fromEntries(Object.entries(f).filter(([k]) => !["id", "case_id", "case_number", "plaintiffs", "created_at", "updated_at"].includes(k))
      .map(([k, v]) => [k, v === "" ? null : v]));
    if (e) await api(`/enforcement/${e.id}`, { method: "PATCH", json: body });
    else await api("/enforcement", { method: "POST", json: { ...body, case_id: caseId } });
    onDone();
    onClose();
  }, "Сохранено");
  return (
    <Modal title={e ? "Исполнительное производство" : "Новый лист / производство"} onClose={onClose} width={720}
           footer={<><button onClick={onClose}>Отмена</button><button className="primary" disabled={busy} onClick={save}>Сохранить</button></>}>
      <div className="form-grid">
        <label className="field">Кто платит
          <select value={f.side} onChange={(x) => setF({ ...f, side: x.target.value })}>
            <option value="debtor">взыскивают с нас (должник — наше юрлицо)</option>
            <option value="creditor">мы взыскиваем</option>
          </select>
        </label>
        <label className="field">Статус
          <select value={f.status} onChange={(x) => setF({ ...f, status: x.target.value })}>{STATUSES.map((s) => <option key={s}>{s}</option>)}</select>
        </label>
        {ENF_FIELDS.map(([k, label, type]) => (
          <label key={k} className="field">{label}
            <input type={type ?? "text"} value={String(f[k] ?? "")} onChange={(x) => setF({ ...f, [k]: x.target.value })} />
          </label>
        ))}
        <label className="field wide">Заметки<textarea rows={2} value={f.notes ?? ""} onChange={(x) => setF({ ...f, notes: x.target.value })} /></label>
      </div>
      <div className="muted small" style={{ marginTop: 8 }}>
        Сроки ставятся сами: должник — 5 рабочих дней на добровольное исполнение со дня получения постановления (иначе сбор 7 %);
        взыскатель — предъявить лист до указанной даты (3 года от вступления в силу).
      </div>
    </Modal>
  );
}

export function EnforcementTable({ items, reload, showCase = true }: { items: Enf[]; reload: () => void; showCase?: boolean }) {
  const { can } = useSession();
  const [edit, setEdit] = useState<Enf | null>(null);
  if (!items.length) return <div className="panel empty-state">Исполнительных листов и производств нет</div>;
  return (
    <div className="panel table-wrap">
      <table>
        <thead><tr>{showCase && <th>Дело</th>}<th>Сторона</th><th>Лист / ИП</th><th>Статус</th><th className="right">Сумма</th><th className="right">Взыскано</th><th>Срок</th><th></th></tr></thead>
        <tbody>
          {items.map((e) => (
            <tr key={e.id}>
              {showCase && <td><Link to={`/cases/${e.case_id}?tab=enforcement`}>{e.case_number || `#${e.case_id}`}</Link><div className="small muted">{e.plaintiffs}</div></td>}
              <td className="small">{e.side === "debtor" ? "с нас" : "в нашу пользу"}</td>
              <td className="small">{e.writ_number || "—"}<div className="mono">{e.ip_number}</div><div className="muted">{e.fssp_department}</div></td>
              <td><span className={`badge ${["окончено", "прекращено", "отозвано", "возвращено"].includes(e.status) ? "done" : "single"}`}>{e.status}</span></td>
              <td className="right nowrap">{e.amount ? fmtShortMoney(Number(e.amount)) : "—"}</td>
              <td className="right nowrap">{e.recovered ? fmtShortMoney(Number(e.recovered)) : "—"}</td>
              <td className="small nowrap">{e.presentation_until && e.side === "creditor" ? `предъявить до ${fmtDate(e.presentation_until)}` : e.start_date ? `возбуждено ${fmtDate(e.start_date)}` : ""}</td>
              <td>{can("lawyer") && <button className="link small" onClick={() => setEdit(e)}>изменить</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {edit && <EnforcementForm caseId={edit.case_id} e={edit} onClose={() => setEdit(null)} onDone={reload} />}
    </div>
  );
}

export function EnforcementPage() {
  const [sp, setSp] = useSearchParams();
  const active = sp.get("active") ?? "1";
  const side = sp.get("side") ?? "";
  const list = useLoad(() => api<Enf[]>(`/enforcement${qs({ active: active === "" ? undefined : active === "1", side })}`), [active, side]);
  const set = (k: string, v: string) => setSp((p) => { const n = new URLSearchParams(p); n.set(k, v); return n; }, { replace: true });
  return (
    <>
      <Topbar title="Исполнение" sub="Исполнительные листы и производства. Новое — из карточки дела, вкладка «Исполнение» (или загрузка из ФССП/1С).">
        <select aria-label="Состояние" value={active} onChange={(e) => set("active", e.target.value)}>
          <option value="1">Действующие</option><option value="0">Завершённые</option><option value="">Все</option>
        </select>
        <select aria-label="Сторона" value={side} onChange={(e) => set("side", e.target.value)}>
          <option value="">Обе стороны</option><option value="debtor">С нас</option><option value="creditor">В нашу пользу</option>
        </select>
      </Topbar>
      <ErrorBox error={list.error} />
      {list.data && <EnforcementTable items={list.data} reload={list.reload} />}
    </>
  );
}

export function EnforcementTab({ caseId, onChanged }: { caseId: number; onChanged?: () => void }) {
  const { can } = useSession();
  const [adding, setAdding] = useState(false);
  const list = useLoad(() => api<Enf[]>(`/enforcement?case_id=${caseId}`), [caseId]);
  const changed = () => { list.reload(); onChanged?.(); }; // сроки исполнения появились в деле — перечитать карточку
  return (
    <div className="stack">
      <div className="row"><span className="spacer" />{can("lawyer") && <button onClick={() => setAdding(true)}>+ Лист / производство</button>}</div>
      {list.data && <EnforcementTable items={list.data} reload={changed} showCase={false} />}
      {adding && <EnforcementForm caseId={caseId} onClose={() => setAdding(false)} onDone={changed} />}
    </div>
  );
}
