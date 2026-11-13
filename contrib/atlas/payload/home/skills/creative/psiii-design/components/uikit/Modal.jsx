import React from "react";
import { Button } from "../core/Button.jsx";

/**
 * Modal — ПСиИИ / Yandex UI-kit dialog. White card (width 528, radius 16) with
 * a soft elevation shadow, a 64px header (title YS Text Medium 18/24 + close),
 * a padded body, and an optional footer with right-aligned actions. Renders a
 * dimmed backdrop when `open`. (Правило 75.)
 *
 * Footer convention: provide `actions` as buttons — the primary action is the
 * one dominant button (graphite or accent), the rest secondary (Правило 75).
 */
export function Modal({
  open = true,
  title,
  onClose,
  children,
  actions,
  width = 528,
  divider = false,
  closeIcon,
  style,
  ...rest
}) {
  if (!open) return null;
  return (
    <div
      role="presentation"
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.4)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
        zIndex: 1000,
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
        style={{
          width,
          maxWidth: "100%",
          maxHeight: "100%",
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
          borderRadius: 16,
          background: "var(--white)",
          boxShadow: "0 0 0 1px rgba(0,0,0,0.12), 0 28px 76px rgba(0,0,0,0.3)",
          ...style,
        }}
        {...rest}
      >
        {/* Header */}
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            gap: 12,
            minHeight: 64,
            padding: "16px 12px 12px 28px",
            boxShadow: divider ? "inset 0 -1px 0 rgba(0,0,0,0.09)" : "none",
          }}
        >
          <span style={{
            flex: 1,
            fontFamily: "var(--font-text)",
            fontWeight: "var(--fw-medium)",
            fontSize: 18,
            lineHeight: "24px",
            color: "var(--gray-900)",
          }}>{title}</span>
          {onClose && (
            <button
              type="button"
              aria-label="Закрыть"
              onClick={onClose}
              style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                width: 24,
                height: 24,
                flexShrink: 0,
                border: "none",
                background: "transparent",
                borderRadius: 999,
                cursor: "pointer",
                color: "var(--gray-900)",
              }}
            >
              {closeIcon || (
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                  <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                </svg>
              )}
            </button>
          )}
        </div>

        {/* Body */}
        <div style={{
          flex: 1,
          minHeight: 0,
          overflowY: "auto",
          padding: "4px 28px 20px",
          fontFamily: "var(--font-text)",
          fontWeight: "var(--fw-regular)",
          fontSize: 14,
          lineHeight: "20px",
          color: "var(--gray-900)",
        }}>
          {children}
        </div>

        {/* Footer */}
        {actions && (
          <div style={{
            display: "flex",
            justifyContent: "flex-end",
            gap: 8,
            padding: 28,
            boxShadow: divider ? "inset 0 1px 0 rgba(0,0,0,0.09)" : "none",
          }}>
            {actions}
          </div>
        )}
      </div>
    </div>
  );
}

/** Convenience: a graphite primary action button for Modal footers. */
Modal.PrimaryAction = function PrimaryAction(props) {
  return <Button type="primary" {...props} />;
};
/** Convenience: a secondary action button for Modal footers. */
Modal.SecondaryAction = function SecondaryAction(props) {
  return <Button type="secondary" {...props} />;
};
