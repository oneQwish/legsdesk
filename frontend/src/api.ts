export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function detail(body: unknown): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((x) => x.msg ?? JSON.stringify(x)).join("; ");
    return JSON.stringify(d);
  }
  return "";
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, ...rest } = init;
  let res: Response;
  try {
    res = await fetch(`/api/v1${path}`, {
      credentials: "same-origin",
      ...rest,
      headers: { ...(json !== undefined ? { "Content-Type": "application/json" } : {}), ...(rest.headers ?? {}) },
      body: json !== undefined ? JSON.stringify(json) : rest.body,
    });
  } catch {
    throw new ApiError(0, "Нет связи с сервером — проверьте сеть и повторите");
  }
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => undefined);
  if (!res.ok) {
    if (res.status === 401 && !path.startsWith("/auth/")) window.dispatchEvent(new Event("lawdesk:unauthorized"));
    const fallback = res.status >= 500 ? `Сервер временно недоступен (${res.status}) — повторите позже` : `Ошибка ${res.status}`;
    throw new ApiError(res.status, detail(body) || fallback);
  }
  // 200 с HTML вместо JSON — обычно страница прокси или ошибки шлюза
  if (body === undefined) throw new ApiError(res.status, "Сервер ответил не данными, а страницей — обновите страницу позже");
  return body as T;
}

/** Настройки интерфейса из backend/settings.toml, раздел [interface] (GET /settings/client).
 *  Здесь — те же умолчания, что на сервере: интерфейс работает, даже если настройки не загрузились. */
export const settings = {
  desk_strip_days: 14,
  desk_strip_max_days: 62,
  desk_hot_days: 3,
  desk_week_days: 10,
  desk_pile_size: 60,
  deadlines_page_limit: 2000,
  deadlines_group_limit: 150,
  goal_conflicts: 50,
  goal_deadlines: 20,
  goal_documents: 20,
  soon_days: 7,
  timezone: "Europe/Moscow",
};

export async function loadClientSettings(): Promise<void> {
  try {
    Object.assign(settings, await api<Partial<typeof settings>>("/settings/client"));
  } catch {
    /* остаются умолчания */
  }
}

const inflight = new Map<string, { at: number; p: Promise<unknown> }>();

/** GET с коротким кэшем: одинаковые запросы из разных частей страницы (фасеты, подборки) идут один раз. */
export function cachedApi<T>(path: string, ttlMs = 5000): Promise<T> {
  const hit = inflight.get(path);
  if (hit && Date.now() - hit.at < ttlMs) return hit.p as Promise<T>;
  const p = api<T>(path);
  inflight.set(path, { at: Date.now(), p });
  p.catch(() => inflight.delete(path));
  return p;
}

/** Сбросить кэш (после изменения подборок и т. п.). */
export function invalidateCache(prefix = "") {
  for (const k of [...inflight.keys()]) if (k.startsWith(prefix)) inflight.delete(k);
}

/** Дата ГГГГ-ММ-ДД по местному времени (toISOString дал бы UTC: с 00:00 до 03:00 по Москве — вчера). */
export function localISO(d: Date = new Date()): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

type QsValue = string | number | boolean | undefined | null | (string | number)[];

export function qs(params: Record<string, QsValue> | URLSearchParams): string {
  const p = new URLSearchParams();
  if (params instanceof URLSearchParams) params.forEach((v, k) => v !== "" && p.append(k, v));
  else
    for (const [k, v] of Object.entries(params)) {
      if (Array.isArray(v)) v.forEach((x) => p.append(k, String(x)));
      else if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
    }
  const s = p.toString();
  return s ? `?${s}` : "";
}

// --- Типы ответа API -----------------------------------------------------------------------

export type Role = "viewer" | "lawyer" | "admin";

export interface Me {
  kind: "user";
  id: number;
  login: string;
  full_name: string;
  role: Role;
  auth_mode: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
}

