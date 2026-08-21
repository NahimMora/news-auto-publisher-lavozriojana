// Sistema de diseño "Editorial Cinemática Riojana" — v2 (dirección de arte).
// Un solo lugar para tipografía, escala, retícula por modo y color, en vez
// de números mágicos repetidos por composición. v2 corrige el problema de
// fondo de v1: los tres modos compartían layout y sólo cambiaban de color.
// Acá cada modo trae su propia retícula (`grid`) y margen (`pad`), y el kit
// de componentes en `shared/editorial/` lee esos tokens para construir
// estructuras realmente distintas — ver docs/DECISIONS.md.
import { AZUL, BORDO, NEGRO, ROJO, WHITE } from "../constants";

// ── Tipografía ───────────────────────────────────────────────────────────
// Archivo (variable, wght 100-900) para todo el sistema; Source Serif 4
// (variable, wght 200-900) como acento de contraste, con más presencia que
// en v1 (Editorial la usa para deck/cita/firma, no sólo una regla fina).
// Ambas SIL Open Font License, cargadas localmente sin red — ver
// remotion/src/shared/fonts.ts.
export const FONT_DISPLAY = "Archivo";
export const FONT_TEXT = "Archivo";
export const FONT_SERIF = "Source Serif 4";

export const WEIGHT = {
  regular: 400,
  medium: 500,
  semibold: 600,
  bold: 700,
  black: 900,
} as const;

// ── Lienzo y safe areas ──────────────────────────────────────────────────
// PremiumSlide y AutomaticInstagramCard comparten exactamente 1080x1350.
export const CANVAS = { w: 1080, h: 1350 };

export const SAFE = {
  pad: 72, // margen editorial genérico (usar mode.pad cuando el contexto lo tenga)
  padTight: 48,
  footerH: 76,
  badgeRadius: 999,
  cardRadius: 18,
};

// Variante exclusiva del recuadro de sección azul. El destaque dentro del
// título conserva AZUL, más luminoso; separar ambos tokens evita que compitan
// visualmente y mantiene contraste suficiente con la etiqueta blanca.
export const SECTION_BLUE_DARK = "#0B2F4F";

// ── Modos de composición ─────────────────────────────────────────────────
// `grid` es la señal estructural: cada slide type lee `mode.grid` y arma una
// composición distinta (columnas/diagonal/módulos), no sólo un color
// distinto sobre el mismo esqueleto.
export type Mode = "cronica" | "editorial" | "datos";
export type GridFlavor = "diagonal" | "column" | "modular";

export interface ModeTokens {
  id: Mode;
  label: string;
  kicker: string; // texto de marca corto para el masthead (no la sección)
  accent: string;
  accentSoft: string;
  ink: string; // negro con tinte sutil de marca, usado como fondo base
  useSerifAccent: boolean;
  photoFilter: string; // tratamiento fotográfico (contraste/saturación)
  scrimStyle: "dramatic" | "airy" | "structured";
  grid: GridFlavor;
  pad: number; // margen editorial del modo, 64-84px a 1080 de ancho
  textureVariant: "ridge" | "rule" | "grid";
  textureOpacity: number;
}

export const MODES: Record<Mode, ModeTokens> = {
  cronica: {
    id: "cronica",
    label: "Crónica",
    kicker: "La Voz Riojana",
    accent: ROJO,
    accentSoft: "#7A0B0B",
    ink: "#130505",
    useSerifAccent: false,
    photoFilter: "contrast(1.16) saturate(1.14) brightness(0.96)",
    scrimStyle: "dramatic",
    grid: "diagonal",
    pad: 64,
    textureVariant: "ridge",
    textureOpacity: 0.05,
  },
  editorial: {
    id: "editorial",
    label: "Editorial",
    kicker: "La Voz Riojana",
    accent: AZUL,
    accentSoft: BORDO,
    ink: "#0A0D13",
    useSerifAccent: true,
    photoFilter: "contrast(1.02) saturate(0.95)",
    scrimStyle: "airy",
    grid: "column",
    pad: 80,
    textureVariant: "rule",
    textureOpacity: 0.04,
  },
  datos: {
    id: "datos",
    label: "Datos",
    kicker: "La Voz Riojana",
    accent: AZUL,
    accentSoft: "#163A57",
    ink: "#070B10",
    useSerifAccent: false,
    photoFilter: "contrast(1.08) saturate(0.86) brightness(0.93)",
    scrimStyle: "structured",
    grid: "modular",
    pad: 68,
    textureVariant: "grid",
    textureOpacity: 0.05,
  },
};

