import * as React from "react";

export interface IconProps extends React.SVGProps<SVGSVGElement> {
  /** Semantic glyph name, e.g. "search" | "bell" | "settings" (see ICON_NAMES). */
  name?: string;
  /** Pixel size (width = height). Default 24. */
  size?: number;
  /** Main-shape color; defaults to currentColor. */
  color?: string;
  /** Knockout/background color for duotone glyphs (sets --ds-icon-bg). */
  bg?: string;
}

/**
 * One glyph from the ПСиИИ / Yandex line-icon set (225 icons), by semantic name.
 *
 * @startingPoint section="Brand" subtitle="Icon — Yandex line glyph" viewport="120x120"
 */
export function Icon(props: IconProps): JSX.Element;

/** All available icon names, alphabetical. */
export const ICON_NAMES: string[];

/** Per-icon metadata: name -> [ruLabel, groupCode, keywords]. Use for search/reuse. */
export const ICON_META: Record<string, [string, string, string]>;

/** Category code -> Russian label (nav, act, ui, doc, fold, comm, media, dev, user, map, nat, shop, misc). */
export const ICON_GROUPS: Record<string, string>;
