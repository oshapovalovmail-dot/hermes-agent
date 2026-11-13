import * as React from "react";

export interface TabItem {
  id?: string;
  label: React.ReactNode;
  icon?: React.ReactNode;
}

export interface TabsProps extends Omit<React.HTMLAttributes<HTMLDivElement>, "onChange"> {
  items: TabItem[];
  /** id (or label) of the active tab. */
  active?: string;
  onChange?: (id: string, e: React.MouseEvent) => void;
  /** Render icon-only tabs (label used as aria-label). */
  iconsOnly?: boolean;
}

/**
 * Tabs — segmented control. Track radius 8 / black-6%; active tab = white pill.
 *
 * @startingPoint section="UI kit" subtitle="Tabs — segmented pill control" viewport="480x80"
 */
export function Tabs(props: TabsProps): JSX.Element;
