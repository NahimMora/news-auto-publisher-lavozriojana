// AutomaticInstagramCardV2 — post 1080×1350 del Visual System V2
// (revisión 2026-10-18: "portada", más elementos y menos aire vacío).
//
//   · Foto a sangre arriba que se funde con el fondo; el titular la monta en
//     el borde (portada de revista, no tarjeta).
//   · Pestaña de marca (sello + LA VOZ RIOJANA) y pestaña de sección
//     (+ localidad) sobre la foto.
//   · Franja de acento a la izquierda, bajada con barra, trama de puntos y la
//     sección como marca de agua detrás del texto.
//   · Banda de pie con el color de la sección: "Nota completa en
//     lavozriojana.com →", fecha y @lavozriojana.
//
// Variantes por reglas (nunca al azar): foto horizontal/cuadrada → foto
// arriba; foto vertical → foto a pantalla completa con el texto sobre un
// velo; sin foto → póster en el color de la sección. Dos tonos: tinta
// (policiales, deportes, espectáculos, urgentes) y papel (el resto).
// Props compatibles con AutomaticInstagramCardSchema (V1) + opcionales V2.
import React from "react";
import { AbsoluteFill, Img, staticFile } from "remotion";
import { z } from "zod";
import { Grain } from "../shared/Grain";
import { Headline } from "./components";
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
  // "papel"/"tinta" fuerzan el tono; "cintas" fuerza foto completa.
  layout: z.enum(["auto", "papel", "tinta", "cintas", "poster"]).default("auto"),
  dateLabel: z.string().default(""),
});

export type AutomaticInstagramCardV2Props = z.infer<typeof AutomaticInstagramCardV2Schema>;

type Layout = "papel" | "tinta" | "cintas" | "poster";

const M = IG.margin; // 64
const INNER_W = IG.w - M * 2;
const STRIPE = 12;
const FOOT_H = 92;

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
    ? fit({ text, maxWidth: width, maxHeight: maxLines * size * TYPE.deck.lh, min: Math.max(26, size - 4), max: size, weight: 500, lh: TYPE.deck.lh, family: V2_FONT_SERIF, italic: true, maxLines })
    : null;

const fitHeadline = (text: string, width: number, maxHeight: number, min: number, max: number, maxLines = 5) =>
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

const caps: React.CSSProperties = {
  fontFamily: `"${V2_FONT_SANS}"`,
  fontWeight: 800,
  fontStretch: "semi-condensed",
  letterSpacing: "0.14em",
  textTransform: "uppercase",
  whiteSpace: "nowrap",
  lineHeight: 1,
};

// ── Piezas comunes ──────────────────────────────────────────────────────
// Pestaña de marca: sello + wordmark sobre tinta, pegada al borde izquierdo.
const BrandTab: React.FC<{ accent: string }> = ({ accent }) => (
  <div style={{ position: "absolute", left: 0, top: 44, height: 76, display: "flex", alignItems: "center", gap: 16, padding: `0 26px 0 ${M - 16}px`, backgroundColor: C.ink }}>
    <Img src={staticFile("logo.png")} style={{ width: 56, height: 56, objectFit: "contain" }} />
    <div style={{ display: "flex", alignItems: "baseline", gap: 9, fontFamily: `"${V2_FONT_SANS}"`, fontWeight: 900, fontStretch: "condensed", fontSize: 31, letterSpacing: "0.04em", color: C.white, lineHeight: 1 }}>
      <span>LA VOZ</span>
      <span>RIOJANA</span>
      <span style={{ width: 9, height: 9, backgroundColor: accent, alignSelf: "center" }} />
    </div>
  </div>
);

// Pestaña de sección (+ localidad) en el color de la sección, borde derecho.
const SectionTab: React.FC<{ style: SectionStyle; locality: string; fill?: string }> = ({ style, locality, fill }) => (
  <div style={{ position: "absolute", right: 0, top: 54, height: 56, display: "flex", alignItems: "center", gap: 14, padding: `0 ${M - 8}px 0 24px`, backgroundColor: fill ?? style.field, ...caps, fontSize: 22, color: C.white }}>
    <span>{style.label}</span>
    {locality ? (
      <>
        <span style={{ width: 2, height: 22, backgroundColor: rgba(C.white, 0.55) }} />
        <span style={{ fontWeight: 600, letterSpacing: "0.1em" }}>{locality}</span>
      </>
    ) : null}
  </div>
);

