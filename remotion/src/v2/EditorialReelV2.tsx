// EditorialReelV2 — Reel 1080×1920 del Visual System V2.
//
// Composición con estados (no un marco fijo):
//   A · Impacto inicial (hook editorial): el video se abre como obturador y
//       el titular se arma en tipografía partida; video y audio desde el frame 0.
//   B · Reorganización: el titular grande sale por máscara y la regla de
//       acento viaja a la posición compacta; el video se asienta.
//   C · Video protagonista: chrome mínimo (firma + regla de progreso) y
//       titular compacto que no tapa el video (debajo en horizontales; en
//       verticales se retira y vuelve al final en videos largos).
//   D · Cierre de marca breve (1,8 s) DESPUÉS del video completo.
//
// El video fuente nunca se recorta: horizontales y cuadrados se escalan
// enteros (contain) y verticales sólo usan "cover" cuando su relación de
// aspecto difiere menos de 4 % de 9:16. Los props son un superconjunto de
// MainSchema (ver Main.tsx) para que el pipeline actual pueda alimentarlo.
import React from "react";
import { Video } from "@remotion/media";
import { AbsoluteFill, Img, Sequence, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { z } from "zod";
import { Deck, Headline, Rule, SectionLabel, Wordmark, camera, maskInset } from "./components";
import { fit } from "./fit";
import { useV2FontsReady } from "./fonts";
import { EASE, SPRING, clamp, mix, p, sp } from "./motion";
import { HookStyle, sentenceCase, tokenize } from "./text";
import { C, REEL, SectionStyle, TIMING, TYPE, rgba, sectionStyle } from "./tokens";
import { Grain } from "../shared/Grain";

export const EditorialReelV2Schema = z.object({
  titulo: z.string(),
  seccion: z.string(),
  assetType: z.enum(["video", "image", "none"]),
  assetFile: z.string(),
  kenBurnsVariant: z.number().default(0),
  durationInFrames: z.number(),
  highlightTerms: z.array(z.string()).optional().default([]),
  // Opcionales V2 (el pipeline actual puede omitirlos):
  assetWidth: z.number().default(0),
  assetHeight: z.number().default(0),
  locality: z.string().default(""),
  breaking: z.boolean().default(false),
  // Compatibilidad: hoy existe un único hook ("cinematic_editorial").
  hookStyle: z.enum(["auto", "cinematic_editorial"]).default("auto"),
});

export type EditorialReelV2Props = z.infer<typeof EditorialReelV2Schema>;

export const REEL_V2_OUTRO_FRAMES = REEL.outroFrames;

const SAFE = REEL.safe;
const CONTENT_W = SAFE.right - SAFE.left + 12; // 888 — evita la columna de botones
const BRAND_Y = SAFE.top;
const BRAND_H = 64;

interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

interface StageLayout {
  kind: "stacked" | "overlay";
  rect: Rect;
  cover: boolean;
  compactTop: number; // y del bloque compacto (stacked) o base inferior (overlay)
}

function compactFitFor(title: string) {
  return fit({
    text: title,
    maxWidth: CONTENT_W,
    maxHeight: 4 * TYPE.reelCompact.max * TYPE.reelCompact.lh,
    min: TYPE.reelCompact.min,
    max: TYPE.reelCompact.max,
    weight: TYPE.reelCompact.weight,
    lh: TYPE.reelCompact.lh,
    stretch: TYPE.reelCompact.stretch,
    tracking: TYPE.reelCompact.tracking,
    maxLines: 4,
  });
}

const LABEL_BLOCK = 30 + 22;

function computeLayout(assetType: string, w: number, h: number, compactH: number): StageLayout {
  const aspect = w > 0 && h > 0 ? w / h : 9 / 16;
  if (assetType === "none") {
    return { kind: "overlay", rect: { x: 0, y: 0, w: REEL.w, h: REEL.h }, cover: true, compactTop: SAFE.bottom };
  }
  if (aspect < 0.85) {
    // Vertical: ocupa la pantalla; sólo "cover" si es prácticamente 9:16.
    const target = REEL.w / REEL.h;
    const cover = Math.abs(aspect - target) / target < 0.04;
    if (cover) return { kind: "overlay", rect: { x: 0, y: 0, w: REEL.w, h: REEL.h }, cover, compactTop: SAFE.bottom };
    let rw = REEL.w;
    let rh = rw / aspect;
    if (rh > REEL.h) {
      rh = REEL.h;
      rw = rh * aspect;
    }
    return {
      kind: "overlay",
      rect: { x: (REEL.w - rw) / 2, y: (REEL.h - rh) / 2, w: rw, h: rh },
      cover: false,
      compactTop: SAFE.bottom,
    };
  }
  // Horizontal / cuadrado: doble plano — video entero arriba, titular
  // compacto debajo, sin texto sobre la imagen.
  const top = BRAND_Y + BRAND_H + 64;
  const gap = 52;
  const headlineBlock = LABEL_BLOCK + compactH;
  const available = SAFE.bottom - top - gap - headlineBlock;
  let rh = Math.min(REEL.w / aspect, available);
  let rw = rh * aspect;
  if (rw > REEL.w) {
    rw = REEL.w;
    rh = rw / aspect;
  }
  const free = SAFE.bottom - top - (rh + gap + headlineBlock);
  const y = top + Math.max(0, free * 0.4);
  return {
    kind: "stacked",
    rect: { x: (REEL.w - rw) / 2, y, w: rw, h: rh },
    cover: false,
    compactTop: y + rh + gap,
  };
}

// ── Fondo contextual: el mismo material, desenfocado y oscurecido. Se pinta
// a 1/4 de resolución y se escala: el desenfoque cuesta 16× menos por frame.
const ContextBackdrop: React.FC<{ assetType: string; assetFile: string; style: SectionStyle }> = ({ assetType, assetFile, style }) => {
  const q = 4;
  const inner: React.CSSProperties = {
    position: "absolute",
    inset: 0,
    width: "100%",
    height: "100%",
    filter: "blur(9px) brightness(0.42) saturate(1.05)",
    transform: "scale(1.12)",
  };
  return (
    <AbsoluteFill style={{ backgroundColor: C.ink, overflow: "hidden" }}>
      {assetFile && assetType !== "none" ? (
        <div style={{ position: "absolute", left: 0, top: 0, width: REEL.w / q, height: REEL.h / q, transform: `scale(${q})`, transformOrigin: "0 0", overflow: "hidden" }}>
          {assetType === "video" ? <Video src={staticFile(assetFile)} muted objectFit="cover" style={inner} /> : <Img src={staticFile(assetFile)} style={{ ...inner, objectFit: "cover" }} />}
        </div>
      ) : null}
      <AbsoluteFill style={{ backgroundColor: rgba(C.ink, assetFile ? 0.38 : 1) }} />
      <AbsoluteFill style={{ backgroundColor: rgba(style.field, 0.1), mixBlendMode: "color" }} />
    </AbsoluteFill>
  );
};

// ── Media principal (nunca recortada salvo el caso 9:16 descripto arriba).
const MainMedia: React.FC<{
  assetType: string;
  assetFile: string;
  layout: StageLayout;
  cam: React.CSSProperties;
  clip: string;
  duration: number;
}> = ({ assetType, assetFile, layout, cam, clip, duration }) => {
  const frame = useCurrentFrame();
  const { rect, cover } = layout;
  const fitMode = cover ? "cover" : "contain";
  // Fotos: deriva lenta y mínima dentro de su propio marco.
  const still = assetType === "image" ? interpolate(frame, [0, Math.max(1, duration)], [1.04, 1], clamp) : 1;
  return (
    <div style={{ position: "absolute", left: rect.x, top: rect.y, width: rect.w, height: rect.h, clipPath: clip, overflow: "hidden" }}>
      <div style={{ position: "absolute", inset: 0, ...cam }}>
        {assetType === "video" ? (
          <Video src={staticFile(assetFile)} objectFit={fitMode} style={{ width: "100%", height: "100%" }} />
        ) : (
          <Img src={staticFile(assetFile)} style={{ width: "100%", height: "100%", objectFit: fitMode, transform: `scale(${still})` }} />
        )}
      </div>
    </div>
  );
};

// ── Firma superior + regla de progreso.
const BrandBar: React.FC<{ style: SectionStyle; reveal: number; progress: number; detail: string }> = ({ style, reveal, progress, detail }) => (
  <div style={{ position: "absolute", left: SAFE.left, top: BRAND_Y, width: CONTENT_W }}>
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 18,
        height: BRAND_H,
        padding: "0 22px 0 8px",
        backgroundColor: rgba(C.ink, 0.9),
        clipPath: maskInset(reveal, "left"),
      }}
    >
      <Wordmark size={30} sealSize={54} accent={style.accent} />
      <div style={{ width: 2, height: 28, backgroundColor: rgba(C.white, 0.28) }} />
      <SectionLabel label={style.label} detail={detail} accent={style.accent} color={C.white} size={23} progress={1} />
    </div>
    <div style={{ position: "relative", marginTop: 14, height: 3, width: CONTENT_W, backgroundColor: rgba(C.white, 0.18), opacity: reveal }}>
      <div style={{ position: "absolute", inset: 0, backgroundColor: style.accent, transform: `scaleX(${progress})`, transformOrigin: "0 50%" }} />
    </div>
  </div>
);

