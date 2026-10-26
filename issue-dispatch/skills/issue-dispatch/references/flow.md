# 処理の流れ (項目の状態)

このファイルが、この仕組み (issue-dispatch) の、管理のセッションがターンのたびに導く**項目の状態**の正本 (計画の R24・KTD19)。状態ごとの取得元 (GitHub のどこから導くか) と判断の基準、場面ごとの扱い、`item state` と作業のセッションの確認 (`work check`・`work held`) が返す値をここに書く。宣言の判定の節は U15 で、割り当ての節は U16 で、状態遷移の図と決定表は U21 で足す。モジュール `issue-dispatch/scripts/issue_dispatch/itemstate.py` が導出を実装し、`gh` は実行しない (項目は `project items`、`PR の報告` の PR の状態は `pr observe` と同じ関数で、呼び出し元が読んで渡す)。

ターンで行うこと (書き込みの候補・質問すること・報告) の導き方は「ターンで行うこと」の節。`item state` は書き込まず、管理のセッション (U21・U23 のスキル) が既存のサブコマンドで実行する。

## 項目の状態の取得元

状態ごとに取得元を 1 つに決める。導出・作業のセッションの確認・待機の終了条件 (U14) は、どれもこの表の取得元を読む。Status (利用者と組み込みワークフローも変える) と担当者では決めない。

| 状態 | 取得元 | 書き込み元と書く順 |
| --- | --- | --- |
| 割り当て中か (`assigned`) | 今の割り当てのコメント `割り当て` (宛先と番号) があり、その番号の `解放` が無く、正常な完了 (下の行) もしていない。進行中の Issue が閉じて、利用者の質問に回答が出ていない間は割り当て中。担当者と Status では決めない | 管理 (`Agent session ID` は排他のフラグで、コメントより先) |
| 割り当ての終了 (`end`) と reopen (`reopened`) | 終了 = 今の番号の `解放` (`kind` が `released`) か、正常な完了 (`kind` が `normal`): Issue が閉じていて、進行中 (`in_progress`) でない。進行中 = 今の割り当ての PR が無いか、読んだ時点で ready for review にもマージ済みにもなっていない。閉じたもの (`ClosedEvent` の `closer`) は問わない。Issue が開いている (reopen された) ときは、今の割り当ての最新の `ClosedEvent` の時点で PR が ready for review かマージ済みだった (PR がマージ済み、または close より前に作られた PR が読んだ時点で draft でない) ことで正常な完了と読む。reopen = 終了した後の `ReopenedEvent`。Status だけの `Todo`・`Done` は、終了でも reopen でもない | 管理 (`解放`。理由ごとに続けて書くものは [issue-format.md](issue-format.md) の `解放`)・利用者 (reopen) |
| 宣言の段階 (`declaration`) | 今の割り当ての判定の要る最新の宣言 (`judged`) と、その宣言への `開始可`・`待機`・宣言の修正の `依頼` のうち最新のもの | 作業 (宣言)・管理 (結果のコメント → Status → 合図) |
| 待機しているもの (`waiting_blockers`)・管理のセッションが書いた `Blocked` (`manager_blocked`) | 判定の要る最新の宣言への、最新の `開始可` より後の `待機` の理由と相手。管理のセッションが書いた `Blocked` かは、理由に `Issue` か `小さな PR` を含む最初の `待機` と、`Blocked` への Status の変化の時刻で判別する (下の基準) | 管理 (`待機` → 理由が `Issue` か `小さな PR` のときだけ `blockedBy` → `Blocked` → 合図。資源・設定・利用者の回答の理由では Status を変えない) |
| 自分が足した `blockedBy` (`own_blockers`) | 今の割り当てのすべての `待機` (前の宣言へのものも、`開始可` の前のものも含む) の理由の `Issue` と `小さな PR` の依頼先の Issue。`blocked-by remove` が外してよい blocker と、人が足した blockedBy の判別に使う | 管理 (`待機` → `blockedBy`) |
| 今の割り当ての PR (`pr`) | 今の割り当て (`割り当て` より後) の最新の `PR の報告` の本文の URL の PR (作者がトークンのログインと違えば無いものとする)。無ければ、Issue を閉じる参照の PR (`closedByPullRequestsReferences`) のうち、作者がトークンのログインで、作成が `割り当て` より後のもの (複数なら作成が最新)。この行が「今の割り当ての PR」の唯一の取得元。`PR の報告` の PR が読めなければ、PR は無しとして `problems` (`what` が `pr-unreadable`) で知らせ、閉じる参照の PR には戻らない (読めるようになれば報告の PR を使うため) | 作業 (`PR の報告` → 合図 `review`) |
| 資源の使用 (`reserved`・`held`) | 予約 = コメント `割り当て` の時点で付いていたラベル `resource:<名前>` (接頭辞は大文字小文字を区別しない。GitHub のラベルの名前が区別しないため) のうち、属性 `reserve` が `on_assign` のもの。持っている資源 (定義の正本は [issue-format.md](issue-format.md) の「更新の種類」。差し戻された宣言は数えない)。空いていない資源がある宣言は、`開始可` まで何も持たない | 利用者 (ラベル)・作業 (宣言)・管理 (`開始可`) |
| 小さな PR | `待機` の理由の `小さな PR` と依頼先の Issue (と、報告の後は PR の URL) | 管理 (依頼・`待機`)・作業 (報告) |
| 割り当ての無い項目の `Blocked` | 最新の `依存の待機` があり、その後に `依存の解消` が無い (管理のセッションが書いたもの)。無ければ利用者が手で付けたもの | 管理 (コメント → Status) |
| 担当者の変化 | Issue の担当者 (範囲は担当者がトークンのログイン 1 人の項目) と、記録の未回答の質問 | 利用者。割り当て中なら、回答が出るまで作業中の項目のまま |
| 記録だけにあるもの | `record.json` (割り当ての意図・質問と回答・報告済みのフラグ・確認した本文の編集の時刻。[records.md](records.md)) | 管理。記録を失えば失う (「記録を失ったとき」) |

