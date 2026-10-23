// MorningBriefV2 — carrusel diario "Lo que tenés que saber hoy" (1080×1350).
// Mismo sistema que las placas de servicio (ServicePieces.tsx): azul noche
// con cuadrícula para la tapa y los servicios, gris frío para las notas,
// Archivo condensada muy pesada y el rojo de marca para lo que importa.
//
//   cover     tapa: fecha y clima en rótulos, título grande y sumario
//             numerado de las notas.
//   news      una lámina por noticia: foto real de la nota + titular + bajada.
//   services  servicios del día: clima destacado y el resto en grilla.
//
// Todo el texto llega armado desde Python con datos ya publicados (títulos y
// bajadas de las notas, SMN, dólar, feriados): la composición sólo lo
// dispone y nunca lo completa.
import React from "react";
import { AbsoluteFill, Img, staticFile } from "remotion";
import { z } from "zod";
import { fit } from "../fit";
import { useV2FontsReady } from "../fonts";
import { C, rgba, sectionStyle } from "../tokens";
import { caps, display } from "./chrome";
import { PlateBackdrop, TagPair, THEMES } from "./ServicePieces";

const IndexItem = z.object({ seccion: z.string(), titulo: z.string() });
const ServiceRow = z.object({ label: z.string(), value: z.string(), note: z.string().default("") });

export const MorningBriefV2Schema = z.object({
  slide: z.enum(["cover", "news", "services"]),
  dateLabel: z.string().default(""),
  weatherLine: z.string().default(""),
  index: z.array(IndexItem).default([]),
  number: z.number().default(1),
  total: z.number().default(5),
  page: z.string().default(""),
  seccion: z.string().default(""),
  titulo: z.string().default(""),
  deck: z.string().default(""),
  assetFile: z.string().default(""),
  services: z.array(ServiceRow).default([]),
});

export type MorningBriefV2Props = z.infer<typeof MorningBriefV2Schema>;

const W = 1080;
const H = 1350;
const M = 72;
const INNER = W - M * 2;
const FOOT = 96;
const INK = THEMES.ink;
const PAPER = THEMES.paper;
// Rojo de marca aclarado para texto sobre azul noche (el corporativo no
// alcanza contraste ahí).
const RED_ON_INK = "#FF5A4F";

const Seal: React.FC<{ size: number }> = ({ size }) => <Img src={staticFile("logo.png")} style={{ width: size, height: size, objectFit: "contain" }} />;

const Wordmark: React.FC<{ size: number; color: string }> = ({ size, color }) => (
  <div style={{ display: "flex", alignItems: "baseline", gap: size * 0.26, ...display(size, color, 900, "condensed"), letterSpacing: "0.04em", lineHeight: 1 }}>
    <span>LA VOZ</span>
    <span>RIOJANA</span>
    <span style={{ width: size * 0.24, height: size * 0.24, backgroundColor: C.red, alignSelf: "center" }} />
  </div>
);

