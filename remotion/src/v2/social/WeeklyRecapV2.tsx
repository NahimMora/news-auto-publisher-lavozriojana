// WeeklyRecapV2 — Reel 1080×1920 de los domingos: "La semana en cinco".
//
// Estructura (30 fps):
//   apertura  2,4 s  sello, "La semana en cinco" y el rango de fechas.
//   5 notas   4,6 s c/u, del puesto 5 al 1: foto real de la nota a pantalla
//             completa con un acercamiento lento; arriba, la regleta de
//             avance de las cinco notas; abajo, un bloque de tinta con el
//             puesto, la sección y el titular; la cifra de alcance real.
//   cierre    2,4 s  sello y llamado a seguir la cuenta.
// Las transiciones son cortinas de tinta (no fundidos genéricos) y todo el
// texto queda dentro de la zona segura de los Reels (y 210–1540, x ≤ 940).
import React from "react";
import { AbsoluteFill, Img, Sequence, interpolate, staticFile, useCurrentFrame } from "remotion";
import { z } from "zod";
import { Grain } from "../../shared/Grain";
import { fit } from "../fit";
import { useV2FontsReady } from "../fonts";
import { EASE, clamp, mix, p } from "../motion";
import { C, V2_FONT_SERIF, rgba, sectionStyle } from "../tokens";
import { caps, display, serif } from "./chrome";

const Entry = z.object({
  titulo: z.string(),
  seccion: z.string(),
  assetFile: z.string().default(""),
  assetWidth: z.number().default(0),
  assetHeight: z.number().default(0),
  metric: z.string().default(""),
});

export const WeeklyRecapV2Schema = z.object({
  rangeLabel: z.string(),
  entries: z.array(Entry),
});

export type WeeklyRecapV2Props = z.infer<typeof WeeklyRecapV2Schema>;

export const RECAP = { intro: 72, entry: 138, outro: 72 } as const;
export const recapDuration = (n: number) => RECAP.intro + RECAP.entry * n + RECAP.outro;

const W = 1080;
const M = 64;
const SAFE_R = 940;

const Seal: React.FC<{ size: number }> = ({ size }) => (
  <Img src={staticFile("logo.png")} style={{ width: size, height: size, objectFit: "contain" }} />
);

// Cortina de tinta: entra desde abajo y libera la escena siguiente.
const Wipe: React.FC<{ at: number }> = ({ at }) => {
  const frame = useCurrentFrame();
  const inT = p(frame, at - 8, 8, EASE.snap);
  const outT = p(frame, at, 10, EASE.snap);
  const top = mix(inT, 100, 0) + mix(outT, 0, -100);
  if (frame < at - 8 || frame > at + 10) return null;
  return <AbsoluteFill style={{ backgroundColor: C.ink, transform: `translateY(${top}%)` }} />;
};

const Intro: React.FC<{ range: string }> = ({ range }) => {
  const frame = useCurrentFrame();
  const a = p(frame, 4, 16);
  const b = p(frame, 12, 18);
  const c = p(frame, 22, 18);
  return (
    <AbsoluteFill style={{ backgroundColor: C.ink }}>
      <Grain opacity={0.06} />
      <div style={{ position: "absolute", left: M, top: 470, opacity: a, transform: `translateY(${mix(a, 30, 0)}px)` }}>
        <Seal size={150} />
      </div>
      <div style={{ position: "absolute", left: M, right: W - SAFE_R, top: 690, display: "flex", flexDirection: "column", gap: 28 }}>
        <div style={{ ...caps(28, C.red, 800, 0.2), opacity: a }}>Resumen semanal</div>
        <div style={{ overflow: "hidden" }}>
          <div style={{ fontFamily: `"${V2_FONT_SERIF}"`, fontWeight: 700, fontSize: 150, lineHeight: 0.95, letterSpacing: "-0.03em", color: C.white, transform: `translateY(${mix(b, 105, 0)}%)` }}>
            La semana
          </div>
        </div>
        <div style={{ overflow: "hidden" }}>
          <div style={{ fontFamily: `"${V2_FONT_SERIF}"`, fontWeight: 700, fontStyle: "italic", fontSize: 150, lineHeight: 0.95, letterSpacing: "-0.03em", color: C.white, transform: `translateY(${mix(c, 105, 0)}%)` }}>
            en cinco
          </div>
        </div>
        <div style={{ height: 4, width: mix(c, 0, 420), backgroundColor: C.red, marginTop: 20 }} />
        <div style={{ ...caps(30, rgba(C.white, 0.8), 700, 0.14), opacity: c }}>{range}</div>
      </div>
      <div style={{ position: "absolute", left: M, top: 1400, ...serif(34, rgba(C.white, 0.7)), opacity: c }}>Las notas más vistas de La Voz Riojana</div>
    </AbsoluteFill>
  );
};

