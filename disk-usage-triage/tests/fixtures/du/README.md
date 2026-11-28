# 偽の `du` の固定データ

偽の `du` (ファイル `disk-usage-triage/tests/fakebin/du`) が出力する、macOS の `du` の出力。ファイル名は、`<場合>.stdout` (標準出力) と `<場合>.stderr` (標準エラー出力)。使い方は、ファイル `disk-usage-triage/tests/fakedu_case.py` とファイル `disk-usage-triage/tests/test_scan.py` にある。

計画 [docs/plans/2026-11-22-1630-feat-disk-usage-triage-plan.md](../../../../docs/plans/2026-11-22-1630-feat-disk-usage-triage-plan.md) の U5 では、U1 (実測) で取った出力を元にする予定だった。しかし U1 の出力は残っていなかったので、U5 を実装するときに取り直した (2026-11-28 に利用者が決めた)。

## 取った環境

- 日付: 2026-11-28
- macOS 27.2 (26B123) の `/usr/bin/du`
- root ではない利用者の権限で、Claude Code の Bash ツールから実行した
- 環境変数 `LC_ALL` は `en_US.UTF-8` にした。モジュール `disk-usage-triage/scripts/disk_usage_triage/scan.py` が `du` を実行するときと同じ値 (計画の KTD4)

## 場合

| 場合 | 取ったコマンド | 終了コード | 置き換え |
| --- | --- | --- | --- |
| `private-var-db` | `LC_ALL=en_US.UTF-8 /usr/bin/du -k -d 1 /private/var/db` | 1 | 置き換えていない。システムのディレクトリだけで、利用者の名前もアプリの名前も含まないため |
| `names` | 新しく作った一時ディレクトリ `<一時ディレクトリ>` で、`LC_ALL=en_US.UTF-8 /usr/bin/du -k -d 1 <一時ディレクトリ>` | 0 | 一時ディレクトリのパス (利用者の名前を含む) を `/Users/u/Library/Caches` に置き換えた。標準エラー出力は空だったので、ファイル `names.stderr` は作っていない |

`private-var-db`:

- 標準出力は 61 行で、最後の行がディレクトリ自身 (`/private/var/db`) の行。
- 標準エラー出力は 60 行で、`du: <パス>: Operation not permitted` と `du: <パス>: Permission denied` の 2 種類の行がある。
- 60 行のうち 47 行は、1 つ下の階層のディレクトリそのもの (例: `/private/var/db/appinstalld`) が読めなかった行。それらのディレクトリの行は、標準出力に無い。
- 残りの 13 行は、もっと下の階層 (例: `/private/var/db/ExtensibleSSO/Configuration`) が読めなかった行。それを含む 1 つ下の階層のディレクトリの行は、標準出力にある。

`names`:

- 1 つ下の階層に、次の名前の 4 つのディレクトリがある。
  - 空白を含む `a b`
  - 日本語の `日本語`
  - `tab` と `name` の間にタブ文字を含む名前
  - アクセント付きの文字 1 つの `é` (Unicode の正規化形式 NFC)
- `a b`・`日本語`・タブ文字を含む名前の下には、それぞれ 300 KiB・100 KiB・40 KiB (1 KiB は 1,024 バイト) のファイルを作った。`é` は空のディレクトリ。
