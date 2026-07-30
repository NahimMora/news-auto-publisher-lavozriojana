import "./index.css";
import { CalculateMetadataFunction, Composition, Still } from "remotion";
import { Outro } from "./Outro";
import { Main, MainProps, MainSchema } from "./Main";
import { FPS, H, W } from "./constants";
import { PremiumSlide, PremiumSlideSchema, PREMIUM_SLIDE_H, PREMIUM_SLIDE_W } from "./PremiumSlide";
import {
  AutomaticInstagramCard,
  AutomaticInstagramCardSchema,
  AUTOMATIC_IG_H,
  AUTOMATIC_IG_W,
} from "./AutomaticInstagramCard";
import { FacebookOgCard, FacebookOgCardSchema, FB_OG_H, FB_OG_W } from "./FacebookOgCard";

const calculateMainMetadata: CalculateMetadataFunction<MainProps> = ({
  props,
}) => {
  return { durationInFrames: props.durationInFrames };
};

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="Outro"
        component={Outro}
        durationInFrames={90}
        fps={FPS}
        width={W}
        height={H}
      />
      <Composition
        id="Main"
        component={Main}
        durationInFrames={120}
        fps={FPS}
        width={W}
        height={H}
        schema={MainSchema}
        defaultProps={{
          titulo: "La Legislatura aprobó el presupuesto 2026 tras un debate de diez horas",
          seccion: "Política",
          assetType: "none",
          assetFile: "",
          kenBurnsVariant: 0,
          durationInFrames: 120,
          highlightTerms: [],
        }}
        calculateMetadata={calculateMainMetadata}
      />
      <Still
        id="PremiumSlide"
        component={PremiumSlide}
        width={PREMIUM_SLIDE_W}
        height={PREMIUM_SLIDE_H}
        schema={PremiumSlideSchema}
        defaultProps={{
          slideType: "cover",
          template: "lvr_cronica",
          title: "Un incendio afecta un comercio en Chilecito",
          text: "",
          items: [],
          highlightTerms: ["incendio", "Chilecito"],
          assetFile: "",
          section: "interior",
          index: 1,
          total: 1,
        }}
      />
      <Still
        id="AutomaticInstagramCard"
        component={AutomaticInstagramCard}
        width={AUTOMATIC_IG_W}
        height={AUTOMATIC_IG_H}
        schema={AutomaticInstagramCardSchema}
        defaultProps={{
          titulo: "La Legislatura aprobó el presupuesto 2026",
          seccion: "Política",
          assetFile: "",
          highlightTerms: [],
        }}
      />
      <Still
        id="FacebookOgCard"
        component={FacebookOgCard}
        width={FB_OG_W}
        height={FB_OG_H}
        schema={FacebookOgCardSchema}
        defaultProps={{
          titulo: "La Legislatura aprobó el presupuesto 2026",
          seccion: "Política",
          assetFile: "",
          highlightTerms: [],
        }}
      />
    </>
  );
};
