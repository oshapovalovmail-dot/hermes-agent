import * as React from "react";

export interface InputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "size" | "style"> {
  label?: React.ReactNode;
  iconLeft?: React.ReactNode;
  /** Field height in px. Default 36. */
  size?: number;
  /** Style for the outer label wrapper. */
  style?: React.CSSProperties;
  /** Style for the inner <input>. */
  inputStyle?: React.CSSProperties;
}

/**
 * Input — rounded text field, hairline stroke → graphite on focus.
 *
 * @startingPoint section="UI kit" subtitle="Input — text field with focus ring" viewport="420x120"
 */
export function Input(props: InputProps): JSX.Element;
