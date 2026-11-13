import React from "react";

/**
 * SlideFooter — the standard ПСиИИ slide footer line.
 * 15px, 50% opacity. Left: the business-group label. Right: brandbook year
 * or page number. Sits in the 20px safe area at the bottom of a slide.
 */
export function SlideFooter({
  label = "Яндекс Поисковые сервисы и ИИ",
  right = "Брендбук 2026",
  style,
  className,
  ...rest
}) {
  return (
    <div
      className={className}
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: "var(--space-12)",
        fontFamily: "var(--font-text)",
        fontWeight: "var(--fw-regular)",
        fontSize: "var(--type-footer)",
        letterSpacing: "var(--tracking-caption)",
        lineHeight: 1.1,
        color: "var(--text-footer)",
        ...style,
      }}
      {...rest}
    >
      <span>{label}</span>
      {right != null && right !== "" ? <span>{right}</span> : null}
    </div>
  );
}
