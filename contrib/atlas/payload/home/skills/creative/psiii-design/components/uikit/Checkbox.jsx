import React from "react";

/**
 * Checkbox — ПСиИИ / Yandex UI-kit. Square 20 (normal) or 16 (small), radius 4.
 * Checked → graphite fill + white check; unchecked → 2px hairline stroke.
 * Optional label in YS Text Regular 14/20. (Правило 75.)
 */
export function Checkbox({
  checked = false,
  size = 20,
  disabled,
  label,
  onChange,
  style,
  ...rest
}) {
  const box = size === 16 ? 16 : 20;
  return (
    <label
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.4 : 1,
        fontFamily: "var(--font-text)",
        fontWeight: "var(--fw-regular)",
        fontSize: 14,
        lineHeight: "20px",
        color: "var(--gray-900)",
        ...style,
      }}
      {...rest}
    >
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={onChange}
        style={{ position: "absolute", opacity: 0, width: 0, height: 0 }}
      />
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          width: box,
          height: box,
          borderRadius: 4,
          flexShrink: 0,
          background: checked ? "var(--graphite)" : "transparent",
          boxShadow: checked ? "none" : "inset 0 0 0 2px var(--control-stroke)",
          transition: "background var(--dur-fast) var(--ease-standard)",
        }}
      >
        {checked && (
          <svg width={box * 0.6} height={box * 0.6} viewBox="0 0 12 8" fill="none">
            <path
              d="M 11.72 0.30 C 12.10 0.69 12.10 1.33 11.71 1.71 L 5.62 7.71 C 5.25 8.08 4.65 8.09 4.26 7.74 L 0.34 4.26 C -0.08 3.89 -0.11 3.26 0.25 2.84 C 0.62 2.43 1.25 2.39 1.67 2.76 L 4.89 5.63 L 10.30 0.29 C 10.70 -0.10 11.33 -0.10 11.72 0.30 Z"
              fill="#FFFFFF"
              fillRule="evenodd"
            />
          </svg>
        )}
      </span>
      {label != null && <span>{label}</span>}
    </label>
  );
}