const Masthead: React.FC<{ right: string; color: string; mute: string }> = ({ right, color, mute }) => (
  <div style={{ position: "absolute", left: M, right: M, top: 52, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
    <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
      <Seal size={72} />
      <Wordmark size={32} color={color} />
    </div>
    <span style={caps(20, mute, 800, 0.16)}>{right}</span>
  </div>
);

const Footer: React.FC<{ left: string; page: string; theme: typeof INK | typeof PAPER }> = ({ left, page, theme }) => (
  <div style={{ position: "absolute", left: M, right: M, bottom: 0, height: FOOT, display: "flex", alignItems: "center", justifyContent: "space-between", borderTop: `2px solid ${theme.rule}` }}>
    <span style={caps(21, theme.mute, 800, 0.14)}>{left}</span>
    <span style={{ ...caps(21, theme.ink, 900, 0.14), fontVariantNumeric: "tabular-nums" }}>{page}</span>
  </div>
);

// ── Tapa ────────────────────────────────────────────────────────────────
const Cover: React.FC<{ props: MorningBriefV2Props }> = ({ props }) => {
  const rows = props.index.slice(0, 5);
  const listTop = 520;
  const rowH = (H - FOOT - 24 - listTop) / Math.max(4, rows.length);
  return (
    <AbsoluteFill>
      <PlateBackdrop tone="ink" />
      <Masthead right="Edición de la mañana" color={C.white} mute={INK.mute} />
      <div style={{ position: "absolute", left: M, right: M, top: 160, display: "flex", flexWrap: "wrap", alignItems: "center", gap: 16 }}>
        <TagPair label="Hoy" fill={C.red} color={C.white} detail={props.dateLabel} theme={INK} k={0.85} />
        {props.weatherLine ? <span style={caps(20, INK.mute, 800, 0.12)}>{props.weatherLine}</span> : null}
      </div>
      <div style={{ position: "absolute", left: M, right: M, top: 262, ...display(120, C.white, 900, "condensed"), lineHeight: 0.9, letterSpacing: "-0.015em", textTransform: "uppercase" }}>
        Lo que tenés que
        <br />
        saber <span style={{ color: RED_ON_INK }}>hoy</span>
      </div>
      <div style={{ position: "absolute", left: M, right: M, top: listTop, display: "flex", flexDirection: "column" }}>
        {rows.map((row, i) => {
          const sec = sectionStyle(row.seccion);
          const t = fit({ text: row.titulo, maxWidth: INNER - 110, maxHeight: rowH - 52, min: 28, max: 38, weight: 800, lh: 1.06, stretch: "semi-condensed", maxLines: 2 });
          return (
            <div key={i} style={{ display: "flex", gap: 28, alignItems: "flex-start", height: rowH, paddingTop: 16, borderTop: `2px solid ${i === 0 ? RED_ON_INK : INK.rule}`, overflow: "hidden" }}>
              <span style={{ width: 82, ...display(80, RED_ON_INK, 900, "condensed"), lineHeight: 0.85, fontVariantNumeric: "tabular-nums" }}>{i + 1}</span>
              <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 8 }}>
                <span style={caps(18, sec.accent === C.red ? RED_ON_INK : INK.accent, 900, 0.16)}>{sec.label}</span>
                <div style={{ ...display(t.fontSize, C.white, 800), lineHeight: `${t.lineHeight}px` }}>
                  {t.lines.map((l, k) => (
                    <div key={k}>{l}</div>
                  ))}
                </div>
              </div>
            </div>
          );
        })}
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: FOOT, backgroundColor: C.red, display: "flex", alignItems: "center", justifyContent: "space-between", padding: `0 ${M}px` }}>
        <span style={caps(24, C.white, 900, 0.12)}>Deslizá para leer cada noticia</span>
        <span style={{ ...caps(24, C.white, 900, 0.1), display: "flex", gap: 16, alignItems: "center" }}>
          {props.page}
          <span style={{ fontSize: 32, letterSpacing: 0 }}>→</span>
        </span>
      </div>
    </AbsoluteFill>
  );
};

// ── Noticia ─────────────────────────────────────────────────────────────
const News: React.FC<{ props: MorningBriefV2Props }> = ({ props }) => {
  const sec = sectionStyle(props.seccion);
  const deck = props.deck
    ? fit({ text: props.deck, maxWidth: INNER - 30, maxHeight: 130, min: 26, max: 32, weight: 500, lh: 1.28, stretch: "semi-condensed", maxLines: 3 })
    : null;
  const headline = fit({ text: props.titulo, maxWidth: INNER, maxHeight: 360, min: 52, max: 92, weight: 900, lh: 0.98, stretch: "condensed", maxLines: 4 });
  // La foto crece hasta donde empieza el texto: sin aire muerto abajo.
  const textH = headline.height + (deck ? deck.height + 26 : 0);
  const photoH = Math.max(540, Math.min(840, H - FOOT - 70 - textH - 34 - 58));
  const textTop = photoH + 58;
  return (
    <AbsoluteFill>
      <PlateBackdrop tone="paper" />
      <div style={{ position: "absolute", left: 0, top: 0, width: W, height: photoH, overflow: "hidden", backgroundColor: INK.bg }}>
        {props.assetFile ? <Img src={staticFile(props.assetFile)} style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : null}
        <AbsoluteFill style={{ background: `linear-gradient(180deg, ${rgba(INK.bg, 0.75)} 0%, ${rgba(INK.bg, 0)} 30%, ${rgba(INK.bg, 0)} 75%, ${rgba(INK.bg, 0.35)} 100%)` }} />
      </div>
      <div style={{ position: "absolute", left: M, top: 46, display: "flex", alignItems: "center", gap: 14 }}>
        <Seal size={58} />
        <span style={caps(21, C.white, 900, 0.14)}>Lo que tenés que saber hoy</span>
      </div>
      <div style={{ position: "absolute", left: M, top: photoH - 58, height: 116, display: "flex", alignItems: "stretch" }}>
        <span style={{ display: "flex", alignItems: "center", padding: "0 30px", backgroundColor: C.red, ...display(84, C.white, 900, "condensed"), lineHeight: 1 }}>{props.number}</span>
        <span style={{ display: "flex", alignItems: "center", padding: "0 28px", backgroundColor: INK.bg, ...caps(24, C.white, 900, 0.16) }}>{sec.label}</span>
      </div>
      <div style={{ position: "absolute", left: M, right: M, top: textTop + 34, display: "flex", flexDirection: "column", gap: 26 }}>
        <div style={{ ...display(headline.fontSize, PAPER.ink, 900, "condensed"), lineHeight: `${headline.lineHeight}px`, letterSpacing: "-0.01em" }}>
          {headline.lines.map((l, i) => (
            <div key={i}>{l}</div>
          ))}
        </div>
        {deck ? (
          <div style={{ ...display(deck.fontSize, PAPER.mute, 500), lineHeight: `${deck.lineHeight}px`, borderLeft: `6px solid ${sec.accent}`, paddingLeft: 24 }}>
            {deck.lines.map((l, i) => (
              <div key={i}>{l}</div>
            ))}
          </div>
        ) : null}
      </div>
      <Footer left="Nota completa en lavozriojana.com" page={props.page} theme={PAPER} />
    </AbsoluteFill>
  );
};

