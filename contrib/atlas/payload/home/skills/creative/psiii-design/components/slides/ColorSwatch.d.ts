import * as React from "react";

export interface ColorSwatchProps extends React.HTMLAttributes<HTMLDivElement> {
  /** The swatch fill (any CSS color). */
  color: string;
  /** Hex value shown beneath, e.g. "#FC3F1D". */
  value: string;
  /** Optional name beneath the value. */
  label?: string;
  /** Swatch width / height in px. Defaults 500×321 (the brandbook block). */
  w?: number;
  h?: number;
}

/** A sharp palette chip with its hex value — the brandbook color-block pattern. */
export function ColorSwatch(props: ColorSwatchProps): JSX.Element;
