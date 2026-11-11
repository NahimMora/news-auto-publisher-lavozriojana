// NightlyNewscastV5 — noticiero policial vertical de La Voz Riojana.
//
// Ejecuta el plan de utils/newscast_v5.py:
//   apertura   en frío: el frame 0 ya es la noticia principal (foto, titular
//              legible en ~0,1 s); la marca abre como barra roja y se contrae
//              en el HUD (~1,4 s) sin cortar el contenido. Variantes
//              "rundown" (tres titulares que se abren) y "map" (lugares del
//              día) para comparar; el plan elige.
//   historias  tomas de ~2–3 s cortadas en pausas reales (general, detalle,
//              contraplano, mapa), titular grande → regleta superior, datos
//              cuando la voz los dice, subtítulos cinéticos abajo.
//   cierre     mosaico de las fotos del día, la frase de la voz en grande y
//              la cuenta.
import React from "react";
import { Audio } from "@remotion/media";
import { AbsoluteFill, Img, Sequence, interpolate, staticFile, useCurrentFrame } from "remotion";
import { fit } from "../fit";
import { useV2FontsReady } from "../fonts";
import { EASE, clamp, mix, p } from "../motion";
import type { NightlyNewscastV5Props, OpeningV5, StoryV5 } from "./schema";
import { MapShot, PhotoShot, Pin, Texture } from "./shots";
import { LA_RIOJA_PATH, LA_RIOJA_VIEW } from "./laRioja";
import { TRANSITION_FRAMES, Transition5 } from "./transitions";
import { C5, CONTENT_W5, L, alpha, caps5, sans, serif } from "./theme";
import { HeadlineSystem5, Hud5, Inserts5, KineticCaptions, Scrims5 } from "./typeLayers";

export { NightlyNewscastV5Schema } from "./schema";
export type { NightlyNewscastV5Props } from "./schema";

const dbToGain = (db: number) => Math.pow(10, db / 20);

function activeShot(story: StoryV5, frame: number) {
  return story.shots.find((s) => frame >= s.from && frame < s.from + s.durationInFrames) ?? story.shots[story.shots.length - 1];
}

// ── Historia ─────────────────────────────────────────────────────────────
const StoryScene5: React.FC<{ story: StoryV5 }> = ({ story }) => {
  const frame = useCurrentFrame();
  const shot = activeShot(story, frame);
  const focus = shot?.media?.focusX ?? 0.5;
  return (
    <AbsoluteFill style={{ backgroundColor: C5.ink }}>
      {story.shots.map((s, k) => (
        <Sequence key={k} from={s.from} durationInFrames={s.durationInFrames} layout="none">
          <AbsoluteFill>{s.kind === "map" ? <MapShot shot={s} /> : <PhotoShot shot={s} entering={k > 0} />}</AbsoluteFill>
        </Sequence>
      ))}
      <Texture />
      {shot?.kind === "map" ? null : <Scrims5 />}
      <HeadlineSystem5 story={story} lead={story.lead} />
      <Inserts5 items={story.inserts} side={focus < 0.5 ? "right" : "left"} />
    </AbsoluteFill>
  );
};

// HUD global: no se corta en las transiciones; índice y avance según el
// frame absoluto.
const GlobalHud: React.FC<{ props: NightlyNewscastV5Props }> = ({ props }) => {
  const frame = useCurrentFrame();
  if (frame >= props.outro.from) return null;
  const k = Math.max(0, props.stories.findIndex((s) => frame >= s.from && frame < s.from + s.durationInFrames));
  const story = props.stories[k];
  const progress = story ? interpolate(frame, [story.from, story.from + story.durationInFrames], [0, 1], clamp) : 0;
  return (
    <Hud5
      index={k}
      count={props.stories.length}
      progress={progress}
      kicker={props.edition.kicker}
      region={props.edition.region}
      dateLabel={props.edition.dateLabel}
      frame={frame}
      brandFrames={props.opening.brandFrames}
    />
  );
};

