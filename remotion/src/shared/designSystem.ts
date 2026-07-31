// Sistema de diseño "Editorial Cinemática Riojana" — tokens compartidos entre
// PremiumSlide y AutomaticInstagramCard. Un solo lugar para tipografía, escala,
// spacing/safe areas, modos de composición y gradientes por capas, en vez de
// números mágicos repetidos por composición.
//
// Paleta de marca: se reimporta de ../constants.ts (fuente única, ver
// docs/DECISIONS.md "Paleta oficial sin dorado") — este archivo no declara
// colores nuevos, sólo los organiza en tokens de uso.
import { AZUL, BORDO, NEGRO, ROJO, WHITE } from "../constants";

// ── Tipografía ───────────────────────────────────────────────────────────
// Archivo (variable, wght 100-900) para todo el sistema; Source Serif 4
// (variable, wght 200-900) como acento de contraste sólo en modo Editorial.
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
  pad: 64, // margen editorial estándar a los bordes
  padTight: 48,
  footerH: 84,
  accentBarW: 12,
  badgeRadius: 999,
  cardRadius: 14,
};

// ── Modos de composición ─────────────────────────────────────────────────
export type Mode = "cronica" | "editorial" | "datos";

export interface ModeTokens {
  id: Mode;
  label: string;
  accent: string;
  accentSoft: string;
  ink: string; // negro con tinte sutil de marca, usado como fondo base
  useSerifAccent: boolean;
  photoFilter: string; // tratamiento fotográfico (contraste/saturación)
  scrimStyle: "dramatic" | "airy" | "structured";
}

export const MODES: Record<Mode, ModeTokens> = {
  cronica: {
    id: "cronica",
    label: "Crónica",
    accent: ROJO,
    accentSoft: "#7A0B0B",
    ink: "#130505",
    useSerifAccent: false,
    photoFilter: "contrast(1.14) saturate(1.1) brightness(0.97)",
    scrimStyle: "dramatic",
  },
  editorial: {
    id: "editorial",
    label: "Editorial",
    accent: AZUL,
    accentSoft: BORDO,
    ink: "#0A0D13",
    useSerifAccent: true,
    photoFilter: "contrast(1.02) saturate(0.95)",
    scrimStyle: "airy",
  },
  datos: {
    id: "datos",
    label: "Datos",
    accent: AZUL,
    accentSoft: "#163A57",
    ink: "#070B10",
    useSerifAccent: false,
    photoFilter: "contrast(1.06) saturate(0.88) brightness(0.94)",
    scrimStyle: "structured",
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
export const TYPE = {
  eyebrow: { size: 27, weight: WEIGHT.bold, tracking: "0.14em" },
  titleCover: { min: 44, max: 76, weight: WEIGHT.black, lineHeightRatio: 1.06, tracking: "-0.01em" },
  titleBody: { min: 34, max: 58, weight: WEIGHT.black, lineHeightRatio: 1.1, tracking: "-0.01em" },
  bodyText: { size: 33, weight: WEIGHT.regular, lineHeightRatio: 1.42 },
  quote: { min: 32, max: 50, weight: WEIGHT.medium, lineHeightRatio: 1.32 },
  number: { size: 220, weight: WEIGHT.black, lineHeightRatio: 0.9 },
  caption: { size: 25, weight: WEIGHT.medium, lineHeightRatio: 1.3 },
  footer: { size: 25, weight: WEIGHT.bold },
};

// ── Helpers de color ─────────────────────────────────────────────────────
export function hexToRgba(hex: string, alpha: number): string {
  const c = hex.replace("#", "");
  const r = parseInt(c.substring(0, 2), 16);
  const g = parseInt(c.substring(2, 4), 16);
  const b = parseInt(c.substring(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

// ── Gradientes por capas (brief: scrim + color de marca + luz radial + viñeta) ──
export function scrimGradient(mode: ModeTokens): string {
  const strength = mode.scrimStyle === "dramatic" ? 0.94 : mode.scrimStyle === "structured" ? 0.88 : 0.82;
  return `linear-gradient(180deg, rgba(6,5,6,0) 0%, rgba(8,5,6,0.32) 42%, rgba(6,4,4,${strength}) 100%)`;
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
