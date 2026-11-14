// Google スライドの指示の作成 (ディレクトリ src/gslides/) のテスト (計画の U6 の Test scenarios)。
// 見本の資料の 3 つの場面 (作る・作り直す・途中からの再開) の指示の配列は、ディレクトリ tests/fixtures/gslides/ の期待のファイルと比べる。

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, test } from "node:test";
import { fileURLToPath } from "node:url";
import sampleDeck from "../examples/sample/deck.ts";
import { assembleDeck } from "../src/check/deck.ts";
import { arrow, badge, box, bullets, parts, slide, text } from "../src/data/parts.ts";
import { schemeColorValues, type Theme } from "../src/data/theme.ts";
import type { Deck, Slide, SlideElement } from "../src/data/types.ts";
import { notesChanges, notesRequestFiles } from "../src/gslides/notes.ts";
import { parseSlideObjectId, PlanError, planSlides, type SlidePlan, slideHash, slideObjectId } from "../src/gslides/plan.ts";
import {
  type Presentation,
  type PresentationMaster,
  parsePresentation,
  type RgbColor,
} from "../src/gslides/presentation.ts";
import {
  colorSchemeRequests,
  MAX_FILE_CHARS,
  MAX_OBJECTS_PER_SLIDE,
  type Request,
  slideRequestFiles,
  slideRequests,
} from "../src/gslides/requests.ts";
import { parseOutline } from "../src/outline/parse.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const SAMPLE_DIR = join(HERE, "..", "examples", "sample");
const FIXTURES = join(HERE, "fixtures", "gslides");
const EMU_PER_INCH = 914_400;
const BASE = 3_000_000;

/** 見本の資料のスライドのデータ */
function sample(): Deck {
  const r = parseOutline(readFileSync(join(SAMPLE_DIR, "outline.md"), "utf8"));
  if (!r.ok) assert.fail("見本の資料の構成案に誤りがある");
  return assembleDeck(r.outline, sampleDeck(parts));
}

/** スライドのデータの、いまの ID */
function idOf(s: Slide, theme: Theme): string {
  return slideObjectId(s.key, slideHash(s, theme.fonts));
}

/** 新しい資料のマスターの配色 (U11 の確認で読んだ値) */
const DEFAULT_COLORS: ReadonlyMap<string, RgbColor> = new Map([
  ["DARK1", { red: 0, green: 0, blue: 0 }],
  ["LIGHT1", { red: 1, green: 1, blue: 1 }],
  ["DARK2", { red: 0.34901962, green: 0.34901962, blue: 0.34901962 }],
  ["LIGHT2", { red: 0.93333334, green: 0.93333334, blue: 0.93333334 }],
  ["ACCENT1", { red: 0.25882354, green: 0.52156866, blue: 0.95686275 }],
  ["ACCENT2", { red: 0.12941177, green: 0.12941177, blue: 0.12941177 }],
  ["ACCENT3", { red: 0.47058824, green: 0.5647059, blue: 0.6117647 }],
  ["ACCENT4", { red: 1, green: 0.67058825, blue: 0.2509804 }],
  ["ACCENT5", { red: 0, green: 0.5921569, blue: 0.654902 }],
  ["ACCENT6", { red: 0.93333334, green: 1, blue: 0.25490198 }],
  ["HYPERLINK", { red: 0, green: 0.5921569, blue: 0.654902 }],
  ["FOLLOWED_HYPERLINK", { red: 0, green: 0.5921569, blue: 0.654902 }],
]);

/** テーマの 12 色を、読み込んだ配色の形にする。読み込んだ値のように、小数の最後の桁を少しずらす */
function themeColors(theme: Theme): Map<string, RgbColor> {
  const types: Record<string, string> = {
    dk1: "DARK1",
    lt1: "LIGHT1",
    dk2: "DARK2",
    lt2: "LIGHT2",
    accent1: "ACCENT1",
    accent2: "ACCENT2",
    accent3: "ACCENT3",
    accent4: "ACCENT4",
    accent5: "ACCENT5",
    accent6: "ACCENT6",
    hlink: "HYPERLINK",
    folHlink: "FOLLOWED_HYPERLINK",
  };
  const colors = new Map<string, RgbColor>();
  for (const [name, hex] of Object.entries(schemeColorValues(theme))) {
    const n = parseInt(hex, 16);
    const c = (v: number): number => Math.min(1, v / 255 + 1e-8);
    colors.set(types[name] ?? "", { red: c((n >> 16) & 255), green: c((n >> 8) & 255), blue: c(n & 255) });
  }
  return colors;
}

/** 読み込んだスライド。notes は欄の文 (null は空の欄) */
interface SlideSpec {
  id: string;
  notes?: string | null;
}

function presentation(slides: readonly SlideSpec[], colors: ReadonlyMap<string, RgbColor> = DEFAULT_COLORS): Presentation {
  const master: PresentationMaster = { objectId: "simple-light-2", colors };
  return {
    revisionId: "rev",
    masters: [master],
    slides: slides.map((s, i) => ({ objectId: s.id, notesObjectId: `n${String(i)}`, notesText: s.notes ?? null })),
  };
}

