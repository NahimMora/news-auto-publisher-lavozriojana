// StoryV2 — historias 1080×1920 para Instagram y Facebook (la misma imagen
// en las dos redes). Una composición, varias piezas por `kind`:
//
//   post      la publicación de Instagram tal cual salió, sobre su propia
//             imagen desenfocada, con marca arriba y llamado abajo.
//   breaking  igual que post, con el rótulo "Último momento".
//   reel      la portada del Reel a pantalla completa + llamado.
//   update    seguimiento: dato anterior tachado y dato nuevo de la fuente.
//   weather   clima del SMN: actual, pronóstico de 5 días y alertas (mismo
//             sistema que las placas de servicio).
//   alert     alerta meteorológica del SMN para La Rioja.
//   dollar    cotizaciones del día (ídem).
//   notice    aviso de servicio (corte de luz/agua, rutas) tomado de una nota.
//   holidays  próximos feriados.
//   payments  cronograma de pagos de Hacienda (ver ServicePieces.tsx).
//   quake     sismo con epicentro en La Rioja (INPRES).
//
// Todos los textos llegan armados desde Python (fuentes verificables); la
// composición sólo los dispone. Nada se inventa ni se completa acá.
import React from "react";
import { AbsoluteFill, Img, staticFile } from "remotion";
import { z } from "zod";
import { fit } from "../fit";
import { useV2FontsReady } from "../fonts";
import { C, V2_FONT_SERIF, rgba } from "../tokens";
import { Brand, FieldBackdrop, PhotoBackdrop, STORY, SourceLine, StoryCta, StoryMasthead, Tab, caps, display, serif } from "./chrome";
import { PlateBackdrop, ServicePiecesSchema, ServicePlate, TagPair, THEMES } from "./ServicePieces";

const WeatherDay = z.object({ label: z.string(), max: z.number(), min: z.number(), rain: z.number().default(0) });
const DollarRow = z.object({ name: z.string(), buy: z.string().default(""), sell: z.string(), delta: z.number().default(0) });
const Holiday = z.object({ day: z.string(), month: z.string(), weekday: z.string(), name: z.string(), kind: z.string().default("") });

export const StoryV2Schema = z.object({
  kind: z.enum(["post", "breaking", "reel", "update", "weather", "alert", "dollar", "notice", "holidays", "payments", "quake"]),
  assetFile: z.string().default(""),
  assetWidth: z.number().default(0),
  assetHeight: z.number().default(0),
  seccion: z.string().default(""),
  titulo: z.string().default(""),
  body: z.string().default(""),
  dateLabel: z.string().default(""),
  timeLabel: z.string().default(""),
  sourceLabel: z.string().default(""),
  // update
  before: z.string().default(""),
  after: z.string().default(""),
  // weather
  place: z.string().default("La Rioja"),
  temp: z.number().default(0),
  sky: z.string().default(""),
  detail: z.string().default(""),
  days: z.array(WeatherDay).default([]),
  alertSummary: z.string().default(""),
  // alert
  level: z.enum(["amarilla", "naranja", "roja"]).default("amarilla"),
  zones: z.array(z.string()).default([]),
  // dollar
  rows: z.array(DollarRow).default([]),
  // notice
  service: z.enum(["luz", "agua", "rutas", "aviso"]).default("aviso"),
  // holidays
  holidays: z.array(Holiday).default([]),
  countdown: z.string().default(""),
  // payments / quake
  ...ServicePiecesSchema,
});

export type StoryV2Props = z.infer<typeof StoryV2Schema>;

const M = STORY.m;
const W = STORY.w - M * 2;

// ── Publicación / último momento ────────────────────────────────────────
const PostStory: React.FC<{ props: StoryV2Props; breaking: boolean }> = ({ props, breaking }) => {
  const ratio = props.assetWidth > 0 && props.assetHeight > 0 ? props.assetHeight / props.assetWidth : 1.25;
  const cardW = ratio > 1.3 ? 760 : 880;
  const cardH = Math.round(cardW * ratio);
  const top = 420 + Math.max(0, (1100 - cardH) / 2);
  return (
    <AbsoluteFill>
      <PhotoBackdrop src={props.assetFile} strength={0.55} />
      <StoryMasthead
        tab={breaking ? <Tab label="Último momento" fill={C.red} live /> : <Tab label="Nueva publicación" fill={rgba(C.white, 0.14)} />}
      />
      <div
        style={{
          position: "absolute",
          left: (STORY.w - cardW) / 2,
          top,
          width: cardW,
          height: cardH,
          boxShadow: "0 40px 90px rgba(0,0,0,0.55), 0 0 0 2px rgba(255,255,255,0.14)",
          backgroundColor: C.ink,
        }}
      >
        {props.assetFile ? <Img src={staticFile(props.assetFile)} style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : null}
        {breaking ? <div style={{ position: "absolute", left: 0, right: 0, top: -10, height: 10, backgroundColor: C.red }} /> : null}
      </div>
      <StoryCta label="Leé la nota completa · link en la bio" />
    </AbsoluteFill>
  );
};

