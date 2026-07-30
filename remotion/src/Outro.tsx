import {
  AbsoluteFill,
  CanvasImage,
  Easing,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { glow } from "@remotion/effects/glow";
import { shine } from "@remotion/effects/shine";
import { GRADIENT_BG_DARK, HANDLE, ROJO, SITE_URL, WHITE } from "./constants";

// Outro de branding LVR — se concatena al final de cada reel.
// Duración pensada para 90 frames (3s a 30fps), ver Root.tsx.
export const Outro: React.FC = () => {
  const frame = useCurrentFrame();
  const { width, durationInFrames } = useVideoConfig();

  const barWidth = interpolate(frame, [0, 22], [0, width], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });

  const logoScale = interpolate(frame, [4, 22], [0.82, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.34, 1.56, 0.64, 1),
    output: "perceptual-scale",
  });

  const logoOpacity = interpolate(frame, [4, 18], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Barrido de brillo sobre el logo, una vez, después de que termina de entrar
  const shineProgress = interpolate(frame, [24, 58], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.quad),
  });

  const textOpacity = interpolate(frame, [24, 38], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const textTranslateY = interpolate(frame, [24, 38], [22, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });

  const iconsOpacity = interpolate(frame, [34, 48], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const fadeOut = interpolate(
    frame,
    [durationInFrames - 18, durationInFrames - 1],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  return (
    <AbsoluteFill
      style={{
        background: GRADIENT_BG_DARK,
        opacity: fadeOut,
      }}
    >
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          width: barWidth,
          height: 12,
          backgroundColor: ROJO,
        }}
      />
      <div
        style={{
          position: "absolute",
          bottom: 0,
          right: 0,
          width: barWidth,
          height: 12,
          backgroundColor: ROJO,
        }}
      />

      <AbsoluteFill
        style={{
          alignItems: "center",
          justifyContent: "center",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <CanvasImage
          src={staticFile("logo.png")}
          width={320}
          height={320}
          style={{
            opacity: logoOpacity,
            scale: logoScale,
          }}
          effects={[
            glow({ radius: 24, intensity: 0.4, color: WHITE }),
            shine({ progress: shineProgress, angle: 25, haloIntensity: 0.35, coreIntensity: 0.5 }),
          ]}
        />

        <div
          style={{
            marginTop: 64,
            opacity: textOpacity,
            translate: `0px ${textTranslateY}px`,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 20,
          }}
        >
          <div
            style={{
              fontFamily: "Arial, sans-serif",
              fontWeight: 700,
              fontSize: 44,
              color: WHITE,
              letterSpacing: 4,
            }}
          >
            SEGUINOS EN
          </div>
          <div
            style={{
              fontFamily: "Arial, sans-serif",
              fontWeight: 900,
              fontSize: 66,
              color: ROJO,
            }}
          >
            {HANDLE}
          </div>
          <div
            style={{
              fontFamily: "Arial, sans-serif",
              fontWeight: 600,
              fontSize: 38,
              color: WHITE,
              opacity: 0.85,
            }}
          >
            {SITE_URL}
          </div>

          {/* Íconos: Facebook e Instagram, ambos en blanco */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 22,
              marginTop: 10,
              opacity: iconsOpacity,
            }}
          >
            <div
              style={{
                width: 34,
                height: 34,
                backgroundColor: WHITE,
                maskImage: `url(${staticFile("fb_icon_base.png")})`,
                maskSize: "contain",
                maskRepeat: "no-repeat",
                maskPosition: "center",
                WebkitMaskImage: `url(${staticFile("fb_icon_base.png")})`,
                WebkitMaskSize: "contain",
                WebkitMaskRepeat: "no-repeat",
                WebkitMaskPosition: "center",
              }}
            />
            <div
              style={{
                width: 34,
                height: 34,
                backgroundColor: WHITE,
                maskImage: `url(${staticFile("ig_icon_base.png")})`,
                maskSize: "contain",
                maskRepeat: "no-repeat",
                maskPosition: "center",
                WebkitMaskImage: `url(${staticFile("ig_icon_base.png")})`,
                WebkitMaskSize: "contain",
                WebkitMaskRepeat: "no-repeat",
                WebkitMaskPosition: "center",
              }}
            />
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
