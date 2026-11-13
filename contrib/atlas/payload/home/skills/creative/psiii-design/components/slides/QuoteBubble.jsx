import React from "react";

/**
 * QuoteBubble — фирменный спич-бабл для цитат и отзывов (Правило 81).
 * Белый бабл (tx2) на светлом фоне (bg2 = #F2F2F2) с фирменным скруглённым
 * хвостиком снизу-слева (точная кривая из эталона цит4.pptx), мягкой тенью на
 * единый силуэт, опциональным круглым аватаром сверху-слева, цитатой в
 * YS Display Cond Heavy (ink, одна фраза — красным) и подписью автор + роль.
 * Цвета берутся из темы и НЕ инвертируются (бабл белый, текст тёмный).
 */
export function QuoteBubble({
  quote,
  author,
  role,
  avatar,
  quoteSize = 80,
  radius = 110,
  tailSize = 168,
  style,
  className,
  ...rest
}) {
  return (
    <div className={className} style={{ position: "relative", ...style }} {...rest}>
      {/* силуэт (бабл + хвостик) — одна общая тень */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          filter: "drop-shadow(0 12px 34px rgba(31,31,32,0.10))",
          pointerEvents: "none",
        }}
      >
        <div style={{ position: "absolute", inset: 0, background: "var(--white)", borderRadius: radius }} />
        <svg
          viewBox="0 0 572438 573276"
          width={tailSize}
          height={tailSize}
          style={{ position: "absolute", left: 54, top: "100%", transform: "translateY(-63%)", display: "block" }}
        >
          <path
            d="M272670 0 L284706 21944 C303486 65883 313870 114192 313870 164901 C313870 342384 186658 490461 17546 524708 L0 526458 L56866 550530 C101266 565177 150080 573276 201322 573276 C406284 573276 572438 443688 572438 283833 C572438 143960 445226 27260 276114 271 Z"
            fill="var(--white)"
          />
        </svg>
      </div>

      {/* контент поверх бабла */}
      <div style={{ position: "relative", padding: "76px 84px" }}>
        {avatar ? (
          <img
            src={avatar}
            alt=""
            style={{
              position: "absolute",
              top: -112,
              left: 60,
              width: 220,
              height: 220,
              borderRadius: "50%",
              objectFit: "cover",
              border: "6px solid #F2F2F2",
            }}
          />
        ) : null}

        <div
          style={{
            fontFamily: "var(--font-display)",
            fontWeight: "var(--fw-heavy)",
            fontSize: quoteSize,
            lineHeight: 0.9,
            letterSpacing: "var(--tracking-display)",
            color: "var(--text-title)",
          }}
        >
          {quote}
        </div>

        {author != null || role != null ? (
          <div style={{ marginTop: 56 }}>
            {author != null ? (
              <div
                style={{
                  fontFamily: "var(--font-text)",
                  fontWeight: "var(--fw-medium)",
                  fontSize: 40,
                  lineHeight: 1.1,
                  color: "var(--text-title)",
                }}
              >
                {author}
              </div>
            ) : null}
            {role != null ? (
              <div
                style={{
                  fontFamily: "var(--font-text)",
                  fontWeight: "var(--fw-regular)",
                  fontSize: 32,
                  lineHeight: 1.1,
                  color: "var(--text-muted)",
                  marginTop: 8,
                }}
              >
                {role}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
