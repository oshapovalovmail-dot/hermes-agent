import * as React from "react";

export interface ContextMenuProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Card width in px. Default 268. */
  width?: number;
}

/**
 * ContextMenu — floating white menu surface for ListItem rows.
 *
 * @startingPoint section="UI kit" subtitle="Context Menu — floating surface" viewport="360x260"
 */
export function ContextMenu(props: ContextMenuProps): JSX.Element;
