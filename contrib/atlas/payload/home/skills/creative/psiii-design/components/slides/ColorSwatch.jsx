import React from "react";

/**
 * ColorSwatch — a palette chip the way the brandbook documents color: a sharp
 * (0-radius) block of color with its hex value beneath. Used on palette slides
 * and in the design-system docs.
 */
export function ColorSwatch({
  color,
  value,
  label,
  w = 500,
  h = 321,
  style,
  className,
  ...rest
}) {
  return (
    <div className={className} style={{ display: "inline-flex", flexDirection: "column", gap: 16, ...style }} {...rest}>
      <div
        style={{
          width: w,
          height: h,
          background: color,
          borderRadius: "var(--radius-0)",
          boxShadow: isLight(color) ? "inset 0 0 0 1px var(--border-subtle)" : "none",
        }}
      />
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <span
          style={{
            fontFamily: "var(--font-text)",
            fontWeight: "var(--fw-regular)",
            fontSize: 48,
            lineHeight: 1.2,
            letterSpacing: "var(--tracking-caption)",
            color: "var(--text-body)",
          }}
        >
          {value}
        </span>
        {label ? (
          <span style={{ fontFamily: "var(--font-text)", fontSize: "var(--type-caption-l)", color: "var(--text-muted)" }}>{label}</span>
        ) : null}
      </div>
    </div>
  );
}

function isLight(c) {
  if (typeof c !== "string" || c[0] !== "#") return false;
  let h = c.slice(1);
  if (h.length === 3) h = h.split("").map((x) => x + x).join("");
  const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
  return 0.299 * r + 0.587 * g + 0.114 * b > 235;
}
