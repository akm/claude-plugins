# プロジェクト固有の設定

このスキルは、リポジトリごとに違うものを設定から読む。置き場は `.claude/akm-claude-plugins/review-triage/config.json`。

[commit-rules-guard](https://github.com/akm/claude-plugins/tree/main/commit-rules-guard) と同じ流儀で、プラグインは共通の規則を持ち、リポジトリ固有の宣言だけをこのファイルに置く。

## 様式

```json
{
  "record_dir": "docs/review-triages",
  "frozen_paths": ["docs/brainstorms/", "docs/plans/", "docs/solutions/"],
  "gates": ["make lint", "make test", "make check-docs"],
  "triage_check_command": "make triage-check",
  "triage_summary_command": "make triage-summary",
  "loop": {
    "max_rounds": 5,
    "review_skill": "ce-code-review",
    "review_args": "",
    "review_model": ""
  }
}
```

| キー | 意味 | 未設定のときの扱い |
| --- | --- | --- |
| `record_dir` | 記録 (YAML と生成サマリ) の置き場 | `docs/review-triages` |
| `frozen_paths` | 当時の記録として書き換えない文書のパス接頭辞 | 凍結扱いのパスは無いものとする |
| `gates` | このリポジトリの関門コマンド。免除条項の突き合わせに使う | 空。**突き合わせ先が無いので、免除条項は使えない** (下記) |
| `triage_check_command` | 記録のスキーマ検査を走らせるコマンド | 検査を走らせず、**走らせていないことを報告に明記する** |
| `triage_summary_command` | 生成サマリを再生成するコマンド | サマリを再生成しない。記録 (YAML) だけが正本として残る |
| `loop` | `review-triage-loop` の既定値 (下記) | 周回の既定値を持たない。`review-triage-loop` は引数で補えないものがあれば人間に尋ねる |

## `triage_summary_command` — 同梱の triagecheck に渡す

**同梱の `triagecheck` は `config.json` を読まない。** 案内する再生成手段は `-summary-command` で渡し、その値がサマリの 1 行目に入ってコミットされる。**`triage_summary_command` には、`triagecheck` が案内する文字列と同じものを書く** — 食い違うと、記録を読んだ人が実在しないコマンドを案内されることになる。

`-summary-command` の既定値と、`-install-wrapper` で省略したときにツールが組み立てる値の規則は、[triagecheck の README「再生成コマンドの案内」](https://github.com/akm/claude-plugins/blob/main/review-triage/tools/triagecheck/README.md#再生成コマンドの案内--summary-command) が正本。ここでは再掲しない。

## `gates` — なぜ関門の一覧が要るか

却下の免除条項は、**「この欠陥を検出する関門が無い」ことを条件にする**。条件を確かめるには、**そのリポジトリにどんな関門があるかを知る必要がある**。

突き合わせの規則は [rejection-gates.md](rejection-gates.md) が定める。要点は 2 つ。

- **粒度はテスト関数名・検査項目名まで求める。** 「テストが失敗する」では、ほぼすべての指摘に当てはまり判定を分けられない。
- **突き合わせは行の完全一致で行う。部分一致にしない。** 短い名前が長い名前に含まれると、実在しない関門名が実在すると誤判定される。

**`gates` が空のとき、免除条項は使わない。** 突き合わせ先が無いまま名前を書かせると、存在しない関門名が検査されないまま通る。**「関門が無いことを確かめた」と「関門の一覧を持っていない」は別の事実である。**

## `loop` — 周回の既定値

[review-triage-loop](../../review-triage-loop/SKILL.md) が読む。**引数で指定された値が設定より優先する** — 設定はリポジトリごとの既定で、引数はその回だけの上書き。

| キー | 意味 | 未設定のときの扱い |
| --- | --- | --- |
| `max_rounds` | 周回の上限 | 5 |
| `review_skill` | 起動するレビュースキル (`code-review` / `ce-code-review`) | 引数にも無ければ人間に尋ねる。**推測して決めない** |
| `review_args` | レビュースキルに渡す引数 (`code-review` の effort など) | 既定の effort を渡す (正本は [review-invocation.md](../../review-triage-loop/references/review-invocation.md) の「effort の既定」の節) |
| `review_model` | 周回に指定するモデル。経路によって実際に使われるかが違う (実効モデルの正本は [review-invocation.md](../../review-triage-loop/references/review-invocation.md) の「実効モデル」の節) | 経路で決まる (正本は [review-invocation.md](../../review-triage-loop/references/review-invocation.md) の「G0 での解決」) |

**`max_rounds` に上限を設ける理由は、収束しない周回を止めるため。** 回数が多いこと自体が「収束していない」という情報で、放置すると同じ型の指摘に何度も応え続けることになる。記録の `runs` の要素数は周回をまたいだ累計で、上限の数え方 (正本は [review-triage-loop の loop-flow.md](../../review-triage-loop/references/loop-flow.md) の決定表 J5) とは別である — 過去に何回まで伸びたかを後から見るときに使う。上限に達したときの扱いは `review-triage-loop` の手順が定める。

### 「未設定」の定義 (正本)

**`loop` のキーが「未設定」とは、キーが無いか、文字列のキー (`review_skill` / `review_args` / `review_model`) の値が空文字列であることを指す。** 未設定のキーは既定に従い、既定が決まらないキー (`review_skill` はいつでも、`review_model` は呼び出し元が対応表に無いとき。ただし周回がモデルを決めない経路は除く — 正本は [review-invocation.md](../../review-triage-loop/references/review-invocation.md) の「G0 での解決」) は人間に尋ねる。JSON の様式が `""` を置いているのは、キーの存在を示すためであって、空のモデル名や空の引数を指定する意味ではない。

**`max_rounds` は整数で、空文字列を未設定とは読まない** — 空や整数でない値は `review-triage-loop` の値の検査 ([arguments.md](../../review-triage-loop/references/arguments.md)) がエラーにする。

`review-triage-loop` の文書 (引数の決定手順・SKILL.md の手順 1) は「未設定」という語でこの定義を参照し、条件を言い直さない。

**`review_model` は 1 つの周回に 1 つの値。** 回ごとに変えることはできない。周回をまたいで変えるのは構わない (記録が回ごとに `model` を持つので後から比較できる) が、そのつど人間が指示する — 周回が勝手に切り替えると、指摘の減り方がモデルの違いによるものか収束によるものかを人間が読み解けなくなる。

**`review_skill` を推測しない。** どちらのスキルで走らせたかは記録の `skill` に残り、後から粒度を比較する材料になる。推測で決めると、記録が実態と食い違う。

## `frozen_paths` — 直さない文書

検討の記録・完了した計画・当時の知見は、**その時点の記録として価値がある。** 指摘がここに当たったときは直さない。

**代わりに、現行の文書側に同じ問題が無いかを見る。** 過去の記録に現れた欠陥が現行の文書にも残っていることはよくあり、そちらは直す対象になる。

**凍結の有無は機械的に判断できない。** ディレクトリ名から推測せず、設定に書かれたものだけを凍結として扱う。

## 検査コマンドを設定しないとどうなるか

記録のスキーマ検査 (`triage_check_command`) は、必須キーの欠落・列挙値の誤り・参照の不整合を捕まえる。**走らせなければ、壊れた記録がそのまま残る。**

同梱の `triagecheck` を使う場合、2 通りの置き方がある。

- **Makefile にターゲットを 1 つ置く**（リポジトリの Makefile をそのまま検査コマンドの置き場にする）
- **`-install-wrapper` でラッパースクリプトを生成する**（`.claude/akm-claude-plugins/review-triage/config.json` のようにリポジトリごとの設定として管理したくない・Makefile に手を入れたくない場合）

どちらの置き方も、Makefile の例 (展開先の求め方・渡すフラグ) と `-install-wrapper` の使い方は [triagecheck の README](https://github.com/akm/claude-plugins/blob/main/review-triage/tools/triagecheck/README.md) が正本。ここに写すと、渡すフラグが増えたときに片方だけ古くなる。

**検査を走らせなかった回は、報告にそう書く。** 「検査で問題が出なかった」と「検査を走らせていない」は別の事実で、混同すると次の読み手が通ったものと誤解する。
