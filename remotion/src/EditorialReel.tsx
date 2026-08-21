import React from "react";
import { Video } from "@remotion/media";
import {
  AbsoluteFill,
  Easing,
  Img,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { MainProps } from "./Main";
import { Grain } from "./shared/Grain";
import { fitText } from "./shared/fitText";
import { useFontsReady } from "./shared/fonts";
import {
  FONT_DISPLAY,
  FONT_SERIF,
  MODES,
  SECTION_BLUE_DARK,
  WEIGHT,
  WHITE,
  hexToRgba,
  modeFromSection,
} from "./shared/designSystem";

export const EDITORIAL_OUTRO_FRAMES = 90;

// Chrome del Reel dimensionado para lectura móvil real. Estos valores reservan
// espacio físico —no sólo agrandan la fuente— para que masthead, sección y firma
// social conserven aire y jerarquía sobre un lienzo 1080×1920.
export const REEL_HEADER_H = 164;
export const REEL_MEDIA_TOP = 150;
export const REEL_PANEL_BOTTOM = 1784;
export const REEL_SECTION_H = 78;
export const REEL_FOOTER_H = 104;

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const easeEditorial = Easing.bezier(0.16, 1, 0.3, 1);
const HEADLINE_LINE_GAP = 4;
const HEADLINE_TOP = 122;
const HEADLINE_COMPACT_BOTTOM_GAP = 34;

type WordToken = { value: string; highlighted: boolean };

const normalizeWord = (word: string): string =>
  word
    .normalize("NFC")
    .toLocaleLowerCase("es-AR")
    .replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, "");

const flagHighlightPhrase = (text: string, phrases: string[]): WordToken[] => {
  const words = text.split(/\s+/).filter(Boolean);
  const normalized = words.map(normalizeWord);
  const marked = new Array(words.length).fill(false);

  for (const candidate of phrases.slice(0, 2)) {
    const phrase = candidate.split(/\s+/).filter(Boolean).map(normalizeWord);
    if (!phrase.length) continue;
    for (let start = 0; start <= normalized.length - phrase.length; start += 1) {
      const matches = phrase.every((word, offset) => normalized[start + offset] === word);
      if (!matches) continue;
      phrase.forEach((_, offset) => {
        marked[start + offset] = true;
      });
      break;
    }
  }

  return words.map((value, index) => ({ value, highlighted: marked[index] }));
};

const splitTokensByLine = (lines: string[], tokens: WordToken[]): WordToken[][] => {
  let cursor = 0;
  return lines.map((line) => {
    const count = line.split(/\s+/).filter(Boolean).length;
    const lineTokens = tokens.slice(cursor, cursor + count);
    cursor += count;
    return lineTokens;
  });
};

type FittedHeadline = ReturnType<typeof fitText>;

const fitCompactHeadline = (text: string): FittedHeadline =>
  fitText({
    text,
    // El layout compacto recompone el texto con una fuente menor, pero conserva
    // reserva para las diferencias entre Canvas y los spans coloreados reales.
    maxWidth: 800,
    maxHeight: 292,
    minFontSize: 48,
    maxFontSize: 72,
    fontFamily: FONT_DISPLAY,
    fontWeight: WEIGHT.black,
    lineHeightRatio: 1.02,
    maxLines: 5,
  });

const fittedHeadlineHeight = (fitted: FittedHeadline): number =>
  fitted.lines.length * fitted.lineHeightPx +
  Math.max(0, fitted.lines.length - 1) * HEADLINE_LINE_GAP;

