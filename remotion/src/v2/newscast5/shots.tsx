// Tomas del Noticiero V5. Cada toma es función pura del frame local: la
// transición de entrada dibuja la MISMA toma en su frame 0, así el corte
// queda invisible.
//
//   full  foto/video a pantalla completa (ampliación ≤ 2×)
//   band  franja nítida de 1150 px con la misma foto desenfocada arriba y
//         abajo; la cámara recorre la foto apaisada (paneo real, no zoom)
//   card  foto chica enmarcada en papel sobre su propio fondo desenfocado
//   map   contorno oficial de La Rioja con el pin de la localidad
import React from "react";
import { Video } from "@remotion/media";
import { AbsoluteFill, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { fit } from "../fit";
import { EASE, clamp, mix, p } from "../motion";
import { LA_RIOJA_CAPITAL as CAPITAL, LA_RIOJA_PATH, LA_RIOJA_VIEW } from "./laRioja";
import type { MediaV5, ShotV5 } from "./schema";
import { C5, GRADE, L, SANS, alpha, caps5, sans, serif } from "./theme";

type Pose = { s: number; x: number; y: number; r: number };

function pose(shot: ShotV5, frame: number): Pose {
  const t = interpolate(frame, [0, Math.max(1, shot.durationInFrames)], [0, 1], { ...clamp, easing: EASE.camera });
  const m = shot.move;
  return { s: mix(t, m.s0, m.s1), x: mix(t, m.x0, m.x1), y: mix(t, m.y0, m.y1), r: mix(t, m.r0, m.r1) };
}

const origin = (m: MediaV5) => `${(m.focusX * 100).toFixed(1)}% ${(m.focusY * 100).toFixed(1)}%`;

// Golpe de entrada de cada toma interna (reencuadre): 5 frames de 1.05 → 1.
function punch(frame: number, enabled: boolean): number {
  return enabled ? interpolate(frame, [0, 6], [1.05, 1], { ...clamp, easing: EASE.out }) : 1;
}

// maxWidth/maxHeight "none": el preflight de Tailwind del proyecto limita
// img/video al 100 % del contenedor y recortaba la franja apaisada.
const MediaEl: React.FC<{ media: MediaV5; style: React.CSSProperties }> = ({ media, style }) =>
  media.type === "video" ? (
    <Video src={staticFile(media.file)} muted trimBefore={media.sourceInFrames} objectFit="cover" style={{ maxWidth: "none", maxHeight: "none", ...style }} />
  ) : (
    <Img src={staticFile(media.file)} style={{ objectFit: "cover", maxWidth: "none", maxHeight: "none", ...style }} />
  );

// Fondo: la misma foto, desenfocada y oscura (extiende el encuadre sin
// inventar imagen).
export const BlurFill: React.FC<{ media: MediaV5; dim?: number; drift?: number }> = ({ media, dim = 0.46, drift = 0 }) => (
  <AbsoluteFill style={{ backgroundColor: C5.ink, overflow: "hidden" }}>
    {media.type === "image" ? (
      <Img
        src={staticFile(media.file)}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          objectPosition: origin(media),
          transform: `scale(${1.25 + drift * 0.04}) translateY(${drift * -14}px)`,
          filter: `blur(38px) brightness(${dim}) saturate(1.15)`,
        }}
      />
    ) : (
      <AbsoluteFill style={{ background: `radial-gradient(ellipse 90% 60% at 50% 50%, ${C5.ink3} 0%, ${C5.ink} 80%)` }} />
    )}
    <AbsoluteFill style={{ background: `linear-gradient(180deg, ${alpha(C5.ink, 0.35)} 0%, ${alpha(C5.ink, 0)} 30%, ${alpha(C5.ink, 0)} 70%, ${alpha(C5.ink, 0.5)} 100%)` }} />
  </AbsoluteFill>
);

