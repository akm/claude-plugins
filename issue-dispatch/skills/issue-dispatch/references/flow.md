# 処理の流れ (項目の状態)

このファイルが、この仕組み (issue-dispatch) の、管理のセッションがターンのたびに導く**項目の状態**の正本 (計画の R24・KTD19)。状態ごとの出どころ (GitHub のどこから導くか) と判断の基準、場面ごとの扱い、`item state` と作業のセッションの確認 (`work check`・`work held`) が返す値をここに書く。宣言の判定の節は U15 で、割り当ての節は U16 で、状態遷移の図と決定表は U21 で足す。モジュール `issue-dispatch/scripts/issue_dispatch/itemstate.py` が導出を実装し、`gh` は実行しない (項目は `project items`、`PR の報告` の PR の状態は `pr observe` と同じ関数で、呼び出し元が読んで渡す)。

ターンで行うこと (書き込みの候補・尋ねること・報告) の導き方は「ターンで行うこと」の節。`item state` は書き込まず、管理のセッション (U21・U23 のスキル) が既存のサブコマンドで実行する。

## 項目の状態の出どころ

状態ごとに出どころを 1 つに決める。導出・作業のセッションの確認・待機の終わる条件 (U14) は、どれもこの表の出どころを読む。Status (利用者と組み込みワークフローも変える) と担当者では決めない。

| 状態 | 出どころ | 書き手と書く順 |
| --- | --- | --- |
| 割り当て中か (`assigned`) | 今の割り当てのコメント `割り当て` (宛先と番号) があり、その番号の `解放` が無く、正常な終わり (下の行) もしていない。進行中の Issue が閉じて、利用者の問いに答えが出ていない間は割り当て中。担当者と Status では決めない | 管理 (`Agent session ID` は排他の印で、コメントより先) |
| 割り当ての終わり (`end`) と reopen (`reopened`) | 終わり = 今の番号の `解放` (`kind` が `released`) か、正常な終わり (`kind` が `normal`): Issue が閉じていて、進行中 (`in_progress`) でない。進行中 = 今の割り当ての PR が無いか、読んだ時点で ready for review にもマージ済みにもなっていない。閉じたもの (`ClosedEvent` の `closer`) は問わない。Issue が開いている (reopen された) ときは、今の割り当ての最新の `ClosedEvent` の時点で PR が ready for review かマージ済みだった (PR がマージ済み、または close より前に作られた PR が読んだ時点で draft でない) ことで正常な終わりと読む。reopen = 終わった後の `ReopenedEvent`。Status だけの `Todo`・`Done` は、終わりでも reopen でもない | 管理 (`解放`。理由ごとに続けて書くものは [issue-format.md](issue-format.md) の `解放`)・利用者 (reopen) |
| 宣言の段階 (`declaration`) | 今の割り当ての判定の要る最新の宣言 (`judged`) と、その宣言への `開始可`・`待機`・宣言の書き直しの `依頼` のうち最新のもの | 作業 (宣言)・管理 (結果のコメント → Status → 合図) |
| 待っているもの・自分が足した `blockedBy` (`own_blockers`)・管理のセッションが書いた `Blocked` (`manager_blocked`) | 判定の要る最新の宣言への、最新の `開始可` より後の `待機` の理由と相手。管理のセッションが書いた `Blocked` かは、理由に `Issue` か `小さな PR` を含む最初の `待機` と、`Blocked` への Status の変化の時刻で見分ける (下の基準) | 管理 (`待機` → 理由が `Issue` か `小さな PR` のときだけ `blockedBy` → `Blocked` → 合図。資源・設定・利用者の答えの理由では Status を変えない) |
| 今の割り当ての PR (`pr`) | 今の割り当て (`割り当て` より後) の最新の `PR の報告` の本文の URL の PR (作者がトークンのログインと違えば無いものとする)。無ければ、Issue を閉じる参照の PR (`closedByPullRequestsReferences`) のうち、作者がトークンのログインで、作成が `割り当て` より後のもの (複数なら作成が最新)。この行が「今の割り当ての PR」の唯一の出どころ。`PR の報告` の PR が読めなければ、PR は無しとして `problems` (`what` が `pr-unreadable`) で知らせ、閉じる参照の PR には戻らない (読めるようになれば報告の PR を使うため) | 作業 (`PR の報告` → 合図 `review`) |
| 資源の使用 (`reserved`・`held`) | 予約 = コメント `割り当て` の時点で付いていたラベル `resource:<名前>` (接頭辞は大文字小文字を区別しない。GitHub のラベルの名前が区別しないため) のうち、属性 `reserve` が `on_assign` のもの。持っている資源 (定義の正本は [issue-format.md](issue-format.md) の「更新の種類」。差し戻された宣言は数えない)。空いていない資源がある宣言は、`開始可` まで何も持たない | 利用者 (ラベル)・作業 (宣言)・管理 (`開始可`) |
| 小さな PR | `待機` の理由の `小さな PR` と依頼先の Issue (と、報告の後は PR の URL) | 管理 (依頼・`待機`)・作業 (報告) |
| 割り当ての無い項目の `Blocked` | 最新の `依存の待ち` があり、その後に `依存の解消` が無い (管理のセッションが書いたもの)。無ければ利用者が手で付けたもの | 管理 (コメント → Status) |
| 担当者の変化 | Issue の担当者 (範囲は担当者がトークンのログイン 1 人の項目) と、記録の未回答の問い | 利用者。割り当て中なら、答えが出るまで作業中の項目のまま |
| 記録だけにあるもの | `record.json` (割り当ての意図・問いと答え・報告済みの印・確かめた本文の編集の時刻。[records.md](records.md)) | 管理。記録を失えば失う (「記録を失ったとき」) |

