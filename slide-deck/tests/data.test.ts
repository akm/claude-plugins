import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { describe, test } from "node:test";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import {
  arrow,
  badge,
  box,
  bullets,
  card,
  parts,
  slide,
  takeaway,
  text,
  title,
} from "../src/data/parts.ts";
import { checkTheme, schemeColorValues, type Theme } from "../src/data/theme.ts";
import { SLIDE_SIZE } from "../src/data/types.ts";
import type { DeckScript, RunInput } from "../src/index.ts";

const PLUGIN_DIR = join(dirname(fileURLToPath(import.meta.url)), "..");

const THEME: Theme = {
  name: "Sample",
  fonts: { heading: "Noto Sans JP", body: "Noto Sans JP" },
  colors: {
    dk1: "1F2933",
    lt1: "FFFFFF",
    dk2: "52606D",
    lt2: "F2F4F7",
    hlink: "0F6E8C",
    folHlink: "6B4F9E",
  },
  accents: {
    accent1: { color: "0F8B8D", meaning: "新しいもの" },
    accent2: { color: "7B8794", meaning: "古いもの" },
    accent3: { color: "D9480F", meaning: "失敗" },
    accent4: { color: "2F9E44", meaning: "成功" },
    accent5: { color: "F0A202", meaning: "重なる期間" },
    accent6: { color: "1C3D5A", meaning: "データ" },
  },
};

describe("関数 box", () => {
  test("位置・大きさ・文字・テーマの色を渡すと、同じ値を持つ要素が 1 つ作られる", () => {
    const s = slide("cutover");
    box(s, 0.5, 1.4, 9.0, 0.6, "新旧が同じデータを読み書きする", {
      fill: "accent5",
      color: "lt1",
      line: "accent3",
    });
    assert.deepEqual(s.elements, [
      {
        kind: "shape",
        shape: "roundRect",
        radius: 0.08,
        x: 0.5,
        y: 1.4,
        w: 9.0,
        h: 0.6,
        fill: { color: "accent5", transparency: 0 },
        outline: { color: "accent3", width: 1, dashed: false },
        text: {
          paragraphs: [
            {
              runs: [
                {
                  text: "新旧が同じデータを読み書きする",
                  fontSize: 14,
                  bold: false,
                  color: "lt1",
                  link: null,
                },
              ],
              bullet: false,
            },
          ],
          align: "center",
          valign: "middle",
          margin: { top: 6, right: 6, bottom: 6, left: 6 },
          paraSpaceAfter: 0,
        },
        name: null,
      },
    ]);
  });

  test("オプションを省略すると、元のファイル build.js のデフォルト値になる (白の塗りつぶし・枠線なし)", () => {
    const s = slide("k");
    box(s, 0, 0, 1, 1, "x");
    const [e] = s.elements;
    assert.ok(e?.kind === "shape");
    assert.deepEqual(e.fill, { color: "lt1", transparency: 0 });
    assert.equal(e.outline, null);
    assert.equal(e.text?.paragraphs[0]?.runs[0]?.color, "dk1");
  });

  test("角の丸い四角以外の形は、角の半径を持たない", () => {
    const s = slide("k");
    box(s, 0, 0, 1.4, 0.7, "DB", { shape: "can", fill: "accent6" });
    const [e] = s.elements;
    assert.ok(e?.kind === "shape");
    assert.equal(e.shape, "can");
    assert.equal("radius" in e, false);
  });

  test("文字が空なら、文字を持たない図形になる", () => {
    const s = slide("k");
    box(s, 3.6, 3.7, 2.4, 0.95, "", { shape: "rect", fill: "accent5", tr: 25 });
    const [e] = s.elements;
    assert.ok(e?.kind === "shape");
    assert.equal(e.text, null);
    assert.deepEqual(e.fill, { color: "accent5", transparency: 25 });
  });

  test("余白の配列は、上・右・下・左の順に読む", () => {
    const s = slide("k");
    box(s, 0, 0, 6, 0.4, "x", { margin: [1, 2, 3, 4] });
    const [e] = s.elements;
    assert.ok(e?.kind === "shape");
    assert.deepEqual(e.text?.margin, { top: 1, right: 2, bottom: 3, left: 4 });
  });

  test("破線の枠線の幅を指定できる", () => {
    const s = slide("k");
    box(s, 0, 0, 1, 1, "x", { line: "accent3", lineW: 2, dash: true });
    const [e] = s.elements;
    assert.ok(e?.kind === "shape");
    assert.deepEqual(e.outline, { color: "accent3", width: 2, dashed: true });
  });
});

