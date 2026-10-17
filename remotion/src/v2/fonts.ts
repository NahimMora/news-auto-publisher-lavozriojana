import { useEffect, useState } from "react";
import { continueRender, delayRender, staticFile } from "remotion";
import { V2_FONT_SANS, V2_FONT_SERIF } from "./tokens";

// Carga local (sin red) de los mismos archivos variables que V1, pero
// registrados con nombres propios y declarando el rango de ancho de Archivo
// (62–125 %). Así `fontStretch: "condensed"` usa el eje wdth real en vez de
// una compresión sintética, y la carga de V1 (shared/fonts.ts) queda intacta.
const FILES: { family: string; file: string; style: "normal" | "italic"; stretch?: string }[] = [
  { family: V2_FONT_SANS, file: "Archivo[wdth,wght].ttf", style: "normal", stretch: "62% 125%" },
  { family: V2_FONT_SANS, file: "Archivo-Italic[wdth,wght].ttf", style: "italic", stretch: "62% 125%" },
  { family: V2_FONT_SERIF, file: "SourceSerif4[opsz,wght].ttf", style: "normal" },
  { family: V2_FONT_SERIF, file: "SourceSerif4-Italic[opsz,wght].ttf", style: "italic" },
];

let promise: Promise<void> | null = null;

function loadOnce(): Promise<void> {
  if (!promise) {
    promise = (async () => {
      if (typeof document === "undefined" || typeof FontFace === "undefined") return;
      await Promise.all(
        FILES.map(async ({ family, file, style, stretch }) => {
          const face = new FontFace(family, `url(${staticFile(`fonts/${file}`)})`, {
            weight: "1 999",
            style,
            ...(stretch ? { stretch } : {}),
          });
          const loaded = await face.load();
          (document.fonts as FontFaceSet).add(loaded);
        }),
      );
    })();
  }
  return promise;
}

// Igual que V1: bloquea la captura hasta que las fuentes están registradas y
// hubo un ciclo completo de render+paint, para que la medición de v2/fit.ts
// use las métricas reales y no las del fallback.
export function useV2FontsReady(): boolean {
  const [ready, setReady] = useState(false);
  const [handle] = useState(() => delayRender("V2: cargando Archivo / Source Serif 4 (local)"));

  useEffect(() => {
    let cancelled = false;
    loadOnce()
      .catch((err) => {
        console.error("V2: no se pudieron cargar las fuentes locales", err);
      })
      .then(() => {
        if (cancelled) return undefined;
        setReady(true);
        return new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
      })
      .then(() => {
        if (!cancelled) continueRender(handle);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return ready;
}
