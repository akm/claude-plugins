# Issue の様式

このファイルが、この仕組み (issue-dispatch) が扱う Issue と PR の様式の正本。管理のセッションと作業のセッションが Issue のどこを読み、どこに何を書くかをここで決める。Project のフィールドと Status の様式は [project-schema.md](project-schema.md)、リポジトリの設定は [project-config.md](project-config.md) が正本で、ここには写さない。コメントの先頭行の様式は U8 で、宣言 (作業のセッションが変える予定のファイルを書くコメント) の様式は U10 で、この文書に足す。

## Issue が持つもの

| 項目 | 書き方 | 誰が書くか | 読み方 |
| --- | --- | --- | --- |
| 依存関係 | GitHub の Issue の blocked by (`blockedBy`) | 利用者。この仕組みも足す (下の「`blockedBy` の追加」) | 項目の一覧 (`project items`) の `blocked_by` に、blocker ごとの開閉が付く。開いた blocker があれば着手しない |
| 必要な資源 | ラベル `resource:<名前>` (例: `resource:staging-db`) | 利用者。この仕組みも、利用者の承認を得て足す (下の「ラベルの追加」) | 同じ資源のラベルを持つ Issue は同時に 1 つだけ進める |
| 人が行う Issue | ラベル `human-handed` を付けるか、担当者をほかの人にする | 利用者 | 割り当ての対象にしない |
| 担当者 (assignee) | 認証しているアカウント (`gh` のトークンのログイン) 1 つだけ | 利用者 | `human-handed` が無く、担当者がトークンのログイン 1 つだけの Issue が、作業のセッションの対象になる。担当者が未設定の Issue は対象にならないので、`Ready` にする前に担当者を決める |
| 親 Issue | sub-issue を持つ Issue | 利用者 | 親 Issue は割り当ての対象にしない (sub-issue は対象にする)。項目の一覧の `is_parent` |
| 大きさ | 1 つの PR で閉じる大きさ | 利用者 | 作る時点で分ける規則は定めない。着手の後に分ける必要が分かったときの扱いは「分割で作る Issue」 |
| PR との結び付き | PR の本文に Issue を閉じる記法 (`Closes #<番号>`) | 作業のセッション | マージで Issue が閉じ、`Done` と資源の解放がそれに続く (`Done` を書く組み込みワークフローの正本は [project-schema.md](project-schema.md) の「組み込みワークフロー」)。PR の側から読むのは `closingIssuesReferences` (下の「PR の観測」) |

## `blockedBy` の追加 (`blocked-by add`)

`gh issue edit <Issue の URL> --add-blocked-by <blocker の URL>` で足す。`--add-blocked-by` は URL の形だけを受け付ける (番号だけや `owner/repo#番号` は受け付けない。U1 の実測) ので、CLI は参照 (`owner/repo#番号` か URL) を URL に直してから渡す。

失敗 (blocker が無い・権限が無い・レート制限など) は理由付きの JSON (`status: error`・`failure`・`message`・`exit_code`) で返し、CLI は再試行しない。再試行するかは呼び出し元のスキルが決める。自分が足した `blockedBy` の削除は U13 で足す (自分が足したものかの導出が要るため)。

## ラベルの追加 (`issue add-label`)

利用者の承認を得た後に呼ぶ (承認なしに行う操作ではない)。手順は次の順で、途中で失敗すればそこで止めて理由を返す。

1. `gh issue view <URL> --json labels` で、既に付いていれば何もしない (`added: false`)。
2. `gh label list` でリポジトリにラベルが無ければ、`gh label create <名前> [--description <説明>]` で作る (`label_created: true`)。色は `gh` のデフォルトに任せる (この仕組みは色を決めない)。説明は呼び出し元が任意で渡す。
3. `gh issue edit <URL> --add-label <名前>` で足す (`added: true`)。

## 分割で作る Issue (`issue create`)

着手の後に Issue を分ける必要が分かったとき (計画の R20) に、分けた部分を新しい Issue にする。新しい Issue は次の様式で作る。

