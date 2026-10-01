# textlint による検査

**textlint (文章を規則で検査するツール) で、用語ファイルの避ける語と、規則集 (textlint の規則をまとめたパッケージ) が出す不自然な言い回しの候補を検出する。** 使うのは、設定キー `textlint` を書いたリポジトリだけ (ファイル [wording-guard/skills/wording-guard/references/project-config.md](project-config.md))。

textlint は語の一覧と文の形で照合する道具なので、**検出したものは着手点であって、範囲ではない。** 検出されなかった言い回しも、SKILL.md の手順 2 で読んだ原則に照らして判断する (用語ファイルを範囲として扱わない理由の正本は [terms.md](terms.md) の「用語ファイルは例であって、範囲ではない」)。

## 何を検出するか

| 種類 | 検出に使うもの | 重大度 |
| --- | --- | --- |
| 避ける語 | 用語ファイル ([terms.md](terms.md)) を、規則 textlint-rule-prh (語のパターンと置き換え先を照合する規則。以下 prh) の辞書に変換したもの | error (失敗にする) |
| 不自然な言い回しの候補 | リポジトリの textlint の設定 (設定キー `textlint.config`) で有効にした規則集 | 設定で決める。warning (失敗にしない) を推奨 |

**次のものは検出しない。**

- 用語ファイルの許容する語と、避ける語の例外 (`exceptions`)。フィルタ textlint-filter-rule-allowlist (指定した文字列の範囲の検出を除くフィルタ) の一覧に入れる。**この一覧はすべての規則に適用される** — 許容する語は、規則集のどの規則でも検出されなくなる
- 引用ブロック。フィルタ textlint-filter-rule-node-types で除く (このスキルが引用を書き換えないため。[rewrite-scope.md](rewrite-scope.md))
- 設定キー `frozen_paths` (書き換えない過去の記録のパス接頭辞) の下のファイル

## セットアップ

textlint と規則集は、プラグインに同梱したファイル `wording-guard/textlint/package.json` と `package-lock.json` で版を固定している。次のコマンドで、利用者のキャッシュに `npm ci` で入れる。**npm で約 380 個のパッケージを取得する。Node と npm が必要。**

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/wording_lint.py setup
```

置き場は `${XDG_CACHE_HOME:-~/.cache}/akm-claude-plugins/wording-guard/textlint-<ロックファイルのハッシュ>`。環境変数 `WORDING_GUARD_CACHE_DIR` で親のディレクトリを変えられる。**プラグインを更新して版が変わると置き場も変わるので、もう一度セットアップする。** 入っていないときは、検査を省略せずに、セットアップのコマンドを添えた誤りを報告する。置き場があるのに textlint が入っていない (中身が消えた・壊れた) ときは、セットアップは取得を始めずに誤りを報告し、置き場を消すよう案内する (置き場は消さない)。

**エージェントがセットアップを実行するときは、人間の承認を得てから実行する** — パッケージを取得するため。

使える規則集は `package.json` にあるもの (textlint-rule-preset-ja-no-ai-slop・textlint-rule-preset-ai-writing・textlint-rule-preset-ja-technical-writing・textlint-rule-ja-no-redundant-expression)。リポジトリの textlint の設定に、これ以外の規則を書くと、textlint の実行が失敗する。

## リポジトリの textlint の設定

設定キー `textlint.config` に、textlint の標準の様式 (JSON) の設定ファイルを指定する。**候補を出す規則集の選び方** (どの規則を有効にし、どれを warning にするか) をここに書く。省略すると、用語ファイルだけで検査する。

```json
{
  "rules": {
    "preset-ja-no-ai-slop": {
      "literal-verb-translation": { "severity": "warning" },
      "sentence-connection": false
    },
    "ja-no-redundant-expression": { "severity": "warning" }
  }
}
```

**この例は様式を示すもので、そのまま写さない。** 規則集の検出の多くはリポジトリの書式 (ダッシュの使い方・文の長さなど) に対するもので、どれを有効にするかはリポジトリごとに違う。[#89](https://github.com/akm/claude-plugins/issues/89) の試行では、このリポジトリで規則ごとの件数を数えてから選んだ。

実行するたびに、この設定・用語ファイルから生成した prh の辞書と許容の一覧・引用ブロックを除くフィルタを合わせた設定を、一時ディレクトリに作って使う。

- 規則 `prh` とフィルタ `allowlist` を自分で書いてもよい。生成した辞書と一覧は、その後ろに足す。`rulePaths` と `allowlistConfigPaths` の相対パスは、設定ファイルの場所から解決する
- **それ以外の規則の設定にパスを書くときは、絶対パスにする** — 合わせた設定は一時ディレクトリに置くので、相対パスが解決できない
- 規則 `prh`・フィルタ `allowlist`・フィルタ `node-types` を `false` にすると誤りになる (用語ファイルの検査に使うため)

## コマンド

```bash
# ファイルかディレクトリを検査する
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/wording_lint.py check docs/ README.md