describe("関数 arrow", () => {
  test("左から右・上から下の矢印は、反転のフラグを持たず、終点にだけ矢じりがある", () => {
    const s = slide("k");
    arrow(s, 1, 2, 3, 2.5);
    assert.deepEqual(s.elements, [
      {
        kind: "line",
        x: 1,
        y: 2,
        w: 2,
        h: 0.5,
        flipH: false,
        flipV: false,
        color: "dk2",
        width: 1.5,
        dashed: false,
        endArrow: true,
        startArrow: false,
      },
    ]);
  });

  test("右から左へ向かう矢印は、左右を反転するフラグを持つ線になる", () => {
    const s = slide("k");
    arrow(s, 7.3, 3.7, 5.7, 4.3);
    const [e] = s.elements;
    assert.ok(e?.kind === "line");
    assert.equal(e.flipH, true);
    assert.equal(e.flipV, false);
    assert.equal(e.x, 5.7);
    assert.equal(e.y, 3.7);
    assert.ok(Math.abs(e.w - 1.6) < 1e-9);
    assert.ok(Math.abs(e.h - 0.6) < 1e-9);
  });

  test("下から上へ向かう矢印は、上下を反転するフラグを持つ線になる", () => {
    const s = slide("k");
    arrow(s, 2, 3, 2, 1);
    const [e] = s.elements;
    assert.ok(e?.kind === "line");
    assert.equal(e.flipH, false);
    assert.equal(e.flipV, true);
    assert.deepEqual([e.x, e.y, e.w, e.h], [2, 1, 0, 2]);
  });

  test("オプション noHead で矢じりを無くし、オプション both で始点にも付ける", () => {
    const s = slide("k");
    arrow(s, 0, 0, 1, 0, { noHead: true, dash: true, color: "accent3", width: 2 });
    arrow(s, 0, 0, 1, 0, { both: true });
    const [plain, both] = s.elements;
    assert.ok(plain?.kind === "line" && both?.kind === "line");
    assert.deepEqual(
      [plain.startArrow, plain.endArrow, plain.dashed, plain.color, plain.width],
      [false, false, true, "accent3", 2],
    );
    assert.deepEqual([both.startArrow, both.endArrow], [true, true]);
  });
});

describe("関数 badge", () => {
  test("番号の入った円は、文字の大きさ・太字・中央揃えのデフォルト値を持つ", () => {
    const s = slide("k");
    badge(s, 1, 0.7, 1.75, 0.5);
    assert.deepEqual(s.elements, [
      {
        kind: "shape",
        shape: "ellipse",
        x: 0.7,
        y: 1.75,
        w: 0.5,
        h: 0.5,
        fill: { color: "accent1", transparency: 0 },
        outline: null,
        text: {
          paragraphs: [
            {
              runs: [{ text: "1", fontSize: 12, bold: true, color: "lt1", link: null }],
              bullet: false,
            },
          ],
          align: "center",
          valign: "middle",
          margin: { top: 0, right: 0, bottom: 0, left: 0 },
          paraSpaceAfter: 0,
        },
        name: null,
      },
    ]);
  });

  test("円の色と文字の大きさを変えられる", () => {
    const s = slide("k");
    badge(s, "A", 0, 0, 0.5, { fill: "accent4", fontSize: 16 });
    const [e] = s.elements;
    assert.ok(e?.kind === "shape");
    assert.equal(e.fill.color, "accent4");
    assert.equal(e.text?.paragraphs[0]?.runs[0]?.fontSize, 16);
  });
});

