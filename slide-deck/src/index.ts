// 資料ごとのスクリプト deck.ts が、名前 slide-deck で import type する型 (計画の KTD2)。
// deck.ts はプラグインのモジュールを実行時に import しないので、ここからは型だけを書き出す。

import type { Parts } from "./data/parts.ts";
import type { SlideFigure } from "./data/types.ts";
import type { Theme } from "./data/theme.ts";

export type {
  ArrowOptions,
  BadgeOptions,
  BoxOptions,
  BulletsOptions,
  CardOptions,
  MarginInput,
  Parts,
  RunInput,
  TextOptions,
} from "./data/parts.ts";
export type { AccentColor, SchemeColorName, Theme } from "./data/theme.ts";
export type {
  Deck,
  Fill,
  LineElement,
  Margin,
  Outline,
  Paragraph,
  Rect,
  ShapeElement,
  ShapeGeometry,
  ShapeKind,
  Slide,
  SlideElement,
  SlideFigure,
  TextBody,
  TextBoxElement,
  TextRun,
  ThemeColorName,
} from "./data/types.ts";

/** 資料ごとのスクリプトの関数が返す値。資料のテーマと、キーごとの図。 */
export interface DeckScriptResult {
  theme: Theme;
  slides: SlideFigure[];
}

/**
 * 資料ごとのスクリプトが default export する関数の型。
 * 部品の関数の集まりを引数で受け取り、テーマとキーごとの図を返す。
 */
export type DeckScript = (p: Parts) => DeckScriptResult;
