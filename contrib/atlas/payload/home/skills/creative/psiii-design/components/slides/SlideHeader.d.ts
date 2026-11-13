import * as React from "react";

export interface SlideHeaderProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Left-hand label (section / business-group name). Default "Поисковые сервисы и ИИ". */
  left?: string;
  /** Show the small dark Yandex corner mark on the right. Default true. */
  mark?: boolean;
}

/** The top safe-area bar of a content slide: left label + dark Yandex corner mark. */
export function SlideHeader(props: SlideHeaderProps): JSX.Element;
