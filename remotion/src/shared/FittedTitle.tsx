import React from "react";
import { escapeRegExp } from "./HighlightedTitle";
import { FitTextOptions, fitText } from "./fitText";

// fitText.ts wrapea por PALABRA COMPLETA delimitada por espacios
// (text.split(/\s+/)). El resaltado tiene que usar EXACTAMENTE la misma
// tokenización — si en cambio se resalta por fragmento de regex y después
// se separa cada fragmento por espacios (como hace
// utils/premium_renderer.py en Python), un término que hace match en medio
// de una palabra con puntuación pegada ("end-to-end:", sin espacio antes
// de los ":") genera DOS tokens para esa única palabra. Como
// assignWordsToLines reparte tokens por CANTIDAD (no por contenido), ese
// token de más corre el resto de la cola y desplaza palabras a la línea
// equivocada — se vio en smoke test manual como un ":" solo en su propia
// línea y el resto del título recortado fuera del lienzo.
//
// Por eso acá se resalta la PALABRA COMPLETA (con su puntuación pegada) si
// el término aparece en cualquier parte de ella — un token por palabra,
// siempre, igual que fitText.ts — en vez de resaltar sólo la subcadena
// exacta que matchea.
type FlaggedWord = { value: string; highlight: boolean };

function flagWords(text: string, terms: string[]): FlaggedWord[] {
  const words = text.split(/\s+/).filter(Boolean);
  const cleaned = (terms || []).map((t) => t.trim()).filter(Boolean);
  if (cleaned.length === 0) {
    return words.map((value) => ({ value, highlight: false }));
  }
  const pattern = cleaned.map(escapeRegExp).join("|");
  const regex = new RegExp(`\\b(?:${pattern})\\b`, "iu");
  return words.map((value) => ({ value, highlight: regex.test(value) }));
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
// resaltado de términos, usado por las composiciones still nuevas
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
  align?: "left" | "center";
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
  onFit,
  ...fitOpts
}) => {
  const result = fitText({ text, ...fitOpts });
  if (onFit) onFit({ overflow: result.overflow, fontSize: result.fontSize });

  const flagged = flagWords(text, highlightTerms || []);
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
