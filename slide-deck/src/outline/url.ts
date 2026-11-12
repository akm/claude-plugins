// 構成案の資料の情報に、Google スライドの URL の行と slide-deck の版の行を書き込む (計画の R15・KTD10)。
// 書き込む行のほかは、1 文字も変えない (改行の文字・最後の改行の有無も含む)。
// publish は空の資料を作った直後に URL を書き込むので、スライドの部分に書式の誤りがあっても書き込む。
// 検査するのは、題名の行と資料の情報の行だけにする。

import {
  checkPluginVersion,
  formatOutlineError,
  INFO_LABELS,
  parseGoogleSlidesUrl,
  scanHeader,
} from "./parse.ts";

/** 書き込みの結果。誤りがあれば、構成案のテキストは変えずに、誤りの配列を返す。 */
export type WriteInfoResult = { ok: true; text: string } | { ok: false; errors: string[] };

/**
 * Google スライドの URL の行を書き込む。
 * 行が無ければ資料の情報の最後に 1 行を足し、あれば、その行だけを置き換える。
 */
export function writeGoogleSlidesUrl(text: string, url: string): WriteInfoResult {
  const ref = parseGoogleSlidesUrl(url);
  if (typeof ref === "string") return { ok: false, errors: [ref] };
  return writeItem(text, "googleSlides", url);
}

/**
 * slide-deck の版の行を書き込む。
 * 行が無ければ資料の情報の最後に 1 行を足し、あれば、その行だけを置き換える。
 */
export function writePluginVersion(text: string, version: string): WriteInfoResult {
  const e = checkPluginVersion(version);
  if (e !== null) return { ok: false, errors: [e] };
  return writeItem(text, "pluginVersion", version);
}

function writeItem(
  text: string,
  field: "googleSlides" | "pluginVersion",
  value: string,
): WriteInfoResult {
  // 改行の文字を行に残して分ける。関数 scanHeader に渡す行 (改行の文字を除いたもの) と、位置が同じになる
  const parts = text.split(/(?<=\n)/);
  const header = scanHeader(parts.map((p) => p.replace(/\r?\n$/, "")));
  if (header.errors.length > 0) return { ok: false, errors: header.errors.map(formatOutlineError) };
  const line = `- ${INFO_LABELS[field]}: ${value}`;
  const existing = header.itemIndex[field];
  if (existing !== undefined) {
    const old = parts[existing] ?? "";
    parts[existing] = line + lineEnding(old);
    return { ok: true, text: parts.join("") };
  }
  // 誤りが無ければ必須の項目の行があるので、資料の情報の最後の行は必ずある
  const last = header.lastItemIndex;
  if (last === null) throw new Error("誤りの無い資料の情報に、項目の行が無い");
  const lastPart = parts[last] ?? "";
  const ending = lineEnding(lastPart);
  if (ending === "") {
    // 資料の情報の最後の行がファイルの最後の行で、改行が無い。改行を足してから行を足し、最後に改行が無い形を保つ
    parts[last] = lastPart + (text.includes("\r\n") ? "\r\n" : "\n");
    parts.splice(last + 1, 0, line);
  } else {
    parts.splice(last + 1, 0, line + ending);
  }
  return { ok: true, text: parts.join("") };
}

/** 行の末尾の改行の文字 (\r\n・\n・無し)。 */
function lineEnding(part: string): string {
  if (part.endsWith("\r\n")) return "\r\n";
  if (part.endsWith("\n")) return "\n";
  return "";
}