// ── Variantes de apertura (para comparar sobre el mismo material) ────────
const OPEN_OVERLAY = 34;

const OpeningOverlay: React.FC<{ opening: OpeningV5 }> = ({ opening }) => {
  const frame = useCurrentFrame();
  if (opening.style === "headline" || frame >= OPEN_OVERLAY) return null;
  // Sale en diagonal (firma del medio) entre los frames 22 y 34.
  const edge = interpolate(frame, [22, OPEN_OVERLAY], [-40, 140], { ...clamp, easing: EASE.inOut });
  const clip = `polygon(${edge + 18}% 0%, 100% 0%, 100% 100%, ${edge - 18}% 100%)`;
  return (
    <AbsoluteFill style={{ clipPath: clip, backgroundColor: C5.ink }}>
      {opening.style === "rundown" ? <Rundown opening={opening} /> : <PlacesMap opening={opening} />}
      <Texture />
    </AbsoluteFill>
  );
};

const Rundown: React.FC<{ opening: OpeningV5 }> = ({ opening }) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left: L.x0, top: 400, ...sans(120, 900), color: C5.white, opacity: p(frame, 0, 4) }}>RESUMEN EN</div>
      <div style={{ position: "absolute", left: L.x0, top: 510, ...sans(120, 900), color: C5.red }}>LA RIOJA</div>
      {opening.teasers.map((t, k) => {
        const tt = p(frame, 2 + k * 3, 8, EASE.out);
        const f = fit({ text: t.title.toUpperCase(), maxWidth: 520, maxHeight: 130, min: 38, max: 56, weight: 900, lh: 1.02, stretch: "condensed", maxLines: 2 });
        return (
          <div key={k} style={{ position: "absolute", left: L.x0, top: 700 + k * 200, width: CONTENT_W5, height: 176, display: "flex", backgroundColor: C5.bone, opacity: tt, transform: `translateX(${mix(tt, 120, 0)}px)`, boxShadow: "0 20px 50px rgba(0,0,0,0.45)" }}>
            {t.file ? <Img src={staticFile(t.file)} style={{ width: 260, height: 176, objectFit: "cover", objectPosition: `${t.focusX * 100}% ${t.focusY * 100}%` }} /> : null}
            <div style={{ padding: "18px 22px", display: "flex", flexDirection: "column", justifyContent: "center", gap: 6 }}>
              <span style={{ ...caps5(20, C5.red, 900, 0.14) }}>{String(k + 1).padStart(2, "0")}</span>
              {f.lines.map((l, i) => (
                <span key={i} style={{ ...sans(f.fontSize, 900), color: C5.ink }}>
                  {l}
                </span>
              ))}
            </div>
          </div>
        );
      })}
    </AbsoluteFill>
  );
};

const PlacesMap: React.FC<{ opening: OpeningV5 }> = ({ opening }) => {
  const frame = useCurrentFrame();
  const scale = L.mapW / LA_RIOJA_VIEW.w;
  const left = (L.w - L.mapW) / 2;
  return (
    <AbsoluteFill>
      <svg width={L.mapW} height={LA_RIOJA_VIEW.h * scale} viewBox={`0 0 ${LA_RIOJA_VIEW.w} ${LA_RIOJA_VIEW.h}`} style={{ position: "absolute", left, top: 520 }}>
        <path d={LA_RIOJA_PATH} fill={C5.ink3} stroke={C5.bone} strokeWidth={3.2} />
      </svg>
      {opening.places.map((pl, k) => {
        const t = p(frame, 3 + k * 3, 7, EASE.out);
        return (
          <div key={k} style={{ position: "absolute", left: left + pl.x * scale - 30, top: 520 + pl.y * scale - 60 - mix(t, 60, 0), opacity: t }}>
            <Pin size={60} color={C5.red} />
          </div>
        );
      })}
      <div style={{ position: "absolute", left: L.x0, top: 330, ...sans(110, 900), color: C5.white }}>RESUMEN POLICIAL</div>
      <div style={{ position: "absolute", left: L.x0, top: 450, ...caps5(34, C5.white, 900, 0.14) }}>{`${opening.count} hechos en La Rioja`}</div>
    </AbsoluteFill>
  );
};

