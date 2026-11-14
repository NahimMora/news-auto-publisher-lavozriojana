// Historia "Mandanos tu noticia" (WA-D4 aprobado en la mesa de formatos,
// 2026-11-14): pantalla bloqueada con la notificación → chat de WhatsApp
// continuo (llegan los mensajes, el vecino escribe y manda una foto) →
// llamado con el número, qué mandar y el botón. 1080×1920, 30 fps, 11 s.
//
// El botón está dibujado: el sticker de enlace de instagrapi es invisible y
// va encima (LINK_BOX en utils/wa_aportes_story.py tiene que coincidir con
// BUTTON_* de acá). La foto del chat es un adjunto genérico (ícono de
// cámara), nunca una foto real de una nota presentada como aporte.
import React from "react";
import { AbsoluteFill, Audio, Img, Sequence, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { z } from "zod";
import { useV2FontsReady } from "../fonts";
import { V2_FONT_SANS } from "../tokens";

export const WA_STORY_FPS = 30;
export const WA_STORY_FRAMES = 330;
const S1 = 57; // pantalla bloqueada (1,9 s)
const S2 = 150; // chat (5,0 s)
// Botón (coordenadas del lienzo): utils/wa_aportes_story.py::LINK_BOX.
export const BUTTON_TOP = 1270;
export const BUTTON_H = 160;
export const BUTTON_SIDE = 70;

const WA = "#25D366";
const WA_INK = "#073B1E";

export const WaAportesStorySchema = z.object({
  question: z.string(),
  sub: z.string(),
  me: z.string(),
  clock: z.string(),
  number: z.string(),
  backdropFile: z.string(),
  sfx: z.boolean(),
});
export type WaAportesStoryProps = z.infer<typeof WaAportesStorySchema>;

const WaIcon: React.FC<{ color: string; size: number }> = ({ color, size }) => (
  <svg viewBox="0 0 32 32" style={{ width: size, height: size, display: "block" }} aria-hidden>
    <path
      fill={color}
      d="M16 3a13 13 0 0 0-11.2 19.6L3 29l6.6-1.7A13 13 0 1 0 16 3zm0 23.6a10.6 10.6 0 0 1-5.4-1.5l-.4-.2-3.9 1 1-3.8-.2-.4A10.6 10.6 0 1 1 16 26.6zm5.8-7.9c-.3-.2-1.9-.9-2.2-1s-.5-.2-.7.2-.8 1-1 1.2-.4.2-.7.1a8.7 8.7 0 0 1-4.3-3.8c-.3-.6.3-.5.9-1.7a.6.6 0 0 0 0-.5l-1-2.4c-.3-.6-.5-.5-.7-.5h-.6a1.2 1.2 0 0 0-.9.4 3.6 3.6 0 0 0-1.1 2.7 6.3 6.3 0 0 0 1.3 3.3 14.4 14.4 0 0 0 5.5 4.9c2 .9 2.8.9 3.8.8a3.2 3.2 0 0 0 2.1-1.5 2.6 2.6 0 0 0 .2-1.5c-.1-.2-.3-.3-.6-.4z"
    />
  </svg>
);

// Aparición con resorte a partir de `at` segundos dentro de la escena.
const usePop = (at: number) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - at * fps, fps, config: { damping: 13, stiffness: 170, mass: 0.7 } });
  return { opacity: Math.min(1, p * 1.4), transform: `scale(${0.6 + 0.4 * p})` };
};
const useRise = (at: number, dist = 40) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - at * fps, fps, config: { damping: 16, stiffness: 140 } });
  return { opacity: p, transform: `translateY(${(1 - p) * dist}px)` };
};

const Sfx: React.FC<{ at: number; src: string; volume?: number; on: boolean }> = ({ at, src, volume = 0.5, on }) =>
  on ? (
    <Sequence from={Math.round(at * WA_STORY_FPS)} layout="none">
      <Audio src={staticFile(src)} volume={volume} />
    </Sequence>
  ) : null;

