// Primitivas del Noticiero policial (V4): identidad gráfica, titulares con
// revelado por máscara, regleta, sellos de datos sincronizados con la voz,
// subtítulos inferiores, escenarios de imagen y transiciones propias.
//
// Retícula 1080×1920 (perfil propio, no una especificación de Meta): HUD en
// y≈232, contenido editorial entre y≈300 y y≈1250, subtítulos en la franja
// inferior segura y≈1290–1450 centrados en x=540; arriba de y≈200 y abajo
// de y≈1500 sólo hay imagen (interfaz de Reels). Botones de IG a la derecha:
// nada esencial pasa de x≈930.
import React from "react";
import { Video } from "@remotion/media";
import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame } from "remotion";
import { fit } from "../fit";
import { EASE, clamp, mix, p } from "../motion";
import { V2_FONT_SANS } from "../tokens";
import type { CaptionPlan, EmphasisPlan, MediaPlan, ShotPlan } from "./schema";

export const P = {
  ink: "#0A0E14",
  ink2: "#121923",
  red: "#D7192A",
  redDeep: "#9E0F1C",
  white: "#FFFFFF",
  bone: "#F3EFE6",
  amber: "#FFB81C",
  steel: "#9AA4AD",
} as const;

export const G = {
  w: 1080,
  h: 1920,
  x0: 64,
  x1: 930,
  hudY: 232,
  heroBottom: 1236,
  barY: 1140,
  capTop: 1292,
  panelH: 1180,
} as const;
export const CONTENT_W = G.x1 - G.x0;

export function alpha(hex: string, a: number): string {
  const c = hex.replace("#", "");
  return `rgba(${parseInt(c.slice(0, 2), 16)}, ${parseInt(c.slice(2, 4), 16)}, ${parseInt(c.slice(4, 6), 16)}, ${a})`;
}

export const font = (size: number, weight = 800, stretch: "condensed" | "semi-condensed" | "normal" = "condensed"): React.CSSProperties => ({
  fontFamily: `"${V2_FONT_SANS}"`,
  fontWeight: weight,
  fontStretch: stretch,
  fontSize: size,
  lineHeight: 1,
  whiteSpace: "nowrap",
});

export const caps = (size: number, color: string, weight = 800, tracking = 0.1): React.CSSProperties => ({
  ...font(size, weight, "semi-condensed"),
  letterSpacing: `${tracking}em`,
  textTransform: "uppercase",
  color,
});

const fold = (s: string) =>
  s
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9ñ]/g, "");

// Entrada sin rebote: 8–12 frames, 12–24 px.
export function rise(frame: number, start: number, distance = 18, duration = 10): React.CSSProperties {
  const t = p(frame, start, duration, EASE.out);
  return { opacity: t, transform: `translateY(${mix(t, distance, 0)}px)` };
}

// ── HUD: marca + formato + avance ────────────────────────────────────────
export const Hud: React.FC<{ index: number; count: number; progress: number; label?: string; enter?: number }> = ({ index, count, progress, label = "Policiales", enter = 1 }) => (
  <div style={{ position: "absolute", left: G.x0, width: CONTENT_W, top: G.hudY, height: 56, display: "flex", alignItems: "center", gap: 14, opacity: enter }}>
    <Img src={staticFile("logo.png")} style={{ width: 56, height: 56, objectFit: "contain", filter: "drop-shadow(0 4px 10px rgba(0,0,0,0.45))" }} />
    <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
      <span style={{ ...caps(26, P.white, 900, 0.04), fontStretch: "condensed", textShadow: "0 2px 10px rgba(0,0,0,0.5)" }}>La Voz Riojana</span>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ ...caps(16, P.white, 900, 0.14), backgroundColor: P.red, padding: "3px 7px" }}>{label}</span>
        <span style={{ ...caps(16, P.white, 800, 0.14), textShadow: "0 2px 8px rgba(0,0,0,0.6)" }}>24 H</span>
      </div>
    </div>
    {count > 0 && index >= 0 ? (
      <div style={{ marginLeft: "auto", display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 8 }}>
        <span style={{ ...font(30, 900), color: P.white, textShadow: "0 2px 10px rgba(0,0,0,0.6)", fontVariantNumeric: "tabular-nums" }}>
          {String(index + 1).padStart(2, "0")}
          <span style={{ color: alpha(P.white, 0.55) }}>{` / ${String(count).padStart(2, "0")}`}</span>
        </span>
        <div style={{ display: "flex", gap: 4 }}>
          {Array.from({ length: count }).map((_, k) => (
            <div key={k} style={{ width: 14, height: 4, backgroundColor: alpha(P.white, 0.3), overflow: "hidden" }}>
              <div style={{ width: `${k < index ? 100 : k === index ? progress * 100 : 0}%`, height: "100%", backgroundColor: k === index ? P.red : P.white }} />
            </div>
          ))}
        </div>
      </div>
    ) : null}
  </div>
);

