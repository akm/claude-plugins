// ライブラリ (Python の venv と Node.js の node_modules) を、プラグインに同梱したロックファイルのバージョンで、
// 利用者のキャッシュのディレクトリに入れる。
// 作り方の SSOT は計画 docs/plans/2026-11-09-2343-feat-slide-deck-plugin-plan.md の KTD7・KTD8。
// ライブラリを入れる前に動く必要があるので、Node.js の標準の機能だけで書く (計画の KTD16)。
// 入口のサブコマンド setup status・setup install の引数・出力・終了コードの SSOT は、ファイル src/cli.ts の --help。

import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  accessSync,
  constants,
  copyFileSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  renameSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { homedir } from "node:os";
import { basename, delimiter, join, resolve } from "node:path";

/** キャッシュのディレクトリの場所そのものを指定する環境変数 (テストと開発のため) */
export const CACHE_DIR_ENV = "SLIDE_DECK_CACHE_DIR";

/** venv を作り終えたことを示すフラグファイルの、venv のディレクトリの中での名前 */
export const VENV_FLAG_FILE = "installed";

/**
 * node_modules を入れ終えたことを確認するファイルの、node_modules の中での名前。
 * npm ci が最後に書くファイル (hidden lockfile) で、入れ終えた node_modules にだけある
 */
export const NODE_MODULES_MARKER_FILE = ".package-lock.json";

/** 必要な Node.js のメジャーバージョン (.ts のファイルを変換せずに実行する。計画の KTD3) */
export const REQUIRED_NODE_MAJOR = 24;

/** プラグインのディレクトリ (このファイルは src/setup/ にある) */
export const PLUGIN_DIR = resolve(import.meta.dirname, "..", "..");

const UV_INSTALL_URL = "https://docs.astral.sh/uv/getting-started/installation/";
const NODE_INSTALL_URL = "https://nodejs.org/ja/download";

/** セットアップを続けられないときの誤り。入口は終了コード 2 にする */
export class SetupError extends Error {
  override name = "SetupError";
}

/** setup の関数の共通の引数。テストは、プラグインのディレクトリ・環境変数・Node.js のバージョンを差し替える */
export interface SetupOptions {
  /** ロックファイルを読むプラグインのディレクトリ。省略すると、このファイルのあるプラグイン */
  readonly pluginDir?: string;
  /** 環境変数 (キャッシュのディレクトリと PATH を読み、uv と npm に渡す)。省略すると process.env */
  readonly env?: NodeJS.ProcessEnv;
  /**
   * 実行している Node.js のバージョン。省略すると process.versions.node。
   * process.versions.node と同じ「24.1.0」の形 (先頭に v を付けない) で渡す。読めなければ inspect が SetupError を送出する
   */
  readonly nodeVersion?: string;
}

/** キャッシュのディレクトリと、その下の venv と node_modules のパス */
export interface CachePaths {
  readonly cacheDir: string;
  /** venv-<uv.lock と .python-version のハッシュ値>/ */
  readonly venvDir: string;
  /** venv の Python の実行ファイル */
  readonly venvPython: string;
  /** venv を作り終えたことを示すフラグファイル */
  readonly venvFlag: string;
  /** node-<package-lock.json のハッシュ値>/ */
  readonly nodeDir: string;
  /** nodeDir の下の node_modules/ */
  readonly nodeModulesDir: string;
}

/**
 * キャッシュのディレクトリを返す。
 * 環境変数 SLIDE_DECK_CACHE_DIR があればその場所そのもの、無ければ $XDG_CACHE_HOME/akm-claude-plugins/slide-deck、
 * XDG_CACHE_HOME も無ければ ~/.cache/akm-claude-plugins/slide-deck。空の文字列の環境変数は、無いものとして扱う
 */
export function cacheDir(env: NodeJS.ProcessEnv = process.env): string {
  const own = env[CACHE_DIR_ENV];
  if (own !== undefined && own !== "") {
    return resolve(own);
  }
  const xdg = env["XDG_CACHE_HOME"];
  const base = xdg !== undefined && xdg !== "" ? xdg : join(homedir(), ".cache");
  return resolve(base, "akm-claude-plugins", "slide-deck");
}

/** ファイルの内容を順に続けたものの、SHA-256 の 16 進数の先頭 16 文字 */
function hashFiles(paths: readonly string[]): string {
  const h = createHash("sha256");
  for (const p of paths) {
    h.update(readFileSync(p));
  }
  return h.digest("hex").slice(0, 16);
}

