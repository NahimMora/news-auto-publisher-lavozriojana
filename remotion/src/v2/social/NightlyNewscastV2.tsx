// NightlyNewscastV2 — Reel 1080×1920 de las 21: "Noticiero de la Noche".
//
// Estructura (30 fps, duraciones según la locución de cada parte):
//   apertura en frío  sirena + cortes rápidos sobre las fotos más fuertes,
//                     luces de patrullero en los bordes y un titular corto
//                     golpeado por cada corte, mientras la voz dice el gancho.
//   sello             cortina roja, sello y "21 H" con golpe de sonido.
//   bloques           un hecho (o varios del mismo tema) por bloque: medios
//                     reales de la nota con cambios de imagen o video
//                     silenciado, regleta de avance, número, rótulo de
//                     sección y lugar, titular y fuente. Policiales entra con
//                     banda roja y destello de luces; el resto, con el color
//                     de su sección.
//   cierre            sello, wordmark y llamado a seguir la cuenta, con firma
//                     sonora y la música que se apaga.
// La música de fondo baja debajo de cada locución. Todo el texto propio queda
// dentro de la zona segura de los Reels (y 210–1540, x 64–940).
import React from "react";
import { Audio, Video } from "@remotion/media";
import { AbsoluteFill, Img, Sequence, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { z } from "zod";
import { Grain } from "../../shared/Grain";
import { fit } from "../fit";
import { useV2FontsReady } from "../fonts";
import { EASE, SPRING, clamp, mix, p, sp } from "../motion";
import { C, REEL, V2_FONT_SERIF, rgba, sectionStyle } from "../tokens";
import { caps, display, serif } from "./chrome";

const Media = z.object({
  type: z.enum(["image", "video"]),
  file: z.string(),
  width: z.number().default(0),
  height: z.number().default(0),
});

const Block = z.object({
  seccion: z.string(),
  lugar: z.string().default(""),
  titulo: z.string(),
  credit: z.string().default(""),
  voiceFile: z.string(),
  voiceFrames: z.number(),
  media: z.array(Media).default([]),
});

export const NightlyNewscastV2Schema = z.object({
  dateLabel: z.string(),
  hook: z.object({
    voiceFile: z.string(),
    voiceFrames: z.number(),
    teasers: z.array(z.string()).default([]),
    media: z.array(Media).default([]),
  }),
  blocks: z.array(Block),
  outro: z.object({ voiceFile: z.string(), voiceFrames: z.number() }),
});

export type NightlyNewscastV2Props = z.infer<typeof NightlyNewscastV2Schema>;
type MediaItem = z.infer<typeof Media>;
type BlockItem = z.infer<typeof Block>;

const W = REEL.w;
const H = REEL.h;
const M = REEL.safe.left;
const SAFE_R = REEL.safe.right;

// La voz arranca apenas después del corte para que el sonido respire.
export const NEWSCAST = {
  hookVoiceDelay: 20,
  hookTail: 8,
  hookMin: 96,
  ident: 42,
  blockVoiceDelay: 8,
  blockTail: 14,
  outroVoiceDelay: 16,
  outroMin: 132,
} as const;

export function newscastTimeline(props: Pick<NightlyNewscastV2Props, "hook" | "blocks" | "outro">) {
  const hook = Math.max(NEWSCAST.hookMin, NEWSCAST.hookVoiceDelay + props.hook.voiceFrames + NEWSCAST.hookTail);
  const identStart = hook;
  const blocksStart = hook + NEWSCAST.ident;
  const blocks: { from: number; duration: number }[] = [];
  let cursor = blocksStart;
  for (const b of props.blocks) {
    const duration = NEWSCAST.blockVoiceDelay + b.voiceFrames + NEWSCAST.blockTail;
    blocks.push({ from: cursor, duration });
    cursor += duration;
  }
  const outroStart = cursor;
  const outro = Math.max(NEWSCAST.outroMin, NEWSCAST.outroVoiceDelay + props.outro.voiceFrames + 36);
  return { hook, identStart, blocksStart, blocks, outroStart, outro, total: outroStart + outro };
}

// ── Piezas visuales ──────────────────────────────────────────────────────
const Seal: React.FC<{ size: number; style?: React.CSSProperties }> = ({ size, style }) => (
  <Img src={staticFile("logo.png")} style={{ width: size, height: size, objectFit: "contain", ...style }} />
);

// Luces de patrullero: rojo y azul que se alternan desde los bordes.
const PoliceLights: React.FC<{ strength?: number }> = ({ strength = 1 }) => {
  const frame = useCurrentFrame();
  const phase = Math.floor(frame / 4) % 4;
  const red = phase === 0 || phase === 1 ? 1 : 0.18;
  const blue = phase === 2 || phase === 3 ? 1 : 0.18;
  const flick = frame % 4 === 0 ? 1 : 0.82;
  return (
    <AbsoluteFill style={{ pointerEvents: "none", mixBlendMode: "screen" }}>
      <AbsoluteFill style={{ background: `radial-gradient(ellipse 70% 55% at 0% 30%, ${rgba("#FF1E2D", 0.75 * red * strength * flick)} 0%, rgba(0,0,0,0) 70%)` }} />
      <AbsoluteFill style={{ background: `radial-gradient(ellipse 70% 55% at 100% 30%, ${rgba("#1E5BFF", 0.75 * blue * strength * flick)} 0%, rgba(0,0,0,0) 70%)` }} />
    </AbsoluteFill>
  );
};

const Vignette: React.FC<{ strength?: number }> = ({ strength = 0.85 }) => (
  <AbsoluteFill style={{ background: `radial-gradient(ellipse 85% 70% at 50% 42%, rgba(0,0,0,0) 40%, ${rgba(C.ink, strength)} 100%)` }} />
);

// Un medio a pantalla del panel: foto con cámara lenta o video silenciado.
const MediaFill: React.FC<{ item: MediaItem; duration: number; variant: number; fromScale?: number }> = ({ item, duration, variant, fromScale = 1.12 }) => {
  const frame = useCurrentFrame();
  if (item.type === "video") {
    return <Video src={staticFile(item.file)} muted objectFit="cover" style={{ width: "100%", height: "100%" }} />;
  }
  const t = interpolate(frame, [0, Math.max(1, duration)], [0, 1], { ...clamp, easing: EASE.camera });
  const scale = mix(t, fromScale, 1.0);
  const driftX = (variant % 2 === 0 ? 1 : -1) * mix(t, 24, 0);
  const driftY = (variant % 3 === 0 ? -1 : 1) * mix(t, 12, 0);
  return (
    <Img
      src={staticFile(item.file)}
      style={{ width: "100%", height: "100%", objectFit: "cover", transform: `translate(${driftX}px, ${driftY}px) scale(${scale})` }}
    />
  );
};

// Secuencia de medios con fundido corto entre uno y otro.
const MediaReel: React.FC<{ media: MediaItem[]; duration: number; seccion: string; fade?: number }> = ({ media, duration, seccion, fade = 8 }) => {
  const frame = useCurrentFrame();
  if (media.length === 0) {
    // Sin foto apta (p. ej. sólo había un fichaje): campo de sección con sello.
    const sec = sectionStyle(seccion);
    return (
      <AbsoluteFill style={{ background: `linear-gradient(150deg, ${sec.field} 0%, ${C.ink} 85%)`, alignItems: "center", justifyContent: "center" }}>
        <Grain opacity={0.08} />
        <div style={{ ...display(220, rgba(C.white, 0.08), 900, "condensed"), position: "absolute", left: -20, bottom: 40, whiteSpace: "nowrap" }}>{sec.label.toUpperCase()}</div>
        <Seal size={230} style={{ opacity: 0.9, transform: `scale(${mix(p(frame, 0, duration, EASE.camera), 1.05, 1)})` }} />
      </AbsoluteFill>
    );
  }
  // Un video ocupa todo el bloque; las fotos se reparten el tiempo.
  const first = media[0];
  if (first.type === "video") {
    return <MediaFill item={first} duration={duration} variant={0} />;
  }
  const slot = Math.max(30, Math.floor(duration / media.length));
  return (
    <AbsoluteFill>
      {media.map((m, i) => {
        const from = i * slot;
        const len = i === media.length - 1 ? duration - from : slot + fade;
        if (len <= 0) return null;
        const opacity = i === 0 ? 1 : p(frame, from, fade, EASE.inOut);
        return (
          <Sequence key={i} from={from} durationInFrames={len} layout="none">
            <AbsoluteFill style={{ opacity }}>
              <MediaFill item={m} duration={len} variant={i} />
            </AbsoluteFill>
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};

// Cortina de color entre escenas.
const Wipe: React.FC<{ at: number; color: string }> = ({ at, color }) => {
  const frame = useCurrentFrame();
  if (frame < at - 9 || frame > at + 11) return null;
  const inT = p(frame, at - 9, 9, EASE.snap);
  const outT = p(frame, at, 11, EASE.snap);
  const top = mix(inT, 100, 0) + mix(outT, 0, -100);
  return (
    <AbsoluteFill style={{ transform: `translateY(${top}%)` }}>
      <AbsoluteFill style={{ backgroundColor: color }} />
      <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: 18, backgroundColor: C.white, opacity: 0.9 }} />
    </AbsoluteFill>
  );
};

// ── Apertura en frío ─────────────────────────────────────────────────────
const ColdOpen: React.FC<{ media: MediaItem[]; teasers: string[]; duration: number; dateLabel: string }> = ({ media, teasers, duration, dateLabel }) => {
  const frame = useCurrentFrame();
  const items = media.length > 0 ? media : [];
  // Cada titular va con la foto de su nota (media[k] ↔ teasers[k]); el ritmo
  // lo dan cortes de encuadre sobre esa misma foto cada medio segundo. La
  // frase final ("Son las nueve…") recorre el resto de las fotos.
  const CUT = 15;
  const index = Math.floor(frame / CUT);
  const local = frame - index * CUT;
  const teaserSpan = teasers.length > 0 ? Math.floor(duration * 0.72) : 0;
  const teaserSlot = Math.max(CUT, Math.floor(teaserSpan / Math.max(1, teasers.length)));
  const inTeasers = frame < teaserSlot * teasers.length;
  const teaserIndex = inTeasers ? Math.floor(frame / teaserSlot) : -1;
  const teaserLocal = inTeasers ? frame - teaserIndex * teaserSlot : frame - teaserSlot * teasers.length;
  const teaser = inTeasers ? teasers[teaserIndex] : "";
  const item = items.length === 0 ? null : inTeasers ? items[teaserIndex % items.length] : items[(teasers.length + index) % items.length];
  const crops = [
    { z: 1.0, o: "50% 50%" },
    { z: 1.2, o: "32% 40%" },
    { z: 1.1, o: "68% 36%" },
    { z: 1.3, o: "50% 66%" },
  ];
  const crop = crops[index % crops.length];
  const flash = index === 0 ? (local < 3 ? mix(local / 3, 0.9, 0) : 0) : local < 1 ? 0.12 : 0;
  const punch = crop.z * interpolate(local, [0, 5], [1.1, 1.0], { ...clamp, easing: EASE.out });
  const shake = teaserLocal < 6 ? Math.sin(teaserLocal * 2.4) * (6 - teaserLocal) * 1.6 : 0;
  const tease = fit({ text: teaser.toUpperCase(), maxWidth: SAFE_R - M, maxHeight: 330, min: 64, max: 118, weight: 900, lh: 0.96, stretch: "condensed", maxLines: 3 });
  const top = p(frame, 0, 10);
  return (
    <AbsoluteFill style={{ backgroundColor: C.ink }}>
      {item && item.file ? (
        <AbsoluteFill style={{ transform: `scale(${punch}) translateX(${shake}px)`, transformOrigin: crop.o }}>
          <MediaFill item={item} duration={CUT} variant={index} fromScale={1.06} />
        </AbsoluteFill>
      ) : (
        // Sin imagen apta para ese titular: campo rojo con el sello.
        <AbsoluteFill style={{ background: `radial-gradient(ellipse 80% 60% at 50% 40%, ${C.red} 0%, ${C.ink} 80%)`, alignItems: "center", justifyContent: "center" }}>
          <Seal size={300} style={{ marginTop: -280, opacity: 0.95, transform: `scale(${punch})` }} />
        </AbsoluteFill>
      )}
      <AbsoluteFill style={{ background: `linear-gradient(180deg, ${rgba(C.ink, 0.55)} 0%, ${rgba(C.ink, 0.1)} 30%, ${rgba(C.ink, 0.25)} 52%, ${rgba(C.ink, 0.92)} 78%)` }} />
      <Vignette strength={0.7} />
      <PoliceLights strength={0.9} />
      <Grain opacity={0.07} />
      <div style={{ position: "absolute", left: M, top: 250, display: "flex", alignItems: "center", gap: 18, opacity: top }}>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 12, backgroundColor: C.red, padding: "12px 18px", ...caps(26, C.white, 900, 0.16) }}>
          <span style={{ width: 14, height: 14, borderRadius: "50%", backgroundColor: C.white, opacity: frame % 30 < 18 ? 1 : 0.25 }} />
          Hoy en La Rioja
        </span>
        <span style={caps(24, rgba(C.white, 0.85), 700, 0.14)}>{dateLabel}</span>
      </div>
      {teaser ? (
        <div style={{ position: "absolute", left: M, right: W - SAFE_R, top: 1180, display: "flex", flexDirection: "column", gap: 22 }}>
          <div style={{ height: 8, width: mix(p(teaserLocal, 0, 8), 0, 180), backgroundColor: C.red }} />
          <div
            style={{
              ...display(tease.fontSize, C.white, 900, "condensed"),
              lineHeight: `${tease.lineHeight}px`,
              textShadow: "0 8px 40px rgba(0,0,0,0.6)",
              transform: `scale(${interpolate(teaserLocal, [0, 5], [1.12, 1], { ...clamp, easing: EASE.out })})`,
              transformOrigin: "left bottom",
            }}
          >
            {tease.lines.map((l, i) => (
              <div key={i}>{l}</div>
            ))}
          </div>
        </div>
      ) : null}
      <AbsoluteFill style={{ backgroundColor: C.white, opacity: flash }} />
    </AbsoluteFill>
  );
};

// ── Sello "21 H" ─────────────────────────────────────────────────────────
const Ident: React.FC<{ dateLabel: string }> = ({ dateLabel }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const band = p(frame, 0, 10, EASE.snap);
  const seal = sp(frame, 4, fps, SPRING.punch);
  const big = sp(frame, 8, fps, SPRING.punch);
  const sub = p(frame, 16, 14);
  return (
    <AbsoluteFill style={{ backgroundColor: C.ink }}>
      <AbsoluteFill style={{ backgroundColor: C.red, clipPath: `inset(0 ${mix(band, 100, 0)}% 0 0)` }} />
      <AbsoluteFill style={{ background: `linear-gradient(160deg, ${rgba(C.ink, 0)} 30%, ${rgba(C.ink, 0.55)} 100%)` }} />
      <Grain opacity={0.06} />
      <div style={{ position: "absolute", left: M, right: W - SAFE_R, top: 560, display: "flex", flexDirection: "column", gap: 34 }}>
        <Seal size={170} style={{ transform: `scale(${mix(seal, 0.6, 1)})`, opacity: Math.min(1, seal * 1.4), filter: "drop-shadow(0 18px 40px rgba(0,0,0,0.45))" }} />
        <div style={{ ...caps(34, C.white, 900, 0.22), opacity: sub }}>Noticiero de la noche</div>
        <div style={{ display: "flex", alignItems: "flex-end", gap: 26, transform: `translateY(${mix(big, 60, 0)}px)`, opacity: Math.min(1, big * 1.5) }}>
          <span style={{ fontFamily: `"${V2_FONT_SERIF}"`, fontWeight: 700, fontSize: 300, lineHeight: 0.82, letterSpacing: "-0.04em", color: C.white }}>21</span>
          <span style={{ ...display(150, C.white, 900, "condensed"), lineHeight: 0.85, paddingBottom: 8 }}>H</span>
        </div>
        <div style={{ height: 6, width: mix(sub, 0, 520), backgroundColor: C.white }} />
        <div style={{ ...caps(30, rgba(C.white, 0.9), 700, 0.16), opacity: sub }}>{dateLabel} · La Rioja</div>
      </div>
    </AbsoluteFill>
  );
};

// ── Bloque de noticia ────────────────────────────────────────────────────
const Progress: React.FC<{ total: number; current: number; t: number }> = ({ total, current, t }) => (
  <div style={{ position: "absolute", left: M, right: W - SAFE_R, top: 232, display: "flex", gap: 8 }}>
    {Array.from({ length: total }).map((_, i) => (
      <div key={i} style={{ flex: 1, height: 6, backgroundColor: rgba(C.white, 0.25), overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${i < current ? 100 : i === current ? t * 100 : 0}%`, backgroundColor: C.white }} />
      </div>
    ))}
  </div>
);

const Masthead: React.FC<{ dateLabel: string }> = ({ dateLabel }) => {
  const frame = useCurrentFrame();
  return (
    <div style={{ position: "absolute", left: M, right: W - SAFE_R, top: 262, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <Seal size={58} />
        <span style={caps(23, C.white, 900, 0.16)}>Noticiero 21 H</span>
      </div>
      <span style={{ display: "inline-flex", alignItems: "center", gap: 10, ...caps(20, rgba(C.white, 0.85), 700, 0.12) }}>
        <span style={{ width: 12, height: 12, borderRadius: "50%", backgroundColor: C.red, opacity: frame % 30 < 18 ? 1 : 0.3 }} />
        {dateLabel}
      </span>
    </div>
  );
};

const BlockScene: React.FC<{ block: BlockItem; index: number; total: number; duration: number; dateLabel: string }> = ({ block, index, total, duration, dateLabel }) => {
  const frame = useCurrentFrame();
  const sec = sectionStyle(block.seccion);
  const policial = sec.key === "policiales";
  const panelTop = 340;
  const panelH = 800;
  const panelBottom = panelTop + panelH;
  const enter = p(frame, 4, 16);
  const num = p(frame, 2, 14);
  const line = p(frame, 12, 18);
  const band = p(frame, 0, 12, EASE.snap);
  const lights = policial ? interpolate(frame, [0, 10, 34, 48], [0, 1, 1, 0], clamp) : 0;
  const headline = fit({ text: block.titulo, maxWidth: SAFE_R - M, maxHeight: 1500 - (panelBottom + 150), min: 52, max: 84, weight: 850, lh: 1.02, stretch: "semi-condensed", maxLines: 3 });
  const bg = block.media.find((m) => m.type === "image");
  return (
    <AbsoluteFill style={{ backgroundColor: C.ink }}>
      {bg ? (
        <Img src={staticFile(bg.file)} style={{ position: "absolute", inset: -100, width: W + 200, height: H + 200, objectFit: "cover", filter: "blur(54px) brightness(0.42) saturate(1.1)" }} />
      ) : null}
      <AbsoluteFill style={{ background: `linear-gradient(180deg, ${rgba(C.ink, 0.6)} 0%, ${rgba(C.ink, 0.3)} 36%, ${rgba(C.ink, 0.92)} 66%)` }} />
      <Grain opacity={0.05} />
      <Progress total={total} current={index} t={p(frame, 0, duration, (x) => x)} />
      <Masthead dateLabel={dateLabel} />
      <div style={{ position: "absolute", left: 0, top: panelTop, width: W, height: panelH, overflow: "hidden", boxShadow: "0 30px 80px rgba(0,0,0,0.55)" }}>
        <MediaReel media={block.media} duration={duration} seccion={block.seccion} />
        <AbsoluteFill style={{ background: `linear-gradient(180deg, rgba(0,0,0,0) 58%, ${rgba(C.ink, 0.8)} 100%)` }} />
        {policial ? <AbsoluteFill style={{ opacity: lights }}><PoliceLights strength={0.85} /></AbsoluteFill> : null}
      </div>
      {/* Banda de sección: entra con un corte seco y deja el rótulo. */}
      <div style={{ position: "absolute", left: 0, top: panelBottom - 6, height: 12, width: `${mix(band, 0, 100)}%`, backgroundColor: sec.field }} />
      <div
        style={{
          position: "absolute",
          left: M - 6,
          top: panelBottom - 210,
          fontFamily: `"${V2_FONT_SERIF}"`,
          fontWeight: 700,
          fontSize: 230,
          lineHeight: 1,
          color: C.white,
          textShadow: "0 10px 40px rgba(0,0,0,0.6)",
          opacity: num,
          transform: `translateY(${mix(num, 36, 0)}px)`,
        }}
      >
        {String(index + 1).padStart(2, "0")}
      </div>
      <div
        style={{
          position: "absolute",
          left: M,
          right: W - SAFE_R,
          top: panelBottom + 48,
          display: "flex",
          flexDirection: "column",
          gap: 24,
          opacity: enter,
          transform: `translateY(${mix(enter, 36, 0)}px)`,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "nowrap" }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 12, backgroundColor: sec.field, padding: "12px 18px", ...caps(25, C.white, 900, 0.16) }}>
            {policial ? <span style={{ width: 12, height: 12, borderRadius: "50%", backgroundColor: frame % 8 < 4 ? "#FF4D57" : "#4D7DFF" }} /> : null}
            {sec.label}
          </span>
          {block.lugar ? <span style={{ border: `2px solid ${rgba(C.white, 0.6)}`, padding: "10px 16px", ...caps(23, C.white, 800, 0.12) }}>{block.lugar}</span> : null}
        </div>
        <div style={{ height: 4, width: mix(line, 0, 200), backgroundColor: sec.accent === C.blue ? C.white : C.red }} />
        <div style={{ ...display(headline.fontSize, C.white, 850), lineHeight: `${headline.lineHeight}px` }}>
          {headline.lines.map((l, i) => (
            <div key={i}>{l}</div>
          ))}
        </div>
      </div>
      {block.credit ? (
        <div style={{ position: "absolute", left: M, top: 1500, ...caps(19, rgba(C.white, 0.62), 700, 0.12), opacity: enter }}>{block.credit}</div>
      ) : null}
    </AbsoluteFill>
  );
};

// ── Cierre ───────────────────────────────────────────────────────────────
const OutroScene: React.FC<{ strip: MediaItem[] }> = ({ strip }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const seal = sp(frame, 2, fps, SPRING.punch);
  const word = p(frame, 10, 16);
  const line = p(frame, 18, 16);
  const pill = sp(frame, 26, fps, SPRING.punch);
  const pulse = 1 + Math.max(0, Math.sin((frame - 40) / 7)) * 0.025 * (frame > 40 ? 1 : 0);
  const images = strip.filter((m) => m.type === "image").slice(0, 5);
  return (
    <AbsoluteFill style={{ backgroundColor: C.ink }}>
      {/* Tira con las fotos de la edición, desenfocada al fondo. */}
      <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: H, display: "flex", opacity: 0.32, filter: "blur(6px) grayscale(0.3)" }}>
        {images.map((m, i) => (
          <div key={i} style={{ flex: 1, height: "100%", overflow: "hidden", transform: `translateY(${(i % 2 === 0 ? -1 : 1) * mix(p(frame, 0, 120, EASE.camera), 40, 0)}px)` }}>
            <Img src={staticFile(m.file)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
          </div>
        ))}
      </div>
      <AbsoluteFill style={{ background: `linear-gradient(180deg, ${rgba(C.ink, 0.7)} 0%, ${rgba(C.ink, 0.92)} 45%, ${rgba(C.ink, 0.97)} 100%)` }} />
      <Grain opacity={0.06} />
      <div style={{ position: "absolute", left: 0, right: 0, top: 470, display: "flex", flexDirection: "column", alignItems: "center", gap: 40 }}>
        <Seal size={240} style={{ transform: `scale(${mix(seal, 0.55, 1)})`, opacity: Math.min(1, seal * 1.4), filter: "drop-shadow(0 20px 50px rgba(0,0,0,0.5))" }} />
        <div style={{ display: "flex", alignItems: "baseline", gap: 20, ...display(84, C.white, 900, "condensed"), letterSpacing: "0.04em", opacity: word, transform: `translateY(${mix(word, 24, 0)}px)` }}>
          <span>LA VOZ</span>
          <span>RIOJANA</span>
        </div>
        <div style={{ height: 4, width: mix(line, 0, 300), backgroundColor: C.red }} />
        <div style={{ ...serif(44, rgba(C.white, 0.88)), opacity: line, textAlign: "center" }}>Todas las noches, a las 21</div>
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, top: 1210, display: "flex", flexDirection: "column", alignItems: "center", gap: 30 }}>
        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 18,
            backgroundColor: C.red,
            padding: "26px 46px",
            borderRadius: 999,
            boxShadow: "0 20px 50px rgba(179,0,0,0.45)",
            transform: `scale(${mix(pill, 0.7, 1) * pulse})`,
            opacity: Math.min(1, pill * 1.5),
            ...caps(34, C.white, 900, 0.1),
          }}
        >
          <span>Seguí @lavozriojana</span>
        </div>
        <div style={{ ...caps(26, rgba(C.white, 0.75), 700, 0.16), opacity: Math.min(1, pill * 1.5) }}>Las notas completas en lavozriojana.com</div>
      </div>
    </AbsoluteFill>
  );
};

// ── Composición ──────────────────────────────────────────────────────────
export const NightlyNewscastV2: React.FC<NightlyNewscastV2Props> = (props) => {
  const ready = useV2FontsReady();
  if (!ready) return <AbsoluteFill style={{ backgroundColor: C.ink }} />;
  const tl = newscastTimeline(props);
  const n = props.blocks.length;
  const voiceRanges: [number, number][] = [
    [NEWSCAST.hookVoiceDelay, NEWSCAST.hookVoiceDelay + props.hook.voiceFrames],
    ...props.blocks.map((b, i) => [tl.blocks[i].from + NEWSCAST.blockVoiceDelay, tl.blocks[i].from + NEWSCAST.blockVoiceDelay + b.voiceFrames] as [number, number]),
    [tl.outroStart + NEWSCAST.outroVoiceDelay, tl.outroStart + NEWSCAST.outroVoiceDelay + props.outro.voiceFrames],
  ];
  // Música: entra con el sello, baja bajo cada locución y se apaga al final.
  const bedVolume = (f: number) => {
    const abs = f + tl.identStart;
    const talking = voiceRanges.some(([a, b]) => abs >= a - 4 && abs <= b + 4);
    const base = talking ? 0.1 : 0.3;
    const fadeIn = interpolate(abs, [tl.identStart, tl.identStart + 6], [0, 1], clamp);
    const fadeOut = interpolate(abs, [tl.total - 40, tl.total - 2], [1, 0], clamp);
    return base * fadeIn * fadeOut;
  };
  const allImages = props.blocks.flatMap((b) => b.media.filter((m) => m.type === "image").slice(0, 1));
  return (
    <AbsoluteFill style={{ backgroundColor: C.ink }}>
      <Sequence durationInFrames={tl.hook}>
        <ColdOpen media={props.hook.media} teasers={props.hook.teasers} duration={tl.hook} dateLabel={props.dateLabel} />
      </Sequence>
      <Sequence from={tl.identStart} durationInFrames={NEWSCAST.ident}>
        <Ident dateLabel={props.dateLabel} />
      </Sequence>
      {props.blocks.map((block, i) => (
        <Sequence key={`b${i}`} from={tl.blocks[i].from} durationInFrames={tl.blocks[i].duration}>
          <BlockScene block={block} index={i} total={n} duration={tl.blocks[i].duration} dateLabel={props.dateLabel} />
        </Sequence>
      ))}
      <Sequence from={tl.outroStart} durationInFrames={tl.outro}>
        <OutroScene strip={allImages} />
      </Sequence>
      {props.blocks.map((block, i) => (
        <Wipe key={`w${i}`} at={tl.blocks[i].from} color={sectionStyle(block.seccion).field} />
      ))}
      <Wipe at={tl.outroStart} color={C.red} />

      {/* Sonido */}
      <Sequence durationInFrames={tl.hook + 10}>
        <Audio src={staticFile("newscast/siren.mp3")} volume={(f) => interpolate(f, [0, 3, 40, tl.hook], [0.0, 0.85, 0.32, 0.0], clamp)} />
      </Sequence>
      <Sequence from={tl.identStart}>
        <Audio src={staticFile("newscast/impact.mp3")} volume={0.9} />
      </Sequence>
      <Sequence from={tl.identStart} durationInFrames={tl.total - tl.identStart}>
        <Audio src={staticFile("newscast/bed.mp3")} loop volume={bedVolume} />
      </Sequence>
      {props.blocks.map((_, i) => (
        <Sequence key={`s${i}`} from={Math.max(0, tl.blocks[i].from - 9)}>
          <Audio src={staticFile("newscast/whoosh.mp3")} volume={0.55} />
        </Sequence>
      ))}
      <Sequence from={Math.max(0, tl.outroStart - 9)}>
        <Audio src={staticFile("newscast/whoosh.mp3")} volume={0.55} />
      </Sequence>
      <Sequence from={tl.outroStart}>
        <Audio src={staticFile("newscast/sting.mp3")} volume={(f) => interpolate(f, [0, 10, tl.outro - 30, tl.outro], [0.5, 0.42, 0.3, 0], clamp)} />
      </Sequence>

      {/* Locución */}
      <Sequence from={NEWSCAST.hookVoiceDelay}>
        <Audio src={staticFile(props.hook.voiceFile)} />
      </Sequence>
      {props.blocks.map((block, i) => (
        <Sequence key={`v${i}`} from={tl.blocks[i].from + NEWSCAST.blockVoiceDelay}>
          <Audio src={staticFile(block.voiceFile)} />
        </Sequence>
      ))}
      <Sequence from={tl.outroStart + NEWSCAST.outroVoiceDelay}>
        <Audio src={staticFile(props.outro.voiceFile)} />
      </Sequence>
    </AbsoluteFill>
  );
};
