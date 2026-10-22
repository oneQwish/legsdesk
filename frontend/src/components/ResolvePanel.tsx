import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, fmtDateTime, fmtValue, moneyHint, type CaseValue, type Observation } from "../api";
import { useSession } from "../App";
import { StatusBadge, clickable, useAction } from "./ui";

/** Варианты значения: наблюдения с одинаковым видом значения объединяются (сколько источников за каждое). */
function groupChoices(v: CaseValue) {
  const key = (o: Observation) => (v.kind === "money" && o.value_num !== null ? o.value_num.toFixed(2) : o.value.trim().toLowerCase());
  const m = new Map<string, Observation[]>();
  for (const o of v.observations) m.set(key(o), [...(m.get(key(o)) ?? []), o]);
  return [...m.values()].sort((a, b) => b.length - a.length);
}

export function ObservationLine({ o, kind }: { o: Observation; kind: string }) {
  return (
    <div className="obs">
      <div><span className="badge src">{o.source}</span></div>
      <div>
        <b>{fmtValue(kind, o.value)}</b>
        {o.source_ref && <span className="muted small"> · {o.source_ref}</span>}
        {o.quote && <div className="quote">«{o.quote}»</div>}
      </div>
      <div className="small nowrap">
        {o.document_id && (
          <Link to={`/documents/${o.document_id}${o.page ? `?page=${o.page}` : ""}`}>документ{o.page ? `, с. ${o.page}` : ""}</Link>
        )}
      </div>
    </div>
  );
}

export default function ResolvePanel({ value, onDone, hotkeys = false }: { value: CaseValue; onDone: (v: CaseValue) => void; hotkeys?: boolean }) {
  const { can } = useSession();
  const choices = useMemo(() => groupChoices(value), [value]);
  const [pick, setPick] = useState<number | "own" | null>(null);
  const [own, setOwn] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const editable = can("lawyer");
  const reopenAction = useAction();
  // те же условия, что у кнопки «Принять»: Enter не обходит проверку (своё значение — только с комментарием)
  const ready = pick !== null && (pick !== "own" || (!!own.trim() && !!note.trim()));

  useEffect(() => {
    setPick(null);
    setOwn("");
    setNote("");
    setError("");
  }, [value.id]);

  const submit = async () => {
    if (pick === null || busy || !ready) return;
    setBusy(true);
    setError("");
    try {
      const body = pick === "own" ? { value: own, note } : { observation_id: choices[pick][0].id, note };
      onDone(await api<CaseValue>(`/values/${value.id}/resolve`, { method: "POST", json: body }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const reopen = () =>
    reopenAction.run(async () => onDone(await api<CaseValue>(`/values/${value.id}/reopen`, { method: "POST", json: { note: "" } })));

  useEffect(() => {
    if (!hotkeys || !editable) return;
    const h = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.tagName === "INPUT" || t.tagName === "TEXTAREA") {
        if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) submit();
        return;
      }
      const n = Number(e.key);
      if (n >= 1 && n <= choices.length) setPick(n - 1);
      if (e.key === "0") setPick("own");
      // Enter на ссылке или кнопке — это их нажатие, а не «принять решение»
      if (e.key === "Enter" && !t.closest("a, button")) submit();
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  });

  if (value.status === "resolved") {
    return (
      <div className="stack">
        <div className="row">
          <StatusBadge status="resolved" />
          <b style={{ fontSize: 16 }}>{fmtValue(value.kind, value.value)}</b>
          <span className="muted small">{value.resolved_by}, {fmtDateTime(value.resolved_at)}</span>
          <span className="spacer" />
          {editable && <button onClick={reopen} disabled={reopenAction.busy}>Пересмотреть</button>}
        </div>
        {value.resolution_note && <div className="quote">{value.resolution_note}</div>}
        <div className="panel">{value.observations.map((o) => <ObservationLine key={o.id} o={o} kind={value.kind} />)}</div>
      </div>
    );
  }

  return (
    <div className="stack">
      {value.status === "appeal_possible" && (
        <div className="notice">По делу есть признаки обжалования: значение в отчёте может быть после апелляции. Сверьте с актом апелляции.</div>
      )}
      {value.kind === "money" && (() => {
        const hint = moneyHint(choices.map((g) => g[0].value_num ?? 0));
        return hint ? <div className="hint">{hint}</div> : null;
      })()}
      {choices.map((group, i) => (
        <div key={i} className={`choice ${pick === i ? "on" : ""}`} {...(editable ? clickable(() => setPick(i)) : {})} role="radio" aria-checked={pick === i}>
          {hotkeys && editable && <kbd>{i + 1}</kbd>}
          <div className="grow">
            <div className="val">{fmtValue(value.kind, group[0].value)}</div>
            <div className="row small" style={{ marginTop: 4 }}>
              {group.map((o) => <span key={o.id} className="badge src">{o.source}</span>)}
            </div>
            {group.map((o) => (o.quote || o.document_id) && (
              <div key={o.id} className="quote">
                {o.quote && <>«{o.quote}» </>}
                {o.document_id && (
                  <Link to={`/documents/${o.document_id}${o.page ? `?page=${o.page}` : ""}`} onClick={(e) => e.stopPropagation()}>
                    {o.source}: документ{o.page ? `, с. ${o.page}` : ""}
                  </Link>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
      {editable && (
        <>
          <div className={`choice ${pick === "own" ? "on" : ""}`} {...clickable(() => setPick("own"))} role="radio" aria-checked={pick === "own"}>
            {hotkeys && <kbd>0</kbd>}
            <div className="grow stack" style={{ gap: 6 }}>
              <span>Своё значение</span>
              {pick === "own" && (
                <input autoFocus aria-label="Своё значение" value={own} onChange={(e) => setOwn(e.target.value)}
                       placeholder={value.kind === "money" ? "123456.78" : value.kind === "date" ? "ГГГГ-ММ-ДД" : "значение"} />
              )}
            </div>
          </div>
          <label className="field">
            Комментарий {pick === "own" ? "(обязателен: откуда значение)" : "(необязательно)"}
            <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="напр.: по цифровому оригиналу письма, с. 4" />
          </label>
          {error && <div className="error">{error}</div>}
          <div className="row">
            <button className="primary" disabled={busy || !ready} onClick={submit}>
              Принять значение
            </button>
            {hotkeys && <span className="muted small"><kbd>1</kbd>–<kbd>9</kbd> выбрать, <kbd>Enter</kbd> принять, <kbd>J</kbd>/<kbd>K</kbd> следующий/предыдущий</span>}
          </div>
        </>
      )}
      {!editable && <div className="muted small">Решать конфликты может роль «юрист».</div>}
    </div>
  );
}
