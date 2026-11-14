// Transiciones entre historias del Noticiero V5. La imagen que entra es la
// primera toma de la historia siguiente dibujada en SU frame 0: al llegar el
// corte ya está en pantalla, así no hay salto. Cada transición dura 9 frames
// (≈0,3 s) y cubre el aire entre locuciones; rotan sin azar y una vez por
// edición la cortina de marca marca el medio del recorrido.
import React from "react";
import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame } from "remotion";
import { EASE, clamp, mix } from "../motion";
import type { ShotV5, StoryV5 } from "./schema";
import { MapShot, PhotoShot, Texture } from "./shots";
import { C5, L } from "./theme";
import { Scrims5 } from "./typeLayers";

export const TRANSITION_FRAMES = 9;

const Incoming: React.FC<{ shot: ShotV5 }> = ({ shot }) => (
  <AbsoluteFill>
    {shot.kind === "map" ? <MapShot shot={shot} frame={0} /> : <PhotoShot shot={shot} frame={0} />}
    <Texture />
    {shot.kind === "map" ? null : <Scrims5 />}
  </AbsoluteFill>
);

export const Transition5: React.FC<{ story: StoryV5 | null; at: number; kind: StoryV5["wipe"] }> = ({ story, at, kind }) => {
  const frame = useCurrentFrame();
  if (kind === "cut") return null;
  if (kind === "brand") {
    // Cortina de marca centrada en el corte: entra 5 frames, sale 5.
    const local = frame - (at - 5);
    if (local < 0 || local > 10) return null;
    const x = local <= 5 ? interpolate(local, [0, 5], [L.w * 1.25, 0], { ...clamp, easing: EASE.out }) : interpolate(local, [5, 10], [0, -L.w * 1.25], { ...clamp, easing: EASE.in });
    return (
      <AbsoluteFill style={{ pointerEvents: "none" }}>
        <div style={{ position: "absolute", top: -300, left: -260, width: L.w + 520, height: L.h + 600, backgroundColor: C5.red, transform: `translateX(${x}px) skewX(-12deg)` }} />
        <Img src={staticFile("logo.png")} style={{ position: "absolute", left: L.w / 2 - 160, top: L.h / 2 - 240, width: 320, height: 320, objectFit: "contain", transform: `translateX(${x}px) rotate(${mix(local / 10, -10, 10)}deg)` }} />
      </AbsoluteFill>
    );
  }
  const local = frame - (at - TRANSITION_FRAMES);
  if (local < 0 || local >= TRANSITION_FRAMES || !story || !story.shots.length) return null;
  const t = interpolate(local + 1, [0, TRANSITION_FRAMES], [0, 1], { ...clamp, easing: EASE.inOut });
  const velocity = Math.sin(Math.PI * Math.min(1, (local + 0.5) / TRANSITION_FRAMES));
  const shot = story.shots[0];
  if (kind === "slash") {
    // Borde en diagonal (la firma gráfica del medio) con banda roja delante.
    const edge = mix(t, -40, 140);
    const poly = `polygon(0% 0%, ${edge + 18}% 0%, ${edge - 18}% 100%, 0% 100%)`;
    return (
      <AbsoluteFill style={{ pointerEvents: "none" }}>
        <AbsoluteFill style={{ clipPath: poly }}>
          <Incoming shot={shot} />
        </AbsoluteFill>
        <div style={{ position: "absolute", top: -200, left: `${edge - 4}%`, width: 70, height: L.h + 400, backgroundColor: C5.red, transform: "skewX(-19deg)", opacity: t < 1 ? 1 : 0 }} />
        <div style={{ position: "absolute", top: -200, left: `calc(${edge - 4}% + 74px)`, width: 10, height: L.h + 400, backgroundColor: C5.white, transform: "skewX(-19deg)", opacity: t < 1 ? 1 : 0 }} />
      </AbsoluteFill>
    );
  }
  if (kind === "slide") {
    const x = mix(t, L.w, 0);
    return (
      <AbsoluteFill style={{ pointerEvents: "none" }}>
        <AbsoluteFill style={{ transform: `translateX(${x}px)`, boxShadow: "-40px 0 80px rgba(0,0,0,0.6)", filter: `blur(${velocity * 6}px)` }}>
          <Incoming shot={shot} />
          <div style={{ position: "absolute", left: 0, top: 0, width: 14, height: L.h, backgroundColor: C5.red }} />
        </AbsoluteFill>
      </AbsoluteFill>
    );
  }
  // lift: la toma entrante sube desde abajo y se asienta.
  const y = mix(t, L.h, 0);
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <AbsoluteFill style={{ transform: `translateY(${y}px) scale(${mix(t, 0.94, 1)})`, transformOrigin: "50% 0%", boxShadow: "0 -40px 80px rgba(0,0,0,0.6)", filter: `blur(${velocity * 5}px)` }}>
        <Incoming shot={shot} />
        <div style={{ position: "absolute", left: 0, top: 0, width: L.w, height: 14, backgroundColor: C5.red }} />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