// ── Escena principal ────────────────────────────────────────────────────
const StoryV2: React.FC<EditorialReelV2Props> = (props) => {
  const frame = useCurrentFrame();
  const D = props.durationInFrames;
  const style = sectionStyle(props.seccion);
  const title = sentenceCase(props.titulo.trim());
  const locality = props.locality.trim();
  // Hook único (cinematic_editorial) para todas las secciones: la sección
  // se distingue por color y etiqueta, no por otra estética.
  const hook: HookStyle = "cinematic_editorial";
  const tokens = tokenize(title, props.highlightTerms, 1);

  // Timeline (se comprime en videos muy cortos).
  const hookEnd = Math.min(TIMING.hookHold, Math.round(D * 0.42));
  const morph = Math.min(TIMING.layoutMorph, Math.max(10, Math.round(D * 0.15)));
  const settled = hookEnd + morph;
  const compactFitted = compactFitFor(title);
  const layout = computeLayout(props.assetType, props.assetWidth, props.assetHeight, compactFitted.height);
  const hasMedia = props.assetType !== "none" && Boolean(props.assetFile);

  // Titular compacto: permanente en "stacked"; en "overlay" se retira tras
  // un tiempo de lectura y reaparece al final de videos largos.
  const holdEnd = layout.kind === "overlay" ? Math.min(D - 8, settled + Math.max(TIMING.minCompactHold, Math.round(D * 0.35))) : D + 1;
  // Sentinela finito (interpolate exige rangos finitos) cuando no hay reprise.
  const repriseAt = layout.kind === "overlay" && D >= 750 ? D - 120 : D + 10_000;
  const compactIn = p(frame, hookEnd + 12, 16, EASE.out);
  const compactOut = frame >= repriseAt ? 0 : p(frame, holdEnd, 14, EASE.inOut);
  const reprise = p(frame, repriseAt, 16, EASE.out);
  const compactVisible = frame >= repriseAt ? reprise : compactIn * (1 - compactOut);

  // Estado A → B
  const scrimHook = layout.kind === "overlay" ? 0.56 : 0.4;
  const scrim = hasMedia ? mix(p(frame, hookEnd - 2, morph, EASE.inOut), scrimHook, 0) : 0;
  const cam = camera(frame, 0, settled + 10, 1.1, 24);
  const mediaClip = maskInset(p(frame, 0, 9, EASE.snap), "center-h");
  const brandReveal = p(frame, hookEnd + 2, 14, EASE.out);
  const progress = interpolate(frame, [0, Math.max(1, D - 1)], [0, 1], clamp);
  const hookExit = hookEnd;

  // Destacado por caja: el color de texto sobre la caja siempre es blanco.
  const accent = style.accent;
  const labelDetail = locality;

  return (
    <AbsoluteFill style={{ backgroundColor: C.ink, overflow: "hidden" }}>
      <ContextBackdrop assetType={props.assetType} assetFile={props.assetFile} style={style} />
      {hasMedia ? <MainMedia assetType={props.assetType} assetFile={props.assetFile} layout={layout} cam={cam} clip={mediaClip} duration={D} /> : <TypeField style={style} />}
      {hasMedia ? (
        <div style={{ position: "absolute", left: 0, top: layout.rect.y + layout.rect.h / 2 - 2, width: REEL.w, opacity: 1 - p(frame, 8, 8) }}>
          <Rule progress={p(frame, 0, 8, EASE.snap)} color={accent} length={REEL.w} thickness={4} />
        </div>
      ) : null}
      <AbsoluteFill style={{ backgroundColor: rgba(C.ink, scrim) }} />

      {/* Estado A — hook */}
      {frame < settled + 4 ? (
        <HookLayer hook={hook} title={title} tokens={tokens} style={style} detail={labelDetail} exitAt={hookExit} hasMedia={hasMedia} region={layout.kind === "stacked" ? { top: layout.rect.y + layout.rect.h + 44, bottom: SAFE.bottom } : null} />
      ) : null}

      {/* Estados B/C — titular compacto */}
      {frame >= hookEnd ? (
        <CompactHeadline
          layout={layout}
          fitted={compactFitted}
          tokens={tokens}
          style={style}
          detail={labelDetail}
          visible={compactVisible}
          enterAt={frame >= repriseAt ? repriseAt : hookEnd + 12}
          hasMedia={hasMedia}
        />
      ) : null}

      {hasMedia ? <BrandBar style={style} reveal={brandReveal} progress={progress} detail="" /> : null}
      <Grain opacity={0.035} />
    </AbsoluteFill>
  );
};

