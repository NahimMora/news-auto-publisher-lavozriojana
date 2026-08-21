import React from "react";
import { z } from "zod";
import { FittedTitle } from "./shared/FittedTitle";
import { HeadlineBlock, EditorialRule } from "./shared/editorial/HeadlineBlock";
import { HeroMedia } from "./shared/editorial/HeroMedia";
import { StoryRail } from "./shared/editorial/StoryRail";
import { EditorialTexture } from "./shared/editorial/EditorialTexture";
import { KeyPointCard } from "./shared/editorial/KeyPointCard";
import { QuoteModule } from "./shared/editorial/QuoteModule";
import { DataModule } from "./shared/editorial/DataModule";
import { BrandSignature } from "./shared/editorial/BrandSignature";
import { ContextChip } from "./shared/editorial/ContextChip";
import { StillLayout } from "./shared/StillLayout";
import { FONT_DISPLAY, FONT_SERIF, MODES, ModeTokens, TYPE, WEIGHT, WHITE, hexToRgba, modeFromTemplate } from "./shared/designSystem";

// Carrusel premium — v2 "Editorial Cinemática Riojana": kit de componentes
// editoriales (shared/editorial/) en vez de un único StillLayout universal.
// Cada slideType tiene una composición propia por modo (Crónica/Editorial/
// Datos derivado de `template`) — retícula, alineación y tratamiento
// fotográfico distintos, no el mismo layout con el color cambiado. Ver
// docs/DECISIONS.md "Editorial Cinemática Riojana" / dirección de arte v2.
export const PREMIUM_SLIDE_W = 1080;
export const PREMIUM_SLIDE_H = 1350;
// Exportadas: AutomaticInstagramCard.tsx reusa la misma escala/chrome (ver
// docs/DECISIONS.md "Editorial Cinemática Riojana" — piezas de una sola
// imagen, manuales o automáticas, comparten diseño con el carrusel premium).
export const PREMIUM_HEADLINE_SCALE = 1.06;
const PREMIUM_BODY_SCALE = 1.14;
export const PREMIUM_MASTHEAD_H = 108;
export const PREMIUM_FOOTER_H = 96;
export const PREMIUM_CHROME_SCALE = 1.18;

const PremiumHeadlineBlock: React.FC<React.ComponentProps<typeof HeadlineBlock>> = (props) => (
  <HeadlineBlock {...props} fontScale={PREMIUM_HEADLINE_SCALE} />
);

export const PremiumSlideSchema = z.object({
  slideType: z.enum([
    "cover",
    "image_text",
    "full_image",
    "key_points",
    "quote",
    "number",
    "closing",
    "context",
    "impact",
  ]),
  template: z.enum(["lvr_cronica", "lvr_datos", "lvr_visual"]).default("lvr_cronica"),
  title: z.string().default(""),
  text: z.string().default(""),
  items: z.array(z.string()).default([]),
  highlightTerms: z.array(z.string()).default([]),
  assetFile: z.string().default(""), // relativo a public/, "" si no hay imagen
  assetOrientation: z.enum(["landscape", "portrait", "square"]).optional(),
  // Metadata de lugar para el chip de portada — nunca un highlight del
  // título (feedback: "la localidad puede ir como chip, no como highlight").
  locality: z.string().default(""),
  section: z.string().default(""),
  index: z.number().default(1),
  total: z.number().default(1),
});

export type PremiumSlideProps = z.infer<typeof PremiumSlideSchema>;

const CONTENT_H = PREMIUM_SLIDE_H - PREMIUM_MASTHEAD_H - PREMIUM_FOOTER_H;
// Portada: la foto ocupa la mayoría del lienzo (protagonismo real) y el
// titular vive separado, en un panel de tinta sólida abajo — no superpuesto
// sobre toda la foto con un scrim parejo (queja explícita: "el título se
// opaca demasiado con la foto").
const COVER_PHOTO_H = Math.round(PREMIUM_SLIDE_H * 0.6);

