import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useSession } from "../App";
import { api, cachedApi, qs, shortCourt, type CaseBrief, type Page } from "../api";
import type { SavedView } from "./FilterPanel";
import { Modal, useToast } from "./overlay";

type Cmd = { group: string; label: string; hint?: string; run: () => void | Promise<void> };
type Facet = { value: string; label: string; count: number };

const norm = (s: string) => s.toLowerCase().replace(/ё/g, "е");
const matches = (label: string, q: string) => norm(q).split(/\s+/).filter(Boolean).every((w) => norm(label).includes(w));

/** Командная палитра (Ctrl+K, «/»): переходы, подборки, быстрые фильтры, действия с открытым делом и поиск дел. */
export default function QuickSearch({ onClose }: { onClose: () => void }) {
  const nav = useNavigate();
  const loc = useLocation();
  const toast = useToast();
  const { me, can, refreshStats } = useSession();
  const [q, setQ] = useState("");
  const [cases, setCases] = useState<CaseBrief[]>([]);
  const [views, setViews] = useState<SavedView[]>([]);
  const [judges, setJudges] = useState<Facet[]>([]);
  const [sel, setSel] = useState(0);
  const caseId = loc.pathname.match(/^\/cases\/(\d+)/)?.[1];

  useEffect(() => {
    cachedApi<SavedView[]>("/views").then(setViews).catch(() => undefined);
    cachedApi<{ facets: Record<string, Facet[]> }>("/cases/facets", 60000).then((f) => setJudges(f.facets.judge ?? [])).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (q.trim().length < 2) {
      setCases([]);
      return;
    }
    const t = setTimeout(() => {
      api<Page<CaseBrief>>(`/cases${qs({ q, size: 6 })}`).then((p) => setCases(p.items)).catch(() => setCases([]));
    }, 180);
    return () => clearTimeout(t);
  }, [q]);

  const go = (to: string) => () => nav(to);
  const commands = useMemo<Cmd[]>(() => {
    const list: Cmd[] = [];
    if (caseId && can("lawyer")) {
      list.push({ group: "Это дело", label: "Назначить меня ответственным", hint: me.login, run: async () => {
        await api(`/cases/${caseId}`, { method: "PATCH", json: { responsible: me.login } });
        toast("Вы — ответственный по делу");
        nav(0);
      } });
      list.push({ group: "Это дело", label: "Пересчитать сроки по актам", run: async () => {
        await api(`/cases/${caseId}/deadlines/recalc`, { method: "POST" });
        toast("Сроки пересчитаны");
        refreshStats();
        nav(0);
      } });
    }
    // быстрые фильтры, распознанные в запросе
    const m = norm(q);
    const corp = m.match(/корп\w*\.?\s*([а-яa-z]?\d+)/i);
    if (corp) list.push({ group: "Фильтр", label: `Дела корпуса ${corp[1].toUpperCase()}`, run: go(`/cases?building=${encodeURIComponent(corp[1].toUpperCase())}`) });
    const year = m.match(/\b(20\d{2})\b/);
    if (year) list.push({ group: "Фильтр", label: `Дела ${year[1]} года`, run: go(`/cases?year=${year[1]}`) });
    const judgeQ = m.match(/суд(ья|ьи|ье)?\s+(.{2,})/)?.[2];
    if (judgeQ)
      for (const j of judges.filter((j) => norm(j.label).includes(judgeQ.trim())).slice(0, 4))
        list.push({ group: "Фильтр", label: `Дела судьи ${j.label}`, hint: `${j.count}`, run: go(`/cases?judge=${encodeURIComponent(j.value)}`) });
    if (/конфл/.test(m) && corp) list.push({ group: "Фильтр", label: `Конфликты корпуса ${corp[1].toUpperCase()}`, run: go(`/conflicts?building=${encodeURIComponent(corp[1].toUpperCase())}`) });

    const fixed: Cmd[] = [
      { group: "Подборки", label: "Мои дела", hint: me.login, run: go(`/cases?responsible=${encodeURIComponent(me.login)}`) },
      { group: "Подборки", label: "Просроченные сроки", run: go("/cases?overdue=true&sort=next_due") },
      { group: "Подборки", label: "Дела без УИД", run: go("/cases?has_uid=false") },
      { group: "Подборки", label: "Дела без ответственного", run: go(`/cases?responsible=${encodeURIComponent("—")}`) },
      ...views.map((v) => ({ group: "Подборки", label: v.name, hint: "сохранённая", run: go(`/${v.page}?${v.params}`) })),
      { group: "Перейти", label: "Стол", run: go("/") },
      { group: "Перейти", label: "Дела", run: go("/cases") },
      { group: "Перейти", label: "Очередь конфликтов", run: go("/conflicts") },
      { group: "Перейти", label: "Сроки", run: go("/deadlines") },
      { group: "Перейти", label: "Документы без дела", run: go("/documents?unlinked=1") },
      { group: "Перейти", label: "Журнал", run: go("/journal") },
      ...(can("admin") ? [{ group: "Перейти", label: "Сервисы и API", run: go("/admin") }] : []),
      ...(can("lawyer") ? [{ group: "Действие", label: "Выгрузка решений юристов (XLSX)", run: () => { window.location.href = "/api/v1/export/values?format=xlsx"; } }] : []),
    ];
    list.push(...(q.trim() ? fixed.filter((c) => matches(`${c.group} ${c.label}`, q)) : fixed));
    for (const c of cases)
      list.push({ group: "Дела", label: `${c.case_number || "без номера"} · ${c.plaintiffs}`, hint: shortCourt(c.court_name), run: go(`/cases/${c.id}`) });
    return list;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, cases, views, judges, caseId]);

  useEffect(() => setSel(0), [q]);

  const exec = async (c: Cmd | undefined) => {
    if (!c) return;
    onClose();
    try {
      await c.run();
    } catch (e) {
      toast((e as Error).message || "Не удалось выполнить команду", "err");
    }
  };

  let lastGroup = "";
  return (
    <Modal title="Команды и поиск" onClose={onClose} width={640}>
      <input className="search-big" autoFocus placeholder="Дело, судья, «корп 401», «2024», «конфликты корп 308», действие…" value={q}
             onChange={(e) => setQ(e.target.value)}
             onKeyDown={(e) => {
               if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, commands.length - 1)); }
               if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
               if (e.key === "Enter") exec(commands[sel]);
             }} />
      <div className="palette">
        {commands.map((c, i) => {
          const head = c.group !== lastGroup ? (lastGroup = c.group) : null;
          return (
            <div key={`${c.group}-${c.label}-${i}`}>
              {head && <div className="palette-group">{head}</div>}
              <div className={`search-hit ${i === sel ? "on" : ""}`} onMouseEnter={() => setSel(i)} onClick={() => exec(c)}>
                <span className="grow ellipsis">{c.label}</span>
                {c.hint && <span className="muted small ellipsis" style={{ maxWidth: 200 }}>{c.hint}</span>}
              </div>
            </div>
          );
        })}
        {commands.length === 0 && <div className="muted small" style={{ padding: 8 }}>Ничего не найдено</div>}
      </div>
      <div className="muted small" style={{ marginTop: 8 }}><kbd>↑</kbd> <kbd>↓</kbd> выбор · <kbd>Enter</kbd> выполнить · <kbd>Esc</kbd> закрыть</div>
    </Modal>
  );
}
