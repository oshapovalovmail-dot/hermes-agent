import React from "react";
import { Logo } from "../brand/Logo.jsx";

/**
 * SlideHeader — the top safe-area bar of a content slide. By default: a small
 * left-hand label (the section / business-group name) and the small dark Yandex
 * corner mark on the right. Pass `left` text or set `mark={false}` to hide it.
 */
export function SlideHeader({ left = "Поисковые сервисы и ИИ", mark = true, style, className, ...rest }) {
  return (
    <div
      className={className}
      style={{
        position: "absolute",
        top: 20,
        left: 20,
        right: 20,
        height: 40,
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "space-between",
        ...style,
      }}
      {...rest}
    >
      <span
        style={{
          fontFamily: "var(--font-text)",
          fontWeight: "var(--fw-regular)",
          fontSize: "var(--type-caption-l)",
          lineHeight: 0.95,
          color: "rgba(0,0,0,0.8)",
        }}
      >
        {left}
      </span>
      {mark ? <Logo kind="mark" tone="dark" height={40} /> : null}
    </div>
  );
}
