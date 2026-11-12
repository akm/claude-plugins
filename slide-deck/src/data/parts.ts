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
 * 部品の関数 (text・box) に渡す文字の一部分の入力 (以下「入力の部分」)。省略した書式は、その文字を渡した部品の関数の書式を使う。
 * 部品の関数に文字列を渡したときは、その文字列を 1 つの入力の部分として扱う。
 *
 * 部品の関数は、入力の部分の配列を、次の規則で段落に分ける。
 * 入力の部分の文字を改行 ("\n") で分けたものを「行」、文字が空の行を「空の行」と呼ぶ。
 * 文字が空の入力の部分 (text が "") は、空の行を 1 つ持つ。行が段落に入ると、行の文字と、その行の入力の部分の書式から、
 * 型 TextRun の値を作る。段落がどの TextRun を持つかは、規則 4 で決める。
 * 1. breakLine が true の入力の部分の後で、段落を区切る。
 * 2. 入力の部分の文字の改行ごとに、段落を区切る。ただし、文字の最後が改行で、その入力の部分の breakLine が true でなければ、
 *    最後の改行の後の空の行は、どの段落にも入れない。次の入力の部分の行は、区切られた新しい段落に入る。
 * 3. bullet が true の入力の部分は、いまの段落に行が 1 つでも入っていれば (空の行を含む)、その入力の部分の前で段落を区切る。
 *    その入力の部分の行が入った段落は、箇条書きの項目になる。
 * 4. 空でない行が 1 つでも入った段落は、空でない行の TextRun だけを持つ。
 *    空の行だけが入った段落は「空行の段落」になり、最初に入った空の行の TextRun を 1 つだけ持つ。
 * 5. 1 か 2 の区切りで作られた最後の段落に、行が 1 つも入っていなければ、その段落を除く。
 * 6. 行が 1 つも入っていない段落 (入力の部分の配列が空のとき) は、部品の関数の書式の、文字が空の TextRun を 1 つ持つ。
 * 空行の段落にも TextRun を持たせるのは、段落の文字の大きさ・太字・色を書き出しの処理に渡すためである。
 * 空行を入れたいときは、前の入力の部分と、文字が空の入力の部分の両方に breakLine を付ける
 * (例: [{ text: "a", breakLine: true }, { text: "", breakLine: true }, { text: "b" }])。
 * この分け方は pptxgenjs の段落の分け方と同じではなく、改行や pptxgenjs のオプション align の扱いで結果が違う入力がある。
 * PowerPoint の書き出しは、この規則で分けた段落をそのまま pptxgenjs に渡し、段落の分け方を pptxgenjs に任せない。
 * はみ出しの見積もりと Google スライドの指示の作成も、同じ段落を使う。
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
 * 関数 box と text の公開する宣言 (オーバーロード) は、この型ではなく文字列と配列の 2 つの形に分けている (理由は関数 box のコメント)。
 * この型を使うのは、2 つの関数の実装のシグネチャと、関数 toParagraphs だけである。
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

/**
 * 関数 bullets のオプション。
 * 指定しなかった書式は、箇条書きを受け取る部品の関数 (box・text) の書式を使う。
 */
