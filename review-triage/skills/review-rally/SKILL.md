---
name: review-rally
description: レビューを、このセッションから起動した別の Claude Code のセッション (レビューのセッション。専用の worktree で動く) に任せ、トリアージと修正をこのセッションで行うループを、停止するまで回す。依頼と完了の通知はセッション間のメッセージで行い、2 回目以降は依頼の前にレビューのセッションの会話を消す。「レビューを別のセッションに任せて回して」「セッションを起動してレビューから修正までを回して」「review-rally を実行して」のような依頼で使う。引数でレビューのセッションのモデル (--model) と effort (--effort)・レビュースキルとそのオプション・上限・全量の起点にする派生元のブランチ (--base)・回数の閾値とフェーズの実行方法 (どちらも review-triage-fix に渡す) を指定できる。Claude のデスクトップアプリで、worktree ではないメインの作業ツリーで動くセッションから使う。
---

# review-rally: レビューを別のセッションに任せるループ

レビューは、このセッション (以下「メインのセッション」) がツール `start_session` で起動するセッション (以下「レビューのセッション」) が行う。レビューのセッションは、アプリが作る専用の git worktree (以下「レビューの worktree」) で動く。**メインのセッションは、依頼文を書き、ツール `SendMessage` で依頼し、完了の通知を受けて [review-triage](../review-triage/SKILL.md) と [review-triage-fix](../review-triage-fix/SKILL.md) を呼ぶ。** 成果物はループの結果の報告で、判断は `review-triage`、修正は `review-triage-fix` が持つ。

端末のワーカーでレビューするループ ([review-loop](../review-loop/SKILL.md)) との違いは、レビューを `claude -p` ではなく対話のセッションで行うことである。人間はレビューのセッションを開いて見守れる。代わりに、レビューのセッションのモデルと effort は、メインのセッション以下しか選べない (アプリの制約)。どの経路で回したかは記録の `notes` の 1 行に残る。

## SSOT の宣言

**ループの順序・分岐・停止の条件・報告は、`review-triage-loop` の [loop-flow.md](../review-triage-loop/references/loop-flow.md) と [reporting.md](../review-triage-loop/references/reporting.md) が SSOT (single source of truth。ある事実を定めている唯一の記述)。** このスキルは `review-triage-loop` を呼ばず、同じ図に従って自分で `review-triage` と `review-triage-fix` を呼ぶ。差し替えるのは G0 (条件を読む) と L1 (レビューを起動する) で、停止ノードを 4 つ (RR1〜RR4) 足す。散文で遷移を言い直さない。

| 流用元 | 使うもの | 使わないもの (このスキルの SSOT) |
| --- | --- | --- |
| [loop-flow.md](../review-triage-loop/references/loop-flow.md) の図と決定表 | G2・G3・L2・J2・J4・J5・J7・J8・J9・F1・S2〜S6 のノードと行 | G0 → RRG0、L1 → RRL1 ([round.md](references/round.md))。追加の停止 RR1〜RR4 と、差し替えた部分の図 ([stops.md](references/stops.md)) |
| [reporting.md](../review-triage-loop/references/reporting.md) | 必ず出すもの 6 項目 (停止した理由に RR1〜RR4 を含める) | このループで足す項目 ([stops.md](references/stops.md) の「停止の報告に足すもの」) |
| [review-invocation.md](../review-triage-loop/references/review-invocation.md) | 「記録のキーの出所」の表・「effort の既定」・「別のプロセスでレビューした結果の取り込み」(呼ぶスキル・結果のファイルの照合・`review-triage` に渡すもの) | 「G0 での解決」(レビューのセッションのモデルは人間が決める)・「範囲」(基点は `review-request` の規則) |
| [arguments.md (review-triage-loop)](../review-triage-loop/references/arguments.md) | 優先順位と、`loop`・`fix` のキーの値の検査 | このスキルの引数の様式 ([arguments.md](references/arguments.md)) |

レビューのセッションの起動と、ループの状態のファイル (`rally.yaml`) の様式の SSOT は [session.md](references/session.md)。

## 前提知識

- **ループは必ず停止する。** 停止の条件は `review-triage-loop` と同じ (上限・収束・選択待ち・進まない・構造の見直し) に、RR1〜RR4 を足したもの。停止したら、レビューのセッションと worktree を片付けずに、片付けの案内を報告に書いて終える (片付けるかどうかは人間が決める。[stops.md](references/stops.md) の「停止のときに行うこと」)。**初版は、停止したループを続ける手段 (`--resume`) を持たない。** 続けるときは新しいループを始める。記録は回をまたいで続くので、推移は失われない。
- **メインのセッションは、worktree ではなくメインの作業ツリーで動かす。** レビューの worktree はメインの作業ツリーの下 (`.claude/worktrees/`) に置かれ、依頼文と結果はその中に書く ([round.md](references/round.md) の「ファイルのディレクトリ」)。メインのセッションが worktree で動いていると、ほかの worktree への書き込みと git の操作を拒否される。
- **レビューのセッションのモデルと effort は人間が決める。** このスキルは推測せず、決まらなければ質問する。アプリは起動元より上のモデルと effort を選べず、上を指定しても誤りにせずに無視するので、起動の直後に実際の値を確認し、指定と違えば停止する (RR2。[session.md](references/session.md))。
- **依頼と完了の通知はセッション間のメッセージで行う。** 依頼文と結果はファイルで、メッセージで渡すのはそのパスと完了の 1 行だけ。依頼文を会話に貼らない理由の SSOT は [review-request.md](../review-triage/references/review-request.md) の「依頼文はファイルに書き出し、パスだけを渡す」。
- **2 回目以降は、依頼の前にレビューのセッションの会話を消す** (ツール `clear_session`)。回ごとにレビュアの文脈が新しくなる。消すことを拒否されたら (人間がそのセッションを画面に開いている・ピン留めしている、など)、会話を残したまま続けずに停止する (RR3)。
- **同時に動くのは、メインのセッションかレビューのセッションのどちらか一方。** レビューの間は、メインのセッションも人間も、メインの作業ツリーとレビューの worktree を変えない。メインのセッションは、依頼を送ったらターンを終える。
- **ループの間に履歴を書き換えない** (reset・rebase・squash)。増分の基点 (直前の回の `head`) が履歴から外れると、依頼文を書けずに停止する (RR4)。
- **通知は人間の入力ではない。** レビューのセッションからのメッセージ・ターンの終了の通知・待機の通知を、人間の回答 (S2 の回答など) として扱わない。

