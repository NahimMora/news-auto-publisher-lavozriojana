import React from "react";
import { AbsoluteFill } from "remotion";
import { z } from "zod";
import { AZUL, WHITE } from "./constants";
import { HighlightedTitle } from "./shared/HighlightedTitle";
import { StillLayout } from "./shared/StillLayout";
import { section_color_token } from "./shared/sectionColors";

export const FB_OG_W = 1200;
export const FB_OG_H = 630;

export const FacebookOgCardSchema = z.object({
  titulo: z.string(),
  seccion: z.string(),
  assetFile: z.string().default(""),
  highlightTerms: z.array(z.string()).default([]),
});

export type FacebookOgCardProps = z.infer<typeof FacebookOgCardSchema>;

export const FacebookOgCard: React.FC<FacebookOgCardProps> = ({
  titulo,
  seccion,
  assetFile,
  highlightTerms,
}) => {
  const accent = section_color_token(seccion);
  return (
    <StillLayout width={FB_OG_W} height={FB_OG_H} accent={accent} section={seccion} backgroundAssetFile={assetFile}>
      <AbsoluteFill style={{ padding: 48, display: "flex", flexDirection: "column", justifyContent: "flex-end" }}>
        <div
          style={{
            position: "absolute", left: 0, right: 0, bottom: 48, height: 320,
            background: "linear-gradient(180deg, rgba(0,0,0,0) 0%, rgba(0,0,0,0.8) 100%)",
          }}
        />
        <HighlightedTitle
          text={titulo.toUpperCase()}
          highlightTerms={highlightTerms}
          color={WHITE}
          highlightColor={AZUL}
          style={{
            position: "relative", zIndex: 1,
            fontFamily: "Arial, sans-serif", fontWeight: 900, fontSize: 46,
            lineHeight: 1.15, textShadow: "0 2px 10px rgba(0,0,0,0.7)",
          }}
        />
      </AbsoluteFill>
    </StillLayout>
  );
};
