# Project の様式

**このファイルが、Project (GitHub Projects) の様式の正本。** モジュール `issue-dispatch/scripts/issue_dispatch/project.py` と、CLI `issue-dispatch/scripts/issue_dispatch.py` のサブコマンド `project check` / `project items` / `project set-status` / `project add-fields` はこれに従う。ほかの文書はフィールドと Status の名前を参照するだけで、意味と作り方を言い直さない。

1 つの Project に、複数のリポジトリ (別の owner も) の Issue を入れる。Project には Issue だけを入れ、PR は入れない。

## フィールド

| 名前 | 型 | 書き込み元 | 意味 |
| --- | --- | --- | --- |
| `Status` | 単一選択 (Project が最初から持つ) | 管理のセッション・利用者・組み込みワークフロー | 下の「Status の選択肢」 |
| `Agent session ID` | テキスト | 管理のセッション | 割り当ての正本。割り当てた作業のセッションの ID。排他のフラグで、コメント `割り当て` より先に書く |
| `Agent session title` | テキスト | 管理のセッション | 人が読む写し (作業のセッションの名前)。管理のセッションが ID に合わせる |
| `Agent stuck state` | 単一選択 | 管理のセッション | 停止しているときだけ値が入り、空なら正常 (下の表)。利用者が空にしたときは上書きせず 1 回だけ報告する |

`Agent stuck state` の値:

| 値 | 意味 |
| --- | --- |
| `idle-no-progress` | 割り当ての後、作業のセッションが入力待ちになったのに着手の宣言が現れない。宣言の修正を頼んだ後は、修正した宣言が現れない |
| `deadline-passed` | 割り当てから期限 (設定 `declare_deadline_minutes`) を過ぎても、形の検査を通った着手の宣言が無い (権限の確認で停止している場合など) |
| `session-missing` | 作業のセッションが `ListAgents` に見つからない |
| `manager-stopped` | 管理のセッションが停止している |
| `waiting-for-user` | 作業のセッションが `ListAgents` で状態 `waiting` のまま 2 回続けて見えた (利用者の入力か権限の承認を待機している可能性がある) |

## Status の選択肢

| 名前 | 書き込み元 | 意味 |
| --- | --- | --- |
| `Todo` | 利用者・組み込みワークフロー・管理のセッション (割り当ての解除と、マージされずに閉じた PR の Issue を戻すときだけ) | 未着手。割り当てない |
| `Ready` | 利用者 (管理のセッションは `Blocked` から戻すときだけ) | 利用者が「着手してよい」と決めたことを示す。割り当ての対象はこの項目だけ |
| `In Progress` | 管理のセッション | 割り当て中 |
| `In review` | 管理のセッション | 今の割り当ての PR の観測の種類が `in_review` (条件の正本は [issue-format.md](issue-format.md) の「PR の観測」) |
| `Blocked` | 管理のセッション・利用者 | ほかの Issue か小さな PR を待機する |
| `Done` | 組み込みワークフロー (管理のセッションは書かない) | Issue が閉じた |

`Todo`・`In Progress`・`Done` は Project が最初から持ち、`Ready`・`In review`・`Blocked` はこの仕組みが足す (`In Progress` の表記は Project のまま使う)。管理のセッションが書く Status は `Todo`・`Ready`・`Blocked`・`In Progress`・`In review` の 5 つに限り、`Done` は書かない (CLI の `project set-status` は、ほかの値を `gh` を実行せずに拒否する)。**Status が空の項目は無視する** — 管理のセッションは Status を書き足さない (Project によって選択肢の名前が違い、空の項目に何を書けばよいかを決められないため)。利用者が手で変えた Status は上書きせず、1 回だけ報告する。

## キューの順

項目の位置 (GraphQL の `orderBy: {field: POSITION, direction: ASC}`) で、上が先。ビューの sort と group は見ない。`project items` の `position` はこの順の 1 始まりの番号。

## 組み込みワークフロー

