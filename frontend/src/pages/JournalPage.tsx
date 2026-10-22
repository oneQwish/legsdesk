import { Topbar } from "../App";
import { useState } from "react";
import { Link } from "react-router-dom";
import { ACTION_LABEL, api, fmtDateTime, qs, type EventItem, type Page } from "../api";
import { ErrorBox, Pager, useLoad } from "../components/ui";
import { describe } from "./CasePage";

export default function JournalPage() {
  const [action, setAction] = useState("");
  const [actor, setActor] = useState("");
  const [page, setPage] = useState(1);
  const list = useLoad(() => api<Page<EventItem>>(`/journal${qs({ action, actor, page, size: 100 })}`), [action, actor, page]);
  return (
    <>
      <Topbar title="Журнал" sub="Все действия людей и сервисов; решения юристов уходят отсюда в ленту для 1С.">
      <input placeholder="Кто (логин/сервис)" value={actor} onChange={(e) => { setActor(e.target.value); setPage(1); }} />
      <select value={action} onChange={(e) => { setAction(e.target.value); setPage(1); }}>
        <option value="">Все действия</option>
        {Object.entries(ACTION_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </select>
      </Topbar>
      <ErrorBox error={list.error} />
      <div className="panel">
        <div className="table-wrap">
          <table>
            <thead><tr><th>Когда</th><th>Кто</th><th>Действие</th><th>Дело</th><th>Подробности</th></tr></thead>
            <tbody>
              {list.data?.items.map((e) => (
                <tr key={e.id}>
                  <td className="nowrap small">{fmtDateTime(e.ts)}</td>
                  <td className="small">{e.actor}</td>
                  <td>{ACTION_LABEL[e.action] ?? e.action}</td>
                  <td>{e.case_id && <Link to={`/cases/${e.case_id}`}>#{e.case_id}</Link>}</td>
                  <td className="small mono" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", maxWidth: 520 }}>{describe(e)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {list.data && <Pager page={page} size={list.data.size} total={list.data.total} onPage={setPage} />}
      </div>
    </>
  );
}