/**
 * キャッシュのディレクトリと、venv と node_modules のパスを求める。
 * venv のハッシュ値は uv.lock と .python-version の内容から求める (.python-version は uv.lock に含まれず、
 * Python のバージョンだけを変えたときにも別の venv にするため)。node_modules のハッシュ値は package-lock.json から求める
 */
export function cachePaths(options: SetupOptions = {}): CachePaths {
  const pluginDir = options.pluginDir ?? PLUGIN_DIR;
  const dir = cacheDir(options.env ?? process.env);
  const venvDir = join(dir, `venv-${hashFiles([join(pluginDir, "uv.lock"), join(pluginDir, ".python-version")])}`);
  const nodeDir = join(dir, `node-${hashFiles([join(pluginDir, "package-lock.json")])}`);
  return {
    cacheDir: dir,
    venvDir,
    venvPython: join(venvDir, "bin", "python"),
    venvFlag: join(venvDir, VENV_FLAG_FILE),
    nodeDir,
    nodeModulesDir: join(nodeDir, "node_modules"),
  };
}

/**
 * venv の状態。
 * - installed: フラグファイルがある
 * - incomplete: ディレクトリがあるのにフラグファイルが無い (作りかけ。setup install が uv sync をやり直す)
 * - missing: ディレクトリが無い
 */
export type VenvState = "installed" | "incomplete" | "missing";

/**
 * node_modules の状態。
 * - installed: node_modules に、npm ci が最後に書くファイル .package-lock.json がある
 * - broken: node-<ハッシュ値>/ があるのに、そのファイルが無い (壊れている。利用者に消してもらう)
 * - missing: node-<ハッシュ値>/ が無い
 */
export type NodeState = "installed" | "broken" | "missing";

export function venvState(paths: CachePaths): VenvState {
  if (existsSync(paths.venvFlag)) {
    return "installed";
  }
  return existsSync(paths.venvDir) ? "incomplete" : "missing";
}

export function nodeState(paths: CachePaths): NodeState {
  if (existsSync(join(paths.nodeModulesDir, NODE_MODULES_MARKER_FILE))) {
    return "installed";
  }
  return existsSync(paths.nodeDir) ? "broken" : "missing";
}

/** 環境変数 PATH から、実行できるファイルを探す。見つからなければ undefined */
export function findExecutable(name: string, env: NodeJS.ProcessEnv): string | undefined {
  for (const dir of (env["PATH"] ?? "").split(delimiter)) {
    if (dir === "") {
      continue;
    }
    const candidate = join(dir, name);
    try {
      if (statSync(candidate).isFile()) {
        accessSync(candidate, constants.X_OK);
        return candidate;
      }
    } catch {
      // 無い・実行できないファイルは、次のディレクトリを探す
    }
  }
  return undefined;
}

/**
 * 取得するものの説明に使う、ロックファイルのパッケージの名前とバージョン。
 * uv.lock は、Python のバージョンなどで分かれると、同じ名前のパッケージを複数のバージョンで持つので、バージョンを配列で持つ
 */
export interface LockedPackage {
  readonly name: string;
  /** 1 つ以上。uv.lock に現れた順 */
  readonly versions: readonly string[];
}

/** 取得するもの (setup status が示す) */
export interface Downloads {
  /** .python-version のバージョン */
  readonly python: string;
  /** pyproject.toml の dependencies (uv.lock のバージョン) */
  readonly pythonPackages: readonly LockedPackage[];
  /** package.json の dependencies (package-lock.json のバージョン) */
  readonly nodePackages: readonly LockedPackage[];
  /** package-lock.json のパッケージのうち、開発のときだけ使うものを除いた数 */
  readonly nodePackageCount: number;
}

