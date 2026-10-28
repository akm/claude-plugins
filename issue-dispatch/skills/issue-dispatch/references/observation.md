# 観測 (スナップショットと差分)

このファイルが、この仕組み (issue-dispatch) の観測 — スナップショット (`snapshot.json`)・差分・待機 — の SSOT (single source of truth。ある事実を定めている唯一の記述)。待機 (`wait.pid` の様式・終了条件・終了コード・標準出力) は「待機」の節。ディレクトリ (`<管理ディレクトリ>/<record_dir>/<owner>-<number>/`) と種類ごとの扱いは [records.md](records.md)。モジュール `issue-dispatch/scripts/issue_dispatch/observe.py` が読み書き・作成・反映・差分を実装し、`gh` は実行しない (項目の読み取りは `project items`、PR の状態は `issues.pr_state`)。待機はモジュール `issue-dispatch/scripts/issue_dispatch/poll.py` が実装する。

## 目的

スナップショットは、前のターンの終了時の Project の状態 (と、コメントに URL で書かれた PR の GitHub 上の状態) の写しで、GitHub から導出し直せるキャッシュ (計画の KTD5)。使うのは 2 つ: 待機が変化に気づいて管理のセッションを起こすこと (U14) と、人の変更を 1 回だけ報告すること (計画の R22)。**何を行うかはスナップショットからは決めない** — 導いた項目の状態 (U13) で決める。差分は「何が変わったか」だけを返し、意味づけ (管理のセッションが足した blocker か・どの宣言が待機するか) はしない。

書き込み元は管理のセッションの再入のターンだけ。Project を読んだとき (`project items --write-snapshot`) に書き、そのターンの CLI の書き込みのたびに書いた値を反映する。待機の直前には再度読み込まない (再度読み込むと、ターンの最初の読み取りから再度の読み込みまでの間にほかの人が起こした変化が、処理されないままスナップショットに入り、待機がその変化に気づかない)。書き込みに失敗したのに反映した値は、次の差分が不一致として見つけ、次のターンで直す。壊れていれば作り直す。

## `snapshot.json` の様式

持つ値は、計画の R21 の「見つける変化」の一覧から決め、一覧に無い値 (タイトル・本文・出来事など) は持たない。

| キー | 内容 |
| --- | --- |
| `version` | 様式の版 (`1`) |
| `taken_at` | Project を読んだ時刻 (UTC) |
| `project_id` | Project の ID |
| `items` | 項目のキー (`owner/repo#番号`) → 下の表。Issue 以外の項目 (draft issue・PR) は持たない |
| `comment_prs` | 開いている項目のコメント (`PR の報告` の本文の URL と、`待機` の理由 `小さな PR` の PR。投稿者がトークンのログインのものだけ) に書かれた PR の URL → `state`・`draft`・`merged`。読めなかった PR は、前のスナップショットに状態があればそれを引き継いで `carried` (引き継いだ値の元の `taken_at`) を持ち、無ければ `partial` に理由を持つ (「欠損の扱い」)。どの割り当てのものかは区別しない (意味づけは U13)。閉じた項目のコメントは読まない |

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
| `partial` | その項目の中の欠損の種類 (`project items` の `problems` の `what` のうち項目を持つもの: 入れ子の connection の上限 `*-truncated`、コメントと出来事の残りのページ `comments`・`events`) のうち、前のスナップショットから値を引き継げなかったもの (フラグ)。無ければ空の配列。差分で比べない値は「欠損の扱い」の表 |
| `carried` | 欠損の種類 → 引き継いだ値の元の `taken_at`。その種類の欠損の影響を受ける値 (「欠損の扱い」の表) は、今読んだ値ではなく前のスナップショットの値 (最後に全部読めたときの値) を持つ。無ければ空のオブジェクト |

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

**欠損の扱い。** 項目の一覧そのものの欠損 (`problems` の `what` が `items-page`・`graphql-errors`) があれば、読めなかっただけの項目が `removed` と読まれるので、差分を返さず保存もしない。1 項目の中の欠損 (入れ子の connection の上限、コメントと出来事の残りのページの読み取りの失敗) と読めなかった PR では観測を中断せず、次のように扱う。