/** 見本の資料を、いまの内容のまま全部作り終え、ノートも入れた資料 */
function published(deck: Deck): Presentation {
  return presentation(
    deck.slides.map((s) => ({ id: idOf(s, deck.theme), notes: s.notes === "" ? null : `${s.notes}\n` })),
    themeColors(deck.theme),
  );
}

function plan(deck: Deck, p: Presentation, recreateAll = false): SlidePlan {
  return planSlides(deck.slides, deck.theme.fonts, p, recreateAll);
}

function actions(p: SlidePlan): Record<string, string> {
  return Object.fromEntries(p.keys.map((k) => [k.key, k.action]));
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null;
}

/** 指示の配列のうち、名前の指示だけを取り出す */
function ofKind(reqs: readonly Request[], kind: string): Record<string, unknown>[] {
  return reqs.flatMap((r) => {
    const body = r[kind];
    return isRecord(body) ? [body] : [];
  });
}

/** 1 つの要素だけの、キー k のスライド */
function oneElement(k: string, add: (s: ReturnType<typeof slide>) => void): Slide {
  const fig = slide(k);
  add(fig);
  return { key: k, title: "題名", takeaway: "一言", notes: "", elements: fig.elements };
}

const FONTS = { heading: "Heading", body: "Body" };

/** スライドを作る指示 */
function requestsOf(s: Slide): Request[] {
  return slideRequests(s, `sd_${s.key}_0123456789`, 0, FONTS);
}

interface Transform {
  scaleX: number;
  scaleY: number;
  translateX: number;
  translateY: number;
}
interface Geometry {
  size: { width: { magnitude: number }; height: { magnitude: number } };
  transform: Transform;
}

/** createShape か createLine の位置と大きさ */
function geometry(body: Record<string, unknown>): Geometry {
  return body["elementProperties"] as Geometry;
}

/** 位置と大きさを、インチに戻す */
function inches(g: Geometry): { x: number; y: number; w: number; h: number } {
  const w = (g.size.width.magnitude * g.transform.scaleX) / EMU_PER_INCH;
  const h = (g.size.height.magnitude * g.transform.scaleY) / EMU_PER_INCH;
  return { x: g.transform.translateX / EMU_PER_INCH, y: g.transform.translateY / EMU_PER_INCH, w, h };
}

function near(actual: number, expected: number, message?: string): void {
  assert.ok(Math.abs(actual - expected) < 1e-6, `${message ?? ""} ${String(actual)} ≠ ${String(expected)}`);
}

/** 図の要素 (題名と一言の後ろの、図の 1 つ目の要素) の指示の ID の番号。題名が 0 なので、図の要素は 1 から */
const FIRST = "sd_k_0123456789_1";

