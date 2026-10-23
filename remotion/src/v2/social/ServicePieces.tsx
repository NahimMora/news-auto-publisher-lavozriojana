// Placa de servicio (v2), compartida por la historia (StoryV2, kinds
// "payments" y "quake") y el post 1080×1350 (ServiceCardV2):
//
//   · zonas libres de 250 px arriba y 350 px abajo (ahí sólo va el fondo);
//   · etiqueta de estado con color fijo (HOY, MAÑANA, ACTUALIZADO, CANCELADO);
//   · un solo dato protagonista (`hero`) con su rótulo (`heroLabel`);
//   · hasta tres renglones de apoyo (`lines`), en orden de importancia;
//   · pie "Fuente · actualizado HH:MM" (`footer`).
//
// Dos tonos: "paper" (pagos: gris frío claro, tinta azul noche, hoja de
// calendario con la fecha) e "ink" (sismo: azul noche con cuadrícula de
// sismógrafo, traza sísmica y barra de magnitud junto al número). La traza y la barra
// son gráficas: no suman palabras. Python arma todos los textos con lo que
// publica la fuente y controla el máximo de 25 palabras.
import React from "react";
import { AbsoluteFill } from "remotion";
import { z } from "zod";
import { EmphText, markData, markPhrase } from "../emphasis";
import { fit } from "../fit";
import { C, rgba } from "../tokens";
import { Brand, caps, display } from "./chrome";

export const PLATE_SAFE = { top: 250, bottom: 350 } as const;

export const PlateStatus = z.enum([
  "hoy",
  "manana",
  "actualizado",
  "cancelado",
]);

export const ServicePiecesSchema = {
  status: PlateStatus.default("hoy"),
  kicker: z.string().default(""),
  hero: z.string().default(""),
  heroLabel: z.string().default(""),
  lines: z.array(z.string()).default([]),
  footer: z.string().default(""),
};

// Colores fijos por estado: el lector los reconoce sin leer.
const STATUS: Record<
  z.infer<typeof PlateStatus>,
  { label: string; fill: string; color: string }
> = {
  hoy: { label: "Hoy", fill: C.red, color: C.white },
  manana: { label: "Mañana", fill: C.blue, color: C.white },
  actualizado: { label: "Actualizado", fill: "#E3A008", color: "#0D1B2A" },
  cancelado: { label: "Cancelado", fill: "#4B5563", color: C.white },
};

// Tonos compartidos con las historias de clima y dólar y el carrusel de la
// mañana: mismo sistema para todas las piezas de servicio.
export const THEMES = {
  paper: {
    bg: "#F3F5F8",
    ink: "#0D1B2A",
    mute: "#56657A",
    rule: rgba("#0D1B2A", 0.13),
    accent: C.blue,
  },
  ink: {
    bg: "#07121E",
    ink: C.white,
    mute: "#9FB2C6",
    rule: rgba(C.white, 0.14),
    accent: "#6EA8DC",
  },
} as const;

export type Theme = (typeof THEMES)[keyof typeof THEMES];

// Fondo: "ink" azul noche con luz arriba a la izquierda y cuadrícula de
// 54 px; "paper" blanco que baja a gris frío.
export const PlateBackdrop: React.FC<{ tone: "paper" | "ink" }> = ({
  tone,
}) => {
  const theme = THEMES[tone];
  return (
    <AbsoluteFill style={{ backgroundColor: theme.bg }}>
      {tone === "ink" ? (
        <>
          <AbsoluteFill
            style={{
              background: `radial-gradient(120% 80% at 0% 0%, ${rgba("#1B4A75", 0.55)} 0%, ${rgba(theme.bg, 0)} 60%)`,
            }}
          />
          <AbsoluteFill
            style={{
              backgroundImage: `linear-gradient(${rgba(C.white, 0.035)} 2px, transparent 2px), linear-gradient(90deg, ${rgba(C.white, 0.035)} 2px, transparent 2px)`,
              backgroundSize: "54px 54px",
            }}
          />
        </>
      ) : (
        <AbsoluteFill
          style={{
            background: `linear-gradient(180deg, ${C.white} 0%, ${theme.bg} 70%)`,
          }}
        />
      )}
    </AbsoluteFill>
  );
};

