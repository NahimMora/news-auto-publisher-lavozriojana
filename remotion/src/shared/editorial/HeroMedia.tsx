import React from "react";
import { Img, staticFile } from "remotion";
import { ModeTokens, SAFE, fullScrimStack, hexToRgba } from "../designSystem";

// Tres tratamientos fotográficos, no uno solo:
//
// - "full_bleed": foto limpia, borde a borde, protagonista real (cover,
//   full_image, card automática con foto de buena calidad).
// - "framed": imagen contenida en un marco editorial con margen — para
//   fotos horizontales/verticales/de baja calidad que no rinden bien a
//   pantalla completa (en vez de forzarlas a cubrir todo el lienzo).
// - "poster": para capturas/flyers que YA traen logos o texto propio. La
//   pieza ajena NUNCA es el fondo completo: vive dentro de un marco propio,
//   sobre un fondo de marca derivado de la imagen (blur + wash de acento),
//   separada físicamente del titular — así no compiten dos sistemas
//   tipográficos ni varios logos en la misma zona.
export type HeroMediaVariant = "full_bleed" | "framed" | "poster";

export const HeroMedia: React.FC<{
  assetFile: string;
  mode: ModeTokens;
  variant: HeroMediaVariant;
  top: number;
  height: number;
  width: number;
  scrim?: "bottom" | "full" | "none";
}> = ({ assetFile, mode, variant, top, height, width, scrim = "bottom" }) => {
  if (!assetFile) return null;
  const src = staticFile(assetFile);

  if (variant === "full_bleed") {
    return (
      <div style={{ position: "absolute", top, left: 0, width, height, overflow: "hidden" }}>
        <Img
          src={src}
          style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover", filter: mode.photoFilter }}
        />
        {scrim === "full" &&
          fullScrimStack(mode).map((layer, i) => <div key={i} style={{ position: "absolute", inset: 0, background: layer }} />)}
        {scrim === "bottom" && (
          <div
            style={{
              position: "absolute",
              left: 0,
              right: 0,
              bottom: 0,
              height: Math.round(height * 0.42),
              background: "linear-gradient(180deg, rgba(0,0,0,0) 0%, rgba(6,4,4,0.88) 100%)",
            }}
          />
        )}
      </div>
    );
  }

  if (variant === "framed") {
    const pad = mode.pad;
    const frameW = width - pad * 2;
    return (
      <div style={{ position: "absolute", top, left: pad, width: frameW, height, overflow: "hidden", borderRadius: SAFE.cardRadius }}>
        <Img
          src={src}
          style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover", filter: mode.photoFilter }}
        />
        <div style={{ position: "absolute", inset: 0, boxShadow: `inset 0 0 0 1px ${hexToRgba("#FFFFFF", 0.14)}` }} />
        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            bottom: 0,
            height: Math.round(height * 0.5),
            background: "linear-gradient(180deg, rgba(0,0,0,0) 0%, rgba(6,4,4,0.75) 100%)",
          }}
        />
      </div>
    );
  }

  // "poster": marco propio sobre fondo de marca derivado de la imagen.
  const pad = mode.pad;
  const posterW = width - pad * 2;
  return (
    <div style={{ position: "absolute", top, left: 0, width, height, overflow: "hidden" }}>
      <Img
        src={src}
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
          objectFit: "cover",
          filter: `blur(60px) brightness(0.45) saturate(0.9) ${mode.photoFilter}`,
          transform: "scale(1.2)",
        }}
      />
      <div style={{ position: "absolute", inset: 0, background: `linear-gradient(160deg, ${hexToRgba(mode.accentSoft, 0.5)} 0%, rgba(0,0,0,0.55) 100%)` }} />
      <div
        style={{
          position: "absolute",
          top: Math.round(height * 0.06),
          left: pad,
          width: posterW,
          height: Math.round(height * 0.82),
          borderRadius: 10,
          overflow: "hidden",
          boxShadow: "0 24px 60px rgba(0,0,0,0.55)",
          border: `1px solid ${hexToRgba("#FFFFFF", 0.22)}`,
          backgroundColor: "#000",
        }}
      >
        <Img src={src} style={{ width: "100%", height: "100%", objectFit: "contain", backgroundColor: "#0B0B0B" }} />
      </div>
    </div>
  );
};
