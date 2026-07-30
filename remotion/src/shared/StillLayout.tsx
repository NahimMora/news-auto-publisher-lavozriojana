import React from "react";
import { AbsoluteFill, Img, staticFile } from "remotion";
import { NEGRO, WHITE } from "../constants";

// Layout compartido entre PremiumSlide, AutomaticInstagramCard y
// FacebookOgCard: barra de acento, footer con sección + numeración, logo.
// Mantiene jerarquía visual consistente entre las tres piezas (Fase 4).

export type StillLayoutProps = {
  width: number;
  height: number;
  accent: string;
  section?: string;
  counter?: string; // p.ej. "2/5"; vacío si no aplica (OG/IG automático)
  backgroundAssetFile?: string; // relativo a public/, "" si no hay imagen
  children: React.ReactNode;
};

export const StillLayout: React.FC<StillLayoutProps> = ({
  width,
  height,
  accent,
  section,
  counter,
  backgroundAssetFile,
  children,
}) => {
  const footerH = Math.round(height * 0.052);
  return (
    <AbsoluteFill style={{ backgroundColor: NEGRO }}>
      {backgroundAssetFile ? (
        <>
          <Img
            src={staticFile(backgroundAssetFile)}
            style={{
              position: "absolute", top: 0, left: 0, width, height,
              objectFit: "cover", filter: "blur(50px) brightness(0.55)",
              transform: "scale(1.15)",
            }}
          />
        </>
      ) : null}

      {/* Barra de acento (identidad compartida entre las 3 piezas) */}
      <div style={{ position: "absolute", top: 0, left: 0, width: Math.max(10, width * 0.013), height, backgroundColor: accent }} />

      <div style={{ position: "absolute", inset: 0 }}>{children}</div>

      {/* Footer: sección + numeración */}
      <div
        style={{
          position: "absolute", left: 0, right: 0, bottom: 0, height: footerH,
          backgroundColor: "#111111", display: "flex", alignItems: "center",
          justifyContent: "space-between", paddingLeft: 40, paddingRight: 40,
        }}
      >
        <div style={{ fontFamily: "Arial, sans-serif", fontWeight: 900, fontSize: footerH * 0.42, color: accent }}>
          {(section || "").toUpperCase()}
        </div>
        {counter ? (
          <div style={{ fontFamily: "Arial, sans-serif", fontWeight: 700, fontSize: footerH * 0.42, color: WHITE }}>
            {counter}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