export interface CaseBrief {
  id: number;
  uid: string | null;
  court_code: string;
  court_name: string;
  case_number: string;
  legal_entity: string;
  complex: string;
  building: string;
  flat: string;
  plaintiffs: string;
  subject: string;
  stage: string;
  status: string;
  outcome: string;
  responsible: string;
  appeal_flag: boolean;
  updated_at: string;
  conflicts: number;
  open_deadlines: number;
  next_due: string | null;
  next_title?: string | null;
  awarded?: number | null;
  claimed?: number | null;
}

export interface Observation {
  id: number;
  source: string;
  source_ref: string;
  value: string;
  value_num: number | null;
  document_id: number | null;
  page: number | null;
  quote: string;
  confidence: number | null;
  observed_at: string;
}

export type ValueStatus = "confirmed" | "single" | "conflict" | "appeal_possible" | "resolved" | "empty";

export interface CaseValue {
  id: number;
  field: string;
  label: string;
  kind: string;
  group: string;
  status: ValueStatus;
  value: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
  resolution_note: string;
  observations: Observation[];
}

export interface DocumentBrief {
  id: number;
  sha256: string;
  filename: string;
  kind: string;
  act_type: string;
  instance: string;
  act_date: string | null;
  motivated_date: string | null;
  outcome: string;
  track_no: string;
  storage_backend: string;
  docflow_id: string;
  link_method: string;
  case_id: number | null;
  pages: number | null;
}

export interface DocumentFull extends DocumentBrief {
  mime: string;
  size: number | null;
  text: string;
  text_source: string;
  signature_ref: string;
  meta: Record<string, unknown>;
  created_at: string;
}

export interface Deadline {
  id: number;
  case_id: number;
  document_id: number | null;
  kind: string;
  title: string;
  start_date: string | null;
  due_date: string;
  rule: string;
  calendar_confirmed: boolean;
  auto: boolean;
  status: "open" | "done" | "cancelled";
  assignee: string;
  note: string;
  case_number?: string;
  court_name?: string;
  plaintiffs?: string;
}

export interface CaseFull extends CaseBrief {
  contract_no: string;
  extra: Record<string, unknown>;
  aliases: { court_code: string; number: string }[];
  values: CaseValue[];
  documents: DocumentBrief[];
  deadlines: Deadline[];
}

export interface EventItem {
  id: number;
  ts: string;
  actor_type: string;
  actor: string;
  action: string;
  entity: string;
  entity_id: number | null;
  case_id: number | null;
  data: Record<string, unknown>;
}

export interface Service {
  id: number;
  name: string;
  description: string;
  scopes: string[];
  task_types: string[];
  active: boolean;
  created_at: string;
  last_seen: string | null;
  keys: { id: number; prefix: string; created_at: string; revoked_at: string | null }[];
}

