// スライドのデータから、pptxgenjs で PowerPoint のファイルを書く (計画の R8・R11・U5)。
// pptxgenjs は、キャッシュの node_modules を起点にした createRequire で読み込む (計画の KTD8)。
// テーマの色は pptxgenjs では書けないので、書いた後に pptx のスキルの scripts/apply_theme.js で書き込む (ファイル src/pptx/build.ts)。

import { createRequire } from "node:module";
import { join } from "node:path";
import type PptxGenJS from "pptxgenjs";
import { title as titleBox, takeaway as takeawayBox, slide as emptyFigure } from "../data/parts.ts";
import type { SchemeColorName, Theme } from "../data/theme.ts";
import { schemeColorValues } from "../data/theme.ts";
import {
  type Deck,
  type LineElement,
  type Margin,
  type Paragraph,
  type ShapeElement,
  SLIDE_SIZE,
  type Slide,
  type SlideFigure,
  type TextBody,
  type TextBoxElement,
  type ThemeColorName,
} from "../data/types.ts";

/** pptxgenjs のクラス */
export type PptxGenConstructor = typeof PptxGenJS;

type Presentation = PptxGenJS;
type PptxSlide = PptxGenJS.Slide;

/** キャッシュの node_modules から pptxgenjs を読み込む */
export function loadPptxGen(nodeModulesDir: string): PptxGenConstructor {
  // createRequire の起点は、そのディレクトリの中のファイルのパスで渡す (ファイルは無くてよい)
  const require = createRequire(join(nodeModulesDir, "slide-deck-pptx.cjs"));
  const loaded: unknown = require("pptxgenjs");
  if (typeof loaded !== "function") {
    throw new Error(`${nodeModulesDir} の pptxgenjs が、クラスを書き出していない`);
  }
  // pptxgenjs の CommonJS の入口は、クラス PptxGenJS そのものを書き出す
  return loaded as PptxGenConstructor;
}

/** 題名のプレースホルダーを持つレイアウトの名前 */
export const CONTENT_LAYOUT = "SLIDE_DECK_CONTENT";

// スライドの大きさのレイアウトの名前。大きさは SLIDE_SIZE から決める
const SLIDE_LAYOUT = "SLIDE_DECK_16x9";

// 箇条書きの字下げ (ポイント)。Google スライドの字下げ (計画の KTD14) と、はみ出しの見積もり (計画の KTD6) と同じ値
const BULLET_INDENT_PT = 16;

/**
 * テーマの色の名前を、pptxgenjs の色の名前にする。
 * pptxgenjs は、tx1・tx2・bg1・bg2・accent1〜6 だけをテーマの色 (a:schemeClr) として書き、ほかの文字列は RGB の値として書く。
 * PowerPoint のファイルのマスターは tx1 を dk1 に、bg1 を lt1 に対応させる (要素 p:clrMap) ので、同じ色になる
 */
export function schemeColor(name: ThemeColorName): string {
  switch (name) {
    case "dk1":
      return "tx1";
    case "lt1":
      return "bg1";
    case "dk2":
      return "tx2";
    case "lt2":
      return "bg2";
    default:
      return name;
  }
}

/** 内側の余白を、pptxgenjs のオプション margin の順序 [左, 右, 下, 上] (ポイント) にする */
function toPptxMargin(m: Margin): [number, number, number, number] {
  return [m.left, m.right, m.bottom, m.top];
}

/**
 * 段落を、pptxgenjs の文字の部分の配列にする。段落の分け方は部品の関数が決めたものをそのまま使い、pptxgenjs に任せない
 * (型 RunInput の説明)。各段落の最後の部分に breakLine を付け、最後の段落だけは付けない。
 * 部品の関数は横の揃え方を必ず決めるので、pptxgenjs は breakLine でだけ段落を区切る
 */
export function toTextProps(paragraphs: readonly Paragraph[]): PptxGenJS.TextProps[] {
  const props: PptxGenJS.TextProps[] = [];
  paragraphs.forEach((p, pi) => {
    p.runs.forEach((r, ri) => {
      const options: PptxGenJS.TextPropsOptions = {
        fontSize: r.fontSize,
        bold: r.bold,
        color: schemeColor(r.color),
        bullet: p.bullet ? { indent: BULLET_INDENT_PT } : false,
        breakLine: ri === p.runs.length - 1 && pi < paragraphs.length - 1,
      };
      if (r.link !== null) options.hyperlink = { url: r.link };
      props.push({ text: r.text, options });
    });
  });
  return props;
}

/** 文字の箱の書式 (段落の分け方以外) を、pptxgenjs のオプションにする */
function textBodyOptions(body: TextBody): PptxGenJS.TextPropsOptions {
  return {
    align: body.align,
    valign: body.valign,
    margin: toPptxMargin(body.margin),
    paraSpaceAfter: body.paraSpaceAfter,
  };
}

function lineOptions(color: ThemeColorName, width: number, dashed: boolean): PptxGenJS.ShapeLineProps {
  return { color: schemeColor(color), width, dashType: dashed ? "dash" : "solid" };
}

function addShape(pres: Presentation, s: PptxSlide, e: ShapeElement): void {
  const options: PptxGenJS.TextPropsOptions = {
    shape: pres.ShapeType[e.shape],
    x: e.x,
    y: e.y,
    w: e.w,
    h: e.h,
    fill: { color: schemeColor(e.fill.color), transparency: e.fill.transparency },
  };
  if (e.shape === "roundRect") options.rectRadius = e.radius;
  if (e.outline !== null) options.line = lineOptions(e.outline.color, e.outline.width, e.outline.dashed);
  if (e.name !== null) options.objectName = e.name;
  if (e.text === null) {
    s.addShape(pres.ShapeType[e.shape], options);
    return;
  }
  s.addText(toTextProps(e.text.paragraphs), { ...options, ...textBodyOptions(e.text) });
}