describe("関数 takeaway", () => {
  test("一言の部品は、スライドの下の決まった位置の文字の箱になる", () => {
    const s = slide("k");
    takeaway(s, "具体的な注意は DB ごとに違う");
    assert.deepEqual(s.elements, [
      {
        kind: "textBox",
        x: 0.5,
        y: 4.78,
        w: 8.5,
        h: 0.42,
        text: {
          paragraphs: [
            {
              runs: [
                {
                  text: "具体的な注意は DB ごとに違う",
                  fontSize: 14,
                  bold: true,
                  color: "dk1",
                  link: null,
                },
              ],
              bullet: false,
            },
          ],
          align: "left",
          valign: "middle",
          margin: { top: 0, right: 0, bottom: 0, left: 0 },
          paraSpaceAfter: 0,
        },
        name: "takeaway",
      },
    ]);
  });

  test("資料ごとのスクリプトに渡す部品の関数の集まりに、題名と一言の部品は入らない", () => {
    assert.deepEqual(Object.keys(parts).sort(), [
      "arrow",
      "badge",
      "box",
      "bullets",
      "card",
      "slide",
      "text",
    ]);
  });
});

describe("関数 title", () => {
  test("題名の部品は、スライドの上の決まった位置の、24 ポイントの太字の文字の箱になる", () => {
    const s = slide("k");
    title(s, "読み出しの流れ");
    const [e] = s.elements;
    assert.ok(e?.kind === "textBox");
    assert.deepEqual(
      { x: e.x, y: e.y, w: e.w, h: e.h, name: e.name },
      { x: 0.5, y: 0.58, w: 9.0, h: 0.62, name: "title" },
    );
    assert.deepEqual(e.text.paragraphs, [
      { runs: [{ text: "読み出しの流れ", fontSize: 24, bold: true, color: "dk1", link: null }], bullet: false },
    ]);
    assert.equal(e.text.align, "left");
    assert.equal(e.text.valign, "middle");
    assert.deepEqual(e.text.margin, { top: 0, right: 0, bottom: 0, left: 0 });
  });

  test("題名と一言の箱は、スライドの大きさ 10×5.625 インチの中に収まる", () => {
    assert.deepEqual(SLIDE_SIZE, { w: 10, h: 5.625 });
    const s = slide("k");
    title(s, "題名");
    takeaway(s, "一言");
    for (const e of s.elements) {
      assert.ok(e.x >= 0 && e.y >= 0 && e.x + e.w <= SLIDE_SIZE.w && e.y + e.h <= SLIDE_SIZE.h);
    }
  });
});

