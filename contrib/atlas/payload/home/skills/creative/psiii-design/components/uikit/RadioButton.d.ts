import * as React from "react";

export interface RadioButtonProps extends Omit<React.HTMLAttributes<HTMLLabelElement>, "onChange"> {
  checked?: boolean;
  /** Circle diameter in px: 20 (normal) or 16 (small). Default 20. */
  size?: 16 | 20;
  disabled?: boolean;
  label?: React.ReactNode;
  name?: string;
  value?: string;
  onChange?: React.ChangeEventHandler<HTMLInputElement>;
}

/**
 * RadioButton — circle. Selected = graphite fill + white dot.
 *
 * @startingPoint section="UI kit" subtitle="Radio — graphite fill, hairline stroke" viewport="320x120"
 */
export function RadioButton(props: RadioButtonProps): JSX.Element;