| ワークフロー | 扱い | 理由 |
| --- | --- | --- |
| `Item closed` | 必須 | Issue が閉じたときに `Done` を書く。`Done` と資源の解放はこれに続く |
| `Item added to project` | 推奨 | 足した項目に Status (`Todo`) が付く。無効でも、`Ready` にするのは利用者なので割り当ては変わらない |
| `Item reopened` | 推奨 | reopen した項目の Status を設定し直す。新しい Project のデフォルトには無く、無ければ reopen した Issue の Status は `Done` のまま残る (U1) |
| `Auto-add to project` | 有効なら案内 | 公開リポジトリでは第三者が開いた Issue も Project に入るので、`Ready` にする前に中身を確認するよう案内する |
| `Pull request linked to issue` | 有効なら無効を推奨 | 管理のセッションが書く `In Progress`・`In review` と別の値を書きうる (無効のままでも続ける) |
| `Auto-close issue`・`Pull request merged`・`Auto-add sub-issues to project` | どちらでもよい | この仕組みは Issue だけを Project に入れる |

`project check` は、必須のワークフローが無効なら不足として、推奨が無効 (一覧に無いものも無効として数える) なら案内として列挙し、中断しない。ワークフローは API で有効・無効を変えられないので、UI の手順を案内する。

## 作り方 (`project check` と `project add-fields`)

`project check` は、フィールド 3 つの有無と型、`Agent stuck state` の値、Status の選択肢、ワークフローを確認し、不足と作る手順の案を返す (読むだけ)。利用者の承認を得てから `project add-fields` が案を実行する。

- フィールドは `gh project field-create <番号> --owner <owner> --name <名前> --data-type TEXT|SINGLE_SELECT [--single-select-options <値,…>]` で作る。
- Status の選択肢は GraphQL の `updateProjectV2Field` (`singleSelectOptions`) で足す。**既存の選択肢を `id` 付きで含めて渡す** — 含めないと既存の値が消える (U1 で確認した)。足す選択肢の色と説明: `Ready` は GREEN「着手してよい」、`In review` は BLUE「PR が ready for review」、`Blocked` は RED「ほかの Issue か小さな PR を待機する」。既存の項目の Status の値は変わらない。
- `Agent stuck state` の値の不足も、Status と同じく既存の値の `id` を保った `updateProjectV2Field` の案にする。
- 既にあるフィールドの型が違うとき (`Agent stuck state` が単一選択でないなど) は作り直しが要るので、案を出さずに報告だけする。

## CLI

| サブコマンド | 入力 | 出力 (JSON) |
| --- | --- | --- |
| `project check --project <owner>/<番号>` | | `status`・`project` (`id`・`title`・`url`・`owner`・`number`)・`check` (`ok`・`partial` (一部が読めなかった応答から作った案)・`missing_fields`・`missing_status_options`・`workflows` (`required_disabled`・`recommended_disabled`・`notice_enabled`・`discouraged_enabled`)・`proposals` (`field_create` の引数の配列と、`update_options` (単一選択のフィールドに選択肢を足す入力 (`field`・`fieldId`・`options`) の配列)))・`rate_limit`・`warnings` (Project は読めたが GraphQL が一緒に返した errors)・`errors` |
| `project items --project <owner>/<番号>` | | `status` (`ok` / `partial` 一部を読めなかった / `error`)・`project_id`・`items` (下の表)・`problems` (`what`: `items-page` 残りのページ・`graphql-errors` data と一緒に返った errors・`comments` / `events` 残りのページ・`labels-truncated` / `blocked_by-truncated` / `body_edits-truncated` / `prs-truncated` / `fields-truncated` 入れ子の connection が 1 ページに収まらない)・`rate_limit`・`errors` |
| `project set-status --project <owner>/<番号> --item <項目の ID> --status <値>` | 値は 5 つのどれか | `status` (`ok` / `rejected` / `error`)・`item_id`・`field`・`value`・`errors` |
| `project add-fields --project <owner>/<番号>` | 承認を得た後に呼ぶ | `status` (`ok` / `error` / `rejected` Project の一部が読めなかった (`warnings`) ので、構造を変える書き込みを行わない)・`results` (実行ごとの `action` (`field-create` / `update-options`)・`field`・`ok`・`failure`)・`errors` |