export const PhotoShot: React.FC<{ shot: ShotV5; frame?: number; entering?: boolean }> = ({ shot, frame: given, entering = false }) => {
  const current = useCurrentFrame();
  const frame = given ?? current;
  const media = shot.media;
  if (!media) return <AbsoluteFill style={{ backgroundColor: C5.ink2 }} />;
  const { s, x, y, r } = pose(shot, frame);
  const hit = punch(frame, entering);
  if (shot.mode === "full") {
    return (
      <AbsoluteFill style={{ backgroundColor: C5.ink, overflow: "hidden" }}>
        <MediaEl
          media={media}
          style={{
            position: "absolute",
            inset: 0,
            width: "100%",
            height: "100%",
            objectPosition: origin(media),
            transform: `translate(${x * L.w}px, ${y * L.h}px) scale(${s * hit})`,
            transformOrigin: origin(media),
            filter: GRADE,
          }}
        />
      </AbsoluteFill>
    );
  }
  if (shot.mode === "band") {
    const width = (L.bandH * media.width) / media.height;
    const left = -(width - L.w) * x;
    return (
      <AbsoluteFill style={{ overflow: "hidden" }}>
        <BlurFill media={media} drift={frame / Math.max(1, shot.durationInFrames)} />
        <div
          style={{
            position: "absolute",
            left: 0,
            top: L.bandTop,
            width: L.w,
            height: L.bandH,
            overflow: "hidden",
            WebkitMaskImage: "linear-gradient(180deg, transparent 0px, black 90px, black calc(100% - 110px), transparent 100%)",
            maskImage: "linear-gradient(180deg, transparent 0px, black 90px, black calc(100% - 110px), transparent 100%)",
          }}
        >
          <MediaEl
            media={media}
            style={{
              position: "absolute",
              top: 0,
              left,
              width,
              height: L.bandH,
              transform: `scale(${s * hit})`,
              transformOrigin: origin(media),
              filter: GRADE,
            }}
          />
        </div>
      </AbsoluteFill>
    );
  }
  // card
  const aspect = media.width / media.height;
  const cardH = Math.min(L.cardMaxH, L.cardW / aspect);
  const lift = shot.framing === "detail" ? 1.035 : 1;
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <BlurFill media={media} dim={0.4} drift={frame / Math.max(1, shot.durationInFrames)} />
      {/* Diagonal de marca bajo la tarjeta (nunca detrás de la regleta). */}
      <div style={{ position: "absolute", left: -200, top: L.cardCY + cardH / 2 + 50, width: 1500, height: 18, backgroundColor: alpha(C5.red, 0.9), transform: `rotate(-6deg) translateX(${mix(p(frame, 0, 16), -400, 0)}px)` }} />
      <div
        style={{
          position: "absolute",
          left: (L.w - L.cardW) / 2,
          top: L.cardCY - cardH / 2,
          width: L.cardW,
          height: cardH,
          transform: `translate(${x * L.w}px, ${y * L.h}px) rotate(${r}deg) scale(${lift * hit})`,
          border: `12px solid ${C5.bone}`,
          boxShadow: "0 40px 90px rgba(0,0,0,0.55)",
          overflow: "hidden",
          backgroundColor: C5.ink2,
        }}
      >
        <MediaEl media={media} style={{ width: "100%", height: "100%", objectPosition: origin(media), transform: `scale(${s})`, transformOrigin: origin(media), filter: GRADE }} />
      </div>
    </AbsoluteFill>
  );
};

// ── Mapa ─────────────────────────────────────────────────────────────────

const Pin: React.FC<{ size: number; color: string }> = ({ size, color }) => (
  <svg width={size} height={size} viewBox="0 0 24 24">
    <path d="M12 2C8.1 2 5 5.1 5 9c0 5.2 7 13 7 13s7-7.8 7-13c0-3.9-3.1-7-7-7zm0 9.5A2.5 2.5 0 1 1 12 6.5a2.5 2.5 0 0 1 0 5z" fill={color} />
  </svg>
);
export { Pin };

