import React from "react";
import { z } from "zod";
import { ContextChip } from "./shared/editorial/ContextChip";
import { EditorialTexture } from "./shared/editorial/EditorialTexture";
import { HeadlineBlock } from "./shared/editorial/HeadlineBlock";
import { HeroMedia, HeroMediaVariant } from "./shared/editorial/HeroMedia";
import { fitText } from "./shared/fitText";
import { StillLayout } from "./shared/StillLayout";
import { PREMIUM_HEADLINE_SCALE, PREMIUM_MASTHEAD_H, PREMIUM_FOOTER_H, PREMIUM_CHROME_SCALE } from "./PremiumSlide";
import { FONT_DISPLAY, MODES, ModeTokens, TYPE, WEIGHT, modeFromSection } from "./shared/designSystem";

// Card automática para noticias scrapeadas / publicaciones personalizadas —
// v2 "Editorial Cinemática Riojana": tres tratamientos fotográficos
// explícitos en vez de un único crop full-bleed. `imageTreatment` es
// compatible hacia atrás: "auto" (default) preserva el comportamiento
// previo (full-bleed cuando hay foto), así que ningún caller existente
// necesita cambiar. Ver shared/editorial/HeroMedia.tsx para el detalle de
// cada tratamiento y docs/DECISIONS.md "Editorial Cinemática Riojana" /
// dirección de arte v2.
//
// Comparte masthead/footer/tipografía con el carrusel premium (mismas
// constantes PREMIUM_*, ver PremiumSlide.tsx) — una pieza de una sola
// imagen debe leerse igual de sólida que una placa del carrusel. Nunca usa
// `showSwipeCue`/`total`: es una pieza única, no hay nada que deslizar.
// Footer con firma social (`showSocialFooter`) en vez de crédito de fuente
// — feedback: "añadí los elementos del footer como redes sociales, url".
export const AUTOMATIC_IG_W = 1080;
export const AUTOMATIC_IG_H = 1350;

const AutoHeadlineBlock: React.FC<React.ComponentProps<typeof HeadlineBlock>> = (props) => (
  <HeadlineBlock {...props} fontScale={PREMIUM_HEADLINE_SCALE} />
);

export const AutomaticInstagramCardSchema = z.object({
  titulo: z.string(),
  seccion: z.string(),
  assetFile: z.string().default(""),
  // Señal barata (media_library.py ya guarda width/height): permite variar
  // la composición según orientación de la foto sin volver a abrirla en
  // Remotion.
  assetOrientation: z.enum(["landscape", "portrait", "square"]).optional(),
  highlightTerms: z.array(z.string()).default([]),
  // Completados por IA (openIA/caption_generator.py::generate_locality_and_deck,
  // ver docs/DECISIONS.md) — nunca inventados si el texto no los sustenta.
  // "locality": chip de lugar (p.ej. "Chilecito"), vacío si el texto no
  // nombra una localidad riojana concreta. "deck": bajada corta ANTES del
  // título (contexto/gancho, no repite el título).
  locality: z.string().default(""),
  deck: z.string().default(""),
  // "auto" = photographic_full_bleed cuando hay imagen (comportamiento
  // previo, sin cambios para callers existentes). Los otros tres valores
  // son selección EXPLÍCITA del caller — nunca se infiere con OCR/IA acá.
  imageTreatment: z
    .enum(["auto", "photographic_full_bleed", "editorial_frame", "branded_poster"])
    .default("auto"),
  // La mejora pedida desde la pestaña Publicaciones es explícita: el lote
  // automático conserva su geometría y tipografía previas.
  publicationStyle: z.enum(["automatic", "manual_publication"]).default("automatic"),
});

export type AutomaticInstagramCardProps = z.infer<typeof AutomaticInstagramCardSchema>;

