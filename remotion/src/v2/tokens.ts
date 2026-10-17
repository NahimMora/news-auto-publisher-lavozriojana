// La Voz Riojana — Visual System V2: tokens compartidos por EditorialReelV2,
// AutomaticInstagramCardV2 y FacebookOgCardV2.
//
// V2 NO modifica los tokens de V1 (shared/designSystem.ts, constants.ts):
// importa los colores corporativos desde constants.ts sólo para leerlos y
// define su propia escala, retícula, safe areas y presets. Ver
// docs/design/VISUAL_SYSTEM_V2.md.
import { AZUL, BORDO, ROJO, WHITE } from "../constants";

// ── Familias ─────────────────────────────────────────────────────────────
// Se registran con nombres propios (ver v2/fonts.ts) para declarar el eje
// de ancho (wdth 62–125) de Archivo sin alterar la carga de V1. El ancho
// condensado es la firma tipográfica de V2: titulares más grandes y con más
// carácter en el mismo espacio, sin cambiar de familia ni de marca.
export const V2_FONT_SANS = "LVR Archivo";
export const V2_FONT_SERIF = "LVR Serif";

export type Stretch = "condensed" | "semi-condensed" | "normal";

// ── Color ────────────────────────────────────────────────────────────────
// Corporativos sin cambios (#B30000, #2F6FB0, #0B2F4F). Se agregan dos
// neutros de soporte: tinta (fondo oscuro con un leve tinte azul de marca) y
// papel (fondo claro cálido, referencia al diario impreso).
export const C = {
  red: ROJO,
  blue: AZUL,
  navy: "#0B2F4F",
  bordo: BORDO,
  ink: "#0A0D12",
  ink2: "#121821",
  paper: "#F2EEE6",
  paperLine: "#D9D2C4",
  paperInk: "#14171C",
  paperMute: "#5B5F66",
  white: WHITE,
} as const;

export interface SectionStyle {
  key: string;
  label: string; // etiqueta visible (con tilde)
  accent: string; // reglas, marcas y caja de destaque
  field: string; // bloque sólido de sección (fondo de etiqueta / poster)
  // Tono "duro" de la sección: policiales y urgentes van sobre tinta;
  // el resto sobre papel en las piezas estáticas.
  tone: "ink" | "paper";
}

const SECTION_TABLE: Record<string, Omit<SectionStyle, "key">> = {
  policiales: { label: "Policiales", accent: C.red, field: C.red, tone: "ink" },
  locales: { label: "La Rioja", accent: C.red, field: C.red, tone: "paper" },
  interior: { label: "Interior", accent: C.blue, field: C.navy, tone: "paper" },
  sociedad: { label: "Sociedad", accent: C.blue, field: C.navy, tone: "paper" },
  economia: { label: "Economía", accent: C.blue, field: C.navy, tone: "paper" },
  salud: { label: "Salud", accent: C.blue, field: C.navy, tone: "paper" },
  educacion: { label: "Educación", accent: C.blue, field: C.navy, tone: "paper" },
  deportes: { label: "Deportes", accent: C.blue, field: C.blue, tone: "ink" },
  cultura: { label: "Cultura", accent: C.red, field: C.bordo, tone: "paper" },
  espectaculos: { label: "Espectáculos", accent: C.red, field: C.bordo, tone: "ink" },
  politica: { label: "Política", accent: C.blue, field: C.navy, tone: "paper" },
};

export function normalizeSectionKey(seccion: string): string {
  return (seccion || "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .trim();
}

export function sectionStyle(seccion: string): SectionStyle {
  const key = normalizeSectionKey(seccion);
  const found = SECTION_TABLE[key];
  if (found) return { key, ...found };
  const label = (seccion || "").trim();
  return { key: key || "general", label: label || "Noticias", accent: C.red, field: C.red, tone: "paper" };
}

export function rgba(hex: string, alpha: number): string {
  const c = hex.replace("#", "");
  const r = parseInt(c.substring(0, 2), 16);
  const g = parseInt(c.substring(2, 4), 16);
  const b = parseInt(c.substring(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

// ── Formatos y safe areas ────────────────────────────────────────────────
// Reel: Instagram/Facebook pintan su UI arriba (~220 px) y abajo (~380 px,
// caption + usuario) y botones a la derecha (~140 px). V2 mantiene todo el
// texto propio dentro de esta zona — V1 ubicaba el footer en 1784 px, debajo
// de la UI de la plataforma.
export const REEL = {
  w: 1080,
  h: 1920,
  fps: 30,
  safe: { top: 210, bottom: 1540, left: 64, right: 940 },
  outroFrames: 54,
} as const;

export const IG = { w: 1080, h: 1350, margin: 64 } as const;
export const OG = { w: 1200, h: 630, margin: 48 } as const;

// ── Escala tipográfica ───────────────────────────────────────────────────
// Rangos de auto-ajuste por formato. El ajuste mide con la fuente real
// (v2/fit.ts) y nunca baja de `min`: si no entra, cambia la composición.
export const TYPE = {
  reelCompact: { min: 50, max: 70, lh: 1.0, tracking: -0.005, weight: 800, stretch: "semi-condensed" as Stretch },
  cardHeadline: { min: 52, max: 92, lh: 1.0, tracking: -0.01, weight: 800, stretch: "semi-condensed" as Stretch },
  ogHeadline: { min: 40, max: 66, lh: 1.0, tracking: -0.005, weight: 800, stretch: "semi-condensed" as Stretch },
  deck: { size: 32, lh: 1.28, weight: 500 },
  label: { size: 24, tracking: 0.16, weight: 800 },
} as const;

// ── Movimiento ───────────────────────────────────────────────────────────
// Tiempos en frames a 30 fps. Cada hook combina presets distintos: entradas
// rápidas, asentamientos lentos y pausas — nunca todo con el mismo timing.
export const TIMING = {
  hookHold: 50, // fin del estado A
  layoutMorph: 22, // duración del estado B
  minCompactHold: 120, // titular compacto visible al menos 4 s
} as const;
