import React from "react";
import { AbsoluteFill } from "remotion";
import { useFontsReady } from "./fonts";
import { Grain } from "./Grain";
import { SlideCounter } from "./SlideCounter";
import { EditorialMasthead } from "./editorial/EditorialMasthead";
import { EditorialTexture } from "./editorial/EditorialTexture";
import { SocialFooter } from "./editorial/SocialFooter";
import { SourceCredit } from "./editorial/SourceCredit";
import { SwipeCue } from "./editorial/SwipeCue";
import { ModeTokens, hexToRgba } from "./designSystem";

// Marco compartido v2: masthead de marca real (no una barra lateral +
// logo chico, queja explícita del brief), grano/textura, y un footer
// liviano con crédito de fuente + señal de continuidad + numeración.
//
// A diferencia de v1 (donde el "fondo con foto" era SIEMPRE la imagen
// blureada a 46px, incluso en cover/full_image — la foto nítida nunca se
// mostraba realmente), acá `media` es responsabilidad de cada slide
// (vía HeroMedia, ver shared/editorial/HeroMedia.tsx) y se pinta a pantalla
// completa DEBAJO del masthead/footer, con foto nítida real cuando el
// tratamiento es full_bleed/framed. StillLayout sólo agrega textura,
// scrim superior de legibilidad y chrome de marca — nunca decide el
// tratamiento fotográfico.
//
// FacebookOgCard sigue usando LegacyStillLayout (workflow "og" fuera de
// alcance de este rediseño).
export const MASTHEAD_H = 92;
export const FOOTER_H = 78;

export type StillLayoutProps = {
  width: number;
  height: number;
  mode: ModeTokens;
  section?: string;
  locality?: string;
  index?: number;
  total?: number;
  sourceCredit?: string;
  showSwipeCue?: boolean;
  // Piezas de una sola imagen (AutomaticInstagramCard/FacebookOgCard) no
  // tienen fuente que citar ni carrusel que señalar — muestran en su lugar
  // la firma social compacta (FB/IG + sitio). PremiumSlide nunca activa
  // esto: su footer sigue siendo crédito de fuente + deslizamiento + numeración.
  showSocialFooter?: boolean;
  boxedSection?: boolean;
  mastheadHeight?: number;
  footerHeight?: number;
  chromeScale?: number;
  media?: React.ReactNode; // pintado a pantalla completa, debajo de masthead/footer
  children: React.ReactNode;
};

export const StillLayout: React.FC<StillLayoutProps> = ({
  width,
  height,
  mode,
  section,
  locality,
  index,
  total,
  sourceCredit,
  showSwipeCue,
  showSocialFooter,
  boxedSection,
  mastheadHeight = MASTHEAD_H,
  footerHeight = FOOTER_H,
  chromeScale = 1,
  media,
  children,
}) => {
  // Bloquea la captura de Remotion (delayRender) hasta que Archivo/Source
  // Serif 4 están registradas de verdad y el DOM volvió a pintar con ellas
  // — ver docs/DECISIONS.md, bug de wrap incorrecto detectado en smoke test.
  const fontsReady = useFontsReady();

  return (
    <AbsoluteFill style={{ backgroundColor: mode.ink }}>
      {!media && (
        <>
          <div
            style={{
              position: "absolute",
              inset: 0,
              background: `radial-gradient(ellipse 900px 700px at 78% -10%, ${hexToRgba(mode.accent, 0.16)} 0%, rgba(0,0,0,0) 60%)`,
            }}
          />
          <div
            style={{
              position: "absolute",
              inset: 0,
              background: `linear-gradient(200deg, ${hexToRgba(mode.accentSoft, 0.22)} 0%, rgba(0,0,0,0) 55%)`,
            }}
          />
        </>
      )}

      {media}

      {media && (
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            right: 0,
            height: 190,
            background: "linear-gradient(180deg, rgba(0,0,0,0.5) 0%, rgba(0,0,0,0) 100%)",
          }}
        />
      )}

      <EditorialTexture mode={mode} zone="footer" width={width} height={height} />
      <Grain opacity={0.03} />

      <EditorialMasthead
        mode={mode}
        section={section || ""}
        locality={locality}
        pad={mode.pad}
        scale={chromeScale}
        boxedSection={boxedSection}
      />

      <div style={{ position: "absolute", top: mastheadHeight, left: 0, right: 0, bottom: footerHeight }}>
        {fontsReady ? children : null}
      </div>

      {/* Footer: crédito de fuente (si hay) + señal de continuidad + numeración */}
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 0,
          height: footerHeight,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          paddingLeft: mode.pad,
          paddingRight: mode.pad,
        }}
      >
        <div style={{ position: "absolute", top: 0, left: mode.pad, right: mode.pad, height: 1, backgroundColor: hexToRgba(mode.accent, 0.3) }} />
        {showSocialFooter ? <SocialFooter scale={chromeScale} /> : <SourceCredit text={sourceCredit} scale={chromeScale} />}
        <div style={{ display: "flex", alignItems: "center", gap: Math.round(28 * chromeScale), marginLeft: "auto" }}>
          {showSwipeCue ? <SwipeCue mode={mode} scale={chromeScale} /> : null}
          {total ? <SlideCounter index={index || 1} total={total} accent={mode.accent} scale={chromeScale} /> : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};
