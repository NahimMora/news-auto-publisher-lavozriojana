// Contrato del plan del Noticiero V5 (utils/newscast_v5.py → build_plan_v5).
// Remotion sólo ejecuta el plan: frames ya cuantizados en Python, recursos
// ya elegidos y validados, mapas sólo con localidades del nomenclador.
import { z } from "zod";

const Media = z.object({
  id: z.string(),
  note: z.string(),
  type: z.enum(["image", "video"]),
  file: z.string(),
  width: z.number(),
  height: z.number(),
  focusX: z.number().default(0.5),
  focusY: z.number().default(0.45),
  label: z.string().default(""),
  sourceInFrames: z.number().default(0),
  durationMs: z.number().default(0),
});

const Move = z.object({ s0: z.number(), s1: z.number(), x0: z.number(), x1: z.number(), y0: z.number(), y1: z.number(), r0: z.number(), r1: z.number() });

const Place = z.object({
  name: z.string(),
  department: z.string().default(""),
  label: z.string(),
  x: z.number(),
  y: z.number(),
});

const Shot = z.object({
  from: z.number(),
  durationInFrames: z.number(),
  kind: z.enum(["image", "video", "map", "type"]),
  mode: z.enum(["full", "band", "card", "map", "type"]),
  framing: z.enum(["wide", "detail"]).default("wide"),
  media: Media.nullable(),
  move: Move,
  place: Place.optional(),
});

const Insert = z.object({
  kind: z.enum(["place", "count", "data", "tag"]),
  text: z.string(),
  value: z.string().default(""),
  at: z.number(),
  until: z.number(),
});

const Story = z.object({
  index: z.number(),
  ids: z.array(z.string()),
  seccion: z.string(),
  tipo: z.string(),
  lead: z.boolean().default(false),
  headline: z.string(),
  strip: z.string(),
  keyword: z.string().default(""),
  tag: z.string().default("Policiales"),
  lugar: z.string().default(""),
  sensible: z.boolean().default(false),
  from: z.number(),
  durationInFrames: z.number(),
  compactAt: z.number(),
  shots: z.array(Shot),
  inserts: z.array(Insert).default([]),
  wipe: z.enum(["cut", "slash", "slide", "lift", "brand"]).default("slash"),
});

const Caption = z.object({
  text: z.string(),
  from: z.number(),
  to: z.number(),
  story: z.number(),
  words: z.array(z.object({ text: z.string(), from: z.number(), key: z.boolean().default(false) })).default([]),
});

const Voice = z.object({ file: z.string(), from: z.number(), durationInFrames: z.number() });
const Tile = z.object({ file: z.string(), focusX: z.number().default(0.5), focusY: z.number().default(0.5) });

const Opening = z.object({
  style: z.enum(["headline", "rundown", "map"]).default("headline"),
  brandFrames: z.number().default(42),
  kicker: z.string().default("Resumen policial"),
  region: z.string().default("La Rioja"),
  dateLabel: z.string().default(""),
  count: z.number().default(0),
  teasers: z.array(Tile.extend({ title: z.string() })).default([]),
  places: z.array(Place).default([]),
});

export const NightlyNewscastV5Schema = z.object({
  version: z.string(),
  fps: z.number().default(30),
  totalFrames: z.number(),
  edition: z.object({
    brand: z.string(),
    kicker: z.string().default("Resumen policial"),
    region: z.string().default("La Rioja"),
    dateLabel: z.string(),
    count: z.number().default(0),
    handle: z.string().default("@lavozriojana.ok"),
    testBanner: z.string().default(""),
  }),
  opening: Opening,
  stories: z.array(Story),
  voices: z.array(Voice),
  captions: z.array(Caption).default([]),
  outro: z.object({
    from: z.number(),
    durationInFrames: z.number(),
    cta: z.string(),
    site: z.string().default("lavozriojana.com"),
    lines: z.array(z.object({ text: z.string(), at: z.number().nullable().default(null) })).default([]),
    tiles: z.array(Tile).default([]),
    voice: Voice.nullable().default(null),
  }),
  music: z.object({ file: z.string(), gainDb: z.number(), openGainDb: z.number(), introGainDb: z.number().default(0) }).nullable().default(null),
  sfx: z.array(z.object({ file: z.string(), from: z.number(), volume: z.number() })).default([]),
});

export type NightlyNewscastV5Props = z.infer<typeof NightlyNewscastV5Schema>;
export type StoryV5 = z.infer<typeof Story>;
export type ShotV5 = z.infer<typeof Shot>;
export type MediaV5 = z.infer<typeof Media>;
export type InsertV5 = z.infer<typeof Insert>;
export type CaptionV5 = z.infer<typeof Caption>;
export type PlaceV5 = z.infer<typeof Place>;
export type OpeningV5 = z.infer<typeof Opening>;