## 手順

### 開始 (`/review-rally`)

1. **条件を決める** (RRG0): 引数と設定から決め、値を検査する ([arguments.md](references/arguments.md))。レビューのセッションのモデルと effort、レビュースキルが決まらなければ人間に質問する。
2. **開始の前提を確認する** ([session.md](references/session.md) の「開始の前提」)。
3. **ループのディレクトリと `rally.yaml` を作る** ([session.md](references/session.md) の「ループのディレクトリを作る」)。
4. **レビューのセッションを起動し、実際の値を確認する** ([session.md](references/session.md) の「起動」)。**起動はこの開始のターンで行う。** アプリは、メッセージや自動の通知で始まったターンからはセッションを起動させない。
5. **決まった条件を報告する** (書くものは [round.md](references/round.md) の決定表の RRG0)。**どの条件で回るかを、回り始める前に人間が知っている状態にする。**
6. **ループを回す**: G2 から [loop-flow.md](../review-triage-loop/references/loop-flow.md) の図に従う。L1 に来たら RRL1 ([round.md](references/round.md))。依頼を送ったら待機を起動して**ターンを終える** ([round.md](references/round.md) の「待機」)。

### 再入 (完了のメッセージ・ターンの終了の通知・待機の通知)

**どれで始まったターンも、同じ 1 つの入口 ([round.md](references/round.md) の「再入の手順」) に入る。** 入口は `rally.yaml` と記録とファイルだけから遷移先を決めるので、会話が compact (会話の要約) された後でも戻れる。

- 取り込んだ回は、L2 で Skill ツールで `review-triage` を呼んで渡す (指摘が 0 件の回も呼ぶ。呼ぶスキルの規則と渡すものの SSOT は [review-invocation.md](../review-triage-loop/references/review-invocation.md) の「別のプロセスでレビューした結果の取り込み」、このスキルでの値は [round.md](references/round.md) の「L2 で `review-triage` に渡すもの」)。その後は図のとおり J2 に進む。
- F1 では Skill ツールで `review-triage-fix` を呼び、`rally.yaml` の `loop.threshold` を `--threshold` に、`loop.stages` の各要素を `--stage` に渡す。

### 停止

図に従って停止ノード (S2〜S6・RR1〜RR4) に到達したら、[stops.md](references/stops.md) の「停止のときに行うこと」のとおり、依頼文と結果を複製し、`rally.yaml` を書き換え、片付けの案内を書いて報告する。報告の形は [reporting.md](../review-triage-loop/references/reporting.md)、停止ノードごとに足すものは [loop-flow.md](../review-triage-loop/references/loop-flow.md) の決定表 (S2〜S6) と [stops.md](references/stops.md) の決定表 (RR1〜RR4)、このループで足すものは [stops.md](references/stops.md) の「停止の報告に足すもの」。

## 原則

- **このスキルは判断も修正もしない。** `review-request`・`review-triage`・`review-triage-fix` を、回ごとに Skill ツールで呼ぶだけ (規則の SSOT は [review-invocation.md](../review-triage-loop/references/review-invocation.md) の「別のプロセスでレビューした結果の取り込み」の「呼ぶスキル」)。
- **待機を起動したターンでは、それ以外のツールを呼ばない。** 通知で次のターンが始まる (理由の SSOT は [round.md](references/round.md) の「待機」)。
- **ループが条件を勝手に変えない。** 条件は `rally.yaml` にある。
- **ループのディレクトリ (`tmp/review-rally/<ループの id>/`) と記録を消さない。** 後で経路どうしの収束を比べる材料になる。
- **人間に返した状態を越えて進まない。** 選択待ち (S2) と停止 (RR1〜RR4) は、人間の判断を求めて停止した結果である。

## このスキルが検出しないもの

- **レビューのセッションのレビューの中身が正しいか** — 確認しない。確認するのは、結果のファイルの様式と、作業ツリーとブランチが変わっていないことだけ ([round.md](references/round.md) の「突き合わせ」)。
- **レビューのセッションが、レビュースキルを実際に呼び出したか・拒否されたツールの呼び出しがあったか** — レビューのセッションの自己申告しか手段が無いので、初版では確認も記録もしない。
- **レビューのセッションの effort がレビュースキルの実行に適用されたか** — `get_session` で確認できるのはセッションの設定までである。
- **収束したことが「欠陥が無い」ことを意味するか** — 意味しない。そのレビュースキル・そのモデル・その effort・その範囲で指摘が出なかったということである。
