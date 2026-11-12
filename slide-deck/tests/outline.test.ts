import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, test } from "node:test";
import { fileURLToPath } from "node:url";
import {
  formatOutlineError,
  parseOutline,
  type DeckOutline,
  type OutlineError,
} from "../src/outline/parse.ts";
import { hasMismatch, matchKeys } from "../src/outline/match.ts";
import { writeGoogleSlidesUrl, writePluginVersion, type WriteInfoResult } from "../src/outline/url.ts";
import { parts } from "../src/data/parts.ts";
import { checkTheme } from "../src/data/theme.ts";
import sampleDeck from "../examples/sample/deck.ts";

const PLUGIN_DIR = join(dirname(fileURLToPath(import.meta.url)), "..");
const FIXTURES = join(PLUGIN_DIR, "tests", "fixtures", "outline");
const SAMPLE_DIR = join(PLUGIN_DIR, "examples", "sample");

function fixture(name: string): string {
  return readFileSync(join(FIXTURES, name), "utf8");
}

/** 誤りが無いことを確認して、読み込んだ構成案を返す。 */
function parseOk(text: string): DeckOutline {
  const r = parseOutline(text);
  if (!r.ok) assert.fail(`誤りが無いはずの構成案に誤りがある:\n${r.errors.map(formatOutlineError).join("\n")}`);
  return r.outline;
}

/** 誤りがあることを確認して、誤りの配列を返す。 */
function parseErrors(text: string): OutlineError[] {
  const r = parseOutline(text);
  if (r.ok) assert.fail("誤りがあるはずの構成案が、誤り無しで読み込まれた");
  return r.errors;
}

/** 資料の情報の 3 つの必須の項目と、題名の行。スライドの部分を後に続けて、テストの構成案を作る。 */
const HEADER = ["# 題名", "", "- 読者: 開発者", "- ねらい: 確認する", "- 形: 図を中心にする", ""];

function outlineOf(...body: string[]): string {
  return [...HEADER, ...body].join("\n") + "\n";
}

