// スライドのデータから、Google スライドの API のメソッド presentations.batchUpdate に渡す指示 (requests) を作る (計画の R11・R17・KTD9・KTD14・U6)。
// 要素ごとの変換は、元にしたツール gslides.js の関数 slideRequests・lineRequests・textRequests・colorSchemeRequest を引き継いだ。
// Google スライドの API の挙動への対処 (計画の KTD14) は、対処ごとに理由をコメントに書いた。
// 指示に資料の版の ID (revisionId) は書かない。Claude が送る直前に読んだ値を付ける (計画の R16)。

import { title as titleBox, takeaway as takeawayBox, slide as emptyFigure } from "../data/parts.ts";
import { type SchemeColorName, schemeColorValues, type Theme } from "../data/theme.ts";
import type {
  LineElement,
  Paragraph,
  Rect,
  ShapeElement,
  ShapeKind,
  Slide,
  SlideFigure,
  TextBody,
  TextBoxElement,
  ThemeColorName,
} from "../data/types.ts";
import type { SlidePlan, SlideStep } from "./plan.ts";
import type { Presentation, PresentationMaster } from "./presentation.ts";

/** batchUpdate の 1 つの指示。形は Google スライドの API の Request */
export type Request = Record<string, unknown>;

const EMU_PER_INCH = 914_400;

// 基準の大きさ (EMU)。Google スライドは、図形の大きさを基準の大きさと拡大率で表し、読み込むと大きさは常にこの値になる
// (Issue #242 の表)。後から大きさを変えるときに、読み込んだ拡大率をそのまま計算に使えるよう、作るときから同じ形で表す
const BASE_SIZE_EMU = 3_000_000;

// Google スライドの文字の内側の余白 (インチ)。API では変えられないので、文字の箱をこの分だけ広げて、文字を配置する範囲をデータに合わせる。
// はみ出しの見積もり (ファイル src/fit/estimate.ts の GOOGLE_MARGIN) と同じ値
const PADDING = { x: 0.1, y: 0.05 } as const;

// 箇条書きの字下げ (ポイント)。はみ出しの見積もりと PowerPoint の書き出しと同じ値
const BULLET_INDENT_PT = 16;

// 角の丸い四角を、この大きさ (インチ) を超えたら四角で描く
const ROUND_RECT_MAX = 1.0;

/** 1 枚のスライドの図形の番号の上限。ID の長さを 50 文字以下にするため、番号は 3 桁まで (計画の KTD9) */
export const MAX_OBJECTS_PER_SLIDE = 1000;

/** テーマの色の名前を、Google スライドの配色の種類にする */
const THEME_COLOR: Record<ThemeColorName, string> = {
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
};

/** テーマの 12 色の名前を、Google スライドの配色の種類にする */
const SCHEME_TYPE: Record<SchemeColorName, string> = {
  ...THEME_COLOR,
  hlink: "HYPERLINK",
  folHlink: "FOLLOWED_HYPERLINK",
};

const SHAPE_TYPE: Record<ShapeKind, string> = {
  roundRect: "ROUND_RECTANGLE",
  rect: "RECTANGLE",
  ellipse: "ELLIPSE",
  can: "CAN",
  chevron: "CHEVRON",
  homePlate: "HOME_PLATE",
};

// 中の文字を、図形に重ねた文字の箱に分ける形
const OVERLAY_SHAPES: ReadonlySet<ShapeKind> = new Set(["ellipse", "can", "chevron", "homePlate"]);

const ALIGN = { left: "START", center: "CENTER", right: "END" } as const;
const VALIGN = { top: "TOP", middle: "MIDDLE", bottom: "BOTTOM" } as const;

