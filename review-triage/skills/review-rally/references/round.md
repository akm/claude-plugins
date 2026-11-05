# ループの開始と 1 回のレビュー (RRG0・RRL1)

**このファイルが、ノード RRG0・RRL1 の手順と、待機と再入の手順の SSOT。**

## 決定表

| ID | 種類 | 条件・内容 | 報告に書くもの |
| --- | --- | --- | --- |
| RRG0 | 手順 | 新しいループなら、次の順に行う。(1) 条件を決める ([arguments.md](arguments.md))。(2) 開始の前提を確認する ([session.md](session.md) の「開始の前提」)。(3) ループのディレクトリと `rally.yaml` を作る ([session.md](session.md) の「ループのディレクトリを作る」)。(4) レビューのセッションを起動し、実際の値を確認する ([session.md](session.md) の「起動」)。再入なら、下の「再入の手順」 | 新しいループのときだけ、決まった条件をループの開始前に出す。書くのは、レビューのセッションのモデルの指定と実効モデル・effort (指定と `get_session` の値)・権限モード、レビュースキルとそのオプション、上限、構造の関門 k、全量の起点のブランチ (`loop.base` と、`--base` による指定か `origin/HEAD` による既定か)、`review-triage-fix` に渡す回数の閾値 N とフェーズごとの実行方法 (書き方は [loop-flow.md](../../review-triage-loop/references/loop-flow.md) の G0 の行と同じ)、`--full-first` と `--full-review` の有無、ループの id とループのディレクトリの絶対パス、レビューのセッション (名前・id・worktree のパス。再利用された worktree なら、そのことと元の HEAD) |
| RRL1 | 手順 | 下の「1 回のレビュー」の手順 | いま何回目か (この起動で数えた回数) と上限、記録の回番号、範囲 (全量か増分か)、識別子 |

## ファイルのディレクトリ

| ディレクトリ | 置くもの | 書き込み元 |
| --- | --- | --- |
| 呼び出し元のセッションの作業ツリーの `tmp/review-rally/<ループの id>/` (ループのディレクトリ) | `rally.yaml` ([session.md](session.md))・依頼文 (`review-request` が書く)・停止のときの結果の複製 ([stops.md](stops.md)) | 呼び出し元のセッション |
| レビューの worktree の `tmp/review-rally/<ループの id>/` (結果のディレクトリ) | 結果 | レビューのセッション |

各セッションは自分の作業ツリーにだけ書き、もう一方のセッションには絶対パスで渡す。Claude のデスクトップアプリの hook が、worktree で動くセッションから別の作業ツリーへの Write ツールの書き込みを拒否するためである。

`review-request` の `--dir` には `tmp/review-rally/<ループの id>` を渡す。`--target-dir` にレビューの worktree を渡すので、結果の出力先は結果のディレクトリになる ([review-request](../../review-request/SKILL.md) の手順 3)。

## 1 回のレビュー (RRL1)

### 手順

1. **依頼文を書く。** 次をすべて確認してから、Skill ツールで [review-request](../../review-request/SKILL.md) を呼び出す。当たれば RR4 で、当たったものをすべて一度に報告する。
   - 呼び出し元のセッションの作業ツリーが clean である (`git status --porcelain` が空)。
   - 記録が読める。
   - 増分の回 (記録に回があり、`next_full` が偽) なら、最後の回の `head` が HEAD の祖先である (`git merge-base --is-ancestor <head> HEAD`)。

   呼び出しは `review-request <loop.review_skill> <loop.model> <loop.review_args> --dir tmp/review-rally/<ループの id> --target-dir <レビューの worktree の絶対パス>` (値は `rally.yaml`。`ce-code-review` には `<loop.review_args>` を渡さない)。記録に回が無いか、`rally.yaml` の `next_full` が真なら全量の回で、`--base <loop.base>` も渡す。記録に回がある状態の全量の回では、`--full-review` も渡す。
   - `review-request` が「同じ識別子の依頼文か結果が既にある」で書かなかったら、Bash ツールで `sleep 60` をバックグラウンドで起動し (`run_in_background: true`)、`description` を「review-rally <ループの id>: 識別子の衝突を避けるため分が変わるまで待機する。通知を受けたら review-rally の再入の手順へ」にして、ターンを終える。
   - それ以外の理由で書かなかったら RR4。
   - 書けたら、`next_full` を偽にする。
