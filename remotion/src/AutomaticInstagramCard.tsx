import React from "react";
import { AbsoluteFill, Img, staticFile } from "remotion";
import { z } from "zod";
import { FittedTitle } from "./shared/FittedTitle";
import { SectionBadge } from "./shared/SectionBadge";
import { StillLayout } from "./shared/StillLayout";
import { FONT_DISPLAY, MODES, SAFE, TYPE, WEIGHT, WHITE, modeFromSection } from "./shared/designSystem";

// Card automática para noticias scrapeadas (rediseño "Editorial Cinemática
// Riojana" — ver docs/DECISIONS.md). Conectada de verdad al pipeline real
// vía layout/image_generator.py::generate_instagram_with_engine (antes sólo
// existía como composición sin wiring productivo).
export const AUTOMATIC_IG_W = 1080;
export const AUTOMATIC_IG_H = 1350;

export const AutomaticInstagramCardSchema = z.object({
  titulo: z.string(),
  seccion: z.string(),
  assetFile: z.string().default(""),
  // Señal barata (media_library.py ya guarda width/height): permite variar
  // la composición según orientación de la foto sin volver a abrirla en
  // Remotion. Opcional para no romper compatibilidad con props anteriores.
  assetOrientation: z.enum(["landscape", "portrait", "square"]).optional(),
  highlightTerms: z.array(z.string()).default([]),
});

export type AutomaticInstagramCardProps = z.infer<typeof AutomaticInstagramCardSchema>;

const PAD = SAFE.pad;
const CONTENT_MAX_Y = AUTOMATIC_IG_H - SAFE.footerH - 30;

export const AutomaticInstagramCard: React.FC<AutomaticInstagramCardProps> = ({
  titulo,
  seccion,
  assetFile,
  assetOrientation,
  highlightTerms,
}) => {
  const mode = MODES[modeFromSection(seccion)];
  const hasImage = Boolean(assetFile);
  // Foto nítida en primer plano sobre el fondo blureado de StillLayout —
  // misma gramática visual que Main.tsx (blur ambiental + foreground
  // nítido), adaptada a una pieza estática. La altura del marco varía según
  // orientación: retrato pide más aire vertical, horizontal rinde mejor
  // más compacta para dejar lugar al titular.
  const frameH = assetOrientation === "portrait" ? 860 : assetOrientation === "square" ? 760 : 660;

  return (
    <StillLayout width={AUTOMATIC_IG_W} height={AUTOMATIC_IG_H} mode={mode} section={seccion} backgroundAssetFile={assetFile}>
      {hasImage && (
        <>
          <Img
            src={staticFile(assetFile)}
            style={{
              position: "absolute", top: 0, left: 0, width: "100%", height: frameH,
              objectFit: "cover", filter: mode.photoFilter,
            }}
          />
          <div
            style={{
              position: "absolute", left: 0, right: 0, top: frameH - 170, height: 170,
              background: "linear-gradient(180deg, rgba(0,0,0,0) 0%, rgba(0,0,0,0.9) 100%)",
            }}
          />
        </>
      )}

      <AbsoluteFill style={{ padding: PAD, paddingBottom: AUTOMATIC_IG_H - CONTENT_MAX_Y, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
        <SectionBadge label={seccion.toUpperCase()} accent={mode.accent} />

        <FittedTitle
          text={titulo}
          highlightTerms={highlightTerms}
          color={WHITE}
          highlightColor={mode.accent}
          fontFamily={FONT_DISPLAY}
          fontWeight={mode.id === "editorial" ? WEIGHT.bold : WEIGHT.black}
          maxWidth={AUTOMATIC_IG_W - PAD * 2}
          maxHeight={hasImage ? 340 : 520}
          minFontSize={TYPE.titleCover.min - 4}
          maxFontSize={TYPE.titleCover.max - 4}
          lineHeightRatio={TYPE.titleCover.lineHeightRatio}
          letterSpacing={TYPE.titleCover.tracking}
          textShadow={hasImage ? "0 4px 18px rgba(0,0,0,0.6)" : undefined}
          maxLines={5}
        />
      </AbsoluteFill>
    </StillLayout>
  );
};