describe("関数 parseOutline", () => {
  test("見本の構成案から、資料の情報・キーの順序・題名・一言・ノートが取り出せる", () => {
    const outline = parseOk(readFileSync(join(SAMPLE_DIR, "outline.md"), "utf8"));
    assert.equal(outline.title, "キャッシュのしくみ");
    assert.deepEqual(outline.info, {
      audience: "キャッシュを使ったことが少ない開発者",
      purpose: "キャッシュが速くなる理由と、古い値が残る問題と、その対処を理解してもらう",
      form: "図を中心にし、1 枚の文は 1〜2 文まで",
      properNouns: "一般化する",
      googleSlides: null,
      pluginVersion: null,
    });
    assert.deepEqual(
      outline.slides.map((s) => s.key),
      ["read-path", "hit-miss", "stale", "expire"],
    );
    const readPath = outline.slides[0];
    assert.ok(readPath);
    assert.equal(readPath.title, "読み出しの流れ");
    assert.equal(readPath.takeaway, "2 回目からは、DB まで読みに行かずに済む");
    assert.equal(readPath.chapter, "1. 読み出し");
    assert.equal(readPath.proposed, false);
    assert.equal(readPath.line, 10);
    assert.equal(
      readPath.notes,
      "アプリケーションは、まずキャッシュに値を問い合わせます。\n" +
        "キャッシュに値が無いときだけ、DB から読みます。\n\n" +
        "DB から読んだ値はキャッシュに残すので、同じ値を続けて読むときは DB に問い合わせません。",
    );
    assert.equal(outline.slides[2]?.notes, "", "ノートの無いスライドのノートは空の文字列");
    assert.deepEqual(outline.proposals, []);
  });

  test("ノートが複数の段落のとき、段落の区切りを保って取り出す", () => {
    const outline = parseOk(fixture("notes.md"));
    const [paragraphs, noNotes] = outline.slides;
    assert.ok(paragraphs && noNotes);
    // 段落の中の改行は残し、段落の間は空行がいくつあっても空行 1 つにする。前後の空行は除く
    assert.equal(
      paragraphs.notes,
      "1 つ目の段落の 1 行目。\n1 つ目の段落の 2 行目。\n\n2 つ目の段落。\n\n3 つ目の段落。",
    );
    assert.equal(noNotes.notes, "");
    // 字下げした行は、図の説明に含まれる
    assert.equal(paragraphs.figure, "箱を 2 つ並べる\n  - 左: 1 つ目の箱\n  - 右: 2 つ目の箱");
    assert.equal(paragraphs.chapter, null, "章の外のスライドの章は null");
  });

  test("改行が CRLF でも、同じ値を取り出す", () => {
    const lf = fixture("notes.md");
    const crlf = parseOk(lf.replaceAll("\n", "\r\n"));
    assert.deepEqual(crlf, parseOk(lf));
  });

  test("同じキーが 2 回あると、2 つの行番号を示す誤りになる", () => {
    const errors = parseErrors(
      outlineOf("### same: 1 つ目", "- 図: 箱", "- 一言: 一言", "", "### same: 2 つ目", "- 図: 箱", "- 一言: 一言"),
    );
    assert.deepEqual(errors, [
      { line: 11, message: "キー same が 7 行目と 11 行目にある。キーは資料の中で 1 つにする" },
    ]);
  });

  for (const [name, key] of [
    ["大文字", "Upper"],
    ["空白", "has space"],
    ["33 文字", "abcdefghijklmnopqrstuvwxyz-012345"],
  ] as const) {
    test(`キーに${name}があると誤りになる`, () => {
      const errors = parseErrors(outlineOf(`### ${key}: 題名`, "- 図: 箱", "- 一言: 一言"));
      assert.deepEqual(errors, [
        {
          line: 7,
          message: `キー ${JSON.stringify(key)} は使えない。キーは英小文字・数字・ハイフンの 1〜32 文字にする`,
        },
      ]);
    });
  }

  test("32 文字のキーは使える", () => {
    const key = "abcdefghijklmnopqrstuvwxyz-01234";
    const outline = parseOk(outlineOf(`### ${key}: 題名`, "- 図: 箱", "- 一言: 一言"));
    assert.equal(outline.slides[0]?.key, key);
  });

  test("- 一言: の行が無いスライドは誤りになる", () => {
    const errors = parseErrors(outlineOf("### no-takeaway: 題名", "- 図: 箱"));
    assert.deepEqual(errors, [{ line: 7, message: "スライドに - 一言: の行が無い" }]);
  });

  test("- 図: の行が無いスライドは誤りになる", () => {
    const errors = parseErrors(outlineOf("### no-figure: 題名", "- 一言: 一言"));
    assert.deepEqual(errors, [{ line: 7, message: "スライドに - 図: の行が無い" }]);
  });

  test("- 図: と - 一言: 以外の項目・2 回目の - 図:・字下げした一言の 2 行目は誤りになる", () => {
    const errors = parseErrors(
      outlineOf(
        "### items: 題名",
        "- 図: 箱",
        "- 図: もう 1 つの箱",
        "- 一言: 一言",
        "  一言の 2 行目",
        "- 補足: 補足",
      ),
    );
    assert.deepEqual(
      errors.map((e) => e.line),
      [9, 11, 12],
    );
  });

  test("箇条書きの直後に空行を入れずにノートを書くと誤りになる", () => {
    const errors = parseErrors(outlineOf("### no-blank: 題名", "- 図: 箱", "- 一言: 一言", "ノート"));
    assert.deepEqual(errors, [{ line: 10, message: "発表者ノートの前に、空行を入れる" }]);
  });

  test("【提案】が付いたスライドは、一覧として返る", () => {
    const outline = parseOk(fixture("proposals.md"));
    assert.deepEqual(
      outline.proposals.map((s) => [s.key, s.title, s.line]),
      [
        ["extra", "提案のスライド", 11],
        ["more", "もう 1 つの提案のスライド", 15],
      ],
    );
    assert.deepEqual(
      outline.slides.map((s) => [s.key, s.proposed]),
      [
        ["requested", false],
        ["extra", true],
        ["more", true],
      ],
    );
  });

  test("固有名の項目が「一般化する」「そのまま書く」以外の値なら誤りになる", () => {
    const errors = parseErrors(
      [...HEADER.slice(0, 5), "- 固有名: ぼかす", "", "### a: 題名", "- 図: 箱", "- 一言: 一言"].join("\n"),
    );
    assert.deepEqual(errors, [
      { line: 6, message: '固有名の値 "ぼかす" は使えない。「一般化する」か「そのまま書く」にする' },
    ]);
    for (const value of ["一般化する", "そのまま書く"] as const) {
      const outline = parseOk(
        [...HEADER.slice(0, 5), `- 固有名: ${value}`, "", "### a: 題名", "- 図: 箱", "- 一言: 一言"].join("\n"),
      );
      assert.equal(outline.info.properNouns, value);
    }
  });

  test("Google スライドの URL から資料の ID を取り出し、形の違う URL は誤りになる", () => {
    const withUrl = (url: string): string =>
      [...HEADER.slice(0, 5), `- Google スライド: ${url}`, "", "### a: 題名", "- 図: 箱", "- 一言: 一言"].join("\n");
    const url = "https://docs.google.com/presentation/d/1AbC_dEf-123/edit";
    assert.deepEqual(parseOk(withUrl(url)).info.googleSlides, { url, presentationId: "1AbC_dEf-123" });
    const errors = parseErrors(withUrl("https://example.com/presentation/d/1AbC"));
    assert.deepEqual(
      errors.map((e) => e.line),
      [6],
    );
  });

  test("slide-deck の版が 数.数.数 の形でなければ誤りになる", () => {
    const withVersion = (v: string): string =>
      [...HEADER.slice(0, 5), `- slide-deck の版: ${v}`, "", "### a: 題名", "- 図: 箱", "- 一言: 一言"].join("\n");
    assert.equal(parseOk(withVersion("0.1.0")).info.pluginVersion, "0.1.0");
    assert.deepEqual(parseErrors(withVersion("v0.1")), [
      { line: 6, message: 'slide-deck の版の値 "v0.1" が、数.数.数 (例: 0.1.0) の形ではない' },
    ]);
  });

  test("誤りのある構成案で、すべての誤りが行番号付きで 1 回で報告される", () => {
    const errors = parseErrors(fixture("errors.md"));
    assert.deepEqual(errors, [
      { line: 1, message: "資料の情報に、項目 形 の行が無い" },
      { line: 4, message: "資料の情報の項目 ねらい の値が空" },
      { line: 5, message: '固有名の値 "ぼかす" は使えない。「一般化する」か「そのまま書く」にする' },
      {
        line: 6,
        message:
          '資料の情報の項目 "作者" は使えない。使える項目は 読者・ねらい・形・固有名・Google スライド・slide-deck の版',
      },
      { line: 10, message: 'キー "Upper" は使えない。キーは英小文字・数字・ハイフンの 1〜32 文字にする' },
      { line: 14, message: 'キー "has space" は使えない。キーは英小文字・数字・ハイフンの 1〜32 文字にする' },
      {
        line: 18,
        message:
          'キー "abcdefghijklmnopqrstuvwxyz-012345" は使えない。キーは英小文字・数字・ハイフンの 1〜32 文字にする',
      },
      { line: 26, message: "キー same が 22 行目と 26 行目にある。キーは資料の中で 1 つにする" },
      { line: 30, message: "スライドに - 一言: の行が無い" },
      {
        line: 32,
        message: "スライドの見出しの下の項目は、- 図: と - 一言: だけにする。補足は発表者ノートに書く",
      },
      { line: 34, message: "章にスライドが 1 枚も無い" },
      {
        line: 42,
        message: "発表者ノートに、- で始まる行は書けない。図の説明は、- 図: の行の後の字下げした行に書く",
      },
      { line: 44, message: "区切りの線 (---) は書けない" },
    ]);
  });

  test("題名の行が無く、スライドが 1 枚も無い構成案は、その 2 つを誤りにする", () => {
    const errors = parseErrors("- 読者: 開発者\n- ねらい: 確認する\n- 形: 図\n");
    assert.deepEqual(errors, [
      { line: 1, message: "最初の行は、題名の行 (# <資料の題名>) にする" },
      { line: 4, message: "スライドの見出し (### <キー>: <題名>) が 1 つも無い" },
    ]);
  });

  test("#### 以下の見出しと、2 つ目の題名の行は誤りになる", () => {
    const errors = parseErrors(outlineOf("# 2 つ目の題名", "### a: 題名", "- 図: 箱", "- 一言: 一言", "#### 小見出し"));
    assert.deepEqual(
      errors.map((e) => [e.line, e.message]),
      [
        [7, "題名の行 (# <資料の題名>) は 1 つだけにする"],
        [11, "見出しは #・##・### だけにする"],
      ],
    );
  });
});