describe("関数 text", () => {
  test("オプションを省略すると、左上揃え・余白 0・14 ポイントの文字の箱になる", () => {
    const s = slide("k");
    text(s, "時間", 8.9, 3.6, 0.6, 0.3);
    const [e] = s.elements;
    assert.ok(e?.kind === "textBox");
    assert.equal(e.text.align, "left");
    assert.equal(e.text.valign, "top");
    assert.deepEqual(e.text.margin, { top: 0, right: 0, bottom: 0, left: 0 });
    assert.equal(e.text.paragraphs[0]?.runs[0]?.fontSize, 14);
  });

  test("文字の中の改行で、段落を分ける", () => {
    const s = slide("k");
    text(s, "DB\n新しいスキーマ", 0, 0, 1, 1);
    const [e] = s.elements;
    assert.ok(e?.kind === "textBox");
    assert.deepEqual(
      e.text.paragraphs.map((p) => p.runs.map((r) => r.text)),
      [["DB"], ["新しいスキーマ"]],
    );
  });

  test("空行の段落も、文字が空の部分を 1 つ持ち、文字の大きさ・太字・色を持つ", () => {
    const s = slide("k");
    text(s, "a\n\nb", 0, 0, 1, 1, { fontSize: 12, bold: true, color: "dk2" });
    const [e] = s.elements;
    assert.ok(e?.kind === "textBox");
    assert.deepEqual(e.text.paragraphs, [
      { runs: [{ text: "a", fontSize: 12, bold: true, color: "dk2", link: null }], bullet: false },
      { runs: [{ text: "", fontSize: 12, bold: true, color: "dk2", link: null }], bullet: false },
      { runs: [{ text: "b", fontSize: 12, bold: true, color: "dk2", link: null }], bullet: false },
    ]);
  });

  test("書式を表す空の部分は、同じ段落に空でない部分を足すときに除く", () => {
    const s = slide("k");
    text(s, [{ text: "a\n" }, { text: "b", bold: true }, { text: "" }], 0, 0, 1, 1);
    const [e] = s.elements;
    assert.ok(e?.kind === "textBox");
    assert.deepEqual(
      e.text.paragraphs.map((p) => p.runs.map((r) => [r.text, r.bold])),
      [[["a", false]], [["b", true]]],
    );
  });

  test("一部ずつ書式の違う文字は、部分ごとに書式を持ち、省略した書式は部品のものになる", () => {
    const s = slide("k");
    text(
      s,
      [
        { text: "300 秒", fontSize: 40, bold: true, color: "accent6" },
        { text: "（最大 3,600 秒）", fontSize: 16 },
      ],
      5.5,
      1.65,
      3.9,
      0.8,
      { color: "dk2" },
    );
    const [e] = s.elements;
    assert.ok(e?.kind === "textBox");
    assert.deepEqual(e.text.paragraphs, [
      {
        runs: [
          { text: "300 秒", fontSize: 40, bold: true, color: "accent6", link: null },
          { text: "（最大 3,600 秒）", fontSize: 16, bold: false, color: "dk2", link: null },
        ],
        bullet: false,
      },
    ]);
  });

  test("リンクと段落の後の間隔を持てる", () => {
    const s = slide("k");
    text(
      s,
      [
        { text: "PostgreSQL 17: PREPARE", breakLine: true },
        { text: "https://www.postgresql.org/docs/17/sql-prepare.html", link: "https://www.postgresql.org/docs/17/sql-prepare.html" },
      ],
      0.5,
      1.35,
      9,
      3.7,
      { psa: 3 },
    );
    const [e] = s.elements;
    assert.ok(e?.kind === "textBox");
    assert.equal(e.text.paraSpaceAfter, 3);
    assert.equal(e.text.paragraphs.length, 2);
    assert.equal(e.text.paragraphs[0]?.runs[0]?.link, null);
    assert.equal(
      e.text.paragraphs[1]?.runs[0]?.link,
      "https://www.postgresql.org/docs/17/sql-prepare.html",
    );
  });
});

