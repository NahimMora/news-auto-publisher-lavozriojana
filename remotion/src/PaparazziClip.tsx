import React from "react";
import { Video } from "@remotion/media";
import { AbsoluteFill, staticFile } from "remotion";
import { z } from "zod";
import { StillLayout } from "./shared/StillLayout";
import { MODES, modeFromSection } from "./shared/designSystem";

// Clip de video para el carrusel paparazzi (imagen+video) — mismo masthead/
// footer "Editorial Cinemática Riojana" que AutomaticInstagramCard (la
// portada del mismo carrusel, ver Root.tsx), para que ambos slides se vean
// como una sola pieza. A diferencia de EditorialReel (Reel 9:16, con
// título/outro), este es sólo el video fuente ya recortado (por Python, ver
// utils/video_renderer.py::render_paparazzi_clips) con el chrome de marca
// encima — sin título propio, porque el titular ya vive en la portada.
export const PAPARAZZI_CLIP_W = 1080;
export const PAPARAZZI_CLIP_H = 1350;

export const PaparazziClipSchema = z.object({
  seccion: z.string(),
  assetFile: z.string(),
  durationInFrames: z.number(),
});

export type PaparazziClipProps = z.infer<typeof PaparazziClipSchema>;

export const PaparazziClip: React.FC<PaparazziClipProps> = ({ seccion, assetFile }) => {
  const mode = MODES[modeFromSection(seccion)];
  const src = staticFile(assetFile);

  // Mismo truco que EditorialReel para video fuente que no es 4:5: fondo
  // blureado a pantalla completa + copia nítida en "contain" arriba, así
  // nunca se recorta feo la imagen real (entrevistas suelen ser 16:9).
  const media = (
    <AbsoluteFill style={{ overflow: "hidden", backgroundColor: "#000" }}>
      <Video
        src={src}
        muted
        objectFit="cover"
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
          filter: "blur(50px) brightness(0.48) saturate(1.15)",
          scale: 1.2,
        }}
      />
      <Video
        src={src}
        objectFit="contain"
        style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
      />
    </AbsoluteFill>
  );

  return (
    <StillLayout width={PAPARAZZI_CLIP_W} height={PAPARAZZI_CLIP_H} mode={mode} section={seccion} showSocialFooter media={media}>
      {null}
    </StillLayout>
  );
};