2. **会話を消す。** `rally.yaml` の `requests` が 1 以上なら、ツール `clear_session` でレビューのセッションの会話を消す。拒否されたら RR3。
3. **依頼する。** 送る直前に、リポジトリのブランチの一覧 (`git for-each-ref --format='%(refname:short) %(objectname:short)' refs/heads`) と、worktree の一覧 (`git worktree list --porcelain`) を取る。worktree の一覧の最初の項目が、メインの作業ツリー (`git worktree add` で追加したものではない、元の作業ツリー) である。最初の項目からメインの作業ツリーの HEAD (`branch` の行のブランチの名前。detached HEAD なら `HEAD` の行の SHA) を、残りの項目からチェックアウトされているブランチの名前を取る。ツール `SendMessage` で、宛先 `to` をレビューのセッションの id (`rally.yaml` の `session.id`) にして、下の「依頼のメッセージ」を送る。結果が `delivered` か `queued` でなければ RR3。送ったら、`rally.yaml` の `waiting` に、識別子・送った時刻 (`date -u +%Y-%m-%dT%H:%M:%SZ`)・ブランチの一覧 (`refs`)・メインの作業ツリーの HEAD (`main_head`)・チェックアウトされているブランチの名前 (`worktree_branches`) を書き、`requests` を 1 つ増やす。記録に回がある状態の全量の回でなければ、`rounds` も 1 つ増やす (J5 が見る回数。数えるのはここだけ。数えない回の SSOT は [review-request.md](../../review-triage/references/review-request.md) の「収束後の全量レビューと、その要否」の「上限」の段落)。
4. **待機を起動して、ターンを終える** (下の「待機」)。
5. **突き合わせる。** 上から順に確認し、最初に通らなかったところで RR1。
   1. 結果のファイル (結果のディレクトリの `review-<識別子>.yaml`) を照合する。照合することの SSOT は [review-invocation.md](../../review-triage-loop/references/review-invocation.md) の「別のプロセスでレビューした結果の取り込み」の「結果のファイルの照合」。
   2. レビューの worktree の HEAD が依頼文の `head` と同じコミットで、`git -C <レビューの worktree> status --porcelain` が空である。
   3. 呼び出し元のセッションの作業ツリーの HEAD が依頼文の `head` と同じコミットで、現在のブランチ (`git symbolic-ref -q --short HEAD` の出力。detached HEAD なら何も出ない) が `rally.yaml` の `branch` と同じで、`git status --porcelain` が空である。ブランチも比べるのは、同じコミットを指す別のブランチに替わったことを検出するため。
   4. ブランチの一覧 (取り方は手順 3) が `rally.yaml` の `waiting.refs` と同じである。比べる前に、`waiting.worktree_branches` と、今の worktree の一覧のメインの作業ツリー以外の項目のブランチを、両方の一覧から除く。メインの作業ツリー以外の worktree で動くセッションのコミットで停止しないようにするため。呼び出し元のセッションのブランチが除かれても、3 で確認している。
   5. メインの作業ツリーの HEAD (取り方は手順 3) が `rally.yaml` の `waiting.main_head` と同じである。呼び出し元のセッションが worktree で動くと、3 はメインの作業ツリーの HEAD を見ないため。

   3〜5 を確認するのは、レビュアのテストがリポジトリのブランチと HEAD を書き換えた実例があるため。メインの作業ツリーのブランチは比べるので、メインの作業ツリーで動く別のセッションがレビューの最中にコミットするか、ブランチを切り替えても停止する。レビュアのテストによる変更と区別できないためである。

   すべて通れば L2 に進む。

