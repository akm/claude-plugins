// 部品の関数。資料ごとのスクリプト deck.ts が、キーごとの図 (SlideFigure) に要素を足すのに使う。
// 引数とデフォルト値は、元にした資料のスクリプト build.js の関数 box・text・arrow・badge・takeaway・card・bullets から引き継いだ。
// 元の関数は pptxgenjs のスライドに直接描いていたが、ここではスライドのデータの要素を図に足す (計画の KTD1)。
// 元のテーマの色の定数は、テーマの色の名前に置き換えた (TEXT は dk1、MUTED は dk2、WHITE は lt1、PANEL は lt2、NEW は accent1)。

import type {
  Margin,
  Paragraph,
  ShapeElement,
  ShapeKind,
  SlideFigure,
  TextBody,
  TextBoxElement,
  ThemeColorName,
} from "./types.ts";

/**
 * 文字の一部分の入力。省略した書式は、その文字を渡した部品の関数の書式を使う。
 * breakLine が true なら、この部分の後で段落を分ける。bullet が true なら、この部分を含む段落を箇条書きの項目にする。
 * 文字の中の改行 ("\n") でも、段落を分ける。
 */
export interface RunInput {
  text: string;
  fontSize?: number;
  bold?: boolean;
  color?: ThemeColorName;
  link?: string;
  bullet?: boolean;
  breakLine?: boolean;
}

/**
 * 部品の関数の中で扱う文字。1 つの文字列か、書式の違う部分の配列。
 * 関数 box と text は、この型の引数を受け取らず、文字列と配列のオーバーロードに分けている (関数 box のコメントを参照)。
 */
type TextInput = string | RunInput[];

/** 内側の余白の入力 (ポイント)。1 つの数なら上下左右に同じ値を使い、配列なら [上, 右, 下, 左] の順。 */
export type MarginInput = number | [number, number, number, number];

/** 関数 box のオプション。 */
export interface BoxOptions {
  /** 形。デフォルト値は roundRect (角の丸い四角)。 */
  shape?: ShapeKind;
  /** 塗りつぶしの色。デフォルト値は lt1。 */
  fill?: ThemeColorName;
  /** 塗りつぶしの透明度 (0〜100)。デフォルト値は 0。 */
  tr?: number;
  /** 文字の色。デフォルト値は dk1。 */
  color?: ThemeColorName;
  /** 文字の大きさ (ポイント)。デフォルト値は 14。 */
  fontSize?: number;
  /** 太字にするか。デフォルト値は false。 */
  bold?: boolean;
  /** 横の揃え方。デフォルト値は center。 */
  align?: TextBody["align"];
  /** 縦の揃え方。デフォルト値は middle。 */
  valign?: TextBody["valign"];
  /** 内側の余白 (ポイント)。デフォルト値は 6。 */
  margin?: MarginInput;
  /** 角の丸い四角の角の半径 (インチ)。デフォルト値は 0.08。ほかの形では使わない。 */
  radius?: number;
  /** 枠線の色。指定しなければ枠線を描かない。 */
  line?: ThemeColorName;
  /** 枠線の幅 (ポイント)。デフォルト値は 1。 */
  lineW?: number;
  /** 枠線を破線にするか。デフォルト値は false。 */
  dash?: boolean;
  /** 要素の名前。 */
  name?: string;
}

/** 関数 text のオプション。 */
export interface TextOptions {
  /** 文字の大きさ (ポイント)。デフォルト値は 14。 */
  fontSize?: number;
  /** 文字の色。デフォルト値は dk1。 */
  color?: ThemeColorName;
  /** 太字にするか。デフォルト値は false。 */
  bold?: boolean;
  /** 横の揃え方。デフォルト値は left。 */
  align?: TextBody["align"];
  /** 縦の揃え方。デフォルト値は top。 */
  valign?: TextBody["valign"];
  /** 内側の余白 (ポイント)。デフォルト値は 0。 */
  margin?: MarginInput;
  /** 要素の名前。 */
  name?: string;
  /** 段落の後の間隔 (ポイント)。デフォルト値は 0 (間隔を空けない)。 */
  psa?: number;
}

/** 関数 arrow のオプション。 */
export interface ArrowOptions {
  /** 線の色。デフォルト値は dk2。 */
  color?: ThemeColorName;
  /** 線の幅 (ポイント)。デフォルト値は 1.5。 */
  width?: number;
  /** 破線にするか。デフォルト値は false。 */
  dash?: boolean;
  /** 終点の矢じりを付けないか。デフォルト値は false (終点に矢じりを付ける)。 */
  noHead?: boolean;
  /** 始点にも矢じりを付けるか。デフォルト値は false。 */
  both?: boolean;
}

/** 関数 badge のオプション。 */
export interface BadgeOptions {
  /** 円の色。デフォルト値は accent1。 */
  fill?: ThemeColorName;
  /** 番号の文字の大きさ (ポイント)。デフォルト値は 12。 */
  fontSize?: number;
}

