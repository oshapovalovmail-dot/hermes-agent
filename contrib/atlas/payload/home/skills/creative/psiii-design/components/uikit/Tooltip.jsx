import React from "react";

/**
 * Tooltip — ПСиИИ / Yandex UI-kit hint bubble. Graphite #2C2C31 surface, white
 * YS Text Regular 14/20, radius 8, optional arrow on one side. (Правило 75.)
 */
export function Tooltip({ children, arrow = "bottom", style, ...rest }) {
  const arrowSize = 6;
  const bg = "rgb(44,44,49)";
  const arrowStyles = {
    bottom: { left: "50%", bottom: -arrowSize, transform: "translateX(-50%)" },
    top: { left: "50%", top: -arrowSize, transform: "translateX(-50%)" },
    left: { top: "50%", left: -arrowSize, transform: "translateY(-50%)" },
    right: { top: "50%", right: -arrowSize, transform: "translateY(-50%)" },
  };
  return (
    <div
      role="tooltip"
      style={{
        position: "relative",
        display: "inline-block",
        maxWidth: 280,
        padding: "8px 12px",
        borderRadius: 8,
        background: bg,
        color: "#FFFFFF",
        fontFamily: "var(--font-text)",
        fontWeight: "var(--fw-regular)",
        fontSize: 14,
        lineHeight: "20px",
        ...style,
      }}
      {...rest}
    >
      {children}
      {arrow && (
        <span
          style={{
            position: "absolute",
            width: arrowSize * 2,
            height: arrowSize * 2,
            background: bg,
            transform: (arrowStyles[arrow].transform || "") + " rotate(45deg)",
            borderRadius: 1,
            ...arrowStyles[arrow],
          }}
        />
      )}
    </div>
  );
}