describe("要素の指示", () => {
  test("円の中の文字は、図形と、その上に重ねた文字の箱の 2 つになり、文字の箱は余白の分だけ広がる", () => {
    const s = oneElement("k", (f) => {
      box(f, 1, 1, 2, 1, "円", { shape: "ellipse", margin: 6 });
    });
    const reqs = requestsOf(s);
    const shapes = ofKind(reqs, "createShape").filter((c) => c["objectId"] !== "sd_k_0123456789_0");
    assert.deepEqual(
      shapes.map((c) => [c["objectId"], c["shapeType"]]),
      [
        [FIRST, "ELLIPSE"],
        ["sd_k_0123456789_2", "TEXT_BOX"],
        ["sd_k_0123456789_3", "TEXT_BOX"],
      ],
    );
    const [ellipse, overlay] = shapes;
    if (ellipse === undefined || overlay === undefined) assert.fail();
    const r = inches(geometry(ellipse));
    near(r.w, 2);
    // 余白 6 ポイントだけ狭め、Google スライドの余白 (左右 0.1・上下 0.05 インチ) だけ広げる
    const o = inches(geometry(overlay));
    near(o.x, 1 + 6 / 72 - 0.1);
    near(o.y, 1 + 6 / 72 - 0.05);
    near(o.w, 2 - 12 / 72 + 0.2);
    near(o.h, 1 - 12 / 72 + 0.1);
    // 文字は、図形ではなく重ねた文字の箱に入る
    const inserts = ofKind(reqs, "insertText").map((i) => i["objectId"]);
    assert.ok(inserts.includes("sd_k_0123456789_2"));
    assert.ok(!inserts.includes(FIRST));
  });

  test("余白 0 の文字の箱は、Google スライドの余白の分だけ広がる", () => {
    const s = oneElement("k", (f) => {
      text(f, "文字", 1, 1, 3, 0.5);
    });
    const created = ofKind(requestsOf(s), "createShape").find((c) => c["objectId"] === FIRST);
    if (created === undefined) assert.fail();
    const r = inches(geometry(created));
    near(r.x, 0.9);
    near(r.y, 0.95);
    near(r.w, 3.2);
    near(r.h, 0.6);
  });

  test("幅と高さのどちらも 1 インチより大きい角の丸い四角は四角になり、どちらかが 1 インチ以下なら角の丸い四角のまま", () => {
    const big = ofKind(requestsOf(oneElement("k", (f) => { box(f, 0, 0, 1.5, 1.2, "大"); })), "createShape");
    assert.equal(big.find((c) => c["objectId"] === FIRST)?.["shapeType"], "RECTANGLE");
    const small = ofKind(requestsOf(oneElement("k", (f) => { box(f, 0, 0, 3, 1, "小"); })), "createShape");
    assert.equal(small.find((c) => c["objectId"] === FIRST)?.["shapeType"], "ROUND_RECTANGLE");
  });

  test("右から左への線は scaleX が負になり、始点は右の端になる。下から上は scaleY が負になる", () => {
    const left = ofKind(requestsOf(oneElement("k", (f) => { arrow(f, 3, 1, 1, 2); })), "createLine")[0];
    if (left === undefined) assert.fail();
    const g = geometry(left);
    assert.ok(g.transform.scaleX < 0);
    assert.ok(g.transform.scaleY > 0);
    near(g.transform.translateX / EMU_PER_INCH, 3);
    near(inches(g).w, -2);
    const up = ofKind(requestsOf(oneElement("k", (f) => { arrow(f, 1, 2, 2, 1); })), "createLine")[0];
    if (up === undefined) assert.fail();
    assert.ok(geometry(up).transform.scaleY < 0);
    near(geometry(up).transform.translateY / EMU_PER_INCH, 2);
  });

  test("縦の線は、幅の軸だけ大きさ 0・拡大率 1 になり、高さの軸は基準の大きさと拡大率で表す", () => {
    const line = ofKind(requestsOf(oneElement("k", (f) => { arrow(f, 1, 1, 1, 3); })), "createLine")[0];
    if (line === undefined) assert.fail();
    const g = geometry(line);
    assert.equal(g.size.width.magnitude, 0);
    assert.equal(g.transform.scaleX, 1);
    assert.equal(g.size.height.magnitude, BASE);
    near(inches(g).h, 2);
  });

  test("createLine は、lineCategory ではなく category を使う", () => {
    const reqs = requestsOf(
      oneElement("k", (f) => {
        arrow(f, 1, 1, 2, 1, { dash: true, both: true });
      }),
    );
    const [line] = ofKind(reqs, "createLine");
    if (line === undefined) assert.fail();
    assert.equal(line["category"], "STRAIGHT");
    assert.equal("lineCategory" in line, false);
    const [props] = ofKind(reqs, "updateLineProperties");
    assert.deepEqual((props?.["lineProperties"] as Record<string, unknown>)["dashStyle"], "DASH");
    assert.deepEqual((props?.["lineProperties"] as Record<string, unknown>)["startArrow"], "FILL_ARROW");
  });

  test("一部ずつ書式の違う文字は、書式の範囲が段落の区切りの改行の文字を含む", () => {
    const s = oneElement("k", (f) => {
      text(f, [{ text: "見出し", bold: true, fontSize: 16, breakLine: true }, { text: "本文" }], 0, 0, 3, 1);
    });
    const styles = ofKind(requestsOf(s), "updateTextStyle").filter((u) => u["objectId"] === FIRST);
    assert.deepEqual(
      styles.map((u) => u["textRange"]),
      [
        { type: "FIXED_RANGE", startIndex: 0, endIndex: 4 },
        { type: "FIXED_RANGE", startIndex: 4, endIndex: 6 },
      ],
    );
    const [first] = styles;
    assert.deepEqual((first?.["style"] as Record<string, unknown>)["bold"], true);
    assert.equal(first?.["fields"], "fontFamily,fontSize,bold,foregroundColor");
  });

  test("書式が同じ文字は、範囲 ALL の 1 つの指示になる", () => {
    const s = oneElement("k", (f) => {
      text(f, "一行目\n二行目", 0, 0, 3, 1);
    });
    const styles = ofKind(requestsOf(s), "updateTextStyle").filter((u) => u["objectId"] === FIRST);
    assert.deepEqual(
      styles.map((u) => u["textRange"]),
      [{ type: "ALL" }],
    );
  });

  test("リンクは link で、フォントは題名が見出しのフォント・ほかが本文のフォントになる", () => {
    const s = oneElement("k", (f) => {
      text(f, [{ text: "RFC", link: "https://example.com/" }], 0, 0, 3, 1);
    });
    const styles = ofKind(requestsOf(s), "updateTextStyle");
    const byId = (id: string): Record<string, unknown> =>
      styles.find((u) => u["objectId"] === id)?.["style"] as Record<string, unknown>;
    assert.equal(byId("sd_k_0123456789_0")["fontFamily"], "Heading");
    assert.equal(byId(FIRST)["fontFamily"], "Body");
    assert.deepEqual(byId(FIRST)["link"], { url: "https://example.com/" });
    assert.equal(byId("sd_k_0123456789_2")["fontFamily"], "Body");
  });

  test("箇条書きは indentStart が 16 ポイントになり、箇条書きの段落だけに付く", () => {
    const all = oneElement("k", (f) => {
      text(f, bullets(["a", "b"]), 0, 0, 3, 1);
    });
    const [indent] = ofKind(requestsOf(all), "updateParagraphStyle").filter(
      (u) => (u["fields"] as string) === "indentFirstLine,indentStart",
    );
    assert.deepEqual((indent?.["style"] as Record<string, unknown>)["indentStart"], { magnitude: 16, unit: "PT" });
    assert.deepEqual(indent?.["textRange"], { type: "ALL" });
    const mixed = oneElement("k", (f) => {
      text(f, [{ text: "見出し", breakLine: true }, ...bullets(["a", "b"])], 0, 0, 3, 1);
    });
    const [created] = ofKind(requestsOf(mixed), "createParagraphBullets");
    assert.deepEqual(created?.["textRange"], { type: "FIXED_RANGE", startIndex: 4, endIndex: 7 });
  });

  test("図形の大きさは基準の大きさ 3,000,000 EMU と拡大率で表され、拡大率から求めた大きさがデータの大きさと一致する", () => {
    const deck = sample();
    for (const s of deck.slides) {
      const reqs = slideRequests(s, idOf(s, deck.theme), 0, deck.theme.fonts);
      const shapes = ofKind(reqs, "createShape").filter((c) => c["shapeType"] !== "TEXT_BOX");
      const datas = s.elements.filter((e): e is Extract<SlideElement, { kind: "shape" }> => e.kind === "shape");
      assert.equal(shapes.length, datas.length);
      shapes.forEach((c, i) => {
        const g = geometry(c);
        assert.equal(g.size.width.magnitude, BASE);
        assert.equal(g.size.height.magnitude, BASE);
        const r = inches(g);
        const e = datas[i];
        if (e === undefined) assert.fail();
        assert.ok(Math.abs(r.w - e.w) * EMU_PER_INCH < 1, `${s.key} の図形 ${String(i)} の幅`);
        assert.ok(Math.abs(r.h - e.h) * EMU_PER_INCH < 1, `${s.key} の図形 ${String(i)} の高さ`);
        assert.ok(Math.abs(r.x - e.x) * EMU_PER_INCH < 1);
      });
    }
  });

  test("32 文字のキーで、スライドの ID と図形の ID が 50 文字以下になる", () => {
    const key = "a".repeat(32);
    const fig = slide(key);
    for (let i = 0; i < MAX_OBJECTS_PER_SLIDE - 2; i++) arrow(fig, 0, 0, 1, 1);
    const s: Slide = { key, title: "題名", takeaway: "一言", notes: "", elements: fig.elements };
    const id = slideObjectId(key, slideHash(s, FONTS));
    assert.equal(id.length, 3 + 32 + 1 + 10);
    const ids = slideRequests(s, id, 0, FONTS).flatMap((r) =>
      Object.values(r).map((body) => (body as Record<string, unknown>)["objectId"]),
    );
    const longest = Math.max(...ids.map((v) => (typeof v === "string" ? v.length : 0)));
    assert.equal(longest, 50);
    assert.deepEqual(parseSlideObjectId(id), { key, hash: id.slice(-10) });
  });

  test("図形が 1000 個を超えるスライドは、誤りになる", () => {
    const fig = slide("k");
    for (let i = 0; i < MAX_OBJECTS_PER_SLIDE - 1; i++) arrow(fig, 0, 0, 1, 1);
    const s: Slide = { key: "k", title: "題名", takeaway: "一言", notes: "", elements: fig.elements };
    assert.throws(() => slideRequests(s, "sd_k_0123456789", 0, FONTS), /図形が 1000 個を超える/);
  });

  test("番号の入った円の文字は太字で、重ねた文字の箱が中央に揃う", () => {
    const s = oneElement("k", (f) => {
      badge(f, 1, 0, 0, 0.32);
    });
    const reqs = requestsOf(s);
    const align = ofKind(reqs, "updateParagraphStyle").find((u) => u["objectId"] === "sd_k_0123456789_2");
    assert.deepEqual((align?.["style"] as Record<string, unknown>)["alignment"], "CENTER");
    const valign = ofKind(reqs, "updateShapeProperties").find((u) => u["objectId"] === "sd_k_0123456789_2");
    assert.deepEqual((valign?.["shapeProperties"] as Record<string, unknown>)["contentAlignment"], "MIDDLE");
  });
});

