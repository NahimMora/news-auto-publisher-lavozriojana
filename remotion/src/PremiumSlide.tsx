import React from "react";
import { AbsoluteFill, Img, staticFile } from "remotion";
import { z } from "zod";
import { FittedTitle } from "./shared/FittedTitle";
import { StillLayout } from "./shared/StillLayout";
import {
  FONT_DISPLAY,
  FONT_SERIF,
  MODES,
  ModeTokens,
  SAFE,
  TYPE,
  WEIGHT,
  WHITE,
  hexToRgba,
  modeFromTemplate,
} from "./shared/designSystem";

// Carrusel premium (Fase 3/4 + rediseño "Editorial Cinemática Riojana"):
// mismo renderer para preview y publicación. 1080x1350 — resolución de
// carrusel de Instagram. Cada slideType tiene tratamiento propio por modo
// (Crónica/Editorial/Datos, derivado de `template` — ver
// docs/DECISIONS.md) en vez de un único layout con color de acento
// intercambiado.
export const PREMIUM_SLIDE_W = 1080;
export const PREMIUM_SLIDE_H = 1350;

export const PremiumSlideSchema = z.object({
  slideType: z.enum([
    "cover",
    "image_text",
    "full_image",
    "key_points",
    "quote",
    "number",
    "closing",
  ]),
  template: z.enum(["lvr_cronica", "lvr_datos", "lvr_visual"]).default("lvr_cronica"),
  title: z.string().default(""),
  text: z.string().default(""),
  items: z.array(z.string()).default([]),
  highlightTerms: z.array(z.string()).default([]),
  assetFile: z.string().default(""), // relativo a public/, "" si no hay imagen
  assetOrientation: z.enum(["landscape", "portrait", "square"]).optional(),
  section: z.string().default(""),
  index: z.number().default(1),
  total: z.number().default(1),
});

export type PremiumSlideProps = z.infer<typeof PremiumSlideSchema>;

const PAD = SAFE.pad;
const CONTENT_MAX_Y = PREMIUM_SLIDE_H - SAFE.footerH - 30; // margen sobre el footer

export const PremiumSlide: React.FC<PremiumSlideProps> = ({
  slideType,
  template,
  title,
  text,
  items,
  highlightTerms,
  assetFile,
  assetOrientation,
  section,
  index,
  total,
}) => {
  const mode = MODES[modeFromTemplate(template)];
  const hasImage = Boolean(assetFile);

  return (
    <StillLayout
      width={PREMIUM_SLIDE_W}
      height={PREMIUM_SLIDE_H}
      mode={mode}
      section={section}
      index={index}
      total={total}
      backgroundAssetFile={slideType === "cover" || slideType === "full_image" ? assetFile : ""}
    >
      {(slideType === "cover" || slideType === "full_image") && (
        <CoverSlide title={title} highlightTerms={highlightTerms} mode={mode} compact={slideType === "full_image"} />
      )}

      {slideType === "image_text" && (
        <ImageTextSlide
          title={title}
          text={text}
          highlightTerms={highlightTerms}
          assetFile={assetFile}
          assetOrientation={assetOrientation}
          mode={mode}
          hasImage={hasImage}
        />
      )}

      {slideType === "key_points" && <KeyPointsSlide title={title} items={items} mode={mode} />}

      {slideType === "quote" && <QuoteSlide text={text} title={title} highlightTerms={highlightTerms} mode={mode} />}

      {slideType === "number" && <NumberSlide number={items[0] || ""} text={text} mode={mode} />}

      {slideType === "closing" && <ClosingSlide text={text} mode={mode} />}
    </StillLayout>
  );
};

// ── Cover / Full image ────────────────────────────────────────────────────
const CoverSlide: React.FC<{ title: string; highlightTerms: string[]; mode: ModeTokens; compact?: boolean }> = ({
  title,
  highlightTerms,
  mode,
  compact,
}) => (
  <AbsoluteFill
    style={{
      padding: PAD,
      paddingBottom: PREMIUM_SLIDE_H - CONTENT_MAX_Y,
      display: "flex",
      flexDirection: "column",
      justifyContent: "flex-end",
    }}
  >
    {mode.useSerifAccent && <EditorialRule mode={mode} />}
    <FittedTitle
      text={title}
      highlightTerms={highlightTerms}
      color={WHITE}
      highlightColor={mode.accent}
      fontFamily={FONT_DISPLAY}
      fontWeight={mode.id === "editorial" ? WEIGHT.bold : WEIGHT.black}
      maxWidth={PREMIUM_SLIDE_W - PAD * 2}
      maxHeight={compact ? 320 : 460}
      minFontSize={TYPE.titleCover.min}
      maxFontSize={compact ? TYPE.titleCover.min + 14 : TYPE.titleCover.max}
      lineHeightRatio={TYPE.titleCover.lineHeightRatio}
      letterSpacing={TYPE.titleCover.tracking}
      textShadow="0 4px 20px rgba(0,0,0,0.55)"
      maxLines={4}
    />
  </AbsoluteFill>
);

