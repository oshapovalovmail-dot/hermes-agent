import React from "react";

/**
 * RadioButton — ПСиИИ / Yandex UI-kit. Circle 20 (normal) or 16 (small).
 * Selected → graphite fill + white dot; unselected → 2px hairline stroke.
 * Optional label in YS Text Regular 14/20. (Правило 75.)
 */
export function RadioButton({
  checked = false,
  size = 20,
  disabled,
  label,
  name,
  value,
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
        type="radio"
        name={name}
        value={value}
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
          borderRadius: "50%",
          flexShrink: 0,
          background: checked ? "var(--graphite)" : "transparent",
          boxShadow: checked ? "none" : "inset 0 0 0 2px var(--control-stroke)",
          transition: "background var(--dur-fast) var(--ease-standard)",
        }}
      >
        {checked && (
          <span
            style={{
              width: box * 0.4,
              height: box * 0.4,
              borderRadius: "50%",
              background: "#FFFFFF",
            }}
          />
        )}
      </span>
      {label != null && <span>{label}</span>}
    </label>
  );
}
