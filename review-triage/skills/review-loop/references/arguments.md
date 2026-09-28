# 引数の様式

**このファイルが `review-loop` の引数と、周回の条件の決め方の正本。** 設定側のキーと既定値は [project-config.md](../../review-triage/references/project-config.md) の「`loop`」「`fix`」「`review_loop`」が正本 — ここでは言い直さない。

## 様式

```
review-loop [--model <指定>] [--effort <値>] [--review <スキル名>] [--review-args "<引数>"]
            [--max <回数>] [--structure-rounds <回数>] [--threshold <N>] [--stage <段>[=<値>]]...
            [--wait-minutes <分>] [--worker-wait-minutes <分>] [--full-review] [--base <ブランチ>]
review-loop --resume [<置き場>] [--max <回数>] [--full-review] [--base <ブランチ>]
review-loop --end [<置き場>]
```

| 引数 | 対応する設定のキー | 例 |
| --- | --- | --- |
| `--model` | `loop.review_model` | `--model opus` |
| `--effort` | `review_loop.worker_effort` | `--effort xhigh` |
| `--review` | `loop.review_skill` | `--review code-review` |
| `--review-args` | `loop.review_args` | `--review-args "high"` |
| `--max` | `loop.max_rounds` | `--max 3` |
| `--structure-rounds` | `loop.structure_rounds` | `--structure-rounds 0` |
| `--threshold` | `fix.threshold_rounds` | `--threshold 3` |
| `--stage` | `fix.stages.<段>` | `--stage investigate=sonnet:high` |
| `--wait-minutes` | `review_loop.wait_minutes` | `--wait-minutes 5` |
| `--worker-wait-minutes` | `review_loop.worker_wait_minutes` | `--worker-wait-minutes 5` |
| `--full-review` | 無し (`loop.yaml` の `review.full_review` に書く) | `--full-review` |
| `--base` | 無し (`loop.yaml` の `review.base` に書く) | `--base feat/a` |

各キーの意味の正本は [project-config.md](../../review-triage/references/project-config.md) の各節。`--model` はワーカーの `--model` にそのまま渡す指定、`--effort` はワーカーの `--effort` で、どちらも周回の条件として `loop.yaml` に残る (語の区別は下の「モデルと effort を指す語」)。

- **`--resume [<置き場>]`**: 止まった (または前のセッションが報告せずに終わった) 周回を続ける。置き場は周回の置き場のパス (絶対パスか、リポジトリのルートからの相対パス)。省けば、現在のブランチの `ended` でない周回 (複数あれば id の新しいもの。探し方は [round.md](round.md) の「開始の前提」の 4 と同じ)。
- **`--end [<置き場>]`**: 周回を終える。置き場の省略は `--resume` と同じ。

設定だけで決めるもの (引数を持たない): `review_loop.dir` (周回の置き場の親)・`review_loop.worker_idle_minutes`・`review_loop.worker_stale_seconds`・`review_loop.review_timeout_minutes`・`review_loop.permission_mode`・`review_loop.allowed_tools`・`review_loop.sandbox_allow_write` (サンドボックスの中の Bash に書き込みを許す場所)・`review_loop.sandbox_allowed_domains` (同じく接続を許すドメイン)。

**`--full-review` と `--base` は設定のキーを持たず、開始時の値を `loop.yaml` の `review.full_review` (真偽値)・`review.base` (ブランチ名) に書く。** どちらもブランチや周回ごとに変わる値で、前例 (`--stage` の値を `loop.stages` に書く) に合わせる。

- **`--full-review`**: 収束後の全量レビューを周回の中で行う。増分の回が収束し、要否の規則 (正本は [review-request.md](../../review-triage/references/review-request.md) の「収束後の全量レビューと、その要否」) で要るときに、止まらずに全量の回を行う。すでに収束した記録で始めたときは、要否に関わらず最初の回を全量にする。どのノードで分かれるかの正本は [stops.md](stops.md) の RJ0・RJ1。
- **`--base <ブランチ>`**: 全量の起点を求める派生元のブランチ。全量の回で `review-request` に `--base` として渡す (渡す回の正本は [round.md](round.md) の RL1 の手順 a の 4。起点の求め方の正本は [review-request の SKILL.md](../../review-request/SKILL.md) の手順 2)。**省いたら、開始時に `origin/HEAD` が指すブランチ名を `review-request` の手順 2 と同じ求め方で解決して書き、解決できなければ周回を始めずに人間に尋ねる** — 空のまま書いて毎回 `review-request` の既定に任せると、開始の報告にブランチ名が出ず、`origin/HEAD` が無ければ回の途中で尋ねることになる。**そのため `origin/HEAD` の無いリポジトリでは、全量の回を行わない周回 (記録に回があり、`--full-review` を付けない周回) でも `--base` が要る** (0.14.0 では要らなかった)。

