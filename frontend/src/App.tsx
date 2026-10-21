import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api, type Me, type Role, type Stats } from "./api";
import AdminPage from "./pages/AdminPage";
import CasePage from "./pages/CasePage";
import CasesPage from "./pages/CasesPage";
import ConflictsPage from "./pages/ConflictsPage";
import DeadlinesPage from "./pages/DeadlinesPage";
import DocumentPage from "./pages/DocumentPage";
import DocumentsPage from "./pages/DocumentsPage";
import HomePage from "./pages/HomePage";
import JournalPage from "./pages/JournalPage";
import LoginPage from "./pages/LoginPage";

interface Session {
  me: Me;
  can: (role: Role) => boolean;
  stats: Stats | null;
  refreshStats: () => void;
}

const SessionCtx = createContext<Session>(null!);
export const useSession = () => useContext(SessionCtx);

const ORDER: Role[] = ["viewer", "lawyer", "admin"];
const ROLE_LABEL: Record<Role, string> = { viewer: "просмотр", lawyer: "юрист", admin: "администратор" };

export default function App() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [stats, setStats] = useState<Stats | null>(null);

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

  if (me === undefined) return null;
  if (me === null) return <LoginPage onLogin={setMe} />;

  const can = (role: Role) => ORDER.indexOf(me.role) >= ORDER.indexOf(role);
  const conflicts = (stats?.values_by_status.conflict ?? 0) + (stats?.values_by_status.appeal_possible ?? 0);
  const urgent = (stats?.deadlines_overdue ?? 0) + (stats?.deadlines_week ?? 0);

  const logout = async () => {
    await api("/auth/logout", { method: "POST" });
    setMe(null);
  };

  return (
    <SessionCtx.Provider value={{ me, can, stats, refreshStats }}>
      <div className="layout">
        <aside className="sidebar">
          <div className="brand">
            Рабочее место юриста<span>судебные дела дольщиков</span>
          </div>
          <nav className="nav stack" style={{ gap: 2 }}>
            <NavLink to="/" end>Сводка</NavLink>
            <NavLink to="/cases">Дела</NavLink>
            <NavLink to="/conflicts">
              Конфликты {conflicts > 0 && <span className="count">{conflicts}</span>}
            </NavLink>
            <NavLink to="/deadlines">
              Сроки {urgent > 0 && <span className="count">{urgent}</span>}
            </NavLink>
            <NavLink to="/documents">Документы</NavLink>
            <NavLink to="/journal">Журнал</NavLink>
            {can("admin") && <NavLink to="/admin">Сервисы и API</NavLink>}
          </nav>
          <div className="userbox">
            <b>{me.full_name || me.login}</b>
            {ROLE_LABEL[me.role]}
            {me.auth_mode === "dev" && " · dev-режим"}
            <div style={{ marginTop: 6 }}>
              <button className="link" onClick={logout}>Выйти</button>
              {" · "}
              <a href="/api/docs" target="_blank" rel="noreferrer">API</a>
            </div>
          </div>
        </aside>
        <main className="main">
          <Routes>
            <Route path="/" element={<HomePage />} />
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
    </SessionCtx.Provider>
  );
}
