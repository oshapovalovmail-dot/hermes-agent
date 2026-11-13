import * as React from "react";

export interface SlideFooterProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Left label. Default "Яндекс Поисковые сервисы и ИИ". */
  label?: string;
  /** Right text — brandbook year or page number. "" hides it. Default "Брендбук 2026". */
  right?: string | number;
}

/** The standard 15px, 50%-opacity ПСиИИ slide footer line. */
export function SlideFooter(props: SlideFooterProps): JSX.Element;
