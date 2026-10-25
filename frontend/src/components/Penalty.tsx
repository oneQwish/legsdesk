import { useEffect, useState } from "react";
import { api, fmtDate, fmtShortMoney, localISO } from "../api";
import { useAction } from "./ui";

type Seg = { start: string; end: string; days: number; rate: number; excluded: boolean; note: string; amount: number };
type Calc = { price: number; due_date: string; end_date: string; base_rate: number; citizen: boolean; days_total: number;
  days_counted: number; total: number; fine_percent: number | null; fine: number | null; fine_note: string; formula: string;
  segments: Seg[]; rules_file: string };
type Defaults = { price: number | null; due_date: string | null; awarded_penalty: number | null; result: Calc | null };

const rub = (n: number) => n.toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " ₽";

/** Калькулятор неустойки за просрочку передачи (214-ФЗ) по делу: подставляет цену договора и срок из
 *  полей дела, показывает расчёт по периодам (моратории, ограничение ставки) и сравнение с присуждённым. */
export default function PenaltyTab({ caseId }: { caseId: number }) {
  const [d, setD] = useState<Defaults | null>(null);
  const [f, setF] = useState({ price: "", due_date: "", end_date: localISO(), citizen: true, claim_deadline: "" });
  const [r, setR] = useState<Calc | null>(null);
  const { run, busy } = useAction();
  useEffect(() => {
    api<Defaults>(`/cases/${caseId}/penalty`).then((x) => {
      setD(x);
      setF((f0) => ({ ...f0, price: x.price ? String(x.price) : "", due_date: x.due_date ?? "" }));
      setR(x.result);
    }).catch(() => setD({ price: null, due_date: null, awarded_penalty: null, result: null }));
  }, [caseId]);
  const calc = () => run(async () => {
    setR(await api<Calc>("/penalty/calc", { method: "POST", json: {
      price: Number(f.price.replace(/\s/g, "").replace(",", ".")), due_date: f.due_date, end_date: f.end_date || null,
      citizen: f.citizen, claim_deadline: f.claim_deadline || null } }));
  });
  const awarded = d?.awarded_penalty;
  return (
    <div className="stack">
      <div className="panel pad">
        <div className="form-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))" }}>
          <label className="field">Цена договора, ₽<input inputMode="decimal" value={f.price} onChange={(e) => setF({ ...f, price: e.target.value })} /></label>
          <label className="field">Последний день срока передачи<input type="date" value={f.due_date} onChange={(e) => setF({ ...f, due_date: e.target.value })} /></label>
          <label className="field">Передано (или на дату)<input type="date" value={f.end_date} onChange={(e) => setF({ ...f, end_date: e.target.value })} /></label>
          <label className="field">Срок по претензии истёк (для штрафа)<input type="date" value={f.claim_deadline} onChange={(e) => setF({ ...f, claim_deadline: e.target.value })} /></label>
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          <label className="row small"><input type="checkbox" checked={f.citizen} onChange={(e) => setF({ ...f, citizen: e.target.checked })} /> Участник — гражданин (двойной размер)</label>
          <span className="spacer" />
          <button className="primary" disabled={busy || !f.price || !f.due_date} onClick={calc}>Рассчитать</button>
        </div>
        {d && (!d.price || !d.due_date) && <div className="muted small" style={{ marginTop: 6 }}>Цену договора и срок передачи можно хранить в полях дела
          «Цена договора» и «Срок передачи по договору» — тогда расчёт появится сам.</div>}
      </div>
      {r && (
        <div className="panel pad stack">
          <div className="row" style={{ alignItems: "baseline" }}>
            <h2 style={{ margin: 0 }}>{rub(r.total)}</h2>
            <span className="muted">неустойка за {r.days_counted} дн. из {r.days_total} (ставка {r.base_rate} % на {fmtDate(r.due_date)})</span>
          </div>
          {awarded != null && (
            <div className="small">Присуждено судом: <b>{rub(awarded)}</b> — {Math.round((100 * awarded) / Math.max(r.total, 0.01))} % от расчёта
              {awarded < r.total * 0.95 && <span className="muted"> (снижение, вероятно, по ст. 333 ГК)</span>}</div>
          )}
          {r.fine_percent !== null && <div className="small">Штраф: <b>{r.fine_percent} %{r.fine ? ` — ${rub(r.fine)}` : ""}</b> <span className="muted">{r.fine_note}</span></div>}
          <div className="table-wrap"><table>
            <thead><tr><th>Период</th><th className="right">Дней</th><th className="right">Ставка</th><th className="right">Сумма</th><th>Основание</th></tr></thead>
            <tbody>
              {r.segments.map((s, i) => (
                <tr key={i} style={{ opacity: s.excluded ? 0.55 : 1 }}>
                  <td className="nowrap">{fmtDate(s.start)} — {fmtDate(s.end)}</td><td className="right">{s.days}</td>
                  <td className="right">{s.excluded ? "—" : `${s.rate} %`}</td><td className="right nowrap">{s.excluded ? "не начисляется" : fmtShortMoney(s.amount)}</td>
                  <td className="small muted">{s.note}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
          <div className="muted small">{r.formula}. Ставки и моратории — в файле {r.rules_file.split("/").pop()} (сверяйте с cbr.ru и текстами постановлений).
            Расчёт — подсказка, а не позиция по делу.</div>
        </div>
      )}
    </div>
  );
}
