---
title: レビューを、メインのセッションから起動した別のセッションに任せるループ (review-rally) - Plan
type: feat
date: 2026-10-29
topic: review-rally
execution: code
---

# レビューを、メインのセッションから起動した別のセッションに任せるループ (review-rally) - Plan

要件の出所は GitHub の Issue [akm/claude-plugins#151](https://github.com/akm/claude-plugins/issues/151) の本文 (「要望」と「決まったこと」) と、前提を確認した 2 つの試験の結果 ([通信の試験](https://github.com/akm/claude-plugins/issues/151#issuecomment-6482935079)・[worktree の書き込みの試験](https://github.com/akm/claude-plugins/issues/151#issuecomment-6483476113))。Q1〜Q6 は、この計画を作る中で出てきた点で、2026-10-29 に利用者が決めた。

この計画で使う語:

- **メインのセッション**: スキル `review-rally` を実行し、トリアージと修正をする Claude Code のセッション。
- **レビューのセッション**: メインのセッションがツール `start_session` で起動し、レビューだけをするセッション。
- **レビューの worktree**: レビューのセッションが動く git worktree。`start_session` の `use_worktree: true` でアプリが作る。
- **ループの id**: ループごとに付ける識別子。`review-loop` と同じく `<YYYYMMDD>-<hhmm>-<ブランチ名>` とする。

## 目的と手段

- **目的**: レビューを、メインのセッションから起動した別のセッションに任せて、レビューから修正までを収束するまで繰り返す。人間の操作は、ループの起動と、停止した後の判断だけにする。
- **手段**: スキル `review-rally` を足す。ループの流れは、ファイル `review-triage/skills/review-triage-loop/references/loop-flow.md` の図に従い、G0 (条件を読む) と L1 (レビューを起動する) を差し替えて、停止を足す。依頼と完了の通知は、ツール `SendMessage` で行う。
- **変えるのは手順書 (Markdown) と、ファイル `review-triage/.claude-plugin/plugin.json` の版、ファイル `review-triage/README.md` だけ。** スクリプトとツール `triagecheck` は変えない。
- **実装を中断して人間に返す条件**:
  - 通し確認 (U7) で、レビューのセッションが結果のファイルを書けない、またはメインのセッションがレビューの worktree を HEAD に合わせられない。
  - スクリプトを足さないと実現できない手順が見つかった。

## 決まったこと (#151 の「決まったこと」の要約)

| ID | 決まったこと |
| --- | --- |
| D1 | 2 回目以降のレビューは、回ごとにツール `clear_session` でレビューのセッションの会話を消してから頼む。拒否されたら停止する |
| D2 | レビューのセッションは別の worktree で動かす。回ごとに、メインのセッションがその worktree を自分の HEAD に合わせる |
| D3 | モデルと effort の制約 (起動元以下) は受け入れる。起動の直後にツール `get_session` で実際の値を確認し、指定と違えば停止する |
| D4 | 初版は最小の形にする。停止したら、レビューのセッションと worktree を片付けて終える。`--resume`・`--end`・`--full-review` に当たるものは後に回す |
| D5 | `review-loop` と共通になる、ワーカーに依らない規則は、`review-triage-loop` の文書へ移し、両方から参照する。別のコミット、できれば先に別の PR にする |
| D6 | 記録には、経路を `notes` の固定の書式の 1 行で残す。スキーマは変えない |

## 計画で決めたこと (2026-10-29)

| ID | 点 | 決めたこと |
| --- | --- | --- |
| Q1 | **停止をもう 1 つ足す。** #151 では review-rally だけの停止を 3 つ (レビュー不成立・起動できないか値が違う・拒否された) としたが、`review-loop` の RA3 に当たる「依頼文を作れない (作業ツリーが clean でない・記録が読めない・増分の基点が HEAD の祖先でない)」が抜けていた | 足す (RR4) |
| Q2 | **依頼文と結果のディレクトリ。** 2026-10-29 の試験で次が分かった。(1) レビューのセッションは、自分の worktree の外へ Write すると PreToolUse の hook に拒否される。メインの作業ツリーは読める。(2) メインのセッション (worktree で動いていない) は、レビューの worktree へ Write でき、`git -C <worktree> checkout --detach` も実行できる。(3) アプリは worktree をメインの作業ツリーの `.claude/worktrees/` の下に置くが、既存の worktree を再利用することがあり、パスは `branch_name` から決まらない | 依頼文と結果を、レビューの worktree の `tmp/review-rally/<ループの id>/` に置く。メインのセッションは `review-request --dir` にこのパスを渡し、結果は読むだけにする。この形は、次の 2 つの無視を前提にする。(i) メインの作業ツリーから見て、`.claude/worktrees/` が git に無視されている。このリポジトリで無視しているのは `.gitignore` ではなく `.git/info/exclude` である。無視されていないリポジトリでは、メインの作業ツリーに `?? .claude/` (`.claude/` の下に追跡するファイルがあれば `?? .claude/worktrees/`) が出て clean でなくなるので、RR4 で停止する (確認の順と案内は「1 回の流れ」の手順 2)。(ii) レビューの worktree の中から見て、`--dir` のディレクトリ (`tmp/` の下) が無視されている。`review-request` が確認するのはメインの作業ツリーから見た無視だけなので、(i) だけが成り立つリポジトリでは、依頼文を書いた時点でレビューの worktree に `?? tmp/` が出る。そのため、「1 回の流れ」の手順 2 で `review-request` を呼び出す前に確認する。レビューの worktree のパスは、起動の後に `get_session` の `cwd` から取る。メインのセッションが worktree で動いているときは、初版では対象外にする (レビューの worktree がメインの作業ツリーの外になり、`--dir` に渡せず、書き込みも拒否されるおそれがある。この場合は試験していない)。起動の前にこれを確認し、当たれば RR2 で停止する |
| Q3 | **依頼文の「作業ツリーの扱い」の値。** 雛形の値は「共有」(読み取り専用。確認のための変更は revert する) と「使い捨て」(複製の中でだけ変えてよい) の 2 つ | 「共有」のまま書き換えない。レビューの worktree は回をまたいで使い続けるので、レビュアが変更を残すと、次の回に HEAD に合わせる操作 (`checkout --detach`) が失敗するか、変更が次の回に残る。「共有」なら、回の後に作業ツリーが clean であることを確認すれば足りる。依頼文の「対象」の作業ツリーには、`review-request` が既定ではメインのセッションの作業ツリーを埋める。レビューの worktree を指すようにするには、`review-request` に、対象の作業ツリーを指定する引数 (名前は U3a で決める。例: `--target-dir`) を足して渡す (2026-10-29 の PR #152 のレビューの指摘を受けて利用者が決めた。依頼文を書くのを `review-request` だけに保つため)。#151 の本文の「依頼文の作業ツリーの扱いを書き換える手順が要る」は、これに合わせて直した |
| Q4 | **設定のキー。** `review-loop` は設定 `review_loop` を持つ | 新しいキーを足さず、`loop` のキー (`review_skill`・`review_args`・`review_model`・`max_rounds`・`structure_rounds`) と `fix` のキーを使う。引数で上書きできるのは `--model`・`--effort`・レビュースキルとそのオプション・`--max`・`--structure-rounds`・`--threshold`・`--stage`。設定のキーを持たない引数として `--base` (記録に回が無いときの最初の全量の回の起点にする派生元のブランチ。`review-request` に渡す) も受け付ける。レビューのセッションのモデルは、引数 `--model`、無ければ `loop.review_model`、それも無ければ人間に質問する。effort は引数 `--effort` で指定し、無ければ人間に質問する (推測しない)。権限モードは指定せず、メインのセッションのものを引き継がせる (権限モードが同じなら、メッセージが承認待ちにならない)。状態のファイルのディレクトリは `tmp/review-rally/` に決め打ちする |
| Q5 | **ループの状態を残すファイル。** 初版は `--resume` を持たないが、会話が長くなって compact (会話の要約) されると、レビューのセッションの id・worktree のパス・回数が失われうる | メインのセッションの `tmp/review-rally/<ループの id>/rally.yaml` に、ループの条件・レビューのセッションの id・worktree のパス・この起動で数えた回数・結果待ちの依頼文の識別子と、その依頼を送った時刻 (記録の `notes` の `review_minutes` の起点) を書く。書き込み元はメインのセッションだけ |
| Q6 | **D5 で移す節。** ファイル `review-triage/skills/review-loop/references/round.md` のうち、ワーカーに依らない節 | 次の 3 つを、ファイル `review-triage/skills/review-triage-loop/references/review-invocation.md` の新しい節「別のプロセスでレビューした結果の取り込み」へ移す。(1) 節「呼ぶスキル」(回ごとに Skill ツールで呼ぶ規則)、(2) 節「L2 で `review-triage` に渡すもの」のうち、記録の `scope` を結果ファイルの値から採る規則・`run_id` を結果ファイルからそのまま写させる規則・`review-triage` が返った後に `run_id` を写したかの確認、(3) 節「1 回のレビュー (RL1)」の手順 (c) の 11 (結果ファイルの `run_id`・`scope`・`base` の照合)。ワーカーのフラグファイルに関わる部分 (手順 (c) の 1〜10)、記録の `model` の採り方、`notes` の書式は移さない |

## 停止

`loop-flow.md` の S2〜S6 に、次を足す。番号は `review-loop` の RA1〜RA3 と区別するため RR とする。

| ID | 停止 | 条件 |
| --- | --- | --- |
| RR1 | レビュー不成立 | レビューのセッションが失敗を通知した・完了を通知せずにターンを終えた (どう判定するかは U4 で決める。下の「1 回の流れ」の手順 5)・結果ファイルが読めないか `run_id`・`scope`・`base` が依頼文と違う・レビューの worktree の HEAD が変わったか clean でない・メインのリポジトリのブランチや HEAD がレビューの間に変わった・`review-triage` が結果の様式を差し戻した |
| RR2 | レビューのセッションを使えない | メインのセッションが worktree で動いている (Q2)・`start_session` が失敗した・`get_session` のモデルか effort が指定と違う・レビューの worktree が clean でないか、HEAD に合わせられない (下の「1 回の流れ」の手順 1) |
| RR3 | 拒否された | `SendMessage` が届かなかった (承認待ちのまま期限が切れた、など)・`clear_session` を拒否された |
| RR4 | 依頼文を作れない (Q1) | 作業ツリーが clean でない・レビューの worktree の中から見て `--dir` のディレクトリが無視されていない (Q2 の (ii))・記録が読めない・増分の基点が HEAD の祖先でない・`review-request` が依頼文を書かなかった |

どの停止でも、レビューの worktree の `tmp/review-rally/<ループの id>/` に依頼文か結果が 1 つでもあれば、そのディレクトリの全体 (前の回のものを含む) を、メインのセッションの `tmp/review-rally/<ループの id>/` に複製してから片付け (U5) をし、報告には複製のパスを書く。依頼文も結果も無い停止 (依頼文を作る前の RR2 など) は、複製せずに片付ける。片付けのアーカイブはレビューの worktree も片付けるので、複製しないと、停止の原因を結果のファイルで調べられなくなる。

## 1 回の流れ (L1 の差し替え)

1. **レビューの worktree を合わせる**: `git -C <worktree> status --porcelain` が空であることを確認してから、`git -C <worktree> checkout --detach <HEAD の SHA>` を実行する。空でないか、切り替えられなければ RR2。依頼文を書く前に合わせるのは、手順 2 のレビューの worktree の中から見た無視の確認を、レビューする HEAD の `.gitignore` で行うため。
2. **依頼文を書く**: RR4 の条件を確認し、Skill ツールで `review-request` を呼び出す。確認は、メインの作業ツリーが clean か (clean でなく、出ているのが `?? .claude/` か `?? .claude/worktrees/` なら、`.gitignore` に `.claude/worktrees/` を足すよう案内する。Q2 の (i)。それ以外の変更なら、コミットするか退避するよう案内する) → レビューの worktree の中から見た無視 (`git -C <worktree> check-ignore -q <--dir のパス>`。当たれば、`.gitignore` に `tmp/` を足すよう案内する。Q2 の (ii)) → 停止の表の RR4 の残りの条件、の順に行う。両方に当たるリポジトリでは、先に (i) の案内が出て、直して起動し直すと (ii) の案内が出る。`review-request` を呼び出すのは、この確認がすべて通った後である (`--dir` はレビューの worktree の中。Q2。対象の作業ツリーを指定する引数にはレビューの worktree を渡す。Q3)。
3. **会話を消す**: 2 回目以降は、ツール `clear_session` を実行する (D1)。
4. **依頼する**: `SendMessage` で、依頼文のパスと、完了の通知の様式 (下記) を送る。会話を消した後なので、毎回すべてを書く。ターンを終える。
5. **通知を受ける**: レビューのセッションからのメッセージ (`from` がレビューのセッションの id) で、次のターンが始まる。人間のメッセージやほかのセッションのメッセージで始まったターンは、通知として扱わない。レビューのセッションのターンの終了の通知 (`<side-sessions-event>`) だけで始まったターンでは、その通知がどの依頼に対するものかが分からない (PR #152 の試しでは、前の回のターンの終了の通知が、完了のメッセージの後に単独で届いた)。このターンの扱いは、次の 2 つの要件を満たすように U4 で決める。規則は、通知が届く時機と、`get_session` の値 (`isRunning`・`lastActivityAt`) がどの操作で更新されるかを試してから決める (計画の文で規則を詰めると、試していない場合への指摘が回ごとに続いたため。2026-10-29 に利用者が決めた)。
   - 前の回の終了の通知を、今の回の失敗と読んで停止しない。
   - 依頼が処理されないまま、利用者に知らせずに待機し続けない。依頼の後にメインのセッションにターンが来ない場合 (レビューのセッションが承認待ちのまま、ターンを終えない、など) も含める。この場合は手順 5 のターンが始まらないので、どう満たすか (期限のある待機など) も U4 で決める。
6. **突き合わせる**: 結果ファイル・レビューの worktree・メインのリポジトリを確認する (RR1 の条件)。通れば L2 (`review-triage`) に進む。

完了の通知の様式 (レビューのセッションが送る 1 行目):

```
review-rally <ループの id> <識別子>: done <結果ファイルの絶対パス>
review-rally <ループの id> <識別子>: failed <理由>
```

## 記録の `notes` の固定書式 (D6)

```
review-rally: <ループの id> / review_session: <セッション id> / model: <指定> (実効: <get_session の値>) / effort: <指定> (実効: <get_session の値>) / permission_mode: <get_session の値> / review_minutes: <依頼を送ってから通知を受けるまでの分>
```

## 実装単位

ドメインごとに分け、依存される方を先にする。各単位で「確認の方法を決める → 文書を書く」の順に進める。この変更はスクリプトを持たないので、単体テストの代わりに、文書の上で手順を辿る確認と、最後の通し確認 (U7) で確認する。

### U1. 共通の規則を `review-triage-loop` の文書へ移す (D5・Q6。別の PR)

- **確認の方法**: 移した後に `review-loop` の手順を文書の上で辿り、参照がすべて解けることと、振る舞いが変わらないことを確認する。`doc-dag` で、参照に循環が無く、同じ事実の複製が増えていないことを確認する。
- **変えるファイル**: `review-triage/skills/review-triage-loop/references/review-invocation.md` (節を足す)、`review-triage/skills/review-loop/references/round.md` (移した節を参照に置き換える)、`review-triage/skills/review-loop/SKILL.md` (流用元の表)。
- **書き方**: 移した部分は、`round.md` では新しい節への参照に置き換える。レビュー不成立の停止の名前は経路ごとに違う (`review-loop` は RA1、`review-rally` は RR1) ので、新しい節では「その経路のレビュー不成立」と書き、各スキルの文書で対応を書く。
- **PR**: この単位だけで 1 つの PR にし、マージしてから U2 以降のブランチを作る。版は patch を上げる。

### U2. スキルの SKILL.md と条件の決め方 (G0 の差し替え。Q4)

- **確認の方法**: 引数と設定の組み合わせごとに、決まる条件を表にして、文書の上で辿る。
- **作るファイル**: `review-triage/skills/review-rally/SKILL.md` (SSOT の宣言・流用元の表・前提知識・手順・原則・検出しないもの)、`review-triage/skills/review-rally/references/arguments.md`。

### U3. レビューのセッションの起動と確認 (D2・D3・RR2)

- **確認の方法**: 起動の前の確認 (メインのセッションが worktree で動いていないこと)、起動の引数 (`model`・`effort`・`use_worktree: true`・`context: "fresh"`・`name`。権限モードは指定しない)、起動の直後の `get_session` の確認 (モデル・effort・worktree のパス) を、文書の上で辿る。
- **作るファイル**: `review-triage/skills/review-rally/references/session.md` (起動の引数・最初の指示文・`get_session` での確認・`rally.yaml` の様式 (Q5))。

### U3a. `review-request` に、依頼文の対象の作業ツリーを指定する引数を足す (Q3)

U4 がこの引数を使うので、U4 より前に行う。

- **確認の方法**: 引数がある場合と無い場合のそれぞれで、依頼文の「対象」の作業ツリーと、`review-request` が確認する作業ツリー (範囲・HEAD・clean) を文書の上で辿る。`review-request` が確認するのは、引数があってもメインのセッションの作業ツリーのままにする。指定した作業ツリーの HEAD と clean は、`review-rally` が「1 回の流れ」の手順 1 (依頼文を書く前) と手順 6 で確認する。`review-request` に確認を足さないのは、`review-request` が確認するのは依頼元 (メインの作業ツリー) の状態で、対象の作業ツリーを HEAD に合わせるのは `review-rally` の手順 1 だからである。`review-request` に足すと、`review-rally` 以外の使い方でも、対象の作業ツリーを先に HEAD に合わせておく前提が要る。
- **変えるファイル**: `review-triage/skills/review-request/SKILL.md` (引数の表・手順 4 の `repo_dir` の埋め方)。雛形は `{{repo_dir}}` を埋める値が変わるだけなので変えない。版は minor を上げる (引数を足すため)。

### U4. 1 回のレビュー (L1 の差し替え。D1・Q1〜Q3・RR1〜RR4)

- **確認の方法**: 上の「1 回の流れ」の各手順で、通る場合と各停止に入る場合を文書の上で辿る。手順 5 の終了の通知だけで始まったターンの扱いは、文書を書く前に、試験用のセッションで通知が届く時機と `get_session` の値の更新のされ方を試し、その結果から手順 5 の 2 つの要件を満たす規則を決める。
- **作るファイル**: `review-triage/skills/review-rally/references/round.md` (worktree を合わせる・依頼文・会話を消す・依頼のメッセージの文面・通知の受け方・突き合わせ・L2 に渡すもの・`notes` の書式)。
- **変えるファイル**: `review-triage/skills/review-triage-loop/references/review-invocation.md`。U1 で書いた、経路を `review-loop` だけとする箇所 (冒頭の宣言・節「記録のキーの出所」の太字の宣言・節「別のプロセスでレビューした結果の取り込み」の冒頭) に `review-rally` を足す。足さないと、`review-rally` の記録の `scope` を表の値から採る読み方ができてしまう。

### U5. 停止と片付け (D4)

- **確認の方法**: 各停止 (S2〜S6・RR1〜RR4) から片付けと報告までを文書の上で辿る。
- **作るファイル**: `review-triage/skills/review-rally/references/stops.md` (追加の停止の決定表・片付け・報告に足すもの)。片付けの前に、依頼文と結果をメインのセッションの `tmp/review-rally/<ループの id>/` に複製する (上の「停止」)。片付けは、レビューのセッションのアーカイブ (ツール `archive_session`。ツールの説明では、アーカイブは既定でセッションの worktree も片付ける)・アプリが作ったブランチの削除。アプリが既存の worktree を再利用したとき (Q2 の (3)) は、アーカイブで、以前から残していた worktree とその `tmp/` のファイルが消えるおそれがある。worktree とブランチの削除は、人間に確認してから行うか、案内だけにするかを、この単位で決めて確認する (削除は元に戻せないため)。

### U6. 版と README を更新する

- `review-triage/.claude-plugin/plugin.json` の `description` (skill の数) と `version` (minor を上げる)、`review-triage/README.md` の「収録スキル」の表。

### U7. 通し確認

- 始める前に、回数・費用・手順を人間に示して許可を得る。
- メインのセッションは、worktree ではなくメインの作業ツリーで動かす必要がある (Q2)。メインの作業ツリーをほかのセッションが使っているときは、そのセッションの作業が一段落するまで待機するか、別の clone で行うかを人間に確認する。
- 小さな変更のあるブランチで `review-rally` を起動し、少なくとも 2 回のレビュー (2 回目は会話を消した後) と、収束 (S3) か停止までを通す。
- 確認すること: Q2 のディレクトリで依頼文と結果を書けるか (`.claude/worktrees/` を無視しているのがどのファイルか)、レビューの worktree を HEAD に合わせられるか、記録の `notes` の行、片付けの後にセッションと worktree が残っていないか、アーカイブで worktree とブランチがどう片付けられるか (U5 の決め方に使う)。

## 後に回すもの

- `--resume`・`--end`・`--full-review` (D4)。
- レビューのセッションの自己申告による「レビュースキルを Skill ツールで呼び出したか」「拒否されたツールの呼び出しの件数」の記録 (D6)。
- 経路ごとの収束の比べ方。記録がたまってから決める。

## 後始末の所有

- push・PR の作成 (本文に `Closes #151`)・Issue へのコメントは、人間の指示を受けてから行う。
- コミットは動機ごとに分ける。U1 (リファクタリング) と U2〜U6 (機能の追加) は別のコミットにする。
- 作業は、このリポジトリの別の worktree (`.claude/worktrees/` の下) で行う。メインの作業ツリーでは、別のセッションが #87 の作業をしているため。
