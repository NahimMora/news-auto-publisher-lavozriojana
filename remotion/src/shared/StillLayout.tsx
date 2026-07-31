import React from "react";
import { AbsoluteFill, Img, staticFile } from "remotion";
import { useFontsReady } from "./fonts";
import { Grain } from "./Grain";
import { SectionBadge } from "./SectionBadge";
import { SlideCounter } from "./SlideCounter";
import { ModeTokens, SAFE, fullScrimStack, hexToRgba } from "./designSystem";

// Layout compartido entre PremiumSlide y AutomaticInstagramCard: fondo
// (foto ambiental con gradientes por capas, o base de marca con textura
// cuando no hay foto), barra de acento, grano editorial, footer con badge
// de sección + numeración, y marca de logo discreta. Un solo lugar para la
// jerarquía visual compartida entre las dos piezas — ver
// docs/DECISIONS.md "Editorial Cinemática Riojana".
//
// FacebookOgCard sigue usando el StillLayout anterior de forma implícita
// (no se tocó en esta entrega, workflow "og" fuera de alcance) — este
// archivo es exclusivamente para PremiumSlide/AutomaticInstagramCard.

export type StillLayoutProps = {
  width: number;
  height: number;
  mode: ModeTokens;
  section?: string;
  index?: number;
  total?: number;
  backgroundAssetFile?: string; // relativo a public/, "" si no hay imagen
  children: React.ReactNode;
};

export const StillLayout: React.FC<StillLayoutProps> = ({
  width,
  height,
  mode,
  section,
  index,
  total,
  backgroundAssetFile,
  children,
}) => {
  // Bloquea la captura de Remotion (delayRender) hasta que Archivo/Source
  // Serif 4 están registradas de verdad y el DOM volvió a pintar con ellas.
  // `children` (títulos/textos vía FittedTitle) sólo se monta después,
  // así fitText.ts siempre mide con la tipografía real — nunca con el
  // fallback del sistema. Ver docs/DECISIONS.md, bug detectado en smoke
  // test manual (wrap incorrecto por medir antes de que cargara la fuente).
  const fontsReady = useFontsReady();
  const footerH = SAFE.footerH;
  const hasImage = Boolean(backgroundAssetFile);

  return (
    <AbsoluteFill style={{ backgroundColor: mode.ink }}>
      {hasImage ? (
        <>
          <Img
            src={staticFile(backgroundAssetFile as string)}
            style={{
              position: "absolute",
              top: 0,
              left: 0,
              width,
              height,
              objectFit: "cover",
              filter: `blur(46px) brightness(0.5) ${mode.photoFilter}`,
              transform: "scale(1.15)",
            }}
          />
          {fullScrimStack(mode).map((layer, i) => (
            <div key={i} style={{ position: "absolute", inset: 0, background: layer }} />
          ))}
        </>
      ) : (
        <>
          <div
            style={{
              position: "absolute",
              inset: 0,
              background: `radial-gradient(ellipse 900px 700px at 78% -10%, ${hexToRgba(mode.accent, 0.16)} 0%, rgba(0,0,0,0) 60%)`,
            }}
          />
          <div
            style={{
              position: "absolute",
              inset: 0,
              background: `linear-gradient(200deg, ${hexToRgba(mode.accentSoft, 0.22)} 0%, rgba(0,0,0,0) 55%)`,
            }}
          />
        </>
      )}

      <Grain opacity={0.03} />

      {/* Barra de acento — identidad compartida entre las piezas */}
      <div style={{ position: "absolute", top: 0, left: 0, width: SAFE.accentBarW, height, backgroundColor: mode.accent }} />

      <div style={{ position: "absolute", inset: 0 }}>{fontsReady ? children : null}</div>

      {/* Marca discreta, esquina superior derecha — siempre por encima del contenido de la slide */}
      <Img
        src={staticFile("logo.png")}
        style={{ position: "absolute", top: 28, right: 28, width: 92, opacity: 0.86, filter: "drop-shadow(0 2px 6px rgba(0,0,0,0.5))" }}
      />

      {/* Footer: separador fino + badge de sección + numeración */}
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 0,
          height: footerH,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          paddingLeft: SAFE.pad,
          paddingRight: SAFE.pad,
        }}
      >
        <div style={{ position: "absolute", top: 0, left: SAFE.accentBarW, right: 0, height: 1, backgroundColor: hexToRgba(mode.accent, 0.35) }} />
        <SectionBadge label={(section || "").toUpperCase()} accent={mode.accent} size="sm" />
        {total ? <SlideCounter index={index || 1} total={total} accent={mode.accent} /> : null}
      </div>
    </AbsoluteFill>
  );
};