describe("マスターの配色", () => {
  test("読み込んだマスターの ID に対する updatePageProperties の colorScheme で、テーマの 12 色を持つ", () => {
    const deck = sample();
    const reqs = colorSchemeRequests(presentation([]), deck.theme);
    assert.equal(reqs.length, 1);
    const [update] = ofKind(reqs, "updatePageProperties");
    assert.equal(update?.["objectId"], "simple-light-2");
    assert.equal(update["fields"], "colorScheme");
    const colors = ((update["pageProperties"] as Record<string, unknown>)["colorScheme"] as { colors: { type: string; color: RgbColor }[] })
      .colors;
    assert.deepEqual(
      colors.map((c) => c.type),
      ["DARK1", "LIGHT1", "DARK2", "LIGHT2", "ACCENT1", "ACCENT2", "ACCENT3", "ACCENT4", "ACCENT5", "ACCENT6", "HYPERLINK", "FOLLOWED_HYPERLINK"],
    );
    // accent1 は 0F6E8C
    const accent1 = colors.find((c) => c.type === "ACCENT1")?.color;
    assert.deepEqual(accent1 && [accent1.red * 255, accent1.green * 255, accent1.blue * 255].map(Math.round), [0x0f, 0x6e, 0x8c]);
  });

  test("読み込んだ配色がテーマと同じなら (小数の最後の桁が違っても)、指示を作らない", () => {
    const deck = sample();
    assert.deepEqual(colorSchemeRequests(presentation([], themeColors(deck.theme)), deck.theme), []);
  });
});

