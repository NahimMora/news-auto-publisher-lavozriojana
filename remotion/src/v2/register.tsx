// Registro de composiciones V2. Root.tsx sólo agrega <V2Compositions />:
// las composiciones V1 (EditorialReel, AutomaticInstagramCard,
// FacebookOgCard, Main, Outro, ...) quedan exactamente igual.
import React from "react";
import { CalculateMetadataFunction, Composition, Still } from "remotion";
import { EditorialReelV2, EditorialReelV2Props, EditorialReelV2Schema, REEL_V2_OUTRO_FRAMES, ReelCoverV2 } from "./EditorialReelV2";
import { AUTOMATIC_IG_V2_H, AUTOMATIC_IG_V2_W, AutomaticInstagramCardV2, AutomaticInstagramCardV2Schema } from "./AutomaticInstagramCardV2";
import { FB_OG_V2_H, FB_OG_V2_W, FacebookOgCardV2, FacebookOgCardV2Schema } from "./FacebookOgCardV2";
import { REEL } from "./tokens";
import { StoryV2, StoryV2Schema } from "./social/StoryV2";
import { ManualStoryTemplate } from "./social/ManualStoryTemplate";
import { ServiceCardV2 } from "./social/ServiceCardV2";
import { MorningBriefV2, MorningBriefV2Schema } from "./social/MorningBriefV2";
import { WeeklyRecapV2, WeeklyRecapV2Props, WeeklyRecapV2Schema, recapDuration } from "./social/WeeklyRecapV2";
import { NightlyNewscastV2, NightlyNewscastV2Props, NightlyNewscastV2Schema, newscastTimeline } from "./social/NightlyNewscastV2";
import { NightlyNewscastV3, NightlyNewscastV3Props, NightlyNewscastV3Schema } from "./newscast/NightlyNewscastV3";
import { NightlyNewscastV5, NightlyNewscastV5Props, NightlyNewscastV5Schema } from "./newscast5/NightlyNewscastV5";
import { NewscastCoverV5 } from "./newscast5/Cover";

const recapMetadata: CalculateMetadataFunction<WeeklyRecapV2Props> = ({ props }) => ({
  durationInFrames: recapDuration(Math.min(5, props.entries.length)),
});

const newscastMetadata: CalculateMetadataFunction<NightlyNewscastV2Props> = ({ props }) => ({
  durationInFrames: newscastTimeline(props).total,
});

// V3: la duración la fija el plan (frames ya cuantizados en Python).
const newscastV3Metadata: CalculateMetadataFunction<NightlyNewscastV3Props> = ({ props }) => ({
  durationInFrames: Math.max(1, props.totalFrames),
});

const newscastV5Metadata: CalculateMetadataFunction<NightlyNewscastV5Props> = ({ props }) => ({
  durationInFrames: Math.max(1, props.totalFrames),
});

const NEWSCAST_V5_DEFAULTS: NightlyNewscastV5Props = {
  version: "lvr-newscast-plan-5.0",
  fps: 30,
  totalFrames: 300,
  edition: { brand: "La Voz Riojana", kicker: "Resumen policial", region: "La Rioja", dateLabel: "", count: 0, handle: "@lavozriojana.ok", testBanner: "" },
  opening: { style: "headline", brandFrames: 42, kicker: "Resumen policial", region: "La Rioja", dateLabel: "", count: 0, teasers: [], places: [] },
  stories: [],
  voices: [],
  captions: [],
  outro: { from: 0, durationInFrames: 300, cta: "@lavozriojana.ok", site: "lavozriojana.com", lines: [], tiles: [], voice: null },
  music: null,
  sfx: [],
};

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
      id="StoryV2"
      component={StoryV2}
      width={1080}
      height={1920}
      schema={StoryV2Schema}
      defaultProps={StoryV2Schema.parse({ kind: "post" })}
    />
    <Still id="ManualStoryTemplate" component={ManualStoryTemplate} width={1080} height={1920} />
    <Still
      id="ServiceCardV2"
      component={ServiceCardV2}
      width={1080}
      height={1350}
      schema={StoryV2Schema}
      defaultProps={StoryV2Schema.parse({ kind: "payments" })}
    />
    <Still
      id="MorningBriefV2"
      component={MorningBriefV2}
      width={1080}
      height={1350}
      schema={MorningBriefV2Schema}
      defaultProps={MorningBriefV2Schema.parse({ slide: "cover" })}
    />
    <Composition
      id="WeeklyRecapV2"
      component={WeeklyRecapV2}
      durationInFrames={recapDuration(5)}
      fps={REEL.fps}
      width={REEL.w}
      height={REEL.h}
      schema={WeeklyRecapV2Schema}
      defaultProps={{ rangeLabel: "12 al 18 de octubre", entries: [] }}
      calculateMetadata={recapMetadata}
    />
    <Composition
      id="NightlyNewscastV2"
      component={NightlyNewscastV2}
      durationInFrames={300}
      fps={REEL.fps}
      width={REEL.w}
      height={REEL.h}
      schema={NightlyNewscastV2Schema}
      defaultProps={{ dateLabel: "", hook: { voiceFile: "", voiceFrames: 60, teasers: [], media: [] }, blocks: [], outro: { voiceFile: "", voiceFrames: 60 } }}
      calculateMetadata={newscastMetadata}
    />
    <Composition
      id="NightlyNewscastV3"
      component={NightlyNewscastV3}
      durationInFrames={300}
      fps={REEL.fps}
      width={REEL.w}
      height={REEL.h}
      schema={NightlyNewscastV3Schema}
      defaultProps={{
        version: "lvr-newscast-plan-3.0",
        fps: 30,
        totalFrames: 300,
        edition: { brand: "La Voz Riojana", descriptor: "Policiales · últimas 24 h", dateLabel: "", testBanner: "", count: 0 },
        intro: null,
        stories: [],
        voices: [],
        captions: [],
        outro: { from: 0, durationInFrames: 300, cta: "@lavozriojana.ok", lines: [], voice: null },
        music: null,
        sfx: [],
      }}
      calculateMetadata={newscastV3Metadata}
    />
    <Composition
      id="NightlyNewscastV5"
      component={NightlyNewscastV5}
      durationInFrames={300}
      fps={REEL.fps}
      width={REEL.w}
      height={REEL.h}
      schema={NightlyNewscastV5Schema}
      defaultProps={NEWSCAST_V5_DEFAULTS}
      calculateMetadata={newscastV5Metadata}
    />
    <Still id="NewscastCoverV5" component={NewscastCoverV5} width={REEL.w} height={REEL.h} schema={NightlyNewscastV5Schema} defaultProps={NEWSCAST_V5_DEFAULTS} />
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
        update: false,
        layout: "auto" as const,
        dateLabel: "",
        growth: false,
        assetFocusY: 50,
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
        growth: false,
      }}
    />
  </>
);
