// テストの偽の pptx のスキルの scripts/apply_theme.js (ファイル tests/helpers/cache.ts の説明)。
// 引数と環境変数 NODE_PATH を、環境変数 FAKE_APPLY_THEME_LOG のファイルに 1 行の JSON で記録する。PowerPoint のファイルは変えない。
// 環境変数 FAKE_APPLY_THEME_FAIL があれば、誤りを出力して終了コード 1 で終了する (本物は、失敗すると 1 で終了する)。

import { appendFileSync } from "node:fs";

const log = process.env.FAKE_APPLY_THEME_LOG;
if (log !== undefined && log !== "") {
  appendFileSync(log, `${JSON.stringify({ argv: process.argv.slice(2), nodePath: process.env.NODE_PATH ?? null })}\n`);
}
if (process.env.FAKE_APPLY_THEME_FAIL !== undefined) {
  console.error("Error: 偽の apply_theme.js の失敗");
  process.exit(1);
}
console.log(`Theme written to ${process.argv[2] ?? ""}`);
