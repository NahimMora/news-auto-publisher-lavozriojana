// NightlyNewscastV3 — noticiero policial vertical de La Voz Riojana (V4).
//
// Ejecuta el plan de utils/newscast_v3.py. Estructura:
//   apertura   4–7 s: cada frase del gancho con la imagen de SU hecho, cortada
//              cuando la voz la dice; frase en pantalla por máscara; cierre de
//              la apertura con la marca y un mosaico de esos hechos.
//   historias  cada una con su familia: el titular entra por máscara con la
//              palabra clave resaltada, se contrae en regleta en la primera
//              pausa real; lugar, cantidades, cifras y términos clave entran
//              cuando la voz los dice; subtítulos abajo con la palabra activa.
//   cierre     2–4 s: la voz y el texto grande dicen lo mismo; invitación a
//              seguir la cuenta. Sin subtítulos de la noticia anterior.
// Transiciones propias (barrido en diagonal, cortina, lugar, iris), efectos
// sutiles en cada dato y música con presencia que baja bajo la voz.
import React from "react";
import { Audio } from "@remotion/media";
import { AbsoluteFill, Img, Sequence, interpolate, staticFile, useCurrentFrame } from "remotion";
import { fit } from "../fit";
import { useV2FontsReady } from "../fonts";
import { EASE, clamp, mix, p } from "../motion";
import {
  CONTENT_W,
  Captions,
  EmphasisLayer,
  G,
  HeroFit,
  HeroLines,
  Hud,
  MediaLayer,
  P,
  PlaceChip,
  Regleta,
  Scrims,
  Transition,
  TypeBackdrop,
  alpha,
  caps,
  chooseHero,
  font,
  rise,
} from "./primitives";
import type { CaptionPlan, IntroPlan, NightlyNewscastV3Props, ShotPlan, StoryPlan } from "./schema";

export { NightlyNewscastV3Schema } from "./schema";
export type { NightlyNewscastV3Props } from "./schema";

const dbToGain = (db: number) => Math.pow(10, db / 20);

function activeEvent(story: StoryPlan, frame: number) {
  return story.events.find((e) => frame >= e.from && frame < e.to) ?? story.events[story.events.length - 1] ?? null;
}

function activeShot(story: StoryPlan, frame: number): ShotPlan {
  return story.shots.find((s) => frame >= s.from && frame < s.from + s.durationInFrames) ?? story.shots[story.shots.length - 1];
}

function storyLayout(story: StoryPlan): "full" | "window" | "type" {
  const media = story.shots.filter((s) => s.media);
  if (!media.length) return "type";
  if (story.family === "judicial") return "window";
  return media.some((s) => s.layout === "window") ? "window" : "full";
}

function tagFor(story: StoryPlan, frame: number): string {
  if (story.family === "judicial") return "Justicia";
  if (story.family === "brief") return "En breve";
  if (story.family === "related" && story.events.length > 1) {
    const e = activeEvent(story, frame);
    return `Hecho ${(e?.index ?? 0) + 1}/${story.events.length}`;
  }
  const s = (story.seccion || "").toLowerCase();
  return s === "policiales" ? "Policiales" : s ? s.charAt(0).toUpperCase() + s.slice(1) : "La Rioja";
}

// ── Escenario de imagen (tomas en secuencia) ─────────────────────────────
const Stage: React.FC<{ story: StoryPlan; layout: "full" | "window"; panelH: number }> = ({ story, layout, panelH }) => (
  <>
    {story.shots.map((shot, k) => (
      <Sequence key={k} from={shot.from} durationInFrames={shot.durationInFrames} layout="none">
        {shot.media ? (
          <div
            style={{
              position: "absolute",
              left: 0,
              top: 0,
              width: G.w,
              height: layout === "full" ? G.h : panelH,
              overflow: "hidden",
              clipPath: layout === "window" ? "polygon(0 0, 100% 0, 100% 100%, 0 93%)" : undefined,
            }}
          >
            <MediaLayer shot={shot} layout={layout} punch={story.principal && k === 0 ? 16 : story.family === "brief" && k === 0 ? 10 : k > 0 ? 8 : 0} />
          </div>
        ) : null}
      </Sequence>
    ))}
  </>
);