const HeadlineLayer: React.FC<{
  fitted: FittedHeadline;
  text: string;
  highlightTerms: string[];
  accent: string;
  compactProgress: number;
  compact: boolean;
}> = ({ fitted, text, highlightTerms, accent, compactProgress, compact }) => {
  const frame = useCurrentFrame();
  const lineTokens = splitTokensByLine(fitted.lines, flagHighlightPhrase(text, highlightTerms));

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        flexDirection: "column",
        gap: HEADLINE_LINE_GAP,
        opacity: compact
          ? interpolate(compactProgress, [0, 0.62, 0.88, 1], [0, 0, 1, 1], clamp)
          : interpolate(compactProgress, [0, 0.42, 0.72, 1], [1, 1, 0, 0], clamp),
        fontFamily: `"${FONT_DISPLAY}"`,
        fontWeight: WEIGHT.black,
        fontSize: fitted.fontSize,
        lineHeight: `${fitted.lineHeightPx}px`,
        letterSpacing: "-0.025em",
        textTransform: "uppercase",
      }}
    >
      {lineTokens.map((line, lineIndex) => {
        const lineStart = 24 + lineIndex * 6;
        const reveal = spring({
          frame: frame - lineStart,
          fps: 30,
          config: { damping: 18, stiffness: 150, mass: 0.82 },
          durationInFrames: 24,
        });
        const ruleWidth = interpolate(reveal, [0, 1], [0, 100]);
        return (
          <div
            key={`${compact ? "compact" : "expanded"}-${lineIndex}-${line.map((token) => token.value).join("-")}`}
            style={{ overflow: "hidden", whiteSpace: "nowrap" }}
          >
            <div
              style={{
                position: "relative",
                width: "fit-content",
                opacity: interpolate(reveal, [0, 0.22, 1], [0, 1, 1]),
                translate: `${interpolate(reveal, [0, 1], [-42, 0])}px ${interpolate(reveal, [0, 1], [50, 0])}px`,
                rotate: `${interpolate(reveal, [0, 1], [-1.2, 0])}deg`,
                filter: `blur(${interpolate(reveal, [0, 1], [7, 0])}px)`,
                color: WHITE,
                textShadow: "0 5px 22px rgba(0,0,0,0.58)",
              }}
            >
              {line.map((token, tokenIndex) => (
                <React.Fragment key={`${token.value}-${tokenIndex}`}>
                  <span style={{ color: token.highlighted ? accent : WHITE }}>{token.value}</span>
                  {tokenIndex < line.length - 1 ? " " : ""}
                </React.Fragment>
              ))}
              {line.some((token) => token.highlighted) ? (
                <div
                  style={{
                    position: "absolute",
                    left: 0,
                    bottom: -2,
                    width: `${ruleWidth}%`,
                    height: 5,
                    borderRadius: 99,
                    backgroundColor: accent,
                    opacity: 0.84,
                    transformOrigin: "left center",
                  }}
                />
              ) : null}
            </div>
          </div>
        );
      })}
    </div>
  );
};

const AnimatedHeadline: React.FC<{
  text: string;
  highlightTerms: string[];
  accent: string;
  maxHeight: number;
  compactProgress: number;
  compactFitted: FittedHeadline;
}> = ({ text, highlightTerms, accent, maxHeight, compactProgress, compactFitted }) => {
  const expandedFitted = fitText({
    text,
    // El contenedor visible mide 920 px. Esta reserva también cubre el ancho
    // de los spans coloreados y evita cortes secundarios fuera de fitText.
    maxWidth: 800,
    maxHeight,
    minFontSize: 48,
    maxFontSize: 88,
    fontFamily: FONT_DISPLAY,
    fontWeight: WEIGHT.black,
    lineHeightRatio: 1.02,
    maxLines: 5,
  });

  return (
    <div style={{ position: "relative", width: "100%", height: maxHeight }}>
      <HeadlineLayer
        fitted={expandedFitted}
        text={text}
        highlightTerms={highlightTerms}
        accent={accent}
        compactProgress={compactProgress}
        compact={false}
      />
      <HeadlineLayer
        fitted={compactFitted}
        text={text}
        highlightTerms={highlightTerms}
        accent={accent}
        compactProgress={compactProgress}
        compact
      />
    </div>
  );
};

