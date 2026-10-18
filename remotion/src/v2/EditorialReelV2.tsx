// EditorialReelV2 — Reel 1080×1920 del Visual System V2 (revisión 2026-10-18).
//
// Una sola composición estable desde el primer cuadro: el titular entra UNA
// vez y queda fijo durante todo el video (sin hook que se borra y vuelve).
//
//   · Encabezado de marca (sello + wordmark + pestaña de sección) y regla
//     con barra de progreso.
//   · Titular con caja de destaque.
//   · Video protagonista a todo el ancho (horizontales/cuadrados), con su
//     crédito ("VIDEO: X / @usuario", "VIDEO: INFOBAE").
//   · Bajada en serif (primera oración del caption) y llamado a la nota.
//   · Fondo: el mismo material desenfocado + trama de puntos + la sección
//     como marca de agua: textura en lugar de vacío.
//
// Todo el texto propio vive entre y=330 y y=1540: entra en el recorte 4:5
// del feed (y 285–1635) y en la zona segura de pantalla completa (la UI de
// Instagram cubre ~380 px abajo y la columna de botones a la derecha).
//
// Verticales: video a pantalla completa (cover sólo si es ~9:16), titular
// compacto arriba sobre un velo, crédito abajo. Sin media: póster
// tipográfico. Con `still` la composición se pinta en su estado final: es
// la misma pieza que se usa como portada (ReelCoverV2).
import React from "react";
import { Video } from "@remotion/media";
import { AbsoluteFill, Img, Sequence, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { z } from "zod";
import { Deck, Headline, Rule, Wordmark, maskInset } from "./components";
import { Fitted, fit } from "./fit";
import { useV2FontsReady } from "./fonts";
import { EASE, SPRING, clamp, mix, p, sp } from "./motion";
import { displayTitle, tokenize } from "./text";
import { C, REEL, SectionStyle, V2_FONT_SANS, V2_FONT_SERIF, rgba, sectionStyle } from "./tokens";
import { Grain } from "../shared/Grain";

export const EditorialReelV2Schema = z.object({
  titulo: z.string(),
  seccion: z.string(),
  assetType: z.enum(["video", "image", "none"]),
  assetFile: z.string(),
  kenBurnsVariant: z.number().default(0),
  durationInFrames: z.number(),
  highlightTerms: z.array(z.string()).optional().default([]),
  // Opcionales V2 (el pipeline puede omitirlos):
  assetWidth: z.number().default(0),
  assetHeight: z.number().default(0),
  locality: z.string().default(""),
  breaking: z.boolean().default(false),
  // Compatibilidad con el contrato anterior; ya no hay hooks alternativos.
  hookStyle: z.enum(["auto", "cinematic_editorial"]).default("auto"),
  deck: z.string().default(""),
  credit: z.string().default(""),
  // Portada: estado final, sin animación.
  still: z.boolean().default(false),
});

export type EditorialReelV2Props = z.infer<typeof EditorialReelV2Schema>;

export const REEL_V2_OUTRO_FRAMES = REEL.outroFrames;

const LEFT = REEL.safe.left; // 64
const RIGHT = REEL.safe.right; // 940
const CONTENT_W = RIGHT - LEFT; // 876
const TOP = 330; // dentro del recorte 4:5 del feed (y 285–1635) con margen
const BOTTOM = REEL.safe.bottom; // 1540
const HEADER_H = 64;
const RULE_Y = TOP + HEADER_H + 14;
const TITLE_Y = RULE_Y + 34;

interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

type Kind = "stacked" | "vertical" | "poster";

interface ReelLayout {
  kind: Kind;
  title: Fitted;
  media: Rect;
  cover: boolean;
  deck: Fitted | null;
  deckY: number;
  creditY: number;
  ctaY: number | null;
}

const fitTitle = (text: string, maxHeight: number, min: number, max: number, maxLines: number) =>
  fit({
    text,
    maxWidth: CONTENT_W,
    maxHeight,
    min,
    max,
    weight: 800,
    lh: 1.0,
    stretch: "semi-condensed",
    tracking: -0.01,
    maxLines,
  });

const DECK_SIZE = 34;
const fitDeckText = (text: string, maxLines: number): Fitted | null =>
  text
    ? fit({
        text,
        maxWidth: CONTENT_W - 30,
        maxHeight: maxLines * DECK_SIZE * 1.3,
        min: 30,
        max: DECK_SIZE,
        weight: 500,
        lh: 1.3,
        family: V2_FONT_SERIF,
        italic: true,
        maxLines,
      })
    : null;

function computeLayout(props: EditorialReelV2Props, title: string, hasMedia: boolean): ReelLayout {
  const aspect = props.assetWidth > 0 && props.assetHeight > 0 ? props.assetWidth / props.assetHeight : 16 / 9;

  if (!hasMedia) {
    const t = fitTitle(title, 620, 72, 118, 6);
    const deck = fitDeckText(props.deck, 4);
    return { kind: "poster", title: t, media: { x: 0, y: 0, w: 0, h: 0 }, cover: false, deck, deckY: 0, creditY: 0, ctaY: null };
  }

  if (aspect < 0.85) {
    // Vertical: el video manda; el titular compacto vive arriba sobre un velo.
    const target = REEL.w / REEL.h;
    const cover = Math.abs(aspect - target) / target < 0.04;
    let rw = REEL.w;
    let rh = rw / aspect;
    if (rh > REEL.h) {
      rh = REEL.h;
      rw = rh * aspect;
    }
    const media = cover ? { x: 0, y: 0, w: REEL.w, h: REEL.h } : { x: (REEL.w - rw) / 2, y: (REEL.h - rh) / 2, w: rw, h: rh };
    const t = fitTitle(title, 3 * 70, 50, 70, 3);
    return { kind: "vertical", title: t, media, cover, deck: null, deckY: 0, creditY: BOTTOM - 46, ctaY: null };
  }

  // Horizontal / cuadrado: titular arriba, video a todo el ancho, bajada.
  let t = fitTitle(title, 4 * 86, 58, 86, 4);
  let deck = fitDeckText(props.deck, 3);
  const creditH = props.credit ? 52 : 0;
  const gapTitle = 40;
  const gapDeck = 30;
  const mediaTop = () => TITLE_Y + t.height + gapTitle;
  const deckBlock = () => (deck ? deck.height + gapDeck : 0);
  let rh = Math.min(REEL.w / aspect, 860);
  let available = BOTTOM - mediaTop() - creditH - deckBlock();
  if (available < 420 && deck) {
    deck = fitDeckText(props.deck, 2);
    available = BOTTOM - mediaTop() - creditH - deckBlock();
  }
  if (available < 420) {
    t = fitTitle(title, 3 * 70, 52, 70, 3);
    available = BOTTOM - mediaTop() - creditH - deckBlock();
  }
  if (available < 380) {
    deck = null;
    available = BOTTOM - mediaTop() - creditH;
  }
  rh = Math.min(rh, available);
  let rw = rh * aspect;
  if (rw > REEL.w) {
    rw = REEL.w;
    rh = rw / aspect;
  }
  const spare = available - rh;
  if (spare > 120) {
    const bigger = fitTitle(title, t.height + spare * 0.6, 58, 104, 5);
    if (!bigger.overflow && bigger.fontSize > t.fontSize) t = bigger;
  }
  const media = { x: (REEL.w - rw) / 2, y: mediaTop(), w: rw, h: rh };
  const creditY = media.y + media.h + 18;
  const deckY = creditY + (creditH ? creditH - 4 : 18);
  const end = deck ? deckY + deck.height : creditY + creditH;
  const ctaY = BOTTOM - end >= 86 ? BOTTOM - 40 : null;
  return { kind: "stacked", title: t, media, cover: false, deck, deckY, creditY, ctaY };
}

// ── Fondo: material desenfocado + trama + marca de agua de sección ──────
const Backdrop: React.FC<{ props: EditorialReelV2Props; style: SectionStyle; hasMedia: boolean; reveal: number }> = ({ props, style, hasMedia, reveal }) => {
  const q = 4; // se pinta a 1/4 de resolución: el desenfoque cuesta 16× menos
  const inner: React.CSSProperties = {
    position: "absolute",
    inset: 0,
    width: "100%",
    height: "100%",
    filter: "blur(10px) brightness(0.62) saturate(1.15)",
    transform: "scale(1.15)",
  };
  return (
    <AbsoluteFill style={{ backgroundColor: C.ink, overflow: "hidden" }}>
      {hasMedia ? (
        <div style={{ position: "absolute", left: 0, top: 0, width: REEL.w / q, height: REEL.h / q, transform: `scale(${q})`, transformOrigin: "0 0", overflow: "hidden", opacity: mix(reveal, 0.55, 1) }}>
          {props.assetType === "video" && !props.still ? (
            <Video src={staticFile(props.assetFile)} muted objectFit="cover" style={inner} />
          ) : (
            <Img src={staticFile(props.assetFile)} style={{ ...inner, objectFit: "cover" }} />
          )}
        </div>
      ) : null}
      {/* Velo de tinta con el color de sección: arriba más denso (texto),
          al centro deja respirar el material, abajo vuelve a cerrar. */}
      <AbsoluteFill
        style={{
          background: `linear-gradient(180deg, ${rgba(C.ink, 0.72)} 0%, ${rgba(C.ink, 0.62)} 34%, ${rgba(C.ink, 0.5)} 56%, ${rgba(C.ink, 0.82)} 82%, ${rgba(C.ink, 0.94)} 100%)`,
        }}
      />
      <AbsoluteFill style={{ backgroundColor: rgba(style.field, 0.16), mixBlendMode: "color" }} />
      {/* Trama de puntos (referencia a la impresión) */}
      <AbsoluteFill
        style={{
          backgroundImage: `radial-gradient(${rgba(C.white, 0.11)} 1.6px, transparent 1.9px)`,
          backgroundSize: "14px 14px",
          maskImage: "linear-gradient(180deg, transparent 0%, black 30%, black 70%, transparent 100%)",
          WebkitMaskImage: "linear-gradient(180deg, transparent 0%, black 30%, black 70%, transparent 100%)",
          opacity: 0.55,
        }}
      />
      {/* Franja de color de sección a la izquierda */}
      <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 12, backgroundColor: style.accent, transform: `scaleY(${reveal})`, transformOrigin: "50% 0%" }} />
    </AbsoluteFill>
  );
};

