# 引数の様式

**このファイルが `review-triage-fix` の引数の正本。** 設定側のキーと既定値は [project-config.md](../../review-triage/references/project-config.md) の「`fix`」が正本 — ここでは言い直さない。

## 様式

```
review-triage-fix [<記録 YAML のパス>] [--threshold <N>]
```

| 引数 | 対応する設定のキー | 例 |
| --- | --- | --- |
| `<記録 YAML のパス>` | (無い。省略時は現在のブランチの記録 — 解決の規則は [SKILL.md](../SKILL.md) の手順 1) | `tmp/review-triages/feat-foo.yaml` |
| `--threshold` | `threshold_rounds` | `--threshold 3` |

`--threshold <N>` は回数の閾値 N — 記録の回番号がこれを越えた回 (回 N+1 以降) で、段 1 (調査) の後に人間に立案者を尋ねる。閾値の意味と数え方の正本は [project-config.md](../../review-triage/references/project-config.md) の「`fix`」、尋ね方の正本は [SKILL.md](../SKILL.md) の手順 4。

## 設定と引数の優先順位

**引数が設定より優先する。** 設定はリポジトリごとの既定で、引数はその回だけの上書き。

決定の順に見る。

1. 引数にあればその値
2. 無ければ設定の `fix` の値 (「未設定」の定義の正本は [project-config.md](../../review-triage/references/project-config.md) の「「未設定」の定義」)
3. どちらにも無ければ、キーごとの既定 ([project-config.md](../../review-triage/references/project-config.md) の「`fix`」の表)

**閾値は既定で決まるので、人間に尋ねることはない。** 尋ねるのは閾値の値ではなく、閾値を越えた回の立案者 (正本は [SKILL.md](../SKILL.md) の手順 4) である。

## 値の検査

**検査するのは、引数か設定かを問わず、決定の結果として採る値。** 引数だけを検査すると、設定に書いた誤記は検査されないまま手順に入る。

- `threshold_rounds` は 1 以上の整数。0 以下や整数でない値は、手順を始めずにエラーとして報告する。

**エラーには、その値が引数と設定のどちらから来たかを書く。** 直す先が違う — 引数ならその場で言い直せるが、設定なら `config.json` を直すことになる。

**エラーは手順を始める前に報告する。** 段 1 (調査) を走らせてから値の誤りに気づくと、調査の実行が無駄になる。

## `review-triage-loop` から呼ばれるとき

`review-triage-loop` は `--threshold` を周回の条件として使わず、`review-triage-fix` にそのまま渡す (正本は [review-triage-loop の arguments.md](../../review-triage-loop/references/arguments.md))。周回から呼ばれても単独で走らせても、値の決定と検査はこのファイルの規則で行う。
