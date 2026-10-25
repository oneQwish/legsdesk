import { useEffect, useState } from "react";
import { api, cachedApi } from "../api";
import { Modal } from "./overlay";
import { useAction } from "./ui";
import { useLogins } from "./Work";

type Preview = { selected: number; will_change: number; applied: boolean;
  preview: { id: number; case_number: string; plaintiffs: string; from: string | boolean; to: string | boolean }[] };

const ACTIONS: Record<string, string> = { responsible: "Ответственный", stage: "Стадия", status: "Статус" };

/** Массово поставить ответственного / стадию / статус: предпросмотр → применить. */
export function BulkCasesModal({ ids, onClose, onDone }: { ids: number[]; onClose: () => void; onDone: () => void }) {
  const logins = useLogins();
  const [action, setAction] = useState("responsible");
  const [value, setValue] = useState("");
  const [note, setNote] = useState("");
  const [pv, setPv] = useState<Preview | null>(null);
  const { run, busy } = useAction();
  useEffect(() => setPv(null), [action, value]);
  const go = (dry: boolean) => run(async () => {
    const r = await api<Preview>("/cases/bulk", { method: "POST", json: { ids, action, value, note, dry_run: dry } });
    setPv(r);
    if (!dry) { onDone(); onClose(); }
  }, dry ? undefined : "Изменения применены");
  return (
    <Modal title={`Массово: ${ids.length} дел`} onClose={onClose} width={640}
           footer={<><button onClick={onClose}>Отмена</button>
             {!pv ? <button className="primary" disabled={busy} onClick={() => go(true)}>Показать, что изменится</button>
                  : <button className="primary" disabled={busy || !pv.will_change} onClick={() => go(false)}>Применить к {pv.will_change}</button>}</>}>
      <div className="form-grid">
        <label className="field">Что поменять
          <select value={action} onChange={(e) => setAction(e.target.value)}>{Object.entries(ACTIONS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
        </label>
        <label className="field">Новое значение
          {action === "responsible"
            ? <select value={value} onChange={(e) => setValue(e.target.value)}><option value="">— снять ответственного —</option>
                {logins.filter((u) => u.role !== "viewer").map((u) => <option key={u.login} value={u.login}>{u.name} ({u.login})</option>)}</select>
            : <input value={value} onChange={(e) => setValue(e.target.value)} placeholder={action === "stage" ? "апелляция" : ""} />}
        </label>
        <label className="field wide">Комментарий для журнала<input value={note} onChange={(e) => setNote(e.target.value)} /></label>
      </div>
      {pv && (
        <div style={{ marginTop: 10 }}>
          <div className="small"><b>{pv.will_change}</b> из {pv.selected} дел изменятся{pv.will_change < pv.selected && " (у остальных уже это значение)"}:</div>
          <ul className="dups">{pv.preview.map((p) => <li key={p.id}>{p.case_number || `#${p.id}`} · {p.plaintiffs} — <span className="muted">{String(p.from || "пусто")} → </span><b>{String(p.to || "пусто")}</b></li>)}</ul>
          {pv.will_change > pv.preview.length && <div className="muted small">… и ещё {pv.will_change - pv.preview.length}</div>}
        </div>
      )}
    </Modal>
  );
}

type RPreview = { disputed: number; will_resolve: number; skipped_no_source: number; field_label: string;
  preview: { case_id: number; case_number: string; value: string; others: string[] }[] };

/** Массово разрешить конфликты поля значением одного источника (по делам текущего фильтра). */
export function BulkResolveModal({ idsQuery, field: field0, onClose, onDone }: { idsQuery: string; field: string; onClose: () => void; onDone: () => void }) {
  const [fields, setFields] = useState<{ key: string; label: string }[]>([]);
  const [field, setField] = useState(field0);
  const [sources, setSources] = useState<string[]>([]);
  const [source, setSource] = useState("");
  const [note, setNote] = useState("");
  const [pv, setPv] = useState<RPreview | null>(null);
  const { run, busy } = useAction();
  useEffect(() => { cachedApi<{ key: string; label: string }[]>("/fields", 60000).then(setFields).catch(() => undefined); }, []);
  useEffect(() => {
    setPv(null);
    if (field) api<string[]>(`/values/sources?field=${encodeURIComponent(field)}`).then((s) => { setSources(s); setSource(s[0] ?? ""); }).catch(() => undefined);
  }, [field]);
  useEffect(() => setPv(null), [source]);
  const go = (dry: boolean) => run(async () => {
    const ids = await api<number[]>(`/cases/ids${idsQuery}`);
    const r = await api<RPreview>("/values/bulk-resolve", { method: "POST", json: { ids, field, source, note, dry_run: dry } });
    setPv(r);
    if (!dry) { onDone(); onClose(); }
  }, dry ? undefined : "Конфликты разрешены");
  return (
    <Modal title="Разрешить конфликты массово" onClose={onClose} width={680}
           footer={<><button onClick={onClose}>Отмена</button>
             {!pv ? <button className="primary" disabled={busy || !field || !source} onClick={() => go(true)}>Показать, что будет принято</button>
                  : <button className="primary" disabled={busy || !pv.will_resolve} onClick={() => go(false)}>Принять в {pv.will_resolve} делах</button>}</>}>
      <div className="muted small" style={{ marginBottom: 8 }}>Берутся дела текущего фильтра очереди. Решение по каждому делу — отдельная запись в журнале
        и в ленте для внешних систем. Дела, где выбранный источник молчит, останутся в очереди.</div>
      <div className="form-grid">
        <label className="field">Поле
          <select value={field} onChange={(e) => setField(e.target.value)}><option value="">— выберите —</option>
            {fields.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}</select>
        </label>
        <label className="field">Принять значение источника
          <select value={source} onChange={(e) => setSource(e.target.value)}>{sources.map((s) => <option key={s}>{s}</option>)}</select>
        </label>
        <label className="field wide">Обоснование (в журнал)<input value={note} onChange={(e) => setNote(e.target.value)} placeholder="напр.: по реестру 1С сверено с актами" /></label>
      </div>
      {pv && (
        <div style={{ marginTop: 10 }}>
          <div className="small">Спорных «{pv.field_label}»: <b>{pv.disputed}</b>; будет принято значение «{source}»: <b>{pv.will_resolve}</b>;
            без значения источника (останутся): {pv.skipped_no_source}</div>
          <ul className="dups">{pv.preview.map((p) => <li key={p.case_id}>{p.case_number || `#${p.case_id}`}: <b>{p.value}</b> <span className="muted">вместо {p.others.join(" / ")}</span></li>)}</ul>
        </div>
      )}
    </Modal>
  );
}