function addTextBox(s: PptxSlide, e: TextBoxElement): void {
  const options: PptxGenJS.TextPropsOptions = {
    x: e.x,
    y: e.y,
    w: e.w,
    h: e.h,
    isTextBox: true,
    ...textBodyOptions(e.text),
  };
  if (e.name !== null) options.objectName = e.name;
  s.addText(toTextProps(e.text.paragraphs), options);
}

function addLine(pres: Presentation, s: PptxSlide, e: LineElement): void {
  // 矢じりは、始点 (beginArrowType) と終点 (endArrowType) に付ける。
  // 型 LineElement の endArrow は終点、startArrow は始点の矢じり (型の説明)
  const line: PptxGenJS.ShapeLineProps = lineOptions(e.color, e.width, e.dashed);
  if (e.endArrow) line.endArrowType = "triangle";
  if (e.startArrow) line.beginArrowType = "triangle";
  s.addShape(pres.ShapeType.line, { x: e.x, y: e.y, w: e.w, h: e.h, flipH: e.flipH, flipV: e.flipV, line });
}

/** 部品の関数 title か takeaway が作る文字の箱を取り出す */
function fixedBox(add: (s: SlideFigure, t: string) => void, key: string, t: string): TextBoxElement {
  const fig = emptyFigure(key);
  add(fig, t);
  const [box] = fig.elements;
  if (box?.kind !== "textBox") throw new Error(`題名か一言の部品の関数が、文字の箱を作らなかった (キー ${key})`);
  return box;
}

/**
 * 題名のプレースホルダーを持つレイアウトを作る。位置と書式は、部品の関数 title が作る箱と同じにする
 * (計画の KTD1。はみ出しの見積もりと Google スライドの指示の作成も、同じ箱を使う)
 */
function defineContentLayout(pres: Presentation): void {
  const box = fixedBox(titleBox, "layout", "");
  const [run] = box.text.paragraphs[0]?.runs ?? [];
  if (run === undefined) throw new Error("題名の部品の関数が、文字の部分を作らなかった");
  pres.defineSlideMaster({
    title: CONTENT_LAYOUT,
    // 背景をテーマの lt1 (背景の色) で塗る。背景を書かないと、PowerPoint のファイルを表示するソフトによって背景の色が違う
    // (macOS の Quick Look では灰色になった)
    background: { color: schemeColor("lt1") },
    objects: [
      {
        placeholder: {
          options: {
            name: "title",
            type: "title",
            x: box.x,
            y: box.y,
            w: box.w,
            h: box.h,
            fontSize: run.fontSize,
            bold: run.bold,
            color: schemeColor(run.color),
            align: box.text.align,
            valign: box.text.valign,
            margin: toPptxMargin(box.text.margin),
          },
          text: "",
        },
      },
    ],
  });
}

function addSlide(pres: Presentation, slide: Slide): void {
  const s = pres.addSlide({ masterName: CONTENT_LAYOUT });
  const title = fixedBox(titleBox, slide.key, slide.title);
  s.addText(toTextProps(title.text.paragraphs), { placeholder: "title" });
  for (const e of slide.elements) {
    switch (e.kind) {
      case "shape":
        addShape(pres, s, e);
        break;
      case "textBox":
        addTextBox(s, e);
        break;
      case "line":
        addLine(pres, s, e);
        break;
    }
  }
  addTextBox(s, fixedBox(takeawayBox, slide.key, slide.takeaway));
  if (slide.notes !== "") s.addNotes(slide.notes);
}

/**
 * スライドのデータから PowerPoint のファイルを作り、内容を返す。
 * スライドの大きさは SLIDE_SIZE。テーマのフォントは書くが、テーマの色は書かない (pptxgenjs が書けないため。テーマの色は、ファイル src/pptx/build.ts が pptx のスキルで書き込む)
 */
export async function renderPptx(deck: Deck, PptxGen: PptxGenConstructor): Promise<Buffer> {
  const pres = new PptxGen();
  pres.defineLayout({ name: SLIDE_LAYOUT, width: SLIDE_SIZE.w, height: SLIDE_SIZE.h });
  pres.layout = SLIDE_LAYOUT;
  pres.title = deck.title;
  pres.theme = { headFontFace: deck.theme.fonts.heading, bodyFontFace: deck.theme.fonts.body };
  defineContentLayout(pres);
  for (const slide of deck.slides) addSlide(pres, slide);
  const out = await pres.write({ outputType: "nodebuffer" });
  if (!Buffer.isBuffer(out)) throw new Error("pptxgenjs が、ファイルの内容を Buffer で返さなかった");
  return out;
}

/** pptx のスキルの scripts/apply_theme.js に渡すテーマ。名前と、テーマの 12 色 (16 進数 6 桁) */
export interface ApplyThemeInput {
  name: string;
  headFontFace: string;
  bodyFontFace: string;
  colors: Record<SchemeColorName, string>;
}

/** テーマを、pptx のスキルの scripts/apply_theme.js に渡す形にする */
export function applyThemeInput(theme: Theme): ApplyThemeInput {
  return {
    name: theme.name,
    headFontFace: theme.fonts.heading,
    bodyFontFace: theme.fonts.body,
    colors: schemeColorValues(theme),
  };
}