- **本文の先頭行** は `split-from: <宣言のコメントの URL>`。URL は `https://github.com/<owner>/<repo>/issues/<番号>#issuecomment-<コメントの id>` の形で、分割の元の Issue と宣言のコメントの両方を指す (GitHub ではリンクとして表示される)。先頭行の後に空行を 1 つ挟み、呼び出し元が渡した本文を続ける。
- **同じ先頭行を持つ開いた Issue が既にあれば作らず、その番号を返す** (`created: false`)。管理のセッションが途中で止まって再開したときに、同じ分割で 2 つ作らないため。比べるのは先頭行の文字列の完全一致で、開いた Issue の一覧 (`gh issue list --state open`) が読めなければ作らない (既にあるかを確かめられないまま作ると 2 つになりうるため)。
- Status と sub-issue の関係は書かない。進行中の Issue の sub-issue にはしない (親 Issue は割り当ての対象から外れるため)。ラベルと担当者は、呼び出し元が渡したものをそのまま付ける。

## PR の観測 (`pr observe`)

PR の URL を受けて読むだけで、書き込みは無い。`PR の報告` と `小さな PR の報告` (コメントの様式は U8) に書かれた PR と、項目の一覧の `prs` にある PR に使う。読むのは GraphQL (`graphql/pr-observe.graphql`) で、PR の状態・draft・作者・`closingIssuesReferences` (参照する Issue とその開閉)・変えたファイルの一覧 (ページを辿って全部) を 1 回の問い合わせで得る。

**作者 (`author.login`) がトークンのログイン (`gh api user`) と違う PR は、無いものとして扱う** (種類 `other_author`。中身 `pr` は返さず、`author` だけを返す)。公開リポジトリでは第三者も PR を作れるので、本文の `Closes` やコメントの URL だけでこの仕組みの PR とは見なさない。

| 種類 (`kind`) | 条件 | 管理のセッションがすること |
| --- | --- | --- |
| `other_author` | 作者がトークンのログインと違う | 無いものとして扱う |
| `draft` | 開いていて draft | `In review` にしない |
| `needs_closing_reference` | 開いていて draft ではなく、参照する Issue が無い | 本文に `Closes #<番号>` を足すよう作業のセッションに頼む (本文の追記が要る) |
| `in_review` | 開いていて draft ではなく、参照する Issue がある | Status を `In review` にする |
| `merged` | マージ済みで、参照する Issue があり、すべて閉じている | 何もしない (`Done` の書き手は [project-schema.md](project-schema.md) の「Status の選択肢」) |
| `merged_issue_open` | マージ済みなのに、参照する Issue に開いたものがある | 書き込まず、利用者に知らせる (組み込みワークフローが無効か、参照が適用されなかった) |
| `merged_without_reference` | マージ済みで、参照する Issue が無い | 書き込まず、利用者に知らせる (マージで Issue は閉じないので、利用者が Issue を閉じる。`Closes` の書き忘れか、既定のブランチ以外を base にした PR。U1 の実測では、既定のブランチ以外を base にした PR は参照を返さない) |
| `closed` | マージせずに閉じた | 作業のセッションに確かめる |

出力の `pr` のキー: `number`・`title`・`url`・`state` (`OPEN` / `MERGED` / `CLOSED`)・`draft`・`created_at`・`merged_at`・`closed_at`・`author`・`base_ref`・`head_ref`・`issues` (参照する Issue の配列。要素は `key` (`owner/repo#番号`)・`number`・`url`・`state`)・`issues_truncated` (参照が 50 を超えて一部しか読めていない)・`files` (変えたファイルの配列。要素は `path`・`additions`・`deletions`・`change_type`)。ほかに `rate_limit` と `warnings` (GraphQL が data と一緒に返した errors) を返す。

## CLI

| サブコマンド | 書き込み | 返すもの |
| --- | --- | --- |
| `issue create --repo <owner/name> --title <題> (--body <本文> \| --body-file <ファイル \| ->) --split-from <宣言のコメントの URL> [--label <名前>]... [--assignee <ログイン>]...` | `gh issue create` (既にあれば無し) | `created`・`number`・`url` |
| `issue add-label --issue <参照> --label <名前> [--description <説明>]` | `gh label create` (無ければ)・`gh issue edit --add-label` (付いていなければ) | `label_created`・`added` |
| `blocked-by add --issue <参照> --blocker <参照>` | `gh issue edit --add-blocked-by` | `issue`・`blocker` (キー) |
| `pr observe --url <PR の URL>` | 無し | `kind`・`pr`・`author`・`rate_limit`・`warnings` |

`<参照>` は `owner/repo#番号` か Issue の URL。どのサブコマンドも JSON を出せれば終了コード 0 で、失敗は `status: error` と `errors` (`key`・`message`・`failure`) で伝える。参照や URL の形が読めないときは `gh` を実行せずに返す。