describe("関数 bullets", () => {
  test("項目ごとに、箇条書きの段落になる", () => {
    const s = slide("k");
    text(s, bullets(["表と列を DB に定義する", "migration で定義を変える"], { fontSize: 13 }), 0, 0, 4, 1);
    const [e] = s.elements;
    assert.ok(e?.kind === "textBox");
    assert.deepEqual(e.text.paragraphs, [
      {
        runs: [{ text: "表と列を DB に定義する", fontSize: 13, bold: false, color: "dk1", link: null }],
        bullet: true,
      },
      {
        runs: [{ text: "migration で定義を変える", fontSize: 13, bold: false, color: "dk1", link: null }],
        bullet: true,
      },
    ]);
  });

  test("書式を指定しなければ、受け取る部品の関数の書式を使う", () => {
    const s = slide("k");
    box(s, 0, 0, 4, 1, bullets(["a", "b"]), { fontSize: 11, color: "lt1" });
    text(s, bullets(["c"]), 0, 0, 4, 1);
    const [boxed, plain] = s.elements;
    assert.ok(boxed?.kind === "shape" && plain?.kind === "textBox");
    assert.deepEqual(
      boxed.text?.paragraphs.map((p) => p.runs.map((r) => [r.text, r.fontSize, r.color])),
      [[["a", 11, "lt1"]], [["b", 11, "lt1"]]],
    );
    assert.deepEqual(
      plain.text.paragraphs.map((p) => p.runs.map((r) => [r.text, r.fontSize, r.color])),
      [[["c", 14, "dk1"]]],
    );
  });

  test("見出しの部分の後に箇条書きを続けると、見出しは箇条書きにならず、項目ごとの段落になる", () => {
    const s = slide("k");
    text(s, [{ text: "見出し", bold: true }, ...bullets(["a", "b"])], 0, 0, 1, 1);
    text(s, [{ text: "a", bullet: true }, { text: "b", bullet: true }], 0, 0, 1, 1);
    const summaries = s.elements.map((e) =>
      e.kind === "textBox" ? e.text.paragraphs.map((p) => [p.bullet, p.runs.map((r) => r.text)]) : [],
    );
    assert.deepEqual(summaries, [
      [
        [false, ["見出し"]],
        [true, ["a"]],
        [true, ["b"]],
      ],
      [
        [true, ["a"]],
        [true, ["b"]],
      ],
    ]);
  });

  test("明示した空の部分の後に箇条書きの項目を続けても、空の部分の段落は残る", () => {
    const s = slide("k");
    text(s, [{ text: "見出し", breakLine: true }, { text: "" }, { text: "a", bullet: true }], 0, 0, 1, 1);
    text(s, [{ text: "", bullet: true }, { text: "b", bullet: true }], 0, 0, 1, 1);
    const summaries = s.elements.map((e) =>
      e.kind === "textBox" ? e.text.paragraphs.map((p) => [p.bullet, p.runs.map((r) => r.text)]) : [],
    );
    assert.deepEqual(summaries, [
      [
        [false, ["見出し"]],
        [false, [""]],
        [true, ["a"]],
      ],
      [
        [true, [""]],
        [true, ["b"]],
      ],
    ]);
  });

  test("最後の項目の後に、空の段落を作らない", () => {
    const s = slide("k");
    text(s, [{ text: "a", bullet: true, breakLine: true }], 0, 0, 1, 1);
    const [e] = s.elements;
    assert.ok(e?.kind === "textBox");
    assert.equal(e.text.paragraphs.length, 1);
  });

  test("明示した空の項目と空の部分は、最後にあっても先頭にあっても残る", () => {
    const s = slide("k");
    text(s, bullets(["a", ""]), 0, 0, 1, 1);
    text(s, bullets(["", "a"]), 0, 0, 1, 1);
    text(s, [{ text: "a", breakLine: true }, { text: "" }], 0, 0, 1, 1);
    const texts = s.elements.map((e) =>
      e.kind === "textBox" ? e.text.paragraphs.map((p) => p.runs.map((r) => r.text)) : [],
    );
    assert.deepEqual(texts, [
      [["a"], [""]],
      [[""], ["a"]],
      [["a"], [""]],
    ]);
  });

  test("項目の無い箇条書きと空の配列は、部品の関数の書式の空の部分を持つ段落 1 つになる", () => {
    const s = slide("k");
    text(s, [], 0, 0, 1, 1, { fontSize: 12, color: "dk2" });
    text(s, bullets([]), 0, 0, 1, 1);
    const paragraphs = s.elements.map((e) => (e.kind === "textBox" ? e.text.paragraphs : []));
    assert.deepEqual(paragraphs, [
      [{ runs: [{ text: "", fontSize: 12, bold: false, color: "dk2", link: null }], bullet: false }],
      [{ runs: [{ text: "", fontSize: 14, bold: false, color: "dk1", link: null }], bullet: false }],
    ]);
  });

  test("末尾に改行があり breakLine も持つ部分の空行の段落は、その部分の書式と bullet を持つ", () => {
    const s = slide("k");
    text(s, bullets(["a\n", "b"], { fontSize: 13 }), 0, 0, 1, 1);
    text(s, [{ text: "a\n", fontSize: 20, breakLine: true }, { text: "b", fontSize: 20 }], 0, 0, 1, 1);
    const summaries = s.elements.map((e) =>
      e.kind === "textBox" ? e.text.paragraphs.map((p) => [p.bullet, p.runs.map((r) => [r.text, r.fontSize])]) : [],
    );
    assert.deepEqual(summaries, [
      [
        [true, [["a", 13]]],
        [true, [["", 13]]],
        [true, [["b", 13]]],
      ],
      [
        [false, [["a", 20]]],
        [false, [["", 20]]],
        [false, [["b", 20]]],
      ],
    ]);
  });

  test("文字の末尾の改行で作られた段落だけを除き、その前の空行は残る", () => {
    const s = slide("k");
    text(s, "a\n\n", 0, 0, 1, 1);
    const [e] = s.elements;
    assert.ok(e?.kind === "textBox");
    assert.deepEqual(
      e.text.paragraphs.map((p) => p.runs.map((r) => r.text)),
      [["a"], [""]],
    );
  });
});

