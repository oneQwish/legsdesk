import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./styles.css";

/** Непойманная ошибка отрисовки — понятное сообщение вместо белого экрана. */
class ErrorBoundary extends React.Component<{ children: React.ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="panel" style={{ maxWidth: 560, margin: "15vh auto", padding: 24 }}>
        <h2 style={{ marginTop: 0 }}>Что-то пошло не так</h2>
        <p>Страница не смогла отобразиться. Обновите её; если повторяется — сообщите администратору, что делали перед этим.</p>
        <p className="muted small">{this.state.error.message}</p>
        <button className="primary" onClick={() => location.reload()}>Обновить страницу</button>
      </div>
    );
  }
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </ErrorBoundary>
  </React.StrictMode>,
);
