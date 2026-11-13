import * as React from "react";

export interface SwitcherProps extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "onChange"> {
  checked?: boolean;
  /** "normal" (44×24) or "small" (36×20). Default "normal". */
  size?: "normal" | "small";
  disabled?: boolean;
  onChange?: (checked: boolean, e: React.MouseEvent) => void;
}

/**
 * Switcher — pill toggle. On = graphite track, white knob.
 *
 * @startingPoint section="UI kit" subtitle="Switcher — graphite on / black-18% off" viewport="240x100"
 */
export function Switcher(props: SwitcherProps): JSX.Element;
