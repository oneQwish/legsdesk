// Иконки меню: простые штриховые SVG 18×18, цвет — currentColor
const P = {
  home: "M3 10.5 10 4l7 6.5V17a1 1 0 0 1-1 1h-4v-5H8v5H4a1 1 0 0 1-1-1z",
  cases: "M3 6h14v11H3zM7 6V4h6v2M3 10h14",
  conflicts: "M10 3 2 17h16zM10 8v4M10 14.5v.01",
  deadlines: "M10 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM10 7v4l3 2",
  documents: "M5 2h7l4 4v12H5zM12 2v4h4M8 10h5M8 13h5",
  journal: "M4 4h12v13H4zM7 8h6M7 11h6M7 14h3",
  services: "M8 3v4M12 3v4M6 7h8v3a4 4 0 0 1-8 0zM10 14v4",
  search: "M9 15a6 6 0 1 0 0-12 6 6 0 0 0 0 12zM13.5 13.5 18 18",
  code: "M7 6 3 10l4 4M13 6l4 4-4 4",
  spread: "M3 4h6v6H3zM11 4h6v6h-6zM3 12h6v5H3zM11 12h6v5h-6z",
  pile: "M5 7h10v10H5zM7 4h10v10",
  table: "M3 4h14v12H3zM3 8h14M3 12h14M8 4v12",
  filter: "M3 4h14l-5.5 6.5V16l-3 1.5v-7z",
};

export function Icon({ name, size = 18 }: { name: keyof typeof P; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={P[name]} />
    </svg>
  );
}
