// Google スライドの資料の読み込みの結果 build/presentation.json の型と検査 (計画の KTD10・U6)。
// スキル publish では、Claude が Google スライドのコネクタで、項目を指定して (field mask は定数 PRESENTATION_FIELDS) 資料を読み込み、
// 結果をそのまま build/presentation.json に書く。サブコマンド requests は、このファイルの検査を通った値だけを使う。
// 形は、U11 の確認 (Issue #251 のコメント) で得た読み込みの結果に合わせた。

/**
 * 読み込みで指定する項目 (Google スライドの API の field mask)。
 * U11 で確認した項目に、マスターの配色 (pageProperties.colorScheme) を足した。配色は、テーマの色と比べ、違うマスターだけを変えるために読む。
 * サブコマンド requests の --help で示す
 */
export const PRESENTATION_FIELDS =
  "revisionId,masters(objectId,pageProperties.colorScheme)," +
  "slides(objectId,slideProperties(masterObjectId,notesPage(notesProperties.speakerNotesObjectId," +
  "pageElements(objectId,shape(shapeType,placeholder.type,text.textElements.textRun.content)))))";

/** 検査の誤りに添える、build/presentation.json に期待する形。サブコマンド requests の --help でも示す */
export const PRESENTATION_SHAPE = `{
  "revisionId": "<資料の版の ID>",
  "masters": [
    { "objectId": "<マスターの ID>",
      "pageProperties": { "colorScheme": { "colors": [ { "type": "DARK1", "color": { "red": 0〜1, "green": 0〜1, "blue": 0〜1 } }, … ] } } }
  ],
  "slides": [
    { "objectId": "<スライドの ID>",
      "slideProperties": { "notesPage": {
        "notesProperties": { "speakerNotesObjectId": "<ノートの欄の ID>" },
        "pageElements": [ { "objectId": "<ノートの欄の ID>", "shape": { "text": { "textElements": [ { "textRun": { "content": "…" } } ] } } }, … ]
      } } }
  ]
}
masters は 1 つ以上。slides は資料のスライドの順序で、空でもよい。ノートの欄が空なら、その要素に text が無い。
色の成分が 0 なら、その成分は無くてよい。`;

/** 色の 3 つの成分 (0〜1)。 */
export interface RgbColor {
  red: number;
  green: number;
  blue: number;
}

/** 読み込んだマスター。colors は、配色の種類 (DARK1・ACCENT1 など) ごとの色。 */
export interface PresentationMaster {
  objectId: string;
  colors: ReadonlyMap<string, RgbColor>;
}

/**
 * 読み込んだスライド。notesText はノートの欄の文 (textRun の content をつないだもの。Google スライドは末尾に改行を付ける)。
 * 要素に text が無ければ null。text があっても文を持たない (段落の始まりだけか、改行だけの) ことがあるので、
 * 欄が空かどうかは、この値ではなく末尾の改行を除いた文で決める (ファイル src/gslides/notes.ts。計画の KTD10)
 */
export interface PresentationSlide {
  objectId: string;
  notesObjectId: string;
  notesText: string | null;
}

/** 検査を通った読み込みの結果。slides の順序は、資料のスライドの順序。 */
export interface Presentation {
  revisionId: string;
  masters: PresentationMaster[];
  slides: PresentationSlide[];
}

export type ParsePresentationResult = { ok: true; presentation: Presentation } | { ok: false; errors: string[] };

type Json = Record<string, unknown>;