const Backdrop: React.FC<{ file: string }> = ({ file }) => {
  const frame = useCurrentFrame();
  const scale = 1.12 + frame * 0.0006;
  return (
    <AbsoluteFill style={{ background: "radial-gradient(120% 80% at 50% 30%, #1d4d34 0%, #0B141A 70%)" }}>
      {file ? (
        <Img
          src={staticFile(file)}
          style={{ position: "absolute", inset: -80, width: "calc(100% + 160px)", height: "calc(100% + 160px)", objectFit: "cover", filter: "blur(28px) brightness(.5)", transform: `scale(${scale})` }}
        />
      ) : null}
    </AbsoluteFill>
  );
};

const LockScreen: React.FC<WaAportesStoryProps> = (p) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const drop = spring({ frame: frame - 0.15 * fps, fps, config: { damping: 14, stiffness: 150 } });
  const head = useRise(0.55, 60);
  return (
    <AbsoluteFill>
      <Backdrop file={p.backdropFile} />
      <div style={{ position: "absolute", left: 0, right: 0, top: 330, textAlign: "center", color: "#fff", fontWeight: 300, fontSize: 200, letterSpacing: -4 }}>{p.clock}</div>
      <div
        style={{
          position: "absolute", left: 50, right: 50, top: 620, background: "rgba(245,245,245,.93)", color: "#111", borderRadius: 40,
          padding: "30px 34px", display: "flex", gap: 26, alignItems: "center", boxShadow: "0 20px 50px rgba(0,0,0,.4)",
          opacity: drop, transform: `translateY(${(1 - drop) * -160}px)`,
        }}
      >
        <span style={{ width: 96, height: 96, borderRadius: 22, background: WA, display: "flex", alignItems: "center", justifyContent: "center", flex: "none" }}>
          <WaIcon color="#fff" size={66} />
        </span>
        <div>
          <div style={{ fontWeight: 800, fontSize: 40 }}>
            La Voz Riojana <span style={{ fontWeight: 500, color: "#666", fontSize: 32 }}>· ahora</span>
          </div>
          <div style={{ fontSize: 42 }}>{p.question}</div>
        </div>
      </div>
      <div style={{ position: "absolute", left: 70, right: 70, top: 1060, color: "#fff", fontWeight: 900, fontStretch: "75%", fontSize: 112, lineHeight: 1.02, textShadow: "0 6px 30px rgba(0,0,0,.6)", ...head }}>
        {p.question}
      </div>
    </AbsoluteFill>
  );
};

const ChatHeader: React.FC = () => (
  <>
    <AbsoluteFill style={{ background: "#0B141A" }} />
    <AbsoluteFill style={{ opacity: 0.06, backgroundImage: "radial-gradient(#fff 2px, transparent 2.5px)", backgroundSize: "46px 46px" }} />
    <div style={{ position: "absolute", left: 0, right: 0, top: 250, height: 150, background: "#1F2C34", display: "flex", alignItems: "center", gap: 24, padding: "0 50px", color: "#E9EDEF" }}>
      <Img src={staticFile("logo.png")} style={{ width: 96, height: 96, borderRadius: "50%", background: "#fff", objectFit: "contain" }} />
      <div>
        <div style={{ fontWeight: 800, fontSize: 46 }}>La Voz Riojana</div>
        <div style={{ fontSize: 30, color: "#8696A0" }}>en línea</div>
      </div>
    </div>
  </>
);

const Bubble: React.FC<{ at: number; me?: boolean; time: string; children: React.ReactNode }> = ({ at, me, time, children }) => {
  const frame = useCurrentFrame();
  const style = usePop(at);
  if (frame < at * WA_STORY_FPS) return null;
  return (
    <div
      style={{
        alignSelf: me ? "flex-end" : "flex-start", maxWidth: 820, background: me ? "#005C4B" : "#202C33", color: "#E9EDEF", fontSize: 44, lineHeight: 1.22,
        padding: "18px 26px 34px", borderRadius: 26, position: "relative", transformOrigin: me ? "right bottom" : "left bottom",
        ...(me ? { borderTopRightRadius: 6 } : { borderTopLeftRadius: 6 }), ...style,
      }}
    >
      {children}
      <span style={{ position: "absolute", right: 20, bottom: 8, fontSize: 22, color: "#8696A0" }}>
        {time} {me ? <b style={{ color: "#53BDEB" }}>✓✓</b> : null}
      </span>
    </div>
  );
};

