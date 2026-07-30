// Paleta y layout — espeja utils/video_renderer.py (Python) para mantener
// consistencia visual entre el fallback estático y las piezas Remotion.

// Paleta oficial: rojo, bordó, negro, blanco y azul. Sin dorado (decisión de
// producto, ver docs/DECISIONS.md 2026-07-30 "Paleta oficial sin dorado").
export const ROJO = "#B30000";
export const BORDO = "#6E0F1A";
export const AZUL = "#2F6FB0";
export const NEGRO = "#0B0B0B";
export const FOOTER_BG = "#111111";
export const WHITE = "#FFFFFF";

// Degradados oscuros (reemplazan los bloques de color plano): más cine, más profundidad.
export const GRADIENT_TOP = "linear-gradient(135deg, #A30000 0%, #3D0000 100%)";
// Versión "grande" del bloque titular: opaca, se ve debajo del video (no hay nada detrás).
export const GRADIENT_HEADLINE_SOLID = "linear-gradient(180deg, #8A0000 0%, #3D0000 100%)";
// Versión "compacta": scrim semi-transparente que flota SOBRE el video, oscurece solo
// hacia abajo para que el texto se lea sin tapar el video de más.
export const GRADIENT_HEADLINE_SCRIM =
  "linear-gradient(180deg, rgba(15,10,10,0) 0%, rgba(20,4,4,0.55) 35%, rgba(15,6,6,0.88) 100%)";
export const GRADIENT_BG_DARK = "linear-gradient(180deg, #161616 0%, #050505 100%)";
// Footer: degradado con más recorrido (no un gris casi plano) — insinúa el rojo de marca
// arriba y se apaga a negro abajo.
export const GRADIENT_FOOTER = "linear-gradient(180deg, #2A0808 0%, #150404 45%, #000000 100%)";

export const W = 1080;
export const H = 1920;
export const FPS = 30;

// Layout — idéntico a _TOP_H, _IMG_Y, etc. en video_renderer.py para el bloque superior,
// que no se anima.
export const TOP_H = 285;
export const IMG_Y = 285;

// Panel de video/imagen: arranca con la altura de hoy y crece hacia abajo hasta ocupar
// prácticamente toda la pantalla (deja solo el footer fijo al final), dando la sensación
// de un reel 9:16 normal una vez que el titular se leyó y se compactó.
export const IMG_H = 760;
export const FOOTER_Y = 1545;
export const FOOTER_H = 90;
export const IMG_H_EXPANDED = FOOTER_Y - IMG_Y; // 1260 — el video llega hasta el footer

export const HEADLINE_Y = IMG_Y + IMG_H; // 1045 — el bloque titular arranca pegado al video
export const HEADLINE_H = 500; // alto "grande" inicial
export const CAPTION_H_COMPACT = 260; // alto de la franja compacta, flotando sobre el video

// Timing de la animación "grande → compacto" (a 30fps)
export const HOLD_END_FRAME = 75; // 2.5s mostrando el titular a tamaño completo
export const SHRINK_END_FRAME = 105; // 1s de transición hasta quedar compacto

export const SITE_URL = "www.lavozriojana.com";
export const HANDLE = "@lavozriojana";