export const PremiumSlide: React.FC<PremiumSlideProps> = ({
  slideType,
  template,
  title,
  text,
  items,
  highlightTerms,
  assetFile,
  assetOrientation,
  locality,
  section,
  index,
  total,
}) => {
  const mode = MODES[modeFromTemplate(template)];
  const hasImage = Boolean(assetFile);
  const isLast = slideType === "closing" || index >= total;

  const bodyBySlideType: Record<string, React.ReactNode> = {
    cover: (
      <CoverSlide
        title={title}
        deck={text}
        highlightTerms={highlightTerms}
        locality={locality}
        hasImage={hasImage}
        items={items}
        mode={mode}
      />
    ),
    image_text: (
      <ImageTextSlide
        title={title}
        text={text}
        highlightTerms={highlightTerms}
        assetFile={assetFile}
        assetOrientation={assetOrientation}
        mode={mode}
      />
    ),
    full_image: (
      <FullImageSlide title={title} caption={text} highlightTerms={highlightTerms} assetFile={assetFile} mode={mode} />
    ),
    key_points: <KeyPointsSlide title={title} items={items} mode={mode} />,
    quote: <QuoteSlide text={text} author={title} highlightTerms={highlightTerms} assetFile={assetFile} mode={mode} />,
    number: <NumberSlide number={items[0] || ""} unit={items[1] || ""} text={text} highlightTerms={highlightTerms} mode={mode} />,
    closing: <ClosingSlide text={text} mode={mode} />,
    context: <ContextSlide title={title} text={text} highlightTerms={highlightTerms} items={items} mode={mode} label="Contexto" />,
    impact: <ContextSlide title={title} text={text} highlightTerms={highlightTerms} items={items} mode={mode} label="Impacto local" />,
  };

  const mediaBySlideType: Record<string, React.ReactNode> = {
    cover: hasImage ? (
      <HeroMedia assetFile={assetFile} mode={mode} variant="full_bleed" top={0} height={COVER_PHOTO_H} width={PREMIUM_SLIDE_W} scrim="none" />
    ) : null,
    full_image: hasImage ? <HeroMedia assetFile={assetFile} mode={mode} variant="full_bleed" top={0} height={PREMIUM_SLIDE_H} width={PREMIUM_SLIDE_W} scrim="bottom" /> : null,
  };

  return (
    <StillLayout
      width={PREMIUM_SLIDE_W}
      height={PREMIUM_SLIDE_H}
      mode={mode}
      section={section}
      index={index}
      total={total}
      showSwipeCue={!isLast}
      mastheadHeight={PREMIUM_MASTHEAD_H}
      footerHeight={PREMIUM_FOOTER_H}
      chromeScale={PREMIUM_CHROME_SCALE}
      media={mediaBySlideType[slideType] || null}
    >
      {bodyBySlideType[slideType]}
    </StillLayout>
  );
};