- **前のスナップショットに引き継ぐ元があるとき** (前のスナップショットにその項目 (PR) があり、同じ種類が `partial` に無い): その種類の欠損の影響を受ける値 (下の表) に、今読んだ値ではなく前のスナップショットの値を書き、`carried` に元の `taken_at` を残す (前のスナップショットでも引き継いでいれば、その元の `taken_at`)。差分は普通に比べる。欠損が続くあいだは引き継いだ値どうしなので差分は出ず、全部読めるようになったターンに、最後に全部読めたときからの変化だけが出る。
- **引き継ぐ元が無いとき** (前のスナップショットが無い・その項目が無い・前のスナップショットでも同じ種類が `partial`): 今読んだ値のまま、その種類を `partial` (フラグ) に入れる。差分は、前後どちらかの `partial` にある種類の欠損の影響を受ける値だけを比べない (読めなかっただけの分を変化と読まないため)。欠損と関係のない値 (close・Status・担当者など) と、項目の追加・除去・並び順は比べる。表に無い種類の欠損は、どの値が影響を受けるか分からないので、引き継がず、その項目のすべての値を比べない。

読めなかった PR は `comment_prs` の値そのものが欠損なので、引き継げなければ比べない。`partial` のある項目と PR は `skipped` (`items`: キー → 欠損の種類、`prs`: URL → 理由) で、引き継いだ項目と PR は `carried` (`items`: キー → 種類 → 元の `taken_at`、`prs`: URL → 元の `taken_at`) で知らせる。

| 欠損の種類 (`partial`。名前と意味の SSOT は [project-schema.md](project-schema.md) の CLI の表の `problems`) | 引き継ぐ値 (項目のキー) | 比べない差分の種類 |
| --- | --- | --- |
| `labels-truncated` | `labels` | `labels` |
| `blocked_by-truncated` | `blocked_by` | `blocked_by` |
| `body_edits-truncated` | `body_edited_at` | `body_edit` |
| `prs-truncated` | `prs` | `pr` (`source` が `reference` のもの) |
| `fields-truncated` | `fields`・`status` (Status もフィールドの値の connection から読む) | `field`・`status` |
| `comments` | `comment_ids` | `comment` |
| `events` | 無し (出来事はスナップショットに持たない。引き継がず `partial` に入る) | 無し |

確認の対象か・割り当て中か・誰が足した blocker か・どの宣言が待機していたか、といった意味づけはここではしない (U13)。

## 書いた値の反映

書き込みのサブコマンド (`project set-status` / `issue add-label` / `blocked-by add` / `comment post`。後の単位の書き込みのサブコマンドも同じ) は、引数 `--snapshot-dir` (値は管理ディレクトリ) があれば、書いた値だけをスナップショットに反映する (関数 `reflect`)。読み取りの後にほかの人が変えた値は反映しない。スナップショットが無い・壊れている・項目が無いときは反映せず、出力の `snapshot.warnings` で知らせ、書き込みの結果は変えない。作業のセッションは管理ディレクトリを持たないので指定しない。

反映の操作: `status` (`value`)・`field` (`field`・`value`)・`comment` (`id`)・`blocked_by` (`action` `add` / `remove`・`blocker`・`state`)・`labels` / `assignees` (`add`・`remove`)。

## 待機

待機は、管理のセッションと作業のセッションがバックグラウンドで起動するプロセス (計画の KTD6)。管理のセッションの `wait` はスナップショットとの差分で終了し、作業のセッションの `wait-assignment`・`wait-decision` は項目の状態 ([flow.md](flow.md) の導出。`work check` と同じ判断) で終了する。どの待機も、**読んだ時点の状態で判定する** (起動の前から成り立っていれば、最初の読み取りで終了する)。スナップショットは読むだけで書かない (書くのは管理のセッションのターン)。待機は記録を読まない。

間隔 (`--interval`) と期限 (`--minutes`) は分で、小数も書ける。間隔が期限以上なら `argparse` と同じ終了コード 2 で拒否する。`wait` では省略時に設定の `poll_minutes`・`wait_minutes` を使う ([project-config.md](project-config.md))。作業の待機は、作業中のブランチのリポジトリの設定から取った値を渡す。

### `wait.pid`

実行中の待機を示すファイル。保存先は、管理の `wait` では記録のディレクトリ ([records.md](records.md))、作業の待機では `${TMPDIR:-/tmp}/issue-dispatch/<セッション ID>/` ([messaging.md](messaging.md) の一時ディレクトリ。作業ツリーには何も書かない)。JSON で、`pid` (待機のプロセス)・`started_at` (そのプロセスの開始時刻。`ps -o lstart=` の文字列のまま)・`owner` (所有者のセッション ID)・`wait` (待機の名前)・`written_at` を持つ。一時名に書いてから改名する。