export function modeFromTemplate(template: string): Mode {
  if (template === "lvr_datos") return "datos";
  if (template === "lvr_visual") return "editorial";
  return "cronica";
}

// Mapeo de sección → modo para cards automáticas. Extiende el criterio de
// remotion/src/shared/sectionColors.ts. Las cards automáticas no traen datos
// numéricos estructurados (a diferencia de los slides number/key_points del
// carrusel premium), así que no reciben modo "datos" — ver
// docs/DECISIONS.md "Editorial Cinemática Riojana".
const SECTION_MODE: Record<string, Mode> = {
  policiales: "cronica",
  locales: "cronica",
  deportes: "cronica",
  politica: "editorial",
  interior: "editorial",
  sociedad: "editorial",
  economia: "editorial",
  salud: "editorial",
  educacion: "editorial",
  cultura: "editorial",
  espectaculos: "editorial",
};

export function modeFromSection(seccion: string): Mode {
  return SECTION_MODE[(seccion || "").toLowerCase().trim()] || "cronica";
}

// ── Escala tipográfica (tamaños en px a 1080x1350, min/max para fitText) ──
// Pisos duros (feedback editorial 2026-07-31, segunda ronda — "ESCALA"):
// titular portada 68, título interior 42, frase principal context 34,
// cuerpo 28, título de key point 28, detalle de key point 25, metadata 22.
// El auto-fit nunca debería tocar estos pisos en el uso normal — si lo
// hace, es señal de que la composición (no el tamaño) tiene que cambiar
// primero.
export const TYPE = {
  kicker: { size: 27, weight: WEIGHT.bold, tracking: "0.15em" }, // piso metadata 22px
  deck: { min: 32, max: 40, weight: WEIGHT.medium, lineHeightRatio: 1.34 },
  titleCover: { min: 68, max: 104, weight: WEIGHT.black, lineHeightRatio: 1.03, tracking: "-0.015em" },
  titleBody: { min: 58, max: 88, weight: WEIGHT.black, lineHeightRatio: 1.06, tracking: "-0.01em" }, // piso "título interior" 42px
  bodyText: { size: 31, min: 28, max: 34, weight: WEIGHT.regular, lineHeightRatio: 1.46 },
  quote: { min: 38, max: 58, weight: WEIGHT.medium, lineHeightRatio: 1.3 },
  number: { size: 264, unit: 48, weight: WEIGHT.black, lineHeightRatio: 0.88 },
  caption: { size: 26, weight: WEIGHT.medium, lineHeightRatio: 1.32 },
  footer: { size: 26, weight: WEIGHT.bold },
  keyPointTitle: { min: 34, max: 50, weight: WEIGHT.bold, lineHeightRatio: 1.12 },
  keyPointBody: { size: 30, min: 28, max: 38, weight: WEIGHT.regular, lineHeightRatio: 1.36 },
};

// ── Helpers de color ─────────────────────────────────────────────────────
export function hexToRgba(hex: string, alpha: number): string {
  const c = hex.replace("#", "");
  const r = parseInt(c.substring(0, 2), 16);
  const g = parseInt(c.substring(2, 4), 16);
  const b = parseInt(c.substring(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

// ── Gradientes por capas (scrim + color de marca + luz radial + viñeta) ──
export function scrimGradient(mode: ModeTokens): string {
  const strength = mode.scrimStyle === "dramatic" ? 0.94 : mode.scrimStyle === "structured" ? 0.88 : 0.8;
  return `linear-gradient(180deg, rgba(6,5,6,0) 0%, rgba(8,5,6,0.3) 40%, rgba(6,4,4,${strength}) 100%)`;
}

export function brandWash(mode: ModeTokens): string {
  return `linear-gradient(158deg, ${hexToRgba(mode.accent, 0.18)} 0%, rgba(0,0,0,0) 52%)`;
}

export function radialLight(): string {
  return "radial-gradient(ellipse 820px 460px at 16% 6%, rgba(255,255,255,0.055) 0%, rgba(255,255,255,0) 62%)";
}

export function vignette(): string {
  return "radial-gradient(ellipse at 50% 45%, rgba(0,0,0,0) 55%, rgba(0,0,0,0.4) 100%)";
}

export function fullScrimStack(mode: ModeTokens): string[] {
  // orden de capas de abajo hacia arriba: viñeta -> luz -> marca -> scrim.
  return [vignette(), radialLight(), brandWash(mode), scrimGradient(mode)];
}

export { AZUL, BORDO, NEGRO, ROJO, WHITE };
