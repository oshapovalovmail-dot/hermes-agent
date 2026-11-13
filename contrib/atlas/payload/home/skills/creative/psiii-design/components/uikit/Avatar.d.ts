import * as React from "react";

export interface AvatarProps extends React.HTMLAttributes<HTMLSpanElement> {
  src?: string;
  alt?: string;
  /** Fallback initials shown when no src. */
  initials?: React.ReactNode;
  /** Diameter in px: 24 / 32 / 40 / 48. Default 40. */
  size?: 24 | 32 | 40 | 48;
  /** Show a red badge dot at bottom-right. */
  badge?: boolean;
}

/**
 * Avatar — circle, image or initials on graphite, optional badge dot.
 *
 * @startingPoint section="UI kit" subtitle="Avatar — image / initials" viewport="320x100"
 */
export function Avatar(props: AvatarProps): JSX.Element;
