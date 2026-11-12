// 構成案 outline.md を読み、資料の情報とスライドごとのキー・題名・一言・図の説明・発表者ノートを取り出す (計画の KTD13)。
// 書式に合わない行は、行番号を付けた誤りにする。最初の誤りで中断せず、すべての誤りを集めてから返す。
//
// 構成案の書式:
//
//   # <資料の題名>
//
//   - 読者: <値>
//   - ねらい: <値>
//   - 形: <値>
//   - 固有名: 一般化する | そのまま書く          (省略できる)
//   - Google スライド: <資料の URL>               (省略できる)
//   - slide-deck の版: <数.数.数>                 (省略できる)
//
//   ## <章の名前>                                  (省略できる)
//
//   ### <キー>: <題名>
//   - 図: <図の説明>
//     <字下げした行も、図の説明に含める>
//   - 一言: <そのスライドで伝えたいことの 1 文>
//
//   <発表者ノートの段落>
//
// - 題名の行の前と、資料の情報の行の間には、空行だけを書ける。
// - 採否を利用者に質問するスライドは、見出しを ### 【提案】<キー>: <題名> にする (計画の R3)。
// - キーは英小文字・数字・ハイフンの 1〜32 文字 (計画の KTD9)。資料の中で 1 つにする。
// - スライドの見出しの下には、まず - 図: と - 一言: の行を 1 回ずつ書く。ほかの項目は書けない。
// - 箇条書きの後に空行を 1 行以上空けて、発表者ノートの段落を書く。ノートは省略できる。
//   ノートは地の文だけにする。- で始まる行と字下げした行は書けない。
// - 章は省略できる。章を書くなら、スライドを 1 枚以上入れる。
// - 区切りの線 (---) は、どこにも書けない。
// - #### 以下の見出しは書けない。

/** 構成案の書式の誤り。line は 1 から数えた行番号。 */
export interface OutlineError {
  line: number;
  message: string;
}

/** 誤りを「<行番号> 行目: <内容>」の形の 1 行にする。 */
export function formatOutlineError(e: OutlineError): string {
  return `${String(e.line)} 行目: ${e.message}`;
}

/** 資料の情報の項目「固有名」の値 (計画の R4)。 */
export type ProperNouns = "一般化する" | "そのまま書く";

const PROPER_NOUNS: readonly ProperNouns[] = ["一般化する", "そのまま書く"];

/** 資料の情報の項目「Google スライド」の値。presentationId は URL の /d/ の後の、資料の ID。 */
export interface GoogleSlidesRef {
  url: string;
  presentationId: string;
}

/** 構成案の先頭の、資料の情報。省略できる項目は、書いていなければ null。 */
export interface OutlineInfo {
  /** 読者 */
  audience: string;
  /** ねらい */
  purpose: string;
  /** 形 */
  form: string;
  /** 固有名 */
  properNouns: ProperNouns | null;
  /** Google スライド */
  googleSlides: GoogleSlidesRef | null;
  /** slide-deck の版 (最後に publish したプラグインの版) */
  pluginVersion: string | null;
}

/** 構成案の 1 枚のスライド。 */
export interface OutlineSlide {
  key: string;
  title: string;
  /** 一言 */
  takeaway: string;
  /** 図の説明。- 図: の行の後の字下げした行も、改行で区切って含める。 */
  figure: string;
  /** 発表者ノート。段落の中の改行は残し、段落の間は空行 1 つ (\n\n) にする。ノートが無ければ空の文字列。 */
  notes: string;
  /** スライドが入っている章の名前。章の外なら null。 */
  chapter: string | null;
  /** 見出しに【提案】が付いているか。 */
  proposed: boolean;
  /** スライドの見出しの行番号 (1 から数える)。 */
  line: number;
}

/** 読み込んだ構成案。slides の順序は構成案の見出しの順序。 */
export interface DeckOutline {
  title: string;
  info: OutlineInfo;
  slides: OutlineSlide[];
  /** 【提案】が付いたスライド。build は、これが空でなければ中断する (計画の R3)。 */
  proposals: OutlineSlide[];
}

