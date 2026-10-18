// Piezas comunes de los formatos sociales V2 (historias, carrusel de la
// mañana, resumen semanal). Mismo sistema que el Reel y la card de IG:
// Archivo condensada para titulares y rótulos, Source Serif itálica para
// bajadas, tinta/papel de marca y el sello oficial como firma.
import React from "react";
import { AbsoluteFill, Img, staticFile } from "remotion";
import { Grain } from "../../shared/Grain";
import { C, V2_FONT_SANS, V2_FONT_SERIF, rgba } from "../tokens";

export const STORY = {
  w: 1080,
  h: 1920,
  m: 72,
  // Instagram/Facebook dibujan barra de progreso y perfil arriba (~220 px) y
  // la caja de respuesta abajo (~260 px). Todo lo propio queda adentro.
  top: 250,
  bottom: 1650,
} as const;

export const caps = (size: number, color: string, weight = 800, tracking = 0.14): React.CSSProperties => ({
  fontFamily: `"${V2_FONT_SANS}"`,
  fontWeight: weight,
  fontStretch: "semi-condensed",
  fontSize: size,
  letterSpacing: `${tracking}em`,
  textTransform: "uppercase",
  lineHeight: 1,
  whiteSpace: "nowrap",
  color,
});

export const serif = (size: number, color: string, italic = true, weight = 500): React.CSSProperties => ({
  fontFamily: `"${V2_FONT_SERIF}"`,
  fontStyle: italic ? "italic" : "normal",
  fontWeight: weight,
  fontSize: size,
  lineHeight: 1.3,
  color,
});

export const display = (size: number, color: string, weight = 850, stretch = "semi-condensed"): React.CSSProperties => ({
  fontFamily: `"${V2_FONT_SANS}"`,
  fontWeight: weight,
  fontStretch: stretch,
  fontSize: size,
  lineHeight: 1.02,
  letterSpacing: "-0.01em",
  color,
});

// Sello + wordmark. `sub` agrega la línea chica debajo (sitio o edición).
export const Brand: React.FC<{ color?: string; seal?: number; size?: number; sub?: string; subColor?: string }> = ({
  color = C.white,
  seal = 96,
  size = 40,
  sub = "lavozriojana.com",
  subColor,
}) => (
  <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
    <Img src={staticFile("logo.png")} style={{ width: seal, height: seal, objectFit: "contain", filter: "drop-shadow(0 6px 14px rgba(0,0,0,0.35))" }} />
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: size * 0.26, ...display(size, color, 900, "condensed"), letterSpacing: "0.04em", lineHeight: 1 }}>
        <span>LA VOZ</span>
        <span>RIOJANA</span>
        <span style={{ width: size * 0.24, height: size * 0.24, backgroundColor: C.red, alignSelf: "center" }} />
      </div>
      {sub ? <div style={caps(Math.round(size * 0.48), subColor ?? rgba(color, 0.62), 700, 0.16)}>{sub}</div> : null}
    </div>
  </div>
);

// Rótulo rectangular (sección, tipo de historia). `live` agrega el punto
// de "en vivo" para último momento.
export const Tab: React.FC<{ label: string; fill: string; color?: string; size?: number; live?: boolean; detail?: string }> = ({
  label,
  fill,
  color = C.white,
  size = 24,
  live,
  detail,
}) => (
  <div style={{ display: "inline-flex", alignItems: "center", gap: size * 0.55, backgroundColor: fill, padding: `${size * 0.55}px ${size * 0.75}px`, ...caps(size, color) }}>
    {live ? <span style={{ width: size * 0.5, height: size * 0.5, borderRadius: "50%", backgroundColor: color }} /> : null}
    <span>{label}</span>
    {detail ? (
      <>
        <span style={{ width: 2, height: size * 0.9, backgroundColor: rgba(color, 0.5) }} />
        <span style={{ fontWeight: 600, letterSpacing: "0.1em" }}>{detail}</span>
      </>
    ) : null}
  </div>
);

