// はみ出しの見積もり。スライドのデータから、文字が箱からはみ出しそうな箇所を一覧にする (計画の R13・KTD6)。
// 式は、元にしたツール fitcheck.py のもの。全角の文字を 1、半角の文字を 0.58、半角の空白を 0.3 文字分の幅とし、
// 行の高さを文字の大きさの 1.25 倍とする。見積もりは目安で、最終の判断は Google スライドの画像の確認 (計画の R21) で行う。

import { slide, takeaway, title } from "../data/parts.ts";
import type { Margin, Paragraph, Rect, Slide, SlideElement, SlideFigure, TextBody } from "../data/types.ts";
import { WIDE_RANGES } from "./east-asian-width.ts";

/** 見積もる 1 枚のスライド。型 Slide のうち、キー・題名・一言・図の要素。 */
export type FitTarget = Pick<Slide, "key" | "title" | "takeaway" | "elements">;

/** はみ出しそうな箇所。長さはインチ。 */
export interface FitIssue {
  /** スライドのキー。 */
  key: string;
  /** スライドの要素の配列 (elements) の添字。題名のときは "title"、一言のときは "takeaway"。 */
  element: number | "title" | "takeaway";
  /** 文字をすべて収めるのに要る高さ。 */
  need: number;
  /** 箱の高さから上下の内側の余白を引いた、文字を置ける高さ。 */
  height: number;
  /** 文字の先頭 (段落を改行でつないだ文字の、先頭の 40 文字)。 */
  head: string;
}

// Google スライドの文字の内側の余白 (インチ)。API で変えられないので、データの余白がこれより小さくても、この余白になる。
// 見積もりでは、各辺でデータの余白とこの余白の大きい方を使う (計画の U4)
const GOOGLE_MARGIN: Margin = { top: 0.05, right: 0.1, bottom: 0.05, left: 0.1 };
// 箇条書きの項目の字下げ (ポイント)。Google スライドの指示の作成で使う字下げ (計画の KTD14) と同じ値
const BULLET_INDENT_PT = 16;
// 行の高さの、文字の大きさに対する倍率
const LINE_HEIGHT_RATIO = 1.25;
// 要る高さが文字を置ける高さをこの割合まで超えても、一覧に出さない。元の fitcheck.py の値
const TOLERANCE = 1.02;
// 結果の文字の先頭の文字数
const HEAD_LENGTH = 40;
// 文字を置ける幅が 0 以下のときに、行数の計算で 0 で割らないために使う幅 (インチ)。元の fitcheck.py の値
const MIN_WIDTH = 0.01;

/** 文字のコードポイントが、範囲の表 WIDE_RANGES のどれかに入るか (二分探索)。 */
function isWide(cp: number): boolean {
  let lo = 0;
  let hi = WIDE_RANGES.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const range = WIDE_RANGES[mid];
    if (range === undefined) return false;
    const [first, last] = range;
    if (cp < first) hi = mid - 1;
    else if (cp > last) lo = mid + 1;
    else return true;
  }
  return false;
}

/**
 * 1 文字の幅 (全角の文字を 1 とした文字数)。半角の空白は 0.3、全角は 1、それ以外は 0.58。
 * 全角は、Python の関数 unicodedata.east_asian_width が W・F・A を返す文字 (ファイル src/fit/east-asian-width.ts)。
 */
export function charWidth(ch: string): number {
  if (ch === " ") return 0.3;
  const cp = ch.codePointAt(0);
  return cp !== undefined && isWide(cp) ? 1 : 0.58;
}

/** 1 行の文字と、その行の最も大きい文字の大きさ (ポイント)。 */
interface Line {
  text: string;
  fontSize: number;
}

/**
 * 段落を行に分ける。文字の部分が改行を含めば、そこで行を分ける。
 * 行の文字の大きさは、その行に入った部分 (文字が空の部分を含む) の最も大きい文字の大きさ。
 */
