import { Topbar } from "../App";
import { useState } from "react";
import { api, fmtDateTime, type Page, type Service, type Task } from "../api";
import { ErrorBox, useAction, useLoad } from "../components/ui";
import { Modal, useToast } from "../components/overlay";
import { FormsAdmin } from "../components/Forms";
import type { Court, Entity } from "../components/CaseForm";
import { invalidateCache } from "../api";

/** Копирование в буфер: navigator.clipboard работает только по HTTPS — иначе через выделение текста. */
async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  }
}

type Tab = "services" | "tasks" | "export" | "users" | "directories" | "backups" | "forms";

export default function AdminPage() {
  const [tab, setTab] = useState<Tab>("services");
  return (
    <>
      <Topbar title="Сервисы и API" sub="Подключение сервисов автоматизации, очередь задач, выгрузка во внешние системы." />
      <div className="tabs">
        <button className={tab === "services" ? "on" : ""} onClick={() => setTab("services")}>Сервисы и ключи</button>
        <button className={tab === "tasks" ? "on" : ""} onClick={() => setTab("tasks")}>Очередь задач</button>
        <button className={tab === "export" ? "on" : ""} onClick={() => setTab("export")}>Выгрузка и календарь</button>
        <button className={tab === "users" ? "on" : ""} onClick={() => setTab("users")}>Пользователи</button>
        <button className={tab === "directories" ? "on" : ""} onClick={() => setTab("directories")}>Справочники</button>
        <button className={tab === "forms" ? "on" : ""} onClick={() => setTab("forms")}>Печатные формы</button>
        <button className={tab === "backups" ? "on" : ""} onClick={() => setTab("backups")}>Резервные копии</button>
      </div>
      {tab === "services" && <Services />}
      {tab === "tasks" && <Tasks />}
      {tab === "export" && <ExportTab />}
      {tab === "users" && <Users />}
      {tab === "directories" && <Directories />}
      {tab === "backups" && <Backups />}
      {tab === "forms" && <FormsAdmin />}
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
  const [creating, setCreating] = useState(false);
  const { run, busy } = useAction();
  const toast = useToast();

  const create = async () => {
    if (creating) return;
    setCreating(true);
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
    } finally {
      setCreating(false);
    }
  };
  const issue = (s: Service) => run(async () => {
    const k = await api<{ key: string }>(`/admin/services/${s.id}/keys`, { method: "POST" });
    setSecret({ name: s.name, key: k.key });
    list.reload();
  });
  const revoke = (id: number) => {
    if (!confirm("Отозвать ключ? Сервис с этим ключом перестанет работать сразу.")) return;
    run(async () => {
      await api(`/admin/keys/${id}`, { method: "DELETE" });
      list.reload();
    }, "Ключ отозван");
  };
  const toggle = (s: Service) => run(async () => {
    await api(`/admin/services/${s.id}`, { method: "PATCH", json: { active: !s.active } });
    list.reload();
  });

  return (
    <div className="stack">
      {secret && (
        <div className="secret">
          <b>Ключ для «{secret.name}» — скопируйте сейчас, больше он показан не будет:</b>
          <div className="mono" style={{ marginTop: 6 }}>{secret.key}</div>
          <div className="row" style={{ marginTop: 8 }}>
            <button onClick={async () => toast(await copyText(secret.key) ? "Ключ скопирован" : "Скопируйте ключ вручную", "ok")}>Копировать</button>
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
                  <button disabled={busy} onClick={() => issue(s)}>Новый ключ</button>{" "}
                  <button disabled={busy} onClick={() => toggle(s)}>{s.active ? "Отключить" : "Включить"}</button>
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
        <div><button className="primary" disabled={!name || sel.length === 0 || creating} onClick={create}>Создать и выдать ключ</button></div>
      </div>
    </div>
  );
}

function Tasks() {
  const [status, setStatus] = useState("");
  const summary = useLoad(() => api<{ type: string; status: string; count: number }[]>("/tasks/summary"), []);
  const list = useLoad(() => api<Page<Task>>(`/tasks?size=100${status ? `&status=${status}` : ""}`), [status]);
  const { run } = useAction();
  const act = (t: Task, what: "retry" | "cancel") => run(async () => {
    await api(`/tasks/${t.id}/${what}`, { method: "POST" });
    list.reload();
    summary.reload();
  });
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
        <h2>Выгрузка для внешних систем (1С и др.)</h2>
        <div className="muted small">Ключ дела — УИД, запасной — код суда + номер. Загружает файл человек; автоматически — коннектор с direction = "out" (docs/коннекторы.md) по ленте изменений <span className="mono">GET /api/v1/changes</span>.</div>
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
        <div className="muted small">Загружается коннектором (из 1С, CSV или другой системы): <span className="mono">PUT /api/v1/calendar</span> (область calendar). Без него сроки считаются по ст. 112 ТК без переносов и помечаются «*».</div>
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
  const { run } = useAction();
  const toggle = (id: number, active: boolean) => run(async () => {
    await api(`/admin/users/${id}?active=${active}`, { method: "PATCH" });
    list.reload();
  });
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


/* --------------------------------- справочники --------------------------------- */

const COURT_FIELDS: [keyof Court, string][] = [["code", "Код (как в 1С)"], ["name", "Полное название"], ["short_name", "Короткое название"],
  ["region", "Регион"], ["address", "Адрес"], ["uid_prefix", "Начало УИД (50RS0010)"]];
const ENTITY_FIELDS: [keyof Entity, string][] = [["name", "Как в деле (ГС-Саввино)"], ["full_name", "Полное наименование"], ["inn", "ИНН"],
  ["ogrn", "ОГРН"], ["address", "Адрес"]];

function Directories() {
  const courts = useLoad(() => api<Court[]>("/directories/courts"), []);
  const entities = useLoad(() => api<Entity[]>("/directories/entities"), []);
  const [court, setCourt] = useState<Partial<Court> | null>(null);
  const [entity, setEntity] = useState<Partial<Entity> | null>(null);
  const { run, busy } = useAction();
  const saveCourt = () => run(async () => {
    await api(`/directories/courts/${encodeURIComponent(court!.code ?? "")}`, { method: "PUT", json: { active: true, ...court } });
    invalidateCache("/directories");
    setCourt(null);
    courts.reload();
  }, "Суд сохранён");
  const saveEntity = () => run(async () => {
    const e = entity!;
    await api(e.id ? `/directories/entities/${e.id}` : "/directories/entities", { method: e.id ? "PUT" : "POST", json: { active: true, ...e } });
    invalidateCache("/directories");
    setEntity(null);
    entities.reload();
  }, "Юрлицо сохранено");
  return (
    <div className="stack">
      <div className="muted small">Справочники можно заполнить вручную или загрузить из 1С коннектором (POST /api/v1/ingest/courts, /ingest/entities).
        Переименование юрлица меняет его и во всех делах.</div>
      <div className="panel table-wrap">
        <div className="row pad"><h2 style={{ margin: 0 }}>Суды</h2><span className="spacer" /><button onClick={() => setCourt({ code: "", name: "" })}>+ Суд</button></div>
        <table>
          <thead><tr><th>Код</th><th>Название</th><th>Коротко</th><th>Регион</th><th>УИД</th><th></th></tr></thead>
          <tbody>
            {courts.data?.map((c) => (
              <tr key={c.code} style={{ opacity: c.active ? 1 : 0.5 }}>
                <td className="mono small">{c.code}</td><td>{c.name}</td><td>{c.short_name}</td><td className="small">{c.region}</td>
                <td className="mono small">{c.uid_prefix}</td><td><button onClick={() => setCourt(c)}>Изменить</button></td>
              </tr>
            ))}
            {courts.data?.length === 0 && <tr><td colSpan={6} className="empty-state">Справочник пуст — дела показывают название суда из источника</td></tr>}
          </tbody>
        </table>
      </div>
      <div className="panel table-wrap">
        <div className="row pad"><h2 style={{ margin: 0 }}>Юрлица</h2><span className="spacer" /><button onClick={() => setEntity({ name: "" })}>+ Юрлицо</button></div>
        <table>
          <thead><tr><th>Как в деле</th><th>Полное наименование</th><th>ИНН</th><th>ОГРН</th><th></th></tr></thead>
          <tbody>
            {entities.data?.map((e) => (
              <tr key={e.id} style={{ opacity: e.active ? 1 : 0.5 }}>
                <td><b>{e.name}</b></td><td>{e.full_name}</td><td className="mono small">{e.inn}</td><td className="mono small">{e.ogrn}</td>
                <td><button onClick={() => setEntity(e)}>Изменить</button></td>
              </tr>
            ))}
            {entities.data?.length === 0 && <tr><td colSpan={5} className="empty-state">Справочник пуст</td></tr>}
          </tbody>
        </table>
      </div>
      {court && (
        <Modal title={courts.data?.some((c) => c.code === court.code) ? "Суд" : "Новый суд"} onClose={() => setCourt(null)}
               footer={<><button onClick={() => setCourt(null)}>Отмена</button><button className="primary" disabled={busy || !court.code || !court.name} onClick={saveCourt}>Сохранить</button></>}>
          <div className="form-grid">
            {COURT_FIELDS.map(([k, label]) => (
              <label key={k} className="field">{label}
                <input value={String(court[k] ?? "")} disabled={k === "code" && !!courts.data?.some((c) => c.code === court.code)}
                       onChange={(e) => setCourt({ ...court, [k]: e.target.value })} />
              </label>
            ))}
            <label className="row small"><input type="checkbox" checked={court.active ?? true} onChange={(e) => setCourt({ ...court, active: e.target.checked })} /> Действует (показывать в выборе)</label>
          </div>
        </Modal>
      )}
      {entity && (
        <Modal title={entity.id ? "Юрлицо" : "Новое юрлицо"} onClose={() => setEntity(null)}
               footer={<><button onClick={() => setEntity(null)}>Отмена</button><button className="primary" disabled={busy || !entity.name} onClick={saveEntity}>Сохранить</button></>}>
          <div className="form-grid">
            {ENTITY_FIELDS.map(([k, label]) => (
              <label key={k} className="field">{label}
                <input value={String(entity[k] ?? "")} onChange={(e) => setEntity({ ...entity, [k]: e.target.value })} />
              </label>
            ))}
            <label className="row small"><input type="checkbox" checked={entity.active ?? true} onChange={(e) => setEntity({ ...entity, active: e.target.checked })} /> Действует</label>
          </div>
        </Modal>
      )}
    </div>
  );
}


/* -------------------------------- резервные копии -------------------------------- */

type BackupStatus = {
  configured: boolean; stale: boolean; error?: string; last_run?: string; last_ok?: string; ok?: boolean;
  db_file?: string; db_size?: number; storage_file?: string; kept?: number; free_mb?: number; backup_time?: string;
  restore_check?: { ok: boolean; details: string };
};

function Backups() {
  const s = useLoad(() => api<BackupStatus>("/admin/backups"), []);
  const d = s.data;
  if (!d) return <ErrorBox error={s.error} />;
  const mb = (n?: number) => (n ? `${(n / 1048576).toFixed(1)} МБ` : "—");
  return (
    <div className="stack">
      <div className={`panel pad ${d.ok && !d.stale ? "" : "notice"}`}>
        <h2 style={{ marginTop: 0 }}>{!d.configured ? "Копии не настроены" : d.ok && !d.stale ? "Копии в порядке" : "Внимание: проблема с копиями"}</h2>
        {d.error && <div className="error">{d.error}</div>}
        {d.configured && (
          <div className="facts">
            <div><span>Последний запуск</span>{fmtDateTime(d.last_run ?? null)}{d.stale && " — давно (больше суток)"}</div>
            <div><span>Последняя успешная копия</span>{fmtDateTime(d.last_ok ?? null)}</div>
            <div><span>Файл базы</span><span className="mono">{d.db_file ?? "—"}</span> ({mb(d.db_size)})</div>
            <div><span>Файлы документов</span><span className="mono">{d.storage_file ?? "—"}</span></div>
            <div><span>Проверка восстановления</span>{d.restore_check ? (d.restore_check.ok ? "✓ прошла" : "✗ не прошла") : "—"} <span className="muted small">{d.restore_check?.details}</span></div>
            <div><span>Хранится копий</span>{d.kept ?? "—"}</div>
            <div><span>Свободно на диске</span>{d.free_mb != null ? `${d.free_mb} МБ` : "—"}</div>
            <div><span>Время ежедневной копии</span>{d.backup_time ?? "—"}</div>
          </div>
        )}
      </div>
      <div className="muted small">Копии делает контейнер backup раз в сутки: база — 30 дней ежедневно, 12 недель еженедельно, 12 месяцев ежемесячно;
        каждая свежая копия проверяется развёртыванием во временную базу. Сделать копию сейчас: <span className="mono">docker compose exec backup backup.sh now</span>.
        Храните копии и на другом сервере — см. «Администрирование», раздел 4.</div>
    </div>
  );
}