**判断の基準** (場面ごとの扱いを決めるときに使う):

- 時刻は、コメントの投稿の時刻と Issue の出来事 (`ClosedEvent`・`ReopenedEvent`・`LabeledEvent`・`UnlabeledEvent`・`ProjectV2ItemStatusChangedEvent` など) の時刻で比べる。出来事を起こしたアカウント (`actor`) は使えない (管理のセッションと利用者は同じアカウントで書く)。Status の出来事は、この Project のもの (`project_number`) だけを見る。
- ある時点の状態 (そのとき付いていたラベルなど) は、その時点までの出来事を時刻の順に全部読んで求める。最初や最新の出来事だけで決めない。
- 投稿者がトークンのログインと違う先頭行のコメントは、この仕組みのコメントとして扱わない ([issue-format.md](issue-format.md) の「コメント」)。
- 宛先と番号を持つ種類のコメント (`開始可`・`待機`・`解放`・`依頼`) は、今の割り当ての宛先と番号のものだけを使う。前の割り当てのものは使わない。
- 同じ場面に 2 つの決まりが当たるときは、利用者の変更を上書きしないほうを選ぶ。

**決めたこと**:

- マージされずに閉じた PR は、draft でなければ ready for review と読む (読んだ時点の `state`・`merged`・`draft` で判定するため)。
- 今の割り当ての PR の候補が複数あるとき (閉じる参照の PR が今の割り当ての後に複数) は、作成が最新のものを使う。
- 開いている Issue の正常な完了の判定は、close の時点で PR が draft だった後に ready になった場合を判別できない (PR の timeline を読まないため)。判別が要ると分かったら、`pr observe` に PR の出来事を足す。
- `開始可` を書くとき (待機が解けて判定し直した後) は、Status を戻り先に戻してから合図を送り (計画の R20)、その `待機` のために足した blockedBy (`own_blockers`) は利用者の承認を得てから `blocked-by remove` で外す (閉じた blocker が残っても判定には影響しないので、承認を待機する間も作業は進む)。
- 管理のセッションが書いた `Blocked` は、判定の要る最新の宣言への `待機` のうち、理由に `Issue` か `小さな PR` を含み、最新の `開始可` より後の最初のものがあり、Status が `Blocked` で、`Blocked` への Status の変化の時刻がその `待機` 以後のもの。変化が `待機` より前なら利用者が付けたもの (`manager_blocked` は偽)。戻り先 (`return_status`) は `In Progress`。
- JSON のコードブロックが読めない宣言と、形が誤っている宣言 (検査は [issue-format.md](issue-format.md) の「宣言」の `declaration parse` と同じ。種類は付けない) も、判定の要る宣言にする (`declaration` は null で `error` に理由。管理のセッションが差し戻す)。

## 宣言の段階

判定の要る宣言は、着手の宣言と宣言の更新のうち、`開始可` の後の資源を外すだけの更新 (`resources-removed-only`) を除いたもの。差し戻された (宣言の修正の `依頼` がある) 宣言を修正した更新は、資源を外しただけでも判定の要る宣言。差し戻された宣言は、持っている資源の計算に入れない。

| 段階 (`stage`) | 条件 |
| --- | --- |
| null | 今の割り当ての宣言が無い (何も求めず、作業のセッションの宣言を待機する) |
| `undecided` | 判定の要る最新の宣言に、判定の結果 (`開始可`・`待機`・宣言の修正の `依頼`) が無い |
| `go` | 最新の結果が `開始可` (作業中) |
| `waiting` | 最新の結果が `待機` (`wait` に理由と相手) |
| `returned` | 最新の結果が宣言の修正の `依頼` |

## 場面ごとの扱い