describe("関数 matchKeys", () => {
  test("構成案にだけあるキーと、資料ごとのスクリプトにだけあるキーが、別々の一覧になる", () => {
    const m = matchKeys(["intro", "flow", "summary", "extra"], ["flow", "intro", "detail", "summary", "more"]);
    assert.deepEqual(m, { outlineOnly: ["extra"], deckOnly: ["detail", "more"], deckDuplicates: [] });
    assert.equal(hasMismatch(m), true);
  });

  test("資料ごとのスクリプトで同じキーの図を 2 回作ると、重複の一覧に 1 回だけ入る", () => {
    const m = matchKeys(["a", "b"], ["a", "b", "a", "a"]);
    assert.deepEqual(m, { outlineOnly: [], deckOnly: [], deckDuplicates: ["a"] });
    assert.equal(hasMismatch(m), true);
  });

  test("キーが一致すれば、どの一覧も空になる。順序の違いは不一致にしない", () => {
    const m = matchKeys(["a", "b", "c"], ["c", "a", "b"]);
    assert.deepEqual(m, { outlineOnly: [], deckOnly: [], deckDuplicates: [] });
    assert.equal(hasMismatch(m), false);
  });
});

/** 書き込みが成功したことを確認して、書き込んだテキストを返す。 */
function written(r: WriteInfoResult): string {
  if (!r.ok) assert.fail(`書き込みが成功するはずが、誤りになった:\n${r.errors.join("\n")}`);
  return r.text;
}