const Chat: React.FC<WaAportesStoryProps> = (p) => {
  const frame = useCurrentFrame();
  const t = frame / WA_STORY_FPS;
  const typed = t < 0.95 ? "" : t >= 2.0 ? "" : p.me.slice(0, Math.round(interpolate(t, [0.95, 1.8], [0, p.me.length], { extrapolateRight: "clamp" })));
  const photo = usePop(2.6);
  return (
    <AbsoluteFill style={{ color: "#E9EDEF" }}>
      <ChatHeader />
      <div style={{ position: "absolute", left: 44, right: 44, top: 420, bottom: 500, display: "flex", flexDirection: "column", justifyContent: "flex-end", gap: 24, overflow: "hidden" }}>
        <Bubble at={0.05} time={p.clock}>{p.question}</Bubble>
        <Bubble at={0.55} time={p.clock}>{p.sub}</Bubble>
        <Bubble at={2.0} me time={p.clock}>{p.me}</Bubble>
        {frame >= 2.6 * WA_STORY_FPS ? (
          <div style={{ alignSelf: "flex-end", width: 520, background: "#005C4B", borderRadius: 26, padding: 10, transformOrigin: "right bottom", ...photo }}>
            <div style={{ height: 290, borderRadius: 18, background: "linear-gradient(135deg,#2a3942,#1b262d)", display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 10 }}>
              <span style={{ fontSize: 110 }}>📷</span>
              <span style={{ fontSize: 30, color: "#AEBAC1" }}>Foto</span>
            </div>
          </div>
        ) : null}
        <Bubble at={3.5} time={p.clock}>¡Gracias por avisar! 🙌</Bubble>
      </div>
      <div style={{ position: "absolute", left: 30, right: 150, bottom: 360, height: 110, background: "#202C33", borderRadius: 60, display: "flex", alignItems: "center", padding: "0 40px", fontSize: 40, overflow: "hidden", whiteSpace: "nowrap" }}>
        <span style={{ color: typed ? "#E9EDEF" : "#8696A0" }}>{typed || "Mensaje"}</span>
        <i style={{ display: "inline-block", width: 4, height: 52, background: WA, marginLeft: 4, opacity: Math.floor(frame / 14) % 2 ? 0 : 1 }} />
      </div>
      <div style={{ position: "absolute", right: 30, bottom: 360, width: 110, height: 110, borderRadius: "50%", background: WA, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 48, color: WA_INK }}>➤</div>
    </AbsoluteFill>
  );
};

const Chip: React.FC<{ at: number; icon: string; label: string }> = ({ at, icon, label }) => {
  const style = usePop(at);
  return (
    <span style={{ background: "#1F2C34", border: `3px solid ${WA}`, borderRadius: 50, padding: "14px 26px", fontWeight: 800, fontSize: 44, ...style }}>
      {icon} {label}
    </span>
  );
};

