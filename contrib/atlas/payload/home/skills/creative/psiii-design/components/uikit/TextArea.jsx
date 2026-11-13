import React from "react";

/**
 * TextArea — ПСиИИ / Yandex UI-kit multi-line field. Rounded (radius 8), white
 * surface with hairline stroke → graphite on focus, padding 12/16, text
 * YS Text Regular 14/18, vertically resizable. Optional label (with required
 * asterisk) above. (Правило 75.)
 */
export function TextArea({
  label,
  required = false,
  placeholder,
  value,
  defaultValue,
  rows = 4,
  disabled,
  onChange,
  style,
  textareaStyle,
  ...rest
}) {
  const [focused, setFocused] = React.useState(false);
  return (
    <label style={{ display: "inline-flex", flexDirection: "column", gap: 8, ...style }}>
      {label != null && (
        <span style={{
          display: "inline-flex", gap: 2,
          fontFamily: "var(--font-text)", fontWeight: "var(--fw-regular)",
          fontSize: 14, lineHeight: "18px", color: "var(--gray-900)",
        }}>
          {label}
          {required && <span style={{ color: "rgb(255,51,51)", fontWeight: "var(--fw-bold)", fontSize: 13 }}>*</span>}
        </span>
      )}
      <span
        style={{
          display: "flex",
          borderRadius: 8,
          background: "var(--white)",
          boxShadow: focused
            ? "inset 0 0 0 2px var(--graphite)"
            : "inset 0 0 0 1px rgba(0,0,0,0.09)",
          opacity: disabled ? 0.4 : 1,
          transition: "box-shadow var(--dur-fast) var(--ease-standard)",
        }}
      >
        <textarea
          placeholder={placeholder}
          value={value}
          defaultValue={defaultValue}
          rows={rows}
          disabled={disabled}
          onChange={onChange}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          style={{
            flex: 1,
            minWidth: 0,
            resize: "vertical",
            border: "none",
            outline: "none",
            background: "transparent",
            padding: "12px 16px",
            fontFamily: "var(--font-text)",
            fontWeight: "var(--fw-regular)",
            fontSize: 14,
            lineHeight: "18px",
            color: "var(--gray-900)",
            ...textareaStyle,
          }}
          {...rest}
        />
      </span>
    </label>
  );
}