// ── Reel ────────────────────────────────────────────────────────────────
const ReelStory: React.FC<{ props: StoryV2Props }> = ({ props }) => (
  <AbsoluteFill style={{ backgroundColor: C.ink }}>
    {props.assetFile ? <Img src={staticFile(props.assetFile)} style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : null}
    <AbsoluteFill style={{ background: `linear-gradient(180deg, rgba(0,0,0,0) 76%, ${rgba(C.ink, 0.92)} 86%)` }} />
    <StoryCta label="▶  Mirá el Reel en el perfil" top={1580} />
  </AbsoluteFill>
);

// ── Seguimiento ─────────────────────────────────────────────────────────
const UpdateStory: React.FC<{ props: StoryV2Props }> = ({ props }) => {
  const photo = Boolean(props.assetFile);
  const title = fit({ text: props.titulo, maxWidth: W, maxHeight: photo ? 110 : 220, min: 40, max: 56, weight: 800, lh: 1.04, stretch: "semi-condensed", maxLines: photo ? 2 : 3 });
  const after = fit({ text: props.after, maxWidth: W - 56, maxHeight: photo ? 250 : 360, min: 48, max: 88, weight: 900, lh: 1.0, stretch: "condensed", maxLines: 4 });
  return (
    <AbsoluteFill>
      <PhotoBackdrop src={props.assetFile} strength={0.7} />
      <StoryMasthead tab={<Tab label="Actualización" fill={C.red} detail={props.timeLabel} />} />
      {props.assetFile ? (
        <div style={{ position: "absolute", left: M, right: M, top: 410, height: 420, overflow: "hidden", boxShadow: "0 30px 70px rgba(0,0,0,0.45)" }}>
          <Img src={staticFile(props.assetFile)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        </div>
      ) : null}
      <div style={{ position: "absolute", left: M, right: M, top: props.assetFile ? 880 : 470, display: "flex", flexDirection: "column", gap: 30 }}>
        <div style={caps(24, rgba(C.white, 0.7), 700, 0.18)}>Seguimos informando</div>
        <div style={{ ...display(title.fontSize, C.white, 800), lineHeight: `${title.lineHeight}px` }}>
          {title.lines.map((l, i) => (
            <div key={i}>{l}</div>
          ))}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 26, marginTop: 6, paddingLeft: 32, borderLeft: `8px solid ${C.red}` }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <span style={caps(22, rgba(C.white, 0.55), 800, 0.18)}>Antes</span>
            <span style={{ ...serif(40, rgba(C.white, 0.55)), textDecoration: "line-through", textDecorationThickness: 3 }}>{props.before}</span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <span style={caps(22, C.white, 800, 0.18)}>Ahora</span>
            <div style={{ ...display(after.fontSize, C.white, 900, "condensed"), lineHeight: `${after.lineHeight}px` }}>
              {after.lines.map((l, i) => (
                <div key={i}>{l}</div>
              ))}
            </div>
          </div>
        </div>
        {props.sourceLabel ? <div style={serif(30, rgba(C.white, 0.7))}>{props.sourceLabel}</div> : null}
      </div>
      <StoryCta label="Nota actualizada · link en la bio" />
    </AbsoluteFill>
  );
};

// ── Clima ───────────────────────────────────────────────────────────────
// Azul noche de las placas de servicio. Temperatura actual gigante, cielo
// y mínima/máxima de hoy al lado; pronóstico en cinco columnas con la franja
// de cada día sobre la misma escala; alerta del SMN en una banda al pie.
const INK = THEMES.ink;
const WARM = "#F2994A";

