// 資料ごとのスクリプト deck.ts と構成案 outline.md を検査し、スライドのデータを作る (入口のサブコマンド check。計画の R9・R10・R13・U5)。
// tsc と eslint は、キャッシュの node_modules/.bin のものを、子プロセスで実行する (計画の KTD8)。
// 入口のサブコマンド check の引数・出力・終了コードの SSOT は、ファイル src/cli.ts の --help。

import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, realpathSync, statSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { parts } from "../data/parts.ts";
import { checkTheme } from "../data/theme.ts";
import type { Deck } from "../data/types.ts";
import { estimateSlides, type FitIssue } from "../fit/estimate.ts";
import type { DeckScript, DeckScriptResult } from "../index.ts";
import { hasMismatch, matchKeys } from "../outline/match.ts";
import { type DeckOutline, formatOutlineError, parseOutline } from "../outline/parse.ts";
import { type CachePaths, cachePaths, nodeState, PLUGIN_DIR, SPAWN_MAX_BUFFER } from "../setup/setup.ts";

/** 実行の誤り (資料のディレクトリやファイルが無い・ライブラリが入っていない・ツールを実行できないなど)。入口は終了コード 2 にする */
export class ExecutionError extends Error {
  override name = "ExecutionError";
}

/** 検査の関数の共通の引数。テストは、プラグインのディレクトリと環境変数を差し替える */
export interface CheckOptions {
  /** プラグインのディレクトリ。省略すると、このファイルのあるプラグイン */
  readonly pluginDir?: string;
  /** 環境変数 (キャッシュのディレクトリを読み、tsc と eslint に渡す)。省略すると process.env */
  readonly env?: NodeJS.ProcessEnv;
}

/** 資料のディレクトリの中のファイルのパス */
export interface DeckPaths {
  readonly deckDir: string;
  /** 構成案 outline.md */
  readonly outline: string;
  /** 資料ごとのスクリプト deck.ts */
  readonly script: string;
  /** 生成したファイルを書き込むディレクトリ build/ */
  readonly buildDir: string;
  /** build/.gitignore (計画の KTD15) */
  readonly gitignore: string;
  /** build/tsconfig.json (計画の KTD2) */
  readonly tsconfig: string;
  /** build/deck-type.ts (deck.ts の default export の型を tsc で検査するファイル) */
  readonly typeCheck: string;
}

/**
 * 資料のディレクトリの中のファイルのパスを求める。ディレクトリか、outline.md・deck.ts が無ければ ExecutionError を送出する。
 * パスは、シンボリックリンクをたどった実際のパスにする。eslint は、--config を指定すると作業ディレクトリ (実際のパス) の外の
 * ファイルを検査しないので、資料のディレクトリのパスがシンボリックリンクを含むと (macOS の /var と /private/var など)、
 * deck.ts を検査の対象の外として扱うため
 */
export function deckPaths(deckDir: string): DeckPaths {
  const given = resolve(deckDir);
  if (!existsSync(given) || !statSync(given).isDirectory()) {
    throw new ExecutionError(`資料のディレクトリ ${given} が無い`);
  }
  const dir = realpathSync(given);
  const buildDir = join(dir, "build");
  const paths: DeckPaths = {
    deckDir: dir,
    outline: join(dir, "outline.md"),
    script: join(dir, "deck.ts"),
    buildDir,
    gitignore: join(buildDir, ".gitignore"),
    tsconfig: join(buildDir, "tsconfig.json"),
    typeCheck: join(buildDir, "deck-type.ts"),
  };
  const missing = [paths.outline, paths.script].filter((p) => !existsSync(p));
  if (missing.length > 0) {
    throw new ExecutionError(`資料のディレクトリに、次のファイルが無い:\n${missing.map((p) => `  ${p}`).join("\n")}`);
  }
  return paths;
}

/**
 * キャッシュのディレクトリのパスを求め、node_modules が入っていることを確認する。入っていなければ ExecutionError を送出する
 */
