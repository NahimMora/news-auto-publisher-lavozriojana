// Presets de movimiento V2. Todo es función pura del frame (determinístico
// entre preview y render): nada de Date, Math.random ni timers del navegador.
import { Easing, interpolate, spring } from "remotion";

export const EASE = {
  // Salida exponencial: entradas editoriales rápidas que se asientan suave.
  out: Easing.bezier(0.16, 1, 0.3, 1),
  // Transiciones de layout: aceleran y frenan de forma simétrica.
  inOut: Easing.bezier(0.65, 0, 0.35, 1),
  // Cortes de máscara: arranque seco, sin rebote.
  snap: Easing.bezier(0.7, 0, 0.2, 1),
  // Movimiento de cámara: muy lento al final.
  camera: Easing.bezier(0.25, 0.1, 0.1, 1),
  in: Easing.bezier(0.5, 0, 0.75, 0),
};

export const SPRING = {
  punch: { damping: 15, stiffness: 240, mass: 0.6 },
  settle: { damping: 26, stiffness: 120, mass: 1 },
  soft: { damping: 30, stiffness: 80, mass: 1 },
} as const;

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

// Progreso 0→1 entre `start` y `start + duration` con easing.
export function p(frame: number, start: number, duration: number, easing = EASE.out): number {
  if (duration <= 0) return frame >= start ? 1 : 0;
  return interpolate(frame, [start, start + duration], [0, 1], { ...clamp, easing });
}

export function sp(frame: number, start: number, fps: number, config: (typeof SPRING)[keyof typeof SPRING], durationInFrames?: number): number {
  return spring({ frame: frame - start, fps, config, durationInFrames });
}

export function mix(t: number, a: number, b: number): number {
  return a + (b - a) * t;
}

export { clamp };
