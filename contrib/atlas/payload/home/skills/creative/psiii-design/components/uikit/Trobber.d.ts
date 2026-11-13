import * as React from "react";

export interface TrobberProps extends React.HTMLAttributes<HTMLSpanElement> {
  /** Diameter in px: 24 (small) or 64 (large). Default 24. */
  size?: 24 | 64 | number;
  /** Arc color. Default graphite. Pass #FFFFFF on dark surfaces. */
  color?: string;
}

/**
 * Trobber — rotating graphite arc spinner.
 *
 * @startingPoint section="UI kit" subtitle="Trobber — loading spinner" viewport="240x120"
 */
export function Trobber(props: TrobberProps): JSX.Element;
