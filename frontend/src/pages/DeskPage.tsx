import { useMemo } from "react";
import { Link } from "react-router-dom";
import { Topbar, useSession } from "../App";
import { api, cachedApi, invalidateCache, localISO, qs, settings, type CaseBrief, type Page } from "../api";
import { VIEW_COLORS, type SavedView } from "../components/FilterPanel";
import Pile from "../components/Pile";
import DayStrip from "../components/DayStrip";
import { CleanDesk, WeekProgress } from "../components/Progress";
import { useAction, useLoad } from "../components/ui";

const plus = (days: number) => {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return localISO(d);
};

function usePile(params: Record<string, string | number | boolean | undefined>, filter?: (c: CaseBrief) => boolean) {
  const r = useLoad(() => api<Page<CaseBrief>>(`/cases${qs({ size: settings.desk_pile_size, ...params })}`), [JSON.stringify(params)]);
  // один и тот же массив, пока не пришли новые данные, — иначе стопка сбрасывала бы позицию на каждую перерисовку
  const items = useMemo(() => (r.data?.items ?? []).filter(filter ?? (() => true)), [r.data]); // eslint-disable-line react-hooks/exhaustive-deps
  return { items, total: filter ? items.length : r.data?.total ?? 0, loading: r.loading };
}

export default function DeskPage() {
  const { me, stats } = useSession();
  const hot = usePile({ due_before: plus(settings.desk_hot_days), sort: "next_due" });
  const week = usePile({ due_before: plus(settings.desk_week_days), sort: "next_due" },
                       (c) => !!c.next_due && c.next_due > plus(settings.desk_hot_days));
  const conflicts = usePile({ has_conflicts: true, sort: "-conflicts" });
  const mine = usePile({ responsible: me.login, sort: "next_due" });
  const noUid = usePile({ has_uid: false, sort: "-updated_at" });
  const recent = usePile({ sort: "-updated_at" });
  const views = useLoad(() => cachedApi<SavedView[]>("/views"), []);
  const { run } = useAction();
  const removeFromDesk = (v: SavedView) => run(async () => {
    await api(`/views/${v.id}`, { method: "PATCH", json: { on_desk: false } });
    invalidateCache("/views");
    views.reload();
  }, `«${v.name}» убрана со стола (подборка осталась в фильтрах)`);

  const conflictsN = (stats?.values_by_status.conflict ?? 0) + (stats?.values_by_status.appeal_possible ?? 0);
  const hello = new Date().getHours() < 12 ? "Доброе утро" : new Date().getHours() < 18 ? "Добрый день" : "Добрый вечер";

  return (
    <>
      <Topbar title="Стол" sub={<>{hello}, {me.full_name || me.login}. Дела разложены по стопкам — листайте или разложите пасьянсом. Свою стопку можно собрать фильтрами в <Link to="/cases">«Делах»</Link> → «Сохранить подборку».</>} />
      <div className="desk-top">
        <DayStrip />
        <CleanDesk />
        <WeekProgress />
      </div>
      <div className="ribbon slim">
        <Link to="/cases"><b>{stats?.cases ?? "—"}</b> дел · с УИД {stats?.cases_with_uid ?? "—"}</Link>
        <Link to="/documents?unlinked=1"><b>{stats?.documents ?? "—"}</b> документов · без дела {stats?.documents_unlinked ?? "—"}</Link>
        <Link to="/conflicts"><b>{conflictsN}</b> конфликтов источников</Link>
      </div>
      <div className="stacks">
        {(views.data ?? []).filter((v) => v.on_desk).map((v) => (
          <ViewPile key={v.id} view={v} onRemove={() => removeFromDesk(v)} />
        ))}
        <Pile title="Горят сроки" color="var(--seal)" {...hot} empty="Сроков, истекающих в ближайшие 3 дня, нет" />
        <Pile title="Сроки на неделю" color="var(--ochre)" {...week} empty="На ближайшие 10 дней сроков нет" />
        <Pile title="Конфликты на разбор" color="var(--violet)" {...conflicts} empty="Источники ни в чём не расходятся" />
        <Pile title="Мои дела" color="var(--ink)" {...mine} empty="Вы ещё не назначены ответственным ни по одному делу — это делается в карточке дела" />
        <Pile title="Без УИД" color="var(--ochre)" {...noUid} empty="У всех дел есть УИД" />
        <Pile title="Недавно изменённые" color="var(--ok)" {...recent} empty="Дел пока нет" />
      </div>
    </>
  );
}

/** Стопка из сохранённой подборки фильтров. */
function ViewPile({ view, onRemove }: { view: SavedView; onRemove: () => void }) {
  const r = useLoad(() => api<Page<CaseBrief>>(`/cases?${view.params}${view.params ? "&" : ""}size=${settings.desk_pile_size}&sort=next_due`), [view.params]);
  return (
    <div className="view-pile">
      <Pile title={view.name} color={VIEW_COLORS[view.color] ?? "var(--ink)"} items={r.data?.items ?? []}
            total={r.data?.total ?? 0} loading={r.loading} empty="По фильтрам подборки дел нет" />
      <div className="view-pile-actions">
        <Link to={`/${view.page}?${view.params}`} className="small">открыть с фильтрами</Link>
        <button className="link small muted" onClick={onRemove}>убрать со стола</button>
      </div>
    </div>
  );
}
