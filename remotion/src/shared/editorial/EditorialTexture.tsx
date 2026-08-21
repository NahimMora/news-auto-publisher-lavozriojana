import React from "react";
import { ModeTokens, hexToRgba } from "../designSystem";

// Textura propia de "Editorial Cinemática Riojana": no es grano stock ni un
// patrón geométrico genérico, sino una silueta de cordón serrano (evoca
// Famatina/Velasco, sin pretender ser topografía real) para Crónica/
// Editorial, y una retícula modular de puntos para Datos. Coordenadas
// fijas (sin Math.random) para que el render sea determinístico entre
// corridas. Vive en una franja acotada (`zone`), nunca como ruido de fondo
// completo — Grain.tsx ya cubre el grano sutil de toda la pieza.
//
// "ridge": silueta de sierra en el borde inferior, coherente con el registro
// fotográfico de Crónica (contraste alto, corte contundente).
// "rule": línea doble fina en el borde superior, registro de edición
// impresa para el modo Editorial.
// "grid": retícula de puntos en el borde derecho, registro modular para
// Datos (menos foto, más cifra/estructura).

const RIDGE_PATH =
  "M0,120 L60,96 L120,108 L190,58 L260,86 L330,40 L410,72 L480,20 L560,54 " +
  "L630,10 L700,46 L770,18 L840,50 L910,30 L980,64 L1080,44 L1080,140 L0,140 Z";

export const EditorialTexture: React.FC<{
  mode: ModeTokens;
  zone?: "header" | "footer" | "full";
  width: number;
  height: number;
}> = ({ mode, zone = "footer", width, height }) => {
  const color = hexToRgba(mode.accent, mode.textureOpacity);

  if (mode.textureVariant === "grid" && zone === "full") {
    // Campo de puntos disperso a pantalla completa: usado por composiciones
    // "Datos" con poco contenido (p.ej. cover/number sin foto) para que el
    // espacio negativo se lea como retícula modular intencional, no como
    // hueco vacío por falta de componentes.
    const cols = 10;
    const rowsN = 13;
    const dots: React.ReactNode[] = [];
    for (let r = 0; r < rowsN; r += 1) {
      for (let c = 0; c < cols; c += 1) {
        dots.push(<circle key={`${r}-${c}`} cx={(width / cols) * (c + 0.5)} cy={(height / rowsN) * (r + 0.5)} r={2} fill={color} />);
      }
    }
    return (
      <svg style={{ position: "absolute", inset: 0, width, height, pointerEvents: "none" }} viewBox={`0 0 ${width} ${height}`}>
        {dots}
      </svg>
    );
  }

  if (mode.textureVariant === "ridge") {
    const top = zone === "header" ? 0 : height - 140;
    return (
      <svg
        style={{ position: "absolute", left: 0, top, width, height: 140, pointerEvents: "none" }}
        viewBox="0 0 1080 140"
        preserveAspectRatio="none"
      >
        <path d={RIDGE_PATH} fill={color} transform={zone === "header" ? "scale(1,-1) translate(0,-140)" : undefined} />
      </svg>
    );
  }

  if (mode.textureVariant === "rule") {
    const top = zone === "header" ? 0 : height - 6;
    return (
      <svg
        style={{ position: "absolute", left: 0, top, width, height: 6, pointerEvents: "none" }}
        viewBox="0 0 1080 6"
        preserveAspectRatio="none"
      >
        <rect x={0} y={0} width={1080} height={2} fill={color} />
        <rect x={0} y={4} width={1080} height={1} fill={color} />
      </svg>
    );
  }

  // "grid" — retícula modular de puntos, borde derecho, franja completa.
  const rows = 14;
  const dots = Array.from({ length: rows }, (_, i) => i);
  return (
    <svg
      style={{ position: "absolute", right: 0, top: 0, width: 64, height, pointerEvents: "none" }}
      viewBox={`0 0 64 ${height}`}
      preserveAspectRatio="none"
    >
      {dots.map((i) => (
        <circle key={i} cx={32} cy={(height / rows) * (i + 0.5)} r={2.5} fill={color} />
      ))}
    </svg>
  );
};