describe("段落の分け方の規則 (型 RunInput の説明の 1〜6)", () => {
  // 期待値は、段落ごとの [箇条書きか, [型 TextRun の値の文字, 文字の大きさ] の配列]
  type Expected = [boolean, [string, number][]][];
  const cases: { name: string; input: RunInput[]; expected: Expected }[] = [
    {
      name: "規則 1: breakLine が true の入力の部分の後で段落を区切る",
      input: [{ text: "a", breakLine: true }, { text: "b" }],
      expected: [[false, [["a", 14]]], [false, [["b", 14]]]],
    },
    {
      name: "規則 2: 入力の部分の文字の改行ごとに段落を区切る",
      input: [{ text: "a\nb" }],
      expected: [[false, [["a", 14]]], [false, [["b", 14]]]],
    },
    {
      name: "規則 2: breakLine の無い入力の部分の最後の改行の後の空の行は段落に入れず、次の入力の部分は新しい段落に入る",
      input: [{ text: "a\n" }, { text: "b" }],
      expected: [[false, [["a", 14]]], [false, [["b", 14]]]],
    },
    {
      name: "規則 2 と 4: breakLine を持つ入力の部分の最後の改行の後の空の行は、空行の段落になる",
      input: [{ text: "a\n", breakLine: true }, { text: "b" }],
      expected: [[false, [["a", 14]]], [false, [["", 14]]], [false, [["b", 14]]]],
    },
    {
      name: "規則 2 と 4: 文字の最初の改行の前の空の行は、空行の段落になる",
      input: [{ text: "\na" }],
      expected: [[false, [["", 14]]], [false, [["a", 14]]]],
    },
    {
      name: "規則 3: bullet が true の入力の部分は、いまの段落に行があれば、その前で段落を区切る",
      input: [{ text: "h" }, { text: "a", bullet: true }],
      expected: [[false, [["h", 14]]], [true, [["a", 14]]]],
    },
    {
      name: "規則 3 と 4: 空の行だけの段落の後に bullet が true の入力の部分が続くと、空行の段落が残る",
      input: [{ text: "" }, { text: "a", bullet: true }],
      expected: [[false, [["", 14]]], [true, [["a", 14]]]],
    },
    {
      name: "規則 4: 空の行の後に、同じ段落に空でない行が入ると、空の行の TextRun は除かれる",
      input: [{ text: "a", breakLine: true }, { text: "" }, { text: "b" }],
      expected: [[false, [["a", 14]]], [false, [["b", 14]]]],
    },
    {
      name: "規則 4: 空でない行の後に、同じ段落に入った空の行の TextRun も除かれる",
      input: [{ text: "a" }, { text: "" }],
      expected: [[false, [["a", 14]]]],
    },
    {
      name: "規則 4: 空の行が 2 つ入った空行の段落は、最初の空の行の書式を持つ",
      input: [{ text: "a", breakLine: true }, { text: "", fontSize: 30 }, { text: "", fontSize: 20 }],
      expected: [[false, [["a", 14]]], [false, [["", 30]]]],
    },
    {
      name: "規則 3 と 4: 空行の段落の書式と bullet は、空の行を持つ入力の部分のものになる",
      input: [{ text: "a\n", bullet: true, breakLine: true, fontSize: 30 }, { text: "b" }],
      expected: [[true, [["a", 30]]], [true, [["", 30]]], [false, [["b", 14]]]],
    },
    {
      name: "規則 5: 最後の入力の部分の breakLine で作られた段落は除く",
      input: [{ text: "a", breakLine: true }],
      expected: [[false, [["a", 14]]]],
    },
    {
      name: "規則 6: 入力の部分の配列が空なら、部品の関数の書式の、文字が空の TextRun を持つ段落が 1 つできる",
      input: [],
      expected: [[false, [["", 14]]]],
    },
    {
      name: "空行の入れ方: 前の入力の部分と文字が空の入力の部分の両方に breakLine を付けると、空行の段落になる",
      input: [{ text: "a", breakLine: true }, { text: "", breakLine: true }, { text: "b" }],
      expected: [[false, [["a", 14]]], [false, [["", 14]]], [false, [["b", 14]]]],
    },
    {
      name: "空行の入れ方: 文字が空の入力の部分が前の入力の部分と同じ段落に入ると、breakLine を付けても空行の段落にならない",
      input: [{ text: "a" }, { text: "", breakLine: true }, { text: "b" }],
      expected: [[false, [["a", 14]]], [false, [["b", 14]]]],
    },
  ];
  for (const c of cases) {
    test(c.name, () => {
      const s = slide("k");
      text(s, c.input, 0, 0, 1, 1);
      const [e] = s.elements;
      assert.ok(e?.kind === "textBox");
      assert.deepEqual(
        e.text.paragraphs.map((p) => [p.bullet, p.runs.map((r) => [r.text, r.fontSize])]),
        c.expected,
      );
    });
  }

  test("部品の関数に渡した文字列は、1 つの入力の部分として扱う", () => {
    const s = slide("k");
    text(s, "a\nb", 0, 0, 1, 1);
    text(s, [{ text: "a\nb" }], 0, 0, 1, 1);
    const [fromString, fromArray] = s.elements;
    assert.ok(fromString?.kind === "textBox" && fromArray?.kind === "textBox");
    assert.deepEqual(fromString.text.paragraphs, fromArray.text.paragraphs);
  });
});

