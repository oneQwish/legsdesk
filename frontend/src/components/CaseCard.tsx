import { useNavigate } from "react-router-dom";
import { daysLeft, fmtDate, shortCourt, type CaseBrief } from "../api";
import AwardBar from "./AwardBar";

export function caseTone(c: CaseBrief): string {
  if (!c.next_due) return "tone-none";
  const n = daysLeft(c.next_due);
  return n <= 3 ? "tone-hot" : n <= 10 ? "tone-soon" : "tone-calm";
}

function dueText(due: string): string {
  const n = daysLeft(due);
  if (n < 0) return `просрочен ${-n} дн.`;
  if (n === 0) return "сегодня";
  if (n === 1) return "завтра";
  return `через ${n} дн.`;
}

/** Карточка дела — «папка» с корешком цвета срочности. Клик открывает дело. */
export default function CaseCard({ c, style, className = "" }: { c: CaseBrief; style?: React.CSSProperties; className?: string }) {
  const nav = useNavigate();
  const overdue = c.next_due !== null && daysLeft(c.next_due) < 0;
  const object = [c.complex, c.building && `корп. ${c.building}`, c.flat && `кв. ${c.flat}`].filter(Boolean).join(", ");
  return (
    <div className={`case-card ${caseTone(c)} ${className}`} style={style}
         onClick={(e) => (e.ctrlKey || e.metaKey ? window.open(`/cases/${c.id}`, "_blank") : nav(`/cases/${c.id}`))}
         onAuxClick={(e) => e.button === 1 && window.open(`/cases/${c.id}`, "_blank")}
         role="link" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && nav(`/cases/${c.id}`)}>
      {overdue && <span className="stamp" style={{ color: "var(--seal)" }}>просрочен</span>}
      <div className="num">{c.case_number || "без номера"}</div>
      <div className="who">{c.plaintiffs || "истцы не указаны"}</div>
      <div className="where ellipsis" title={c.court_name}>{shortCourt(c.court_name)}</div>
      {object && <div className="where ellipsis">{object} · {c.legal_entity}</div>}
      <AwardBar compact claimed={c.claimed} awarded={c.awarded} />
      <div className="foot">
        {c.next_due ? (
          <div className="due">
            <div className="muted ellipsis">{c.next_title ?? "срок"}</div>
            <b>{fmtDate(c.next_due)}</b>{" "}
            <span className={`badge ${overdue ? "overdue" : daysLeft(c.next_due) <= 7 ? "soon" : "later"}`}>{dueText(c.next_due)}</span>
          </div>
        ) : (
          <span className="due muted">открытых сроков нет</span>
        )}
      </div>
      <div className="row" style={{ gap: 6 }}>
        {c.conflicts > 0 && <span className="badge conflict">конфликтов: {c.conflicts}</span>}
        {!c.uid && <span className="badge soon">нет УИД</span>}
        {c.responsible && <span className="badge single">{c.responsible}</span>}
      </div>
    </div>
  );
}