// Titular grande → regleta en la primera pausa real.
const HeadlineSystem: React.FC<{ story: StoryPlan; hero: HeroFit; heroTop: number; color?: string; boxColor?: string }> = ({ story, hero, heroTop, color = P.white, boxColor }) => {
  const frame = useCurrentFrame();
  const switchAt = Math.min(story.compactAt, story.durationInFrames - 12);
  const exit = interpolate(frame, [switchAt, switchAt + 9], [0, 1], { ...clamp, easing: EASE.in });
  const slam = story.family === "brief" && !story.principal ? interpolate(frame, [0, 7], [1.1, 1], { ...clamp, easing: EASE.out }) : 1;
  return (
    <>
      {frame < switchAt + 12 ? (
        <div style={{ position: "absolute", left: G.x0, width: CONTENT_W, top: heroTop, transform: `scale(${slam})`, transformOrigin: "left bottom" }}>
          <HeroLines hero={hero} keyword={story.keyword} start={story.principal ? 0 : 1} color={color} exit={exit} boxColor={boxColor} />
          <div style={{ height: 7, marginTop: 14, width: `${p(frame, 6, 10, EASE.snap) * (1 - exit) * 34}%`, backgroundColor: P.red }} />
        </div>
      ) : null}
      {frame >= switchAt ? <Regleta tag={tagFor(story, frame)} text={story.tituloCorto || story.titulo} start={switchAt + 3} /> : null}
    </>
  );
};

// ── Historia con imagen ──────────────────────────────────────────────────
const MediaStory: React.FC<{ story: StoryPlan; cues: CaptionPlan[]; count: number }> = ({ story, cues, count }) => {
  const frame = useCurrentFrame();
  const layout = storyLayout(story) as "full" | "window";
  const shot = activeShot(story, frame);
  const event = activeEvent(story, frame);
  const judicial = story.family === "judicial";
  const panelH = G.panelH;
  const hero = chooseHero(story.titulo, story.tituloCorto, {
    min: 78,
    max: story.principal ? 136 : story.family === "brief" ? 118 : 120,
    maxHeight: 400,
    maxLines: 3,
  });
  const heroTop = G.heroBottom - hero.height - 20;
  const focus = shot.media?.focusX ?? 0.5;
  const side: "left" | "right" = focus < 0.5 ? "right" : "left";
  const lowerColor = P.ink;
  return (
    <AbsoluteFill style={{ backgroundColor: P.ink }}>
      {layout === "window" ? <div style={{ position: "absolute", left: 0, top: panelH - 120, width: G.w, height: G.h - panelH + 120, backgroundColor: lowerColor }} /> : null}
      <Stage story={story} layout={layout} panelH={panelH} />
      {layout === "full" ? <Scrims /> : <AbsoluteFill style={{ background: `linear-gradient(180deg, ${alpha(P.ink, 0.65)} 0%, ${alpha(P.ink, 0)} 18%)` }} />}
      {layout === "window" ? (
        <div style={{ position: "absolute", left: 0, top: panelH - 84, width: G.w, height: 10, backgroundColor: judicial ? P.bone : P.red, transform: "skewY(-4.3deg)", transformOrigin: "left" }} />
      ) : null}
      {layout === "window" ? (
        <div style={{ position: "absolute", left: 0, top: panelH - 330, width: G.w, height: 330, background: `linear-gradient(180deg, ${alpha(P.ink, 0)} 0%, ${alpha(P.ink, 0.75)} 100%)` }} />
      ) : null}
      {judicial ? (
        <div style={{ position: "absolute", left: G.x0, top: 316, display: "flex", alignItems: "center", gap: 12, ...rise(frame, 3, 14, 9) }}>
          <span style={{ ...caps(28, P.ink, 900, 0.16), backgroundColor: P.bone, padding: "8px 16px" }}>Justicia</span>
        </div>
      ) : null}
      <Hud index={story.index} count={count} progress={p(frame, 0, story.durationInFrames, (v) => v)} />
      {story.family === "related" && event && story.events.length > 1 ? (
        <div key={event.index} style={{ position: "absolute", left: G.x0, top: 330, ...rise(frame - event.from, 2, 16, 9) }}>
          <span style={{ ...font(150, 900), color: P.white, textShadow: "0 8px 40px rgba(0,0,0,0.6)" }}>
            {event.index + 1}
            <span style={{ ...font(70, 900), color: alpha(P.white, 0.6) }}>{`/${story.events.length}`}</span>
          </span>
          {event.lugar ? <PlaceChip text={event.lugar} top={170} /> : null}
        </div>
      ) : null}
      {story.family === "timeline" ? <TimelineRail story={story} top={G.barY - 80} /> : null}
      <HeadlineSystem story={story} hero={hero} heroTop={heroTop} color={P.white} boxColor={P.red} />
      <EmphasisLayer items={story.emphasis} side={side} top={(shot.media?.focusY ?? 0.5) < 0.42 ? 760 : 470} end={story.durationInFrames} />
      <Captions cues={cues} offset={story.from} />
    </AbsoluteFill>
  );
};

