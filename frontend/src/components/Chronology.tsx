import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ACTION_LABEL, api, daysLeft, DEADLINE_KIND, fmtDate, type CaseFull, type EventItem } from "../api";
import { useLoad } from "./ui";

type Item = { date: string; kind: "doc" | "deadline" | "decision" | "event"; title: string; sub?: string; to?: string; color: string; future?: boolean };

const KIND_LABEL = { doc: "Акты и документы", deadline: "Сроки", decision: "Решения юристов", event: "Прочие события" };
const DECISIONS = new Set(["value_resolved", "value_reopened", "case_merged", "deadline_updated"]);

/** Хронология дела: акты, сроки и решения юристов на одной оси времени + список по датам. */
export default function Chronology({ c }: { c: CaseFull }) {
  const ev = useLoad(() => api<EventItem[]>(`/cases/${c.id}/events`), [c.id]);
  const [show, setShow] = useState<Record<string, boolean>>({ doc: true, deadline: true, decision: true, event: false });

  const items = useMemo(() => {
    const out: Item[] = [];
    for (const d of c.documents)
      if (d.act_date) out.push({ date: d.act_date, kind: "doc", title: d.act_type || d.kind, sub: [d.instance, d.outcome].filter(Boolean).join(" · "), to: `/documents/${d.id}`, color: "var(--ink)" });
    for (const d of c.deadlines)
      if (d.status !== "cancelled")
        out.push({ date: d.due_date, kind: "deadline", title: d.title, sub: d.status === "done" ? "выполнено" : daysLeft(d.due_date) < 0 ? "просрочен" : "открыт",
                   color: DEADLINE_KIND[d.kind]?.color ?? "var(--ink-2)", future: daysLeft(d.due_date) > 0 });
    for (const e of ev.data ?? []) {
      const kind = DECISIONS.has(e.action) ? "decision" : "event";
      if (e.action === "document_viewed" || e.action === "login") continue;
      const data = e.data as Record<string, unknown>;
      const sub = e.action === "value_resolved" ? `${data.field}: ${(data.after as { value?: string })?.value ?? ""} — ${e.actor}` : e.actor;
      out.push({ date: e.ts.slice(0, 10), kind, title: ACTION_LABEL[e.action] ?? e.action, sub, color: kind === "decision" ? "var(--violet)" : "var(--muted)" });
    }
    return out.sort((a, b) => a.date.localeCompare(b.date));
  }, [c, ev.data]);

  const visible = items.filter((i) => show[i.kind]);
  if (!items.length) return <div className="panel empty-state">Событий пока нет</div>;
  const t = (s: string) => new Date(s + "T00:00:00").getTime();
  const today = new Date().toISOString().slice(0, 10);
  const lo = Math.min(...items.map((i) => t(i.date)), t(today));
  const hi = Math.max(...items.map((i) => t(i.date)), t(today));
  const span = Math.max(hi - lo, 86400000);
  const x = (s: string) => 2 + ((t(s) - lo) / span) * 96;
  const years = [];
  for (let y = new Date(lo).getFullYear() + 1; y <= new Date(hi).getFullYear(); y++) years.push(y);
  const lane = { doc: 0, deadline: 1, decision: 2, event: 3 };

  return (
    <div className="stack">
      <div className="row">
        {(Object.keys(KIND_LABEL) as (keyof typeof KIND_LABEL)[]).map((k) => (
          <label key={k} className="row small" style={{ gap: 4 }}>
            <input type="checkbox" checked={show[k]} onChange={(e) => setShow({ ...show, [k]: e.target.checked })} />
            {KIND_LABEL[k]} <span className="muted">{items.filter((i) => i.kind === k).length}</span>
          </label>
        ))}
      </div>
      <div className="panel chrono-axis">
        <div className="axis-line" />
        {years.map((y) => <span key={y} className="year" style={{ left: `${x(`${y}-01-01`)}%` }}>{y}</span>)}
        <span className="today-mark" style={{ left: `${x(today)}%` }}><span>сегодня</span></span>
        {visible.map((i, k) => (
          <span key={k} className={`mark ${i.kind} ${i.future ? "future" : ""}`}
                style={{ left: `${x(i.date)}%`, top: 18 + lane[i.kind] * 15, background: i.color }}
                title={`${fmtDate(i.date)} — ${i.title}${i.sub ? `\n${i.sub}` : ""}`} />
        ))}
        <span className="axis-edge left">{fmtDate(new Date(lo).toISOString().slice(0, 10))}</span>
        <span className="axis-edge right">{fmtDate(new Date(hi).toISOString().slice(0, 10))}</span>
      </div>
      <div className="panel chrono-list">
        {visible.slice().reverse().map((i, k) => (
          <div key={k} className={`chrono-item ${i.future ? "future" : ""}`}>
            <span className="date">{fmtDate(i.date)}</span>
            <span className="pin" style={{ background: i.color }} />
            <div className="grow">
              {i.to ? <Link to={i.to}><b>{i.title}</b></Link> : <b>{i.title}</b>}
              {i.sub && <div className="small muted">{i.sub}</div>}
            </div>
            <span className="small muted">{KIND_LABEL[i.kind].toLowerCase()}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
