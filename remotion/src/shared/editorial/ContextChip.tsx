import React from "react";
import { FONT_DISPLAY, ModeTokens, WEIGHT, hexToRgba, WHITE } from "../designSystem";

// Chip de contexto (localidad / fuente / fecha / estado). Sólo se renderiza
// cuando el caller pasa un valor real — nunca se inventa un dato editorial
// para llenar espacio.
export const ContextChip: React.FC<{ mode: ModeTokens; label: string }> = ({ mode, label }) =>
  label ? (
    <div
      style={{
        display: "inline-flex",
        alignSelf: "flex-start",
        alignItems: "center",
        padding: "12px 24px",
        borderRadius: 999,
        border: `2px solid ${hexToRgba(mode.accent, 0.55)}`,
        backgroundColor: hexToRgba(mode.accent, 0.12),
      }}
    >
      <span
        style={{
          fontFamily: `"${FONT_DISPLAY}"`,
          fontWeight: WEIGHT.bold,
          fontSize: 29,
          letterSpacing: "0.08em",
          color: WHITE,
          textTransform: "uppercase",
        }}
      >
        {label}
      </span>
    </div>
  ) : null;
