import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link, useNavigate } from "react-router-dom";
import { useSession } from "../App";
import { api, cachedApi, fmtDate, fmtDateTime, type Assignment, type Comment, type Hearing, type Notice, type UserLogin } from "../api";
import { Icon } from "./icons";
import { Modal, useToast } from "./overlay";
import { DueBadge, ErrorBox, useAction, useLoad } from "./ui";

// ------------------------------------------------------------------------------------------
// Колокольчик: уведомления пользователя (сроки, поручения, упоминания, конфликты, заседания)
// ------------------------------------------------------------------------------------------

export function Bell() {
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<{ unread: number; items: Notice[] }>({ unread: 0, items: [] });
  const box = useRef<HTMLDivElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  const load = () => api<{ unread: number; items: Notice[] }>("/notifications?limit=30").then(setData).catch(() => undefined);
  useEffect(() => {
    load();
    const t = setInterval(load, 60000); // раз в минуту — новые уведомления без перезагрузки страницы
    return () => clearInterval(t);
  }, []);
  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => {
      const t = e.target as Node;
      if (!box.current?.contains(t) && !pop.current?.contains(t)) setOpen(false);
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);
  const go = async (n: Notice) => {
    setOpen(false);
    if (!n.read_at) await api("/notifications/read", { method: "POST", json: [n.id] }).catch(() => undefined);
    load();
    if (n.link) nav(n.link);
  };
  const readAll = async () => {
    await api("/notifications/read", { method: "POST", json: [] }).catch(() => undefined);
    load();
  };
  return (
    <div className="bell" ref={box}>
      <button onClick={() => { setOpen(!open); if (!open) load(); }} data-tip="Уведомления" aria-label={`Уведомления: непрочитанных ${data.unread}`}
              aria-expanded={open}>
        <Icon name="bell" size={20} />
        {data.unread > 0 && <span className="dot">{data.unread > 99 ? "99+" : data.unread}</span>}
      </button>
      {open && createPortal(
        <div className="bell-pop panel" role="dialog" aria-label="Уведомления" ref={pop}>
          <div className="row pad" style={{ paddingBottom: 6 }}>
            <b>Уведомления</b><span className="spacer" />
            {data.unread > 0 && <button className="link small" onClick={readAll}>прочитать все</button>}
          </div>
          <div className="bell-list">
            {data.items.map((n) => (
              <button key={n.id} className={`bell-item ${n.read_at ? "" : "unread"}`} onClick={() => go(n)}>
                <span className={`bell-kind k-${n.kind}`} />
                <span className="grow">
                  <span className="t">{n.title}</span>
                  {n.body && <span className="b">{n.body}</span>}
                  <span className="muted small">{fmtDateTime(n.created_at)}</span>
                </span>
              </button>
            ))}
            {data.items.length === 0 && <div className="empty-state small">Уведомлений нет</div>}
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}

// ------------------------------------------------------------------------------------------
// Поручения
// ------------------------------------------------------------------------------------------

export function useLogins() {
  const [list, setList] = useState<UserLogin[]>([]);
  useEffect(() => {
    cachedApi<UserLogin[]>("/users/logins", 60000).then(setList).catch(() => undefined);
  }, []);
  return list;
}

/** Окно «Дать поручение»: по одному делу, по нескольким (caseIds) или без дела. */
export function AssignmentModal({ caseId, caseIds, onClose, onDone }: { caseId?: number; caseIds?: number[]; onClose: () => void; onDone?: () => void }) {
  const logins = useLogins();
  const { me } = useSession();
  const [f, setF] = useState({ title: "", body: "", assignee: me.login, due_date: "" });
  const { run, busy } = useAction();
  const n = caseIds?.length ?? 0;
  const save = () => run(async () => {
    await api("/assignments", { method: "POST", json: { ...f, due_date: f.due_date || null, case_id: caseId ?? null, case_ids: caseIds ?? [] } });
    onDone?.();
    onClose();
  }, n > 1 ? `Поручения даны по ${n} делам` : "Поручение дано");
  return (
    <Modal title={n > 1 ? `Поручение по ${n} делам` : "Поручение"} onClose={onClose}
           footer={<><button onClick={onClose}>Отмена</button><button className="primary" disabled={busy || !f.title.trim() || !f.assignee} onClick={save}>Дать поручение</button></>}>
      <div className="form-grid">
        <label className="field wide">Что сделать
          <input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} placeholder="напр.: подготовить возражения на апелляционную жалобу" />
        </label>
        <label className="field">Кому
          <select value={f.assignee} onChange={(e) => setF({ ...f, assignee: e.target.value })}>
            {!logins.some((u) => u.login === f.assignee) && <option value={f.assignee}>{f.assignee}</option>}
            {logins.filter((u) => u.role !== "viewer").map((u) => <option key={u.login} value={u.login}>{u.name} ({u.login})</option>)}
          </select>
        </label>
        <label className="field">Срок
          <input type="date" value={f.due_date} onChange={(e) => setF({ ...f, due_date: e.target.value })} />
        </label>
        <label className="field wide">Подробности
          <textarea rows={3} value={f.body} onChange={(e) => setF({ ...f, body: e.target.value })} />
        </label>
      </div>
    </Modal>
  );
}

export function AssignmentList({ items, reload, showCase = true }: { items: Assignment[]; reload: () => void; showCase?: boolean }) {
  const { can, me } = useSession();
  const { run, busy } = useAction();
  const setStatus = (a: Assignment, status: string) => run(async () => {
    const result = status === "done" ? window.prompt("Что сделано (необязательно)?", "") ?? "" : "";
    await api(`/assignments/${a.id}`, { method: "PATCH", json: { status, result } });
    reload();
  }, status === "done" ? "Поручение выполнено" : undefined);
  if (!items.length) return <div className="panel empty-state">Поручений нет</div>;
  return (
    <div className="panel table-wrap">
      <table>
        <thead><tr><th>Срок</th><th>Что</th>{showCase && <th>Дело</th>}<th>Кому / от кого</th><th></th></tr></thead>
        <tbody>
          {items.map((a) => (
            <tr key={a.id} style={{ opacity: a.status === "open" ? 1 : 0.6 }}>
              <td className="nowrap">{a.due_date ? <><b>{fmtDate(a.due_date)}</b><div><DueBadge due={a.due_date} status={a.status} /></div></> : <span className="muted">без срока</span>}</td>
              <td>{a.title}{a.body && <div className="muted small">{a.body}</div>}{a.result && <div className="small">✓ {a.result}</div>}</td>
              {showCase && <td>{a.case_id ? <Link to={`/cases/${a.case_id}`}>{a.case_number || `#${a.case_id}`}</Link> : "—"}<div className="small muted">{a.plaintiffs}</div></td>}
              <td className="small">{a.assignee}<div className="muted">от {a.author}</div></td>
              <td className="nowrap">
                {can("lawyer") && a.status === "open" && <>
                  <button disabled={busy} onClick={() => setStatus(a, "done")}>Выполнено</button>{" "}
                  {(a.author === me.login || can("admin")) && <button className="link small muted" disabled={busy} onClick={() => setStatus(a, "cancelled")}>отменить</button>}
                </>}
                {can("lawyer") && a.status !== "open" && <button className="link small" disabled={busy} onClick={() => setStatus(a, "open")}>вернуть</button>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ------------------------------------------------------------------------------------------
// Обсуждение в деле
// ------------------------------------------------------------------------------------------

function MentionText({ text }: { text: string }) {
  const parts = text.split(/(@[A-Za-z0-9._-]{2,64})/g);
  return <>{parts.map((p, i) => (i % 2 ? <span key={i} className="mention">{p}</span> : p))}</>;
}

export function Discussion({ caseId }: { caseId: number }) {
  const { can, me } = useSession();
  const logins = useLogins();
  const list = useLoad(() => api<Comment[]>(`/cases/${caseId}/comments`), [caseId]);
  const [text, setText] = useState("");
  const [pin, setPin] = useState(false);
  const { run, busy } = useAction();
  const toast = useToast();
  const at = text.match(/@([A-Za-z0-9._-]*)$/)?.[1];
  const hints = at !== undefined ? logins.filter((u) => u.login.startsWith(at.toLowerCase()) || u.name.toLowerCase().includes(at.toLowerCase())).slice(0, 6) : [];
  const send = () => run(async () => {
    await api(`/cases/${caseId}/comments`, { method: "POST", json: { text, pinned: pin } });
    setText("");
    setPin(false);
    list.reload();
  });
  const togglePin = (c: Comment) => run(async () => {
    await api(`/comments/${c.id}`, { method: "PATCH", json: { pinned: !c.pinned } });
    list.reload();
  });
  const remove = (c: Comment) => {
    if (!confirm("Удалить комментарий?")) return;
    run(async () => {
      await api(`/comments/${c.id}`, { method: "DELETE" });
      list.reload();
      toast("Комментарий удалён");
    });
  };
  return (
    <div className="stack">
      {can("lawyer") && (
        <div className="panel pad stack" style={{ gap: 6 }}>
          <textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} aria-label="Комментарий"
                    placeholder="Комментарий по делу. @логин — упомянуть коллегу (придёт уведомление)"
                    onKeyDown={(e) => e.key === "Enter" && (e.ctrlKey || e.metaKey) && text.trim() && send()} />
          {hints.length > 0 && (
            <div className="row small">{hints.map((u) => (
              <button key={u.login} className="chip" onClick={() => setText(text.replace(/@[A-Za-z0-9._-]*$/, `@${u.login} `))}>@{u.login} · {u.name}</button>
            ))}</div>
          )}
          <div className="row">
            <label className="row small"><input type="checkbox" checked={pin} onChange={(e) => setPin(e.target.checked)} /> Закрепить как «важно по делу»</label>
            <span className="spacer" />
            <span className="muted small">Ctrl+Enter</span>
            <button className="primary" disabled={busy || !text.trim()} onClick={send}>Отправить</button>
          </div>
        </div>
      )}
      <ErrorBox error={list.error} />
      {list.data?.map((c) => (
        <div key={c.id} className={`panel pad comment ${c.pinned ? "pinned" : ""}`}>
          <div className="row small">
            <b>{c.author}</b><span className="muted">{fmtDateTime(c.created_at)}{c.edited_at && " · изменено"}</span>
            {c.pinned && <span className="badge appeal_possible">важно</span>}
            <span className="spacer" />
            {can("lawyer") && <button className="link small" onClick={() => togglePin(c)}>{c.pinned ? "открепить" : "закрепить"}</button>}
            {(c.author === me.login || can("admin")) && <button className="link small danger" onClick={() => remove(c)}>удалить</button>}
          </div>
          <div style={{ whiteSpace: "pre-wrap", marginTop: 4 }}><MentionText text={c.text} /></div>
        </div>
      ))}
      {list.data?.length === 0 && <div className="panel empty-state">Обсуждения пока нет</div>}
    </div>
  );
}

/** Закреплённые заметки — над вкладками карточки дела. */
export function PinnedNotes({ caseId }: { caseId: number }) {
  const list = useLoad(() => api<Comment[]>(`/cases/${caseId}/comments`), [caseId]);
  const pinned = (list.data ?? []).filter((c) => c.pinned);
  if (!pinned.length) return null;
  return (
    <div className="pinned-notes">
      {pinned.map((c) => (
        <div key={c.id} className="notice small"><b>Важно:</b> <MentionText text={c.text} /> <span className="muted">— {c.author}</span></div>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------------------------------
// Заседания
// ------------------------------------------------------------------------------------------

export function HearingList({ items, reload, showCase = true }: { items: Hearing[]; reload: () => void; showCase?: boolean }) {
  const { can } = useSession();
  const [linking, setLinking] = useState<Hearing | null>(null);
  if (!items.length) return <div className="panel empty-state">Заседаний нет</div>;
  return (
    <div className="panel table-wrap">
      <table>
        <thead><tr><th>Дата</th><th>Суд, судья</th><th>Дело (как в календаре)</th>{showCase && <th>Дело в рабочем месте</th>}<th>Ответственные</th></tr></thead>
        <tbody>
          {items.map((h) => (
            <tr key={h.id} className={h.highlight ? "hl" : ""}>
              <td className="nowrap"><b>{fmtDate(h.date)}</b><div className="small">{h.time}</div></td>
              <td className="small">{h.court}<div className="muted">{h.judge}</div></td>
              <td className="small">{h.case_text}{h.notes.trim() && <div className="muted">{h.notes}</div>}<div className="muted">{h.plaintiff}</div></td>
              {showCase && (
                <td className="small nowrap">
                  {h.case_id ? <Link to={`/cases/${h.case_id}`}>{h.case_number || `#${h.case_id}`}</Link> : <span className="badge appeal_possible">без дела</span>}
                  {h.case_id && <div className="muted">{h.link_method}</div>}
                  {can("lawyer") && <div><button className="link small" onClick={() => setLinking(h)}>{h.case_id ? "перепривязать" : "привязать"}</button></div>}
                </td>
              )}
              <td className="small">{h.owners.join(", ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {linking && <LinkHearing h={linking} onClose={() => setLinking(null)} onDone={reload} />}
    </div>
  );
}

function LinkHearing({ h, onClose, onDone }: { h: Hearing; onClose: () => void; onDone: () => void }) {
  const [q, setQ] = useState(h.case_numbers[0] ?? "");
  const found = useLoad(() => (q.trim().length > 1 ? api<{ items: { id: number; case_number: string; plaintiffs: string; court_name: string }[] }>(`/cases?q=${encodeURIComponent(q)}&size=8`) : Promise.resolve({ items: [] })), [q]);
  const { run, busy } = useAction();
  const link = (caseId: number | null) => run(async () => {
    await api(`/hearings/${h.id}/link`, { method: "POST", json: { case_id: caseId } });
    onDone();
    onClose();
  }, caseId ? "Заседание привязано" : "Привязка снята");
  return (
    <Modal title={`Заседание ${fmtDate(h.date)} — к какому делу?`} onClose={onClose}
           footer={<><button onClick={onClose}>Отмена</button>{h.case_id && <button disabled={busy} onClick={() => link(null)}>Отвязать</button>}</>}>
      <div className="muted small" style={{ marginBottom: 8 }}>В календаре: «{h.case_text}» · {h.court} · {h.plaintiff}</div>
      <input className="search-big" autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Номер, УИД, истец" aria-label="Поиск дела" />
      <div className="stack" style={{ gap: 4, marginTop: 8 }}>
        {found.data?.items.map((c) => (
          <button key={c.id} className="bell-item" disabled={busy} onClick={() => link(c.id)}>
            <span className="grow"><span className="t">{c.case_number || `#${c.id}`} · {c.plaintiffs}</span><span className="muted small">{c.court_name}</span></span>
          </button>
        ))}
      </div>
    </Modal>
  );
}