// ── Cover ──────────────────────────────────────────────────────────────
// Rediseño (feedback editorial): la foto es protagonista arriba (sin scrim
// parejo encima), separada físicamente del panel de titular abajo. El
// panel tiene su propio degradado negro que "sube" desde el borde inferior
// para sostener la lectura, en vez de oscurecer la foto entera. El titular
// puede bajar de tamaño/líneas si eso da más aire — nunca es el único
// recurso. La localidad es un chip aparte, nunca un highlight del título.
const CoverSlide: React.FC<{
  title: string;
  deck: string;
  highlightTerms: string[];
  locality: string;
  hasImage: boolean;
  items: string[];
  mode: ModeTokens;
}> = ({ title, deck, highlightTerms, locality, hasImage, items, mode }) => {
  const pad = mode.pad;
  const width = PREMIUM_SLIDE_W - pad * 2;
  // La localidad se muestra como chip aparte — nunca además como frase
  // destacada del título (feedback: "no destacar la localidad cuando ya
  // aparece como chip").
  const effectiveHighlights = highlightTerms.filter(
    (term) => term.trim().toLowerCase() !== locality.trim().toLowerCase(),
  );

  if (!hasImage) {
    // Sin imagen asignada todavía: fallback sobrio en vez de un hueco
    // negro — misma retícula de puntos que usa el resto del sistema para
    // "Datos", reusada acá como textura de marca genérica. En Datos,
    // además, si hay una cifra clara (items[0]/items[1], p.ej. "10"/
    // "horas") se agrega como ancla informativa de baja opacidad — reduce
    // la sensación de vacío sin inventar un dato que el texto no traiga.
    const statValue = items[0] || "";
    const statUnit = items[1] || "";
    const showGhostStat = mode.grid === "modular" && Boolean(statValue);
    return (
      <div style={{ position: "absolute", inset: 0 }}>
        <EditorialTexture mode={mode} zone="full" width={PREMIUM_SLIDE_W} height={PREMIUM_SLIDE_H} />
        {showGhostStat ? (
          <div
            style={{
              position: "absolute",
              right: -8,
              bottom: pad * 0.9,
              fontFamily: `"${FONT_DISPLAY}"`,
              fontWeight: WEIGHT.black,
              fontSize: 300,
              lineHeight: 0.82,
              color: hexToRgba(mode.accent, 0.14),
              pointerEvents: "none",
              textTransform: "uppercase",
            }}
          >
            {statValue}
          </div>
        ) : null}
        <div style={{ position: "absolute", inset: 0, padding: pad, display: "flex", flexDirection: "column", justifyContent: "center", gap: 18 }}>
          {locality ? <ContextChip mode={mode} label={locality} /> : null}
          <PremiumHeadlineBlock mode={mode} title={title} deck={deck} highlightTerms={effectiveHighlights} width={width} maxHeight={520} maxLines={5} />
          {showGhostStat && statUnit ? (
            <span
              style={{
                fontFamily: `"${FONT_DISPLAY}"`,
                fontWeight: WEIGHT.bold,
                fontSize: 29,
                letterSpacing: "0.1em",
                textTransform: "uppercase",
                color: hexToRgba(WHITE, 0.55),
              }}
            >
              {statValue} {statUnit}
            </span>
          ) : null}
        </div>
      </div>
    );
  }

  // CoverSlide se renderiza dentro del slot `children` de StillLayout, que
  // ya está recortado/offseteado por el masthead (empieza en canvas
  // y=PREMIUM_MASTHEAD_H). `media`, en cambio, se pinta a nivel de canvas completo
  // (y=0). Para que el panel arranque exactamente donde termina la foto
  // (media, top=0..COVER_PHOTO_H en coordenadas de canvas), acá hay que
  // restar PREMIUM_MASTHEAD_H — si no, el panel arranca más abajo de lo debido y
  // el título calculado con ese alto "de más" termina desbordando el
  // límite real (el footer), como pasó en la primera versión de este
  // rediseño (título cortado en el borde inferior).
  const panelTop = COVER_PHOTO_H - PREMIUM_MASTHEAD_H;
  const panelH = CONTENT_H - panelTop;
  const fadeH = 150; // transición foto → panel: el "degradado negro que sube desde abajo"

  const panel = (
    <>
      {/* Degradado dentro de la foto: transparente arriba, sólido justo antes del panel */}
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          top: panelTop - fadeH,
          height: fadeH,
          background: `linear-gradient(180deg, rgba(0,0,0,0) 0%, ${mode.ink} 100%)`,
        }}
      />
      {/* Panel de tinta sólida: acá vive el titular, separado de la foto */}
      <div style={{ position: "absolute", left: 0, right: 0, top: panelTop, bottom: 0, backgroundColor: mode.ink }} />
    </>
  );

  if (mode.grid === "column") {
    // Editorial: portada a ancho completo y alineada a la izquierda. La
    // columna angosta a la derecha desaprovechaba el panel y hacía que el
    // primer slide se percibiera corrido respecto del resto del carrusel.
    return (
      <div style={{ position: "absolute", inset: 0 }}>
        {panel}
        <div style={{ position: "absolute", left: 0, right: 0, top: panelTop, bottom: 0, padding: `0 ${pad}px`, display: "flex", flexDirection: "column", justifyContent: "center" }}>
          <div style={{ width: "100%", display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 16 }}>
            {locality ? <ContextChip mode={mode} label={locality} /> : null}
            <PremiumHeadlineBlock mode={mode} title={title} deck={deck} highlightTerms={effectiveHighlights} width={width} maxHeight={panelH - 90} maxLines={5} />
          </div>
        </div>
      </div>
    );
  }

  if (mode.grid === "modular") {
    // Datos: panel con marco modular, título + bajada dentro de un bloque
    // acotado (no todo el ancho) para reforzar la retícula.
    return (
      <div style={{ position: "absolute", inset: 0 }}>
        {panel}
        <div style={{ position: "absolute", left: 0, right: 0, top: panelTop, bottom: 0, padding: pad, display: "flex", flexDirection: "column", justifyContent: "center" }}>
          {locality ? (
            <div style={{ marginBottom: 16 }}>
              <ContextChip mode={mode} label={locality} />
            </div>
          ) : null}
          <div style={{ borderLeft: `4px solid ${mode.accent}`, paddingLeft: 24 }}>
            <PremiumHeadlineBlock mode={mode} title={title} deck={deck} highlightTerms={effectiveHighlights} width={width - 28} maxHeight={panelH - 90} maxLines={5} rule={false} />
          </div>
        </div>
      </div>
    );
  }

  // Crónica: panel anclado abajo, bloque contundente pero con aire real
  // (ya no pegado al borde de la foto sin transición).
  return (
    <div style={{ position: "absolute", inset: 0 }}>
      {panel}
      <div style={{ position: "absolute", left: 0, right: 0, top: panelTop, bottom: 0, padding: pad, display: "flex", flexDirection: "column", justifyContent: "flex-end", gap: 14 }}>
        {locality ? <ContextChip mode={mode} label={locality} /> : null}
        <PremiumHeadlineBlock
          mode={mode}
          title={title}
          deck={deck}
          highlightTerms={effectiveHighlights}
          width={width}
          maxHeight={panelH - 60}
          maxLines={5}
          maxHighlightPhrases={1}
        />
      </div>
    </div>
  );
};

