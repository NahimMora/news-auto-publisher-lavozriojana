// Contrato del plan audiovisual del Noticiero (utils/newscast_v3.py →
// build_plan). Remotion sólo ejecuta el plan: tiempos en frames ya
// cuantizados en Python, recursos ya elegidos y validados.
import { z } from "zod";

const Media = z.object({
  id: z.string(),
  note: z.string(),
  type: z.enum(["image", "video"]),
  file: z.string(),
  width: z.number(),
  height: z.number(),
  role: z.enum(["actual", "context"]).default("actual"),
  label: z.string().default(""),
  sourceInFrames: z.number().default(0),
  durationMs: z.number().default(0),
  focusX: z.number().default(0.5),
  focusY: z.number().default(0.45),
  textZone: z.string().default("ninguna"),
  edgeSubjects: z.boolean().default(false),
  people: z.boolean().default(false),
});

const Move = z.object({ scaleFrom: z.number(), scaleTo: z.number(), dx: z.number(), dy: z.number() });

const Shot = z.object({
  from: z.number(),
  durationInFrames: z.number(),
  event: z.number().default(0),
  layout: z.enum(["full", "window", "type"]),
  framing: z.enum(["general", "detail"]).default("general"),
  media: Media.nullable(),
  move: Move,
});

const Event = z.object({
  index: z.number(),
  ids: z.array(z.string()),
  lugar: z.string().default(""),
  momento: z.string().default(""),
  dato: z.string().default(""),
  from: z.number(),
  to: z.number(),
  credit: z.string().default(""),
  datoAt: z.number().nullable().default(null),
});

const Emphasis = z.object({
  kind: z.enum(["place", "count", "data", "tag"]),
  text: z.string(),
  value: z.string().default(""),
  at: z.number(),
});

const Tramo = z.object({ texto: z.string(), lugar: z.string().default(""), momento: z.string().default(""), dato: z.string().default("") });

export const FAMILY = z.enum(["video", "photo", "timeline", "related", "data", "limited", "principal", "service", "judicial", "brief"]);

const Story = z.object({
  index: z.number(),
  seccion: z.string(),
  tipo: z.string(),
  family: FAMILY,
  principal: z.boolean().default(false),
  titulo: z.string(),
  tituloCorto: z.string().default(""),
  keyword: z.string().default(""),
  lugar: z.string().default(""),
  credit: z.string().default(""),
  servicio: z.object({ accion: z.string().default(""), zona: z.string().default(""), vigencia: z.string().default("") }).partial().default({}),
  tramos: z.array(Tramo).default([]),
  from: z.number(),
  durationInFrames: z.number(),
  compactAt: z.number(),
  shots: z.array(Shot),
  events: z.array(Event).default([]),
  emphasis: z.array(Emphasis).default([]),
  wipe: z.enum(["slash", "cover", "locality", "iris"]).default("slash"),
});

const Caption = z.object({
  text: z.string(),
  from: z.number(),
  to: z.number(),
  story: z.number(),
  words: z.array(z.object({ text: z.string(), from: z.number(), method: z.string().default("asr") })).default([]),
});
const Voice = z.object({ file: z.string(), from: z.number(), durationInFrames: z.number() });

const Beat = z.object({
  from: z.number(),
  to: z.number(),
  ids: z.array(z.string()),
  text: z.string().default(""),
  shot: Shot,
});

const Intro = z.object({
  from: z.number(),
  durationInFrames: z.number(),
  beats: z.array(Beat),
  tailFrom: z.number(),
  tailText: z.string().default(""),
  voice: Voice.nullable().default(null),
});

const Sfx = z.object({ file: z.string(), from: z.number(), volume: z.number() });

export const NightlyNewscastV3Schema = z.object({
  version: z.string(),
  fps: z.number().default(30),
  totalFrames: z.number(),
  edition: z.object({ brand: z.string(), descriptor: z.string(), dateLabel: z.string(), testBanner: z.string().default(""), count: z.number().default(0) }),
  intro: Intro.nullable().default(null),
  stories: z.array(Story),
  voices: z.array(Voice),
  captions: z.array(Caption).default([]),
  outro: z.object({
    from: z.number(),
    durationInFrames: z.number(),
    cta: z.string(),
    lines: z.array(z.object({ text: z.string(), at: z.number().nullable().default(null) })).default([]),
    voice: Voice.nullable().default(null),
  }),
  music: z.object({ file: z.string(), gainDb: z.number(), openGainDb: z.number(), introGainDb: z.number().default(0) }).nullable().default(null),
  sfx: z.array(Sfx).default([]),
});

export type NightlyNewscastV3Props = z.infer<typeof NightlyNewscastV3Schema>;
export type StoryPlan = z.infer<typeof Story>;
export type ShotPlan = z.infer<typeof Shot>;
export type MediaPlan = z.infer<typeof Media>;
export type EventPlan = z.infer<typeof Event>;
export type EmphasisPlan = z.infer<typeof Emphasis>;
export type IntroPlan = z.infer<typeof Intro>;
export type CaptionPlan = z.infer<typeof Caption>;
