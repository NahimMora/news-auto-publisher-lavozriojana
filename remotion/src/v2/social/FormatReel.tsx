// Reels de formato propio (Fase 2, aprobados en la mesa de formatos el
// 2026-11-14): Último momento (UM), Datos útiles (DU) y Un día como hoy (EF).
//
// Una sola composición guiada por datos: el guion (Python, utils/format_reels.py)
// llega partido en tramos ("beats"), cada uno con su diseño y su modo de
// subtítulo, y los tiempos salen de la locución real alineada palabra por
// palabra. Gramática aprobada: foto o video real desde el cuadro 0, primer
// título COMPLETO y grande (las palabras se encienden con la voz), nada más
// de 1 s sin algo nuevo, subtítulos integrados de varias maneras durante todo
// el video (nunca una franja fija abajo) y cierre Compartí/Guardá/Seguí.
import React from "react";
import {
  AbsoluteFill, Audio, Img, OffthreadVideo, Sequence, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig,
} from "remotion";
import { z } from "zod";
import { fit } from "../fit";
import { useV2FontsReady } from "../fonts";
import { LA_RIOJA_PATH, LA_RIOJA_VIEW, LA_RIOJA_CAPITAL } from "../newscast5/laRioja";
import { C, V2_FONT_SANS } from "../tokens";

export const FORMAT_REEL_FPS = 30;
const W = 1080;
const GOLD = "#FFD15C";
const OK = "#1E7A46";
const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

const Word = z.object({ text: z.string(), startMs: z.number(), endMs: z.number() });
const Cue = z.object({ text: z.string(), startMs: z.number(), endMs: z.number(), words: z.array(Word) });
const Item = z.object({ text: z.string(), at: z.number() });
const Beat = z.object({
  from: z.number(),
  to: z.number(),
  layout: z.enum(["hook", "chips", "stamps", "number", "card", "calendar", "outro"]),
  caption: z.enum(["title", "callout", "marker", "pill", "chunk", "pop", "none"]),
  title: z.string(),
  items: z.array(Item),
  value: z.string(),
  label: z.string(),
  detail: z.string(),
  index: z.number(),
});

export const FormatReelSchema = z.object({
  kind: z.enum(["um", "du", "ef"]),
  badge: z.string(),
  accent: z.string(),
  media: z.object({ type: z.enum(["video", "photo"]), file: z.string(), width: z.number(), height: z.number() }),
  credit: z.string(),
  place: z.object({ label: z.string(), x: z.number(), y: z.number() }).nullable(),
  voiceFile: z.string(),
  totalFrames: z.number(),
  cues: z.array(Cue),
  beats: z.array(Beat),
  cards: z.array(z.string()),
  music: z.boolean(),
});
export type FormatReelProps = z.infer<typeof FormatReelSchema>;
type BeatT = z.infer<typeof Beat>;
type CueT = z.infer<typeof Cue>;

const cond = (size: number, stretch = "72%", weight = 900): React.CSSProperties => ({
  fontWeight: weight, fontStretch: stretch, fontSize: size, lineHeight: 0.95,
});

// ── Fondo: foto o video real desde el cuadro 0 ───────────────────────────
const FILTERS: Record<BeatT["layout"], string> = {
  hook: "saturate(1.15) contrast(1.05)",
  chips: "brightness(.6)",
  stamps: "brightness(.68) saturate(.9)",
  number: "blur(16px) brightness(.42)",
  card: "blur(16px) brightness(.5) saturate(1.1)",
  calendar: "brightness(.5)",
  outro: "blur(14px) brightness(.38)",
};

