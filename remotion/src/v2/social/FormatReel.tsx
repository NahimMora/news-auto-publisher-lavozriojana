// Reels de formato propio: Último momento (UM), Datos útiles (DU) y Efemérides (EF).
//
// Traslado FIEL de los prototipos aprobados en la mesa de formatos (UM-A4 y
// DU-C4, ronda 4, 2026-11-14): mismos componentes, tamaños, colores,
// animaciones y subtítulos. Los datos (guion, palabras con tiempo real de la
// voz, ítems) llegan de utils/format_reels.py.
//
// UM: video real continuo de fondo (cada tramo sólo cambia el filtro), gancho
// con el titular completo y la palabra que se dice marcada con una caja de
// color, mapa + chips, sellos, cifra gigante, balance con tilde y cierre.
// DU: foto con Ken Burns, pregunta gigante + cápsula de llamado, tarjetas
// apiladas (fecha con cápsula, lista con barras, monto o cifra con contador)
// y cierre. Subtítulos con las cinco formas del prototipo (callout, marker,
// pill, chunk, pop); el gancho no lleva subtítulo (el titular es el texto).
import React from "react";
import {
  AbsoluteFill, Audio, Easing, Img, OffthreadVideo, Sequence, interpolate, staticFile, useCurrentFrame,
} from "remotion";
import { z } from "zod";
import { fit } from "../fit";
import { useV2FontsReady } from "../fonts";
import { LA_RIOJA_PATH, LA_RIOJA_VIEW } from "../newscast5/laRioja";
import { V2_FONT_SANS } from "../tokens";

export const FORMAT_REEL_FPS = 30;
const C = { red: "#B30000", blue: "#2F6FB0", navy: "#0B2F4F", ink: "#0A0D12", gold: "#FFD15C", green: "#1E7A46" };
const MONO = "LVR Mono";
const EASE = Easing.bezier(0.2, 0.8, 0.2, 1);
const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

const Word = z.object({ t: z.string(), s: z.number(), e: z.number() });
const Item = z.object({ text: z.string(), at: z.number(), icon: z.string() });
const Beat = z.object({
  from: z.number(),
  to: z.number(),
  layout: z.enum(["hook", "mapchips", "stamps", "number", "check", "card", "who", "efmap", "years", "calendar", "outro"]),
  card: z.enum(["fecha", "lista", "monto", "cifra", "texto", ""]),
  cap: z.enum(["title", "callout", "marker", "pill", "chunk", "pop", "none"]),
  capY: z.number(),
  words: z.array(Word),
  keys: z.array(z.string()),
  ctaFrom: z.number(),
  items: z.array(Item),
  value: z.string(),
  unit: z.string(),
  label: z.string(),
  pill: z.string(),
  detail: z.string(),
  detailAt: z.number(),
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
  heads: z.array(z.string()),
  music: z.boolean(),
  beats: z.array(Beat),
  // EF: fecha del hecho (día, mes abreviado, año) y apodo/nombre del protagonista.
  ef: z.object({ day: z.string(), month: z.string(), year: z.string(), now: z.string() }).nullable(),
});
export type FormatReelProps = z.infer<typeof FormatReelSchema>;
type BeatT = z.infer<typeof Beat>;
type WordT = z.infer<typeof Word>;

// ── Utilidades de tiempo ─────────────────────────────────────────────────
const msToFrame = (ms: number) => (ms / 1000) * FORMAT_REEL_FPS;
const fold = (s: string) => s.toLowerCase().normalize("NFD").replace(/\p{M}/gu, "").replace(/[^\w$%]/g, "");
// Palabra actual (índice dentro del tramo) para el cuadro absoluto `abs`.
const currentWord = (words: WordT[], abs: number) => {
  let cw = -1;
  words.forEach((w, i) => {
    if (msToFrame(w.s) <= abs + 1) cw = i;
  });
  return cw;
};

// ── Animaciones del prototipo (CSS → cuadros) ────────────────────────────
const prog = (f: number, seconds: number, ease = EASE) => interpolate(f, [0, seconds * FORMAT_REEL_FPS], [0, 1], { ...clamp, easing: ease });
const keyframes = (p: number, stops: number[], values: number[]) => interpolate(p, stops, values, clamp);

// pop: scale(.3) rotate(-8°) → 70 % scale(1.1) rotate(2°) → 1
const popStyle = (f: number): React.CSSProperties => {
  if (f < 0) return { opacity: 0 };
  const p = prog(f, 0.45);
  return {
    opacity: keyframes(p, [0, 0.7], [0, 1]),
    transform: `scale(${keyframes(p, [0, 0.7, 1], [0.3, 1.1, 1])}) rotate(${keyframes(p, [0, 0.7, 1], [-8, 2, 0])}deg)`,
  };
};
// stampR: scale(2.4) rotate(r-10) → 60 % scale(.92) rotate(r) → 1
const stampStyle = (f: number, r: number): React.CSSProperties => {
  if (f < 0) return { opacity: 0 };
  const p = prog(f, 0.45);
  return {
    opacity: keyframes(p, [0, 0.6], [0, 1]),
    transform: `scale(${keyframes(p, [0, 0.6, 1], [2.4, 0.92, 1])}) rotate(${keyframes(p, [0, 0.6], [r - 10, r])}deg)`,
  };
};
const riseStyle = (f: number, d = 70, sec = 0.5): React.CSSProperties => {
  if (f < 0) return { opacity: 0 };
  const p = prog(f, sec);
  return { opacity: p, transform: `translateY(${(1 - p) * d}px)` };
};
const slamStyle = (f: number): React.CSSProperties => {
  if (f < 0) return { opacity: 0 };
  const p = prog(f, 0.5);
  return {
    opacity: keyframes(p, [0, 0.55], [0, 1]),
    transform: `scale(${keyframes(p, [0, 0.55, 1], [1.5, 0.96, 1])}) rotate(${keyframes(p, [0, 0.55], [-3, 0])}deg)`,
  };
};
const wipeStyle = (f: number): React.CSSProperties => ({ clipPath: `inset(0 ${100 - prog(f, 0.5, Easing.bezier(0.6, 0, 0.2, 1)) * 100}% 0 0)` });

// Transiciones de escena del prototipo.
type Tr = "flash" | "whip" | "zoom" | "up";
const sceneTransition = (f: number, tr: Tr): React.CSSProperties => {
  if (tr === "flash") return { filter: `brightness(${3 - 2 * prog(f, 0.35, Easing.out(Easing.quad))})` };
  if (tr === "whip") {
    const p = prog(f, 0.4, Easing.bezier(0.6, 0, 0.2, 1));
    return { transform: `translateX(${(1 - p) * 70}%) skewX(${(1 - p) * -8}deg)`, filter: `blur(${(1 - p) * 10}px)` };
  }
  if (tr === "zoom") {
    const p = prog(f, 0.45);
    return { transform: `scale(${1.25 - 0.25 * p})`, filter: `blur(${(1 - p) * 8}px)` };
  }
  return { transform: `translateY(${(1 - prog(f, 0.45)) * 25}%)` };
};

// ── Íconos ───────────────────────────────────────────────────────────────
const Pin: React.FC<{ color: string; size: number }> = ({ color, size }) => (
  <svg viewBox="0 0 24 24" width={size} height={size} style={{ flex: "none" }} aria-hidden>
    <path d="M12 2C8.1 2 5 5.1 5 9c0 5.2 7 13 7 13s7-7.8 7-13c0-3.9-3.1-7-7-7zm0 9.5A2.5 2.5 0 1 1 12 6.5a2.5 2.5 0 0 1 0 5z" fill={color} />
  </svg>
);
const SHARE = (c: string) => (
  <svg viewBox="0 0 24 24" width={86} height={86}><path fill="none" stroke={c} strokeWidth={2.2} strokeLinejoin="round" d="M21 3 3 10.5l7 2.5 2.5 7L21 3zM10 13l5-5" /></svg>
);
const SAVE = (c: string) => (
  <svg viewBox="0 0 24 24" width={86} height={86}><path fill="none" stroke={c} strokeWidth={2.2} strokeLinejoin="round" d="M6 3h12v18l-6-4.5L6 21z" /></svg>
);

// ── Fondo ────────────────────────────────────────────────────────────────
const VF: Record<BeatT["layout"], string> = {
  hook: "saturate(1.15) contrast(1.05)",
  mapchips: "brightness(.6)",
  stamps: "brightness(.7) saturate(.85)",
  number: "blur(16px) brightness(.42)",
  check: "brightness(.62)",
  card: "blur(16px) brightness(.5) saturate(1.1)",
  who: "brightness(.5)",
  efmap: "blur(12px) brightness(.42)",
  years: "brightness(.36)",
  calendar: "blur(6px) brightness(.45)",
  outro: "blur(14px) brightness(.38)",
};