// Banda de pie: llamado a la nota + fecha + cuenta.
const FooterBand: React.FC<{ color: string; dateLabel: string }> = ({ color, dateLabel }) => (
  <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: FOOT_H, backgroundColor: color, display: "flex", alignItems: "center", justifyContent: "space-between", padding: `0 ${M}px 0 ${M}px` }}>
    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
      <span style={{ ...caps, fontSize: 21, color: rgba(C.white, 0.78) }}>Nota completa en</span>
      <span style={{ ...caps, fontSize: 23, color: C.white }}>lavozriojana.com</span>
      <span style={{ ...caps, fontSize: 26, color: C.white, letterSpacing: 0 }}>→</span>
    </div>
    <span style={{ ...caps, fontSize: 19, color: rgba(C.white, 0.78) }}>{dateLabel || "@lavozriojana"}</span>
  </div>
);

const LeftStripe: React.FC<{ color: string; top?: number }> = ({ color, top = 0 }) => (
  <div style={{ position: "absolute", left: 0, top, bottom: FOOT_H, width: STRIPE, backgroundColor: color }} />
);

// Trama de puntos (referencia a la impresión), desvanecida hacia arriba.
const Halftone: React.FC<{ color: string; top: number; height: number; opacity?: number }> = ({ color, top, height, opacity = 1 }) => (
  <div
    style={{
      position: "absolute",
      right: 0,
      top,
      width: IG.w * 0.55,
      height,
      backgroundImage: `radial-gradient(${color} 1.7px, transparent 2px)`,
      backgroundSize: "15px 15px",
      maskImage: "linear-gradient(200deg, black 0%, transparent 70%)",
      WebkitMaskImage: "linear-gradient(200deg, black 0%, transparent 70%)",
      opacity,
    }}
  />
);

const Watermark: React.FC<{ label: string; bottom: number; color: string }> = ({ label, bottom, color }) => {
  const text = label.toLocaleUpperCase("es-AR");
  const fitted = fit({ text, maxWidth: INNER_W + 40, maxHeight: 220, min: 80, max: 220, weight: 900, lh: 1, stretch: "condensed", tracking: -0.01, maxLines: 1 });
  return (
    <div
      style={{
        position: "absolute",
        left: M - 6,
        bottom,
        fontFamily: `"${V2_FONT_SANS}"`,
        fontWeight: 900,
        fontStretch: "condensed",
        fontSize: fitted.fontSize,
        lineHeight: 0.8,
        letterSpacing: "-0.01em",
        color: "transparent",
        WebkitTextStroke: `2px ${color}`,
        whiteSpace: "nowrap",
      }}
    >
      {text}
    </div>
  );
};