const WeatherStory: React.FC<{ props: StoryV2Props }> = ({ props }) => {
  const days = props.days.slice(0, 5);
  const today = days[0];
  const lo = Math.min(...days.map((d) => d.min), props.temp);
  const hi = Math.max(...days.map((d) => d.max), props.temp);
  const span = Math.max(1, hi - lo);
  const alertOn = Boolean(props.alertSummary) && !/^sin alertas/i.test(props.alertSummary);
  const temp = `${Math.round(props.temp)}°`;
  const tempFit = fit({ text: temp, maxWidth: 560, maxHeight: 420, min: 200, max: 420, weight: 900, lh: 0.9, stretch: "condensed", maxLines: 1 });
  const sideW = W - tempFit.widest - 36;
  const sky = fit({ text: props.sky, maxWidth: sideW, maxHeight: 190, min: 44, max: 76, weight: 900, lh: 0.98, stretch: "condensed", maxLines: 3 });
  const colGap = 14;
  const colW = (W - colGap * (days.length - 1)) / Math.max(1, days.length);
  const barH = 190;
  return (
    <AbsoluteFill>
      <PlateBackdrop tone="ink" />
      <AbsoluteFill style={{ background: `radial-gradient(70% 40% at 100% 30%, ${rgba(WARM, props.temp >= 28 ? 0.2 : 0.06)} 0%, ${rgba(WARM, 0)} 70%)` }} />
      <div style={{ position: "absolute", left: M, right: M, top: STORY.top, display: "flex", flexDirection: "column", gap: 28 }}>
        <Brand color={C.white} seal={78} size={32} sub="" />
        <TagPair label="El tiempo" fill={C.blue} color={C.white} detail={props.place} theme={INK} />
      </div>
      <div style={{ position: "absolute", left: M, right: M, top: 470, display: "flex", flexDirection: "column", gap: 10 }}>
        <span style={caps(26, INK.mute, 800, 0.16)}>{props.dateLabel}</span>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 36 }}>
          <div style={{ ...display(tempFit.fontSize, C.white, 900, "condensed"), lineHeight: `${tempFit.lineHeight}px`, letterSpacing: "-0.03em" }}>{temp}</div>
          <div style={{ width: sideW, display: "flex", flexDirection: "column", gap: 22, paddingTop: 24 }}>
            <div style={{ ...display(sky.fontSize, C.white, 900, "condensed"), lineHeight: `${sky.lineHeight}px` }}>
              {sky.lines.map((l, i) => (
                <div key={i}>{l}</div>
              ))}
            </div>
            {today ? (
              <div style={{ display: "flex", gap: 12 }}>
                {[
                  ["Mín", today.min, INK.accent],
                  ["Máx", today.max, WARM],
                ].map(([label, value, color]) => (
                  <div key={label as string} style={{ flex: 1, borderTop: `6px solid ${color}`, backgroundColor: rgba(C.white, 0.06), padding: "14px 16px" }}>
                    <div style={caps(20, INK.mute, 800, 0.16)}>{label as string}</div>
                    <div style={{ ...display(64, C.white, 900, "condensed"), lineHeight: 1, marginTop: 8 }}>{Math.round(value as number)}°</div>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </div>
        {props.detail ? <span style={{ ...caps(24, INK.mute, 700, 0.1), whiteSpace: "normal", lineHeight: 1.3, marginTop: 12 }}>{props.detail}</span> : null}
      </div>
      <div style={{ position: "absolute", left: M, right: M, top: 1000, display: "flex", gap: colGap }}>
        {days.map((d, i) => {
          const top = ((hi - d.max) / span) * barH;
          const bottom = ((hi - d.min) / span) * barH;
          return (
            <div
              key={i}
              style={{
                width: colW,
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: 12,
                padding: "20px 0 18px",
                backgroundColor: i === 0 ? rgba(C.white, 0.09) : rgba(C.white, 0.035),
                borderTop: `4px solid ${i === 0 ? C.red : INK.rule}`,
              }}
            >
              <span style={caps(24, i === 0 ? C.white : INK.mute, 900, 0.12)}>{d.label}</span>
              <span style={{ ...display(54, C.white, 900, "condensed"), lineHeight: 1 }}>{Math.round(d.max)}°</span>
              <div style={{ position: "relative", width: 14, height: barH, borderRadius: 7, backgroundColor: rgba(C.white, 0.08) }}>
                <div
                  style={{
                    position: "absolute",
                    left: 0,
                    right: 0,
                    top,
                    height: Math.max(14, bottom - top),
                    borderRadius: 7,
                    background: `linear-gradient(180deg, ${WARM}, ${INK.accent})`,
                  }}
                />
              </div>
              <span style={{ ...display(40, INK.mute, 800, "condensed"), lineHeight: 1 }}>{Math.round(d.min)}°</span>
              <span style={{ ...caps(18, d.rain > 0 ? INK.accent : rgba(C.white, 0.3), 800, 0.06), height: 18 }}>
                {d.rain > 0 ? `${d.rain.toLocaleString("es-AR")} mm` : "Sin lluvia"}
              </span>
            </div>
          );
        })}
      </div>
      <div
        style={{
          position: "absolute",
          left: M,
          right: M,
          top: 1478,
          display: "flex",
          alignItems: "center",
          gap: 18,
          padding: "20px 24px",
          backgroundColor: alertOn ? "#E3A008" : rgba(C.white, 0.06),
          border: alertOn ? "none" : `2px solid ${INK.rule}`,
        }}
      >
        <span style={{ width: 16, height: 16, borderRadius: 8, backgroundColor: alertOn ? INK.bg : "#3DD68C", flexShrink: 0 }} />
        <span style={{ ...caps(24, alertOn ? INK.bg : C.white, 900, 0.1), whiteSpace: "normal", lineHeight: 1.2 }}>{props.alertSummary || "Sin alertas del SMN para La Rioja"}</span>
      </div>
      <SourceLine left={props.sourceLabel || "Fuente: Servicio Meteorológico Nacional"} color={C.white} top={1586} />
    </AbsoluteFill>
  );
};

// ── Alerta ──────────────────────────────────────────────────────────────
const LEVEL = {
  amarilla: { color: "#E8B400", ink: C.ink },
  naranja: { color: "#EE7A00", ink: C.white },
  roja: { color: "#D0021B", ink: C.white },
} as const;

const AlertStory: React.FC<{ props: StoryV2Props }> = ({ props }) => {
  const level = LEVEL[props.level];
  const title = fit({ text: props.titulo, maxWidth: W, maxHeight: 440, min: 64, max: 140, weight: 900, lh: 1.0, stretch: "condensed", maxLines: 3 });
  return (
    <AbsoluteFill>
      <FieldBackdrop from={rgba(level.color, 1)} to="#2a1600" />
      <AbsoluteFill style={{ background: `linear-gradient(180deg, ${rgba(C.ink, 0.15)} 0%, ${rgba(C.ink, 0.75)} 70%)` }} />
      <StoryMasthead tab={<Tab label={`Alerta ${props.level}`} fill={C.ink} />} />
      <div style={{ position: "absolute", left: M, right: M, top: 540, display: "flex", flexDirection: "column", gap: 40 }}>
        <svg width={130} height={116} viewBox="0 0 130 116">
          <path d="M65 6 L124 110 L6 110 Z" fill="none" stroke={C.white} strokeWidth={9} strokeLinejoin="round" />
          <rect x={59} y={40} width={12} height={40} rx={4} fill={C.white} />
          <circle cx={65} cy={94} r={7} fill={C.white} />
        </svg>
        <div style={{ ...display(title.fontSize, C.white, 900, "condensed"), lineHeight: `${title.lineHeight}px` }}>
          {title.lines.map((l, i) => (
            <div key={i}>{l}</div>
          ))}
        </div>
        {props.body ? <div style={serif(38, rgba(C.white, 0.92))}>{props.body}</div> : null}
        {props.zones.length ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 16, marginTop: 10 }}>
            <span style={caps(22, rgba(C.white, 0.7), 800, 0.18)}>Zonas</span>
            <div style={serif(34, C.white, false, 500)}>{props.zones.join(" · ")}</div>
          </div>
        ) : null}
        {props.timeLabel ? <div style={caps(24, C.white, 700, 0.12)}>{props.timeLabel}</div> : null}
      </div>
      <SourceLine left={props.sourceLabel || "Fuente: Servicio Meteorológico Nacional"} />
    </AbsoluteFill>
  );
};

