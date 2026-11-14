// Portada del Noticiero V5 (1080×1920, cover_url de Instagram).
//
// Recortes que contempla (perfil propio, conservador): la grilla del perfil
// muestra el 3:4 central (y 240–1680) y el feed puede mostrar el 1:1 central
// (y 420–1500). Marca, titular y la lista de "además" viven dentro del 1:1;
// nada esencial fuera del 3:4. Recibe el mismo plan que el video: la
// portada siempre anuncia lo que el Reel efectivamente cuenta.
import React from "react";
import { AbsoluteFill, Img, staticFile } from "remotion";
import { fit } from "../fit";
import { useV2FontsReady } from "../fonts";
import { HeroLines, chooseHero } from "../newscast/primitives";
import type { NightlyNewscastV5Props } from "./schema";
import { PhotoShot, Texture } from "./shots";
import { C5, CONTENT_W5, L, alpha, caps5, sans, serif } from "./theme";

export const NewscastCoverV5: React.FC<NightlyNewscastV5Props> = (props) => {
  const ready = useV2FontsReady();
  if (!ready) return <AbsoluteFill style={{ backgroundColor: C5.ink }} />;
  const lead = props.stories[0];
  const shot = lead?.shots.find((s) => s.media && s.kind !== "map") ?? null;
  const hero = lead ? chooseHero(lead.headline, lead.strip, { min: 92, max: 156, maxHeight: 520, maxLines: 4 }) : null;
  const others = props.stories.slice(1, 4);
  const heroTop = 1060 - (hero?.height ?? 0);
  return (
    <AbsoluteFill style={{ backgroundColor: C5.ink }}>
      {shot ? <PhotoShot shot={{ ...shot, framing: "wide", move: { ...shot.move, s1: shot.move.s0, x1: shot.move.x0, y1: shot.move.y0, r1: shot.move.r0 } }} frame={0} /> : null}
      <Texture />
      <AbsoluteFill style={{ background: `linear-gradient(180deg, ${alpha(C5.ink, 0.75)} 0%, ${alpha(C5.ink, 0.15)} 24%, ${alpha(C5.ink, 0.1)} 38%, ${alpha(C5.ink, 0.82)} 58%, ${alpha(C5.ink, 0.94)} 100%)` }} />
      {/* Marca dentro del 3:4 */}
      <div style={{ position: "absolute", left: L.x0, top: 300, display: "flex", alignItems: "center", gap: 18 }}>
        <Img src={staticFile("logo.png")} style={{ width: 92, height: 92, objectFit: "contain" }} />
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <span style={{ ...sans(54, 900), color: C5.white }}>LA VOZ RIOJANA</span>
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <span style={{ ...caps5(24, C5.white, 900, 0.14), backgroundColor: C5.red, padding: "4px 10px" }}>{props.edition.kicker}</span>
            <span style={{ ...caps5(24, C5.white, 900, 0.14) }}>{props.edition.region}</span>
          </div>
        </div>
      </div>
      {hero && lead ? (
        <div style={{ position: "absolute", left: L.x0, width: CONTENT_W5, top: heroTop }}>
          <HeroLines hero={hero} keyword={lead.keyword} start={-30} color={C5.white} boxColor={C5.red} />
          <div style={{ height: 10, width: 220, backgroundColor: C5.red, marginTop: 20 }} />
        </div>
      ) : null}
      {others.length ? (
        <div style={{ position: "absolute", left: L.x0, width: CONTENT_W5, top: 1120, display: "flex", flexDirection: "column", gap: 12 }}>
          <span style={{ ...caps5(26, alpha(C5.white, 0.75), 900, 0.18) }}>{`Además · ${props.stories.length - 1} hechos más`}</span>
          {others.map((s, k) => {
            const f = fit({ text: s.strip.toUpperCase(), maxWidth: CONTENT_W5 - 40, maxHeight: 50, min: 30, max: 44, weight: 900, lh: 1, stretch: "condensed", maxLines: 1 });
            return (
              <div key={k} style={{ display: "flex", alignItems: "center", gap: 14 }}>
                <span style={{ width: 14, height: 14, backgroundColor: C5.red, display: "inline-block", flex: "none" }} />
                <span style={{ ...sans(f.fontSize, 900), color: C5.white }}>{f.lines[0]}</span>
              </div>
            );
          })}
        </div>
      ) : null}
      <div style={{ position: "absolute", left: L.x0, top: 1440, ...serif(38, alpha(C5.white, 0.9)) }}>{props.edition.dateLabel ? props.edition.dateLabel.charAt(0) + props.edition.dateLabel.slice(1).toLowerCase() : ""}</div>
    </AbsoluteFill>
  );
};