**判断の基準** (場面ごとの扱いを決めるときに使う):

- 時刻は、コメントの投稿の時刻と Issue の出来事 (`ClosedEvent`・`ReopenedEvent`・`LabeledEvent`・`UnlabeledEvent`・`ProjectV2ItemStatusChangedEvent` など) の時刻で比べる。出来事の書き手 (`actor`) は使えない (管理のセッションと利用者は同じアカウントで書く)。Status の出来事は、この Project のもの (`project_number`) だけを見る。
- ある時点の状態 (そのとき付いていたラベルなど) は、その時点までの出来事を時刻の順に全部読んで求める。最初や最新の出来事だけで決めない。
- 書き手がトークンのログインと違う先頭行のコメントは、この仕組みのコメントとして扱わない ([issue-format.md](issue-format.md) の「コメント」)。
- 宛先と番号を持つ種類のコメント (`開始可`・`待機`・`解放`・`依頼`) は、今の割り当ての宛先と番号のものだけを使う。前の割り当てのものは使わない。
- 同じ場面に 2 つの決まりが当たるときは、利用者の変更を上書きしないほうを選ぶ。

**決めたこと**:

- マージされずに閉じた PR は、draft でなければ ready for review と読む (読んだ時点の `state`・`merged`・`draft` で判定するため)。
- 今の割り当ての PR の候補が複数あるとき (閉じる参照の PR が今の割り当ての後に複数) は、作成が最新のものを使う。
- 開いている Issue の正常な終わりの判定は、close の時点で PR が draft だった後に ready になった場合を見分けられない (PR の timeline を読まないため)。見分けが要ると分かったら、`pr observe` に PR の出来事を足す。
- 管理のセッションが書いた `Blocked` は、判定の要る最新の宣言への `待機` のうち、理由に `Issue` か `小さな PR` を含み、最新の `開始可` より後の最初のものがあり、Status が `Blocked` で、`Blocked` への Status の変化の時刻がその `待機` 以後のもの。変化が `待機` より前なら利用者が付けたもの (`manager_blocked` は偽)。戻り先 (`return_status`) は `In Progress`。
- JSON のコードブロックが読めない宣言と、形が誤っている宣言 (検査は [issue-format.md](issue-format.md) の「宣言」の `declaration parse` と同じ。種類は付けない) も、判定の要る宣言にする (`declaration` は null で `error` に理由。管理のセッションが差し戻す)。

## 宣言の段階

