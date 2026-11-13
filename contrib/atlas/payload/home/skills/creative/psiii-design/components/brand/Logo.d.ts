import * as React from "react";

export type LogoKind = "mark" | "yandex" | "psiii";
export type LogoTone = "brand" | "dark" | "light";

/**
 * Brand marks for Яндекс · Поисковые сервисы и ИИ.
 */
export interface LogoProps extends Omit<React.SVGProps<SVGSVGElement>, "width" | "height"> {
  /** Which mark to render. Default "yandex". */
  kind?: LogoKind;
  /** "brand" keeps original colors; "dark" = ink; "light" = white. Default "brand". */
  tone?: LogoTone;
  /** Pixel height (width derived from aspect). */
  height?: number;
  /** Pixel width (height derived from aspect). */
  width?: number;
}

/**
 * Brand marks for Яндекс · Поисковые сервисы и ИИ (round «Я» mark, Yandex
 * wordmark, ПСиИИ wordmark), recolorable for dark / light backgrounds.
 *
 * @startingPoint section="Brand" subtitle="Yandex & ПСиИИ logos" viewport="700x200"
 */
export function Logo(props: LogoProps): JSX.Element;
