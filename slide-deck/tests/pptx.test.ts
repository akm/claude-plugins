// PowerPoint の書き出し (ファイル src/pptx/write.ts) のテスト。
// 書き出したファイル (ZIP) の XML を読み、スライドのデータと一致することを確認する。
// pptxgenjs は、テストでは開発のときの node_modules から読み込む (入口がキャッシュから読み込むことは tests/cli.test.ts で確認する)。

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, test } from "node:test";
import { fileURLToPath } from "node:url";
import JSZip from "jszip";
import PptxGen from "pptxgenjs";
import sampleDeck from "../examples/sample/deck.ts";
import { assembleDeck } from "../src/check/deck.ts";
import { arrow, box, bullets, parts, slide, text } from "../src/data/parts.ts";
import { SCHEME_COLOR_NAMES, type Theme } from "../src/data/theme.ts";
import { type Deck, type Paragraph, SLIDE_SIZE, type Slide, type SlideElement } from "../src/data/types.ts";
import { parseOutline } from "../src/outline/parse.ts";
import { applyThemeInput, renderPptx, schemeColor } from "../src/pptx/write.ts";

const SAMPLE_DIR = join(dirname(fileURLToPath(import.meta.url)), "..", "examples", "sample");
const EMU_PER_INCH = 914400;
const EMU_PER_PT = 12700;

/** 見本の資料のスライドのデータ */
function sample(): Deck {
  const r = parseOutline(readFileSync(join(SAMPLE_DIR, "outline.md"), "utf8"));
  if (!r.ok) assert.fail("見本の資料の構成案に誤りがある");
  return assembleDeck(r.outline, sampleDeck(parts));
}

/** 書き出したファイルの部品 (ZIP の中のファイル) の内容を読む */
async function render(deck: Deck): Promise<(name: string) => Promise<string>> {
  const zip = await JSZip.loadAsync(await renderPptx(deck, PptxGen));
  return async (name) => {
    const file = zip.file(name);
    if (file === null) assert.fail(`${name} が無い`);
    return file.async("string");
  };
}

function decode(s: string): string {
  return s
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&amp;/g, "&");
}

/** スライドの XML の図形 (要素 p:sp) を、順に取り出す */
function shapes(xml: string): string[] {
  return xml.split("<p:sp>").slice(1);
}

/** 図形の段落ごとの文字。文字を持たない図形は空の配列 */
function paragraphTexts(sp: string): string[] {
  return [...sp.matchAll(/<a:p>(.*?)<\/a:p>/gs)].map((m) =>
    [...(m[1] ?? "").matchAll(/<a:t>(.*?)<\/a:t>/gs)].map((t) => decode(t[1] ?? "")).join(""),
  );
}

/** スライドのデータの段落ごとの文字 */
function dataTexts(paragraphs: readonly Paragraph[]): string[] {
  return paragraphs.map((p) => p.runs.map((r) => r.text).join(""));
}

function elementTexts(e: SlideElement): string[] {
  if (e.kind === "line" || (e.kind === "shape" && e.text === null)) return [];
  return dataTexts(e.kind === "shape" ? (e.text?.paragraphs ?? []) : e.text.paragraphs);
}

/** 1 枚のスライドの、図形の順序で並べた期待の段落ごとの文字。題名・図の要素・一言の順 */
function expectedTexts(s: Slide): string[][] {
  return [[s.title], ...s.elements.map(elementTexts), [s.takeaway]];
}

/** 図を 1 枚だけ持つ資料 */
function oneSlide(build: (fig: ReturnType<typeof slide>) => void): Deck {
  const fig = slide("k");
  build(fig);
  const theme: Theme = sampleDeck(parts).theme;
  return { title: "資料", theme, slides: [{ key: "k", title: "題名", takeaway: "一言", notes: "", elements: fig.elements }] };
}

/** 図を 1 枚だけ持つ資料の、図の要素の図形 (題名と一言の図形を除く) */
async function figureShapes(deck: Deck): Promise<string[]> {
  const read = await render(deck);
  return shapes(await read("ppt/slides/slide1.xml")).slice(1, -1);
}

