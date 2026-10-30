# 引数の様式

**このファイルが `review-rally` の引数と、ループの条件の決め方の SSOT。** 設定のキーと既定値は [project-config.md](../../review-triage/references/project-config.md) の「`loop`」「`fix`」が SSOT で、ここでは言い直さない。このスキルは新しい設定のキーを持たない。

## 様式

```
review-rally [--model <指定>] [--effort <値>] [--review <スキル名>] [--review-args "<引数>"]
             [--max <回数>] [--structure-rounds <回数>] [--threshold <N>] [--stage <フェーズ>[=<値>]]...
             [--base <ブランチ>]
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
| `--base` | 無し (`rally.yaml` の `loop.base` に書く) | `--base feat/a` |

各キーの意味の SSOT は [project-config.md](../../review-triage/references/project-config.md) の各節。

- **`--model`** は、レビューのセッションを起動するときに `start_session` の `model` に渡す指定。**`--effort`** は、同じく `effort` に渡す値。どちらもループの条件として `rally.yaml` に残る (語の区別は下の「モデルと effort を指す語」)。
- **`--effort` は設定のキーを持たない。** レビューのセッションの effort は、メインのセッションの effort 以下しか選べず (アプリの制約)、メインのセッションの effort は起動ごとに変わりうるので、リポジトリごとの既定に向かない。
- **`--threshold` と `--stage` はループの条件ではなく、`review-triage-fix` にそのまま渡す。** 扱いは `review-triage-loop` と同じで、SSOT は [review-triage-loop の arguments.md](../../review-triage-loop/references/arguments.md) の該当の段落。ループは開始前の報告に書くために同じ規則で値を決めて検査し、`review-triage-fix` を呼ぶ (F1) たびに渡す。
- **`--base <ブランチ>`** は、全量の起点を求める派生元のブランチ。記録に回が無いときの最初の全量の回で、`review-request` に `--base` として渡す (起点の求め方の SSOT は [review-request の SKILL.md](../../review-request/SKILL.md) の手順 2)。設定のキーを持たない。ブランチやループごとに変わる値だからである。**省いたら、開始時に `origin/HEAD` が指すブランチ名を、`review-request` の手順 2 と同じ求め方で解決して書く。解決できなければ、ループを始めずに人間に質問する。** 空のまま書いて `review-request` の既定に任せると、開始の報告にブランチ名が出ないためである。記録に回があるときは使わない (増分の回の基点は直前の回の `head`)。

設定で決めるもの (引数を持たない) は無い。権限モードは指定せず、メインのセッションのものをレビューのセッションに引き継がせる。権限モードが同じなら、セッション間のメッセージが承認待ちにならない (#151 の通信の試験で確認した)。

## 設定と引数の優先順位

決定の順に見る (`review-triage-loop` と同じ規則。SSOT は [review-triage-loop の arguments.md](../../review-triage-loop/references/arguments.md) の「設定と引数の優先順位」)。

1. 引数にあればその値
2. 無ければ設定の値 (上の表の対応するキー。「未設定」の定義の SSOT は [project-config.md](../../review-triage/references/project-config.md) の「「未設定」の定義」)
3. どちらにも無ければ、キーごとの既定 ([project-config.md](../../review-triage/references/project-config.md) の各節の表)
4. 既定で決まらないものは**人間に質問する**。レビューのセッションのモデルの指定 (`--model`) と effort (`--effort`)、レビュースキル (`--review`) が当たる

**レビューのセッションのモデルと effort は推測しない。** `review-triage-loop` の「G0 での解決」(指定が未設定なら呼び出し元の 1 つ前の世代を既定にする) は使わない。このスキルでは、レビューのセッションのモデルを決めるのは人間である ([SKILL.md](../SKILL.md) の前提知識)。

## 値の検査

**検査するのは、引数か設定かを問わず、決定の結果として採る値。** 引数の誤りも、`loop`・`fix` の設定の誤りも、ループを始めずにエラーとして報告する (`review-triage-loop` と同じ規則)。

| 値 | 条件 |
| --- | --- |
| レビューのセッションのモデルの指定 | 空でない文字列。表記は検査しない (`start_session` が解釈し、起動の後に実際の値と比べる。比べ方の SSOT は [session.md](session.md) の「起動」)。effort と違い、開始の前にメインのセッションのモデルと比べない。モデルには、どちらが上かを決める手段が無いためである (指定は別名 `opus` でも版を含む名前でもよく、このスキルはモデルの上下の表を持たない)。指定がメインのセッションより上かどうかは、起動の後に実際の値と比べて初めて分かる (違えば RR2) |
| レビューのセッションの effort | `low` / `medium` / `high` / `xhigh` / `max` のいずれかで、メインのセッションの effort (`get_session` の `self` の `effort`) 以下。上なら、ループを始めずに、メインのセッションの effort を上げるか、指定を下げるよう案内する (上の値は `start_session` に無視されるので、起動してから RR2 で停止させずに、開始の前に誤りとして報告する) |
| `review_skill`・`review_args`・`max_rounds`・`structure_rounds` | [review-triage-loop の arguments.md](../../review-triage-loop/references/arguments.md) の「値の検査」と同じ条件 |
| `threshold_rounds`・`stages` | [review-triage-fix の arguments.md](../../review-triage-fix/references/arguments.md) の「値の検査」と同じ条件 |
| `--base` のブランチ | `git rev-parse --verify --quiet "<ブランチ>^{commit}"` でコミットに解決でき、`git merge-base <ブランチ> HEAD` が共通祖先を返す (`review-request` の手順 2 と同じ検査) |

**エラーには、その値が引数と設定のどちらから来たかを書く。** 直す先が違う。

## モデルと effort を指す語

このループには、モデルと、それぞれ別の effort が 2 つずつ現れる。**語を混ぜない。**

| 語 | 何か | 決めるもの | 残る場所 |
| --- | --- | --- | --- |
| レビューのセッションのモデルの指定 | `start_session` の `model` に渡す値 | 人間 (`--model` か `loop.review_model`) | `rally.yaml` の `loop.model`・依頼文の `model` と識別子・記録の `notes` の `model` |
| 実効モデル | レビューのセッションが実際に動くモデル (`get_session` の `model`) | アプリ (指定が起動元より上なら無視される) | `rally.yaml` の `session.model`・記録の `model` と `notes` の `(実効: …)` |
| レビューのセッションの effort | `start_session` の `effort` に渡す、レビューのセッションの effort | 人間 (`--effort`) | `rally.yaml` の `loop.effort` と `session.effort` (`get_session` の値)・記録の `notes` の `effort` |
| レビュースキルの effort | レビュースキル (`code-review`) に渡す effort | `--review-args` か `loop.review_args` (無ければ既定。SSOT は [review-invocation.md](../../review-triage-loop/references/review-invocation.md) の「effort の既定」) | 依頼文の `effort`・結果と記録の `level` |
