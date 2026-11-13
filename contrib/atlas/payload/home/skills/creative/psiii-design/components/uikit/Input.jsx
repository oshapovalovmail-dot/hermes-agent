import React from "react";

/**
 * Input — ПСиИИ / Yandex UI-kit text field. Rounded (radius 12), white surface
 * with a hairline stroke that turns graphite on focus. Optional label above and
 * leading icon. Text YS Text Regular 14/20. (Правило 75.)
 */
export function Input({
  label,
  placeholder,
  value,
  defaultValue,
  iconLeft,
  size = 36,
  disabled,
  onChange,
  style,
  inputStyle,
  ...rest
}) {
  const [focused, setFocused] = React.useState(false);
  const px = size >= 48 ? 16 : 12;
  return (
    <label style={{ display: "inline-flex", flexDirection: "column", gap: 6, ...style }}>
      {label != null && (
        <span style={{
          fontFamily: "var(--font-text)", fontWeight: "var(--fw-regular)",
          fontSize: 13, lineHeight: "16px", color: "var(--text-muted)",
        }}>{label}</span>
      )}
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 8,
          height: size,
          padding: `0 ${px}px`,
          borderRadius: 12,
          background: "var(--white)",
          boxShadow: focused
            ? "inset 0 0 0 2px var(--graphite)"
            : "inset 0 0 0 1px var(--control-stroke)",
          opacity: disabled ? 0.4 : 1,
          transition: "box-shadow var(--dur-fast) var(--ease-standard)",
        }}
      >
        {iconLeft}
        <input
          type="text"
          placeholder={placeholder}
          value={value}
          defaultValue={defaultValue}
          disabled={disabled}
          onChange={onChange}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          style={{
            flex: 1,
            minWidth: 0,
            border: "none",
            outline: "none",
            background: "transparent",
            fontFamily: "var(--font-text)",
            fontWeight: "var(--fw-regular)",
            fontSize: 14,
            lineHeight: "20px",
            color: "var(--gray-900)",
            ...inputStyle,
          }}
          {...rest}
        />
      </span>
    </label>
  );
}