function toLines(p: Paragraph): Line[] {
  const lines: Line[] = [];
  let current: Line | null = null;
  for (const run of p.runs) {
    for (const [i, segment] of run.text.split("\n").entries()) {
      if (current === null || i > 0) {
        current = { text: "", fontSize: run.fontSize };
        lines.push(current);
      }
      current.text += segment;
      current.fontSize = Math.max(current.fontSize, run.fontSize);
    }
  }
  return lines;
}

/** 文字をすべて収めるのに要る高さ (インチ)。width は文字を置ける幅 (インチ)。 */
function neededHeight(body: TextBody, width: number): number {
  let need = 0;
  for (const p of body.paragraphs) {
    const lineWidth = p.bullet ? width - BULLET_INDENT_PT / 72 : width;
    for (const line of toLines(p)) {
      let ems = 0;
      for (const ch of line.text) ems += charWidth(ch);
      const n = Math.max(1, Math.ceil(((ems * line.fontSize) / 72) / Math.max(lineWidth, MIN_WIDTH)));
      need += (n * line.fontSize * LINE_HEIGHT_RATIO) / 72;
    }
  }
  // 段落の後の間隔は、段落の間にだけ足す。最後の段落の後の間隔は、文字が箱からはみ出すかどうかに影響しないため
  need += (Math.max(0, body.paragraphs.length - 1) * body.paraSpaceAfter) / 72;
  return need;
}

/** 文字の箱の文字を見積もり、はみ出しそうなら箇所を返す。 */
function estimateBody(
  key: string,
  element: FitIssue["element"],
  rect: Rect,
  body: TextBody,
): FitIssue | null {
  const all = body.paragraphs.map((p) => p.runs.map((r) => r.text).join("")).join("\n");
  if (all.trim() === "") return null;
  const m = body.margin;
  const left = Math.max(m.left / 72, GOOGLE_MARGIN.left);
  const right = Math.max(m.right / 72, GOOGLE_MARGIN.right);
  const top = Math.max(m.top / 72, GOOGLE_MARGIN.top);
  const bottom = Math.max(m.bottom / 72, GOOGLE_MARGIN.bottom);
  const width = rect.w - left - right;
  const height = rect.h - top - bottom;
  const need = neededHeight(body, width);
  if (need <= height * TOLERANCE && width > 0) return null;
  return { key, element, need, height, head: Array.from(all).slice(0, HEAD_LENGTH).join("") };
}

/** 要素の文字を返す。線と、文字を持たない図形は null。 */
function textOf(e: SlideElement): TextBody | null {
  switch (e.kind) {
    case "line":
      return null;
    case "shape":
      return e.text;
    case "textBox":
      return e.text;
  }
}

/** 部品の関数 title か takeaway が作る文字の箱で、題名か一言を見積もる。 */
function estimateFixedBox(
  key: string,
  element: "title" | "takeaway",
  add: (s: SlideFigure, t: string) => void,
  t: string,
): FitIssue | null {
  const fig = slide(key);
  add(fig, t);
  const [box] = fig.elements;
  if (box?.kind !== "textBox") {
    throw new Error(`関数 ${element} が文字の箱を作らなかった (キー ${key})`);
  }
  return estimateBody(key, element, box, box.text);
}

/**
 * スライドの題名・図の要素の文字・一言を見積もり、はみ出しそうな箇所を一覧にする。
 * 題名は部品の関数 title が、一言は部品の関数 takeaway が作る箱で見積もる。
 * 一覧は、スライドの順序に並ぶ。スライドの中では、題名・要素の順序の図の要素・一言の順に並ぶ。
 */
export function estimateSlides(slides: readonly FitTarget[]): FitIssue[] {
  const issues: FitIssue[] = [];
  for (const s of slides) {
    const titleIssue = estimateFixedBox(s.key, "title", title, s.title);
    if (titleIssue !== null) issues.push(titleIssue);
    s.elements.forEach((e, i) => {
      const body = textOf(e);
      if (body === null) return;
      const issue = estimateBody(s.key, i, e, body);
      if (issue !== null) issues.push(issue);
    });
    const takeawayIssue = estimateFixedBox(s.key, "takeaway", takeaway, s.takeaway);
    if (takeawayIssue !== null) issues.push(takeawayIssue);
  }
  return issues;
}