const Media: React.FC<{ p: FormatReelProps; layout: BeatT["layout"] }> = ({ p, layout }) => {
  const frame = useCurrentFrame();
  const kb = 1.06 + frame * 0.00035;
  const gray = p.kind === "ef" ? " grayscale(1) contrast(1.12)" : "";
  const style: React.CSSProperties = {
    position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover",
    filter: FILTERS[layout] + gray, transform: `scale(${kb})`,
  };
  return (
    <AbsoluteFill style={{ background: C.ink, overflow: "hidden" }}>
      {p.media.type === "video" ? (
        <OffthreadVideo src={staticFile(p.media.file)} muted style={style} />
      ) : (
        <Img src={staticFile(p.media.file)} style={style} />
      )}
      {p.kind === "ef" ? <AbsoluteFill style={{ background: "linear-gradient(135deg,rgba(11,47,79,.55),rgba(110,15,26,.4))", mixBlendMode: "multiply" }} /> : null}
      {p.kind === "du" && layout !== "hook" ? <AbsoluteFill style={{ background: "linear-gradient(rgba(11,47,79,.3),rgba(11,47,79,.78))" }} /> : null}
    </AbsoluteFill>
  );
};

// ── Marca y rótulo ───────────────────────────────────────────────────────
const Bug: React.FC<{ p: FormatReelProps; enter: boolean }> = ({ p, enter }) => {
  const frame = useCurrentFrame();
  const wipe = enter ? interpolate(frame, [0, 10], [0, 1], clamp) : 1;
  const live = Math.floor(frame / 15) % 2 === 0;
  const badgeBg = p.kind === "um" ? C.red : p.kind === "du" ? GOLD : "rgba(10,13,18,.78)";
  const badgeFg = p.kind === "du" ? C.navy : "#fff";
  return (
    <div style={{ position: "absolute", left: 44, top: 120, display: "flex", alignItems: "center", clipPath: `inset(0 ${100 - wipe * 100}% 0 0)` }}>
      <span style={{ background: "#fff", padding: "8px 16px 8px 8px", display: "flex", alignItems: "center", gap: 10, color: C.ink, ...cond(34) }}>
        <Img src={staticFile("logo.png")} style={{ width: 48, height: 48, borderRadius: "50%", objectFit: "contain" }} />
        LA VOZ RIOJANA
      </span>
      <span style={{ background: badgeBg, color: badgeFg, padding: "16px 20px", display: "flex", alignItems: "center", gap: 12, letterSpacing: "0.02em", ...cond(34) }}>
        {p.kind === "um" ? <i style={{ width: 20, height: 20, borderRadius: "50%", background: "#fff", opacity: live ? 1 : 0.25, display: "inline-block" }} /> : null}
        {p.badge}
      </span>
    </div>
  );
};

const Credit: React.FC<{ text: string }> = ({ text }) =>
  text ? (
    <div style={{ position: "absolute", right: 36, top: 212, fontWeight: 700, fontSize: 22, letterSpacing: "0.06em", color: "rgba(255,255,255,.85)", background: "rgba(0,0,0,.45)", padding: "6px 10px" }}>
      {text}
    </div>
  ) : null;

// ── Animaciones base ─────────────────────────────────────────────────────
const usePop = (at: number) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = spring({ frame: frame - at, fps, config: { damping: 12, stiffness: 180, mass: 0.7 } });
  return { k, style: { opacity: Math.min(1, k * 1.5), transform: `scale(${0.55 + 0.45 * k})` } as React.CSSProperties };
};
const useStamp = (at: number, rot: number) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = spring({ frame: frame - at, fps, config: { damping: 14, stiffness: 220, mass: 0.6 } });
  return { opacity: Math.min(1, k * 2), transform: `scale(${2.2 - 1.2 * k}) rotate(${rot - 10 * (1 - k)}deg)` } as React.CSSProperties;
};

// ── Tramos ───────────────────────────────────────────────────────────────
const msToFrame = (ms: number) => (ms / 1000) * FORMAT_REEL_FPS;

