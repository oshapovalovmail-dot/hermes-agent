import * as React from "react";

export interface CheckboxProps extends Omit<React.HTMLAttributes<HTMLLabelElement>, "onChange"> {
  checked?: boolean;
  /** Box side in px: 20 (normal) or 16 (small). Default 20. */
  size?: 16 | 20;
  disabled?: boolean;
  label?: React.ReactNode;
  onChange?: React.ChangeEventHandler<HTMLInputElement>;
}

/**
 * Checkbox — square, radius 4. Checked = graphite fill + white check.
 *
 * @startingPoint section="UI kit" subtitle="Checkbox — graphite fill, hairline stroke" viewport="320x120"
 */
export function Checkbox(props: CheckboxProps): JSX.Element;