// ── Cronología ───────────────────────────────────────────────────────────
const TimelineRail: React.FC<{ story: StoryPlan; top: number }> = ({ story, top }) => {
  const frame = useCurrentFrame();
  const nodes = story.events.filter((e) => e.momento);
  return (
    <div style={{ position: "absolute", left: G.x0, top, width: CONTENT_W, height: 56, display: "flex", alignItems: "center" }}>
      {nodes.map((e, i) => {
        const active = frame >= e.from && frame < e.to;
        const past = frame >= e.to;
        return (
          <React.Fragment key={i}>
            {i > 0 ? <div style={{ flex: 1, height: 4, backgroundColor: past || active ? P.white : alpha(P.white, 0.3), transformOrigin: "left", transform: `scaleX(${Math.max(0.1, p(frame, e.from - 6, 8))})` }} /> : null}
            <span style={{ ...caps(28, P.white, 900, 0.06), padding: "10px 16px", backgroundColor: active ? P.red : alpha(P.ink, 0.7), border: `2px solid ${active ? P.red : alpha(P.white, 0.5)}` }}>{e.momento}</span>
          </React.Fragment>
        );
      })}
    </div>
  );
};

// ── Historia sin imagen propia: tipografía viva ──────────────────────────
const TypeStory: React.FC<{ story: StoryPlan; cues: CaptionPlan[]; count: number }> = ({ story, cues, count }) => {
  const frame = useCurrentFrame();
  const switchAt = Math.min(story.compactAt, story.durationInFrames - 12);
  const hero = chooseHero(story.titulo, story.tituloCorto, { min: 88, max: 140, maxHeight: 560, maxLines: 4 });
  const morph = interpolate(frame, [switchAt, switchAt + 12], [0, 1], { ...clamp, easing: EASE.inOut });
  const top = mix(morph, 980 - hero.height / 2, 330);
  const scale = mix(morph, 1, 0.66);
  const word = story.lugar || story.keyword || "";
  return (
    <AbsoluteFill>
      <TypeBackdrop word={word} duration={story.durationInFrames} />
      <Hud index={story.index} count={count} progress={p(frame, 0, story.durationInFrames, (v) => v)} />
      <div style={{ position: "absolute", left: G.x0, width: CONTENT_W, top, transform: `scale(${scale})`, transformOrigin: "left top" }}>
        <div style={{ ...caps(26, P.white, 900, 0.14), backgroundColor: P.red, padding: "6px 12px", display: "inline-block", marginBottom: 22, ...rise(frame, 2, 12, 8) }}>{tagFor(story, frame)}</div>
        <HeroLines hero={hero} keyword={story.keyword} start={story.principal ? 0 : 2} />
      </div>
      <EmphasisLayer items={story.emphasis.filter((e) => e.kind !== "tag" && e.at >= switchAt + 10)} side="left" top={760} chipTop={1180} end={story.durationInFrames} />
      <Captions cues={cues} offset={story.from} />
    </AbsoluteFill>
  );
};

