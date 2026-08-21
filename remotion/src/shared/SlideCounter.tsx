import React from "react";
import { FONT_DISPLAY, WEIGHT, WHITE } from "./designSystem";

// Numeración de slide del carrusel premium — mismo tratamiento tipográfico
// en toda la pieza para dar sensación de ritmo/continuidad entre slides.
export const SlideCounter: React.FC<{ index: number; total: number; accent: string; scale?: number }> = ({
  index,
  total,
  accent,
  scale = 1,
}) => {
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: Math.round(3 * scale), fontFamily: `"${FONT_DISPLAY}"` }}>
      <span style={{ fontWeight: WEIGHT.black, fontSize: Math.round(27 * scale), color: WHITE }}>{index}</span>
      <span style={{ fontWeight: WEIGHT.medium, fontSize: Math.round(21 * scale), color: accent }}>/{total}</span>
    </div>
  );
};
