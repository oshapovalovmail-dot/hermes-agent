import * as React from "react";

export interface DividerProps extends React.HTMLAttributes<HTMLDivElement> {
  orientation?: "horizontal" | "vertical";
  /** Margin along the line in px. Default 0. */
  inset?: number;
}

/**
 * Divider — hairline separator rgba(0,0,0,0.09).
 *
 * @startingPoint section="UI kit" subtitle="Divider — hairline separator" viewport="320x60"
 */
export function Divider(props: DividerProps): JSX.Element;
