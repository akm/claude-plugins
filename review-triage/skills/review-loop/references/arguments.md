# 引数の様式

**このファイルが `review-loop` の引数と、周回の条件の決め方の正本。** 設定側のキーと既定値は [project-config.md](../../review-triage/references/project-config.md) の「`loop`」「`fix`」「`review_loop`」が正本 — ここでは言い直さない。

## 様式

```
review-loop [--model <指定>] [--effort <値>] [--review <スキル名>] [--review-args "<引数>"]
            [--max <回数>] [--structure-rounds <回数>] [--threshold <N>] [--stage <段>[=<値>]]...
            [--wait-minutes <分>] [--worker-wait-minutes <分>]
review-loop --resume [<置き場>] [--max <回数>]
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

各キーの意味の正本は [project-config.md](../../review-triage/references/project-config.md) の各節。`--model` はワーカーの `--model` にそのまま渡す指定、`--effort` はワーカーの `--effort` で、どちらも周回の条件として `loop.yaml` に残る (語の区別は下の「モデルと effort を指す語」)。

- **`--resume [<置き場>]`**: 止まった (または前のセッションが報告せずに終わった) 周回を続ける。置き場は周回の置き場のパス (絶対パスか、リポジトリのルートからの相対パス)。省けば、現在のブランチの `ended` でない周回 (複数あれば id の新しいもの。探し方は [round.md](round.md) の「開始の前提」の 4 と同じ)。
- **`--end [<置き場>]`**: 周回を終える。置き場の省略は `--resume` と同じ。

設定だけで決めるもの (引数を持たない): `review_loop.dir` (周回の置き場の親)・`review_loop.worker_idle_minutes`・`review_loop.worker_stale_seconds`・`review_loop.review_timeout_minutes`・`review_loop.permission_mode`・`review_loop.allowed_tools`。

**`--threshold` と `--stage` は周回の条件ではなく、`review-triage-fix` にそのまま渡す。** 扱いは `review-triage-loop` と同じで、正本は [review-triage-loop の arguments.md](../../review-triage-loop/references/arguments.md) の該当の段落 — 周回は開始前の報告に書くために同じ規則で値を決めて検査し、`review-triage-fix` を呼ぶ (F1) たびに渡す。

**`--resume` で受け付けるのは `--max` だけ。** ほかの条件は `loop.yaml` から復元する — 再開のたびに条件が変わると、記録の回ごとの違いが条件の違いによるものか収束によるものかを読み解けなくなる。条件を変えたいときは、`--end` で終えてから新しい周回を始める。`--max` は起動ごとの上限 (J5 は起動ごとに 0 から数える) なので、再開のたびに決めてよい。省略時は `loop.yaml` の `loop.max_rounds`。

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
| `allowed_tools` | 文字列の配列 |
| `dir` | 空でない文字列。リポジトリのルートからの相対パスとして解決する |

**エラーと警告には、その値が引数と設定のどちらから来たかを書く。** 直す先が違う。

## モデルと effort を指す語

この周回には、モデルとそれぞれ別の effort が 2 つずつ現れる。**語を混ぜない。** モデルの語 (指定・実効モデル) の定義の正本は [review-invocation.md](../../review-triage-loop/references/review-invocation.md) の「実効モデル」で、このスキルもその 2 語だけを使う。

| 語 | 何か | 決めるもの | 残る場所 |
| --- | --- | --- | --- |
| ワーカーのモデルの指定 | `claude -p --model` に渡す綴り (`opus` のような別名か、版を含む名前) | 人間 (`--model` か `loop.review_model`) | `loop.yaml` の `worker.model`・`worker.yaml` の `model`・依頼文の `model` と識別子・完了の印の `model.specified`・記録の `notes` の `worker_model` |
| 実効モデル | レビュアの実行が実際に動いたモデルの名前 (モデル ID から `claude-` を除いた記録の表記) | ワーカーがログから読む | 完了の印の `model.effective`・記録の `model` と `notes` の `(実効: …)` |
| ワーカーの effort | `claude -p --effort` に渡す、レビュアの実行 (セッション) の effort | 人間 (`--effort` か `review_loop.worker_effort`) | `loop.yaml` の `worker.effort`・`worker.yaml` の `effort`・完了の印の `effort`・記録の `notes` の `worker_effort` |
| レビュースキルの effort | レビュースキル (`code-review`) に渡す effort | `--review-args` か `loop.review_args` (無ければ既定。正本は [review-invocation.md](../../review-triage-loop/references/review-invocation.md) の「effort の既定」) | 依頼文の `effort`・結果と記録の `level` |

**ワーカーの effort は実行時の値を確かめられない** — `claude -p` のログに effort は出ないので、残るのはワーカーに渡した値である。
