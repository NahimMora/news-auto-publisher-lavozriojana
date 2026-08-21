import React from "react";
import { FONT_DISPLAY, FONT_SERIF, ModeTokens, TYPE, WEIGHT, WHITE, hexToRgba } from "../designSystem";

// Cifra grande + unidad + contexto + comparación visual. `comparison` sólo
// se pinta cuando el caller la provee explícitamente (0-1): nunca se
// inventa una proporción para "llenar" el módulo.
export const DataModule: React.FC<{
  mode: ModeTokens;
  value: string;
  unit?: string;
  comparison?: { ratio: number; label: string } | null;
  width: number;
}> = ({ mode, value, unit, comparison, width }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 22, width }}>
    <div style={{ display: "flex", alignItems: "flex-end", gap: 16 }}>
      <div
        style={{
          fontFamily: `"${FONT_DISPLAY}"`,
          fontWeight: TYPE.number.weight,
          fontSize: Math.round(TYPE.number.size * 1.05),
          lineHeight: TYPE.number.lineHeightRatio,
          color: mode.accent,
        }}
      >
        {value}
      </div>
      {unit ? (
        <div
          style={{
            fontFamily: `"${mode.useSerifAccent ? FONT_SERIF : FONT_DISPLAY}"`,
            fontStyle: mode.useSerifAccent ? "italic" : "normal",
            fontWeight: WEIGHT.bold,
            fontSize: Math.round(TYPE.number.unit * 1.12),
            color: WHITE,
            paddingBottom: 22,
          }}
        >
          {unit}
        </div>
      ) : null}
    </div>

    {comparison ? (
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ width: "100%", height: 10, borderRadius: 5, backgroundColor: hexToRgba(WHITE, 0.14), overflow: "hidden" }}>
          <div
            style={{
              width: `${Math.max(4, Math.min(100, comparison.ratio * 100))}%`,
              height: "100%",
              backgroundColor: mode.accent,
              borderRadius: 5,
            }}
          />
        </div>
        <div style={{ fontFamily: `"${FONT_DISPLAY}"`, fontWeight: WEIGHT.medium, fontSize: 28, color: hexToRgba(WHITE, 0.68) }}>
          {comparison.label}
        </div>
      </div>
    ) : null}
  </div>
);