// Encabezado de historia: marca a la izquierda, rótulo a la derecha y una
// regla fina debajo. Ocupa y=250..370.
export const StoryMasthead: React.FC<{ tab?: React.ReactNode; color?: string; rule?: string }> = ({ tab, color = C.white, rule }) => (
  <div style={{ position: "absolute", left: STORY.m, right: STORY.m, top: STORY.top, display: "flex", flexDirection: "column", gap: 26 }}>
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
      <Brand color={color} />
      {tab}
    </div>
    <div style={{ height: 2, backgroundColor: rule ?? rgba(color, 0.22) }} />
  </div>
);

// Llamado al pie (botón blanco). Siempre dentro de la zona segura.
export const StoryCta: React.FC<{ label: string; top?: number; dark?: boolean }> = ({ label, top = 1556, dark }) => (
  <div style={{ position: "absolute", left: 0, right: 0, top, display: "flex", justifyContent: "center" }}>
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 18,
        padding: "26px 44px",
        borderRadius: 999,
        backgroundColor: dark ? C.ink : C.white,
        boxShadow: "0 18px 40px rgba(0,0,0,0.35)",
        ...caps(27, dark ? C.white : C.ink, 800, 0.08),
      }}
    >
      <span>{label}</span>
      <span style={{ fontSize: 32, letterSpacing: 0 }}>→</span>
    </div>
  </div>
);

// Línea de fuente al pie de las piezas de servicio.
export const SourceLine: React.FC<{ left: string; right?: string; color?: string; top?: number }> = ({ left, right = "lavozriojana.com", color = C.white, top = 1590 }) => (
  <div style={{ position: "absolute", left: STORY.m, right: STORY.m, top, display: "flex", flexDirection: "column", gap: 22 }}>
    <div style={{ height: 2, backgroundColor: rgba(color, 0.22) }} />
    <div style={{ display: "flex", justifyContent: "space-between", ...caps(20, rgba(color, 0.7), 700, 0.12) }}>
      <span>{left}</span>
      <span>{right}</span>
    </div>
  </div>
);

// Fondo de foto desenfocada (o de color) con velo, para que cualquier
// imagen quede pareja detrás del contenido.
export const PhotoBackdrop: React.FC<{ src?: string; tint?: string; strength?: number }> = ({ src, tint = C.ink, strength = 0.62 }) => (
  <AbsoluteFill style={{ backgroundColor: tint }}>
    {src ? (
      <Img
        src={staticFile(src)}
        style={{ position: "absolute", inset: -120, width: STORY.w + 240, height: STORY.h + 240, objectFit: "cover", filter: "blur(46px) saturate(1.15)" }}
      />
    ) : null}
    <AbsoluteFill style={{ background: `linear-gradient(180deg, ${rgba(tint, strength + 0.18)} 0%, ${rgba(tint, strength)} 38%, ${rgba(tint, strength + 0.25)} 100%)` }} />
    <Grain opacity={0.05} />
  </AbsoluteFill>
);

// Fondo liso con degradé y textura de puntos muy sutil.
export const FieldBackdrop: React.FC<{ from: string; to: string; dots?: string }> = ({ from, to, dots }) => (
  <AbsoluteFill style={{ background: `linear-gradient(165deg, ${from} 0%, ${to} 78%)` }}>
    {dots ? (
      <AbsoluteFill
        style={{
          backgroundImage: `radial-gradient(${dots} 1.6px, transparent 1.8px)`,
          backgroundSize: "22px 22px",
          maskImage: "linear-gradient(200deg, rgba(0,0,0,0.9) 0%, rgba(0,0,0,0) 55%)",
          WebkitMaskImage: "linear-gradient(200deg, rgba(0,0,0,0.9) 0%, rgba(0,0,0,0) 55%)",
        }}
      />
    ) : null}
    <Grain opacity={0.045} />
  </AbsoluteFill>
);

export const Hairline: React.FC<{ color: string; style?: React.CSSProperties }> = ({ color, style }) => (
  <div style={{ height: 2, backgroundColor: color, ...style }} />
);
