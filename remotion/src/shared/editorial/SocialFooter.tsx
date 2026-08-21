import React from "react";
import { SocialMark } from "./SocialMark";
import { FONT_DISPLAY, WEIGHT, hexToRgba, WHITE } from "../designSystem";

// Firma social compacta para el footer de piezas de una sola imagen
// (AutomaticInstagramCard/FacebookOgCard): íconos FB/IG + el sitio, mismo
// idioma visual que BrandSignature (cierre del carrusel premium) pero
// dimensionado para vivir en la franja angosta del footer en vez de un
// panel completo. Nunca se usa en PremiumSlide — ahí el footer muestra
// crédito de fuente + señal de continuidad + numeración (ver StillLayout).
export const SocialFooter: React.FC<{ scale?: number }> = ({ scale = 1 }) => {
  const s = (value: number) => Math.round(value * scale);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: s(14) }}>
      <SocialMark file="fb_icon_base.png" size={s(28)} />
      <SocialMark file="ig_icon_base.png" size={s(28)} />
      <span
        style={{
          fontFamily: `"${FONT_DISPLAY}"`,
          fontWeight: WEIGHT.medium,
          fontSize: s(25),
          color: hexToRgba(WHITE, 0.66),
        }}
      >
        lavozriojana.com
      </span>
    </div>
  );
};
