# 差し替えた部分の流れと、追加の停止

**このファイルが、`review-rally` が `review-triage-loop` のループから差し替えた部分のノードと遷移 (図) と、追加の停止ノード RR1〜RR4 の条件と報告 (決定表)、どの停止でも行うこと (複製・`rally.yaml` の書き換え・片付けの案内) の SSOT。** 差し替えないノードとその遷移は [loop-flow.md](../../review-triage-loop/references/loop-flow.md) の図が SSOT で、ここでは言い直さない。規律は `loop-flow.md` の冒頭と同じで、図が遷移の SSOT、決定表が条件と報告の SSOT、散文はノード ID で参照する。

- 図の ID 集合 (RRG0・RRL1・RR1・RR2・RR3・RR4) と決定表の ID 集合は 1:1。RRG0 と RRL1 の決定表は [round.md](round.md)、RR1〜RR4 の決定表はこのファイルにある。**同梱の `triagecheck` はこのファイルを検査しない。** 人手で照合する。
- 図の `IN` はループに入る起点 (スキルの起動・人間のメッセージ以外で始まったターン) を示す記号で、ノード ID ではない (決定表の行を持たない)。
- 図の G2・L2・J2 は `loop-flow.md` のノードで、そこから先は `loop-flow.md` の図に従う (J5 を経て L1 に戻ったら、L1 の代わりに RRL1 に入る)。

## 図

```mermaid
flowchart TD
  IN(["/review-rally・人間のメッセージ以外で始まったターン"])
  RRG0["RRG0: 条件とループの状態を読む (新しいループならループのディレクトリと rally.yaml を作り、レビューのセッションを起動する)"]
  RRL1["RRL1: 1 worktree を合わせる → 2 依頼文を書く → 3 会話を消す → 4 依頼する → 5 待機 / 6 突き合わせる"]
  G2{"G2 (loop-flow.md)"}
  L2["L2: review-triage を呼ぶ (loop-flow.md)"]
  J2{"J2 (loop-flow.md)"}
  RR1["RR1: 停止 (レビュー不成立)"]
  RR2["RR2: 停止 (レビューのセッションを使えない)"]
  RR3["RR3: 停止 (拒否された)"]
  RR4["RR4: 停止 (依頼文を作れない)"]

  IN --> RRG0
  RRG0 -- "新しいループ: 起動と確認が通る" --> G2
  RRG0 -- "新しいループ: start_session が失敗した・値が指定と違う" --> RR2
  RRG0 -- "再入: 結果待ちの依頼の完了のメッセージ → 6 から" --> RRL1
  RRG0 -- "再入: 識別子の衝突の待機の通知 → 1 から" --> RRL1
  RRG0 -- "再入: 前の回の通知・結果待ちが無い → 何もせずに終える" --> IN
  G2 -. "loop-flow.md の図のとおり進み、L1 に来たら 1 から" .-> RRL1
  RRL1 -- "2 の識別子の衝突か 5 で待機を起動し、ターンを終える → 次のターンで" --> IN
  RRL1 -- "1 worktree が clean でない・合わせられない" --> RR2
  RRL1 -- "1・2 依頼のディレクトリが無視されていない・作業ツリーが clean でない・記録が読めない・基点が祖先でない・依頼文を書けない" --> RR4
  RRL1 -- "3 会話の消去を拒否された / 4 メッセージが届かない / 依頼が処理されない" --> RR3
  RRL1 -- "失敗の通知・完了の通知の様式が違う・完了を通知せずに終了した・応答なし / 6 突き合わせが通らない" --> RR1
  RRL1 -- "6 が通る" --> L2
  L2 -- "様式の差し戻し・記録の末尾の回の run_id が識別子でない" --> RR1
  L2 --> J2

  style RR1 fill:#dc26262e,stroke:#b91c1c
  style RR2 fill:#dc26262e,stroke:#b91c1c
  style RR3 fill:#dc26262e,stroke:#b91c1c
  style RR4 fill:#dc26262e,stroke:#b91c1c
```