テストで決めた扱い (テストの名前に場面を書く。`issue-dispatch/tests/test_itemstate.py`)。

| 場面 | 読み方 |
| --- | --- |
| フィールドに ID があるが、コメント `割り当て` が無い | 割り当て中ではない (取得元はコメント) |
| 前の割り当ての `解放` があり、新しい `割り当て` がある | 新しい割り当てが今の割り当て。前の `解放` は数えない |
| 割り当て中の項目の Status が `Todo` にされた (Status の変化が `割り当て` より後) | 終了でも reopen でもない。割り当て中のまま、解除するかを質問する (`status-changed`) |
| `割り当て` の後にフィールドか Status が書かれていない (更新がコメントより前で、その後の Status の変化が無い) | 途中で中断された書き込み。残りの書き込み (`set-field`・`set-status` `In Progress`) を行う |
| フィールド `Agent session ID` の値が宛先と違い、更新が `割り当て` より後 | 利用者の変更。空なら `field-cleared`、別の値なら `field-changed` を質問する |
| 担当者が自分 1 人でなくなった | `assignee-changed` を質問する。回答が出るまで作業中の項目のまま |
| 進行中の Issue が閉じた | `close-in-progress` を質問する。回答が出るまで割り当て中で、ほかの書き込みはしない |
| `close-in-progress` の回答を待機する間に reopen された | 質問を撤回し (`withdraw-question`)、フィールドは空にせず、Status を導いた状態 (`Blocked` か `In Progress`) に戻し、`reopened-while-pending` を報告する |
| `待機` (理由に `Issue` か `小さな PR`) の後に blockedBy か `Blocked` が無い | その blocker の `BlockedByRemovedEvent` が `待機` より後に無ければ残りの書き込み (`blocked-by-add`) を行い、あれば `blocked-by-removed` を報告して足し直さない。Status の変化が `待機` より後に無ければ残りの書き込み (`set-status` `Blocked`) を行い、あれば `status-changed` を報告する |
| `In Progress`・`In review` の項目に人が足した blockedBy | 導出せず `blocked-by-added` を報告する |
| 確認の対象のリポジトリ (設定 `third_party_edit_check`) で、`割り当て` より後 (記録の確認した時刻より後) に第三者が本文を編集した | `third-party-edit` を質問する |
| `PR の報告` の PR が Issue を閉じる参照を持たず、向け先が既定のブランチ | `依頼` (本文の追記) を書く (同じ PR への未対応の `依頼` があれば書かない) |
| `PR の報告` の PR の向け先が既定のブランチでない | 本文の追記を頼まず `pr-base-not-default` を 1 回報告する (閉じる参照に現れないので `In review` にならず、マージでも Issue は閉じない。正常な完了の判定には使う) |
| 今の割り当ての PR がマージ済みで Issue が開いている | `merged-issue-open` を質問する |
| 今の割り当ての PR がマージされずに閉じ、Issue が開いている | `pr-closed-unmerged` を質問する |
| 正常な完了の後に PR が開いたまま残っている | 判定の相手にせず `pr-left-open` を 1 回報告する |
| 記録の意図にある項目が Project の一覧に無い | 除去。`removed` を質問する |
| 初めて扱う項目 (記録にその項目の情報が無い) で、最後に書いた管理のセッションの ID が自分と違う | `引き継ぎ` を書く (自分の `引き継ぎ` が既にあれば書かない) |
| 割り当ての無い項目 (担当者が自分 1 人、Status が `Ready` か `Blocked`) に開いている blocker がある | `依存の待機` → `Blocked`。`依存の待機` の後で中断されていれば残りの書き込み (`Blocked`) を行い、利用者が `Ready` に戻していれば (Status の変化がコメントより後) 報告して書き換えない |
| 管理のセッションが `Blocked` にした割り当ての無い項目の blocker がすべて閉じた | `依存の解消` → `Ready` |
| `依存の待機` の無い `Blocked` (利用者が手で付けた) | blocker が閉じても書き換えない |
| Issue が閉じていて、今の割り当ての PR がマージ済み・ready for review (開いている)・マージされずに閉じた (draft でない) | 正常な完了 (`end.kind` が `normal`) |
| Issue が閉じていて、今の割り当ての PR が無い・draft | 進行中の close。割り当て中のまま (利用者の回答を待機する) |
| reopen の後の割り当てで、前の割り当てのマージ済みの PR だけがある | 今の割り当ての PR は無い。進行中 |
| 正常な完了か `解放` の後に `ReopenedEvent` | `reopened`。フィールドが自分の書いた値 (今の割り当ての宛先) なら空にして (`clear-field`) 報告する。人が書いた値は消さない。Status は変えない |
| 進行中の close の後の `ReopenedEvent` | 終了した後の reopen ではない (回答を待機する間の reopen) |
| `PR の報告` の PR の作者がトークンのログインと違う | 無いものとし、閉じる参照の PR を使う |
| `PR の報告` の PR が Issue を閉じる参照を持たない | `pr.closing` が偽 (`In review` にせず本文の追記を頼む材料) |
| `待機` の理由が `利用者の回答`・`資源`・`設定` だけ | Status を変えない理由なので、Status が `Blocked` でも管理のセッションのものではない |
| `待機` (理由に `Issue` か `小さな PR`) の後に `開始可` | 作業中 (`go`)。`own_blockers` は空 |
| `開始可` の後の、資源を外すだけの更新 | 判定の要る宣言は `開始可` の宣言のまま。持っている資源は減る |
| `開始可` の後の、ファイルを変えた更新 | 判定の要る宣言はその更新 (`undecided`)。持っている資源は `開始可` の宣言のもののまま |
| 割り当ての後に利用者が足したラベルの資源 | 予約していない (`reserved` に入らない。宣言のときに空きを確認する) |

