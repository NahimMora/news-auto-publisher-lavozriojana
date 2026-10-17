// Biblioteca de motion design V2: titulares cinéticos, revelados por
// palabra/línea, tipografía partida, máscaras, reglas editoriales, etiqueta
// de sección, cámara virtual, destacados y firma de marca. Cada pieza es
// una función pura del frame actual.
import React from "react";
import { Img, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { Fitted } from "./fit";
import { EASE, SPRING, clamp, mix, p, sp } from "./motion";
import { Token, splitByLines } from "./text";
import { C, Stretch, V2_FONT_SANS, V2_FONT_SERIF, rgba } from "./tokens";

export type RevealMode = "word" | "line" | "split" | "none";

export interface HeadlineProps {
  fitted: Fitted;
  tokens: Token[];
  color: string;
  accent: string;
  weight: number;
  stretch: Stretch;
  tracking: number;
  uppercase?: boolean;
  mode: RevealMode;
  start: number; // frame de inicio del revelado
  stagger: number; // frames entre líneas/palabras
  highlightAt?: number; // frame en que entra la caja de destaque
  exitAt?: number; // frame en que sale (máscara hacia arriba)
  exitDuration?: number;
  highlightText?: string;
  align?: "left" | "center";
}

// Agrupa tokens contiguos destacados en "runs" para que la caja de destaque
// sea continua dentro de una línea.
function runs(line: Token[]): { text: string; highlighted: boolean; index: number }[] {
  const out: { text: string; highlighted: boolean; index: number }[] = [];
  line.forEach((token, i) => {
    const last = out[out.length - 1];
    if (last && last.highlighted === token.highlighted) {
      last.text += ` ${token.value}`;
    } else {
      out.push({ text: token.value, highlighted: token.highlighted, index: i });
    }
  });
  return out;
}

// Titular con revelado por máscara. Los modos combinan timings distintos:
// "word" = golpe tipográfico palabra por palabra (hook urgente);
// "line" = línea por línea desde una máscara (editorial);
// "split" = cada línea se arma desde dos mitades que convergen.
export const Headline: React.FC<HeadlineProps> = ({
  fitted,
  tokens,
  color,
  accent,
  weight,
  stretch,
  tracking,
  uppercase,
  mode,
  start,
  stagger,
  highlightAt,
  exitAt,
  exitDuration = 12,
  highlightText = C.white,
  align = "left",
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const lines = splitByLines(fitted.lines, tokens);
  // Reserva vertical para acentos y descendentes dentro de la máscara.
  const padY = fitted.fontSize * 0.14;
  let wordCursor = 0;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: align === "center" ? "center" : "flex-start",
        fontFamily: `"${V2_FONT_SANS}"`,
        fontWeight: weight,
        fontStretch: stretch,
        fontSize: fitted.fontSize,
        lineHeight: `${fitted.lineHeight}px`,
        letterSpacing: `${tracking}em`,
        textTransform: uppercase ? "uppercase" : "none",
        color,
        fontKerning: "normal",
      }}
    >
      {lines.map((line, li) => {
        const lineStart = start + li * stagger;
        const exitP = exitAt === undefined ? 0 : p(frame, exitAt + li, exitDuration, EASE.in);
        let lineTransform = "";
        let lineOpacity = 1;
        if (mode === "line") {
          const t = p(frame, lineStart, 16, EASE.out);
          lineTransform = `translateY(${mix(t, 105, 0) + exitP * -110}%)`;
        } else if (mode === "split") {
          const t = p(frame, lineStart, 18, EASE.out);
          lineTransform = `translateY(${exitP * -110}%)`;
          lineOpacity = interpolate(t, [0, 0.15], [0, 1], clamp);
        } else {
          lineTransform = `translateY(${exitP * -110}%)`;
        }
        const lineRuns = runs(line);
        const splitT = mode === "split" ? p(frame, lineStart, 18, EASE.out) : 1;
        const content = (offsetY: number, clipTop: boolean | null) => (
          <div
            style={{
              whiteSpace: "nowrap",
              transform: lineTransform,
              opacity: lineOpacity,
              ...(clipTop === null
                ? {}
                : {
                    position: clipTop ? "relative" : "absolute",
                    inset: clipTop ? undefined : 0,
                    clipPath: clipTop ? "inset(0 0 50% 0)" : "inset(50% 0 0 0)",
                    translate: `${offsetY}px 0px`,
                  }),
            }}
          >
            {lineRuns.map((run, ri) => {
              const words = run.text.split(" ");
              const runStartWord = wordCursor;
              wordCursor += words.length;
              const boxT =
                run.highlighted && highlightAt !== undefined ? p(frame, highlightAt + li * 3, 14, EASE.snap) : run.highlighted ? 1 : 0;
              const spanStyle: React.CSSProperties = run.highlighted
                ? {
                    backgroundImage: `linear-gradient(${accent}, ${accent})`,
                    backgroundRepeat: "no-repeat",
                    backgroundSize: `${boxT * 100}% 100%`,
                    backgroundPosition: "left center",
                    color: boxT > 0.5 ? highlightText : color,
                    padding: "0 0.1em",
                    margin: "0 -0.02em",
                    boxDecorationBreak: "clone",
                  }
                : {};
              return (
                <React.Fragment key={`${li}-${ri}`}>
                  {ri > 0 ? " " : ""}
                  <span style={spanStyle}>
                    {mode === "word"
                      ? words.map((word, wi) => {
                          const wStart = start + (runStartWord + wi) * stagger;
                          const s = sp(frame, wStart, fps, SPRING.punch, 14);
                          return (
                            <React.Fragment key={wi}>
                              {wi > 0 ? " " : ""}
                              <span
                                style={{
                                  display: "inline-block",
                                  opacity: interpolate(s, [0, 0.2], [0, 1], clamp),
                                  transform: `translateY(${mix(s, 0.5, 0)}em) scale(${mix(s, 1.18, 1)})`,
                                  transformOrigin: "50% 100%",
                                }}
                              >
                                {word}
                              </span>
                            </React.Fragment>
                          );
                        })
                      : run.text}
                  </span>
                </React.Fragment>
              );
            })}
          </div>
        );
        return (
          <div
            key={`line-${li}-${line.map((t) => t.value).join("_")}`}
            style={{
              overflow: "hidden",
              padding: `${padY}px 0.12em`,
              margin: `${-padY}px -0.12em`,
              position: "relative",
            }}
          >
            {mode === "split" ? (
              <div style={{ position: "relative" }}>
                {content(mix(splitT, -80, 0), true)}
                {content(mix(splitT, 80, 0), false)}
              </div>
            ) : (
              content(0, null)
            )}
          </div>
        );
      })}
    </div>
  );
};

