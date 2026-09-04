# review-triage

レビュー指摘を**一件ずつ吟味して採択 / 保留 / 却下に選り分け**、採択したものを**原因で束ねて直す** skill 2 つと、記録を検査する Go ツールを配布するプラグインです。

## 収録スキル

| スキル | 説明 |
| --- | --- |
| `review-triage` | 指摘を判定し、記録に残す。**修正はしない** (判断までが範囲)。判定の後、同じ型の指摘が続いていないかを直前の回と照らして検知する |
| `review-triage-fix` | 採択した指摘を原因で束ね、問題単位で直す。検知があれば、束ねる前に図で繰り返しを人間と確かめて捉え直す (俯瞰) |

`code-review` や `ce-code-review` が出した指摘を入力にします。**2 つのスキルの間の受け渡しは記録 (YAML) だけで行います。**

## 繰り返しを検知して捉え直す

レビューと修正を繰り返すうちに、修正が次の指摘を生む連鎖に入ることがあります (同じ規則を経路ごとに書いていて、指摘のたびに 1 経路ずつ直す、など)。`review-triage` はこの繰り返しを検知して記録に残し、`review-triage-fix` は束ねる前に、履歴の連鎖と構造の軸の 2 段の図で人間と確かめてから、修正の単位を捉え直します。検知の条件の正本は [recurrence-detection.md](skills/review-triage/references/recurrence-detection.md)、俯瞰の手順の正本は [reframing.md](skills/review-triage-fix/references/reframing.md) です。

## なぜ記録を残すか

理由の正本は [record-schema.md](skills/review-triage/references/record-schema.md) の冒頭と「ファイルの単位」です。ここは紹介として要点だけを書きます。

**却下は「対処しなかった欠陥」を作る操作で、誤った却下は気づかれないまま残ります。** 採択は修正と再レビューで検証されますが、**却下を検証する経路は記録しかありません。** 指摘を減らすほど成功に見えるので、誤った却下は成果に計上されてしまいます。

**件数の集計・累計は人が書きません。** 生成サマリが YAML から計算します。手書きの累計は誤りやすく、このスキルの 1 回目の試行では、その誤りが指摘の約 3 分の 1 を占めました。

## 同梱の検査ツール (triagecheck)

記録のスキーマと、判定フローの図・決定表の一致を機械的に検査します。**Go が必要です。**

バイナリは配らず `go run` で都度実行します (理由の正本は [tools/triagecheck/README.md](tools/triagecheck/README.md) の「前提」)。`go install` したバイナリを使う運用にすると、プラグインを更新してもバイナリが古いまま残り、**新しいスキーマを検査しないまま処理を続けます。**

詳しい呼び出し方 (Makefile に置く例、および呼び出し用のラッパースクリプトを生成する `-install-wrapper`) は [tools/triagecheck/README.md](tools/triagecheck/README.md) を参照してください。

## プロジェクト固有の設定

`.claude/akm-claude-plugins/review-triage/config.json` に置きます。様式と各キーの意味の正本は [project-config.md](skills/review-triage/references/project-config.md) で、以下はその例です。

```json
{
  "record_dir": "docs/review-triages",
  "frozen_paths": ["docs/brainstorms/", "docs/plans/", "docs/solutions/"],
  "gates": ["make lint", "make test", "make check-docs"],
  "triage_check_command": "make triage-check",
  "triage_summary_command": "make triage-summary"
}
```

**`gates` (関門の一覧) がとくに重要です。** 却下の免除条項は「この欠陥を検出する関門が無い」ことを条件にするため、そのリポジトリにどんな関門があるかを知らないと判定できません。未設定のときの扱いと理由は [project-config.md](skills/review-triage/references/project-config.md) の「`gates` — なぜ関門の一覧が要るか」を参照してください。

別に、指摘の分類と被害者を宣言する `.claude/review-triage.yaml` が要ります。`review-triage --gen-config` が雛形を生成します (様式の正本は [config-schema.md](skills/review-triage/references/config-schema.md))。

## 併用すると役に立つプラグイン

いずれも**別プラグインで、無くても動きます** (該当の手順を飛ばし、飛ばしたことを報告します)。

- [mermaid-preview](../mermaid-preview/README.md) — 保留の判断や、俯瞰の 2 段の図を提示するときに使います。無ければ Markdown の表と箇条書きで続けます
- [doc-dag](../doc-dag/README.md) — 修正で文書を変更した後、重複が再び生じていないかを確認するのに使います

## 文中の例について

[gate-examples.md](skills/review-triage/references/gate-examples.md) のファイルパスと関門名は、このスキルが生まれた lappds という Go のリポジトリのものです。**自分のリポジトリで使うときは、関門の名前を自分のリポジトリの実在するものに読み替えてください。**

## 使い方

インストール手順は [リポジトリの README](../README.md#使い方) を参照してください。

```bash
claude plugin marketplace add akm/claude-plugins
claude plugin install review-triage@akm-claude-plugins
```

レビューを走らせた後で「レビューの指摘を選り分けて」のように依頼すると起動します。**同じセッションで直前に走らせたレビューの指摘を対象にします** — 勝手にレビューを走らせることはありません。
