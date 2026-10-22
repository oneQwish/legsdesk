import { useEffect, useState } from "react";
import type { CaseBrief } from "../api";
import CaseCard from "./CaseCard";
import { Icon } from "./icons";

/** Стопка дел: верхняя карточка + «листы» под ней; листать кнопками или колесом, разложить пасьянсом. */
export default function Pile({ title, color, items, total, empty, loading }: {
  title: string;
  color: string;
  items: CaseBrief[];
  total: number;
  empty: string;
  loading?: boolean;
}) {
  const [i, setI] = useState(0);
  const [spread, setSpread] = useState(false);
  useEffect(() => setI(0), [items]);
  const n = items.length;
  const cur = items[Math.min(i, n - 1)];
  const go = (d: number) => n && setI((x) => (x + d + n) % n);

  return (
    <section>
      <div className="pile-head">
        <span className="tone" style={{ background: color }} />
        <h3>{title}</h3>
        <span className="n">{loading ? "…" : total}</span>
      </div>
      {n === 0 ? (
        <div className="pile-empty">{loading ? "Загрузка…" : empty}</div>
      ) : (
        <>
          <div className="pile" onWheel={(e) => { if (Math.abs(e.deltaY) > 20) go(e.deltaY > 0 ? 1 : -1); }}>
            {n > 2 && <div className="ghost-card g2" />}
            {n > 1 && <div className="ghost-card g1" />}
            <CaseCard key={cur.id} c={cur} className="flip-in" />
          </div>
          <div className="pile-ctl">
            <button onClick={() => go(-1)} disabled={n < 2} aria-label="Предыдущее">‹</button>
            <span className="pos">{Math.min(i, n - 1) + 1} из {total}</span>
            <button onClick={() => go(1)} disabled={n < 2} aria-label="Следующее">›</button>
            <span className="spacer" />
            <button className="ghost" onClick={() => setSpread(true)} disabled={n < 2}><Icon name="spread" size={15} /> Разложить</button>
          </div>
        </>
      )}
      {spread && <Spread title={title} color={color} items={items} total={total} onClose={() => setSpread(false)} />}
    </section>
  );
}

/** Разложенная стопка: карточки «раздаются» на стол с лёгким поворотом. */
export function Spread({ title, color, items, total, onClose }: { title: string; color: string; items: CaseBrief[]; total: number; onClose: () => void }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <div className="spread-back" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="spread" onClick={(e) => e.target === e.currentTarget && onClose()}>
        <div className="row">
          <span className="tone" style={{ width: 10, height: 10, borderRadius: "50%", background: color }} />
          <h1>{title}</h1>
          <span className="muted">{items.length < total ? `${items.length} из ${total}` : total}</span>
          <span className="spacer" />
          <button onClick={onClose}><Icon name="pile" size={15} /> Собрать в стопку <kbd>Esc</kbd></button>
        </div>
        <div className="spread-grid">
          {items.map((c, k) => (
            <CaseCard key={c.id} c={c} style={{
              animationDelay: `${Math.min(k, 30) * 28}ms`,
              ["--rot" as string]: `${((c.id * 37) % 7) - 3}deg`,
              ["--dx" as string]: `${((c.id * 53) % 60) - 30}px`,
            }} />
          ))}
        </div>
      </div>
    </div>
  );
}