export function installedCache(options: CheckOptions = {}): CachePaths {
  const paths = cachePaths({ pluginDir: options.pluginDir ?? PLUGIN_DIR, env: options.env ?? process.env });
  if (nodeState(paths) !== "installed") {
    throw new ExecutionError(
      `ライブラリ (node_modules) が、キャッシュのディレクトリ ${paths.nodeModulesDir} に入っていない。` +
        "サブコマンド setup status で状態を確認し、setup install で入れる",
    );
  }
  return paths;
}

// build/deck-type.ts の内容。deck.ts に default export が無いときや、型 DeckScript に合わないときに、tsc が指摘する
const TYPE_CHECK_SOURCE = `// プラグイン slide-deck のサブコマンド check が書くファイル。
// 資料ごとのスクリプト deck.ts の default export が、型 DeckScript であることを tsc で検査する。
import type { DeckScript } from "slide-deck";
import deck from "../deck.ts";

deck satisfies DeckScript;
`;

/**
 * 資料のディレクトリに build/ を作り、.gitignore・tsconfig.json・deck-type.ts を書く (計画の KTD2・KTD15)。
 * tsconfig.json は、プラグインの tsconfig.json の compilerOptions を使い、名前 slide-deck をプラグインの型に対応させる。
 * 型の定義は、types を空にして、資料のディレクトリより上にある @types を読み込まない
 * (資料ごとのスクリプトは、Node.js の機能を使わず、部品の関数でスライドのデータを作るだけにするため)。
 */
export function prepareBuildDir(paths: DeckPaths, pluginDir: string = PLUGIN_DIR): void {
  mkdirSync(paths.buildDir, { recursive: true });
  // 生成したファイルが、プロジェクトのコミットに入らないようにする。プロジェクトの .gitignore は変えない
  writeFileSync(paths.gitignore, "*\n");
  const pluginTsconfig: unknown = JSON.parse(readFileSync(join(pluginDir, "tsconfig.json"), "utf8"));
  if (typeof pluginTsconfig !== "object" || pluginTsconfig === null || !("compilerOptions" in pluginTsconfig)) {
    throw new ExecutionError(`プラグインの ${join(pluginDir, "tsconfig.json")} に compilerOptions が無い`);
  }
  const base: unknown = pluginTsconfig.compilerOptions;
  if (typeof base !== "object" || base === null) {
    throw new ExecutionError(`プラグインの ${join(pluginDir, "tsconfig.json")} の compilerOptions がオブジェクトではない`);
  }
  const tsconfig = {
    compilerOptions: {
      ...base,
      types: [],
      paths: { "slide-deck": [join(pluginDir, "src", "index.ts")] },
    },
    files: ["../deck.ts", "deck-type.ts"],
  };
  writeFileSync(paths.tsconfig, `${JSON.stringify(tsconfig, null, 2)}\n`);
  writeFileSync(paths.typeCheck, TYPE_CHECK_SOURCE);
}

/** tsc か eslint の実行の結果。ok が false なら、output に指摘がある */
export interface ToolResult {
  readonly ok: boolean;
  readonly output: string;
}

/**
 * キャッシュの node_modules/.bin のツールを、いまの Node.js で実行する。
 * 終了コードが okCodes なら成功、findingCodes なら指摘あり、それ以外と起動の失敗は ExecutionError にする
 */
function runBin(
  cache: CachePaths,
  name: string,
  args: readonly string[],
  cwd: string,
  env: NodeJS.ProcessEnv,
  findingCodes: readonly number[],
): ToolResult {
  const bin = join(cache.nodeModulesDir, ".bin", name);
  const r = spawnSync(process.execPath, [bin, ...args], { cwd, env, encoding: "utf8", maxBuffer: SPAWN_MAX_BUFFER });
  if (r.error !== undefined) {
    throw new ExecutionError(`${name} を実行できない (${bin}): ${r.error.message}`);
  }
  const output = `${r.stdout}${r.stderr}`.trimEnd();
  if (r.status === 0) return { ok: true, output };
  if (r.status !== null && findingCodes.includes(r.status)) return { ok: false, output };
  throw new ExecutionError(
    `${name} が終了コード ${String(r.status)} (シグナル ${String(r.signal)}) で終了した (${bin}):\n${output}`,
  );
}

