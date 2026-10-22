import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, cachedApi, fmtDate, invalidateCache, localISO, qs, shortCourt } from "../api";
import { createPortal } from "react-dom";
import { Modal, useToast } from "./overlay";
import { Icon } from "./icons";
import { useLoad } from "./ui";

// ------------------------------------------------------------------------------------------
// Описание фильтров. Состояние — в адресе страницы (?building=401&building=308&has_uid=false…),
// поэтому подборку можно сохранить, переслать ссылкой и вернуться к ней кнопкой «назад».
// ------------------------------------------------------------------------------------------

type FacetItem = { value: string; label: string; count: number };
type FacetsResp = {
  facets: Record<string, FacetItem[]>;
  flags: Record<string, { true: number; false?: number }>;
  total: number;
  sum_fields: { key: string; label: string }[];
};

/** Списочные фасеты: ключ параметра, подпись, вид (chips — короткие значения плиткой). */
const FACETS: { key: string; label: string; chips?: boolean; open?: boolean }[] = [
  { key: "legal_entity", label: "Юрлицо", chips: true, open: true },
  { key: "complex", label: "ЖК", open: true },
  { key: "building", label: "Корпус", chips: true, open: true },
  { key: "court", label: "Суд", open: true },
  { key: "judge", label: "Судья", open: true },
  { key: "year", label: "Год дела", chips: true, open: true },
  { key: "subject", label: "Предмет иска" },
  { key: "outcome", label: "Исход" },
  { key: "case_status", label: "Статус" },
  { key: "stage", label: "Стадия" },
  { key: "responsible", label: "Ответственный" },
  { key: "conflict_field", label: "Конфликт по полю" },
  { key: "deadline_kind", label: "Открытый срок" },
  { key: "act_type", label: "Документы в деле" },
];
// Ключ фасета в ответе API отличается только у статуса (в адресе — case_status, чтобы не путать со статусом срока)
const apiKey = (k: string) => (k === "case_status" ? "status" : k);

const FLAGS: { key: string; label: string; yes: string; no?: string }[] = [
  { key: "overdue", label: "Просрочено", yes: "есть" },
  { key: "has_conflicts", label: "Конфликты", yes: "есть", no: "нет" },
  { key: "has_uid", label: "УИД", yes: "есть", no: "нет" },
  { key: "appeal_flag", label: "Обжалование", yes: "есть", no: "нет" },
  { key: "has_documents", label: "Документы", yes: "есть", no: "нет" },
];

const RANGES: { from: string; to: string; label: string }[] = [
  { from: "due_from", to: "due_before", label: "Ближайший срок" },
  { from: "decision_from", to: "decision_to", label: "Дата решения" },
  { from: "updated_from", to: "updated_to", label: "Изменено" },
];

export const FILTER_KEYS = [
  "q", ...FACETS.map((f) => f.key), ...FLAGS.map((f) => f.key), ...RANGES.flatMap((r) => [r.from, r.to]),
  "sum_field", "sum_min", "sum_max",
];

/** Только параметры фильтров из адреса (без страницы, сортировки, параметров самой страницы). */
export function filterParams(sp: URLSearchParams): URLSearchParams {
  const out = new URLSearchParams();
  sp.forEach((v, k) => FILTER_KEYS.includes(k) && v !== "" && out.append(k, v));
  return out;
}

export function activeCount(sp: URLSearchParams): number {
  const keys = new Set<string>();
  filterParams(sp).forEach((_, k) => keys.add(k === "sum_min" || k === "sum_max" ? "sum_field" : k));
  return keys.size;
}

// ------------------------------------------------------------------------------------------

