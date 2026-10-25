import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, fmtDate } from "../api";
import { Modal, useToast } from "./overlay";
import { useAction, useDebounced } from "./ui";

export type FormTpl = { key: string; title: string; file: string; size: number };

/** Скачать файл, который сервер отдаёт на POST (заполненная форма). */
async function download(path: string): Promise<void> {
  const r = await fetch(`/api/v1${path}`, { method: "POST", credentials: "same-origin" });
  if (!r.ok) {
    const body = await r.json().catch(() => null);
    throw new Error((body && body.detail) || `Ошибка ${r.status}`);
  }
  const name = decodeURIComponent((r.headers.get("Content-Disposition") ?? "").split("''")[1] ?? "документ.docx");
  const url = URL.createObjectURL(await r.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 1000);
}

/** Окно «Документ по шаблону»: выбрать форму → скачать заполненный .docx. */
export function FormsModal({ caseId, onClose }: { caseId: number; onClose: () => void }) {
  const [forms, setForms] = useState<FormTpl[] | null>(null);
  const { run, busy } = useAction();
  useEffect(() => {
    api<FormTpl[]>("/forms").then(setForms).catch(() => setForms([]));
  }, []);
  return (
    <Modal title="Документ по шаблону" onClose={onClose} footer={<button onClick={onClose}>Закрыть</button>}>
      <div className="muted small" style={{ marginBottom: 8 }}>Данные дела подставятся в шаблон; документ откроется в Word — допишите и подпишите.</div>
      <div className="stack" style={{ gap: 4 }}>
        {forms?.map((f) => (
          <button key={f.key} className="bell-item" disabled={busy}
                  onClick={() => run(() => download(`/cases/${caseId}/forms/${encodeURIComponent(f.key)}`), "Документ сформирован")}>
            <span className="grow"><span className="t">{f.title}</span><span className="muted small">{f.file}</span></span>
          </button>
        ))}
        {forms?.length === 0 && <div className="empty-state">Шаблонов нет — администратор добавляет их в «Сервисы и API» → «Печатные формы»</div>}
      </div>
    </Modal>
  );
}

type Hit = { id: number; filename: string; kind: string; act_type: string; act_date: string | null; case_id: number | null; case_number: string | null; snippet: string };

/** Поиск по текстам документов с подсветкой найденного (русская морфология). */
export function TextSearch() {
  const [q, setQ] = useState("");
  const qd = useDebounced(q.trim(), 400);
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    if (qd.length < 2) return setHits(null);
    let live = true;
    api<Hit[]>(`/documents/search?q=${encodeURIComponent(qd)}`).then((h) => live && (setHits(h), setErr(""))).catch((e) => live && setErr(e.message));
    return () => { live = false; };
  }, [qd]);
  return (
    <div className="stack">
      <input className="search-big" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Поиск по тексту документов"
             placeholder="Слова из текста: неустойка мораторий · «точная фраза» · -исключить" />
      {err && <div className="error">{err}</div>}
      {hits?.map((h) => (
        <div key={h.id} className="panel pad">
          <div className="row small">
            <Link to={`/documents/${h.id}?find=${encodeURIComponent(qd)}`}><b>{h.act_type || h.kind || "документ"}</b> {h.act_date && `от ${fmtDate(h.act_date)}`}</Link>
            <span className="muted">{h.filename}</span><span className="spacer" />
            {h.case_id ? <Link to={`/cases/${h.case_id}`}>дело {h.case_number || `#${h.case_id}`}</Link> : <span className="badge appeal_possible">без дела</span>}
          </div>
          <div className="snippet">{h.snippet.split("\u0002").map((part, i) => {
            if (i === 0) return part;
            const [hit, rest] = part.split("\u0003");
            return <span key={i}><mark>{hit}</mark>{rest}</span>;
          })}</div>
        </div>
      ))}
      {hits?.length === 0 && <div className="panel empty-state">Ничего не найдено</div>}
    </div>
  );
}

/** Администрирование шаблонов: список, загрузка, удаление, подсказка по полям. */
export function FormsAdmin() {
  const toast = useToast();
  const [forms, setForms] = useState<FormTpl[]>([]);
  const [vars, setVars] = useState<Record<string, string>>({});
  const [showVars, setShowVars] = useState(false);
  const { run, busy } = useAction();
  const load = () => api<FormTpl[]>("/forms").then(setForms).catch(() => undefined);
  useEffect(() => {
    load();
    api<Record<string, string>>("/forms/variables").then(setVars).catch(() => undefined);
  }, []);
  const upload = (file: File) => run(async () => {
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch("/api/v1/forms", { method: "POST", body: fd, credentials: "same-origin" });
    if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail ?? `Ошибка ${r.status}`);
    load();
  }, "Шаблон загружен");
  const remove = (f: FormTpl) => {
    if (!confirm(`Удалить шаблон «${f.title}»?`)) return;
    run(async () => { await api(`/forms/${encodeURIComponent(f.key)}`, { method: "DELETE" }); load(); toast("Шаблон удалён"); });
  };
  return (
    <div className="stack">
      <div className="muted small">Шаблон — обычный документ Word: в нужных местах напишите поля в двойных фигурных скобках, например
        {" "}<span className="mono">{"{{ case.case_number }}"}</span>. Имя файла станет названием формы. Файл с тем же именем заменит прежний.</div>
      <div className="row">
        <label className="btn">Загрузить шаблон .docx
          <input type="file" accept=".docx" hidden disabled={busy} onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = ""; }} />
        </label>
        <button className="link" onClick={() => setShowVars(!showVars)}>{showVars ? "скрыть поля" : "Какие поля можно вставить"}</button>
      </div>
      {showVars && (
        <div className="panel table-wrap"><table><tbody>
          {Object.entries(vars).map(([k, v]) => <tr key={k}><td className="mono small">{k}</td><td className="small">{v}</td></tr>)}
        </tbody></table></div>
      )}
      <div className="panel table-wrap"><table>
        <thead><tr><th>Форма</th><th>Файл</th><th></th></tr></thead>
        <tbody>
          {forms.map((f) => (
            <tr key={f.key}><td>{f.title}</td><td className="small mono">{f.file}</td>
              <td><button className="link small danger" onClick={() => remove(f)}>удалить</button></td></tr>
          ))}
          {forms.length === 0 && <tr><td colSpan={3} className="empty-state">Шаблонов нет</td></tr>}
        </tbody>
      </table></div>
    </div>
  );
}