const CallToAction: React.FC<WaAportesStoryProps> = (p) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const title = useRise(0, 50);
  const num = usePop(0.25);
  const btn = usePop(1.2);
  const hint = useRise(1.9, 30);
  const pulse = frame > 1.7 * fps ? 1 + 0.035 * Math.sin(((frame - 1.7 * fps) / fps) * Math.PI * 2.2) : 1;
  // Dedo: entra a 1,6 s y toca el botón (baja, presiona, vuelve).
  const fIn = spring({ frame: frame - 1.6 * fps, fps, config: { damping: 15, stiffness: 120 } });
  const cycle = ((frame - 1.6 * fps) / fps) % 1.1;
  const press = frame > 1.9 * fps ? Math.max(0, Math.sin((cycle / 1.1) * Math.PI * 2)) : 0;
  return (
    <AbsoluteFill style={{ color: "#fff" }}>
      <ChatHeader />
      <AbsoluteFill style={{ background: "rgba(11,20,26,.86)" }} />
      <div style={{ position: "absolute", left: 70, right: 70, top: 420, display: "flex", flexDirection: "column", alignItems: "center", gap: 44, textAlign: "center" }}>
        <div style={{ fontWeight: 900, fontStretch: "75%", fontSize: 112, lineHeight: 1.0, ...title }}>Escribinos por WhatsApp</div>
        <div style={{ display: "flex", alignItems: "center", gap: 22, background: "#fff", color: WA_INK, borderRadius: 30, padding: "22px 38px", ...num }}>
          <WaIcon color={WA} size={84} />
          <span style={{ fontWeight: 900, fontStretch: "72%", fontSize: 100, letterSpacing: "0.01em" }}>{p.number}</span>
        </div>
        <div style={{ display: "flex", gap: 18, flexWrap: "wrap", justifyContent: "center" }}>
          <Chip at={0.55} icon="📷" label="Fotos" />
          <Chip at={0.75} icon="🎥" label="Videos" />
          <Chip at={0.95} icon="📍" label="Dónde pasó" />
        </div>
      </div>
      <div
        style={{
          position: "absolute", left: BUTTON_SIDE, right: BUTTON_SIDE, top: BUTTON_TOP, height: BUTTON_H, background: WA, color: WA_INK, borderRadius: 80,
          display: "flex", alignItems: "center", justifyContent: "center", gap: 22, fontWeight: 900, fontStretch: "80%", fontSize: 58,
          boxShadow: "0 18px 40px rgba(0,0,0,.45)", opacity: btn.opacity, transform: `${btn.transform} scale(${pulse * (1 - press * 0.05)})`,
        }}
      >
        <WaIcon color={WA_INK} size={76} />
        MANDANOS TU NOTICIA
      </div>
      <div
        style={{
          position: "absolute", left: 870, top: BUTTON_TOP + 92, fontSize: 104, lineHeight: 1, filter: "drop-shadow(0 6px 10px rgba(0,0,0,.5))",
          opacity: fIn, transform: `translate(${(1 - fIn) * 60 + (1 - press) * 18}px, ${(1 - fIn) * 140 + (1 - press) * 26}px) rotate(${(1 - press) * 8}deg)`,
        }}
      >
        👆
      </div>
      <div style={{ position: "absolute", left: 70, right: 70, top: BUTTON_TOP + BUTTON_H + 70, textAlign: "center", fontSize: 40, fontWeight: 700, color: "#B9C3C9", ...hint }}>
        Guardá el número en tus contactos
      </div>
    </AbsoluteFill>
  );
};

export const WaAportesStory: React.FC<WaAportesStoryProps> = (props) => {
  useV2FontsReady();
  const on = props.sfx;
  return (
    <AbsoluteFill style={{ fontFamily: V2_FONT_SANS, background: "#0B141A" }}>
      <Sequence durationInFrames={S1}>
        <LockScreen {...props} />
      </Sequence>
      <Sequence from={S1} durationInFrames={S2}>
        <Chat {...props} />
      </Sequence>
      <Sequence from={S1 + S2}>
        <CallToAction {...props} />
      </Sequence>
      <Sfx on={on} at={0.2} src="newscast/ping.mp3" />
      <Sfx on={on} at={S1 / WA_STORY_FPS + 0.05} src="newscast/ping.mp3" volume={0.35} />
      <Sfx on={on} at={S1 / WA_STORY_FPS + 0.55} src="newscast/ping.mp3" volume={0.35} />
      <Sfx on={on} at={S1 / WA_STORY_FPS + 2.0} src="newscast/tick.mp3" />
      <Sfx on={on} at={S1 / WA_STORY_FPS + 2.6} src="newscast/tick.mp3" />
      <Sfx on={on} at={S1 / WA_STORY_FPS + 3.5} src="newscast/ping.mp3" volume={0.35} />
      <Sfx on={on} at={(S1 + S2) / WA_STORY_FPS} src="newscast/whoosh.mp3" volume={0.4} />
      <Sfx on={on} at={(S1 + S2) / WA_STORY_FPS + 1.2} src="newscast/impact.mp3" volume={0.35} />
    </AbsoluteFill>
  );
};

export const WA_STORY_DEFAULTS: WaAportesStoryProps = {
  question: "¿Viste algo que merece ser noticia?",
  sub: "Mandanos fotos, videos y qué pasó 📲",
  me: "¡Cayó granizo en el centro! 😮",
  clock: "20:04",
  number: "380 492-2704",
  backdropFile: "",
  sfx: true,
};