const AmbientField: React.FC<{ accent: string; progress: number }> = ({ accent, progress }) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ overflow: "hidden", backgroundColor: "#05070A" }}>
      <div
        style={{
          position: "absolute",
          width: 980,
          height: 980,
          left: -420 + Math.sin(frame / 42) * 28,
          top: -340 + Math.cos(frame / 50) * 24,
          borderRadius: "50%",
          background: `radial-gradient(circle, ${hexToRgba(accent, 0.42)} 0%, rgba(0,0,0,0) 68%)`,
          opacity: 0.56,
          scale: 1 + Math.sin(frame / 34) * 0.035,
        }}
      />
      <div
        style={{
          position: "absolute",
          width: 760,
          height: 760,
          right: -390 + Math.cos(frame / 48) * 20,
          bottom: -260 + Math.sin(frame / 52) * 25,
          borderRadius: "50%",
          background: "radial-gradient(circle, rgba(47,111,176,0.22) 0%, rgba(0,0,0,0) 70%)",
        }}
      />
      <div
        style={{
          position: "absolute",
          inset: 0,
          opacity: 0.18,
          backgroundImage:
            "linear-gradient(rgba(255,255,255,.06) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.04) 1px, transparent 1px)",
          backgroundSize: "96px 96px",
          translate: `${-(frame * 0.16) % 96}px ${-(frame * 0.08) % 96}px`,
          maskImage: "linear-gradient(180deg, black 0%, transparent 72%)",
        }}
      />
      <div
        style={{
          position: "absolute",
          top: 0,
          bottom: 0,
          left: `${interpolate(progress, [0, 1], [-55, 130])}%`,
          width: 150,
          rotate: "14deg",
          background: "linear-gradient(90deg, transparent, rgba(255,255,255,0.09), transparent)",
          filter: "blur(12px)",
        }}
      />
    </AbsoluteFill>
  );
};

const StoryMedia: React.FC<Pick<MainProps, "assetType" | "assetFile" | "kenBurnsVariant"> & {
  accent: string;
  duration: number;
  reveal: number;
}> = ({ assetType, assetFile, kenBurnsVariant, accent, duration, reveal }) => {
  const frame = useCurrentFrame();
  const zoom = interpolate(frame, [0, Math.max(1, duration)], [1.08, 1.015], {
    ...clamp,
    easing: Easing.out(Easing.cubic),
  });
  const travel = interpolate(frame, [0, Math.max(1, duration)], [0, 26], clamp);
  const x = kenBurnsVariant === 1 ? -travel : kenBurnsVariant === 0 ? travel * 0.35 : 0;
  const y = kenBurnsVariant === 2 ? -travel : travel * 0.18;
  const mainMediaStyle: React.CSSProperties = {
    position: "absolute",
    inset: 0,
    width: "100%",
    height: "100%",
    translate: `${x}px ${y}px`,
    scale: zoom,
  };

  return (
    <div
      style={{
        position: "absolute",
        top: REEL_MEDIA_TOP,
        left: 28,
        right: 28,
        bottom: 136,
        overflow: "hidden",
        borderRadius: 24,
        clipPath: `inset(${interpolate(reveal, [0, 1], [48, 0])}% ${interpolate(reveal, [0, 1], [49, 0])}% round 24px)`,
        boxShadow: `0 34px 90px rgba(0,0,0,0.58), inset 0 0 0 1px ${hexToRgba(WHITE, 0.12)}`,
        backgroundColor: "#050505",
      }}
    >
      {assetType === "video" && assetFile ? (
        <>
          <Video
            src={staticFile(assetFile)}
            muted
            objectFit="cover"
            style={{ position: "absolute", inset: 0, width: "100%", height: "100%", filter: "blur(54px) brightness(0.48) saturate(1.18)", scale: 1.22 }}
          />
          <Video src={staticFile(assetFile)} objectFit="contain" style={mainMediaStyle} />
        </>
      ) : null}
      {assetType === "image" && assetFile ? (
        <>
          <Img
            src={staticFile(assetFile)}
            style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover", filter: "blur(54px) brightness(0.48) saturate(1.18)", scale: 1.22 }}
          />
          <Img src={staticFile(assetFile)} style={{ ...mainMediaStyle, objectFit: "contain" }} />
        </>
      ) : null}
      {assetType === "none" || !assetFile ? (
        <AbsoluteFill style={{ background: `linear-gradient(145deg, ${hexToRgba(accent, 0.48)} 0%, #090B10 45%, #020304 100%)` }}>
          <div
            style={{
              position: "absolute",
              left: 118,
              top: 250,
              width: 720,
              height: 720,
              border: `2px solid ${hexToRgba(WHITE, 0.08)}`,
              borderRadius: "50%",
              scale: 1 + Math.sin(frame / 18) * 0.045,
            }}
          />
          <div
            style={{
              position: "absolute",
              left: 264,
              top: 396,
              width: 430,
              height: 430,
              border: `1px solid ${hexToRgba(accent, 0.35)}`,
              rotate: `${frame * 0.16}deg`,
            }}
          />
        </AbsoluteFill>
      ) : null}
      <AbsoluteFill style={{ background: "linear-gradient(180deg, rgba(0,0,0,0.06) 0%, rgba(0,0,0,0.08) 44%, rgba(1,3,6,0.9) 100%)" }} />
      <AbsoluteFill style={{ boxShadow: `inset 0 0 0 1px ${hexToRgba(WHITE, 0.1)}` }} />
    </div>
  );
};

