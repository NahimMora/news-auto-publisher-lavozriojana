import React from "react";
import { Img, staticFile } from "remotion";
import { FONT_DISPLAY, FONT_SERIF, ModeTokens, SECTION_BLUE_DARK, WEIGHT, WHITE, hexToRgba } from "../designSystem";

// Cabecera de marca real: reemplaza "barra azul lateral + logo chiquito"
// (queja explícita del brief) por una jerarquía marca → sección → edición
// que además cambia de estructura según `mode.grid` — no es el mismo
// masthead con otro color. `locality`/`edition` sólo se muestran si vienen
// cargados (nunca se inventa dato editorial).
export const EditorialMasthead: React.FC<{
  mode: ModeTokens;
  section: string;
  locality?: string;
  pad: number;
  scale?: number;
  // Las piezas de "Publicaciones" fuerzan la bandera de sección que usa
  // la portada Premium Crónica. El color sigue viniendo del modo visual:
  // rojo para Crónica y azul para Editorial.
  boxedSection?: boolean;
}> = ({ mode, section, locality, pad, scale = 1, boxedSection = false }) => {
  const sectionLabel = (section || "").toUpperCase();
  const scaled = (value: number) => Math.round(value * scale);
  const sectionBackground = boxedSection && mode.grid === "column" ? SECTION_BLUE_DARK : mode.accent;

  if (mode.grid === "diagonal" || boxedSection) {
    return (
      <div style={{ position: "absolute", top: 0, left: 0, right: 0, display: "flex", alignItems: "stretch" }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: scaled(14),
            backgroundColor: sectionBackground,
            padding: `${scaled(18)}px ${pad}px`,
            clipPath: `polygon(0 0, 100% 0, calc(100% - ${scaled(34)}px) 100%, 0 100%)`,
          }}
        >
          <Img src={staticFile("logo.png")} style={{ width: scaled(34), height: scaled(34), objectFit: "contain" }} />
          <span
            style={{
              fontFamily: `"${FONT_DISPLAY}"`,
              fontWeight: WEIGHT.black,
              fontSize: scaled(24),
              letterSpacing: "0.1em",
              color: WHITE,
              textTransform: "uppercase",
            }}
          >
            {sectionLabel || mode.label}
          </span>
        </div>
        {locality ? (
          <div style={{ display: "flex", alignItems: "center", paddingLeft: scaled(18) }}>
            <span
              style={{
                fontFamily: `"${FONT_DISPLAY}"`,
                fontWeight: WEIGHT.bold,
                fontSize: scaled(22),
                letterSpacing: "0.08em",
                color: hexToRgba(WHITE, 0.75),
                textTransform: "uppercase",
              }}
            >
              {locality}
            </span>
          </div>
        ) : null}
      </div>
    );
  }

  if (mode.grid === "column") {
    return (
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: `${scaled(28)}px ${pad}px ${scaled(20)}px ${pad}px`,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: scaled(14) }}>
          <Img src={staticFile("logo.png")} style={{ width: scaled(30), height: scaled(30), objectFit: "contain", opacity: 0.92 }} />
          <span
            style={{
              fontFamily: `"${FONT_SERIF}"`,
              fontStyle: "italic",
              fontWeight: WEIGHT.semibold,
              fontSize: scaled(27),
              color: WHITE,
            }}
          >
            {mode.kicker}
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: scaled(16) }}>
          {locality ? (
            <span
              style={{
                fontFamily: `"${FONT_DISPLAY}"`,
                fontWeight: WEIGHT.medium,
                fontSize: scaled(22),
                color: hexToRgba(WHITE, 0.6),
              }}
            >
              {locality}
            </span>
          ) : null}
          <div style={{ width: 1, height: scaled(22), backgroundColor: hexToRgba(WHITE, 0.3) }} />
          <span
            style={{
              fontFamily: `"${FONT_DISPLAY}"`,
              fontWeight: WEIGHT.bold,
              fontSize: scaled(24),
              letterSpacing: "0.12em",
              color: mode.accent,
              textTransform: "uppercase",
            }}
          >
            {sectionLabel}
          </span>
        </div>
      </div>
    );
  }

  // "modular" — Datos: tags cuadrados a ambos extremos, sensación de UI de
  // panel de datos.
  return (
    <div
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        right: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: `${scaled(26)}px ${pad}px ${scaled(18)}px ${pad}px`,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: scaled(12),
          padding: `${scaled(8)}px ${scaled(16)}px ${scaled(8)}px ${scaled(10)}px`,
          borderRadius: scaled(10),
          border: `1px solid ${hexToRgba(WHITE, 0.18)}`,
        }}
      >
        <Img src={staticFile("logo.png")} style={{ width: scaled(26), height: scaled(26), objectFit: "contain" }} />
        <span
          style={{
            fontFamily: `"${FONT_DISPLAY}"`,
            fontWeight: WEIGHT.bold,
            fontSize: scaled(22),
            letterSpacing: "0.08em",
            color: WHITE,
            textTransform: "uppercase",
          }}
        >
          {mode.kicker}
        </span>
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: scaled(10),
          padding: `${scaled(8)}px ${scaled(16)}px`,
          borderRadius: scaled(10),
          backgroundColor: hexToRgba(mode.accent, 0.16),
          border: `1px solid ${hexToRgba(mode.accent, 0.5)}`,
        }}
      >
        {locality ? (
          <>
            <span style={{ fontFamily: `"${FONT_DISPLAY}"`, fontWeight: WEIGHT.medium, fontSize: scaled(22), color: hexToRgba(WHITE, 0.7) }}>
              {locality}
            </span>
            <div style={{ width: 1, height: scaled(18), backgroundColor: hexToRgba(mode.accent, 0.5) }} />
          </>
        ) : null}
        <span
          style={{
            fontFamily: `"${FONT_DISPLAY}"`,
            fontWeight: WEIGHT.bold,
            fontSize: scaled(22),
            letterSpacing: "0.1em",
            color: mode.accent,
            textTransform: "uppercase",
          }}
        >
          {sectionLabel}
        </span>
      </div>
    </div>
  );
};
