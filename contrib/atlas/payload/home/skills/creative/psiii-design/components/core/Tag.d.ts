import * as React from "react";

export type TagTone = "neutral" | "dark" | "accent" | "outline";

export interface TagProps extends React.HTMLAttributes<HTMLSpanElement> {
  /** "neutral" (black-6% chip) · "dark" (graphite) · "accent" (red) · "outline". */
  tone?: TagTone;
  iconLeft?: React.ReactNode;
  /** Show a removable × (Close Circle Fill). */
  removable?: boolean;
  /** Pinned chip — no remove control even if removable. */
  pinned?: boolean;
  onRemove?: (e: React.MouseEvent) => void;
  /** Override the pill radius (e.g. 0 for a hard-edged label). */
  radius?: number;
}

/**
 * Tag — chip / removable filter. Black-6% pill, YS Text Regular 14/20.
 *
 * @startingPoint section="Core" subtitle="Tag — chip, removable, pinned" viewport="520x120"
 */
export function Tag(props: TagProps): JSX.Element;
