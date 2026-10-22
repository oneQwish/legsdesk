import { useNavigate } from "react-router-dom";
import { DEADLINE_KIND, api } from "../api";
import { useLoad } from "./ui";

type Day = { date: string; working: boolean; total: number; kinds: Record<string, number> };
type Strip = { overdue: { total: number; kinds: Record<string, number> }; days: Day[]; calendar_confirmed: boolean };

const WD = ["Вс", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"];
const MON = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];

/** Точки сроков по видам (не больше 5, дальше «+N»). */
function Dots({ kinds }: { kinds: Record<string, number> }) {
  const dots: string[] = [];
  for (const [k, n] of Object.entries(kinds).sort((a, b) => b[1] - a[1])) for (let i = 0; i < n; i++) dots.push(k);
  const shown = dots.slice(0, 5);
  return (
    <div className="dots">
      {shown.map((k, i) => <i key={i} style={{ background: DEADLINE_KIND[k]?.color ?? "var(--ink-2)" }} />)}
      {dots.length > 5 && <span>+{dots.length - 5}</span>}
    </div>
  );
}

function title(kinds: Record<string, number>): string {
  return Object.entries(kinds).map(([k, n]) => `${DEADLINE_KIND[k]?.label ?? k}: ${n}`).join("\n");
}

/** Лента дней на две недели: сколько сроков истекает в каждый день. Клик — сроки этого дня. */
export default function DayStrip({ days = 14 }: { days?: number }) {
  const nav = useNavigate();
  const r = useLoad(() => api<Strip>(`/desk/strip?days=${days}`), [days]);
  const s = r.data;
  if (!s) return <div className="strip panel" style={{ minHeight: 96 }} />;
  const max = Math.max(1, ...s.days.map((d) => d.total));
  return (
    <div className="strip panel">
      <button className={`strip-day overdue ${s.overdue.total ? "hot" : ""}`} onClick={() => nav("/deadlines")}
              title={s.overdue.total ? title(s.overdue.kinds) : "Просроченных сроков нет"}>
        <span className="wd">до сегодня</span>
        <span className="n">{s.overdue.total || "✓"}</span>
        <span className="lbl">{s.overdue.total ? "просрочено" : "без просрочек"}</span>
      </button>
      {s.days.map((d, i) => {
        const dt = new Date(d.date + "T00:00:00");
        const day = dt.getDate();
        return (
          <button key={d.date} className={`strip-day ${i === 0 ? "today" : ""} ${d.working ? "" : "off"} ${d.total ? "has" : ""}`}
                  onClick={() => nav(`/deadlines?due_from=${d.date}&due_before=${d.date}`)}
                  title={d.total ? `${dt.toLocaleDateString("ru-RU")}\n${title(d.kinds)}` : `${dt.toLocaleDateString("ru-RU")}: сроков нет${d.working ? "" : " (нерабочий день)"}`}>
            <span className="wd">{i === 0 ? "сегодня" : WD[dt.getDay()]}</span>
            <span className="d">{day}{(i === 0 || day === 1) && <small> {MON[dt.getMonth()]}</small>}</span>
            <span className="bar"><span style={{ height: `${(d.total / max) * 100}%` }} /></span>
            <Dots kinds={d.kinds} />
          </button>
        );
      })}
      {!s.calendar_confirmed && <span className="strip-note" title="Календарь года не загружен: переносы праздников не учтены">* календарь без переносов</span>}
    </div>
  );
}