/** 関数 card のオプション。 */
export interface CardOptions {
  /** 塗りつぶしの色。デフォルト値は lt2。 */
  fill?: ThemeColorName;
  /** 塗りつぶしの透明度 (0〜100)。デフォルト値は 0。 */
  tr?: number;
  /** 要素の名前。 */
  name?: string;
}

/** 関数 bullets のオプション。 */
export interface BulletsOptions {
  /** 文字の大きさ (ポイント)。デフォルト値は 14。 */
  fontSize?: number;
  /** 文字の色。デフォルト値は dk1。 */
  color?: ThemeColorName;
}

/** 文字の書式のうち、部品の関数が決めるもの。文字の一部分の入力で省略した書式に使う。 */
interface RunDefaults {
  fontSize: number;
  bold: boolean;
  color: ThemeColorName;
}

function toMargin(m: MarginInput): Margin {
  if (typeof m === "number") return { top: m, right: m, bottom: m, left: m };
  const [top, right, bottom, left] = m;
  return { top, right, bottom, left };
}

/**
 * 文字の入力を段落に分ける。
 * 部分の breakLine と文字の中の改行で段落を分け、部分の bullet はその部分を含む段落に付ける。
 * 最後の段落が空なら (最後の部分の breakLine や、末尾の改行で作られたもの) 除く。
 */
function toParagraphs(t: TextInput, d: RunDefaults): Paragraph[] {
  const inputs: RunInput[] = typeof t === "string" ? [{ text: t }] : t;
  let current: Paragraph = { runs: [], bullet: false };
  const paragraphs: Paragraph[] = [current];
  const breakParagraph = (): void => {
    current = { runs: [], bullet: false };
    paragraphs.push(current);
  };
  for (const input of inputs) {
    const lines = input.text.split("\n");
    lines.forEach((line, i) => {
      if (i > 0) breakParagraph();
      if (input.bullet === true) current.bullet = true;
      if (line === "") return;
      current.runs.push({
        text: line,
        fontSize: input.fontSize ?? d.fontSize,
        bold: input.bold ?? d.bold,
        color: input.color ?? d.color,
        link: input.link ?? null,
      });
    });
    if (input.breakLine === true) breakParagraph();
  }
  const last = paragraphs[paragraphs.length - 1];
  if (paragraphs.length > 1 && last !== undefined && last.runs.length === 0) paragraphs.pop();
  return paragraphs;
}

function hasText(paragraphs: Paragraph[]): boolean {
  return paragraphs.some((p) => p.runs.length > 0);
}

/** 資料ごとのスクリプトが、キーごとの空の図を作る。部品の関数は、この図に要素を足す。 */
export function slide(key: string): SlideFigure {
  return { key, elements: [] };
}

/**
 * 文字の入った箱を足す。形のデフォルト値は角の丸い四角。
 * 文字が空 ("" か空の配列) なら、文字を持たない図形になる (塗りつぶしだけの四角などに使う)。
 */
export function box(
  s: SlideFigure,
  x: number,
  y: number,
  w: number,
  h: number,
  t: string,
  o?: BoxOptions,
): void;
// 文字列と配列を 1 つの引数の型 (string | RunInput[]) にまとめると、配列に書いた bold や link を、
// 規則 no-deprecated が String.prototype の非推奨のメソッドとして誤って指摘する。
// 資料ごとのスクリプトも同じ規則で検査するので、オーバーロードに分けたまま、規則 unified-signatures の指摘の対象から除く
export function box(
  s: SlideFigure,
  x: number,
  y: number,
  w: number,
  h: number,
  // eslint-disable-next-line @typescript-eslint/unified-signatures
  t: RunInput[],
  o?: BoxOptions,
): void;
export function box(
  s: SlideFigure,
  x: number,
  y: number,
  w: number,
  h: number,
  t: TextInput,
  o: BoxOptions = {},
): void {
  const paragraphs = toParagraphs(t, {
    fontSize: o.fontSize ?? 14,
    bold: o.bold ?? false,
    color: o.color ?? "dk1",
  });
  const text: TextBody | null = hasText(paragraphs)
    ? {
        paragraphs,
        align: o.align ?? "center",
        valign: o.valign ?? "middle",
        margin: toMargin(o.margin ?? 6),
        paraSpaceAfter: 0,
      }
    : null;
  const shape = o.shape ?? "roundRect";
  const common = {
    kind: "shape" as const,
    x,
    y,
    w,
    h,
    fill: { color: o.fill ?? "lt1", transparency: o.tr ?? 0 },
    outline:
      o.line === undefined ? null : { color: o.line, width: o.lineW ?? 1, dashed: o.dash ?? false },
    text,
    name: o.name ?? null,
  };
  const element: ShapeElement =
    shape === "roundRect" ? { ...common, shape, radius: o.radius ?? 0.08 } : { ...common, shape };
  s.elements.push(element);
}