// ── Imagen + texto ───────────────────────────────────────────────────────
const ImageTextSlide: React.FC<{
  title: string;
  text: string;
  highlightTerms: string[];
  assetFile: string;
  assetOrientation?: "landscape" | "portrait" | "square";
  mode: ModeTokens;
}> = ({ title, text, highlightTerms, assetFile, assetOrientation, mode }) => {
  const pad = mode.pad;
  const hasImage = Boolean(assetFile);

  if (mode.grid === "column") {
    // Editorial: split real, imagen a la izquierda / texto a la derecha —
    // "deben formar una unidad", no una tarjeta apilada.
    const colGap = 40;
    const imgW = Math.round(PREMIUM_SLIDE_W * 0.44);
    const textW = PREMIUM_SLIDE_W - pad * 2 - imgW - colGap;
    return (
      <div style={{ position: "absolute", inset: 0, display: "flex" }}>
        {hasImage && (
          <div style={{ position: "relative", width: imgW + pad, height: "100%" }}>
            <HeroMedia assetFile={assetFile} mode={mode} variant="framed" top={0} height={CONTENT_H} width={imgW + pad} scrim="bottom" />
          </div>
        )}
        <div
          style={{
            width: hasImage ? textW : PREMIUM_SLIDE_W - pad * 2,
            marginLeft: hasImage ? 0 : pad,
            marginRight: pad,
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
            gap: 20,
          }}
        >
          <PremiumHeadlineBlock mode={mode} title={title} highlightTerms={highlightTerms} width={hasImage ? textW : PREMIUM_SLIDE_W - pad * 2} maxHeight={260} maxLines={4} size="body" />
          <BodyText text={text} width={hasImage ? textW : PREMIUM_SLIDE_W - pad * 2} maxHeight={280} highlightTerms={highlightTerms} accent={mode.accent} />
        </div>
      </div>
    );
  }

  if (mode.grid === "modular") {
    // Datos: panel modular — imagen chica arriba, título y cuerpo abajo en
    // bloque estructurado con regla divisoria.
    const imgH = hasImage ? Math.round(CONTENT_H * 0.4) : 0;
    return (
      <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column" }}>
        {hasImage && <HeroMedia assetFile={assetFile} mode={mode} variant="framed" top={20} height={imgH} width={PREMIUM_SLIDE_W} scrim="none" />}
        <div
          style={{
            position: "absolute",
            top: hasImage ? imgH + 44 : 36,
            left: pad,
            right: pad,
            display: "flex",
            flexDirection: "column",
            gap: 18,
          }}
        >
          <PremiumHeadlineBlock mode={mode} title={title} highlightTerms={highlightTerms} width={PREMIUM_SLIDE_W - pad * 2} maxHeight={180} maxLines={3} size="body" rule={false} />
          <div style={{ width: "100%", height: 1, backgroundColor: hexToRgba(mode.accent, 0.35) }} />
          <BodyText text={text} width={PREMIUM_SLIDE_W - pad * 2} maxHeight={260} highlightTerms={highlightTerms} accent={mode.accent} />
        </div>
      </div>
    );
  }

  // Crónica: superpuesta — el titular arranca montado sobre el borde
  // inferior de la foto, texto queda debajo en la zona de tinta.
  const imgH = assetOrientation === "portrait" ? 780 : assetOrientation === "square" ? 700 : 620;
  const overlap = 64;
  return (
    <div style={{ position: "absolute", inset: 0 }}>
      {hasImage && <HeroMedia assetFile={assetFile} mode={mode} variant="full_bleed" top={0} height={imgH} width={PREMIUM_SLIDE_W} scrim="bottom" />}
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          top: hasImage ? imgH - overlap : 0,
          bottom: 0,
          padding: `0 ${pad}px`,
          display: "flex",
          flexDirection: "column",
          gap: 22,
          justifyContent: "flex-start",
        }}
      >
        <PremiumHeadlineBlock mode={mode} title={title} highlightTerms={highlightTerms} width={PREMIUM_SLIDE_W - pad * 2} maxHeight={220} maxLines={3} size="body" />
        <BodyText text={text} width={PREMIUM_SLIDE_W - pad * 2} maxHeight={280} highlightTerms={highlightTerms} accent={mode.accent} />
      </div>
    </div>
  );
};

const BodyText: React.FC<{ text: string; width: number; maxHeight: number; highlightTerms?: string[]; accent?: string }> = ({
  text,
  width,
  maxHeight,
  highlightTerms,
  accent,
}) => {
  if (!text) return null;
  return (
    <FittedTitle
      text={text}
      highlightTerms={highlightTerms}
      color={hexToRgba(WHITE, 0.9)}
      highlightColor={accent || WHITE}
      fontFamily={FONT_DISPLAY}
      fontWeight={WEIGHT.regular}
      maxWidth={width}
      maxHeight={maxHeight}
      minFontSize={Math.round(TYPE.bodyText.min * PREMIUM_BODY_SCALE)}
      maxFontSize={Math.round(TYPE.bodyText.max * PREMIUM_BODY_SCALE)}
      lineHeightRatio={TYPE.bodyText.lineHeightRatio}
      maxLines={6}
    />
  );
};

