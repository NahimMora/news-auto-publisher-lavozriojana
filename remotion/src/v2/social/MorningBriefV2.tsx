// MorningBriefV2 — carrusel diario "Lo que tenés que saber hoy" (1080×1350).
// Tapa de diario: cabecera con sello, doble filete, fecha y clima, título en
// serif y sumario numerado; después una lámina por noticia (foto real de la
// nota + titular + bajada) y una lámina final de servicios del día.
//
// Todo el texto llega armado desde Python con datos ya publicados (títulos y
// bajadas de las notas, SMN, dólar, feriados): la composición sólo lo
// dispone y nunca lo completa.
import React from "react";
import { AbsoluteFill, Img, staticFile } from "remotion";
import { z } from "zod";
import { Grain } from "../../shared/Grain";
import { fit } from "../fit";
import { useV2FontsReady } from "../fonts";
import { C, V2_FONT_SERIF, rgba, sectionStyle } from "../tokens";
import { caps, display, serif } from "./chrome";

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

const Seal: React.FC<{ size: number }> = ({ size }) => (
  <Img src={staticFile("logo.png")} style={{ width: size, height: size, objectFit: "contain" }} />
);

const Wordmark: React.FC<{ size: number; color: string }> = ({ size, color }) => (
  <div style={{ display: "flex", alignItems: "baseline", gap: size * 0.26, ...display(size, color, 900, "condensed"), letterSpacing: "0.04em", lineHeight: 1 }}>
    <span>LA VOZ</span>
    <span>RIOJANA</span>
    <span style={{ width: size * 0.24, height: size * 0.24, backgroundColor: C.red, alignSelf: "center" }} />
  </div>
);

const DoubleRule: React.FC<{ color: string }> = ({ color }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
    <div style={{ height: 4, backgroundColor: color }} />
    <div style={{ height: 1.5, backgroundColor: color }} />
  </div>
);

const Footer: React.FC<{ left: string; page: string; dark?: boolean }> = ({ left, page, dark }) => {
  const fg = dark ? C.white : C.paperInk;
  return (
    <div style={{ position: "absolute", left: M, right: M, bottom: 0, height: FOOT, display: "flex", flexDirection: "column", justifyContent: "center", gap: 0 }}>
      <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: 2, backgroundColor: rgba(fg, 0.18) }} />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={caps(21, rgba(fg, 0.75), 800, 0.14)}>{left}</span>
        <span style={{ ...caps(21, fg, 800, 0.14), fontVariantNumeric: "tabular-nums" }}>{page}</span>
      </div>
    </div>
  );
};

// ── Tapa ────────────────────────────────────────────────────────────────
const Cover: React.FC<{ props: MorningBriefV2Props }> = ({ props }) => {
  const ink = C.paperInk;
  const rows = props.index.slice(0, 5);
  return (
    <AbsoluteFill style={{ backgroundColor: C.paper }}>
      <Grain opacity={0.05} />
      <div style={{ position: "absolute", left: M, right: M, top: 56, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
          <Seal size={78} />
          <Wordmark size={36} color={ink} />
        </div>
        <span style={caps(20, C.paperMute, 800, 0.16)}>Edición de la mañana</span>
      </div>
      <div style={{ position: "absolute", left: M, right: M, top: 162 }}>
        <DoubleRule color={ink} />
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "18px 0", borderBottom: `1.5px solid ${rgba(ink, 0.9)}` }}>
          <span style={caps(21, ink, 800, 0.14)}>{props.dateLabel}</span>
          <span style={caps(21, ink, 700, 0.1)}>{props.weatherLine}</span>
        </div>
      </div>
      <div style={{ position: "absolute", left: M, right: M, top: 286, display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ fontFamily: `"${V2_FONT_SERIF}"`, fontWeight: 700, fontSize: 104, lineHeight: 0.98, letterSpacing: "-0.02em", color: ink }}>
          Lo que tenés que
          <br />
          saber <span style={{ fontStyle: "italic", color: C.red }}>hoy</span>
        </div>
      </div>
      <div style={{ position: "absolute", left: M, right: M, top: 520, display: "flex", flexDirection: "column" }}>
        {rows.map((row, i) => {
          const sec = sectionStyle(row.seccion);
          const t = fit({ text: row.titulo, maxWidth: INNER - 110, maxHeight: 76, min: 28, max: 35, weight: 750, lh: 1.08, stretch: "semi-condensed", maxLines: 2 });
          return (
            <div key={i} style={{ display: "flex", gap: 30, alignItems: "flex-start", padding: "18px 0 0", borderTop: `1.5px solid ${rgba(ink, i === 0 ? 0.9 : 0.16)}`, height: 144, overflow: "hidden" }}>
              <span style={{ width: 80, fontFamily: `"${V2_FONT_SERIF}"`, fontWeight: 700, fontSize: 64, lineHeight: 0.9, color: C.red, fontVariantNumeric: "lining-nums" }}>{i + 1}</span>
              <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 10 }}>
                <span style={caps(17, sec.accent === C.red ? C.red : C.blue, 800, 0.16)}>{sec.label}</span>
                <div style={{ ...display(t.fontSize, ink, 750), lineHeight: `${t.lineHeight}px` }}>
                  {t.lines.map((l, k) => (
                    <div key={k}>{l}</div>
                  ))}
                </div>
              </div>
            </div>
          );
        })}
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: FOOT, backgroundColor: C.ink, display: "flex", alignItems: "center", justifyContent: "space-between", padding: `0 ${M}px` }}>
        <span style={caps(22, C.white, 800, 0.12)}>Deslizá para leer cada noticia</span>
        <span style={{ ...caps(22, C.white, 800, 0.1), display: "flex", gap: 16, alignItems: "center" }}>
          {props.page}
          <span style={{ fontSize: 30, letterSpacing: 0 }}>→</span>
        </span>
      </div>
    </AbsoluteFill>
  );
};

