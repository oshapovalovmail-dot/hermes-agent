import React from "react";

/**
 * StatNumber — a big display figure with an optional caption beneath. The deck
 * pattern for metrics ("24%", "10%" + a one/two-line подпись). Set in YS Display
 * Cond Heavy with ultra-tight leading; the value can carry the red accent.
 */
export function StatNumber({
  value,
  caption,
  accent = false,
  size = 180,
  align = "left",
  style,
  className,
  ...rest
}) {
  return (
    <div
      className={className}
      style={{ display: "flex", flexDirection: "column", gap: 16, textAlign: align, alignItems: align === "center" ? "center" : "flex-start", ...style }}
      {...rest}
    >
      <span
        style={{
          fontFamily: "var(--font-display)",
          fontWeight: "var(--fw-heavy)",
          fontSize: size,
          lineHeight: "var(--leading-display)",
          letterSpacing: "var(--tracking-display)",
          color: accent ? "var(--accent)" : "var(--text-title)",
        }}
      >
        {value}
      </span>
      {caption != null && caption !== "" ? (
        <span
          style={{
            fontFamily: "var(--font-text)",
            fontWeight: "var(--fw-regular)",
            fontSize: "var(--type-caption-l)",
            lineHeight: 1.2,
            color: "var(--text-muted)",
            maxWidth: 360,
          }}
        >
          {caption}
        </span>
      ) : null}
    </div>
  );
}