const Hook: React.FC<{ p: FormatReelProps; b: BeatT }> = ({ p, b }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const upper = p.kind !== "du";
  const text = upper ? b.title.toUpperCase() : b.title;
  const box = fit({ text, maxWidth: W - 112, maxHeight: 620, min: 96, max: 178, weight: 900, lh: 0.9, stretch: "condensed", maxLines: 5, uppercase: upper });
  const slam = spring({ frame, fps, config: { damping: 13, stiffness: 160 } });
  const words = p.cues.flatMap((c) => c.words).filter((w) => msToFrame(w.startMs) < b.to);
  const absolute = frame + b.from;
  let wi = 0;
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ background: p.kind === "du"
        ? "linear-gradient(rgba(11,47,79,.35),rgba(11,47,79,.05) 25%,rgba(11,47,79,.6) 45%,rgba(11,47,79,.96) 80%)"
        : "linear-gradient(rgba(10,13,18,.5),transparent 20%,transparent 38%,rgba(10,13,18,.9) 72%)" }} />
      {p.kind === "ef" && b.value ? (
        <div style={{ position: "absolute", left: 30, top: 300, ...cond(400, "62%"), lineHeight: 0.8, color: "transparent", WebkitTextStroke: "5px rgba(255,209,92,.75)", opacity: interpolate(frame, [0, 12], [0, 1], clamp) }}>
          {b.value}
        </div>
      ) : null}
      <div style={{ position: "absolute", left: 56, right: 56, top: Math.max(700, 1480 - box.height), transform: `translateY(${(1 - slam) * 80}px)`, opacity: Math.min(1, slam * 1.6) }}>
        <div style={{ width: 200 * interpolate(frame, [0, 10], [0, 1], clamp), height: 18, background: p.accent, marginBottom: 34 }} />
        <div style={{ ...cond(box.fontSize, "70%"), lineHeight: `${box.lineHeight}px`, color: "#fff", textShadow: "0 6px 30px rgba(0,0,0,.45)" }}>
          {box.lines.map((line, li) => (
            <div key={li}>
              {line.split(" ").map((w, k) => {
                const token = words[wi++];
                const lit = !token || msToFrame(token.startMs) <= absolute + 2;
                const isKey = b.items.some((it) => it.text && w.toLowerCase().includes(it.text.toLowerCase()));
                return (
                  <span key={k} style={{ opacity: lit ? 1 : 0.38, color: isKey ? p.accent : undefined }}>
                    {w}{" "}
                  </span>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </AbsoluteFill>
  );
};

const MiniMap: React.FC<{ place: NonNullable<FormatReelProps["place"]>; accent: string }> = ({ place, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pop = usePop(0);
  const w = 480;
  const scale = w / LA_RIOJA_VIEW.w;
  const drop = spring({ frame: frame - 6, fps, config: { damping: 11, stiffness: 190, mass: 0.7 } });
  const ring = interpolate(frame % 36, [0, 30], [0, 1], clamp);
  const capital = Math.hypot(place.x - LA_RIOJA_CAPITAL.x, place.y - LA_RIOJA_CAPITAL.y) < 2;
  return (
    <div style={{ position: "absolute", left: 44, top: 470, width: w + 44, padding: 22, background: "rgba(10,13,18,.82)", border: "6px solid #fff", ...pop.style }}>
      <svg width={w} height={LA_RIOJA_VIEW.h * scale} viewBox={`0 0 ${LA_RIOJA_VIEW.w} ${LA_RIOJA_VIEW.h}`} style={{ overflow: "visible", display: "block" }}>
        <path d={LA_RIOJA_PATH} fill="#1b2430" stroke="rgba(255,255,255,.9)" strokeWidth={6} strokeLinejoin="round" />
        {!capital ? <circle cx={LA_RIOJA_CAPITAL.x} cy={LA_RIOJA_CAPITAL.y} r={14} fill="#fff" /> : null}
        <circle cx={place.x} cy={place.y} r={30 + ring * 120} fill="none" stroke={accent} strokeWidth={8} opacity={1 - ring} />
        <circle cx={place.x} cy={place.y - (1 - drop) * 140} r={30} fill={accent} stroke="#fff" strokeWidth={8} />
      </svg>
      <div style={{ marginTop: 14, color: "#fff", ...cond(58) }}>{place.label.toUpperCase()}</div>
    </div>
  );
};

const Chip: React.FC<{ at: number; text: string; bg: string; fg: string; top: number; left: number; border?: string }> = ({ at, text, bg, fg, top, left, border }) => {
  const frame = useCurrentFrame();
  const pop = usePop(at);
  if (frame < at) return null;
  return (
    <div style={{ position: "absolute", left, right: 44, top, background: bg, color: fg, padding: "20px 24px", boxShadow: "0 12px 28px rgba(0,0,0,.35)", borderLeft: border, ...cond(50), lineHeight: 1, ...pop.style, transformOrigin: "left center" }}>
      {text}
    </div>
  );
};

const Chips: React.FC<{ p: FormatReelProps; b: BeatT }> = ({ p, b }) => {
  const left = p.place ? 610 : 56;
  const palette: [string, string, string | undefined][] = [[p.accent, C.ink, undefined], [C.red, "#fff", undefined], [C.ink, "#fff", `12px solid ${p.accent}`]];
  return (
    <AbsoluteFill>
      {p.place ? <MiniMap place={p.place} accent={p.accent} /> : null}
      {b.items.slice(0, 3).map((it, i) => (
        <Chip key={i} at={it.at - b.from} text={it.text.toUpperCase()} bg={palette[i][0]} fg={palette[i][1]} border={palette[i][2]} top={500 + i * 210} left={left} />
      ))}
    </AbsoluteFill>
  );
};

const Stamp: React.FC<{ at: number; text: string; x: number; y: number; r: number; bg: string }> = ({ at, text, x, y, r, bg }) => {
  const frame = useCurrentFrame();
  const style = useStamp(at, r);
  if (frame < at) return null;
  const box = fit({ text, maxWidth: W - x - 120, maxHeight: 200, min: 60, max: 92, weight: 900, lh: 0.95, stretch: "condensed", maxLines: 2, uppercase: true });
  return (
    <div style={{ position: "absolute", left: x, top: y, border: "10px solid #fff", color: "#fff", background: bg, padding: "14px 30px", ...cond(box.fontSize, "70%"), ...style }}>
      {box.lines.map((l, i) => <div key={i}>{l}</div>)}
    </div>
  );
};

const Stamps: React.FC<{ p: FormatReelProps; b: BeatT }> = ({ p, b }) => {
  const spots: [number, number, number, string][] = [[90, 560, -6, "rgba(10,13,18,.65)"], [150, 820, 4, p.accent], [60, 1080, -3, C.red]];
  return (
    <AbsoluteFill>
      {b.items.slice(0, 3).map((it, i) => <Stamp key={i} at={it.at - b.from} text={it.text.toUpperCase()} x={spots[i][0]} y={spots[i][1]} r={spots[i][2]} bg={spots[i][3]} />)}
    </AbsoluteFill>
  );
};

// Contador: sólo si el valor es una cifra entera simple; si no, entra entero.
const Counter: React.FC<{ value: string; at: number; size: number; color: string }> = ({ value, at, size, color }) => {
  const frame = useCurrentFrame();
  const m = value.match(/^([^\d]*)([\d.]+)([^\d]*)$/);
  const n = m ? Number(m[2].replace(/\./g, "")) : NaN;
  let shown = value;
  if (m && Number.isFinite(n) && n > 0) {
    const t = interpolate(frame, [at, at + 18], [0, 1], { ...clamp, easing: (x) => 1 - Math.pow(1 - x, 3) });
    shown = `${m[1]}${Math.round(n * t).toLocaleString("es-AR")}${m[3]}`;
  }
  const box = fit({ text: value, maxWidth: W - 120, maxHeight: size * 1.1, min: 110, max: size, weight: 900, lh: 0.85, stretch: "condensed", maxLines: 1 });
  return <div style={{ ...cond(box.fontSize, "62%"), lineHeight: 0.85, color, whiteSpace: "nowrap" }}>{shown}</div>;
};

const NumberBeat: React.FC<{ p: FormatReelProps; b: BeatT }> = ({ p, b }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const slam = spring({ frame, fps, config: { damping: 12, stiffness: 170 } });
  const label = usePop(6);
  const stampAt = (b.items[0]?.at ?? b.from + 24) - b.from;
  return (
    <AbsoluteFill style={{ alignItems: "center" }}>
      <div style={{ position: "absolute", top: 360, left: 0, right: 0, display: "flex", justifyContent: "center", transform: `scale(${1.6 - 0.6 * slam})`, opacity: Math.min(1, slam * 2) }}>
        <Counter value={b.value} at={0} size={440} color={p.accent} />
      </div>
      <div style={{ position: "absolute", left: 60, right: 60, top: 820, textAlign: "center", color: "#fff", ...cond(100), ...label.style }}>{b.label.toUpperCase()}</div>
      {b.detail ? <Stamp at={stampAt} text={b.detail} x={150} y={1040} r={-4} bg={OK} /> : null}
    </AbsoluteFill>
  );
};

const Card: React.FC<{ p: FormatReelProps; b: BeatT }> = ({ p, b }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const k = spring({ frame, fps, config: { damping: 14, stiffness: 150 } });
  const prev = p.cards.slice(0, Math.max(0, b.index - 1));
  const top = 360 + prev.length * 120;
  const valueAt = (b.items[0]?.at ?? b.from + 8) - b.from;
  const lit = interpolate(frame, [valueAt, valueAt + 8], [0, 1], clamp);
  const valueBox = fit({ text: b.value.toUpperCase(), maxWidth: 820, maxHeight: 240, min: 70, max: 170, weight: 900, lh: 0.92, stretch: "condensed", maxLines: 2, uppercase: true });
  return (
    <AbsoluteFill>
      {prev.map((h, j) => (
        <div key={j} style={{ position: "absolute", left: 84 + j * 6, right: 84 + j * 6, top: 360 + j * 120, height: 150, background: "#fff", color: C.navy, borderRadius: 26, boxShadow: "0 18px 40px rgba(0,0,0,.3)", padding: "26px 40px", opacity: 0.94, display: "flex", justifyContent: "space-between" }}>
          <span style={{ ...cond(56, "70%"), color: j % 2 ? C.blue : C.navy, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 760 }}>{h.toUpperCase()}</span>
          <span style={{ width: 52, height: 52, borderRadius: "50%", background: GOLD, display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 900, fontSize: 30 }}>{j + 1}</span>
        </div>
      ))}
      <div style={{ position: "absolute", left: 70, right: 70, top, minHeight: 400, background: "#fff", color: C.navy, borderRadius: 30, boxShadow: "0 26px 60px rgba(0,0,0,.4)", padding: "40px 46px", transform: `translateY(${(1 - k) * 260}px) scale(${0.92 + 0.08 * k})`, opacity: Math.min(1, k * 1.6) }}>
        <div style={{ position: "absolute", right: 34, top: 30, width: 76, height: 76, borderRadius: "50%", background: GOLD, display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 900, fontSize: 42 }}>{b.index}</div>
        <div style={{ fontWeight: 800, fontSize: 32, letterSpacing: "0.08em", textTransform: "uppercase", color: C.blue, maxWidth: 760 }}>{b.label}</div>
        <div style={{ ...cond(valueBox.fontSize, "66%"), lineHeight: `${valueBox.lineHeight}px`, marginTop: 22, color: C.navy, opacity: 0.25 + 0.75 * lit, transform: `scale(${0.96 + 0.04 * lit})`, transformOrigin: "left center" }}>
          {valueBox.lines.map((l, i) => <div key={i}>{l}</div>)}
        </div>
        {b.detail ? <div style={{ fontSize: 40, fontWeight: 700, color: "#3D5A75", marginTop: 14, opacity: interpolate(frame, [valueAt + 6, valueAt + 16], [0, 1], clamp) }}>{b.detail}</div> : null}
      </div>
    </AbsoluteFill>
  );
};

const Calendar: React.FC<{ b: BeatT }> = ({ b }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const drop = spring({ frame, fps, config: { damping: 13, stiffness: 150 } });
  const [month, day] = [b.label, b.value];
  const stampAt = (b.items[0]?.at ?? b.from + 20) - b.from;
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left: 340, top: 300, width: 400, borderRadius: 30, overflow: "hidden", background: "#fff", color: C.ink, textAlign: "center", boxShadow: "0 20px 50px rgba(0,0,0,.45)", transform: `translateY(${(1 - drop) * -400}px)` }}>
        <div style={{ background: C.red, color: "#fff", ...cond(70, "75%"), letterSpacing: "0.14em", padding: "14px 0" }}>{month.toUpperCase()}</div>
        <div style={{ ...cond(250, "62%") }}>{day}</div>
      </div>
      {b.detail ? <Stamp at={stampAt} text={b.detail} x={110} y={860} r={-6} bg="rgba(10,13,18,.6)" /> : null}
    </AbsoluteFill>
  );
};

const SHARE = (c: string) => (
  <svg viewBox="0 0 24 24" width={86} height={86}><path fill="none" stroke={c} strokeWidth={2.2} strokeLinejoin="round" d="M21 3 3 10.5l7 2.5 2.5 7L21 3zM10 13l5-5" /></svg>
);
const SAVE = (c: string) => (
  <svg viewBox="0 0 24 24" width={86} height={86}><path fill="none" stroke={c} strokeWidth={2.2} strokeLinejoin="round" d="M6 3h12v18l-6-4.5L6 21z" /></svg>
);

const Outro: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const logo = usePop(0);
  const cycle = (frame / fps - 0.9) % 1.1;
  const press = frame > 0.9 * fps ? Math.max(0, Math.sin((cycle / 1.1) * Math.PI * 2)) : 0;
  const ring = frame > 0.9 * fps ? (cycle / 1.1) : 0;
  const acts: [string, ((c: string) => React.ReactNode) | null][] = [["Compartí", SHARE], ["Guardá", SAVE], ["Seguí", null]];
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", gap: 46, color: "#fff" }}>
      <div style={{ ...logo.style, display: "flex", flexDirection: "column", alignItems: "center", gap: 24 }}>
        <Img src={staticFile("logo.png")} style={{ width: 230, height: 230, borderRadius: "50%", background: "#fff", objectFit: "contain", border: "8px solid #fff" }} />
        <div style={{ ...cond(76, "78%") }}>@lavozriojana.ok</div>
      </div>
      <div style={{ display: "flex", gap: 60 }}>
        {acts.map(([label, icon], i) => (
          <ActButton key={label} i={i} label={label} icon={icon} press={i === 0 ? press : 0} ring={i === 0 ? ring : 0} />
        ))}
      </div>
    </AbsoluteFill>
  );
};

const ActButton: React.FC<{ i: number; label: string; icon: ((c: string) => React.ReactNode) | null; press: number; ring: number }> = ({ i, label, icon, press, ring }) => {
  const pop = usePop(6 + i * 5);
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 18, ...pop.style }}>
      <span style={{ position: "relative", display: "block", width: 176, height: 176 }}>
        {i === 0 ? <span style={{ position: "absolute", inset: 0, borderRadius: "50%", border: "6px solid #fff", transform: `scale(${1 + ring * 0.5})`, opacity: ring > 0.45 ? (1 - ring) * 1.6 : 0 }} /> : null}
        <span style={{ width: 176, height: 176, borderRadius: "50%", background: i === 2 ? "#0095F6" : "#fff", display: "flex", alignItems: "center", justifyContent: "center", boxShadow: "0 16px 36px rgba(0,0,0,.4)", transform: `scale(${1 - press * 0.1})` }}>
          {icon ? icon(C.ink) : <b style={{ color: "#fff", fontWeight: 900, fontSize: 110, lineHeight: 1 }}>+</b>}
        </span>
        {i === 0 ? (
          <span style={{ position: "absolute", left: 62, top: 84, fontSize: 84, lineHeight: 1, filter: "drop-shadow(0 6px 10px rgba(0,0,0,.45))", transform: `translate(${(1 - press) * 22}px, ${(1 - press) * 34}px) rotate(${(1 - press) * 8}deg)` }}>👆</span>
        ) : null}
      </span>
      <span style={{ fontWeight: 900, fontStretch: "80%", fontSize: 46 }}>{label}</span>
    </div>
  );
};

