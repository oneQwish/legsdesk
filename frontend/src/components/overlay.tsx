import { createPortal } from "react-dom";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

// --- Модальное окно ----------------------------------------------------------------------------

export function Modal({ title, onClose, children, footer, width = 480 }: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  width?: number;
}) {
  const box = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && close.current();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);
  useEffect(() => {
    // фокус — только при открытии окна
    box.current?.querySelector<HTMLElement>("input, select, textarea, button.primary")?.focus();
  }, []);
  return createPortal(
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal panel" style={{ maxWidth: width }} ref={box} role="dialog" aria-label={title}>
        <div className="modal-head">
          <h2 style={{ margin: 0 }}>{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Закрыть">×</button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

/** Простой диалог «ввести значение»: заменяет window.prompt. */
export function PromptModal({ title, label, initial = "", type = "text", hint, placeholder, okText = "Сохранить", onSubmit, onClose }: {
  title: string;
  label: string;
  initial?: string;
  type?: string;
  hint?: ReactNode;
  placeholder?: string;
  okText?: string;
  onSubmit: (value: string) => Promise<void> | void;
  onClose: () => void;
}) {
  const [v, setV] = useState(initial);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    setErr("");
    try {
      await onSubmit(v);
      onClose();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal title={title} onClose={onClose}
           footer={<><button onClick={onClose}>Отмена</button><button className="primary" disabled={busy} onClick={submit}>{okText}</button></>}>
      <label className="field">
        {label}
        <input type={type} value={v} placeholder={placeholder} onChange={(e) => setV(e.target.value)}
               onKeyDown={(e) => e.key === "Enter" && submit()} />
      </label>
      {hint && <div className="muted small" style={{ marginTop: 8 }}>{hint}</div>}
      {err && <div className="error" style={{ marginTop: 10 }}>{err}</div>}
    </Modal>
  );
}

// --- Уведомления -------------------------------------------------------------------------------

type Toast = { id: number; text: string; kind: "ok" | "err" };
const ToastCtx = createContext<(text: string, kind?: "ok" | "err") => void>(() => undefined);
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((text: string, kind: "ok" | "err" = "ok") => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x, { id, text, kind }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), kind === "err" ? 6000 : 3000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" aria-live="polite">
        {items.map((t) => <div key={t.id} className={`toast ${t.kind}`}>{t.kind === "ok" ? "✓ " : "⚠ "}{t.text}</div>)}
      </div>
    </ToastCtx.Provider>
  );
}
