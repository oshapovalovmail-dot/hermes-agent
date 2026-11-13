import React from "react";

/**
 * Tag — ПСиИИ / Yandex UI-kit chip ("Tag Item"). Pill (radius 36), black-6%
 * surface, YS Text Regular 14/20, height 28. Optional removable × (Close Circle
 * Fill, black-45%); `pinned` shows the chip with no remove control. Extra tones
 * (dark / accent / outline) are kept for slide labels. (Правило 75.)
 */
export function Tag({
  children,
  tone = "neutral",
  iconLeft,
  removable = false,
  pinned = false,
  onRemove,
  radius,
  style,
  className,
  ...rest
}) {
  const [hover, setHover] = React.useState(false);
  const tones = {
    neutral: {
      background: hover && !pinned ? "rgba(0,0,0,0.10)" : "rgba(0,0,0,0.06)",
      color: "var(--gray-900)",
    },
    dark: { background: "var(--graphite)", color: "var(--white)" },
    accent: { background: "var(--accent)", color: "var(--white)" },
    outline: { background: "transparent", color: "var(--gray-900)", boxShadow: "inset 0 0 0 1px var(--border-subtle)" },
  };
  const t = tones[tone] || tones.neutral;
  const showClose = removable && !pinned;
  return (
    <span
      className={className}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        height: 28,
        padding: showClose ? "0 8px 0 12px" : "0 12px",
        borderRadius: radius != null ? radius : 36,
        fontFamily: "var(--font-text)",
        fontWeight: "var(--fw-regular)",
        fontSize: 14,
        lineHeight: "20px",
        whiteSpace: "nowrap",
        transition: "background var(--dur-fast) var(--ease-standard)",
        ...t,
        ...style,
      }}
      {...rest}
    >
      {iconLeft}
      {children}
      {showClose && (
        <button
          type="button"
          aria-label="Удалить"
          onClick={(e) => { e.stopPropagation(); onRemove && onRemove(e); }}
          style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            width: 16,
            height: 16,
            padding: 0,
            border: "none",
            background: "transparent",
            cursor: "pointer",
            flexShrink: 0,
          }}
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <circle cx="8" cy="8" r="8" fill={tone === "dark" || tone === "accent" ? "rgba(255,255,255,0.4)" : "rgba(0,0,0,0.45)"} />
            <path d="M5.5 5.5l5 5M10.5 5.5l-5 5" stroke="#FFFFFF" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </button>
      )}
    </span>
  );
}
