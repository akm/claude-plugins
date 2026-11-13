# 偽の `gh` が返す固定データ

実物の `gh` の出力をコピーしたファイル。偽の `gh` (ファイル `issue-practice/tests/fake-gh`) がモードや応答の指定に従って返し、テストが `gh` の出力の形を確認するのに使う。名前は `<場合>.stdout` と `<場合>.stderr` の組で、標準出力と標準エラー出力をそのまま書いている。

出所は 2 つある。

- **issue-dispatch からコピーしたもの**: プラグイン issue-dispatch の固定データ (ディレクトリ `issue-dispatch/tests/fixtures/gh/`) を、そのままコピーした。取った日は 2026-10-21〜22、`gh` は 2.102.0。取り方は、issue-dispatch の固定データの README にある。
- **このプラグインで取ったもの**: 公開のリポジトリ akm/claude-plugins に対して、読むだけのコマンドで取った。書き込みはしていない。取った日は 2026-11-14、`gh` は 2.103.3。

| 場合 | コマンド | 終了コード | 出所 |
| --- | --- | --- | --- |
| `auth-invalid-token` | `GH_TOKEN` に無効なトークンを入れて `gh api graphql` (認証切れ) | 1 | issue-dispatch からコピー |
| `auth-not-logged-in` | 認証の無い `GH_CONFIG_DIR` と空の `GH_TOKEN` で `gh api graphql` | 4 | issue-dispatch からコピー |
| `network-unreachable` | `https_proxy` を繋がらない宛先 (`127.0.0.1:9`) にして `gh api graphql` | 1 | issue-dispatch からコピー |
| `graphql-rate-limited` | GraphQL のレート制限の応答 (`errors[].type` が `RATE_LIMITED`) | 1 | issue-dispatch からコピー (issue-dispatch で手で作ったもの) |
| `graphql-bad-field` | `gh api graphql` で存在しないフィールドを読む (`errors` の形) | 1 | issue-dispatch からコピー |
| `issue-not-found` | `gh issue view 999 --json number` (無い番号) | 1 | issue-dispatch からコピー |
| `api-user` | `gh api user` (REST。トークンのログイン)。`login`・`id`・`node_id`・`html_url`・`type` だけを残したもの | 0 | issue-dispatch からコピー |
| `issue-view-266` | `gh issue view 266 -R akm/claude-plugins --json number,url,state,title,body,updatedAt` (節「クローズ条件」をマークで囲んでいない作業 Issue) | 0 | このプラグインで取った |
| `issue-view-239` | `gh issue view 239 -R akm/claude-plugins --json number,url,state,title,body,updatedAt` (節「クローズ条件」と「PR マージ計画」をマークで囲んだ管理 Issue) | 0 | このプラグインで取った |
| `issue-comments-266` | `gh api repos/akm/claude-plugins/issues/266/comments --paginate --slurp` (ページの配列の中にコメントの配列)。コメントのキーを `id`・`html_url`・`created_at`・`updated_at`・`body`・`user` (`login`・`type`) だけに切り詰めた | 0 | このプラグインで取ったものを切り詰めた |

後の単位が固定データを足すときは、同じ名前の付け方でこの表に行を足す。