### 依頼のメッセージ

**会話を消した後に送るので、レビューの規則をすべて書く。** `<回>` は記録の `runs` の数 + 1。`<レビューのセッションのブランチ>` は `rally.yaml` の `session.branch`。`<SHA>` は呼び出し元のセッションの `git rev-parse HEAD` の結果。

レビューの worktree の HEAD は、レビューのセッションが自分の作業ツリーで切り替える。呼び出し元のセッションの `git -C` は hook に拒否されないが、別の作業ツリーのファイルを変える操作になるためである。`--detach` を使わないのは、ブランチがどの worktree にもチェックアウトされていない状態になり、同時に動く別のループの突き合わせで、増えたブランチとして扱われるためである。

```
review-rally <ループの id>: 記録の回番号 <回> のレビューの依頼 (識別子 <識別子>)

あなたは review-rally のレビューのセッションです。この会話より前のやり取りは消してあるので、
このメッセージに書いたことだけに従ってください。日本語で応答してください。

1. あなたの作業ツリー (cwd) を、レビューするコミットに切り替える。git status --porcelain の出力が
   空であることを確認してから、git checkout -B <レビューのセッションのブランチ> <SHA> を実行する。
   出力が空でないか、切り替えられなければ、依頼文を読まずに、下の 3 の失敗のメッセージを送る。
2. 依頼文 <依頼文の絶対パス> を Read ツールで読み、そのとおりにレビューする。指摘を見つけても直さない。
   依頼文の「対象」の作業ツリーは、あなたの作業ツリー (cwd) である。
3. 結果を書き出したら、ツール SendMessage で、宛先 to を <呼び出し元のセッションの id> にして、
   次の形の 1 行目で始まるメッセージを送り、ほかに何もせずにターンを終える。
   ツールが読み込まれていなければ ToolSearch の select:SendMessage で読み込む。
   - 成功: review-rally <ループの id> <識別子>: done <結果のファイルの絶対パス>
   - 失敗: review-rally <ループの id> <識別子>: failed <理由>
   2 行目以降に、依頼文が求める報告 (skill を実際に呼んだか・実際に渡した effort とモデル・
   HEAD と作業ツリーが不変であることの確認の結果) を書く。
```

## 待機

Bash ツールで `sleep 1800` をバックグラウンドで (`run_in_background: true`) 起動する。完了のメッセージが来ないまま時間が過ぎたことを、30 分ごとに確認するため。

`description` は次の形にする。通知に含まれるのはこの文と終了コードだけなので、compact (会話の要約) の後でも、この文から再入の手順に戻れるようにする。

```
review-rally <ループの id> (<識別子>): 依頼の後の 30 分ごとの確認。通知を受けたら review-rally の再入の手順へ
```

**待機を起動したターンでは、それ以外のツールを呼ばずにターンを終える。** 人間には 1 行 (何を待機しているか) だけ伝える。

## 再入の手順

**人間のメッセージ以外で始まったターン (レビューのセッションからのメッセージ・ターンの終了の通知 `<side-sessions-event>`・待機の通知) は、どれもこの入口に入る。** 遷移先は、会話の文脈ではなく、`rally.yaml`・記録・ファイルと、ターンを始めたもの (メッセージの `from` と 1 行目、待機の通知の `description`) から決める。これらを人間の回答 (S2 の回答など) として扱わない。

呼び出し元のセッションのターンが途中で中断したループは、この手順では扱わない。新しいループを始める。

