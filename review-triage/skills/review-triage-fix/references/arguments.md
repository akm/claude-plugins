# 引数の様式

**このファイルが `review-triage-fix` の引数の正本。** 設定側のキーと既定値は [project-config.md](../../review-triage/references/project-config.md) の「`fix`」が正本 — ここでは言い直さない。

## 様式

```
review-triage-fix [<記録 YAML のパス>] [--threshold <N>] [--stage <段>[=<値>]]...
```

| 引数 | 対応する設定のキー | 例 |
| --- | --- | --- |
| `<記録 YAML のパス>` | (無い。省略時は現在のブランチの記録 — 解決の規則は [SKILL.md](../SKILL.md) の手順 1) | `tmp/review-triages/feat-foo.yaml` |
| `--threshold` | `threshold_rounds` | `--threshold 3` |
| `--stage` | `stages.<段>` (`subagent` / `model` / `effort` の 3 つをまとめて) | `--stage investigate=sonnet`・`--stage plan=session`・`--stage fix=opus:high`・`--stage fix` |

`--threshold <N>` は回数の閾値 N — 記録の回番号がこれを越えた回 (回 N+1 以降) で、段 1 (調査) の後に人間に立案者を尋ねる。閾値の意味と数え方の正本は [project-config.md](../../review-triage/references/project-config.md) の「`fix`」、尋ね方の正本は [SKILL.md](../SKILL.md) の手順 4。

### `--stage <段>[=<値>]` — 段の走らせ方

段 (`<段>`) ごとに、セッション内で走らせるか sub-agent で走らせるか、sub-agent ならそのモデルと effort を指定する。段の名前は 3 つ — `investigate` (段 1 = 調査)・`plan` (段 2 = 立案)・`fix` (段 3 = 修正)。段と手順の対応の正本は [SKILL.md](../SKILL.md) の「手順」の冒頭。

| `<値>` | 意味 |
| --- | --- |
| `session` | その段をセッション内で走らせる。設定の `stages.<段>.subagent` が `true` でも上書きする |
| `<model>[:<effort>]` | その段を sub-agent で走らせる。`<model>` はモデルの指定、`:<effort>` は effort の指定 (省けば未設定)。`<model>` は空にできない — 設定の `model` を残したまま effort だけを引数で変える形は無い |
| (`=` 以降を省く) | その段を sub-agent で走らせ、モデルと effort はどちらも未設定 |

- **`--stage` は、その段の 3 つのキー (`subagent` / `model` / `effort`) をまとめて上書きする。** `=` 以降を省いた形は「sub-agent で、モデルと effort は未設定」を指定したことになり、設定にその段の `model` / `effort` があっても使わない。
- **段ごとに 1 つ。** 同じ段に 2 つ以上あれば、手順を始めずにエラーとして報告する。
- 未設定のモデル・effort をどう解決するか (実効モデル・agent 定義の名前) の正本は [stage-subagent.md](stage-subagent.md) の「走らせ方の決定」。**回 N+1 以降の段 2 (`plan`) には、引数も設定も効かない** — その回の段 2 は立案者の選択 (SKILL.md の手順 4) で決まる。指定があっても使わず、使わなかったことを報告に書く。

## 設定と引数の優先順位

**引数が設定より優先する。** 設定はリポジトリごとの既定で、引数はその回だけの上書き。

決定の順に見る。

1. 引数にあればその値
2. 無ければ設定の `fix` の値 (「未設定」の定義の正本は [project-config.md](../../review-triage/references/project-config.md) の「「未設定」の定義」)
3. どちらにも無ければ、キーごとの既定 ([project-config.md](../../review-triage/references/project-config.md) の「`fix`」の表)

**閾値も段の走らせ方も既定で決まるので、人間に尋ねることはない。** 尋ねるのは閾値の値でも走らせ方でもなく、閾値を越えた回の立案者 (正本は [SKILL.md](../SKILL.md) の手順 4) である。

## 値の検査

**検査するのは、引数か設定かを問わず、決定の結果として採る値。** 引数だけを検査すると、設定に書いた誤記は検査されないまま手順に入る。

- `threshold_rounds` は 1 以上の整数。0 以下や整数でない値は、手順を始めずにエラーとして報告する。
- `--stage` の `<段>` は `investigate` / `plan` / `fix` のいずれか。
- `--stage` の `<値>` は `session` か `<model>[:<effort>]` (`<model>` は空でない)。
- effort (`--stage` の `:<effort>`、設定の `stages.<段>.effort`) は `low` / `medium` / `high` / `xhigh` / `max` のいずれか。それ以外 (例: `--stage investigate=sonnet:ultra`) は、手順を始めずにエラーとして報告する。**検査するのは綴りだけ** — 実効モデルがその effort に対応しているかは検出できない (限界の正本は [stage-subagent.md](stage-subagent.md) の「effort と定義名の対応」)。
- 設定の `stages.<段>.subagent` は真偽値 (JSON の `true` / `false`)。文字列や空は未設定と読まず、エラーとして報告する。
- モデルの指定 (`--stage` の `<model>`、設定の `stages.<段>.model`) は、実効モデルに解決できること。解決の規則と、解決できないときに止める規則の正本は [stage-subagent.md](stage-subagent.md) の「実効モデルの解決」。**解決も手順を始める前に 3 段分行う** — 段 3 の指定が解決できないことに段 1・2 を走らせた後で気づくと、その実行が無駄になる。
- `subagent` が `false` に決まった段 (引数 `session` を含む) の `model` / `effort` は採る値ではないので検査しない。

**エラーには、その値が引数と設定のどちらから来たかを書く。** 直す先が違う — 引数ならその場で言い直せるが、設定なら `config.json` を直すことになる。

**エラーは手順を始める前に報告する。** 段 1 (調査) を走らせてから値の誤りに気づくと、調査の実行が無駄になる。

## `review-triage-loop` から呼ばれるとき

`review-triage-loop` は `--threshold` と `--stage` を周回の条件として使わず、`review-triage-fix` にそのまま渡す (正本は [review-triage-loop の arguments.md](../../review-triage-loop/references/arguments.md))。周回から呼ばれても単独で走らせても、値の決定と検査はこのファイルの規則で行う。