// ── Dólar ───────────────────────────────────────────────────────────────
// Las dos primeras cotizaciones (oficial y blue) en tarjetas grandes; el
// resto en filas. Variación desde el último aviso en un chip: sube en rojo,
// baja en verde. La brecha sale del texto que arma Python.
const UP = "#FF6B5E";
const DOWN = "#3DD68C";

const Delta: React.FC<{ value: number; size?: number }> = ({ value, size = 22 }) =>
  value ? (
    <span style={{ ...caps(size, value > 0 ? UP : DOWN, 900, 0.06), display: "inline-flex", alignItems: "center", gap: 8 }}>
      {value > 0 ? "▲" : "▼"} ${Math.abs(value).toLocaleString("es-AR", { maximumFractionDigits: 2 })}
    </span>
  ) : (
    <span style={caps(size, THEMES.ink.mute, 800, 0.06)}>Sin cambios</span>
  );

const DollarStory: React.FC<{ props: StoryV2Props }> = ({ props }) => {
  const featured = props.rows.slice(0, 2);
  const rest = props.rows.slice(2, 5);
  const gap = /brecha[^:]*:\s*([\d.,]+\s*%)/i.exec(props.body)?.[1] ?? "";
  const cardW = (W - 20) / 2;
  // Las filas restantes llenan el alto hasta la banda de brecha.
  const rowH = Math.min(190, 392 / Math.max(1, rest.length));
  return (
    <AbsoluteFill>
      <PlateBackdrop tone="ink" />
      <div style={{ position: "absolute", left: M, right: M, top: STORY.top, display: "flex", flexDirection: "column", gap: 28 }}>
        <Brand color={C.white} seal={78} size={32} sub="" />
        <TagPair label="Economía" fill={C.red} color={C.white} detail={props.dateLabel} theme={INK} />
      </div>
      <div style={{ position: "absolute", left: M, right: M, top: 470, ...display(176, C.white, 900, "condensed"), lineHeight: 0.92, letterSpacing: "-0.02em" }}>
        DÓLAR <span style={{ color: INK.accent }}>HOY</span>
      </div>
      <div style={{ position: "absolute", left: M, right: M, top: 660, display: "flex", gap: 20 }}>
        {featured.map((row, i) => {
          const sell = fit({ text: `$${row.sell}`, maxWidth: cardW - 56, maxHeight: 150, min: 80, max: 140, weight: 900, lh: 1, stretch: "condensed", maxLines: 1 });
          return (
            <div key={i} style={{ width: cardW, backgroundColor: i === 1 ? C.blue : rgba(C.white, 0.07), border: i === 1 ? "none" : `2px solid ${INK.rule}`, padding: "28px 28px 26px", display: "flex", flexDirection: "column", gap: 14 }}>
              <span style={caps(28, C.white, 900, 0.14)}>{row.name}</span>
              <span style={{ ...display(sell.fontSize, C.white, 900, "condensed"), lineHeight: 1, fontVariantNumeric: "tabular-nums" }}>${row.sell}</span>
              <span style={caps(20, rgba(C.white, 0.7), 800, 0.12)}>Venta</span>
              <div style={{ height: 2, backgroundColor: rgba(C.white, 0.18), margin: "4px 0" }} />
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ ...caps(22, rgba(C.white, 0.85), 800, 0.08), fontVariantNumeric: "tabular-nums" }}>{row.buy ? `Compra $${row.buy}` : ""}</span>
                <Delta value={row.delta ?? 0} size={20} />
              </div>
            </div>
          );
        })}
      </div>
      <div style={{ position: "absolute", left: M, right: M, top: 1048, display: "flex", flexDirection: "column" }}>
        {rest.map((row, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", height: rowH, borderTop: `2px solid ${i === 0 ? INK.accent : INK.rule}`, gap: 20 }}>
            <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 10 }}>
              <span style={{ ...display(rowH > 150 ? 64 : 52, C.white, 900, "condensed"), lineHeight: 1 }}>{row.name}</span>
              <Delta value={row.delta ?? 0} size={18} />
            </div>
            <span style={{ width: 230, textAlign: "right", ...caps(24, INK.mute, 800, 0.06), fontVariantNumeric: "tabular-nums" }}>{row.buy ? `Compra $${row.buy}` : ""}</span>
            <span style={{ width: 330, textAlign: "right", ...display(rowH > 150 ? 96 : 76, C.white, 900, "condensed"), lineHeight: 1, fontVariantNumeric: "tabular-nums" }}>${row.sell}</span>
          </div>
        ))}
      </div>
      {gap ? (
        <div style={{ position: "absolute", left: M, right: M, top: 1458, display: "flex", alignItems: "center", justifyContent: "space-between", padding: "18px 24px", backgroundColor: rgba(C.white, 0.06), border: `2px solid ${INK.rule}` }}>
          <span style={caps(24, INK.mute, 800, 0.14)}>Brecha blue / oficial</span>
          <span style={{ ...display(58, C.white, 900, "condensed"), lineHeight: 1 }}>{gap}</span>
        </div>
      ) : null}
      <SourceLine left={props.sourceLabel || "Fuente: dolarapi.com"} right={props.timeLabel ? `Actualizado ${props.timeLabel}` : "lavozriojana.com"} color={C.white} top={1586} />
    </AbsoluteFill>
  );
};