/** 16 進数 6 桁の色を、0〜255 の 3 つの成分にする */
function rgb255(hex: string): [number, number, number] {
  const n = parseInt(hex, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function themeColor(name: ThemeColorName): Record<string, string> {
  return { themeColor: THEME_COLOR[name] };
}

const round = (v: number, digits: number): number => Number(v.toFixed(digits));

/** 1 つの軸の大きさ (インチ) を、大きさ (EMU) と拡大率にする */
function axis(length: number): { size: number; scale: number } {
  // 大きさが 0 の軸 (縦や横の線) は、拡大率 0 にせず、元の gslides.js と同じく大きさ 0・拡大率 1 にする。
  // 拡大率 0 を Google スライドが受け付けるかは確認していない (U6 を実装するときに決めた)
  if (length === 0) return { size: 0, scale: 1 };
  return { size: BASE_SIZE_EMU, scale: round((length * EMU_PER_INCH) / BASE_SIZE_EMU, 7) };
}

/** 要素の位置と大きさ。flipH・flipV なら、その軸の拡大率を負にし、始点を反対の端にする */
function elementProperties(page: string, r: Rect, flipH = false, flipV = false): Request {
  const x = axis(r.w);
  const y = axis(r.h);
  return {
    pageObjectId: page,
    size: { width: { magnitude: x.size, unit: "EMU" }, height: { magnitude: y.size, unit: "EMU" } },
    transform: {
      scaleX: flipH ? -x.scale : x.scale,
      scaleY: flipV ? -y.scale : y.scale,
      translateX: Math.round((flipH ? r.x + r.w : r.x) * EMU_PER_INCH),
      translateY: Math.round((flipV ? r.y + r.h : r.y) * EMU_PER_INCH),
      unit: "EMU",
    },
  };
}

/**
 * 文字の箱の位置と大きさ。データの内側の余白の分だけ狭めてから、Google スライドの余白の分だけ広げる。
 * Google スライドの余白は API で変えられないので、こうすると文字を配置する範囲が、データの箱から余白を引いた範囲と一致する
 * (余白 0 の箱は、Google スライドの余白の分だけ広がる。余白が 0 でない箱の扱いは、U6 を実装するときに決めた)
 */
function textBoxRect(r: Rect, body: TextBody): Rect {
  const m = body.margin;
  return {
    x: r.x + m.left / 72 - PADDING.x,
    y: r.y + m.top / 72 - PADDING.y,
    w: r.w - (m.left + m.right) / 72 + 2 * PADDING.x,
    h: r.h - (m.top + m.bottom) / 72 + 2 * PADDING.y,
  };
}

/** 文字の書式で使うフォント。題名は見出しのフォント、ほかは本文のフォント */
interface Fonts {
  family: string;
}

/** 段落の文字。段落を改行でつなぐ */
function joinParagraphs(paragraphs: readonly Paragraph[]): string {
  return paragraphs.map((p) => p.runs.map((r) => r.text).join("")).join("\n");
}

/** 文字の範囲 (文字の位置。Google スライドの API の位置は UTF-16 の単位で数える) */
interface Span {
  start: number;
  end: number;
}

/** 箇条書きの段落が続く範囲 */
function bulletSpans(paragraphs: readonly Paragraph[]): Span[] {
  const spans: Span[] = [];
  let at = 0;
  let open: Span | null = null;
  paragraphs.forEach((p, i) => {
    const length = p.runs.reduce((n, r) => n + r.text.length, 0) + (i < paragraphs.length - 1 ? 1 : 0);
    if (p.bullet) {
      if (open === null) {
        open = { start: at, end: at + length };
        spans.push(open);
      } else open.end = at + length;
    } else open = null;
    at += length;
  });
  return spans.filter((s) => s.end > s.start);
}

/** 文字の指示。文字が空なら、指示は無い */
function textRequests(objectId: string, body: TextBody, isTextBox: boolean, fonts: Fonts): Request[] {
  const full = joinParagraphs(body.paragraphs);
  if (full === "") return [];
  const reqs: Request[] = [{ insertText: { objectId, text: full } }];

  const runs: { span: Span; style: Record<string, unknown>; fields: string }[] = [];
  let at = 0;
  body.paragraphs.forEach((p, pi) => {
    p.runs.forEach((r, ri) => {
      const start = at;
      at += r.text.length;
      // 段落の区切りの改行を、その段落の最後の部分の範囲に含める。
      // 含めないと、改行の文字だけが書式の付かない (デフォルトの大きさの) まま残り、その行が高くなる (計画の KTD14)
      if (ri === p.runs.length - 1 && pi < body.paragraphs.length - 1) at += 1;
      const style: Record<string, unknown> = {
        fontFamily: fonts.family,
        fontSize: { magnitude: r.fontSize, unit: "PT" },
      };
      // 新しい箱の文字は太字ではないので、太字のときだけ指定する (指示を短くするため。元の gslides.js と同じ)
      if (r.bold) style["bold"] = true;
      style["foregroundColor"] = { opaqueColor: themeColor(r.color) };
      if (r.link !== null) style["link"] = { url: r.link };
      const fields = `fontFamily,fontSize${r.bold ? ",bold" : ""},foregroundColor${r.link !== null ? ",link" : ""}`;
      runs.push({ span: { start, end: at }, style, fields });
    });
  });
  const [first] = runs;
  const same = first !== undefined && runs.every((r) => JSON.stringify(r.style) === JSON.stringify(first.style));
  if (same) {
    reqs.push({ updateTextStyle: { objectId, textRange: { type: "ALL" }, style: first.style, fields: first.fields } });
  } else {
    for (const r of runs) {
      if (r.span.end === r.span.start) continue;
      reqs.push({
        updateTextStyle: {
          objectId,
          textRange: { type: "FIXED_RANGE", startIndex: r.span.start, endIndex: r.span.end },
          style: r.style,
          fields: r.fields,
        },
      });
    }
  }

  const paragraphStyle: Record<string, unknown> = {};
  const paragraphFields: string[] = [];
  // 文字の箱の横の揃え方のデフォルト値は左揃え (START) なので、そのときは指定しない (指示を短くするため)
  if (!isTextBox || body.align !== "left") {
    paragraphStyle["alignment"] = ALIGN[body.align];
    paragraphFields.push("alignment");
  }
  if (body.paraSpaceAfter > 0) {
    paragraphStyle["spaceBelow"] = { magnitude: body.paraSpaceAfter, unit: "PT" };
    paragraphFields.push("spaceBelow");
  }
  if (paragraphFields.length > 0) {
    reqs.push({
      updateParagraphStyle: { objectId, textRange: { type: "ALL" }, style: paragraphStyle, fields: paragraphFields.join(",") },
    });
  }

  const bullets = bulletSpans(body.paragraphs);
  const allBullets = body.paragraphs.every((p) => p.bullet);
  const ranges: Record<string, unknown>[] = allBullets
    ? [{ type: "ALL" }]
    : bullets.map((s) => ({ type: "FIXED_RANGE", startIndex: s.start, endIndex: s.end }));
  for (const textRange of ranges) {
    reqs.push({ createParagraphBullets: { objectId, textRange, bulletPreset: "BULLET_DISC_CIRCLE_SQUARE" } });
    // 箇条書きの字下げのデフォルト値は大きく、幅の狭い箱では行が折り返されるので、字下げを 16 ポイントにする (計画の KTD14)
    reqs.push({
      updateParagraphStyle: {
        objectId,
        textRange,
        style: { indentFirstLine: { magnitude: 0, unit: "PT" }, indentStart: { magnitude: BULLET_INDENT_PT, unit: "PT" } },
        fields: "indentFirstLine,indentStart",
      },
    });
  }
  return reqs;
}

/** 文字の箱の指示 */
function textBoxRequests(objectId: string, page: string, r: Rect, body: TextBody, fonts: Fonts): Request[] {
  const reqs: Request[] = [
    { createShape: { objectId, shapeType: "TEXT_BOX", elementProperties: elementProperties(page, textBoxRect(r, body)) } },
  ];
  // 文字の箱の縦の揃え方のデフォルト値は上揃え (TOP) なので、そのときは指定しない (指示を短くするため)
  if (body.valign !== "top") {
    reqs.push({
      updateShapeProperties: { objectId, shapeProperties: { contentAlignment: VALIGN[body.valign] }, fields: "contentAlignment" },
    });
  }
  reqs.push(...textRequests(objectId, body, true, fonts));
  return reqs;
}

/** 図形の指示。円・円柱・山形・五角形の矢印の中の文字は、図形に重ねた文字の箱にする */
function shapeRequests(nextId: () => string, page: string, e: ShapeElement, fonts: Fonts): Request[] {
  const objectId = nextId();
  let shapeType = SHAPE_TYPE[e.shape];
  // 角の丸い四角の丸みの大きさは API で変えられず、大きな箱では丸みが大きくなりすぎるので、大きな箱は四角で描く (計画の KTD14)
  if (e.shape === "roundRect" && Math.min(e.w, e.h) > ROUND_RECT_MAX) shapeType = "RECTANGLE";
  const reqs: Request[] = [{ createShape: { objectId, shapeType, elementProperties: elementProperties(page, e) } }];

  const solidFill: Record<string, unknown> = { color: themeColor(e.fill.color) };
  if (e.fill.transparency > 0) solidFill["alpha"] = round(1 - e.fill.transparency / 100, 3);
  const shapeProperties: Record<string, unknown> = { shapeBackgroundFill: { solidFill } };
  if (e.outline === null) {
    shapeProperties["outline"] = { propertyState: "NOT_RENDERED" };
  } else {
    const outline: Record<string, unknown> = {
      outlineFill: { solidFill: { color: themeColor(e.outline.color) } },
      weight: { magnitude: e.outline.width, unit: "PT" },
    };
    if (e.outline.dashed) outline["dashStyle"] = "DASH";
    shapeProperties["outline"] = outline;
  }
  const fields = ["shapeBackgroundFill", "outline"];
  const overlay = e.text !== null && OVERLAY_SHAPES.has(e.shape);
  if (e.text !== null && !overlay) {
    shapeProperties["contentAlignment"] = VALIGN[e.text.valign];
    fields.push("contentAlignment");
  }
  reqs.push({ updateShapeProperties: { objectId, shapeProperties, fields: fields.join(",") } });

  if (e.text === null) return reqs;
  if (overlay) {
    // Google スライドは、円・円柱・山形・五角形の矢印の中の文字を、図形の内側の狭い範囲に収めて折り返すので、
    // 図形と文字を分け、図形の外形に合わせた文字の箱を上に重ねる (計画の KTD14)
    reqs.push(...textBoxRequests(nextId(), page, e, e.text, fonts));
  } else {
    reqs.push(...textRequests(objectId, e.text, false, fonts));
  }
  return reqs;
}

/** 線の指示 */
function lineRequests(objectId: string, page: string, e: LineElement): Request[] {
  // 線の向きは、始点と終点ではなく拡大率の正負で表すので、右から左・下から上の線は、拡大率を負にする (計画の KTD14)
  const lineProperties: Record<string, unknown> = {
    lineFill: { solidFill: { color: themeColor(e.color) } },
    weight: { magnitude: e.width, unit: "PT" },
    dashStyle: e.dashed ? "DASH" : "SOLID",
    endArrow: e.endArrow ? "FILL_ARROW" : "NONE",
    startArrow: e.startArrow ? "FILL_ARROW" : "NONE",
  };
  return [
    // 線の種類は、非推奨の lineCategory ではなく category で指定する (計画の KTD14)
    { createLine: { objectId, category: "STRAIGHT", elementProperties: elementProperties(page, e, e.flipH, e.flipV) } },
    { updateLineProperties: { objectId, lineProperties, fields: "lineFill,weight,dashStyle,endArrow,startArrow" } },
  ];
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
 * 1 枚のスライドの、図形 (題名・図の要素・一言) と、その ID の数。図形の ID は <スライドの ID>_<番号> で、番号は 0 から数える。
 * 円などの中の文字は図形と文字の箱の 2 つになるので、要素の数より多くなることがある
 */
export function countObjects(slide: Slide): number {
  let n = 2;
  for (const e of slide.elements) n += e.kind === "shape" && e.text !== null && OVERLAY_SHAPES.has(e.shape) ? 2 : 1;
  return n;
}

/**
 * 1 枚のスライドを作る指示。スライドはレイアウト BLANK で作り、題名は部品の関数 title の箱の位置と書式で、普通の文字の箱として置く
 * (U6 を実装するときに決めた)。スライド番号は作らない。レイアウト BLANK のスライドに、スライド番号のプレースホルダーを作れないため
 * (計画の R22)
 */
export function slideRequests(slide: Slide, objectId: string, insertionIndex: number, fonts: Theme["fonts"]): Request[] {
  if (countObjects(slide) > MAX_OBJECTS_PER_SLIDE) {
    throw new Error(`スライド ${slide.key} の図形が ${String(MAX_OBJECTS_PER_SLIDE)} 個を超える`);
  }
  let n = 0;
  const nextId = (): string => `${objectId}_${String(n++)}`;
  const body: Fonts = { family: fonts.body };
  const reqs: Request[] = [
    { createSlide: { objectId, insertionIndex, slideLayoutReference: { predefinedLayout: "BLANK" } } },
  ];
  const title = fixedBox(titleBox, slide.key, slide.title);
  reqs.push(...textBoxRequests(nextId(), objectId, title, title.text, { family: fonts.heading }));
  for (const e of slide.elements) {
    switch (e.kind) {
      case "shape":
        reqs.push(...shapeRequests(nextId, objectId, e, body));
        break;
      case "textBox":
        reqs.push(...textBoxRequests(nextId(), objectId, e, e.text, body));
        break;
      case "line":
        reqs.push(...lineRequests(nextId(), objectId, e));
        break;
    }
  }
  const takeaway = fixedBox(takeawayBox, slide.key, slide.takeaway);
  reqs.push(...textBoxRequests(nextId(), objectId, takeaway, takeaway.text, body));
  return reqs;
}

/** マスターの配色が、テーマの 12 色と同じか。読み込んだ値は小数の最後の桁が違うことがあるので、0〜255 に丸めて比べる */
function sameScheme(master: PresentationMaster, theme: Theme): boolean {
  const values = schemeColorValues(theme);
  return Object.entries(SCHEME_TYPE).every(([name, type]) => {
    const read = master.colors.get(type);
    if (read === undefined) return false;
    const [r, g, b] = rgb255(values[name as SchemeColorName]);
    return Math.round(read.red * 255) === r && Math.round(read.green * 255) === g && Math.round(read.blue * 255) === b;
  });
}

/** 読み込んだ配色がテーマの 12 色と違う、マスターの ID */
export function mastersToRecolor(presentation: Presentation, theme: Theme): string[] {
  return presentation.masters.filter((m) => !sameScheme(m, theme)).map((m) => m.objectId);
}

/**
 * マスターの配色を、テーマの 12 色に変える指示。読み込んだ配色がテーマと違うマスターだけについて作る。
 * 図形の色はテーマの色で指定するので、配色を変えると、すべてのスライドの色が変わる (計画の R11)。
 * 配色は updatePageProperties の colorScheme で変えられる (計画の KTD14。U11 で確認した)
 */
export function colorSchemeRequests(presentation: Presentation, theme: Theme): Request[] {
  const values = schemeColorValues(theme);
  const colors = Object.entries(SCHEME_TYPE).map(([name, type]) => {
    const [red, green, blue] = rgb255(values[name as SchemeColorName]);
    return { type, color: { red: round(red / 255, 8), green: round(green / 255, 8), blue: round(blue / 255, 8) } };
  });
  return mastersToRecolor(presentation, theme).map((objectId) => ({
    updatePageProperties: { objectId, pageProperties: { colorScheme: { colors } }, fields: "colorScheme" },
  }));
}

/** 1 つの操作の指示 */
function stepRequests(step: SlideStep, fonts: Theme["fonts"]): Request[] {
  switch (step.kind) {
    case "delete":
      return [{ deleteObject: { objectId: step.objectId } }];
    case "move":
      return [{ updateSlidesPosition: { slideObjectIds: step.objectIds, insertionIndex: step.insertionIndex } }];
    case "create": {
      const create = slideRequests(step.slide, step.objectId, step.insertionIndex, fonts);
      if (step.replaceId === null) return create;
      const remove = { deleteObject: { objectId: step.replaceId } };
      return step.replaceFirst ? [remove, ...create] : [...create, remove];
    }
  }
}

/**
 * 1 つの指示のファイルの字数 (JSON の文字列の長さ) の上限。Claude はファイルを Bash の出力として読んでコネクタに渡すので、
 * 出力の上限 (約 3 万字) を超えると、超えた分が切り捨てられる (Issue #242 の表)。図形の多いスライドは 1 枚で約 1.5 万字になるので、
 * 枚数ではなく字数で分ける (U6 を実装するときに決めた)
 */
export const MAX_FILE_CHARS = 20_000;

/**
 * 指示のまとまりを、字数の上限を超えないようにファイルに分ける。まとまりは分けず、順序を保つ。
 * 1 つで上限を超えるまとまりは、それだけのファイルにする
 */
export function packRequests(units: readonly Request[][], limit: number = MAX_FILE_CHARS): Request[][] {
  const files: Request[][] = [];
  let current: Request[] = [];
  for (const unit of units) {
    if (unit.length === 0) continue;
    const joined = [...current, ...unit];
    if (current.length > 0 && JSON.stringify(joined).length > limit) {
      files.push(current);
      current = [...unit];
    } else {
      current = joined;
    }
  }
  if (current.length > 0) files.push(current);
  return files;
}

/**
 * 作業を、指示のファイルごとの配列にする。最初のファイルの先頭に、配色・消す・並べ替える指示を入れ、
 * 作る・作り直すスライドを、字数の上限 (MAX_FILE_CHARS) まで入れる。作り直しの「作る」と「古いスライドを消す」は、同じファイルに入る。
 * 送る指示が無ければ、空の配列を返す
 */
export function slideRequestFiles(plan: SlidePlan, presentation: Presentation, theme: Theme, limit: number = MAX_FILE_CHARS): Request[][] {
  const head = [...colorSchemeRequests(presentation, theme)];
  const creates: Request[][] = [];
  for (const step of plan.steps) {
    if (step.kind === "create") creates.push(stepRequests(step, theme.fonts));
    else head.push(...stepRequests(step, theme.fonts));
  }
  return packRequests([head, ...creates], limit);
}