describe("関数 card", () => {
  test("背景のカードは、文字と枠線の無い、角の丸い四角になる", () => {
    const s = slide("k");
    card(s, 0.5, 1.45, 4.3, 2.95);
    assert.deepEqual(s.elements, [
      {
        kind: "shape",
        shape: "roundRect",
        radius: 0.1,
        x: 0.5,
        y: 1.45,
        w: 4.3,
        h: 2.95,
        fill: { color: "lt2", transparency: 0 },
        outline: null,
        text: null,
        name: null,
      },
    ]);
  });
});

describe("図の要素の順序", () => {
  test("1 枚のスライドに要素を足した順序が、データの順序 (重なりの順序) になる", () => {
    const s = slide("k");
    card(s, 0, 0, 4, 2);
    box(s, 0.2, 0.2, 1, 0.5, "a");
    arrow(s, 1.2, 0.45, 2, 0.45);
    badge(s, 1, 2, 0.2, 0.5);
    text(s, "b", 0.2, 1, 3, 0.5);
    assert.deepEqual(
      s.elements.map((e) => (e.kind === "shape" ? e.shape : e.kind)),
      ["roundRect", "roundRect", "line", "ellipse", "textBox"],
    );
  });

  test("資料ごとのスクリプトの関数は、部品の関数の集まりを受け取り、テーマとキーごとの図を返す", () => {
    const deck: DeckScript = (p) => {
      const a = p.slide("a");
      p.box(a, 0, 0, 1, 1, "a");
      const b = p.slide("b");
      p.arrow(b, 0, 0, 1, 1);
      return { theme: THEME, slides: [a, b] };
    };
    const result = deck(parts);
    assert.equal(result.theme, THEME);
    assert.deepEqual(
      result.slides.map((f) => [f.key, f.elements.length]),
      [
        ["a", 1],
        ["b", 1],
      ],
    );
  });
});