describe("差の計算", () => {
  test("内容を変えていないスライドは、ハッシュ値が変わらず、差が「そのまま」になり、指示のファイルが無い", () => {
    const deck = sample();
    const p = plan(deck, published(deck));
    assert.deepEqual(Object.values(actions(p)), ["keep", "keep", "keep", "keep"]);
    assert.deepEqual(p.steps, []);
    assert.deepEqual(slideRequestFiles(p, published(deck), deck.theme), []);
  });

  test("図の文字を 1 文字だけ変えたスライドは、差が「作り直す」になり、新しい ID で同じ位置に作ってから古いスライドを消す", () => {
    const deck = sample();
    const before = published(deck);
    const changed = changeOneChar(deck, "stale");
    const p = plan(changed, before);
    assert.deepEqual(actions(p), { "read-path": "keep", "hit-miss": "keep", stale: "recreate", expire: "keep" });
    const files = slideRequestFiles(p, before, changed.theme);
    assert.equal(files.length, 1);
    const [file = []] = files;
    const [create] = ofKind(file, "createSlide");
    assert.equal(create?.["insertionIndex"], 2);
    assert.notEqual(create["objectId"], idOf(deck.slides[2] as Slide, deck.theme));
    const deletes = ofKind(file, "deleteObject");
    assert.deepEqual(deletes, [{ objectId: idOf(deck.slides[2] as Slide, deck.theme) }]);
    assert.ok(Object.keys(file.at(-1) ?? {}).includes("deleteObject"), "古いスライドを消す指示は、作る指示の後");
  });

  test("発表者ノートだけを変えたスライドは、差が「そのまま」で、ノートの指示だけが作られる", () => {
    const deck = sample();
    const before = published(deck);
    const edited: Deck = { ...deck, slides: deck.slides.map((s) => (s.key === "hit-miss" ? { ...s, notes: "新しいノート" } : s)) };
    const p = plan(edited, before);
    assert.deepEqual(Object.values(actions(p)), ["keep", "keep", "keep", "keep"]);
    assert.deepEqual(slideRequestFiles(p, before, edited.theme), []);
    const changes = notesChanges(edited.slides, p.keys, before);
    assert.deepEqual(
      changes.map((c) => c.key),
      ["hit-miss"],
    );
  });

  test("前にスライドを 1 枚足しても、後ろのスライドのハッシュ値は変わらない", () => {
    const deck = sample();
    const extra: Slide = { key: "intro", title: "はじめに", takeaway: "一言", notes: "", elements: [] };
    const added: Deck = { ...deck, slides: [extra, ...deck.slides] };
    const p = plan(added, published(deck));
    assert.deepEqual(actions(p), { intro: "create", "read-path": "keep", "hit-miss": "keep", stale: "keep", expire: "keep" });
    const [create] = p.steps;
    assert.deepEqual(create?.kind === "create" ? [create.objectId, create.insertionIndex] : [], [idOf(extra, deck.theme), 0]);
  });

  test("テーマのフォントを変えると、すべてのスライドのハッシュ値が変わる", () => {
    const deck = sample();
    const theme: Theme = { ...deck.theme, fonts: { heading: "Other", body: deck.theme.fonts.body } };
    const p = plan({ ...deck, theme }, published(deck));
    assert.deepEqual(Object.values(actions(p)), ["recreate", "recreate", "recreate", "recreate"]);
  });

  test("資料にあって構成案に無いキーは「消す」、キーの無いスライドは「触れない」になる", () => {
    const deck = sample();
    const [first, ...rest] = deck.slides;
    if (first === undefined) assert.fail();
    const p = plan({ ...deck, slides: rest }, presentation([{ id: idOf(first, deck.theme) }, { id: "g_user" }, ...rest.map((s) => ({ id: idOf(s, deck.theme) }))]));
    assert.deepEqual(p.removed, [{ key: "read-path", objectId: idOf(first, deck.theme) }]);
    assert.deepEqual(p.untouched, ["g_user"]);
    assert.deepEqual(p.steps, [{ kind: "delete", objectId: idOf(first, deck.theme) }]);
  });

  test("構成案で 2 つのキーの順序を入れ替えると、ハッシュ値は変わらず、並べ替えの指示だけが作られる", () => {
    const deck = sample();
    const [a, b, c, d] = deck.slides;
    if (a === undefined || b === undefined || c === undefined || d === undefined) assert.fail();
    const swapped: Deck = { ...deck, slides: [a, c, b, d] };
    const before = published(deck);
    const p = plan(swapped, before);
    assert.deepEqual(Object.values(actions(p)), ["keep", "keep", "keep", "keep"]);
    assert.deepEqual(p.steps, [{ kind: "move", objectIds: [idOf(c, deck.theme)], insertionIndex: 1 }]);
    assert.deepEqual(slideRequestFiles(p, before, deck.theme), [
      [{ updateSlidesPosition: { slideObjectIds: [idOf(c, deck.theme)], insertionIndex: 1 } }],
    ]);
  });

  test("キーの無いスライドは、前のキーのあるスライドを並べ替えると一緒に動き、間に挿入したスライドはその後ろに入る", () => {
    const deck = sample();
    const [a, b] = deck.slides;
    if (a === undefined || b === undefined) assert.fail();
    const ida = idOf(a, deck.theme);
    const idb = idOf(b, deck.theme);
    // 資料は a・利用者のスライド・b。構成案で b・a の順にすると、利用者のスライドは a と一緒に、b の後ろへ動く
    const before = presentation([{ id: ida }, { id: "g_user" }, { id: idb }]);
    const moved = plan({ ...deck, slides: [b, a] }, before);
    assert.deepEqual(moved.steps, [{ kind: "move", objectIds: [idb], insertionIndex: 0 }]);
    // b を前に動かす代わりに a を後ろに動かす場合も、利用者のスライドは a と一緒に動く
    const before2 = presentation([{ id: idb }, { id: ida }, { id: "g_user" }, { id: idOf(deck.slides[2] as Slide, deck.theme) }]);
    const moved2 = plan({ ...deck, slides: [deck.slides[2] as Slide, a, b] }, before2);
    assert.deepEqual(moved2.steps, [
      { kind: "move", objectIds: [idOf(deck.slides[2] as Slide, deck.theme)], insertionIndex: 0 },
      { kind: "move", objectIds: [ida, "g_user"], insertionIndex: 1 },
    ]);
    // a と b の間に新しいスライドを挿入すると、利用者のスライドの後ろ (位置 2) に入る
    const extra: Slide = { key: "between", title: "間", takeaway: "一言", notes: "", elements: [] };
    const inserted = plan({ ...deck, slides: [a, extra, b] }, before);
    assert.deepEqual(
      inserted.steps.map((s) => (s.kind === "create" ? [s.objectId, s.insertionIndex] : s.kind)),
      [[idOf(extra, deck.theme), 2]],
    );
  });

  test("先頭にあるキーの無いスライドは先頭に残り、最初のキーのスライドはその後ろに作る", () => {
    const deck = sample();
    const [a] = deck.slides;
    if (a === undefined) assert.fail();
    const p = plan({ ...deck, slides: [a] }, presentation([{ id: "g_cover" }, { id: "g_other" }]));
    assert.equal(p.initialSlideId, null);
    assert.deepEqual(
      p.steps.map((s) => (s.kind === "create" ? s.insertionIndex : s.kind)),
      [2],
    );
  });

  test("指示のファイルは字数の上限以下に分け、上限を超える 1 枚のスライドはそれだけのファイルになり、作り直しの作ると消すは分けない", () => {
    const deck = sample();
    const six = [...deck.slides, ...deck.slides.slice(0, 2).map((s) => ({ ...s, key: `${s.key}-2` }))];
    const p = presentation([{ id: "p" }]);
    const sp = planSlides(six, deck.theme.fonts, p, false);
    const files = slideRequestFiles(sp, p, deck.theme);
    assert.ok(files.length >= 2);
    for (const f of files) assert.ok(JSON.stringify(f).length <= MAX_FILE_CHARS, String(JSON.stringify(f).length));
    // スライドの順序を保ち、どのスライドも 1 つのファイルに収まる
    assert.deepEqual(
      files.flatMap((f) => ofKind(f, "createSlide").map((c) => c["objectId"])),
      six.map((s) => idOf(s, deck.theme)),
    );
    // 上限を小さくすると、1 枚ずつのファイルになる (最初のファイルは、配色と最初のスライドを消す指示も持つ)
    const small = slideRequestFiles(sp, p, deck.theme, 100);
    assert.deepEqual(
      small.map((f) => ofKind(f, "createSlide").length),
      [0, 1, 1, 1, 1, 1, 1],
    );
    // 作り直しは、作る指示と古いスライドを消す指示が同じファイルに入る
    const before = published(deck);
    const recreate = slideRequestFiles(plan(deck, before, true), before, deck.theme, 100);
    assert.equal(recreate.length, 4);
    for (const f of recreate) {
      assert.equal(ofKind(f, "createSlide").length, 1);
      assert.equal(ofKind(f, "deleteObject").length, 1);
    }
  });

  test("新しく作った資料 (キーの無いスライドが 1 枚だけ) では、最初の指示のファイルがそのスライドを消す指示を持つ。既存の資料では持たない", () => {
    const deck = sample();
    const fresh = presentation([{ id: "p" }]);
    const p = plan(deck, fresh);
    assert.equal(p.initialSlideId, "p");
    const [first = []] = slideRequestFiles(p, fresh, deck.theme);
    assert.deepEqual(ofKind(first, "deleteObject"), [{ objectId: "p" }]);
    const ofIndex = (s: SlidePlan): number[] => s.steps.flatMap((x) => (x.kind === "create" ? [x.insertionIndex] : []));
    assert.deepEqual(ofIndex(p), [0, 1, 2, 3]);

    const existing = presentation([{ id: "g_user" }, { id: idOf(deck.slides[0] as Slide, deck.theme) }]);
    const q = plan(deck, existing);
    assert.equal(q.initialSlideId, null);
    const [firstOfExisting = []] = slideRequestFiles(q, existing, deck.theme);
    assert.deepEqual(ofKind(firstOfExisting, "deleteObject"), []);
  });

  test("途中まで作った資料 (ハッシュ値の一致するスライドが 4 枚ある) では、残りの 2 枚だけが「作る」になる", () => {
    const deck = sample();
    const six: Deck = { ...deck, slides: [...deck.slides, ...deck.slides.slice(0, 2).map((s) => ({ ...s, key: `${s.key}-2` }))] };
    const p = plan(six, presentation(six.slides.slice(0, 4).map((s) => ({ id: idOf(s, deck.theme) }))));
    assert.deepEqual(Object.values(actions(p)), ["keep", "keep", "keep", "keep", "create", "create"]);
    assert.deepEqual(
      p.steps.map((s) => (s.kind === "create" ? s.insertionIndex : -1)),
      [4, 5],
    );
  });

  test("--recreate-all では、ハッシュ値が一致するスライドも作り直し、古いスライドを消してから同じ ID で作る", () => {
    const deck = sample();
    const before = published(deck);
    const p = plan(deck, before, true);
    assert.deepEqual(Object.values(actions(p)), ["recreate", "recreate", "recreate", "recreate"]);
    const [file = []] = slideRequestFiles(p, before, deck.theme);
    const [first, second] = file;
    const id = idOf(deck.slides[0] as Slide, deck.theme);
    assert.deepEqual(first, { deleteObject: { objectId: id } });
    assert.deepEqual(ofKind(second ? [second] : [], "createSlide")[0]?.["objectId"], id);
    // ノートは、作り直した後に資料を再度読み込んでから入れる
    assert.deepEqual(notesChanges(deck.slides, p.keys, before), []);
  });

  test("同じキーのスライドが資料に 2 枚あると、誤りになる", () => {
    const deck = sample();
    assert.throws(
      () => plan(deck, presentation([{ id: "sd_stale_0000000000" }, { id: "sd_stale_1111111111" }])),
      (e: unknown) => e instanceof PlanError && /キー stale のスライドが 2 枚ある/.test(e.message),
    );
  });
});