const CONTENT_H = AUTOMATIC_IG_H - PREMIUM_MASTHEAD_H - PREMIUM_FOOTER_H;
// El lote conserva los 810px históricos. En Publicaciones, la imagen cubre
// hasta el comienzo más bajo posible del panel; el panel se pinta encima y
// calcula su altura según el texto (ver FullBleedBody).
const AUTOMATIC_PHOTO_H = Math.round(AUTOMATIC_IG_H * 0.6);
const MANUAL_PHOTO_MIN_H = 700;
const MANUAL_PANEL_MIN_H = 260;
const MANUAL_PANEL_MAX_H = CONTENT_H - (MANUAL_PHOTO_MIN_H - PREMIUM_MASTHEAD_H);
const MANUAL_PHOTO_MAX_H = CONTENT_H - MANUAL_PANEL_MIN_H + PREMIUM_MASTHEAD_H;
// Piso excepcional: sólo se alcanza con entradas patológicas (p.ej. una
// palabra sin espacios de 120 caracteres). El auto-fit mantiene el mayor
// tamaño posible para cualquier título normal.
const MANUAL_TITLE_MIN_FONT_SIZE = 32;

// Alto aproximado de ContextChip (padding 12px arriba/abajo + fuente 29px +
// borde) — se resta del presupuesto del título junto con el `gap` cuando
// hay localidad, si no el chip se suma sin reservarle lugar y el bloque
// total (chip + gap + título) puede terminar más alto que el panel,
// desbordando hacia la foto o el footer (bug real: "el título se
// sobrepone al footer").
const CHIP_H = 68;

function resolveVariant(treatment: string, hasImage: boolean): HeroMediaVariant {
  if (!hasImage) return "full_bleed";
  if (treatment === "editorial_frame") return "framed";
  if (treatment === "branded_poster") return "poster";
  return "full_bleed"; // "auto" | "photographic_full_bleed"
}

export const AutomaticInstagramCard: React.FC<AutomaticInstagramCardProps> = ({
  titulo,
  seccion,
  assetFile,
  assetOrientation,
  highlightTerms,
  locality,
  deck,
  imageTreatment,
  publicationStyle,
}) => {
  const mode = MODES[modeFromSection(seccion)];
  const hasImage = Boolean(assetFile);
  const variant = resolveVariant(imageTreatment, hasImage);
  const manualPublication = publicationStyle === "manual_publication";
  const photoH = manualPublication ? MANUAL_PHOTO_MAX_H : AUTOMATIC_PHOTO_H;

  const frameH = assetOrientation === "portrait" ? 860 : assetOrientation === "square" ? 760 : 660;

  // full_bleed necesita pintarse debajo del masthead (bleed real hasta el
  // borde) — usa el slot `media` de StillLayout. framed/poster son
  // composiciones contenidas dentro del área de contenido: cada Body
  // arma su propio HeroMedia con la MISMA geometría que usa para ubicar
  // el titular, para no desincronizar imagen y texto (ver FramedBody/
  // PosterBody más abajo).
  const media: React.ReactNode =
    hasImage && variant === "full_bleed" ? (
      <HeroMedia assetFile={assetFile} mode={mode} variant="full_bleed" top={0} height={photoH} width={AUTOMATIC_IG_W} scrim="none" />
    ) : null;

  return (
    <StillLayout
      width={AUTOMATIC_IG_W}
      height={AUTOMATIC_IG_H}
      mode={mode}
      section={seccion}
      media={media}
      mastheadHeight={PREMIUM_MASTHEAD_H}
      footerHeight={PREMIUM_FOOTER_H}
      chromeScale={PREMIUM_CHROME_SCALE}
      showSocialFooter
      boxedSection={manualPublication}
    >
      {!hasImage && <NoImageBody titulo={titulo} highlightTerms={highlightTerms} mode={mode} locality={locality} deck={deck} manualPublication={manualPublication} />}

      {hasImage && variant === "full_bleed" && (
        <FullBleedBody titulo={titulo} highlightTerms={highlightTerms} mode={mode} locality={locality} deck={deck} manualPublication={manualPublication} photoH={photoH} />
      )}

      {hasImage && variant === "framed" && (
        <FramedBody titulo={titulo} highlightTerms={highlightTerms} assetFile={assetFile} frameH={frameH} mode={mode} manualPublication={manualPublication} />
      )}

      {hasImage && variant === "poster" && (
        <PosterBody titulo={titulo} highlightTerms={highlightTerms} assetFile={assetFile} mode={mode} manualPublication={manualPublication} />
      )}
    </StillLayout>
  );
};