// ── Foto protagonista ────────────────────────────────────────────────────
const FullImageSlide: React.FC<{
  title: string;
  caption: string;
  highlightTerms: string[];
  assetFile: string;
  mode: ModeTokens;
}> = ({ title, caption, highlightTerms, mode }) => {
  const pad = mode.pad;
  const width = PREMIUM_SLIDE_W - pad * 2;

  if (mode.grid === "column") {
    return (
      <div style={{ position: "absolute", inset: 0, padding: pad, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
        <div />
        <div style={{ alignSelf: "flex-end", display: "flex", flexDirection: "column", gap: 16, alignItems: "flex-end" }}>
          <PremiumHeadlineBlock mode={mode} title={title} highlightTerms={highlightTerms} width={Math.round(width * 0.72)} maxHeight={220} maxLines={3} align="right" />
          {caption ? <CaptionLine text={caption} /> : null}
        </div>
      </div>
    );
  }

  if (mode.grid === "modular") {
    return (
      <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", justifyContent: "flex-end" }}>
        <div
          style={{
            margin: `0 ${pad}px 28px ${pad}px`,
            padding: "26px 30px",
            borderRadius: 14,
            backgroundColor: hexToRgba("#000000", 0.5),
            border: `1px solid ${hexToRgba(mode.accent, 0.45)}`,
            display: "flex",
            flexDirection: "column",
            gap: 12,
          }}
        >
          <PremiumHeadlineBlock mode={mode} title={title} highlightTerms={highlightTerms} width={width - 60} maxHeight={200} maxLines={3} rule={false} />
          {caption ? <CaptionLine text={caption} /> : null}
        </div>
      </div>
    );
  }

  return (
    <div style={{ position: "absolute", inset: 0, padding: pad, display: "flex", flexDirection: "column", justifyContent: "flex-end", gap: 14 }}>
      <div
        style={{
          alignSelf: "flex-start",
          padding: "10px 4px",
          borderLeft: `6px solid ${mode.accent}`,
          paddingLeft: 20,
        }}
      >
        <PremiumHeadlineBlock mode={mode} title={title} highlightTerms={highlightTerms} width={width - 26} maxHeight={280} maxLines={3} rule={false} />
      </div>
      {caption ? <CaptionLine text={caption} /> : null}
    </div>
  );
};

const CaptionLine: React.FC<{ text: string }> = ({ text }) => (
  <div style={{ fontFamily: `"${FONT_DISPLAY}"`, fontWeight: WEIGHT.medium, fontSize: 28, color: hexToRgba(WHITE, 0.68) }}>{text}</div>
);

// ── Puntos clave ─────────────────────────────────────────────────────────
// Rediseño (feedback editorial): "Puntos clave" no debe destacar más que la
// lista — el rótulo baja a kicker chico, y la lista pasa a ser el elemento
// protagonista, ocupando todo el espacio útil. Máximo 3-4 puntos (nunca
// más), cada uno grande y con desarrollo real (ver KeyPointCard).
const KeyPointsSlide: React.FC<{ title: string; items: string[]; mode: ModeTokens }> = ({ title, items, mode }) => {
  const pad = mode.pad;
  const width = PREMIUM_SLIDE_W - pad * 2;
  const rows = items.slice(0, 4);
  const kicker = (title || "Puntos clave").toUpperCase();

  const Kicker = () => (
    <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 8 }}>
      <div style={{ width: 40, height: 4, backgroundColor: mode.accent, borderRadius: 2 }} />
      <span style={{ fontFamily: `"${FONT_DISPLAY}"`, fontWeight: WEIGHT.bold, fontSize: Math.round(TYPE.kicker.size * 1.12), letterSpacing: TYPE.kicker.tracking, color: WHITE, textTransform: "uppercase" }}>
        {kicker}
      </span>
    </div>
  );

  if (mode.grid === "column" || mode.grid === "modular") {
    if (rows.length >= 4) {
      // 4 puntos: grilla 2x2 real, con filas que ESTIRAN para llenar el
      // espacio (a diferencia de un bloque chico centrado) — cada tile
      // queda grande de verdad, no una lista flotando arriba.
      const colW = Math.round((width - 40) / 2);
      return (
        <div style={{ position: "absolute", inset: 0, padding: pad, display: "flex", flexDirection: "column" }}>
          <Kicker />
          <div
            style={{
              marginTop: 20,
              display: "grid",
              gridTemplateColumns: `${colW}px ${colW}px`,
              gridTemplateRows: "1fr 1fr",
              columnGap: 40,
              rowGap: 36,
              flex: 1,
            }}
          >
            {rows.map((item, i) =>
              mode.grid === "modular" ? (
                <div key={i} style={{ border: `1px solid ${hexToRgba(mode.accent, 0.35)}`, borderRadius: 14, padding: "28px 26px", display: "flex", alignItems: "center" }}>
                  <KeyPointCard mode={mode} index={i} text={item} width={colW - 52} layout="vertical" />
                </div>
              ) : (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    paddingRight: i % 2 === 0 ? 20 : 0,
                    borderRight: i % 2 === 0 ? `1px solid ${hexToRgba(mode.accent, 0.25)}` : undefined,
                  }}
                >
                  <KeyPointCard mode={mode} index={i} text={item} width={colW - 20} layout="vertical" />
                </div>
              ),
            )}
          </div>
        </div>
      );
    }

    // 3 puntos (o menos): columna única, tarjetas grandes distribuidas en
    // todo el alto disponible.
    return (
      <div style={{ position: "absolute", inset: 0, padding: pad, display: "flex", flexDirection: "column" }}>
        <Kicker />
        <div style={{ marginTop: 12, display: "flex", flexDirection: "column", justifyContent: "space-evenly", flex: 1, gap: 24 }}>
          {rows.map((item, i) =>
            mode.grid === "modular" ? (
              <div key={i} style={{ border: `1px solid ${hexToRgba(mode.accent, 0.35)}`, borderRadius: 14, padding: "28px 26px" }}>
                <KeyPointCard mode={mode} index={i} text={item} width={width - 52 - 48} />
              </div>
            ) : (
              <KeyPointCard key={i} mode={mode} index={i} text={item} width={width} />
            ),
          )}
        </div>
      </div>
    );
  }

  // Crónica: columna única con riel vertical conectando los módulos,
  // distribuidos en todo el alto disponible (no un bloque chico centrado).
  return (
    <div style={{ position: "absolute", inset: 0, padding: pad, display: "flex", flexDirection: "column" }}>
      <Kicker />
      <div style={{ display: "flex", flexDirection: "row", gap: 30, flex: 1, marginTop: 12 }}>
        <StoryRail mode={mode} />
        <div style={{ display: "flex", flexDirection: "column", justifyContent: "space-evenly", gap: 24, width: width - 32, flex: 1 }}>
          {rows.map((item, i) => (
            <KeyPointCard key={i} mode={mode} index={i} text={item} width={width - 32} />
          ))}
        </div>
      </div>
    </div>
  );
};

