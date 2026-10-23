// Placa de servicio (v2), compartida por la historia (StoryV2, kinds
// "payments" y "quake") y el post 1080×1350 (ServiceCardV2):
//
//   · zonas libres de 250 px arriba y 350 px abajo (ahí sólo va el fondo);
//   · etiqueta de estado con color fijo (HOY, MAÑANA, ACTUALIZADO, CANCELADO);
//   · un solo dato protagonista (`hero`) con su rótulo (`heroLabel`);
//   · hasta tres renglones de apoyo (`lines`), en orden de importancia;
//   · pie "Fuente · actualizado HH:MM" (`footer`).
//
// Python arma todos los textos con lo que publica la fuente y controla el
// máximo de 25 palabras; la composición sólo los dispone.
import React from "react";
import { AbsoluteFill } from "remotion";
import { z } from "zod";
import { fit } from "../fit";
import { C, V2_FONT_SERIF, rgba } from "../tokens";
import { Brand, FieldBackdrop, caps, display, serif } from "./chrome";

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
  actualizado: { label: "Actualizado", fill: "#F2A900", color: C.ink },
  cancelado: { label: "Cancelado", fill: "#5B5F66", color: C.white },
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
  const ink = tone === "paper" ? C.paperInk : C.white;
  const mute = tone === "paper" ? C.paperMute : rgba(C.white, 0.72);
  const accent = tone === "paper" ? C.red : "#F2A900";
  const tag = STATUS[status];
  const top = PLATE_SAFE.top;
  const bottom = height - PLATE_SAFE.bottom;
  const inner = width - margin * 2;
  const zone = bottom - top;
  // La historia tiene más alto útil que el post: todo crece hasta un 30 %.
  const k = Math.min(1.3, Math.max(1, zone / 1000));
  // Alto fijo: marca 64, estado 30+62, rótulo del dato 20+30, margen de
  // renglones 30 y pie 28+40. Los renglones reservan ~58 px cada uno y el
  // dato protagonista se queda con el resto.
  const fixed = (64 + 92 + 50 + 30 + 68) * k;
  const rows = lines.slice(0, 3);
  const rowsH = (rows.length * 58 + Math.max(0, rows.length - 1) * 18) * k;
  const numeric = /^[\d.,]+$/.test(hero);
  const heroFit = fit({
    text: hero,
    maxWidth: inner,
    maxHeight: Math.max(80, zone - fixed - rowsH - 28 * k),
    min: 64,
    max: (numeric ? 340 : 150) * k,
    weight: 900,
    lh: numeric ? 1.0 : 0.98,
    stretch: "condensed",
    maxLines: numeric ? 1 : 3,
  });
  const lineBudget = zone - fixed - heroFit.height - 28 * k;
  const lineFits = rows.map((text, i) =>
    fit({
      text,
      maxWidth: inner,
      maxHeight: Math.max(48, lineBudget / Math.max(1, rows.length) - 18 * k),
      min: 28,
      max: (i === 0 ? 50 : 40) * k,
      weight: i === 0 ? 800 : 500,
      lh: 1.18,
      italic: i !== 0,
      family: i === 0 ? undefined : V2_FONT_SERIF,
      stretch: "semi-condensed",
      maxLines: 2,
    }),
  );
  return (
    <AbsoluteFill>
      {tone === "paper" ? (
        <AbsoluteFill style={{ backgroundColor: C.paper }} />
      ) : (
        <FieldBackdrop from="#3a2400" to={C.ink} dots={rgba("#F2A900", 0.1)} />
      )}
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
        <Brand
          color={ink}
          seal={Math.round(64 * k)}
          size={Math.round(28 * k)}
          sub=""
        />
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 24 * k,
            marginTop: 30 * k,
          }}
        >
          <span
            style={{
              ...caps(30 * k, tag.color, 900, 0.14),
              backgroundColor: tag.fill,
              padding: `${16 * k}px ${22 * k}px`,
            }}
          >
            {tag.label}
          </span>
          {kicker ? (
            <span style={caps(28 * k, accent, 900, 0.12)}>{kicker}</span>
          ) : null}
        </div>
        <div
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            justifyContent: k > 1 ? "center" : "flex-start",
          }}
        >
          <div
            style={{
              marginTop: 28 * k,
              ...display(heroFit.fontSize, ink, 900, "condensed"),
              lineHeight: `${heroFit.lineHeight}px`,
            }}
          >
            {heroFit.lines.map((l, i) => (
              <div key={i}>{l}</div>
            ))}
          </div>
          {heroLabel ? (
            <div
              style={{
                ...caps(30 * k, mute, 800, 0.14),
                marginTop: 20 * k,
              }}
            >
              {heroLabel}
            </div>
          ) : null}
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 18 * k,
              marginTop: 30 * k,
              borderLeft: `6px solid ${accent}`,
              paddingLeft: 26 * k,
            }}
          >
            {lineFits.map((f, i) => (
              <div
                key={i}
                style={{
                  ...(i === 0
                    ? display(f.fontSize, ink, 800)
                    : serif(f.fontSize, mute)),
                  lineHeight: `${f.lineHeight}px`,
                }}
              >
                {f.lines.map((l, j) => (
                  <div key={j}>{l}</div>
                ))}
              </div>
            ))}
          </div>
        </div>
        <div
          style={{
            marginTop: 28 * k,
            display: "flex",
            flexDirection: "column",
            gap: 18 * k,
          }}
        >
          <div style={{ height: 2, backgroundColor: rgba(ink, 0.2) }} />
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              ...caps(20 * k, rgba(ink, 0.7), 700, 0.12),
            }}
          >
            <span>{footer}</span>
            <span>lavozriojana.com</span>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
