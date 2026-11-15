// 資料のディレクトリの構成案 outline.md だけを扱う入口の処理 (サブコマンド check-outline と write-info。計画の KTD17)。
// check-outline は、deck.ts とライブラリが無くても、構成案の書式を検査できるようにする (スキル outline が使う)。
// write-info は、資料の情報に Google スライドの URL の行と slide-deck の版の行を書き込む (スキル publish が使う。計画の R15・KTD10)。

import { existsSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { ExecutionError } from "../check/deck.ts";
import { PLUGIN_DIR } from "../setup/setup.ts";
import { checkPluginVersion, type DeckOutline, formatOutlineError, INFO_LABELS, parseGoogleSlidesUrl, parseOutline } from "./parse.ts";
import { writeGoogleSlidesUrl, writePluginVersion } from "./url.ts";

/** 資料のディレクトリの outline.md のパスを求める。ディレクトリか outline.md が無ければ ExecutionError を送出する */
export function outlinePath(deckDir: string): string {
  const dir = resolve(deckDir);
  if (!existsSync(dir) || !statSync(dir).isDirectory()) {
    throw new ExecutionError(`資料のディレクトリ ${dir} が無い`);
  }
  const path = join(dir, "outline.md");
  if (!existsSync(path)) throw new ExecutionError(`資料のディレクトリに、構成案 ${path} が無い`);
  return path;
}

/** プラグインのファイル .claude-plugin/plugin.json の版を読む。読めないか形が違えば ExecutionError を送出する */
export function pluginVersion(pluginDir: string = PLUGIN_DIR): string {
  const path = join(pluginDir, ".claude-plugin", "plugin.json");
  let version: unknown;
  try {
    const json: unknown = JSON.parse(readFileSync(path, "utf8"));
    version = typeof json === "object" && json !== null && "version" in json ? json.version : undefined;
  } catch (e) {
    throw new ExecutionError(`プラグインの ${path} を読めない: ${e instanceof Error ? e.message : String(e)}`);
  }
  if (typeof version !== "string" || checkPluginVersion(version) !== null) {
    throw new ExecutionError(`プラグインの ${path} の version が、数.数.数 の形の文字列ではない`);
  }
  return version;
}

/** サブコマンド check-outline の結果。誤りが無ければ outline に読み込んだ構成案があり、誤りがあれば outline は null */
export interface OutlineCheckReport {
  readonly errors: readonly string[];
  readonly outline: DeckOutline | null;
  /** このプラグインの版 */
  readonly currentVersion: string;
}

/** 資料のディレクトリの構成案を読み、書式を検査する */
export function checkOutlineFile(deckDir: string, pluginDir: string = PLUGIN_DIR): OutlineCheckReport {
  const path = outlinePath(deckDir);
  const currentVersion = pluginVersion(pluginDir);
  const parsed = parseOutline(readFileSync(path, "utf8"));
  if (!parsed.ok) return { errors: parsed.errors.map(formatOutlineError), outline: null, currentVersion };
  return { errors: [], outline: parsed.outline, currentVersion };
}

/** サブコマンド check-outline の結果を、利用者に示す文字列にする */
export function formatOutlineCheckReport(report: OutlineCheckReport): string {
  if (report.outline === null) {
    return `構成案 outline.md の書式の誤り:\n${report.errors.map((e) => `  ${e}`).join("\n")}\n`;
  }
  const { info, slides, proposals } = report.outline;
  const lines = [`構成案の書式の誤りは無い (スライド ${String(slides.length)} 枚)`];
  lines.push(
    info.googleSlides === null
      ? `${INFO_LABELS.googleSlides}: 無い`
      : `${INFO_LABELS.googleSlides}: ${info.googleSlides.url} (資料の ID: ${info.googleSlides.presentationId})`,
  );
  lines.push(`${INFO_LABELS.pluginVersion}: ${info.pluginVersion ?? "無い"} (今の版: ${report.currentVersion})`);
  lines.push(`${INFO_LABELS.properNouns}: ${info.properNouns ?? "無い"}`);
  if (proposals.length > 0) {
    lines.push("【提案】が付いたスライド (採否を利用者に質問する):");
    for (const s of proposals) lines.push(`  ${String(s.line)} 行目: ${s.key}: ${s.title}`);
  }
  return `${lines.join("\n")}\n`;
}

/** サブコマンド write-info に渡す、書き込む項目。どちらも省略できるが、少なくとも 1 つを指定する */
export interface WriteInfoRequest {
  /** Google スライドの URL */
  readonly googleSlides?: string;
  /** true なら、このプラグインの版を書き込む */
  readonly pluginVersion?: boolean;
}

/** サブコマンド write-info の結果。書き込めたら written に書き込んだ行があり、資料の情報に誤りがあれば errors にある */
export type WriteInfoReport = { ok: true; written: string[] } | { ok: false; errors: string[] };

/**
 * 資料のディレクトリの構成案の資料の情報に、Google スライドの URL の行と slide-deck の版の行を書き込む。
 * 書き込む行のほかは変えない。題名の行か資料の情報の行に誤りがあれば、ファイルを変えずに誤りを返す。
 * URL の形が違うときは、引数の誤りなので ExecutionError を送出する
 */
export function writeOutlineInfo(
  deckDir: string,
  request: WriteInfoRequest,
  pluginDir: string = PLUGIN_DIR,
): WriteInfoReport {
  const path = outlinePath(deckDir);
  if (request.googleSlides !== undefined) {
    const ref = parseGoogleSlidesUrl(request.googleSlides);
    if (typeof ref === "string") throw new ExecutionError(ref);
  }
  const version = request.pluginVersion === true ? pluginVersion(pluginDir) : undefined;
  let text = readFileSync(path, "utf8");
  const written: string[] = [];
  if (request.googleSlides !== undefined) {
    const r = writeGoogleSlidesUrl(text, request.googleSlides);
    if (!r.ok) return { ok: false, errors: r.errors };
    text = r.text;
    written.push(`- ${INFO_LABELS.googleSlides}: ${request.googleSlides}`);
  }
  if (version !== undefined) {
    const r = writePluginVersion(text, version);
    if (!r.ok) return { ok: false, errors: r.errors };
    text = r.text;
    written.push(`- ${INFO_LABELS.pluginVersion}: ${version}`);
  }
  // 両方の行を作り終えてから 1 回だけ書く。片方だけが書き込まれた状態を残さない
  writeFileSync(path, text);
  return { ok: true, written };
}