**再入 (人間のメッセージ以外で始まったターン) の中身 (どのターンをどの依頼の通知とみなすか・何もせずに終えるのはどんなときか) の SSOT は [round.md](round.md) の「再入の手順」。** 開始の前提が満たされないときは、ループを始めずに報告する ([session.md](session.md) の「開始の前提」)。停止ではないので、図に含めない。

## 決定表 (RR1〜RR4)

| ID | 種類 | 条件 | 報告に書くもの |
| --- | --- | --- | --- |
| RR1 | 停止 | レビュー不成立。レビューのセッションが失敗を通知した・完了の通知の 1 行目が様式どおりでない・完了を通知せずにターンを終了し、結果のファイルも無い・応答なし (`isRunning` が真のまま、`lastActivityAt` が 60 分より前)・突き合わせ ([round.md](round.md) の手順 6) が通らない・`review-triage` が結果の様式を差し戻した・`review-triage` の後に記録の末尾の回の `run_id` が識別子でない。どれに当たるかの決め方の SSOT は [round.md](round.md) の「再入の手順」 | その回の識別子と、不成立の理由 (失敗の通知の理由・通知の 1 行目・一致しなかった項目と両方の値)。結果のファイルの有無と、複製したパス (下の「停止のときに行うこと」の 1)。応答なしなら、承認待ちなどでレビューのセッションのターンが進んでいないおそれがあること (人間がレビューのセッションを開いて確認する)。突き合わせの 4 (ブランチが動いた) なら、動いたブランチと、依頼の前と後の SHA (一覧が同じで、現在のブランチの reflog に `waiting.reflog_since` より後の項目があるなら、その項目)。戻すかどうかは人間が決めること |
| RR2 | 停止 | レビューのセッションを使えない。`start_session` が失敗した・`get_session` のモデル・effort・権限モードが指定やメインのセッションと違う・`worktreePath` が無いか `.claude/worktrees/` の下にない ([session.md](session.md) の「起動」の 2)・レビューの worktree が clean でないか、HEAD に合わせられない ([round.md](round.md) の手順 1) | 当たった項目と、指定の値と実際の値。モデルか effort が違うなら、アプリは起動元より上の値を無視するので、メインのセッションのモデルか effort を上げるか、指定を下げて新しいループを始めること。レビューの worktree が clean でなければ、`git -C <レビューの worktree> status --porcelain` の出力 |
| RR3 | 停止 | 拒否された。`clear_session` を拒否された ([round.md](round.md) の手順 3)・`SendMessage` の結果が `delivered` でも `queued` でもない (手順 4)・依頼が処理されない (待機の通知の時点で `isRunning` が偽で、`lastActivityAt` が依頼を送った時刻より前。[round.md](round.md) の「完了のメッセージが無いまま来たターン」) | 拒否したツールと、その結果の文面。`clear_session` なら、人間がレビューのセッションを画面に開いているかピン留めしていると拒否されるので、閉じるか外してから新しいループを始めること。`SendMessage` や依頼が処理されないなら、レビューのセッションの権限モードがメインのセッションと違うと、メッセージが承認待ちになることがあること |
| RR4 | 停止 | 依頼文を作れない。レビューの worktree の中から見て依頼のディレクトリが無視されていない ([round.md](round.md) の手順 1)・メインの作業ツリーが clean でない・記録が読めない・増分の基点 (記録の最後の回の `head`) が HEAD の祖先でない・`review-request` が識別子の衝突以外の理由で依頼文を書かなかった (手順 2) | 当たったものすべてと、何を片付ければよいか。汚れたファイルの一覧、記録のパスと読めない理由、基点の SHA と現在の HEAD、`review-request` が報告した理由。依頼のディレクトリが無視されていなければ、どのファイル (`.gitignore`) に何 (`tmp/`) を足し、どのブランチ (現在のブランチ) にコミットするか。基点が祖先でないときは、ループの間に履歴を書き換えた (reset・rebase・squash) ことが原因であり、どう続けるかは人間が決めること |

## 停止のときに行うこと

**どの停止ノード ([loop-flow.md](../../review-triage-loop/references/loop-flow.md) の S2〜S6 と、上の RR1〜RR4) でも、次の順に行ってから報告する。**