// ── Subtítulos integrados: un modo por tramo ─────────────────────────────
const CAPTION_Y: Record<BeatT["layout"], number> = { hook: 0, chips: 1250, stamps: 300, number: 1300, card: 1330, calendar: 1330, outro: 0 };

const Captions: React.FC<{ p: FormatReelProps; b: BeatT }> = ({ p, b }) => {
  const frame = useCurrentFrame() + b.from;
  const ms = (frame / FORMAT_REEL_FPS) * 1000;
  if (b.caption === "title" || b.caption === "none") return null;
  const cue: CueT | undefined = p.cues.find((c) => ms >= c.startMs - 60 && ms <= c.endMs + 120);
  if (!cue || msToFrame(cue.startMs) >= b.to || msToFrame(cue.endMs) < b.from) return null;
  const y = CAPTION_Y[b.layout] || 1300;
  const keys = b.items.map((it) => it.text.toLowerCase());
  const local = frame - msToFrame(cue.startMs);
  const pop = Math.min(1, Math.max(0, local / 4));
  const wordNow = cue.words.filter((w) => w.startMs <= ms + 40).pop();
  const words = cue.words.map((w) => w.text);
  const isKey = (w: string) => keys.some((k) => k && k.split(" ").some((part) => part.length > 3 && w.toLowerCase().includes(part)));
  const base: React.CSSProperties = { position: "absolute", left: 56, right: 56, top: y, display: "flex", justifyContent: "center", opacity: pop, transform: `translateY(${(1 - pop) * 20}px)` };
  if (b.caption === "pop") {
    return (
      <div style={{ ...base, top: b.layout === "card" || b.layout === "calendar" ? y : 820 }}>
        <span style={{ ...cond(150, "68%"), color: "#fff", textTransform: "uppercase", textShadow: "0 8px 30px rgba(0,0,0,.6)" }}>{wordNow?.text.replace(/[.,;:]$/, "") ?? ""}</span>
      </div>
    );
  }
  if (b.caption === "chunk") {
    return (
      <div style={{ ...base, flexWrap: "wrap", gap: 14 }}>
        {words.map((w, i) => (
          <span key={i} style={{ ...cond(84, "70%"), textTransform: "uppercase", color: isKey(w) ? p.accent : "#fff", textShadow: "0 6px 24px rgba(0,0,0,.7)" }}>{w}</span>
        ))}
      </div>
    );
  }
  if (b.caption === "marker") {
    return (
      <div style={{ ...base, flexWrap: "wrap", gap: 10 }}>
        {cue.words.map((w, i) => {
          const on = w.startMs <= ms + 40;
          return (
            <span key={i} style={{ fontSize: 54, fontWeight: 800, color: on && isKey(w.text) ? C.ink : "#fff", background: on && isKey(w.text) ? GOLD : "rgba(10,13,18,.62)", padding: "4px 12px", borderRadius: 8 }}>{w.text}</span>
          );
        })}
      </div>
    );
  }
  if (b.caption === "callout") {
    return (
      <div style={base}>
        <div style={{ background: "#fff", color: C.ink, padding: "18px 28px", borderLeft: `14px solid ${p.accent}`, fontSize: 52, fontWeight: 800, lineHeight: 1.15, boxShadow: "0 14px 30px rgba(0,0,0,.35)", maxWidth: 920 }}>
          {cue.words.map((w, i) => <span key={i} style={{ opacity: w.startMs <= ms + 40 ? 1 : 0.35 }}>{w.text} </span>)}
        </div>
      </div>
    );
  }
  return (
    <div style={base}>
      <div style={{ background: "rgba(10,13,18,.82)", color: "#fff", padding: "16px 34px", borderRadius: 60, fontSize: 52, fontWeight: 800, lineHeight: 1.15, maxWidth: 940, textAlign: "center" }}>
        {cue.words.map((w, i) => <span key={i} style={{ color: w.startMs <= ms + 40 && isKey(w.text) ? p.accent : "#fff" }}>{w.text} </span>)}
      </div>
    </div>
  );
};

