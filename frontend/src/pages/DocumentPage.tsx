import { useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useSession } from "../App";
import { api, fmtDate, type DocumentFull } from "../api";
import { ErrorBox, StatusBadge, useLoad } from "../components/ui";

type Extracted = { id: number; field: string; source: string; value: string; page: number | null; quote: string; value_status: string };

export default function DocumentPage() {
  const { id } = useParams();
  const [sp] = useSearchParams();
  const { can } = useSession();
  const doc = useLoad(() => api<DocumentFull>(`/documents/${id}`), [id]);
  const extracted = useLoad(() => api<Extracted[]>(`/documents/${id}/observations`), [id]);
  const [find, setFind] = useState("");
  const d = doc.data;

  const highlighted = useMemo(() => {
    if (!d?.text || find.trim().length < 2) return null;
    const re = new RegExp(`(${find.trim().replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi");
    return d.text.split(re).map((part, i) => (i % 2 ? <mark key={i}>{part}</mark> : part));
  }, [d?.text, find]);

  if (doc.error) return <ErrorBox error={doc.error} />;
  if (!d) return null;
  const page = sp.get("page");
  const hasFile = Boolean(d.storage_backend && d.storage_backend !== "external");

  const link = async () => {
    const v = prompt("ID дела, к которому привязать документ (пусто — отвязать):", d.case_id ? String(d.case_id) : "");
    if (v === null) return;
    try {
      await api(`/documents/${d.id}/link`, { method: "POST", json: v ? { case_id: Number(v) } : {} });
      doc.reload();
    } catch (e) {
      alert((e as Error).message);
    }
  };

  return (
    <>
      <div className="page-head">
        <div className="grow">
          <div className="muted small">
            <Link to="/documents">Документы</Link> / #{d.id}
            {d.case_id && <> · <Link to={`/cases/${d.case_id}`}>дело #{d.case_id}</Link></>}
          </div>
          <h1>{d.act_type || d.kind} {d.act_date && `от ${fmtDate(d.act_date)}`}</h1>
          <div className="muted small">{d.filename} · <span className="mono">{d.sha256}</span></div>
        </div>
        <div className="row">
          {hasFile && <a className="btn" href={`/api/v1/documents/${d.id}/file`} target="_blank" rel="noreferrer">Открыть файл</a>}
          {d.signature_ref && <a className="btn" href={`/api/v1/documents/${d.id}/file?signature=true`}>Подпись .sig</a>}
          {can("lawyer") && <button onClick={link}>{d.case_id ? "Перепривязать" : "Привязать к делу"}</button>}
        </div>
      </div>
      <div className="viewer">
        {hasFile ? (
          <iframe title="Документ" src={`/api/v1/documents/${d.id}/file${page ? `#page=${page}` : ""}`} />
        ) : (
          <div className="panel empty-state">
            Файл не загружен в хранилище{d.docflow_id ? ` (карточка 1С:ДО ${d.docflow_id})` : ""}.<br />Доступен текст справа.
          </div>
        )}
        <div className="side stack">
          <div className="panel pad">
            <div className="facts">
              <div><span>Тип</span>{d.kind}</div>
              <div><span>Инстанция</span>{d.instance || "—"}</div>
              <div><span>Дата акта</span>{fmtDate(d.act_date)}</div>
              <div><span>Мотивированное</span>{fmtDate(d.motivated_date)}</div>
              <div><span>Трек Почты</span><span className="mono">{d.track_no || "—"}</span></div>
              <div><span>Привязка</span>{d.case_id ? d.link_method || "—" : "не привязан"}</div>
            </div>
            {"unresolved_case_ref" in d.meta && (
              <div className="notice small" style={{ marginTop: 10 }}>
                Сервис указал дело, которого нет в базе: {JSON.stringify(d.meta.unresolved_case_ref)}
              </div>
            )}
          </div>
          {extracted.data && extracted.data.length > 0 && (
            <div className="panel pad">
              <h2>Извлечено из документа</h2>
              <table>
                <tbody>
                  {extracted.data.map((o) => (
                    <tr key={o.id}>
                      <td className="small">{o.field}{o.page && <div className="muted">с. {o.page}</div>}</td>
                      <td><b>{o.value}</b>{o.quote && <div className="quote">«{o.quote}»</div>}</td>
                      <td><StatusBadge status={o.value_status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="panel pad">
            <div className="row" style={{ marginBottom: 8 }}>
              <h2 style={{ margin: 0 }}>Текст</h2>
              <span className="muted small">{d.text_source}</span>
              <span className="spacer" />
              <input placeholder="Найти в тексте" value={find} onChange={(e) => setFind(e.target.value)} />
            </div>
            <div className="doctext">{highlighted ?? (d.text || <span className="muted">Текста нет</span>)}</div>
          </div>
        </div>
      </div>
    </>
  );
}
