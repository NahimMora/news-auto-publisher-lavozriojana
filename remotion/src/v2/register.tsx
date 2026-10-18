// Registro de composiciones V2. Root.tsx sólo agrega <V2Compositions />:
// las composiciones V1 (EditorialReel, AutomaticInstagramCard,
// FacebookOgCard, Main, Outro, ...) quedan exactamente igual.
import React from "react";
import { CalculateMetadataFunction, Composition, Still } from "remotion";
import { EditorialReelV2, EditorialReelV2Props, EditorialReelV2Schema, REEL_V2_OUTRO_FRAMES, ReelCoverV2 } from "./EditorialReelV2";
import { AUTOMATIC_IG_V2_H, AUTOMATIC_IG_V2_W, AutomaticInstagramCardV2, AutomaticInstagramCardV2Schema } from "./AutomaticInstagramCardV2";
import { FB_OG_V2_H, FB_OG_V2_W, FacebookOgCardV2, FacebookOgCardV2Schema } from "./FacebookOgCardV2";
import { REEL } from "./tokens";

const reelMetadata: CalculateMetadataFunction<EditorialReelV2Props> = ({ props }) => ({
  durationInFrames: props.durationInFrames + REEL_V2_OUTRO_FRAMES,
});

export const V2Compositions: React.FC = () => (
  <>
    <Composition
      id="EditorialReelV2"
      component={EditorialReelV2}
      durationInFrames={210}
      fps={REEL.fps}
      width={REEL.w}
      height={REEL.h}
      schema={EditorialReelV2Schema}
      defaultProps={{
        titulo: "La Legislatura aprobó el presupuesto 2026 tras un debate de diez horas",
        seccion: "Política",
        assetType: "none" as const,
        assetFile: "",
        kenBurnsVariant: 0,
        durationInFrames: 150,
        highlightTerms: ["aprobó el presupuesto"],
        assetWidth: 0,
        assetHeight: 0,
        locality: "",
        breaking: false,
        hookStyle: "auto" as const,
        deck: "",
        credit: "",
        still: false,
      }}
      calculateMetadata={reelMetadata}
    />
    <Still
      id="ReelCoverV2"
      component={ReelCoverV2}
      width={REEL.w}
      height={REEL.h}
      schema={EditorialReelV2Schema}
      defaultProps={{
        titulo: "La Legislatura aprobó el presupuesto 2026 tras un debate de diez horas",
        seccion: "Política",
        assetType: "image" as const,
        assetFile: "",
        kenBurnsVariant: 0,
        durationInFrames: 150,
        highlightTerms: ["aprobó el presupuesto"],
        assetWidth: 0,
        assetHeight: 0,
        locality: "",
        breaking: false,
        hookStyle: "auto" as const,
        deck: "",
        credit: "",
        still: true,
      }}
    />
    <Still
      id="AutomaticInstagramCardV2"
      component={AutomaticInstagramCardV2}
      width={AUTOMATIC_IG_V2_W}
      height={AUTOMATIC_IG_V2_H}
      schema={AutomaticInstagramCardV2Schema}
      defaultProps={{
        titulo: "La Legislatura aprobó el presupuesto 2026",
        seccion: "Política",
        assetFile: "",
        highlightTerms: [],
        locality: "",
        deck: "",
        imageTreatment: "auto",
        publicationStyle: "automatic",
        assetWidth: 0,
        assetHeight: 0,
        breaking: false,
        layout: "auto" as const,
        dateLabel: "",
      }}
    />
    <Still
      id="FacebookOgCardV2"
      component={FacebookOgCardV2}
      width={FB_OG_V2_W}
      height={FB_OG_V2_H}
      schema={FacebookOgCardV2Schema}
      defaultProps={{
        titulo: "La Legislatura aprobó el presupuesto 2026",
        seccion: "Política",
        assetFile: "",
        highlightTerms: [],
        publicationStyle: "automatic",
        locality: "",
        breaking: false,
      }}
    />
  </>
);