// ── Aviso de servicio ───────────────────────────────────────────────────
const SERVICE = {
  luz: { label: "Corte de luz", color: "#F2A900", from: "#2b2208" },
  agua: { label: "Corte de agua", color: "#3d8fe0", from: "#0c2236" },
  rutas: { label: "Rutas", color: "#45b37a", from: "#0d2a1d" },
  aviso: { label: "Aviso", color: C.red, from: "#2a0d0d" },
} as const;

const ServiceIcon: React.FC<{ service: StoryV2Props["service"]; color: string }> = ({ service, color }) => {
  if (service === "luz")
    return (
      <svg width={120} height={150} viewBox="0 0 120 150">
        <path d="M70 4 L14 86 H56 L44 146 L106 58 H64 Z" fill={color} />
      </svg>
    );
  if (service === "agua")
    return (
      <svg width={120} height={150} viewBox="0 0 120 150">
        <path d="M60 6 C60 6 108 66 108 96 A48 48 0 0 1 12 96 C12 66 60 6 60 6 Z" fill={color} />
      </svg>
    );
  if (service === "rutas")
    return (
      <svg width={150} height={150} viewBox="0 0 150 150">
        <path d="M52 8 L20 142 H64 L70 8 Z M80 8 L86 142 H130 L98 8 Z" fill={color} />
        <rect x={71} y={20} width={8} height={26} fill={color} />
        <rect x={71} y={64} width={8} height={26} fill={color} />
        <rect x={71} y={108} width={8} height={30} fill={color} />
      </svg>
    );
  return (
    <svg width={130} height={130} viewBox="0 0 130 130">
      <circle cx={65} cy={65} r={58} fill="none" stroke={color} strokeWidth={9} />
      <rect x={59} y={30} width={12} height={46} rx={4} fill={color} />
      <circle cx={65} cy={96} r={7} fill={color} />
    </svg>
  );
};