// Rótulo doble: bloque de color (estado o tipo de pieza) + detalle con borde.
export const TagPair: React.FC<{
  label: string;
  fill: string;
  color: string;
  detail?: string;
  theme: Theme;
  k?: number;
}> = ({ label, fill, color, detail, theme, k = 1 }) => (
  <div style={{ display: "flex", alignItems: "stretch" }}>
    <span
      style={{
        ...caps(26 * k, color, 900, 0.16),
        backgroundColor: fill,
        padding: `${14 * k}px ${20 * k}px`,
      }}
    >
      {label}
    </span>
    {detail ? (
      <span
        style={{
          ...caps(26 * k, theme.ink, 800, 0.14),
          padding: `${14 * k}px ${20 * k}px`,
          border: `2px solid ${theme.rule}`,
          borderLeft: "none",
          display: "flex",
          alignItems: "center",
        }}
      >
        {detail}
      </span>
    ) : null}
  </div>
);

const MONTHS = [
  "Ene",
  "Feb",
  "Mar",
  "Abr",
  "May",
  "Jun",
  "Jul",
  "Ago",
  "Sep",
  "Oct",
  "Nov",
  "Dic",
];

// Pseudoaleatorio con semilla: la misma placa siempre dibuja la misma traza.
function seeded(seed: string): () => number {
  let h = 2166136261;
  for (const ch of seed) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
  return () => {
    h = Math.imul(h ^ (h >>> 15), h | 1);
    h ^= h + Math.imul(h ^ (h >>> 7), h | 61);
    return ((h ^ (h >>> 14)) >>> 0) / 4294967296;
  };
}

// Traza de sismógrafo: ruido de fondo, arribo brusco y decaimiento. La
// amplitud crece con la magnitud.
const Seismogram: React.FC<{
  width: number;
  height: number;
  magnitude: number;
  seed: string;
  color: string;
}> = ({ width, height, magnitude, seed, color }) => {
  const rand = seeded(seed);
  const n = 220;
  const mid = height / 2;
  const scale = Math.min(1, Math.max(0.35, magnitude / 7));
  const points: string[] = [];
  for (let i = 0; i <= n; i++) {
    const x = (i / n) * width;
    const t = i / n;
    const env =
      t < 0.34
        ? 0.05
        : t < 0.4
          ? 0.05 + ((t - 0.34) / 0.06) * 0.95
          : Math.exp(-(t - 0.4) * 4.2);
    const sign = i % 2 === 0 ? 1 : -1;
    const y =
      mid + sign * env * scale * (0.35 + rand() * 0.65) * (height / 2 - 4);
    points.push(`${x.toFixed(1)},${y.toFixed(1)}`);
  }
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      style={{ display: "block" }}
    >
      <line
        x1={0}
        y1={mid}
        x2={width}
        y2={mid}
        stroke={rgba(color, 0.25)}
        strokeWidth={1.5}
      />
      <polyline
        points={points.join(" ")}
        fill="none"
        stroke={color}
        strokeWidth={2.6}
        strokeLinejoin="round"
      />
    </svg>
  );
};

// Barra de magnitud de 1 a 9: segmentos llenos hasta el valor publicado.
const MagnitudeBar: React.FC<{
  value: number;
  width: number;
  k: number;
  theme: Theme;
}> = ({ value, width, k, theme }) => {
  const segments = 9;
  const gap = 6 * k;
  const w = (width - gap * (segments - 1)) / segments;
  return (
    <div style={{ display: "flex", gap, alignItems: "flex-end" }}>
      {Array.from({ length: segments }, (_, i) => {
        const fill = Math.min(1, Math.max(0, value - i));
        return (
          <div
            key={i}
            style={{
              width: w,
              height: (14 + i * 3.2) * k,
              backgroundColor: theme.rule,
              position: "relative",
            }}
          >
            <div
              style={{
                position: "absolute",
                left: 0,
                top: 0,
                bottom: 0,
                width: `${fill * 100}%`,
                backgroundColor: theme.accent,
              }}
            />
          </div>
        );
      })}
    </div>
  );
};

