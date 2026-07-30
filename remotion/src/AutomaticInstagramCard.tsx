import React from "react";
import { AbsoluteFill } from "remotion";
import { z } from "zod";
import { AZUL, WHITE } from "./constants";
import { HighlightedTitle } from "./shared/HighlightedTitle";
import { StillLayout } from "./shared/StillLayout";
import { section_color_token } from "./shared/sectionColors";

export const AUTOMATIC_IG_W = 1080;
export const AUTOMATIC_IG_H = 1350;

export const AutomaticInstagramCardSchema = z.object({
  titulo: z.string(),
  seccion: z.string(),
  assetFile: z.string().default(""),
  highlightTerms: z.array(z.string()).default([]),
});

export type AutomaticInstagramCardProps = z.infer<typeof AutomaticInstagramCardSchema>;

export const AutomaticInstagramCard: React.FC<AutomaticInstagramCardProps> = ({
  titulo,
  seccion,
  assetFile,
  highlightTerms,
}) => {
  const accent = section_color_token(seccion);
  return (
    <StillLayout
      width={AUTOMATIC_IG_W}
      height={AUTOMATIC_IG_H}
      accent={accent}
      section={seccion}
      backgroundAssetFile={assetFile}
    >
      <AbsoluteFill style={{ padding: 64, display: "flex", flexDirection: "column", justifyContent: "flex-end" }}>
        <div
          style={{
            position: "absolute", left: 0, right: 0, bottom: 90, height: 480,
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
            fontFamily: "Arial, sans-serif", fontWeight: 900, fontSize: 62,
            lineHeight: 1.15, textShadow: "0 3px 12px rgba(0,0,0,0.7)",
          }}
        />
      </AbsoluteFill>
    </StillLayout>
  );
};
