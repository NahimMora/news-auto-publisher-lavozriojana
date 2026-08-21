import React from "react";
import { z } from "zod";
import { HeadlineBlock } from "./shared/editorial/HeadlineBlock";
import { HeroMedia } from "./shared/editorial/HeroMedia";
import { StillLayout } from "./shared/StillLayout";
import { MODES, ModeTokens, hexToRgba, modeFromSection } from "./shared/designSystem";

// Tarjeta de Open Graph (imagen que Facebook/WhatsApp/etc. muestran al
// compartir el link del artículo web, ver pipeline/node_webapp/media.py
// ::generate_og_image) — v2 "Editorial Cinemática Riojana": mismo sistema
// visual que AutomaticInstagramCard/PremiumSlide (masthead de marca,
// HeroMedia, HeadlineBlock, modo por sección), no la versión vieja
// standalone (Arial + AZUL/WHITE fijos, ver shared/LegacyStillLayout.tsx).
// El lienzo 1200x630 es mucho más bajo que el 1080x1350 de las otras dos
// piezas: masthead/footer/chrome usan constantes propias más grandes que
// la primera versión (feedback: "la sección que se vea como las de estudio
// premium" — antes 0.82 se veía chico/distinto), el padding se comprime un
// 25% respecto del token de marca (`mode.pad`, pensado para el lienzo
// 1080x1350) y el titular usa una escala tipográfica propia más chica —
// nunca la de Premium/Automatic, que no entraría en un panel tan bajo.
// Nunca usa `showSwipeCue`/`total`: es una pieza única, no un carrusel.
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

const OG_MASTHEAD_H = 92;
const OG_FOOTER_H = 78;
const OG_CHROME_SCALE = 1.05;
// Escala tipográfica propia para el titular: TYPE.titleBody (58-88px) no
// entra en un panel de ~200px de alto sin desbordar — 0.62 baja el piso a
// ~36px, todavía sólido para una tarjeta que se ve chica en un link
// preview, nunca a tamaño completo de pantalla como el feed de Instagram.
const OG_HEADLINE_SCALE = 0.62;
const CONTENT_H = FB_OG_H - OG_MASTHEAD_H - OG_FOOTER_H;
// Foto arriba, panel de tinta abajo con el titular — mismo lenguaje que
// CoverSlide/FullBleedBody, con menos proporción de foto que las otras dos
// piezas (52% vs 60%) para que el panel tenga alto real donde entrar.
const PHOTO_H = Math.round(FB_OG_H * 0.52);

const OgHeadlineBlock: React.FC<React.ComponentProps<typeof HeadlineBlock>> = (props) => (
  <HeadlineBlock {...props} fontScale={OG_HEADLINE_SCALE} />
);

export const FacebookOgCard: React.FC<FacebookOgCardProps> = ({ titulo, seccion, assetFile, highlightTerms, publicationStyle }) => {
  const mode = MODES[modeFromSection(seccion)];
  const hasImage = Boolean(assetFile);

  const media = hasImage ? (
    <HeroMedia assetFile={assetFile} mode={mode} variant="full_bleed" top={0} height={PHOTO_H} width={FB_OG_W} scrim="none" />
  ) : null;

  return (
    <StillLayout
      width={FB_OG_W}
      height={FB_OG_H}
      mode={mode}
      section={seccion}
      media={media}
      mastheadHeight={OG_MASTHEAD_H}
      footerHeight={OG_FOOTER_H}
      chromeScale={OG_CHROME_SCALE}
      showSocialFooter
      boxedSection={publicationStyle === "manual_publication"}
    >
      {hasImage ? (
        <ImageBody titulo={titulo} highlightTerms={highlightTerms} mode={mode} />
      ) : (
        <NoImageBody titulo={titulo} highlightTerms={highlightTerms} mode={mode} />
      )}
    </StillLayout>
  );
};