// Regla editorial animada: se dibuja desde un extremo y puede retirarse.
export const Rule: React.FC<{
  progress: number;
  color: string;
  thickness?: number;
  length: number | string;
  vertical?: boolean;
  origin?: "start" | "end" | "center";
  style?: React.CSSProperties;
}> = ({ progress, color, thickness = 4, length, vertical, origin = "start", style }) => {
  const o = origin === "start" ? "0%" : origin === "end" ? "100%" : "50%";
  return (
    <div
      style={{
        width: vertical ? thickness : length,
        height: vertical ? length : thickness,
        backgroundColor: color,
        transform: vertical ? `scaleY(${progress})` : `scaleX(${progress})`,
        transformOrigin: vertical ? `50% ${o}` : `${o} 50%`,
        ...style,
      }}
    />
  );
};

// Etiqueta de sección: marcador cuadrado de acento + texto con tracking.
// Se revela con máscara de izquierda a derecha.
export const SectionLabel: React.FC<{
  label: string;
  detail?: string;
  accent: string;
  color: string;
  size?: number;
  progress: number;
  boxed?: boolean;
}> = ({ label, detail, accent, color, size = 24, progress, boxed }) => (
  <div
    style={{
      display: "inline-flex",
      alignItems: "center",
      gap: size * 0.55,
      clipPath: `inset(-20% ${(1 - progress) * 100}% -20% 0)`,
      fontFamily: `"${V2_FONT_SANS}"`,
      fontWeight: 800,
      fontStretch: "semi-condensed",
      fontSize: size,
      letterSpacing: "0.16em",
      textTransform: "uppercase",
      color,
      lineHeight: 1,
      whiteSpace: "nowrap",
      ...(boxed ? { backgroundColor: accent, padding: `${size * 0.42}px ${size * 0.6}px`, color: C.white } : {}),
    }}
  >
    {boxed ? null : <div style={{ width: size * 0.62, height: size * 0.62, backgroundColor: accent, flexShrink: 0 }} />}
    <span>{label}</span>
    {detail ? (
      <>
        <span style={{ width: 2, height: size * 0.9, backgroundColor: boxed ? rgba(C.white, 0.6) : rgba(color, 0.35) }} />
        <span style={{ fontWeight: 600, letterSpacing: "0.1em" }}>{detail}</span>
      </>
    ) : null}
  </div>
);

