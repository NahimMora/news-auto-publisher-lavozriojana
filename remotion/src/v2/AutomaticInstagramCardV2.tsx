// AutomaticInstagramCardV2 — post 1080×1350 del Visual System V2.
//
// Cuatro composiciones elegidas por reglas (nunca al azar), todas con la
// misma retícula, firma y tipografía del Reel V2:
//   · papel   — foto horizontal/cuadrada, secciones de tono "papel": página
//               editorial clara, foto con margen, titular en tinta.
//   · tinta   — misma retícula sobre tinta, foto a sangre (policiales,
//               deportes, espectáculos y noticias urgentes).
//   · cintas  — foto vertical a sangre; el titular vive en cintas sólidas por
//               línea (legibilidad garantizada sin degradados).
//   · poster  — sin foto: campo de color de sección y titular protagonista.
// Props compatibles con AutomaticInstagramCardSchema (V1) + opcionales V2.
import React from "react";
import { AbsoluteFill, Img, staticFile } from "remotion";
import { z } from "zod";
import { Grain } from "../shared/Grain";
import { Headline, SectionLabel, Wordmark } from "./components";
import { Fitted, fit } from "./fit";
import { useV2FontsReady } from "./fonts";
import { Token, tokenize } from "./text";
import { C, IG, SectionStyle, TYPE, V2_FONT_SANS, V2_FONT_SERIF, rgba, sectionStyle } from "./tokens";

export const AUTOMATIC_IG_V2_W = IG.w;
export const AUTOMATIC_IG_V2_H = IG.h;

export const AutomaticInstagramCardV2Schema = z.object({
  titulo: z.string(),
  seccion: z.string(),
  assetFile: z.string().default(""),
  assetOrientation: z.enum(["landscape", "portrait", "square"]).optional(),
  highlightTerms: z.array(z.string()).default([]),
  locality: z.string().default(""),
  deck: z.string().default(""),
  // Aceptados por compatibilidad con el contrato V1; V2 no los usa.
  imageTreatment: z.string().default("auto"),
  publicationStyle: z.string().default("automatic"),
  // Opcionales V2.
  assetWidth: z.number().default(0),
  assetHeight: z.number().default(0),
  breaking: z.boolean().default(false),
  layout: z.enum(["auto", "papel", "tinta", "cintas", "poster"]).default("auto"),
});

export type AutomaticInstagramCardV2Props = z.infer<typeof AutomaticInstagramCardV2Schema>;

type Layout = "papel" | "tinta" | "cintas" | "poster";

const M = IG.margin;
const INNER_W = IG.w - M * 2;
const MAST_H = 116;
const FOOT_H = 84;

function aspectOf(props: AutomaticInstagramCardV2Props): number {
  if (props.assetWidth > 0 && props.assetHeight > 0) return props.assetWidth / props.assetHeight;
  if (props.assetOrientation === "portrait") return 0.8;
  if (props.assetOrientation === "square") return 1;
  return 1.6;
}

export function resolveCardLayout(props: AutomaticInstagramCardV2Props, style: SectionStyle): Layout {
  if (props.layout !== "auto") return props.assetFile || props.layout === "poster" ? props.layout : "poster";
  if (!props.assetFile) return "poster";
  if (aspectOf(props) <= 0.87) return "cintas";
  return style.tone === "ink" || props.breaking ? "tinta" : "papel";
}

const fitDeck = (text: string, width: number, size: number, maxLines: number): Fitted | null =>
  text
    ? fit({ text, maxWidth: width, maxHeight: maxLines * size * TYPE.deck.lh, min: size, max: size, weight: 500, lh: TYPE.deck.lh, family: V2_FONT_SERIF, italic: true, maxLines })
    : null;

