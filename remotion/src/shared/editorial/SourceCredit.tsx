import React from "react";
import { FONT_DISPLAY, WEIGHT, hexToRgba, WHITE } from "../designSystem";

// Crédito visible pero secundario — nunca compite con el titular. Sólo se
// pinta si hay texto real.
export const SourceCredit: React.FC<{ text?: string; scale?: number }> = ({ text, scale = 1 }) =>
  text ? (
    <div
      style={{
        fontFamily: `"${FONT_DISPLAY}"`,
        fontWeight: WEIGHT.medium,
        fontSize: Math.round(22 * scale),
        color: hexToRgba(WHITE, 0.56),
        letterSpacing: "0.01em",
      }}
    >
      {text}
    </div>
  ) : null;
