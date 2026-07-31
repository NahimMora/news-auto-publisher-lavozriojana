import React from "react";
import { AbsoluteFill, Img, staticFile } from "remotion";
import { NEGRO, WHITE } from "../constants";

// Copia congelada del StillLayout previo al rediseño "Editorial Cinemática
// Riojana", usada exclusivamente por FacebookOgCard.tsx. El brief de este
// rediseño pidió explícitamente NO tocar el workflow "og" — ver
// docs/DECISIONS.md "Editorial Cinemática Riojana" (fuera de alcance). En
// vez de forzar a FacebookOgCard a adoptar el contrato nuevo de
// shared/StillLayout.tsx (que ahora requiere `mode` en vez de `accent`),
// se aísla acá para que FacebookOgCard.tsx quede pixel-idéntico a como
// estaba, sin depender de un contrato pensado para otras dos piezas.

export type LegacyStillLayoutProps = {
  width: number;
  height: number;
  accent: string;
  section?: string;
  counter?: string;
  backgroundAssetFile?: string;
  children: React.ReactNode;
};

export const LegacyStillLayout: React.FC<LegacyStillLayoutProps> = ({
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
        <Img
          src={staticFile(backgroundAssetFile)}
          style={{
            position: "absolute", top: 0, left: 0, width, height,
            objectFit: "cover", filter: "blur(50px) brightness(0.55)",
            transform: "scale(1.15)",
          }}
        />
      ) : null}

      <div style={{ position: "absolute", top: 0, left: 0, width: Math.max(10, width * 0.013), height, backgroundColor: accent }} />

      <div style={{ position: "absolute", inset: 0 }}>{children}</div>

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
