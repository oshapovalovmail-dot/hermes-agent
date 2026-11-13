import React from "react";

/**
 * Badge — a tiny status/count indicator. Either a bare dot or a small
 * number/short label. For longer labels use Tag instead.
 */
export function Badge({ children, tone = "accent", dot = false, style, className, ...rest }) {
  const tones = {
    accent: { background: "var(--accent)", color: "var(--white)" },
    dark: { background: "var(--gray-900)", color: "var(--white)" },
    neutral: { background: "var(--gray-200)", color: "var(--gray-900)" },
  };
  const t = tones[tone] || tones.accent;
  if (dot) {
    return (
      <span
        className={className}
        style={{ display: "inline-block", width: 10, height: 10, borderRadius: "var(--radius-full)", background: t.background, ...style }}
        {...rest}
      />
    );
  }
  return (
    <span
      className={className}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        minWidth: 22,
        height: 22,
        padding: "0 7px",
        borderRadius: "var(--radius-full)",
        fontFamily: "var(--font-text)",
        fontWeight: "var(--fw-bold)",
        fontSize: 13,
        lineHeight: 1,
        ...t,
        ...style,
      }}
      {...rest}
    >
      {children}
    </span>
  );
}
