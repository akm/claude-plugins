# 偽の `gh` が返す固定データ

実物の `gh` の出力をコピーしたファイル。偽の `gh` (ファイル `gh-notification-dispatch/tests/fake-gh`) がモードや応答の指定に従って返し、テストが `gh` の出力の形を確認するのに使う。名前は `<場合>.stdout` と `<場合>.stderr` の組で、標準出力と標準エラー出力をそのまま書いている。

出所:

- **issue-practice からコピーしたもの**: プラグイン issue-practice の固定データ (ディレクトリ `issue-practice/tests/fixtures/gh/`) を、そのままコピーした。issue-practice も、プラグイン issue-dispatch からコピーしている。取った日と取り方は、issue-practice の固定データの README にある。
- **このプラグインで取ったもの**: 公開のリポジトリ akm/claude-plugins と、存在しない名前のリポジトリに対して、読むだけのコマンドで取った。取った日は 2026-11-16、`gh` は 2.103.3。

| 場合 | コマンド | 終了コード | 出所 |
| --- | --- | --- | --- |
| `auth-invalid-token` | `GH_TOKEN` に無効なトークンを入れて `gh api graphql` (認証切れ) | 1 | issue-practice からコピー |
| `auth-not-logged-in` | 認証の無い `GH_CONFIG_DIR` と空の `GH_TOKEN` で `gh api graphql` | 4 | issue-practice からコピー |
| `network-unreachable` | `https_proxy` を繋がらない宛先 (`127.0.0.1:9`) にして `gh api graphql` | 1 | issue-practice からコピー |
| `graphql-rate-limited` | GraphQL のレート制限の応答 (`errors[].type` が `RATE_LIMITED`) | 1 | issue-practice からコピー (issue-dispatch で手で作ったもの) |
| `graphql-bad-field` | `gh api graphql` で存在しないフィールドを読む (`errors` の形) | 1 | issue-practice からコピー |
| `api-user` | `gh api user` (REST。トークンのログイン)。`login`・`id`・`node_id`・`html_url`・`type` だけを残したもの | 0 | issue-practice からコピー |
| `repo-not-found` | `gh api repos/akm/<存在しない名前>` (読めないリポジトリ。状態コード 404) | 1 | このプラグインで取った |
| `repo-claude-plugins` | `gh api repos/akm/claude-plugins`。`id`・`name`・`full_name`・`private`・`owner` (`login`)・`html_url` だけを残したもの。大文字と小文字の違う名前 (`repos/AKM/Claude-Plugins`) でも、`full_name` は同じ値になった | 0 | このプラグインで取ったものを切り詰めた |
| `repo-view` | リポジトリの作業ツリーで `gh repo view --json nameWithOwner` | 0 | このプラグインで取った |
| `repo-view-not-git` | git のリポジトリでないディレクトリ (`/tmp`) で `gh repo view --json nameWithOwner` | 1 | このプラグインで取った |
