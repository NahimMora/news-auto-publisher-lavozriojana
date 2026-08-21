import React from "react";
import { ModeTokens, hexToRgba } from "../designSystem";

// Línea vertical que conecta visualmente una lista de módulos (puntos
// clave, datos). Sin esto, una lista de tarjetas se ve como bloques
// sueltos flotando; con el riel, se lee como una sola narrativa en capas.
//
// Se usa como hijo de un flex row con `alignSelf: stretch` (ver
// KeyPointsSlide en PremiumSlide.tsx): así el riel toma automáticamente el
// alto real de la lista de tarjetas, sin adivinar un `height` fijo que se
// desincroniza apenas cambia la cantidad de líneas de un ítem.
export const StoryRail: React.FC<{ mode: ModeTokens }> = ({ mode }) => (
  <div
    style={{
      width: 2,
      alignSelf: "stretch",
      background: `linear-gradient(180deg, ${hexToRgba(mode.accent, 0.05)} 0%, ${hexToRgba(mode.accent, 0.55)} 12%, ${hexToRgba(
        mode.accent,
        0.55,
      )} 88%, ${hexToRgba(mode.accent, 0.05)} 100%)`,
    }}
  />
);