## `item state` が返す値

| キー | 内容 |
| --- | --- |
| `key` | 項目 (`owner/repo#番号`) |
| `assignment` | 今の割り当て (`to` 宛先・`number` 番号・`comment_id`・`at`)。無ければ null (以下のキーは初期値) |
| `release` | 今の番号の `解放` (`comment_id`・`at`・`reason`)。無ければ null |
| `pr` | 今の割り当ての PR (`url`・`source` (`report` / `reference`)・`state`・`draft`・`merged`・`closing` (Issue を閉じる参照に割り当ての Issue を含むか)・`base_ref`・`created_at`)。無ければ null |
| `in_progress` | 進行中か |
| `end` | 割り当ての終了 (`kind` が `released` / `normal`・`at`・`released` なら `reason`)。無ければ null |
| `assigned` | 割り当て中か |
| `reopened` | 終了した後の reopen (`at`)。無ければ null |
| `declaration` | `judged` (判定の要る最新の宣言: `comment_id`・`at`・`kind`・`declaration` (JSON。読めなければ null)・`error`・`update_kind`)・`stage`・`go`・`wait` (`comment_id`・`at`・`reasons`)・`returned`・`manager_blocked`・`blocked_wait` (その `待機` の ID)・`return_status`・`own_blockers`・`waiting_blockers` (Issue の参照の配列)・`go_declaration`・`go_declaration_id` (その `開始可` の宣言のコメントの ID)・`held` (名前の順)・`declared_resources` (読めた宣言ごとの `comment_id`・`at`・`resources`・`returned` (差し戻されたか)・`go` (`開始可` があるか)。投稿の順。判定がコメントを再度読み込まずに、宣言に無い予約の解放と更新の前に持っていた資源を求める) |
| `reserved` | 割り当てのときに予約した資源 (名前の順) |
| `problems` | 導出を続けられるが知らせるもの (`what` が `pr-unreadable`: `PR の報告` の PR が読めない) |

出力の `usage` は、割り当て中の項目の `reserved` と `held` から導いた資源の使用 (資源の名前 → 持つ項目の配列。[resources.md](resources.md) の判断が読む)。

## 作業のセッションの確認

同じ導出の、自分の項目についての読み出し (計画の R26・R27)。書き込みの `gh` は実行しない。

| サブコマンド | 返すもの |
| --- | --- |
| `work check` | `field_is_mine` (フィールド `Agent session ID` が自分の ID か)・`assignment`・`assigned_to_me` (今の割り当ての宛先が自分か)・`released` (今の番号の `解放`)・`pending_requests` (自分宛てで今の割り当ての番号の `依頼` のうち、まだ行っていないもの: `comment_id`・`at`・`kind`・`values`)・`third_party_edits` (`割り当て` より後の、トークンのログイン以外による本文の編集。確認の対象かは呼び出し元が決める) |
| `work held` | 自分宛ての今の割り当てで割り当て中の Issue (閉じて利用者の回答を待機する Issue を含む。割り当てが終了した Issue は返さない) を Project の順に: `key`・`state`・`status`・`assignment` (番号)・`judged`・`update_kind`・`stage`・`has_go`・`has_wait`・`manager_blocked`・`pending_requests` |

`依頼` を行ったかの判断: `宣言の修正` は、その後に `宣言の更新` があれば行った。`本文の追記` は、依頼の PR が Issue を閉じる参照にその Issue を含めば行った。`小さな PR` は、対応する `小さな PR の報告` ([issue-format.md](issue-format.md) の「報告と依頼の対応づけ」) があれば行った。

## ターンで行うこと

`item state` は、項目の状態に加えて、ターンで行うことを種類ごとに分けて返す。どれも書き込みの候補で、`item state` 自身は書かない。