// ── Titular protagonista ─────────────────────────────────────────────────
export interface HeroFit {
  lines: string[];
  size: number;
  lh: number;
  height: number;
  overflow: boolean;
}

export function fitHero(text: string, opts: { min: number; max: number; maxHeight: number; maxLines: number; width?: number }): HeroFit {
  const f = fit({ text, maxWidth: opts.width ?? CONTENT_W, maxHeight: opts.maxHeight, min: opts.min, max: opts.max, weight: 900, lh: 0.94, stretch: "condensed", tracking: -0.01, maxLines: opts.maxLines, uppercase: true });
  return { lines: f.lines, size: f.fontSize, lh: f.lineHeight, height: f.height, overflow: f.overflow };
}

export function chooseHero(full: string, short: string, opts: { min: number; max: number; maxHeight: number; maxLines: number; width?: number }): HeroFit {
  const a = fitHero(full, opts);
  if (!a.overflow) return a;
  if (short) {
    const b = fitHero(short, opts);
    if (!b.overflow) return b;
  }
  return fitHero(short || full, { ...opts, maxLines: opts.maxLines + 1, maxHeight: opts.maxHeight + opts.min });
}

// Líneas que entran por máscara (cada una sube desde su propio recorte,
// escalonadas 3 frames); la palabra clave recibe una caja roja que se barre.
export const HeroLines: React.FC<{ hero: HeroFit; keyword?: string; start: number; color?: string; exit?: number; boxColor?: string }> = ({
  hero,
  keyword = "",
  start,
  color = P.white,
  exit = 0,
  boxColor = P.red,
}) => {
  const frame = useCurrentFrame();
  const keys = keyword.split(/\s+/).map(fold).filter(Boolean);
  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      {hero.lines.map((line, i) => {
        const t = p(frame, start + i * 3, 9, EASE.out);
        const out = exit > 0 ? interpolate(exit, [i * 0.12, 0.6 + i * 0.12], [0, 1], clamp) : 0;
        const words = line.split(" ");
        return (
          <div key={i} style={{ clipPath: "inset(0 -400px 0 -400px)", height: hero.lh + hero.size * 0.2, marginTop: -hero.size * 0.14, paddingTop: hero.size * 0.14, marginBottom: -hero.size * 0.06 }}>
            <div
              style={{
                ...font(hero.size, 900),
                lineHeight: `${hero.lh}px`,
                letterSpacing: "-0.01em",
                textTransform: "uppercase",
                color,
                transform: `translateY(${mix(t, hero.lh * 1.3, 0) + mix(out, 0, hero.lh * 1.3)}px)`,
                textShadow: "0 6px 30px rgba(0,0,0,0.45)",
                whiteSpace: "pre",
              }}
            >
              {words.map((w, k) => {
                const isKey = keys.length > 0 && keys.includes(fold(w));
                const sep = k < words.length - 1 ? " " : "";
                if (!isKey) return <span key={k}>{w + sep}</span>;
                const wipe = p(frame, start + 8 + i * 3, 8, EASE.snap);
                return (
                  <span key={k} style={{ position: "relative", padding: `0 ${hero.size * 0.08}px`, margin: `0 -${hero.size * 0.08}px` }}>
                    <span style={{ position: "absolute", left: 0, right: 0, top: hero.size * 0.06, bottom: hero.size * 0.0, backgroundColor: boxColor, clipPath: `inset(0 ${100 - wipe * 100}% 0 0)` }} />
                    <span style={{ position: "relative" }}>{w}</span>
                    {sep}
                  </span>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
};

// Regleta: el titular contraído en zócalo (etiqueta roja + titular corto).
export const Regleta: React.FC<{ tag: string; text: string; start: number; top?: number }> = ({ tag, text, start, top = G.barY }) => {
  const frame = useCurrentFrame();
  const t = p(frame, start, 10, EASE.snap);
  const tagW = 20 + tag.length * 16;
  const f = fit({ text: text.toUpperCase(), maxWidth: CONTENT_W - tagW - 40, maxHeight: 64, min: 40, max: 58, weight: 900, lh: 1, stretch: "condensed", maxLines: 1 });
  const text2 = f.overflow ? fit({ text: text.toUpperCase(), maxWidth: CONTENT_W - 40, maxHeight: 112, min: 40, max: 52, weight: 900, lh: 1.04, stretch: "condensed", maxLines: 2 }) : null;
  return (
    <div style={{ position: "absolute", left: G.x0, top, width: CONTENT_W, clipPath: `inset(0 ${100 - t * 100}% 0 0)` }}>
      <div style={{ display: "flex", alignItems: "stretch", boxShadow: "0 14px 40px rgba(0,0,0,0.35)" }}>
        <div style={{ backgroundColor: P.red, padding: "0 16px", display: "flex", alignItems: "center", ...caps(22, P.white, 900, 0.12) }}>{tag}</div>
        <div style={{ backgroundColor: P.white, padding: "12px 18px", flex: 1, minWidth: 0 }}>
          {(text2 ?? f).lines.map((l, i) => (
            <div key={i} style={{ ...font((text2 ?? f).fontSize, 900), lineHeight: `${(text2 ?? f).lineHeight}px`, color: P.ink, textTransform: "uppercase" }}>
              {l}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

// ── Sellos de datos sincronizados con la voz ─────────────────────────────
const Pin: React.FC<{ size: number; color: string }> = ({ size, color }) => (
  <svg width={size} height={size} viewBox="0 0 24 24">
    <path d="M12 2C8.1 2 5 5.1 5 9c0 5.2 7 13 7 13s7-7.8 7-13c0-3.9-3.1-7-7-7zm0 9.5A2.5 2.5 0 1 1 12 6.5a2.5 2.5 0 0 1 0 5z" fill={color} />
  </svg>
);

export const PlaceChip: React.FC<{ text: string; top: number; opacity?: number }> = ({ text, top, opacity = 1 }) => (
  <div style={{ position: "absolute", left: G.x0, top, display: "flex", alignItems: "center", gap: 8, backgroundColor: alpha(P.ink, 0.82), padding: "8px 14px 8px 10px", opacity }}>
    <Pin size={26} color={P.red} />
    <span style={{ ...caps(26, P.white, 900, 0.08) }}>{text}</span>
  </div>
);

function splitValue(text: string): { value: string; rest: string } {
  const m = text.match(/^(.*?\d[\d.,]*\s*%?)(.*)$/);
  return m ? { value: m[1].trim(), rest: m[2].trim() } : { value: text, rest: "" };
}

// Cada dato entra cuando la voz lo dice, se sostiene ~1,6–2 s y sale; el
// lugar queda después como chip permanente sobre la regleta.
export const EmphasisLayer: React.FC<{ items: EmphasisPlan[]; side: "left" | "right"; top?: number; chipTop?: number; end: number }> = ({ items, side, top = 470, chipTop = G.barY - 64, end }) => {
  const frame = useCurrentFrame();
  const place = items.find((x) => x.kind === "place");
  return (
    <>
      {items.map((item, k) => {
        const hold = item.kind === "place" ? 46 : item.kind === "tag" ? 40 : 58;
        if (frame < item.at || frame > item.at + hold + 12) return null;
        const t = p(frame, item.at, 9, EASE.out);
        const out = p(frame, item.at + hold, 10, EASE.in);
        const x = side === "right" ? G.x1 : G.x0;
        const anchor: React.CSSProperties = side === "right" ? { right: G.w - x } : { left: x };
        if (item.kind === "place") {
          return (
            <div key={k} style={{ position: "absolute", ...anchor, top, transform: `skewX(-8deg) translateX(${mix(t, side === "right" ? 60 : -60, 0)}px)`, opacity: t * (1 - out) }}>
              <div style={{ display: "flex", alignItems: "center", gap: 14, backgroundColor: P.red, padding: "16px 26px 16px 20px", boxShadow: "0 20px 50px rgba(0,0,0,0.4)" }}>
                <span style={{ transform: "skewX(8deg)", display: "flex" }}>
                  <Pin size={56} color={P.white} />
                </span>
                <span style={{ ...caps(fit({ text: item.text.toUpperCase(), maxWidth: 640, maxHeight: 80, min: 44, max: 76, weight: 900, lh: 1, stretch: "condensed", maxLines: 1 }).fontSize, P.white, 900, 0.02), fontStretch: "condensed", transform: "skewX(8deg)" }}>
                  {item.text}
                </span>
              </div>
            </div>
          );
        }
        if (item.kind === "tag") {
          return (
            <div key={k} style={{ position: "absolute", left: 0, right: 0, top: top + 10, height: 132, overflow: "hidden", opacity: 1 - out }}>
              <div style={{ position: "absolute", left: 0, right: 0, top: 0, bottom: 0, backgroundColor: alpha(P.ink, 0.86), clipPath: `inset(0 ${100 - t * 100}% 0 0)` }} />
              <div style={{ position: "absolute", left: G.x0, top: 18, ...font(108, 900), color: P.white, letterSpacing: "0.02em", transform: `translateX(${mix(p(frame, item.at, hold + 12, (v) => v), 30, -30)}px)`, opacity: t }}>
                <span style={{ color: P.red }}>■ </span>
                {item.text}
              </div>
            </div>
          );
        }
        const { value, rest } = item.kind === "count" ? { value: item.value, rest: item.text } : splitValue(item.text);
        const big = fit({ text: value, maxWidth: 520, maxHeight: 210, min: 120, max: 210, weight: 900, lh: 1, stretch: "condensed", maxLines: 1 });
        const label = rest ? fit({ text: rest.toUpperCase(), maxWidth: 520, maxHeight: 110, min: 34, max: 52, weight: 900, lh: 1, stretch: "condensed", maxLines: 2 }) : null;
        return (
          <div key={k} style={{ position: "absolute", ...anchor, top: top - 20, opacity: 1 - out }}>
            <div style={{ backgroundColor: P.white, padding: "18px 28px 22px", clipPath: `inset(${100 - t * 100}% 0 0 0)`, boxShadow: "0 24px 60px rgba(0,0,0,0.45)", minWidth: 280 }}>
              <div style={{ height: 8, width: mix(p(frame, item.at + 4, 10), 0, 120), backgroundColor: P.red, marginBottom: 6 }} />
              <div style={{ ...font(big.fontSize, 900), color: P.red, letterSpacing: "-0.02em" }}>{value}</div>
              {label
                ? label.lines.map((l, i) => (
                    <div key={i} style={{ ...font(label.fontSize, 900), color: P.ink, marginTop: i === 0 ? 4 : 0 }}>
                      {l}
                    </div>
                  ))
                : null}
            </div>
          </div>
        );
      })}
      {place && frame > place.at + 46 && frame < end ? <PlaceChip text={place.text} top={chipTop} opacity={p(frame, place.at + 46, 8)} /> : null}
    </>
  );
};

// ── Subtítulos (franja inferior segura) ──────────────────────────────────
// Transcripción alineada: aparece con su frase, la palabra que se está
// diciendo va en blanco pleno y las siguientes un poco atenuadas. Sin rebote.
export const Captions: React.FC<{ cues: CaptionPlan[]; offset: number; top?: number }> = ({ cues, offset, top = G.capTop }) => {
  const frame = useCurrentFrame();
  const abs = frame + offset;
  const cue = cues.find((c) => abs >= c.from && abs < c.to);
  if (!cue) return null;
  const f = fit({ text: cue.text, maxWidth: 860, maxHeight: 2 * 62, min: 48, max: 56, weight: 700, lh: 1.1, stretch: "normal", maxLines: 2 });
  const words = cue.words.length ? cue.words : cue.text.split(" ").map((w) => ({ text: w, from: cue.from, method: "asr" }));
  const pop = p(abs, cue.from, 4, EASE.out);
  let cursor = 0;
  return (
    <div style={{ position: "absolute", left: 0, right: 0, top, display: "flex", justifyContent: "center" }}>
      <div style={{ backgroundColor: alpha(P.ink, 0.78), padding: "10px 22px 12px", borderRadius: 8, transform: `scale(${mix(pop, 0.97, 1)})`, opacity: mix(pop, 0.4, 1), maxWidth: 920 }}>
        {f.lines.map((line, li) => {
          const n = line.split(" ").length;
          const slice = words.slice(cursor, cursor + n);
          cursor += n;
          return (
            <div key={li} style={{ ...font(f.fontSize, 700, "normal"), lineHeight: `${f.lineHeight}px`, textAlign: "center", color: P.white }}>
              {slice.map((w, k) => (
                <span key={k} style={{ color: abs >= w.from ? P.white : alpha(P.white, 0.62) }}>
                  {w.text}
                  {k < slice.length - 1 ? " " : ""}
                </span>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
};

// ── Escenarios de imagen ─────────────────────────────────────────────────
const Still: React.FC<{ media: MediaPlan; shot: ShotPlan; position: string; punch?: number }> = ({ media, shot, position, punch = 0 }) => {
  const frame = useCurrentFrame();
  const t = interpolate(frame, [0, Math.max(1, shot.durationInFrames)], [0, 1], { ...clamp, easing: EASE.camera });
  const detail = shot.framing === "detail" ? 1.25 : 1;
  const hit = punch > 0 ? interpolate(frame, [0, punch], [1.1, 1], { ...clamp, easing: EASE.out }) : 1;
  const scale = mix(t, shot.move.scaleFrom, shot.move.scaleTo) * detail * hit;
  const dx = mix(t, 0, shot.move.dx) * G.w;
  const dy = mix(t, 0, shot.move.dy) * G.h;
  return (
    <Img
      src={staticFile(media.file)}
      style={{ width: "100%", height: "100%", objectFit: "cover", objectPosition: position, transform: `translate(${dx}px, ${dy}px) scale(${scale})`, transformOrigin: position }}
    />
  );
};

export function mediaPosition(media: MediaPlan, layout: "full" | "window"): string {
  if (media.type === "video" && media.textZone === "abajo" && layout === "window") return `${(media.focusX * 100).toFixed(1)}% 0%`;
  return `${(media.focusX * 100).toFixed(1)}% ${(media.focusY * 100).toFixed(1)}%`;
}

export const MediaLayer: React.FC<{ shot: ShotPlan; layout: "full" | "window"; punch?: number }> = ({ shot, layout, punch = 0 }) => {
  const frame = useCurrentFrame();
  const media = shot.media;
  if (!media) return null;
  const pos = mediaPosition(media, layout);
  if (media.type === "video") {
    const hit = punch > 0 ? interpolate(frame, [0, punch], [1.08, 1], { ...clamp, easing: EASE.out }) : 1;
    // Zócalos y cintas del canal quedan fuera: se amplía 16 % desde arriba.
    const lowText = layout === "full" && media.textZone === "abajo";
    return (
      <div style={{ width: "100%", height: "100%", transform: `scale(${hit * (lowText ? 1.16 : 1)})`, transformOrigin: lowText ? "50% 0%" : "50% 50%" }}>
        <Video src={staticFile(media.file)} muted trimBefore={media.sourceInFrames} objectFit="cover" style={{ width: "100%", height: "100%", objectPosition: pos }} />
      </div>
    );
  }
  return <Still media={media} shot={shot} position={pos} punch={punch} />;
};

// Degradados de lectura: arriba para el HUD, abajo para titular/subtítulos.
export const Scrims: React.FC<{ strength?: number }> = ({ strength = 1 }) => (
  <>
    <AbsoluteFill style={{ background: `linear-gradient(180deg, ${alpha(P.ink, 0.7 * strength)} 0%, ${alpha(P.ink, 0.25 * strength)} 15%, ${alpha(P.ink, 0)} 26%)` }} />
    <AbsoluteFill
      style={{ background: `linear-gradient(180deg, ${alpha(P.ink, 0)} 40%, ${alpha(P.ink, 0.5 * strength)} 52%, ${alpha(P.ink, 0.82 * strength)} 64%, ${alpha(P.ink, 0.9 * strength)} 78%, ${alpha(P.ink, 0.7 * strength)} 100%)` }}
    />
  </>
);

// Fondo tipográfico vivo para historias sin imagen propia: franjas en
// diagonal que se desplazan y el lugar o la palabra clave gigante calada.
export const TypeBackdrop: React.FC<{ word: string; tone?: string; duration: number }> = ({ word, tone = P.red, duration }) => {
  const frame = useCurrentFrame();
  const drift = interpolate(frame, [0, Math.max(1, duration)], [0, -220], clamp);
  return (
    <AbsoluteFill style={{ backgroundColor: P.ink, overflow: "hidden" }}>
      <AbsoluteFill style={{ background: `radial-gradient(ellipse 80% 55% at 25% 30%, ${alpha(tone, 0.32)} 0%, ${alpha(P.ink, 0)} 70%)` }} />
      {[0, 1, 2, 3, 4, 5].map((k) => (
        <div
          key={k}
          style={{
            position: "absolute",
            left: -400 + k * 340 + drift * (k % 2 ? 1 : 0.6),
            top: -200,
            width: 90,
            height: 2600,
            backgroundColor: alpha(k % 3 === 0 ? tone : P.white, k % 3 === 0 ? 0.16 : 0.035),
            transform: "rotate(24deg)",
          }}
        />
      ))}
      {word ? (
        <div
          style={{
            position: "absolute",
            left: 40 + drift * 0.5,
            top: 1440,
            ...font(300, 900),
            color: "transparent",
            WebkitTextStroke: `3px ${alpha(P.white, 0.09)}`,
            textTransform: "uppercase",
          }}
        >
          {word}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

// ── Transiciones (cubren el corte; 14 frames centrados en la frontera) ───
export const TRANSITION_HALF = 7;

export const Transition: React.FC<{ kind: "slash" | "cover" | "locality" | "iris"; at: number; text?: string }> = ({ kind, at, text = "" }) => {
  const frame = useCurrentFrame();
  const local = frame - (at - TRANSITION_HALF);
  if (local < 0 || local > TRANSITION_HALF * 2) return null;
  const t = local / (TRANSITION_HALF * 2); // 0 → 1, cubre del todo en 0,5
  if (kind === "slash") {
    const bands = [
      { color: P.red, delay: 0, w: 1.0 },
      { color: P.ink, delay: 0.08, w: 0.9 },
      { color: P.white, delay: 0.16, w: 0.08 },
    ];
    return (
      <AbsoluteFill style={{ pointerEvents: "none" }}>
        {bands.map((b, k) => {
          const x = interpolate(t, [b.delay, 0.5, 1 - b.delay * 0.5], [-1.6, 0, 1.6], { ...clamp, easing: EASE.inOut });
          return (
            <div key={k} style={{ position: "absolute", top: -400, left: -200, width: G.w * 1.4 * b.w, height: G.h + 800, backgroundColor: b.color, transform: `translateX(${x * G.w * 1.1}px) skewX(-16deg)` }} />
          );
        })}
      </AbsoluteFill>
    );
  }
  if (kind === "cover") {
    const inX = interpolate(t, [0, 0.46], [G.w * 1.3, 0], { ...clamp, easing: EASE.out });
    const outX = interpolate(t, [0.54, 1], [0, -G.w * 1.3], { ...clamp, easing: EASE.in });
    const x = t < 0.5 ? inX : outX;
    const spin = interpolate(t, [0, 1], [-14, 14], clamp);
    return (
      <AbsoluteFill style={{ pointerEvents: "none" }}>
        <div style={{ position: "absolute", top: -300, left: -260, width: G.w + 520, height: G.h + 600, backgroundColor: P.red, transform: `translateX(${x}px) skewX(-12deg)` }} />
        <div style={{ position: "absolute", top: -300, left: -260, width: 70, height: G.h + 600, backgroundColor: P.white, transform: `translateX(${x + (t < 0.5 ? -40 : G.w + 480)}px) skewX(-12deg)` }} />
        <Img
          src={staticFile("logo.png")}
          style={{ position: "absolute", left: G.w / 2 - 170, top: G.h / 2 - 260, width: 340, height: 340, objectFit: "contain", transform: `translateX(${x}px) rotate(${spin}deg)`, filter: "drop-shadow(0 20px 40px rgba(0,0,0,0.35))" }}
        />
      </AbsoluteFill>
    );
  }
  if (kind === "locality") {
    const x = interpolate(t, [0, 0.5, 1], [-G.w, 0, G.w], { ...clamp, easing: EASE.inOut });
    const tx = interpolate(t, [0, 1], [240, -240], clamp);
    return (
      <AbsoluteFill style={{ pointerEvents: "none" }}>
        <AbsoluteFill style={{ backgroundColor: P.red, transform: `translateX(${x}px)` }}>
          <div style={{ position: "absolute", left: G.x0 + tx, top: G.h / 2 - 110, display: "flex", alignItems: "center", gap: 24 }}>
            <Pin size={150} color={P.white} />
            <span style={{ ...font(fit({ text: text.toUpperCase(), maxWidth: 780, maxHeight: 220, min: 90, max: 200, weight: 900, lh: 1, stretch: "condensed", maxLines: 1 }).fontSize, 900), color: P.white, textTransform: "uppercase" }}>
              {text}
            </span>
          </div>
        </AbsoluteFill>
      </AbsoluteFill>
    );
  }
  // iris: rectángulo que crece desde el centro y se abre.
  const grow = interpolate(t, [0, 0.5], [0, 1], { ...clamp, easing: EASE.in });
  const open = interpolate(t, [0.5, 1], [0, 1], { ...clamp, easing: EASE.out });
  const inset = t < 0.5 ? mix(grow, 50, 0) : 0;
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <AbsoluteFill style={{ backgroundColor: P.ink, clipPath: t < 0.5 ? `inset(${inset}% ${inset}% ${inset}% ${inset}%)` : `inset(0 0 0 0)`, opacity: t < 0.5 ? 1 : 1 - open }} />
      <AbsoluteFill style={{ border: `${mix(t < 0.5 ? grow : 1 - open, 0, 26)}px solid ${P.red}`, opacity: t < 0.5 ? grow : 1 - open }} />
    </AbsoluteFill>
  );
};