- **起動時**: `wait.pid` があれば、その PID のプロセスの開始時刻が `started_at` と一致し、コマンドがこの CLI の待機 (`issue_dispatch.py` と待機の名前を含む) なら、SIGTERM を送って終了するまで待機する。一致しなければ (PID が別のプロセスに再利用されている)、停止せずに `wait.pid` だけ消す。その後、自分の PID で `wait.pid` を書き、標準出力の最初の行に `pid <PID>` を書く。
- **終了するとき**: `wait.pid` の PID が自分のときだけ消す (停止された待機が、後から起動した待機の `wait.pid` を消さないため)。
- **SIGTERM を受けたとき**: 標準出力に `stopped <PID>` を書き、終了コード 6 で終了する。読み取り (`gh` の呼び出し) の間に受けたときも、その読み取りの結果 (終了条件に当たっていても) を捨てて同じく終了する (捨てた変化は、新しい待機が最初の読み取りで見つける)。前の待機を停止する新しい待機は、待機時間の後も前の待機が動いていても起動を続ける (前の待機は、その読み取りが終了したときに停止する)。再入の手順は、出力に `stopped` の行があるか、`wait.pid` に通知と別の PID があるときは何もしない (停止した待機の通知で再入を繰り返さないため。計画の R24)。

### 終了条件と標準出力

標準出力は、最初の行が `pid <PID>`、終了の行が先頭の語で種類を示す 1 行 (期限と失敗の終了コードでは終了の行を書かない)。スキルは先頭の語で分ける。

| 待機 | 終了条件 | 終了の行 |
| --- | --- | --- |
| `wait` | スナップショットと今の Project (と `comment_prs` の PR の状態) に差分がある (「差分の種類と処理の順」) | `diff <種類,...>` (差分の種類を処理の順に、重複なく) |
| `wait-assignment` | 新しい割り当て: `--blocked`・`--in-review`・`--pending` に渡した Issue 以外で、開いていて、自分の ID が `Agent session ID` に入り、自分宛ての最新の `割り当て` があってその番号の `解放` が無く、Status が `In Progress` の項目 (`割り当て` が無い項目は、割り当ての書き込みの途中なので返さない) | `assignment <項目>` |
| `wait-assignment` | `--blocked` に渡した Issue が `In Progress` に戻った (フィールドが自分の ID) | `resumed <項目>` |
| `wait-assignment` | `--pending` に渡した Issue が戻った: 開いていて、フィールドが自分の ID で、Status が `In Progress` か `Blocked` | `resumed <項目>` |
| `wait-assignment` | `--in-review`・`--pending` に渡した Issue の正常な完了 ([flow.md](flow.md) の `end`。正常な完了の後に reopen されてフィールドが空にされた場合を含む。進行中の Issue の close では終了しない) | `stop close` |
| `wait-assignment` | 自分宛ての `依頼` (本文の追記) があり、その PR が開いていて、閉じる参照にまだ Issue が無い (追記が済んだ PR と閉じた PR では終了しない) | `request` |
| `wait-decision` | 自分宛てで、`--declaration` に渡した宣言の ID を持つ `開始可` | `go` |
| `wait-decision` | 自分宛てで、`--declaration` に渡した宣言の ID を持つ `依頼` (宣言の修正) | `request` |
| `wait-decision` | 今の Issue の Status が `Blocked` で、それが管理のセッションが書いた `Blocked` ([flow.md](flow.md) の `manager_blocked`。利用者が手で付けた `Blocked` では終了しない) | `wait` |
| `wait-decision` | `--review-update` を渡されたときの、今の Issue の正常な完了 | `stop close` |
| どちらも | 見る Issue (`wait-assignment` では `--blocked`・`--in-review`・`--pending` に渡した Issue、`wait-decision` では `--issue`) に、自分宛てで今の割り当ての番号の `解放` がある (フィールドが自分の ID でなくなっただけでは終了しない) | `stop <理由>` (理由は `解放` の先頭行の値) |
| どちらも | SIGTERM を受けた | `stopped <PID>` |

