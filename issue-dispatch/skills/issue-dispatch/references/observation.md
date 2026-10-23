# 観測 (スナップショットと差分)

このファイルが、この仕組み (issue-dispatch) の観測 — スナップショット (`snapshot.json`)・差分・待機 — の正本。待機 (`wait.pid` の様式と待機の終わる条件) は U14 でこの文書に足す。置き場 (`<管理ディレクトリ>/<record_dir>/<owner>-<number>/`) と種類ごとの扱いは [records.md](records.md)。モジュール `issue-dispatch/scripts/issue_dispatch/observe.py` が読み書き・作成・反映・差分を実装し、`gh` は実行しない (項目の読み取りは `project items`、PR の状態は `issues.pr_state`)。

## 目的

スナップショットは、前のターンの終わりの Project の状態 (と、コメントに URL で書かれた PR の GitHub 上の状態) の写しで、GitHub から導出し直せるキャッシュ (計画の KTD5)。使うのは 2 つ: 待機が変化に気づいて管理のセッションを起こすこと (U14) と、人の変更を 1 回だけ報告すること (計画の R22)。**何を行うかはスナップショットからは決めない** — 導いた項目の状態 (U13) で決める。差分は「何が変わったか」だけを返し、意味づけ (管理のセッションが足した blocker か・どの宣言が待つか) はしない。

書き手は管理のセッションの再入のターンだけ。Project を読んだとき (`project items --write-snapshot`) に書き、そのターンの CLI の書き込みのたびに書いた値を反映する。待機の直前には読み直さない (読み直すと、ターンの最初の読み取りから読み直しまでの間にほかの人が起こした変化が、処理されないままスナップショットに入り、待機がその変化に気づかない)。書き込みに失敗したのに反映した値は、次の差分が食い違いとして見つけ、次のターンで直す。壊れていれば作り直す。

## `snapshot.json` の様式

持つ値は、計画の R21 の「見つける変化」の一覧から決め、一覧に無い値 (タイトル・本文・出来事など) は持たない。

| キー | 内容 |
| --- | --- |
| `version` | 様式の版 (`1`) |
| `taken_at` | Project を読んだ時刻 (UTC) |
| `project_id` | Project の ID |
| `items` | 項目のキー (`owner/repo#番号`) → 下の表。Issue 以外の項目 (draft issue・PR) は持たない |
| `comment_prs` | 開いている項目のコメント (`PR の報告` の本文の URL と、`待機` の理由 `小さな PR` の PR。書き手がトークンのログインのものだけ) に書かれた PR の URL → `state`・`draft`・`merged` (読めなかった PR は `partial` に理由)。どの割り当てのものかは区別しない (意味づけは U13)。閉じた項目のコメントは読まない |

項目の値:

| キー | 内容 |
| --- | --- |
| `item_id` / `position` | 項目の ID・位置 (1 始まり) |
| `state` | `OPEN` / `CLOSED` |
| `status` | Status の名前 (無ければ null) |
| `fields` | フィールド名 → `value` (テキストか選択肢の名前) と `updated_at`。Status は含まない |
| `assignees` / `labels` | 担当者のログイン・ラベルの名前 (名前の順) |
| `blocked_by` | blocker のキー → `OPEN` / `CLOSED` |
| `body_edited_at` | 本文の最新の編集の時刻 (作成も編集に数える) |
| `comment_ids` | 読んだコメントの `database_id` (昇順) |
| `prs` | Issue を閉じる参照の PR の URL → `state`・`draft`・`merged` (閉じたものも含む) |
| `partial` | その項目の中の欠けの種類 (`project items` の `problems` の `what` のうち項目を持つもの: 入れ子の connection の上限 `*-truncated`、コメントと出来事の続き `comments`・`events`)。無ければ空の配列 |

## 差分の種類と処理の順

`observe diff` は、スナップショットと今の Project (と PR の状態) の違いを、下の表の順 (計画の R12 の処理の順: 人の変更 → close・reopen と項目の除去 → `blockedBy` → コメント → PR → 項目の追加・並び順・本文の編集) に並べて返す。同じ種類の中は今の位置の順。要素は `kind`・`item` (コメントの URL の PR は null) と、種類ごとの値。