describe("見本の資料の PowerPoint のファイル", () => {
  test("スライドの数・各スライドの図形の順序と段落ごとの文字・発表者ノートが、構成案と deck.ts の図と一致する", async () => {
    const deck = sample();
    const read = await render(deck);
    const presentation = await read("ppt/presentation.xml");
    assert.equal([...presentation.matchAll(/<p:sldId /g)].length, deck.slides.length);
    assert.equal(deck.slides.length, 4);
    for (const [i, s] of deck.slides.entries()) {
      const xml = await read(`ppt/slides/slide${String(i + 1)}.xml`);
      assert.deepEqual(shapes(xml).map(paragraphTexts), expectedTexts(s), s.key);
      const notes = await read(`ppt/notesSlides/notesSlide${String(i + 1)}.xml`);
      const body = shapes(notes).find((sp) => sp.includes('type="body"'));
      assert.ok(body !== undefined);
      // pptxgenjs は、ノートの改行を CR LF にして 1 つの段落に書く
      assert.equal(paragraphTexts(body).join("\n").replace(/\r\n/g, "\n"), s.notes, s.key);
    }
  });

  test("図形と文字の色は、どれもテーマの色 (a:schemeClr) で書かれている", async () => {
    const read = await render(sample());
    for (let i = 1; i <= 4; i++) {
      const xml = await read(`ppt/slides/slide${String(i)}.xml`);
      assert.doesNotMatch(xml, /<a:srgbClr/, `slide${String(i)}.xml`);
      assert.match(xml, /<a:schemeClr val="accent\d"\/>/);
    }
    // 見本の資料のキー read-path の最初の箱は、塗りつぶしが accent1 で、文字が lt1 (PowerPoint のファイルでは bg1)
    const [, first] = shapes(await read("ppt/slides/slide1.xml"));
    assert.match(first ?? "", /<p:spPr>.*<a:solidFill><a:schemeClr val="accent1"\/><\/a:solidFill>.*<\/p:spPr>/s);
    assert.match(first ?? "", /<a:rPr [^>]*><a:solidFill><a:schemeClr val="bg1"\/><\/a:solidFill>/);
  });

  test("スライドの大きさは SLIDE_SIZE (10×5.625 インチ) で、文書のプロパティのタイトルは資料の題名", async () => {
    const read = await render(sample());
    assert.match(
      await read("ppt/presentation.xml"),
      new RegExp(`<p:sldSz cx="${String(SLIDE_SIZE.w * EMU_PER_INCH)}" cy="${String(SLIDE_SIZE.h * EMU_PER_INCH)}"/>`),
    );
    assert.match(await read("docProps/core.xml"), /<dc:title>キャッシュのしくみ<\/dc:title>/);
  });

  test("題名は、部品の関数 title の箱と同じ位置の、レイアウトの題名のプレースホルダーに入る", async () => {
    const read = await render(sample());
    const [title] = shapes(await read("ppt/slides/slide1.xml"));
    assert.match(title ?? "", /<p:ph\s[^>]*type="title"/);
    const layout = await read("ppt/slideLayouts/slideLayout2.xml");
    assert.match(layout, /<p:cSld name="SLIDE_DECK_CONTENT">/);
    const x = String(0.5 * EMU_PER_INCH);
    const y = String(Math.round(0.58 * EMU_PER_INCH));
    assert.match(layout, new RegExp(`<p:ph\\s[^>]*type="title".*<a:off x="${x}" y="${y}"/><a:ext cx="${String(9 * EMU_PER_INCH)}"`, "s"));
    assert.match(layout, /<a:defRPr [^>]*sz="2400" b="1"/);
  });

  test("レイアウトの背景を、テーマの lt1 (PowerPoint のファイルでは bg1) で塗る", async () => {
    const read = await render(sample());
    assert.match(
      await read("ppt/slideLayouts/slideLayout2.xml"),
      /<p:bg><p:bgPr><a:solidFill><a:schemeClr val="bg1"\/><\/a:solidFill>/,
    );
  });
});