| キー | 内容 |
| --- | --- |
| `actions` | 書き込みの候補 (下の表の種類)。`continuation` が真なら途中で中断された書き込みの残り |
| `questions` | 質問すること (`kind`・`item`・`options`。判定の質問は対象 `subject` も。項目の状態の質問の種類と選択肢は下の質問の表、判定の質問は「判定」の質問の表)。記録に同じ項目と種類 (と対象) の未回答の質問があれば質問し直さない。記録を失ったために質問し直すものは `record_lost` が真 |
| `reports` | 1 回だけ報告するもの (`kind`・`item` と内容)。記録の報告済みのフラグ (`reported`) があるものは返さない |
| `pending` | 回答を待機する項目 (`question_id`・`item`・`kind`・`asked_at`)。この項目には手を付けない (回答を待機する間の reopen による質問の撤回を除く) |
| `record_lost` | 記録を失ったか (記録が無い・前の記録が `ended`) |

| `actions` の種類 (`kind`) | 値 | 実行するサブコマンド |
| --- | --- | --- |
| `comment` | `comment_kind`・`values`・`body` | `comment post` |
| `set-status` | `item_id`・`status` | `project set-status` |
| `blocked-by-add` | `blocker` | `blocked-by add` |
| `blocked-by-remove` | `blocker`・`needs_approval` (真) | `blocked-by remove` (承認を得た後。「判定」の宣言の修正の扱い) |
| `set-field` | `item_id`・`field`・`value` | 割り当てのフィールドの書き込み (U16) |
| `clear-field` | `item_id`・`fields` | 同上 (空にする) |
| `withdraw-question` | `question_id` | `record apply` の `withdraw` |

| `reports` の種類 (`kind`) | 何を知らせるか |
| --- | --- |
| `status-changed` | 人が Status を変えた (`before`・`after`、または `status` と `after_comment`) |
| `field-changed` | 人が `Agent session ID`・`Agent session title` を変えた (割り当ての無い項目) |
| `blocked-by-added` / `blocked-by-removed` | 人が blockedBy を足した / 自分が足した blockedBy を外した (足し直さない) |
| `reopened` | 終了した後の reopen (`fields_cleared` 空にしたか) |
| `reopened-while-pending` | 回答を待機する間の reopen (質問を撤回した) |
| `pr-base-not-default` | `PR の報告` の PR の向け先が既定のブランチでない |
| `pr-left-open` | 正常な完了の後に PR が開いたまま残っている |

項目の状態の質問の種類 (`kind`) と選択肢 (`options`)。回答に従う処理は U16・U21 で決める。

| 種類 | 質問の内容 | 選択肢 |
| --- | --- | --- |
| `close-in-progress` | 進行中の Issue が閉じられた。作業のセッションに作業を中断するよう伝えるか、reopen して続けるか | `stop` / `reopen` |
| `assignee-changed` | 割り当て中の項目の担当者が自分 1 人でなくなった。割り当てを解除するか、そのまま続けるか | `release` / `continue` |
| `field-cleared` | `Agent session ID` が空にされた。解除するか、書き戻すか | `release` / `restore` |
| `field-changed` | `Agent session ID` が別の値にされた。解除するか、書き戻すか | `release` / `restore` |
| `removed` | 割り当て中の項目が Project から除かれた。解除するか、持ち続けるか | `release` / `keep` |
| `status-changed` | 割り当て中の項目の Status を手で変えられた。解除するか、Status を戻すか | `release` / `restore` |
| `third-party-edit` | 確認の対象の項目の本文を、割り当ての後に第三者が編集した。作業のセッションに作業を中断するよう伝えてよいか | `stop` / `continue` |
| `merged-issue-open` | PR がマージされたが Issue が開いている。閉じるか | `close` / `keep` |
| `pr-closed-unmerged` | PR がマージされずに閉じた。Status を戻して解除するか | `release` / `keep` |
| `user-answer-lost` | 記録を失ったので、`利用者の回答` を待機していた宣言の質問を出し直す (自由回答) | 無し |

**人の変更の判別** (計画の R22・KTD7): `--diffs` で渡した差分 (`observe diff` の出力) のうち、記録の意図 (自分の部分書き込み) と組み込みワークフローの遷移 (閉じた → `Done`、reopen → `Todo` (ワークフロー「Item reopened」が有効なとき)、追加 → `Todo`) と利用者が着手を決める遷移 (`Todo` か空 → `Ready`、reopen した項目の `Done` → `Ready`) で説明できないものを報告する。割り当て中の項目の Status とフィールドの変化は、場面の表のとおり質問にする。差分は報告のきっかけとしてだけ使い、残りの書き込みを行うかの判別には使わない (判別は出来事の時刻で行う)。

**記録を失ったとき** (記録が無い・前の記録が `ended`): 記録にだけある情報 (割り当ての意図・質問と回答・報告済みのフラグ・確認した本文の編集の時刻) を失い、同じ導出で続ける。`利用者の回答` を待機する宣言は `user-answer-lost` で質問し直し、閉じて回答を待機する項目は `close-in-progress` を質問し直し、報告済みのフラグが無いので人の変更などを 1 回ずつ報告し直すことがある。確認の対象の項目は、割り当ての前に利用者に再確認する (U16)。どれも `record_lost` を真にして返す。

