import * as React from "react";

export interface SelectProps extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "value" | "size" | "style"> {
  label?: React.ReactNode;
  placeholder?: string;
  /** Selected value label. Empty → placeholder shown muted. */
  value?: React.ReactNode;
  iconLeft?: React.ReactNode;
  /** Trigger height in px. Default 36. */
  size?: number;
  style?: React.CSSProperties;
}

/**
 * Select — dropdown trigger (Input shell + chevron). Wire onClick to a menu.
 *
 * @startingPoint section="UI kit" subtitle="Select — dropdown trigger" viewport="420x120"
 */
export function Select(props: SelectProps): JSX.Element;