/** tsc で、build/tsconfig.json の資料ごとのスクリプトを検査する */
export function typeCheck(paths: DeckPaths, cache: CachePaths, env: NodeJS.ProcessEnv): ToolResult {
  // tsc は、型の誤りがあれば、noEmit でも終了コード 1 か 2 を返す (2 は出力を生成した場合だが、区別しない)
  return runBin(cache, "tsc", ["-p", paths.tsconfig, "--pretty", "false"], paths.deckDir, env, [1, 2]);
}

/** eslint で、資料ごとのスクリプトを検査する (設定は、プラグインのファイル src/check/eslint.deck.config.mjs) */
export function lint(paths: DeckPaths, cache: CachePaths, env: NodeJS.ProcessEnv, pluginDir: string = PLUGIN_DIR): ToolResult {
  const config = join(pluginDir, "src", "check", "eslint.deck.config.mjs");
  return runBin(
    cache,
    "eslint",
    ["--config", config, paths.script],
    paths.deckDir,
    { ...env, SLIDE_DECK_NODE_MODULES: cache.nodeModulesDir, SLIDE_DECK_TSCONFIG: paths.tsconfig },
    // eslint の終了コード 1 は指摘あり、2 は設定の誤りなどの実行の誤り
    [1],
  );
}

/** 資料ごとのスクリプトを実行した結果。実行できなければ、message に理由がある */
export type LoadResult = { ok: true; result: DeckScriptResult } | { ok: false; message: string };

/**
 * 資料ごとのスクリプトを import し、default export の関数に部品の関数の集まりを渡して実行する。
 * tsc で型を検査した後に呼ぶ。実行の途中の例外は、資料ごとのスクリプトの誤りとして返す
 */
export async function loadDeckScript(paths: DeckPaths): Promise<LoadResult> {
  try {
    const mod: unknown = await import(pathToFileURL(paths.script).href);
    const fn: unknown = typeof mod === "object" && mod !== null && "default" in mod ? mod.default : undefined;
    if (typeof fn !== "function") {
      return { ok: false, message: "deck.ts が、関数を default export していない" };
    }
    // 型は、build/deck-type.ts で tsc が DeckScript であることを検査した
    const result = (fn as DeckScript)(parts);
    return { ok: true, result };
  } catch (e) {
    return { ok: false, message: e instanceof Error ? (e.stack ?? e.message) : String(e) };
  }
}

/**
 * 構成案と、資料ごとのスクリプトの結果から、スライドのデータを作る。キーが一致していることを確認した後に呼ぶ。
 * スライドの順序は構成案の順序。題名・一言・発表者ノートは構成案から、図は資料ごとのスクリプトから取る (計画の R8)
 */
export function assembleDeck(outline: DeckOutline, result: DeckScriptResult): Deck {
  const figures = new Map(result.slides.map((f) => [f.key, f]));
  return {
    title: outline.title,
    theme: result.theme,
    slides: outline.slides.map((s) => {
      const figure = figures.get(s.key);
      if (figure === undefined) throw new Error(`資料ごとのスクリプトに、キー ${s.key} の図が無い`);
      return { key: s.key, title: s.title, takeaway: s.takeaway, notes: s.notes, elements: figure.elements };
    }),
  };
}

/** 検査の指摘の 1 つの種類。heading は種類の見出し、lines はその指摘 */
export interface Finding {
  readonly heading: string;
  readonly lines: readonly string[];
}

/** 検査の結果。指摘が無ければ deck にスライドのデータがあり、指摘があれば deck は null */
export interface CheckReport {
  readonly findings: readonly Finding[];
  readonly deck: Deck | null;
}

/** はみ出しそうな箇所の要素を、利用者に示す名前にする */
function describeFitElement(e: FitIssue["element"]): string {
  if (e === "title") return "題名";
  if (e === "takeaway") return "一言";
  return `deck.ts の要素 ${String(e)} (スライドの要素の配列の添字。足した順に 0 から数える)`;
}

function formatFitIssue(i: FitIssue): string {
  return `${i.key} の${describeFitElement(i.element)}: 要る高さ ${i.need.toFixed(2)} インチ、文字を置ける高さ ${i.height.toFixed(2)} インチ、文字の先頭 ${JSON.stringify(i.head)}`;
}

