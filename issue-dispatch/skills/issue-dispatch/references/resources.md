# 資源の扱い

このファイルが、この仕組み (issue-dispatch) の資源の扱いの正本。資源は、同時に使える数が限られるもの (検証用の DB・GPU など) で、Issue のラベル `resource:<名前>` (正本は [issue-format.md](issue-format.md) の「Issue が持つもの」) と宣言の `resources` (同じ文書の「宣言」) で表す。資源の種類で変わりうる判断はすべて属性にし、属性は管理ディレクトリの設定の `resources` に資源の名前ごとに書く (設定のキーの正本は [project-config.md](project-config.md))。設定に無い資源と、書かれていない属性はデフォルト値で扱い、デフォルト値は資源の種類を区別しないときの扱い。新しい種類のために判断を変えるときは、属性の表に行を足し、契機の表の「読む属性」を直す (計画の KTD8)。モジュール `issue-dispatch/scripts/issue_dispatch/resources.py` が、属性の適用と契機ごとの判断を実装する (`gh` は使わない)。

**資源の名前は大文字小文字を区別しない** (ラベルの名前を GitHub が区別しないため)。設定の `resources` のキー・ラベル・宣言の `resources`・使用の表の名前を同じ規則で比べ、返す名前は渡された表記のまま。設定で表記だけ違う 2 つ目以降の資源は警告して使わない。

## 属性

| 属性 | 決めること | 値 | デフォルト値 |
| --- | --- | --- | --- |
| `capacity` | 同時に資源を持てる (予約か宣言で使っている) 項目の数 | 1 以上の整数 | `1` |
| `reserve` | いつ予約するか | `on_assign` (割り当てのとき) / `on_declare` (着手の宣言のとき。割り当ては資源の空きを待機しない) | `on_assign` |
| `when_busy` | 資源を持つ項目の数が `capacity` に達しているときにどうするか | `wait` (割り当てない・コメント `待機` を書く) / `ask` (使用中であることを示して利用者に質問する。進める選択肢も示す) | `wait` |
| `release_undeclared` | 予約したのに着手の宣言の `resources` に無い資源をどうするか | `release` (質問せずに解放する) / `ask` (利用者に質問する) | `ask` |

未知の属性と誤った値は警告してデフォルト値を使う (`resources attributes` の `warnings`)。

## 資源の使用と持っている資源

資源の使用 (資源 → 持っている項目) は記録に書かず、割り当て・ラベル・宣言・`開始可` から、ターンのたびに導く (取得元の正本は [flow.md](flow.md) の「項目の状態の取得元」の行「資源の使用」。関数 `itemstate.resource_usage` が導き、判定は宣言に無い予約として解放したものを除く (条件の正本は [flow.md](flow.md) の「判定」の「資源の使用」))。項目が持つ資源は、割り当てで予約した資源と、持っている資源 (定義の正本は [issue-format.md](issue-format.md) の「更新の種類」) の両方。関数 `held_from_history` は、今の割り当ての宣言の配列 (投稿の順。宣言ごとに `開始可` を書いたか・差し戻されたか) からその定義のとおり持っている資源を求める。差し戻された宣言は数えず、比べる相手にもしない。

資源の確保と解放は同じセッションが組で行う: 管理のセッションは割り当てのとき (ラベルの資源) と `開始可` を書くとき (宣言の資源) に予約し、Issue の close と割り当ての解除のときに解放する。作業のセッションは着手の宣言の `resources` で使うと宣言し、使い終えたら資源を外した `宣言の更新` で使い終えたと宣言する。

## 契機

判断は契機ごとに 1 つの関数で、属性 (設定から) と資源の使用 (U13 が求める) と利用者の回答 (記録にある。読むのは呼び出し元) を引数で受ける。利用者の回答の値: `when_busy` が `ask` の資源には `wait` (待機する) / `proceed` (進める)、`release_undeclared` が `ask` の資源には `release` (解放してよい) / `keep` (解放してはいけない)。