const StoryScene: React.FC<MainProps> = ({
  titulo,
  seccion,
  assetType,
  assetFile,
  kenBurnsVariant,
  durationInFrames,
  highlightTerms = [],
}) => {
  const frame = useCurrentFrame();
  const mode = MODES[modeFromSection(seccion)];
  const accent = mode.accent;
  const sectionBackground = mode.id === "cronica" ? accent : SECTION_BLUE_DARK;
  const intro = spring({ frame, fps: 30, config: { damping: 20, stiffness: 125, mass: 0.9 }, durationInFrames: 34 });
  const mediaReveal = interpolate(frame, [3, 32], [0, 1], { ...clamp, easing: easeEditorial });
  const badgeReveal = spring({ frame: frame - 15, fps: 30, config: { damping: 16, stiffness: 175 }, durationInFrames: 24 });
  const compactEnabled = durationInFrames >= 180;
  const compactStart = Math.min(126, durationInFrames - 58);
  const compactProgress = compactEnabled
    ? interpolate(frame, [compactStart, compactStart + 32], [0, 1], { ...clamp, easing: Easing.inOut(Easing.cubic) })
    : 0;
  const compactHeadlineFit = fitCompactHeadline(titulo);
  const compactPanelHeight =
    HEADLINE_TOP + fittedHeadlineHeight(compactHeadlineFit) + HEADLINE_COMPACT_BOTTOM_GAP;
  const compactPanelTop = REEL_PANEL_BOTTOM - compactPanelHeight;
  // En compacto se mueve el panel completo según el alto real del layout
  // recompuesto: sección, titular y footer quedan agrupados para cualquier título.
  const panelTop = interpolate(compactProgress, [0, 1], [990, compactPanelTop]);
  const panelBottom = REEL_PANEL_BOTTOM;
  const panelHeight = panelBottom - panelTop;
  const footerReveal = spring({ frame: frame - 42, fps: 30, config: { damping: 18, stiffness: 140 }, durationInFrames: 24 });
  const shimmerProgress = interpolate(frame, [40, 94], [0, 1], clamp);
  const progress = frame / Math.max(1, durationInFrames - 1);

  return (
    <AbsoluteFill style={{ backgroundColor: "#05070A", color: WHITE, overflow: "hidden" }}>
      <AmbientField accent={accent} progress={shimmerProgress} />
      <StoryMedia
        assetType={assetType}
        assetFile={assetFile}
        kenBurnsVariant={kenBurnsVariant}
        accent={accent}
        duration={durationInFrames}
        reveal={mediaReveal}
      />

      <div
        style={{
          position: "absolute",
          left: 28,
          right: 28,
          top: panelTop,
          height: panelHeight,
          clipPath: `polygon(0 ${interpolate(intro, [0, 1], [18, 0])}%, 100% 0, 100% 100%, 0 100%)`,
          background: `linear-gradient(155deg, ${hexToRgba(sectionBackground, 0.94)} 0%, rgba(8,10,14,0.97) 43%, rgba(3,4,7,0.99) 100%)`,
          borderRadius: "0 0 24px 24px",
          boxShadow: "0 -28px 70px rgba(0,0,0,0.38)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            width: `${interpolate(intro, [0, 1], [0, 100])}%`,
            height: 7,
            backgroundColor: accent,
            boxShadow: `0 0 26px ${hexToRgba(accent, 0.75)}`,
          }}
        />
        <div
          style={{
            position: "absolute",
            top: HEADLINE_TOP,
            left: 52,
            right: 52,
            bottom: 42,
            transformOrigin: "left bottom",
          }}
        >
          <AnimatedHeadline
            text={titulo}
            highlightTerms={highlightTerms}
            accent={accent}
            // Conserva las métricas del titular durante la compactación. Si el
            // presupuesto se redujera junto con el panel, fitText volvería a
            // partir líneas a mitad de la transición.
            maxHeight={Math.max(375, panelHeight - 174)}
            compactProgress={compactProgress}
            compactFitted={compactHeadlineFit}
          />
        </div>
        <div
          style={{
            position: "absolute",
            right: -220 + shimmerProgress * 1380,
            top: -180,
            width: 150,
            height: panelHeight + 360,
            rotate: "18deg",
            background: "linear-gradient(90deg, transparent, rgba(255,255,255,0.09), transparent)",
            filter: "blur(12px)",
          }}
        />
      </div>

      <div
        style={{
          position: "absolute",
          left: 52,
          top: panelTop + 26,
          height: REEL_SECTION_H,
          display: "flex",
          alignItems: "center",
          gap: 15,
          padding: "0 34px 0 22px",
          backgroundColor: sectionBackground,
          clipPath: "polygon(0 0, 100% 0, calc(100% - 24px) 100%, 0 100%)",
          opacity: interpolate(badgeReveal, [0, 0.12, 1], [0, 1, 1]),
          translate: `${interpolate(badgeReveal, [0, 1], [-58, 0])}px 0px`,
          scale: interpolate(badgeReveal, [0, 1], [0.86, 1]),
          transformOrigin: "left center",
          boxShadow: `0 10px 24px ${hexToRgba(sectionBackground, 0.36)}`,
        }}
      >
        <Img src={staticFile("logo.png")} style={{ width: 42, height: 42, objectFit: "contain" }} />
        <span
          style={{
            fontFamily: `"${FONT_DISPLAY}"`,
            fontWeight: WEIGHT.black,
            fontSize: 31,
            letterSpacing: "0.14em",
            textTransform: "uppercase",
          }}
        >
          {seccion}
        </span>
      </div>

      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          height: REEL_HEADER_H,
          padding: "0 52px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          background: "linear-gradient(180deg, rgba(3,4,7,0.98) 0%, rgba(3,4,7,0.78) 72%, rgba(3,4,7,0) 100%)",
          opacity: interpolate(intro, [0, 0.18, 1], [0, 1, 1]),
          translate: `0px ${interpolate(intro, [0, 1], [-38, 0])}px`,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <Img src={staticFile("logo.png")} style={{ width: 74, height: 74, objectFit: "contain" }} />
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            <span style={{ fontFamily: `"${FONT_DISPLAY}"`, fontWeight: WEIGHT.black, fontSize: 35, letterSpacing: "0.065em" }}>LA VOZ RIOJANA</span>
            <span style={{ fontFamily: `"${FONT_SERIF}"`, fontStyle: "italic", fontWeight: WEIGHT.medium, fontSize: 24, color: hexToRgba(WHITE, 0.72) }}>Periodismo de La Rioja</span>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ width: 12, height: 12, borderRadius: "50%", backgroundColor: accent, boxShadow: `0 0 18px ${accent}`, scale: 0.9 + Math.sin(frame / 7) * 0.12 }} />
          <span style={{ fontFamily: `"${FONT_DISPLAY}"`, fontWeight: WEIGHT.bold, fontSize: 24, letterSpacing: "0.11em", color: hexToRgba(WHITE, 0.82) }}>EDICIÓN DIGITAL</span>
        </div>
      </div>

      <div
        style={{
          position: "absolute",
          right: 11,
          top: 210,
          bottom: 292,
          width: 2,
          backgroundColor: hexToRgba(WHITE, 0.14),
          opacity: interpolate(intro, [0, 1], [0, 1]),
        }}
      >
        <div style={{ width: 2, height: `${progress * 100}%`, backgroundColor: accent, boxShadow: `0 0 14px ${accent}` }} />
        <div style={{ position: "absolute", left: -4, top: `calc(${progress * 100}% - 5px)`, width: 10, height: 10, borderRadius: "50%", backgroundColor: WHITE }} />
      </div>

      <div
        style={{
          position: "absolute",
          left: 52,
          right: 52,
          bottom: 16,
          height: REEL_FOOTER_H,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          opacity: interpolate(footerReveal, [0, 0.15, 1], [0, 1, 1]),
          translate: `0px ${interpolate(footerReveal, [0, 1], [34, 0])}px`,
        }}
      >
        <span style={{ fontFamily: `"${FONT_DISPLAY}"`, fontWeight: WEIGHT.bold, fontSize: 33, letterSpacing: "0.02em" }}>lavozriojana.com</span>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          {["fb_icon_base.png", "ig_icon_base.png"].map((file) => (
            <div
              key={file}
              style={{
                width: 38,
                height: 38,
                backgroundColor: WHITE,
                maskImage: `url(${staticFile(file)})`,
                maskSize: "contain",
                maskRepeat: "no-repeat",
                maskPosition: "center",
                WebkitMaskImage: `url(${staticFile(file)})`,
                WebkitMaskSize: "contain",
                WebkitMaskRepeat: "no-repeat",
                WebkitMaskPosition: "center",
              }}
            />
          ))}
          <span style={{ fontFamily: `"${FONT_DISPLAY}"`, fontWeight: WEIGHT.bold, fontSize: 33, color: accent }}>@lavozriojana</span>
        </div>
      </div>
      <Grain opacity={0.045} />
    </AbsoluteFill>
  );
};