const Progress: React.FC<{ total: number; current: number; t: number }> = ({ total, current, t }) => (
  <div style={{ position: "absolute", left: M, right: W - SAFE_R, top: 236, display: "flex", gap: 10 }}>
    {Array.from({ length: total }).map((_, i) => (
      <div key={i} style={{ flex: 1, height: 6, backgroundColor: rgba(C.white, 0.25), overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${i < current ? 100 : i === current ? t * 100 : 0}%`, backgroundColor: C.white }} />
      </div>
    ))}
  </div>
);

const EntryScene: React.FC<{ entry: z.infer<typeof Entry>; rank: number; index: number; total: number }> = ({ entry, rank, index, total }) => {
  const frame = useCurrentFrame();
  const sec = sectionStyle(entry.seccion);
  const zoom = interpolate(frame, [0, RECAP.entry], [1.1, 1.0], { ...clamp, easing: EASE.camera });
  const block = p(frame, 8, 18);
  const num = p(frame, 2, 16);
  const line = p(frame, 16, 20);
  const aspect = entry.assetWidth > 0 && entry.assetHeight > 0 ? entry.assetWidth / entry.assetHeight : 1.5;
  // Foto horizontal: panel a todo el ancho (nunca se estira una foto chica
  // a pantalla completa); vertical: ocupa el panel más alto.
  const panelTop = 360;
  const panelH = Math.round(Math.max(560, Math.min(820, W / aspect)));
  const panelBottom = panelTop + panelH;
  const headline = fit({ text: entry.titulo, maxWidth: SAFE_R - M, maxHeight: 1540 - (panelBottom + 190), min: 50, max: 80, weight: 850, lh: 1.03, stretch: "semi-condensed", maxLines: 4 });
  return (
    <AbsoluteFill style={{ backgroundColor: C.ink }}>
      {entry.assetFile ? (
        <Img src={staticFile(entry.assetFile)} style={{ position: "absolute", inset: -100, width: W + 200, height: 1920 + 200, objectFit: "cover", filter: "blur(50px) brightness(0.45) saturate(1.1)" }} />
      ) : null}
      <AbsoluteFill style={{ background: `linear-gradient(180deg, ${rgba(C.ink, 0.55)} 0%, ${rgba(C.ink, 0.35)} 40%, ${rgba(C.ink, 0.9)} 70%)` }} />
      <Grain opacity={0.05} />
      <Progress total={total} current={index} t={p(frame, 0, RECAP.entry, (x) => x)} />
      <div style={{ position: "absolute", left: M, top: 274, display: "flex", alignItems: "center", gap: 16 }}>
        <Seal size={56} />
        <span style={caps(22, C.white, 800, 0.16)}>La semana en cinco</span>
      </div>
      <div style={{ position: "absolute", left: 0, top: panelTop, width: W, height: panelH, overflow: "hidden", boxShadow: "0 30px 80px rgba(0,0,0,0.5)" }}>
        {entry.assetFile ? (
          <Img src={staticFile(entry.assetFile)} style={{ width: "100%", height: "100%", objectFit: "cover", transform: `scale(${zoom})` }} />
        ) : null}
        <AbsoluteFill style={{ background: `linear-gradient(180deg, rgba(0,0,0,0) 55%, ${rgba(C.ink, 0.75)} 100%)` }} />
      </div>
      <div
        style={{
          position: "absolute",
          left: M - 8,
          top: panelBottom - 230,
          fontFamily: `"${V2_FONT_SERIF}"`,
          fontWeight: 700,
          fontSize: 280,
          lineHeight: 1,
          color: C.white,
          textShadow: "0 10px 40px rgba(0,0,0,0.55)",
          opacity: num,
          transform: `translateY(${mix(num, 40, 0)}px)`,
        }}
      >
        {rank}
      </div>
      <div
        style={{
          position: "absolute",
          left: M,
          right: W - SAFE_R,
          top: panelBottom + 70,
          display: "flex",
          flexDirection: "column",
          gap: 26,
          opacity: block,
          transform: `translateY(${mix(block, 40, 0)}px)`,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
          <span style={{ backgroundColor: sec.field, padding: "12px 18px", ...caps(24, C.white, 800, 0.16) }}>{sec.label}</span>
          {entry.metric ? <span style={caps(22, rgba(C.white, 0.8), 700, 0.1)}>{entry.metric}</span> : null}
        </div>
        <div style={{ height: 4, width: mix(line, 0, 220), backgroundColor: C.red }} />
        <div style={{ ...display(headline.fontSize, C.white, 850), lineHeight: `${headline.lineHeight}px` }}>
          {headline.lines.map((l, i) => (
            <div key={i}>{l}</div>
          ))}
        </div>
      </div>
    </AbsoluteFill>
  );
};

const Outro: React.FC = () => {
  const frame = useCurrentFrame();
  const a = p(frame, 4, 16);
  const b = p(frame, 14, 18);
  return (
    <AbsoluteFill style={{ backgroundColor: C.ink, alignItems: "center" }}>
      <Grain opacity={0.06} />
      <div style={{ position: "absolute", top: 520, display: "flex", flexDirection: "column", alignItems: "center", gap: 46, opacity: a, transform: `scale(${mix(a, 0.94, 1)})` }}>
        <Seal size={260} />
        <div style={{ display: "flex", alignItems: "baseline", gap: 18, ...display(76, C.white, 900, "condensed"), letterSpacing: "0.04em" }}>
          <span>LA VOZ</span>
          <span>RIOJANA</span>
        </div>
      </div>
      <div style={{ position: "absolute", top: 1080, display: "flex", flexDirection: "column", alignItems: "center", gap: 26, opacity: b }}>
        <div style={serif(42, rgba(C.white, 0.85))}>Todos los domingos, lo más visto de la semana</div>
        <div style={{ ...caps(30, C.white, 800, 0.12), backgroundColor: C.red, padding: "20px 34px" }}>Seguí @lavozriojana</div>
      </div>
    </AbsoluteFill>
  );
};

export const WeeklyRecapV2: React.FC<WeeklyRecapV2Props> = ({ rangeLabel, entries }) => {
  const ready = useV2FontsReady();
  if (!ready) return <AbsoluteFill style={{ backgroundColor: C.ink }} />;
  const list = entries.slice(0, 5);
  const n = list.length;
  return (
    <AbsoluteFill style={{ backgroundColor: C.ink }}>
      <Sequence durationInFrames={RECAP.intro}>
        <Intro range={rangeLabel} />
      </Sequence>
      {list.map((entry, i) => (
        <Sequence key={i} from={RECAP.intro + RECAP.entry * i} durationInFrames={RECAP.entry}>
          <EntryScene entry={entry} rank={n - i} index={i} total={n} />
        </Sequence>
      ))}
      <Sequence from={RECAP.intro + RECAP.entry * n} durationInFrames={RECAP.outro}>
        <Outro />
      </Sequence>
      {Array.from({ length: n + 1 }).map((_, i) => (
        <Wipe key={`w${i}`} at={RECAP.intro + RECAP.entry * i} />
      ))}
    </AbsoluteFill>
  );
};