// Foto protagonista arriba, panel de tinta sólida separado abajo con el
// titular — mismo lenguaje que CoverSlide (PremiumSlide.tsx) y
// FullBleedBody (AutomaticInstagramCard.tsx), acotado a 2 líneas porque el
// panel disponible acá es bajo. Siempre a ancho completo y alineado a la
// izquierda (mismo criterio que AutomaticInstagramCard: Premium tampoco
// achica/alinea a la derecha en modo Editorial).
const ImageBody: React.FC<{ titulo: string; highlightTerms: string[]; mode: ModeTokens }> = ({ titulo, highlightTerms, mode }) => {
  // Padding comprimido: `mode.pad` (64/80) está pensado para un lienzo de
  // 1350px de alto — sin comprimir, el panel de ~200px de esta tarjeta no
  // deja lugar real para el titular (bug real: el título se superponía al
  // footer). 75% da un margen visualmente equivalente en un lienzo bajo.
  const pad = Math.round(mode.pad * 0.75);
  const width = FB_OG_W - pad * 2;
  // Igual que en AutomaticInstagramCard.tsx: `media` se pinta en
  // coordenadas de canvas completo, mientras este componente vive dentro
  // del slot `children` (offseteado por OG_MASTHEAD_H) — hay que restar
  // OG_MASTHEAD_H para que el panel arranque justo donde termina la foto.
  const panelTop = PHOTO_H - OG_MASTHEAD_H;
  const panelH = CONTENT_H - panelTop;
  const fadeH = 90;
  return (
    <div style={{ position: "absolute", inset: 0 }}>
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          top: panelTop - fadeH,
          height: fadeH,
          background: `linear-gradient(180deg, rgba(0,0,0,0) 0%, ${mode.ink} 100%)`,
        }}
      />
      <div style={{ position: "absolute", left: 0, right: 0, top: panelTop, bottom: 0, backgroundColor: mode.ink }} />
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          top: panelTop,
          bottom: 0,
          padding: pad,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          overflow: "hidden",
        }}
      >
        {/* `maxHeight` resta el padding real de ambos lados (panelH - pad*2)
            — antes restaba un valor fijo (36) mucho menor que el padding
            real, y el titular podía desbordar el panel y superponerse al
            footer. `overflow:hidden` es la red de seguridad si un título
            extremo todavía no entra ni al piso tipográfico. */}
        <OgHeadlineBlock
          mode={mode}
          title={titulo}
          highlightTerms={highlightTerms}
          width={width}
          maxHeight={panelH - pad * 2}
          maxLines={2}
          size="body"
        />
      </div>
    </div>
  );
};

// Sin imagen: mismo criterio que NoImageBody en AutomaticInstagramCard.tsx,
// comprimido al alto disponible de este lienzo. Siempre a ancho completo y
// alineado a la izquierda.
const NoImageBody: React.FC<{ titulo: string; highlightTerms: string[]; mode: ModeTokens }> = ({ titulo, highlightTerms, mode }) => {
  const pad = Math.round(mode.pad * 0.75);
  const width = FB_OG_W - pad * 2;

  return (
    <div style={{ position: "absolute", inset: 0 }}>
      {mode.grid !== "column" && (
        <div
          style={{
            position: "absolute",
            top: 0,
            right: 0,
            width: FB_OG_W * 0.5,
            height: CONTENT_H,
            background: `linear-gradient(200deg, ${hexToRgba(mode.accent, 0.2)} 0%, rgba(0,0,0,0) 62%)`,
            clipPath: "polygon(24% 0, 100% 0, 100% 100%, 0% 100%)",
          }}
        />
      )}
      <div style={{ position: "absolute", inset: 0, padding: pad, display: "flex", flexDirection: "column", justifyContent: "center", overflow: "hidden" }}>
        <OgHeadlineBlock mode={mode} title={titulo} highlightTerms={highlightTerms} width={width} maxHeight={CONTENT_H - pad * 2} maxLines={3} size="body" />
      </div>
    </div>
  );
};
