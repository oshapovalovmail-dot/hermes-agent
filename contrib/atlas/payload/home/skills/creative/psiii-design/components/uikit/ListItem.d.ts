import * as React from "react";

export interface ListItemProps extends React.HTMLAttributes<HTMLDivElement> {
  label?: React.ReactNode;
  iconLeft?: React.ReactNode;
  /** Trailing muted hint text (black-44%). */
  hint?: React.ReactNode;
  /** Arbitrary trailing node (badge, chevron, switcher). */
  trailing?: React.ReactNode;
  selected?: boolean;
  disabled?: boolean;
}

/**
 * ListItem — menu/list row. Hover & selected = black-6% fill.
 *
 * @startingPoint section="UI kit" subtitle="List Item — menu / list row" viewport="320x120"
 */
export function ListItem(props: ListItemProps): JSX.Element;
