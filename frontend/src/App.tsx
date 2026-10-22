import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api, type Me, type Role, type Stats } from "./api";
import { Icon } from "./components/icons";
import { ToastProvider } from "./components/overlay";
import QuickSearch from "./components/QuickSearch";
import AdminPage from "./pages/AdminPage";
import CasePage from "./pages/CasePage";
import CasesPage from "./pages/CasesPage";
import ConflictsPage from "./pages/ConflictsPage";
import DeadlinesPage from "./pages/DeadlinesPage";
import DeskPage from "./pages/DeskPage";
import DocumentPage from "./pages/DocumentPage";
import DocumentsPage from "./pages/DocumentsPage";
import JournalPage from "./pages/JournalPage";
import LoginPage from "./pages/LoginPage";

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
        <Icon name="search" size={16} /> Найти дело <kbd>Ctrl K</kbd>
      </button>
    </div>
  );
}

export default function App() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [stats, setStats] = useState<Stats | null>(null);
  const [search, setSearch] = useState(false);

  const refreshStats = useCallback(() => {
    api<Stats>("/stats").then(setStats).catch(() => undefined);
  }, []);

  useEffect(() => {
    api<Me>("/auth/me").then(setMe).catch(() => setMe(null));
    const onUnauthorized = () => setMe(null);
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
      if ((e.key === "k" && (e.ctrlKey || e.metaKey)) || (e.key === "/" && !typing)) {
        e.preventDefault();
        setSearch(true);
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  if (me === undefined) return null;
  if (me === null) return <LoginPage onLogin={setMe} />;

  const can = (role: Role) => ORDER.indexOf(me.role) >= ORDER.indexOf(role);
  const conflicts = (stats?.values_by_status.conflict ?? 0) + (stats?.values_by_status.appeal_possible ?? 0);
  const urgent = (stats?.deadlines_overdue ?? 0) + (stats?.deadlines_week ?? 0);
  const initials = (me.full_name || me.login).split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();

  const logout = async () => {
    await api("/auth/logout", { method: "POST" });
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
            {item("/documents", "documents", "Документы")}
            {item("/journal", "journal", "Журнал")}
            {can("admin") && item("/admin", "services", "Сервисы и API")}
            <div className="rail-bottom">
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
              <Route path="/cases/:id" element={<CasePage />} />
              <Route path="/conflicts" element={<ConflictsPage />} />
              <Route path="/deadlines" element={<DeadlinesPage />} />
              <Route path="/documents" element={<DocumentsPage />} />
              <Route path="/documents/:id" element={<DocumentPage />} />
              <Route path="/journal" element={<JournalPage />} />
              <Route path="/admin" element={can("admin") ? <AdminPage /> : <Navigate to="/" />} />
              <Route path="*" element={<Navigate to="/" />} />
            </Routes>
          </main>
        </div>
        {search && <QuickSearch onClose={() => setSearch(false)} />}
      </ToastProvider>
    </SessionCtx.Provider>
  );
}