// ── Image + texto ──────────────────────────────────────────────────────
const ImageTextSlide: React.FC<{
  title: string;
  text: string;
  highlightTerms: string[];
  assetFile: string;
  assetOrientation?: "landscape" | "portrait" | "square";
  mode: ModeTokens;
  hasImage: boolean;
}> = ({ title, text, highlightTerms, assetFile, assetOrientation, mode, hasImage }) => {
  const imageH = assetOrientation === "portrait" ? 760 : assetOrientation === "square" ? 680 : 600;
  const contentTop = hasImage ? imageH - 34 : PAD;

  return (
    <AbsoluteFill>
      {hasImage && (
        <>
          <Img
            src={staticFile(assetFile)}
            style={{
              position: "absolute", top: 0, left: 0, right: 0, width: "100%", height: imageH,
              objectFit: "cover", filter: mode.photoFilter,
            }}
          />
          <div
            style={{
              position: "absolute", left: 0, right: 0, top: imageH - 140, height: 140,
              background: "linear-gradient(180deg, rgba(0,0,0,0) 0%, rgba(0,0,0,0.85) 100%)",
            }}
          />
        </>
      )}
      <div
        style={{
          position: "absolute", left: 0, right: 0, top: contentTop, bottom: PREMIUM_SLIDE_H - CONTENT_MAX_Y,
          padding: `0 ${PAD}px`, display: "flex", flexDirection: "column", gap: 22, justifyContent: "flex-start",
        }}
      >
        {mode.useSerifAccent && <EditorialRule mode={mode} />}
        <FittedTitle
          text={title}
          highlightTerms={highlightTerms}
          color={WHITE}
          highlightColor={mode.accent}
          fontFamily={FONT_DISPLAY}
          fontWeight={mode.id === "editorial" ? WEIGHT.bold : WEIGHT.black}
          maxWidth={PREMIUM_SLIDE_W - PAD * 2}
          maxHeight={220}
          minFontSize={TYPE.titleBody.min}
          maxFontSize={TYPE.titleBody.max}
          lineHeightRatio={TYPE.titleBody.lineHeightRatio}
          letterSpacing={TYPE.titleBody.tracking}
          maxLines={3}
        />
        <FittedTitle
          text={text}
          color={hexToRgba(WHITE, 0.92)}
          highlightColor={mode.accent}
          fontFamily={FONT_DISPLAY}
          fontWeight={WEIGHT.regular}
          maxWidth={PREMIUM_SLIDE_W - PAD * 2}
          maxHeight={CONTENT_MAX_Y - contentTop - 200}
          minFontSize={24}
          maxFontSize={TYPE.bodyText.size}
          lineHeightRatio={TYPE.bodyText.lineHeightRatio}
          maxLines={6}
        />
      </div>
    </AbsoluteFill>
  );
};

// ── Puntos clave ───────────────────────────────────────────────────────
const KeyPointsSlide: React.FC<{ title: string; items: string[]; mode: ModeTokens }> = ({ title, items, mode }) => {
  const rows = items.slice(0, 6);
  return (
    <AbsoluteFill style={{ padding: PAD, paddingBottom: PREMIUM_SLIDE_H - CONTENT_MAX_Y, display: "flex", flexDirection: "column" }}>
      {mode.useSerifAccent && <EditorialRule mode={mode} />}
      <FittedTitle
        text={title || "Puntos clave"}
        color={WHITE}
        highlightColor={mode.accent}
        fontFamily={FONT_DISPLAY}
        fontWeight={mode.id === "editorial" ? WEIGHT.bold : WEIGHT.black}
        maxWidth={PREMIUM_SLIDE_W - PAD * 2}
        maxHeight={140}
        minFontSize={38}
        maxFontSize={54}
        lineHeightRatio={1.1}
        maxLines={2}
      />
      <div style={{ marginTop: 30, display: "flex", flexDirection: "column", gap: 22, flex: 1, overflow: "hidden" }}>
        {rows.map((item, i) => (
          <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 20 }}>
            {mode.id === "datos" ? (
              <div
                style={{
                  minWidth: 44, height: 44, borderRadius: 8, backgroundColor: hexToRgba(mode.accent, 0.16),
                  border: `1px solid ${hexToRgba(mode.accent, 0.5)}`, display: "flex", alignItems: "center",
                  justifyContent: "center", fontFamily: `"${FONT_DISPLAY}"`, fontWeight: WEIGHT.black,
                  fontSize: 19, color: mode.accent,
                }}
              >
                {String(i + 1).padStart(2, "0")}
              </div>
            ) : (
              <div style={{ width: 13, height: 13, borderRadius: 999, backgroundColor: mode.accent, marginTop: 11, flexShrink: 0 }} />
            )}
            <FittedTitle
              text={item}
              color={WHITE}
              highlightColor={mode.accent}
              fontFamily={FONT_DISPLAY}
              fontWeight={WEIGHT.regular}
              maxWidth={PREMIUM_SLIDE_W - PAD * 2 - 64}
              maxHeight={96}
              minFontSize={24}
              maxFontSize={32}
              lineHeightRatio={1.28}
              maxLines={2}
            />
          </div>
        ))}
      </div>
    </AbsoluteFill>
  );
};

