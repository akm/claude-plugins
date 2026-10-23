# 処理の流れ (項目の状態)

このファイルが、この仕組み (issue-dispatch) の、管理のセッションがターンのたびに導く**項目の状態**の正本 (計画の R24・KTD19)。状態ごとの出どころ (GitHub のどこから導くか) と判断の基準、場面ごとの扱い、`item state` と作業のセッションの確認 (`work check`・`work held`) が返す値をここに書く。宣言の判定の節は U15 で、割り当ての節は U16 で、状態遷移の図と決定表は U21 で足す。モジュール `issue-dispatch/scripts/issue_dispatch/itemstate.py` が導出を実装し、`gh` は実行しない (項目は `project items`、`PR の報告` の PR の状態は `pr observe` と同じ関数で、呼び出し元が読んで渡す)。

割り当ての無い項目の `Blocked` の導出・人の変更の見分け・途中で止まった書き込みの続き・利用者に尋ねる場面・記録を失ったときの扱いは、この文書の次の版 (U13 の後半) で足す。

## 項目の状態の出どころ

状態ごとに出どころを 1 つに決める。導出・作業のセッションの確認・待機の終わる条件 (U14) は、どれもこの表の出どころを読む。Status (利用者と組み込みワークフローも変える) と担当者では決めない。

| 状態 | 出どころ | 書き手と書く順 |
| --- | --- | --- |
| 割り当て中か (`assigned`) | 今の割り当てのコメント `割り当て` (宛先と番号) があり、その番号の `解放` が無く、正常な終わり (下の行) もしていない。進行中の Issue が閉じて、利用者の問いに答えが出ていない間は割り当て中。担当者と Status では決めない | 管理 (`Agent session ID` は排他の印で、コメントより先) |
| 割り当ての終わり (`end`) と reopen (`reopened`) | 終わり = 今の番号の `解放` (`kind` が `released`) か、正常な終わり (`kind` が `normal`): Issue が閉じていて、進行中 (`in_progress`) でない。進行中 = 今の割り当ての PR が無いか、読んだ時点で ready for review にもマージ済みにもなっていない。閉じたもの (`ClosedEvent` の `closer`) は問わない。Issue が開いている (reopen された) ときは、今の割り当ての最新の `ClosedEvent` の時点で PR が ready for review かマージ済みだった (PR がマージ済み、または close より前に作られた PR が読んだ時点で draft でない) ことで正常な終わりと読む。reopen = 終わった後の `ReopenedEvent`。Status だけの `Todo`・`Done` は、終わりでも reopen でもない | 管理 (`解放`。理由ごとに続けて書くものは [issue-format.md](issue-format.md) の `解放`)・利用者 (reopen) |
| 宣言の段階 (`declaration`) | 今の割り当ての判定の要る最新の宣言 (`judged`) と、その宣言への `開始可`・`待機`・宣言の書き直しの `依頼` のうち最新のもの | 作業 (宣言)・管理 (結果のコメント → Status → 合図) |
| 待っているもの・自分が足した `blockedBy` (`own_blockers`)・管理のセッションが書いた `Blocked` (`manager_blocked`) | 判定の要る最新の宣言への、最新の `開始可` より後の `待機` の理由と相手。管理のセッションが書いた `Blocked` かは、理由に `Issue` か `小さな PR` を含む最初の `待機` と、`Blocked` への Status の変化の時刻で見分ける (下の基準) | 管理 (`待機` → 理由が `Issue` か `小さな PR` のときだけ `blockedBy` → `Blocked` → 合図。資源・設定・利用者の答えの理由では Status を変えない) |
| 今の割り当ての PR (`pr`) | 今の割り当て (`割り当て` より後) の最新の `PR の報告` の本文の URL の PR (作者がトークンのログインと違えば無いものとする)。無ければ、Issue を閉じる参照の PR (`closedByPullRequestsReferences`) のうち、作者がトークンのログインで、作成が `割り当て` より後のもの (複数なら作成が最新)。この行が「今の割り当ての PR」の唯一の出どころ。`PR の報告` の PR が読めなければ、PR は無しとして `problems` (`what` が `pr-unreadable`) で知らせ、閉じる参照の PR には戻らない (読めるようになれば報告の PR を使うため) | 作業 (`PR の報告` → 合図 `review`) |
| 資源の使用 (`reserved`・`held`) | 予約 = コメント `割り当て` の時点で付いていたラベル `resource:<名前>` のうち、属性 `reserve` が `on_assign` のもの。持っている資源 = 最後に `開始可` を書いた宣言の `resources` のうち、その後の差し戻されていないどの更新にも残っているもの ([issue-format.md](issue-format.md) の「更新の種類」)。空いていない資源がある宣言は、`開始可` まで何も持たない | 利用者 (ラベル)・作業 (宣言)・管理 (`開始可`) |
| 小さな PR | `待機` の理由の `小さな PR` と依頼先の Issue (と、報告の後は PR の URL) | 管理 (依頼・`待機`)・作業 (報告) |
| 割り当ての無い項目の `Blocked`・担当者の変化・記録だけにあるもの | 次の版で書く | |

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
- JSON のコードブロックが読めない宣言も、判定の要る宣言にする (`declaration` は null で `error` に理由。管理のセッションが差し戻す)。

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
| 割り当て中の項目の Status が `Todo` にされた | 終わりでも reopen でもない。割り当て中のまま (割り当てを解除するかの問いは次の版) |
| Issue が閉じていて、今の割り当ての PR がマージ済み・ready for review (開いている)・マージされずに閉じた (draft でない) | 正常な終わり (`end.kind` が `normal`) |
| Issue が閉じていて、今の割り当ての PR が無い・draft | 進行中の close。割り当て中のまま (利用者の答えを待つ) |
| reopen の後の割り当てで、前の割り当てのマージ済みの PR だけがある | 今の割り当ての PR は無い。進行中 |
| 正常な終わりか `解放` の後に `ReopenedEvent` | `reopened` (次の版でフィールドを空にして報告する) |
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

## CLI

| サブコマンド | 書き込み | 返すもの |
| --- | --- | --- |
| `item state --dir <管理ディレクトリ> [--project <owner>/<番号>] [--issue <owner/repo#番号>]` | 無し | `items` (割り当てのある項目の状態。上の表)・`usage`・`problems`・`rate_limit`・`warnings`・`errors`。設定の `project` と `resources` (属性) を読む。項目の一覧そのものが欠ければ (`problems` の `what` が `items-page`・`graphql-errors`) 導かずに `errors` (key `partial`) |
| `work check --project <owner>/<番号> --issue <owner/repo#番号> [--session <ID>]` | 無し | `session`・上の表の値・`problems`・`rate_limit`・`errors`。`--session` を省けば環境変数 (`CLAUDE_CODE_HOST_SESSION_ID`、無ければ `CLAUDE_CODE_SESSION_ID`)。項目が無ければ `errors` (key `issue`) |
| `work held --project <owner>/<番号> [--session <ID>]` | 無し | `session`・`items` (上の表)・`problems`・`rate_limit`・`errors` |

`PR の報告` の PR が読めなければ、`problems` (`what` が `report-pr`) で知らせ、その項目の `pr` は無しになる (上の表の行「今の割り当ての PR」)。
