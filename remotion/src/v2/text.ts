// Reglas de texto de V2: destacados y caja de oración del titular.
// Todo es determinístico y se apoya SOLO en el texto recibido: nunca se
// inventa una cifra, una frase ni un destacado que no esté en el titular.

export interface Token {
  value: string;
  highlighted: boolean;
}

const norm = (word: string): string =>
  word
    .normalize("NFC")
    .toLocaleLowerCase("es-AR")
    .replace(/^[^\p{L}\p{N}%$]+|[^\p{L}\p{N}%$]+$/gu, "");

// Marca las palabras que forman una frase destacada (máx. 1 por defecto).
// Frases que no aparecen literalmente en el titular se ignoran.
export function tokenize(text: string, phrases: string[], maxPhrases = 1): Token[] {
  const words = text.split(/\s+/).filter(Boolean);
  const normalized = words.map(norm);
  const marked = new Array<boolean>(words.length).fill(false);
  let used = 0;
  for (const candidate of phrases) {
    if (used >= maxPhrases) break;
    const phrase = candidate.split(/\s+/).filter(Boolean).map(norm).filter(Boolean);
    if (!phrase.length) continue;
    for (let start = 0; start <= normalized.length - phrase.length; start += 1) {
      if (!phrase.every((w, o) => normalized[start + o] === w)) continue;
      phrase.forEach((_, o) => {
        marked[start + o] = true;
      });
      used += 1;
      break;
    }
  }
  return words.map((value, i) => ({ value, highlighted: marked[i] }));
}

export function splitByLines(lines: string[], tokens: Token[]): Token[][] {
  let cursor = 0;
  return lines.map((line) => {
    const count = line.split(/\s+/).filter(Boolean).length;
    const slice = tokens.slice(cursor, cursor + count);
    cursor += count;
    return slice;
  });
}

// Titular tal como se muestra. El pipeline manda el título con su caja
// original (nombres propios en mayúscula); si sólo llega en MAYÚSCULAS se
// conserva así: bajarlo a minúsculas rompía los nombres propios
// ("charlotte caniggia").
export function displayTitle(title: string): string {
  return title.replace(/\s+/g, " ").trim();
}

// Versión "oración" de un titular en mayúsculas (sólo para QA/galería: no
// distingue nombres propios).
const KEEP_UPPER = new Set(["AFA", "INDEC", "ANSES", "PAMI", "UNLaR", "UNLAR", "IPV", "EPEC", "FMI", "IA", "ESPN", "TV", "NOA", "VTV", "DNI", "AFIP", "ARCA", "LAM"]);

export function sentenceCase(title: string): string {
  const letters = title.replace(/[^\p{L}]/gu, "");
  if (!letters || letters !== letters.toLocaleUpperCase("es-AR")) return title;
  const lower = title
    .split(/(\s+)/)
    .map((part) => (KEEP_UPPER.has(part.replace(/[^\p{L}]/gu, "")) ? part : part.toLocaleLowerCase("es-AR")))
    .join("");
  return lower.charAt(0).toLocaleUpperCase("es-AR") + lower.slice(1);
}