// UM: un solo video que corre de punta a punta; el filtro cambia por tramo.
const VideoBackdrop: React.FC<{ p: FormatReelProps }> = ({ p }) => {
  const frame = useCurrentFrame();
  const beat = p.beats.find((b) => frame >= b.from && frame < b.to) ?? p.beats[p.beats.length - 1];
  return (
    <AbsoluteFill style={{ overflow: "hidden", background: "#000" }}>
      <OffthreadVideo
        src={staticFile(p.media.file)}
        muted
        style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover", filter: VF[beat.layout], transform: "scale(1.3)", transformOrigin: "50% 26%" }}
      />
    </AbsoluteFill>
  );
};

// DU: foto por escena con el Ken Burns del prototipo (6 s, 1.05 → 1.22).
const Photo: React.FC<{ p: FormatReelProps; filter?: string }> = ({ p, filter }) => {
  const frame = useCurrentFrame();
  const k = prog(frame, 6, Easing.linear);
  return (
    <div style={{ position: "absolute", inset: -60, overflow: "hidden" }}>
      <Img
        src={staticFile(p.media.file)}
        style={{ width: "100%", height: "100%", objectFit: "cover", objectPosition: "center 40%", filter, transform: `scale(${1.05 + 0.17 * k}) translate(${-2 * k}%, ${-2 * k}%)` }}
      />
    </div>
  );
};

// ── Cabeceras ────────────────────────────────────────────────────────────
const LiveDot: React.FC = () => {
  const frame = useCurrentFrame();
  return <i style={{ display: "inline-block", width: 20, height: 20, borderRadius: "50%", background: "#fff", opacity: Math.floor(frame / 15) % 2 ? 0 : 1 }} />;
};

const UmTop: React.FC<{ credit: string }> = ({ credit }) => {
  const frame = useCurrentFrame();
  return (
    <>
      <div style={{ position: "absolute", left: 44, top: 120, display: "flex", alignItems: "center", ...wipeStyle(frame) }}>
        <span style={{ background: "#fff", padding: "8px 16px 8px 8px", display: "flex", alignItems: "center", gap: 10, color: C.ink, fontWeight: 900, fontStretch: "72%", fontSize: 34 }}>
          <Img src={staticFile("logo.png")} style={{ width: 48, height: 48, borderRadius: "50%" }} />
          LA VOZ RIOJANA
        </span>
        <span style={{ background: C.red, color: "#fff", fontWeight: 900, fontStretch: "72%", fontSize: 34, padding: "16px 20px", display: "flex", alignItems: "center", gap: 12 }}>
          <LiveDot />
          ÚLTIMO MOMENTO
        </span>
      </div>
      {credit ? (
        <div style={{ position: "absolute", right: 36, top: 212, fontFamily: MONO, fontWeight: 700, fontSize: 22, color: "rgba(255,255,255,.85)", background: "rgba(0,0,0,.45)", padding: "6px 10px" }}>{credit}</div>
      ) : null}
    </>
  );
};

const Bug: React.FC = () => (
  <div style={{ position: "absolute", left: 44, top: 120, display: "flex", alignItems: "center", gap: 12, background: "rgba(10,13,18,.6)", padding: "8px 16px 8px 8px" }}>
    <Img src={staticFile("logo.png")} style={{ width: 52, height: 52, borderRadius: "50%", background: "#fff" }} />
    <span style={{ fontWeight: 900, fontStretch: "72%", fontSize: 30, letterSpacing: "0.04em" }}>LA VOZ RIOJANA</span>
  </div>
);

const DuHead: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <>
      <div style={{ position: "absolute", left: 56, top: 120, display: "inline-flex", alignItems: "center", gap: 14, fontWeight: 900, fontStretch: "72%", fontSize: 34, letterSpacing: "0.04em", lineHeight: 1 }}>
        <Img src={staticFile("logo.png")} style={{ width: 56, height: 56, borderRadius: "50%", background: "#fff" }} />
        LA VOZ RIOJANA
      </div>
      <div style={{ position: "absolute", right: 56, top: 126, background: C.gold, color: C.navy, fontWeight: 900, fontStretch: "75%", fontSize: 32, padding: "10px 18px", borderRadius: 30, ...popStyle(frame) }}>DATO ÚTIL</div>
    </>
  );
};

// ── Titular del gancho: entero desde el primer cuadro, palabra actual marcada ──
const TitleWords: React.FC<{ words: WordT[]; from: number; to: number; abs: number; acc: string; upper: boolean }> = ({ words, from, to, abs, acc, upper }) => {
  const cw = currentWord(words, abs);
  return (
    <>
      {words.slice(from, to).map((w, i) => {
        const k = from + i;
        const cur = k === cw;
        return (
          <React.Fragment key={k}>
            <span style={cur ? { background: acc, color: C.ink, boxShadow: `0 0 0 .05em ${acc}`, WebkitBoxDecorationBreak: "clone", boxDecorationBreak: "clone" } : undefined}>
              {upper ? w.t.toUpperCase() : w.t}
            </span>{" "}
          </React.Fragment>
        );
      })}
    </>
  );
};

const HookUM: React.FC<{ p: FormatReelProps; b: BeatT }> = ({ p, b }) => {
  const frame = useCurrentFrame();
  const text = b.words.map((w) => w.t).join(" ").toUpperCase();
  const box = fit({ text, maxWidth: 968, maxHeight: 620, min: 110, max: 170, weight: 900, lh: 0.98, stretch: "condensed", maxLines: 5, uppercase: true });
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ background: "linear-gradient(rgba(10,13,18,.5),transparent 20%,transparent 38%,rgba(10,13,18,.9) 72%)" }} />
      <UmTop credit={p.credit} />
      <div style={{ position: "absolute", left: 56, right: 56, top: 800 }}>
        <div style={{ width: 200, height: 18, background: p.accent, marginBottom: 34, ...wipeStyle(frame) }} />
        <h2 style={{ margin: 0, fontWeight: 900, fontStretch: "72%", fontSize: box.fontSize, lineHeight: 0.98, ...slamStyle(frame) }}>
          <TitleWords words={b.words} from={0} to={b.words.length} abs={frame + b.from} acc={p.accent} upper />
        </h2>
      </div>
    </AbsoluteFill>
  );
};