// ── Cierre ───────────────────────────────────────────────────────────────
const Outro5: React.FC<{ outro: NightlyNewscastV5Props["outro"] }> = ({ outro }) => {
  const frame = useCurrentFrame();
  const tiles = outro.tiles.slice(0, 6);
  const cols = 2;
  const tileW = L.w / cols;
  const tileH = L.h / Math.max(1, Math.ceil(tiles.length / cols));
  const band = p(frame, 2, 12, EASE.out);
  const lines = outro.lines.length ? outro.lines : [{ text: "Lo que pasa en La Rioja", at: null }, { text: "lo sabés acá", at: null }, { text: "Seguinos", at: null }];
  return (
    <AbsoluteFill style={{ backgroundColor: C5.ink, overflow: "hidden" }}>
      {tiles.map((t, k) => {
        const tt = p(frame, k * 2, 12, EASE.out);
        return (
          <div key={k} style={{ position: "absolute", left: (k % cols) * tileW, top: Math.floor(k / cols) * tileH, width: tileW, height: tileH, overflow: "hidden", opacity: tt }}>
            <Img
              src={staticFile(t.file)}
              style={{ width: "100%", height: "100%", objectFit: "cover", objectPosition: `${t.focusX * 100}% ${t.focusY * 100}%`, transform: `scale(${mix(tt, 1.25, 1.06) + frame * 0.0008})`, filter: "grayscale(0.2) brightness(0.58) contrast(1.08)" }}
            />
          </div>
        );
      })}
      <AbsoluteFill style={{ background: `linear-gradient(180deg, ${alpha(C5.ink, 0.6)} 0%, ${alpha(C5.ink, 0.2)} 40%, ${alpha(C5.ink, 0.7)} 100%)` }} />
      <div style={{ position: "absolute", left: -120, top: 620, width: L.w + 240, height: 580, backgroundColor: C5.red, transform: `skewY(-6deg) translateX(${mix(band, -L.w * 1.3, 0)}px)`, boxShadow: "0 40px 90px rgba(0,0,0,0.5)" }} />
      <div style={{ position: "absolute", left: 0, right: 0, top: 360, display: "flex", justifyContent: "center" }}>
        <Img src={staticFile("logo.png")} style={{ width: 190, height: 190, objectFit: "contain", transform: `scale(${mix(p(frame, 0, 12, EASE.out), 0.7, 1)}) rotate(${mix(p(frame, 0, 14), -14, 0)}deg)`, filter: "drop-shadow(0 20px 50px rgba(0,0,0,0.5))" }} />
      </div>
      <div style={{ position: "absolute", left: L.x0, width: CONTENT_W5, top: 690, display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
        {lines.map((l, k) => {
          const at = (l.at ?? outro.from + 6 + k * 18) - outro.from;
          const last = k === lines.length - 1;
          const f = fit({ text: l.text.toUpperCase(), maxWidth: CONTENT_W5 - (last ? 80 : 0), maxHeight: 2 * 118, min: 70, max: last ? 120 : 112, weight: 900, lh: 1, stretch: "condensed", maxLines: 2 });
          return (
            <div key={k} style={{ display: "flex", flexDirection: "column", alignItems: "center", marginTop: last ? 18 : 0 }}>
              {f.lines.map((line, j) => (
                <div key={j} style={{ overflow: "hidden", height: f.fontSize * 1.16, paddingTop: f.fontSize * 0.12 }}>
                  <div style={{ ...sans(f.fontSize, 900), color: last ? C5.red : C5.white, backgroundColor: last ? C5.white : "transparent", padding: last ? "4px 34px 0" : 0, transform: `translateY(${mix(p(frame, at + j * 2, 8, EASE.out), f.fontSize * 1.3, 0)}px)` }}>
                    {line}
                  </div>
                </div>
              ))}
            </div>
          );
        })}
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, top: 1345, display: "flex", flexDirection: "column", alignItems: "center", gap: 14, opacity: p(frame, 16, 10), transform: `translateY(${mix(p(frame, 16, 12, EASE.out), 20, 0)}px)` }}>
        <span style={{ ...sans(56, 900), color: C5.white, letterSpacing: "0.01em" }}>{outro.cta}</span>
        <span style={{ ...serif(36, alpha(C5.white, 0.85)) }}>{`Las notas completas, en ${outro.site}`}</span>
      </div>
    </AbsoluteFill>
  );
};