// ── Servicio (se conserva para avisos con zona y vigencia) ───────────────
const ServiceStory: React.FC<{ story: StoryPlan; cues: CaptionPlan[]; count: number }> = ({ story, cues, count }) => {
  const frame = useCurrentFrame();
  const hero = chooseHero(story.servicio.accion || story.titulo, story.tituloCorto, { min: 72, max: 110, maxHeight: 340, maxLines: 3 });
  const rows: [string, string, number][] = [
    ["Zona", story.servicio.zona ?? "", 6],
    ["Vigencia", story.servicio.vigencia ?? "", 12],
  ];
  return (
    <AbsoluteFill style={{ backgroundColor: P.bone }}>
      <div style={{ position: "absolute", left: 0, top: 0, width: G.w, height: 300, backgroundColor: P.ink }} />
      <Hud index={story.index} count={count} progress={p(frame, 0, story.durationInFrames, (v) => v)} label="Servicio" />
      <div style={{ position: "absolute", left: G.x0, width: CONTENT_W, top: 420 }}>
        <HeroLines hero={hero} start={1} color={P.ink} />
      </div>
      <div style={{ position: "absolute", left: G.x0, width: CONTENT_W, top: 460 + hero.height + 40, display: "flex", flexDirection: "column", gap: 22 }}>
        {rows
          .filter(([, v]) => v)
          .map(([k, v, at]) => (
            <div key={k} style={{ borderLeft: `10px solid ${P.red}`, paddingLeft: 24, ...rise(frame, at, 14, 9) }}>
              <div style={caps(24, alpha(P.ink, 0.65), 900, 0.14)}>{k}</div>
              <div style={{ ...font(56, 900), color: P.ink, marginTop: 8, whiteSpace: "normal" }}>{v}</div>
            </div>
          ))}
      </div>
      <Captions cues={cues} offset={story.from} />
    </AbsoluteFill>
  );
};

// Hechos relacionados con encuadres distintos: cada hecho usa el suyo.
function splitByShot(story: StoryPlan): StoryPlan[] | null {
  const layouts = new Set(story.shots.map((s) => (s.media ? s.layout : "type")));
  if (story.family !== "related" || layouts.size < 2) return null;
  return story.shots.map((shot) => ({
    ...story,
    principal: story.principal && shot.from === 0,
    from: story.from + shot.from,
    durationInFrames: shot.durationInFrames,
    compactAt: story.compactAt - shot.from,
    shots: [{ ...shot, from: 0 }],
    emphasis: story.emphasis.filter((e) => e.at >= shot.from && e.at < shot.from + shot.durationInFrames).map((e) => ({ ...e, at: e.at - shot.from })),
    events: story.events.map((e) => ({ ...e, from: e.from - shot.from, to: e.to - shot.from, datoAt: e.datoAt === null ? null : e.datoAt - shot.from })),
  }));
}

const StoryScene: React.FC<{ story: StoryPlan; cues: CaptionPlan[]; count: number }> = ({ story, cues, count }) => {
  const parts = splitByShot(story);
  if (parts) {
    return (
      <>
        {parts.map((part, k) => (
          <Sequence key={k} from={part.from - story.from} durationInFrames={part.durationInFrames}>
            <StoryScene story={part} cues={cues} count={count} />
          </Sequence>
        ))}
      </>
    );
  }
  if (story.family === "service") return <ServiceStory story={story} cues={cues} count={count} />;
  const layout = storyLayout(story);
  if (layout === "type") return <TypeStory story={story} cues={cues} count={count} />;
  return <MediaStory story={story} cues={cues} count={count} />;
};