**処理の順**: 項目ごとに、割り当てのある項目の場面 (`引き継ぎ` → 回答を待機する間の reopen → 終了した後の reopen と残った PR → 進行中の close → 担当者 → フィールド → Status → `待機` の残りの書き込み → 第三者の本文の編集 → PR) → 割り当ての無い項目の `Blocked` の再導出、の順に導き、最後に差分からの人の変更と、Project から除かれた項目を足す。差分の種類の順 (計画の R12) は [observation.md](observation.md)。未判定の宣言の判定の順は下の「判定」。待機していた宣言の再判定は U15 の後半。

## 判定

宣言の判定 (計画の R20・KTD9・KTD14・AE32・AE54)。モジュール `issue-dispatch/scripts/issue_dispatch/judge.py` (関数 `judge.judge`) と CLI の `declaration judge` がこれに従う。競合の可能性の規則は [issue-format.md](issue-format.md) の「競合の可能性」、資源の判断は [resources.md](resources.md) の契機の表、リポジトリの設定の読み方は [repositories.md](repositories.md) が正本で、ここでは言い直さない。

**判定の順序と比較の相手**: 未判定の宣言 (判定の要る最新の宣言で、段階が `undecided` のもの) を、投稿の順 (同じなら Project の中の順) に 1 件ずつ判定する。比較の相手は、その時点で `開始可` になっている宣言 (項目ごとに最新の `開始可` の宣言) だけで、未判定の宣言どうしは比較しない。同じ実行で先に `開始可` にした宣言は後の宣言の相手になり、予約した資源は後の宣言には空いていない。相手の項目の PR が ready for review の後なら、PR が変更したファイルのうち相手の宣言に無いものも、節なしのファイルとして相手に加える (「PR が変えたファイルとの照合」と同じ取得元)。比較の規則 (同じリポジトリの同じパスごと。別のリポジトリは競合しない) は [issue-format.md](issue-format.md) の「競合の可能性」。

**1 件の判定**: 上から順に分岐し、結果 (`result`) を `go`・`wait`・`ask`・`request` のどれかに決める。

| 順 | 条件 | 結果 |
| --- | --- | --- |
| 1 | 割り当てで予約したのに宣言に無い資源 (着手の宣言だけ。資源はリポジトリの規則に依らず読めた宣言の `resources` から分かるので、設定の読み取りと形の検査の前に行う。前の宣言で解放した予約は予約済みとしない。`resources.judge_declare` の `release`・`keep`・`ask_undeclared`・`request_rewrite`) | [resources.md](resources.md) の契機 `declare` の行のとおり、2 以降の結果に依らず扱う。`release` は結果の `release` に載せる (待機する宣言でも解放する)。`ask_undeclared` は質問 `release-undeclared` (対象は資源の名前) を出す (待機する宣言でも出す)。解放した資源と回答を待機する予約は、どの経路のコメントの本文にも書く。`request_rewrite` は `依頼` (宣言の修正: その資源を加える) にして終了、`開始可` は書かない |
| 2 | リポジトリの設定が読めない (`repo.read_repo_config` が `unreadable`) | `wait`: `待機` (理由 `設定`)。本文に理由と直し方と、直したら管理のセッションに知らせることを書く。そのリポジトリの宣言は判定しない。設定ファイルが無い (`missing`) は読めないことではなく、デフォルトの表だけで照合して進む |
| 3 | 宣言の形の誤り (コメントの JSON を、リポジトリの規則で種類を付けて `declaration.parse` で検査する) | `request`: `依頼` (宣言の修正)。本文に誤りの一覧と使った規則 (リポジトリの設定とデフォルトの表か、デフォルトの表だけか) を書く |
| 4 | 競合の可能性 (`declaration.conflictability`) の相手ごとの結果 | 相手ごとに、記録の質問の回答で扱いを決める (下の表)。ready for review の後の資源だけを変える更新 (`resources-only`) は比較しない |
| 5 | 宣言の資源の空き (着手の宣言は `judge_declare`、更新は `judge_update`) | 同じ契機 `declare` / `update` の行のとおり。結果 `wait` は `待機` (理由 `資源`)、`ask` は質問 `resource-busy` (対象は資源の名前) を出して回答まで `待機` (理由 `利用者の回答`)。4 で待機・質問になった宣言は 5 に進まない |
| 6 | どれにも当たらない | `go`: `開始可`。本文に比較した相手の数・予約した資源を書く |

競合の可能性の相手ごとの扱い:

