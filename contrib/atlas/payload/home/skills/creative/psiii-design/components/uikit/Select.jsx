import React from "react";

/**
 * Select — ПСиИИ / Yandex UI-kit dropdown trigger. Same shell as Input plus a
 * trailing chevron. Renders as a button; wire onClick to your menu/Context Menu.
 * Placeholder shows muted until a value is picked. (Правило 75.)
 */
export function Select({
  label,
  placeholder = "Выберите",
  value,
  iconLeft,
  size = 36,
  disabled,
  onClick,
  style,
  ...rest
}) {
  const px = size >= 48 ? 16 : 12;
  const hasValue = value != null && value !== "";
  return (
    <span style={{ display: "inline-flex", flexDirection: "column", gap: 6, ...style }}>
      {label != null && (
        <span style={{
          fontFamily: "var(--font-text)", fontWeight: "var(--fw-regular)",
          fontSize: 13, lineHeight: "16px", color: "var(--text-muted)",
        }}>{label}</span>
      )}
      <button
        type="button"
        disabled={disabled}
        onClick={onClick}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 8,
          height: size,
          padding: `0 ${px}px`,
          borderRadius: 12,
          background: "var(--white)",
          boxShadow: "inset 0 0 0 1px var(--control-stroke)",
          cursor: disabled ? "not-allowed" : "pointer",
          opacity: disabled ? 0.4 : 1,
          fontFamily: "var(--font-text)",
          fontWeight: "var(--fw-regular)",
          fontSize: 14,
          lineHeight: "20px",
          color: hasValue ? "var(--gray-900)" : "var(--text-muted)",
        }}
        {...rest}
      >
        {iconLeft}
        <span style={{ flex: 1, minWidth: 0, textAlign: "left", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {hasValue ? value : placeholder}
        </span>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" style={{ flexShrink: 0 }}>
          <path d="M6 9l6 6 6-6" stroke="var(--gray-900)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
    </span>
  );
}
