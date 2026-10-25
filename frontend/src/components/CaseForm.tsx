import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, api, cachedApi, qs, type CaseBrief } from "../api";
import { Modal, useToast } from "./overlay";
import { useDebounced } from "./ui";

export type Court = { code: string; name: string; short_name: string; region: string; address: string; uid_prefix: string; active: boolean };
export type Entity = { id: number; name: string; full_name: string; inn: string; ogrn: string; address: string; active: boolean };
type Dup = { id: number; uid: string | null; case_number: string; court_name: string; plaintiffs: string; building: string; flat: string; why: string[] };

type Form = Record<string, string | boolean>;

const FIELDS: { key: string; label: string; wide?: boolean; placeholder?: string }[] = [
  { key: "uid", label: "УИД", placeholder: "50RS0010-01-2026-000123-45" },
  { key: "case_number", label: "Номер дела / материала", placeholder: "2-1234/2026 или М-567/2026" },
  { key: "plaintiffs", label: "Истцы", wide: true, placeholder: "Иванов И.И.; Иванова А.А." },
  { key: "complex", label: "ЖК" },
  { key: "building", label: "Корпус" },
  { key: "flat", label: "Квартира" },
  { key: "contract_no", label: "Договор" },
  { key: "subject", label: "Предмет иска", wide: true, placeholder: "неустойка за просрочку передачи" },
  { key: "stage", label: "Стадия", placeholder: "иск | 1-я инстанция | апелляция | кассация | исполнение" },
  { key: "status", label: "Статус" },
  { key: "outcome", label: "Исход" },
  { key: "responsible", label: "Ответственный (логин)" },
];

/** Справочники судов и юрлиц — для выпадающих списков (кэшируются на минуту). */
export function useDirectories() {
  const [courts, setCourts] = useState<Court[]>([]);
  const [entities, setEntities] = useState<Entity[]>([]);
  useEffect(() => {
    cachedApi<Court[]>("/directories/courts", 60000).then(setCourts).catch(() => undefined);
    cachedApi<Entity[]>("/directories/entities", 60000).then(setEntities).catch(() => undefined);
  }, []);
  return { courts, entities };
}

/** Новое дело (case не задан) или правка реквизитов существующего. */
export default function CaseForm({ c, onClose, onSaved }: { c?: CaseBrief & { contract_no?: string }; onClose: () => void; onSaved?: () => void }) {
  const nav = useNavigate();
  const toast = useToast();
  const { courts, entities } = useDirectories();
  const init: Form = c
    ? Object.fromEntries([...FIELDS.map((f) => [f.key, String((c as unknown as Record<string, unknown>)[f.key] ?? "")]),
        ["court_code", c.court_code], ["legal_entity", c.legal_entity], ["appeal_flag", c.appeal_flag]])
    : { court_code: "", legal_entity: "", appeal_flag: false };
  const [f, setF] = useState<Form>(init);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [dups, setDups] = useState<Dup[]>([]);
  const set = (k: string, v: string | boolean) => setF((x) => ({ ...x, [k]: v }));

  // похожие дела — подсказываем по ходу ввода (только для нового дела)
  const probe = useDebounced(JSON.stringify([f.uid, f.case_number, f.contract_no, f.building, f.flat, f.plaintiffs]), 500);
  useEffect(() => {
    if (c) return;
    const [uid, case_number, contract_no, building, flat, plaintiffs] = JSON.parse(probe) as string[];
    if (![uid, case_number, contract_no, flat].some((x) => x && String(x).trim())) return setDups([]);
    api<Dup[]>(`/cases/duplicates${qs({ uid, case_number, contract_no, building, flat, plaintiffs })}`).then(setDups).catch(() => undefined);
  }, [probe, c]);

  const changed = () => Object.fromEntries(Object.entries(f).filter(([k, v]) => !c || v !== init[k]));

  const save = async (force = false) => {
    if (busy) return;
    setBusy(true);
    setErr("");
    try {
      if (c) {
        await api(`/cases/${c.id}`, { method: "PATCH", json: { ...changed(), note } });
        toast("Реквизиты дела сохранены");
        onSaved?.();
        onClose();
      } else {
        const body = Object.fromEntries(Object.entries(f).filter(([, v]) => v !== ""));
        const r = await api<CaseBrief>("/cases", { method: "POST", json: { ...body, force } });
        toast("Дело заведено");
        onClose();
        nav(`/cases/${r.id}`);
      }
    } catch (e) {
      const d = e instanceof ApiError ? e.message : (e as Error).message;
      setErr(d);
    } finally {
      setBusy(false);
    }
  };

  const nothing = c && Object.keys(changed()).length === 0;
  return (
    <Modal title={c ? `Реквизиты дела № ${c.case_number || c.id}` : "Новое дело"} onClose={onClose} width={720}
           footer={<>
             <button onClick={onClose}>Отмена</button>
             {!c && dups.length > 0 && <button disabled={busy} onClick={() => save(true)}>Это не дубль — создать</button>}
             <button className="primary" disabled={busy || !!nothing || (!c && dups.length > 0) || (!c && !f.uid && !f.case_number)}
                     onClick={() => save(false)}>{c ? "Сохранить" : "Создать дело"}</button>
           </>}>
      <div className="form-grid">
        <label className="field">Суд
          <select value={String(f.court_code ?? "")} onChange={(e) => set("court_code", e.target.value)}>
            <option value="">— не выбран —</option>
            {courts.filter((x) => x.active || x.code === f.court_code).map((x) => <option key={x.code} value={x.code}>{x.short_name || x.name}</option>)}
            {f.court_code && !courts.some((x) => x.code === f.court_code) && <option value={String(f.court_code)}>{c?.court_name || f.court_code} (нет в справочнике)</option>}
          </select>
        </label>
        <label className="field">Юрлицо (ответчик)
          <select value={String(f.legal_entity ?? "")} onChange={(e) => set("legal_entity", e.target.value)}>
            <option value="">— не выбрано —</option>
            {entities.filter((x) => x.active || x.name === f.legal_entity).map((x) => <option key={x.id} value={x.name}>{x.name}</option>)}
            {f.legal_entity && !entities.some((x) => x.name === f.legal_entity) && <option value={String(f.legal_entity)}>{String(f.legal_entity)} (нет в справочнике)</option>}
          </select>
        </label>
        {FIELDS.map((x) => (
          <label key={x.key} className={`field ${x.wide ? "wide" : ""}`}>{x.label}
            <input value={String(f[x.key] ?? "")} placeholder={x.placeholder} onChange={(e) => set(x.key, e.target.value)} />
          </label>
        ))}
        <label className="row small wide"><input type="checkbox" checked={!!f.appeal_flag} onChange={(e) => set("appeal_flag", e.target.checked)} /> Есть признаки обжалования</label>
        {c && (
          <label className="field wide">Комментарий к правке (попадёт в журнал)
            <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="напр.: по определению суда от 12.03" />
          </label>
        )}
      </div>
      {dups.length > 0 && (
        <div className="notice" style={{ marginTop: 12 }}>
          <b>Похожие дела уже есть — проверьте, не дубль ли это:</b>
          <ul className="dups">
            {dups.map((d) => (
              <li key={d.id}>
                <Link to={`/cases/${d.id}`} onClick={onClose}>{d.case_number || `#${d.id}`}</Link> · {d.plaintiffs || "—"}
                {d.building && `, корп. ${d.building}, кв. ${d.flat}`} <span className="muted">— {d.why.join(", ")}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {err && <div className="error" style={{ marginTop: 10 }}>{err}</div>}
    </Modal>
  );
}