// ── Sin imagen: mismo criterio que el fallback sin imagen de CoverSlide
// (PremiumSlide.tsx) — textura de marca en vez de un hueco negro, contenido
// centrado con chip de lugar + bajada + título, siempre a ancho completo y
// alineado a la izquierda (Crónica/Editorial no se diferencian acá, igual
// que en Premium; sólo "Datos" cambia de composición, y las cards
// automáticas no usan ese modo).
const NoImageBody: React.FC<{
  titulo: string;
  highlightTerms: string[];
  mode: ModeTokens;
  locality: string;
  deck: string;
  manualPublication: boolean;
}> = ({
  titulo,
  highlightTerms,
  mode,
  locality,
  deck,
  manualPublication,
}) => {
  const pad = mode.pad;
  const width = AUTOMATIC_IG_W - pad * 2;
  const gap = 18;
  const chipReserve = locality ? CHIP_H + gap : 0;
  return (
    <div style={{ position: "absolute", inset: 0 }}>
      <EditorialTexture mode={mode} zone="full" width={AUTOMATIC_IG_W} height={AUTOMATIC_IG_H} />
      <div style={{ position: "absolute", inset: 0, padding: pad, display: "flex", flexDirection: "column", justifyContent: "center", gap, overflow: "hidden" }}>
        {locality ? <ContextChip mode={mode} label={locality} /> : null}
        <AutoHeadlineBlock
          mode={mode}
          title={titulo}
          deck={deck}
          highlightTerms={highlightTerms}
          width={width}
          maxHeight={CONTENT_H - pad * 2 - chipReserve}
          maxLines={5}
          minFontSize={manualPublication ? MANUAL_TITLE_MIN_FONT_SIZE : undefined}
        />
      </div>
    </div>
  );
};