export default function FilterPanel({ page, onClose }: { page: "cases" | "conflicts" | "deadlines"; onClose?: () => void }) {
  const [sp, setSp] = useSearchParams();
  const fp = filterParams(sp);
  const facets = useLoad(() => cachedApi<FacetsResp>(`/cases/facets${qs(fp)}`), [fp.toString()]);
  const urlQ = sp.get("q") ?? "";
  const [q, setQ] = useState(urlQ);
  const [saving, setSaving] = useState(false);
  // поиск в адресе поменялся извне (чип «×», подборка, «назад») — поле ввода следует за ним
  useEffect(() => setQ(urlQ), [urlQ]);

  /** Изменить параметры адреса; любое изменение фильтра сбрасывает страницу на первую.
   *  От актуального адреса (ссылка latest), а не от запомненного при отрисовке: иначе отложенный поиск
   *  затирал бы фильтр, выбранный за эти 350 мс (в react-router 6 и setSp(prev => …) получает старый адрес). */
  const latest = useRef(sp);
  latest.current = sp;
  const update = (fn: (p: URLSearchParams) => void) => {
    const next = new URLSearchParams(latest.current);
    fn(next);
    next.delete("page");
    latest.current = next;
    setSp(next, { replace: true });
  };
  const toggle = (key: string, value: string) =>
    update((p) => {
      const cur = p.getAll(key);
      p.delete(key);
      (cur.includes(value) ? cur.filter((x) => x !== value) : [...cur, value]).forEach((v) => p.append(key, v));
    });
  const setOne = (key: string, value: string) => update((p) => (value ? p.set(key, value) : p.delete(key)));

  useEffect(() => {
    const t = setTimeout(() => q !== urlQ && setOne("q", q.trim() ? q : ""), 350);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  const reset = () => {
    setQ("");
    update((p) => FILTER_KEYS.forEach((k) => p.delete(k)));
  };
  const n = activeCount(sp);
  const d = facets.data;

  return (
    <aside className="filters-panel">
      <div className="fp-head">
        <h2 style={{ margin: 0 }}>Фильтры</h2>
        {n > 0 && <span className="badge conflict">{n}</span>}
        <span className="spacer" />
        {n > 0 && <button className="link small" onClick={reset}>Сбросить</button>}
        {onClose && <button className="icon-btn" onClick={onClose} aria-label="Закрыть">×</button>}
      </div>
      <SavedViews page={page} onSave={() => setSaving(true)} canSave={n > 0} />
      <div className="fp-total">{d ? <><b>{d.total}</b> дел подходит</> : " "}</div>

      <input className="fp-search" placeholder="Номер, УИД, истец, договор" aria-label="Поиск по делам" value={q} onChange={(e) => setQ(e.target.value)} />

      <Section title="Быстрые" open>
        {FLAGS.map((f) => {
          const cur = sp.get(f.key) ?? "";
          const c = d?.flags[f.key];
          return (
            <div key={f.key} className="flag">
              <span className="grow">{f.label}</span>
              <div className="seg tiny">
                <button className={cur === "" ? "on" : ""} onClick={() => setOne(f.key, "")}>все</button>
                <button className={cur === "true" ? "on" : ""} onClick={() => setOne(f.key, "true")}>{f.yes} <i>{c?.true ?? ""}</i></button>
                {f.no && <button className={cur === "false" ? "on" : ""} onClick={() => setOne(f.key, "false")}>{f.no} <i>{c?.false ?? ""}</i></button>}
              </div>
            </div>
          );
        })}
      </Section>

      {FACETS.map((f) => (
        <FacetSection key={f.key} title={f.label} chips={f.chips}
                      items={(d?.facets[apiKey(f.key)] ?? []).map((x) => (f.key === "court" ? { ...x, label: shortCourt(x.label) } : x))}
                      selected={sp.getAll(f.key)} onToggle={(v) => toggle(f.key, v)}
                      onClear={() => update((p) => p.delete(f.key))} defaultOpen={f.open} />
      ))}

      <Section title="Даты" open={RANGES.some((r) => sp.get(r.from) || sp.get(r.to))}>
        {RANGES.map((r) => (
          <div key={r.from} className="range">
            <div className="small muted">{r.label}</div>
            <div className="row" style={{ flexWrap: "nowrap" }}>
              <input type="date" value={sp.get(r.from) ?? ""} onChange={(e) => setOne(r.from, e.target.value)} aria-label={`${r.label} с`} />
              <span className="muted">—</span>
              <input type="date" value={sp.get(r.to) ?? ""} onChange={(e) => setOne(r.to, e.target.value)} aria-label={`${r.label} по`} />
            </div>
          </div>
        ))}
        <div className="row" style={{ gap: 4 }}>
          {[["Просрочено", -3650, -1], ["Сегодня–3 дня", 0, 3], ["Неделя", 0, 7], ["Месяц", 0, 31]].map(([label, a, b]) => (
            <button key={label as string} className="chip" onClick={() => update((p) => {
              const day = (n: number) => { const d = new Date(); d.setDate(d.getDate() + n); return localISO(d); };
              p.set("due_from", day(a as number));
              p.set("due_before", day(b as number));
            })}>{label}</button>
          ))}
        </div>
      </Section>

      <Section title="Суммы" open={!!sp.get("sum_field")}>
        <select value={sp.get("sum_field") ?? ""} onChange={(e) => update((p) => {
          if (e.target.value) p.set("sum_field", e.target.value);
          else ["sum_field", "sum_min", "sum_max"].forEach((k) => p.delete(k));
        })} style={{ width: "100%" }}>
          <option value="">Выберите поле суммы…</option>
          {d?.sum_fields.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
        </select>
        {sp.get("sum_field") && (
          <div className="row" style={{ flexWrap: "nowrap", marginTop: 6 }}>
            <NumInput placeholder="от, ₽" value={sp.get("sum_min") ?? ""} onCommit={(v) => setOne("sum_min", v)} />
            <span className="muted">—</span>
            <NumInput placeholder="до, ₽" value={sp.get("sum_max") ?? ""} onCommit={(v) => setOne("sum_max", v)} />
          </div>
        )}
        <div className="muted small" style={{ marginTop: 4 }}>Только согласованные или решённые значения (спорные не участвуют).</div>
      </Section>

      {saving && <SaveViewModal page={page} params={fp.toString()} onClose={() => setSaving(false)} />}
    </aside>
  );
}

// --- Части панели ---------------------------------------------------------------------------

function Section({ title, open, children, badge }: { title: string; open?: boolean; children: React.ReactNode; badge?: number }) {
  const [o, setO] = useState(!!open);
  useEffect(() => {
    if (open) setO(true);
  }, [open]);
  return (
    <div className="fp-sec">
      <button className="fp-sec-head" onClick={() => setO(!o)} aria-expanded={o}>
        <span className="grow">{title}</span>
        {badge ? <span className="badge conflict">{badge}</span> : null}
        <span className="muted">{o ? "−" : "+"}</span>
      </button>
      {o && <div className="fp-sec-body">{children}</div>}
    </div>
  );
}

function FacetSection({ title, items, selected, onToggle, onClear, chips, defaultOpen }: {
  title: string;
  items: FacetItem[];
  selected: string[];
  onToggle: (v: string) => void;
  onClear: () => void;
  chips?: boolean;
  defaultOpen?: boolean;
}) {
  const [find, setFind] = useState("");
  const [all, setAll] = useState(false);
  // выбранные значения показываем всегда, даже если с текущими фильтрами по ним 0 дел
  const merged = useMemo(() => {
    const m = [...items];
    for (const v of selected) if (!m.some((x) => x.value === v)) m.push({ value: v, label: v === "—" ? "не указано" : v, count: 0 });
    return m;
  }, [items, selected]);
  const shown = merged.filter((x) => !find || x.label.toLowerCase().includes(find.toLowerCase()));
  const LIMIT = chips ? 16 : 7;
  const visible = all || find ? shown : shown.slice(0, LIMIT);
  if (merged.length === 0) return null;

  return (
    <Section title={title} open={defaultOpen || selected.length > 0} badge={selected.length}>
      {merged.length > 10 && (
        <input className="fp-find" placeholder={`Найти: ${title.toLowerCase()}`} value={find} onChange={(e) => setFind(e.target.value)} />
      )}
      {chips ? (
        <div className="chips">
          {visible.map((x) => (
            <button key={x.value} className={`chip ${selected.includes(x.value) ? "on" : ""} ${x.count === 0 ? "zero" : ""}`}
                    onClick={() => onToggle(x.value)}>
              {x.label} <i>{x.count}</i>
            </button>
          ))}
        </div>
      ) : (
        <div className="checks">
          {visible.map((x) => (
            <label key={x.value} className={`check ${x.count === 0 ? "zero" : ""}`} title={x.label}>
              <input type="checkbox" checked={selected.includes(x.value)} onChange={() => onToggle(x.value)} />
              <span className="ellipsis grow">{x.label}</span>
              <i>{x.count}</i>
            </label>
          ))}
        </div>
      )}
      <div className="row small" style={{ marginTop: 4 }}>
        {!find && shown.length > LIMIT && (
          <button className="link" onClick={() => setAll(!all)}>{all ? "свернуть" : `ещё ${shown.length - LIMIT}`}</button>
        )}
        <span className="spacer" />
        {selected.length > 0 && <button className="link" onClick={onClear}>очистить</button>}
      </div>
    </Section>
  );
}

function NumInput({ value, onCommit, placeholder }: { value: string; onCommit: (v: string) => void; placeholder: string }) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  const commit = () => v !== value && onCommit(v.replace(/\s/g, "").replace(",", "."));
  return <input inputMode="decimal" placeholder={placeholder} value={v} onChange={(e) => setV(e.target.value)}
                onBlur={commit} onKeyDown={(e) => e.key === "Enter" && commit()} style={{ width: "100%" }} />;
}

// --- Подборки ---------------------------------------------------------------------------------

export type SavedView = { id: number; name: string; page: string; params: string; on_desk: boolean; color: string; position: number };
export const VIEW_COLORS: Record<string, string> = { ink: "var(--ink)", seal: "var(--seal)", ochre: "var(--ochre)", ok: "var(--ok)", violet: "var(--violet)" };

function SavedViews({ page, onSave, canSave }: { page: string; onSave: () => void; canSave: boolean }) {
  const [sp, setSp] = useSearchParams();
  const views = useLoad(() => cachedApi<SavedView[]>("/views"), []);
  useEffect(() => {
    const h = () => {
      invalidateCache("/views");
      views.reload();
    };
    window.addEventListener("lawdesk:views", h);
    return () => window.removeEventListener("lawdesk:views", h);
  }, [views]);
  const cur = filterParams(sp).toString();
  const apply = (v: SavedView) => {
    const next = new URLSearchParams(v.params);
    for (const k of ["sort", "field", "status", "kind"]) if (sp.get(k)) next.set(k, sp.get(k)!);
    setSp(next);
  };
  const list = views.data ?? [];
  return (
    <div className="views">
      {list.map((v) => (
        <button key={v.id} className={`view-pill ${v.params === cur ? "on" : ""}`} onClick={() => apply(v)} title={v.page !== page ? "сохранено на другой странице" : ""}>
          <span className="tone" style={{ background: VIEW_COLORS[v.color] ?? "var(--ink)" }} />{v.name}
        </button>
      ))}
      <button className="view-pill add" onClick={onSave} disabled={!canSave} title={canSave ? "Сохранить текущие фильтры" : "Сначала выберите фильтры"}>
        <Icon name="pile" size={13} /> Сохранить подборку
      </button>
    </div>
  );
}

function SaveViewModal({ page, params, onClose }: { page: string; params: string; onClose: () => void }) {
  const toast = useToast();
  const [name, setName] = useState("");
  const [color, setColor] = useState("ink");
  const [onDesk, setOnDesk] = useState(true);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    if (busy || !name.trim()) return;
    setBusy(true);
    try {
      await api("/views", { method: "POST", json: { name, page, params, color, on_desk: onDesk } });
      window.dispatchEvent(new Event("lawdesk:views"));
      toast(onDesk ? `Подборка «${name}» выложена на стол` : `Подборка «${name}» сохранена`);
      onClose();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const COLOR_NAME: Record<string, string> = { ink: "чернила", seal: "сургуч", ochre: "охра", ok: "малахит", violet: "фиолетовый" };
  return (
    <Modal title="Сохранить подборку" onClose={onClose}
           footer={<><button onClick={onClose}>Отмена</button><button className="primary" disabled={!name.trim() || busy} onClick={save}>Сохранить</button></>}>
      <div className="stack">
        <label className="field">Название
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="напр.: «Разбор на сегодня», «Корпус 401, долг > 500 тыс.»"
                 onKeyDown={(e) => e.key === "Enter" && save()} />
        </label>
        <div className="row">
          <span className="small muted">Цвет стопки</span>
          {Object.entries(VIEW_COLORS).map(([k, c]) => (
            <button key={k} className={`swatch ${color === k ? "on" : ""}`} style={{ background: c }} onClick={() => setColor(k)} aria-label={`Цвет: ${COLOR_NAME[k] ?? k}`} aria-pressed={color === k} />
          ))}
        </div>
        <label className="row small"><input type="checkbox" checked={onDesk} onChange={(e) => setOnDesk(e.target.checked)} /> Выложить стопкой на «Стол»</label>
        <div className="muted small">Фильтры: <span className="mono">{decodeURIComponent(params).replace(/&/g, " · ") || "—"}</span></div>
        {err && <div className="error">{err}</div>}
      </div>
    </Modal>
  );
}

// --- Чипы активных фильтров над результатами -------------------------------------------------

const LABEL: Record<string, string> = Object.fromEntries([
  ...FACETS.map((f) => [f.key, f.label]), ...FLAGS.map((f) => [f.key, f.label]),
  ["q", "Поиск"], ["due_from", "Срок с"], ["due_before", "Срок по"], ["decision_from", "Решение с"], ["decision_to", "Решение по"],
  ["updated_from", "Изменено с"], ["updated_to", "Изменено по"], ["sum_min", "Сумма от"], ["sum_max", "Сумма до"], ["sum_field", "Сумма"],
]);

export function ActiveChips() {
  const [sp, setSp] = useSearchParams();
  const fp = filterParams(sp);
  const facets = useLoad(() => cachedApi<FacetsResp>(`/cases/facets${qs(fp)}`), [fp.toString()]);
  const entries: [string, string][] = [];
  fp.forEach((v, k) => entries.push([k, v]));
  if (!entries.length) return null;
  const labelOf = (k: string, v: string) => {
    if (v === "true") return FLAGS.find((f) => f.key === k)?.yes ?? "да";
    if (v === "false") return FLAGS.find((f) => f.key === k)?.no ?? "нет";
    if (/^\d{4}-\d{2}-\d{2}$/.test(v)) return fmtDate(v);
    if (k === "sum_field") return facets.data?.sum_fields.find((s) => s.key === v)?.label ?? v;
    if (k === "sum_min" || k === "sum_max") return Number(v).toLocaleString("ru-RU") + " ₽";
    return facets.data?.facets[apiKey(k)]?.find((x) => x.value === v)?.label ?? (v === "—" ? "не указано" : v);
  };
  const remove = (k: string, v: string) => {
    const next = new URLSearchParams(sp);
    const rest = next.getAll(k).filter((x) => x !== v);
    next.delete(k);
    rest.forEach((x) => next.append(k, x));
    if (k === "sum_field") ["sum_min", "sum_max"].forEach((x) => next.delete(x));
    next.delete("page");
    setSp(next, { replace: true });
  };
  return (
    <div className="active-chips">
      {entries.map(([k, v]) => (
        <span key={k + v} className="achip">
          <span className="muted">{LABEL[k] ?? k}:</span> {labelOf(k, v)}
          <button onClick={() => remove(k, v)} aria-label="Убрать фильтр">×</button>
        </span>
      ))}
      <button className="link small" onClick={() => {
        const next = new URLSearchParams(sp);
        FILTER_KEYS.forEach((k) => next.delete(k));
        next.delete("page");
        setSp(next, { replace: true });
      }}>сбросить все</button>
    </div>
  );
}

/** Кнопка «Фильтры» с выезжающей панелью — для страниц, где панель не стоит постоянно. */
export function FilterButton({ page }: { page: "cases" | "conflicts" | "deadlines" }) {
  const [sp] = useSearchParams();
  const [open, setOpen] = useState(false);
  const n = activeCount(sp);
  return (
    <>
      <button onClick={() => setOpen(true)}>
        <Icon name="filter" size={15} /> Фильтры {n > 0 && <span className="badge-count">{n}</span>}
      </button>
      {open && createPortal(
        <div className="fp-drawer-back" onMouseDown={(e) => e.target === e.currentTarget && setOpen(false)}>
          <FilterPanel page={page} onClose={() => setOpen(false)} />
        </div>,
        document.body,
      )}
    </>
  );
}
