# 引数の様式

**このファイルが `review-triage-fix` の引数の SSOT。** 設定のキーと既定値は [project-config.md](../../review-triage/references/project-config.md) の「`fix`」が SSOT — ここでは言い直さない。

## 様式

```
review-triage-fix [<記録 YAML のパス>] [--threshold <N>] [--stage <フェーズ>[=<値>]]...
```

| 引数 | 対応する設定のキー | 例 |
| --- | --- | --- |
| `<記録 YAML のパス>` | (無い。省略時は現在のブランチの記録 — 解決の規則は [SKILL.md](../SKILL.md) の手順 1) | `tmp/review-triages/feat-foo.yaml` |
| `--threshold` | `threshold_rounds` | `--threshold 3` |
| `--stage` | `stages.<フェーズ>` (`subagent` / `model` / `effort` の 3 つをまとめて) | `--stage investigate=sonnet`・`--stage plan=session`・`--stage fix=opus:high`・`--stage fix` |

`--threshold <N>` は回数の閾値 N — 記録の回番号がこれを越えた回 (N+1 回目以降) で、調査フェーズの後に人間に立案者の選択を求める。閾値の意味と数え方の SSOT は [project-config.md](../../review-triage/references/project-config.md) の「`fix`」、質問の仕方の SSOT は [SKILL.md](../SKILL.md) の手順 4。

### `--stage <フェーズ>[=<値>]` — フェーズの実行方法

フェーズ (`<フェーズ>`) ごとに、セッション内で実行するか sub-agent で実行するか、sub-agent ならそのモデルと effort を指定する。フェーズの名前は 3 つ — `investigate` (調査フェーズ)・`plan` (立案フェーズ)・`fix` (修正フェーズ)。フェーズと手順の対応の SSOT は [SKILL.md](../SKILL.md) の「手順」の冒頭。

| `<値>` | 意味 |
| --- | --- |
| `session` | そのフェーズをセッション内で実行する。設定の `stages.<フェーズ>.subagent` が `true` でも上書きする |
| `<model>[:<effort>]` | そのフェーズを sub-agent で実行する。`<model>` はモデルの指定、`:<effort>` は effort の指定 (省けば未設定)。`<model>` は空にできない — 設定の `model` を残したまま effort だけを引数で変える形は無い |
| (`=` 以降を省く) | そのフェーズを sub-agent で実行し、モデルと effort はどちらも未設定 |

- **`--stage` は、そのフェーズの 3 つのキー (`subagent` / `model` / `effort`) をまとめて上書きする。** `=` 以降を省いた形は「sub-agent で、モデルと effort は未設定」を指定したことになり、設定にそのフェーズの `model` / `effort` があっても使わない。
- **フェーズごとに 1 つ。** 同じフェーズに 2 つ以上あれば、手順を始めずにエラーとして報告する。
- 未設定のモデル・effort をどう解決するか (実効モデル・agent 定義の名前) の SSOT は [stage-subagent.md](stage-subagent.md) の「実行方法の決定」。**N+1 回目以降の立案フェーズ (`plan`) には、引数も設定も適用されない** — その回の立案フェーズは立案者の選択 (SKILL.md の手順 4) で決まる。指定があっても使わず、使わなかったことを報告に書く。

## 設定と引数の優先順位

**引数が設定より優先する。** 設定はリポジトリごとの既定で、引数はその回だけの上書き。

決定の順に見る。

1. 引数にあればその値
2. 無ければ設定の `fix` の値 (「未設定」の定義の SSOT は [project-config.md](../../review-triage/references/project-config.md) の「「未設定」の定義」)
3. どちらにも無ければ、キーごとの既定 ([project-config.md](../../review-triage/references/project-config.md) の「`fix`」の表)

**閾値もフェーズの実行方法も既定で決まるので、人間に質問することはない。** 質問するのは閾値の値でも実行方法でもなく、閾値を越えた回の立案者 (SSOT は [SKILL.md](../SKILL.md) の手順 4) である。

## 値の検査

**検査するのは、引数か設定かを問わず、決定の結果として採る値。** 引数だけを検査すると、設定に書いた誤記は検査されないまま手順に入る。

- `threshold_rounds` は 1 以上の整数。0 以下や整数でない値は、手順を始めずにエラーとして報告する。
- `--stage` の `<フェーズ>` は `investigate` / `plan` / `fix` のいずれか。
- `--stage` の `<値>` は `session` か `<model>[:<effort>]` (`<model>` は空でない)。
- effort (`--stage` の `:<effort>`、設定の `stages.<フェーズ>.effort`) は `low` / `medium` / `high` / `xhigh` / `max` のいずれか。それ以外 (例: `--stage investigate=sonnet:ultra`) は、手順を始めずにエラーとして報告する。**検査するのは表記だけ** — 実効モデルがその effort に対応しているかは検出できない (限界の SSOT は [stage-subagent.md](stage-subagent.md) の「effort と定義名の対応」)。
- 設定の `stages.<フェーズ>.subagent` は真偽値 (JSON の `true` / `false`)。文字列や空は未設定と読まず、エラーとして報告する。
- モデルの指定 (`--stage` の `<model>`、設定の `stages.<フェーズ>.model`) は、実効モデルに解決できること。解決の規則と、解決できないときに中断する規則の SSOT は [stage-subagent.md](stage-subagent.md) の「実効モデルの解決」。**解決も手順を始める前に 3 つのフェーズについて行う** — 修正フェーズの指定が解決できないことに調査フェーズ・立案フェーズを実行した後で気づくと、その実行が無駄になる。
- `subagent` が `false` に決まったフェーズ (引数 `session` を含む) の `model` / `effort` は採る値ではないので検査しない。

**エラーには、その値が引数と設定のどちらから来たかを書く。** 直す先が違う — 引数ならその場で言い直せるが、設定なら `config.json` を直すことになる。

**エラーは手順を始める前に報告する。** 調査フェーズを実行してから値の誤りに気づくと、調査の実行が無駄になる。

## `review-triage-loop` から呼ばれるとき

`review-triage-loop` は `--threshold` と `--stage` をループの条件として使わず、`review-triage-fix` にそのまま渡す (SSOT は [review-triage-loop の arguments.md](../../review-triage-loop/references/arguments.md))。ループから呼ばれても単独で実行しても、値の決定と検査はこのファイルの規則で行う。