/** setup status が示す状態 */
export interface SetupReport {
  readonly paths: CachePaths;
  readonly nodeVersion: string;
  readonly uv: string | undefined;
  readonly npm: string | undefined;
  readonly venv: VenvState;
  readonly node: NodeState;
  readonly downloads: Downloads;
  /** 入れられない理由と直し方。空でなければ setup install は何も入れずに終了する */
  readonly problems: readonly string[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * uv.lock から、プロジェクト自身 (source が virtual のパッケージ) の dependencies の名前とバージョンを読む。
 * 同じ名前の [[package]] が複数あれば (resolution-markers で分かれたとき)、そのバージョンをすべて返す。
 * uv.lock は TOML だが、Node.js の標準の機能に TOML を読むものが無いので、uv が書く行の形 (行頭の name = "…" など) で読む
 */
export function readUvLockDependencies(uvLock: string): LockedPackage[] {
  const blocks = uvLock.split(/^\[\[package\]\]$/m).slice(1);
  const versions = new Map<string, string[]>();
  let root: string | undefined;
  for (const block of blocks) {
    const name = /^name = "([^"]+)"$/m.exec(block)?.[1];
    const version = /^version = "([^"]+)"$/m.exec(block)?.[1];
    if (name === undefined || version === undefined) {
      throw new SetupError(`uv.lock の [[package]] に、name か version の行が無い: ${block.slice(0, 80)}`);
    }
    versions.set(name, [...(versions.get(name) ?? []), version]);
    if (/^source = \{ virtual = "\." \}$/m.test(block)) {
      root = block;
    }
  }
  if (root === undefined) {
    throw new SetupError('uv.lock に、プロジェクト自身のパッケージ (source = { virtual = "." }) が無い');
  }
  const deps = /^dependencies = \[\n([\s\S]*?)^\]/m.exec(root)?.[1] ?? "";
  // 分かれたパッケージは、dependencies にも同じ名前が marker 付きで複数並ぶので、名前を 1 つにまとめる
  const names = [...new Set([...deps.matchAll(/\{ name = "([^"]+)"/g)].map((m) => m[1] ?? ""))];
  return names.map((name) => {
    const found = versions.get(name);
    if (found === undefined) {
      throw new SetupError(`uv.lock に、プロジェクトが使うパッケージ ${name} の項目が無い`);
    }
    return { name, versions: found };
  });
}

/** package-lock.json から、package.json の dependencies の名前とバージョンと、開発のときだけ使うものを除いたパッケージの数を読む */
export function readPackageLock(packageLock: string): { packages: LockedPackage[]; count: number } {
  const data: unknown = JSON.parse(packageLock);
  const packages = isRecord(data) ? data["packages"] : undefined;
  if (!isRecord(packages)) {
    throw new SetupError("package-lock.json に packages が無い");
  }
  const root = packages[""];
  const deps = isRecord(root) ? root["dependencies"] : undefined;
  if (!isRecord(deps)) {
    throw new SetupError('package-lock.json の packages[""] に dependencies が無い');
  }
  const direct = Object.keys(deps).map((name) => {
    const entry = packages[`node_modules/${name}`];
    const version = isRecord(entry) ? entry["version"] : undefined;
    if (typeof version !== "string") {
      throw new SetupError(`package-lock.json に、node_modules/${name} の version が無い`);
    }
    return { name, versions: [version] };
  });
  const count = Object.entries(packages).filter(([key, entry]) => key !== "" && !(isRecord(entry) && entry["dev"] === true)).length;
  return { packages: direct, count };
}

function readDownloads(pluginDir: string): Downloads {
  const lock = readPackageLock(readFileSync(join(pluginDir, "package-lock.json"), "utf8"));
  return {
    python: readFileSync(join(pluginDir, ".python-version"), "utf8").trim(),
    pythonPackages: readUvLockDependencies(readFileSync(join(pluginDir, "uv.lock"), "utf8")),
    nodePackages: lock.packages,
    nodePackageCount: lock.count,
  };
}

/**
 * Node.js・uv・npm の有無と、venv と node_modules の状態を調べる。何も入れない。
 * uv は venv を、npm は node_modules を入れるときだけ要るので、入っているものに要るツールが無くても、入れられない理由にしない
 */
export function inspect(options: SetupOptions = {}): SetupReport {
  const pluginDir = options.pluginDir ?? PLUGIN_DIR;
  const env = options.env ?? process.env;
  const nodeVersion = options.nodeVersion ?? process.versions.node;
  const paths = cachePaths({ pluginDir, env });
  const uv = findExecutable("uv", env);
  const npm = findExecutable("npm", env);
  const venv = venvState(paths);
  const node = nodeState(paths);
  const problems: string[] = [];
  const major = /^(\d+)\.\d+\.\d+/.exec(nodeVersion)?.[1];
  if (major === undefined) {
    // 読めない値を 24 以上とも 24 未満とも決めずに、実行の誤りにする
    throw new SetupError(`Node.js のバージョン ${nodeVersion} を読めない (process.versions.node と同じ「24.1.0」の形で渡す)`);
  }
  if (Number(major) < REQUIRED_NODE_MAJOR) {
    problems.push(
      `Node.js ${String(REQUIRED_NODE_MAJOR)} 以上が要る (実行している Node.js は ${nodeVersion})。入れ方: ${NODE_INSTALL_URL}`,
    );
  }
  if (venv !== "installed" && uv === undefined) {
    problems.push(`venv を入れるのに要る uv が、PATH に無い。入れ方: ${UV_INSTALL_URL}`);
  }
  if (node === "missing" && npm === undefined) {
    problems.push(`node_modules を入れるのに要る npm が、PATH に無い。npm は Node.js に含まれる。入れ方: ${NODE_INSTALL_URL}`);
  }
  if (node === "broken") {
    problems.push(
      `node_modules のディレクトリ ${paths.nodeDir} があるのに、入れ終えたことを示すファイル node_modules/${NODE_MODULES_MARKER_FILE} が無い (壊れている)。` +
        `ディレクトリを消してから (rm -rf "${paths.nodeDir}")、もう一度 setup install を実行する`,
    );
  }
  return { paths, nodeVersion, uv, npm, venv, node, downloads: readDownloads(pluginDir), problems };
}

/** setup status の終了コード。入れられない理由があれば 2、入れるものがあれば 1、どちらも入っていれば 0 */
export function statusExitCode(report: SetupReport): 0 | 1 | 2 {
  if (report.problems.length > 0) {
    return 2;
  }
  return report.venv === "installed" && report.node === "installed" ? 0 : 1;
}

const VENV_STATE_TEXT: Readonly<Record<VenvState, string>> = {
  installed: "入っている",
  incomplete: `作りかけ (フラグファイル ${VENV_FLAG_FILE} が無い。setup install が uv sync をやり直す)`,
  missing: "無い",
};

const NODE_STATE_TEXT: Readonly<Record<NodeState, string>> = {
  installed: "入っている",
  broken: `壊れている (node_modules/${NODE_MODULES_MARKER_FILE} が無い)`,
  missing: "無い",
};

/** 取得するものの説明に使う、パッケージの名前とバージョンを「・」で区切って続けた文字列 */
export function formatPackages(packages: readonly LockedPackage[]): string {
  return packages
    .map((p) => (p.versions.length === 1 ? `${p.name} ${p.versions.join("")}` : `${p.name} ${p.versions.join(" か ")} (uv.lock で、Python のバージョンなどの条件ごとに分かれている)`))
    .join("・");
}

/** setup status の出力の文 */
export function formatStatus(report: SetupReport): string {
  const { paths, downloads } = report;
  const lines = [
    `キャッシュのディレクトリ: ${paths.cacheDir}`,
    `Node.js: ${report.nodeVersion}`,
    `uv: ${report.uv ?? "無い"}`,
    `npm: ${report.npm ?? "無い"}`,
    `venv: ${VENV_STATE_TEXT[report.venv]} (${paths.venvDir})`,
    `node_modules: ${NODE_STATE_TEXT[report.node]} (${paths.nodeModulesDir})`,
  ];
  const fetches: string[] = [];
  if (report.venv !== "installed") {
    fetches.push(
      `- venv: Python ${downloads.python} (ファイル .python-version のバージョン。無ければ uv が取得する) と、` +
        `uv.lock のバージョンの ${formatPackages(downloads.pythonPackages)} (と、それらが使うパッケージ)`,
    );
  }
  if (report.node === "missing") {
    fetches.push(
      `- node_modules: package-lock.json のバージョンの ${formatPackages(downloads.nodePackages)} ` +
        `(と、それらが使うパッケージ。開発のときだけ使うものを除いて ${String(downloads.nodePackageCount)} 個)`,
    );
  }
  if (fetches.length > 0) {
    lines.push("", "取得するもの:", ...fetches);
  }
  if (report.problems.length > 0) {
    lines.push("", "入れられない理由:", ...report.problems.map((p) => `- ${p}`));
  }
  return lines.join("\n") + "\n";
}

interface RunResult {
  readonly status: number | null;
  readonly stderr: string;
}

function run(command: string, args: readonly string[], cwd: string, env: NodeJS.ProcessEnv): RunResult {
  const r = spawnSync(command, args, { cwd, env, encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
  if (r.error !== undefined) {
    throw new SetupError(`${command} を実行できない: ${r.error.message}`);
  }
  return { status: r.status, stderr: r.stderr };
}

function exitText(r: RunResult): string {
  return r.status === null ? "シグナルで終了" : `終了コード ${String(r.status)}`;
}

/**
 * venv を、その場で uv sync して作り、作り終えたらフラグファイルを作る (uv の venv は、中のスクリプトが作ったときの絶対パスを
 * 持つので、別の名前で作って改名しない)。同じ venv を同時に入れる実行は、uv が venv の中のロックで排他する。
 * 失敗したら、venv のディレクトリをフラグファイルを作らずに残す。消すと、同時に入れている別の実行の venv も消えるため。
 * 次の setup install が uv sync をやり直す (uv の同期は、何度実行しても同じ結果になる)
 */
function installVenv(uv: string, pluginDir: string, paths: CachePaths, env: NodeJS.ProcessEnv, log: (line: string) => void): void {
  mkdirSync(paths.cacheDir, { recursive: true });
  log(`venv を入れる (uv sync --frozen --no-dev): ${paths.venvDir}`);
  const r = run(uv, ["sync", "--frozen", "--no-dev", "--project", pluginDir], pluginDir, {
    ...env,
    UV_PROJECT_ENVIRONMENT: paths.venvDir,
  });
  if (r.status !== 0) {
    throw new SetupError(
      `uv sync が失敗した (${exitText(r)})。venv のディレクトリ ${paths.venvDir} は、フラグファイルを作らずに残した ` +
        `(次の setup install が uv sync をやり直す):\n${r.stderr.trim()}`,
    );
  }
  writeFileSync(paths.venvFlag, "");
  log(`venv を入れた: ${paths.venvDir}`);
}

/**
 * node_modules を、一時的な名前のディレクトリで npm ci してから node-<ハッシュ値>/ に改名して入れる
 * (node_modules/.bin のリンクは相対パスなので、改名しても動く)。
 * 改名の前に、同時に実行した別の setup install が node-<ハッシュ値>/ を作り終えていたら (改名が失敗し、入れ終えた node_modules が
 * ある)、入ったものとして扱う。一時的な名前のディレクトリは、成否に関わらず最後に消す
 */
function installNodeModules(npm: string, pluginDir: string, paths: CachePaths, env: NodeJS.ProcessEnv, log: (line: string) => void): void {
  mkdirSync(paths.cacheDir, { recursive: true });
  const work = mkdtempSync(join(paths.cacheDir, `${basename(paths.nodeDir)}.`));
  let preempted = false;
  try {
    for (const name of ["package.json", "package-lock.json"]) {
      copyFileSync(join(pluginDir, name), join(work, name));
    }
    log(`node_modules を入れる (npm ci --omit=dev): ${work}`);
    const r = run(npm, ["ci", "--omit=dev", "--no-audit", "--no-fund"], work, env);
    if (r.status !== 0) {
      throw new SetupError(`npm ci が失敗した (${exitText(r)}):\n${r.stderr.trim()}`);
    }
    try {
      renameSync(work, paths.nodeDir);
    } catch (e) {
      if (nodeState(paths) !== "installed") {
        throw new SetupError(`入れた node_modules を、ディレクトリ ${paths.nodeDir} に移せない: ${errorMessage(e)}`);
      }
      preempted = true;
    }
  } finally {
    rmSync(work, { recursive: true, force: true });
  }
  log(
    preempted
      ? `node_modules は、同時に実行した別の setup install が先に入れた: ${paths.nodeDir}`
      : `node_modules を入れた: ${paths.nodeDir}`,
  );
}

function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/**
 * 入っていないものだけを入れる。入れられない理由 (inspect の problems) があれば、何も入れずに SetupError を送出する。
 * venv を先に入れ、失敗したらそこで終了する (別の方法を試さない)。ファイルの操作の失敗も SetupError にする
 */
export function install(options: SetupOptions & { readonly log: (line: string) => void }): void {
  const pluginDir = options.pluginDir ?? PLUGIN_DIR;
  const env = options.env ?? process.env;
  const report = inspect(options);
  if (report.problems.length > 0) {
    throw new SetupError(report.problems.join("\n"));
  }
  try {
    if (report.venv !== "installed") {
      if (report.uv === undefined) {
        throw new SetupError("uv が無い (inspect が調べたはずの条件)");
      }
      installVenv(report.uv, pluginDir, report.paths, env, options.log);
    }
    if (report.node === "missing") {
      if (report.npm === undefined) {
        throw new SetupError("npm が無い (inspect が調べたはずの条件)");
      }
      installNodeModules(report.npm, pluginDir, report.paths, env, options.log);
    }
  } catch (e) {
    if (e instanceof SetupError) {
      throw e;
    }
    throw new SetupError(`セットアップに失敗した: ${errorMessage(e)}`);
  }
  if (report.venv === "installed" && report.node === "installed") {
    options.log(`venv と node_modules は入っている: ${report.paths.cacheDir}`);
  }
}
