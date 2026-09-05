# 引数の様式

**このファイルが `review-triage-loop` の引数の正本。** 設定側のキーと既定値は [project-config.md](../../review-triage/references/project-config.md) の「`loop`」が正本 — ここでは言い直さない。

## 様式

```
review-triage-loop [--max <回数>] [--review <スキル名>] [--review-args "<引数>"]
```

| 引数 | 対応する設定のキー | 例 |
| --- | --- | --- |
| `--max` | `max_rounds` | `--max 3` |
| `--review` | `review_skill` | `--review code-review` |
| `--review-args` | `review_args` | `--review-args "high"` |

## 設定と引数の優先順位

**引数が設定より優先する。** 設定はリポジトリごとの既定で、引数はその回だけの上書き。

決定の順に見る。

1. 引数にあればその値
2. 無ければ設定の `loop` の値
3. どちらにも無ければ、キーごとの既定 ([project-config.md](../../review-triage/references/project-config.md) の「`loop`」の表)
4. `review_skill` だけは既定が無いので、**人間に尋ねる** (理由は同じ表の下の説明)

**設定に書いてあれば尋ねない** — リポジトリごとに決めるのが本来の置き場だからである。尋ねるのは、設定にも引数にも無いときだけ。

## 値の検査

- `--max` は 1 以上の整数。0 以下や整数でない値は、周回を始めずにエラーとして報告する。
- `--review` は `code-review` か `ce-code-review`。それ以外の値は、対応する起動の経路が無いので ([review-invocation.md](review-invocation.md))、周回を始めずにエラーとして報告する。
- `--review-args` の中身は検査しない。レビュースキルにそのまま渡し、解釈はそちらに委ねる。

**エラーは周回を始める前に報告する。** 1 周目を走らせてから引数の誤りに気づくと、レビューの実行が無駄になる。
