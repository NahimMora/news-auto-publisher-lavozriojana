import React from "react";
import { FittedTitle } from "../FittedTitle";
import { FONT_DISPLAY, ModeTokens, TYPE, WEIGHT, WHITE, hexToRgba } from "../designSystem";

// Módulo numerado con desarrollo real: número + término corto en negrita +
// desarrollo en texto regular, no una línea de bullet diminuta. Acepta un
// string "Término: desarrollo" o "Término — desarrollo" y separa ambas
// partes; si no hay separador, el texto completo se trata como desarrollo
// y el número queda como único acento.
function splitKeyPoint(raw: string): { term: string; body: string } {
  const match = raw.match(/^(.{1,42}?)\s*[:—-]\s+(.+)$/su);
  if (match) return { term: match[1], body: match[2] };
  return { term: "", body: raw };
}

export const KeyPointCard: React.FC<{
  mode: ModeTokens;
  index: number;
  text: string;
  width: number;
  layout?: "horizontal" | "vertical";
}> = ({
  mode,
  index,
  text,
  width,
  layout = "horizontal",
}) => {
  const { term, body } = splitKeyPoint(text);
  const vertical = layout === "vertical";
  const chipSize = vertical ? 72 : 84;
  const gap = vertical ? 18 : 28;
  const textWidth = vertical ? width : width - chipSize - gap;
  return (
    <div style={{ display: "flex", flexDirection: vertical ? "column" : "row", alignItems: "flex-start", gap, width }}>
      <div
        style={{
          minWidth: chipSize,
          height: chipSize,
          borderRadius: mode.grid === "diagonal" ? 999 : 14,
          backgroundColor: mode.grid === "modular" ? hexToRgba(mode.accent, 0.14) : mode.accent,
          border: mode.grid === "modular" ? `1px solid ${hexToRgba(mode.accent, 0.6)}` : undefined,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: `"${FONT_DISPLAY}"`,
          fontWeight: WEIGHT.black,
          fontSize: 36,
          color: mode.grid === "modular" ? mode.accent : WHITE,
        }}
      >
        {String(index + 1).padStart(2, "0")}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, width: textWidth }}>
        {term ? (
          <FittedTitle
            text={term}
            color={mode.accent}
            highlightColor={mode.accent}
            fontFamily={FONT_DISPLAY}
            fontWeight={WEIGHT.bold}
            maxWidth={textWidth}
            maxHeight={vertical ? 92 : 56}
            minFontSize={Math.round(TYPE.keyPointTitle.min * 1.12)}
            maxFontSize={Math.round(TYPE.keyPointTitle.max * 1.12)}
            lineHeightRatio={TYPE.keyPointTitle.lineHeightRatio}
            maxLines={vertical ? 2 : 1}
          />
        ) : null}
        <FittedTitle
          text={body}
          color={WHITE}
          highlightColor={mode.accent}
          fontFamily={FONT_DISPLAY}
          fontWeight={WEIGHT.regular}
          maxWidth={textWidth}
          maxHeight={TYPE.keyPointBody.size * TYPE.keyPointBody.lineHeightRatio * (vertical ? 6 : 4)}
          minFontSize={Math.round(TYPE.keyPointBody.min * 1.12)}
          maxFontSize={Math.round(TYPE.keyPointBody.max * 1.12)}
          lineHeightRatio={TYPE.keyPointBody.lineHeightRatio}
          maxLines={vertical ? 6 : 4}
        />
      </div>
    </div>
  );
};
