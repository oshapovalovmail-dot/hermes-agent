import React from "react";
import { ICONS, ICON_NAMES } from "./icon-data.js";

/**
 * Icon — renders one glyph from the ПСиИИ / Yandex line-icon set (225 icons).
 * Icons are addressed by semantic name ("search", "bell", "settings", "trash"…).
 * See ICON_NAMES or the Icons gallery card for the full list. (Правило 73.)
 *
 * Single-color filled paths; the main shape follows `currentColor`, so set
 * `color=` on the icon (or any ancestor). Default render size 24px. A few
 * duotone glyphs (doc_plus, bookmark_cross, power…) knock out detail using
 * --ds-icon-bg (defaults to #fff); on dark surfaces pass `bg="<surface>"`
 * (or set --ds-icon-bg) so the knockout matches.
 */
export function Icon({ name = "search", size = 24, color, bg, style, className, ...rest }) {
  const def = ICONS[name] || ICONS[ICON_NAMES[0]];
  const css = { display: "inline-block", flex: "none", color, ...style };
  if (bg) css["--ds-icon-bg"] = bg;
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox={def.viewBox}
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
      style={css}
      dangerouslySetInnerHTML={{ __html: def.body }}
      {...rest}
    />
  );
}

export { ICON_NAMES };