const fitHeadline = (text: string, width: number, maxHeight: number, min: number = TYPE.cardHeadline.min, max: number = TYPE.cardHeadline.max, maxLines = 5) =>
  fit({
    text,
    maxWidth: width,
    maxHeight,
    min,
    max,
    weight: TYPE.cardHeadline.weight,
    lh: TYPE.cardHeadline.lh,
    stretch: TYPE.cardHeadline.stretch,
    tracking: TYPE.cardHeadline.tracking,
    maxLines,
  });

// ── Piezas comunes ──────────────────────────────────────────────────────
const Masthead: React.FC<{ style: SectionStyle; ink: boolean; locality: string }> = ({ style, ink, locality }) => {
  const color = ink ? C.white : C.paperInk;
  return (
    <div style={{ position: "absolute", left: M, right: M, top: 0, height: MAST_H, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
      <Wordmark size={30} sealSize={58} color={color} accent={style.accent} />
      <SectionLabel label={style.label} detail={locality} accent={style.accent} color={color} size={22} progress={1} />
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 2, backgroundColor: ink ? rgba(C.white, 0.22) : C.paperInk }} />
    </div>
  );
};

const Footer: React.FC<{ ink: boolean; band?: boolean }> = ({ ink, band }) => {
  const color = ink ? rgba(C.white, 0.82) : C.paperInk;
  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        bottom: 0,
        height: FOOT_H,
        padding: `0 ${M}px`,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        fontFamily: `"${V2_FONT_SANS}"`,
        fontWeight: 700,
        fontStretch: "semi-condensed",
        fontSize: 23,
        letterSpacing: "0.12em",
        color,
        backgroundColor: band ? C.ink : "transparent",
      }}
    >
      {band ? null : <div style={{ position: "absolute", left: M, right: M, top: 0, height: 1, backgroundColor: ink ? rgba(C.white, 0.22) : C.paperLine }} />}
      <span>LAVOZRIOJANA.COM</span>
      <span>@LAVOZRIOJANA</span>
    </div>
  );
};

const DeckBlock: React.FC<{ fitted: Fitted; color: string }> = ({ fitted, color }) => (
  <div style={{ fontFamily: `"${V2_FONT_SERIF}"`, fontStyle: "italic", fontWeight: 500, fontSize: fitted.fontSize, lineHeight: `${fitted.lineHeight}px`, color }}>
    {fitted.lines.map((l, i) => (
      <div key={i} style={{ whiteSpace: "nowrap" }}>
        {l}
      </div>
    ))}
  </div>
);

const StaticHeadline: React.FC<{ fitted: Fitted; tokens: Token[]; color: string; accent: string }> = ({ fitted, tokens, color, accent }) => (
  <Headline
    fitted={fitted}
    tokens={tokens}
    color={color}
    accent={accent}
    weight={TYPE.cardHeadline.weight}
    stretch={TYPE.cardHeadline.stretch}
    tracking={TYPE.cardHeadline.tracking}
    mode="none"
    start={0}
    stagger={0}
  />
);

