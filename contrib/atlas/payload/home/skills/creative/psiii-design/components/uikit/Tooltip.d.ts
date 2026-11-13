import * as React from "react";

export interface TooltipProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Side the arrow points from, or false for no arrow. Default "bottom". */
  arrow?: "top" | "bottom" | "left" | "right" | false;
}

/**
 * Tooltip — graphite bubble, white text, optional arrow.
 *
 * @startingPoint section="UI kit" subtitle="Tooltip — graphite hint bubble" viewport="360x140"
 */
export function Tooltip(props: TooltipProps): JSX.Element;
