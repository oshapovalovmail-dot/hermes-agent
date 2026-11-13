import * as React from "react";

export interface ModalProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Show the dialog + backdrop. Default true. */
  open?: boolean;
  title?: React.ReactNode;
  /** Close handler; also fires on backdrop click and the × button. */
  onClose?: () => void;
  /** Right-aligned footer buttons. Omit for no footer. */
  actions?: React.ReactNode;
  /** Card width in px. Default 528. */
  width?: number;
  /** Hairline dividers under the header and above the footer. Default false. */
  divider?: boolean;
  /** Custom close-button glyph (defaults to an × icon). */
  closeIcon?: React.ReactNode;
}

/**
 * Modal — dialog card (header + body + footer) on a dimmed backdrop.
 *
 * @startingPoint section="UI kit" subtitle="Modal — dialog with header & actions" viewport="640x420"
 */
export function Modal(props: ModalProps): JSX.Element | null;
export namespace Modal {
  function PrimaryAction(props: React.ComponentProps<"button">): JSX.Element;
  function SecondaryAction(props: React.ComponentProps<"button">): JSX.Element;
}