// Foto protagonista arriba, panel de tinta sólida separado abajo con el
// titular — mismo lenguaje que la portada del carrusel premium (ver
// PremiumSlide.tsx::CoverSlide). Siempre a ancho completo y alineado a la
// izquierda (feedback: el 80%/alineado a la derecha en modo Editorial
// achicaba el título sin necesidad — Premium tampoco lo hace).
const FullBleedBody: React.FC<{
  titulo: string;
  highlightTerms: string[];
  mode: ModeTokens;
  locality: string;
  deck: string;
  manualPublication: boolean;
  photoH: number;
}> = ({
  titulo,
  highlightTerms,
  mode,
  locality,
  deck,
  manualPublication,
  photoH,
}) => {
  const pad = mode.pad;
  const width = AUTOMATIC_IG_W - pad * 2;
  // Igual que CoverSlide en PremiumSlide.tsx: este componente se renderiza
  // dentro del slot `children` de StillLayout (offseteado por el masthead),
  // pero `media` se pinta en coordenadas de canvas completo — hay que
  // restar PREMIUM_MASTHEAD_H para que el panel arranque justo donde termina
  // la foto real, si no el título calculado desborda el límite del footer.
  const targetTitleFontSize = Math.round(TYPE.titleCover.min * PREMIUM_HEADLINE_SCALE);
  const targetTitle = manualPublication
    ? fitText({
        text: titulo,
        maxWidth: width,
        maxHeight: 1000,
        minFontSize: targetTitleFontSize,
        maxFontSize: targetTitleFontSize,
        fontFamily: FONT_DISPLAY,
        fontWeight: mode.id === "editorial" ? WEIGHT.bold : WEIGHT.black,
        lineHeightRatio: TYPE.titleCover.lineHeightRatio,
        maxLines: 5,
      })
    : null;
  const targetDeckH = deck
    ? Math.round(TYPE.deck.min * PREMIUM_HEADLINE_SCALE) * TYPE.deck.lineHeightRatio * 2 + 14
    : 0;
  const targetChipH = locality ? CHIP_H + (mode.grid === "column" ? 16 : 14) : 0;
  const targetContentH = targetTitle
    ? targetTitle.lines.length * targetTitle.lineHeightPx + targetDeckH + targetChipH + 24
    : 0;
  const preliminaryPanelH = Math.max(MANUAL_PANEL_MIN_H, Math.min(MANUAL_PANEL_MAX_H, Math.ceil(targetContentH + 72)));
  const proportionalPadY = Math.max(36, Math.min(48, Math.round(preliminaryPanelH * 0.075)));
  const manualPanelH = Math.max(
    MANUAL_PANEL_MIN_H,
    Math.min(MANUAL_PANEL_MAX_H, Math.ceil(targetContentH + proportionalPadY * 2)),
  );
  const panelH = manualPublication ? manualPanelH : CONTENT_H - (photoH - PREMIUM_MASTHEAD_H);
  const panelTop = CONTENT_H - panelH;
  // En Publicaciones, el aire vertical acompaña la altura real del panel:
  // 7,5% por lado, con límites seguros. Antes se reutilizaba `mode.pad`
  // (64/80px, pensado como margen horizontal) también arriba y abajo; eso
  // encogía el bloque tipográfico y dejaba dos franjas vacías visibles.
  // El lote automático conserva exactamente el padding anterior.
  const panelPadY = manualPublication ? Math.max(36, Math.min(48, Math.round(panelH * 0.075))) : pad;
  const fadeH = 150;
  const panel = (
    <>
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          top: panelTop - fadeH,
          height: fadeH,
          background: `linear-gradient(180deg, rgba(0,0,0,0) 0%, ${mode.ink} 100%)`,
        }}
      />
      <div style={{ position: "absolute", left: 0, right: 0, top: panelTop, bottom: 0, backgroundColor: mode.ink }} />
    </>
  );

  if (mode.grid === "column") {
    // Editorial: centrado verticalmente en el panel (nunca anclado al
    // borde superior) — mismo criterio que CoverSlide, evita que el
    // título quede pegado contra la foto cuando el texto es corto.
    // Padding real en las 4 direcciones (antes sólo horizontal, sin
    // reservar aire arriba/abajo) — `maxHeight` resta ese padding y,
    // cuando hay chip de localidad, también su alto + el `gap`: si no, el
    // conjunto (chip + gap + título) puede terminar más alto que el panel
    // y desbordar hacia la foto o el footer.
    const gap = 16;
    const chipReserve = locality ? CHIP_H + gap : 0;
    return (
      <div style={{ position: "absolute", inset: 0 }}>
        {panel}
        <div style={{ position: "absolute", left: 0, right: 0, top: panelTop, bottom: 0, padding: `${panelPadY}px ${pad}px`, display: "flex", flexDirection: "column", justifyContent: "center", overflow: "hidden" }}>
          <div style={{ width: "100%", display: "flex", flexDirection: "column", alignItems: "flex-start", gap }}>
            {locality ? <ContextChip mode={mode} label={locality} /> : null}
            <AutoHeadlineBlock
              mode={mode}
              title={titulo}
              deck={deck}
              highlightTerms={highlightTerms}
              width={width}
              maxHeight={panelH - panelPadY * 2 - chipReserve}
              maxLines={manualPublication ? 5 : 3}
              minFontSize={manualPublication ? MANUAL_TITLE_MIN_FONT_SIZE : undefined}
            />
          </div>
        </div>
      </div>
    );
  }

  // Crónica: panel anclado abajo — `maxHeight` resta el padding de AMBOS
  // lados (antes sólo restaba un valor fijo de 60px, más chico que el
  // padding real: el título podía desbordar el margen superior del panel y
  // quedar pegado contra la foto, feedback "el título está muy arriba") y,
  // cuando hay chip de localidad, también su alto + el `gap` (mismo
  // criterio que arriba: si no, el conjunto puede desbordar y superponerse
  // al footer). `overflow:hidden` es la red de seguridad final.
  const gap = 14;
  const chipReserve = locality ? CHIP_H + gap : 0;
  return (
    <div style={{ position: "absolute", inset: 0 }}>
      {panel}
      <div style={{ position: "absolute", left: 0, right: 0, top: panelTop, bottom: 0, padding: `${panelPadY}px ${pad}px`, display: "flex", flexDirection: "column", justifyContent: manualPublication ? "center" : "flex-end", gap, overflow: "hidden" }}>
        {locality ? <ContextChip mode={mode} label={locality} /> : null}
        <AutoHeadlineBlock
          mode={mode}
          title={titulo}
          deck={deck}
          highlightTerms={highlightTerms}
          width={width}
          maxHeight={panelH - panelPadY * 2 - chipReserve}
          maxLines={manualPublication ? 5 : 3}
          minFontSize={manualPublication ? MANUAL_TITLE_MIN_FONT_SIZE : undefined}
          maxHighlightPhrases={1}
        />
      </div>
    </div>
  );
};

