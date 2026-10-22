# 偽の `gh` が返す固定データ

実物の `gh` の出力を写したファイル。偽の `gh` (`issue-dispatch/tests/fake-gh`) がモードや応答の指定に従って返し、テストが `gh` の出力の形を確かめるのに使う。名前は `<場合>.stdout` と `<場合>.stderr` の組で、標準出力と標準エラー出力をそのまま写している。

実物は、U1 の検証用のリポジトリ `akm/issue-dispatch-verify-a` (private) と Project に対して、読むだけのコマンドで取った。書き込みはしていない。取った日は 2026-10-21、`gh` は 2.102.0。

| 場合 | コマンド | 終了コード | 出所 |
| --- | --- | --- | --- |
| `graphql-issue-ok` | `gh api graphql` で Issue #1 の `closedByPullRequestsReferences(includeClosedPrs:true)` と `rateLimit { cost remaining resetAt }` を読む | 0 | 実物 |
| `graphql-bad-field` | `gh api graphql` で存在しないフィールド `noSuchField` を読む (`errors` の形) | 1 | 実物 |
| `issue-view-ok` | `gh issue view 1 --json number,title,state,url,labels,body` | 0 | 実物 |
| `issue-not-found` | `gh issue view 999 --json number` (無い番号) | 1 | 実物 |
| `pr-view-ok` | `gh pr view 4 --json number,title,state,isDraft,mergedAt,closedAt,url,closingIssuesReferences` (マージ済みの PR) | 0 | 実物 |
| `rate-limit-status` | `gh api rate_limit` (REST。レート制限の残りと再開時刻) | 0 | 実物 |
| `auth-invalid-token` | `GH_TOKEN` に無効なトークンを入れて `gh api graphql` (認証切れ) | 1 | 実物 |
| `auth-not-logged-in` | 認証の無い `GH_CONFIG_DIR` と空の `GH_TOKEN` で `gh api graphql` | 4 | 実物 |
| `network-unreachable` | `https_proxy` を繋がらない宛先 (`127.0.0.1:9`) にして `gh api graphql` | 1 | 実物 |
| `project-meta-ok` | `gh api graphql` で検証用 Project #3 のフィールド (選択肢の id・色・説明) とワークフローを読む (クエリ `issue-dispatch/scripts/issue_dispatch/graphql/project-meta.graphql`) | 0 | 実物 (2026-10-22) |
| `project-items-ok` | `gh api graphql` で検証用 Project #3 の項目の一覧を読む (クエリ `issue-dispatch/scripts/issue_dispatch/graphql/items.graphql`)。実物は 100 件で、`akm/issue-dispatch-verify-a` の 3 件と `akm/issue-dispatch-verify-b` の先頭 2 件に切り詰めた | 0 | 実物を切り詰めた (2026-10-22) |
| `project-items-page1` / `project-items-page2` | `project-items-ok` を 3 件と 2 件に分け、1 ページ目の `pageInfo` を `hasNextPage: true` にしたもの (ページを辿るテスト用) | 0 | **手で作った** (`project-items-ok` から) |
| `pr-observe-merged` / `pr-observe-closed` / `pr-observe-open-other-base` | `gh api graphql` で PR #4 (マージ済み。Issue #1 を閉じる参照を持つ) / #5 (マージせずに閉じた。Issue #2 を参照) / #6 (開いている。base は `other-base`。参照なし) を読む (クエリ `issue-dispatch/scripts/issue_dispatch/graphql/pr-observe.graphql`) | 0 | 実物 (2026-10-22) |
| `issue-list-open` | `gh issue list --state open --json number,url,title,body --limit 500` (開いた Issue #3 と #1) | 0 | 実物 (2026-10-22) |
| `label-list` | `gh label list --json name,color,description --limit 200` (デフォルトのラベルと `resource:verify`) | 0 | 実物 (2026-10-22) |
| `api-user` | `gh api user` (REST。トークンのログイン)。実物の応答から `login`・`id`・`node_id`・`html_url`・`type` だけを残した (ほかは個人の情報で、テストに要らない) | 0 | 実物を切り詰めた (2026-10-22) |
| `graphql-rate-limited` | GraphQL のレート制限の応答 (`errors[].type` が `RATE_LIMITED`) | 1 | **手で作った。** 実物のレート制限は起こせないので、GitHub の GraphQL API の文書の形で書いた。stderr は `gh` が `errors[].message` を書く形に合わせた |

後の単位 (U7 以降) が自分のクエリの出力を足すときは、同じ名前の付け方でこの表に行を足す。