export interface BulletsOptions {
  /** 文字の大きさ (ポイント)。デフォルト値は、受け取る部品の関数の文字の大きさ。 */
  fontSize?: number;
  /** 文字の色。デフォルト値は、受け取る部品の関数の文字の色。 */
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
 * 入力の部分の配列を段落に分ける。分け方は、型 RunInput の説明の規則 1〜6 のとおり。
 */
function toParagraphs(t: TextInput, d: RunDefaults): Paragraph[] {
  const inputs: RunInput[] = typeof t === "string" ? [{ text: t }] : t;
  let current: Paragraph = { runs: [], bullet: false };
  const paragraphs: Paragraph[] = [current];
  // fromBreakOnly は、最後の段落が区切りで作られ、まだ行が入っていないか (規則 5 で使う)。
  // 関数 breakParagraph の中でも書き換えるので、変数ではなくオブジェクトのプロパティに持つ
  // (変数にすると、TypeScript の型の検査がクロージャの中の書き換えを考慮せず、常に false と見なす)
  const state = { fromBreakOnly: false };
  const breakParagraph = (): void => {
    current = { runs: [], bullet: false };
    paragraphs.push(current);
    state.fromBreakOnly = true;
  };
  for (const input of inputs) {
    // 規則 3。見出しなど bullet の無い入力の部分の後に、関数 bullets の項目を breakLine なしで続けたときに、
    // 見出しまで箇条書きの段落にしないため (pptxgenjs も、オプション align を指定しなければ、bullet の部分の前で段落を区切る)
    if (input.bullet === true && current.runs.length > 0) breakParagraph();
    const lines = input.text.split("\n");
    lines.forEach((line, i) => {
      // 規則 2
      if (i > 0) breakParagraph();
      // 文字の最後の改行は、breakLine と同じく「この後で段落を区切る」ことだけを表すので、改行の後の空の行は段落に入れない
      // ("a\n" の次の入力の部分が "b" なら、段落は a と b の 2 つで、間に空行の段落を作らない)。
      // ただし入力の部分が breakLine も持つときは、改行と breakLine で 2 回区切るので、間の空行の段落は区切りの後も残る。
      // その段落が入力の部分の書式と bullet を持つように、空の行を入れる
      if (i > 0 && i === lines.length - 1 && line === "" && input.breakLine !== true) return;
      state.fromBreakOnly = false;
      if (input.bullet === true) current.bullet = true;
      const run = {
        text: line,
        fontSize: input.fontSize ?? d.fontSize,
        bold: input.bold ?? d.bold,
        color: input.color ?? d.color,
        link: input.link ?? null,
      };
      if (line === "") {
        // 規則 4。空の行の TextRun は、段落にまだ TextRun が無いときだけ足す (最初の空の行だけを持つため)
        if (current.runs.length === 0) current.runs.push(run);
        return;
      }
      // 規則 4。空でない行の TextRun を足すときは、空の行の TextRun を除く
      current.runs = current.runs.filter((r) => r.text !== "");
      current.runs.push(run);
    });
    // 規則 1
    if (input.breakLine === true) breakParagraph();
  }
  // 規則 5
  if (paragraphs.length > 1 && state.fromBreakOnly) paragraphs.pop();
  // 規則 6
  for (const p of paragraphs) {
    if (p.runs.length === 0) {
      p.runs.push({ text: "", fontSize: d.fontSize, bold: d.bold, color: d.color, link: null });
    }
  }
  return paragraphs;
}

/** 段落に、空でない文字の部分が無いか。 */
function isBlank(p: Paragraph): boolean {
  return p.runs.every((r) => r.text === "");
}

function hasText(paragraphs: Paragraph[]): boolean {
  return paragraphs.some((p) => !isBlank(p));
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
    endArrow: o.noHead !== true,
    startArrow: o.both === true,
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
 * 題名を、スライドの上の決まった位置の文字の箱として足す。位置と書式は、元にした build.js の題名のプレースホルダーと同じ。
 * PowerPoint の書き出しは、この箱の位置と書式で題名のプレースホルダーを作り、そこに題名を入れる。
 * はみ出しの見積もりは、この箱で題名を見積もる。題名は構成案から読むので、資料ごとのスクリプトには渡さない (型 Parts に含めない)。
 * 位置は、スライドの大きさ (型 Deck の説明) を前提にする。
 */
export function title(s: SlideFigure, t: string): void {
  text(s, t, 0.5, 0.58, 9.0, 0.62, {
    fontSize: 24,
    bold: true,
    color: "dk1",
    valign: "middle",
    name: "title",
  });
}

/**
 * 一言 (そのスライドで伝えたいことの 1 文) を、スライドの下の決まった位置の文字の箱として足す。
 * 一言は構成案から読むので、資料ごとのスクリプトには渡さない (型 Parts に含めない)。
 * 位置は、スライドの大きさ (型 Deck の説明) を前提にする。
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

/**
 * 箇条書きの文字を作る。戻り値を関数 text や box に渡す。項目ごとに段落を分ける。
 * 指定しなかった書式は項目に書かず、受け取る部品の関数の書式を使う (型 RunInput の説明のとおり)。
 */
export function bullets(items: string[], o: BulletsOptions = {}): RunInput[] {
  return items.map((t, i) => {
    const item: RunInput = { text: t, bullet: true, breakLine: i < items.length - 1 };
    if (o.fontSize !== undefined) item.fontSize = o.fontSize;
    if (o.color !== undefined) item.color = o.color;
    return item;
  });
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
