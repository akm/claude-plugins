// 入口 src/cli.ts のサブコマンド check と pptx のテスト (計画の U5 の Test scenarios)。
// プラグインのディレクトリのコピー (node_modules を持たない) の入口を、一時的なキャッシュのディレクトリを指定して実行する
// (補助はファイル tests/helpers/cache.ts)。

import assert from "node:assert/strict";
import { spawnSync, type SpawnSyncReturns } from "node:child_process";
import { existsSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, test } from "node:test";
import { makeSandbox, type TestSandbox } from "./helpers/cache.ts";

let sandbox: TestSandbox;

beforeEach(() => {
  sandbox = makeSandbox();
});

afterEach(() => {
  sandbox.cleanup();
});

function runCli(args: readonly string[], extra: Record<string, string> = {}): SpawnSyncReturns<string> {
  return spawnSync(process.execPath, [sandbox.cli, ...args], { env: { ...sandbox.env, ...extra }, encoding: "utf8" });
}

/** 資料のディレクトリのファイルの文字を置き換える。置き換える文字が無ければ失敗する */
function edit(deckDir: string, file: string, from: string, to: string): void {
  const path = join(deckDir, file);
  const before = readFileSync(path, "utf8");
  assert.ok(before.includes(from), `${file} に ${from} が無い`);
  writeFileSync(path, before.replace(from, to));
}

// 見本の資料の deck.ts の、関数の最初の行。ここに行を足して、誤りを入れる
const DECK_FIRST_LINE = "const deck: DeckScript = (p) => {";

