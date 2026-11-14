// FacebookOgCardV2 — imagen Open Graph 1200×630 del Visual System V2.
//
// Diseñada para la miniatura del link preview, no adaptada del vertical:
// columna de texto a la izquierda (papel o tinta según la sección) con el
// titular condensado lo más grande posible, regla de acento vertical como
// costura y foto a alto completo a la derecha. Sin foto: campo de sección
// con el titular a todo el ancho.
import React from "react";
import { AbsoluteFill, Img, staticFile } from "remotion";
import { z } from "zod";
import { Grain } from "../shared/Grain";
import { Headline, SectionLabel, Wordmark } from "./components";
import { fit } from "./fit";
import { useV2FontsReady } from "./fonts";
import { tokenize } from "./text";
import { C, OG, TYPE, V2_FONT_SANS, rgba, sectionStyle } from "./tokens";

export const FB_OG_V2_W = OG.w;
export const FB_OG_V2_H = OG.h;

export const FacebookOgCardV2Schema = z.object({
  titulo: z.string(),
  seccion: z.string(),
  assetFile: z.string().default(""),
  highlightTerms: z.array(z.string()).default([]),
  publicationStyle: z.string().default("automatic"),
  locality: z.string().default(""),
  breaking: z.boolean().default(false),
  // Reglas de crecimiento (T02, GROWTH_IMAGE_RULES_ENABLED): etiquetas y
  // titular más legibles en el celular. Apagado = render idéntico al anterior.
  growth: z.boolean().default(false),
});

export type FacebookOgCardV2Props = z.infer<typeof FacebookOgCardV2Schema>;

const M = OG.margin;
const TEXT_W = 600;
const SEAM = 8;

// Con ``growth``: cuerpo mínimo mayor y etiquetas legibles a 360 px (el OG se
// ve a ~0,3×). El titular ya se agranda al máximo que entra; si no entra con
// el mínimo nuevo, vuelve a la escala anterior y, por último, ajusta por alto:
// nunca se corta.
const GROWTH_OG = { min: 46, maxLines: 5, label: 26, wordmark: 28, seal: 52 } as const;

export const FacebookOgCardV2: React.FC<FacebookOgCardV2Props> = ({ titulo, seccion, assetFile, highlightTerms, locality, breaking, growth }) => {
  const ready = useV2FontsReady();
  const style = sectionStyle(seccion);
  const hasImage = Boolean(assetFile);
  // Tono "tinta" (policiales, deportes, espectáculos, urgentes) usa el campo
  // de color de la sección: identidad reconocible incluso en miniatura.
  const fieldTone = !hasImage || style.tone === "ink" || breaking;
  const bg = fieldTone ? style.field : C.paper;
  const fg = fieldTone ? C.white : C.paperInk;
  const mute = fieldTone ? rgba(C.white, 0.78) : C.paperMute;
  // Destacado: caja de tinta sobre campos de color; caja de acento sobre papel.
  const accent = fieldTone ? C.ink : style.accent;
  if (!ready) return <AbsoluteFill style={{ backgroundColor: bg }} />;

  const colW = hasImage ? TEXT_W : OG.w;
  const innerW = colW - M * 2;
  const top = 92;
  const bottom = OG.h - 92;
  const fitOg = (min: number, maxLines: number) =>
    fit({
      text: titulo,
      maxWidth: innerW,
      maxHeight: bottom - top,
      min,
      max: hasImage ? TYPE.ogHeadline.max : 88,
      weight: TYPE.ogHeadline.weight,
      lh: TYPE.ogHeadline.lh,
      stretch: TYPE.ogHeadline.stretch,
      tracking: TYPE.ogHeadline.tracking,
      maxLines,
    });
  const legacy = () => fitOg(TYPE.ogHeadline.min, 5);
  const grown = growth ? fitOg(GROWTH_OG.min, GROWTH_OG.maxLines) : null;
  // Último recurso con ``growth``: líneas según el alto disponible (sin cortar).
  const headline = grown && !grown.overflow ? grown : growth ? [legacy(), fitOg(TYPE.ogHeadline.min, 9)].find((f) => !f.overflow) ?? legacy() : legacy();
  const tokens = tokenize(titulo, highlightTerms, 1);

  return (
    <AbsoluteFill style={{ backgroundColor: bg }}>
      {hasImage ? (
        <div style={{ position: "absolute", left: TEXT_W, top: 0, right: 0, bottom: 0, overflow: "hidden" }}>
          <Img src={staticFile(assetFile)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
          <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: SEAM, backgroundColor: fieldTone ? C.ink : style.accent }} />
        </div>
      ) : null}
      <div style={{ position: "absolute", left: M, top: 40, width: innerW }}>
        <SectionLabel label={style.label} detail={locality} accent={fieldTone ? C.white : style.accent} color={mute} size={growth ? GROWTH_OG.label : 18} progress={1} />
      </div>
      <div style={{ position: "absolute", left: M, top, width: innerW, height: bottom - top, display: "flex", flexDirection: "column", justifyContent: "center" }}>
        <Headline
          fitted={headline}
          tokens={tokens}
          color={fg}
          accent={accent}
          weight={TYPE.ogHeadline.weight}
          stretch={TYPE.ogHeadline.stretch}
          tracking={TYPE.ogHeadline.tracking}
          mode="none"
          start={0}
          stagger={0}
        />
      </div>
      <div style={{ position: "absolute", left: M, bottom: 30, width: innerW, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <Wordmark size={growth ? GROWTH_OG.wordmark : 22} sealSize={growth ? GROWTH_OG.seal : 42} color={fg} accent={fieldTone ? C.white : style.accent} />
        {hasImage ? null : (
          <span style={{ fontFamily: `"${V2_FONT_SANS}"`, fontWeight: 700, fontStretch: "semi-condensed", fontSize: 18, letterSpacing: "0.14em", color: mute }}>LAVOZRIOJANA.COM</span>
        )}
      </div>
      <Grain opacity={0.035} />
    </AbsoluteFill>
  );
};