// ── Apertura ─────────────────────────────────────────────────────────────
const Intro: React.FC<{ intro: IntroPlan; dateLabel: string; descriptor: string }> = ({ intro, dateLabel, descriptor }) => {
  const frame = useCurrentFrame();
  const inTail = frame >= intro.tailFrom;
  const beat = intro.beats.find((b) => frame >= b.from && frame < b.to) ?? intro.beats[intro.beats.length - 1];
  const tailT = p(frame, intro.tailFrom, 12, EASE.snap);
  return (
    <AbsoluteFill style={{ backgroundColor: P.ink }}>
      {intro.beats.map((b, k) => (
        <Sequence key={k} from={b.from} durationInFrames={Math.max(1, b.to - b.from + (k === intro.beats.length - 1 ? 14 : 0))} layout="none">
          <AbsoluteFill>
            {b.shot.media ? (
              <MediaLayer shot={{ ...b.shot, move: { scaleFrom: 1.16, scaleTo: 1.0, dx: 0, dy: 0 } }} layout="full" punch={10} />
            ) : (
              <TypeBackdrop word="" duration={b.to - b.from} />
            )}
          </AbsoluteFill>
        </Sequence>
      ))}
      <Scrims strength={1.05} />
      {!inTail && beat ? (
        <>
          <div style={{ position: "absolute", left: G.x0, top: G.hudY, display: "flex", alignItems: "center", gap: 12, ...rise(frame, 0, 10, 8) }}>
            <span style={{ ...caps(24, P.white, 900, 0.14), backgroundColor: P.red, padding: "8px 14px" }}>Noticiero policial</span>
            <span style={{ ...caps(22, P.white, 800, 0.12), textShadow: "0 2px 10px rgba(0,0,0,0.7)" }}>{dateLabel}</span>
          </div>
          {beat.text ? (
            <div key={beat.from} style={{ position: "absolute", left: G.x0, width: CONTENT_W, bottom: G.h - 1250 }}>
              <HeroLines hero={chooseHero(beat.text.replace(/\.$/, ""), "", { min: 86, max: 132, maxHeight: 440, maxLines: 4 })} start={beat.from + 1} />
              <div style={{ height: 8, marginTop: 14, width: `${p(frame, beat.from + 4, 8, EASE.snap) * 30}%`, backgroundColor: P.red }} />
            </div>
          ) : null}
        </>
      ) : null}
      {/* Cierre de la apertura: la marca sobre los hechos del día. */}
      {frame >= intro.tailFrom - 1 ? (
        <AbsoluteFill>
          <AbsoluteFill style={{ backgroundColor: P.red, clipPath: `polygon(0 0, ${tailT * 140}% 0, ${tailT * 140 - 40}% 100%, 0 100%)` }} />
          <AbsoluteFill style={{ opacity: p(frame, intro.tailFrom + 4, 8) }}>
            <div style={{ position: "absolute", left: 0, right: 0, top: 360, display: "flex", justifyContent: "center", gap: 14 }}>
              {intro.beats.map((b, k) =>
                b.shot.media ? (
                  <div key={k} style={{ width: 300, height: 400, overflow: "hidden", border: `5px solid ${P.white}`, transform: `translateY(${mix(p(frame, intro.tailFrom + 4 + k * 3, 10), 60, 0)}px) rotate(${(k - 1) * 3}deg)`, boxShadow: "0 20px 50px rgba(0,0,0,0.4)" }}>
                    {b.shot.media.type === "image" ? (
                      <Img src={staticFile(b.shot.media.file)} style={{ width: "100%", height: "100%", objectFit: "cover", objectPosition: `${b.shot.media.focusX * 100}% ${b.shot.media.focusY * 100}%` }} />
                    ) : (
                      <MediaLayer shot={{ ...b.shot, media: { ...b.shot.media, sourceInFrames: b.shot.media.sourceInFrames + 20 } }} layout="full" />
                    )}
                  </div>
                ) : null,
              )}
            </div>
            <div style={{ position: "absolute", left: 0, right: 0, top: 860, display: "flex", flexDirection: "column", alignItems: "center", gap: 18 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 22, transform: `scale(${mix(p(frame, intro.tailFrom + 6, 10), 0.85, 1)})` }}>
                <Img src={staticFile("logo.png")} style={{ width: 130, height: 130, objectFit: "contain", transform: `rotate(${mix(p(frame, intro.tailFrom + 6, 12), -12, 0)}deg)` }} />
                <span style={{ ...font(110, 900), color: P.white, letterSpacing: "0.01em" }}>LA VOZ RIOJANA</span>
              </div>
              <span style={{ ...caps(36, P.white, 900, 0.18), backgroundColor: P.ink, padding: "10px 22px", ...rise(frame, intro.tailFrom + 12, 12, 8) }}>{descriptor}</span>
              <span style={{ ...font(54, 700, "semi-condensed"), color: P.white, marginTop: 16, ...rise(frame, intro.tailFrom + 16, 12, 8) }}>{intro.tailText}</span>
            </div>
          </AbsoluteFill>
        </AbsoluteFill>
      ) : null}
    </AbsoluteFill>
  );
};