/** テキストの行の配列の、位置 index に行 line を挿入したテキストを返す (改行は \n)。 */
function insertLine(text: string, index: number, line: string): string {
  const lines = text.split("\n");
  lines.splice(index, 0, line);
  return lines.join("\n");
}

const NEW_URL = "https://docs.google.com/presentation/d/new-id/edit";

describe("関数 writeGoogleSlidesUrl と writePluginVersion", () => {
  test("Google スライドの URL の行が無い構成案に URL を書き込むと、資料の情報の最後に 1 行が足され、ほかの行は変わらない", () => {
    const before = fixture("no-url.md");
    const after = written(writeGoogleSlidesUrl(before, NEW_URL));
    // 資料の情報の最後の行 (6 行目の固有名) の次に足す
    assert.equal(after, insertLine(before, 6, `- Google スライド: ${NEW_URL}`));
    assert.deepEqual(parseOk(after).info.googleSlides, { url: NEW_URL, presentationId: "new-id" });
  });

  test("Google スライドの URL の行が既にあれば、その行だけが置き換わる", () => {
    const before = fixture("with-url.md");
    const after = written(writeGoogleSlidesUrl(before, NEW_URL));
    const lines = before.split("\n");
    lines[3] = `- Google スライド: ${NEW_URL}`;
    assert.equal(after, lines.join("\n"));
  });

  test("slide-deck の版の行も、無ければ資料の情報の最後に足し、あれば置き換える", () => {
    const noVersion = fixture("no-url.md");
    assert.equal(written(writePluginVersion(noVersion, "0.2.0")), insertLine(noVersion, 6, "- slide-deck の版: 0.2.0"));
    const withVersion = fixture("with-url.md");
    const lines = withVersion.split("\n");
    lines[5] = "- slide-deck の版: 0.2.0";
    assert.equal(written(writePluginVersion(withVersion, "0.2.0")), lines.join("\n"));
  });

  test("URL と版を続けて書き込むと、資料の情報の最後に、書き込んだ順に並ぶ", () => {
    const before = fixture("no-url.md");
    const after = written(writePluginVersion(written(writeGoogleSlidesUrl(before, NEW_URL)), "0.2.0"));
    assert.equal(after, insertLine(insertLine(before, 6, `- Google スライド: ${NEW_URL}`), 7, "- slide-deck の版: 0.2.0"));
  });

  test("改行が CRLF の構成案と、最後に改行の無い構成案は、その形のまま書き込む", () => {
    const lf = fixture("no-url.md");
    const expected = insertLine(lf, 6, `- Google スライド: ${NEW_URL}`);
    const crlf = lf.replaceAll("\n", "\r\n");
    assert.equal(written(writeGoogleSlidesUrl(crlf, NEW_URL)), expected.replaceAll("\n", "\r\n"));
    // 資料の情報の最後の行が、ファイルの最後の行で、改行が無い
    const headerOnly = ["# 題名", "", "- 読者: 開発者", "- ねらい: 確認する", "- 形: 図"].join("\n");
    assert.equal(written(writeGoogleSlidesUrl(headerOnly, NEW_URL)), `${headerOnly}\n- Google スライド: ${NEW_URL}`);
    assert.equal(
      written(writeGoogleSlidesUrl(headerOnly.replaceAll("\n", "\r\n"), NEW_URL)),
      `${headerOnly.replaceAll("\n", "\r\n")}\r\n- Google スライド: ${NEW_URL}`,
    );
  });

  test("スライドの部分に誤りがあっても書き込み、資料の情報に誤りがあれば書き込まない", () => {
    const slideError = fixture("no-url.md").replace("### first: 1 枚目", "### First: 1 枚目");
    assert.equal(parseOutline(slideError).ok, false);
    assert.equal(
      written(writeGoogleSlidesUrl(slideError, NEW_URL)),
      insertLine(slideError, 6, `- Google スライド: ${NEW_URL}`),
    );
    const headerError = fixture("no-url.md").replace("- 形: 図を中心にする\n", "");
    assert.deepEqual(writeGoogleSlidesUrl(headerError, NEW_URL), {
      ok: false,
      errors: ["1 行目: 資料の情報に、項目 形 の行が無い"],
    });
  });

  test("書き込む値の形が違えば、誤りになる", () => {
    const before = fixture("no-url.md");
    assert.deepEqual(writeGoogleSlidesUrl(before, "https://example.com/d/x"), {
      ok: false,
      errors: [
        'Google スライドの値 "https://example.com/d/x" が、https://docs.google.com/presentation/d/<資料の ID> で始まる URL ではない',
      ],
    });
    assert.deepEqual(writePluginVersion(before, "1.0"), {
      ok: false,
      errors: ['slide-deck の版の値 "1.0" が、数.数.数 (例: 0.1.0) の形ではない'],
    });
  });
});