const NoticeStory: React.FC<{ props: StoryV2Props }> = ({ props }) => {
  const s = SERVICE[props.service];
  const title = fit({ text: props.titulo, maxWidth: W, maxHeight: 420, min: 56, max: 96, weight: 900, lh: 1.02, stretch: "condensed", maxLines: 5 });
  const body = props.body
    ? fit({ text: props.body, maxWidth: W, maxHeight: 330, min: 30, max: 38, weight: 500, lh: 1.3, family: V2_FONT_SERIF, italic: true, maxLines: 7 })
    : null;
  return (
    <AbsoluteFill>
      <FieldBackdrop from={s.from} to={C.ink} dots={rgba(s.color, 0.12)} />
      <StoryMasthead tab={<Tab label={s.label} fill={s.color} color={props.service === "luz" ? C.ink : C.white} />} />
      <div style={{ position: "absolute", left: M, right: M, top: 460, display: "flex", flexDirection: "column", gap: 38 }}>
        <ServiceIcon service={props.service} color={s.color} />
        <div style={{ ...display(title.fontSize, C.white, 900, "condensed"), lineHeight: `${title.lineHeight}px` }}>
          {title.lines.map((l, i) => (
            <div key={i}>{l}</div>
          ))}
        </div>
        {body ? (
          <div style={{ ...serif(body.fontSize, rgba(C.white, 0.88)), lineHeight: `${body.lineHeight}px`, borderLeft: `6px solid ${s.color}`, paddingLeft: 26 }}>
            {body.lines.map((l, i) => (
              <div key={i}>{l}</div>
            ))}
          </div>
        ) : null}
        {props.dateLabel ? <div style={caps(22, rgba(C.white, 0.65), 700, 0.14)}>{props.dateLabel}</div> : null}
      </div>
      <StoryCta label="Detalles · link en la bio" top={1480} />
      <SourceLine left={props.sourceLabel || "Información de servicio"} top={1612} />
    </AbsoluteFill>
  );
};