| 契機 (`--trigger`) | 行うこと | 読む属性 | 結果 |
| --- | --- | --- | --- |
| 割り当て `assign` (R19) | ラベルの資源のうち `reserve` が `on_assign` のものについて、資源を持つ項目の数 (自分を除く) が `capacity` に達していれば `when_busy` に従う。`wait` なら候補にしない。`ask` なら割り当てるかを利用者に質問し、利用者が待機すると回答したら `wait` と同じに候補にせず、回答を記録に書いて、その資源が解放されるまで同じ質問を出し直さない。進めると回答したら割り当てる。`reserve` が `on_declare` の資源は予約せず、空きも待機しない | `reserve`・`capacity`・`when_busy` | `assign` (割り当てて `reserve` の資源を予約する) / `skip` (候補から外す。`busy` に資源) / `ask` (`ask` に資源) |
| 着手の宣言 `declare` (R20) | 宣言の `resources` のうち予約していない資源は空きを確認し、すべて空いていれば `開始可` を書くときに予約する。空いていないものがあれば、どれも予約せずに `when_busy` に従う (`wait` ならコメント `待機` を書き、合図 `wait` を送る。Status は変えない。`ask` なら利用者に質問し、回答を待機する間は `待機` を書き、待機すると回答したら `wait` と同じ)。待機している宣言は新しく要る資源を持たない。予約したのに宣言に無い資源は `release_undeclared` に従う: `release` なら解放する。`ask` なら質問し、回答を待機する間もほかの判定が済んでいれば `開始可` を書き、その資源は回答が出るまで予約のまま残す。解放してよいと回答したら解放し、解放してはいけないと回答したら予約を残してコメント `依頼` (宣言の修正) と合図 `request` でその資源を足した更新を頼む。宣言の資源が Issue のラベルに無ければ、ラベルを足すことを提案し、承認の後に `issue add-label` で足す (ラベルの提案は呼び出し元) | `capacity`・`when_busy`・`release_undeclared` | `go` (`reserve` の資源を予約する) / `wait` (`wait_for` の資源を待機する) / `ask` (`ask` の資源を質問する)。宣言に無い予約は結果に依らず `release`・`keep`・`ask_undeclared`・`request_rewrite` に分ける |
| 宣言の更新 `update` (R20。ready for review の前も後も) | 持っている資源から外した資源を解放する。足した資源 (前に外して足し直したものも含む) は、着手の宣言と同じに空きを確認する。資源を外すだけの更新 (種類 `resources-removed-only`。種類の判定は [issue-format.md](issue-format.md) の「更新の種類」で、呼び出し元が渡す) は判定せず `開始可` を書かない | `capacity`・`when_busy` | `skip` (資源を外すだけの更新。`release` だけ) / `go` / `wait` / `ask` と `reserve`・`wait_for`・`ask`・`release` |
| Issue の close・割り当ての解除 `close` (R21。進行中の Issue の close では、利用者が中断すると回答した後) | その項目が持つ資源をすべて解放する | — | `release` に資源 |
| 資源の解放 `release` (宣言の更新で外したとき・着手の宣言で `release_undeclared` に従って解放したとき・Issue の close・割り当ての解除) | その資源で `待機` になっていた宣言を、宣言の投稿の順 (同じなら Project の中の順) に判定し直す (ファイルの競合の可能性は、[flow.md](flow.md) の「判定」の「`開始可` を書く直前の比較」のとおりに扱う)。`開始可` になった宣言にはコメント `開始可` を書き、合図 `go` を送る (Status が `Blocked` の項目は戻す) | — | `rejudge` に待機していた宣言 (判定し直す順) |

`開始可` を書くのは、ファイルの競合の可能性でも資源でも待機しないときだけ。属性を 1 つ変えたとき、結果が変わるのは、その属性を読む契機だけ。

## CLI

| サブコマンド | 書き込み | 返すもの |
| --- | --- | --- |
| `resources attributes --dir <管理ディレクトリ> [--name <資源>]` | 無し | `resources` (設定の資源ごとの属性。`--name` なら その資源 1 つで、設定に無ければデフォルト値)・`defaults`・`warnings` (未知の属性・誤った値・表記だけ違う名前) |
| `resources judge --dir <管理ディレクトリ> --trigger <契機> (--body <JSON> \| --body-file <ファイル \| ->)` | 無し | 契機の表の「結果」に書いたキー。本文のキーは契機ごと: `assign` は `item`・`resources` (ラベルの資源)・`usage`・`answers`。`declare` は `item`・`declared`・`reserved`・`usage`・`answers`・`undeclared_answers`。`update` は `item`・`kind` (更新の種類)・`held`・`declared`・`usage`・`answers`。`close` は `item`・`usage`。`release` は `resource`・`waiting` (要素は `item`・`declaration`・`posted_at` (文字列)・`position` (整数)・`wait_for`)。`usage` は資源の名前 → 持っている項目 (`owner/repo#番号`) の配列。資源の名前の配列は空でない文字列の配列、`answers` と `undeclared_answers` は資源の名前 → 回答 (文字列)。入れ子の中身まで検査し、形が違えば `errors` で返す |
