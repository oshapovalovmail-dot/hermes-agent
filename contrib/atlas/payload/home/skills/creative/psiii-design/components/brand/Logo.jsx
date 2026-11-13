import React from "react";
import { LOGOS } from "./logo-data.js";

/**
 * Logo — the brand marks for Яндекс · Поисковые сервисы и ИИ.
 *
 *  kind="mark"   → the round Yandex «Я» mark (red on white by default)
 *  kind="yandex" → the Yandex wordmark (+ red «Я»)
 *  kind="psiii"  → the ПСиИИ wordmark
 *
 *  tone="brand" (default) keeps the original brand colors.
 *  tone="dark"  renders the logo solid ink (#1F1F20) — for the small corner mark.
 *  tone="light" renders it solid white — for use on dark / photo backgrounds.
 */
export function Logo({ kind = "yandex", tone = "brand", height, width, style, className, ...rest }) {
  const def = LOGOS[kind] || LOGOS.yandex;
  const [, , vbw, vbh] = def.viewBox.split(" ").map(Number);

  let body = def.body;
  if (tone === "dark") body = recolor(body, "#1F1F20");
  else if (tone === "light") body = recolor(body, "#FFFFFF");

  // default sizing: lock to height, preserve aspect
  let h = height, w = width;
  if (h == null && w == null) h = kind === "mark" ? 40 : 48;
  if (h != null && w == null) w = (vbw / vbh) * h;
  if (w != null && h == null) h = (vbh / vbw) * w;

  return (
    <svg
      className={className}
      width={w}
      height={h}
      viewBox={def.viewBox}
      role="img"
      aria-label={LABELS[kind]}
      xmlns="http://www.w3.org/2000/svg"
      style={{ display: "block", flex: "none", ...style }}
      dangerouslySetInnerHTML={{ __html: body }}
      {...rest}
    />
  );
}

const LABELS = {
  mark: "Яндекс",
  yandex: "Яндекс",
  psiii: "Поисковые сервисы и ИИ",
};

function recolor(svg, color) {
  // force every fill (named or hex) to a single color, preserving fill="none"
  return svg.replace(/fill="(?!none")[^"]*"/g, `fill="${color}"`);
}