判定の要る宣言は、着手の宣言と宣言の更新のうち、`開始可` の後の資源を外すだけの更新 (`resources-removed-only`) を除いたもの。差し戻された (宣言の書き直しの `依頼` がある) 宣言を書き直した更新は、資源を外しただけでも判定の要る宣言。差し戻された宣言は、持っている資源の計算に入れない。

| 段階 (`stage`) | 条件 |
| --- | --- |
| null | 今の割り当ての宣言が無い (何も求めず、作業のセッションの宣言を待つ) |
| `undecided` | 判定の要る最新の宣言に、判定の結果 (`開始可`・`待機`・宣言の書き直しの `依頼`) が無い |
| `go` | 最新の結果が `開始可` (作業中) |
| `waiting` | 最新の結果が `待機` (`wait` に理由と相手) |
| `returned` | 最新の結果が宣言の書き直しの `依頼` |

## 場面ごとの扱い

テストで決めた扱い (テストの名前に場面を書く。`issue-dispatch/tests/test_itemstate.py`)。

| 場面 | 読み方 |
| --- | --- |
| フィールドに ID があるが、コメント `割り当て` が無い | 割り当て中ではない (出どころはコメント) |
| 前の割り当ての `解放` があり、新しい `割り当て` がある | 新しい割り当てが今の割り当て。前の `解放` は数えない |
| 割り当て中の項目の Status が `Todo` にされた (Status の変化が `割り当て` より後) | 終わりでも reopen でもない。割り当て中のまま、解除するかを尋ねる (`status-changed`) |
| `割り当て` の後にフィールドか Status が書かれていない (更新がコメントより前で、その後の Status の変化が無い) | 途中で止まった書き込み。続き (`set-field`・`set-status` `In Progress`) を書く |
| フィールド `Agent session ID` の値が宛先と違い、更新が `割り当て` より後 | 利用者の変更。空なら `field-cleared`、別の値なら `field-changed` を尋ねる |
| 担当者が自分 1 人でなくなった | `assignee-changed` を尋ねる。答えが出るまで作業中の項目のまま |
| 進行中の Issue が閉じた | `close-in-progress` を尋ねる。答えが出るまで割り当て中で、ほかの書き込みはしない |
| `close-in-progress` の答えを待つ間に reopen された | 問いを取り下げ (`withdraw-question`)、フィールドは空にせず、Status を導いた状態 (`Blocked` か `In Progress`) に戻し、`reopened-while-pending` を報告する |
| `待機` (理由に `Issue` か `小さな PR`) の後に blockedBy か `Blocked` が無い | その blocker の `BlockedByRemovedEvent` が `待機` より後に無ければ続き (`blocked-by-add`) を書き、あれば `blocked-by-removed` を報告して足し直さない。Status の変化が `待機` より後に無ければ続き (`set-status` `Blocked`) を書き、あれば `status-changed` を報告する |
| `In Progress`・`In review` の項目に人が足した blockedBy | 導出せず `blocked-by-added` を報告する |
| 確認の対象のリポジトリ (設定 `third_party_edit_check`) で、`割り当て` より後 (記録の確かめた時刻より後) に第三者が本文を編集した | `third-party-edit` を尋ねる |
| `PR の報告` の PR が Issue を閉じる参照を持たず、向け先が既定のブランチ | `依頼` (本文の追記) を書く (同じ PR への未対応の `依頼` があれば書かない) |
| `PR の報告` の PR の向け先が既定のブランチでない | 本文の追記を頼まず `pr-base-not-default` を 1 回報告する (閉じる参照に現れないので `In review` にならず、マージでも Issue は閉じない。正常な終わりの判定には使う) |
| 今の割り当ての PR がマージ済みで Issue が開いている | `merged-issue-open` を尋ねる |
| 今の割り当ての PR がマージされずに閉じ、Issue が開いている | `pr-closed-unmerged` を尋ねる |
| 正常な終わりの後に PR が開いたまま残っている | 判定の相手にせず `pr-left-open` を 1 回報告する |
| 記録の意図にある項目が Project の一覧に無い | 除去。`removed` を尋ねる |
| 初めて扱う項目 (記録にその項目の情報が無い) で、最後に書いた管理のセッションの ID が自分と違う | `引き継ぎ` を書く (自分の `引き継ぎ` が既にあれば書かない) |
| 割り当ての無い項目 (担当者が自分 1 人、Status が `Ready` か `Blocked`) に開いている blocker がある | `依存の待ち` → `Blocked`。`依存の待ち` の後に止まっていれば続きの `Blocked` を書き、利用者が `Ready` に戻していれば (Status の変化がコメントより後) 報告して書き換えない |
| 管理のセッションが `Blocked` にした割り当ての無い項目の blocker がすべて閉じた | `依存の解消` → `Ready` |
| `依存の待ち` の無い `Blocked` (利用者が手で付けた) | blocker が閉じても書き換えない |
| Issue が閉じていて、今の割り当ての PR がマージ済み・ready for review (開いている)・マージされずに閉じた (draft でない) | 正常な終わり (`end.kind` が `normal`) |
| Issue が閉じていて、今の割り当ての PR が無い・draft | 進行中の close。割り当て中のまま (利用者の答えを待つ) |
| reopen の後の割り当てで、前の割り当てのマージ済みの PR だけがある | 今の割り当ての PR は無い。進行中 |
| 正常な終わりか `解放` の後に `ReopenedEvent` | `reopened`。フィールドが自分の書いた値 (今の割り当ての宛先) なら空にして (`clear-field`) 報告する。人が書いた値は消さない。Status は変えない |
| 進行中の close の後の `ReopenedEvent` | 終わった後の reopen ではない (答えを待つ間の reopen) |
| `PR の報告` の PR の作者がトークンのログインと違う | 無いものとし、閉じる参照の PR を使う |
| `PR の報告` の PR が Issue を閉じる参照を持たない | `pr.closing` が偽 (`In review` にせず本文の追記を頼む材料) |
| `待機` の理由が `利用者の答え`・`資源`・`設定` だけ | Status を変えない理由なので、Status が `Blocked` でも管理のセッションのものではない |
| `待機` (理由に `Issue` か `小さな PR`) の後に `開始可` | 作業中 (`go`)。`own_blockers` は空 |
| `開始可` の後の、資源を外すだけの更新 | 判定の要る宣言は `開始可` の宣言のまま。持っている資源は減る |
| `開始可` の後の、ファイルを変えた更新 | 判定の要る宣言はその更新 (`undecided`)。持っている資源は `開始可` の宣言のもののまま |
| 割り当ての後に利用者が足したラベルの資源 | 予約していない (`reserved` に入らない。宣言のときに空きを確かめる) |