終了コードは、JSON を出せれば 0 (誤りは JSON の `errors`)。

`project items` の各要素 (項目):

| キー | 内容 |
| --- | --- |
| `item_id` / `position` / `item_updated_at` | 項目の ID (書き込みに使う)・位置 (1 始まり)・項目の更新時刻 |
| `content_type` | `Issue` / `DraftIssue` / `PullRequest`。Issue 以外は以下のキーを持たず、`key` は null |
| `key` / `repo` / `number` / `url` / `title` / `state` / `created_at` / `author` | Issue の参照 (`owner/repo#番号`)・リポジトリ・番号・URL・タイトル・`OPEN` / `CLOSED`・作成時刻・作者のログイン |
| `visibility` / `in_organization` | リポジトリの公開範囲 (`PUBLIC` / `PRIVATE` / `INTERNAL`) と、組織のリポジトリか |
| `assignees` / `labels` | 担当者のログインの配列・ラベルの名前の配列 |
| `parent` / `sub_issues` / `is_parent` | 親 Issue の参照 (無ければ null)・sub-issue の数 (`total`・`completed`)・sub-issue を持つか (割り当ての対象にしない) |
| `blocked_by` | blocker の配列 (`key`・`url`・`state`) |
| `status` | `name`・`option_id`・`updated_at`。Status が空なら null |
| `fields` | フィールド名 → 値 (テキストは `text`、単一選択は `name`・`option_id`) と `updated_at`。`Status` は含まない |
| `body_edits` | 本文の編集の履歴 (`editor`・`edited_at`・`deleted_at`)。作成したときの本文の版も含む (`edited_at` が `created_at` と同じ件) |
| `prs` | Issue を閉じる参照を持つ PR (閉じたものも含む): `number`・`url`・`state`・`draft`・`merged`・`created_at`・`merged_at`・`closed_at`・`author`・`base_ref` |
| `comments` | コメントの配列 (`id`・`database_id`・`url`・`author`・`created_at`・`body`)。先頭行の解析は comments の単位 |
| `events` | タイムラインの出来事を時刻の順に (`type`・`at` と種類ごとの値: `label`・`blocking`・`status`・`previous_status`・`was_automated`・`closer_pr`・`state_reason`・`project_number`) |

出来事の `type` は `ClosedEvent`・`ReopenedEvent`・`LabeledEvent`・`UnlabeledEvent`・`BlockedByAddedEvent`・`BlockedByRemovedEvent`・`ProjectV2ItemStatusChangedEvent`・`AddedToProjectV2Event`・`RemovedFromProjectV2Event`。コメントと出来事が 1 ページに収まらない項目は、Issue ごとの残りのページを読んで全部返す。ラベル・blocker・本文の編集・PR・フィールドの値は上限 (blocker 50 と フィールド 50 は GitHub の上限。ほかは 50〜100) まで読み、超えていれば `problems` に入れて知らせる (欠損したまま返さない)。

## 実測 (U1。2026-10-19)

- 書き込み (テキストのフィールド・Status・コメント・`blockedBy`・ラベル) の直後に項目の一覧を読むと、1 回目の読み取りで書いた値が返る。
- フィールドの値の `updatedAt` が読め、Status の `updatedAt` は最後に変えた時刻と一致する。
- ワークフローが付けた Status の変化も `ProjectV2ItemStatusChangedEvent` の `wasAutomated` は false で、ワークフローの変更と人の変更は `wasAutomated` では判別できない。
- `Item closed` で、Issue が閉じた 1 秒後に `Done` が付く。reopen しても Status は `Done` のまま残る (デフォルトに `Item reopened` は無い)。
- 一覧のクエリの費用は、項目 20 件で 1、100 件で 7〜8 ポイント (上限は 1 時間 5,000)。