describe("ノートの指示", () => {
  test("ノートの指示は、読み込んだ結果のノートの欄の ID を使い、構成案の文を入れる。欄に文があれば消す指示を先に入れ、空なら入れない", () => {
    const deck = sample();
    const [a, b] = deck.slides;
    if (a === undefined || b === undefined) assert.fail();
    const p = presentation([
      { id: idOf(a, deck.theme), notes: "古いノート\n" },
      { id: idOf(b, deck.theme), notes: null },
    ]);
    const slides = [a, b];
    const changes = notesChanges(slides, plan({ ...deck, slides }, p).keys, p);
    assert.deepEqual(changes, [
      {
        key: a.key,
        requests: [
          { deleteText: { objectId: "n0", textRange: { type: "ALL" } } },
          { insertText: { objectId: "n0", insertionIndex: 0, text: a.notes } },
        ],
      },
      { key: b.key, requests: [{ insertText: { objectId: "n1", insertionIndex: 0, text: b.notes } }] },
    ]);
  });

  test("スライドを作った後、ノートを入れる前に失敗した資料をもう一度処理すると、そのスライドのノートの指示が作られる", () => {
    const deck = sample();
    const p = presentation(deck.slides.map((s) => ({ id: idOf(s, deck.theme), notes: null })));
    const q = plan(deck, p);
    assert.deepEqual(Object.values(actions(q)), ["keep", "keep", "keep", "keep"]);
    // 見本の資料でノートがあるのは read-path・hit-miss・expire
    assert.deepEqual(
      notesChanges(deck.slides, q.keys, p).map((c) => c.key),
      ["read-path", "hit-miss", "expire"],
    );
  });

  test("構成案のノートが空で、欄に文があれば、消す指示だけを作る。読んだ文の末尾の改行は比べない", () => {
    const deck = sample();
    const [, , stale] = deck.slides;
    if (stale === undefined) assert.fail();
    assert.equal(stale.notes, "");
    const p = presentation([{ id: idOf(stale, deck.theme), notes: "手で書いたノート\n" }]);
    const slides = [stale];
    assert.deepEqual(notesChanges(slides, plan({ ...deck, slides }, p).keys, p), [
      { key: "stale", requests: [{ deleteText: { objectId: "n0", textRange: { type: "ALL" } } }] },
    ]);
    const same = presentation([{ id: idOf(stale, deck.theme), notes: "\n" }]);
    assert.deepEqual(notesChanges(slides, plan({ ...deck, slides }, same).keys, same), []);
  });

  test("ノートの指示は、字数の上限以下のファイルに分け、1 枚のスライドの指示は分けない", () => {
    const changes = Array.from({ length: 5 }, (_, i) => ({
      key: `k${String(i)}`,
      requests: [{ deleteText: { objectId: `n${String(i)}` } }, { insertText: { objectId: `n${String(i)}`, text: "あ".repeat(30) } }],
    }));
    const files = notesRequestFiles(changes, 200);
    assert.deepEqual(
      files.map((f) => f.length),
      [2, 2, 2, 2, 2],
    );
    assert.deepEqual(
      notesRequestFiles(changes).map((f) => f.length),
      [10],
    );
  });
});