export type ParseOutlineResult =
  | { ok: true; outline: DeckOutline }
  | { ok: false; errors: OutlineError[] };

/** 資料の情報の項目の名前と、型 OutlineInfo のプロパティの名前の対応。 */
export const INFO_LABELS = {
  audience: "読者",
  purpose: "ねらい",
  form: "形",
  properNouns: "固有名",
  googleSlides: "Google スライド",
  pluginVersion: "slide-deck の版",
} as const;

type InfoField = keyof typeof INFO_LABELS;

const INFO_FIELDS = Object.keys(INFO_LABELS) as InfoField[];
const REQUIRED_FIELDS: readonly InfoField[] = ["audience", "purpose", "form"];

const GOOGLE_SLIDES_URL = /^https:\/\/docs\.google\.com\/presentation\/d\/([A-Za-z0-9_-]+)(?:[/?#]\S*)?$/;
const PLUGIN_VERSION = /^\d+\.\d+\.\d+$/;
const KEY = /^[a-z0-9-]{1,32}$/;
const HEADING = /^(#{1,6})(?:[ \t]+(.*))?$/;
const INFO_ITEM = /^- ([^:]+?):[ \t]*(.*)$/;
const THEMATIC_BREAK = /^-{3,}[ \t]*$/;
const INDENTED = /^[ \t]+\S/;

/**
 * 資料の情報の項目「Google スライド」の値を検査し、資料の ID を取り出す。
 * 形が違えば、誤りの内容を文字列で返す。
 */
export function parseGoogleSlidesUrl(value: string): GoogleSlidesRef | string {
  const m = GOOGLE_SLIDES_URL.exec(value);
  const id = m?.[1];
  if (id === undefined) {
    return `Google スライドの値 ${JSON.stringify(value)} が、https://docs.google.com/presentation/d/<資料の ID> で始まる URL ではない`;
  }
  return { url: value, presentationId: id };
}

/** 資料の情報の項目「slide-deck の版」の値を検査する。形が違えば、誤りの内容を文字列で返す。 */
export function checkPluginVersion(value: string): string | null {
  return PLUGIN_VERSION.test(value)
    ? null
    : `slide-deck の版の値 ${JSON.stringify(value)} が、数.数.数 (例: 0.1.0) の形ではない`;
}

/** 構成案のテキストを行に分ける。各行の末尾の \r は除く。 */
export function splitLines(text: string): string[] {
  return text.split("\n").map((l) => l.replace(/\r$/, ""));
}

/** 関数 scanHeader の結果。行の位置 (index) は 0 から数える。 */
export interface HeaderScan {
  /** 資料の題名。題名の行に誤りがあれば null。 */
  title: string | null;
  /** 資料の情報。題名の行か資料の情報の行に誤りがあれば null。 */
  info: OutlineInfo | null;
  /** 資料の情報の項目ごとの行の位置。 */
  itemIndex: Partial<Record<InfoField, number>>;
  /** 資料の情報の最後の項目の行の位置。項目が無ければ null。 */
  lastItemIndex: number | null;
  /** 題名と資料の情報の後の、最初の見出しの行の位置。見出しが無ければ行の数。 */
  end: number;
  errors: OutlineError[];
}

/**
 * 題名の行と資料の情報の行を読む。スライドの部分は読まない。
 * 関数 parseOutline と、資料の情報の行を書き込むファイル url.ts が使う。
 */
export function scanHeader(lines: readonly string[]): HeaderScan {
  const errors: OutlineError[] = [];
  const err = (index: number, message: string): void => {
    errors.push({ line: index + 1, message });
  };
  let i = 0;
  while (i < lines.length && (lines[i] ?? "").trim() === "") i++;
  let title: string | null = null;
  let titleIndex = 0;
  const first = lines[i];
  if (first === undefined) {
    err(0, "題名の行 (# <資料の題名>) が無い");
  } else {
    titleIndex = i;
    const m = HEADING.exec(first);
    const heading = m?.[1];
    const text = (m?.[2] ?? "").trim();
    if (heading === "#" && text !== "") {
      title = text;
      i++;
    } else {
      err(i, "最初の行は、題名の行 (# <資料の題名>) にする");
      // 題名が空の # の行だけは、題名の行として読み終える。
      // ほかの行は、資料の情報の行か、スライドの部分の始まりとして、次の処理で読む
      if (heading === "#") i++;
    }
  }

  const values: Partial<Record<InfoField, string>> = {};
  const itemIndex: Partial<Record<InfoField, number>> = {};
  let lastItemIndex: number | null = null;
  for (; i < lines.length; i++) {
    const line = lines[i] ?? "";
    if (HEADING.test(line)) break;
    if (line.trim() === "") continue;
    if (THEMATIC_BREAK.test(line)) {
      err(i, "区切りの線 (---) は書けない");
      continue;
    }
    const m = INFO_ITEM.exec(line);
    const label = m?.[1];
    if (m === null || label === undefined) {
      err(i, "資料の情報の行は、- <項目>: <値> の形にする");
      continue;
    }
    const field = INFO_FIELDS.find((f) => INFO_LABELS[f] === label);
    if (field === undefined) {
      const names = INFO_FIELDS.map((f) => INFO_LABELS[f]).join("・");
      err(i, `資料の情報の項目 ${JSON.stringify(label)} は使えない。使える項目は ${names}`);
      continue;
    }
    lastItemIndex = i;
    const prev = itemIndex[field];
    if (prev !== undefined) {
      err(i, `資料の情報の項目 ${label} が ${String(prev + 1)} 行目と ${String(i + 1)} 行目にある。1 回だけ書く`);
      continue;
    }
    itemIndex[field] = i;
    const value = (m[2] ?? "").trim();
    if (value === "") {
      err(i, `資料の情報の項目 ${label} の値が空`);
      continue;
    }
    values[field] = value;
  }
  const end = i;

  for (const f of REQUIRED_FIELDS) {
    if (itemIndex[f] === undefined) err(titleIndex, `資料の情報に、項目 ${INFO_LABELS[f]} の行が無い`);
  }

  let properNouns: ProperNouns | null = null;
  const pn = values.properNouns;
  if (pn !== undefined) {
    const found = PROPER_NOUNS.find((v) => v === pn);
    if (found === undefined) {
      err(itemIndex.properNouns ?? titleIndex, `固有名の値 ${JSON.stringify(pn)} は使えない。「一般化する」か「そのまま書く」にする`);
    } else {
      properNouns = found;
    }
  }
  let googleSlides: GoogleSlidesRef | null = null;
  if (values.googleSlides !== undefined) {
    const r = parseGoogleSlidesUrl(values.googleSlides);
    if (typeof r === "string") err(itemIndex.googleSlides ?? titleIndex, r);
    else googleSlides = r;
  }
  const pluginVersion = values.pluginVersion ?? null;
  if (pluginVersion !== null) {
    const e = checkPluginVersion(pluginVersion);
    if (e !== null) err(itemIndex.pluginVersion ?? titleIndex, e);
  }

  const { audience, purpose, form } = values;
  const info =
    errors.length === 0 && audience !== undefined && purpose !== undefined && form !== undefined
      ? { audience, purpose, form, properNouns, googleSlides, pluginVersion }
      : null;
  return { title, info, itemIndex, lastItemIndex, end, errors };
}

/** 読んでいる途中のスライド。 */
interface SlideDraft {
  /** 見出しの形が正しければキー。誤りがあれば null (誤りは見出しの行で報告済み)。 */
  key: string | null;
  title: string;
  proposed: boolean;
  chapter: string | null;
  index: number;
  figureIndex: number | null;
  figure: string[];
  takeawayIndex: number | null;
  takeaway: string;
  /** 箇条書きの最後の項目。字下げした行を、どの項目に含めるかを決める。 */
  lastItem: "figure" | "takeaway" | "other" | null;
  /** 箇条書きの後の空行を読んだか (読んだら、以降の行はノート)。 */
  inNotes: boolean;
  paragraphs: string[][];
}

/** 構成案のテキストを読む。誤りがあれば、すべての誤りを行番号の順に返す。 */
export function parseOutline(text: string): ParseOutlineResult {
  const lines = splitLines(text);
  const header = scanHeader(lines);
  const errors: OutlineError[] = [...header.errors];
  const err = (index: number, message: string): void => {
    errors.push({ line: index + 1, message });
  };

  const slides: OutlineSlide[] = [];
  const keyIndex = new Map<string, number>();
  let chapter: { name: string | null; index: number; slides: number } | null = null;
  let draft: SlideDraft | null = null;
  let slideHeadings = 0;

  const finishSlide = (): void => {
    if (draft === null) return;
    const d = draft;
    draft = null;
    if (d.figureIndex === null) err(d.index, "スライドに - 図: の行が無い");
    if (d.takeawayIndex === null) err(d.index, "スライドに - 一言: の行が無い");
    if (d.figureIndex !== null && d.figure.length === 0) err(d.figureIndex, "図の説明が空");
    if (d.key === null || d.figureIndex === null || d.takeawayIndex === null) return;
    slides.push({
      key: d.key,
      title: d.title,
      takeaway: d.takeaway,
      figure: d.figure.join("\n"),
      notes: d.paragraphs
        .filter((p) => p.length > 0)
        .map((p) => p.join("\n"))
        .join("\n\n"),
      chapter: d.chapter,
      proposed: d.proposed,
      line: d.index + 1,
    });
  };
  const finishChapter = (): void => {
    if (chapter !== null && chapter.slides === 0) err(chapter.index, "章にスライドが 1 枚も無い");
    chapter = null;
  };

  for (let i = header.end; i < lines.length; i++) {
    const line = lines[i] ?? "";
    const heading = HEADING.exec(line);
    if (heading !== null) {
      finishSlide();
      const level = (heading[1] ?? "").length;
      const content = (heading[2] ?? "").trim();
      if (level === 1) {
        err(i, "題名の行 (# <資料の題名>) は 1 つだけにする");
      } else if (level === 2) {
        finishChapter();
        if (content === "") err(i, "章の見出しの名前が空");
        chapter = { name: content === "" ? null : content, index: i, slides: 0 };
      } else if (level === 3) {
        slideHeadings++;
        if (chapter !== null) chapter.slides++;
        draft = startSlide(content, i, chapter?.name ?? null, err);
        if (draft.key !== null) {
          const prev = keyIndex.get(draft.key);
          if (prev === undefined) {
            keyIndex.set(draft.key, i);
          } else {
            err(i, `キー ${draft.key} が ${String(prev + 1)} 行目と ${String(i + 1)} 行目にある。キーは資料の中で 1 つにする`);
          }
        }
      } else {
        err(i, "見出しは #・##・### だけにする");
      }
      continue;
    }
    if (THEMATIC_BREAK.test(line)) {
      err(i, "区切りの線 (---) は書けない");
      continue;
    }
    if (draft === null) {
      if (line.trim() !== "") err(i, "章の見出しとスライドの見出しの間には、文を書けない");
      continue;
    }
    readSlideLine(draft, line, i, err);
  }
  finishSlide();
  finishChapter();
  if (slideHeadings === 0) {
    err(Math.min(header.end, lines.length - 1), "スライドの見出し (### <キー>: <題名>) が 1 つも無い");
  }

  if (errors.length > 0 || header.title === null || header.info === null) {
    return { ok: false, errors: errors.sort((a, b) => a.line - b.line) };
  }
  return {
    ok: true,
    outline: {
      title: header.title,
      info: header.info,
      slides,
      proposals: slides.filter((s) => s.proposed),
    },
  };
}

const PROPOSAL = "【提案】";

/** スライドの見出しの内容 (### の後) を読み、読んでいる途中のスライドを作る。 */
function startSlide(
  content: string,
  index: number,
  chapter: string | null,
  err: (index: number, message: string) => void,
): SlideDraft {
  const proposed = content.startsWith(PROPOSAL);
  const rest = proposed ? content.slice(PROPOSAL.length) : content;
  const colon = rest.indexOf(":");
  let key: string | null = null;
  let title = "";
  if (colon < 0) {
    err(index, "スライドの見出しは ### <キー>: <題名> の形にする");
  } else {
    const k = rest.slice(0, colon);
    title = rest.slice(colon + 1).trim();
    if (!KEY.test(k)) {
      err(
        index,
        `キー ${JSON.stringify(k)} は使えない。キーは英小文字・数字・ハイフンの 1〜32 文字にする`,
      );
    } else if (title === "") {
      err(index, `スライド ${k} の題名が空`);
    } else {
      key = k;
    }
  }
  return {
    key,
    title,
    proposed,
    chapter,
    index,
    figureIndex: null,
    figure: [],
    takeawayIndex: null,
    takeaway: "",
    lastItem: null,
    inNotes: false,
    paragraphs: [],
  };
}

const SLIDE_ITEM = /^- (図|一言):[ \t]*(.*)$/;

/** スライドの見出しの後の 1 行を読む。 */
function readSlideLine(
  d: SlideDraft,
  line: string,
  index: number,
  err: (index: number, message: string) => void,
): void {
  const blank = line.trim() === "";
  if (!d.inNotes) {
    const hasItems = d.lastItem !== null;
    if (blank) {
      // 箇条書きの後の空行から、ノートが始まる。見出しと箇条書きの間の空行は読み飛ばす
      if (hasItems) d.inNotes = true;
      return;
    }
    if (line.startsWith("- ")) {
      readSlideItem(d, line, index, err);
      return;
    }
    if (INDENTED.test(line)) {
      if (d.lastItem === "figure") d.figure.push(line.trimEnd());
      else if (d.lastItem === "takeaway") err(index, "一言は 1 行で書く");
      else if (d.lastItem === null) err(index, "字下げした行は、- 図: の行の後にだけ書ける");
      // d.lastItem が "other" なら、その項目の行で誤りを報告済み
      return;
    }
    if (hasItems) err(index, "発表者ノートの前に、空行を入れる");
    d.inNotes = true;
  }
  if (blank) {
    if ((d.paragraphs.at(-1)?.length ?? 0) > 0) d.paragraphs.push([]);
    return;
  }
  if (line.startsWith("- ")) {
    err(index, "発表者ノートに、- で始まる行は書けない。図の説明は、- 図: の行の後の字下げした行に書く");
    return;
  }
  if (INDENTED.test(line)) {
    err(index, "発表者ノートの行は、字下げしない");
    return;
  }
  const last = d.paragraphs.at(-1);
  if (last === undefined) d.paragraphs.push([line.trimEnd()]);
  else last.push(line.trimEnd());
}

/** スライドの見出しの下の、- で始まる項目の行を読む。 */
function readSlideItem(
  d: SlideDraft,
  line: string,
  index: number,
  err: (index: number, message: string) => void,
): void {
  const m = SLIDE_ITEM.exec(line);
  const name = m?.[1];
  const value = (m?.[2] ?? "").trim();
  if (name === "図") {
    d.lastItem = "figure";
    if (d.figureIndex !== null) {
      err(index, `- 図: の行が ${String(d.figureIndex + 1)} 行目にもある。複数の図は、字下げした行で書く`);
      return;
    }
    d.figureIndex = index;
    if (value !== "") d.figure.push(value);
    return;
  }
  if (name === "一言") {
    d.lastItem = "takeaway";
    if (d.takeawayIndex !== null) {
      err(index, `- 一言: の行が ${String(d.takeawayIndex + 1)} 行目にもある`);
      return;
    }
    d.takeawayIndex = index;
    if (value === "") err(index, "一言が空");
    d.takeaway = value;
    return;
  }
  d.lastItem = "other";
  err(index, "スライドの見出しの下の項目は、- 図: と - 一言: だけにする。補足は発表者ノートに書く");
}