describe("check", () => {
  test("見本の資料では、指摘が無く終了コード 0 になり、build/ に .gitignore・tsconfig.json・deck-type.ts を書く", () => {
    const deck = sandbox.copySample();
    const r = runCli(["check", deck]);
    assert.equal(r.status, 0, r.stdout + r.stderr);
    assert.equal(r.stdout, "検査の指摘は無い (スライド 4 枚)\n");
    assert.equal(readFileSync(join(deck, "build", ".gitignore"), "utf8"), "*\n");
    assert.ok(existsSync(join(deck, "build", "tsconfig.json")));
    assert.ok(existsSync(join(deck, "build", "deck-type.ts")));
    assert.equal(existsSync(join(deck, "build", "deck.pptx")), false);
  });

  test("プラグインのディレクトリに node_modules が無く、ライブラリがキャッシュのディレクトリにだけあっても成功する", () => {
    assert.equal(existsSync(join(sandbox.pluginDir, "node_modules")), false);
    assert.ok(existsSync(join(sandbox.cache.nodeModulesDir, ".bin", "tsc")));
    const deck = sandbox.copySample();
    assert.equal(runCli(["check", deck]).status, 0);
  });

  test("資料のディレクトリより上に別の tsconfig.json があっても、build/tsconfig.json で検査して成功する", () => {
    const deck = sandbox.copySample("project/slides/sample");
    // 上の tsconfig.json を使うと、存在しない型の定義を読み込もうとして tsc が失敗し、strict でない設定で検査することになる
    writeFileSync(
      join(sandbox.root, "project", "tsconfig.json"),
      JSON.stringify({ compilerOptions: { strict: false, types: ["does-not-exist"] }, include: ["**/*.ts"] }),
    );
    const r = runCli(["check", deck]);
    assert.equal(r.status, 0, r.stdout + r.stderr);
    const tsconfig = JSON.parse(readFileSync(join(deck, "build", "tsconfig.json"), "utf8")) as {
      compilerOptions: { strict: boolean; paths: Record<string, string[]> };
    };
    assert.equal(tsconfig.compilerOptions.strict, true);
    assert.deepEqual(tsconfig.compilerOptions.paths["slide-deck"], [join(sandbox.pluginDir, "src", "index.ts")]);
  });

  test("deck.ts に any を書くと、eslint の指摘を示して終了コード 1 になる", () => {
    const deck = sandbox.copySample();
    edit(deck, "deck.ts", DECK_FIRST_LINE, `${DECK_FIRST_LINE}\n  const unused: any = p.slide("x");\n  void unused;`);
    const r = runCli(["check", deck]);
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.match(r.stdout, /^eslint の指摘:$/m);
    assert.match(r.stdout, /@typescript-eslint\/no-explicit-any/);
    assert.doesNotMatch(r.stdout, /tsc の指摘/);
  });

  test("資料のディレクトリのパスがシンボリックリンクを含んでも、eslint が deck.ts を検査の対象の外として扱わない", () => {
    // eslint は、--config を指定すると、作業ディレクトリ (実際のパス) の外のファイルを、警告だけを出して検査しない
    const deck = sandbox.copySample();
    edit(deck, "deck.ts", DECK_FIRST_LINE, `${DECK_FIRST_LINE}\n  const unused: any = p.slide("x");\n  void unused;`);
    const link = join(sandbox.root, "link");
    symlinkSync(deck, link, "dir");
    const r = runCli(["check", link]);
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.match(r.stdout, /@typescript-eslint\/no-explicit-any/);
  });

  test("部品の関数の引数の誤りで、tsc の指摘を示して終了コード 1 になる", () => {
    const deck = sandbox.copySample();
    edit(deck, "deck.ts", DECK_FIRST_LINE, `${DECK_FIRST_LINE}\n  p.box(p.slide("x"), 1, 2, 3, "文字");`);
    const r = runCli(["check", deck]);
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.match(r.stdout, /^tsc の指摘:$/m);
    assert.match(r.stdout, /deck\.ts\(\d+,\d+\): error TS2554/);
  });

  test("deck.ts が関数を default export していないと、tsc の指摘を示して終了コード 1 になる", () => {
    const deck = sandbox.copySample();
    edit(deck, "deck.ts", "export default deck;", "export { deck };");
    const r = runCli(["check", deck]);
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.match(r.stdout, /build\/deck-type\.ts\(\d+,\d+\): error TS2613: .* has no default export/);
  });

  test("キーが一致しないと、片方にしか無いキーと重複したキーを示して終了コード 1 になる", () => {
    const deck = sandbox.copySample();
    edit(deck, "deck.ts", 'p.slide("stale")', 'p.slide("hit-miss")');
    edit(deck, "deck.ts", 'p.slide("expire")', 'p.slide("expiry")');
    const r = runCli(["check", deck]);
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.equal(
      r.stdout,
      [
        "構成案と deck.ts のキーの不一致:",
        "  構成案にだけあるキー: stale, expire",
        "  deck.ts にだけあるキー: expiry",
        "  deck.ts で 2 回以上図を作ったキー: hit-miss",
        "",
      ].join("\n"),
    );
  });

  test("【提案】が残っていると、スライドを示して終了コード 1 になる", () => {
    const deck = sandbox.copySample();
    edit(deck, "outline.md", "### stale: 古い値が残る", "### 【提案】stale: 古い値が残る");
    const r = runCli(["check", deck]);
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.match(r.stdout, /^【提案】が付いたままのスライド .*:\n {2}\d+ 行目: stale: 古い値が残る$/m);
  });

  test("構成案の書式の誤りは、行番号を付けて示し、終了コード 1 になる", () => {
    const deck = sandbox.copySample();
    edit(deck, "outline.md", "- 一言: 2 回目からは", "- ひとこと: 2 回目からは");
    const r = runCli(["check", deck]);
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.match(r.stdout, /^構成案 outline\.md の書式の誤り:\n {2}\d+ 行目: /m);
  });

  test("文字が箱からはみ出しそうな箇所があると、一覧を示して終了コード 1 になる", () => {
    const deck = sandbox.copySample();
    edit(deck, "outline.md", "### read-path: 読み出しの流れ", `### read-path: ${"とても長い題名".repeat(6)}`);
    const r = runCli(["check", deck]);
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.match(r.stdout, /^文字が箱からはみ出しそうな箇所 .*:\n {2}read-path の題名: 要る高さ [\d.]+ インチ、文字を置ける高さ 0\.52 インチ、/m);
  });

  test("テーマの色の値の形が違うと、テーマの誤りを示して終了コード 1 になる", () => {
    const deck = sandbox.copySample();
    edit(deck, "deck.ts", 'dk1: "1F2933"', 'dk1: "#1F2933"');
    const r = runCli(["check", deck]);
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.match(r.stdout, /^deck\.ts のテーマの誤り:\n {2}テーマの色 dk1 の値 "#1F2933" が/m);
  });

  test("資料のディレクトリか deck.ts が無いと、終了コード 2 になる", () => {
    const missing = runCli(["check", join(sandbox.root, "missing")]);
    assert.equal(missing.status, 2);
    assert.match(missing.stderr, /資料のディレクトリ .*missing が無い/);
    const deck = sandbox.copySample();
    rmSync(join(deck, "deck.ts"));
    const noScript = runCli(["check", deck]);
    assert.equal(noScript.status, 2);
    assert.match(noScript.stderr, /資料のディレクトリに、次のファイルが無い:\n {2}.*deck\.ts/);
  });

  test("引数の数が違うと、説明を示して終了コード 2 になる", () => {
    const deck = sandbox.copySample();
    const r = runCli(["check", deck, "extra"]);
    assert.equal(r.status, 2);
    assert.match(r.stderr, /引数 <資料のディレクトリ> を指定する/);
    assert.match(r.stderr, /使い方: node <プラグインのディレクトリ>\/src\/cli\.ts check/);
  });

  test("node_modules がキャッシュのディレクトリに入っていないと、setup install を示して終了コード 2 になる", () => {
    const empty = makeSandbox({ nodeModules: false });
    try {
      const deck = empty.copySample();
      const r = spawnSync(process.execPath, [empty.cli, "check", deck], { env: empty.env, encoding: "utf8" });
      assert.equal(r.status, 2, r.stdout + r.stderr);
      assert.match(r.stderr, /setup install で入れる/);
    } finally {
      empty.cleanup();
    }
  });
});

describe("--help", () => {
  for (const name of ["check"]) {
    test(`${name} --help が、引数・出力・終了コードを示す`, () => {
      const r = runCli([name, "--help"]);
      assert.equal(r.status, 0, r.stderr);
      assert.ok(r.stdout.startsWith(`使い方: node <プラグインのディレクトリ>/src/cli.ts ${name} <資料のディレクトリ>`), r.stdout);
      for (const heading of ["引数:", "出力", "終了コード:"]) {
        assert.match(r.stdout, new RegExp(`^${heading}`, "m"), heading);
      }
      for (const code of [0, 1, 2]) assert.match(r.stdout, new RegExp(`^ {2}${String(code)} {2}`, "m"));
    });
  }
});