# ファイルにしていない文章 (Issue・PR の本文、コミットメッセージの下書き) を検査する
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/wording_lint.py check --stdin --filename issue.md < draft.md

# 自動修正してよい避ける語 (autofix = true) だけを、ファイルに適用する
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/wording_lint.py fix docs/
```

| 終了コード | 意味 |
| --- | --- |
| 0 | 成功。`check` では error の検出が無い (warning だけなら 0) |
| 1 | `check` で error の検出 (用語ファイルの避ける語) がある |
| 2 | 設定ファイル・用語ファイルの誤り、設定キー `textlint` が無い、または指定したパスが無いか、指定したファイルが Markdown (`.md`) でない (ディレクトリを指定すると、その下の Markdown だけを対象にする) |
| 3 | textlint が入っていない、または textlint・npm の実行に失敗した |

**`fix` はファイルの全体に適用する。** 他の人が書いた文章も直すので、今回の変更で書いたファイルだけに使う ([rewrite-scope.md](rewrite-scope.md))。文脈によって言い換えが変わる語 (`autofix` を書かない語) は、`fix` では直さない — [#89](https://github.com/akm/claude-plugins/issues/89) の試行で、自動修正が「効かない」を「適用される」に書き換え、意味が逆になったため。

## hook

設定キー `textlint.hook` を `true` にすると、Claude Code のツール Edit・MultiEdit・Write が Markdown を書いた直後に、書き足した文章を検査する (PostToolUse の hook。同梱のファイル `wording-guard/hooks/hooks.json`)。

- **Edit・MultiEdit は、書き換える前の文字列と後の文字列を両方検査し、書き換えた後の文字列で増えた検出だけを返す。** 書き換えた後の文字列 (`new_string`) には、書き換える箇所を一意に特定するために、変えていない前後の行も入ることがある。そこにあった検出 (他の人が既に書いた文章) を、今回持ち込んだものとして扱わないため
- **Write は、書いた内容の全体を検査する** — 書き換える前の内容は hook に渡されない。既存のファイルを Write で書き直すと、前からあった検出も返る
- error (避ける語) があれば、Claude に直すよう求める (`decision: block`)。warning (規則集の候補) だけなら、判断の材料として渡す (`additionalContext`)
- 設定・用語ファイルの誤りや、textlint が入っていないときは、検査を省略せずに、Claude と利用者の両方に知らせる
- 設定キー `textlint.hook` が `true` でないリポジトリ、Markdown 以外のファイル、設定キー `frozen_paths` の下のファイル、git リポジトリの外のファイルでは何もしない。**プラグインの hook は、プラグインを有効にしたすべてのリポジトリで動く** ので、設定で有効にしたリポジトリでだけ検査する
- Python 3.11 以降が必要 (用語ファイルを標準ライブラリ `tomllib` で読むため)

## 動作の確認

textlint そのものは CI の環境に無いので、テスト (ディレクトリ `wording-guard/tests/`) は textlint の実行を差し替えている。textlint を実際に実行する確認は、次の手順で行う。

1. セットアップする (上の「セットアップ」)
2. 設定キー `textlint` を書いたリポジトリで、避ける語・例外・許容する語・引用ブロックを含む Markdown を作り、`check` を実行する。避ける語だけが error になり、例外・許容する語・引用ブロックは検出されないことを確かめる
3. 同じファイルの複製に `fix` を実行し、`autofix = true` の語だけが書き換わることを確かめる
