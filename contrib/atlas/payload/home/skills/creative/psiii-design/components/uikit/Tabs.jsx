import React from "react";

/**
 * Tabs — ПСиИИ / Yandex UI-kit segmented control. Track radius 8, black-6% fill,
 * 4px padding; the active tab is a white pill (Small-28), inactive tabs are
 * ghost. Labels YS Text Regular 14/20. Pass items + active id; set iconsOnly to
 * render icon-only tabs. (Правило 75.)
 */
export function Tabs({ items = [], active, onChange, iconsOnly = false, style, ...rest }) {
  return (
    <div
      role="tablist"
      style={{
        display: "inline-flex",
        gap: 0,
        padding: 4,
        height: 36,
        borderRadius: 8,
        background: "var(--control-secondary)",
        boxSizing: "border-box",
        ...style,
      }}
      {...rest}
    >
      {items.map((it) => {
        const id = it.id ?? it.label;
        const isActive = id === active;
        return (
          <button
            key={id}
            role="tab"
            aria-selected={isActive}
            aria-label={iconsOnly && typeof it.label === "string" ? it.label : undefined}
            onClick={(e) => onChange && onChange(id, e)}
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 6,
              flexGrow: 1,
              height: 28,
              padding: iconsOnly ? "0 8px" : "0 16px",
              border: "none",
              borderRadius: 999,
              background: isActive ? "var(--white)" : "transparent",
              color: "var(--gray-900)",
              fontFamily: "var(--font-text)",
              fontWeight: "var(--fw-regular)",
              fontSize: 14,
              lineHeight: "20px",
              cursor: "pointer",
              whiteSpace: "nowrap",
              transition: "background var(--dur-fast) var(--ease-standard)",
            }}
          >
            {it.icon}
            {!iconsOnly && it.label}
          </button>
        );
      })}
    </div>
  );
}
