import * as React from "react";

/**
 * Фирменный спич-бабл для цитат и отзывов (Правило 81): белый бабл на светлом
 * фоне с скруглённым хвостиком снизу-слева, мягкой тенью, опциональным круглым
 * аватаром, крупной цитатой (YS Display Cond Heavy) и подписью.
 */
export interface QuoteBubbleProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Текст цитаты. Одну ключевую фразу заверни в <span style={{color:'var(--accent)'}}> — исключение Правила 80. */
  quote: React.ReactNode;
  /** Имя автора (YS Text Medium, ink). */
  author?: React.ReactNode;
  /** Должность / компания под именем (серым). */
  role?: React.ReactNode;
  /** URL фото автора — круглый аватар сверху-слева. Без него круг не рисуется. */
  avatar?: string;
  /** Кегль цитаты в px. Default 80 (≈84 по Правилу 81). */
  quoteSize?: number;
  /** Радиус скругления бабла в px. Default 110. */
  radius?: number;
  /** Размер хвостика в px. Default 200. */
  tailSize?: number;
}

/**
 * Фирменный спич-бабл для цитат и отзывов (Правило 81).
 *
 * @startingPoint section="Slides" subtitle="QuoteBubble — цитата/отзыв в фирменном спич-бабле" viewport="800x440"
 */
export function QuoteBubble(props: QuoteBubbleProps): JSX.Element;