function isObject(v: unknown): v is Json {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** 読み込みの結果の検査。誤りは、場所 (JSON の中のパス) を付けてすべて集める */
class Checker {
  readonly errors: string[] = [];

  fail(path: string, message: string): void {
    this.errors.push(`${path}: ${message}`);
  }

  object(v: unknown, path: string): Json | null {
    if (isObject(v)) return v;
    this.fail(path, v === undefined ? "無い" : "オブジェクトではない");
    return null;
  }

  array(v: unknown, path: string): unknown[] | null {
    if (Array.isArray(v)) return v as unknown[];
    this.fail(path, v === undefined ? "無い" : "配列ではない");
    return null;
  }

  string(v: unknown, path: string): string | null {
    if (typeof v === "string" && v !== "") return v;
    this.fail(path, v === undefined ? "無い" : "空でない文字列ではない");
    return null;
  }
}

function parseColor(c: Checker, v: unknown, path: string): RgbColor | null {
  const o = c.object(v, path);
  if (o === null) return null;
  const color: RgbColor = { red: 0, green: 0, blue: 0 };
  let ok = true;
  for (const name of ["red", "green", "blue"] as const) {
    const value = o[name];
    // 成分が 0 のときは、読み込みの結果からその成分が除かれる (U11 の確認)
    if (value === undefined) continue;
    if (typeof value !== "number" || value < 0 || value > 1) {
      c.fail(`${path}.${name}`, "0〜1 の数ではない");
      ok = false;
      continue;
    }
    color[name] = value;
  }
  return ok ? color : null;
}

function parseMaster(c: Checker, v: unknown, path: string): PresentationMaster | null {
  const o = c.object(v, path);
  if (o === null) return null;
  const objectId = c.string(o["objectId"], `${path}.objectId`);
  const pageProperties = c.object(o["pageProperties"], `${path}.pageProperties`);
  const scheme = pageProperties === null ? null : c.object(pageProperties["colorScheme"], `${path}.pageProperties.colorScheme`);
  const list = scheme === null ? null : c.array(scheme["colors"], `${path}.pageProperties.colorScheme.colors`);
  if (objectId === null || list === null) return null;
  const colors = new Map<string, RgbColor>();
  list.forEach((item, i) => {
    const p = `${path}.pageProperties.colorScheme.colors[${String(i)}]`;
    const entry = c.object(item, p);
    if (entry === null) return;
    const type = c.string(entry["type"], `${p}.type`);
    const color = parseColor(c, entry["color"], `${p}.color`);
    if (type !== null && color !== null) colors.set(type, color);
  });
  return { objectId, colors };
}

/** ノートの欄の要素の text から、文をつないで返す。text が無ければ null */
function notesText(c: Checker, element: Json, path: string): string | null {
  const shape = c.object(element["shape"], `${path}.shape`);
  if (shape === null) return null;
  const text = shape["text"];
  if (text === undefined) return null;
  const body = c.object(text, `${path}.shape.text`);
  const elements = body === null ? null : c.array(body["textElements"], `${path}.shape.text.textElements`);
  if (elements === null) return null;
  // 段落の始まりを表す要素は、項目の指定で中身が除かれて {} になる (U11 の確認)。textRun を持つ要素だけをつなぐ
  return elements
    .map((e) => (isObject(e) && isObject(e["textRun"]) && typeof e["textRun"]["content"] === "string" ? e["textRun"]["content"] : ""))
    .join("");
}

function parseSlide(c: Checker, v: unknown, path: string): PresentationSlide | null {
  const o = c.object(v, path);
  if (o === null) return null;
  const objectId = c.string(o["objectId"], `${path}.objectId`);
  const props = c.object(o["slideProperties"], `${path}.slideProperties`);
  const notesPage = props === null ? null : c.object(props["notesPage"], `${path}.slideProperties.notesPage`);
  if (notesPage === null) return null;
  const notesPath = `${path}.slideProperties.notesPage`;
  const notesProperties = c.object(notesPage["notesProperties"], `${notesPath}.notesProperties`);
  const notesObjectId =
    notesProperties === null
      ? null
      : c.string(notesProperties["speakerNotesObjectId"], `${notesPath}.notesProperties.speakerNotesObjectId`);
  const elements = c.array(notesPage["pageElements"], `${notesPath}.pageElements`);
  if (objectId === null || notesObjectId === null || elements === null) return null;
  const index = elements.findIndex((e) => isObject(e) && e["objectId"] === notesObjectId);
  const element = elements[index];
  if (!isObject(element)) {
    c.fail(`${notesPath}.pageElements`, `ノートの欄の ID ${notesObjectId} を持つ要素が無い`);
    return null;
  }
  const text = notesText(c, element, `${notesPath}.pageElements[${String(index)}]`);
  return { objectId, notesObjectId, notesText: text };
}

/**
 * build/presentation.json の内容 (JSON.parse の結果) を検査する。
 * 形が違えば、場所を付けた誤りをすべて返す (表示するときは PRESENTATION_SHAPE を添える)
 */
export function parsePresentation(json: unknown): ParsePresentationResult {
  const c = new Checker();
  const root = c.object(json, "(全体)");
  if (root === null) return { ok: false, errors: c.errors };
  const revisionId = c.string(root["revisionId"], "revisionId");
  const masterList = c.array(root["masters"], "masters");
  if (masterList?.length === 0) c.fail("masters", "空 (マスターが 1 つ以上要る)");
  const slideList = c.array(root["slides"], "slides");
  const masters = (masterList ?? []).map((m, i) => parseMaster(c, m, `masters[${String(i)}]`));
  const slides = (slideList ?? []).map((s, i) => parseSlide(c, s, `slides[${String(i)}]`));
  const ids = new Set<string>();
  for (const [i, s] of slides.entries()) {
    if (s === null) continue;
    if (ids.has(s.objectId)) c.fail(`slides[${String(i)}].objectId`, `スライドの ID ${s.objectId} が 2 回ある`);
    ids.add(s.objectId);
  }
  if (c.errors.length > 0 || revisionId === null) return { ok: false, errors: c.errors };
  return {
    ok: true,
    presentation: {
      revisionId,
      masters: masters.filter((m) => m !== null),
      slides: slides.filter((s) => s !== null),
    },
  };
}
