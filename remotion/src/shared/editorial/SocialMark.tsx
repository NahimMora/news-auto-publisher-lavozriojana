import React from "react";
import { staticFile } from "remotion";
import { WHITE } from "../designSystem";

// Ícono social monocromo (máscara CSS sobre el PNG base) — mismo recurso
// que usa BrandSignature en el cierre del carrusel premium, parametrizado
// en tamaño para poder vivir también en un footer angosto.
export const SocialMark: React.FC<{ file: string; size?: number }> = ({ file, size = 38 }) => (
  <div
    style={{
      width: size,
      height: size,
      backgroundColor: WHITE,
      maskImage: `url(${staticFile(file)})`,
      maskSize: "contain",
      maskRepeat: "no-repeat",
      maskPosition: "center",
      WebkitMaskImage: `url(${staticFile(file)})`,
      WebkitMaskSize: "contain",
      WebkitMaskRepeat: "no-repeat",
      WebkitMaskPosition: "center",
    }}
  />
);