| 順 | 種類 (`kind`) | 条件 | 値 |
| --- | --- | --- | --- |
| 1 | `status` | Status の名前が違う | `before`・`after` |
| 2 | `field` | フィールドの値が違う (前にあって今は無い = 人が空にした、も含む。`Agent stuck state` を空にした・`Agent session ID` を別の値にした、はこれ) | `field`・`before`・`after` |
| 3 | `assignees` | 担当者が違う | `added`・`removed` |
| 4 | `labels` | ラベルが違う | `added`・`removed` |
| 5 | `closed` | 開いていた Issue が閉じた (`Done` を書く呼び出しは無い。組み込みワークフローが書く) | `before`・`after` |
| 6 | `reopened` | 閉じていた Issue が開いた | `before`・`after` |
| 7 | `removed` | 項目が Project から除かれた | `position` (前の位置) |
| 8 | `blocked_by` | blocker が足された・外された・開閉が変わった | `added`・`removed`・`state_changed` (`key`・`before`・`after`) |
| 9 | `comment` | コメントが足された | `ids` (足されたコメントの `database_id`) |
| 10 | `pr` | PR の状態 (`state`・`draft`・`merged`) が違う、または PR が現れた・消えた | `url`・`source` (`reference` Issue を閉じる参照 / `comment` コメントの URL)・`before`・`after` |
| 11 | `added` | 項目が Project に足された | `position` |
| 12 | `position` | 両方にある項目の相対の順が変わった (項目の追加・除去で位置の数値がずれただけでは返さない)。1 件で、`item` は null | `before`・`after` (項目のキーの配列。位置の順) |
| 13 | `body_edit` | 本文の最新の編集の時刻が違う | `before`・`after` |

**欠けの扱い。** 項目の一覧そのものの欠け (`problems` の `what` が `items-page`・`graphql-errors`) があれば、読めなかっただけの項目が `removed` と読まれるので、差分を返さず保存もしない。1 項目の中の欠け (`partial`) と読めなかった PR は、読むたびに同じく出る (上限を超える項目や消された PR) ので観測を止めず、前後どちらかに欠けがある項目・PR だけを比べずに `skipped` (`items`: キー → 欠けの種類、`prs`: URL → 理由) で知らせる。

確認の対象か・割り当て中か・誰が足した blocker か・どの宣言が待っていたか、といった意味づけはここではしない (U13)。

## 書いた値の反映

書き込みのサブコマンド (`project set-status` / `issue add-label` / `blocked-by add` / `comment post`。後の単位の書き込みのサブコマンドも同じ) は、引数 `--snapshot-dir` (値は管理ディレクトリ) があれば、書いた値だけをスナップショットに反映する (関数 `reflect`)。読み取りの後にほかの人が変えた値は反映しない。スナップショットが無い・壊れている・項目が無いときは反映せず、出力の `snapshot.warnings` で知らせ、書き込みの結果は変えない。作業のセッションは管理ディレクトリを持たないので指定しない。

反映の操作: `status` (`value`)・`field` (`field`・`value`)・`comment` (`id`)・`blocked_by` (`action` `add` / `remove`・`blocker`・`state`)・`labels` / `assignees` (`add`・`remove`)。

## CLI

| サブコマンド | 書き込み | 返すもの |
| --- | --- | --- |
| `project items --project <owner>/<番号> --write-snapshot --dir <管理ディレクトリ>` | `snapshot.json` (GitHub には書かない) | 引数 `--write-snapshot` は `--dir` と一緒に指定する。`project items` の出力に `snapshot` (`path`・`taken_at`・`comment_prs`) を足す。項目の一覧そのものが欠ければ、スナップショットを書かずに `errors` (key `partial`) で返す。1 項目の中の欠けと読めなかった PR (`problems` の `what`: `comment-pr`) は印を付けて保存し、`status` は `partial`、`snapshot.skipped` にそれらを返す (「欠けの扱い」) |
| `observe diff --dir <管理ディレクトリ> --project <owner>/<番号>` | 無し | `diffs` (上の表の順)・`snapshot_taken_at`・`problems`・`rate_limit`。スナップショットが無い・壊れていれば `errors` (key `snapshot`) で、`gh` は実行しない。項目の一覧そのものが欠ければ、差分を返さずに `errors` (key `partial`) と `problems` で返す。1 項目の中の欠けと読めなかった PR は比べずに `skipped` で返し、`status` は `partial` (「欠けの扱い」)。スナップショットにある `comment_prs` の PR は、コメントが消えていても状態を読み直す (待っていた PR の変化を見つけるため) |
| 書き込みのサブコマンドの `--snapshot-dir <管理ディレクトリ>` | `snapshot.json` | 出力に `snapshot` (`reflected`・`warnings`) を足す |