const Flash: React.FC = () => {
  const frame = useCurrentFrame();
  const o = interpolate(frame, [0, 5], [0.55, 0], clamp);
  return o > 0 ? <AbsoluteFill style={{ background: "#fff", opacity: o }} /> : null;
};

const BeatView: React.FC<{ p: FormatReelProps; b: BeatT }> = ({ p, b }) => (
  <AbsoluteFill>
    <Media p={p} layout={b.layout} />
    {b.layout === "hook" ? <Hook p={p} b={b} /> : null}
    {b.layout === "chips" ? <Chips p={p} b={b} /> : null}
    {b.layout === "stamps" ? <Stamps p={p} b={b} /> : null}
    {b.layout === "number" ? <NumberBeat p={p} b={b} /> : null}
    {b.layout === "card" ? <Card p={p} b={b} /> : null}
    {b.layout === "calendar" ? <Calendar b={b} /> : null}
    {b.layout === "outro" ? <Outro /> : <Bug p={p} enter={b.layout === "hook"} />}
    {b.layout === "hook" ? <Credit text={p.credit} /> : null}
    <Captions p={p} b={b} />
    <Flash />
  </AbsoluteFill>
);

const Sfx: React.FC<{ at: number; src: string; volume: number }> = ({ at, src, volume }) => (
  <Sequence from={Math.max(0, Math.round(at))} layout="none">
    <Audio src={staticFile(src)} volume={volume} />
  </Sequence>
);

