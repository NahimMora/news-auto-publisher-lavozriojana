// ManualStoryTemplate — fondo vacío 1080×1920 para la historia "Nueva
// publicación" que el operador sube a mano: encima pega el post o Reel
// compartido y el sticker de link a la nota web. Sin textos de la nota: la
// pieza no dice nada que no esté en la publicación compartida.
import React from "react";
import { AbsoluteFill } from "remotion";
import { useV2FontsReady } from "../fonts";
import { C, rgba } from "../tokens";
import { PhotoBackdrop, STORY, StoryMasthead, Tab, caps } from "./chrome";

export const ManualStoryTemplate: React.FC = () => {
  const ready = useV2FontsReady();
  if (!ready) return <AbsoluteFill style={{ backgroundColor: C.ink }} />;
  return (
    <AbsoluteFill>
      <PhotoBackdrop />
      <StoryMasthead tab={<Tab label="Nueva publicación" fill={rgba(C.white, 0.14)} />} />
      {/* Debajo de la publicación pegada: invita al sticker de link, que va abajo. */}
      <div
        style={{
          position: "absolute",
          left: STORY.m,
          right: STORY.m,
          top: 1440,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 14,
          ...caps(28, rgba(C.white, 0.82), 800, 0.12),
        }}
      >
        <span>Leé la nota completa</span>
        <span style={{ fontSize: 40, letterSpacing: 0 }}>↓</span>
      </div>
    </AbsoluteFill>
  );
};