// ── Composición ──────────────────────────────────────────────────────────
export const NightlyNewscastV5: React.FC<NightlyNewscastV5Props> = (props) => {
  const ready = useV2FontsReady();
  if (!ready) return <AbsoluteFill style={{ backgroundColor: C5.ink }} />;
  const voiceRanges = [...props.voices, ...(props.outro.voice ? [props.outro.voice] : [])].map((v) => [v.from, v.from + v.durationInFrames] as const);
  const music = props.music;
  const musicVolume = (f: number) => {
    if (!music) return 0;
    const near = Math.min(...voiceRanges.map(([a, b]) => (f < a ? a - f : f >= b ? f - b : 0)));
    const open = Math.min(1, Math.max(0, (near - 2) / 8));
    // Más presencia en el primer segundo y medio (la marca abre con música).
    const hook = f < 45 ? music.introGainDb - music.gainDb : 0;
    const db = mix(open, music.gainDb, music.openGainDb) + hook * (1 - p(f, 30, 15));
    const fadeOut = interpolate(f, [props.totalFrames - 26, props.totalFrames - 1], [1, 0], clamp);
    return dbToGain(db) * fadeOut;
  };
  const cues = props.captions.filter((c) => c.to <= props.outro.from);
  return (
    <AbsoluteFill style={{ backgroundColor: C5.ink }}>
      {props.stories.map((story, k) => (
        <Sequence key={k} from={story.from} durationInFrames={story.durationInFrames}>
          <StoryScene5 story={story} />
        </Sequence>
      ))}
      <Sequence from={props.outro.from} durationInFrames={props.outro.durationInFrames}>
        <Outro5 outro={props.outro} />
      </Sequence>
      {props.stories.map((story, k) => (k > 0 ? <Transition5 key={`t${k}`} story={story} at={story.from} kind={story.wipe} /> : null))}
      <Transition5 story={null} at={props.outro.from} kind="brand" />
      <GlobalHud props={props} />
      <KineticCaptions cues={cues} />
      <OpeningOverlay opening={props.opening} />

      {/* Sonido */}
      {music ? <Audio src={staticFile(music.file)} loop volume={musicVolume} /> : null}
      {props.sfx.map((s, k) => (
        <Sequence key={`fx${k}`} from={Math.max(0, s.from)} durationInFrames={s.file.endsWith("sting.mp3") ? Math.max(1, props.totalFrames - s.from) : 75}>
          <Audio src={staticFile(s.file)} volume={(f) => s.volume * (s.file.endsWith("sting.mp3") ? interpolate(f, [0, 60, 110], [1, 0.7, 0], clamp) : 1)} />
        </Sequence>
      ))}
      {props.voices.map((v, k) => (
        <Sequence key={`v${k}`} from={v.from} durationInFrames={v.durationInFrames}>
          <Audio src={staticFile(v.file)} />
        </Sequence>
      ))}
      {props.outro.voice ? (
        <Sequence from={props.outro.voice.from} durationInFrames={props.outro.voice.durationInFrames}>
          <Audio src={staticFile(props.outro.voice.file)} />
        </Sequence>
      ) : null}
      {props.edition.testBanner ? (
        <div style={{ position: "absolute", left: 0, right: 0, top: 180, display: "flex", justifyContent: "center" }}>
          <span style={{ ...caps5(22, C5.ink, 900, 0.12), backgroundColor: "#F2C94C", padding: "6px 14px" }}>{props.edition.testBanner}</span>
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

export { TRANSITION_FRAMES };
