import * as React from "react";

export type ButtonType =
  | "primary"
  | "secondary"
  | "stroke"
  | "ghost"
  | "link"
  | "accent";
export type ButtonSize = 24 | 28 | 36 | 64;

/**
 * The ПСиИИ interface button — pill-shaped, flat, YS Text Regular.
 * Values mirror the Yandex UI-kit: graphite primary fill, translucent-black
 * secondary, hairline stroke, blue link (UI-only), and a rare red accent CTA.
 */
export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /**
   * "primary" (graphite #2C2C32) · "secondary" (black 6%) · "stroke" (hairline) ·
   * "ghost" (transparent) · "link" (blue #0077FF, UI-only) · "accent" (red — one
   * main CTA per screen, use sparingly).
   */
  type?: ButtonType;
  /** Pill height in px: 24 · 28 · 36 · 64. Default 36. Prefer ≥36 on slides. */
  size?: ButtonSize;
  /** Icon-only button: pass a single icon as children, omit the label. */
  iconOnly?: boolean;
  iconLeft?: React.ReactNode;
  iconRight?: React.ReactNode;
}

/**
 * The ПСиИИ interface button — pill-shaped, flat, YS Text Regular.
 *
 * @startingPoint section="Core" subtitle="Pill buttons — graphite / secondary / stroke / ghost / link / accent" viewport="760x160"
 */
export function Button(props: ButtonProps): JSX.Element;
