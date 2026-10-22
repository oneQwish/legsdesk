import { fmtShortMoney, fmtValue } from "../api";

export type AwardPart = { label: string; value: number };

const PART_COLORS = ["var(--ink-2)", "var(--seal)", "var(--ochre)", "var(--ok)", "var(--violet)", "var(--link)", "var(--muted)"];

/** «Присуждено от заявленного»: полоса с долей; в подробном виде — с разбивкой по категориям. */
export default function AwardBar({ claimed, awarded, parts, compact }: {
  claimed: number | null | undefined;
  awarded: number | null | undefined;
  parts?: AwardPart[];
  compact?: boolean;
}) {
  if (!awarded && !claimed) return null;
  const pct = claimed ? Math.round(((awarded ?? 0) / claimed) * 100) : null;
  if (compact) {
    return (
      <div className="award compact" title={`Заявлено ${fmtValue("money", String(claimed ?? ""))}, присуждено ${fmtValue("money", String(awarded ?? 0))}`}>
        <div className="award-bar"><span style={{ width: `${Math.min(100, pct ?? 0)}%` }} /></div>
        <span className="small"><b>{fmtShortMoney(awarded)}</b>{pct !== null && <span className="muted"> · {pct}% от {fmtShortMoney(claimed)}</span>}</span>
      </div>
    );
  }
  const total = Math.max(claimed ?? 0, awarded ?? 0) || 1;
  return (
    <div className="award">
      <div className="row" style={{ alignItems: "baseline" }}>
        <span className="muted small grow">Присуждено от заявленного</span>
        {pct !== null && <b className="serif award-pct">{pct}%</b>}
      </div>
      <div className="award-bar big">
        {(parts && parts.length ? parts : [{ label: "присуждено", value: awarded ?? 0 }]).map((p, i) => (
          <span key={p.label} style={{ width: `${(p.value / total) * 100}%`, background: PART_COLORS[i % PART_COLORS.length] }}
                title={`${p.label}: ${fmtValue("money", String(p.value))}`} />
        ))}
      </div>
      <div className="row small" style={{ justifyContent: "space-between" }}>
        <span>присуждено <b>{fmtValue("money", String(awarded ?? 0))}</b></span>
        <span className="muted">заявлено {claimed ? fmtValue("money", String(claimed)) : "— (нет данных)"}</span>
      </div>
      {parts && parts.length > 1 && (
        <div className="award-legend">
          {parts.map((p, i) => (
            <span key={p.label}><i style={{ background: PART_COLORS[i % PART_COLORS.length] }} />{p.label} {fmtShortMoney(p.value)}</span>
          ))}
        </div>
      )}
    </div>
  );
}
