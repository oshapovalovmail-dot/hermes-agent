import * as React from "react";

export type SlideBg = "white" | "ink" | "maroon" | "accent";

/**
 * The fixed 1920×1080 ПСиИИ slide canvas — background, optional grid, content inset.
 */
export interface SlideFrameProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Background: "white" (default) · "ink" · "maroon" · "accent". */
  bg?: SlideBg;
  /** Show the always-on 12-column + safe-area grid. Default false. */
  grid?: boolean;
  /** Wrap children in the standard 40px content inset. Default true; set false to position freely. */
  inset?: boolean;
}

/**
 * The fixed 1920×1080 ПСиИИ slide canvas — background, optional grid, content inset.
 *
 * @startingPoint section="Slides" subtitle="1920×1080 slide canvas with grid" viewport="1280x720"
 */
export function SlideFrame(props: SlideFrameProps): JSX.Element;