// Sin foto ni video: campo tipográfico con retícula de reglas.
const TypeField: React.FC<{ style: SectionStyle }> = ({ style }) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ backgroundColor: C.ink }}>
      {[0, 1, 2, 3, 4].map((i) => (
        <div key={i} style={{ position: "absolute", left: SAFE.left, top: 360 + i * 240, width: CONTENT_W }}>
          <Rule progress={p(frame, 4 + i * 3, 24)} color={rgba(C.white, 0.1)} length={CONTENT_W} thickness={2} />
        </div>
      ))}
      <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 14, backgroundColor: style.accent, transform: `scaleY(${p(frame, 0, 20)})`, transformOrigin: "50% 0%" }} />
    </AbsoluteFill>
  );
};

// ── Hooks ────────────────────────────────────────────────────────────────
const HookLayer: React.FC<{
  hook: HookStyle;
  title: string;
  tokens: ReturnType<typeof tokenize>;
  style: SectionStyle;
  detail: string;
  exitAt: number;
  hasMedia: boolean;
  // Doble plano: el hook vive debajo del video, sin tapar su contenido.
  region: { top: number; bottom: number } | null;
}> = ({ title, tokens, style, detail, exitAt, hasMedia, region }) => {
  const frame = useCurrentFrame();
  const accent = style.accent;
  const hookBottom = SAFE.bottom - 20;
  const persist = !hasMedia; // sin media el titular grande se queda
  const labelH = 70;
  const regionH = region ? region.bottom - region.top - labelH : 0;
  const place: React.CSSProperties = region
    ? { position: "absolute", left: SAFE.left, top: region.top, width: CONTENT_W }
    : { position: "absolute", left: SAFE.left, bottom: REEL.h - hookBottom, width: CONTENT_W };

  const big = fit({
    text: title,
    maxWidth: CONTENT_W,
    maxHeight: region ? regionH : 640,
    min: region ? 58 : 72,
    max: 112,
    weight: 800,
    lh: 0.98,
    stretch: "semi-condensed",
    tracking: -0.015,
    maxLines: 6,
  });
  return (
    <div style={place}>
      <div style={{ marginBottom: 26 }}>
        <SectionLabel label={style.label} detail={detail} accent={accent} color={C.white} size={26} progress={p(frame, 10, 16)} />
      </div>
      <Headline
        fitted={big}
        tokens={tokens}
        color={C.white}
        accent={accent}
        weight={800}
        stretch="semi-condensed"
        tracking={-0.015}
        mode="split"
        start={10}
        stagger={5}
        // La caja entra recién cuando todas las líneas terminaron de armarse.
        highlightAt={Math.min(10 + big.lines.length * 5 + 14, Math.max(0, exitAt - 16))}
        exitAt={persist ? undefined : exitAt}
        exitDuration={10}
      />
    </div>
  );
};