| 相手の結果 | 記録の質問 (種類・対象 `subject`) | 回答と扱い |
| --- | --- | --- |
| `conflict` | `conflict`・`<相手の項目>:<相手の宣言の ID>` | 回答が無ければ質問し、回答まで `待機` (理由 `利用者の回答`)。`wait`: `待機` (理由 `Issue` 相手) と、相手を `blockedBy` に追加し Status を `Blocked` にする。`small-pr`: `待機` (理由 `小さな PR` 相手。相手の `小さな PR の報告` があれば PR も) と、相手のセッションへの `依頼` (小さな PR。待機する Issue がこの項目の `依頼` が相手の項目に既にあれば出さない) と `blockedBy`・`Blocked`。`proceed`: 競合しうるまま進む |
| `needs-user` (種類 `unknown-content` の同じパス) | `unknown-content`・`<相手の項目>:<相手の宣言の ID>:<パス>` | 回答が無ければ質問し、回答まで `待機`。`conflict`: その相手を `conflict` として上の行で扱う。`none`: 競合しない。同じ相手に `conflict` のパスもあれば `conflict` の質問だけを出す |

`待機` の理由 (すべて並べる決まりは [issue-format.md](issue-format.md) の「種類」) は、未回答の質問があれば `利用者の回答` を先頭に、回答済みの相手の `Issue`・`小さな PR` を続ける。結果は、未回答の質問があれば `ask`、無ければ `wait`。

判定の質問の種類 (`kind`) と選択肢 (`options`)。回答に従う処理はこの節が決める。

| 種類 | 質問の内容 | 選択肢 |
| --- | --- | --- |
| `conflict` | 宣言が相手 (`subject`) の `開始可` の宣言と競合しうる。相手の完了まで待機するか、共通の変更を先に小さな PR にするか、競合しうるまま進めるか | `wait` / `small-pr` / `proceed` |
| `unknown-content` | 種類 `unknown-content` の同じパス (`subject`) が競合しうるか | `conflict` / `none` |
| `resource-busy` | 宣言の資源 (`subject`) が空いていない (属性 `when_busy` が `ask`)。待機するか進めるか。回答を読む範囲は下の「資源の質問の回答が有効な範囲」 | `wait` / `proceed` |
| `release-undeclared` | 割り当てで予約したのに宣言に無い資源 (`subject`) を解放してよいか (属性 `release_undeclared` が `ask`) | `release` / `keep` |
| `small-pr-closed` | 待機していた小さな PR がマージされずに閉じた。相手の Issue の完了を待機するか、作り直しを頼むか、競合しうるまま進めるか (U15 の後半) | `wait-issue` / `redo` / `proceed` |

**質問の対象と宣言の修正**: 質問は項目・種類・対象 (`subject`) で引き、今の割り当て (コメント `割り当て` の時刻以後に質問したもの) の質問だけを読む (割り当てが終了すれば資源・宣言・相手が新しくなるので、前の割り当ての質問と回答は材料にしない)。回答の無いもの (未回答・撤回) は回答無しに数える。記録に同じ項目・種類・対象の未回答の質問があれば質問を出し直さない (`待機` は書く)。対象を相手の宣言の ID にするのは、判定を待機する宣言が修正されて自分の宣言の ID が変わっても、同じ相手への回答を使い、新しい相手だけ質問するため (計画の U15 の Approach 2)。小さな PR の `依頼` と `小さな PR の報告` は前の宣言の ID で対応づけたまま読み、新しい `依頼` は出さない。前の `待機` のために書いた `Blocked` と `blockedBy` は、新しい判定で `Issue`・`小さな PR` を待機しなければ Status を `In Progress` に戻し、自分が足した `blockedBy` のうち待機しなくなった相手は外す候補 (`blocked-by-remove`) にする。待機する相手が変われば、新しい相手を追加し前の相手を外す候補にする。記録の項目の `conflict_choice` は判定では使わない (`conflict` の質問の回答で代える)。

**資源の質問の回答が有効な範囲**: 質問 `resource-busy` の対象は資源の名前だが、保存された回答を読むのは、回答の時刻より後にその項目がその資源を解放していないときだけ (解放は、`開始可` になったどれかの宣言にあった資源が、それより後の読めた宣言の `resources` に無いこと。`declared_resources` から導く。関数 `judge.released_since`)。回答は「このとき始めた使用で、今の持ち主と同時に使ってよい (`proceed`) か待機する (`wait`) か」という判断なので、その使用が続く間 (`開始可` の前の修正・更新の出し直し) は読み、使い終えて解放した後に足し直した更新では読まずに質問を出す。記録は書き換えない (解放はコメントから導けるため)。

**`開始可` を書く直前の比較**: 判定は常にその時点の `開始可` の宣言すべてと比較するので、利用者の回答や待機の解消の後に `開始可` を書くときも、その間に `開始可` になった宣言と比べ直すことになる (AE54)。例外は ready for review の後の資源だけを変える更新で、比較しない。