// Firma tipográfica de marca. El sello (logo oficial) es opcional: en
// tamaños chicos el wordmark se lee mejor que el escudo detallado.
export const Wordmark: React.FC<{
  size?: number;
  color?: string;
  seal?: boolean;
  sealSize?: number;
  accent?: string;
}> = ({ size = 28, color = C.white, seal = true, sealSize, accent = C.red }) => (
  <div style={{ display: "inline-flex", alignItems: "center", gap: size * 0.5 }}>
    {seal ? (
      <Img src={staticFile("logo.png")} style={{ width: sealSize ?? size * 2.1, height: sealSize ?? size * 2.1, objectFit: "contain" }} />
    ) : null}
    <div
      style={{
        fontFamily: `"${V2_FONT_SANS}"`,
        fontWeight: 900,
        fontStretch: "condensed",
        fontSize: size,
        letterSpacing: "0.04em",
        color,
        lineHeight: 1,
        whiteSpace: "nowrap",
        display: "flex",
        alignItems: "baseline",
        gap: size * 0.28,
      }}
    >
      <span>LA VOZ</span>
      <span>RIOJANA</span>
      <span style={{ width: size * 0.26, height: size * 0.26, backgroundColor: accent, alignSelf: "center" }} />
    </div>
  </div>
);

// Bajada en serif itálica — contraste editorial con el titular sans.
export const Deck: React.FC<{ text: string; size?: number; color: string; maxWidth: number; progress?: number }> = ({
  text,
  size = 32,
  color,
  maxWidth,
  progress = 1,
}) => (
  <div
    style={{
      fontFamily: `"${V2_FONT_SERIF}"`,
      fontStyle: "italic",
      fontWeight: 500,
      fontSize: size,
      lineHeight: 1.28,
      color,
      maxWidth,
      opacity: interpolate(progress, [0, 1], [0, 1], clamp),
      transform: `translateY(${mix(progress, 18, 0)}px)`,
    }}
  >
    {text}
  </div>
);

// Revelado por máscara rectangular desde el centro (apertura de obturador)
// o desde un lado.
export function maskInset(progress: number, from: "center-h" | "center-v" | "left" | "bottom" | "top"): string {
  const r = (1 - progress) * 100;
  switch (from) {
    case "center-h":
      return `inset(${r / 2}% 0 ${r / 2}% 0)`;
    case "center-v":
      return `inset(0 ${r / 2}% 0 ${r / 2}%)`;
    case "left":
      return `inset(0 ${r}% 0 0)`;
    case "bottom":
      return `inset(${r}% 0 0 0)`;
    case "top":
      return `inset(0 0 ${r}% 0)`;
    default:
      return "none";
  }
}

// Cámara virtual: escala y desplazamiento lentos que se detienen. Se usa
// sólo en el hook; en el estado de video protagonista la cámara queda fija.
export function camera(frame: number, start: number, duration: number, fromScale: number, drift = 0): React.CSSProperties {
  const t = p(frame, start, duration, EASE.camera);
  return {
    transform: `translateY(${mix(t, drift, 0)}px) scale(${mix(t, fromScale, 1)})`,
  };
}
