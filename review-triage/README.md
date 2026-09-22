# review-triage

レビュー指摘を**一件ずつ吟味して採択 / 保留 / 却下に選り分け**、採択したものを**原因で束ねて直す** skill 4 つと、記録を検査する Go ツールを配布するプラグインです。

## 収録スキル

| スキル | 説明 |
| --- | --- |
| `review-request` | 別セッションで走らせる上流レビューの依頼文を、雛形から埋めて `tmp/` に書き出す。結果の出力先を依頼文に埋め込み、新しいセッションにはそのパス 1 つを渡す |
| `review-triage` | 指摘を判定し、記録に残す。**修正はしない** (判断までが範囲) |
| `review-triage-fix` | 採択した指摘を原因で束ね、調査 → 立案 → 修正 の 3 段で問題単位で直す。記録の回番号が回数の閾値 N を越えた回では、調査の後に人間が立案者 (セッションのモデル / 指定モデルの sub-agent / 人間自身) を選ぶ。段ごとに sub-agent で走らせられる |
| `review-triage-loop` | レビューの起動から上の 2 つまでを 1 周として、終了条件に当たるまで繰り返す。**判断も修正もせず、2 つを呼ぶだけ** |

`code-review` や `ce-code-review` が出した指摘を入力にします。**2 つのスキルの間の受け渡しは記録 (YAML) だけで行います。**

`review-triage` と `review-triage-fix` は、それぞれ単独でも使えます。`review-triage-loop` は、レビューから修正までを人間が毎回指示する代わりに、上限回数まで自動で回したいときに使います (詳細は [SKILL.md](skills/review-triage-loop/SKILL.md))。

## なぜ記録を残すか

理由の正本は [record-schema.md](skills/review-triage/references/record-schema.md) の冒頭と「ファイルの単位」です。ここは紹介として要点だけを書きます。

**却下は「対処しなかった欠陥」を作る操作で、誤った却下は気づかれないまま残ります。** 採択は修正と再レビューで検証されますが、**却下を検証する経路は記録しかありません。** 指摘を減らすほど成功に見えるので、誤った却下は成果に計上されてしまいます。

**件数の集計・累計は人が書きません。** 生成サマリが YAML から計算します。手書きの累計は誤りやすく、このスキルの 1 回目の試行では、その誤りが指摘の約 3 分の 1 を占めました。

## 同梱の検査ツール (triagecheck)

記録のスキーマと、判定フローの図・決定表の一致を機械的に検査します。**Go が必要です。**

バイナリは配らず `go run` で都度実行します (理由の正本は [tools/triagecheck/README.md](tools/triagecheck/README.md) の「前提」)。`go install` したバイナリを使う運用にすると、プラグインを更新してもバイナリが古いまま残り、**新しいスキーマを検査しないまま処理を続けます。**

詳しい呼び出し方 (Makefile に置く例、および呼び出し用のラッパースクリプトを生成する `-install-wrapper`) は [tools/triagecheck/README.md](tools/triagecheck/README.md) を参照してください。

## 同梱の道具 (nearedges)

Markdown の修正の差分から、コミット前に読み直す範囲 — 同じ表の全行・同じ箇条書きとその親・同じ節の全文・変更行が参照する先 (近くの辺) — を列挙します。`review-triage-fix` の段 3 が観点 B (並びを読み直す) に使い、読んだ範囲を記録の `plans[].verification.near_edges` に残します。`-hints` で差分の種類に応じた観点 (B・C・F) も提示します。使い方は [tools/nearedges/README.md](tools/nearedges/README.md)。**Go が必要です** (triagecheck と同じく `go run` で都度実行)。

## プロジェクト固有の設定

`.claude/akm-claude-plugins/review-triage/config.json` に置きます。様式と各キーの意味の正本は [project-config.md](skills/review-triage/references/project-config.md) で、以下はその例です。

