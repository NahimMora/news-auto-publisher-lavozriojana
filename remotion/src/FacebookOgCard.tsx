import React from "react";
import { AbsoluteFill, Img, staticFile } from "remotion";
import { z } from "zod";
import { useFontsReady } from "./shared/fonts";
import { Grain } from "./shared/Grain";
import { EditorialMasthead } from "./shared/editorial/EditorialMasthead";
import { HeadlineBlock } from "./shared/editorial/HeadlineBlock";
import { SocialFooter } from "./shared/editorial/SocialFooter";
import { MODES, ModeTokens, hexToRgba, modeFromSection } from "./shared/designSystem";

// Tarjeta de Open Graph (imagen que Facebook/WhatsApp/etc. muestran al
// compartir el link del artículo web, ver pipeline/node_webapp/media.py
// ::generate_og_image) — v3 en dos columnas (LVR-IMPROVEMENT-0003).
//
// La v2 apilaba foto arriba (52%) y un panel de tinta abajo: en un lienzo
// 1200x630 eso dejaba la foto recortada a una franja y el titular chico,
// con mucho espacio vacío. El formato es muy horizontal, así que la foto
// ocupa la columna izquierda a alto completo (recorte `cover` centrado, sin
// recorte inteligente) y la columna derecha concentra sección, titular y
// marca. El titular es el gancho ya generado para Instagram
// (`titulo_instagram`), sin llamadas extra a IA.
export const FB_OG_W = 1200;
export const FB_OG_H = 630;

export const FacebookOgCardSchema = z.object({
  titulo: z.string(),
  seccion: z.string(),
  assetFile: z.string().default(""),
  highlightTerms: z.array(z.string()).default([]),
  publicationStyle: z.enum(["automatic", "manual_publication"]).default("automatic"),
});

export type FacebookOgCardProps = z.infer<typeof FacebookOgCardSchema>;

const PHOTO_W = 640;
const MASTHEAD_H = 96;
const FOOTER_H = 84;
const CHROME_SCALE = 1.0;
const PAD = 44;
// El titular tiene una columna alta para él solo: escala mayor que la v2
// (0.62) para que se lea en el tamaño chico del link preview.
const HEADLINE_SCALE = 0.74;
const MAX_LINES = 5;

export const FacebookOgCard: React.FC<FacebookOgCardProps> = ({ titulo, seccion, assetFile, highlightTerms, publicationStyle }) => {
  const mode = MODES[modeFromSection(seccion)];
  const fontsReady = useFontsReady();
  const hasImage = Boolean(assetFile);
  const columnLeft = hasImage ? PHOTO_W : 0;
  const columnW = FB_OG_W - columnLeft;
  const headlineW = columnW - PAD * 2;
  const headlineMaxH = FB_OG_H - MASTHEAD_H - FOOTER_H - PAD;

  return (
    <AbsoluteFill style={{ backgroundColor: mode.ink }}>
      {hasImage ? <PhotoColumn assetFile={assetFile} mode={mode} /> : <NoImageGlow mode={mode} />}

      <div style={{ position: "absolute", top: 0, bottom: 0, left: columnLeft, width: columnW }}>
        <Grain opacity={0.03} />
        <EditorialMasthead
          mode={mode}
          section={seccion}
          pad={PAD}
          scale={CHROME_SCALE}
          boxedSection={publicationStyle === "manual_publication"}
        />
        <div
          style={{
            position: "absolute",
            top: MASTHEAD_H,
            bottom: FOOTER_H,
            left: PAD,
            right: PAD,
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
            overflow: "hidden",
          }}
        >
          {fontsReady ? (
            <HeadlineBlock
              mode={mode}
              title={titulo}
              highlightTerms={highlightTerms}
              width={headlineW}
              maxHeight={headlineMaxH}
              maxLines={MAX_LINES}
              size="body"
              fontScale={HEADLINE_SCALE}
            />
          ) : null}
        </div>
        <div
          style={{
            position: "absolute",
            left: PAD,
            right: PAD,
            bottom: 0,
            height: FOOTER_H,
            display: "flex",
            alignItems: "center",
          }}
        >
          <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, backgroundColor: hexToRgba(mode.accent, 0.3) }} />
          <SocialFooter scale={CHROME_SCALE} />
        </div>
      </div>
    </AbsoluteFill>
  );
};

// Foto a alto completo en la columna izquierda; un fundido corto hacia la
// tinta evita un corte duro contra la columna de texto.
const PhotoColumn: React.FC<{ assetFile: string; mode: ModeTokens }> = ({ assetFile, mode }) => (
  <div style={{ position: "absolute", top: 0, left: 0, width: PHOTO_W, height: FB_OG_H, overflow: "hidden" }}>
    <Img
      src={staticFile(assetFile)}
      style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover", filter: mode.photoFilter }}
    />
    <div
      style={{
        position: "absolute",
        top: 0,
        bottom: 0,
        right: 0,
        width: 56,
        background: `linear-gradient(90deg, rgba(0,0,0,0) 0%, ${mode.ink} 100%)`,
      }}
    />
  </div>
);

const NoImageGlow: React.FC<{ mode: ModeTokens }> = ({ mode }) => (
  <div
    style={{
      position: "absolute",
      inset: 0,
      background: `radial-gradient(ellipse 900px 700px at 78% -10%, ${hexToRgba(mode.accent, 0.16)} 0%, rgba(0,0,0,0) 60%)`,
    }}
  />
);
