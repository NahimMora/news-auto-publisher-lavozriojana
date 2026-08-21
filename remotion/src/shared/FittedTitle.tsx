import React from "react";
import { FitTextOptions, fitText } from "./fitText";

// fitText.ts wrapea por PALABRA COMPLETA delimitada por espacios
// (text.split(/\s+/)). El resaltado tiene que usar EXACTAMENTE la misma
// tokenización para no desincronizar índices entre líneas y tokens.
type FlaggedWord = { value: string; highlight: boolean };

// Feedback editorial (2026-07-31, segunda ronda): el énfasis tiene que leerse
// como FRASE (2-4 palabras en Publicaciones), no como palabras sueltas — "un comercio en
// pleno centro", no "comercio" y "centro" resaltados por separado sin
// relación visual. `highlightTerms` sigue siendo un array de strings, pero
// ahora cada string se trata como una frase candidata: se busca como
// secuencia contigua de palabras (comparación insensible a mayúsculas/
// puntuación de borde) y, si aparece, TODAS sus palabras se resaltan juntas
// — nunca una palabra suelta de en medio.
function normalizeWord(word: string): string {
  return word
    .toLowerCase()
    .normalize("NFC")
    .replace(/^[.,;:!?¿¡"'«»()\-—–]+|[.,;:!?¿¡"'«»()\-—–]+$/g, "");
}

// Tope de cobertura: como máximo ~30% de las palabras del texto principal
// pueden estar resaltadas, y como máximo `maxPhrases` frases distintas (por
// defecto 2, 1 en portada Crónica — ver CoverSlide). Cada frase candidata
// que no entre en el presupuesto simplemente no se resalta (nunca se
// trunca a la mitad).
function flagPhrases(
  text: string,
  phrases: string[],
  opts: { maxPhrases?: number; maxCoverageRatio?: number } = {},
): FlaggedWord[] {
  const { maxPhrases = 2, maxCoverageRatio = 0.3 } = opts;
  const words = text.split(/\s+/).filter(Boolean);
  const normWords = words.map(normalizeWord);
  const highlighted = new Array(words.length).fill(false);

  const candidates = (phrases || [])
    .map((p) => p.trim())
    .filter(Boolean)
    .map((p) => p.split(/\s+/).filter(Boolean).map(normalizeWord))
    .filter((p) => p.length > 0);

  const maxHighlightedWords = Math.max(1, Math.floor(words.length * maxCoverageRatio));
  let usedPhrases = 0;
  let highlightedCount = 0;

  for (const phraseWords of candidates) {
    if (usedPhrases >= maxPhrases) break;
    // El tope de cobertura (~30%) frena una SEGUNDA frase que infle el
    // resaltado — la primera frase siempre puede intentar matchear, aunque
    // sea una fracción grande de un titular corto (los ejemplos del brief,
    // p.ej. "un comercio en pleno centro" sobre un titular de 10 palabras,
    // superan el 30% y siguen siendo válidos).
    if (usedPhrases > 0 && highlightedCount + phraseWords.length > maxHighlightedWords) continue;
    for (let i = 0; i <= normWords.length - phraseWords.length; i += 1) {
      let alreadyUsed = false;
      let matches = true;
      for (let j = 0; j < phraseWords.length; j += 1) {
        if (highlighted[i + j]) alreadyUsed = true;
        if (normWords[i + j] !== phraseWords[j]) {
          matches = false;
          break;
        }
      }
      if (matches && !alreadyUsed) {
        for (let j = 0; j < phraseWords.length; j += 1) highlighted[i + j] = true;
        highlightedCount += phraseWords.length;
        usedPhrases += 1;
        break;
      }
    }
  }

  return words.map((value, i) => ({ value, highlight: highlighted[i] }));
}

function assignWordsToLines(lines: string[], flagged: FlaggedWord[]): FlaggedWord[][] {
  const totalLineWords = lines.reduce((acc, line) => acc + line.split(/\s+/).filter(Boolean).length, 0);
  if (totalLineWords !== flagged.length) {
    // Tokenización no coincidió (p.ej. espacios múltiples) — se degrada a
    // texto sin resaltar en vez de arriesgar un cruce de índices.
    return lines.map((line) => line.split(/\s+/).filter(Boolean).map((value) => ({ value, highlight: false })));
  }
  let cursor = 0;
  return lines.map((line) => {
    const count = line.split(/\s+/).filter(Boolean).length;
    const tokens = flagged.slice(cursor, cursor + count);
    cursor += count;
    return tokens;
  });
}

// Título con auto-fit real (Canvas 2D measureText, ver fitText.ts) +
// resaltado de frases, usado por las composiciones still nuevas
// (PremiumSlide, AutomaticInstagramCard). A diferencia de HighlightedTitle
// (que Main.tsx sigue usando con wrapping implícito del navegador), este
// componente calcula el wrap/tamaño él mismo para poder detectar overflow
// (cierra docs/KNOWN_ISSUES.md #70) y garantizar que ningún título se corte.

export type FittedTitleProps = Omit<FitTextOptions, "text"> & {
  text: string;
  highlightTerms?: string[];
  color: string;
  highlightColor: string;
  letterSpacing?: string;
  textShadow?: string;
  align?: "left" | "center" | "right";
  // Tope de frases resaltadas simultáneas — 2 por defecto, 1 en la portada
  // de Crónica (ver PremiumSlide.tsx::CoverSlide).
  maxHighlightPhrases?: number;
  onFit?: (result: { overflow: boolean; fontSize: number }) => void;
};

export const FittedTitle: React.FC<FittedTitleProps> = ({
  text,
  highlightTerms,
  color,
  highlightColor,
  letterSpacing,
  textShadow,
  align = "left",
  maxHighlightPhrases,
  onFit,
  ...fitOpts
}) => {
  const result = fitText({ text, ...fitOpts });
  if (onFit) onFit({ overflow: result.overflow, fontSize: result.fontSize });

  const flagged = flagPhrases(text, highlightTerms || [], { maxPhrases: maxHighlightPhrases });
  const lineTokens = assignWordsToLines(result.lines, flagged);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        fontFamily: `"${fitOpts.fontFamily}"`,
        fontWeight: fitOpts.fontWeight,
        fontSize: result.fontSize,
        lineHeight: `${result.lineHeightPx}px`,
        letterSpacing,
        textShadow,
        textAlign: align,
      }}
    >
      {lineTokens.map((tokens, lineIndex) => (
        <div key={lineIndex}>
          {tokens.map((token, tokenIndex) => (
            <React.Fragment key={tokenIndex}>
              <span style={{ color: token.highlight ? highlightColor : color }}>{token.value}</span>
              {tokenIndex < tokens.length - 1 ? " " : ""}
            </React.Fragment>
          ))}
        </div>
      ))}
    </div>
  );
};
