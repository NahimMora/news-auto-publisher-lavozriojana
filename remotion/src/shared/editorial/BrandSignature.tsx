import React from "react";
import { Img, staticFile } from "remotion";
import { FittedTitle } from "../FittedTitle";
import { SocialMark } from "./SocialMark";
import { FONT_DISPLAY, FONT_SERIF, ModeTokens, WEIGHT, WHITE, hexToRgba } from "../designSystem";

// Cierre de marca con peso real — reemplaza "pantalla vacía con dos
// líneas" (queja explícita del brief): logo grande, wordmark, línea de
// síntesis/CTA y el mismo par de íconos sociales que ya usa Main.tsx (Reels),
// para que el cierre del carrusel se sienta parte de la misma familia
// visual que el resto de las piezas de la marca.
export const BrandSignature: React.FC<{ mode: ModeTokens; text: string; width: number }> = ({ mode, text, width }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 31, width }}>
    <div style={{ display: "flex", alignItems: "center", gap: 22 }}>
      <Img src={staticFile("logo.png")} style={{ width: 84, height: 84, objectFit: "contain" }} />
      <div
        style={{
          fontFamily: `"${mode.useSerifAccent ? FONT_SERIF : FONT_DISPLAY}"`,
          fontStyle: mode.useSerifAccent ? "italic" : "normal",
          fontWeight: mode.useSerifAccent ? WEIGHT.semibold : WEIGHT.black,
          fontSize: 57,
          color: WHITE,
          lineHeight: 1.02,
        }}
      >
        La Voz Riojana
      </div>
    </div>

    <div style={{ width: 88, height: 4, backgroundColor: mode.accent, borderRadius: 2 }} />

    <FittedTitle
      text={text}
      color={hexToRgba(WHITE, 0.92)}
      highlightColor={mode.accent}
      fontFamily={FONT_DISPLAY}
      fontWeight={WEIGHT.medium}
      maxWidth={width}
      maxHeight={180}
      minFontSize={34}
      maxFontSize={42}
      lineHeightRatio={1.36}
      maxLines={4}
    />

    <div style={{ display: "flex", alignItems: "center", gap: 18, marginTop: 4 }}>
      <SocialMark file="fb_icon_base.png" />
      <SocialMark file="ig_icon_base.png" />
      <span style={{ fontFamily: `"${FONT_DISPLAY}"`, fontWeight: WEIGHT.bold, fontSize: 30, color: mode.accent }}>
        @lavozriojana
      </span>
    </div>
  </div>
);