const Watermark: React.FC<{ label: string; y: number }> = ({ label, y }) => {
  const text = label.toLocaleUpperCase("es-AR");
  const fitted = fit({ text, maxWidth: REEL.w - LEFT * 2, maxHeight: 250, min: 90, max: 250, weight: 900, lh: 1, stretch: "condensed", tracking: -0.01, maxLines: 1 });
  return (
    <div
      style={{
        position: "absolute",
        left: LEFT,
        top: y,
        fontFamily: `"${V2_FONT_SANS}"`,
        fontWeight: 900,
        fontStretch: "condensed",
        fontSize: fitted.fontSize,
        lineHeight: 1,
        letterSpacing: "-0.01em",
        color: "transparent",
        WebkitTextStroke: `2px ${rgba(C.white, 0.1)}`,
        whiteSpace: "nowrap",
      }}
    >
      {text}
    </div>
  );
};

// ── Encabezado: sello + wordmark a la izquierda, pestaña de sección a la
// derecha, regla con progreso debajo.
const Header: React.FC<{ style: SectionStyle; locality: string; reveal: number; progress: number }> = ({ style, locality, reveal, progress }) => (
  <>
    <div style={{ position: "absolute", left: LEFT, top: TOP, width: CONTENT_W, height: HEADER_H, display: "flex", alignItems: "center", justifyContent: "space-between", clipPath: maskInset(reveal, "left") }}>
      <Wordmark size={30} sealSize={58} accent={style.accent} />
      <div
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 12,
          height: 46,
          padding: "0 18px",
          backgroundColor: style.field,
          fontFamily: `"${V2_FONT_SANS}"`,
          fontWeight: 800,
          fontStretch: "semi-condensed",
          fontSize: 22,
          letterSpacing: "0.16em",
          textTransform: "uppercase",
          color: C.white,
          whiteSpace: "nowrap",
        }}
      >
        <span>{style.label}</span>
        {locality ? (
          <>
            <span style={{ width: 2, height: 20, backgroundColor: rgba(C.white, 0.55) }} />
            <span style={{ fontWeight: 600, letterSpacing: "0.1em" }}>{locality}</span>
          </>
        ) : null}
      </div>
    </div>
    <div style={{ position: "absolute", left: LEFT, top: RULE_Y, width: CONTENT_W, height: 4, backgroundColor: rgba(C.white, 0.2), transform: `scaleX(${reveal})`, transformOrigin: "0 50%" }}>
      <div style={{ position: "absolute", inset: 0, backgroundColor: style.accent, transform: `scaleX(${progress})`, transformOrigin: "0 50%" }} />
    </div>
  </>
);