// Franjas en diagonal que se desplazan (fondo vivo del cierre).
const TypeStripes: React.FC<{ duration: number }> = ({ duration }) => {
  const frame = useCurrentFrame();
  const drift = interpolate(frame, [0, Math.max(1, duration)], [0, -160], clamp);
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      {[0, 1, 2, 3, 4].map((k) => (
        <div key={k} style={{ position: "absolute", left: -300 + k * 330 + drift, top: -200, width: 70, height: 2600, backgroundColor: alpha(P.white, 0.05), transform: "rotate(24deg)" }} />
      ))}
    </AbsoluteFill>
  );
};

// ── Cierre ───────────────────────────────────────────────────────────────
const Outro: React.FC<{ outro: NightlyNewscastV3Props["outro"] }> = ({ outro }) => {
  const frame = useCurrentFrame();
  const bg = p(frame, 0, 10, EASE.snap);
  const lines = outro.lines.length ? outro.lines : [{ text: "Lo que pasa en La Rioja, lo sabés acá", at: 0 }];
  return (
    <AbsoluteFill style={{ backgroundColor: P.ink }}>
      <AbsoluteFill style={{ backgroundColor: P.red, clipPath: `polygon(0 0, 100% 0, 100% ${mix(bg, 0, 60)}%, 0 ${mix(bg, 0, 70)}%)` }} />
      <TypeStripes duration={outro.durationInFrames} />
      {/* Logo, frases y CTA en una sola columna: el CTA siempre queda debajo. */}
      <div style={{ position: "absolute", left: G.x0, width: CONTENT_W, top: 280, display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
        <Img src={staticFile("logo.png")} style={{ width: 260, height: 260, objectFit: "contain", marginBottom: 20, transform: `scale(${mix(p(frame, 2, 12), 0.6, 1)}) rotate(${mix(p(frame, 2, 14), -20, 0)}deg)`, filter: "drop-shadow(0 20px 50px rgba(0,0,0,0.45))" }} />
        {lines.map((l, k) => {
          const at = (l.at ?? outro.from + 6 + k * 18) - outro.from;
          const last = k === lines.length - 1;
          // Se mide y se dibujan TODAS las líneas resultantes: nunca se corta
          // una frase hablada (antes se veía "LO QUE PASA EN LA").
          const f = fit({ text: l.text.toUpperCase(), maxWidth: CONTENT_W - (last ? 60 : 0), maxHeight: 2 * 120, min: 70, max: last ? 128 : 116, weight: 900, lh: 1, stretch: "condensed", maxLines: 2 });
          return (
            <div key={k} style={{ display: "flex", flexDirection: "column", alignItems: "center", marginTop: last ? 14 : 0 }}>
              {f.lines.map((line, j) => (
                <div key={j} style={{ overflow: "hidden", height: f.fontSize * 1.2, paddingTop: f.fontSize * 0.14 }}>
                  <div style={{ ...font(f.fontSize, 900), color: last ? P.red : P.white, backgroundColor: last ? P.white : "transparent", padding: last ? "4px 30px 0" : 0, transform: `translateY(${mix(p(frame, at + j * 3, 9, EASE.out), f.fontSize * 1.4, 0)}px)` }}>
                    {line}
                  </div>
                </div>
              ))}
            </div>
          );
        })}
        <div style={{ marginTop: 34, display: "flex", alignItems: "center", gap: 16, border: `3px solid ${P.white}`, padding: "14px 28px", ...rise(frame, 14, 14, 10) }}>
          <span style={{ ...caps(28, P.white, 900, 0.1), backgroundColor: P.red, padding: "6px 12px" }}>Instagram</span>
          <span style={{ ...font(46, 800, "semi-condensed"), color: P.white }}>{outro.cta}</span>
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ── Composición ──────────────────────────────────────────────────────────
export const NightlyNewscastV3: React.FC<NightlyNewscastV3Props> = (props) => {
  const ready = useV2FontsReady();
  if (!ready) return <AbsoluteFill style={{ backgroundColor: P.ink }} />;
  const count = props.stories.length;
  const intro = props.intro;
  const voiceRanges = [...props.voices, ...(intro?.voice ? [intro.voice] : []), ...(props.outro.voice ? [props.outro.voice] : [])].map((v) => [v.from, v.from + v.durationInFrames] as const);
  const music = props.music;
  const introEnd = intro ? intro.durationInFrames : 0;
  const musicVolume = (f: number) => {
    if (!music) return 0;
    let db: number;
    if (f < introEnd) {
      // Apertura: música adelante, baja apenas bajo la frase del gancho.
      db = music.introGainDb - (intro?.voice && f >= intro.voice.from && f < intro.voice.from + intro.voice.durationInFrames ? 4 : 0);
    } else {
      const near = Math.min(...voiceRanges.map(([a, b]) => (f < a ? a - f : f >= b ? f - b : 0)));
      const open = Math.min(1, Math.max(0, (near - 2) / 8));
      db = mix(open, music.gainDb, music.openGainDb);
    }
    const fadeIn = interpolate(f, [0, 4], [0.4, 1], clamp);
    const fadeOut = interpolate(f, [props.totalFrames - 26, props.totalFrames - 1], [1, 0], clamp);
    return dbToGain(db) * fadeIn * fadeOut;
  };
  const cuesFor = (k: number) => props.captions.filter((c) => c.story === k && c.to <= props.outro.from);
  return (
    <AbsoluteFill style={{ backgroundColor: P.ink }}>
      {intro ? (
        <Sequence durationInFrames={intro.durationInFrames}>
          <Intro intro={intro} dateLabel={props.edition.dateLabel} descriptor={props.edition.descriptor} />
        </Sequence>
      ) : null}
      {props.stories.map((story, k) => (
        <Sequence key={k} from={story.from} durationInFrames={story.durationInFrames}>
          <StoryScene story={story} cues={cuesFor(k)} count={count} />
        </Sequence>
      ))}
      <Sequence from={props.outro.from} durationInFrames={props.outro.durationInFrames}>
        <Outro outro={props.outro} />
      </Sequence>
      {/* Transiciones: cubren cada corte entre bloques. */}
      {props.stories.map((story, k) =>
        k > 0 || intro ? (
          <Transition key={`t${k}`} kind={story.wipe} at={story.from} text={story.lugar || story.events.find((e) => e.lugar)?.lugar || ""} />
        ) : null,
      )}
      <Transition kind="slash" at={props.outro.from} />

      {/* Sonido */}
      {music ? <Audio src={staticFile(music.file)} loop volume={musicVolume} /> : null}
      {props.sfx.map((s, k) => (
        <Sequence key={`fx${k}`} from={Math.max(0, s.from)} durationInFrames={s.file.endsWith("sting.mp3") ? Math.max(1, props.totalFrames - s.from) : 75}>
          <Audio src={staticFile(s.file)} volume={(f) => s.volume * (s.file.endsWith("sting.mp3") ? interpolate(f, [0, 60, 110], [1, 0.7, 0], clamp) : 1)} />
        </Sequence>
      ))}

      {/* Locución */}
      {intro?.voice ? (
        <Sequence from={intro.voice.from} durationInFrames={intro.voice.durationInFrames}>
          <Audio src={staticFile(intro.voice.file)} />
        </Sequence>
      ) : null}
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
        <div style={{ position: "absolute", left: 0, right: 0, top: 196, display: "flex", justifyContent: "center" }}>
          <span style={{ ...caps(22, P.ink, 900, 0.12), backgroundColor: "#F2C94C", padding: "6px 14px" }}>{props.edition.testBanner}</span>
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