// Hoja de calendario con la fecha ("Jueves 15/10"). Sin fecha reconocible,
// muestra el rótulo tal cual.
const CalendarLeaf: React.FC<{ label: string; k: number; theme: Theme }> = ({
  label,
  k,
  theme,
}) => {
  const m = /^(\S+)\s+(\d{1,2})\/(\d{1,2})$/.exec(label.trim());
  const w = 196 * k;
  return (
    <div
      style={{
        width: w,
        flexShrink: 0,
        backgroundColor: C.white,
        boxShadow: `0 ${10 * k}px ${28 * k}px ${rgba(theme.ink, 0.14)}`,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
      }}
    >
      <div
        style={{
          alignSelf: "stretch",
          backgroundColor: C.red,
          padding: `${12 * k}px 0`,
          textAlign: "center",
          ...caps(24 * k, C.white, 900, 0.2),
        }}
      >
        {m ? MONTHS[Number(m[3]) - 1] : ""}
      </div>
      <div
        style={{
          ...display((m ? 104 : 34) * k, theme.ink, 900, "condensed"),
          lineHeight: 1,
          padding: `${14 * k}px 0 ${6 * k}px`,
        }}
      >
        {m ? m[2] : label}
      </div>
      {m ? (
        <div
          style={{
            ...caps(20 * k, theme.mute, 800, 0.16),
            paddingBottom: 18 * k,
          }}
        >
          {m[1]}
        </div>
      ) : null}
    </div>
  );
};

interface PlateProps {
  status: z.infer<typeof PlateStatus>;
  kicker: string;
  hero: string;
  heroLabel: string;
  lines: string[];
  footer: string;
  tone: "paper" | "ink";
  width: number;
  height: number;
  margin: number;
}