// Rótulo arriba a la izquierda, provincia a la derecha, foto del hecho abajo
// a la izquierda: nada del mapa entra en la franja de subtítulos.
const MAP_LABEL_W = 620;

export const MapShot: React.FC<{ shot: ShotV5; frame?: number }> = ({ shot, frame: given }) => {
  const current = useCurrentFrame();
  const { fps } = useVideoConfig();
  const frame = given ?? current;
  const place = shot.place;
  if (!place) return <AbsoluteFill style={{ backgroundColor: C5.ink }} />;
  const scale = L.mapW / LA_RIOJA_VIEW.w;
  const mapH = LA_RIOJA_VIEW.h * scale;
  const left = L.w - L.mapW - 50;
  const top = L.mapTop;
  const px = left + place.x * scale;
  const py = top + place.y * scale;
  const cam = interpolate(frame, [0, Math.max(1, shot.durationInFrames)], [shot.move.s0, shot.move.s1], { ...clamp, easing: EASE.camera });
  const drop = spring({ frame: frame - 5, fps, config: { damping: 11, stiffness: 190, mass: 0.7 } });
  const ring = (k: number) => {
    const t = interpolate(frame, [10 + k * 9, 34 + k * 9], [0, 1], clamp);
    return { opacity: (1 - t) * 0.9, size: mix(t, 20, 170) };
  };
  const isCapital = Math.abs(place.x - CAPITAL.x) < 1 && Math.abs(place.y - CAPITAL.y) < 1;
  // El rótulo "Capital" sólo si no se pisa con el pin (Sanagasta está a ~40 px).
  const capitalLabel = !isCapital && Math.hypot(place.x - CAPITAL.x, place.y - CAPITAL.y) > 120;
  const name = place.label.toUpperCase();
  const nameFit = fit({ text: name, maxWidth: MAP_LABEL_W, maxHeight: 130, min: 70, max: 124, weight: 900, lh: 1, stretch: "condensed", maxLines: 1 });
  const media = shot.media;
  // "Departamento General Ortiz de Ocampo" entra en una línea sobre el mapa.
  const deptSize = Math.min(42, Math.floor(860 / Math.max(1, `Departamento ${place.department}`.length) / 0.5));
  return (
    <AbsoluteFill style={{ backgroundColor: C5.ink, overflow: "hidden" }}>
      <AbsoluteFill style={{ background: `radial-gradient(ellipse 70% 45% at ${(px / L.w) * 100}% ${(py / L.h) * 100}%, ${alpha(C5.red, 0.3)} 0%, ${alpha(C5.ink, 0)} 70%)` }} />
      <div style={{ position: "absolute", inset: 0, transform: `scale(${cam})`, transformOrigin: `${px}px ${py}px` }}>
        <svg width={L.mapW} height={mapH} viewBox={`0 0 ${LA_RIOJA_VIEW.w} ${LA_RIOJA_VIEW.h}`} style={{ position: "absolute", left, top, overflow: "visible" }}>
          <defs>
            <linearGradient id="lr-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={C5.ink3} />
              <stop offset="100%" stopColor={C5.ink2} />
            </linearGradient>
          </defs>
          <path
            d={LA_RIOJA_PATH}
            fill="url(#lr-fill)"
            stroke={alpha(C5.bone, 0.9)}
            strokeWidth={4}
            strokeLinejoin="round"
            strokeDasharray={6000}
            strokeDashoffset={mix(p(frame, 0, 16, EASE.out), 6000, 0)}
          />
          {!isCapital ? (
            <g opacity={p(frame, 6, 8)}>
              <circle cx={CAPITAL.x} cy={CAPITAL.y} r={11} fill={C5.white} />
              {capitalLabel ? (
                <text x={CAPITAL.x + 22} y={CAPITAL.y + 11} fill={alpha(C5.white, 0.8)} style={{ fontFamily: `"${SANS}"`, fontWeight: 800, fontSize: 36, letterSpacing: "0.08em" }}>
                  CAPITAL
                </text>
              ) : null}
            </g>
          ) : null}
        </svg>
        {[0, 1].map((k) => {
          const rr = ring(k);
          return (
            <div
              key={k}
              style={{ position: "absolute", left: px - rr.size / 2, top: py - rr.size / 2, width: rr.size, height: rr.size, borderRadius: "50%", border: `4px solid ${C5.red}`, opacity: rr.opacity }}
            />
          );
        })}
        <div style={{ position: "absolute", left: px - 36, top: py - 72 - mix(drop, 120, 0), opacity: Math.min(1, drop * 3) }}>
          <Pin size={72} color={C5.red} />
        </div>
      </div>
      {/* Rótulo: localidad grande y departamento en itálica de diario. */}
      <div style={{ position: "absolute", left: L.x0, top: L.insertTop - 40, display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 12 }}>
        <span style={{ ...caps5(26, alpha(C5.white, 0.75), 900, 0.2), opacity: p(frame, 2, 8) }}>Dónde pasó</span>
        <div style={{ backgroundColor: C5.red, padding: "10px 24px 2px", boxShadow: "0 20px 50px rgba(0,0,0,0.45)", clipPath: `inset(0 ${100 - p(frame, 8, 10, EASE.snap) * 100}% 0 0)` }}>
          <span style={{ ...sans(nameFit.fontSize, 900), color: C5.white, letterSpacing: "-0.005em" }}>{name}</span>
        </div>
        {place.department && !isCapital ? (
          <span style={{ ...serif(deptSize, C5.bone), textShadow: "0 4px 18px rgba(0,0,0,0.7)", opacity: p(frame, 14, 8) }}>{`Departamento ${place.department}`}</span>
        ) : null}
      </div>
      {/* La foto del hecho, chica: el "qué" no se pierde mientras se ve el "dónde". */}
      {media && media.type === "image" ? (
        <div
          style={{
            position: "absolute",
            left: L.x0,
            top: 990,
            width: 330,
            height: 220,
            border: `8px solid ${C5.bone}`,
            overflow: "hidden",
            boxShadow: "0 24px 60px rgba(0,0,0,0.6)",
            transform: `rotate(-4deg) translateY(${mix(p(frame, 12, 12, EASE.out), 80, 0)}px)`,
            opacity: p(frame, 12, 8),
          }}
        >
          <Img src={staticFile(media.file)} style={{ width: "100%", height: "100%", objectFit: "cover", objectPosition: origin(media), filter: GRADE, maxWidth: "none" }} />
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

// Textura común: grano fotográfico (tile propio, desplazado por frame de
// forma determinista) y viñeta suave.
export const Texture: React.FC<{ strength?: number }> = ({ strength = 1 }) => {
  const frame = useCurrentFrame();
  const ox = -((frame * 137) % 512);
  const oy = -((frame * 251) % 512);
  return (
    <>
      <AbsoluteFill style={{ mixBlendMode: "overlay", opacity: 0.1 * strength, pointerEvents: "none", overflow: "hidden" }}>
        <div style={{ position: "absolute", left: ox, top: oy, width: 512 * 3, height: 512 * 5, display: "flex", flexWrap: "wrap" }}>
          {Array.from({ length: 15 }).map((_, k) => (
            <Img key={k} src={staticFile("newscast/grain.png")} style={{ width: 512, height: 512 }} />
          ))}
        </div>
      </AbsoluteFill>
      <AbsoluteFill style={{ background: `radial-gradient(ellipse 85% 70% at 50% 45%, ${alpha(C5.ink, 0)} 55%, ${alpha(C5.ink, 0.45 * strength)} 100%)`, pointerEvents: "none" }} />
    </>
  );
};