**`review_loop.permission_mode` が未設定なら、デフォルトの `auto` を `loop.yaml` の `worker.permission_mode` に書く** (デフォルト値の正本は [project-config.md](../../review-triage/references/project-config.md) の「`review_loop`」)。周回の権限モードは `loop.yaml` に書いた値で決まり、ワーカーのデフォルトには任せない — 案内の起動コマンドはこの値を常に渡し、各回の突き合わせは完了の印の権限モードの指定をこの値と比べる。

**`--threshold` と `--stage` は周回の条件ではなく、`review-triage-fix` にそのまま渡す。** 扱いは `review-triage-loop` と同じで、正本は [review-triage-loop の arguments.md](../../review-triage-loop/references/arguments.md) の該当の段落 — 周回は開始前の報告に書くために同じ規則で値を決めて検査し、`review-triage-fix` を呼ぶ (F1) たびに渡す。

**`--resume` で受け付けるのは `--max` と `--full-review` だけ。** 例外は `--base` で、`loop.yaml` に `review.base` が無いとき (下の「0.14.0 以前に始めた周回」) だけ受け付ける。ほかの引数と、`review.base` があるときの `--base` は、引数の誤りとして再開せずにエラーにする。ほかの条件は `loop.yaml` から復元する — 再開のたびに条件が変わると、記録の回ごとの違いが条件の違いによるものか収束によるものかを読み解けなくなる。条件を変えたいときは、`--end` で終えてから新しい周回を始める。`--max` は起動ごとの上限 (J5 は起動ごとに 0 から数える) なので、再開のたびに決めてよい。省略時は `loop.yaml` の `loop.max_rounds`。

**`--resume --full-review` は、その起動で次に書く依頼文を全量にする。** 修正が残っていれば、それを済ませてから全量にする。**ただし、待っている回 (取り込む完了の印か、印の無い依頼文の回) の依頼文の scope が `full` なら、印を書かない** — その回が全量の回なので、印を書くと、その回の採択が 0 件でも同じ HEAD の全量の回がもう 1 回続く。要否に関わらず全量にする明示の指定で、印は `loop.yaml` の実行時のキー `full_review_next` に書く (真にする所は [reentry.md](reentry.md) の「再入の手順」の 1 と [stops.md](stops.md) の RJ0・RJ1、偽に戻す所は [round.md](round.md) の RL1 の手順 a の 7 と [stops.md](stops.md) の「停止のときに書き換えるもの」。一覧は [loop-files.md](loop-files.md) の「`loop.yaml`」)。**周回の条件 `review.full_review` は変えない。** 範囲を 1 回変えるだけで、範囲は記録の回ごとに `scope` として残るので、上の「記録の回ごとの違いを読み解けなくなる」には当たらない。`--max` と同じく、次の起動には持ち越さない。

**書き込みを許す場所と接続を許すドメイン (`review_loop.sandbox_allow_write`・`review_loop.sandbox_allowed_domains`) は周回の条件ではなく、`--resume` のたびに設定から読み直して、`loop.yaml` の `worker.sandbox_allow_write`・`worker.sandbox_allowed_domains` に書く。** この 2 つは、ワーカーを動かすマシンごとに変わる値 (環境の値) で、周回の結果を比べるときにそろえる値ではない。開始時の値のままにすると、書き込みを許す場所が足りずに RA1 で止まった周回を、終えずに直して続けられない。読み直すときの値の誤りは、開始時と同じく未設定 (空の一覧) として扱い、警告を `--resume` の開始の報告に書く。**権限モードは周回の条件のままで、`--resume` では読み直さない。**

**0.13.0 で始めた周回の `loop.yaml` には、この 2 つのキーが無い。** 無ければ空の一覧として扱う (`--resume` で読み直した後は書かれている)。権限モードは `loop.yaml` の値のまま続く。

**0.14.0 以前に始めた周回の `loop.yaml` には、`review.full_review` と `review.base` が無い。** `review.full_review` が無ければ偽とする (その周回は `--full-review` の無い条件で始めたので、条件は変わらない)。`review.base` が無ければ、`--resume` の開始時に、引数 `--base` があればその値を (値の検査は開始時の `--base` と同じ)、無ければ上の `--base` を省いたときと同じ求め方で解決したブランチ名を書く。**解決できなければ再開せず、`--resume --base <ブランチ>` で再開するよう案内する** — `review.base` はまだ条件として決まっていないので、ここで決めても「再開のたびに条件を変えない」には当たらない。

## 設定と引数の優先順位

決定の順に見る (`review-triage-loop` と同じ規則。正本は [review-triage-loop の arguments.md](../../review-triage-loop/references/arguments.md) の「設定と引数の優先順位」)。

