import React from "react";
import { FittedTitle } from "../FittedTitle";
import { FONT_DISPLAY, FONT_SERIF, ModeTokens, TYPE, WEIGHT, WHITE, hexToRgba } from "../designSystem";

// Titular con composición adaptable: regla editorial + deck opcional +
// título con auto-fit real (FittedTitle/fitText.ts). El tamaño de fuente
// nunca es el primer recurso para "hacer entrar" un título largo — quien
// arma el slide decide antes cuántas líneas/qué layout permitir; acá sólo
// se expone `maxLines`/`maxHeight`/`width` para que ese cambio de
// composición sea explícito en cada slide, no un efecto secundario del
// auto-fit.
export const HeadlineBlock: React.FC<{
  mode: ModeTokens;
  title: string;
  highlightTerms?: string[];
  deck?: string;
  width: number;
  maxHeight: number;
  maxLines?: number;
  size?: "cover" | "body";
  rule?: boolean;
  align?: "left" | "right";
  maxHighlightPhrases?: number;
  fontScale?: number;
  // Permite que una composición con menos alto (p.ej. Publicaciones con
  // foto + footer) baje el piso tipográfico sin alterar la escala Premium
  // del resto de los slides.
  minFontSize?: number;
}> = ({
  mode,
  title,
  highlightTerms,
  deck,
  width,
  maxHeight,
  maxLines,
  size = "cover",
  rule = true,
  align = "left",
  maxHighlightPhrases,
  fontScale = 1,
  minFontSize,
}) => {
  const baseScale = size === "cover" ? TYPE.titleCover : TYPE.titleBody;
  const titleScale = {
    ...baseScale,
    min: minFontSize ?? Math.round(baseScale.min * fontScale),
    max: Math.round(baseScale.max * fontScale),
  };
  // La bajada usa FittedTitle (tamaño fijo, máx. 2 líneas) en vez de un div
  // suelto: así su alto real es determinístico y el presupuesto que se le
  // resta al título (`deckH`) coincide con lo que efectivamente ocupa —
  // antes era un valor fijo (64px) que asumía una sola línea, y una bajada
  // de 2 líneas hacía que el título calculado desbordara el panel.
  const deckFontSize = Math.round(TYPE.deck.min * fontScale);
  const deckLineH = deckFontSize * TYPE.deck.lineHeightRatio;
  const deckH = deck ? deckLineH * 2 + 14 : 0;
  const ruleH = rule ? 24 : 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", width, alignItems: align === "right" ? "flex-end" : "flex-start" }}>
      {rule && <EditorialRule mode={mode} align={align} />}
      {deck ? (
        <div style={{ marginBottom: 14 }}>
          <FittedTitle
            text={deck}
            color={hexToRgba(WHITE, 0.82)}
            highlightColor={hexToRgba(WHITE, 0.82)}
            fontFamily={mode.useSerifAccent ? FONT_SERIF : FONT_DISPLAY}
            fontWeight={mode.useSerifAccent ? WEIGHT.medium : WEIGHT.semibold}
            maxWidth={width}
            maxHeight={deckLineH * 2}
            minFontSize={deckFontSize}
            maxFontSize={deckFontSize}
            lineHeightRatio={TYPE.deck.lineHeightRatio}
            maxLines={2}
            align={align}
          />
        </div>
      ) : null}
      <FittedTitle
        text={title}
        highlightTerms={highlightTerms}
        color={WHITE}
        highlightColor={mode.accent}
        fontFamily={FONT_DISPLAY}
        fontWeight={mode.id === "editorial" ? WEIGHT.bold : WEIGHT.black}
        maxWidth={width}
        maxHeight={Math.max(titleScale.min * titleScale.lineHeightRatio, maxHeight - deckH - ruleH)}
        minFontSize={titleScale.min}
        maxFontSize={titleScale.max}
        lineHeightRatio={titleScale.lineHeightRatio}
        letterSpacing={titleScale.tracking}
        textShadow="0 4px 24px rgba(0,0,0,0.5)"
        maxLines={maxLines}
        align={align}
        maxHighlightPhrases={maxHighlightPhrases}
      />
    </div>
  );
};

export const EditorialRule: React.FC<{ mode: ModeTokens; align?: "left" | "right"; width?: number }> = ({
  mode,
  align = "left",
  width = 72,
}) => (
  <div
    style={{
      width,
      height: 4,
      backgroundColor: mode.accent,
      marginBottom: 20,
      borderRadius: 2,
      alignSelf: align === "right" ? "flex-end" : "flex-start",
    }}
  />
);
