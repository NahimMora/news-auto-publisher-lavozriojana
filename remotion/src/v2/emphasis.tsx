// Resaltados en tres niveles para las piezas de servicio, historias y carrusel:
//   1. núcleo: la frase destacada del título (``tokenize``), en color y 900;
//   2. datos: cifras con su unidad, horarios, rangos y fechas de los textos
//      corridos, en negrita;
//   3. resto: más liviano, para que lo anterior se lea primero.
// Sólo marca palabras que ya están en el texto: nunca agrega ni cambia nada.
// ``fit`` mide con el peso más pesado, así que mezclar pesos nunca desborda.
import React from "react";
import { Token, splitByLines, tokenize } from "./text";

const norm = (word: string): string =>
  word
    .normalize("NFC")
    .toLocaleLowerCase("es-AR")
    .replace(/^[^\p{L}\p{N}%$°/]+|[^\p{L}\p{N}%$°/]+$/gu, "");

const UNITS = new Set([
  "km/h", "km", "kilómetros", "mm", "milímetros", "°c", "°", "grados", "%", "por", "metros", "m", "cm",
  "horas", "hora", "h", "hs", "minutos", "min", "años", "días", "pesos", "dólares", "millones", "mil",
  "personas", "heridos", "heridas", "muertos", "víctimas", "detenidos", "casos", "usuarios", "barrios",
]);
const MONTHS = new Set([
  "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "setiembre", "octubre", "noviembre", "diciembre",
]);
const WEEKDAYS = new Set(["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]);
const hasDigit = (w: string) => /\d/.test(w);

// Cifras con unidad ("100 km/h", "15 y 30 mm"), horarios ("de 8 a 13"),
// fechas ("23 de octubre") y montos ("$ 1.535").
export function markData(text: string): Token[] {
  const words = text.split(/\s+/).filter(Boolean);
  const n = words.map(norm);
  // "lunes 19/10", "viernes 23 de octubre": el día va con su fecha.
  const marked = words.map((w, i) => hasDigit(w) || /^\$/.test(w) || (WEEKDAYS.has(n[i]) && hasDigit(words[i + 1] ?? "")));
  for (let i = 1; i < words.length; i += 1) {
    if (!marked[i - 1]) continue;
    // "por ciento" sólo detrás de un número.
    if (UNITS.has(n[i]) && (n[i] !== "por" || n[i + 1] === "ciento")) {
      marked[i] = true;
      if (n[i] === "por") marked[i + 1] = true;
    }
    if (n[i] === "de" && MONTHS.has(n[i + 1] ?? "")) {
      marked[i] = true;
      marked[i + 1] = true;
    }
    // Rangos: "entre 50 y 70", "de 8 a 13".
    if ((n[i] === "y" || n[i] === "a" || n[i] === "al") && hasDigit(words[i + 1] ?? "")) marked[i] = true;
  }
  return words.map((value, i) => ({ value, highlighted: marked[i] }));
}

// Núcleo del título: la frase destacada (si llega) o nada.
export function markPhrase(text: string, phrases: string[]): Token[] {
  return tokenize(text, phrases, 1);
}

export const EmphText: React.FC<{
  lines: string[];
  tokens: Token[];
  base: React.CSSProperties;
  strong: React.CSSProperties;
  lineHeight: number;
}> = ({ lines, tokens, base, strong, lineHeight }) => (
  <div style={{ ...base, lineHeight: `${lineHeight}px` }}>
    {splitByLines(lines, tokens).map((line, i) => (
      <div key={i}>
        {line.map((t, j) => (
          <React.Fragment key={j}>
            {j ? " " : ""}
            <span style={t.highlighted ? strong : undefined}>{t.value}</span>
          </React.Fragment>
        ))}
      </div>
    ))}
  </div>
);
