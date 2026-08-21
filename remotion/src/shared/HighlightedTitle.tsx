import React from "react";

// Componente compartido: resalta 1-3 términos dentro de un título,
// preservando tildes/mayúsculas del texto original y con coincidencia de
// palabra completa (mismo contrato que utils/premium_renderer.py en
// Python — ver docs/DECISIONS.md "Palabras clave destacadas").
//
// Contrato: { title, highlight_terms }. Si highlightTerms está vacío,
// renderiza el título normal sin romper el wrapping existente.
//
// Usado hoy por Main.tsx (Reels) con wrapping implícito del navegador. Las
// composiciones still nuevas (PremiumSlide, AutomaticInstagramCard) usan
// `FittedTitle.tsx`, que agrega auto-fit/overflow medido con Canvas 2D sin
// tocar este contrato ni arriesgar el video ya estable — ver
// docs/DECISIONS.md "Editorial Cinemática Riojana".

export type HighlightedTitleProps = {
  text: string;
  highlightTerms?: string[];
  color: string;
  highlightColor: string;
  style?: React.CSSProperties;
};

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function splitWithHighlights(
  text: string,
  terms: string[],
): { value: string; highlight: boolean }[] {
  const cleaned = (terms || []).map((t) => t.trim()).filter(Boolean);
  if (cleaned.length === 0) {
    return [{ value: text, highlight: false }];
  }
  const pattern = cleaned.map(escapeRegExp).join("|");
  const regex = new RegExp(`\\b(${pattern})\\b`, "giu");
  const parts: { value: string; highlight: boolean }[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ value: text.slice(lastIndex, match.index), highlight: false });
    }
    parts.push({ value: match[0], highlight: true });
    lastIndex = match.index + match[0].length;
    if (match.index === regex.lastIndex) regex.lastIndex += 1; // evita loop infinito
  }
  if (lastIndex < text.length) {
    parts.push({ value: text.slice(lastIndex), highlight: false });
  }
  return parts.length ? parts : [{ value: text, highlight: false }];
}

export const HighlightedTitle: React.FC<HighlightedTitleProps> = ({
  text,
  highlightTerms,
  color,
  highlightColor,
  style,
}) => {
  const parts = splitWithHighlights(text, highlightTerms || []);
  return (
    <div style={style}>
      {parts.map((part, index) => (
        <span key={index} style={{ color: part.highlight ? highlightColor : color }}>
          {part.value}
        </span>
      ))}
    </div>
  );
};

export { escapeRegExp, splitWithHighlights };
