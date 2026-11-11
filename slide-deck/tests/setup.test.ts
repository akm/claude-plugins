// キャッシュのディレクトリへのインストール (ファイル src/setup/setup.ts と、入口 src/cli.ts のサブコマンド setup status・setup install) のテスト。
// 本物の uv と npm は使わず、偽の uv と npm (引数を記録し、venv や node_modules の代わりのファイルを作るスクリプト) を一時的なディレクトリに作り、
// そのディレクトリだけを環境変数 PATH に指定して使う。
// 偽のスクリプトは /bin/sh で動き、PATH を偽のスクリプトのディレクトリだけにしても動くよう、外部のコマンドは /bin/mkdir だけを絶対パスで使う。

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { appendFileSync, copyFileSync, existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { basename, join } from "node:path";
import { afterEach, beforeEach, describe, test } from "node:test";
import {
  cachePaths,
  formatPackages,
  inspect,
  install,
  nodeState,
  PLUGIN_DIR,
  readPackageLock,
  readUvLockDependencies,
  SetupError,
  statusExitCode,
  venvState,
} from "../src/setup/setup.ts";

const CLI = join(PLUGIN_DIR, "src", "cli.ts");

const FAKE_UV = `#!/bin/sh
printf 'uv %s\\n' "$*" >> "$FAKE_LOG"
if [ -n "$FAKE_UV_FAIL" ]; then echo "偽の uv: 失敗" >&2; exit 1; fi
/bin/mkdir -p "$UV_PROJECT_ENVIRONMENT/bin" || exit 1
: > "$UV_PROJECT_ENVIRONMENT/bin/python"
printf 'UV_PROJECT_ENVIRONMENT=%s\\n' "$UV_PROJECT_ENVIRONMENT" >> "$FAKE_LOG"
`;

// FAKE_NPM_FAIL があれば、node_modules を作りかけてから失敗する。
// FAKE_NPM_PREEMPT があれば、同時に実行した別の setup install の代わりに、そのディレクトリに入れ終えた node_modules を作る
const FAKE_NPM = `#!/bin/sh
printf 'npm %s\\n' "$*" >> "$FAKE_LOG"
[ -f package.json ] && [ -f package-lock.json ] || { echo "偽の npm: package.json か package-lock.json が無い" >&2; exit 1; }
/bin/mkdir -p node_modules/pptxgenjs || exit 1
if [ -n "$FAKE_NPM_FAIL" ]; then echo "偽の npm: 失敗" >&2; exit 1; fi
if [ -n "$FAKE_NPM_PREEMPT" ]; then
  /bin/mkdir -p "$FAKE_NPM_PREEMPT/node_modules" || exit 1
  : > "$FAKE_NPM_PREEMPT/node_modules/.package-lock.json"
fi
: > node_modules/.package-lock.json
`;

interface Sandbox {
  readonly root: string;
  readonly cache: string;
  readonly bin: string;
  readonly log: string;
  /** 偽の uv と npm のディレクトリだけを PATH に指定した環境変数 */
  env(extra?: Record<string, string>): NodeJS.ProcessEnv;
  /** 偽の uv と npm の呼び出しの記録 (1 行に 1 つ) */
  calls(): string[];
}

function makeSandbox(tools: readonly ("uv" | "npm")[] = ["uv", "npm"]): Sandbox {
  const root = mkdtempSync(join(tmpdir(), "slide-deck-setup-"));
  const cache = join(root, "cache");
  const bin = join(root, "bin");
  const log = join(root, "calls.log");
  mkdirSync(bin);
  writeFileSync(log, "");
  if (tools.includes("uv")) {
    writeFileSync(join(bin, "uv"), FAKE_UV, { mode: 0o755 });
  }
  if (tools.includes("npm")) {
    writeFileSync(join(bin, "npm"), FAKE_NPM, { mode: 0o755 });
  }
  return {
    root,
    cache,
    bin,
    log,
    env: (extra = {}) => ({ PATH: bin, FAKE_LOG: log, SLIDE_DECK_CACHE_DIR: cache, ...extra }),
    calls: () => readFileSync(log, "utf8").split("\n").filter((l) => l !== ""),
  };
}

/** 入口を、偽の uv と npm のディレクトリだけを PATH に指定して実行する。extra で環境変数を足すか置き換える */
function runCli(
  sandbox: Sandbox,
  args: readonly string[],
  extra: Record<string, string> = {},
): { status: number | null; stdout: string; stderr: string } {
  const r = spawnSync(process.execPath, [CLI, ...args], { env: sandbox.env(extra), encoding: "utf8" });
  return { status: r.status, stdout: r.stdout, stderr: r.stderr };
}

/** プラグインのロックファイルなどを、一時的なプラグインのディレクトリにコピーする (ロックファイルを変えるテストのため) */
function copyPlugin(dest: string): string {
  mkdirSync(dest);
  for (const name of ["package.json", "package-lock.json", "uv.lock", ".python-version", "pyproject.toml"]) {
    copyFileSync(join(PLUGIN_DIR, name), join(dest, name));
  }
  return dest;
}

function sha16(...contents: Buffer[]): string {
  const h = createHash("sha256");
  for (const c of contents) {
    h.update(c);
  }
  return h.digest("hex").slice(0, 16);
}

let sandbox: Sandbox;
const silent = (): void => undefined;

beforeEach(() => {
  sandbox = makeSandbox();
});

afterEach(() => {
  rmSync(sandbox.root, { recursive: true, force: true });
});

describe("パスを求める関数", () => {
  test("SLIDE_DECK_CACHE_DIR を設定すると、その場所の下のパスを返す", () => {
    const p = cachePaths({ env: { SLIDE_DECK_CACHE_DIR: sandbox.cache, XDG_CACHE_HOME: "/xdg" } });
    assert.equal(p.cacheDir, sandbox.cache);
    for (const path of [p.venvDir, p.venvPython, p.venvFlag, p.nodeDir, p.nodeModulesDir]) {
      assert.ok(path.startsWith(sandbox.cache + "/"), path);
    }
    assert.equal(p.venvPython, join(p.venvDir, "bin", "python"));
    assert.equal(p.venvFlag, join(p.venvDir, "installed"));
    assert.equal(p.nodeModulesDir, join(p.nodeDir, "node_modules"));
  });

  test("SLIDE_DECK_CACHE_DIR が無ければ XDG_CACHE_HOME の下、どちらも無ければ ~/.cache の下を使う", () => {
    assert.equal(cachePaths({ env: { XDG_CACHE_HOME: "/xdg" } }).cacheDir, "/xdg/akm-claude-plugins/slide-deck");
    assert.equal(cachePaths({ env: { SLIDE_DECK_CACHE_DIR: "", XDG_CACHE_HOME: "" } }).cacheDir, join(homedir(), ".cache", "akm-claude-plugins", "slide-deck"));
  });

  test("ディレクトリ名のハッシュ値は、venv が uv.lock と .python-version の、node_modules が package-lock.json の SHA-256 の先頭 16 文字", () => {
    const p = cachePaths({ env: sandbox.env() });
    const read = (name: string): Buffer => readFileSync(join(PLUGIN_DIR, name));
    assert.equal(p.venvDir, join(sandbox.cache, `venv-${sha16(read("uv.lock"), read(".python-version"))}`));
    assert.equal(p.nodeDir, join(sandbox.cache, `node-${sha16(read("package-lock.json"))}`));
  });

  test(".python-version だけを変えても、別の venv のディレクトリになる", () => {
    const plugin = copyPlugin(join(sandbox.root, "plugin"));
    const before = cachePaths({ pluginDir: plugin, env: sandbox.env() });
    writeFileSync(join(plugin, ".python-version"), "3.15\n");
    const after = cachePaths({ pluginDir: plugin, env: sandbox.env() });
    assert.notEqual(after.venvDir, before.venvDir);
    assert.equal(after.nodeDir, before.nodeDir);
  });
});

describe("setup install", () => {
  test("何も無い状態から入れると、2 つのディレクトリができ、venv にフラグファイルがある", () => {
    const r = runCli(sandbox, ["setup", "install"]);
    assert.equal(r.status, 0, r.stderr);
    const p = cachePaths({ env: sandbox.env() });
    assert.ok(existsSync(p.venvFlag));
    assert.ok(existsSync(p.venvPython));
    assert.ok(existsSync(join(p.nodeModulesDir, ".package-lock.json")));
    assert.deepEqual(sandbox.calls(), [
      `uv sync --frozen --no-dev --project ${PLUGIN_DIR}`,
      `UV_PROJECT_ENVIRONMENT=${p.venvDir}`,
      "npm ci --omit=dev --no-audit --no-fund",
    ]);
    // 一時的な名前のディレクトリが残らない
    assert.deepEqual(readdirSync(sandbox.cache).sort(), [basename(p.nodeDir), basename(p.venvDir)].sort());
  });

  test("入っている状態では、setup status が「入っている」と示して終了コード 0 を返し、setup install は何も実行しない", () => {
    assert.equal(runCli(sandbox, ["setup", "install"]).status, 0);
    const callsAfterFirst = sandbox.calls();

    const status = runCli(sandbox, ["setup", "status"]);
    assert.equal(status.status, 0, status.stderr);
    assert.match(status.stdout, /^venv: 入っている /m);
    assert.match(status.stdout, /^node_modules: 入っている /m);
    assert.doesNotMatch(status.stdout, /取得するもの/);

    const second = runCli(sandbox, ["setup", "install"]);
    assert.equal(second.status, 0, second.stderr);
    assert.match(second.stdout, /venv と node_modules は入っている/);
    assert.deepEqual(sandbox.calls(), callsAfterFirst);
  });

  test("入っている状態では、uv と npm が PATH に無くても、入れられない理由にせず終了コード 0 を返す", () => {
    assert.equal(runCli(sandbox, ["setup", "install"]).status, 0);
    const callsAfterFirst = sandbox.calls();
    // 偽の uv と npm を作っていない空のディレクトリだけを PATH にする
    const empty = join(sandbox.root, "empty-bin");
    mkdirSync(empty);

    const status = runCli(sandbox, ["setup", "status"], { PATH: empty });
    assert.equal(status.status, 0, status.stdout + status.stderr);
    assert.match(status.stdout, /^uv: 無い$/m);
    assert.match(status.stdout, /^npm: 無い$/m);
    assert.doesNotMatch(status.stdout, /入れられない理由/);

    const install = runCli(sandbox, ["setup", "install"], { PATH: empty });
    assert.equal(install.status, 0, install.stderr);
    assert.match(install.stdout, /venv と node_modules は入っている/);
    assert.deepEqual(sandbox.calls(), callsAfterFirst);
  });

  test("package-lock.json を変えると、別のハッシュ値の node_modules のディレクトリが入れる対象になる", () => {
    const plugin = copyPlugin(join(sandbox.root, "plugin"));
    install({ pluginDir: plugin, env: sandbox.env(), log: silent });
    const before = cachePaths({ pluginDir: plugin, env: sandbox.env() });

    appendFileSync(join(plugin, "package-lock.json"), "\n");
    const report = inspect({ pluginDir: plugin, env: sandbox.env() });
    assert.notEqual(report.paths.nodeDir, before.nodeDir);
    assert.equal(report.node, "missing");
    assert.equal(report.venv, "installed");
    assert.equal(statusExitCode(report), 1);

    install({ pluginDir: plugin, env: sandbox.env(), log: silent });
    assert.equal(nodeState(report.paths), "installed");
    // 前のハッシュ値のディレクトリは消さない
    assert.equal(nodeState(before), "installed");
  });

  test("uv が PATH に無いと、入れ方を示して終了コード 2 になり、何も入れない", () => {
    const noUv = makeSandbox(["npm"]);
    try {
      const r = runCli(noUv, ["setup", "install"]);
      assert.equal(r.status, 2);
      assert.match(r.stderr, /uv が、PATH に無い。入れ方: https:\/\/docs\.astral\.sh\/uv\//);
      assert.deepEqual(noUv.calls(), []);
      assert.equal(existsSync(noUv.cache), false);

      const status = runCli(noUv, ["setup", "status"]);
      assert.equal(status.status, 2);
      assert.match(status.stdout, /^uv: 無い$/m);
      assert.match(status.stdout, /入れられない理由:\n- venv を入れるのに要る uv が/);
    } finally {
      rmSync(noUv.root, { recursive: true, force: true });
    }
  });

  test("Node.js が 24 未満だと、setup status の終了コードが入れ方を示して 2 になり、setup install は何も入れずに誤りになる", () => {
    const report = inspect({ env: sandbox.env(), nodeVersion: "22.12.0" });
    assert.equal(statusExitCode(report), 2);
    assert.match(report.problems.join("\n"), /Node\.js 24 以上が要る \(実行している Node\.js は 22\.12\.0\)。入れ方: https:\/\/nodejs\.org\//);
    assert.throws(() => { install({ env: sandbox.env(), nodeVersion: "22.12.0", log: silent }); }, SetupError);
    assert.deepEqual(sandbox.calls(), []);
  });

  test("Node.js のバージョンを読めない (先頭に v が付いた) ときは、24 未満とも以上とも決めずに誤りにする", () => {
    assert.throws(
      () => inspect({ env: sandbox.env(), nodeVersion: "v18.0.0" }),
      (e: unknown) => e instanceof SetupError && e.message.includes("Node.js のバージョン v18.0.0 を読めない"),
    );
    assert.throws(() => { install({ env: sandbox.env(), nodeVersion: "v18.0.0", log: silent }); }, SetupError);
    assert.deepEqual(sandbox.calls(), []);
  });

  test("強制終了で残った一時的な名前のディレクトリがあると、setup status がそのパスを示し、終了コードは変わらない", () => {
    assert.equal(runCli(sandbox, ["setup", "install"]).status, 0);
    const p = cachePaths({ env: sandbox.env() });
    const leftover = join(sandbox.cache, `${basename(p.nodeDir)}.AbC123`);
    mkdirSync(join(leftover, "node_modules"), { recursive: true });

    const status = runCli(sandbox, ["setup", "status"]);
    assert.equal(status.status, 0, status.stderr);
    assert.match(status.stdout, /残っている一時的なディレクトリ .*:\n- (.+)$/m);
    assert.ok(status.stdout.includes(`- ${leftover}\n`), status.stdout);
    // 入っている node-<ハッシュ値>/ と venv-<ハッシュ値>/ は示さない
    assert.equal(inspect({ env: sandbox.env() }).leftoverDirs.length, 1);
  });

  test("npm ci が失敗すると、一時的なディレクトリが残らず、node-<ハッシュ値>/ も作られない", () => {
    const env = sandbox.env({ FAKE_NPM_FAIL: "1" });
    assert.throws(() => { install({ env, log: silent }); }, (e: unknown) => e instanceof SetupError && /npm ci が失敗した[\s\S]*偽の npm: 失敗/.test(e.message));
    const p = cachePaths({ env });
    assert.deepEqual(readdirSync(sandbox.cache).filter((name) => name.startsWith("node-")), []);
    assert.equal(nodeState(p), "missing");
  });

  test("改名の直前に、別の実行が node-<ハッシュ値>/ を作り終えていたら、入ったものとして扱う", () => {
    const p = cachePaths({ env: sandbox.env() });
    const lines: string[] = [];
    install({ env: sandbox.env({ FAKE_NPM_PREEMPT: p.nodeDir }), log: (line) => lines.push(line) });
    assert.equal(nodeState(p), "installed");
    assert.match(lines.join("\n"), /同時に実行した別の setup install が先に入れた/);
    // 一時的な名前のディレクトリは消す
    assert.deepEqual(readdirSync(sandbox.cache).filter((name) => name.startsWith("node-")), [basename(p.nodeDir)]);
  });

  test("フラグファイルの無い venv のディレクトリがあると、setup status が作りかけと示し、setup install がもう一度 uv sync を実行してフラグファイルを作る", () => {
    const p = cachePaths({ env: sandbox.env() });
    mkdirSync(p.venvDir, { recursive: true });
    assert.equal(venvState(p), "incomplete");

    const status = runCli(sandbox, ["setup", "status"]);
    assert.equal(status.status, 1, status.stderr);
    assert.match(status.stdout, /^venv: 作りかけ /m);

    install({ env: sandbox.env(), log: silent });
    assert.equal(venvState(p), "installed");
    assert.equal(sandbox.calls().filter((c) => c.startsWith("uv sync")).length, 1);
  });

  test("uv sync が失敗すると、venv にフラグファイルを作らず、node_modules も入れない", () => {
    const env = sandbox.env({ FAKE_UV_FAIL: "1" });
    assert.throws(() => { install({ env, log: silent }); }, (e: unknown) => e instanceof SetupError && /uv sync が失敗した[\s\S]*偽の uv: 失敗/.test(e.message));
    const p = cachePaths({ env });
    assert.notEqual(venvState(p), "installed");
    assert.equal(nodeState(p), "missing");
    assert.deepEqual(sandbox.calls().filter((c) => c.startsWith("npm")), []);
  });

  test("node_modules のディレクトリが壊れていると、消すよう案内して終了コード 2 になり、何も入れない", () => {
    const p = cachePaths({ env: sandbox.env() });
    mkdirSync(p.nodeDir, { recursive: true });

    const status = runCli(sandbox, ["setup", "status"]);
    assert.equal(status.status, 2);
    assert.match(status.stdout, /^node_modules: 壊れている /m);

    const r = runCli(sandbox, ["setup", "install"]);
    assert.equal(r.status, 2);
    assert.ok(r.stderr.includes(`rm -rf "${p.nodeDir}"`), r.stderr);
    assert.deepEqual(sandbox.calls(), []);
  });
});

describe("setup status", () => {
  test("何も無い状態では、取得するものをロックファイルのバージョンで示して終了コード 1 を返し、何も入れない", () => {
    const r = runCli(sandbox, ["setup", "status"]);
    assert.equal(r.status, 1, r.stderr);
    assert.match(r.stdout, /^venv: 無い /m);
    assert.match(r.stdout, /^node_modules: 無い /m);
    assert.match(r.stdout, /^- venv: Python 3\.14 .*pillow \d+\.\d+\.\d+/m);
    assert.match(r.stdout, /^- node_modules: .*pptxgenjs \d+\.\d+\.\d+/m);
    assert.deepEqual(sandbox.calls(), []);
    assert.equal(existsSync(sandbox.cache), false);
  });

  test("ロックファイルから、直接使うパッケージの名前とバージョンを読む", () => {
    const uv = readUvLockDependencies(readFileSync(join(PLUGIN_DIR, "uv.lock"), "utf8"));
    assert.deepEqual(uv.map((p) => p.name).sort(), ["defusedxml", "lxml", "pillow"]);
    const npm = readPackageLock(readFileSync(join(PLUGIN_DIR, "package-lock.json"), "utf8"));
    assert.deepEqual(npm.packages.map((p) => p.name).sort(), ["@eslint/js", "eslint", "pptxgenjs", "typescript", "typescript-eslint"]);
    // 開発のときだけ使う @types/node は数えない
    assert.ok(npm.count > npm.packages.length);
  });

  test("uv.lock に同じ名前のパッケージが条件ごとに複数あると、そのバージョンをすべて読んで示す", () => {
    const uvLock = [
      "version = 1",
      "",
      "[[package]]",
      'name = "pillow"',
      'version = "12.0.0"',
      'source = { registry = "https://pypi.org/simple" }',
      "",
      "[[package]]",
      'name = "pillow"',
      'version = "13.0.0"',
      'source = { registry = "https://pypi.org/simple" }',
      "",
      "[[package]]",
      'name = "slide-deck"',
      'version = "0.0.1"',
      'source = { virtual = "." }',
      "dependencies = [",
      '    { name = "pillow", version = "12.0.0", source = { registry = "https://pypi.org/simple" }, marker = "python_full_version < \'3.15\'" },',
      '    { name = "pillow", version = "13.0.0", source = { registry = "https://pypi.org/simple" }, marker = "python_full_version >= \'3.15\'" },',
      "]",
      "",
    ].join("\n");
    const packages = readUvLockDependencies(uvLock);
    assert.deepEqual(packages, [{ name: "pillow", versions: ["12.0.0", "13.0.0"] }]);
    assert.equal(formatPackages(packages), "pillow 12.0.0 か 13.0.0 (uv.lock で、Python のバージョンなどの条件ごとに分かれている)");
    assert.equal(formatPackages([{ name: "lxml", versions: ["6.1.3"] }, { name: "pillow", versions: ["13.0.0"] }]), "lxml 6.1.3・pillow 13.0.0");

    // dependencies の行が片方のバージョンだけを指すときは、そのバージョンだけを示す
    const onlyNew = uvLock.replace(/^ {4}\{ name = "pillow", version = "12\.0\.0".*\n/m, "");
    assert.deepEqual(readUvLockDependencies(onlyNew), [{ name: "pillow", versions: ["13.0.0"] }]);

    // version の無い行で名前が分かれていると、どのバージョンを使うかが決まらないので誤りにする
    const noVersion = onlyNew.replace(/\{ name = "pillow", version = "13\.0\.0", [^\n]*/, '{ name = "pillow" },');
    assert.throws(
      () => readUvLockDependencies(noVersion),
      (e: unknown) => e instanceof SetupError && e.message.includes("pillow の行に version が無いのに"),
    );
  });
});

describe("--help", () => {
  for (const name of ["setup status", "setup install"]) {
    test(`${name} --help が、引数・出力・終了コードを示す`, () => {
      const r = runCli(sandbox, [...name.split(" "), "--help"]);
      assert.equal(r.status, 0, r.stderr);
      assert.ok(r.stdout.startsWith(`使い方: node <プラグインのディレクトリ>/src/cli.ts ${name}`), r.stdout);
      for (const heading of ["引数:", "出力", "終了コード:"]) {
        assert.match(r.stdout, new RegExp(`^${heading}`, "m"), heading);
      }
      assert.match(r.stdout, /^ {2}0 {2}/m);
      assert.match(r.stdout, /^ {2}2 {2}/m);
      assert.deepEqual(sandbox.calls(), []);
    });
  }

  test("存在しないサブコマンドは、サブコマンドの一覧を示して終了コード 2 になる", () => {
    const r = runCli(sandbox, ["setup", "remove"]);
    assert.equal(r.status, 2);
    assert.match(r.stderr, /存在しないサブコマンド: setup remove/);
    assert.match(r.stderr, /setup status/);
  });
});
