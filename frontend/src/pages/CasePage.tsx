import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useSession } from "../App";
import { ACTION_LABEL, api, fmtDate, fmtDateTime, fmtValue, type CaseFull, type CaseValue, type Deadline, type EventItem } from "../api";
import ResolvePanel, { ObservationLine } from "../components/ResolvePanel";
import { DueBadge, ErrorBox, StatusBadge, useLoad } from "../components/ui";

type Tab = "values" | "documents" | "deadlines" | "journal";

export default function CasePage() {
  const { id } = useParams();
  const { can, refreshStats } = useSession();
  const nav = useNavigate();
  const [tab, setTab] = useState<Tab>("values");
  const c = useLoad(() => api<CaseFull>(`/cases/${id}`), [id]);
  const data = c.data;

  if (c.error) return <ErrorBox error={c.error} />;
  if (!data) return null;

  const replaceValue = (v: CaseValue) => {
    c.setData({ ...data, values: data.values.map((x) => (x.id === v.id ? v : x)) });
    refreshStats();
  };

  const conflicts = data.values.filter((v) => v.status === "conflict" || v.status === "appeal_possible").length;
  const openDl = data.deadlines.filter((d) => d.status === "open").length;

  const setResponsible = async () => {
    const r = prompt("Ответственный юрист (логин или ФИО):", data.responsible);
    if (r === null) return;
    await api(`/cases/${data.id}`, { method: "PATCH", json: { responsible: r } });
    c.reload();
  };
  const merge = async () => {
    const other = prompt("ID дела-дубля, которое нужно влить в это дело (номера, значения, документы и сроки перейдут сюда):");
    if (!other) return;
    try {
      await api(`/cases/${data.id}/merge/${Number(other)}`, { method: "POST" });
      c.reload();
    } catch (e) {
      alert((e as Error).message);
    }
  };

  return (
    <>
      <div className="page-head">
        <div className="grow">
          <div className="muted small"><Link to="/cases">Дела</Link> / #{data.id}</div>
          <h1>Дело {data.case_number || "без номера"}</h1>
          <div className="muted">
            {data.court_name}
            {data.uid ? <> · УИД <span className="mono">{data.uid}</span></> : <> · <span className="badge appeal_possible">УИД нет</span></>}
          </div>
        </div>
        {can("lawyer") && (
          <div className="row">
            <button onClick={setResponsible}>Ответственный</button>
            <button onClick={merge}>Слить дубль…</button>
          </div>
        )}
      </div>

      <div className="panel pad" style={{ marginBottom: 14 }}>
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

      <div className="tabs">
        <button className={tab === "values" ? "on" : ""} onClick={() => setTab("values")}>
          Поля и источники {conflicts > 0 && <span className="badge conflict">{conflicts}</span>}
        </button>
        <button className={tab === "documents" ? "on" : ""} onClick={() => setTab("documents")}>Документы ({data.documents.length})</button>
        <button className={tab === "deadlines" ? "on" : ""} onClick={() => setTab("deadlines")}>
          Сроки {openDl > 0 && <span className="badge single">{openDl}</span>}
        </button>
        <button className={tab === "journal" ? "on" : ""} onClick={() => setTab("journal")}>Журнал</button>
      </div>

      {tab === "values" && <ValuesTab values={data.values} onChange={replaceValue} />}
      {tab === "documents" && (
        <div className="panel table-wrap">
          <table>
            <thead><tr><th>Дата</th><th>Вид акта</th><th>Инстанция</th><th>Тип</th><th>Файл</th><th>Привязка</th></tr></thead>
            <tbody>
              {data.documents.map((d) => (
                <tr key={d.id} className="clickable" onClick={() => nav(`/documents/${d.id}`)}>
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
      {tab === "journal" && <JournalTab caseId={data.id} />}
    </>
  );
}

function ValuesTab({ values, onChange }: { values: CaseValue[]; onChange: (v: CaseValue) => void }) {
  const [open, setOpen] = useState<number | null>(values.find((v) => v.status === "conflict" || v.status === "appeal_possible")?.id ?? null);
  const groups = [...new Set(values.map((v) => v.group))];
  if (values.length === 0) return <div className="panel empty-state">Источники ещё не прислали значений по этому делу</div>;
  return (
    <div className="stack">
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
  const disputed = v.status === "conflict" || v.status === "appeal_possible";
  return (
    <>
      <tr className="clickable" onClick={toggle}>
        <td style={{ width: "28%" }}>{v.label}</td>
        <td><b>{disputed ? <span className="muted">источники расходятся</span> : fmtValue(v.kind, v.value)}</b></td>
        <td className="nowrap"><StatusBadge status={v.status} /></td>
        <td className="right muted small nowrap">{v.observations.map((o) => o.source).join(", ")} {open ? "▲" : "▼"}</td>
      </tr>
      {open && (
        <tr>
          <td colSpan={4} style={{ background: "var(--panel-2)" }}>
            {disputed || v.status === "resolved" ? (
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
  const [err, setErr] = useState("");
  const patch = async (d: Deadline, body: Partial<Deadline>) => {
    await api(`/deadlines/${d.id}`, { method: "PATCH", json: body });
    reload();
    refreshStats();
  };
  const add = async () => {
    try {
      await api(`/cases/${caseId}/deadlines`, { method: "POST", json: { title, due_date: due } });
      setTitle("");
      setDue("");
      reload();
      refreshStats();
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  const recalc = async () => {
    await api(`/cases/${caseId}/deadlines/recalc`, { method: "POST" });
    reload();
  };
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
                <td className="small" style={{ whiteSpace: "pre-wrap", maxWidth: 420 }}>
                  {d.rule}
                  {!d.calendar_confirmed && <div className="notice small" style={{ marginTop: 4 }}>Календарь года не загружен из 1С — переносы праздников не учтены</div>}
                  {d.note && <div className="muted">{d.note}</div>}
                </td>
                <td className="small">{d.auto ? "авто" : "вручную"}</td>
                <td className="nowrap">
                  {can("lawyer") && d.status === "open" && (
                    <>
                      <button onClick={() => patch(d, { status: "done" })}>Выполнено</button>{" "}
                      <button onClick={() => {
                        const v = prompt("Новая дата (ГГГГ-ММ-ДД). После правки срок не пересчитывается автоматически.", d.due_date);
                        if (v) patch(d, { due_date: v });
                      }}>Дата…</button>
                    </>
                  )}
                  {can("lawyer") && d.status !== "open" && <button onClick={() => patch(d, { status: "open" })}>Вернуть</button>}
                </td>
              </tr>
            ))}
            {deadlines.length === 0 && <tr><td colSpan={5} className="empty-state">Сроков нет: они появятся, когда к делу будет привязан акт с датой</td></tr>}
          </tbody>
        </table>
      </div>
      {can("lawyer") && (
        <div className="panel pad row">
          <input className="grow" placeholder="Свой срок: напр. «подать возражения на апелляционную жалобу»" value={title} onChange={(e) => setTitle(e.target.value)} />
          <input type="date" value={due} onChange={(e) => setDue(e.target.value)} />
          <button className="primary" disabled={!title || !due} onClick={add}>Добавить</button>
          <button onClick={recalc} title="Пересчитать автоматические сроки по актам дела">Пересчитать</button>
          {err && <div className="error">{err}</div>}
        </div>
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
