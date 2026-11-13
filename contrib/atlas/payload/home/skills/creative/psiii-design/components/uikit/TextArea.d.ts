import * as React from "react";

export interface TextAreaProps extends Omit<React.TextareaHTMLAttributes<HTMLTextAreaElement>, "style"> {
  label?: React.ReactNode;
  /** Show a red required asterisk next to the label. */
  required?: boolean;
  /** Style for the outer label wrapper. */
  style?: React.CSSProperties;
  /** Style for the inner <textarea>. */
  textareaStyle?: React.CSSProperties;
}

/**
 * TextArea — multi-line field, hairline stroke → graphite on focus, resizable.
 *
 * @startingPoint section="UI kit" subtitle="TextArea — multi-line field" viewport="440x200"
 */
export function TextArea(props: TextAreaProps): JSX.Element;
