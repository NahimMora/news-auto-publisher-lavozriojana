import React from "react";
import { FONT_DISPLAY, ModeTokens, WEIGHT, hexToRgba, WHITE } from "../designSystem";

// Señal discreta de continuidad del carrusel — sólo en slides que no son
// el cierre. Un texto chico + flecha, nunca un elemento decorativo grande.
export const SwipeCue: React.FC<{ mode: ModeTokens; scale?: number }> = ({ mode, scale = 1 }) => (
  <div style={{ display: "flex", alignItems: "center", gap: Math.round(8 * scale) }}>
    <span
      style={{
        fontFamily: `"${FONT_DISPLAY}"`,
        fontWeight: WEIGHT.bold,
        fontSize: Math.round(22 * scale),
        letterSpacing: "0.12em",
        color: hexToRgba(WHITE, 0.6),
        textTransform: "uppercase",
      }}
    >
      Deslizá
    </span>
    <span style={{ color: mode.accent, fontSize: Math.round(26 * scale), fontWeight: WEIGHT.black, lineHeight: 1 }}>&rarr;</span>
  </div>
);
