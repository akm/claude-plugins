---
name: review-loop
description: レビューを端末のワーカー (人間が起動し、依頼文ごとに claude -p を人間が決めたモデルと effort で走らせるスクリプト) に任せ、トリアージと修正をこのセッションで行う周回を、止まるまで回す。受け渡しは周回の置き場のファイルだけで、完了の印をバックグラウンドで待つ。「レビューをワーカーに任せて回して」「別プロセスでレビューして収束まで回して」「review-loop を実行して」のような依頼で使う。引数でワーカーのモデル (--model) と effort (--effort)・レビュースキルとそのオプション・上限・収束の後に全量の回を行うか (--full-review)・全量の起点にする派生元のブランチ (--base) を指定でき、--resume で止まった周回を続け (--resume --full-review なら次の回を全量にする)、--end で周回を終える。
---

# review-loop: レビューを端末のワーカーに任せる周回

レビューは、人間が端末で起動するワーカー (スクリプト `review-triage/scripts/review-loop-worker.sh`) が行う。ワーカーは依頼文ごとに `claude -p` を、人間が決めたモデルと effort で走らせる。**このセッション (作業側) は、依頼文を書き、完了の印を待ち、[review-triage](../review-triage/SKILL.md) と [review-triage-fix](../review-triage-fix/SKILL.md) を呼ぶ。** 成果物は周回の結果の報告で、判断は `review-triage`、修正は `review-triage-fix` が持つ。

同じセッションの sub-agent でレビューする周回 ([review-triage-loop](../review-triage-loop/SKILL.md)) との違いは、レビューを走らせるモデルとセッションの effort を人間が選べることと、レビュアが回ごとに新しいプロセスになること。どちらの経路で回したかは記録の `notes` の 1 行に残り、後から収束を比べられる。

## 正本の宣言

**周回の順序・分岐・止まる条件・報告は、`review-triage-loop` の [loop-flow.md](../review-triage-loop/references/loop-flow.md) と [reporting.md](../review-triage-loop/references/reporting.md) が正本。** このスキルは `review-triage-loop` を呼ばず、同じ図に従って自分で `review-triage` と `review-triage-fix` を呼ぶ。差し替えるのは G0 と L1 だけで、停止ノードを 3 つ足す。散文で遷移を言い直さない。

| 流用元 | 使うもの | 使わないもの (このスキルの正本) |
| --- | --- | --- |
| [loop-flow.md](../review-triage-loop/references/loop-flow.md) の図と決定表 | G2・G3・L2・J2・J4・J5・J7・J8・J9・F1・S2〜S6 のノードと行 | G0 → RG0、L1 → RL1 ([round.md](references/round.md))。追加の停止 RA1〜RA3 と、差し替えた部分の図 ([stops.md](references/stops.md)) |
| [reporting.md](../review-triage-loop/references/reporting.md) | 必ず出すもの 6 項目 (止まった理由に RA1〜RA3 を含める) | この周回で足す項目 ([stops.md](references/stops.md) の「停止の報告に足すもの」) |
| [review-invocation.md](../review-triage-loop/references/review-invocation.md) | 「記録のキーの出所」の表 (読み替え方は [round.md](references/round.md) の「L2 で `review-triage` に渡すもの」)・「effort の既定」 | 「G0 での解決」(ワーカーのモデルは人間が決める)・「範囲」(基点は `review-request` の規則。[round.md](references/round.md) の RL1 の手順 a) |
| [arguments.md (review-triage-loop)](../review-triage-loop/references/arguments.md) | 優先順位と、`loop`・`fix` のキーの値の検査 | このスキルの引数の様式 ([arguments.md](references/arguments.md)) |

周回の置き場のファイルの様式の正本は [loop-files.md](references/loop-files.md)、ワーカーの振る舞いの正本は [worker.md](references/worker.md)。

## 同梱のスクリプト

プラグインの展開先にある。**人間への案内と Bash の呼び出しには、次の絶対パスをそのまま使う** (references の文書が「SKILL.md の「同梱のスクリプト」」と書くのはこのパス)。

- 待機スクリプト: `${CLAUDE_PLUGIN_ROOT}/scripts/review-loop-wait.sh`
- ワーカーのスクリプト: `${CLAUDE_PLUGIN_ROOT}/scripts/review-loop-worker.sh`