// ── Cita ───────────────────────────────────────────────────────────────
const QuoteSlide: React.FC<{ text: string; author: string; highlightTerms: string[]; assetFile: string; mode: ModeTokens }> = ({
  text,
  author,
  highlightTerms,
  mode,
}) => {
  const pad = mode.pad;
  const width = PREMIUM_SLIDE_W - pad * 2;

  if (mode.grid === "modular") {
    return (
      <div style={{ position: "absolute", inset: 0, padding: pad, display: "flex", flexDirection: "column", justifyContent: "center" }}>
        <div
          style={{
            borderLeft: `5px solid ${mode.accent}`,
            backgroundColor: hexToRgba("#000000", 0.24),
            borderRadius: "0 14px 14px 0",
            padding: "38px 44px",
          }}
        >
          <QuoteModule mode={mode} text={text} highlightTerms={highlightTerms} author={author} width={width - 88} maxHeight={480} />
        </div>
      </div>
    );
  }

  if (mode.grid === "column") {
    return (
      <div style={{ position: "absolute", inset: 0, padding: pad, display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center", textAlign: "center" }}>
        <div style={{ width: 64, height: 3, backgroundColor: mode.accent, marginBottom: 26 }} />
        <QuoteModule mode={mode} text={text} highlightTerms={highlightTerms} author={author} width={Math.round(width * 0.86)} maxHeight={460} />
      </div>
    );
  }

  return (
    <div style={{ position: "absolute", inset: 0, padding: pad, display: "flex", flexDirection: "column", justifyContent: "center" }}>
      <QuoteModule mode={mode} text={text} highlightTerms={highlightTerms} author={author} width={width} maxHeight={520} />
    </div>
  );
};

// ── Número ─────────────────────────────────────────────────────────────
const NumberSlide: React.FC<{ number: string; unit: string; text: string; highlightTerms: string[]; mode: ModeTokens }> = ({
  number,
  unit,
  text,
  highlightTerms,
  mode,
}) => {
  const pad = mode.pad;
  const width = PREMIUM_SLIDE_W - pad * 2;

  if (mode.grid === "modular") {
    // Datos: panel dividido — cifra a la izquierda, contexto a la derecha.
    // La fila vive DENTRO de un contenedor que centra verticalmente (en vez
    // de forzar alto completo con `inset:0` sobre la fila): así el divisor
    // (`alignSelf: stretch`) toma el alto real del contenido, no el alto
    // completo de la slide.
    const leftW = Math.round(width * 0.46);
    const rightW = width - leftW - 40;
    return (
      <div style={{ position: "absolute", inset: 0, padding: pad, display: "flex", flexDirection: "column", justifyContent: "center" }}>
        <div style={{ display: "flex", flexDirection: "row", alignItems: "stretch", gap: 40 }}>
          <div style={{ width: leftW, display: "flex", flexDirection: "column", justifyContent: "center", gap: 18 }}>
            <ContextChip mode={mode} label="En números" />
            <DataModule mode={mode} value={number} unit={unit} comparison={null} width={leftW} />
          </div>
          <div style={{ width: 1, backgroundColor: hexToRgba(mode.accent, 0.35) }} />
          <div style={{ width: rightW, display: "flex", alignItems: "center" }}>
            <BodyText text={text} width={rightW} maxHeight={320} highlightTerms={highlightTerms} accent={mode.accent} />
          </div>
        </div>
      </div>
    );
  }

  if (mode.grid === "column") {
    return (
      <div style={{ position: "absolute", inset: 0, padding: pad, display: "flex", flexDirection: "column", justifyContent: "center", gap: 24 }}>
        <EditorialRule mode={mode} />
        <DataModule mode={mode} value={number} unit={unit} comparison={null} width={width} />
        <BodyText text={text} width={width} maxHeight={220} highlightTerms={highlightTerms} accent={mode.accent} />
      </div>
    );
  }

  return (
    <div style={{ position: "absolute", inset: 0, padding: pad, display: "flex", flexDirection: "column", justifyContent: "flex-end", gap: 24 }}>
      <ContextChip mode={mode} label="En números" />
      <DataModule mode={mode} value={number} unit={unit} comparison={null} width={width} />
      <BodyText text={text} width={width} maxHeight={220} highlightTerms={highlightTerms} accent={mode.accent} />
    </div>
  );
};

// ── Contexto (ampliación editorial sin imagen) ──────────────────────────
// Slide nuevo pedido por el feedback: antecedentes/impacto local/próximos
// pasos, sin foto. Dos jerarquías tipográficas (kicker + subtítulo serif +
// cuerpo regular) y dos niveles de color (acento + blanco) para que no se
// sienta "un párrafo de caption pegado sobre un fondo".
const ContextSlide: React.FC<{ title: string; text: string; highlightTerms: string[]; items: string[]; mode: ModeTokens; label: string }> = ({
  title,
  text,
  highlightTerms,
  items,
  mode,
  label,
}) => {
  const pad = mode.pad;
  const width = PREMIUM_SLIDE_W - pad * 2;

  // "Frase principal" del context — piso 34px (ver ESCALA). Tamaño máximo
  // generoso a propósito: el auto-fit crece hasta acá antes de conformarse
  // con menos líneas, así el bloque ocupa espacio real en vez de quedar
  // chico y centrado con vacío alrededor.
  const Subhead: React.FC<{ maxWidth: number; maxFontSize?: number }> = ({ maxWidth, maxFontSize = 56 }) =>
    title ? (
      <FittedTitle
        text={title}
        highlightTerms={highlightTerms}
        color={mode.accent}
        highlightColor={WHITE}
        fontFamily={FONT_SERIF}
        fontWeight={WEIGHT.semibold}
        maxWidth={maxWidth}
        maxHeight={220}
        minFontSize={38}
        maxFontSize={maxFontSize}
        lineHeightRatio={1.18}
        maxLines={3}
      />
    ) : null;

  // Cuerpo con más presencia que el body genérico (BodyText/TYPE.bodyText):
  // el contexto es lectura editorial, no una leyenda chica — feedback
  // "mejor densidad informativa, más lectura editorial". Piso 28px.
  const ContextBody: React.FC<{
    width: number;
    maxHeight: number;
    maxFontSize?: number;
    lineHeightRatio?: number;
    minFontSize?: number;
  }> = ({ width: bodyWidth, maxHeight, maxFontSize = 46, lineHeightRatio = 1.4, minFontSize = 32 }) =>
    text ? (
      <FittedTitle
        text={text}
        color={hexToRgba(WHITE, 0.92)}
        highlightColor={mode.accent}
        highlightTerms={highlightTerms}
        fontFamily={FONT_DISPLAY}
        fontWeight={WEIGHT.regular}
        maxWidth={bodyWidth}
        maxHeight={maxHeight}
        minFontSize={minFontSize}
        maxFontSize={maxFontSize}
        lineHeightRatio={lineHeightRatio}
        maxLines={8}
      />
    ) : null;

  if (mode.grid === "column") {
    // Editorial: retícula 35/65 — kicker + título corto en Source Serif a
    // la izquierda (angosto), desarrollo amplio en Archivo a la derecha.
    const leftW = Math.round(width * 0.35);
    const rightW = width - leftW - 40;
    return (
      <div style={{ position: "absolute", inset: 0, padding: pad, display: "flex", alignItems: "center", gap: 40 }}>
        <div style={{ width: leftW, display: "flex", flexDirection: "column", gap: 18 }}>
          <ContextChip mode={mode} label={label} />
          <Subhead maxWidth={leftW} maxFontSize={48} />
        </div>
        <div style={{ width: 1, alignSelf: "stretch", backgroundColor: hexToRgba(mode.accent, 0.3) }} />
        <div style={{ width: rightW }}>
          <ContextBody width={rightW} maxHeight={620} maxFontSize={44} />
        </div>
      </div>
    );
  }

  if (mode.grid === "modular") {
    // Datos: panel con marco angosto a 65-75% del ancho (no de borde a
    // borde) — se lee como bloque anclado, no como placa genérica. Dato
    // auxiliar (items[0], p.ej. "6 departamentos · 2026") sólo si viene
    // cargado — nunca inventado.
    const panelW = Math.round(width * 0.82);
    const auxData = items[0] || "";
    return (
      <div style={{ position: "absolute", inset: 0, padding: pad, display: "flex", flexDirection: "column", justifyContent: "center" }}>
        <div style={{ width: panelW, border: `1px solid ${hexToRgba(mode.accent, 0.4)}`, borderRadius: 16, padding: "40px 40px 44px 40px", display: "flex", flexDirection: "column", gap: 22 }}>
          <ContextChip mode={mode} label={label} />
          <Subhead maxWidth={panelW - 80} maxFontSize={50} />
          <div style={{ width: "100%", height: 1, backgroundColor: hexToRgba(mode.accent, 0.3) }} />
          <ContextBody width={panelW - 80} maxHeight={460} maxFontSize={44} />
          {auxData ? (
            <span
              style={{
                fontFamily: `"${FONT_DISPLAY}"`,
                fontWeight: WEIGHT.bold,
                fontSize: 28,
                letterSpacing: "0.06em",
                color: hexToRgba(mode.accent, 0.85),
                textTransform: "uppercase",
              }}
            >
              {auxData}
            </span>
          ) : null}
        </div>
      </div>
    );
  }

  // Crónica: barra de acento a la izquierda, subtítulo serif + cuerpo
  // apilados — bloque grande, ocupa al menos ~55% del área útil.
  return (
    <div style={{ position: "absolute", inset: 0, padding: pad, display: "flex", flexDirection: "column", justifyContent: "center" }}>
      <div style={{ borderLeft: `8px solid ${mode.accent}`, paddingLeft: 36, display: "flex", flexDirection: "column", gap: 56 }}>
        <ContextChip mode={mode} label={label} />
        <Subhead maxWidth={width - 44} maxFontSize={58} />
        <ContextBody width={width - 44} maxHeight={680} maxFontSize={46} minFontSize={38} lineHeightRatio={1.5} />
      </div>
    </div>
  );
};

// ── Cierre de marca ───────────────────────────────────────────────────
const ClosingSlide: React.FC<{ text: string; mode: ModeTokens }> = ({ text, mode }) => {
  const pad = mode.pad;
  const width = PREMIUM_SLIDE_W - pad * 2;

  if (mode.grid === "diagonal") {
    return (
      <div style={{ position: "absolute", inset: 0 }}>
        <div
          style={{
            position: "absolute",
            top: 0,
            right: 0,
            width: PREMIUM_SLIDE_W * 0.62,
            height: "100%",
            background: `linear-gradient(200deg, ${hexToRgba(mode.accent, 0.16)} 0%, rgba(0,0,0,0) 60%)`,
            clipPath: "polygon(30% 0, 100% 0, 100% 100%, 0% 100%)",
          }}
        />
        <div style={{ position: "absolute", inset: 0, padding: pad, display: "flex", alignItems: "center" }}>
          <BrandSignature mode={mode} text={text || "Seguí la cobertura completa en nuestras redes"} width={width} />
        </div>
      </div>
    );
  }

  if (mode.grid === "modular") {
    return (
      <div style={{ position: "absolute", inset: 0, padding: pad, display: "flex", alignItems: "center" }}>
        <div
          style={{
            width: "100%",
            border: `1px solid ${hexToRgba(mode.accent, 0.4)}`,
            borderRadius: 18,
            padding: "44px 40px",
          }}
        >
          <BrandSignature mode={mode} text={text || "Seguí la cobertura completa en nuestras redes"} width={width - 80} />
        </div>
      </div>
    );
  }

  return (
    <div style={{ position: "absolute", inset: 0, padding: pad, display: "flex", alignItems: "center" }}>
      <BrandSignature mode={mode} text={text || "Seguí la cobertura completa en nuestras redes"} width={width} />
    </div>
  );
};
