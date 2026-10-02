# wording-guard

**書き手が自分の文章に混ぜた比喩・口語・擬人化は、書いた本人には見えない。** これから外へ出す日本語の文章からそれを見つけ、リポジトリの規約が定める原則に照らして言い換える skill と、言い換えを決めた語を textlint で検出する hook を配布するプラグインです。

## 収録スキル

| スキル | 説明 |
| --- | --- |
| `wording-guard` | これから書く日本語の文章の不自然な言い回しを、原則に照らして見つけ、種類ごとに広げて直す |

## 何を解決するか

考え方と手順の正本は同梱のファイル [wording-guard/skills/wording-guard/SKILL.md](skills/wording-guard/SKILL.md) です。ここは要点だけを書きます。

語を 1 つ指摘されて直しても、**同じ原則に反する別の語が残ります。** あるレビューコメントの下書きでは、プログラムやデータを主語にして人や物の動きを表す動詞が、人間が 3 回指摘するまで別の語で残り続けました (3 往復の記録はファイル [wording-guard/skills/wording-guard/references/kind-expansion.md](skills/wording-guard/references/kind-expansion.md) にあります)。

このスキルは、見つけた 1 件から**種類** (他の表現に当てはめて判定できる 1 文) を書き、その種類で対象全体を探し直します。**語の一覧との照合ではありません。** 一覧を範囲にすると、一覧に無い表現が検査されないまま残るためです。

**判断の基準はこのスキルが持ちません。** リポジトリの規約から読みます。一覧を作らず原則だけを置くリポジトリと、例の表を持ちつつ「表は例であって網羅ではない」と宣言するリポジトリがあり、どちらの方針もそのリポジトリの規約に書いてあるためです。スキル自身が持つのは、SKILL.md の手順 2 が使うと定めた一般の 3 原則だけです。

## 用語ファイル (任意)

言い換えを決めた語 (避ける語) と、使い続けると決めた語 (許容する語) を、理由と決めた場所とともに TOML のファイルに記録できます。スキルは避ける語を検索の着手点にし、許容する語を候補から外します。**用語ファイルは決めたことの記録であって、検査の範囲ではありません。** 用語ファイルに無い言い回しも、原則に照らして判断します。

```toml
[[terms]]
pattern = "周回"
verdict = "avoid"
replacements = ["ループ", "繰り返し"]
reason = "日本語の「周回」はコースや軌道を回ること。処理の繰り返しには通じにくい"
decided_in = "https://github.com/akm/claude-plugins/issues/87"
```

様式と意味は同梱のファイル [wording-guard/skills/wording-guard/references/terms.md](skills/wording-guard/references/terms.md) を参照してください。様式の検査とまとめた内容の確認は、次のコマンドで行えます (Python 3.11 以降が必要です)。

```bash
python3 <プラグインのディレクトリ>/scripts/wording_lint.py terms
```

## textlint による検査 (任意)

設定キー `textlint` を書くと、textlint (文章を規則で検査するツール) で、用語ファイルの避ける語と、規則集 (textlint の規則をまとめたパッケージ) が出す不自然な言い回しの候補を検出します。避ける語は error (失敗にする重大度) として報告します。候補の重大度はリポジトリの textlint の設定で決め、warning (失敗にしない重大度) を推奨します。**検出したものは着手点であって、範囲ではありません。**

- **スキル:** 手順 3 で対象を検査し、結果を候補にします
- **hook:** `textlint.hook` を `true` にすると、Claude Code が Markdown を書いた直後に、書き足した文章を検査します。error の検出 (避ける語と、設定で error にした規則集の規則) があれば直すよう Claude に求め、warning だけなら判断の材料として渡します
- **コマンド:** `wording_lint.py check` で検査し、`wording_lint.py fix` で自動修正してよい避ける語 (`autofix = true`) だけを直します

**Node と npm が必要です。** textlint と規則集の版はプラグインが固定していて、次のコマンドで利用者のキャッシュに入れます (npm で約 380 個のパッケージを取得します)。プラグインを更新して版が変わったら、もう一度実行します。

```bash
python3 <プラグインのディレクトリ>/scripts/wording_lint.py setup
```

詳細は同梱のファイル [wording-guard/skills/wording-guard/references/textlint.md](skills/wording-guard/references/textlint.md) を参照してください。

## 書き換えないもの

- **引用** — 原文と一致していることに意味があるため。
- **他の人が既に書いた文章** — 今回の変更で持ち込んだものだけを直します。**規範文書が使っていることは、自分が使ってよい理由になりません。**
- **過去の記録** — 検討の記録・完了した計画・逐語引用のトリアージ記録。

詳細は同梱のファイル [wording-guard/skills/wording-guard/references/rewrite-scope.md](skills/wording-guard/references/rewrite-scope.md) を参照してください。

## プロジェクト固有の設定 (任意)

ファイル `.claude/akm-claude-plugins/wording-guard/config.json` に置きます。**無くても実行できます。**

```json
{
  "convention_paths": ["CLAUDE.md#文書の言い回し"],
  "frozen_paths": ["docs/plans/", "docs/solutions/", "tmp/review-triages/"],
  "quote_markers": ["> "],
  "terms_paths": [".claude/akm-claude-plugins/wording-guard/terms.toml"],
  "textlint": { "config": ".claude/akm-claude-plugins/wording-guard/textlintrc.json", "hook": true }
}
```

上の例は様式を示すもので、**そのまま写す対象ではありません。** 置き場はリポジトリごとに決めます。

- `convention_paths` — 判断の基準になる規約の置き場。未設定ならリポジトリのルートの `CLAUDE.md` を読み、規約が見つからなければ一般の 3 原則だけで判断することを報告して進みます。
- `frozen_paths` — 書き換えない過去の記録のパス接頭辞。未設定なら書き換えないパスを無いものとし、過去の記録らしき文書が見つかったら人間に確認します。
- `quote_markers` — 引用の目印になる行頭の文字列。**未設定なら引用ブロックとコードブロックを目印にします。** コードブロックは値を設定しても目印のままです。
- `terms_paths` — 用語ファイルの置き場の配列。未設定なら用語ファイルを使いません。書いたファイルが無ければ誤りとして報告します。
- `textlint` — textlint で検査するかどうかと、その設定 (`config`: 候補を出す規則集を選ぶ textlint の設定ファイル、`hook`: hook で検査するか)。未設定なら textlint を使いません。

詳細は同梱のファイル [wording-guard/skills/wording-guard/references/project-config.md](skills/wording-guard/references/project-config.md) を参照してください。

## 使い方

インストール手順は [リポジトリの README](../README.md#使い方) を参照してください。

```bash
claude plugin marketplace add akm/claude-plugins
claude plugin install wording-guard@akm-claude-plugins
```

「この文章の言い回しを直して」「不自然な言い回しを探して」のように依頼すると起動します。PR 本文・Issue 本文・レビューコメント・コミットメッセージを投稿する直前に、その下書きを渡す使い方も想定しています。

## このプラグインがしないこと

正本は同梱の [SKILL.md](skills/wording-guard/SKILL.md) の「このスキルがしないこと」です。ここは要約です。

- **文章の内容のレビュー** — 主張の正しさ・構成・過不足は別の関心事です。
- **一覧の網羅の保証** — 原則に照らした判断なので、読みの深さに依存します。見つけた分を直し、走査の回数と各回の結果を報告します。
- **他人が書いた既存の文書の一括修正** — 別の作業として扱います。
- **英語の文章** — 日本語の文章だけを対象にします。