## 前提知識

- **周回は必ず止まる。** 止まる条件は `review-triage-loop` と同じ (上限・収束・選択待ち・進まない・構造の見直し) に、RA1〜RA3 を足したもの。
- **停止と終了は別。** 停止 (S2〜S6・RA1〜RA3) は人間の判断を待つ状態で、判断の後に `--resume` で続けられる (停止のときに書き換えるものとワーカーの扱いの正本は [stops.md](references/stops.md) の「停止のときに書き換えるもの」)。周回を終えるのは人間が `--end` を打ったときだけ。
- **ワーカーのモデルと effort は人間が決める。** このスキルは推測せず、決まらなければ尋ねる。ワーカーを起動するのも人間で、このスキルは起動コマンドを案内する ([guide-template.md](references/guide-template.md))。
- **受け渡しは周回の置き場のファイルだけ。** セッション間のメッセージは使わない。
- **同時に動くのは、作業側かレビュアの実行 (ワーカーが起動する `claude -p` の 1 回) のどちらか一方。** レビュアの実行は作業側の作業ツリーでは動かない。ワーカーは依頼文ごとに一時ディレクトリ (回の作業場所。以下「作業場所」) を作り、その中の使い捨ての作業ツリー (作業側のリポジトリの複製) でレビュアの実行を行い、回の終わりに作業場所を消す。ただしワーカーは、依頼文を受け取ったときと、レビュアの実行が終わった後に、作業側の HEAD と作業ツリーが依頼文のとおりかを確かめ、違えばその回を `failed` にする。そのため、レビューの間は作業側も人間も作業ツリーを変えない。作業場所と複製の作り方と消し方、この確認の正本は [worker.md](references/worker.md) の「回の処理」。
- **周回の間に履歴を書き換えない** (reset・rebase・squash)。増分の基点 (直前の回の `head`) が履歴から外れると、依頼文を書けずに止まる (RA3)。
- **待機の通知は人間の入力ではない。** 通知を人間の答え (S2 の回答など) として扱わない。

## 手順

### 開始 (`/review-loop`)

1. **条件を決める** (RG0): 引数と設定から決め、値を検査する ([arguments.md](references/arguments.md))。ワーカーのモデルと effort、レビュースキルが決まらなければ人間に尋ねる。
2. **開始の前提を確かめる** ([round.md](references/round.md) の「開始の前提」)。
3. **置き場と `loop.yaml` を作る** ([round.md](references/round.md) の「置き場を作る」)。
4. **決まった条件を報告する** (書くものは [round.md](references/round.md) の決定表の RG0)。**どの条件で回るかを、回り始める前に人間が知っている状態にする。**
5. **周回を回す**: G2 から [loop-flow.md](../review-triage-loop/references/loop-flow.md) の図に従う。L1 に来たら RL1 ([round.md](references/round.md))。回 1 の最初の依頼文を書いたら、ワーカーの起動を案内し ([guide-template.md](references/guide-template.md))、待機を起動して**ターンを終える** ([reentry.md](references/reentry.md) の「待機」)。

### 再入 (待機の通知・`--resume`)

**待機の通知と `--resume` は、同じ 1 つの入口 ([reentry.md](references/reentry.md) の「再入の手順」) に入る。** 通知の `description` に周回 id・回・識別子が書いてあるので、会話の文脈が無くても入口に戻れる。

- `--resume [<置き場>]` は、周回を探し (探し方と、受け付ける引数 `--max`・`--full-review` の扱いは [arguments.md](references/arguments.md))、条件を `loop.yaml` から読んでから入口に入る (レビュアの実行のサンドボックスで書き込みを許す場所と接続を許すドメインだけは、入口の手順 1 で設定から読み直す)。この起動で数える回数は 0 から始める。
- 取り込んだ回は、L2 で Skill ツールで `review-triage` を呼んで渡す (指摘が 0 件の回も呼ぶ。呼ぶスキルの規則は [round.md](references/round.md) の「呼ぶスキル」、渡すものは「L2 で `review-triage` に渡すもの」)。その後は図のとおり J2 に進む。
- F1 では Skill ツールで `review-triage-fix` を呼び、`loop.yaml` の `loop.threshold` を `--threshold` に、`loop.stages` の各要素を `--stage` に渡す。

### 停止

