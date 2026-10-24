import { useState } from "react";
import { Link } from "react-router-dom";
import { useSession } from "../App";
import { cachedApi, settings } from "../api";
import { PromptModal } from "./overlay";
import { useLoad } from "./ui";

type Metric = { this_week: number; last_week: number };
type ProgressResp = { metrics: Record<string, Metric>; streak: number; overdue_now: number; scope: string };

// цели по умолчанию — из settings.toml ([interface] goal_*); юрист может поменять свои
const METRICS: { key: string; label: string; readonly goal: number; to: string }[] = [
  { key: "conflicts", label: "Конфликты разобраны", get goal() { return settings.goal_conflicts; }, to: "/conflicts" },
  { key: "deadlines", label: "Сроки закрыты", get goal() { return settings.goal_deadlines; }, to: "/deadlines" },
  { key: "documents", label: "Документы привязаны", get goal() { return settings.goal_documents; }, to: "/documents?unlinked=1" },
];

function loadGoals(): Record<string, number> {
  try {
    return JSON.parse(localStorage.getItem("lawdesk.goals") ?? "{}");
  } catch {
    return {};
  }
}

function plural(n: number, one: string, few: string, many: string) {
  const m10 = n % 10, m100 = n % 100;
  return m10 === 1 && m100 !== 11 ? one : m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14) ? few : many;
}

/** Недельный прогресс с целями (цели — личные, хранятся в браузере). */
export function WeekProgress() {
  const p = useLoad(() => cachedApi<ProgressResp>("/desk/progress"), []);
  const [goals, setGoals] = useState(loadGoals);
  const [editing, setEditing] = useState<(typeof METRICS)[number] | null>(null);
  const goal = (k: string, d: number) => goals[k] ?? d;
  return (
    <div className="progress panel">
      <div className="row" style={{ marginBottom: 8 }}>
        <h3 className="grow" style={{ margin: 0 }}>Моя неделя</h3>
        <span className="muted small">цель — по клику на число</span>
      </div>
      {METRICS.map((m) => {
        const v = p.data?.metrics[m.key];
        const g = goal(m.key, m.goal);
        const pct = Math.min(100, ((v?.this_week ?? 0) / g) * 100);
        const diff = v ? v.this_week - v.last_week : 0;
        return (
          <div key={m.key} className="metric">
            <div className="row" style={{ gap: 6 }}>
              <Link to={m.to} className="grow small" style={{ color: "inherit" }}>{m.label}</Link>
              <button className="link small" onClick={() => setEditing(m)} title="Изменить цель на неделю">
                <b className="serif" style={{ color: "var(--ink)", fontSize: 15 }}>{v?.this_week ?? "—"}</b> <span className="muted">/ {g}</span>
              </button>
              {v && diff !== 0 && <span className={`delta ${diff > 0 ? "up" : "down"}`} title="К прошлой неделе">{diff > 0 ? "↑" : "↓"}{Math.abs(diff)}</span>}
            </div>
            <div className={`meter ${pct >= 100 ? "full" : ""}`}><span style={{ width: `${pct}%` }} /></div>
          </div>
        );
      })}
      {editing && (
        <PromptModal title={`Цель на неделю: ${editing.label.toLowerCase()}`} label="Сколько за неделю" type="number"
          initial={String(goal(editing.key, editing.goal))} onClose={() => setEditing(null)}
          onSubmit={(v) => {
            const n = Math.max(1, Number(v) || editing.goal);
            const next = { ...goals, [editing.key]: n };
            setGoals(next);
            try { localStorage.setItem("lawdesk.goals", JSON.stringify(next)); } catch { /* без сохранения */ }
          }} />
      )}
    </div>
  );
}

/** «Чистый стол»: всё разобрано — спокойный экран и серия дней без просрочек; иначе — что осталось до чистоты. */
export function CleanDesk() {
  const { stats } = useSession();
  const p = useLoad(() => cachedApi<ProgressResp>("/desk/progress"), []);
  const conflicts = (stats?.values_by_status.conflict ?? 0) + (stats?.values_by_status.appeal_possible ?? 0);
  const overdue = stats?.deadlines_overdue ?? 0;
  const clean = stats !== null && conflicts === 0 && overdue === 0;
  const streak = p.data?.streak ?? 0;
  return (
    <div className={`clean panel ${clean ? "is-clean" : ""}`}>
      <div className="seal-badge" aria-hidden="true">{clean ? "✓" : conflicts + overdue}</div>
      <div className="grow">
        {clean ? (
          <>
            <h3 style={{ margin: 0 }}>Стол чист</h3>
            <div className="small muted">Конфликтов и просрочек нет. Хорошая работа.</div>
          </>
        ) : (
          <>
            <h3 style={{ margin: 0 }}>До чистого стола</h3>
            <div className="small">
              {conflicts > 0 && <Link to="/conflicts">{conflicts} {plural(conflicts, "конфликт", "конфликта", "конфликтов")}</Link>}
              {conflicts > 0 && overdue > 0 && " и "}
              {overdue > 0 && <Link to="/deadlines" style={{ color: "var(--seal)" }}>{overdue} {plural(overdue, "просрочка", "просрочки", "просрочек")}</Link>}
            </div>
          </>
        )}
        <div className="streak small">
          {p.data && (p.data.overdue_now
            ? <>Серия без просрочек прервана · <span className="muted">{p.data.scope}</span></>
            : <><b>{streak}</b> {plural(streak, "день", "дня", "дней")} без просрочек · <span className="muted">{p.data.scope}</span></>)}
        </div>
      </div>
    </div>
  );
}
