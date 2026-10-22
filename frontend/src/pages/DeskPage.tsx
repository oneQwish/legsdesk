import { Link } from "react-router-dom";
import { Topbar, useSession } from "../App";
import { api, qs, type CaseBrief, type Page } from "../api";
import Pile from "../components/Pile";
import { useLoad } from "../components/ui";

const iso = (d: Date) => d.toISOString().slice(0, 10);
const plus = (days: number) => iso(new Date(Date.now() + days * 86400000));

function usePile(params: Record<string, string | number | boolean | undefined>, filter?: (c: CaseBrief) => boolean) {
  const r = useLoad(() => api<Page<CaseBrief>>(`/cases${qs({ size: 60, ...params })}`), [JSON.stringify(params)]);
  const items = (r.data?.items ?? []).filter(filter ?? (() => true));
  return { items, total: filter ? items.length : r.data?.total ?? 0, loading: r.loading };
}

export default function DeskPage() {
  const { me, stats } = useSession();
  const hot = usePile({ due_before: plus(3), sort: "next_due" });
  const week = usePile({ due_before: plus(10), sort: "next_due" }, (c) => !!c.next_due && c.next_due > plus(3));
  const conflicts = usePile({ has_conflicts: true, sort: "-conflicts" });
  const mine = usePile({ responsible: me.login, sort: "next_due" });
  const noUid = usePile({ has_uid: false, sort: "-updated_at" });
  const recent = usePile({ sort: "-updated_at" });

  const conflictsN = (stats?.values_by_status.conflict ?? 0) + (stats?.values_by_status.appeal_possible ?? 0);
  const hello = new Date().getHours() < 12 ? "Доброе утро" : new Date().getHours() < 18 ? "Добрый день" : "Добрый вечер";

  return (
    <>
      <Topbar title="Стол" sub={`${hello}, ${me.full_name || me.login}. Дела разложены по стопкам — листайте или разложите пасьянсом.`} />
      <div className="ribbon">
        <Link to="/deadlines" className={stats?.deadlines_overdue ? "hot" : ""}><div className="v">{stats?.deadlines_overdue ?? "—"}</div><div className="l">сроков просрочено</div></Link>
        <Link to="/deadlines"><div className="v">{stats?.deadlines_week ?? "—"}</div><div className="l">сроков на 7 дней</div></Link>
        <Link to="/conflicts" className={conflictsN ? "hot" : ""}><div className="v">{conflictsN}</div><div className="l">конфликтов источников</div></Link>
        <Link to="/cases"><div className="v">{stats?.cases ?? "—"}</div><div className="l">дел · с УИД {stats?.cases_with_uid ?? "—"}</div></Link>
        <Link to="/documents?unlinked=1"><div className="v">{stats?.documents ?? "—"}</div><div className="l">документов · без дела {stats?.documents_unlinked ?? "—"}</div></Link>
      </div>
      <div className="stacks">
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