// ── Media principal: nunca recortada salvo el caso ~9:16.
const MainMedia: React.FC<{ props: EditorialReelV2Props; rect: Rect; cover: boolean; reveal: number; still: boolean; framed: boolean }> = ({ props, rect, cover, reveal, still, framed }) => {
  const frame = useCurrentFrame();
  const fitMode = cover ? "cover" : "contain";
  const drift = props.assetType === "image" && !still ? interpolate(frame, [0, Math.max(1, props.durationInFrames)], [1.05, 1], clamp) : 1;
  return (
    <div style={{ position: "absolute", left: rect.x, top: rect.y, width: rect.w, height: rect.h, opacity: mix(reveal, 0.2, 1), transform: `scale(${mix(reveal, 1.03, 1)})`, overflow: "hidden", backgroundColor: framed ? C.ink : "transparent" }}>
      {props.assetType === "video" && !still ? (
        <Video src={staticFile(props.assetFile)} objectFit={fitMode} style={{ width: "100%", height: "100%" }} />
      ) : (
        <Img src={staticFile(props.assetFile)} style={{ width: "100%", height: "100%", objectFit: fitMode, transform: `scale(${drift})` }} />
      )}
    </div>
  );
};

// Bordes del panel: regla de acento arriba y línea fina abajo.
const PanelEdges: React.FC<{ rect: Rect; accent: string; reveal: number }> = ({ rect, accent, reveal }) => (
  <>
    <div style={{ position: "absolute", left: 0, top: rect.y - 6, width: REEL.w, height: 6, backgroundColor: accent, transform: `scaleX(${reveal})`, transformOrigin: "0 50%" }} />
    <div style={{ position: "absolute", left: 0, top: rect.y + rect.h, width: REEL.w, height: 2, backgroundColor: rgba(C.white, 0.25), transform: `scaleX(${reveal})`, transformOrigin: "100% 50%" }} />
  </>
);

