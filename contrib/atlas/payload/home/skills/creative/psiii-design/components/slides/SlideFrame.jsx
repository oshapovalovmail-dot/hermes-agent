import React from "react";

/**
 * SlideFrame — the fixed 1920×1080 ПСиИИ slide canvas. Renders at native slide
 * pixels; let a deck stage or a card viewport scale it to fit. Provides the
 * background, the always-on column grid (optional), and the 40px content inset.
 *
 *  bg: "white" (default) · "ink" (#1F1F20) · "maroon" (#330001) · "accent" (red)
 */
export function SlideFrame({
  bg = "white",
  grid = false,
  inset = true,
  children,
  style,
  className,
  ...rest
}) {
  const backgrounds = {
    white: { background: "var(--surface-page)", color: "var(--text-primary)" },
    ink: { background: "var(--gray-900)", color: "var(--white)" },
    maroon: { background: "var(--maroon)", color: "var(--white)" },
    accent: { background: "var(--accent)", color: "var(--white)" },
  };
  const b = backgrounds[bg] || backgrounds.white;

  return (
    <div
      className={className}
      style={{
        position: "relative",
        width: 1920,
        height: 1080,
        overflow: "hidden",
        fontFamily: "var(--font-text)",
        ...b,
        ...style,
      }}
      {...rest}
    >
      {grid ? <GridOverlay light={bg !== "white"} /> : null}
      {inset ? (
        <div style={{ position: "absolute", inset: 0, padding: "var(--content-top) var(--margin-x) 80px" }}>
          {children}
        </div>
      ) : (
        children
      )}
    </div>
  );
}

function GridOverlay({ light }) {
  const cols = 12;
  const line = light ? "rgba(255,255,255,0.18)" : "var(--grid)";
  return (
    <div aria-hidden="true" style={{ position: "absolute", inset: 0, pointerEvents: "none" }}>
      {/* outer safe-area box */}
      <div style={{ position: "absolute", inset: 20, boxShadow: `inset 0 0 0 1px ${line}`, opacity: 0.6 }} />
      {/* column guides inside the 40px content margin */}
      <div style={{ position: "absolute", left: 40, right: 40, top: 0, bottom: 0, display: "grid", gridTemplateColumns: `repeat(${cols}, 1fr)`, columnGap: 20 }}>
        {Array.from({ length: cols }).map((_, i) => (
          <div key={i} style={{ boxShadow: `inset 1px 0 0 ${line}, inset -1px 0 0 ${line}`, opacity: 0.35 }} />
        ))}
      </div>
      {/* horizontal thirds */}
      {[360, 720].map((y) => (
        <div key={y} style={{ position: "absolute", left: 0, right: 0, top: y, height: 1, background: line, opacity: 0.35 }} />
      ))}
    </div>
  );
}
