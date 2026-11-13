import * as React from "react";

/**
 * A big display metric with an optional caption — the deck stat pattern.
 */
export interface StatNumberProps extends React.HTMLAttributes<HTMLDivElement> {
  /** The figure, e.g. "24%". */
  value: React.ReactNode;
  /** Optional caption beneath (one or two lines). */
  caption?: React.ReactNode;
  /** Render the value in Yandex red. Default false. */
  accent?: boolean;
  /** Figure size in px. Default 180. */
  size?: number;
  /** Text alignment. Default "left". */
  align?: "left" | "center";
}

/**
 * A big display metric with an optional caption — the deck stat pattern.
 *
 * @startingPoint section="Slides" subtitle="Big metric figure + caption" viewport="700x320"
 */
export function StatNumber(props: StatNumberProps): JSX.Element;