```json
{
  "record_dir": "tmp/review-triages",
  "frozen_paths": ["docs/brainstorms/", "docs/plans/", "docs/solutions/"],
  "gates": ["make lint", "make test", "make check-docs"],
  "triage_check_command": "make triage-check",
  "triage_summary_command": "make triage-summary",
  "loop": {
    "max_rounds": 10,
    "review_skill": "code-review",
    "review_args": "high",
    "review_model": ""
  },
  "fix": {
    "threshold_rounds": 5,
    "stages": {
      "investigate": { "subagent": false, "model": "", "effort": "" },
      "plan":        { "subagent": false, "model": "", "effort": "" },
      "fix":         { "subagent": false, "model": "", "effort": "" }
    }
  }
}
```

`loop` は `review-triage-loop` の既定 (上限・レビュースキル・そのオプション・モデル) で、`review-triage` と `review-triage-fix` だけを使うなら要りません。各キーの意味と「未設定」の定義は [project-config.md](skills/review-triage/references/project-config.md) の「`loop`」を参照してください。

`fix` は `review-triage-fix` の既定 — 回数の閾値 N (`threshold_rounds`) と、段 (調査 / 立案 / 修正) ごとに sub-agent で走らせるか・その model と effort (`stages`) — で、無くても既定 (閾値 5、どの段もセッション内) で動きます。各キーの意味は同ファイルの「`fix`」を参照してください。

**`gates` (関門の一覧) がとくに重要です。** 却下の免除条項は「この欠陥を検出する関門が無い」ことを条件にするため、そのリポジトリにどんな関門があるかを知らないと判定できません。未設定のときの扱いと理由は [project-config.md](skills/review-triage/references/project-config.md) の「`gates` — なぜ関門の一覧が要るか」を参照してください。

別に、指摘の分類と被害者を宣言する `.claude/review-triage.yaml` が要ります。`review-triage --gen-config` が雛形を生成します (様式の正本は [config-schema.md](skills/review-triage/references/config-schema.md))。

## 同梱の agent 定義

`agents/` に、`review-triage-fix` が段を sub-agent で走らせるときに使う汎用の agent 定義を 6 つ同梱しています — `fix-stage` (effort をセッションから継承) と `fix-stage-low` / `fix-stage-medium` / `fix-stage-high` / `fix-stage-xhigh` / `fix-stage-max`。参照名は `review-triage:fix-stage-high` の形です。Claude Code は sub-agent の effort を agent 定義の frontmatter でしか受けず、呼び出し時に上書きできないため、effort ごとに定義を分けています。定義の違いは effort だけで、どの段を行うかは `review-triage-fix` が依頼文で指示し、model は呼び出し時に渡します (走らせ方・依頼文・検証の正本は [stage-subagent.md](skills/review-triage-fix/references/stage-subagent.md))。**`review-triage-fix` の依頼文を伴わない用途では使いません。**

## 併用すると役に立つプラグイン

いずれも**別プラグインで、無くても動きます** (該当の手順を飛ばし、飛ばしたことを報告します)。

- [mermaid-preview](../mermaid-preview/README.md) — 保留の判断を提示するときに使います。無ければ Markdown の表と箇条書きで続けます
- [doc-dag](../doc-dag/README.md) — 同じ記述が複数の箇所にあるとき片方を正本にしてもう片方を参照に変える修正と、修正で文書を変更した後に重複が再び生じていないかの確認に使います

## 文中の例について

[gate-examples.md](skills/review-triage/references/gate-examples.md) のファイルパスと関門名は、このスキルが生まれた lappds という Go のリポジトリのものです。**自分のリポジトリで使うときは、関門の名前を自分のリポジトリの実在するものに読み替えてください。**

## 使い方

インストール手順は [リポジトリの README](../README.md#使い方) を参照してください。

```bash
claude plugin marketplace add akm/claude-plugins
claude plugin install review-triage@akm-claude-plugins
```

別セッションでレビューを走らせるときは、先に「レビューの依頼文を作って」(`review-request`) で依頼文を `tmp/` に書き出し、新しいセッションにそのパスを渡します。結果が返ったら「レビューの指摘を選り分けて」のように依頼すると `review-triage` が起動します。同じセッションで走らせたレビューの指摘も対象にできます。**勝手にレビューを走らせることはありません。**
