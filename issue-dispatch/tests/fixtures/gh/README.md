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
| `graphql-rate-limited` | GraphQL のレート制限の応答 (`errors[].type` が `RATE_LIMITED`) | 1 | **手で作った。** 実物のレート制限は起こせないので、GitHub の GraphQL API の文書の形で書いた。stderr は `gh` が `errors[].message` を書く形に合わせた |

後の単位 (U7 以降) が自分のクエリの出力を足すときは、同じ名前の付け方でこの表に行を足す。