// ── Titular compacto (estado C) ──────────────────────────────────────────
const CompactHeadline: React.FC<{
  layout: StageLayout;
  fitted: ReturnType<typeof compactFitFor>;
  tokens: ReturnType<typeof tokenize>;
  style: SectionStyle;
  detail: string;
  visible: number;
  enterAt: number;
  hasMedia: boolean;
}> = ({ layout, fitted, tokens, style, detail, visible, enterAt, hasMedia }) => {
  if (!hasMedia) return null;
  if (visible <= 0.001) return null;
  const ruleW = 120;
  const inner = (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: 18, marginBottom: 22 }}>
        <Rule progress={visible} color={style.accent} length={ruleW} thickness={6} />
        <SectionLabel label={style.label} detail={detail} accent={style.accent} color={C.white} size={22} progress={visible} />
      </div>
      <Headline
        fitted={fitted}
        tokens={tokens}
        color={C.white}
        accent={style.accent}
        weight={TYPE.reelCompact.weight}
        stretch={TYPE.reelCompact.stretch}
        tracking={TYPE.reelCompact.tracking}
        mode="line"
        start={enterAt}
        stagger={3}
        highlightAt={enterAt + 14}
      />
    </>
  );
  if (layout.kind === "stacked") {
    return <div style={{ position: "absolute", left: SAFE.left, top: layout.compactTop, width: CONTENT_W, opacity: Math.min(1, visible * 1.4) }}>{inner}</div>;
  }
  // Overlay: bloque sólido compacto anclado a la zona segura inferior.
  const blockH = LABEL_BLOCK + fitted.height + 64;
  return (
    <div
      style={{
        position: "absolute",
        left: SAFE.left - 24,
        bottom: REEL.h - layout.compactTop,
        width: Math.min(CONTENT_W + 48, fitted.widest + 80),
        minWidth: 520,
        height: blockH,
        padding: "30px 32px 34px",
        backgroundColor: rgba(C.ink, 0.92),
        clipPath: maskInset(visible, "bottom"),
      }}
    >
      {inner}
    </div>
  );
};

// ── Cierre de marca (estado D) ───────────────────────────────────────────
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
        <StoryV2 {...props} />
      </Sequence>
      <Sequence from={props.durationInFrames} durationInFrames={REEL_V2_OUTRO_FRAMES} premountFor={30}>
        <OutroV2 seccion={props.seccion} />
      </Sequence>
    </AbsoluteFill>
  );
};