describe("読み込みの結果の検査", () => {
  const u11 = (name: string): unknown => JSON.parse(readFileSync(join(FIXTURES, name), "utf8"));

  test("U11 で得た読み込みの結果の例 (配色は U11 の 3 の読み込みの結果) が、検査を通る", () => {
    const fresh = parsePresentation(u11("u11-new.json"));
    assert.ok(fresh.ok, fresh.ok ? "" : fresh.errors.join("\n"));
    assert.deepEqual(fresh.presentation.slides, [{ objectId: "p", notesObjectId: "i3", notesText: null }]);
    assert.deepEqual(fresh.presentation.masters[0]?.colors.get("DARK1"), { red: 0, green: 0, blue: 0 });
    const written = parsePresentation(u11("u11-notes.json"));
    assert.ok(written.ok, written.ok ? "" : written.errors.join("\n"));
    assert.deepEqual(written.presentation.slides, [
      { objectId: "p", notesObjectId: "i3", notesText: "U11 の確認: ノートの書き込み\n" },
    ]);
  });

  test("必要なキー (スライドの一覧・マスター) が無ければ、場所を示した誤りになる", () => {
    const r = parsePresentation({ revisionId: "rev" });
    assert.deepEqual(r.ok ? [] : r.errors, ["masters: 無い", "slides: 無い"]);
    const noScheme = parsePresentation({ revisionId: "rev", masters: [{ objectId: "m" }], slides: [] });
    assert.deepEqual(noScheme.ok ? [] : noScheme.errors, ["masters[0].pageProperties: 無い"]);
    const noNotes = parsePresentation({
      revisionId: "rev",
      masters: [{ objectId: "m", pageProperties: { colorScheme: { colors: [] } } }],
      slides: [{ objectId: "s", slideProperties: {} }],
    });
    assert.deepEqual(noNotes.ok ? [] : noNotes.errors, ["slides[0].slideProperties.notesPage: 無い"]);
  });

  test("ノートの欄の ID を持つ要素が無いと、誤りになる", () => {
    const r = parsePresentation({
      revisionId: "rev",
      masters: [{ objectId: "m", pageProperties: { colorScheme: { colors: [] } } }],
      slides: [
        {
          objectId: "s",
          slideProperties: { notesPage: { notesProperties: { speakerNotesObjectId: "x" }, pageElements: [{ objectId: "y" }] } },
        },
      ],
    });
    assert.deepEqual(r.ok ? [] : r.errors, ["slides[0].slideProperties.notesPage.pageElements: ノートの欄の ID x を持つ要素が無い"]);
  });
});

