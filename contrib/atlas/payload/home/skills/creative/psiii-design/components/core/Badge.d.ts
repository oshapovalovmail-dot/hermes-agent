import * as React from "react";

export type BadgeTone = "accent" | "dark" | "neutral";

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  /** "accent" (red) · "dark" (ink) · "neutral" (gray). */
  tone?: BadgeTone;
  /** Render a bare 10px status dot instead of a labelled badge. */
  dot?: boolean;
}

/** A tiny count / status indicator (dot or short number). Use Tag for words. */
export function Badge(props: BadgeProps): JSX.Element;