const HookDU: React.FC<{ p: FormatReelProps; b: BeatT }> = ({ p, b }) => {
  const frame = useCurrentFrame();
  const q = b.ctaFrom >= 0 ? b.ctaFrom : b.words.length;
  const text = b.words.slice(0, q).map((w) => w.t).join(" ");
  const box = fit({ text, maxWidth: 968, maxHeight: 560, min: 120, max: 190, weight: 900, lh: 0.98, stretch: "condensed", maxLines: 4 });
  const ctaAt = q < b.words.length ? msToFrame(b.words[q].s) - b.from : 1e9;
  const bounce = Math.sin(((frame / FORMAT_REEL_FPS) * Math.PI * 2) / 0.9) * 9 + 9;
  return (
    <AbsoluteFill>
      <Photo p={p} />
      <AbsoluteFill style={{ background: "linear-gradient(rgba(11,47,79,.35),rgba(11,47,79,.05) 25%,rgba(11,47,79,.6) 45%,rgba(11,47,79,.96) 80%)" }} />
      <DuHead />
      <h2 style={{ position: "absolute", left: 56, right: 56, top: 700, margin: 0, fontWeight: 900, fontStretch: "72%", fontSize: box.fontSize, lineHeight: 0.98, ...slamStyle(frame) }}>
        <TitleWords words={b.words} from={0} to={q} abs={frame + b.from} acc={p.accent} upper={false} />
      </h2>
      {q < b.words.length ? (
        <div style={{ position: "absolute", left: 56, top: 1300, ...popStyle(frame - ctaAt) }}>
          <div style={{ display: "flex", alignItems: "center", gap: 18, background: C.gold, color: C.navy, borderRadius: 70, padding: "22px 40px", fontWeight: 900, fontStretch: "78%", fontSize: 64, transform: "rotate(-2deg)" }}>
            <span><TitleWords words={b.words} from={q} to={b.words.length} abs={frame + b.from} acc="#ffffff" upper={false} /></span>
            <span style={{ display: "inline-block", transform: `translateY(${bounce}px)` }}>👇</span>
          </div>
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

// ── Último momento ───────────────────────────────────────────────────────
const MapBox: React.FC<{ place: NonNullable<FormatReelProps["place"]>; acc: string }> = ({ place, acc }) => {
  const frame = useCurrentFrame();
  const ping = ((frame / FORMAT_REEL_FPS) % 1.4) / 1.4;
  return (
    <div style={{ position: "absolute", left: 44, top: 470, width: 540, height: 631, boxSizing: "border-box", background: "rgba(10,13,18,.82)", border: "6px solid #fff", padding: 22, ...popStyle(frame) }}>
      <svg viewBox={`0 0 ${LA_RIOJA_VIEW.w} ${LA_RIOJA_VIEW.h}`} style={{ width: "100%", height: "100%", overflow: "visible" }} aria-hidden>
        <path d={LA_RIOJA_PATH} fill="rgba(255,255,255,.1)" stroke="rgba(255,255,255,.7)" strokeWidth={6} />
        <circle cx={place.x} cy={place.y} r={30 * (0.6 + 2 * ping)} fill="none" stroke={acc} strokeWidth={9} opacity={0.9 * (1 - ping)} />
        <circle cx={place.x} cy={place.y} r={24} fill={acc} stroke="#fff" strokeWidth={8} />
        <text x={place.x + 44} y={place.y + 18} fill="#fff" fontFamily={V2_FONT_SANS} fontWeight={900} fontStretch="75%" fontSize={70} style={{ paintOrder: "stroke", stroke: C.ink, strokeWidth: 10 }}>
          {place.label}
        </text>
      </svg>
    </div>
  );
};

const MapChips: React.FC<{ p: FormatReelProps; b: BeatT }> = ({ p, b }) => {
  const frame = useCurrentFrame();
  const left = p.place ? 610 : 56;
  const styles: [string, string, string | undefined][] = [[p.accent, C.ink, undefined], [C.red, "#fff", undefined], [C.ink, "#fff", `12px solid ${p.accent}`]];
  const tops = [500, 720, 900];
  return (
    <AbsoluteFill>
      <Bug />
      {p.place ? <MapBox place={p.place} acc={p.accent} /> : null}
      {b.items.slice(0, 3).map((it, i) => {
        const f = frame - (it.at - b.from);
        if (f < 0) return null;
        const [bg, fg, border] = styles[i];
        return (
          <div key={i} style={{ position: "absolute", left, right: 44, top: tops[i], background: bg, color: fg, fontWeight: 900, fontStretch: "72%", fontSize: 50, lineHeight: 1, padding: "20px 24px", boxShadow: "0 12px 28px rgba(0,0,0,.35)", borderLeft: border, display: "flex", alignItems: "center", gap: 10, ...popStyle(f) }}>
            {it.icon === "pin" ? <Pin color={fg} size={44} /> : null}
            <span>{it.text.toUpperCase()}</span>
          </div>
        );
      })}
    </AbsoluteFill>
  );
};

const Stamp: React.FC<{ f: number; text: string; x: number; y: number; r: number; bg: string; size?: number; right?: number; center?: boolean }> = ({ f, text, x, y, r, bg, size = 92, right, center }) => {
  if (f < 0) return null;
  return (
    <div style={{ position: "absolute", left: x, right, top: y, border: "10px solid #fff", color: "#fff", background: bg, fontWeight: 900, fontStretch: "70%", fontSize: size, lineHeight: 0.95, padding: "14px 30px", textAlign: center ? "center" : undefined, ...stampStyle(f, r) }}>
      {text.toUpperCase()}
    </div>
  );
};

const Stamps: React.FC<{ p: FormatReelProps; b: BeatT }> = ({ p, b }) => {
  const frame = useCurrentFrame();
  const spots: [number, number, number, string][] = [[90, 560, -6, "rgba(10,13,18,.65)"], [160, 800, 4, p.accent], [60, 1060, -3, C.red]];
  return (
    <AbsoluteFill>
      {b.items.slice(0, 3).map((it, i) => (
        <Stamp key={i} f={frame - (it.at - b.from)} text={it.text} x={spots[i][0]} y={spots[i][1]} r={spots[i][2]} bg={spots[i][3]} />
      ))}
    </AbsoluteFill>
  );
};

// Contador: cifras enteras simples cuentan desde 0; si no, la cifra entra entera.
const counted = (value: string, f: number) => {
  const m = value.match(/^([^\d]*)([\d.]+)([^\d]*)$/);
  const n = m ? Number(m[2].replace(/\./g, "")) : NaN;
  if (!m || !Number.isFinite(n) || n <= 0) return value;
  const t = interpolate(f, [0, 0.8 * FORMAT_REEL_FPS], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
  return `${m[1]}${Math.round(n * t).toLocaleString("es-AR")}${m[3]}`;
};

const NumberBeat: React.FC<{ p: FormatReelProps; b: BeatT }> = ({ p, b }) => {
  const frame = useCurrentFrame();
  const labelAt = b.items[0] ? b.items[0].at - b.from : 8;
  const box = fit({ text: b.value, maxWidth: 1000, maxHeight: 420, min: 160, max: 460, weight: 900, lh: 0.85, stretch: "condensed", maxLines: 1 });
  return (
    <AbsoluteFill>
      <Bug />
      <div style={{ position: "absolute", left: 0, right: 0, top: 360, textAlign: "center", fontWeight: 900, fontStretch: "62%", fontSize: box.fontSize, lineHeight: 0.85, color: p.accent, ...slamStyle(frame) }}>{counted(b.value, frame)}</div>
      <div style={{ position: "absolute", left: 60, right: 60, top: 770, textAlign: "center", fontWeight: 900, fontStretch: "72%", fontSize: 100, lineHeight: 0.95, ...riseStyle(frame - labelAt) }}>{b.label.toUpperCase()}</div>
      {b.detail ? <Stamp f={frame - (b.detailAt - b.from)} text={b.detail} x={170} right={170} y={1020} r={-4} bg={C.green} size={74} center /> : null}
    </AbsoluteFill>
  );
};

const CheckBeat: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill>
      <Bug />
      <AbsoluteFill style={{ background: "radial-gradient(circle at 50% 50%,rgba(10,13,18,.2),rgba(10,13,18,.75))" }} />
      <div style={{ position: "absolute", left: 0, right: 0, top: 500, display: "flex", justifyContent: "center", ...popStyle(frame) }}>
        <span style={{ width: 200, height: 200, borderRadius: "50%", background: C.green, border: "10px solid #fff", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 900, fontSize: 120 }}>✓</span>
      </div>
    </AbsoluteFill>
  );
};

// ── Datos útiles: cada dato con su forma propia, nada lineal ─────────────
// Cada tarjeta entra desde un lado distinto y queda apenas inclinada; los
// datos ya contados se achican a fichas arriba (no una pila que baja). Forma
// por tipo: fecha = hoja de calendario, monto = ticket troquelado, cifra =
// número gigante con sticker de unidad, lista = fichas grandes con ícono,
// texto = nota adhesiva.
const Badge: React.FC<{ n: number; size: number }> = ({ n, size }) => (
  <span style={{ width: size, height: size, borderRadius: "50%", background: C.gold, color: C.navy, display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 900, fontSize: size * 0.56, flex: "none" }}>{n}</span>
);

const lit = (f: number): React.CSSProperties => (f < 0 ? { opacity: 0.2, filter: "grayscale(1)" } : { opacity: 1, ...popStyle(f) });

const MONTHS: Record<string, string> = { enero: "ENE", febrero: "FEB", marzo: "MAR", abril: "ABR", mayo: "MAY", junio: "JUN", julio: "JUL", agosto: "AGO", septiembre: "SEP", setiembre: "SEP", octubre: "OCT", noviembre: "NOV", diciembre: "DIC" };
const parseDate = (value: string): { day: string; month: string } | null => {
  const m = value.toLowerCase().normalize("NFD").replace(/\p{M}/gu, "").match(/(\d{1,2})\s*(?:de\s+)?([a-z]+)/);
  if (!m || !MONTHS[m[2]]) return null;
  return { day: m[1], month: MONTHS[m[2]] };
};

const Label: React.FC<{ text: string; color?: string }> = ({ text, color = C.blue }) => (
  <div style={{ fontFamily: MONO, fontWeight: 700, fontSize: 30, lineHeight: 1.1, letterSpacing: "0.08em", textTransform: "uppercase", color }}>{text}</div>
);

const Detail: React.FC<{ b: BeatT; frame: number; color?: string }> = ({ b, frame, color = "#3D5A75" }) =>
  b.detail ? <div style={{ fontSize: 40, fontWeight: 700, lineHeight: 1.15, color, marginTop: 16, ...riseStyle(frame - (b.detailAt - b.from)) }}>{b.detail}</div> : null;

// Fecha: hoja de calendario con el día gigante; cápsula y rótulo al costado.
const DateCard: React.FC<{ b: BeatT; frame: number; valueAt: number }> = ({ b, frame, valueAt }) => {
  const d = parseDate(b.value);
  const tear = prog(frame - valueAt, 0.45);
  return (
    <div style={{ display: "flex", gap: 40, alignItems: "center" }}>
      <div style={{ width: 420, flex: "none", borderRadius: 34, overflow: "hidden", background: "#fff", color: C.ink, textAlign: "center", boxShadow: "0 26px 60px rgba(0,0,0,.45)", transform: `rotate(${-4 + 4 * tear}deg)` }}>
        <div style={{ background: C.red, color: "#fff", fontWeight: 900, fontStretch: "75%", fontSize: 86, letterSpacing: "0.14em", padding: "18px 0" }}>{d ? d.month : "FECHA"}</div>
        <div style={{ fontWeight: 900, fontStretch: "62%", fontSize: d ? 320 : 100, lineHeight: 1, padding: d ? "8px 0 22px" : "46px 20px", ...lit(frame - valueAt) }}>{d ? d.day : b.value.toUpperCase()}</div>
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <Label text={b.label} color={C.gold} />
        {b.pill ? <div style={{ display: "inline-block", marginTop: 20, background: C.gold, color: C.navy, borderRadius: 40, padding: "10px 24px", fontWeight: 900, fontStretch: "78%", fontSize: 46, ...popStyle(frame - 4) }}>{b.pill.toUpperCase()}</div> : null}
        <div style={{ fontWeight: 900, fontStretch: "70%", fontSize: 72, lineHeight: 0.95, marginTop: 16, color: "#fff", ...lit(frame - valueAt) }}>{b.value.toUpperCase()}</div>
        <Detail b={b} frame={frame} color="rgba(255,255,255,.85)" />
      </div>
    </div>
  );
};

// Monto: ticket navy troquelado, cifra dorada con contador.
const AmountCard: React.FC<{ b: BeatT; frame: number; valueAt: number }> = ({ b, frame, valueAt }) => {
  const f = frame - Math.min(valueAt, 12);
  const shown = f < 0 ? b.value.replace(/[\d.]+/, "0") : counted(b.value, f);
  const notch = (side: "left" | "right"): React.CSSProperties => ({ position: "absolute", top: 232, [side]: -34, width: 68, height: 68, borderRadius: "50%", background: "rgba(11,47,79,.95)" });
  return (
    <div style={{ position: "relative", background: C.navy, borderRadius: 34, padding: "40px 50px 44px", boxShadow: "0 26px 60px rgba(0,0,0,.45)", border: `5px solid ${C.gold}` }}>
      <Label text={b.label} color={C.gold} />
      <div style={{ fontWeight: 900, fontStretch: "66%", fontSize: 250, lineHeight: 0.95, color: C.gold, marginTop: 20 }}>{shown}</div>
      <div style={{ borderTop: "6px dashed rgba(255,209,92,.6)", margin: "22px -50px 0" }} />
      <span style={notch("left")} />
      <span style={notch("right")} />
      {b.detail || b.pill ? <div style={{ fontSize: 42, fontWeight: 800, color: "#fff", marginTop: 22, ...riseStyle(frame - (b.detailAt - b.from)) }}>{b.detail || b.pill}</div> : null}
    </div>
  );
};

// Cifra: número gigante con la unidad como sticker girado.
const NumberCard: React.FC<{ b: BeatT; frame: number; valueAt: number }> = ({ b, frame, valueAt }) => {
  const f = frame - Math.min(valueAt, 12);
  const shown = f < 0 ? b.value.replace(/[\d.]+/, "0") : counted(b.value, f);
  return (
    <div style={{ position: "relative", textAlign: "center", paddingTop: 10 }}>
      <Label text={b.label} color={C.gold} />
      <div style={{ fontWeight: 900, fontStretch: "62%", fontSize: 420, lineHeight: 0.85, color: "#fff", textShadow: "0 18px 50px rgba(0,0,0,.5)", marginTop: 18 }}>{shown}</div>
      {b.unit ? (
        <div style={{ display: "inline-block", marginTop: 6, background: C.gold, color: C.navy, fontWeight: 900, fontStretch: "70%", fontSize: 92, padding: "8px 34px", borderRadius: 14, boxShadow: "0 14px 34px rgba(0,0,0,.4)", ...stampStyle(frame - Math.min(valueAt + 10, 22), -4) }}>{b.unit.toUpperCase()}</div>
      ) : null}
      {b.pill || b.detail ? <div style={{ fontSize: 42, fontWeight: 800, color: "#fff", marginTop: 26, ...riseStyle(frame - (b.detailAt - b.from)) }}>{b.pill || b.detail}</div> : null}
    </div>
  );
};

// Lista: fichas grandes, alternadas, con el ícono enorme.
const ListCard: React.FC<{ b: BeatT; frame: number }> = ({ b, frame }) => {
  const opts = b.items.slice(0, 3);
  const two = opts.length === 2;
  return (
    <div>
      <Label text={b.label} color={C.gold} />
      <div style={{ display: "flex", flexDirection: two ? "row" : "column", gap: 28, marginTop: 26 }}>
        {opts.map((it, i) => {
          const f = frame - (it.at - b.from);
          return (
            <div key={i} style={{ flex: 1, background: i % 2 ? C.blue : "#fff", color: i % 2 ? "#fff" : C.navy, borderRadius: 34, padding: two ? "54px 20px" : "26px 34px", display: "flex", flexDirection: two ? "column" : "row", alignItems: "center", gap: two ? 14 : 26, boxShadow: "0 22px 50px rgba(0,0,0,.4)", transform: `rotate(${i % 2 ? 2.5 : -2.5}deg)`, ...lit(f) }}>
              {it.icon ? <span style={{ fontSize: two ? 190 : 104, lineHeight: 1 }}>{it.icon}</span> : null}
              <span style={{ fontWeight: 900, fontStretch: "70%", fontSize: two ? 84 : 80, lineHeight: 1, textAlign: "center" }}>{it.text.toUpperCase()}</span>
            </div>
          );
        })}
      </div>
      <Detail b={b} frame={frame} color="rgba(255,255,255,.85)" />
    </div>
  );
};

// Texto: nota adhesiva dorada.
const NoteCard: React.FC<{ b: BeatT; frame: number; valueAt: number }> = ({ b, frame, valueAt }) => {
  const box = fit({ text: b.value.toUpperCase(), maxWidth: 780, maxHeight: 300, min: 80, max: 140, weight: 900, lh: 0.95, stretch: "condensed", maxLines: 3, uppercase: true });
  return (
    <div style={{ position: "relative", background: C.gold, color: C.navy, borderRadius: 8, padding: "56px 54px 48px", boxShadow: "0 30px 60px rgba(0,0,0,.45)" }}>
      <span style={{ position: "absolute", top: -26, left: "50%", width: 180, height: 52, marginLeft: -90, background: "rgba(255,255,255,.55)", transform: "rotate(-3deg)" }} />
      <Label text={b.label} color={C.navy} />
      {b.pill ? <div style={{ fontWeight: 900, fontStretch: "78%", fontSize: 46, marginTop: 14 }}>{b.pill.toUpperCase()}</div> : null}
      <div style={{ fontWeight: 900, fontStretch: "66%", fontSize: box.fontSize, lineHeight: 0.95, marginTop: 14, ...lit(frame - valueAt) }}>
        {box.lines.map((l, i) => <div key={i}>{l}</div>)}
      </div>
      <Detail b={b} frame={frame} color={C.navy} />
    </div>
  );
};

// Entrada distinta para cada tarjeta y una leve inclinación final.
const ENTRIES: { dx: number; dy: number; tilt: number }[] = [
  { dx: -1, dy: 0, tilt: -2 },
  { dx: 1, dy: 0, tilt: 2 },
  { dx: 0, dy: 1, tilt: -1.5 },
  { dx: -1, dy: -0.4, tilt: 2.5 },
  { dx: 1, dy: 0.4, tilt: -1 },
];

const Collected: React.FC<{ heads: string[]; frame: number }> = ({ heads, frame }) => (
  <>
    {heads.map((h, j) => {
      const last = j === heads.length - 1;
      const f = last ? frame : 99;
      const k = prog(f, 0.45);
      return (
        <div key={j} style={{ position: "absolute", left: 56 + (j % 2) * 490, top: 214 + Math.floor(j / 2) * 86, width: 478, height: 72, boxSizing: "border-box", background: "rgba(255,255,255,.95)", color: C.navy, borderRadius: 40, padding: "0 14px 0 24px", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, boxShadow: "0 10px 24px rgba(0,0,0,.3)", opacity: last ? k : 1, transform: last ? `translateY(${(1 - k) * 260}px) scale(${1.6 - 0.6 * k})` : undefined }}>
          <span style={{ fontWeight: 900, fontStretch: "70%", fontSize: 40, lineHeight: 1, whiteSpace: "nowrap", overflow: "hidden" }}>{h.toUpperCase()}</span>
          <Badge n={j + 1} size={46} />
        </div>
      );
    })}
  </>
);

const Card: React.FC<{ p: FormatReelProps; b: BeatT }> = ({ p, b }) => {
  const frame = useCurrentFrame();
  const n = b.index;
  const heads = p.heads.slice(0, Math.max(0, n - 1));
  const e = ENTRIES[(n - 1) % ENTRIES.length];
  const k = prog(frame, 0.65);
  const settle = keyframes(k, [0, 0.7, 1], [1, -0.04, 0]);
  const valueAt = (b.items[0]?.at ?? b.from + 6) - b.from;
  const top = 214 + Math.ceil(heads.length / 2) * 86 + 70;
  const body =
    b.card === "fecha" ? <DateCard b={b} frame={frame} valueAt={valueAt} />
      : b.card === "monto" ? <AmountCard b={b} frame={frame} valueAt={valueAt} />
        : b.card === "cifra" ? <NumberCard b={b} frame={frame} valueAt={valueAt} />
          : b.card === "lista" ? <ListCard b={b} frame={frame} />
            : <NoteCard b={b} frame={frame} valueAt={valueAt} />;
  return (
    <AbsoluteFill>
      <Photo p={p} filter={VF.card} />
      <AbsoluteFill style={{ background: "linear-gradient(rgba(11,47,79,.35),rgba(11,47,79,.85))" }} />
      <DuHead />
      <Collected heads={heads} frame={frame} />
      <div style={{ position: "absolute", left: 70, right: 70, top: Math.max(top, 560), transform: `translate(${e.dx * settle * 1000}px, ${e.dy * settle * 1400}px) rotate(${e.tilt + (e.dx || e.dy) * settle * 14}deg)` }}>
        <div style={{ position: "absolute", right: -18, top: -30, zIndex: 2 }}><Badge n={n} size={76} /></div>
        {body}
      </div>
    </AbsoluteFill>
  );
};

// ── Efemérides (EF): archivo histórico ───────────────────────────────────
// Misma estructura aprobada en EF-A4 (titular completo sobre el retrato,
// apodo y cargos, mapa, contador de años, calendario con sello) con lo que se
// sumó a UM/DU: titular con la palabra dicha marcada, subtítulos de cuatro
// formas distintas, algo nuevo en pantalla a cada rato y más gráfica (retrato
// de archivo con grano, medallón, mapa que se dibuja con mira, regla de años
// que se llena y calendario que pasa las hojas).
const BORDO = "#7A1426";
// Filtro del retrato por tramo: el gancho luce la foto; el resto la baja para que lea el gráfico.
const EF_VF: Record<BeatT["layout"], string> = { ...VF, hook: "brightness(1.12) contrast(1.1)", who: "brightness(.55)" };

// Retrato continuo de punta a punta: blanco y negro teñido de ROJO (duotono rojo
// LVR / bordó; el responsable lo pidió rojo en vez del gris pálido, 2026-11-15),
// grano de película que se mueve, rayas de proyector y viñeta. El filtro cambia por tramo.
const ArchiveBackdrop: React.FC<{ p: FormatReelProps }> = ({ p }) => {
  const frame = useCurrentFrame();
  const beat = p.beats.find((b) => frame >= b.from && frame < b.to) ?? p.beats[p.beats.length - 1];
  const k = frame / Math.max(1, p.totalFrames);
  const flicker = 1 + 0.035 * Math.sin(frame * 1.7) * Math.sin(frame * 0.53);
  const scratch = frame % 11 < 2;
  return (
    <AbsoluteFill style={{ overflow: "hidden", background: "#000" }}>
      <Img
        src={staticFile(p.media.file)}
        style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover", objectPosition: "center 30%", filter: `grayscale(1) contrast(1.15) ${EF_VF[beat.layout]} brightness(${flicker})`, transform: `scale(${1.08 + 0.16 * k}) translate(${-1.5 * k}%, ${-2 * k}%)` }}
      />
      <AbsoluteFill style={{ background: `linear-gradient(160deg,#E0303F,${BORDO})`, mixBlendMode: "multiply", opacity: beat.layout === "hook" ? 0.9 : 1 }} />
      <AbsoluteFill style={{ background: "#3A0710", mixBlendMode: "screen", opacity: 0.35 }} />
      <AbsoluteFill style={{ backgroundImage: "radial-gradient(rgba(255,255,255,.07) 1px,transparent 1.4px)", backgroundSize: "7px 7px", backgroundPosition: `${(frame * 37) % 7}px ${(frame * 53) % 7}px` }} />
      {scratch ? <div style={{ position: "absolute", left: (frame * 131) % 1080, top: 0, bottom: 0, width: 2, background: "rgba(255,255,255,.16)" }} /> : null}
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 45%,transparent 45%,rgba(0,0,0,.62))" }} />
    </AbsoluteFill>
  );
};

const EfHead: React.FC<{ p: FormatReelProps }> = ({ p }) => {
  const frame = useCurrentFrame();
  return (
    <>
      <div style={{ position: "absolute", left: 44, top: 120, display: "flex", alignItems: "center", ...wipeStyle(frame) }}>
        <span style={{ background: "#fff", padding: "8px 16px 8px 8px", display: "flex", alignItems: "center", gap: 10, color: C.ink, fontWeight: 900, fontStretch: "72%", fontSize: 34 }}>
          <Img src={staticFile("logo.png")} style={{ width: 48, height: 48, borderRadius: "50%" }} />
          LA VOZ RIOJANA
        </span>
        <span style={{ background: p.accent, color: C.navy, fontWeight: 900, fontStretch: "72%", fontSize: 34, padding: "16px 20px" }}>UN DÍA COMO HOY</span>
      </div>
      {p.ef ? (
        <div style={{ position: "absolute", right: 44, top: 108, width: 124, borderRadius: 16, overflow: "hidden", background: "#fff", color: C.ink, textAlign: "center", boxShadow: "0 10px 26px rgba(0,0,0,.45)", ...popStyle(frame - 6) }}>
          <div style={{ background: C.red, color: "#fff", fontWeight: 900, fontStretch: "75%", fontSize: 28, letterSpacing: "0.12em", padding: "4px 0" }}>{p.ef.month}</div>
          <div style={{ fontWeight: 900, fontStretch: "62%", fontSize: 72, lineHeight: 1, padding: "2px 0 6px" }}>{p.ef.day}</div>
        </div>
      ) : null}
    </>
  );
};

const HookEF: React.FC<{ p: FormatReelProps; b: BeatT }> = ({ p, b }) => {
  const frame = useCurrentFrame();
  const text = b.words.map((w) => w.t).join(" ").toUpperCase();
  const box = fit({ text, maxWidth: 968, maxHeight: 560, min: 104, max: 160, weight: 900, lh: 0.96, stretch: "condensed", maxLines: 5, uppercase: true });
  const r = prog(frame, 0.55);
  const drift = prog(frame, 6, Easing.linear);
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ background: "linear-gradient(rgba(10,13,18,.45),transparent 18%,transparent 40%,rgba(10,13,18,.94) 62%)" }} />
      <EfHead p={p} />
      {p.ef ? (
        <div style={{ position: "absolute", left: 30, top: 620, fontWeight: 900, fontStretch: "62%", fontSize: 400, lineHeight: 0.8, color: "transparent", WebkitTextStroke: `5px ${p.accent}`, opacity: 0.7 * r, transform: `translate(${-40 * drift}px, ${(1 - r) * 70}px)` }}>
          {p.ef.year}
        </div>
      ) : null}
      <div style={{ position: "absolute", left: 56, right: 56, top: 960 }}>
        <div style={{ width: 200, height: 18, background: p.accent, marginBottom: 30, ...wipeStyle(frame) }} />
        <h2 style={{ margin: 0, fontWeight: 900, fontStretch: "72%", fontSize: box.fontSize, lineHeight: 0.96, textShadow: "0 6px 30px rgba(0,0,0,.55)", ...slamStyle(frame) }}>
          <TitleWords words={b.words} from={0} to={b.words.length} abs={frame + b.from} acc={p.accent} upper />
        </h2>
      </div>
    </AbsoluteFill>
  );
};

