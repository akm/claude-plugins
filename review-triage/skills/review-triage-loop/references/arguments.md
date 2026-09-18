# 引数の様式

**このファイルが `review-triage-loop` の引数の正本。** 設定側のキーと既定値は [project-config.md](../../review-triage/references/project-config.md) の「`loop`」が正本 — ここでは言い直さない。

## 様式

```
review-triage-loop [--max <回数>] [--review <スキル名>] [--review-args "<引数>"] [--model <モデル>] [--threshold <N>]
```

| 引数 | 対応する設定のキー | 例 |
| --- | --- | --- |
| `--max` | `max_rounds` | `--max 3` |
| `--review` | `review_skill` | `--review code-review` |
| `--review-args` | `review_args` | `--review-args "high"` |
| `--model` | `review_model` | `--model sonnet` |
| `--threshold` | `fix.threshold_rounds` (`review-triage-fix` の設定) | `--threshold 3` |

**`--threshold <N>` は周回の条件ではなく、`review-triage-fix` にそのまま渡す。** 回数の閾値 N (記録の回番号がこれを越えた回で、`review-triage-fix` が調査の後に人間に立案者を尋ねる) の意味・決め方・検査の正本は [review-triage-fix の arguments.md](../../review-triage-fix/references/arguments.md) と [project-config.md](../../review-triage/references/project-config.md) の「`fix`」で、周回はこの値で分岐しない。周回が行うのは 2 つだけ — 開始前の報告 (決定表 G0) に書くために同じ規則で値を決めて検査すること (下の「値の検査」) と、`review-triage-fix` を呼ぶ (F1) たびにその値を渡すこと。

## 設定と引数の優先順位

**引数が設定より優先する。** 設定はリポジトリごとの既定で、引数はその回だけの上書き。

決定の順に見る。

1. 引数にあればその値
2. 無ければ設定の `loop` の値 (「未設定」の定義の正本は [project-config.md](../../review-triage/references/project-config.md) の「「未設定」の定義」。`--threshold` だけは設定の `fix` を見る — 上の段落のとおり)
3. どちらにも無ければ、キーごとの既定 ([project-config.md](../../review-triage/references/project-config.md) の「`loop`」の表。`--threshold` は「`fix`」の表)
4. 既定で決まらないものは**人間に尋ねる** — `review_skill` (既定を持たない。理由は同じ表の下の説明) と、`review_model` で呼び出し元が既定の対応表に無いとき ([review-invocation.md](review-invocation.md) の「G0 での解決」)。周回がモデルを決めない経路では尋ねない (正本は同ファイルの「G0 での解決」)

**設定で決まっていれば尋ねない** — リポジトリごとに決めるのが本来の置き場だからである。尋ねるのは、引数でも設定でも未設定 (定義は上の参照先) のときだけ。

## 値の検査

**検査するのは、引数か設定かを問わず、決定の結果として採る値。** 引数だけを検査すると、設定に書いた誤記は「設定に書いてあれば尋ねない」を通って検査されないまま周回に入る。

- `max_rounds` は 1 以上の整数。0 以下や整数でない値は、周回を始めずにエラーとして報告する。
- `review_skill` は `code-review` か `ce-code-review`。それ以外の値は、対応する起動の経路が無いので ([review-invocation.md](review-invocation.md))、周回を始めずにエラーとして報告する。
- `review_args` の中身は検査しない。レビュースキルにそのまま渡し、解釈はそちらに委ねる。
- `review_model` の値は検査しない。指定が効かなかったときの報告の条件は [review-invocation.md](review-invocation.md) の「実効モデル」が正本。
- `fix.threshold_rounds` (`--threshold`) は、[review-triage-fix の arguments.md](../../review-triage-fix/references/arguments.md) の「値の検査」と同じ条件 (1 以上の整数) で検査する。誤りは周回を始めずにエラーとして報告する — `review-triage-fix` を呼んだ回で初めて気づくと、そこまでのレビューの実行が無駄になる。

**エラーには、その値が引数と設定のどちらから来たかを書く。** 直す先が違う — 引数ならその場で言い直せるが、設定なら `config.json` を直すことになる。

**エラーは周回を始める前に報告する。** 1 周目を走らせてから値の誤りに気づくと、レビューの実行が無駄になる。
