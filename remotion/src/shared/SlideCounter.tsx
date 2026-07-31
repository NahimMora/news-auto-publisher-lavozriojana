import React from "react";
import { FONT_DISPLAY, WEIGHT, WHITE } from "./designSystem";

// Numeración de slide del carrusel premium — mismo tratamiento tipográfico
// en toda la pieza para dar sensación de ritmo/continuidad entre slides.
export const SlideCounter: React.FC<{ index: number; total: number; accent: string }> = ({
  index,
  total,
  accent,
}) => {
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 3, fontFamily: `"${FONT_DISPLAY}"` }}>
      <span style={{ fontWeight: WEIGHT.black, fontSize: 27, color: WHITE }}>{index}</span>
      <span style={{ fontWeight: WEIGHT.medium, fontSize: 21, color: accent }}>/{total}</span>
    </div>
  );
};
