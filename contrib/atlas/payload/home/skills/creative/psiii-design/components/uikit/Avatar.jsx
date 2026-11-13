import React from "react";

/**
 * Avatar — ПСиИИ / Yandex UI-kit. Circle with image or initials on a graphite
 * fill. Sizes 24 / 32 / 40 / 48. Optional badge dot (e.g. notifications) at the
 * bottom-right. (Правило 75.)
 */
export function Avatar({
  src,
  alt = "",
  initials,
  size = 40,
  badge = false,
  style,
  ...rest
}) {
  const fs = Math.round(size * 0.4);
  const dot = Math.round(size * 0.28);
  return (
    <span
      style={{
        position: "relative",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: size,
        height: size,
        borderRadius: "50%",
        overflow: "hidden",
        background: "var(--graphite)",
        color: "#FFFFFF",
        fontFamily: "var(--font-text)",
        fontWeight: "var(--fw-regular)",
        fontSize: fs,
        lineHeight: 1,
        flexShrink: 0,
        ...style,
      }}
      {...rest}
    >
      {src ? (
        <img src={src} alt={alt} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      ) : (
        initials
      )}
      {badge && (
        <span
          style={{
            position: "absolute",
            right: 0,
            bottom: 0,
            width: dot,
            height: dot,
            borderRadius: "50%",
            background: "var(--accent)",
            boxShadow: "0 0 0 2px var(--white)",
            overflow: "visible",
          }}
        />
      )}
    </span>
  );
}
