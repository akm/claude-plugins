import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, test } from "node:test";
import { fileURLToPath } from "node:url";
import sampleDeck from "../examples/sample/deck.ts";
import { arrow, box, bullets, card, parts, slide, text } from "../src/data/parts.ts";
import type { SlideElement, TextBoxElement } from "../src/data/types.ts";
import { charWidth, estimateSlides, type FitIssue, type FitTarget } from "../src/fit/estimate.ts";
import { parseOutline } from "../src/outline/parse.ts";

const SAMPLE_DIR = join(dirname(fileURLToPath(import.meta.url)), "..", "examples", "sample");

// 14 ポイントの 1 行の高さ (インチ)。行の高さは文字の大きさの 1.25 倍 (計画の KTD6)
const LINE_14 = (14 * 1.25) / 72;
// 全角 10 文字・14 ポイントの文字の幅 (インチ)。1.94 インチ
const ZENKAKU_10 = "あいうえおかきくけこ";

/** 要素だけのスライド 1 枚 (一言は空) を見積もる。 */
function estimate(elements: SlideElement[], key = "k"): FitIssue[] {
  return estimateSlides([{ key, takeaway: "", elements }]);
}

/** 実数を、丸めの誤差を許して比べる。 */
function assertClose(actual: number, expected: number): void {
  assert.ok(Math.abs(actual - expected) < 1e-9, `${String(actual)} は ${String(expected)} と等しくない`);
}

// 関数 text の内側の余白のデフォルト値は 0 なので、見積もりでは Google スライドの余白
// (左右 0.1 インチ・上下 0.05 インチ) を使う。文字を置ける幅は、箱の幅から 0.2 インチを引いた幅になる
describe("関数 estimateSlides の、文字の幅と行数", () => {
  test("全角 10 文字・14 ポイントの文字が、文字を置ける幅 2 インチの箱に 1 行で入るとき、一覧は空になる", () => {
    const s = slide("k");
    text(s, ZENKAKU_10, 0, 0, 2.2, LINE_14 + 0.1);
    assert.deepEqual(estimate(s.elements), []);
  });

  test("同じ文字が、文字を置ける幅 1 インチの箱で 2 行になり、高さが 1 行分しか無いとき、一覧に 1 件出る", () => {
    const s = slide("cutover");
    text(s, ZENKAKU_10, 0, 0, 1.2, LINE_14 + 0.1);
    const issues = estimate(s.elements, "cutover");
    assert.equal(issues.length, 1);
    const [issue] = issues;
    assert.ok(issue !== undefined);
    assert.equal(issue.key, "cutover");
    assert.equal(issue.element, 0);
    assertClose(issue.need, 2 * LINE_14);
    assertClose(issue.height, LINE_14);
    assert.equal(issue.head, ZENKAKU_10);
  });

  test("改行を含む文字は、行ごとに見積もる", () => {
    // 部品の関数は改行で段落を分ける。2 行分の高さがあれば入り、1 行分なら一覧に出る
    const fits = slide("k");
    text(fits, "あいう\nえお", 0, 0, 2.2, 2 * LINE_14 + 0.1);
    assert.deepEqual(estimate(fits.elements), []);
    const overflows = slide("k");
    text(overflows, "あいう\nえお", 0, 0, 2.2, LINE_14 + 0.1);
    const [issue] = estimate(overflows.elements);
    assert.ok(issue !== undefined);
    assertClose(issue.need, 2 * LINE_14);
    assert.equal(issue.head, "あいう\nえお");
  });

  test("段落の中の文字の部分が改行を含んでも、行ごとに見積もる", () => {
    // 部品の関数を通さずに作ったデータでも、改行の前後を 1 行にまとめて幅を数えない。
    // まとめて数えると、全角 5 文字と改行の文字の幅は 1 インチほどで、1 行に入ると見積もってしまう
    const element: TextBoxElement = {
      kind: "textBox",
      x: 0,
      y: 0,
      w: 2.2,
      h: LINE_14 + 0.1,
      text: {
        paragraphs: [
          {
            runs: [
              { text: "あいう\nえお", fontSize: 14, bold: false, color: "dk1", link: null },
            ],
            bullet: false,
          },
        ],
        align: "left",
        valign: "top",
        margin: { top: 0, right: 0, bottom: 0, left: 0 },
        paraSpaceAfter: 0,
      },
      name: null,
    };
    const [issue] = estimate([element]);
    assert.ok(issue !== undefined);
    assertClose(issue.need, 2 * LINE_14);
  });

  test("半角の英数字は 0.58 文字分の幅で数える", () => {
    // 半角 20 文字・14 ポイントの幅は 20 × 0.58 × 14 / 72 = 2.256 インチ
    const half = "ABCDEFGHIJ0123456789";
    const fits = slide("k");
    text(fits, half, 0, 0, 2.5, LINE_14 + 0.1);
    assert.deepEqual(estimate(fits.elements), []);
    const overflows = slide("k");
    text(overflows, half, 0, 0, 2.4, LINE_14 + 0.1);
    assert.equal(estimate(overflows.elements).length, 1);
  });

  test("一部ずつ大きさの違う文字は、行ごとに最も大きい文字で見積もる", () => {
    // 20 ポイントで見積もると幅 10 × 20 / 72 = 2.78 インチの 1 行で、高さは 20 × 1.25 / 72 = 0.347 インチ。
    // 後の部分の 10 ポイントで見積もると、高さ 0.174 インチで入ってしまう
    const s = slide("k");
    text(
      s,
      [
        { text: "あいうえお", fontSize: 20 },
        { text: "かきくけこ", fontSize: 10 },
      ],
      0,
      0,
      3.2,
      0.3 + 0.1,
    );
    const [issue] = estimate(s.elements);
    assert.ok(issue !== undefined);
    assertClose(issue.need, (20 * 1.25) / 72);
  });

  test("幅が余白より狭い箱は、一覧に出る", () => {
    // 文字を置ける幅は 0.15 - 0.2 で負になる。高さが十分にあっても一覧に出る
    // (行数を幅 0.01 インチで数えるので、要る高さは 20 行分の 4.9 インチで、高さ 10 インチに収まる)
    const s = slide("k");
    text(s, "あ", 0, 0, 0.15, 10);
    assert.equal(estimate(s.elements).length, 1);
  });
});

