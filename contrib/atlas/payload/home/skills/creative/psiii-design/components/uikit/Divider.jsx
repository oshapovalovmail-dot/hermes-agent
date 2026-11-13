import React from "react";

/**
 * Divider — ПСиИИ / Yandex UI-kit. Hairline separator rgba(0,0,0,0.09).
 * Horizontal by default; pass orientation="vertical" for an inline rule.
 * (Правило 75.)
 */
export function Divider({ orientation = "horizontal", inset = 0, style, ...rest }) {
  const vertical = orientation === "vertical";
  return (
    <div
      role="separator"
      aria-orientation={orientation}
      style={{
        background: "rgba(0,0,0,0.09)",
        flexShrink: 0,
        ...(vertical
          ? { width: 1, alignSelf: "stretch", margin: `${inset}px 0` }
          : { height: 1, width: "100%", margin: `0 ${inset}px` }),
        ...style,
      }}
      {...rest}
    />
  );
}