// ── Noticia ─────────────────────────────────────────────────────────────
const News: React.FC<{ props: MorningBriefV2Props }> = ({ props }) => {
  const ink = C.paperInk;
  const sec = sectionStyle(props.seccion);
  const deck = props.deck ? fit({ text: props.deck, maxWidth: INNER - 27, maxHeight: 130, min: 27, max: 31, weight: 500, lh: 1.3, family: V2_FONT_SERIF, italic: true, maxLines: 3 }) : null;
  const headline = fit({ text: props.titulo, maxWidth: INNER, maxHeight: 340, min: 48, max: 80, weight: 850, lh: 1.02, stretch: "semi-condensed", maxLines: 4 });
  // La foto crece hasta donde empieza el texto: sin aire muerto abajo.
  const textH = headline.height + (deck ? deck.height + 22 : 0);
  const photoH = Math.max(560, Math.min(860, H - FOOT - 70 - textH - 34 - 58));
  const textTop = photoH + 58;
  return (
    <AbsoluteFill style={{ backgroundColor: C.paper }}>
      <div style={{ position: "absolute", left: 0, top: 0, width: W, height: photoH, overflow: "hidden", backgroundColor: C.ink }}>
        {props.assetFile ? <Img src={staticFile(props.assetFile)} style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : null}
        <AbsoluteFill style={{ background: `linear-gradient(180deg, ${rgba(C.ink, 0.55)} 0%, rgba(0,0,0,0) 28%)` }} />
      </div>
      <div style={{ position: "absolute", left: M, top: 48, display: "flex", alignItems: "center", gap: 14 }}>
        <Seal size={58} />
        <span style={caps(21, C.white, 800, 0.14)}>Lo que tenés que saber hoy</span>
      </div>
      <div
        style={{
          position: "absolute",
          left: M,
          top: photoH - 58,
          height: 116,
          display: "flex",
          alignItems: "center",
          gap: 22,
          padding: "0 30px 0 26px",
          backgroundColor: C.ink,
        }}
      >
        <span style={{ fontFamily: `"${V2_FONT_SERIF}"`, fontWeight: 700, fontSize: 76, lineHeight: 1, color: C.white }}>{props.number}</span>
        <span style={{ width: 2, height: 54, backgroundColor: rgba(C.white, 0.35) }} />
        <span style={caps(22, C.white, 800, 0.16)}>{sec.label}</span>
      </div>
      <div style={{ position: "absolute", left: M, right: M, top: textTop + 34, display: "flex", flexDirection: "column", gap: 22 }}>
        <div style={{ ...display(headline.fontSize, ink, 850), lineHeight: `${headline.lineHeight}px` }}>
          {headline.lines.map((l, i) => (
            <div key={i}>{l}</div>
          ))}
        </div>
        {deck ? (
          <div style={{ ...serif(deck.fontSize, C.paperMute), lineHeight: `${deck.lineHeight}px`, borderLeft: `5px solid ${sec.accent}`, paddingLeft: 22 }}>
            {deck.lines.map((l, i) => (
              <div key={i}>{l}</div>
            ))}
          </div>
        ) : null}
      </div>
      <Footer left="Nota completa en lavozriojana.com" page={props.page} />
    </AbsoluteFill>
  );
};

// ── Servicios ───────────────────────────────────────────────────────────
const Services: React.FC<{ props: MorningBriefV2Props }> = ({ props }) => (
  <AbsoluteFill style={{ backgroundColor: C.ink }}>
    <Grain opacity={0.05} />
    <div style={{ position: "absolute", left: M, right: M, top: 64, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
        <Seal size={72} />
        <Wordmark size={32} color={C.white} />
      </div>
      <span style={caps(20, rgba(C.white, 0.6), 800, 0.16)}>{props.dateLabel}</span>
    </div>
    <div style={{ position: "absolute", left: M, right: M, top: 170 }}>
      <DoubleRule color={rgba(C.white, 0.85)} />
    </div>
    <div style={{ position: "absolute", left: M, right: M, top: 214, fontFamily: `"${V2_FONT_SERIF}"`, fontWeight: 700, fontSize: 84, lineHeight: 1, letterSpacing: "-0.02em", color: C.white }}>
      Para organizar <span style={{ fontStyle: "italic", color: "#ff6b6b" }}>tu día</span>
    </div>
    <div style={{ position: "absolute", left: M, right: M, top: 352, display: "flex", flexDirection: "column" }}>
      {props.services.slice(0, 6).map((row, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: 24, minHeight: 148, borderTop: `1.5px solid ${rgba(C.white, i === 0 ? 0.6 : 0.16)}`, padding: "16px 0" }}>
          <span style={{ width: 250, ...caps(21, rgba(C.white, 0.6), 800, 0.14), whiteSpace: "normal", lineHeight: 1.25 }}>{row.label}</span>
          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 8 }}>
            <span style={{ ...display(48, C.white, 850), lineHeight: 1.05 }}>{row.value}</span>
            {row.note ? <span style={serif(26, rgba(C.white, 0.66))}>{row.note}</span> : null}
          </div>
        </div>
      ))}
    </div>
    <Footer left="Seguí @lavozriojana · todos los días a las 8" page={props.page} dark />
  </AbsoluteFill>
);

export const MorningBriefV2: React.FC<MorningBriefV2Props> = (props) => {
  const ready = useV2FontsReady();
  if (!ready) return <AbsoluteFill style={{ backgroundColor: C.paper }} />;
  if (props.slide === "cover") return <Cover props={props} />;
  if (props.slide === "services") return <Services props={props} />;
  return <News props={props} />;
};