// ── Papel / Tinta: misma retícula, dos tonos ────────────────────────────
const EditorialPage: React.FC<{ props: AutomaticInstagramCardV2Props; style: SectionStyle; ink: boolean; tokens: Token[] }> = ({ props, style, ink, tokens }) => {
  const aspect = aspectOf(props);
  const photoW = ink ? IG.w : INNER_W;
  const photoX = ink ? 0 : M;
  const photoTop = ink ? MAST_H : MAST_H + 28;
  const contentBottom = IG.h - FOOT_H - 30;
  const gap = 34;
  const kicker = 44;
  // La foto crece todo lo posible mientras el titular conserve un tamaño
  // protagonista (≥ 76 px); recién después se acepta el mínimo del sistema.
  // Recorte máximo de la foto: ~25 % sobre su proporción natural.
  const maxPhoto = Math.round(Math.max(460, Math.min(ink ? 740 : 700, (photoW / aspect) * 1.3)));
  let deck = fitDeck(props.deck, INNER_W, TYPE.deck.size, 3);
  let photoH = maxPhoto;
  let headline = null as Fitted | null;
  let room = 0;
  const search = (minSize: number) => {
    for (let h = maxPhoto; h >= 380; h -= 20) {
      const deckH = deck ? deck.height + 22 : 0;
      const r = contentBottom - (photoTop + h + gap + kicker) - deckH;
      const candidate = fitHeadline(props.titulo, INNER_W, r, minSize, 104);
      if (!candidate.overflow) {
        photoH = h;
        room = r;
        return candidate;
      }
    }
    return null;
  };
  headline = search(76) ?? search(TYPE.cardHeadline.min);
  if (!headline && deck) {
    deck = null; // sin lugar: se prioriza el titular sobre la bajada
    headline = search(TYPE.cardHeadline.min);
  }
  if (!headline) {
    photoH = 380;
    room = contentBottom - (photoTop + photoH + gap + kicker);
    headline = fitHeadline(props.titulo, INNER_W, room, 40, 60, 6);
  }
  // Aire sobrante: una parte separa foto y texto, el resto queda abajo.
  const spare = Math.max(0, room - headline.height);
  const textTop = photoTop + photoH + gap + Math.min(48, spare * 0.5);
  const textColor = ink ? C.white : C.paperInk;
  return (
    <AbsoluteFill style={{ backgroundColor: ink ? C.ink : C.paper }}>
      <Masthead style={style} ink={ink} locality="" />
      <div style={{ position: "absolute", left: photoX, top: photoTop, width: photoW, height: photoH, overflow: "hidden", backgroundColor: C.ink2 }}>
        <Img src={staticFile(props.assetFile)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      </div>
      {/* Regla de acento: corte editorial entre imagen y texto */}
      <div style={{ position: "absolute", left: M, top: photoTop + photoH - 4, width: 180, height: 8, backgroundColor: style.accent }} />
      <div style={{ position: "absolute", left: M, top: textTop, width: INNER_W }}>
        <div style={{ height: kicker, display: "flex", alignItems: "flex-start" }}>
          {props.locality ? (
            <SectionLabel label={props.locality} accent={style.accent} color={ink ? rgba(C.white, 0.8) : C.paperMute} size={21} progress={1} />
          ) : (
            <SectionLabel label={style.label} accent={style.accent} color={ink ? rgba(C.white, 0.8) : C.paperMute} size={21} progress={1} />
          )}
        </div>
        <StaticHeadline fitted={headline} tokens={tokens} color={textColor} accent={style.accent} />
        {deck ? (
          <div style={{ marginTop: 22 }}>
            <DeckBlock fitted={deck} color={ink ? rgba(C.white, 0.78) : C.paperMute} />
          </div>
        ) : null}
      </div>
      <Footer ink={ink} />
      <Grain opacity={ink ? 0.04 : 0.05} />
    </AbsoluteFill>
  );
};

// ── Cintas: foto vertical a sangre ──────────────────────────────────────
const Ribbons: React.FC<{ props: AutomaticInstagramCardV2Props; style: SectionStyle; tokens: Token[] }> = ({ props, style, tokens }) => {
  const padX = 18;
  const maxW = INNER_W - padX * 2 - 40;
  const headline = fitHeadline(props.titulo, maxW, 5 * 80, 50, 80, 5);
  const deck = fitDeck(props.deck, maxW, 29, 2);
  const lines = headline.lines;
  let cursor = 0;
  const tokenLines = lines.map((line) => {
    const n = line.split(/\s+/).length;
    const slice = tokens.slice(cursor, cursor + n);
    cursor += n;
    return slice;
  });
  return (
    <AbsoluteFill style={{ backgroundColor: C.ink }}>
      <Img src={staticFile(props.assetFile)} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover" }} />
      <div style={{ position: "absolute", left: M - 8, top: 40, padding: "8px 18px 8px 8px", backgroundColor: C.ink }}>
        <Wordmark size={26} sealSize={50} accent={style.accent} />
      </div>
      <div style={{ position: "absolute", left: M - padX, bottom: FOOT_H + 34, display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 6 }}>
        <div style={{ marginBottom: 8 }}>
          <SectionLabel label={style.label} detail={props.locality} accent={style.field} color={C.white} size={22} progress={1} boxed />
        </div>
        {tokenLines.map((line, i) => (
          <div
            key={i}
            style={{
              backgroundColor: C.ink,
              padding: `${headline.fontSize * 0.08}px ${padX}px ${headline.fontSize * 0.12}px`,
              fontFamily: `"${V2_FONT_SANS}"`,
              fontWeight: TYPE.cardHeadline.weight,
              fontStretch: TYPE.cardHeadline.stretch,
              fontSize: headline.fontSize,
              lineHeight: `${headline.lineHeight}px`,
              letterSpacing: `${TYPE.cardHeadline.tracking}em`,
              color: C.white,
              whiteSpace: "nowrap",
            }}
          >
            {line.map((t, j) => (
              <React.Fragment key={j}>
                {j > 0 ? " " : ""}
                <span style={t.highlighted ? { backgroundColor: style.accent, boxShadow: `0.12em 0 0 ${style.accent}, -0.12em 0 0 ${style.accent}` } : undefined}>{t.value}</span>
              </React.Fragment>
            ))}
          </div>
        ))}
        {deck ? (
          <div style={{ marginTop: 8, backgroundColor: C.paper, padding: `10px ${padX}px 12px` }}>
            <DeckBlock fitted={deck} color={C.paperInk} />
          </div>
        ) : null}
      </div>
      <Footer ink band />
    </AbsoluteFill>
  );
};

// ── Póster: sin fotografía ──────────────────────────────────────────────
const Poster: React.FC<{ props: AutomaticInstagramCardV2Props; style: SectionStyle; tokens: Token[] }> = ({ props, style, tokens }) => {
  const deck = fitDeck(props.deck, INNER_W, 34, 3);
  const top = MAST_H + 120;
  const room = IG.h - FOOT_H - 60 - top - (deck ? deck.height + 30 : 0);
  const headline = fitHeadline(props.titulo, INNER_W, room, 64, 136, 7);
  return (
    <AbsoluteFill style={{ backgroundColor: style.field }}>
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <div key={i} style={{ position: "absolute", left: M, right: M, top: MAST_H + 60 + i * 180, height: 1, backgroundColor: rgba(C.white, 0.12) }} />
      ))}
      <Masthead style={{ ...style, accent: style.field === C.red ? C.white : C.red }} ink locality={props.locality} />
      <div style={{ position: "absolute", left: M, width: INNER_W, bottom: FOOT_H + 50 }}>
        <div style={{ width: 120, height: 10, backgroundColor: C.white, marginBottom: 34 }} />
        <StaticHeadline fitted={headline} tokens={tokens} color={C.white} accent={style.field === C.red ? C.ink : C.red} />
        {deck ? (
          <div style={{ marginTop: 30 }}>
            <DeckBlock fitted={deck} color={rgba(C.white, 0.86)} />
          </div>
        ) : null}
      </div>
      <Footer ink />
      <Grain opacity={0.05} />
    </AbsoluteFill>
  );
};

export const AutomaticInstagramCardV2: React.FC<AutomaticInstagramCardV2Props> = (props) => {
  const ready = useV2FontsReady();
  const style = sectionStyle(props.seccion);
  if (!ready) return <AbsoluteFill style={{ backgroundColor: C.paper }} />;
  const tokens = tokenize(props.titulo, props.highlightTerms, 1);
  const layout = resolveCardLayout(props, style);
  if (layout === "poster") return <Poster props={props} style={style} tokens={tokens} />;
  if (layout === "cintas") return <Ribbons props={props} style={style} tokens={tokens} />;
  return <EditorialPage props={props} style={style} ink={layout === "tinta"} tokens={tokens} />;
};