// ── Feriados ────────────────────────────────────────────────────────────
const HolidaysStory: React.FC<{ props: StoryV2Props }> = ({ props }) => {
  const [next, ...rest] = props.holidays;
  const ink = C.paperInk;
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ backgroundColor: C.paper }} />
      <StoryMasthead color={ink} tab={<Tab label="Feriados" fill={C.red} />} rule={rgba(ink, 0.18)} />
      <div style={{ position: "absolute", left: M, right: M, top: 440, display: "flex", flexDirection: "column", gap: 14 }}>
        <div style={display(96, ink, 900, "condensed")}>Próximos feriados</div>
        {props.countdown ? <div style={serif(36, C.paperMute)}>{props.countdown}</div> : null}
      </div>
      {next ? (
        <div style={{ position: "absolute", left: M, right: M, top: 680, display: "flex", gap: 40, alignItems: "stretch", padding: "44px 44px", backgroundColor: C.ink }}>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", width: 200, borderRight: `2px solid ${rgba(C.white, 0.2)}`, paddingRight: 36 }}>
            <span style={{ ...display(150, C.white, 900, "condensed"), lineHeight: 0.92 }}>{next.day}</span>
            <span style={caps(30, C.red, 900, 0.16)}>{next.month}</span>
          </div>
          <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center", gap: 18 }}>
            <span style={caps(24, rgba(C.white, 0.65), 700, 0.16)}>{next.weekday}</span>
            <span style={{ ...display(54, C.white, 850), lineHeight: 1.05 }}>{next.name}</span>
            {next.kind ? <span style={serif(30, rgba(C.white, 0.7))}>{next.kind}</span> : null}
          </div>
        </div>
      ) : null}
      <div style={{ position: "absolute", left: M, right: M, top: 1060, display: "flex", flexDirection: "column" }}>
        {rest.slice(0, 3).map((h, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 36, padding: "34px 0", borderTop: `2px solid ${rgba(ink, 0.14)}` }}>
            <div style={{ width: 150, display: "flex", alignItems: "baseline", gap: 12 }}>
              <span style={display(64, ink, 900, "condensed")}>{h.day}</span>
              <span style={caps(22, C.red, 900, 0.14)}>{h.month}</span>
            </div>
            <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 10 }}>
              <span style={{ ...display(38, ink, 800), lineHeight: 1.08 }}>{h.name}</span>
              <span style={caps(19, C.paperMute, 700, 0.12)}>
                {h.weekday}
                {h.kind ? ` · ${h.kind}` : ""}
              </span>
            </div>
          </div>
        ))}
      </div>
      <SourceLine left={props.sourceLabel || "Fuente: calendario oficial"} color={ink} />
    </AbsoluteFill>
  );
};

// ── Placas de servicio (pagos y sismo) ──────────────────────────────────
const ServiceStory: React.FC<{ props: StoryV2Props }> = ({ props }) => (
  <ServicePlate
    status={props.status}
    kicker={props.kicker}
    hero={props.hero}
    heroLabel={props.heroLabel}
    lines={props.lines}
    footer={props.footer}
    tone={props.kind === "payments" ? "paper" : "ink"}
    width={STORY.w}
    height={STORY.h}
    margin={M}
  />
);

export const StoryV2: React.FC<StoryV2Props> = (props) => {
  const ready = useV2FontsReady();
  if (!ready) return <AbsoluteFill style={{ backgroundColor: C.ink }} />;
  switch (props.kind) {
    case "post":
      return <PostStory props={props} breaking={false} />;
    case "breaking":
      return <PostStory props={props} breaking />;
    case "reel":
      return <ReelStory props={props} />;
    case "update":
      return <UpdateStory props={props} />;
    case "weather":
      return <WeatherStory props={props} />;
    case "alert":
      return <AlertStory props={props} />;
    case "dollar":
      return <DollarStory props={props} />;
    case "notice":
      return <NoticeStory props={props} />;
    case "holidays":
      return <HolidaysStory props={props} />;
    case "payments":
    case "quake":
      return <ServiceStory props={props} />;
    default:
      return <AbsoluteFill style={{ backgroundColor: C.ink }} />;
  }
};