const smallCaps: React.CSSProperties = {
  fontFamily: `"${V2_FONT_SANS}"`,
  fontWeight: 800,
  fontStretch: "semi-condensed",
  letterSpacing: "0.14em",
  textTransform: "uppercase",
  whiteSpace: "nowrap",
  lineHeight: 1,
};

const PlayGlyph: React.FC<{ size: number; color: string }> = ({ size, color }) => (
  <div style={{ width: 0, height: 0, borderTop: `${size * 0.55}px solid transparent`, borderBottom: `${size * 0.55}px solid transparent`, borderLeft: `${size * 0.9}px solid ${color}` }} />
);

const Credit: React.FC<{ text: string; y: number; opacity: number; boxed?: boolean }> = ({ text, y, opacity, boxed }) => (
  <div style={{ position: "absolute", left: LEFT, top: y, display: "flex", alignItems: "center", gap: 14, opacity, ...(boxed ? { backgroundColor: rgba(C.ink, 0.78), padding: "10px 16px 10px 14px", left: LEFT - 14 } : {}) }}>
    <PlayGlyph size={20} color={C.red} />
    <div style={{ ...smallCaps, fontSize: 22, color: rgba(C.white, 0.86) }}>{text}</div>
  </div>
);

const DeckWithBar: React.FC<{ fitted: Fitted; y: number; accent: string; t: number }> = ({ fitted, y, accent, t }) => (
  <div style={{ position: "absolute", left: LEFT, top: y, width: CONTENT_W, display: "flex", gap: 24 }}>
    <div style={{ width: 6, backgroundColor: accent, transform: `scaleY(${t})`, transformOrigin: "50% 0%", flexShrink: 0 }} />
    <div
      style={{
        fontFamily: `"${V2_FONT_SERIF}"`,
        fontStyle: "italic",
        fontWeight: 500,
        fontSize: fitted.fontSize,
        lineHeight: `${fitted.lineHeight}px`,
        color: rgba(C.white, 0.9),
        opacity: t,
        transform: `translateY(${mix(t, 14, 0)}px)`,
      }}
    >
      {fitted.lines.map((line, i) => (
        <div key={i} style={{ whiteSpace: "nowrap" }}>
          {line}
        </div>
      ))}
    </div>
  </div>
);

