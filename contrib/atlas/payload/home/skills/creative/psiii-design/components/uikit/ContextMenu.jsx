import React from "react";

/**
 * ContextMenu — ПСиИИ / Yandex UI-kit floating menu surface. White card,
 * radius 14, soft shadow, 4px padding; fill it with ListItem rows. Width 268
 * by default (the kit's row width). (Правило 75.)
 */
export function ContextMenu({ children, width = 268, style, ...rest }) {
  return (
    <div
      role="menu"
      style={{
        width,
        padding: 4,
        borderRadius: 14,
        background: "var(--white)",
        boxShadow: "0 4px 24px rgba(0,0,0,0.12), 0 0 0 1px rgba(0,0,0,0.04)",
        display: "flex",
        flexDirection: "column",
        gap: 2,
        ...style,
      }}
      {...rest}
    >
      {children}
    </div>
  );
}
