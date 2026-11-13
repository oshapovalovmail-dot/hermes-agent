import React from "react";

let __spinInjected = false;
function ensureKeyframes() {
  if (__spinInjected || typeof document === "undefined") return;
  __spinInjected = true;
  const s = document.createElement("style");
  s.textContent = "@keyframes ps-trobber-spin{to{transform:rotate(360deg)}}";
  document.head.appendChild(s);
}

/**
 * Trobber — ПСиИИ / Yandex UI-kit spinner. A graphite arc ring that rotates.
 * Sizes 24 (small) or 64 (large). Pass color to recolor (e.g. white on dark).
 * (Правило 75.)
 */
export function Trobber({ size = 24, color = "var(--graphite)", style, ...rest }) {
  ensureKeyframes();
  const stroke = size >= 48 ? 4 : 2.5;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  return (
    <span
      role="status"
      aria-label="Загрузка"
      style={{ display: "inline-flex", width: size, height: size, ...style }}
      {...rest}
    >
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        style={{ animation: "ps-trobber-spin 0.8s linear infinite" }}
      >
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${c * 0.28} ${c}`}
        />
      </svg>
    </span>
  );
}