describe("見本の資料", () => {
  test("見本の資料の構成案と資料ごとのスクリプトのキーが一致する", () => {
    const outline = parseOk(readFileSync(join(SAMPLE_DIR, "outline.md"), "utf8"));
    const result = sampleDeck(parts);
    const m = matchKeys(
      outline.slides.map((s) => s.key),
      result.slides.map((s) => s.key),
    );
    assert.deepEqual(m, { outlineOnly: [], deckOnly: [], deckDuplicates: [] });
    assert.deepEqual(checkTheme(result.theme), []);
  });

  test("見本の資料ごとのスクリプトは、部品の関数をすべて使い、6 つの形をすべて使う", () => {
    const used = new Set<string>();
    const tracked = Object.fromEntries(
      Object.entries(parts).map(([name, fn]) => [
        name,
        (...args: unknown[]): unknown => {
          used.add(name);
          return (fn as (...a: unknown[]) => unknown)(...args);
        },
      ]),
    ) as unknown as typeof parts;
    const result = sampleDeck(tracked);
    assert.deepEqual([...used].sort(), Object.keys(parts).sort());
    const shapes = new Set(
      result.slides.flatMap((s) => s.elements.flatMap((e) => (e.kind === "shape" ? [e.shape] : []))),
    );
    assert.deepEqual([...shapes].sort(), ["can", "chevron", "ellipse", "homePlate", "rect", "roundRect"]);
  });
});