複数が同時に当たれば、`wait-assignment` は `stop` → `request` → `resumed` → `assignment`、`wait-decision` は `stop` → `go` → `request` → `wait` の順で 1 つを返す。前の割り当て・別の宛先・別の宣言への `開始可`・`解放` では終了しない (コメントの投稿者がトークンのログインと同じものだけを見る)。

### 終了コード

| 終了コード | 意味 | 作業のセッションの扱い (計画の KTD6) |
| --- | --- | --- |
| 0 | 終了条件に当たった (終了の行あり) | 終了の行の語で分ける |
| 124 | 期限 (期限切れを宣言する前にもう 1 度確認する) | 状態ごとの扱い (`available` の送り直しなど) |
| 8 | `gh` の認証切れ | 中断し、`gh auth login` を案内する |
| 3 | レート制限の再開 (`gh api rate_limit`) を期限内に待機できない、または再開時刻を読めない (期限内なら待機して続ける) | 何も送らずに起動し直す |
| 4 | ネットワークの失敗 (接続の失敗・タイムアウト・`gh` のほかの失敗) が続けて 3 回 (間に成功があれば数え直す) | 1 回目は起動し直す。2 回目も 4 なら中断する |
| 5 | スナップショットが無い・壊れている (`wait` だけ。上書きしない。先に `project items --write-snapshot` が要る) | — |
| 6 | 停止された (`stopped` の行) | 何もしない |
| 2 | 引数の誤り (`argparse`) と、間隔が期限以上 | 中断する |

## CLI

| サブコマンド | 書き込み | 返すもの |
| --- | --- | --- |
| `project items --project <owner>/<番号> --write-snapshot --dir <管理ディレクトリ>` | `snapshot.json` (GitHub には書かない) | 引数 `--write-snapshot` は `--dir` と一緒に指定する。`project items` の出力に `snapshot` (`path`・`taken_at`・`comment_prs`) を足す。項目の一覧そのものが無ければ、スナップショットを書かずに `errors` (key `partial`) で返す。1 項目の中の欠損と読めなかった PR (`problems` の `what`: `comment-pr`) は、既存のスナップショットに引き継ぐ元があれば前の値を引き継ぎ、無ければフラグ `partial` を付けて保存し、`status` は `partial`、`snapshot.skipped` と `snapshot.carried` にそれらを返す (「欠損の扱い」)。読む PR は今のコメントに書かれたものだけで、既存のスナップショットにだけある PR は再度読み込まず保存にも残さない (項目が閉じた後の PR の URL が増え続けないため)。既存のスナップショットが壊れていれば、引き継がずに上書きし、`snapshot.warnings` (key `snapshot`) で知らせる |
| `observe diff --dir <管理ディレクトリ> --project <owner>/<番号>` | 無し | `diffs` (上の表の順)・`snapshot_taken_at`・`problems`・`rate_limit`。スナップショットが無い・壊れていれば `errors` (key `snapshot`) で、`gh` は実行しない。項目の一覧そのものが無ければ、差分を返さずに `errors` (key `partial`) と `problems` で返す。1 項目の中の欠損と読めなかった PR は、スナップショットに引き継ぐ元があれば前の値を引き継いで比べ (`carried` で返す)、無ければその種類の欠損の影響を受ける値 (PR はその PR) を比べずに `skipped` で返し、`status` は `partial` (「欠損の扱い」)。スナップショットにある `comment_prs` の PR は、コメントが消えていても状態を再度読み込む (待機していた PR の変化を見つけるため) |
| 書き込みのサブコマンドの `--snapshot-dir <管理ディレクトリ>` | `snapshot.json` | 出力に `snapshot` (`reflected`・`warnings`) を足す |
| `wait --dir <管理ディレクトリ> [--project <owner>/<番号>] [--interval <分>] [--minutes <分>]` | `wait.pid` (記録のディレクトリ) | 「待機」の節。終了コードと標準出力の行 (JSON ではない)。スナップショットが無い・壊れていれば 5 |
| `wait-assignment --project <owner>/<番号> [--session <ID>] [--blocked <Issue>]... [--in-review <Issue>]... [--pending <Issue>] --interval <分> --minutes <分>` | `wait.pid` (一時ディレクトリ) | 「待機」の節。`--session` を省けば環境変数 |
| `wait-decision --project <owner>/<番号> --issue <Issue> [--session <ID>] --declaration <宣言のコメントの ID> [--review-update] --interval <分> --minutes <分>` | `wait.pid` (一時ディレクトリ) | 「待機」の節 |