図に従って停止ノード (S2〜S6・RA1〜RA3) に到達したら、[stops.md](references/stops.md) の「停止のときに書き換えるもの」のとおり `loop.yaml` を書き換えてから報告する。報告の形は [reporting.md](../review-triage-loop/references/reporting.md)、停止ノードごとに足すものは [loop-flow.md](../review-triage-loop/references/loop-flow.md) の決定表 (S2〜S6) と [stops.md](references/stops.md) の決定表 (RA1〜RA3)、この周回で足すものは [stops.md](references/stops.md) の「停止の報告に足すもの」。

### 終了 (`--end`)

1. **周回を探す** (`--resume` と同じ。[arguments.md](references/arguments.md))。`ended` なら報告して終わる。
2. **印の無い依頼文があれば、人間に「印を待つ / 捨てる」を尋ねる** (blocking question tool があればそれで、無ければ番号付きの選択肢で)。待つか捨てるかで費用と記録が変わるので、スキルが決めない。
   - **待つ**: 待機を起動してターンを終える。`description` は「review-loop <周回 id> (<識別子>): --end の前に完了の印を待つ (0 = 現れた / 124 = 期限切れ / それ以外 = 中断)。通知を受けたら review-loop の終了の手順 3 へ」。通知を受けたら、終了コードと事象に関わらず、結果を取り込まずに 3 に進み、報告に結果ファイルのパス (あれば) を書く (取り込むなら、人間がそのパスを `review-triage` に渡す)。
   - **捨てる**: そのまま 3 に進む。ワーカーは、レビュー中ならその回を終えて (置き場に `end` が現れたので `failed` の印を書いて) から、まだ依頼文を受け取っていなければすぐに、一覧を出力して終わる。
3. **`end` を書く** (理由を 1 行。一時名から改名する)。`end` が既にあれば (人間が直接置いた) 書かない。
4. **`loop.yaml` を `state: ended`・`stop_reason: "end: <理由>"` にする。** 人間が `end` を直接置いていたときの理由は「end を外部で置かれた」。
5. **報告する**: 周回の id と置き場、ワーカーが一覧を出力して終わること (ワーカーが動いていなければ、次に起動しても `end` があるので起動時の確認で止まること。止まるまでに行う後始末の正本は [worker.md](references/worker.md) の「起動時の確認」の 2)、置き場は消さずに残すこと。

## 原則

- **このスキルは判断も修正もしない。** `review-request`・`review-triage`・`review-triage-fix` を、回ごとに Skill ツールで呼ぶだけ ([round.md](references/round.md) の「呼ぶスキル」)。
- **待機を起動したターンでは、それ以外のツールを呼ばない。** 通知で次のターンが始まる (理由の正本は [reentry.md](references/reentry.md) の「待機」)。
- **周回が条件を勝手に変えない。** 条件は `loop.yaml` にある (再開のときの規則の正本は [arguments.md](references/arguments.md) の「様式」)。
- **置き場のファイルは、書く側だけが書く** ([loop-files.md](references/loop-files.md) の「ファイルの一覧」)。作業側はワーカーのファイル (`worker.yaml`・完了の印・ログ) にも、レビュアの実行の結果にも書き込まない。
- **置き場を消さない。** 後で経路どうしの収束を比べる材料になる。
- **人間に返した状態を越えて進まない。** 選択待ち (S2) と停止 (RA1〜RA3) は、人間の判断を求めて止まった結果である。

## このスキルが検出しないもの

- **レビュアの実行の中身が正しいか** — 確かめない。何を確かめるかの正本は [worker.md](references/worker.md) の「このワーカーが検出しないもの」。
- **レビュアの実行が、複製と作業場所の外に残したもののうち、ワーカーが検出しないもの** — サンドボックスの一時ディレクトリ (`/private/tmp/claude-<利用者の番号>`) への書き込み・ホームと作業側の外へのツールによる書き込み・利用者の設定が接続を許すホストへの送信など。一覧の正本は [worker.md](references/worker.md) の「このワーカーが検出しないもの」。
- **ワーカーの effort が実際に効いたか** — `claude -p` のログに effort は記録されないので、ワーカーに渡した値を記録に残すだけ。
- **収束したことが「欠陥が無い」ことを意味するか** — 意味しない。そのレビュースキル・そのモデル・その effort・その範囲で指摘が出なかったということである。
