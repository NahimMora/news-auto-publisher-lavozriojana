// ServiceCardV2 — post 1080×1350 (Instagram y Facebook) de las placas de
// servicio: cronograma de pagos y sismo. Misma placa que la historia
// (ServicePieces.tsx) en el formato del feed. Usa las props de StoryV2
// (`kind` "payments" o "quake").
import React from "react";
import { AbsoluteFill } from "remotion";
import { useV2FontsReady } from "../fonts";
import { C, IG } from "../tokens";
import { ServicePlate } from "./ServicePieces";
import { StoryV2Props } from "./StoryV2";

export const ServiceCardV2: React.FC<StoryV2Props> = (props) => {
  const ready = useV2FontsReady();
  if (!ready) return <AbsoluteFill style={{ backgroundColor: C.ink }} />;
  return (
    <ServicePlate
      status={props.status}
      kicker={props.kicker}
      hero={props.hero}
      heroLabel={props.heroLabel}
      lines={props.lines}
      footer={props.footer}
      tone={props.kind === "payments" ? "paper" : "ink"}
      width={IG.w}
      height={IG.h}
      margin={IG.margin}
    />
  );
};
