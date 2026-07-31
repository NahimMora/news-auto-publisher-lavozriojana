import React from "react";
import { FONT_DISPLAY, WEIGHT, WHITE } from "./designSystem";

// Badge de sección reutilizable entre PremiumSlide y AutomaticInstagramCard
// — jerarquía sección→titular→marca definida una sola vez.
export const SectionBadge: React.FC<{ label: string; accent: string; size?: "sm" | "md" }> = ({
  label,
  accent,
  size = "md",
}) => {
  const fontSize = size === "sm" ? 21 : 26;
  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        alignSelf: "flex-start",
        padding: size === "sm" ? "7px 16px" : "10px 20px",
        borderRadius: 999,
        backgroundColor: accent,
      }}
    >
      <span
        style={{
          fontFamily: `"${FONT_DISPLAY}"`,
          fontWeight: WEIGHT.bold,
          fontSize,
          letterSpacing: "0.14em",
          color: WHITE,
          textTransform: "uppercase",
        }}
      >
        {label}
      </span>
    </div>
  );
};