export const FormatReel: React.FC<FormatReelProps> = (p) => {
  useV2FontsReady();
  return (
    <AbsoluteFill style={{ fontFamily: V2_FONT_SANS, background: C.ink, color: "#fff" }}>
      {p.beats.map((b, i) => (
        <Sequence key={i} from={b.from} durationInFrames={Math.max(1, b.to - b.from)}>
          <BeatView p={p} b={b} />
        </Sequence>
      ))}
      {p.voiceFile ? <Audio src={staticFile(p.voiceFile)} /> : null}
      {p.music ? <Audio src={staticFile("newscast/bed.mp3")} volume={0.1} loop /> : null}
      <Sfx at={0} src="newscast/impact.mp3" volume={0.45} />
      {p.beats.slice(1).map((b, i) => <Sfx key={`w${i}`} at={b.from} src="newscast/whoosh.mp3" volume={0.32} />)}
      {p.beats.flatMap((b) => (b.layout === "hook" ? [] : b.items)).map((it, i) => <Sfx key={`t${i}`} at={it.at} src="newscast/tick.mp3" volume={0.3} />)}
    </AbsoluteFill>
  );
};

export const FORMAT_REEL_DEFAULTS: FormatReelProps = {
  kind: "du",
  badge: "DATO ÚTIL",
  accent: GOLD,
  media: { type: "photo", file: "logo.png", width: 1000, height: 1000 },
  credit: "",
  place: null,
  voiceFile: "",
  totalFrames: 150,
  cues: [],
  beats: [
    { from: 0, to: 60, layout: "hook", caption: "title", title: "¿Vas a estudiar en la UNLaR? Anotá esto.", items: [], value: "", label: "", detail: "", index: 0 },
    { from: 60, to: 110, layout: "card", caption: "pill", title: "", items: [{ text: "27", at: 70 }], value: "27 de diciembre", label: "Inscripciones", detail: "último día para anotarte", index: 1 },
    { from: 110, to: 150, layout: "outro", caption: "none", title: "", items: [], value: "", label: "", detail: "", index: 0 },
  ],
  cards: ["27 de diciembre"],
  music: false,
};
