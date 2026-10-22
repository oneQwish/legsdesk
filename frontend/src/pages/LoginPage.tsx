import { useState, type FormEvent } from "react";
import { api, type Me } from "../api";

export default function LoginPage({ onLogin }: { onLogin: (m: Me) => void }) {
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/auth/login", { method: "POST", json: { login, password } });
      onLogin(await api<Me>("/auth/me"));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <form className="panel" onSubmit={submit}>
        <div>
          <div className="rail-logo">Ю</div>
          <h1>Рабочее место юриста</h1>
          <div className="muted">Вход с доменной учётной записью</div>
        </div>
        <label className="field">
          Логин (DOMAIN\login или login)
          <input autoFocus value={login} onChange={(e) => setLogin(e.target.value)} autoComplete="username" />
        </label>
        <label className="field">
          Пароль
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
        </label>
        {error && <div className="error">{error}</div>}
        <button className="primary" disabled={busy || !login || !password}>
          {busy ? "Вход…" : "Войти"}
        </button>
      </form>
    </div>
  );
}