/** 塗りつぶしと枠線の無い、文字の箱を足す。 */
export function text(
  s: SlideFigure,
  t: string,
  x: number,
  y: number,
  w: number,
  h: number,
  o?: TextOptions,
): void;
// オーバーロードに分ける理由は、関数 box と同じ
export function text(
  s: SlideFigure,
  // eslint-disable-next-line @typescript-eslint/unified-signatures
  t: RunInput[],
  x: number,
  y: number,
  w: number,
  h: number,
  o?: TextOptions,
): void;
export function text(
  s: SlideFigure,
  t: TextInput,
  x: number,
  y: number,
  w: number,
  h: number,
  o: TextOptions = {},
): void {
  const element: TextBoxElement = {
    kind: "textBox",
    x,
    y,
    w,
    h,
    text: {
      paragraphs: toParagraphs(t, {
        fontSize: o.fontSize ?? 14,
        bold: o.bold ?? false,
        color: o.color ?? "dk1",
      }),
      align: o.align ?? "left",
      valign: o.valign ?? "top",
      margin: toMargin(o.margin ?? 0),
      paraSpaceAfter: o.psa ?? 0,
    },
    name: o.name ?? null,
  };
  s.elements.push(element);
}

/**
 * 始点 (x1, y1) から終点 (x2, y2) への矢印を足す。
 * 線の位置と大きさは 2 点を囲む四角で持ち、終点が始点より左なら左右を、上なら上下を反転するフラグを立てる。
 */
export function arrow(
  s: SlideFigure,
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  o: ArrowOptions = {},
): void {
  s.elements.push({
    kind: "line",
    x: Math.min(x1, x2),
    y: Math.min(y1, y2),
    w: Math.abs(x2 - x1),
    h: Math.abs(y2 - y1),
    flipH: x2 < x1,
    flipV: y2 < y1,
    color: o.color ?? "dk2",
    width: o.width ?? 1.5,
    dashed: o.dash ?? false,
    headEnd: o.noHead !== true,
    headStart: o.both === true,
  });
}

/** 番号の入った円を足す。(x, y) は円を囲む四角の左上の角、d は直径 (インチ)。 */
export function badge(
  s: SlideFigure,
  n: number | string,
  x: number,
  y: number,
  d: number,
  o: BadgeOptions = {},
): void {
  s.elements.push({
    kind: "shape",
    shape: "ellipse",
    x,
    y,
    w: d,
    h: d,
    fill: { color: o.fill ?? "accent1", transparency: 0 },
    outline: null,
    text: {
      paragraphs: toParagraphs(String(n), {
        fontSize: o.fontSize ?? 12,
        bold: true,
        color: "lt1",
      }),
      align: "center",
      valign: "middle",
      margin: toMargin(0),
      paraSpaceAfter: 0,
    },
    name: null,
  });
}

/**
 * 一言 (そのスライドで伝えたいことの 1 文) を、スライドの下の決まった位置の文字の箱として足す。
 * 一言は構成案から読むので、資料ごとのスクリプトには渡さない (型 Parts に含めない)。
 */
export function takeaway(s: SlideFigure, t: string): void {
  text(s, t, 0.5, 4.78, 8.5, 0.42, {
    fontSize: 14,
    bold: true,
    color: "dk1",
    valign: "middle",
    name: "takeaway",
  });
}

/** 図の部分をまとめる背景のカード (文字の無い、角の丸い四角) を足す。 */
export function card(
  s: SlideFigure,
  x: number,
  y: number,
  w: number,
  h: number,
  o: CardOptions = {},
): void {
  s.elements.push({
    kind: "shape",
    shape: "roundRect",
    radius: 0.1,
    x,
    y,
    w,
    h,
    fill: { color: o.fill ?? "lt2", transparency: o.tr ?? 0 },
    outline: null,
    text: null,
    name: o.name ?? null,
  });
}

/** 箇条書きの文字を作る。戻り値を関数 text や box に渡す。項目ごとに段落を分ける。 */
export function bullets(items: string[], o: BulletsOptions = {}): RunInput[] {
  return items.map((t, i) => ({
    text: t,
    bullet: true,
    breakLine: i < items.length - 1,
    fontSize: o.fontSize ?? 14,
    color: o.color ?? "dk1",
  }));
}

/** 資料ごとのスクリプトに渡す、部品の関数の集まり (計画の KTD2)。 */
export interface Parts {
  slide: typeof slide;
  box: typeof box;
  text: typeof text;
  arrow: typeof arrow;
  badge: typeof badge;
  card: typeof card;
  bullets: typeof bullets;
}

/** 資料ごとのスクリプトに渡す、部品の関数の集まりの値。 */
export const parts: Parts = { slide, box, text, arrow, badge, card, bullets };
