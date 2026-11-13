import React from "react";

/**
 * ListItem — ПСиИИ / Yandex UI-kit row. Height 32, radius 8, padding 6/8, gap 8.
 * Optional leading icon, trailing hint (black-44%) or badge. Hover → black-6%.
 * Selected → black-6% kept + graphite label. Label YS Text Regular 14/20.
 */
export function ListItem({
  label,
  iconLeft,
  hint,
  trailing,
  selected = false,
  disabled,
  onClick,
  style,
  ...rest
}) {
  const [hover, setHover] = React.useState(false);
  const bg = selected || hover ? "var(--control-secondary)" : "transparent";
  return (
    <div
      role="menuitem"
      onClick={(e) => { if (!disabled && onClick) onClick(e); }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        minHeight: 32,
        padding: "6px 8px",
        borderRadius: 8,
        background: bg,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.4 : 1,
        fontFamily: "var(--font-text)",
        fontWeight: "var(--fw-regular)",
        fontSize: 14,
        lineHeight: "20px",
        color: "var(--gray-900)",
        transition: "background var(--dur-fast) var(--ease-standard)",
        ...style,
      }}
      {...rest}
    >
      {iconLeft}
      <span style={{ flex: 1, minWidth: 0, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
        {label}
      </span>
      {hint != null && (
        <span style={{ flexShrink: 0, color: "rgba(0,0,0,0.44)" }}>{hint}</span>
      )}
      {trailing}
    </div>
  );
}
