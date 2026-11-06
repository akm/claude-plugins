# 引数の様式

**このファイルが `review-rally` の引数と、ループの条件の決め方の SSOT。** 設定のキーと既定値は [project-config.md](../../review-triage/references/project-config.md) の「`loop`」「`fix`」が SSOT。このスキルは新しい設定のキーを持たない。

## 様式

```
review-rally [--model <指定>] [--effort <値>] [--review <スキル名>] [--review-args "<引数>"]
             [--max <回数>] [--structure-rounds <回数>] [--threshold <N>] [--stage <フェーズ>[=<値>]]...
             [--min-fix-necessity <must|should|could>]
             [--base <ブランチ>] [--full-first] [--full-review]
```

| 引数 | 対応する設定のキー | 例 |
| --- | --- | --- |
| `--model` | `loop.review_model` | `--model claude-opus-5-5` |
| `--effort` | 無し | `--effort high` |
| `--review` | `loop.review_skill` | `--review code-review` |
| `--review-args` | `loop.review_args` | `--review-args "high"` |
| `--max` | `loop.max_rounds` | `--max 3` |
| `--structure-rounds` | `loop.structure_rounds` | `--structure-rounds 0` |
| `--threshold` | `fix.threshold_rounds` | `--threshold 3` |
| `--stage` | `fix.stages.<フェーズ>` | `--stage investigate=sonnet:high` |
| `--min-fix-necessity` | `triage.min_fix_necessity` | `--min-fix-necessity must` |
| `--base` | 無し (`rally.yaml` の `loop.base` に書く) | `--base feat/a` |
| `--full-first` | 無し (`rally.yaml` の `loop.full_first` に書く) | `--full-first` |
| `--full-review` | 無し (`rally.yaml` の `loop.full_review` に書く) | `--full-review` |

- **`--model`** と **`--effort`** は、レビューのセッションを起動するときに `start_session` の `model` と `effort` に渡す。
- **`--threshold` と `--stage` は、`review-triage-fix` にそのまま渡す。** 扱いの SSOT は [review-triage-loop の arguments.md](../../review-triage-loop/references/arguments.md) の該当の段落。開始前の報告に書くために、同じ規則で値を決めて検査する。
- **`--min-fix-necessity` は、`review-triage` にそのまま渡す。** 扱いの SSOT は [review-triage-loop の arguments.md](../../review-triage-loop/references/arguments.md) の該当の段落。決めた値は `rally.yaml` の `loop.min_fix_necessity` に書き、L2 で `review-triage` を呼び出すたびに渡す。下限が無ければ、キーを書かず、引数も渡さない。
- **`--base <ブランチ>`** は、全量の起点を求める派生元のブランチ。全量の回 ([round.md](round.md) の手順 1) で、`review-request` に `--base` として渡す (起点の求め方の SSOT は [review-request の SKILL.md](../../review-request/SKILL.md) の手順 2)。**省いたら、開始時に `origin/HEAD` が指すブランチ名を、`review-request` の手順 2 と同じ求め方で解決して書く。解決できなければ、ループを始めずに人間に質問する。** 空のまま書くと、開始の報告にブランチ名が出ないためである。
- **`--full-first`** は、この起動の 1 回目の依頼文を、収束後の全量レビューの要否を問わずに全量にする。記録に回が無ければ、付けなくても 1 回目は全量になる。
- **`--full-review`** は、収束した後に、収束後の全量レビューが要れば、停止せずに全量の回を行う ([stops.md](stops.md) の RRJ1)。

## 設定と引数の優先順位

`review-triage-loop` と同じ規則 (SSOT は [review-triage-loop の arguments.md](../../review-triage-loop/references/arguments.md) の「設定と引数の優先順位」)。

1. 引数にあればその値
2. 無ければ設定の値 (上の表の対応するキー。「未設定」の定義の SSOT は [project-config.md](../../review-triage/references/project-config.md) の「「未設定」の定義」)
3. どちらにも無ければ、キーごとの既定 ([project-config.md](../../review-triage/references/project-config.md) の各節の表)
4. 既定で決まらないものは**人間に質問する**。レビューのセッションのモデルの指定 (`--model`) と effort (`--effort`)、レビュースキル (`--review`) が当たる

**レビューのセッションのモデルと effort は推測しない。** `review-triage-loop` の「G0 での解決」は使わない。

## 値の検査

検査するのは、引数か設定かを問わず、決定の結果として採る値。誤りはループを始めずにエラーとして報告し、その値が引数と設定のどちらから来たかを書く。

| 値 | 条件 |
| --- | --- |
| レビューのセッションのモデルの指定 | 空でない文字列。表記は検査しない (起動の後に実際の値と比べる。[session.md](session.md) の「起動」) |
| レビューのセッションの effort | `low` / `medium` / `high` / `xhigh` / `max` のいずれかで、呼び出し元のセッションの effort (`get_session` の `self` の `effort`) 以下。上なら、呼び出し元のセッションの effort を上げるか、指定を下げるよう案内する |
| `review_skill`・`review_args`・`max_rounds`・`structure_rounds`・`min_fix_necessity` | [review-triage-loop の arguments.md](../../review-triage-loop/references/arguments.md) の「値の検査」と同じ条件 |
| `threshold_rounds`・`stages` | [review-triage-fix の arguments.md](../../review-triage-fix/references/arguments.md) の「値の検査」と同じ条件 |
| `--base` のブランチ | `git rev-parse --verify --quiet "<ブランチ>^{commit}"` でコミットに解決でき、`git merge-base <ブランチ> HEAD` が共通祖先を返す |

## モデルと effort を指す語

このループには、モデルと effort がそれぞれ 2 つずつ現れる。

| 語 | 何か | 決めるもの |
| --- | --- | --- |
| レビューのセッションのモデルの指定 | `start_session` の `model` に渡す値 | 人間 (`--model` か `loop.review_model`) |
| 実効モデル | レビューのセッションが実際に動くモデル (`get_session` の `model`) | アプリ ([session.md](session.md) の「起動」の 4) |
| レビューのセッションの effort | `start_session` の `effort` に渡す、レビューのセッションの effort | 人間 (`--effort`) |
| レビュースキルの effort | レビュースキル (`code-review`) に渡す effort | `--review-args` か `loop.review_args` (無ければ既定。SSOT は [review-invocation.md](../../review-triage-loop/references/review-invocation.md) の「effort の既定」) |
