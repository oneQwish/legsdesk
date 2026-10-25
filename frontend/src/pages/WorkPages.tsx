import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Topbar, useSession } from "../App";
import { api, localISO, qs, type Assignment, type Hearing } from "../api";
import { AssignmentList, AssignmentModal, HearingList } from "../components/Work";
import { ErrorBox, useDebounced, useLoad } from "../components/ui";

/** Поручения: мне, от меня, все. */
export function AssignmentsPage() {
  const { me, can } = useSession();
  const [sp, setSp] = useSearchParams();
  const who = sp.get("who") ?? "me";
  const status = sp.get("status") ?? "open";
  const [creating, setCreating] = useState(false);
  const params = { status, ...(who === "me" ? { assignee: me.login } : who === "mine" ? { author: me.login } : {}) };
  const list = useLoad(() => api<Assignment[]>(`/assignments${qs(params)}`), [who, status]);
  const set = (k: string, v: string) => setSp((p) => { const n = new URLSearchParams(p); n.set(k, v); return n; }, { replace: true });
  return (
    <>
      <Topbar title="Поручения" sub="Кто что делает и к какому сроку. Поручение по делу видно и в карточке дела.">
        <div className="seg" role="group" aria-label="Чьи">
          {[["me", "Мне"], ["mine", "Я дал(а)"], ["all", "Все"]].map(([k, l]) => (
            <button key={k} className={who === k ? "on" : ""} aria-pressed={who === k} onClick={() => set("who", k)}>{l}</button>
          ))}
        </div>
        <select aria-label="Статус" value={status} onChange={(e) => set("status", e.target.value)}>
          <option value="open">Открытые</option><option value="done">Выполненные</option><option value="cancelled">Отменённые</option>
          <option value="open,done,cancelled">Все</option>
        </select>
        {can("lawyer") && <button className="primary" onClick={() => setCreating(true)}>+ Поручение</button>}
      </Topbar>
      <ErrorBox error={list.error} />
      {list.data && <AssignmentList items={list.data} reload={list.reload} />}
      {creating && <AssignmentModal onClose={() => setCreating(false)} onDone={list.reload} />}
    </>
  );
}

/** Заседания из судебного календаря: по датам, без дела, поиск. */
export function HearingsPage() {
  const [sp, setSp] = useSearchParams();
  const today = localISO();
  const plus = (n: number) => { const d = new Date(); d.setDate(d.getDate() + n); return localISO(d); };
  const from = sp.get("from") ?? today;
  const to = sp.get("to") ?? plus(30);
  const unlinked = sp.get("unlinked") === "1";
  const [q, setQ] = useState(sp.get("q") ?? "");
  const qd = useDebounced(q.trim(), 350);
  const list = useLoad(() => api<Hearing[]>(`/hearings${qs({ date_from: from, date_to: to, unlinked: unlinked || undefined, q: qd })}`),
                       [from, to, unlinked, qd]);
  const set = (k: string, v: string) => setSp((p) => { const n = new URLSearchParams(p); if (v) n.set(k, v); else n.delete(k); return n; }, { replace: true });
  return (
    <>
      <Topbar title="Заседания" sub="Из «Судебного календаря» (обновляется коннектором). Привязка к делу — по номеру; не нашлось — привяжите вручную.">
        <input type="date" aria-label="С" value={from} onChange={(e) => set("from", e.target.value)} />
        <input type="date" aria-label="По" value={to} onChange={(e) => set("to", e.target.value)} />
        <input aria-label="Поиск" placeholder="Номер, истец, суд, судья" value={q} onChange={(e) => setQ(e.target.value)} />
        <label className="row small"><input type="checkbox" checked={unlinked} onChange={(e) => set("unlinked", e.target.checked ? "1" : "")} /> без дела</label>
      </Topbar>
      <ErrorBox error={list.error} />
      {list.data && <HearingList items={list.data} reload={list.reload} />}
    </>
  );
}
