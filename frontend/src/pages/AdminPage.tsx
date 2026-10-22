import { Topbar } from "../App";
import { useState } from "react";
import { api, fmtDateTime, type Page, type Service, type Task } from "../api";
import { ErrorBox, useLoad } from "../components/ui";

type Tab = "services" | "tasks" | "export" | "users";

export default function AdminPage() {
  const [tab, setTab] = useState<Tab>("services");
  return (
    <>
      <Topbar title="Сервисы и API" sub="Подключение сервисов автоматизации, очередь задач, выгрузка для 1С." />
      <div className="tabs">
        <button className={tab === "services" ? "on" : ""} onClick={() => setTab("services")}>Сервисы и ключи</button>
        <button className={tab === "tasks" ? "on" : ""} onClick={() => setTab("tasks")}>Очередь задач</button>
        <button className={tab === "export" ? "on" : ""} onClick={() => setTab("export")}>Выгрузка и календарь</button>
        <button className={tab === "users" ? "on" : ""} onClick={() => setTab("users")}>Пользователи</button>
      </div>
      {tab === "services" && <Services />}
      {tab === "tasks" && <Tasks />}
      {tab === "export" && <ExportTab />}
      {tab === "users" && <Users />}
    </>
  );
}

function Services() {
  const scopes = useLoad(() => api<Record<string, string>>("/admin/scopes"), []);
  const list = useLoad(() => api<Service[]>("/admin/services"), []);
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [sel, setSel] = useState<string[]>(["read", "ingest"]);
  const [types, setTypes] = useState("");
  const [secret, setSecret] = useState<{ name: string; key: string } | null>(null);
  const [err, setErr] = useState("");

  const create = async () => {
    setErr("");
    try {
      const s = await api<Service>("/admin/services", {
        method: "POST",
        json: { name, description: desc, scopes: sel, task_types: types.split(",").map((x) => x.trim()).filter(Boolean) },
      });
      const k = await api<{ key: string }>(`/admin/services/${s.id}/keys`, { method: "POST" });
      setSecret({ name: s.name, key: k.key });
      setName("");
      setDesc("");
      setTypes("");
      list.reload();
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  const issue = async (s: Service) => {
    const k = await api<{ key: string }>(`/admin/services/${s.id}/keys`, { method: "POST" });
    setSecret({ name: s.name, key: k.key });
    list.reload();
  };
  const revoke = async (id: number) => {
    if (!confirm("Отозвать ключ? Сервис с этим ключом перестанет работать сразу.")) return;
    await api(`/admin/keys/${id}`, { method: "DELETE" });
    list.reload();
  };
  const toggle = async (s: Service) => {
    await api(`/admin/services/${s.id}`, { method: "PATCH", json: { active: !s.active } });
    list.reload();
  };

  return (
    <div className="stack">
      {secret && (
        <div className="secret">
          <b>Ключ для «{secret.name}» — скопируйте сейчас, больше он показан не будет:</b>
          <div className="mono" style={{ marginTop: 6 }}>{secret.key}</div>
          <div className="row" style={{ marginTop: 8 }}>
            <button onClick={() => navigator.clipboard.writeText(secret.key)}>Копировать</button>
            <button onClick={() => setSecret(null)}>Скрыть</button>
          </div>
        </div>
      )}
      <div className="panel table-wrap">
        <table>
          <thead><tr><th>Сервис</th><th>Права</th><th>Типы задач</th><th>Был в сети</th><th>Ключи</th><th></th></tr></thead>
          <tbody>
            {list.data?.map((s) => (
              <tr key={s.id} style={{ opacity: s.active ? 1 : 0.5 }}>
                <td><b>{s.name}</b><div className="muted small">{s.description}</div></td>
                <td>{s.scopes.map((x) => <span key={x} className="badge src" style={{ marginRight: 3 }}>{x}</span>)}</td>
                <td className="small">{s.task_types.join(", ") || "—"}</td>
                <td className="small nowrap">{fmtDateTime(s.last_seen)}</td>
                <td className="small">
                  {s.keys.map((k) => (
                    <div key={k.id} className="nowrap">
                      <span className="mono">ldk_{k.prefix}_…</span>{" "}
                      {k.revoked_at ? <span className="muted">отозван</span> : <button className="link danger" onClick={() => revoke(k.id)}>отозвать</button>}
                    </div>
                  ))}
                </td>
                <td className="nowrap">
                  <button onClick={() => issue(s)}>Новый ключ</button>{" "}
                  <button onClick={() => toggle(s)}>{s.active ? "Отключить" : "Включить"}</button>
                </td>
              </tr>
            ))}
            {list.data?.length === 0 && <tr><td colSpan={6} className="empty-state">Сервисов нет</td></tr>}
          </tbody>
        </table>
      </div>
      <div className="panel pad stack">
        <h2>Подключить сервис</h2>
        <div className="row">
          <label className="field">Имя<input value={name} onChange={(e) => setName(e.target.value)} placeholder="ocr-mac, letters-loader…" /></label>
          <label className="field grow">Описание<input value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="Что делает сервис" /></label>
          <label className="field">Типы задач (через запятую)<input value={types} onChange={(e) => setTypes(e.target.value)} placeholder="ocr, extract" /></label>
        </div>
        <div className="row">
          {Object.entries(scopes.data ?? {}).map(([k, v]) => (
            <label key={k} className="row small" title={v}>
              <input type="checkbox" checked={sel.includes(k)} onChange={(e) => setSel(e.target.checked ? [...sel, k] : sel.filter((x) => x !== k))} />
              <b>{k}</b> <span className="muted">{v}</span>
            </label>
          ))}
        </div>
        <ErrorBox error={err} />
        <div><button className="primary" disabled={!name || sel.length === 0} onClick={create}>Создать и выдать ключ</button></div>
      </div>
    </div>
  );
}

function Tasks() {
  const [status, setStatus] = useState("");
  const summary = useLoad(() => api<{ type: string; status: string; count: number }[]>("/tasks/summary"), []);
  const list = useLoad(() => api<Page<Task>>(`/tasks?size=100${status ? `&status=${status}` : ""}`), [status]);
  const act = async (t: Task, what: "retry" | "cancel") => {
    await api(`/tasks/${t.id}/${what}`, { method: "POST" });
    list.reload();
    summary.reload();
  };
  const types = [...new Set(summary.data?.map((r) => r.type))];
  const statuses = ["queued", "running", "done", "failed", "cancelled"];
  return (
    <div className="stack">
      <div className="panel table-wrap">
        <table>
          <thead><tr><th>Тип</th>{statuses.map((s) => <th key={s} className="right">{s}</th>)}</tr></thead>
          <tbody>
            {types.map((t) => (
              <tr key={t}>
                <td><b>{t}</b></td>
                {statuses.map((s) => <td key={s} className="right">{summary.data?.find((r) => r.type === t && r.status === s)?.count ?? ""}</td>)}
              </tr>
            ))}
            {types.length === 0 && <tr><td colSpan={6} className="empty-state">Очередь пуста</td></tr>}
          </tbody>
        </table>
      </div>
      <div className="row">
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Все статусы</option>
          {statuses.map((s) => <option key={s}>{s}</option>)}
        </select>
      </div>
      <div className="panel table-wrap">
        <table>
          <thead><tr><th>#</th><th>Тип</th><th>Статус</th><th>Попытки</th><th>Исполнитель</th><th>Создана</th><th>Ошибка / результат</th><th></th></tr></thead>
          <tbody>
            {list.data?.items.map((t) => (
              <tr key={t.id}>
                <td>{t.id}</td>
                <td>{t.type}</td>
                <td>{t.status}</td>
                <td>{t.attempts}/{t.max_attempts}</td>
                <td className="small">{t.locked_by}</td>
                <td className="small nowrap">{fmtDateTime(t.created_at)}<div className="muted">{t.created_by}</div></td>
                <td className="small mono" style={{ maxWidth: 360, wordBreak: "break-word" }}>{t.error || (t.result ? JSON.stringify(t.result) : "")}</td>
                <td className="nowrap">
                  {(t.status === "failed" || t.status === "cancelled") && <button onClick={() => act(t, "retry")}>Повторить</button>}
                  {(t.status === "queued" || t.status === "running") && <button className="danger" onClick={() => act(t, "cancel")}>Отменить</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ExportTab() {
  const cal = useLoad(() => api<{ year: number; days: number; nonworking: number }[]>("/calendar"), []);
  const [status, setStatus] = useState("resolved");
  const [since, setSince] = useState("");
  const url = (format: string) => `/api/v1/export/values?format=${format}&status=${status}${since ? `&since=${since}` : ""}`;
  const thisYear = new Date().getFullYear();
  const missing = [thisYear, thisYear + 1].filter((y) => !cal.data?.some((c) => c.year === y));
  return (
    <div className="stack">
      <div className="panel pad stack">
        <h2>Выгрузка для загрузки в 1С</h2>
        <div className="muted small">Ключ дела — УИД, запасной — код суда 1С + номер. Загрузку в 1С выполняет человек; автоматическая интеграция читает ленту изменений <span className="mono">GET /api/v1/changes</span>.</div>
        <div className="row">
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="resolved">Только решения юристов</option>
            <option value="resolved,confirmed">Решения + подтверждённые источниками</option>
            <option value="resolved,confirmed,single">Все известные значения</option>
          </select>
          <label className="row small">изменённые с <input type="date" value={since} onChange={(e) => setSince(e.target.value)} /></label>
          <a className="btn" href={url("xlsx")}>Скачать XLSX</a>
          <a className="btn" href={url("csv")}>Скачать CSV</a>
        </div>
      </div>
      <div className="panel pad stack">
        <h2>Производственный календарь</h2>
        <div className="muted small">Загружается сервисом из регламентированного календаря 1С: <span className="mono">PUT /api/v1/calendar</span> (область calendar). Без него сроки считаются по ст. 112 ТК без переносов и помечаются «*».</div>
        {missing.length > 0 && <div className="notice">Не загружен календарь на {missing.join(" и ")} год.</div>}
        <table>
          <thead><tr><th>Год</th><th className="right">Дней</th><th className="right">Нерабочих</th></tr></thead>
          <tbody>
            {cal.data?.map((c) => <tr key={c.year}><td>{c.year}</td><td className="right">{c.days}</td><td className="right">{c.nonworking}</td></tr>)}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Users() {
  const list = useLoad(() => api<{ id: number; login: string; full_name: string; role: string; active: boolean; last_login: string | null }[]>("/admin/users"), []);
  const toggle = async (id: number, active: boolean) => {
    await api(`/admin/users/${id}?active=${active}`, { method: "PATCH" });
    list.reload();
  };
  return (
    <div className="stack">
      <div className="muted small">Роли назначаются группами AD (администратор / юрист / просмотр) при каждом входе. Здесь можно только закрыть доступ к рабочему месту.</div>
      <div className="panel table-wrap">
        <table>
          <thead><tr><th>Логин</th><th>ФИО</th><th>Роль</th><th>Последний вход</th><th></th></tr></thead>
          <tbody>
            {list.data?.map((u) => (
              <tr key={u.id} style={{ opacity: u.active ? 1 : 0.5 }}>
                <td className="mono">{u.login}</td>
                <td>{u.full_name}</td>
                <td>{u.role}</td>
                <td className="small">{fmtDateTime(u.last_login)}</td>
                <td><button onClick={() => toggle(u.id, !u.active)}>{u.active ? "Закрыть доступ" : "Открыть доступ"}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
