import React from "react";
import { AbsoluteFill, Img, staticFile } from "remotion";
import { z } from "zod";
import { AZUL, BORDO, ROJO, WHITE } from "./constants";
import { HighlightedTitle } from "./shared/HighlightedTitle";
import { StillLayout } from "./shared/StillLayout";

// Carrusel premium (Fase 3/4): mismo renderer para preview y publicación.
// 1080x1350 — resolución de carrusel de Instagram.
export const PREMIUM_SLIDE_W = 1080;
export const PREMIUM_SLIDE_H = 1350;

export const PremiumSlideSchema = z.object({
  slideType: z.enum([
    "cover",
    "image_text",
    "full_image",
    "key_points",
    "quote",
    "number",
    "closing",
  ]),
  template: z.enum(["lvr_cronica", "lvr_datos", "lvr_visual"]).default("lvr_cronica"),
  title: z.string().default(""),
  text: z.string().default(""),
  items: z.array(z.string()).default([]),
  highlightTerms: z.array(z.string()).default([]),
  assetFile: z.string().default(""), // relativo a public/, "" si no hay imagen
  section: z.string().default(""),
  index: z.number().default(1),
  total: z.number().default(1),
});

export type PremiumSlideProps = z.infer<typeof PremiumSlideSchema>;

const TEMPLATE_ACCENT: Record<string, string> = {
  lvr_cronica: ROJO,
  lvr_datos: AZUL,
  lvr_visual: BORDO,
};

export const PremiumSlide: React.FC<PremiumSlideProps> = ({
  slideType,
  template,
  title,
  text,
  items,
  highlightTerms,
  assetFile,
  section,
  index,
  total,
}) => {
  const accent = TEMPLATE_ACCENT[template] || ROJO;
  const hasImage = Boolean(assetFile);

  return (
    <StillLayout
      width={PREMIUM_SLIDE_W}
      height={PREMIUM_SLIDE_H}
      accent={accent}
      section={section}
      counter={total ? `${index}/${total}` : undefined}
      backgroundAssetFile={slideType === "cover" || slideType === "full_image" ? assetFile : ""}
    >
      <AbsoluteFill style={{ padding: 64, display: "flex", flexDirection: "column", justifyContent: "flex-end" }}>
        {(slideType === "cover" || slideType === "full_image") && (
          <>
            <div style={{ position: "absolute", left: 0, right: 0, bottom: 90, height: 420, background: "linear-gradient(180deg, rgba(0,0,0,0) 0%, rgba(0,0,0,0.75) 100%)" }} />
            <HighlightedTitle
              text={title}
              highlightTerms={highlightTerms}
              color={WHITE}
              highlightColor={accent}
              style={{ position: "relative", zIndex: 1, fontFamily: "Arial, sans-serif", fontWeight: 900, fontSize: 64, lineHeight: 1.15, textShadow: "0 3px 12px rgba(0,0,0,0.7)" }}
            />
          </>
        )}

        {slideType === "image_text" && (
          <>
            {hasImage && (
              <Img
                src={staticFile(assetFile)}
                style={{ position: "absolute", top: 0, left: 0, right: 0, width: "100%", height: 650, objectFit: "cover" }}
              />
            )}
            <HighlightedTitle
              text={title}
              highlightTerms={highlightTerms}
              color={WHITE}
              highlightColor={accent}
              style={{ fontFamily: "Arial, sans-serif", fontWeight: 900, fontSize: 56, lineHeight: 1.2, marginBottom: 20 }}
            />
            <div style={{ fontFamily: "Arial, sans-serif", fontWeight: 400, fontSize: 34, lineHeight: 1.4, color: WHITE }}>{text}</div>
          </>
        )}

        {slideType === "key_points" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
            <div style={{ fontFamily: "Arial, sans-serif", fontWeight: 900, fontSize: 56, color: WHITE, marginBottom: 20 }}>
              {title || "Puntos clave"}
            </div>
            {items.slice(0, 6).map((item, i) => (
              <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 16 }}>
                <div style={{ width: 14, height: 14, borderRadius: 999, backgroundColor: accent, marginTop: 10 }} />
                <div style={{ fontFamily: "Arial, sans-serif", fontWeight: 400, fontSize: 34, color: WHITE, lineHeight: 1.3 }}>{item}</div>
              </div>
            ))}
          </div>
        )}

        {slideType === "quote" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
            <div style={{ fontFamily: "Georgia, serif", fontWeight: 900, fontSize: 140, color: accent, lineHeight: 0.6 }}>“</div>
            <HighlightedTitle
              text={text}
              highlightTerms={highlightTerms}
              color={WHITE}
              highlightColor={accent}
              style={{ fontFamily: "Arial, sans-serif", fontWeight: 700, fontSize: 48, lineHeight: 1.35 }}
            />
            {title ? (
              <div style={{ fontFamily: "Arial, sans-serif", fontWeight: 700, fontSize: 30, color: accent }}>— {title}</div>
            ) : null}
          </div>
        )}

        {slideType === "number" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
            <div style={{ fontFamily: "Arial, sans-serif", fontWeight: 900, fontSize: 220, color: accent, lineHeight: 1 }}>
              {items[0] || ""}
            </div>
            <div style={{ fontFamily: "Arial, sans-serif", fontWeight: 400, fontSize: 34, color: WHITE, lineHeight: 1.4 }}>{text}</div>
          </div>
        )}

        {slideType === "closing" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 16, alignItems: "flex-start" }}>
            <div style={{ fontFamily: "Arial, sans-serif", fontWeight: 900, fontSize: 60, color: accent }}>La Voz Riojana</div>
            <div style={{ fontFamily: "Arial, sans-serif", fontWeight: 400, fontSize: 34, color: WHITE }}>
              {text || "Seguinos para más noticias"}
            </div>
          </div>
        )}
      </AbsoluteFill>
    </StillLayout>
  );
};