describe("関数 estimateSlides の、余白・段落の間隔・箇条書き", () => {
  test("データの余白が Google スライドの余白より大きいときは、データの余白で見積もる", () => {
    // 左右 0.25 インチ (18 ポイント) の余白で、文字を置ける幅は 2.5 - 0.5 = 2 インチ
    const fits = slide("k");
    text(fits, ZENKAKU_10, 0, 0, 2.5, LINE_14 + 0.5, { margin: 18 });
    assert.deepEqual(estimate(fits.elements), []);
    const overflows = slide("k");
    text(overflows, ZENKAKU_10, 0, 0, 2.3, LINE_14 + 0.5, { margin: 18 });
    const [issue] = estimate(overflows.elements);
    assert.ok(issue !== undefined);
    assertClose(issue.height, LINE_14);
  });

  test("段落の後の間隔は、段落の間にだけ足す", () => {
    // 2 段落・12 ポイントの間隔で、要る高さは 2 行分 + 12 / 72 インチ。
    // 最後の段落の後にも足すと、0.66 インチの高さに入らなくなる
    const need = 2 * LINE_14 + 12 / 72;
    const fits = slide("k");
    text(fits, "あ\nい", 0, 0, 2.2, 0.66 + 0.1, { psa: 12 });
    assert.deepEqual(estimate(fits.elements), []);
    const overflows = slide("k");
    text(overflows, "あ\nい", 0, 0, 2.2, 0.6 + 0.1, { psa: 12 });
    const [issue] = estimate(overflows.elements);
    assert.ok(issue !== undefined);
    assertClose(issue.need, need);
  });

  test("箇条書きの項目は、文字を置ける幅から字下げの 16 ポイントを引いて見積もる", () => {
    // 文字を置ける幅 2 インチから 16 / 72 インチを引くと 1.78 インチで、全角 10 文字 (1.94 インチ) は 2 行になる
    const s = slide("k");
    text(s, bullets([ZENKAKU_10]), 0, 0, 2.2, LINE_14 + 0.1);
    const [issue] = estimate(s.elements);
    assert.ok(issue !== undefined);
    assertClose(issue.need, 2 * LINE_14);
  });
});

