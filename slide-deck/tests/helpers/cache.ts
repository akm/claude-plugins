// サブコマンド check と pptx のテストの補助 (計画の U5 の Approach 7)。
// 一時的なディレクトリに、次の 3 つを作る。
// - プラグインのディレクトリのコピー。node_modules を持たないので、ライブラリをキャッシュのディレクトリからしか読み込めない
//   (利用者の環境では、プラグインの展開先に node_modules が無い。計画の KTD8)。
// - キャッシュのディレクトリ (環境変数 SLIDE_DECK_CACHE_DIR)。node-<ハッシュ値>/node_modules は、
//   CI が npm ci で入れたファイル slide-deck/node_modules へのシンボリックリンクにする。
//   venv は、フラグファイルと、引数を記録するだけの bin/python を持つ偽物にする (CI には pptx のスキルが無いため)。
// - 資料のディレクトリ。見本の資料 examples/sample/ の outline.md と deck.ts をコピーする。

import {
  chmodSync,
  cpSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { type CachePaths, cachePaths, PLUGIN_DIR } from "../../src/setup/setup.ts";

/** 偽の pptx のスキルのディレクトリ (scripts/apply_theme.js と scripts/office/validate.py を持つ) */
export const FAKE_PPTX_SKILL = join(PLUGIN_DIR, "tests", "fixtures", "pptx-skill");

/** 偽の apply_theme.js が呼び出しを記録するファイルを指定する環境変数 */
export const FAKE_APPLY_THEME_LOG_ENV = "FAKE_APPLY_THEME_LOG";

/** 偽の bin/python の終了コードを指定する環境変数 (無ければ 0) */
export const FAKE_PYTHON_EXIT_ENV = "FAKE_PYTHON_EXIT";

// プラグインのディレクトリのうち、サブコマンド check と pptx が読むファイル
const PLUGIN_FILES = ["src", "tsconfig.json", "package.json", "package-lock.json", "uv.lock", ".python-version"];

export interface TestSandbox {
  readonly root: string;
  /** node_modules を持たない、プラグインのディレクトリのコピー */
  readonly pluginDir: string;
  /** プラグインのディレクトリのコピーの入口 src/cli.ts */
  readonly cli: string;
  /** キャッシュのディレクトリのパス */
  readonly cache: CachePaths;
  /** 偽の bin/python が引数を記録するファイル */
  readonly pythonLog: string;
  /** 偽の apply_theme.js が呼び出しを記録するファイル */
  readonly applyThemeLog: string;
  /** キャッシュのディレクトリと、偽のスクリプトの記録先を指定した環境変数 */
  readonly env: NodeJS.ProcessEnv;
  /** 見本の資料をコピーした資料のディレクトリを作る。relative は root からの相対パス */
  copySample(relative?: string): string;
  /** 偽の bin/python の呼び出し (1 行に 1 回。引数を空白でつないだもの) */
  pythonCalls(): string[];
  /** 偽の apply_theme.js の呼び出し */
  applyThemeCalls(): ApplyThemeCall[];
  cleanup(): void;
}

/** 偽の apply_theme.js の 1 回の呼び出し */
export interface ApplyThemeCall {
  readonly argv: string[];
  readonly nodePath: string | null;
}

export interface SandboxOptions {
  /** 偽の venv を作るか。デフォルト値は true */
  readonly venv?: boolean;
  /** node_modules へのシンボリックリンクを作るか。デフォルト値は true */
  readonly nodeModules?: boolean;
}

/** 一時的なディレクトリに、プラグインのディレクトリのコピー・キャッシュのディレクトリを作る */
export function makeSandbox(options: SandboxOptions = {}): TestSandbox {
  // 実際のパスにする。入口は、プラグインのディレクトリを実際のパスで求める (macOS の一時的なディレクトリ /var は /private/var へのリンク)
  const root = realpathSync(mkdtempSync(join(tmpdir(), "slide-deck-test-")));
  const pluginDir = join(root, "plugin");
  mkdirSync(pluginDir);
  for (const f of PLUGIN_FILES) cpSync(join(PLUGIN_DIR, f), join(pluginDir, f), { recursive: true });
  const pythonLog = join(root, "python.log");
  const applyThemeLog = join(root, "apply-theme.log");
  const env: NodeJS.ProcessEnv = {
    ...process.env,
    SLIDE_DECK_CACHE_DIR: join(root, "cache"),
    [FAKE_APPLY_THEME_LOG_ENV]: applyThemeLog,
  };
  const cache = cachePaths({ pluginDir, env });
  if (options.nodeModules !== false) {
    mkdirSync(cache.nodeDir, { recursive: true });
    symlinkSync(join(PLUGIN_DIR, "node_modules"), cache.nodeModulesDir, "dir");
  }
  if (options.venv !== false) {
    mkdirSync(join(cache.venvDir, "bin"), { recursive: true });
    writeFileSync(
      cache.venvPython,
      `#!/bin/sh\nprintf '%s\\n' "$*" >> '${pythonLog}'\necho "偽の python: $*"\nexit "\${${FAKE_PYTHON_EXIT_ENV}:-0}"\n`,
    );
    chmodSync(cache.venvPython, 0o755);
    writeFileSync(cache.venvFlag, "");
  }
  const readLines = (file: string): string[] =>
    existsSync(file) ? readFileSync(file, "utf8").split("\n").filter((l) => l !== "") : [];
  return {
    root,
    pluginDir,
    cli: join(pluginDir, "src", "cli.ts"),
    cache,
    pythonLog,
    applyThemeLog,
    env,
    copySample(relative = "deck") {
      const dir = join(root, relative);
      mkdirSync(dir, { recursive: true });
      for (const f of ["outline.md", "deck.ts"]) cpSync(join(PLUGIN_DIR, "examples", "sample", f), join(dir, f));
      return dir;
    },
    pythonCalls: () => readLines(pythonLog),
    applyThemeCalls: () => readLines(applyThemeLog).map((l) => JSON.parse(l) as ApplyThemeCall),
    cleanup: () => {
      rmSync(root, { recursive: true, force: true });
    },
  };
}
