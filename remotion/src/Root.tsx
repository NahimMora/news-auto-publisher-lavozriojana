import "./index.css";
import { CalculateMetadataFunction, Composition } from "remotion";
import { Outro } from "./Outro";
import { Main, MainProps, MainSchema } from "./Main";
import { FPS, H, W } from "./constants";

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
        }}
        calculateMetadata={calculateMainMetadata}
      />
    </>
  );
};
