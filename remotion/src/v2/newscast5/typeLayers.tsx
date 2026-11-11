// Capa tipográfica del Noticiero V5: HUD (con la marca que abre el Reel y se
// contrae), titular grande → regleta superior, datos que entran cuando la
// voz los dice y subtítulos cinéticos.
//
// Jerarquía: el titular grande vive en el tercio inferior sólo mientras se
// presenta el hecho; después sube a la regleta (y≈312) y la parte baja queda
// para los subtítulos (y≈1318–1470). Titular y subtítulo nunca compiten en
// la misma franja.
import React from "react";
import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame } from "remotion";
import { fit } from "../fit";
import { EASE, clamp, mix, p } from "../motion";
import { HeroLines, chooseHero } from "../newscast/primitives";
import { Pin } from "./shots";
import type { CaptionV5, InsertV5, StoryV5 } from "./schema";
import { C5, CONTENT_W5, L, alpha, caps5, sans, serif } from "./theme";

// ── HUD: marca + formato + contador + avance ─────────────────────────────
// En los primeros ``brandFrames`` del Reel la marca ocupa una barra roja
// grande (la apertura del medio) y se contrae en el HUD: identidad sin
// esperar, encima de la noticia que ya está corriendo.
export const Hud5: React.FC<{
  index: number;
  count: number;
  progress: number;
  kicker: string;
  region: string;
  dateLabel: string;
  frame: number; // frame absoluto del Reel
  brandFrames: number;
}> = ({ index, count, progress, kicker, region, dateLabel, frame, brandFrames }) => {
  const collapse = p(frame, brandFrames - 12, 12, EASE.inOut);
  const open = frame < brandFrames;
  const compactIn = p(frame, brandFrames - 6, 10, EASE.out);
  return (
    <>
      {open ? (
        <div style={{ position: "absolute", left: 0, top: L.hudY - 22, width: L.w, height: 150, overflow: "hidden", clipPath: `inset(0 ${collapse * 100}% 0 0)` }}>
          <div style={{ position: "absolute", inset: 0, backgroundColor: C5.red, boxShadow: "0 18px 50px rgba(0,0,0,0.35)" }} />
          <div style={{ position: "absolute", left: L.x0, top: 20, display: "flex", alignItems: "center", gap: 22, transform: `translateX(${mix(p(frame, 0, 8, EASE.out), -30, 0)}px)` }}>
            <Img src={staticFile("logo.png")} style={{ width: 104, height: 104, objectFit: "contain", filter: "drop-shadow(0 6px 16px rgba(0,0,0,0.35))" }} />
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <span style={{ ...sans(64, 900), color: C5.white, letterSpacing: "0.005em" }}>LA VOZ RIOJANA</span>
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <span style={{ ...caps5(26, C5.red, 900, 0.12), backgroundColor: C5.white, padding: "4px 10px" }}>{kicker}</span>
                <span style={{ ...caps5(26, C5.white, 900, 0.12) }}>{region}</span>
                <span style={{ ...serif(28, alpha(C5.white, 0.9)) }}>{dateLabel ? `· ${dateLabel.toLowerCase()}` : ""}</span>
              </div>
            </div>
          </div>
        </div>
      ) : null}
      <div style={{ position: "absolute", left: L.x0, width: CONTENT_W5, top: L.hudY, height: 60, display: "flex", alignItems: "center", gap: 14, opacity: open ? compactIn : 1 }}>
        <Img src={staticFile("logo.png")} style={{ width: 56, height: 56, objectFit: "contain", filter: "drop-shadow(0 4px 10px rgba(0,0,0,0.45))" }} />
        <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
          <span style={{ ...caps5(26, C5.white, 900, 0.03), fontStretch: "condensed", textShadow: "0 2px 10px rgba(0,0,0,0.55)" }}>La Voz Riojana</span>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ ...caps5(16, C5.white, 900, 0.14), backgroundColor: C5.red, padding: "3px 7px" }}>{kicker}</span>
            <span style={{ ...caps5(16, C5.white, 800, 0.14), textShadow: "0 2px 8px rgba(0,0,0,0.6)" }}>{region}</span>
          </div>
        </div>
        {count > 0 ? (
          <div style={{ marginLeft: "auto", display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 8 }}>
            <span style={{ ...sans(32, 900), color: C5.white, textShadow: "0 2px 10px rgba(0,0,0,0.6)", fontVariantNumeric: "tabular-nums" }}>
              {String(index + 1).padStart(2, "0")}
              <span style={{ color: alpha(C5.white, 0.55) }}>{` / ${String(count).padStart(2, "0")}`}</span>
            </span>
            <div style={{ display: "flex", gap: 4 }}>
              {Array.from({ length: count }).map((_, k) => (
                <div key={k} style={{ width: Math.max(10, Math.min(22, 200 / count)), height: 5, backgroundColor: alpha(C5.white, 0.3), overflow: "hidden" }}>
                  <div style={{ width: `${k < index ? 100 : k === index ? progress * 100 : 0}%`, height: "100%", backgroundColor: k === index ? C5.red : C5.white }} />
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </>
  );
};

// ── Titular grande → regleta superior ────────────────────────────────────
export const HeadlineSystem5: React.FC<{ story: StoryV5; lead: boolean }> = ({ story, lead }) => {
  const frame = useCurrentFrame();
  const switchAt = Math.min(story.compactAt, story.durationInFrames - 10);
  const exit = interpolate(frame, [switchAt, switchAt + 8], [0, 1], { ...clamp, easing: EASE.in });
  const hero = chooseHero(story.headline, story.strip, { min: 84, max: lead ? 150 : 128, maxHeight: lead ? 470 : 400, maxLines: lead ? 4 : 3 });
  const top = L.headBottom - hero.height - 26;
  // En el gancho el titular ya está legible en el frame 2: entra en 6 frames
  // y no en 9 (el primer segundo decide si se sigue mirando).
  const start = lead ? -4 : 1;
  return (
    <>
      {frame < switchAt + 10 ? (
        <div style={{ position: "absolute", left: L.x0, width: CONTENT_W5, top }}>
          {lead ? (
            <div style={{ ...caps5(34, C5.white, 900, 0.14), marginBottom: 20, display: "flex", alignItems: "center", gap: 14, opacity: 1 - exit, textShadow: "0 3px 14px rgba(0,0,0,0.7)" }}>
              <span style={{ width: 34, height: 6, backgroundColor: C5.red, display: "inline-block" }} />
              Lo más importante
            </div>
          ) : null}
          <HeroLines hero={hero} keyword={story.keyword} start={start} color={C5.white} exit={exit} boxColor={C5.red} />
          <div style={{ height: 8, marginTop: 16, width: `${p(frame, start + 6, 10, EASE.snap) * (1 - exit) * 30}%`, backgroundColor: C5.red }} />
        </div>
      ) : null}
      {frame >= switchAt ? <Strip5 tag={story.tag} text={story.strip} start={switchAt + 2} /> : null}
    </>
  );
};

export const Strip5: React.FC<{ tag: string; text: string; start: number }> = ({ tag, text, start }) => {
  const frame = useCurrentFrame();
  const t = p(frame, start, 10, EASE.snap);
  const tagW = 26 + tag.length * 15;
  const f = fit({ text: text.toUpperCase(), maxWidth: CONTENT_W5 - tagW - 44, maxHeight: 56, min: 34, max: 50, weight: 900, lh: 1, stretch: "condensed", maxLines: 1 });
  const lines = f.overflow ? fit({ text: text.toUpperCase(), maxWidth: CONTENT_W5 - tagW - 44, maxHeight: 92, min: 32, max: 42, weight: 900, lh: 1.05, stretch: "condensed", maxLines: 2 }) : f;
  return (
    <div style={{ position: "absolute", left: L.x0, top: L.stripY, width: CONTENT_W5, clipPath: `inset(0 ${100 - t * 100}% 0 0)` }}>
      <div style={{ display: "inline-flex", alignItems: "stretch", maxWidth: CONTENT_W5, boxShadow: "0 14px 40px rgba(0,0,0,0.35)" }}>
        <div style={{ backgroundColor: C5.red, padding: "0 14px", display: "flex", alignItems: "center", ...caps5(20, C5.white, 900, 0.12) }}>{tag}</div>
        <div style={{ backgroundColor: C5.white, padding: "10px 16px 8px" }}>
          {lines.lines.map((l, i) => (
            <div key={i} style={{ ...sans(lines.fontSize, 900), lineHeight: `${lines.lineHeight}px`, color: C5.ink, textTransform: "uppercase" }}>
              {l}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

// ── Datos y lugar que entran con la voz ──────────────────────────────────
function splitValue(text: string): { value: string; rest: string } {
  const m = text.match(/^(.*?\d[\d.,]*\s*%?)(.*)$/);
  return m ? { value: m[1].trim(), rest: m[2].trim() } : { value: text, rest: "" };
}

// Las cifras grandes cuentan hasta su valor final (con separador de miles);
// las chicas entran ya con su valor: contar hasta 4 no aporta nada.
function counted(value: string, t: number): string {
  const digits = value.replace(/\./g, "").replace(",", ".");
  const n = Number(digits.replace(/[^\d.]/g, ""));
  if (!Number.isFinite(n) || n < 20 || /[^\d.,\s%]/.test(value)) return value;
  const shown = Math.round(n * t);
  const formatted = shown.toLocaleString("es-AR");
  return value.replace(/[\d.,]+/, formatted);
}

export const Inserts5: React.FC<{ items: InsertV5[]; side: "left" | "right" }> = ({ items, side }) => {
  const frame = useCurrentFrame();
  return (
    <>
      {items.map((item, k) => {
        if (frame < item.at - 1 || frame > item.until + 8) return null;
        const t = p(frame, item.at, 9, EASE.out);
        const out = p(frame, item.until, 8, EASE.in);
        const anchor: React.CSSProperties = side === "right" ? { right: L.w - L.x1 } : { left: L.x0 };
        if (item.kind === "place") {
          const size = fit({ text: item.text.toUpperCase(), maxWidth: 600, maxHeight: 80, min: 44, max: 74, weight: 900, lh: 1, stretch: "condensed", maxLines: 1 }).fontSize;
          return (
            <div key={k} style={{ position: "absolute", ...anchor, top: L.insertTop + 30, transform: `skewX(-8deg) translateX(${mix(t, side === "right" ? 60 : -60, 0) + mix(out, 0, side === "right" ? 80 : -80)}px)`, opacity: t * (1 - out) }}>
              <div style={{ display: "flex", alignItems: "center", gap: 14, backgroundColor: C5.red, padding: "14px 26px 12px 18px", boxShadow: "0 20px 50px rgba(0,0,0,0.4)" }}>
                <span style={{ transform: "skewX(8deg)", display: "flex" }}>
                  <Pin size={54} color={C5.white} />
                </span>
                <span style={{ ...sans(size, 900), color: C5.white, textTransform: "uppercase", transform: "skewX(8deg)" }}>{item.text}</span>
              </div>
            </div>
          );
        }
        const { value, rest } = item.kind === "count" ? { value: item.value, rest: item.text } : splitValue(item.text);
        const big = fit({ text: value, maxWidth: 520, maxHeight: 220, min: 120, max: 220, weight: 900, lh: 1, stretch: "condensed", maxLines: 1 });
        const label = rest ? fit({ text: rest.toUpperCase(), maxWidth: 480, maxHeight: 110, min: 34, max: 54, weight: 900, lh: 1, stretch: "condensed", maxLines: 2 }) : null;
        const count = p(frame, item.at, 16, EASE.out);
        return (
          <div key={k} style={{ position: "absolute", ...anchor, top: L.insertTop, opacity: 1 - out, transform: `translateY(${mix(out, 0, -30)}px)` }}>
            <div style={{ backgroundColor: C5.bone, padding: "16px 30px 22px", clipPath: `inset(${100 - t * 100}% 0 0 0)`, boxShadow: "0 30px 70px rgba(0,0,0,0.5)", minWidth: 260, transform: `rotate(${side === "right" ? 1.5 : -1.5}deg)` }}>
              <div style={{ height: 8, width: mix(p(frame, item.at + 4, 10), 0, 120), backgroundColor: C5.red, marginBottom: 6 }} />
              <div style={{ ...sans(big.fontSize, 900), color: C5.red, letterSpacing: "-0.02em", fontVariantNumeric: "tabular-nums" }}>{counted(value, count)}</div>
              {label
                ? label.lines.map((l, i) => (
                    <div key={i} style={{ ...sans(label.fontSize, 900), color: C5.ink, marginTop: i === 0 ? 2 : 0 }}>
                      {l}
                    </div>
                  ))
                : null}
            </div>
          </div>
        );
      })}
    </>
  );
};

// ── Subtítulos cinéticos ─────────────────────────────────────────────────
// Grupos cortos (1–4 palabras) centrados abajo; cada palabra aparece cuando
// se dice (sube 14 px en 4 frames) en el lugar que ya tiene reservado, así
// el grupo no "baila". Una palabra clave por grupo va sobre caja roja.
export const KineticCaptions: React.FC<{ cues: CaptionV5[] }> = ({ cues }) => {
  const frame = useCurrentFrame();
  const cue = cues.find((c) => frame >= c.from && frame < c.to);
  if (!cue) return null;
  const f = fit({ text: cue.text, maxWidth: 900, maxHeight: 2 * 76, min: 52, max: 68, weight: 800, lh: 1.12, stretch: "semi-condensed", maxLines: 2 });
  const words = cue.words.length ? cue.words : cue.text.split(" ").map((w) => ({ text: w, from: cue.from, key: false }));
  let cursor = 0;
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div style={{ position: "absolute", left: 0, right: 0, top: L.capTop, display: "flex", flexDirection: "column", alignItems: "center" }}>
        {f.lines.map((line, li) => {
          const n = line.split(" ").length;
          const slice = words.slice(cursor, cursor + n);
          cursor += n;
          return (
            <div key={li} style={{ display: "flex", gap: f.fontSize * 0.26, height: f.lineHeight, alignItems: "center" }}>
              {slice.map((w, k) => {
                const t = p(frame, w.from - 1, 4, EASE.out);
                const box = w.key ? p(frame, w.from, 5, EASE.snap) : 0;
                return (
                  <span key={k} style={{ position: "relative", display: "inline-block", opacity: t, transform: `translateY(${mix(t, 14, 0)}px)` }}>
                    {w.key ? (
                      <span style={{ position: "absolute", left: -10, right: -10, top: f.fontSize * 0.04, bottom: -f.fontSize * 0.04, backgroundColor: C5.red, clipPath: `inset(0 ${100 - box * 100}% 0 0)` }} />
                    ) : null}
                    <span
                      style={{
                        position: "relative",
                        ...sans(f.fontSize, 800, "semi-condensed"),
                        color: C5.white,
                        textShadow: w.key ? "none" : `0 0 3px ${alpha(C5.ink, 0.95)}, 0 3px 10px ${alpha(C5.ink, 0.85)}, 0 0 22px ${alpha(C5.ink, 0.6)}`,
                      }}
                    >
                      {w.text}
                    </span>
                  </span>
                );
              })}
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

// Degradado de lectura inferior (subtítulos) y superior (HUD/regleta).
export const Scrims5: React.FC<{ strength?: number }> = ({ strength = 1 }) => (
  <>
    <AbsoluteFill style={{ background: `linear-gradient(180deg, ${alpha(C5.ink, 0.62 * strength)} 0%, ${alpha(C5.ink, 0.2 * strength)} 18%, ${alpha(C5.ink, 0)} 26%)`, pointerEvents: "none" }} />
    <AbsoluteFill
      style={{ background: `linear-gradient(180deg, ${alpha(C5.ink, 0)} 46%, ${alpha(C5.ink, 0.45 * strength)} 58%, ${alpha(C5.ink, 0.78 * strength)} 70%, ${alpha(C5.ink, 0.86 * strength)} 82%, ${alpha(C5.ink, 0.6 * strength)} 100%)`, pointerEvents: "none" }}
    />
  </>
);
