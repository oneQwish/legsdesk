import { createContext, lazy, Suspense, useCallback, useContext, useEffect, useState, type ComponentType, type ReactNode } from "react";
import { NavLink, Navigate, Route, Routes, useParams } from "react-router-dom";
import { api, loadClientSettings, type Me, type Role, type Stats } from "./api";
import { Icon } from "./components/icons";
import { anyModalOpen, ToastProvider } from "./components/overlay";
import QuickSearch from "./components/QuickSearch";
import { Bell } from "./components/Work";
import { AssignmentsPage, HearingsPage } from "./pages/WorkPages";
import CasePage from "./pages/CasePage";
import CasesPage from "./pages/CasesPage";
import ConflictsPage from "./pages/ConflictsPage";
import DeadlinesPage from "./pages/DeadlinesPage";
import DeskPage from "./pages/DeskPage";
import DocumentsPage from "./pages/DocumentsPage";
import JournalPage from "./pages/JournalPage";
import LoginPage from "./pages/LoginPage";

// Редко открываемые страницы грузятся отдельно — первый экран открывается быстрее
const AdminPage = lazy(() => import("./pages/AdminPage"));
const DocumentPage = lazy(() => import("./pages/DocumentPage"));

/** Страница с :id создаётся заново при смене id: иначе при переходе из дела в дело
 *  на миг показывалось бы прежнее дело, а кнопки действовали бы на него. */
function ById({ page: Page }: { page: ComponentType }) {
  const { id } = useParams();
  return <Page key={id} />;
}

interface Session {
  me: Me;
  can: (role: Role) => boolean;
  stats: Stats | null;
  refreshStats: () => void;
  openSearch: () => void;
}

const SessionCtx = createContext<Session>(null!);
export const useSession = () => useContext(SessionCtx);

const ORDER: Role[] = ["viewer", "lawyer", "admin"];
const ROLE_LABEL: Record<Role, string> = { viewer: "просмотр", lawyer: "юрист", admin: "администратор" };

/** Верхний ряд страницы: заголовок, пояснение, действия и быстрый поиск. */
export function Topbar({ title, sub, children }: { title: ReactNode; sub?: ReactNode; children?: ReactNode }) {
  const { openSearch } = useSession();
  return (
    <div className="topbar">
      <div className="title">
        <h1>{title}</h1>
        {sub && <div className="sub">{sub}</div>}
      </div>
      {children}
      <button className="search-btn" onClick={openSearch}>
        <Icon name="search" size={16} /> Дело, судья, команда… <kbd>Ctrl K</kbd>
      </button>
    </div>
  );
}

export default function App() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [stats, setStats] = useState<Stats | null>(null);
  const [search, setSearch] = useState(false);
  const [expired, setExpired] = useState(false);

  const refreshStats = useCallback(() => {
    api<Stats>("/stats").then(setStats).catch(() => undefined);
  }, []);

  useEffect(() => {
    // настройки интерфейса — до первой отрисовки страниц, чтобы пороги и размеры стопок были сразу верными
    api<Me>("/auth/me").then(async (m) => { await loadClientSettings(); setMe(m); }).catch(() => setMe(null));
    // сессия истекла посреди работы: вход поверх страницы, а не вместо неё — недописанный комментарий не пропадёт
    const onUnauthorized = () => setExpired(true);
    window.addEventListener("lawdesk:unauthorized", onUnauthorized);
    return () => window.removeEventListener("lawdesk:unauthorized", onUnauthorized);
  }, []);

  useEffect(() => {
    if (me) refreshStats();
  }, [me, refreshStats]);

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      const typing = t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT";
      if (((e.key === "k" || e.key === "л") && (e.ctrlKey || e.metaKey)) || (e.key === "/" && !typing)) {
        if (anyModalOpen()) return;
        e.preventDefault();
        setSearch(true);
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  if (me === undefined) return null;
  if (me === null) return <LoginPage onLogin={(m) => void loadClientSettings().then(() => setMe(m))} />;

  const can = (role: Role) => ORDER.indexOf(me.role) >= ORDER.indexOf(role);
  const conflicts = (stats?.values_by_status.conflict ?? 0) + (stats?.values_by_status.appeal_possible ?? 0);
  const urgent = (stats?.deadlines_overdue ?? 0) + (stats?.deadlines_week ?? 0);
  const initials = (me.full_name || me.login).split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();

  const logout = async () => {
    await api("/auth/logout", { method: "POST" }).catch(() => undefined); // выйти локально даже без связи
    setMe(null);
  };

  const item = (to: string, icon: Parameters<typeof Icon>[0]["name"], tip: string, count = 0, end = false) => (
    <NavLink to={to} end={end} data-tip={tip} aria-label={tip}>
      <Icon name={icon} size={20} />
      {count > 0 && <span className="dot">{count > 99 ? "99+" : count}</span>}
    </NavLink>
  );

  return (
    <SessionCtx.Provider value={{ me, can, stats, refreshStats, openSearch: () => setSearch(true) }}>
      <ToastProvider>
        <div className="layout">
          <nav className="rail">
            <div className="rail-logo" title="Рабочее место юриста">Ю</div>
            {item("/", "home", "Стол", 0, true)}
            {item("/cases", "cases", "Дела")}
            {item("/conflicts", "conflicts", "Конфликты", conflicts)}
            {item("/deadlines", "deadlines", "Сроки", urgent)}
            {item("/assignments", "assign", "Поручения")}
            {item("/hearings", "hearing", "Заседания")}
            {item("/documents", "documents", "Документы")}
            {item("/journal", "journal", "Журнал")}
            {can("admin") && item("/admin", "services", "Сервисы и API")}
            <div className="rail-bottom">
              <Bell />
              <a href="/api/docs" target="_blank" rel="noreferrer" data-tip="Документация API" aria-label="API"><Icon name="code" size={18} /></a>
              <button onClick={logout} data-tip={`${me.full_name || me.login} · ${ROLE_LABEL[me.role]}${me.auth_mode === "dev" ? " · dev" : ""} — выйти`} aria-label="Выйти">
                <span className="avatar">{initials}</span>
              </button>
            </div>
          </nav>
          <main className="main">
            <Routes>
              <Route path="/" element={<DeskPage />} />
              <Route path="/cases" element={<CasesPage />} />
              <Route path="/cases/:id" element={<ById page={CasePage} />} />
              <Route path="/conflicts" element={<ConflictsPage />} />
              <Route path="/deadlines" element={<DeadlinesPage />} />
              <Route path="/documents" element={<DocumentsPage />} />
              <Route path="/documents/:id" element={<Suspense fallback={null}><ById page={DocumentPage} /></Suspense>} />
              <Route path="/journal" element={<JournalPage />} />
              <Route path="/assignments" element={<AssignmentsPage />} />
              <Route path="/hearings" element={<HearingsPage />} />
              <Route path="/admin" element={can("admin") ? <Suspense fallback={null}><AdminPage /></Suspense> : <Navigate to="/" />} />
              <Route path="*" element={<Navigate to="/" />} />
            </Routes>
          </main>
        </div>
        {search && <QuickSearch onClose={() => setSearch(false)} />}
        {expired && (
          <div className="session-expired" role="dialog" aria-modal="true" aria-label="Сессия истекла">
            <div className="notice" style={{ maxWidth: 420, margin: "0 auto 12px" }}>
              Сессия истекла — войдите снова. Открытая страница и введённый текст сохранятся.
            </div>
            <LoginPage onLogin={(m) => { setMe(m); setExpired(false); }} />
          </div>
        )}
      </ToastProvider>
    </SessionCtx.Provider>
  );
}
