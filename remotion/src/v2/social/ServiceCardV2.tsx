// ServiceCardV2 — post 1080×1350 (Instagram y Facebook) de las placas de
// servicio: cronograma de pagos y sismo sentido. Mismo contenido que la
// historia (ServicePieces.tsx) en el formato del feed. Usa las props de
// StoryV2 (`kind` "payments" o "quake").
import React from "react";
import { AbsoluteFill } from "remotion";
import { useV2FontsReady } from "../fonts";
import { C, IG, rgba } from "../tokens";
import { Brand, FieldBackdrop, SourceLine, Tab } from "./chrome";
import { PaymentsBlock, QuakeBlock } from "./ServicePieces";
import { StoryV2Props } from "./StoryV2";

const M = IG.margin;
const W = IG.w - M * 2;

const Header: React.FC<{ tab: React.ReactNode; color: string }> = ({ tab, color }) => (
  <div style={{ position: "absolute", left: M, right: M, top: M, display: "flex", flexDirection: "column", gap: 24 }}>
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
      <Brand color={color} seal={80} size={34} />
      {tab}
    </div>
    <div style={{ height: 2, backgroundColor: rgba(color, 0.2) }} />
  </div>
);

export const ServiceCardV2: React.FC<StoryV2Props> = (props) => {
  const ready = useV2FontsReady();
  if (!ready) return <AbsoluteFill style={{ backgroundColor: C.ink }} />;
  if (props.kind === "payments") {
    const ink = C.paperInk;
    return (
      <AbsoluteFill>
        <AbsoluteFill style={{ backgroundColor: C.paper }} />
        <Header color={ink} tab={<Tab label="Cronograma de pagos" fill={C.red} size={22} />} />
        <div style={{ position: "absolute", left: M, top: 230 }}>
          <PaymentsBlock headline={props.headline} subhead={props.subhead} groups={props.groups} width={W} height={980} ink={ink} mute={C.paperMute} />
        </div>
        <SourceLine left={props.sourceLabel || "Fuente: Ministerio de Hacienda de La Rioja"} color={ink} top={IG.h - 120} />
      </AbsoluteFill>
    );
  }
  return (
    <AbsoluteFill>
      <FieldBackdrop from="#3a2400" to={C.ink} dots={rgba("#F2A900", 0.1)} />
      <Header color={C.white} tab={<Tab label="Sismo" fill="#F2A900" color={C.ink} size={22} />} />
      <div style={{ position: "absolute", left: M, top: 230 }}>
        <QuakeBlock
          magnitude={props.magnitude}
          headline={props.headline}
          timeLabel={props.timeLabel}
          epicenter={props.epicenter}
          depth={props.depth}
          felt={props.felt}
          width={W}
          compact
        />
      </div>
      <SourceLine left={props.sourceLabel || "Fuente: INPRES"} top={IG.h - 120} />
    </AbsoluteFill>
  );
};
