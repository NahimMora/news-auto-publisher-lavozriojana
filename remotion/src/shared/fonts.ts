import { useEffect, useState } from "react";
import { continueRender, delayRender, staticFile } from "remotion";

// Carga local de Archivo y Source Serif 4 (ambas variables, SIL OFL) sin red
// en render-time — ver remotion/public/fonts/OFL-*.txt. Se usa la API
// FontFace nativa en vez de @remotion/fonts porque ésta última no documenta
// soporte de rango de peso variable (font-weight: 100 900), que es lo que
// permite pedir distintos fontWeight (400/700/900) desde un único archivo.
const FONT_FILES: { family: string; file: string; style: "normal" | "italic" }[] = [
  { family: "Archivo", file: "Archivo[wdth,wght].ttf", style: "normal" },
  { family: "Archivo", file: "Archivo-Italic[wdth,wght].ttf", style: "italic" },
  { family: "Source Serif 4", file: "SourceSerif4[opsz,wght].ttf", style: "normal" },
  { family: "Source Serif 4", file: "SourceSerif4-Italic[opsz,wght].ttf", style: "italic" },
];

let sharedFontsPromise: Promise<void> | null = null;

function loadFontsOnce(): Promise<void> {
  if (!sharedFontsPromise) {
    sharedFontsPromise = (async () => {
      if (typeof document === "undefined" || typeof FontFace === "undefined") return;
      await Promise.all(
        FONT_FILES.map(async ({ family, file, style }) => {
          const face = new FontFace(family, `url(${staticFile(`fonts/${file}`)})`, {
            weight: "1 999",
            style,
          });
          const loaded = await face.load();
          (document.fonts as FontFaceSet).add(loaded);
        }),
      );
    })();
  }
  return sharedFontsPromise;
}

function waitTwoFrames(): Promise<void> {
  // fitText.ts mide con Canvas 2D antes de pintar: si sólo esperáramos la
  // promesa de carga de fuentes, React podría no haber re-renderizado (ni
  // el navegador re-pintado) todavía con la fuente real ya registrada, y
  // Remotion capturaría el frame con el layout calculado sobre la métrica
  // de la fuente de fallback (bug real detectado en smoke test: "capital
  // riojana" partido en dos líneas de una palabra). Dos rAF anidados
  // garantizan un ciclo completo de render+paint antes de continueRender.
  return new Promise((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
  });
}

// Hook usado por cada composición still (PremiumSlide, AutomaticInstagramCard):
// bloquea la captura de Remotion con delayRender hasta que las fuentes están
// realmente registradas Y el componente volvió a renderizar/pintar con
// `ready=true` — recién ahí fitText.ts mide con la tipografía real.
export function useFontsReady(): boolean {
  const [ready, setReady] = useState(false);
  const [handle] = useState(() => delayRender("Cargando tipografía Archivo / Source Serif 4 (local, sin red)"));

  useEffect(() => {
    let cancelled = false;
    loadFontsOnce()
      .catch((err) => {
        console.error("No se pudieron cargar las fuentes locales, se usa el fallback del sistema", err);
      })
      .then(() => {
        if (cancelled) return undefined;
        setReady(true);
        return waitTwoFrames();
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