const CinematicOutro: React.FC<{ seccion: string }> = ({ seccion }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const mode = MODES[modeFromSection(seccion)];
  const accent = mode.accent;
  const curtain = interpolate(frame, [0, 18], [0, 1], { ...clamp, easing: easeEditorial });
  const logo = spring({ frame: frame - 8, fps, config: { damping: 16, stiffness: 130, mass: 0.9 }, durationInFrames: 28 });
  const copy = spring({ frame: frame - 24, fps, config: { damping: 18, stiffness: 140 }, durationInFrames: 24 });
  const fade = interpolate(frame, [durationInFrames - 14, durationInFrames - 1], [1, 0], clamp);
  const orbit = frame * 0.42;

  return (
    <AbsoluteFill style={{ backgroundColor: "#040609", color: WHITE, opacity: fade, overflow: "hidden" }}>
      <AmbientField accent={accent} progress={interpolate(frame, [5, 70], [0, 1], clamp)} />
      <div style={{ position: "absolute", inset: 0, backgroundColor: accent, clipPath: `polygon(0 0, ${curtain * 100}% 0, ${Math.max(0, curtain * 100 - 20)}% 100%, 0 100%)`, opacity: 0.13 }} />
      {[560, 720, 880].map((size, index) => (
        <div
          key={size}
          style={{
            position: "absolute",
            left: 540 - size / 2,
            top: 700 - size / 2,
            width: size,
            height: size,
            borderRadius: "50%",
            border: `1px solid ${hexToRgba(index === 1 ? accent : WHITE, 0.12)}`,
            scale: interpolate(logo, [0, 1], [0.72 + index * 0.08, 1]),
            rotate: `${index % 2 ? -orbit : orbit}deg`,
          }}
        />
      ))}
      <div
        style={{
          position: "absolute",
          left: 170,
          right: 170,
          top: 332,
          height: 740,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <Img
          src={staticFile("logo.png")}
          style={{
            width: 310,
            height: 310,
            objectFit: "contain",
            opacity: interpolate(logo, [0, 0.1, 1], [0, 1, 1]),
            scale: interpolate(logo, [0, 1], [0.68, 1]),
            rotate: `${interpolate(logo, [0, 1], [-5, 0])}deg`,
            filter: `drop-shadow(0 24px 46px rgba(0,0,0,0.52)) drop-shadow(0 0 28px ${hexToRgba(accent, 0.34)})`,
          }}
        />
        <div style={{ marginTop: 44, width: interpolate(copy, [0, 1], [0, 520]), height: 5, backgroundColor: accent, boxShadow: `0 0 24px ${hexToRgba(accent, 0.7)}` }} />
        <div
          style={{
            marginTop: 42,
            opacity: interpolate(copy, [0, 0.16, 1], [0, 1, 1]),
            translate: `0px ${interpolate(copy, [0, 1], [46, 0])}px`,
            textAlign: "center",
          }}
        >
          <div style={{ fontFamily: `"${FONT_DISPLAY}"`, fontWeight: WEIGHT.black, fontSize: 58, letterSpacing: "0.04em" }}>LA VOZ RIOJANA</div>
          <div style={{ marginTop: 18, fontFamily: `"${FONT_SERIF}"`, fontStyle: "italic", fontWeight: WEIGHT.medium, fontSize: 34, color: hexToRgba(WHITE, 0.76) }}>Seguinos en nuestras redes</div>
        </div>
      </div>
      <div
        style={{
          position: "absolute",
          left: 100,
          right: 100,
          bottom: 190,
          padding: "36px 42px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          borderTop: `1px solid ${hexToRgba(WHITE, 0.16)}`,
          borderBottom: `1px solid ${hexToRgba(WHITE, 0.16)}`,
          opacity: interpolate(copy, [0, 1], [0, 1]),
        }}
      >
        <span style={{ fontFamily: `"${FONT_DISPLAY}"`, fontWeight: WEIGHT.bold, fontSize: 36 }}>lavozriojana.com</span>
        <span style={{ fontFamily: `"${FONT_DISPLAY}"`, fontWeight: WEIGHT.black, fontSize: 36, color: accent }}>@lavozriojana</span>
      </div>
      <Grain opacity={0.052} />
    </AbsoluteFill>
  );
};

export const EditorialReel: React.FC<MainProps> = (props) => {
  const fontsReady = useFontsReady();
  if (!fontsReady) return <AbsoluteFill style={{ backgroundColor: "#05070A" }} />;

  return (
    <AbsoluteFill style={{ backgroundColor: "#05070A" }}>
      <Sequence durationInFrames={props.durationInFrames} premountFor={30}>
        <StoryScene {...props} />
      </Sequence>
      <Sequence from={props.durationInFrames} durationInFrames={EDITORIAL_OUTRO_FRAMES} premountFor={30}>
        <CinematicOutro seccion={props.seccion} />
      </Sequence>
    </AbsoluteFill>
  );
};
