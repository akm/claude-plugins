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
  "triage_summary_command": "make triage-summary"
}
```

| キー | 意味 | 未設定のときの扱い |
| --- | --- | --- |
| `record_dir` | 記録 (YAML と生成サマリ) の置き場 | `docs/review-triages` |
| `frozen_paths` | 当時の記録として書き換えない文書のパス接頭辞 | 凍結扱いのパスは無いものとする |
| `gates` | このリポジトリの関門コマンド。免除条項の突き合わせに使う | 空。**突き合わせ先が無いので、免除条項は使えない** (下記) |
| `triage_check_command` | 記録のスキーマ検査を走らせるコマンド | 検査を走らせず、**走らせていないことを報告に明記する** |
| `triage_summary_command` | 生成サマリを再生成するコマンド | サマリを再生成しない。記録 (YAML) だけが正本として残る |

## `triage_summary_command` — 同梱の triagecheck に渡す

**同梱の `triagecheck` は `config.json` を読まない。** 案内する再生成手段は `-summary-command` で渡し、その値がサマリの 1 行目に入ってコミットされる。**`triage_summary_command` には、`triagecheck` が案内する文字列と同じものを書く** — 食い違うと、記録を読んだ人が実在しないコマンドを案内されることになる。

`-summary-command` の既定値と、`-install-wrapper` で省略したときにツールが組み立てる値の規則は、[triagecheck の README「再生成コマンドの案内」](https://github.com/akm/claude-plugins/blob/main/review-triage/tools/triagecheck/README.md#再生成コマンドの案内--summary-command) が正本。ここでは再掲しない。

## `gates` — なぜ関門の一覧が要るか

却下の免除条項は、**「この欠陥を検出する関門が無い」ことを条件にする**。条件を確かめるには、**そのリポジトリにどんな関門があるかを知る必要がある**。

突き合わせの規則は [rejection-gates.md](rejection-gates.md) が定める。要点は 2 つ。

- **粒度はテスト関数名・検査項目名まで求める。** 「テストが失敗する」では、ほぼすべての指摘に当てはまり判定を分けられない。
- **突き合わせは行の完全一致で行う。部分一致にしない。** 短い名前が長い名前に含まれると、実在しない関門名が実在すると誤判定される。

**`gates` が空のとき、免除条項は使わない。** 突き合わせ先が無いまま名前を書かせると、存在しない関門名が検査されないまま通る。**「関門が無いことを確かめた」と「関門の一覧を持っていない」は別の事実である。**

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
