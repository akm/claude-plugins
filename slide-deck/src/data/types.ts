// スライドのデータの型。
// 資料ごとのスクリプト deck.ts が部品の関数で作り、PowerPoint の書き出しと Google スライドの指示の作成が読む。
// 2 つの書き出しの処理の両方が扱える要素だけを持つ (計画の KTD1)。
// 位置と大きさはインチ、文字の大きさ・線の幅・内側の余白・段落の後の間隔はポイントで持つ。
// 値はすべて決まった値で持ち、省略やデフォルト値を残さない。書き出しの処理がデフォルト値を知らなくて済むようにするため。

import type { Theme } from "./theme.ts";

/** 図形と文字の色に使う、テーマの色の名前。色の値ではなく、この名前で指定する。 */
export type ThemeColorName =
  | "dk1"
  | "lt1"
  | "dk2"
  | "lt2"
  | "accent1"
  | "accent2"
  | "accent3"
  | "accent4"
  | "accent5"
  | "accent6";

/** 位置と大きさ (インチ)。x と y は左上の角。 */
export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** 塗りつぶし。transparency は透明度 (0〜100。0 が不透明)。 */
export interface Fill {
  color: ThemeColorName;
  transparency: number;
}

/** 図形の枠線。width はポイント。 */
export interface Outline {
  color: ThemeColorName;
  width: number;
  dashed: boolean;
}

/** 文字の一部分と、その書式。link は文字に付けるリンクの URL (無ければ null)。 */
export interface TextRun {
  text: string;
  fontSize: number;
  bold: boolean;
  color: ThemeColorName;
  link: string | null;
}

/** 段落。bullet が true なら箇条書きの項目にする。 */
export interface Paragraph {
  runs: TextRun[];
  bullet: boolean;
}

/** 内側の余白 (ポイント)。 */
export interface Margin {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

/** 図形や文字の箱の中の文字。paraSpaceAfter は段落の後の間隔 (ポイント。0 なら間隔を空けない)。 */
export interface TextBody {
  paragraphs: Paragraph[];
  align: "left" | "center" | "right";
  valign: "top" | "middle" | "bottom";
  margin: Margin;
  paraSpaceAfter: number;
}

/**
 * 図形の形。名前は PowerPoint のファイルの形式 (Office Open XML) の形の名前に合わせた。
 * roundRect は角の丸い四角、rect は四角、ellipse は円、can は円柱、chevron は山形、homePlate は五角形の矢印。
 */
export type ShapeKind = "roundRect" | "rect" | "ellipse" | "can" | "chevron" | "homePlate";

/** 形と、形ごとの値。角の丸い四角だけが角の半径 (インチ) を持つ。 */
export type ShapeGeometry =
  | { shape: "roundRect"; radius: number }
  | { shape: Exclude<ShapeKind, "roundRect"> };

/** 図形。中に文字を持てる (文字が無ければ text は null)。枠線が無ければ outline は null。 */
export type ShapeElement = Rect &
  ShapeGeometry & {
    kind: "shape";
    fill: Fill;
    outline: Outline | null;
    text: TextBody | null;
    name: string | null;
  };

/** 塗りつぶしと枠線の無い、文字の箱。 */
export type TextBoxElement = Rect & {
  kind: "textBox";
  text: TextBody;
  name: string | null;
};

/**
 * 線。位置と大きさは、始点と終点を囲む四角で持つ。
 * 始点が終点より右なら flipH、下なら flipV を true にして、向きを表す。
 * headEnd は終点に、headStart は始点に、矢じりを付けるか。width はポイント。
 */
export type LineElement = Rect & {
  kind: "line";
  flipH: boolean;
  flipV: boolean;
  color: ThemeColorName;
  width: number;
  dashed: boolean;
  headEnd: boolean;
  headStart: boolean;
};

/** スライドの要素。 */
export type SlideElement = ShapeElement | TextBoxElement | LineElement;

/**
 * 1 つのキーの図。資料ごとのスクリプトが、部品の関数で要素を足して作る。
 * elements の順序は足した順序で、後の要素ほど前面に重なる。
 */
export interface SlideFigure {
  readonly key: string;
  readonly elements: SlideElement[];
}

/**
 * 1 枚のスライドのデータ。題名・一言・発表者ノート (notes) は構成案から、図 (elements) は資料ごとのスクリプトから取る (計画の R8)。
 */
export interface Slide {
  key: string;
  title: string;
  takeaway: string;
  notes: string;
  elements: SlideElement[];
}

/** 1 つの資料のデータ。2 つの書き出しの処理は、これだけを読む。slides の順序は構成案のスライドの順序。 */
export interface Deck {
  theme: Theme;
  slides: Slide[];
}
