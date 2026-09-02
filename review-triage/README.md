# review-triage

レビュー指摘を**一件ずつ吟味して採択 / 保留 / 却下に選り分け**、採択したものを**原因で束ねて直す** skill 2 つと、記録を検査する Go ツールを配布するプラグインです。

## 収録スキル

| スキル | 説明 |
| --- | --- |
| `review-triage` | 指摘を判定し、記録に残す。**修正はしない** (判断までが範囲) |
| `review-triage-fix` | 採択した指摘を原因で束ね、問題単位で直す |

`code-review` や `ce-code-review` が出した指摘を入力にします。**2 つのスキルの間の受け渡しは記録 (YAML) だけで行います。**

## なぜ記録を残すか

**却下は「対処しなかった欠陥」を作る操作で、誤った却下は気づかれないまま残ります。** 採択は修正と再レビューで検証されますが、**却下を検証する経路は記録しかありません。** 指摘を減らすほど成功に見えるので、誤った却下は成果に計上されてしまいます。

**件数の集計・累計は人が書きません。** 生成サマリが YAML から計算します。手書きの累計は誤りやすく、このスキルの 1 回目の試行では、その誤りが指摘の約 3 分の 1 を占めました。

## 同梱の検査ツール (triagecheck)

記録のスキーマと、判定フローの図・決定表の一致を機械的に検査します。**Go が必要です。**

バイナリは配らず `go run` で都度実行します。`go install` したバイナリを使う運用にすると、プラグインを更新してもバイナリが古いまま残り、**新しいスキーマを検査しないまま処理を続けます。**

詳しい呼び出し方 (Makefile に置く例、および呼び出し用のラッパースクリプトを生成する `-install-wrapper`) は [tools/triagecheck/README.md](tools/triagecheck/README.md) を参照してください。

## プロジェクト固有の設定

`.claude/akm-claude-plugins/review-triage/config.json` に置きます。

```json
{
  "record_dir": "docs/review-triages",
  "frozen_paths": ["docs/brainstorms/", "docs/plans/", "docs/solutions/"],
  "gates": ["make lint", "make test", "make check-docs"],
  "triage_check_command": "make triage-check",
  "triage_summary_command": "make triage-summary"
}
```

**`gates` (関門の一覧) がとくに重要です。** 却下の免除条項は「この欠陥を検出する関門が無い」ことを条件にするため、**そのリポジトリにどんな関門があるかを知らないと判定できません。** 未設定のときは免除条項を使いません — 突き合わせ先が無いまま関門名を書かせると、存在しない関門名が検査されないまま通るためです。

別に、指摘の分類と被害者を宣言する `.claude/review-triage.yaml` が要ります。`review-triage --gen-config` が雛形を生成します。

詳細は `skills/review-triage/references/project-config.md` を参照してください。

## 併用すると効くプラグイン

いずれも**別プラグインで、無くても動きます** (該当の手順を飛ばし、飛ばしたことを報告します)。

- [mermaid-preview](../mermaid-preview/README.md) — 保留の判断を図で提示するときに使います
- [doc-dag](../doc-dag/README.md) — 修正で文書を触った後、重複の再侵入を確認するのに使います

## 文中の例について

`references/gate-examples.md` のファイルパスと関門名は、このスキルが生まれた lappds という Go のリポジトリのものです。**自分のリポジトリで使うときは、関門の名前を自分のリポジトリの実在するものに読み替えてください。**

## 使い方

インストール手順は [リポジトリの README](../README.md#使い方) を参照してください。

```bash
claude plugin marketplace add akm/claude-plugins
claude plugin install review-triage@akm-claude-plugins
```

レビューを走らせた後で「レビューの指摘を選り分けて」のように依頼すると起動します。**同じセッションで直前に走らせたレビューの指摘を対象にします** — 勝手にレビューを走らせることはありません。