describe("関数 estimateSlides の対象と結果", () => {
  test("図形の中の文字も見積もり、要素の番号はスライドの要素の配列の添字になる", () => {
    // 関数 box の余白のデフォルト値 6 ポイント (0.083 インチ) は、Google スライドの左右の余白 0.1 インチより小さい
    const s = slide("k");
    card(s, 0, 0, 5, 3);
    arrow(s, 0, 0, 1, 1);
    box(s, 0, 0, 1.2, LINE_14 + 0.1, ZENKAKU_10);
    const issues = estimate(s.elements);
    assert.equal(issues.length, 1);
    assert.equal(issues[0]?.element, 2);
  });

  test("線・文字の無い図形・空白だけの文字は、一覧に出ない", () => {
    const s = slide("k");
    arrow(s, 0, 0, 1, 1);
    card(s, 0, 0, 0.01, 0.01);
    text(s, "   ", 0, 0, 0.01, 0.01);
    assert.deepEqual(estimate(s.elements), []);
  });

  test("一言は、部品の関数 takeaway が作る箱で見積もり、要素の番号を takeaway にする", () => {
    // 一言の箱は幅 8.5 インチ・高さ 0.42 インチ・14 ポイントの太字
    assert.deepEqual(estimateSlides([{ key: "k", takeaway: ZENKAKU_10, elements: [] }]), []);
    const long = ZENKAKU_10.repeat(5);
    const [issue] = estimateSlides([{ key: "k", takeaway: long, elements: [] }]);
    assert.ok(issue !== undefined);
    assert.equal(issue.element, "takeaway");
    assertClose(issue.need, 2 * LINE_14);
    assertClose(issue.height, 0.42 - 0.1);
  });

  test("一覧は、スライドの順序、スライドの中では要素の順序で、一言は最後に並ぶ", () => {
    const a = slide("a");
    text(a, ZENKAKU_10, 0, 0, 1.2, LINE_14 + 0.1);
    text(a, ZENKAKU_10, 0, 0, 1.2, LINE_14 + 0.1);
    const b = slide("b");
    text(b, ZENKAKU_10, 0, 0, 1.2, LINE_14 + 0.1);
    const issues = estimateSlides([
      { key: "a", takeaway: ZENKAKU_10.repeat(5), elements: a.elements },
      { key: "b", takeaway: "", elements: b.elements },
    ]);
    assert.deepEqual(
      issues.map((i) => [i.key, i.element]),
      [
        ["a", 0],
        ["a", 1],
        ["a", "takeaway"],
        ["b", 0],
      ],
    );
  });

  test("文字の先頭は、段落を改行でつないだ文字の先頭 40 文字", () => {
    const s = slide("k");
    text(s, ["あ".repeat(30), "い".repeat(30)].join("\n"), 0, 0, 0.15, 0.1);
    const [issue] = estimate(s.elements);
    assert.equal(issue?.head, `${"あ".repeat(30)}\n${"い".repeat(9)}`);
  });
});

/** 見本の資料の構成案の一言と、資料ごとのスクリプトの図を、構成案の順序で組み合わせる。 */
function sampleTargets(): FitTarget[] {
  const r = parseOutline(readFileSync(join(SAMPLE_DIR, "outline.md"), "utf8"));
  if (!r.ok) assert.fail("見本の資料の構成案に誤りがある");
  const figures = sampleDeck(parts).slides;
  return r.outline.slides.map((s) => {
    const figure = figures.find((f) => f.key === s.key);
    if (figure === undefined) assert.fail(`見本の資料ごとのスクリプトに、キー ${s.key} の図が無い`);
    return { key: s.key, takeaway: s.takeaway, elements: figure.elements };
  });
}

describe("見本の資料", () => {
  test("見本の資料では、一覧が空になる", () => {
    assert.deepEqual(estimateSlides(sampleTargets()), []);
  });

  test("見本の資料の文字の箱をわざと狭くすると、その箱が一覧に出る", () => {
    const targets = sampleTargets();
    const [first] = targets;
    assert.ok(first !== undefined);
    const index = first.elements.findIndex((e) => e.kind !== "line" && e.text !== null);
    const element = first.elements[index];
    assert.ok(element !== undefined && element.kind !== "line");
    first.elements[index] = { ...element, w: 0.5 };
    assert.deepEqual(
      estimateSlides(targets).map((i) => [i.key, i.element]),
      [[first.key, index]],
    );
  });
});

describe("関数 charWidth", () => {
  test("全角の文字は 1、半角の文字は 0.58、半角の空白は 0.3 文字分の幅", () => {
    assert.equal(charWidth("あ"), 1);
    assert.equal(charWidth("漢"), 1);
    assert.equal(charWidth("Ａ"), 1);
    assert.equal(charWidth("　"), 1);
    assert.equal(charWidth("A"), 0.58);
    assert.equal(charWidth("1"), 0.58);
    assert.equal(charWidth("ｱ"), 0.58);
    assert.equal(charWidth(" "), 0.3);
  });

  test("文脈で幅が変わる文字 (東アジアの文字幅の A) は、全角として数える", () => {
    for (const ch of ["→", "×", "…", "○", "①", "※"]) assert.equal(charWidth(ch), 1, ch);
  });

  test("基本多言語面の外の文字も、範囲の表で判定する", () => {
    // 絵文字 U+1F600 は W
    assert.equal(charWidth("😀"), 1);
    assert.equal(charWidth("𝐀"), 0.58);
  });
});
