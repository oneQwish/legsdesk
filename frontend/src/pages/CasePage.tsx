import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Topbar, useSession } from "../App";
import { ACTION_LABEL, api, fmtDate, fmtDateTime, fmtValue, shortCourt, type Assignment, type CaseFull, type CaseValue, type Deadline, type EventItem, type Hearing } from "../api";
import AwardBar, { type AwardPart } from "../components/AwardBar";
import CasePath from "../components/CasePath";
import CaseForm from "../components/CaseForm";
import { AssignmentList, AssignmentModal, Discussion, HearingList, PinnedNotes } from "../components/Work";
import Chronology from "../components/Chronology";
import ResolvePanel, { ObservationLine } from "../components/ResolvePanel";
import { PromptModal, useToast } from "../components/overlay";
import { DueBadge, ErrorBox, StatusBadge, clickable, useAction, useLoad } from "../components/ui";

type Tab = "values" | "chronology" | "documents" | "deadlines" | "journal" | "discussion" | "work";
const TABS: Tab[] = ["values", "chronology", "documents", "deadlines", "journal", "discussion", "work"];

export default function CasePage() {
  const { id } = useParams();
  const { can, refreshStats } = useSession();
  const nav = useNavigate();
  // вкладка — из ссылки (уведомление ведёт сразу в «Обсуждение» или «Сроки»)
  const [sp] = useSearchParams();
  const [tab, setTab] = useState<Tab>(TABS.includes(sp.get("tab") as Tab) ? (sp.get("tab") as Tab) : "values");
  const [giving, setGiving] = useState(false);
  const [dialog, setDialog] = useState<"" | "responsible" | "merge" | "edit">("");
  const toast = useToast();
  const c = useLoad(() => api<CaseFull>(`/cases/${id}`), [id]);
  const data = c.data;

  if (c.error) return <ErrorBox error={c.error} />;
  if (!data) return null;

  const replaceValue = (v: CaseValue) => {
    c.setData({ ...data, values: data.values.map((x) => (x.id === v.id ? v : x)) });
    refreshStats();
    toast(v.status === "resolved" ? `${v.label}: принято ${fmtValue(v.kind, v.value)}` : `${v.label}: решение отменено`);
  };

  const conflicts = data.values.filter(disputedV).length;
  const sums = amounts(data.values);
  const openDl = data.deadlines.filter((d) => d.status === "open").length;

  return (
    <>
      <Topbar
        title={<><span className="muted small" style={{ fontFamily: "var(--sans)", fontWeight: 400, display: "block" }}><Link to="/cases">Дела</Link> / #{data.id}</span>Дело № {data.case_number || "без номера"}</>}
        sub={<span title={data.court_name}>{shortCourt(data.court_name)}{data.uid ? <> · УИД <span className="mono">{data.uid}</span></> : <> · <span className="badge appeal_possible">УИД нет</span></>}</span>}>
        {can("lawyer") && (
          <div className="row">
            <button onClick={() => setDialog("edit")}>Реквизиты…</button>
            <button onClick={() => setGiving(true)}>Поручение…</button>
            <button onClick={() => setDialog("responsible")}>Ответственный</button>
            <button onClick={() => setDialog("merge")}>Слить дубль…</button>
          </div>
        )}
      </Topbar>

      <CasePath c={data} />
      <PinnedNotes caseId={data.id} />
      <div className="case-summary">
      <div className="panel pad">
        <div className="facts">
          <div><span>Истцы</span>{data.plaintiffs || "—"}</div>
          <div><span>Ответчик</span>{data.legal_entity || "—"}</div>
          <div><span>Объект</span>{[data.complex, data.building && `корп. ${data.building}`, data.flat && `кв. ${data.flat}`].filter(Boolean).join(", ") || "—"}</div>
          <div><span>Договор</span><span className="mono">{data.contract_no || "—"}</span></div>
          <div><span>Предмет</span>{data.subject || "—"}</div>
          <div><span>Стадия / статус</span>{[data.stage, data.status].filter(Boolean).join(" · ") || "—"}</div>
          <div><span>Исход</span>{data.outcome || "—"}</div>
          <div><span>Ответственный</span>{data.responsible || "—"}</div>
          <div>
            <span>Номера дела</span>
            {data.aliases.map((a) => <span key={a.number} className="badge single" style={{ marginRight: 4 }}>{a.number}</span>)}
          </div>
          {Array.isArray(data.extra.other_uids) && (data.extra.other_uids as string[]).length > 0 && (
            <div><span>Спорные УИД</span>{(data.extra.other_uids as string[]).map((u) => <div key={u} className="mono">{u}</div>)}</div>
          )}
        </div>
      </div>
      <div className="panel"><AwardBar claimed={sums.claimed} awarded={sums.awarded} parts={sums.parts} /></div>
      </div>

      <div className="tabs">
        <button className={tab === "values" ? "on" : ""} onClick={() => setTab("values")}>
          Поля и источники {conflicts > 0 && <span className="badge conflict">{conflicts}</span>}
        </button>
        <button className={tab === "documents" ? "on" : ""} onClick={() => setTab("documents")}>Документы ({data.documents.length})</button>
        <button className={tab === "deadlines" ? "on" : ""} onClick={() => setTab("deadlines")}>
          Сроки {openDl > 0 && <span className="badge single">{openDl}</span>}
        </button>
        <button className={tab === "chronology" ? "on" : ""} onClick={() => setTab("chronology")}>Хронология</button>
        <button className={tab === "discussion" ? "on" : ""} onClick={() => setTab("discussion")}>Обсуждение</button>
        <button className={tab === "work" ? "on" : ""} onClick={() => setTab("work")}>Поручения и заседания</button>
        <button className={tab === "journal" ? "on" : ""} onClick={() => setTab("journal")}>Журнал</button>
      </div>

      {tab === "values" && <ValuesTab values={data.values} onChange={replaceValue} />}
      {tab === "documents" && (
        <div className="panel table-wrap">
          <table>
            <thead><tr><th>Дата</th><th>Вид акта</th><th>Инстанция</th><th>Тип</th><th>Файл</th><th>Привязка</th></tr></thead>
            <tbody>
              {data.documents.map((d) => (
                <tr key={d.id} className="clickable" {...clickable(() => nav(`/documents/${d.id}`))}>
                  <td className="nowrap">{fmtDate(d.act_date)}</td>
                  <td>{d.act_type || <span className="muted">не определён</span>}</td>
                  <td>{d.instance}</td>
                  <td>{d.kind}{d.track_no && <div className="mono muted">{d.track_no}</div>}</td>
                  <td className="small">{d.filename}</td>
                  <td className="small muted">{d.link_method}</td>
                </tr>
              ))}
              {data.documents.length === 0 && <tr><td colSpan={6} className="empty-state">Документов нет</td></tr>}
            </tbody>
          </table>
        </div>
      )}
      {tab === "deadlines" && <DeadlinesTab caseId={data.id} deadlines={data.deadlines} reload={c.reload} />}
      {tab === "chronology" && <Chronology c={data} />}
      {tab === "journal" && <JournalTab caseId={data.id} />}
      {tab === "discussion" && <Discussion caseId={data.id} />}
      {tab === "work" && <WorkTab caseId={data.id} onGive={() => setGiving(true)} />}
      {giving && <AssignmentModal caseId={data.id} onClose={() => setGiving(false)} onDone={() => setTab("work")} />}

      {dialog === "edit" && <CaseForm c={data} onClose={() => setDialog("")} onSaved={c.reload} />}
      {dialog === "responsible" && (
        <PromptModal title="Ответственный юрист" label="Логин или ФИО" initial={data.responsible} onClose={() => setDialog("")}
          onSubmit={async (v) => {
            await api(`/cases/${data.id}`, { method: "PATCH", json: { responsible: v } });
            c.reload();
            toast("Ответственный назначен");
          }} />
      )}
      {dialog === "merge" && (
        <PromptModal title="Слить дубль в это дело" label="ID дела-дубля" type="number" okText="Слить" onClose={() => setDialog("")}
          hint="Номера, значения источников, документы и сроки дубля перейдут в это дело, дубль будет удалён. Действие пишется в журнал."
          onSubmit={async (v) => {
            await api(`/cases/${data.id}/merge/${Number(v)}`, { method: "POST" });
            c.reload();
            toast(`Дело #${v} слито`);
          }} />
      )}
    </>
  );
}

const disputedV = (v: CaseValue) => v.status === "conflict" || v.status === "appeal_possible";
const numV = (v: CaseValue) => Number(String(v.value ?? "").replace(/[^\d.,-]/g, "").replace(",", "."));

/** Заявлено, присуждено (согласованные денежные поля без спорных) и разбивка по категориям. */
function amounts(values: CaseValue[]): { claimed: number | null; awarded: number | null; parts: AwardPart[] } {
  const claim = values.find((v) => v.field === "claim_total" && !disputedV(v) && v.value);
  const parts = values
    .filter((v) => v.kind === "money" && v.field !== "claim_total" && !disputedV(v) && v.value)
    .map((v) => ({ label: v.label, value: numV(v) || 0 }))
    .filter((p) => p.value > 0)
    .sort((a, b) => b.value - a.value);
  const awarded = parts.length ? parts.reduce((a, p) => a + p.value, 0) : null;
  return { claimed: claim ? numV(claim) : null, awarded, parts };
}

function ValuesTab({ values, onChange }: { values: CaseValue[]; onChange: (v: CaseValue) => void }) {
  const [open, setOpen] = useState<number | null>(values.find((v) => v.status === "conflict" || v.status === "appeal_possible")?.id ?? null);
  const groups = [...new Set(values.map((v) => v.group))];
  if (values.length === 0) return <div className="panel empty-state">Источники ещё не прислали значений по этому делу</div>;
  const money = values.filter((v) => v.kind === "money" && v.field !== "claim_total");
  const disputed = disputedV;
  const total = money.filter((v) => !disputed(v) && v.value).reduce((a, v) => a + (numV(v) || 0), 0);
  const anyDisputed = money.some(disputed);
  return (
    <div className="stack">
      {money.length > 0 && (
        <div className="sums">
          {money.map((v) => (
            <div key={v.id} className={disputed(v) ? "disputed" : ""} style={{ cursor: "pointer" }} {...clickable(() => setOpen(v.id))}>
              <div className="l">{v.label}</div>
              <div className="v">{disputed(v) ? "расходятся ↓" : fmtValue(v.kind, v.value)}</div>
            </div>
          ))}
          <div className="total">
            <div className="l">Взыскано всего{anyDisputed && " (без спорных)"}</div>
            <div className="v">{fmtValue("money", String(total))}</div>
          </div>
        </div>
      )}
      {groups.map((g) => (
        <div key={g}>
          <div className="group-title">{g}</div>
          <div className="panel table-wrap">
            <table>
              <tbody>
                {values.filter((v) => v.group === g).map((v) => (
                  <ValueRow key={v.id} v={v} open={open === v.id} toggle={() => setOpen(open === v.id ? null : v.id)} onChange={onChange} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </div>
  );
}

function ValueRow({ v, open, toggle, onChange }: { v: CaseValue; open: boolean; toggle: () => void; onChange: (v: CaseValue) => void }) {
  const { can } = useSession();
  const disputed = disputedV(v);
  return (
    <>
      <tr className="clickable" {...clickable(toggle)} aria-expanded={open}>
        <td style={{ width: "28%" }}>{v.label}</td>
        <td><b>{disputed ? <span className="muted">источники расходятся</span> : fmtValue(v.kind, v.value)}</b></td>
        <td className="nowrap"><StatusBadge status={v.status} /></td>
        <td className="right muted small nowrap">{v.observations.map((o) => o.source).join(", ")} {open ? "▲" : "▼"}</td>
      </tr>
      {open && (
        <tr>
          <td colSpan={4} style={{ background: "var(--panel-2)" }}>
            {disputed || v.status === "resolved" || can("lawyer") ? (
              <ResolvePanel value={v} onDone={onChange} />
            ) : (
              <div className="panel">{v.observations.map((o) => <ObservationLine key={o.id} o={o} kind={v.kind} />)}</div>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

function DeadlinesTab({ caseId, deadlines, reload }: { caseId: number; deadlines: Deadline[]; reload: () => void }) {
  const { can, refreshStats } = useSession();
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const [editing, setEditing] = useState<Deadline | null>(null);
  const toast = useToast();
  const { run, busy } = useAction();
  const save = async (d: Deadline, body: Partial<Deadline>) => {
    await api(`/deadlines/${d.id}`, { method: "PATCH", json: body });
    reload();
    refreshStats();
  };
  const patch = (d: Deadline, body: Partial<Deadline>) =>
    run(() => save(d, body), body.status === "done" ? `«${d.title}» — выполнено` : undefined);
  const add = () => run(async () => {
    await api(`/cases/${caseId}/deadlines`, { method: "POST", json: { title, due_date: due } });
    setTitle("");
    setDue("");
    reload();
    refreshStats();
  }, "Срок добавлен");
  const recalc = () => run(async () => {
    await api(`/cases/${caseId}/deadlines/recalc`, { method: "POST" });
    reload();
  }, "Сроки пересчитаны по актам");
  return (
    <div className="stack">
      <div className="panel table-wrap">
        <table>
          <thead><tr><th>Срок</th><th>Что</th><th>Как посчитано</th><th>Статус</th><th></th></tr></thead>
          <tbody>
            {deadlines.map((d) => (
              <tr key={d.id}>
                <td className="nowrap">
                  <b>{fmtDate(d.due_date)}</b>
                  <div><DueBadge due={d.due_date} status={d.status} /></div>
                </td>
                <td>
                  {d.title}
                  {d.document_id && <div className="small"><Link to={`/documents/${d.document_id}`}>акт</Link></div>}
                </td>
                <td className="small" style={{ maxWidth: 420 }}>
                  <details className="rule"><summary>{d.rule.split(":")[0]}</summary><div>{d.rule}</div></details>
                  {!d.calendar_confirmed && <div className="notice small" style={{ marginTop: 4 }}>Производственный календарь года не загружен — переносы праздников не учтены</div>}
                  {d.note && <div className="muted">{d.note}</div>}
                </td>
                <td className="small">{d.auto ? "авто" : "вручную"}</td>
                <td className="nowrap">
                  {can("lawyer") && d.status === "open" && (
                    <>
                      <button disabled={busy} onClick={() => patch(d, { status: "done" })}>Выполнено</button>{" "}
                      <button onClick={() => setEditing(d)}>Дата…</button>
                    </>
                  )}
                  {can("lawyer") && d.status !== "open" && <button disabled={busy} onClick={() => patch(d, { status: "open" })}>Вернуть</button>}
                </td>
              </tr>
            ))}
            {deadlines.length === 0 && <tr><td colSpan={5} className="empty-state">Сроков нет: они появятся, когда к делу будет привязан акт с датой</td></tr>}
          </tbody>
        </table>
      </div>
      {can("lawyer") && (
        <div className="panel pad row">
          <input className="grow" aria-label="Название своего срока" placeholder="Свой срок: напр. «подать возражения на апелляционную жалобу»" value={title} onChange={(e) => setTitle(e.target.value)} />
          <input type="date" aria-label="Дата срока" value={due} onChange={(e) => setDue(e.target.value)} />
          <button className="primary" disabled={!title || !due || busy} onClick={add}>Добавить</button>
          <button onClick={recalc} disabled={busy} title="Пересчитать автоматические сроки по актам дела">Пересчитать</button>
        </div>
      )}
      {editing && (
        <PromptModal title={`Изменить срок: ${editing.title}`} label="Новая дата" type="date" initial={editing.due_date}
          hint="После ручной правки срок больше не пересчитывается автоматически (например, при загрузке производственного календаря)."
          onClose={() => setEditing(null)}
          onSubmit={async (v) => {
            await save(editing, { due_date: v });
            toast("Дата срока изменена");
          }} />
      )}
    </div>
  );
}

function JournalTab({ caseId }: { caseId: number }) {
  const ev = useLoad(() => api<EventItem[]>(`/cases/${caseId}/events`), [caseId]);
  return (
    <div className="panel table-wrap">
      <table>
        <thead><tr><th>Когда</th><th>Кто</th><th>Действие</th><th>Подробности</th></tr></thead>
        <tbody>
          {ev.data?.map((e) => (
            <tr key={e.id}>
              <td className="nowrap small">{fmtDateTime(e.ts)}</td>
              <td className="small">{e.actor}<div className="muted">{e.actor_type === "service" ? "сервис" : e.actor_type === "user" ? "пользователь" : "система"}</div></td>
              <td>{ACTION_LABEL[e.action] ?? e.action}</td>
              <td className="small mono" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{describe(e)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function describe(e: EventItem): string {
  const d = e.data as Record<string, unknown>;
  if (e.action === "value_resolved") {
    const after = (d.after as { value?: string })?.value;
    return `${d.field}: ${after} (выбрано: ${d.chosen})${d.note ? ` — ${d.note}` : ""}`;
  }
  if (e.action === "value_status") return `${d.field}: ${d.old} → ${d.new}`;
  return Object.keys(d).length ? JSON.stringify(d, null, 0) : "";
}

function WorkTab({ caseId, onGive }: { caseId: number; onGive: () => void }) {
  const { can } = useSession();
  const a = useLoad(() => api<Assignment[]>(`/assignments?case_id=${caseId}&status=open,done,cancelled`), [caseId]);
  const h = useLoad(() => api<Hearing[]>(`/hearings?case_id=${caseId}`), [caseId]);
  return (
    <div className="stack">
      <div className="row"><div className="group-title" style={{ margin: 0 }}>Поручения</div><span className="spacer" />
        {can("lawyer") && <button onClick={onGive}>+ Поручение</button>}</div>
      {a.data && <AssignmentList items={a.data} reload={a.reload} showCase={false} />}
      <div className="group-title">Заседания (из судебного календаря)</div>
      {h.data && <HearingList items={h.data} reload={h.reload} showCase={false} />}
    </div>
  );
}
