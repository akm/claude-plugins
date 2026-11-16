# slide-deck

図を中心にした説明資料を、構成案から **PowerPoint のファイルと Google スライドの両方**に、同じ手順で作るプラグインです。作った資料の一部のスライドを、ほかのスライドに影響させずに直せます。何を作るかは親の Issue [#242](https://github.com/akm/claude-plugins/issues/242) に、作り方の決定は計画 [docs/plans/2026-11-09-2343-feat-slide-deck-plugin-plan.md](../docs/plans/2026-11-09-2343-feat-slide-deck-plugin-plan.md) にあります。

## 収録スキル

フェーズごとの 3 つのスキルです。Google スライドのコネクタが無ければ `build` まで、のように、場面に合わせて組み合わせられます。

| スキル | 入力 | 出力 |
| --- | --- | --- |
| `slide-deck:outline` | 利用者の依頼 | 構成案 `outline.md` (資料の情報と、スライドごとのキー・題名・一言・図の説明・発表者ノート) |
| `slide-deck:build` | 構成案 | 資料ごとのスクリプト `deck.mts` と、PowerPoint のファイル `build/deck.pptx` |
| `slide-deck:publish` | 構成案と `deck.mts` | Google スライドの資料 (URL と、最後に反映したプラグインの版を構成案に記録する) |

直すときも同じ 3 つのスキルを使います。まず構成案を直し (`outline`)、`deck.mts` と PowerPoint のファイルを作り直し (`build`)、Google スライドでは内容が変わったスライドだけを作り直します (`publish`)。

## しくみ

- **構成案** (ファイル `outline.md`): スライドの順序・題名・一言・発表者ノートを Markdown で書きます。文がすべて構成案にあるので、文章の規約の検査をそのままかけられます。書式は [references/outline-format.md](references/outline-format.md)。
- **資料ごとのスクリプト** (ファイル `deck.mts`): キーごとの図だけを、部品の関数で TypeScript で書きます。書き方は [references/deck-script.md](references/deck-script.md)。
- **スライドのデータ**: 構成案と `deck.mts` から作る、型で形を決めた値です。PowerPoint の書き出しと、Google スライドの指示の作成の両方が、同じデータを読みます。
- **キー**: スライドを指す名前で、構成案で決めます。Google スライドのスライドの ID は `sd_<キー>_<内容のハッシュ値>` で、資料を読むだけで、どのスライドの内容が変わったかが決まります。利用者が Google スライドで足したスライド (キーの無いスライド) は、内容を変えずに残します。
- **テーマの色**: 6 つのアクセント色に資料ごとに意味を割り当て、図形の色はテーマの色の名前で指定します。PowerPoint のファイルのテーマと、Google スライドのマスターの配色に書き込みます。

Google スライドへの反映の方法 (コネクタの使い方・指示の送り方・API への対処) は [references/google-slides.md](references/google-slides.md) にあります。

## 必要なもの

| もの | 使うスキル | 無いとき |
| --- | --- | --- |
| Node.js 24 以上 | `outline`・`build`・`publish` | 中断して、入れ方を示します |
| npm | `build`・`publish` | 中断して、入れ方を示します |
| uv | `build`・`publish` | 中断して、入れ方を示します |
| スキル `anthropic-skills:pptx` (Claude のデスクトップアプリが配るもの) | `build` | 中断します。マーケットプレイスで配る版にはファイル `scripts/apply_theme.js` が無いので使えません |
| スキル `anthropic-skills:google-workspace` | `publish` | 中断します |
| Google スライドと Google ドライブのコネクタ | `publish` | 中断して、有効にするよう求めます。Claude のデスクトップアプリ以外 (Claude Code の CLI など) では使えないことがあります |

スキル `outline` は、Node.js のほかは使いません (ライブラリも要りません)。

## ライブラリのインストール

ライブラリ (Node.js の pptxgenjs・typescript・eslint・typescript-eslint と、Python の Pillow・lxml・defusedxml) は、プラグインに同梱したロックファイル (`package-lock.json`・`uv.lock`) のバージョンで、利用者のキャッシュのディレクトリ `~/.cache/akm-claude-plugins/slide-deck/` (`XDG_CACHE_HOME` があればその下) に入れます。typescript (約 24MB) と pptxgenjs (約 5MB) などと、Python の venv が入ります。

**取得の前に、承認を求めます。** スキル `build` と `publish` は、最初に次のコマンドで入っているかを確認し、入れるものがあれば、取得するものと入れる場所を示して承認を得てから、`setup install` を実行します。入っていれば質問しません。

```bash
node <プラグインのディレクトリ>/src/cli.ts setup status
```

ロックファイルを変えないバージョンのプラグインどうしは、同じものを使います。プラグインを更新してロックファイルが変わったときだけ、もう一度承認を求めます。古いバージョンのディレクトリは自動では消しません。

## 資料のディレクトリ

1 つの資料の `outline.md` と `deck.mts` を作るディレクトリです。git で管理するかはプロジェクトごとに違うので、スキル `outline` が毎回質問します (案として `tmp/slides/<資料名>/` を添えます)。ツールは、生成したファイルを資料のディレクトリの `build/` に書き、その中に内容が `*` のファイル `.gitignore` を書きます。プロジェクトの `.gitignore` は変えません。

見本の資料 (題材は「キャッシュのしくみ」、4 枚) が、ディレクトリ [examples/sample/](examples/sample/) にあります。スキルの手順の例と、テストの入力に使っています。

## 入口のサブコマンド

スキルは、`node <プラグインのディレクトリ>/src/cli.ts <サブコマンド>` を実行します。引数・出力・終了コードは、サブコマンドごとの `--help` の出力が SSOT (single source of truth。ある事実を定めている唯一の記述) です。終了コードは、どれも、成功 0・検査の指摘あり 1・実行の誤り 2 です。

| サブコマンド | すること |
| --- | --- |
| `setup status` | ライブラリが入っているかと、取得するものを示す |
| `setup install` | 入っていないライブラリだけを入れる |
| `check-outline` | 構成案の書式だけを検査し、資料の情報と【提案】のスライドを示す |
| `check` | 構成案と `deck.mts` を検査する (tsc と eslint・キーの突き合わせ・文字のはみ出しの見積もり) |
| `pptx` | `check` に合格したときだけ PowerPoint のファイルを書き、テーマの色を書き込み、形式を検査する |
| `requests` | `check` に合格したときだけ、Google スライドから読み込んだ結果と比べて、指示のファイルを書く |
| `write-info` | 構成案に、Google スライドの URL の行と slide-deck の版の行を書き込む |

スライドの画像をまとめるツールは、`python/slide_deck_tools/thumbs_grid.py` (`--help` あり) です。

## できないこと

- 表・画像・グラフ。図形・線・文字だけで図を描きます。
- スライド番号。Google スライドでは、メニューの「挿入 > スライド番号」で付けてもらいます。
- Keynote での PDF の書き出しの確認。

## 開発

テストは、TypeScript が node:test、Python が unittest で、CI で実行します。

```bash
cd slide-deck
npm ci
npm test
uv sync --frozen
uv run mypy python
uv run python -m unittest discover -s python/tests
```

`npm test` は、`tsc --noEmit`・`eslint .`・`node --test` を続けて実行します。
