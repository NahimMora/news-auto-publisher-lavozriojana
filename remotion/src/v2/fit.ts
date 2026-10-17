// Ajuste tipográfico medido con Canvas 2D sobre la fuente real, con soporte
// de ancho (font-stretch) y tracking. Mismo contrato que shared/fitText.ts
// (búsqueda binaria + wrap por palabra), que no se modifica: V1 no conoce el
// eje de ancho y su string de fuente no lo incluye.
import { Stretch, V2_FONT_SANS } from "./tokens";

export interface FitSpec {
  text: string;
  maxWidth: number;
  maxHeight: number;
  min: number;
  max: number;
  weight: number;
  lh: number;
  stretch?: Stretch;
  tracking?: number; // em
  family?: string;
  maxLines?: number;
  uppercase?: boolean;
  italic?: boolean;
}

export interface Fitted {
  lines: string[];
  fontSize: number;
  lineHeight: number;
  height: number;
  widest: number;
  overflow: boolean;
}

let canvas: HTMLCanvasElement | null = null;

function ctxFor(font: string, letterSpacingPx: number): CanvasRenderingContext2D | null {
  if (typeof document === "undefined") return null;
  if (!canvas) canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.font = font;
  // letterSpacing existe en Chromium (el renderer de Remotion); si faltara,
  // se compensa abajo sumando tracking por carácter.
  const anyCtx = ctx as unknown as { letterSpacing?: string };
  if ("letterSpacing" in anyCtx) anyCtx.letterSpacing = `${letterSpacingPx}px`;
  return ctx;
}

export function fontString(size: number, weight: number, stretch: Stretch = "normal", family = V2_FONT_SANS, italic = false): string {
  return `${italic ? "italic " : ""}${weight} ${stretch} ${size}px "${family}"`;
}

export function measure(text: string, size: number, spec: Pick<FitSpec, "weight" | "stretch" | "tracking" | "family" | "italic">): number {
  const trackingPx = (spec.tracking ?? 0) * size;
  const ctx = ctxFor(fontString(size, spec.weight, spec.stretch, spec.family, spec.italic), trackingPx);
  if (!ctx) return text.length * size * 0.5;
  const supportsSpacing = "letterSpacing" in (ctx as unknown as Record<string, unknown>);
  const base = ctx.measureText(text).width;
  return supportsSpacing ? base : base + trackingPx * text.length;
}

function wrap(words: string[], size: number, spec: FitSpec): string[] {
  const lines: string[] = [];
  let current = "";
  for (const word of words) {
    const candidate = current ? `${current} ${word}` : word;
    if (!current || measure(candidate, size, spec) <= spec.maxWidth) {
      current = candidate;
    } else {
      lines.push(current);
      current = word;
    }
  }
  if (current) lines.push(current);
  return lines;
}

export function fit(spec: FitSpec): Fitted {
  const source = spec.uppercase ? spec.text.toLocaleUpperCase("es-AR") : spec.text;
  const words = source.split(/\s+/).filter(Boolean);
  let lo = spec.min;
  let hi = spec.max;
  let best: { size: number; lines: string[] } | null = null;
  while (lo <= hi) {
    const mid = Math.floor((lo + hi) / 2);
    const lines = wrap(words, mid, spec);
    const widest = Math.max(0, ...lines.map((l) => measure(l, mid, spec)));
    const height = lines.length * mid * spec.lh;
    const okLines = spec.maxLines ? lines.length <= spec.maxLines : true;
    if (height <= spec.maxHeight && okLines && widest <= spec.maxWidth + 0.5) {
      best = { size: mid, lines };
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  const overflow = best === null;
  const size = best ? best.size : spec.min;
  const lines = best ? best.lines : wrap(words, size, spec);
  const widest = Math.max(0, ...lines.map((l) => measure(l, size, spec)));
  return { lines, fontSize: size, lineHeight: size * spec.lh, height: lines.length * size * spec.lh, widest, overflow };
}