## `item state` が返す値

| キー | 内容 |
| --- | --- |
| `key` | 項目 (`owner/repo#番号`) |
| `assignment` | 今の割り当て (`to` 宛先・`number` 番号・`comment_id`・`at`)。無ければ null (以下のキーは初期値) |
| `release` | 今の番号の `解放` (`comment_id`・`at`・`reason`)。無ければ null |
| `pr` | 今の割り当ての PR (`url`・`source` (`report` / `reference`)・`state`・`draft`・`merged`・`closing` (Issue を閉じる参照に割り当ての Issue を含むか)・`base_ref`・`created_at`)。無ければ null |
| `in_progress` | 進行中か |
| `end` | 割り当ての終わり (`kind` が `released` / `normal`・`at`・`released` なら `reason`)。無ければ null |
| `assigned` | 割り当て中か |
| `reopened` | 終わった後の reopen (`at`)。無ければ null |
| `declaration` | `judged` (判定の要る最新の宣言: `comment_id`・`at`・`kind`・`declaration` (JSON。読めなければ null)・`error`・`update_kind`)・`stage`・`go`・`wait` (`comment_id`・`at`・`reasons`)・`returned`・`manager_blocked`・`blocked_wait` (その `待機` の ID)・`return_status`・`own_blockers` (Issue の参照の配列)・`go_declaration`・`held` (名前の順) |
| `reserved` | 割り当てのときに予約した資源 (名前の順) |
| `problems` | 導出を続けられるが知らせるもの (`what` が `pr-unreadable`: `PR の報告` の PR が読めない) |

