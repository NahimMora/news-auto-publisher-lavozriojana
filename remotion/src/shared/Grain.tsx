import React from "react";

// Textura muy sutil (grano editorial) vía filtro SVG feTurbulence —
// determinístico (seed fija), sin assets binarios ni costo de red. Nunca
// debe competir con el contenido: opacity baja + mix-blend-mode overlay.
let grainInstanceCounter = 0;

export const Grain: React.FC<{ opacity?: number }> = ({ opacity = 0.035 }) => {
  const filterId = React.useMemo(() => `lvr-grain-${++grainInstanceCounter}`, []);
  return (
    <svg
      style={{
        position: "absolute",
        inset: 0,
        width: "100%",
        height: "100%",
        mixBlendMode: "overlay",
        opacity,
        pointerEvents: "none",
      }}
    >
      <filter id={filterId}>
        <feTurbulence type="fractalNoise" baseFrequency={0.85} numOctaves={2} seed={7} stitchTiles="stitch" />
        <feColorMatrix type="matrix" values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 0.55 0" />
      </filter>
      <rect width="100%" height="100%" filter={`url(#${filterId})`} />
    </svg>
  );
};