// Quién era: medallón con el retrato y anillo que gira, apodo gigante, nombre y cargos.
const WhoEF: React.FC<{ p: FormatReelProps; b: BeatT }> = ({ p, b }) => {
  const frame = useCurrentFrame();
  const nick = fit({ text: b.value.toUpperCase(), maxWidth: 968, maxHeight: 200, min: 90, max: 180, weight: 900, lh: 0.9, stretch: "condensed", maxLines: 1, uppercase: true });
  const nameTop = 790 + Math.round(nick.fontSize * 0.9) + 24;
  return (
    <AbsoluteFill>
      <EfHead p={p} />
      <div style={{ position: "absolute", left: 300, top: 270, width: 480, height: 480, ...popStyle(frame) }}>
        <svg viewBox="0 0 480 480" style={{ position: "absolute", inset: 0, transform: `rotate(${frame * 0.6}deg)` }} aria-hidden>
          <circle cx={240} cy={240} r={232} fill="none" stroke={p.accent} strokeWidth={8} strokeDasharray="18 14" />
        </svg>
        <div style={{ position: "absolute", inset: 26, borderRadius: "50%", overflow: "hidden", border: "8px solid #fff", boxShadow: "0 20px 50px rgba(0,0,0,.5)" }}>
          <Img src={staticFile(p.media.file)} style={{ width: "100%", height: "100%", objectFit: "cover", objectPosition: "center 25%", filter: "grayscale(1) contrast(1.2) sepia(.25)" }} />
        </div>
      </div>
      {b.value ? (
        <div style={{ position: "absolute", left: 56, right: 56, top: 790, textAlign: "center", fontWeight: 900, fontStretch: "66%", fontSize: nick.fontSize, lineHeight: 0.9, color: p.accent, textShadow: "0 10px 30px rgba(0,0,0,.6)", ...slamStyle(frame - 4) }}>
          {b.value.toUpperCase()}
        </div>
      ) : null}
      {b.label ? (
        <div style={{ position: "absolute", left: 0, right: 0, top: nameTop, display: "flex", justifyContent: "center" }}>
          <span style={{ background: "#fff", color: C.navy, fontWeight: 900, fontStretch: "72%", fontSize: 58, padding: "12px 26px", ...wipeStyle(frame - 8) }}>{b.label.toUpperCase()}</span>
        </div>
      ) : null}
      <div style={{ position: "absolute", left: 56, right: 56, top: nameTop + 120, display: "flex", flexWrap: "wrap", justifyContent: "center", gap: 18 }}>
        {b.items.slice(0, 3).map((it, i) => {
          const f = frame - (it.at - b.from);
          return (
            <span key={i} style={{ background: i % 2 ? C.navy : BORDO, color: "#fff", fontWeight: 900, fontStretch: "75%", fontSize: 50, padding: "12px 22px", border: i % 2 ? `4px solid ${p.accent}` : undefined, boxShadow: "0 12px 28px rgba(0,0,0,.35)", ...(f < 0 ? { opacity: 0 } : popStyle(f)) }}>
              {it.text.toUpperCase()}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

// Dónde: mapa grande que se dibuja, mira que cruza al lugar, pulso y chips.
const MapEF: React.FC<{ p: FormatReelProps; b: BeatT }> = ({ p, b }) => {
  const frame = useCurrentFrame();
  const ping = ((frame / FORMAT_REEL_FPS) % 1.4) / 1.4;
  const draw = prog(frame, 0.9);
  const cross = prog(frame - 12, 0.5);
  const pl = p.place;
  const right = pl ? pl.x > 600 : false;
  return (
    <AbsoluteFill>
      <EfHead p={p} />
      {pl ? (
        <div style={{ position: "absolute", left: 189, top: 230, width: 702, height: 820, ...popStyle(frame) }}>
          <svg viewBox={`0 0 ${LA_RIOJA_VIEW.w} ${LA_RIOJA_VIEW.h}`} style={{ width: "100%", height: "100%", overflow: "visible" }} aria-hidden>
            <path d={LA_RIOJA_PATH} pathLength={1} fill={`rgba(11,47,79,${0.6 * draw})`} stroke="#fff" strokeWidth={7} strokeDasharray={1} strokeDashoffset={1 - draw} />
            <line x1={pl.x} y1={pl.y * (1 - cross)} x2={pl.x} y2={pl.y + (LA_RIOJA_VIEW.h - pl.y) * cross} stroke={p.accent} strokeWidth={4} strokeDasharray="14 10" opacity={0.75} />
            <line x1={pl.x * (1 - cross)} y1={pl.y} x2={pl.x + (LA_RIOJA_VIEW.w - pl.x) * cross} y2={pl.y} stroke={p.accent} strokeWidth={4} strokeDasharray="14 10" opacity={0.75} />
            {cross > 0.9 ? <circle cx={pl.x} cy={pl.y} r={34 * (0.6 + 2.2 * ping)} fill="none" stroke={p.accent} strokeWidth={10} opacity={0.9 * (1 - ping)} /> : null}
            <circle cx={pl.x} cy={pl.y} r={28 * cross} fill={p.accent} stroke="#fff" strokeWidth={9} />
            <text x={right ? pl.x - 52 : pl.x + 52} y={pl.y + 30} textAnchor={right ? "end" : "start"} fill="#fff" fontFamily={V2_FONT_SANS} fontWeight={900} fontStretch="72%" fontSize={110} opacity={cross} style={{ paintOrder: "stroke", stroke: C.ink, strokeWidth: 14 }}>
              {pl.label.toUpperCase()}
            </text>
          </svg>
        </div>
      ) : null}
      <div style={{ position: "absolute", left: 56, right: 56, top: pl ? 1090 : 600, display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center", gap: 14 }}>
        {b.items.slice(0, 3).map((it, i) => {
          const f = frame - (it.at - b.from);
          return (
            <span key={i} style={{ display: "inline-flex", alignItems: "center", gap: 10, background: i % 2 ? C.red : "#fff", color: i % 2 ? "#fff" : C.navy, fontWeight: 900, fontStretch: "72%", fontSize: pl ? 48 : 80, padding: "14px 22px", boxShadow: "0 12px 28px rgba(0,0,0,.35)", ...(f < 0 ? { opacity: 0 } : popStyle(f)) }}>
              {i === 0 ? <Pin color={C.navy} size={pl ? 40 : 64} /> : null}
              {it.text.toUpperCase()}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

// Cuántos años: regla de décadas que se llena del año del hecho al actual y contador gigante.
const YearsEF: React.FC<{ p: FormatReelProps; b: BeatT }> = ({ p, b }) => {
  const frame = useCurrentFrame();
  const valueAt = (b.items[0]?.at ?? b.from + 8) - b.from;
  const y0 = Number(p.ef?.year ?? 0);
  const y1 = Number(p.ef?.now ?? 0);
  const n = Math.max(1, Math.floor((y1 - y0) / 10));
  const fill = prog(frame - 4, 1.1, Easing.inOut(Easing.cubic));
  const f = frame - Math.min(valueAt, 10);
  const shown = f < 0 ? b.value.replace(/[\d.]+/, "0") : counted(b.value, f);
  return (
    <AbsoluteFill>
      <EfHead p={p} />
      {y0 && y1 ? (
        <div style={{ position: "absolute", left: 90, right: 90, top: 330, height: 150, ...riseStyle(frame) }}>
          <div style={{ position: "absolute", left: 0, top: 0, fontWeight: 900, fontStretch: "72%", fontSize: 64, lineHeight: 1 }}>{y0}</div>
          <div style={{ position: "absolute", right: 0, top: 0, fontWeight: 900, fontStretch: "72%", fontSize: 64, lineHeight: 1, color: p.accent, opacity: fill > 0.95 ? 1 : 0.35 }}>{y1}</div>
          <div style={{ position: "absolute", left: 0, right: 0, top: 100, height: 10, background: "rgba(255,255,255,.25)", borderRadius: 5 }} />
          <div style={{ position: "absolute", left: 0, top: 100, height: 10, width: `${fill * 100}%`, background: `linear-gradient(90deg,#fff,${p.accent})`, borderRadius: 5 }} />
          {Array.from({ length: n + 1 }).map((_, i) => (
            <span key={i} style={{ position: "absolute", left: `${(i / n) * 100}%`, top: i % 5 === 0 ? 80 : 88, width: 4, height: i % 5 === 0 ? 50 : 34, marginLeft: -2, background: i / n <= fill ? "#fff" : "rgba(255,255,255,.25)" }} />
          ))}
          <span style={{ position: "absolute", left: `${fill * 100}%`, top: 89, width: 32, height: 32, marginLeft: -16, borderRadius: "50%", background: p.accent, boxShadow: "0 0 0 10px rgba(255,209,92,.3)" }} />
        </div>
      ) : null}
      <div style={{ position: "absolute", left: 0, right: 0, top: 560, textAlign: "center", fontWeight: 900, fontStretch: "62%", fontSize: 400, lineHeight: 0.85, color: p.accent, textShadow: "0 18px 50px rgba(0,0,0,.5)", ...slamStyle(frame) }}>{shown}</div>
      <div style={{ position: "absolute", left: 0, right: 0, top: 930, display: "flex", justifyContent: "center" }}>
        <span style={{ background: "#fff", color: C.navy, fontWeight: 900, fontStretch: "70%", fontSize: 110, lineHeight: 1, padding: "8px 44px", borderRadius: 12, boxShadow: "0 14px 34px rgba(0,0,0,.4)", ...stampStyle(frame - Math.min(valueAt + 8, 20), -3) }}>
          {(b.label || "años").toUpperCase()}
        </span>
      </div>
    </AbsoluteFill>
  );
};

// Por qué importa: hoja de calendario que cae y pasa los días hasta la fecha, sello y dato.
const CalendarEF: React.FC<{ p: FormatReelProps; b: BeatT }> = ({ p, b }) => {
  const frame = useCurrentFrame();
  const d = parseDate(b.value) ?? (p.ef ? { day: p.ef.day, month: p.ef.month } : null);
  const target = Number(d?.day ?? 1);
  const dropP = prog(frame, 0.45);
  const flip = prog(frame - 6, 0.8, Easing.out(Easing.cubic));
  const day = Math.max(1, Math.round(1 + (target - 1) * flip));
  const sealAt = (b.items[0]?.at ?? b.from + 20) - b.from;
  return (
    <AbsoluteFill>
      <EfHead p={p} />
      <div style={{ position: "absolute", left: 310, top: 290, width: 460, transform: `translateY(${(1 - dropP) * -900}px)` }}>
        <div style={{ position: "absolute", inset: 0, transform: "rotate(5deg) translate(16px,12px)", background: "#E9E2D0", borderRadius: 30, boxShadow: "0 20px 50px rgba(0,0,0,.4)" }} />
        <div style={{ position: "relative", borderRadius: 30, overflow: "hidden", background: "#fff", color: C.ink, textAlign: "center", boxShadow: "0 24px 60px rgba(0,0,0,.5)" }}>
          <div style={{ background: C.red, color: "#fff", fontWeight: 900, fontStretch: "75%", fontSize: 80, letterSpacing: "0.14em", padding: "16px 0" }}>{d?.month ?? ""}</div>
          <div style={{ fontWeight: 900, fontStretch: "62%", fontSize: 290, lineHeight: 1, padding: "6px 0 18px" }}>{day}</div>
        </div>
        {[120, 316].map((x) => <span key={x} style={{ position: "absolute", left: x, top: -18, width: 24, height: 52, borderRadius: 12, background: C.ink, border: "4px solid #fff" }} />)}
      </div>
      {b.items[0] ? (
        <div style={{ position: "absolute", left: 100, right: 100, top: 860, ...stampStyle(frame - sealAt, -6) }}>
          <div style={{ border: `14px solid ${p.accent}`, color: p.accent, textAlign: "center", padding: "22px 20px", background: "rgba(10,13,18,.65)", fontWeight: 900, fontStretch: "70%", fontSize: 104, lineHeight: 0.95 }}>
            {b.items[0].text.toUpperCase()}
          </div>
        </div>
      ) : null}
      {b.detail ? (
        <div style={{ position: "absolute", left: 0, right: 0, top: 1150, display: "flex", justifyContent: "center", ...riseStyle(frame - (b.detailAt - b.from)) }}>
          <span style={{ background: C.navy, color: "#fff", fontFamily: MONO, fontWeight: 700, fontSize: 40, letterSpacing: "0.06em", padding: "12px 24px", border: `3px solid ${p.accent}` }}>{b.detail.toUpperCase()}</span>
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

// ── Cierre ───────────────────────────────────────────────────────────────
const ActButton: React.FC<{ i: number; label: string; icon: ((c: string) => React.ReactNode) | null; frame: number }> = ({ i, label, icon, frame }) => {
  const f = frame - Math.round(i * 0.16 * FORMAT_REEL_FPS);
  const cycle = ((((frame / FORMAT_REEL_FPS - 0.5) % 1.1) + 1.1) % 1.1) / 1.1;
  const active = frame > 0.5 * FORMAT_REEL_FPS && i === 0;
  const press = active ? keyframes(cycle, [0, 0.38, 0.48, 0.62, 1], [1, 1, 0.9, 1, 1]) : 1;
  const ringS = active ? keyframes(cycle, [0, 0.44, 0.9, 1], [1, 1, 1.5, 1.5]) : 1;
  const ringO = active ? keyframes(cycle, [0, 0.44, 0.5, 0.9, 1], [0, 0, 0.85, 0, 0]) : 0;
  const finger = active ? keyframes(cycle, [0, 0.4, 0.55, 1], [1, 0, 0, 1]) : 1;
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 18, ...popStyle(f) }}>
      <span style={{ position: "relative", display: "block", width: 176, height: 176 }}>
        {i === 0 ? <span style={{ position: "absolute", inset: 0, borderRadius: "50%", border: "6px solid #fff", transform: `scale(${ringS})`, opacity: ringO }} /> : null}
        <span style={{ width: 176, height: 176, borderRadius: "50%", background: i === 2 ? "#0095F6" : "#fff", display: "flex", alignItems: "center", justifyContent: "center", boxShadow: "0 16px 36px rgba(0,0,0,.4)", transform: `scale(${press})` }}>
          {icon ? icon(C.ink) : <b style={{ color: "#fff", fontWeight: 900, fontSize: 110, lineHeight: 1 }}>+</b>}
        </span>
        {i === 0 ? (
          <span style={{ position: "absolute", left: 62, top: 84, fontSize: 84, lineHeight: 1, filter: "drop-shadow(0 6px 10px rgba(0,0,0,.45))", transform: `translate(${finger * 22}px, ${finger * 34}px) rotate(${finger * 8}deg)` }}>👆</span>
        ) : null}
      </span>
      <span style={{ fontWeight: 900, fontStretch: "80%", fontSize: 46 }}>{label}</span>
    </div>
  );
};

const Outro: React.FC<{ p: FormatReelProps }> = ({ p }) => {
  const frame = useCurrentFrame();
  const acts: [string, ((c: string) => React.ReactNode) | null][] = [["Compartí", SHARE], ["Guardá", SAVE], ["Seguí", null]];
  return (
    <AbsoluteFill>
      {p.kind === "du" ? (
        <>
          <Photo p={p} filter="brightness(.4)" />
          <AbsoluteFill style={{ background: "rgba(11,47,79,.45)" }} />
        </>
      ) : null}
      <div style={{ position: "absolute", left: 80, right: 80, top: 360, bottom: 440, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 56, textAlign: "center" }}>
        <div style={popStyle(frame)}>
          <Img src={staticFile("logo.png")} style={{ width: 210, height: 210, borderRadius: "50%", background: "#fff", boxShadow: "0 18px 40px rgba(0,0,0,.4)" }} />
          <div style={{ fontWeight: 900, fontStretch: "72%", fontSize: 84, lineHeight: 0.98, marginTop: 26 }}>@lavozriojana.ok</div>
        </div>
        <div style={{ display: "flex", justifyContent: "center", gap: 60 }}>
          {acts.map(([label, icon], i) => <ActButton key={label} i={i} label={label} icon={icon} frame={frame} />)}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ── Subtítulos (cinco formas del prototipo) ──────────────────────────────
// Frases cortadas en la puntuación; las largas en trozos parejos de hasta `max` palabras.
const cuesOf = (words: WordT[], max: number): number[][] => {
  const phrases: number[][] = [];
  let cur: number[] = [];
  words.forEach((w, i) => {
    cur.push(i);
    if (/[.,;:?!]$/.test(w.t)) {
      phrases.push(cur);
      cur = [];
    }
  });
  if (cur.length) phrases.push(cur);
  const out: number[][] = [];
  phrases.forEach((ph) => {
    const n = Math.ceil(ph.length / max);
    const size = Math.ceil(ph.length / n);
    for (let i = 0; i < ph.length; i += size) out.push(ph.slice(i, i + size));
  });
  return out;
};

const Captions: React.FC<{ p: FormatReelProps; b: BeatT }> = ({ p, b }) => {
  const frame = useCurrentFrame();
  if (b.cap === "none" || b.cap === "title" || !b.words.length) return null;
  const abs = frame + b.from;
  const cw = currentWord(b.words, abs);
  if (cw < 0) return null;
  const cues = cuesOf(b.words, b.cap === "pop" ? 2 : 4);
  const ci = Math.max(0, cues.findIndex((q) => q.includes(cw)));
  const cue = cues[ci] ?? cues[cues.length - 1];
  const keys = b.keys.map(fold).filter(Boolean);
  const isKey = (t: string) => keys.some((k) => fold(t).startsWith(k));
  const cueStart = msToFrame(b.words[cue[0]].s);
  const fresh = riseStyle(abs - cueStart, 70, 0.3);
  const acc = p.accent;
  const base: React.CSSProperties = { position: "absolute", left: 70, right: 70, top: b.capY, display: "flex", flexWrap: "wrap", justifyContent: "center", gap: "4px 16px", textAlign: "center", zIndex: 22 };
  const shadow = "0 4px 24px rgba(0,0,0,.6),0 2px 4px rgba(0,0,0,.5)";
  const word = (k: number) => {
    const w = b.words[k];
    const v = k <= cw;
    const cur = k === cw;
    const key = isKey(w.t);
    const common: React.CSSProperties = { fontWeight: 900, fontStretch: "76%", lineHeight: 1.08, display: "inline-block" };
    if (b.cap === "pill") {
      return <span key={k} style={{ ...common, fontSize: 58, color: cur || (key && v) ? C.red : C.navy, opacity: v ? 1 : 0.3, textDecoration: key && v ? "underline" : undefined, textDecorationThickness: 5, textUnderlineOffset: 8 }}>{w.t}</span>;
    }
    if (b.cap === "marker") {
      const st: React.CSSProperties = { ...common, fontSize: 72, color: "#fff", textShadow: shadow, opacity: v ? 1 : 0, transform: v ? (cur ? "scale(1.08)" : "none") : "translateY(16px)" };
      if (key && v) Object.assign(st, { background: acc, color: C.ink, padding: "0 12px", borderRadius: 4, textShadow: "none", transform: "rotate(-1.5deg)" });
      return <span key={k} style={st}>{w.t}</span>;
    }
    if (b.cap === "callout") {
      return <span key={k} style={{ ...common, fontSize: 56, color: cur || (key && v) ? acc : "#fff", opacity: v ? 1 : 0 }}>{w.t}</span>;
    }
    if (b.cap === "pop") {
      const longest = Math.max(...cue.map((i) => b.words[i].t.length));
      const pf = Math.min(150, Math.floor(1700 / Math.max(1, longest)));
      const pw = cur ? prog(abs - msToFrame(w.s), 0.28) : 1;
      return <span key={k} style={{ ...common, fontSize: pf, lineHeight: 0.95, textTransform: "uppercase", color: key && v ? acc : "#fff", textShadow: shadow, opacity: v ? pw : 0, transform: cur ? `scale(${1.7 - 0.7 * pw})` : "none" }}>{w.t}</span>;
    }
    // chunk
    const st: React.CSSProperties = { ...common, fontSize: 66, color: key && v ? acc : "#fff", textShadow: shadow, opacity: v ? 1 : 0.28 };
    if (cur) Object.assign(st, { transform: "scale(1.12) rotate(-1.5deg)", color: C.ink, background: acc, padding: "0 12px", textShadow: "none", borderRadius: 6 });
    return <span key={k} style={st}>{w.t}</span>;
  };
  if (b.cap === "pill") {
    return (
      <div style={base}>
        <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: "2px 14px", background: "#fff", borderRadius: 30, padding: "18px 34px 20px", boxShadow: "0 14px 34px rgba(0,0,0,.35)", ...fresh }}>{cue.map(word)}</div>
      </div>
    );
  }
  if (b.cap === "callout") {
    return (
      <div style={base}>
        <div style={{ position: "relative", display: "flex", flexWrap: "wrap", justifyContent: "flex-start", gap: "2px 14px", background: "rgba(10,13,18,.9)", borderLeft: `12px solid ${acc}`, borderRadius: 10, padding: "22px 30px", ...fresh }}>
          <span style={{ position: "absolute", left: 70, top: -36, borderLeft: "18px solid transparent", borderRight: "18px solid transparent", borderBottom: "18px solid rgba(10,13,18,.9)", borderTop: "18px solid transparent" }} />
          {cue.map(word)}
        </div>
      </div>
    );
  }
  return (
    <div style={base}>
      {/* marker agranda la palabra dicha (scale 1.08): con 16 px se pegaba a la vecina ("Elsubmarino") */}
      <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: b.cap === "marker" ? "4px 30px" : "4px 16px", maxWidth: "100%", ...fresh }}>{cue.map(word)}</div>
    </div>
  );
};

// ── Escena ───────────────────────────────────────────────────────────────
const TRANSITION: Record<BeatT["layout"], Tr> = { hook: "flash", mapchips: "whip", stamps: "zoom", number: "up", check: "zoom", card: "up", who: "whip", efmap: "zoom", years: "up", calendar: "flash", outro: "zoom" };

const Scene: React.FC<{ p: FormatReelProps; b: BeatT }> = ({ p, b }) => {
  const frame = useCurrentFrame();
  const tr = sceneTransition(frame, TRANSITION[b.layout]);
  return (
    <AbsoluteFill style={tr}>
      {b.layout === "hook" ? (p.kind === "um" ? <HookUM p={p} b={b} /> : p.kind === "ef" ? <HookEF p={p} b={b} /> : <HookDU p={p} b={b} />) : null}
      {b.layout === "who" ? <WhoEF p={p} b={b} /> : null}
      {b.layout === "efmap" ? <MapEF p={p} b={b} /> : null}
      {b.layout === "years" ? <YearsEF p={p} b={b} /> : null}
      {b.layout === "calendar" ? <CalendarEF p={p} b={b} /> : null}
      {b.layout === "mapchips" ? <MapChips p={p} b={b} /> : null}
      {b.layout === "stamps" ? <Stamps p={p} b={b} /> : null}
      {b.layout === "number" ? <NumberBeat p={p} b={b} /> : null}
      {b.layout === "check" ? <CheckBeat /> : null}
      {b.layout === "card" ? <Card p={p} b={b} /> : null}
      {b.layout === "outro" ? <Outro p={p} /> : null}
      <Captions p={p} b={b} />
    </AbsoluteFill>
  );
};

const Sfx: React.FC<{ at: number; src: string; volume: number }> = ({ at, src, volume }) => (
  <Sequence from={Math.max(0, Math.round(at))} layout="none">
    <Audio src={staticFile(src)} volume={volume} />
  </Sequence>
);

export const FormatReel: React.FC<FormatReelProps> = (p) => {
  useV2FontsReady();
  return (
    <AbsoluteFill style={{ fontFamily: V2_FONT_SANS, background: C.ink, color: "#fff", overflow: "hidden" }}>
      {p.kind === "um" ? <VideoBackdrop p={p} /> : null}
      {p.kind === "ef" ? <ArchiveBackdrop p={p} /> : null}
      {p.beats.map((b, i) => (
        <Sequence key={i} from={b.from} durationInFrames={Math.max(1, b.to - b.from)}>
          <Scene p={p} b={b} />
        </Sequence>
      ))}
      {p.voiceFile ? <Audio src={staticFile(p.voiceFile)} /> : null}
      {p.music ? <Audio src={staticFile("newscast/bed.mp3")} volume={0.1} loop /> : null}
      <Sfx at={0} src="newscast/impact.mp3" volume={0.45} />
      {p.beats.slice(1).map((b, i) => <Sfx key={`w${i}`} at={b.from} src="newscast/whoosh.mp3" volume={0.32} />)}
      {p.beats.filter((b) => b.layout !== "hook").flatMap((b) => b.items).map((it, i) => <Sfx key={`t${i}`} at={it.at} src="newscast/tick.mp3" volume={0.3} />)}
    </AbsoluteFill>
  );
};

export const FORMAT_REEL_DEFAULTS: FormatReelProps = {
  kind: "du",
  badge: "DATO ÚTIL",
  accent: C.gold,
  media: { type: "photo", file: "logo.png", width: 1000, height: 1000 },
  credit: "",
  place: null,
  voiceFile: "",
  totalFrames: 120,
  heads: [],
  music: false,
  ef: null,
  beats: [
    { from: 0, to: 60, layout: "hook", card: "", cap: "title", capY: 0, words: [{ t: "¿Vas", s: 0, e: 300 }, { t: "a", s: 300, e: 400 }, { t: "estudiar?", s: 400, e: 900 }, { t: "Anotá", s: 1000, e: 1400 }, { t: "esto.", s: 1400, e: 1800 }], keys: [], ctaFrom: 3, items: [], value: "", unit: "", label: "", pill: "", detail: "", detailAt: 0, index: 0 },
    { from: 60, to: 120, layout: "outro", card: "", cap: "none", capY: 0, words: [], keys: [], ctaFrom: -1, items: [], value: "", unit: "", label: "", pill: "", detail: "", detailAt: 0, index: 0 },
  ],
};