出力の `usage` は、割り当て中の項目の `reserved` と `held` から導いた資源の使用 (資源の名前 → 持つ項目の配列。[resources.md](resources.md) の判断が読む)。

## 作業のセッションの確認

同じ導出の、自分の項目についての読み出し (計画の R26・R27)。書き込みの `gh` は実行しない。

| サブコマンド | 返すもの |
| --- | --- |
| `work check` | `field_is_mine` (フィールド `Agent session ID` が自分の ID か)・`assignment`・`assigned_to_me` (今の割り当ての宛先が自分か)・`released` (今の番号の `解放`)・`pending_requests` (自分宛てで今の割り当ての番号の `依頼` のうち、まだ行っていないもの: `comment_id`・`at`・`kind`・`values`)・`third_party_edits` (`割り当て` より後の、トークンのログイン以外による本文の編集。確認の対象かは呼び出し元が決める) |
| `work held` | 自分宛ての今の割り当てで割り当て中の Issue (閉じて利用者の答えを待つ Issue を含む。割り当てが終わった Issue は返さない) を Project の順に: `key`・`state`・`status`・`assignment` (番号)・`judged`・`update_kind`・`stage`・`has_go`・`has_wait`・`manager_blocked`・`pending_requests` |

`依頼` を行ったかの判断: `宣言の書き直し` は、その後に `宣言の更新` があれば行った。`本文の追記` は、依頼の PR が Issue を閉じる参照にその Issue を含めば行った。`小さな PR` は、対応する `小さな PR の報告` ([issue-format.md](issue-format.md) の「報告と依頼の対応づけ」) があれば行った。

## ターンで行うこと

`item state` は、項目の状態に加えて、ターンで行うことを種類ごとに分けて返す。どれも書き込みの候補で、`item state` 自身は書かない。

| キー | 内容 |
| --- | --- |
| `actions` | 書き込みの候補 (下の表の種類)。`continuation` が真なら途中で止まった書き込みの続き |
| `questions` | 尋ねること (`kind`・`item`・`options`。種類と選択肢の正本は [records.md](records.md) の問いの表)。記録に同じ項目と種類の未回答の問いがあれば尋ね直さない。記録を失ったために尋ね直すものは `record_lost` が真 |
| `reports` | 1 回だけ報告するもの (`kind`・`item` と内容)。記録の報告済みの印 (`reported`) があるものは返さない |
| `pending` | 答えを待つ項目 (`question_id`・`item`・`kind`・`asked_at`)。この項目には手を付けない (答えを待つ間の reopen による問いの取り下げを除く) |
| `record_lost` | 記録を失ったか (記録が無い・前の記録が `ended`) |

| `actions` の種類 (`kind`) | 値 | 実行するサブコマンド |
| --- | --- | --- |
| `comment` | `comment_kind`・`values`・`body` | `comment post` |
| `set-status` | `item_id`・`status` | `project set-status` |
| `blocked-by-add` | `blocker` | `blocked-by add` |
| `set-field` | `item_id`・`field`・`value` | 割り当てのフィールドの書き込み (U16) |
| `clear-field` | `item_id`・`fields` | 同上 (空にする) |
| `withdraw-question` | `question_id` | `record apply` の `withdraw` |

| `reports` の種類 (`kind`) | 何を知らせるか |
| --- | --- |
| `status-changed` | 人が Status を変えた (`before`・`after`、または `status` と `after_comment`) |
| `field-changed` | 人が `Agent session ID`・`Agent session title` を変えた (割り当ての無い項目) |
| `blocked-by-added` / `blocked-by-removed` | 人が blockedBy を足した / 自分が足した blockedBy を外した (足し直さない) |
| `reopened` | 終わった後の reopen (`fields_cleared` 空にしたか) |
| `reopened-while-pending` | 答えを待つ間の reopen (問いを取り下げた) |
| `pr-base-not-default` | `PR の報告` の PR の向け先が既定のブランチでない |
| `pr-left-open` | 正常な終わりの後に PR が開いたまま残っている |

