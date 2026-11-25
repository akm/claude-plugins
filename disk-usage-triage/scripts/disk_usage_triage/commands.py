"""消すコマンドに使ってよい、実行ファイルとサブコマンドの組 (計画 docs/plans/2026-11-22-1630-feat-disk-usage-triage-plan.md の KTD6)。

判定表 (ファイル `disk-usage-triage/scripts/disk_usage_triage/judgment-table.json`) のツールのコマンドと、判定表に無い項目に
Claude が書いたコマンド (計画の R16) は、この組のどれかで始める。実行ファイルだけで許可すると、`rustup run`・`uv run`・
`pnpm exec` のように別のコマンドを起動するサブコマンドを経由して、選んだ項目の外のものを消せるため (計画の KD17)。

計画の U3 では、判定表が使う組だけを定数に書いた。Claude が書いたコマンドの検査 (計画の R16) と、各ツールの文書を確認して組を足す
作業は、計画の U4 で行う。組を増やすときは、プラグインを更新する。
"""

# 組は、引数の配列の先頭の要素と、順に比べる (("pnpm", "store", "prune") は、pnpm store prune で始まるコマンドに一致する)
ALLOWED = (
    ("go", "clean"),
    ("npm", "cache", "clean"),
    ("pip", "cache", "purge"),
    ("pnpm", "store", "prune"),
    ("rustup", "toolchain", "uninstall"),
    ("uv", "cache", "clean"),
    ("xcrun", "simctl", "delete"),
)