export const ServicePlate: React.FC<PlateProps> = ({
  status,
  kicker,
  hero,
  heroLabel,
  lines,
  footer,
  tone,
  width,
  height,
  margin,
}) => {
  const theme = THEMES[tone];
  const tag = STATUS[status];
  const top = PLATE_SAFE.top;
  const zone = height - PLATE_SAFE.bottom - top;
  const inner = width - margin * 2;
  // La historia tiene más alto útil que el post: todo crece hasta un 30 %.
  const k = Math.min(1.3, Math.max(1, zone / 1000));
  const numeric = /^[\d.,]+$/.test(hero);
  const rows = lines.slice(0, 3);

  // Alto fijo: marca + estado (144) y pie (66); 28 de aire entre bloques.
  const body = zone - (144 + 66 + 56) * k;
  const rowFits = (w: number, budget: number) =>
    rows.map((text, i) =>
      fit({
        text,
        maxWidth: w,
        maxHeight: Math.max(40, budget / Math.max(1, rows.length) - 28 * k),
        min: 26,
        max: (i === 0 ? 44 : 34) * k,
        // Se mide con el peso de los datos resaltados (ver ../emphasis.tsx).
        weight: 800,
        lh: 1.15,
        stretch: "semi-condensed",
        maxLines: 2,
      }),
    );

  const Rows: React.FC<{ fits: ReturnType<typeof rowFits> }> = ({ fits }) => (
    <div
      style={{ display: "flex", flexDirection: "column", minWidth: 0, flex: 1 }}
    >
      {fits.map((f, i) => (
        <div
          key={i}
          style={{
            borderTop: `2px solid ${i === 0 ? theme.accent : theme.rule}`,
            padding: `${14 * k}px 0`,
          }}
        >
          <EmphText
            lines={f.lines}
            tokens={i === 0 ? markPhrase(rows[i], []) : markData(rows[i])}
            lineHeight={f.lineHeight}
            base={display(
              f.fontSize,
              i === 0 ? theme.ink : theme.mute,
              i === 0 ? 800 : 500,
            )}
            strong={{ color: theme.ink, fontWeight: 800 }}
          />
        </div>
      ))}
    </div>
  );

  let content: React.ReactNode;
  if (numeric) {
    const rowsH = rows.length * 66 * k;
    const heroFit = fit({
      text: hero,
      maxWidth: inner * 0.6,
      maxHeight: Math.max(120, body - rowsH - 28 * k),
      min: 90,
      max: 330 * k,
      weight: 900,
      lh: 1.0,
      stretch: "condensed",
      maxLines: 1,
    });
    const magnitude = Number(hero.replace(",", "."));
    const side = inner - heroFit.widest - 40 * k;
    content = (
      <>
        <div
          style={{
            display: "flex",
            alignItems: "flex-end",
            gap: 40 * k,
          }}
        >
          <div
            style={{
              ...display(heroFit.fontSize, theme.ink, 900, "condensed"),
              lineHeight: `${heroFit.lineHeight}px`,
            }}
          >
            {heroFit.lines[0]}
          </div>
          <div
            style={{
              width: side,
              display: "flex",
              flexDirection: "column",
              gap: 16 * k,
              paddingBottom: heroFit.fontSize * 0.14,
            }}
          >
            <div style={{ opacity: 0.85, marginBottom: 8 * k }}>
              <Seismogram
                width={side}
                height={heroFit.height * 0.4}
                magnitude={magnitude}
                seed={`${hero}${rows[0] ?? ""}`}
                color={theme.accent}
              />
            </div>
            <span style={caps(26 * k, theme.mute, 800, 0.16)}>{heroLabel}</span>
            <MagnitudeBar value={magnitude} width={side} k={k} theme={theme} />
          </div>
        </div>
        <div style={{ marginTop: 28 * k, display: "flex" }}>
          <Rows fits={rowFits(inner, body - heroFit.height - 28 * k)} />
        </div>
      </>
    );
  } else {
    const rowH = 196 * k;
    const heroFit = fit({
      text: hero,
      maxWidth: inner,
      maxHeight: Math.max(100, body - rowH - 28 * k),
      min: 64,
      max: 140 * k,
      weight: 900,
      lh: 0.96,
      stretch: "condensed",
      maxLines: 2,
    });
    const textW = inner - 196 * k - 36 * k;
    content = (
      <>
        <div
          style={{
            ...display(heroFit.fontSize, theme.ink, 900, "condensed"),
            lineHeight: `${heroFit.lineHeight}px`,
          }}
        >
          {heroFit.lines.map((l, i) => (
            <div key={i}>{l}</div>
          ))}
        </div>
        <div
          style={{
            marginTop: 28 * k,
            display: "flex",
            gap: 36 * k,
            alignItems: "flex-start",
          }}
        >
          <CalendarLeaf label={heroLabel} k={k} theme={theme} />
          <Rows fits={rowFits(textW, rowH)} />
        </div>
      </>
    );
  }

  return (
    <AbsoluteFill style={{ backgroundColor: theme.bg }}>
      <PlateBackdrop tone={tone} />
      <div
        style={{
          position: "absolute",
          left: margin,
          width: inner,
          top,
          height: zone,
          display: "flex",
          flexDirection: "column",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 24 * k,
          }}
        >
          <Brand
            color={theme.ink}
            seal={Math.round(60 * k)}
            size={Math.round(26 * k)}
            sub=""
          />
        </div>
        <div style={{ marginTop: 28 * k }}>
          <TagPair
            label={tag.label}
            fill={tag.fill}
            color={tag.color}
            detail={kicker}
            theme={theme}
            k={k}
          />
        </div>
        <div
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            justifyContent: k > 1 ? "center" : "flex-start",
            paddingTop: 28 * k,
          }}
        >
          {content}
        </div>
        <div
          style={{
            marginTop: 28 * k,
            display: "flex",
            flexDirection: "column",
            gap: 16 * k,
          }}
        >
          <div style={{ height: 2, backgroundColor: theme.rule }} />
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              gap: 24,
              ...caps(19 * Math.min(k, 1.1), theme.mute, 700, 0.12),
            }}
          >
            <span
              style={{ whiteSpace: "normal", minWidth: 0, lineHeight: 1.3 }}
            >
              {footer}
            </span>
            <span style={{ flexShrink: 0 }}>lavozriojana.com</span>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