1. **依頼文と結果を複製する。** レビューの worktree の依頼のディレクトリ (`tmp/review-rally/<ループの id>/`) に依頼文か結果が 1 つでもあれば、そのディレクトリの全体 (前の回のものを含む) を、メインのセッションのループのディレクトリに複製する。依頼文も結果も無ければ (1 回目の依頼文を書く前の停止)、複製しない。片付けでレビューの worktree を消すと、停止の原因を結果のファイルで調べられなくなるためである。
2. **`rally.yaml` を `state: stopped`・`stop_reason: "<ID>: <1 行の理由>"` にする。**
3. **片付けはしない。案内だけを報告に書く** (下の「片付けの案内」)。レビューのセッションのアーカイブは既定で worktree も片付け、アプリが再利用した worktree には以前の作業のファイルが残っていることがある。どれも元に戻せないので、行うかどうかと、いつ行うかは人間が決める (2026-10-29 に利用者が決めた)。

## 片付けの案内

停止の報告に、`rally.yaml` の `session` から組み立てた次の手順を、人間が実行できる形で書く。

- **新しく作られた worktree なら** (`session.reused` が偽): レビューのセッション (`session.name`・`session.id`) をアーカイブする (サイドバーから。アーカイブで worktree も片付けられる)。アーカイブの後にブランチ (`session.branch`) が残っていれば、`git branch -D <session.branch>` で消す。
- **再利用された worktree なら** (`session.reused` が真): レビューのセッションを**アーカイブしない** (以前の作業のファイルが消えるおそれがある)。依頼のディレクトリを消し (`rm -r <レビューの worktree>/tmp/review-rally/<ループの id>`。1 で複製してある)、worktree を元の HEAD に戻し (`session.original_head` はブランチ名か SHA のどちらか。`git -C <レビューの worktree> show-ref --verify --quiet refs/heads/<session.original_head>` が成功すればブランチ名なので `git -C <レビューの worktree> checkout <session.original_head>`、失敗すれば SHA なので `git -C <レビューの worktree> checkout --detach <session.original_head>`)、ブランチを消す (`git branch -D <session.branch>`)。レビューのセッションは、待機したまま残す。
- **ループのディレクトリ (メインの作業ツリーの `tmp/review-rally/<ループの id>/`) と記録は消さない。** 後で経路どうしの収束を比べる材料になる。

## 停止の報告に足すもの

**停止の報告の全体は [reporting.md](../../review-triage-loop/references/reporting.md) の「必ず出すもの」の 6 項目で、S2〜S6 ごとに足すものは [loop-flow.md](../../review-triage-loop/references/loop-flow.md) の決定表の「報告に書くもの」。** 1 の「停止した理由」には RR1〜RR4 も入る。このループでは、どの停止 (S2〜S6・RR1〜RR4) でも次を足す。

| 項目 | 書くもの |
| --- | --- |
| ループ | ループの id と、ループのディレクトリの絶対パス |
| レビューのセッション | 名前・id・worktree のパス・実効モデルと effort (`rally.yaml` の `session`) |
| 複製 | 上の「停止のときに行うこと」の 1 で複製したか、複製先の絶対パス |
| 片付け | 上の「片付けの案内」 |
| 回数 | この起動で回した回数と上限 (reporting.md の 2) |
| 次にできる操作 | 新しいループを始めること (初版は `--resume` を持たない。記録は続くので、推移は失われない)。S2 なら、回答の渡し先 (`review-triage-fix` を単独で起動して回答する。SSOT は loop-flow.md の S2 の行) |
| S3 のとき | 収束後の全量レビューの要否 (規則の SSOT は [review-request.md](../../review-triage/references/review-request.md) の「収束後の全量レビューと、その要否」) と、行い方。このループは収束後の全量の回をループに含めないので、`review-request --full-review --base <loop.base>` で依頼文を作り、別のセッションで実行する手段を案内する。**`--base` を必ず付けるよう書く。** 付けないと起点が `origin/HEAD` になり (省いたときの既定。SSOT は [review-request の SKILL.md](../../review-request/SKILL.md) の手順 2)、範囲が広がる。行うかどうかは人間が決める |
