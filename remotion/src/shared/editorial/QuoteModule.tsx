import React from "react";
import { FittedTitle } from "../FittedTitle";
import { FONT_DISPLAY, FONT_SERIF, ModeTokens, TYPE, WEIGHT, WHITE, hexToRgba } from "../designSystem";

export const QuoteModule: React.FC<{
  mode: ModeTokens;
  text: string;
  highlightTerms?: string[];
  author?: string;
  width: number;
  maxHeight: number;
}> = ({ mode, text, highlightTerms, author, width, maxHeight }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 22, width }}>
    <div
      style={{
        fontFamily: `"${FONT_SERIF}"`,
        fontWeight: WEIGHT.black,
        fontSize: 154,
        color: mode.accent,
        lineHeight: 0.5,
        fontStyle: "italic",
      }}
    >
      &ldquo;
    </div>
    <FittedTitle
      text={text}
      highlightTerms={highlightTerms}
      color={WHITE}
      highlightColor={mode.accent}
      fontFamily={mode.useSerifAccent ? FONT_SERIF : FONT_DISPLAY}
      fontWeight={mode.useSerifAccent ? WEIGHT.semibold : WEIGHT.bold}
      maxWidth={width}
      maxHeight={maxHeight}
      minFontSize={Math.round(TYPE.quote.min * 1.1)}
      maxFontSize={Math.round(TYPE.quote.max * 1.1)}
      lineHeightRatio={TYPE.quote.lineHeightRatio}
      maxLines={7}
    />
    {author ? (
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <div style={{ width: 40, height: 3, backgroundColor: mode.accent, borderRadius: 2 }} />
        <div
          style={{
            fontFamily: `"${FONT_SERIF}"`,
            fontStyle: "italic",
            fontWeight: WEIGHT.semibold,
            fontSize: 34,
            color: hexToRgba(WHITE, 0.86),
          }}
        >
          {author}
        </div>
      </div>
    ) : null}
  </div>
);