// ── Servicios ───────────────────────────────────────────────────────────
const ServiceTile: React.FC<{ row: z.infer<typeof ServiceRow>; width: number; height: number; big?: boolean }> = ({ row, width, height, big }) => {
  const value = fit({
    text: row.value,
    maxWidth: width - 56,
    maxHeight: height - (big ? 110 : 128),
    min: 34,
    max: big ? 84 : 88,
    weight: 900,
    lh: 1.0,
    stretch: "condensed",
    maxLines: 2,
  });
  return (
    <div
      style={{
        width,
        height,
        padding: "22px 28px",
        backgroundColor: big ? C.blue : rgba(C.white, 0.06),
        border: big ? "none" : `2px solid ${INK.rule}`,
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
      }}
    >
      <span style={caps(20, big ? rgba(C.white, 0.85) : INK.mute, 900, 0.16)}>{row.label}</span>
      <div style={{ ...display(value.fontSize, C.white, 900, "condensed"), lineHeight: `${value.lineHeight}px` }}>
        {value.lines.map((l, i) => (
          <div key={i}>{l}</div>
        ))}
      </div>
      <span style={{ ...caps(18, big ? rgba(C.white, 0.85) : INK.mute, 800, 0.1), whiteSpace: "normal", lineHeight: 1.25 }}>{row.note}</span>
    </div>
  );
};

const Services: React.FC<{ props: MorningBriefV2Props }> = ({ props }) => {
  const [first, ...rest] = props.services.slice(0, 6);
  const gap = 16;
  const gridTop = 600;
  const rowsN = Math.max(1, Math.ceil(rest.length / 2));
  const tileH = Math.min(300, (H - FOOT - 28 - gridTop - gap * (rowsN - 1)) / rowsN);
  const half = (INNER - gap) / 2;
  const title = fit({ text: "Para organizar tu día", maxWidth: INNER, maxHeight: 120, min: 64, max: 112, weight: 900, lh: 1, stretch: "condensed", maxLines: 1, uppercase: true });
  return (
    <AbsoluteFill>
      <PlateBackdrop tone="ink" />
      <Masthead right={props.dateLabel} color={C.white} mute={INK.mute} />
      <div style={{ position: "absolute", left: M, right: M, top: 176, ...display(title.fontSize, C.white, 900, "condensed"), lineHeight: 1, textTransform: "uppercase", letterSpacing: "-0.015em", whiteSpace: "nowrap" }}>
        Para organizar <span style={{ color: RED_ON_INK }}>tu día</span>
      </div>
      {first ? (
        <div style={{ position: "absolute", left: M, top: 318 }}>
          <ServiceTile row={first} width={INNER} height={262} big />
        </div>
      ) : null}
      <div style={{ position: "absolute", left: M, right: M, top: gridTop, display: "flex", flexWrap: "wrap", gap }}>
        {rest.map((row, i) => {
          const alone = i === rest.length - 1 && rest.length % 2 === 1;
          return <ServiceTile key={i} row={row} width={alone ? INNER : half} height={tileH} />;
        })}
      </div>
      <Footer left="Seguí @lavozriojana · todos los días a las 8" page={props.page} theme={INK} />
    </AbsoluteFill>
  );
};

export const MorningBriefV2: React.FC<MorningBriefV2Props> = (props) => {
  const ready = useV2FontsReady();
  if (!ready) return <AbsoluteFill style={{ backgroundColor: INK.bg }} />;
  if (props.slide === "cover") return <Cover props={props} />;
  if (props.slide === "services") return <Services props={props} />;
  return <News props={props} />;
};
