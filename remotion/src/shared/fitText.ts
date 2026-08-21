// Auto-fit + wrap de texto medido con Canvas 2D real (Remotion renderiza en
// Chromium headless de verdad, measureText está disponible en render-time).
// Replica el contrato de layout/image_generator.py::_fit_title y
// utils/premium_renderer.py::_wrap_text: búsqueda binaria de tamaño de
// fuente entre un mínimo y máximo, wrap por palabra completa, y devuelve
// overflow=true cuando ni el tamaño mínimo evita que el bloque exceda el
// alto disponible (cierra docs/KNOWN_ISSUES.md #70).

export interface FitTextResult {
  lines: string[];
  fontSize: number;
  lineHeightPx: number;
  overflow: boolean;
}

export interface FitTextOptions {
  text: string;
  maxWidth: number;
  maxHeight: number;
  minFontSize: number;
  maxFontSize: number;
  fontFamily: string;
  fontWeight: number;
  lineHeightRatio?: number;
  maxLines?: number;
}

let measureCanvas: HTMLCanvasElement | null = null;

function measureWidth(text: string, font: string): number {
  if (typeof document === "undefined") return text.length * 10;
  if (!measureCanvas) measureCanvas = document.createElement("canvas");
  const ctx = measureCanvas.getContext("2d");
  if (!ctx) return text.length * 10;
  ctx.font = font;
  return ctx.measureText(text).width;
}

// Corta una palabra SIN espacios (identificador, URL, hashtag largo) a
// nivel de carácter cuando ella sola ya excede maxWidth — el wrap por
// palabra completa no tiene forma de partirla, y sin esto el texto se
// desbordaría del lienzo pase lo que pase con el tamaño de fuente (bug
// real detectado en smoke test manual con un título técnico de prueba).
function breakLongWord(word: string, font: string, maxWidth: number): string[] {
  const chunks: string[] = [];
  let current = "";
  for (const ch of word) {
    const candidate = current + ch;
    if (measureWidth(candidate, font) <= maxWidth || !current) {
      current = candidate;
    } else {
      chunks.push(current);
      current = ch;
    }
  }
  if (current) chunks.push(current);
  return chunks.length ? chunks : [word];
}

function wrapAtSize(
  text: string,
  fontSize: number,
  fontFamily: string,
  fontWeight: number,
  maxWidth: number,
): string[] {
  const font = `${fontWeight} ${fontSize}px "${fontFamily}"`;
  const words = text.split(/\s+/).filter(Boolean);
  if (words.length === 0) return [""];
  const lines: string[] = [];
  let current = "";
  for (const word of words) {
    if (measureWidth(word, font) > maxWidth) {
      if (current) {
        lines.push(current);
        current = "";
      }
      const chunks = breakLongWord(word, font, maxWidth);
      for (let i = 0; i < chunks.length - 1; i += 1) lines.push(chunks[i]);
      current = chunks[chunks.length - 1] || "";
      continue;
    }
    const candidate = current ? `${current} ${word}` : word;
    if (measureWidth(candidate, font) <= maxWidth || !current) {
      current = candidate;
    } else {
      lines.push(current);
      current = word;
    }
  }
  if (current) lines.push(current);
  return lines.length ? lines : [""];
}

export function fitText(opts: FitTextOptions): FitTextResult {
  const {
    text,
    maxWidth,
    maxHeight,
    minFontSize,
    maxFontSize,
    fontFamily,
    fontWeight,
    lineHeightRatio = 1.18,
    maxLines,
  } = opts;

  let lo = minFontSize;
  let hi = maxFontSize;
  let best = { fontSize: minFontSize, lines: wrapAtSize(text, minFontSize, fontFamily, fontWeight, maxWidth) };

  while (lo <= hi) {
    const mid = Math.floor((lo + hi) / 2);
    const lines = wrapAtSize(text, mid, fontFamily, fontWeight, maxWidth);
    const blockHeight = lines.length * mid * lineHeightRatio;
    const fitsLines = maxLines ? lines.length <= maxLines : true;
    if (blockHeight <= maxHeight && fitsLines) {
      best = { fontSize: mid, lines };
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }

  let lines = best.lines;
  if (maxLines && lines.length > maxLines) {
    lines = lines.slice(0, maxLines);
    const last = lines[maxLines - 1] ?? "";
    lines[maxLines - 1] = `${last.replace(/[\s.,;:]+$/, "")}…`;
  }

  const blockHeight = lines.length * best.fontSize * lineHeightRatio;
  const overflow = blockHeight > maxHeight + 0.5 || (maxLines ? best.lines.length > maxLines : false);

  return {
    lines,
    fontSize: best.fontSize,
    lineHeightPx: best.fontSize * lineHeightRatio,
    overflow,
  };
}