// ── editorial_frame: para fotos horizontales/verticales/de baja calidad —
// no se fuerza el crop a pantalla completa. Imagen contenida arriba,
// titular abajo en la zona de tinta.
const FramedBody: React.FC<{
  titulo: string;
  highlightTerms: string[];
  assetFile: string;
  frameH: number;
  mode: ModeTokens;
  manualPublication: boolean;
}> = ({
  titulo,
  highlightTerms,
  assetFile,
  frameH,
  mode,
  manualPublication,
}) => {
  const pad = mode.pad;
  const width = AUTOMATIC_IG_W - pad * 2;
  const imgTop = 24;
  const imgH = Math.min(frameH, Math.round(CONTENT_H * 0.5));
  return (
    <div style={{ position: "absolute", inset: 0 }}>
      <HeroMedia assetFile={assetFile} mode={mode} variant="framed" top={imgTop} height={imgH} width={AUTOMATIC_IG_W} scrim="bottom" />
      <div style={{ position: "absolute", left: pad, right: pad, top: imgTop + imgH + 34, bottom: 0, display: "flex", alignItems: "flex-start" }}>
        <AutoHeadlineBlock
          mode={mode}
          title={titulo}
          highlightTerms={highlightTerms}
          width={width}
          maxHeight={CONTENT_H - imgH - imgTop - 34}
          maxLines={manualPublication ? 5 : 4}
          minFontSize={manualPublication ? MANUAL_TITLE_MIN_FONT_SIZE : undefined}
          size="body"
        />
      </div>
    </div>
  );
};

// ── branded_poster: la pieza ajena (screenshot/flyer con logo o texto
// propio) queda contenida en un marco, y el titular vive físicamente
// separado en la franja inferior — nunca superpuesto sobre la imagen.
// El HeroMedia y el bloque de titular comparten la misma `posterH`, así la
// imagen y el texto no se desincronizan.
const PosterBody: React.FC<{
  titulo: string;
  highlightTerms: string[];
  assetFile: string;
  mode: ModeTokens;
  manualPublication: boolean;
}> = ({
  titulo,
  highlightTerms,
  assetFile,
  mode,
  manualPublication,
}) => {
  const pad = mode.pad;
  const width = AUTOMATIC_IG_W - pad * 2;
  const posterH = Math.round(CONTENT_H * 0.6);
  return (
    <div style={{ position: "absolute", inset: 0 }}>
      <HeroMedia assetFile={assetFile} mode={mode} variant="poster" top={0} height={posterH} width={AUTOMATIC_IG_W} scrim="none" />
      <div
        style={{
          position: "absolute",
          left: pad,
          right: pad,
          top: posterH + 34,
          bottom: 0,
          display: "flex",
          flexDirection: "column",
          justifyContent: "flex-start",
        }}
      >
        <AutoHeadlineBlock
          mode={mode}
          title={titulo}
          highlightTerms={highlightTerms}
          width={width}
          maxHeight={CONTENT_H - posterH - 34}
          maxLines={manualPublication ? 5 : 4}
          minFontSize={manualPublication ? MANUAL_TITLE_MIN_FONT_SIZE : undefined}
          size="body"
        />
      </div>
    </div>
  );
};