describe("テーマ", () => {
  test("12 色の名前と値の対応を返す", () => {
    assert.deepEqual(schemeColorValues(THEME), {
      dk1: "1F2933",
      lt1: "FFFFFF",
      dk2: "52606D",
      lt2: "F2F4F7",
      hlink: "0F6E8C",
      folHlink: "6B4F9E",
      accent1: "0F8B8D",
      accent2: "7B8794",
      accent3: "D9480F",
      accent4: "2F9E44",
      accent5: "F0A202",
      accent6: "1C3D5A",
    });
  });

  test("正しいテーマには、誤りが無い", () => {
    assert.deepEqual(checkTheme(THEME), []);
  });

  test("16 進数 6 桁でない色の値と、空の意味を、すべて誤りにする", () => {
    const theme: Theme = {
      ...THEME,
      colors: { ...THEME.colors, dk1: "#1F2933" },
      accents: { ...THEME.accents, accent3: { color: "D948", meaning: "" } },
    };
    assert.deepEqual(checkTheme(theme), [
      'テーマの色 dk1 の値 "#1F2933" が、16 進数 6 桁 (例: "0F8B8D") ではない',
      'テーマの色 accent3 の値 "D948" が、16 進数 6 桁 (例: "0F8B8D") ではない',
      "テーマの色 accent3 の meaning が空",
    ]);
  });

  test("アクセント色が 6 つ揃っていないテーマは、型エラーになる (型の検査で確認する)", () => {
    // tsconfig.json の設定で、テーマを書いた一時的なファイルを型の検査にかける。
    // 揃っているテーマで誤りが出ないことも確認し、型エラーの原因がアクセント色の不足だけであることを示す
    const dir = mkdtempSync(join(tmpdir(), "slide-deck-theme-"));
    try {
      const index = JSON.stringify(join(PLUGIN_DIR, "src", "index.ts"));
      const accents = (n: number): string =>
        Array.from({ length: n }, (_, i) => `accent${String(i + 1)}: { color: "0F8B8D", meaning: "m" },`).join("\n");
      const source = (n: number): string => `import type { Theme } from ${index};
export const theme: Theme = {
  name: "T",
  fonts: { heading: "F", body: "F" },
  colors: { dk1: "000000", lt1: "FFFFFF", dk2: "333333", lt2: "EEEEEE", hlink: "0000FF", folHlink: "800080" },
  accents: {
${accents(n)}
  },
};
`;
      const complete = join(dir, "complete.ts");
      const missing = join(dir, "missing.ts");
      writeFileSync(complete, source(6));
      writeFileSync(missing, source(5));

      const configPath = join(PLUGIN_DIR, "tsconfig.json");
      const config = ts.readConfigFile(configPath, (p) => ts.sys.readFile(p));
      const parsed = ts.parseJsonConfigFileContent(config.config, ts.sys, PLUGIN_DIR, undefined, configPath);
      const program = ts.createProgram([complete, missing], parsed.options);
      const messages = (file: string): string[] =>
        ts
          .getPreEmitDiagnostics(program, program.getSourceFile(file))
          .map((d) => ts.flattenDiagnosticMessageText(d.messageText, "\n"));

      assert.deepEqual(messages(complete), []);
      const errors = messages(missing);
      assert.equal(errors.length, 1, errors.join("\n"));
      assert.match(errors[0] ?? "", /accent6/);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
