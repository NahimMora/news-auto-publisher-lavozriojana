import {
  AbsoluteFill,
  Easing,
  Img,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { Video } from "@remotion/media";
import { z } from "zod";
import {
  CAPTION_H_COMPACT,
  FOOTER_H,
  FOOTER_Y,
  GOLD,
  GRADIENT_BG_DARK,
  GRADIENT_FOOTER,
  GRADIENT_HEADLINE_SCRIM,
  GRADIENT_HEADLINE_SOLID,
  GRADIENT_TOP,
  H,
  HANDLE,
  HEADLINE_H,
  HEADLINE_Y,
  HOLD_END_FRAME,
  IMG_H,
  IMG_H_EXPANDED,
  IMG_Y,
  SHRINK_END_FRAME,
  SITE_URL,
  TOP_H,
  W,
  WHITE,
} from "./constants";

// `durationInFrames` no se usa dentro del componente: solo existe para que
// calculateMetadata (Root.tsx) fije la duración real del reel por prop.
export const MainSchema = z.object({
  titulo: z.string(),
  seccion: z.string(),
  assetType: z.enum(["video", "image", "none"]),
  assetFile: z.string(), // ruta relativa a public/ (p.ej. "tmp/<id>.mp4"); "" si assetType="none"
  kenBurnsVariant: z.number(), // 0/1/2 — dirección del paneo cuando assetType="image"
  durationInFrames: z.number(),
});

export type MainProps = z.infer<typeof MainSchema>;

// Composición principal: reemplaza el compositing de ffmpeg. Todo el reel (bloque
// superior, panel de video/imagen, caption animado, footer, logo) se renderiza acá en
// una sola pasada — Python solo copia el asset a public/tmp/ y llama a esta composición.
//
// El panel de video/imagen arranca del tamaño de siempre (IMG_H) y, una vez que el
// titular se leyó (HOLD_END_FRAME), crece hacia abajo hasta casi ocupar toda la pantalla
// (IMG_H_EXPANDED, llega justo hasta el footer). El caption (badge + título) se encoge en
// simultáneo: como HEADLINE_Y + HEADLINE_H == FOOTER_Y por diseño, su borde inferior queda
// SIEMPRE pegado al footer sin importar el progreso — solo se le "come" espacio por
// arriba, dando el efecto de achicarse hacia abajo hasta terminar flotando como una franja
// (scrim) sobre el propio video, en vez de ocupar un bloque aparte debajo.
export const Main: React.FC<MainProps> = ({
  titulo,
  seccion,
  assetType,
  assetFile,
  kenBurnsVariant,
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  // ── Entradas (igual que antes)
  const dividerWidth = interpolate(frame, [0, 18], [0, W], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });
  const badgeScale = interpolate(frame, [6, 20], [0.6, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.34, 1.56, 0.64, 1),
    output: "perceptual-scale",
  });
  const badgeOpacity = interpolate(frame, [6, 16], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const titleOpacity = interpolate(frame, [16, 30], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const titleTranslateY = interpolate(frame, [16, 30], [36, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });
  const footerOpacity = interpolate(frame, [20, 32], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const logoOpacity = interpolate(frame, [10, 22], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // ── Progreso único "grande → compacto"
  const shrinkProgress = interpolate(
    frame, [HOLD_END_FRAME, SHRINK_END_FRAME], [0, 1],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.bezier(0.65, 0, 0.35, 1),
    },
  );

  const videoAreaHeight = interpolate(shrinkProgress, [0, 1], [IMG_H, IMG_H_EXPANDED]);
  const captionTop = interpolate(shrinkProgress, [0, 1], [HEADLINE_Y, FOOTER_Y - CAPTION_H_COMPACT]);
  const captionHeight = interpolate(shrinkProgress, [0, 1], [HEADLINE_H, CAPTION_H_COMPACT]);
  const titleFontSize = interpolate(shrinkProgress, [0, 1], [62, 38]);
  const badgeFontSize = interpolate(shrinkProgress, [0, 1], [34, 27]);
  const captionPaddingTop = interpolate(shrinkProgress, [0, 1], [52, 24]);
  const captionGap = interpolate(shrinkProgress, [0, 1], [26, 14]);
  const badgePadY = interpolate(shrinkProgress, [0, 1], [14, 10]);
  const badgePadX = interpolate(shrinkProgress, [0, 1], [30, 22]);
  const solidOpacity = interpolate(shrinkProgress, [0, 1], [1, 0]);
  const scrimOpacity = shrinkProgress;

  // Ken Burns (solo para imagen): zoom ease-out + paneo sutil, 3 variantes.
  const kenBurnsZoom = interpolate(frame, [0, Math.max(durationInFrames, 1)], [1, 1.07], {
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.quad),
  });
  const panT = interpolate(frame, [0, Math.max(durationInFrames, 1)], [0, 1], {
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.quad),
  });
  const panX = kenBurnsVariant === 1 ? panT * -18 : 0;
  const panY = kenBurnsVariant === 2 ? panT * -18 : 0;

  return (
    <AbsoluteFill style={{ backgroundColor: "#0B0B0B" }}>
      {/* ── Panel de video/imagen: crece hacia abajo */}
      <div
        style={{
          position: "absolute",
          top: IMG_Y,
          left: 0,
          width: W,
          height: videoAreaHeight,
          overflow: "hidden",
          backgroundColor: "#000",
        }}
      >
        {assetType === "video" && (
          <>
            <Video
              src={staticFile(assetFile)}
              muted
              style={{
                position: "absolute", top: 0, left: 0, width: "100%", height: "100%",
                objectFit: "cover", filter: "blur(60px) brightness(0.5) saturate(1.3)",
                transform: "scale(1.2)",
              }}
            />
            <Video
              src={staticFile(assetFile)}
              style={{
                position: "absolute", top: "50%", left: "50%", width: "100%", height: "100%",
                transform: "translate(-50%, -50%)", objectFit: "contain",
              }}
            />
          </>
        )}
        {assetType === "image" && (
          <>
            <Img
              src={staticFile(assetFile)}
              style={{
                position: "absolute", top: 0, left: 0, width: "100%", height: "100%",
                objectFit: "cover", filter: "blur(60px) brightness(0.5) saturate(1.3)",
                transform: "scale(1.25)",
              }}
            />
            <Img
              src={staticFile(assetFile)}
              style={{
                position: "absolute", top: "50%", left: "50%", width: "100%", height: "100%",
                transform: `translate(calc(-50% + ${panX}px), calc(-50% + ${panY}px)) scale(${kenBurnsZoom})`,
                objectFit: "contain",
              }}
            />
          </>
        )}
        {assetType === "none" && (
          <div style={{ position: "absolute", inset: 0, background: GRADIENT_BG_DARK }} />
        )}

        {/* viñeta sutil para dirigir el ojo al centro */}
        <div
          style={{
            position: "absolute", inset: 0,
            background: "radial-gradient(ellipse at center, rgba(0,0,0,0) 60%, rgba(0,0,0,0.35) 100%)",
          }}
        />
      </div>

      {/* ── Bloque superior (fijo, no se anima) */}
      <div
        style={{
          position: "absolute", top: 0, left: 0, width: W, height: TOP_H,
          background: GRADIENT_TOP,
        }}
      />

      {/* ── Línea divisora animada (sweep) */}
      <div
        style={{
          position: "absolute", top: IMG_Y - 8, left: 0, width: dividerWidth, height: 8,
          backgroundColor: WHITE,
        }}
      />

      {/* ── Logo esquina superior-derecha del panel de video (posición fija) */}
      <Img
        src={staticFile("logo.png")}
        style={{
          position: "absolute", top: IMG_Y + 20, right: 24, width: 130, opacity: logoOpacity,
        }}
      />

      {/* ── Caption: encoge y termina flotando sobre el video, siempre pegado al footer */}
      <div
        style={{
          position: "absolute", top: captionTop, left: 0, width: W, height: captionHeight,
          overflow: "hidden",
        }}
      >
        <div style={{ position: "absolute", inset: 0, background: GRADIENT_HEADLINE_SOLID, opacity: solidOpacity }} />
        <div style={{ position: "absolute", inset: 0, background: GRADIENT_HEADLINE_SCRIM, opacity: scrimOpacity }} />

        <div
          style={{
            position: "absolute", left: 60, right: 60, top: 0, bottom: 0,
            display: "flex", flexDirection: "column", justifyContent: "flex-start",
            paddingTop: captionPaddingTop, gap: captionGap,
          }}
        >
          <div
            style={{
              alignSelf: "flex-start",
              opacity: badgeOpacity,
              scale: badgeScale,
              transformOrigin: "left center",
              backgroundColor: WHITE,
              borderRadius: 14,
              padding: `${badgePadY}px ${badgePadX}px`,
            }}
          >
            <div style={{ fontFamily: "Arial, sans-serif", fontWeight: 900, fontSize: badgeFontSize, color: "#8A0000" }}>
              {seccion.toUpperCase()}
            </div>
          </div>

          <div
            style={{
              opacity: titleOpacity,
              translate: `0px ${titleTranslateY}px`,
              fontFamily: "Arial, sans-serif", fontWeight: 900, fontSize: titleFontSize,
              lineHeight: 1.15, color: WHITE, textShadow: "0 3px 10px rgba(0,0,0,0.6)",
            }}
          >
            {titulo.toUpperCase()}
          </div>
        </div>
      </div>

      {/* ── Footer: posición fija, siempre visible */}
      <div
        style={{
          position: "absolute", top: FOOTER_Y, left: 0, width: W, height: H - FOOTER_Y,
          background: GRADIENT_FOOTER,
        }}
      />
      <div
        style={{
          position: "absolute", left: 60, top: FOOTER_Y + (FOOTER_H - 34) / 2, opacity: footerOpacity,
          fontFamily: "Arial, sans-serif", fontWeight: 700, fontSize: 30, color: WHITE,
        }}
      >
        {SITE_URL}
      </div>
      <div
        style={{
          position: "absolute", right: 60, top: FOOTER_Y, height: FOOTER_H,
          display: "flex", alignItems: "center", gap: 14, opacity: footerOpacity,
        }}
      >
        <div
          style={{
            width: 30, height: 30, backgroundColor: WHITE,
            maskImage: `url(${staticFile("fb_icon_base.png")})`,
            maskSize: "contain", maskRepeat: "no-repeat", maskPosition: "center",
            WebkitMaskImage: `url(${staticFile("fb_icon_base.png")})`,
            WebkitMaskSize: "contain", WebkitMaskRepeat: "no-repeat", WebkitMaskPosition: "center",
          }}
        />
        <div
          style={{
            width: 30, height: 30, backgroundColor: WHITE,
            maskImage: `url(${staticFile("ig_icon_base.png")})`,
            maskSize: "contain", maskRepeat: "no-repeat", maskPosition: "center",
            WebkitMaskImage: `url(${staticFile("ig_icon_base.png")})`,
            WebkitMaskSize: "contain", WebkitMaskRepeat: "no-repeat", WebkitMaskPosition: "center",
          }}
        />
        <div style={{ fontFamily: "Arial, sans-serif", fontWeight: 700, fontSize: 30, color: GOLD }}>
          {HANDLE}
        </div>
      </div>
    </AbsoluteFill>
  );
};
