import { createPortal } from "react-dom";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

// --- Модальное окно ----------------------------------------------------------------------------

// Открытые окна по порядку: Escape закрывает только верхнее (окно поверх палитры, палитра поверх страницы)
const stack: number[] = [];
let seq = 0;
export const anyModalOpen = () => stack.length > 0;
const FOCUSABLE = "a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])";

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
    const id = ++seq;
    stack.push(id);
    const opener = document.activeElement as HTMLElement | null;
    const h = (e: KeyboardEvent) => {
      if (stack[stack.length - 1] !== id) return;
      if (e.key === "Escape") {
        e.stopPropagation();
        close.current();
      }
      if (e.key === "Tab" && box.current) {
        // фокус не уходит из окна на страницу под ним
        const els = [...box.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
        if (!els.length) return;
        const first = els[0], last = els[els.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    window.addEventListener("keydown", h);
    // фокус — только при открытии окна
    box.current?.querySelector<HTMLElement>("input, select, textarea, button.primary")?.focus();
    return () => {
      window.removeEventListener("keydown", h);
      stack.splice(stack.indexOf(id), 1);
      opener?.focus?.(); // вернуть фокус туда, откуда окно открыли
    };
  }, []);
  return createPortal(
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal panel" style={{ maxWidth: width }} ref={box} role="dialog" aria-modal="true" aria-label={title}>
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
    if (busy) return;
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