const Cta: React.FC<{ y: number; opacity: number }> = ({ y, opacity }) => (
  <div style={{ position: "absolute", left: LEFT, top: y - 26, display: "flex", alignItems: "center", gap: 14, opacity }}>
    <div style={{ ...smallCaps, fontSize: 22, color: rgba(C.white, 0.72) }}>Nota completa en</div>
    <div style={{ ...smallCaps, fontSize: 22, color: C.white }}>lavozriojana.com</div>
    <div style={{ ...smallCaps, fontSize: 24, color: C.red, letterSpacing: 0 }}>→</div>
  </div>
);

// Insignia de portada: indica que es un video sin depender de la UI.
const CoverBadge: React.FC<{ rect: Rect }> = ({ rect }) => (
  <div style={{ position: "absolute", left: Math.max(LEFT, rect.x + 24), top: rect.y + 24, display: "flex", alignItems: "center", gap: 12, backgroundColor: C.red, padding: "12px 18px 12px 16px" }}>
    <PlayGlyph size={20} color={C.white} />
    <div style={{ ...smallCaps, fontSize: 22, color: C.white }}>Video</div>
  </div>
);

// ── Escena principal ────────────────────────────────────────────────────
const StoryV2: React.FC<EditorialReelV2Props> = (props) => {
  const current = useCurrentFrame();
  const still = props.still;
  // En la portada todo se pinta en su estado final.
  const frame = still ? 100_000 : current;
  const D = props.durationInFrames;
  const style = sectionStyle(props.seccion);
  const title = displayTitle(props.titulo.trim());
  const tokens = tokenize(title, props.highlightTerms, 1);
  const hasMedia = props.assetType !== "none" && Boolean(props.assetFile);
  const layout = computeLayout(props, title, hasMedia);
  const locality = props.locality.trim();
  const credit = props.credit.trim();

  const bgReveal = still ? 1 : p(frame, 0, 10, EASE.out);
  const mediaReveal = still ? 1 : p(frame, 0, 8, EASE.out);
  const headerReveal = still ? 1 : p(frame, 2, 14, EASE.out);
  const progress = still ? 0 : interpolate(frame, [0, Math.max(1, D - 1)], [0, 1], clamp);
  const titleStart = 6;
  const titleStagger = 4;
  const highlightAt = titleStart + layout.title.lines.length * titleStagger + 12;
  const deckT = still ? 1 : p(frame, highlightAt, 16, EASE.out);
  const creditT = still ? 1 : p(frame, highlightAt - 6, 14, EASE.out);
  const ctaT = still ? 1 : p(frame, highlightAt + 10, 16, EASE.out);

  const headline = (fitted: Fitted) => (
    <Headline
      fitted={fitted}
      tokens={tokens}
      color={C.white}
      accent={style.accent}
      weight={800}
      stretch="semi-condensed"
      tracking={-0.01}
      mode={still ? "none" : "line"}
      start={titleStart}
      stagger={titleStagger}
      highlightAt={still ? undefined : highlightAt}
    />
  );

  if (layout.kind === "poster") {
    const deck = layout.deck;
    const blockH = layout.title.height + (deck ? deck.height + 40 : 0);
    const top = Math.max(TITLE_Y + 40, (TITLE_Y + BOTTOM) / 2 - blockH / 2);
    return (
      <AbsoluteFill style={{ backgroundColor: C.ink, overflow: "hidden" }}>
        <Backdrop props={props} style={style} hasMedia={false} reveal={bgReveal} />
        <Watermark label={style.label} y={BOTTOM + 60} />
        <Header style={style} locality={locality} reveal={headerReveal} progress={progress} />
        <div style={{ position: "absolute", left: LEFT, top, width: CONTENT_W }}>
          {headline(layout.title)}
          {deck ? (
            <div style={{ marginTop: 40 }}>
              <Deck text={deck.lines.join(" ")} size={deck.fontSize} color={rgba(C.white, 0.88)} maxWidth={CONTENT_W} progress={deckT} />
            </div>
          ) : null}
        </div>
        <Grain opacity={0.035} />
      </AbsoluteFill>
    );
  }

  if (layout.kind === "vertical") {
    return (
      <AbsoluteFill style={{ backgroundColor: C.ink, overflow: "hidden" }}>
        <Backdrop props={props} style={style} hasMedia reveal={bgReveal} />
        <MainMedia props={props} rect={layout.media} cover={layout.cover} reveal={mediaReveal} still={still} framed={false} />
        {/* Velo superior: legibilidad del titular sin un bloque opaco */}
        <div style={{ position: "absolute", left: 0, top: 0, width: REEL.w, height: TITLE_Y + layout.title.height + 220, background: `linear-gradient(180deg, ${rgba(C.ink, 0.92)} 0%, ${rgba(C.ink, 0.82)} 60%, ${rgba(C.ink, 0)} 100%)` }} />
        <div style={{ position: "absolute", left: 0, bottom: 0, width: REEL.w, height: 520, background: `linear-gradient(0deg, ${rgba(C.ink, 0.7)} 0%, ${rgba(C.ink, 0)} 100%)` }} />
        <Header style={style} locality={locality} reveal={headerReveal} progress={progress} />
        <div style={{ position: "absolute", left: LEFT, top: TITLE_Y, width: CONTENT_W }}>{headline(layout.title)}</div>
        {credit ? <Credit text={credit} y={layout.creditY} opacity={creditT} boxed /> : null}
        {still ? <CoverBadge rect={{ x: LEFT, y: TITLE_Y + layout.title.height + 30, w: 0, h: 0 }} /> : null}
        <Grain opacity={0.03} />
      </AbsoluteFill>
    );
  }

  return (
    <AbsoluteFill style={{ backgroundColor: C.ink, overflow: "hidden" }}>
      <Backdrop props={props} style={style} hasMedia reveal={bgReveal} />
      <Watermark label={style.label} y={BOTTOM + 60} />
      <Header style={style} locality={locality} reveal={headerReveal} progress={progress} />
      <div style={{ position: "absolute", left: LEFT, top: TITLE_Y, width: CONTENT_W }}>{headline(layout.title)}</div>
      <MainMedia props={props} rect={layout.media} cover={false} reveal={mediaReveal} still={still} framed />
      <PanelEdges rect={layout.media} accent={style.accent} reveal={mediaReveal} />
      {still ? <CoverBadge rect={layout.media} /> : null}
      {credit ? <Credit text={credit} y={layout.creditY} opacity={creditT} /> : null}
      {layout.deck ? <DeckWithBar fitted={layout.deck} y={layout.deckY} accent={style.accent} t={deckT} /> : null}
      {layout.ctaY !== null ? <Cta y={layout.ctaY} opacity={ctaT} /> : null}
      <Grain opacity={0.03} />
    </AbsoluteFill>
  );
};