// ── Cita ───────────────────────────────────────────────────────────────
const QuoteSlide: React.FC<{ text: string; title: string; highlightTerms: string[]; mode: ModeTokens }> = ({
  text,
  title,
  highlightTerms,
  mode,
}) => (
  <AbsoluteFill style={{ padding: PAD, paddingBottom: PREMIUM_SLIDE_H - CONTENT_MAX_Y, display: "flex", flexDirection: "column", justifyContent: "center", gap: 20 }}>
    <div
      style={{
        fontFamily: `"${FONT_SERIF}"`, fontWeight: WEIGHT.black, fontSize: 130, color: mode.accent,
        lineHeight: 0.6, fontStyle: "italic",
      }}
    >
      &ldquo;
    </div>
    <FittedTitle
      text={text}
      highlightTerms={highlightTerms}
      color={WHITE}
      highlightColor={mode.accent}
      fontFamily={mode.useSerifAccent ? FONT_SERIF : FONT_DISPLAY}
      fontWeight={mode.useSerifAccent ? WEIGHT.semibold : WEIGHT.bold}
      maxWidth={PREMIUM_SLIDE_W - PAD * 2}
      maxHeight={520}
      minFontSize={TYPE.quote.min}
      maxFontSize={TYPE.quote.max}
      lineHeightRatio={TYPE.quote.lineHeightRatio}
      maxLines={7}
    />
    {title ? (
      <div style={{ fontFamily: `"${FONT_SERIF}"`, fontStyle: "italic", fontWeight: WEIGHT.semibold, fontSize: 28, color: mode.accent }}>
        — {title}
      </div>
    ) : null}
  </AbsoluteFill>
);

// ── Número ─────────────────────────────────────────────────────────────
const NumberSlide: React.FC<{ number: string; text: string; mode: ModeTokens }> = ({ number, text, mode }) => (
  <AbsoluteFill style={{ padding: PAD, paddingBottom: PREMIUM_SLIDE_H - CONTENT_MAX_Y, display: "flex", flexDirection: "column", justifyContent: "center", gap: 26 }}>
    <div
      style={{
        display: "inline-flex", alignSelf: "flex-start", padding: "6px 16px", borderRadius: 999,
        backgroundColor: hexToRgba(mode.accent, 0.16), border: `1px solid ${hexToRgba(mode.accent, 0.45)}`,
        fontFamily: `"${FONT_DISPLAY}"`, fontWeight: WEIGHT.bold, fontSize: 20, letterSpacing: "0.12em",
        color: mode.accent, textTransform: "uppercase",
      }}
    >
      En números
    </div>
    <div style={{ fontFamily: `"${FONT_DISPLAY}"`, fontWeight: WEIGHT.black, fontSize: TYPE.number.size, lineHeight: TYPE.number.lineHeightRatio, color: mode.accent }}>
      {number}
    </div>
    <FittedTitle
      text={text}
      color={WHITE}
      highlightColor={mode.accent}
      fontFamily={FONT_DISPLAY}
      fontWeight={WEIGHT.regular}
      maxWidth={PREMIUM_SLIDE_W - PAD * 2}
      maxHeight={260}
      minFontSize={26}
      maxFontSize={36}
      lineHeightRatio={1.4}
      maxLines={5}
    />
  </AbsoluteFill>
);

// ── Cierre de marca ───────────────────────────────────────────────────
const ClosingSlide: React.FC<{ text: string; mode: ModeTokens }> = ({ text, mode }) => (
  <AbsoluteFill style={{ padding: PAD, paddingBottom: PREMIUM_SLIDE_H - CONTENT_MAX_Y, display: "flex", flexDirection: "column", justifyContent: "center", gap: 18, alignItems: "flex-start" }}>
    <div
      style={{
        fontFamily: `"${mode.useSerifAccent ? FONT_SERIF : FONT_DISPLAY}"`,
        fontStyle: mode.useSerifAccent ? "italic" : "normal",
        fontWeight: mode.useSerifAccent ? WEIGHT.semibold : WEIGHT.black,
        fontSize: 58, color: mode.accent,
      }}
    >
      La Voz Riojana
    </div>
    <FittedTitle
      text={text || "Seguinos para más noticias"}
      color={WHITE}
      highlightColor={mode.accent}
      fontFamily={FONT_DISPLAY}
      fontWeight={WEIGHT.regular}
      maxWidth={PREMIUM_SLIDE_W - PAD * 2}
      maxHeight={200}
      minFontSize={26}
      maxFontSize={36}
      lineHeightRatio={1.4}
      maxLines={4}
    />
  </AbsoluteFill>
);

// ── Regla editorial (acento visual del modo Editorial) ──────────────────
const EditorialRule: React.FC<{ mode: ModeTokens }> = ({ mode }) => (
  <div style={{ width: 64, height: 3, backgroundColor: mode.accent, marginBottom: 18, borderRadius: 2 }} />
);
