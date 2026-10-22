import { daysLeft, fmtDate, type CaseFull, type DocumentBrief } from "../api";

type Stage = { key: string; label: string; state: "done" | "current" | "todo" | "skipped"; date?: string | null; note?: string };

const isDecision = (d: DocumentBrief) => /^(решение|заочное решение|дополнительное решение)/i.test(d.act_type) && d.instance !== "апелляция";
const isAppeal = (d: DocumentBrief) => /^апелляционн/i.test(d.act_type) || d.instance === "апелляция";
const isCassation = (d: DocumentBrief) => /^кассационн/i.test(d.act_type) || d.instance === "кассация";
const isFssp = (d: DocumentBrief) => d.kind === "ФССП";

/** Этапы дела по его документам и срокам: иск → решение → апелляция → вступление в силу → кассация → исполнение. */
export function caseStages(c: CaseFull): Stage[] {
  const first = (f: (d: DocumentBrief) => boolean) =>
    c.documents.filter(f).sort((a, b) => (a.act_date ?? "").localeCompare(b.act_date ?? ""))[0];
  const decision = first(isDecision);
  const appeal = first(isAppeal);
  const cassation = first(isCassation);
  const fssp = first(isFssp);
  const appealDl = c.deadlines.find((d) => d.kind === "appeal" && d.status !== "cancelled");
  const effDl = c.deadlines.find((d) => d.kind === "effective" && d.status !== "cancelled");
  const cassDl = c.deadlines.find((d) => d.kind === "cassation" && d.status !== "cancelled");
  // вступило в силу: после апелляционного определения — в день его принятия; без жалобы — по истечении срока
  const effDate = appeal?.act_date ?? (effDl && daysLeft(effDl.due_date) <= 0 ? effDl.due_date : null);
  const appealWindowOpen = !!appealDl && appealDl.status === "open" && daysLeft(appealDl.due_date) >= 0;

  const st: Stage[] = [{ key: "claim", label: "Иск", state: "done", note: c.aliases.find((a) => a.number.startsWith("М-"))?.number }];
  st.push(decision
    ? { key: "decision", label: "Решение", state: "done", date: decision.act_date, note: c.outcome || undefined }
    : { key: "decision", label: "Решение", state: "current", note: "рассмотрение" });
  if (appeal) st.push({ key: "appeal", label: "Апелляция", state: "done", date: appeal.act_date, note: appeal.outcome || undefined });
  else if (decision && (appealWindowOpen || c.appeal_flag))
    st.push({ key: "appeal", label: "Апелляция", state: "current", date: appealDl?.due_date, note: c.appeal_flag ? "есть признаки обжалования" : "срок подачи до" });
  else if (decision && effDate) st.push({ key: "appeal", label: "Апелляция", state: "skipped", note: "не обжаловано" });
  else st.push({ key: "appeal", label: "Апелляция", state: "todo" });
  st.push(effDate
    ? { key: "effective", label: "Вступило в силу", state: "done", date: effDate }
    : { key: "effective", label: "Вступление в силу", state: decision && !appealWindowOpen ? "current" : "todo", date: effDl?.due_date, note: effDl ? "ожидается" : undefined });
  if (cassation) st.push({ key: "cassation", label: "Кассация", state: "done", date: cassation.act_date });
  else if (cassDl && cassDl.status === "open") st.push({ key: "cassation", label: "Кассация", state: "current", date: cassDl.due_date, note: "срок подачи до" });
  else st.push({ key: "cassation", label: "Кассация", state: effDate && fssp ? "skipped" : "todo" });
  const cassOpen = !cassation && !!cassDl && cassDl.status === "open";
  st.push(fssp
    ? { key: "fssp", label: "Исполнение", state: "done", date: fssp.act_date }
    : { key: "fssp", label: "Исполнение", state: effDate && !cassOpen ? "current" : "todo", note: effDate ? "можно начинать" : undefined });
  // «текущий» — только один: последний из отмеченных current
  const cur = st.map((s) => s.state).lastIndexOf("current");
  st.forEach((s, i) => { if (s.state === "current" && i !== cur) s.state = "todo"; });
  return st;
}

export default function CasePath({ c }: { c: CaseFull }) {
  const stages = caseStages(c);
  return (
    <ol className="path" aria-label="Путь дела">
      {stages.map((s) => (
        <li key={s.key} className={`path-step ${s.state}`}>
          <span className="node">{s.state === "done" ? "✓" : s.state === "skipped" ? "–" : ""}</span>
          <span className="lbl">{s.label}</span>
          <span className="sub">{s.date ? fmtDate(s.date) : ""}{s.note ? (s.date ? " · " : "") + s.note : ""}</span>
        </li>
      ))}
    </ol>
  );
}
