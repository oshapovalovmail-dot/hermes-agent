import React from "react";

/**
 * Button — the ПСиИИ interface button, mirrored from the Yandex UI-kit.
 * Pill-shaped (radius-full), flat, YS Text Regular 14/20 (Правило 75).
 *
 * Types: primary (graphite #2C2C32) · secondary (black 6%) · stroke (hairline
 * 12%) · ghost (transparent) · link (blue #0077FF — UI only, never on slides) ·
 * accent (Yandex red — one main CTA per screen, use sparingly).
 *
 * Sizes are the kit's pixel heights: 24 / 28 / 36 / 64. Default 36.
 */
export function Button({
  type = "primary",
  size = 36,
  children,
  iconLeft,
  iconRight,
  iconOnly = false,
  disabled,
  style,
  className,
  ...rest
}) {
  // height → { padding-x, icon, font, gap } — values from the kit
  const sizes = {
    24: { px: 8, icon: 14, fs: 13, gap: 4 },
    28: { px: 12, icon: 16, fs: 14, gap: 8 },
    36: { px: 16, icon: 16, fs: 14, gap: 8 },
    64: { px: 28, icon: 24, fs: 18, gap: 10 },
  };
  const s = sizes[size] || sizes[36];

  const types = {
    primary: { background: "var(--graphite)", color: "var(--white)" },
    secondary: { background: "var(--control-secondary)", color: "var(--gray-900)" },
    stroke: { background: "transparent", color: "var(--gray-900)", boxShadow: "inset 0 0 0 1px var(--control-stroke)" },
    ghost: { background: "transparent", color: "var(--gray-900)" },
    link: { background: "transparent", color: "var(--link-blue)" },
    accent: { background: "var(--accent)", color: "var(--white)" },
  };
  const t = types[type] || types.primary;

  const pressColor = {
    primary: "var(--graphite-press)",
    accent: "var(--accent-press)",
    link: "var(--link-blue-press)",
  };

  return (
    <button
      className={className}
      disabled={disabled}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        gap: s.gap,
        height: size,
        width: iconOnly ? size : undefined,
        padding: iconOnly ? 0 : `0 ${s.px}px`,
        border: "none",
        borderRadius: "var(--radius-full)",
        fontFamily: "var(--font-text)",
        fontWeight: "var(--fw-regular)",
        fontSize: s.fs,
        lineHeight: "20px",
        letterSpacing: "0",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.4 : 1,
        whiteSpace: "nowrap",
        transition: "filter var(--dur-fast) var(--ease-standard), background var(--dur-fast) var(--ease-standard), opacity var(--dur-fast) var(--ease-standard)",
        ...t,
        ...style,
      }}
      onMouseDown={(e) => {
        if (disabled) return;
        const pc = pressColor[type];
        if (pc) e.currentTarget.style.background = pc;
        else e.currentTarget.style.filter = "brightness(0.96)";
      }}
      onMouseUp={(e) => { e.currentTarget.style.filter = "none"; e.currentTarget.style.background = ""; e.currentTarget.style.background = t.background; }}
      onMouseLeave={(e) => { e.currentTarget.style.filter = "none"; e.currentTarget.style.background = t.background; }}
      {...rest}
    >
      {iconLeft}
      {children}
      {iconRight}
    </button>
  );
}