1. **`rally.yaml` を読む。** ターンを始めたものがループの id を持てば (メッセージの 1 行目・待機の通知の `description`) そのループの `rally.yaml` を、持たなければ呼び出し元のセッションの作業ツリーの `tmp/review-rally/` の下で `state` が `active` の `rally.yaml` を読む。読めなければ中断して知らせる。`state` が `active` でなければ、何もせずに終える。
2. **結果待ちが無ければ (`waiting.run_id` が空)、識別子の衝突の待機の通知 (`description` が `review-rally <ループの id>: 識別子の衝突` で始まる) なら RRL1 の手順 1 からやり直し、それ以外なら何もせずに終える。**
3. **ターンを始めたもので分ける。**

   | ターンを始めたもの | 扱い |
   | --- | --- |
   | レビューのセッション (`from` が `session.id`) のメッセージで、1 行目が `review-rally <ループの id> <識別子>: done <パス>` | 識別子が `waiting.run_id` と違うか、記録に同じ `run_id` の回があれば、何もせずに終える。同じなら手順 5 (突き合わせ) に進む |
   | 同じく、1 行目が `review-rally <ループの id> <識別子>: failed <理由>` | 識別子が `waiting.run_id` と同じなら RR1。違えば何もせずに終える |
   | 同じく、1 行目がどちらの形でもない | RR1 |
   | ターンの終了の通知だけ | 下の「完了のメッセージが無いまま来たターン」 |
   | 待機の通知 (`description` が `review-rally <ループの id> (<識別子>)` で始まる) | 識別子が `waiting.run_id` と違えば何もせずに終える。同じなら、下の「完了のメッセージが無いまま来たターン」 |
   | ほかのセッションのメッセージ | 通知として扱わない。ループを進めない |

### 完了のメッセージが無いまま来たターン

ターンの終了の通知は、どの依頼に対するものかを持たず、前の回のものが遅れて届くことがある。そこで、ツール `get_session` でレビューのセッションの `isRunning` と `lastActivityAt` を読み、`rally.yaml` の `waiting.sent_at` と比べて決める。

| `isRunning` | `lastActivityAt` | 扱い |
| --- | --- | --- |
| `true` | 今から 60 分以内 | レビュー中。待機の通知で入ったなら、待機を起動し直す。ターンの終了の通知で入ったなら、何もせずに終える |
| `true` | 今から 60 分より前 | RR1 (応答なし) |
| `false` | `waiting.sent_at` より前 | 依頼を受けたターンがまだ始まっていない。待機の通知で入ったなら RR3 (依頼が処理されない)。ターンの終了の通知で入ったなら、何もせずに終える |
| `false` | `waiting.sent_at` より後 | 依頼を受けたターンが、完了のメッセージを送らずに終了した。結果のディレクトリに結果のファイル (`review-<識別子>.yaml`) があれば手順 5 に進む。無ければ RR1 |

## L2 で `review-triage` に渡すもの

渡すものと、`review-triage` が返った後に確認することの SSOT は、[review-invocation.md](../../review-triage-loop/references/review-invocation.md) の「別のプロセスでレビューした結果の取り込み」の「`review-triage` に渡すもの」。そこで「その経路のレビュー不成立」と書くものは、このスキルでは RR1。このスキルの値は次のとおり。

- 「レビュアの実行を確認した材料」は、`get_session` の値 (`rally.yaml` の `session`) と完了のメッセージ。
- 記録の `model` は、`rally.yaml` の `session.model` から `claude-` を除いたもの (`opus-5-5` など)。
- 記録の `notes` に書く 1 行は、下の「`notes` の固定書式」。

`review-triage` が返ったら、`rally.yaml` の `waiting.run_id` を空にする。

## `notes` の固定書式

```
review-rally: <ループの id> / review_session: <session.id> / model: <loop.model> (実効: <session.model>) / effort: <loop.effort> (実効: <session.effort>) / permission_mode: <session.permission_mode> / review_minutes: <分>
```

- `review_minutes` は、`waiting.sent_at` から、手順 5 に入ったターンまでの分 (小数第 1 位まで)。
- 記録のスキーマは変えない。ほかの経路の回と収束を比べるときは、この行の有無で経路を分ける。
