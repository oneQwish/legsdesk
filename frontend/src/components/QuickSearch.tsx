import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, qs, shortCourt, type CaseBrief, type Page } from "../api";
import { Modal } from "./overlay";

/** Быстрый переход к делу по номеру, УИД, истцу или договору (Ctrl+K / «/»). */
export default function QuickSearch({ onClose }: { onClose: () => void }) {
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [items, setItems] = useState<CaseBrief[]>([]);
  const [sel, setSel] = useState(0);

  useEffect(() => {
    if (q.trim().length < 2) {
      setItems([]);
      return;
    }
    const t = setTimeout(() => {
      api<Page<CaseBrief>>(`/cases${qs({ q, size: 8 })}`).then((p) => {
        setItems(p.items);
        setSel(0);
      }).catch(() => setItems([]));
    }, 200);
    return () => clearTimeout(t);
  }, [q]);

  const go = (c: CaseBrief | undefined) => {
    if (!c) return;
    onClose();
    nav(`/cases/${c.id}`);
  };

  return (
    <Modal title="Найти дело" onClose={onClose} width={620}>
      <input className="search-big" placeholder="Номер (2-…, М-…), УИД, фамилия истца, договор" value={q}
             onChange={(e) => setQ(e.target.value)}
             onKeyDown={(e) => {
               if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, items.length - 1)); }
               if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
               if (e.key === "Enter") go(items[sel]);
             }} />
      <div style={{ marginTop: 8 }}>
        {items.map((c, i) => (
          <div key={c.id} className={`search-hit ${i === sel ? "on" : ""}`} onMouseEnter={() => setSel(i)} onClick={() => go(c)}>
            <div className="row">
              <b>{c.case_number || "без номера"}</b>
              <span className="mono muted small">{c.uid}</span>
              <span className="spacer" />
              {c.conflicts > 0 && <span className="badge conflict">{c.conflicts}</span>}
            </div>
            <div className="small">{c.plaintiffs} <span className="muted">· {shortCourt(c.court_name)}</span></div>
          </div>
        ))}
        {q.trim().length >= 2 && items.length === 0 && <div className="muted small" style={{ padding: 8 }}>Ничего не найдено</div>}
        {q.trim().length < 2 && <div className="muted small" style={{ padding: 8 }}><kbd>↑</kbd> <kbd>↓</kbd> выбор, <kbd>Enter</kbd> открыть, <kbd>Esc</kbd> закрыть</div>}
      </div>
    </Modal>
  );
}