/**
 * 資料のディレクトリを検査する。検査の順序と、指摘があったときに後の検査をするかは次のとおり。
 * 1. 構成案の書式と【提案】の残り。
 * 2. tsc と eslint。どちらかに指摘があれば、資料ごとのスクリプトを実行せずに終える。
 * 3. 資料ごとのスクリプトの実行と、テーマの値。
 * 4. 構成案と資料ごとのスクリプトのキーの突き合わせ (構成案に書式の誤りが無いときだけ)。
 * 5. はみ出しの見積もり (キーが一致し、テーマに誤りが無いときだけ)。
 * 資料のディレクトリやファイルが無い・ライブラリが入っていない・ツールを実行できないときは、ExecutionError を送出する
 */
export async function checkDeck(deckDir: string, options: CheckOptions = {}): Promise<CheckReport> {
  const pluginDir = options.pluginDir ?? PLUGIN_DIR;
  const env = options.env ?? process.env;
  const paths = deckPaths(deckDir);
  const cache = installedCache({ pluginDir, env });
  prepareBuildDir(paths, pluginDir);
  const findings: Finding[] = [];

  const parsed = parseOutline(readFileSync(paths.outline, "utf8"));
  if (!parsed.ok) {
    findings.push({ heading: "構成案 outline.md の書式の誤り", lines: parsed.errors.map(formatOutlineError) });
  } else if (parsed.outline.proposals.length > 0) {
    findings.push({
      heading: "【提案】が付いたままのスライド (採否を決め、採用するなら【提案】を外し、採用しないならスライドを消す)",
      lines: parsed.outline.proposals.map((s) => `${String(s.line)} 行目: ${s.key}: ${s.title}`),
    });
  }

  const tsc = typeCheck(paths, cache, env);
  if (!tsc.ok) findings.push({ heading: "tsc の指摘", lines: tsc.output.split("\n") });
  const eslint = lint(paths, cache, env, pluginDir);
  if (!eslint.ok) findings.push({ heading: "eslint の指摘", lines: eslint.output.split("\n") });
  if (!tsc.ok || !eslint.ok) return { findings, deck: null };

  const loaded = await loadDeckScript(paths);
  if (!loaded.ok) {
    findings.push({ heading: "deck.ts を実行できない", lines: loaded.message.split("\n") });
    return { findings, deck: null };
  }
  const themeErrors = checkTheme(loaded.result.theme);
  if (themeErrors.length > 0) findings.push({ heading: "deck.ts のテーマの誤り", lines: themeErrors });
  if (!parsed.ok) return { findings, deck: null };

  const outline = parsed.outline;
  const mismatch = matchKeys(
    outline.slides.map((s) => s.key),
    loaded.result.slides.map((f) => f.key),
  );
  if (hasMismatch(mismatch)) {
    const lines: string[] = [];
    if (mismatch.outlineOnly.length > 0) lines.push(`構成案にだけあるキー: ${mismatch.outlineOnly.join(", ")}`);
    if (mismatch.deckOnly.length > 0) lines.push(`deck.ts にだけあるキー: ${mismatch.deckOnly.join(", ")}`);
    if (mismatch.deckDuplicates.length > 0) {
      lines.push(`deck.ts で 2 回以上図を作ったキー: ${mismatch.deckDuplicates.join(", ")}`);
    }
    findings.push({ heading: "構成案と deck.ts のキーの不一致", lines });
    return { findings, deck: null };
  }
  if (themeErrors.length > 0) return { findings, deck: null };

  const deck = assembleDeck(outline, loaded.result);
  const fit = estimateSlides(deck.slides);
  if (fit.length > 0) {
    findings.push({ heading: "文字が箱からはみ出しそうな箇所 (箱を広げるか、文を縮める)", lines: fit.map(formatFitIssue) });
  }
  return { findings, deck: findings.length === 0 ? deck : null };
}

/** 検査の結果を、利用者に示す文字列にする。指摘が無ければ、スライドの枚数を示す */
export function formatCheckReport(report: CheckReport): string {
  if (report.deck !== null) {
    return `検査の指摘は無い (スライド ${String(report.deck.slides.length)} 枚)\n`;
  }
  return report.findings.map((f) => `${f.heading}:\n${f.lines.map((l) => `  ${l}`).join("\n")}\n`).join("\n");
}
