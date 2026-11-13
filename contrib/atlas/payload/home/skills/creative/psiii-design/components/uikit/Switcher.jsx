import React from "react";

/**
 * Switcher — ПСиИИ / Yandex UI-kit toggle. Pill track, white knob.
 * On → graphite track; off → black 18% track. Sizes: normal (track 44×24) and
 * small (track 36×20). (Правило 75.)
 */
export function Switcher({
  checked = false,
  size = "normal",
  disabled,
  onChange,
  style,
  ...rest
}) {
  const dims = size === "small"
    ? { w: 36, h: 20, knob: 16 }
    : { w: 44, h: 24, knob: 20 };
  const pad = (dims.h - dims.knob) / 2;
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={(e) => { if (!disabled && onChange) onChange(!checked, e); }}
      style={{
        position: "relative",
        width: dims.w,
        height: dims.h,
        border: "none",
        padding: 0,
        borderRadius: 999,
        background: checked ? "var(--graphite)" : "rgba(0,0,0,0.18)",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.4 : 1,
        transition: "background var(--dur-fast) var(--ease-standard)",
        flexShrink: 0,
        ...style,
      }}
      {...rest}
    >
      <span
        style={{
          position: "absolute",
          top: pad,
          left: checked ? dims.w - dims.knob - pad : pad,
          width: dims.knob,
          height: dims.knob,
          borderRadius: "50%",
          background: "#FFFFFF",
          boxShadow: "0 1px 2px rgba(0,0,0,0.3)",
          transition: "left var(--dur-fast) var(--ease-standard)",
        }}
      />
    </button>
  );
}