1. 引数にあればその値
2. 無ければ設定の値 (上の表の対応するキー。「未設定」の定義の正本は [project-config.md](../../review-triage/references/project-config.md) の「「未設定」の定義」)
3. どちらにも無ければ、キーごとの既定 ([project-config.md](../../review-triage/references/project-config.md) の各節の表)
4. 既定で決まらないものは**人間に尋ねる** — ワーカーのモデルの指定 (`--model`) と effort (`--effort`)、レビュースキル (`--review`)

**ワーカーのモデルと effort は推測しない。** `review-triage-loop` の「G0 での解決」(指定が未設定なら呼び出し元の 1 つ前の世代を既定にする) は使わない — このスキルではワーカーのモデルを決めるのは人間で ([SKILL.md](../SKILL.md) の前提知識)、既定を持たない。

## 値の検査

**検査するのは、引数か設定かを問わず、決定の結果として採る値。** 誤りの扱いは出所で分ける。

- **引数の誤りは、周回を始めずにエラーとして報告する。** 引数はその場で言い直せる。
- **`loop`・`fix` の設定の誤りも、周回を始めずにエラーとして報告する** (`review-triage-loop` と同じ規則)。
- **`review_loop` の設定の誤りは、そのキーを未設定として扱い (既定があれば既定、無ければ人間に尋ねる)、警告を開始の報告に書く。** 失われるのは利用者が書いた数行で、既定で続けても周回の記録は壊れない (失敗時の態度の正本は [loop-files.md](loop-files.md) の「ファイルの種類ごとの態度」)。

| 値 | 条件 |
| --- | --- |
| ワーカーのモデルの指定 | 空でない文字列。綴りは検査しない (`claude --model` が解釈する) |
| ワーカーの effort | `low` / `medium` / `high` / `xhigh` / `max` のいずれか |
| `review_skill`・`review_args`・`max_rounds`・`structure_rounds` | [review-triage-loop の arguments.md](../../review-triage-loop/references/arguments.md) の「値の検査」と同じ条件 |
| `threshold_rounds`・`stages` | [review-triage-fix の arguments.md](../../review-triage-fix/references/arguments.md) の「値の検査」と同じ条件 |
| `wait_minutes`・`worker_wait_minutes`・`worker_idle_minutes`・`review_timeout_minutes` | 正の数 (小数を許す) |
| `worker_stale_seconds` | 10 以上の整数 (ワーカーは 5 秒おきに更新時刻を進めるので、それより短いと動いているワーカーを停滞と読む) |
| `permission_mode` | `bypassPermissions` でない (ワーカーが受け付けない。理由の正本は [worker.md](worker.md) の「レビュアの実行の権限」) |
| `allowed_tools`・`sandbox_allow_write`・`sandbox_allowed_domains` | 文字列の配列。`sandbox_allow_write` の各値が書き込みを許せる場所かは、ワーカーが起動時に確かめる (正本は [worker.md](worker.md) の「起動時の確認」の 12) |
| `dir` | 空でない文字列。リポジトリのルートからの相対パスとして解決する |
| `--base` のブランチ | `git rev-parse --verify --quiet "<ブランチ>^{commit}"` でコミットに解決できる (`review-request` の手順 2 と同じ検査) |

**エラーと警告には、その値が引数と設定のどちらから来たかを書く。** 直す先が違う。

## モデルと effort を指す語

この周回には、モデルとそれぞれ別の effort が 2 つずつ現れる。**語を混ぜない。** モデルの語 (指定・実効モデル) の定義の正本は [review-invocation.md](../../review-triage-loop/references/review-invocation.md) の「実効モデル」で、このスキルもその 2 語だけを使う。

| 語 | 何か | 決めるもの | 残る場所 |
| --- | --- | --- | --- |
| ワーカーのモデルの指定 | `claude -p --model` に渡す綴り (`opus` のような別名か、版を含む名前) | 人間 (`--model` か `loop.review_model`) | `loop.yaml` の `worker.model`・`worker.yaml` の `model`・依頼文の `model` と識別子・完了の印の `model.specified`・記録の `notes` の `worker_model` |
| 実効モデル | レビュアの実行が実際に動いたモデルの名前 (モデル ID から `claude-` を除いた記録の表記) | ワーカーがログから読む | 完了の印の `model.effective`・記録の `model` と `notes` の `(実効: …)` |
| ワーカーの effort | `claude -p --effort` に渡す、レビュアの実行 (セッション) の effort | 人間 (`--effort` か `review_loop.worker_effort`) | `loop.yaml` の `worker.effort`・`worker.yaml` の `effort`・完了の印の `effort`・記録の `notes` の `worker_effort` |
| レビュースキルの effort | レビュースキル (`code-review`) に渡す effort | `--review-args` か `loop.review_args` (無ければ既定。正本は [review-invocation.md](../../review-triage-loop/references/review-invocation.md) の「effort の既定」) | 依頼文の `effort`・結果と記録の `level` |

**ワーカーの effort は実行時の値を確かめられない** — `claude -p` のログに effort は記録されないので、残るのはワーカーに渡した値である。
