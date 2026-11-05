# 追加の判定と停止

**このファイルが、`review-rally` が足した判定 RRJ1 と停止 RR1〜RR4 の決定表と、どの停止でも行うことの SSOT。** RR1〜RR4 に進む条件は、その ID を書いた手順が定める。

## 決定表 (RRJ1・RR1〜RR4)

| ID | 種類 | 条件 | 報告に書くもの |
| --- | --- | --- | --- |
| RRJ1 | 判定 | `rally.yaml` の `loop.full_review` が真で、収束後の全量レビューが要るか (要否の規則の SSOT は [review-request.md](../../review-triage/references/review-request.md) の「収束後の全量レビューと、その要否」)。J2 の「無い」で通る。上限 (J5) を見ない。「はい」なら `next_full` を真にしてから、[round.md](round.md) の手順 1 に入る。「いいえ」なら S3 | — |
| RR1 | 停止 | レビュー不成立 | その回の識別子と、不成立の理由 (失敗の通知の理由・通知の 1 行目・一致しなかった項目と両方の値)。結果のファイルの有無と、複製したパス (下の「停止のときに行うこと」の 1)。応答なしなら、承認待ちなどでレビューのセッションのターンが進んでいないおそれがあること (人間がレビューのセッションを開いて確認する)。レビューの worktree が clean でないか、切り替えに失敗したときは、失敗の通知の理由にそのことが書かれる。リポジトリのブランチの一覧かメインの作業ツリーの HEAD が依頼の前と違うなら、SHA が変わった・増えた・消えたブランチと、依頼の前と後の値。メインの作業ツリーで動く別のセッションの操作でも同じ差が出ること。戻すかどうかは人間が決めること |
| RR2 | 停止 | レビューのセッションを使えない | 当たった項目と、指定の値と実際の値。モデルか effort が違うなら、呼び出し元のセッションのモデルか effort を上げるか、指定を下げて新しいループを始めること |
| RR3 | 停止 | 拒否された | 拒否したツールと、その結果の文面。`clear_session` なら、人間がレビューのセッションを画面に開いているかピン留めしていると拒否されるので、閉じるか外してから新しいループを始めること。`SendMessage` や依頼が処理されないなら、メッセージが承認待ちになっているおそれがあること ([session.md](session.md) の「起動」の 1) |
| RR4 | 停止 | 依頼文を作れない | 当たったものすべてと、何を片付ければよいか。汚れたファイルの一覧、記録のパスと読めない理由、基点の SHA と現在の HEAD、`review-request` が報告した理由。ループのディレクトリが無視されていなければ、どのファイル (`.gitignore`) に何 (`tmp/`) を足し、どのブランチ (現在のブランチ) にコミットするか。基点が祖先でないときは、ループの間に履歴を書き換えた (reset・rebase・squash) ことが原因であり、どう続けるかは人間が決めること |

## 停止のときに行うこと

**どの停止ノード ([loop-flow.md](../../review-triage-loop/references/loop-flow.md) の S2〜S6 と、上の RR1〜RR4) でも、次の順に行ってから報告する。**

1. **結果を複製する。** 結果のディレクトリに結果が 1 つでもあれば、すべての結果を Bash ツールの `cp` でループのディレクトリに複製する。依頼文は既にループのディレクトリにある。レビューの worktree を片付けた後も、停止の原因を調べられるようにするため。
2. **`rally.yaml` を `state: stopped`・`stop_reason: "<ID>: <1 行の理由>"` にする。**
3. **片付けはしない。案内だけを報告に書く** (下の「片付けの案内」)。片付けは元に戻せないので、行うかどうかは人間が決める。

## 片付けの案内

停止の報告に、次の手順を、人間が実行できる形で書く。手順は `rally.yaml` の `session` から組み立てる。`session` の値は、起動の手順のどこまで進んだかで決まる ([session.md](session.md) の「起動」)。値が空のキーを使う手順は書かない。

- **`session.id` が空なら** (`start_session` が失敗した): 片付けるものは無いと書く。
- **`session.id` があり、`session.worktree` が空なら** (`worktreePath` の確認に通らなかった): worktree とブランチを確認していないので、アーカイブと `git branch -D` を案内しない。レビューのセッション (`session.name`・`session.id`) を開いて、どう片付けるかを人間が決めると書く。
- **`session.worktree` があり、新しく作られた worktree なら** (`session.reused` が偽): レビューのセッション (`session.name`・`session.id`) をアーカイブする (サイドバーから。アーカイブで worktree も片付けられる)。アーカイブの後にブランチ (`session.branch`) が残っていれば、`git branch -D <session.branch>` で消す。
- **`session.worktree` があり、再利用された worktree なら** (`session.reused` が真): レビューのセッションを**アーカイブしない** (以前の作業のファイルが消えるおそれがある)。結果のディレクトリを消し (`rm -r <レビューの worktree>/tmp/review-rally/<ループの id>`)、worktree を元の HEAD に戻し (`git -C <レビューの worktree> show-ref --verify --quiet refs/heads/<session.original_head>` が成功すれば `git -C <レビューの worktree> checkout <session.original_head>`、失敗すれば `git -C <レビューの worktree> checkout --detach <session.original_head>`)、ブランチを消す (`git branch -D <session.branch>`)。
- **ループのディレクトリと記録は消さない。** ほかの経路と収束を比べる材料になる。どちらも呼び出し元のセッションの作業ツリーにあり ([session.md](session.md) の「開始の前提」)、その作業ツリーが片付けられると一緒に消えるので、残すときは片付ける前に複製する。

## 停止の報告に足すもの

報告の全体は [reporting.md](../../review-triage-loop/references/reporting.md) の「必ず出すもの」で、S2〜S6 ごとに足すものは [loop-flow.md](../../review-triage-loop/references/loop-flow.md) の決定表。このループでは、どの停止 (S2〜S6・RR1〜RR4) でも次を足す。

| 項目 | 書くもの |
| --- | --- |
| ループ | ループの id と、ループのディレクトリの絶対パス |
| レビューのセッション | 名前・id・worktree のパス・実効モデルと effort (`rally.yaml` の `session`) |
| 複製 | 上の「停止のときに行うこと」の 1 で複製したか、複製先の絶対パス |
| 片付け | 上の「片付けの案内」 |
| 回数 | この起動で回した回数と上限 (reporting.md の 2) |
| 次にできる操作 | 新しいループを始めること (このスキルは `--resume` を持たない)。S2 なら、回答の渡し先 (`review-triage-fix` を単独で起動して回答する。SSOT は loop-flow.md の S2 の行) |
| S3 のとき | 収束後の全量レビューの要否 (規則の SSOT は [review-request.md](../../review-triage/references/review-request.md) の「収束後の全量レビューと、その要否」) と、全量で見直すには `--full-first` を付けて新しいループを始めること。行うかどうかは人間が決める |