const DeckBlock: React.FC<{ fitted: Fitted; color: string; accent: string }> = ({ fitted, color, accent }) => (
  <div style={{ display: "flex", gap: 22 }}>
    <div style={{ width: 6, backgroundColor: accent, flexShrink: 0 }} />
    <div style={{ fontFamily: `"${V2_FONT_SERIF}"`, fontStyle: "italic", fontWeight: 500, fontSize: fitted.fontSize, lineHeight: `${fitted.lineHeight}px`, color }}>
      {fitted.lines.map((l, i) => (
        <div key={i} style={{ whiteSpace: "nowrap" }}>
          {l}
        </div>
      ))}
    </div>
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

interface TextPlan {
  headline: Fitted;
  deck: Fitted | null;
  height: number;
}

const DECK_GAP = 26;

// Titular protagonista: primero con bajada y tamaño grande; si no entra,
// se achica; recién al final se omite la bajada (nunca se corta el titular).
function planText(title: string, deckText: string, room: number, width: number, maxSize = 96): TextPlan {
  const deck3 = fitDeck(deckText, width - 28, TYPE.deck.size, 3);
  const deck2 = fitDeck(deckText, width - 28, TYPE.deck.size, 2);
  const attempts: [Fitted | null, number][] = [
    [deck3, 72],
    [deck2, 64],
    [deck2, TYPE.cardHeadline.min],
    [null, TYPE.cardHeadline.min],
  ];
  for (const [deck, min] of attempts) {
    const deckH = deck ? deck.height + DECK_GAP : 0;
    const headline = fitHeadline(title, width, room - deckH, min, maxSize, 5);
    if (!headline.overflow) return { headline, deck, height: headline.height + deckH };
  }
  const headline = fitHeadline(title, width, room, 40, 60, 6);
  return { headline, deck: null, height: headline.height };
}

// ── Foto arriba (papel / tinta) ─────────────────────────────────────────
const PhotoTop: React.FC<{ props: AutomaticInstagramCardV2Props; style: SectionStyle; ink: boolean; tokens: Token[] }> = ({ props, style, ink, tokens }) => {
  const bg = ink ? C.ink : C.paper;
  const textColor = ink ? C.white : C.paperInk;
  const aspect = aspectOf(props);
  const textW = INNER_W;
  const textBottom = IG.h - FOOT_H - 40;
  const overlap = 96; // el titular monta el borde inferior de la foto
  // Recorte máximo de la foto: ~40 % del ancho sobre su proporción natural.
  const natural = IG.w / aspect;
  const maxPhoto = Math.round(Math.min(1000, Math.max(560, natural * 1.65)));
  // El titular manda: se busca la foto más alta que deja un titular ≥ 70 px.
  let plan: TextPlan | null = null;
  for (let h = Math.min(maxPhoto, 820); h >= 520; h -= 20) {
    const candidate = planText(props.titulo, props.deck, textBottom - (h - overlap), textW);
    if (candidate.headline.fontSize >= 70 || h === 520) {
      plan = candidate;
      break;
    }
  }
  if (!plan) plan = planText(props.titulo, props.deck, textBottom - (520 - overlap), textW);
  // El texto queda anclado abajo y la foto crece hasta alcanzarlo: sin
  // huecos con titulares cortos.
  const textTop = textBottom - plan.height;
  const photoH = Math.min(maxPhoto, textTop + overlap);
  const fadeFrom = photoH - overlap - 170;
  return (
    <AbsoluteFill style={{ backgroundColor: bg }}>
      <Halftone color={ink ? rgba(C.white, 0.09) : rgba(C.paperInk, 0.1)} top={photoH} height={Math.max(0, IG.h - photoH - FOOT_H)} />
      <div style={{ position: "absolute", left: 0, top: 0, width: IG.w, height: photoH, overflow: "hidden", backgroundColor: C.ink2 }}>
        <Img src={staticFile(props.assetFile)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      </div>
      {/* Fundido de la foto hacia el fondo, para que el titular la monte */}
      <div style={{ position: "absolute", left: 0, top: fadeFrom, width: IG.w, height: photoH - fadeFrom + 2, background: `linear-gradient(180deg, ${rgba(bg, 0)} 0%, ${rgba(bg, 0.72)} 52%, ${rgba(bg, 0.97)} 86%, ${bg} 100%)` }} />
      <BrandTab accent={style.accent} />
      <SectionTab style={style} locality={props.locality} />
      <LeftStripe color={style.accent} top={photoH - overlap - 10} />
      <div style={{ position: "absolute", left: M, top: textTop, width: textW }}>
        <StaticHeadline fitted={plan.headline} tokens={tokens} color={textColor} accent={style.accent} />
        {plan.deck ? (
          <div style={{ marginTop: DECK_GAP }}>
            <DeckBlock fitted={plan.deck} color={ink ? rgba(C.white, 0.8) : C.paperMute} accent={style.accent} />
          </div>
        ) : null}
      </div>
      <FooterBand color={ink ? style.field : C.ink} dateLabel={props.dateLabel} />
      <Grain opacity={ink ? 0.04 : 0.05} />
    </AbsoluteFill>
  );
};

// ── Foto vertical a pantalla completa ───────────────────────────────────
const FullPhoto: React.FC<{ props: AutomaticInstagramCardV2Props; style: SectionStyle; tokens: Token[] }> = ({ props, style, tokens }) => {
  const textBottom = IG.h - FOOT_H - 44;
  const plan = planText(props.titulo, props.deck, 560, INNER_W, 88);
  const textTop = textBottom - plan.height;
  const veilTop = textTop - 300;
  return (
    <AbsoluteFill style={{ backgroundColor: C.ink }}>
      <Img src={staticFile(props.assetFile)} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover" }} />
      <div style={{ position: "absolute", left: 0, top: 0, width: IG.w, height: 260, background: `linear-gradient(180deg, ${rgba(C.ink, 0.55)} 0%, ${rgba(C.ink, 0)} 100%)` }} />
      <div style={{ position: "absolute", left: 0, top: veilTop, width: IG.w, bottom: 0, background: `linear-gradient(180deg, ${rgba(C.ink, 0)} 0%, ${rgba(C.ink, 0.78)} 32%, ${rgba(C.ink, 0.94)} 62%, ${C.ink} 100%)` }} />
      <BrandTab accent={style.accent} />
      <SectionTab style={style} locality={props.locality} />
      <LeftStripe color={style.accent} top={textTop - 24} />
      <div style={{ position: "absolute", left: M, top: textTop, width: INNER_W }}>
        <StaticHeadline fitted={plan.headline} tokens={tokens} color={C.white} accent={style.accent} />
        {plan.deck ? (
          <div style={{ marginTop: DECK_GAP }}>
            <DeckBlock fitted={plan.deck} color={rgba(C.white, 0.84)} accent={style.accent} />
          </div>
        ) : null}
      </div>
      <FooterBand color={style.field} dateLabel={props.dateLabel} />
      <Grain opacity={0.04} />
    </AbsoluteFill>
  );
};

// ── Póster: sin fotografía ──────────────────────────────────────────────
const Poster: React.FC<{ props: AutomaticInstagramCardV2Props; style: SectionStyle; tokens: Token[] }> = ({ props, style, tokens }) => {
  const top = 200;
  const textBottom = IG.h - FOOT_H - 60;
  const plan = planText(props.titulo, props.deck, textBottom - top, INNER_W, 132);
  const textTop = Math.max(top, textBottom - plan.height);
  const boxAccent = style.field === C.red ? C.ink : C.red;
  return (
    <AbsoluteFill style={{ backgroundColor: style.field }}>
      <AbsoluteFill style={{ background: `radial-gradient(120% 80% at 85% 10%, ${rgba(C.white, 0.12)} 0%, ${rgba(C.white, 0)} 60%)` }} />
      <Halftone color={rgba(C.white, 0.16)} top={150} height={520} />
      <Watermark label={style.label} bottom={IG.h - 150 - 200} color={rgba(C.white, 0.12)} />
      <BrandTab accent={style.field === C.red ? C.white : C.red} />
      <SectionTab style={style} locality={props.locality} fill={C.ink} />
      <div style={{ position: "absolute", left: M, top: textTop - 44, width: 120, height: 10, backgroundColor: C.white }} />
      <div style={{ position: "absolute", left: M, top: textTop, width: INNER_W }}>
        <StaticHeadline fitted={plan.headline} tokens={tokens} color={C.white} accent={boxAccent} />
        {plan.deck ? (
          <div style={{ marginTop: DECK_GAP }}>
            <DeckBlock fitted={plan.deck} color={rgba(C.white, 0.9)} accent={C.white} />
          </div>
        ) : null}
      </div>
      <FooterBand color={C.ink} dateLabel={props.dateLabel} />
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
  if (layout === "cintas") return <FullPhoto props={props} style={style} tokens={tokens} />;
  return <PhotoTop props={props} style={style} ink={layout === "tinta"} tokens={tokens} />;
};