// ── Cierre de marca (1,8 s) ─────────────────────────────────────────────
const OutroV2: React.FC<{ seccion: string }> = ({ seccion }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const style = sectionStyle(seccion);
  const field = style.field;
  const panel = p(frame, 0, 12, EASE.snap);
  const seal = sp(frame, 8, fps, SPRING.settle, 22);
  const ruleP = p(frame, 22, 14, EASE.out);
  const follow = p(frame, 26, 14, EASE.out);
  return (
    <AbsoluteFill style={{ backgroundColor: C.ink }}>
      <AbsoluteFill style={{ backgroundColor: field, clipPath: maskInset(panel, "bottom") }} />
      <AbsoluteFill style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", paddingBottom: 120 }}>
        <div
          style={{
            width: 220,
            height: 220,
            clipPath: `circle(${mix(seal, 0, 52)}% at 50% 50%)`,
            transform: `scale(${mix(seal, 0.86, 1)})`,
          }}
        >
          <Img src={staticFile("logo.png")} style={{ width: 220, height: 220, objectFit: "contain" }} />
        </div>
        <div style={{ marginTop: 40, overflow: "hidden", padding: "6px 0" }}>
          <div style={{ transform: `translateY(${mix(p(frame, 14, 14), 110, 0)}%)` }}>
            <Wordmark size={84} seal={false} accent={style.field === C.red ? C.white : C.red} />
          </div>
        </div>
        <div style={{ marginTop: 30 }}>
          <Rule progress={ruleP} color={C.white} length={420} thickness={3} origin="center" />
        </div>
        <div style={{ marginTop: 30 }}>
          <Deck text="Seguinos en @lavozriojana" size={40} color={C.white} maxWidth={800} progress={follow} />
        </div>
        <div
          style={{
            marginTop: 18,
            fontFamily: '"LVR Archivo"',
            fontWeight: 700,
            fontStretch: "semi-condensed",
            fontSize: 28,
            letterSpacing: "0.12em",
            color: rgba(C.white, 0.8),
            opacity: follow,
          }}
        >
          LAVOZRIOJANA.COM
        </div>
      </AbsoluteFill>
      <Grain opacity={0.04} />
    </AbsoluteFill>
  );
};

export const EditorialReelV2: React.FC<EditorialReelV2Props> = (props) => {
  const ready = useV2FontsReady();
  if (!ready) return <AbsoluteFill style={{ backgroundColor: C.ink }} />;
  return (
    <AbsoluteFill style={{ backgroundColor: C.ink }}>
      <Sequence durationInFrames={props.durationInFrames} premountFor={30}>
        <StoryV2 {...props} still={false} />
      </Sequence>
      <Sequence from={props.durationInFrames} durationInFrames={REEL_V2_OUTRO_FRAMES} premountFor={30}>
        <OutroV2 seccion={props.seccion} />
      </Sequence>
    </AbsoluteFill>
  );
};

// Portada 1080×1920 (cover_url de Instagram, miniatura de Facebook): la misma
// pieza en su estado final, con un cuadro del video como imagen. Lo esencial
// queda dentro del recorte 4:5 del feed (y 285–1635) y del 3:4 de la grilla.
export const ReelCoverV2: React.FC<EditorialReelV2Props> = (props) => {
  const ready = useV2FontsReady();
  if (!ready) return <AbsoluteFill style={{ backgroundColor: C.ink }} />;
  return <StoryV2 {...props} assetType={props.assetFile ? "image" : "none"} still />;
};