/** キー key のスライドの、最初の文字の入った箱の文字を 1 文字変える */
function changeOneChar(deck: Deck, key: string): Deck {
  return {
    ...deck,
    slides: deck.slides.map((s) => {
      if (s.key !== key) return s;
      let done = false;
      const elements = s.elements.map((e) => {
        if (done || e.kind === "line" || e.text === null) return e;
        done = true;
        const [p, ...ps] = e.text.paragraphs;
        const [r, ...rs] = p?.runs ?? [];
        if (p === undefined || r === undefined) return e;
        return { ...e, text: { ...e.text, paragraphs: [{ ...p, runs: [{ ...r, text: `${r.text}!` }, ...rs] }, ...ps] } };
      });
      return { ...s, elements };
    }),
  };
}

describe("見本の資料の指示の配列", () => {
  const expected = (name: string): unknown => JSON.parse(readFileSync(join(FIXTURES, name), "utf8"));
  const run = (deck: Deck, p: Presentation): { files: Request[][]; notes: Request[][] } => {
    const sp = plan(deck, p);
    return {
      files: slideRequestFiles(sp, p, deck.theme),
      notes: notesRequestFiles(notesChanges(deck.slides, sp.keys, p)),
    };
  };

  test("作る: 新しく作った資料に、すべてのスライドを作る", () => {
    const deck = sample();
    assert.deepEqual(run(deck, presentation([{ id: "p" }])), expected("create.json"));
  });

  test("作り直す: stale の図の文字を 1 文字変えると、stale だけを作り直す", () => {
    const deck = sample();
    assert.deepEqual(run(changeOneChar(deck, "stale"), published(deck)), expected("recreate.json"));
  });

  test("途中からの再開: 最初のファイルだけ送った資料では、残りの 2 枚を作り、作ったスライドのノートを入れる", () => {
    const deck = sample();
    const [a, b] = deck.slides;
    if (a === undefined || b === undefined) assert.fail();
    const p = presentation([{ id: idOf(a, deck.theme) }, { id: idOf(b, deck.theme) }], themeColors(deck.theme));
    assert.deepEqual(run(deck, p), expected("resume.json"));
  });
});