**人の変更の見分け** (計画の R22・KTD7): `--diffs` で渡した差分 (`observe diff` の出力) のうち、記録の意図 (自分の部分書き込み) と組み込みワークフローの遷移 (閉じた → `Done`、reopen → `Todo` (ワークフロー「Item reopened」が有効なとき)、追加 → `Todo`) と利用者が着手を決める遷移 (`Todo` か空 → `Ready`、reopen した項目の `Done` → `Ready`) で説明できないものを報告する。割り当て中の項目の Status とフィールドの変化は、場面の表のとおり問いにする。差分は報告のきっかけとしてだけ使い、続きを書くかの見分けには使わない (見分けは出来事の時刻で行う)。

**記録を失ったとき** (記録が無い・前の記録が `ended`): 記録にだけある情報 (割り当ての意図・問いと答え・報告済みの印・確かめた本文の編集の時刻) を失い、同じ導出で続ける。`利用者の答え` を待つ宣言は `user-answer-lost` で尋ね直し、閉じて答えを待つ項目は `close-in-progress` を尋ね直し、報告済みの印が無いので人の変更などを 1 回ずつ報告し直すことがある。確認の対象の項目は、割り当ての前に利用者に確かめ直す (U16)。どれも `record_lost` を真にして返す。

**処理の順**: 項目ごとに、割り当てのある項目の場面 (`引き継ぎ` → 答えを待つ間の reopen → 終わった後の reopen と残った PR → 進行中の close → 担当者 → フィールド → Status → `待機` の続き → 第三者の本文の編集 → PR) → 割り当ての無い項目の `Blocked` の再導出、の順に導き、最後に差分からの人の変更と、Project から除かれた項目を足す。差分の種類の順 (計画の R12) は [observation.md](observation.md)。待っていた宣言の判定し直しの順 (宣言の投稿の順。同じなら Project の中の順) は U15。

## CLI

| サブコマンド | 書き込み | 返すもの |
| --- | --- | --- |
| `item state --dir <管理ディレクトリ> [--project <owner>/<番号>] [--issue <owner/repo#番号>] [--diffs <ファイル \| ->]` | 無し | `items` (割り当てのある項目の状態。上の表)・`usage`・`actions`・`questions`・`reports`・`pending`・`record_lost` (「ターンで行うこと」)・`problems`・`rate_limit`・`warnings`・`errors`。設定の `project`・`resources` (属性)・`third_party_edit_check` と、記録 (無ければ記録を失った扱い。壊れていれば `errors` (key `record`)) と、Project のメタ情報 (ワークフローの有効・無効) を読む。`--diffs` は `observe diff` の出力 (JSON)。項目の一覧そのものが欠ければ (`problems` の `what` が `items-page`・`graphql-errors`) 導かずに `errors` (key `partial`) |
| `blocked-by remove --dir <管理ディレクトリ> --issue <owner/repo#番号> --blocker <owner/repo#番号> [--snapshot-dir <管理ディレクトリ>]` | `blockedBy` | 項目の状態の `own_blockers` にある blocker だけを外す (決まりの正本は [issue-format.md](issue-format.md) の「`blockedBy` の削除」)。それ以外は `rejected` (`own_blockers` を返す)。承認を得た後に呼ぶ。外したら `--snapshot-dir` のスナップショットに反映する ([observation.md](observation.md)) |
| `work check --project <owner>/<番号> --issue <owner/repo#番号> [--session <ID>]` | 無し | `session`・上の表の値・`problems`・`rate_limit`・`errors`。`--session` を省けば環境変数 (`CLAUDE_CODE_HOST_SESSION_ID`、無ければ `CLAUDE_CODE_SESSION_ID`)。項目が無ければ `errors` (key `issue`) |
| `work held --project <owner>/<番号> [--session <ID>]` | 無し | `session`・`items` (上の表)・`problems`・`rate_limit`・`errors` |

`PR の報告` の PR が読めなければ、`problems` (`what` が `report-pr`) で知らせ、その項目の `pr` は無しになる (上の表の行「今の割り当ての PR」)。

`blocked-by remove` の `gh` の呼び方も [issue-format.md](issue-format.md) の「`blockedBy` の削除」。