**資源の使用** (`judge.usage_for`): `item state` の `usage` から、宣言に無い予約として解放したもの (`judge.released_reservations`) を除く。解放したとみなす予約は、`開始可` の後は持っている資源 (`held`) に無い予約 (後の宣言で足し直して予約し直したものは持っている) のうち、`開始可` になったどれかの宣言にあったもの (持った後に更新で外した資源。[resources.md](resources.md) の契機 `update` のとおり結果に依らず解放。最新の `開始可` の宣言だけで見ない) と、どの `開始可` の宣言にも無かったもの (宣言に書かれなかった予約) で属性 `release_undeclared` が `release` か質問 `release-undeclared` の回答が `release` のもの。`開始可` の前は今の割り当ての読めた着手の宣言 (修正を含む) のどれかに無い予約で、属性か回答が `release` のもの。判定する宣言より前の宣言で解放した予約は、その宣言の判定で予約済みとして扱わない (足し直せば新しい資源として空きを確認する)。解放は GitHub への書き込みが無い導出なので、判定と資源の使用が同じ関数で決める。

**返すもの**: `judgments` (宣言ごと: `item`・`declaration`・`to`・`assignment`・`update_kind`・`repo_config` (読み取りの結果の `status`)・`result`・`waits` (`待機` の理由)・`compared` (比較した相手の宣言の ID)・`recompared` (ファイルの競合の可能性を比較したか)・`reserve`・`release`・`keep` (回答を待機する予約))、`actions` (「ターンで行うこと」の種類。宣言ごとにコメントを先にする (R24))、`questions` (`subject` 付き)、`signals` (作業のセッションに送る合図: `kind` が `go`・`wait`・`request`、`to`・`item`・`declaration`。`request` は `request_kind` も。送り方は U17)。`declaration judge` 自身は書かない。

待機の解消 (相手の割り当ての終了・小さな PR のマージ・資源の解放・設定が読めるようになったこと・回答) の検出と再判定、質問 `small-pr-closed` は U15 の後半。

## CLI

| サブコマンド | 書き込み | 返すもの |
| --- | --- | --- |
| `declaration judge --dir <管理ディレクトリ> [--project <owner>/<番号>] [--issue <owner/repo#番号>]` | 無し | `judgments`・`actions`・`questions`・`signals` (「判定」)・`record_lost`・`problems`・`rate_limit`・`warnings`・`errors`。入力は `item state` と同じで、リポジトリの設定は設定の `repositories` の clone から読む。`--issue` は、投稿の順に並べた未判定の宣言のうち、その項目の宣言まで判定する (前に投稿された宣言も判定し、後の宣言は判定しない。その項目に未判定の宣言が無ければ何も判定しない。判定の順序の決まりを守るため。比較の相手はすべての項目から集める)。`--issue` が参照の形でなければ `errors` (key `issue`。`gh` を読まない)、Project に無ければ `rejected` (key `issue`) |
| `item state --dir <管理ディレクトリ> [--project <owner>/<番号>] [--issue <owner/repo#番号>] [--diffs <ファイル \| ->]` | 無し | `items` (割り当てのある項目の状態。上の表)・`usage`・`actions`・`questions`・`reports`・`pending`・`record_lost` (「ターンで行うこと」)・`problems`・`rate_limit`・`warnings`・`errors`。設定の `project`・`resources` (属性)・`third_party_edit_check` と、記録 (無ければ記録を失った扱い。壊れていれば `errors` (key `record`)) と、Project のメタ情報 (ワークフローの有効・無効) を読む。`--diffs` は `observe diff` の出力 (JSON)。項目の一覧そのものが無ければ (`problems` の `what` が `items-page`・`graphql-errors`) 導かずに `errors` (key `partial`) |
| `blocked-by remove --dir <管理ディレクトリ> --issue <owner/repo#番号> --blocker <owner/repo#番号> [--snapshot-dir <管理ディレクトリ>]` | `blockedBy` | 項目の状態の `own_blockers` にある blocker だけを外す (決まりの正本は [issue-format.md](issue-format.md) の「`blockedBy` の削除」)。それ以外は `rejected` (`own_blockers` を返す)。承認を得た後に呼ぶ。外したら `--snapshot-dir` のスナップショットに反映する ([observation.md](observation.md)) |
| `work check --project <owner>/<番号> --issue <owner/repo#番号> [--session <ID>]` | 無し | `session`・上の表の値・`problems`・`rate_limit`・`errors`。`--session` を省けば環境変数 (`CLAUDE_CODE_HOST_SESSION_ID`、無ければ `CLAUDE_CODE_SESSION_ID`)。項目が無ければ `errors` (key `issue`) |
| `work held --project <owner>/<番号> [--session <ID>]` | 無し | `session`・`items` (上の表)・`problems`・`rate_limit`・`errors` |

`PR の報告` の PR が読めなければ、`problems` (`what` が `report-pr`) で知らせ、その項目の `pr` は無しになる (上の表の行「今の割り当ての PR」)。

`blocked-by remove` の `gh` の呼び方も [issue-format.md](issue-format.md) の「`blockedBy` の削除」。
