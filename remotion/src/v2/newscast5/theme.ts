// Dirección de arte del Noticiero V5 (La Voz Riojana en video).
//
// Identidad: tinta casi negra con un leve azul de marca, rojo de marca como
// único color protagonista (una cosa roja por cuadro: la palabra clave, el
// dato o el pin), papel hueso para tarjetas (referencia al diario impreso),
// Archivo condensado 900 para titulares y Source Serif itálica para fechas y
// departamentos (la voz "de diario" del medio).
//
// Retícula 1080×1920 (perfil propio, conservador frente a la interfaz de
// Reels; no es una especificación de Meta):
//   y < 200        sólo imagen (barra superior de Instagram)
//   y 228–292      HUD: marca, formato, contador y avance
//   y 312–380      titular contraído (regleta superior)
//   y 430–1000     datos, lugar y mapa
//   y 820–1248     titular grande (tercio inferior)
//   y 1318–1470    subtítulos cinéticos
//   y > 1500       sólo imagen (usuario, caption y audio de Instagram)
//   x > 930        sólo imagen (botones laterales)
import type { CSSProperties } from "react";
import { V2_FONT_SANS, V2_FONT_SERIF } from "../tokens";

export const C5 = {
  ink: "#0A0E14",
  ink2: "#121925",
  ink3: "#1B2433",
  red: "#D7192A",
  redDeep: "#9E0F1C",
  white: "#FFFFFF",
  bone: "#F3EFE6",
  steel: "#9AA4AD",
} as const;

export const L = {
  w: 1080,
  h: 1920,
  x0: 64,
  x1: 930,
  hudY: 228,
  stripY: 312,
  insertTop: 452,
  headBottom: 1248,
  capTop: 1318,
  bandTop: 400,
  bandH: 1150,
  cardW: 940,
  cardCY: 800,
  cardMaxH: 640,
  mapW: 500,
  mapTop: 700,
} as const;

export const CONTENT_W5 = L.x1 - L.x0;
export const SANS = V2_FONT_SANS;
export const SERIF = V2_FONT_SERIF;

// Tratamiento común de fotos: un punto más de contraste y saturación para que
// fotos de distintas fuentes se vean de una misma "cámara".
export const GRADE = "contrast(1.07) saturate(1.06) brightness(0.98)";

export function alpha(hex: string, a: number): string {
  const c = hex.replace("#", "");
  return `rgba(${parseInt(c.slice(0, 2), 16)}, ${parseInt(c.slice(2, 4), 16)}, ${parseInt(c.slice(4, 6), 16)}, ${a})`;
}

export const sans = (size: number, weight = 800, stretch: "condensed" | "semi-condensed" | "normal" = "condensed"): CSSProperties => ({
  fontFamily: `"${SANS}"`,
  fontWeight: weight,
  fontStretch: stretch,
  fontSize: size,
  lineHeight: 1,
  whiteSpace: "nowrap",
});

export const caps5 = (size: number, color: string, weight = 800, tracking = 0.1): CSSProperties => ({
  ...sans(size, weight, "semi-condensed"),
  letterSpacing: `${tracking}em`,
  textTransform: "uppercase",
  color,
});

export const serif = (size: number, color: string, weight = 500): CSSProperties => ({
  fontFamily: `"${SERIF}"`,
  fontStyle: "italic",
  fontWeight: weight,
  fontSize: size,
  lineHeight: 1.1,
  color,
  whiteSpace: "nowrap",
});
