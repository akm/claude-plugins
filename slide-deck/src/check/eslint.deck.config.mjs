// サブコマンド check が、資料ごとのスクリプト deck.ts を eslint で検査するときに渡す設定 (計画の KTD4・KTD8)。
// 規則は、プラグインのコードの設定 (ファイル eslint.config.mjs) と同じ tseslint.configs.strictTypeChecked にする。
// プラグインのディレクトリには node_modules が無いので、この設定ファイルからの import では @eslint/js と typescript-eslint を読み込めない。
// そのため、check が環境変数 SLIDE_DECK_NODE_MODULES に指定したキャッシュの node_modules から、場所を明示して読み込む。
// 型の情報には、check が書いた資料のディレクトリの build/tsconfig.json (環境変数 SLIDE_DECK_TSCONFIG) を使う。
// projectService は検査するファイルから上のディレクトリの tsconfig.json を使い、下にある build/tsconfig.json を使わないので使わない。

import { createRequire } from "node:module";
import { dirname, join } from "node:path";

const nodeModules = process.env["SLIDE_DECK_NODE_MODULES"];
const tsconfig = process.env["SLIDE_DECK_TSCONFIG"];
if (nodeModules === undefined || nodeModules === "" || tsconfig === undefined || tsconfig === "") {
  throw new Error(
    "環境変数 SLIDE_DECK_NODE_MODULES と SLIDE_DECK_TSCONFIG が無い。この設定ファイルは、サブコマンド check が eslint に渡すためのもの",
  );
}

const require = createRequire(join(nodeModules, "slide-deck-eslint-config.cjs"));
const { defineConfig } = require("eslint/config");
const js = require("@eslint/js");
const tseslint = require("typescript-eslint");

export default defineConfig({
  files: ["**/*.ts"],
  extends: [js.configs.recommended, tseslint.configs.strictTypeChecked],
  languageOptions: {
    parserOptions: {
      projectService: false,
      project: tsconfig,
      tsconfigRootDir: dirname(tsconfig),
    },
  },
});
