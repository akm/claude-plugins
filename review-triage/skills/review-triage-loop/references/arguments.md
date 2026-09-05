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
3. どちらにも無ければ、キーごとの既定 (`max_rounds` は 5、`review_args` は空)
4. `review_skill` だけは既定を持たない — **人間に尋ねる**

## `review_skill` に既定を置かない理由

どちらのスキルで走らせたかは記録の `skill` に残り、後から粒度を比較する材料になる。既定で決めると、利用者が意識しないまま片方に寄り、記録の比較の前提が崩れる。

**設定に書いてあれば尋ねない** — リポジトリごとに決めるのが本来の置き場だからである。尋ねるのは、設定にも引数にも無いときだけ。

## 値の検査

- `--max` は 1 以上の整数。0 以下や整数でない値は、周回を始めずにエラーとして報告する。
- `--review` は `code-review` か `ce-code-review`。それ以外の値は、対応する起動の経路が無いので ([review-invocation.md](review-invocation.md))、周回を始めずにエラーとして報告する。
- `--review-args` の中身は検査しない。レビュースキルにそのまま渡し、解釈はそちらに委ねる。

**エラーは周回を始める前に報告する。** 1 周目を走らせてから引数の誤りに気づくと、レビューの実行が無駄になる。