describe("要素の書き出し", () => {
  test("段落は、部品の関数が分けた段落のとおりになり、箇条書きは字下げ 16 ポイントの項目になる", async () => {
    const deck = oneSlide((fig) => {
      text(fig, [{ text: "見出し", bold: true }, ...bullets(["a", "b"])], 0, 0, 3, 2);
      box(fig, 0, 2, 3, 1, [{ text: "上", breakLine: true }, { text: "", breakLine: true }, { text: "下" }]);
    });
    const [list, lines] = await figureShapes(deck);
    assert.deepEqual(paragraphTexts(list ?? ""), ["見出し", "a", "b"]);
    const items = [...(list ?? "").matchAll(/<a:pPr ([^>]*)>(.*?)<\/a:pPr>/gs)];
    assert.equal(items.length, 3);
    assert.match(items[0]?.[2] ?? "", /<a:buNone\/>/);
    for (const item of items.slice(1)) {
      assert.match(item[1] ?? "", new RegExp(`marL="${String(16 * EMU_PER_PT)}"`));
      assert.match(item[2] ?? "", /<a:buChar /);
    }
    assert.deepEqual(paragraphTexts(lines ?? ""), ["上", "", "下"]);
  });

  test("内側の余白は、上・右・下・左がそれぞれの辺の余白になる", async () => {
    const deck = oneSlide((fig) => {
      box(fig, 0, 0, 3, 1, "文字", { margin: [1, 2, 3, 4] });
    });
    const [sp] = await figureShapes(deck);
    const body = /<a:bodyPr [^>]*>/.exec(sp ?? "")?.[0] ?? "";
    assert.match(body, new RegExp(`tIns="${String(1 * EMU_PER_PT)}"`));
    assert.match(body, new RegExp(`rIns="${String(2 * EMU_PER_PT)}"`));
    assert.match(body, new RegExp(`bIns="${String(3 * EMU_PER_PT)}"`));
    assert.match(body, new RegExp(`lIns="${String(4 * EMU_PER_PT)}"`));
  });

  test("図形の形・角の半径・枠線を、データのとおりに書く", async () => {
    const deck = oneSlide((fig) => {
      box(fig, 0, 0, 2, 1, "角丸", { radius: 0.25, line: "accent3", lineW: 2, dash: true });
      box(fig, 0, 0, 2, 1, "", { shape: "homePlate", fill: "accent2" });
      box(fig, 0, 0, 2, 1, "円柱", { shape: "can" });
    });
    const [round, home, can] = await figureShapes(deck);
    assert.match(round ?? "", /prst="roundRect"/);
    // 角の半径 0.25 インチは、短い辺 1 インチに対する割合 (100000 が 1 倍) で書かれる
    assert.match(round ?? "", /<a:gd name="adj" fmla="val 25000"\/>/);
    assert.match(round ?? "", new RegExp(`<a:ln w="${String(2 * EMU_PER_PT)}"><a:solidFill><a:schemeClr val="accent3"/></a:solidFill><a:prstDash val="dash"/>`));
    assert.match(home ?? "", /prst="homePlate"/);
    assert.doesNotMatch(home ?? "", /<p:txBody>/);
    assert.match(can ?? "", /prst="can"/);
  });

  test("線は、向きを反転のフラグで表し、終点の矢じりを a:tailEnd に、始点の矢じりを a:headEnd に書く", async () => {
    const deck = oneSlide((fig) => {
      arrow(fig, 3, 2, 1, 1);
      arrow(fig, 0, 0, 1, 1, { both: true });
      arrow(fig, 0, 0, 1, 0, { noHead: true, dash: true });
    });
    const [back, both, plain] = await figureShapes(deck);
    assert.match(back ?? "", /<a:xfrm flipH="1" flipV="1">/);
    assert.match(back ?? "", /<a:tailEnd type="triangle"\/>/);
    assert.doesNotMatch(back ?? "", /<a:headEnd/);
    assert.match(both ?? "", /<a:headEnd type="triangle"\/><a:tailEnd type="triangle"\/>/);
    assert.doesNotMatch(plain ?? "", /<a:headEnd|<a:tailEnd/);
    assert.match(plain ?? "", /<a:prstDash val="dash"\/>/);
  });

  test("リンクの付いた文字は、その URL へのリンクになる", async () => {
    const deck = oneSlide((fig) => {
      text(fig, [{ text: "規則: " }, { text: "RFC 9111", link: "https://www.rfc-editor.org/rfc/rfc9111" }], 0, 0, 3, 1);
    });
    const read = await render(deck);
    const [, sp] = shapes(await read("ppt/slides/slide1.xml"));
    const id = /<a:hlinkClick r:id="(rId\d+)"/.exec(sp ?? "")?.[1];
    assert.ok(id !== undefined);
    assert.match(
      await read("ppt/slides/_rels/slide1.xml.rels"),
      new RegExp(`Id="${id}"[^>]*Target="https://www\\.rfc-editor\\.org/rfc/rfc9111"`),
    );
  });

  test("テーマの色の名前は、dk1・lt1・dk2・lt2 を tx1・bg1・tx2・bg2 に、ほかはそのままにする", () => {
    assert.deepEqual(
      (["dk1", "lt1", "dk2", "lt2", "accent1", "accent6"] as const).map(schemeColor),
      ["tx1", "bg1", "tx2", "bg2", "accent1", "accent6"],
    );
  });
});

describe("関数 applyThemeInput", () => {
  test("pptx のスキルの apply_theme.js に渡すテーマは、名前・フォント・12 色を持つ", () => {
    const theme = sampleDeck(parts).theme;
    const input = applyThemeInput(theme);
    assert.equal(input.name, "Cache");
    assert.equal(input.headFontFace, "Noto Sans JP");
    assert.deepEqual(Object.keys(input.colors).sort(), [...SCHEME_COLOR_NAMES].sort());
    assert.equal(input.colors.accent1, "0F6E8C");
    assert.equal(input.colors.dk1, "1F2933");
  });
});