export interface Task {
  id: number;
  type: string;
  status: string;
  priority: number;
  payload: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error: string;
  attempts: number;
  max_attempts: number;
  case_id: number | null;
  locked_by: string;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface Stats {
  cases: number;
  cases_with_uid: number;
  documents: number;
  documents_unlinked: number;
  values_by_status: Record<string, number>;
  deadlines_overdue: number;
  deadlines_week: number;
}

// --- Форматирование -------------------------------------------------------------------------

export const fmtDate = (s: string | null | undefined) => (s ? new Date(s.length === 10 ? s + "T00:00:00" : s).toLocaleDateString("ru-RU") : "—");
export const fmtDateTime = (s: string | null | undefined) =>
  s ? new Date(s).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" }) : "—";

export function fmtValue(kind: string, v: string | null): string {
  if (v === null || v === "") return "—";
  if (kind === "money") {
    const n = Number(String(v).replace(/[^\d.,-]/g, "").replace(",", "."));
    if (!Number.isNaN(n)) return n.toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " ₽";
  }
  return v;
}

/** «Железнодорожный городской суд Московской области» → «Железнодорожный горсуд МО». */
export function shortCourt(name: string): string {
  return name
    .replace(/городской суд/i, "горсуд")
    .replace(/районный суд/i, "райсуд")
    .replace(/Московской области/i, "МО")
    .replace(/г\. Москвы/i, "Москва")
    .replace(/г\. Санкт-Петербурга/i, "СПб")
    .replace(/судебный участок/i, "с/у")
    .replace(/мирового судьи/i, "МС");
}

/** Подсказка для расходящихся сумм: кратность 2 или 0,5 часто означает «на двух истцов / в равных долях». */
export function moneyHint(values: number[]): string {
  const v = values.filter((x) => x > 0).sort((a, b) => a - b);
  for (let i = 0; i < v.length; i++)
    for (let j = i + 1; j < v.length; j++) {
      const r = v[j] / v[i];
      for (const k of [2, 3, 4])
        if (Math.abs(r - k) < 0.0005) return `Одно значение ровно в ${k} раза больше другого — возможно, сумма на ${k} истцов («в равных долях»).`;
      if (Math.abs(r - 10) < 0.0005 || Math.abs(r - 100) < 0.0005) return "Значения отличаются на разряд — вероятна ошибка распознавания цифр.";
    }
  return "";
}

/** Краткая сумма: 1 257 727 → «1,26 млн», 612 567 → «613 тыс.» */
export function fmtShortMoney(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  if (Math.abs(n) >= 1e6) return (n / 1e6).toLocaleString("ru-RU", { maximumFractionDigits: 2 }) + " млн";
  if (Math.abs(n) >= 1e3) return Math.round(n / 1e3).toLocaleString("ru-RU") + " тыс.";
  return Math.round(n).toLocaleString("ru-RU") + " ₽";
}

export const DEADLINE_KIND: Record<string, { label: string; color: string }> = {
  appeal: { label: "апелляционная жалоба", color: "var(--seal)" },
  effective: { label: "вступление в силу", color: "var(--ok)" },
  cassation: { label: "кассационная жалоба", color: "var(--violet)" },
  private_complaint: { label: "частная жалоба", color: "var(--ochre)" },
  default_cancel: { label: "отмена заочного", color: "var(--ochre)" },
  hearing: { label: "заседание", color: "var(--link)" },
  custom: { label: "свой срок", color: "var(--ink-2)" },
};

export function daysLeft(due: string): number {
  const d = new Date(due + "T00:00:00");
  const t = new Date();
  t.setHours(0, 0, 0, 0);
  return Math.round((d.getTime() - t.getTime()) / 86400000);
}

export const STATUS_LABEL: Record<string, string> = {
  confirmed: "подтверждено",
  single: "один источник",
  conflict: "конфликт",
  appeal_possible: "возможна апелляция",
  resolved: "решено юристом",
  empty: "нет данных",
};

export const ACTION_LABEL: Record<string, string> = {
  login: "Вход",
  case_created: "Дело создано",
  case_updated: "Дело изменено",
  case_merged: "Дела слиты",
  value_resolved: "Конфликт разрешён",
  value_reopened: "Поле открыто снова",
  value_status: "Статус поля",
  document_created: "Документ загружен",
  document_updated: "Документ обновлён",
  document_linked: "Документ привязан",
  document_viewed: "Документ открыт",
  deadline_added: "Срок добавлен",
  deadline_updated: "Срок изменён",
  deadlines_recalculated: "Сроки пересчитаны",
  calendar_loaded: "Календарь загружен",
  task_created: "Задача создана",
  task_done: "Задача выполнена",
  task_failed: "Задача провалена",
  task_cancelled: "Задача отменена",
  task_retried: "Задача перезапущена",
  service_created: "Сервис создан",
  service_updated: "Сервис изменён",
  api_key_issued: "Выдан API-ключ",
  api_key_revoked: "API-ключ отозван",
  export: "Выгрузка",
  user_active: "Доступ пользователя",
};
