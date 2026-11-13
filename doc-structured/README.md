# doc-structured

Claude Code で作るアプリケーションの文書を、定義が 1 か所だけにあり、参照が機械的に検査される構成で書くための、規則・生成と検査のツール・スキル・hook を配布するプラグインです。**作成中**です。何を作るかは親の Issue [#192](https://github.com/akm/claude-plugins/issues/192) と sub-issues に、決めたことはファイル [doc-structured/docs/decisions.md](docs/decisions.md) にあります。

今あるもの:

| 場所 | 中身 |
| --- | --- |
| [bin/doc-structured](bin/doc-structured) | プロジェクトに置くスクリプト (ツールの入口)。プロジェクトが設定したバージョンのツールを取得して実行する |
| [tool/](tool/) | ツール `doc-structured` の Python パッケージ (コマンド `doc-structured`) とテスト |
| [rules/](rules/) | 規則の文書。プロジェクトのディレクトリ `.claude/rules/` に置くコピーの元 |
| [skills/](skills/) | スキル `doc-structured:generate`・`doc-structured:check`・`doc-structured:links-fix`・`doc-structured:refs` |
| [hooks/hooks.json](hooks/hooks.json)・[hook-scripts/](hook-scripts/) | 生成したファイルの直接の編集を拒否する hook (下の節「hook」) |
| [scripts/plugin-version-notice](scripts/plugin-version-notice) | スキルの前置きで、プラグインと設定のバージョンの違いを 1 行で伝えるスクリプト |
| [docs/decisions.md](docs/decisions.md) | 文書の構成の決定の一覧 |
| [docs/release.md](docs/release.md) | 公開の手順 |

## ツールの実行

プロジェクトでは、スキル・人間・CI のどれも、プロジェクトのスクリプト `bin/doc-structured` でツールを実行します。

```bash
bin/doc-structured version
```

スクリプトは次のことをします。

1. 設定ファイル `.claude/akm-claude-plugins/doc-structured/config.yaml` から、`version: 1.2.3` の形の行を文字列の一致で取り出す。この形の行が 1 行だけ無ければ、エラーで終了する。設定ファイルの場所は、スクリプト自身の場所 (プロジェクトのルートの `bin/`) から決める。
2. そのバージョンのツールが取得済みでなければ、ディレクトリ `$XDG_CACHE_HOME/akm-claude-plugins/doc-structured/<バージョン>/` (`XDG_CACHE_HOME` が無ければ `~/.cache/…`) に venv を作り、このリポジトリのタグ `doc-structured--v<バージョン>` から `pip install "git+https://github.com/akm/claude-plugins@doc-structured--v<バージョン>#subdirectory=doc-structured/tool"` で取得する。取得に失敗したら、別の方法を試さず、作りかけの venv を消し、エラーを標準エラー出力に書いて終了コード 1 で終了する。
3. 取得済みの venv のコマンド `doc-structured` を、受け取った引数のまま実行する。2 回目以降は取得をしない。

必要なもの: Python 3.12 以上の `python3`、初回の取得に `git` と GitHub・PyPI への接続。GitHub Actions のランナー `ubuntu-slim` にはどちらもあります (Python 3.12.3)。

ツール `doc-structured` は、起動時に設定ファイルをカレントディレクトリから親へ向かって探し、全体を YAML として読み、形が違えばエラーの文を標準エラー出力に書いて終了コード 1 で終了します。知らないサブコマンドを受け取ったときは、使い方を標準エラー出力に書いて終了コード 2 で終了します (プラグインのバージョンが新しく、ツールが古いときに起きます)。

| コマンド | すること |
| --- | --- |
| `doc-structured version` | ツールのバージョンを表示する |
| `doc-structured --version` | 同じ。設定ファイルは読まない |
| `doc-structured generate` | ドメインの YAML から、生成するファイルを作り直す。YAML に誤りがあるか、生成するファイルの場所に手で書いたファイル (先頭の記述が無く、空白と BOM 以外の文字があるファイル) があれば、何も書かず、終了コード 1 で終了する |
| `doc-structured check [--light\|--heavy\|--all\|--only <検査>]` | 検査を実行する。指定が無ければ軽い群 (`--light`)。問題があれば終了コード 1、引数の誤りは終了コード 2 |
| `doc-structured links-fix [<ファイル>...] [--choose <ファイル> <ラベル> <ID か URL>]...` | 手書きの Markdown の定義の行とファイルのアンカーのうち、直し方が 1 つに決まるものを直す。ファイルの指定が無ければ、すべての手書きの Markdown。判断の要るもの (参照先の候補が 0 件か複数のラベルなど) は「パス:行:列: メッセージ」の形で出力し、残れば終了コード 1。`--choose` で、ラベルの参照先を渡す。YAML に誤りがあれば、何も直さずに終了コード 1 |
| `doc-structured refs <ID>` | その ID と子孫の ID を参照している、手書きの Markdown の箇所を「パス:行:列: <参照している ID> <リンク> (<行が属する ID>)」の形で出力する。生成したファイルと記録は探さない。見つからなくても終了コード 0。ID の形が違えば終了コード 1。YAML に誤りがあっても実行する |

生成するファイルと検査の内容は、規則の文書 [rules/doc-structured-domains.md](rules/doc-structured-domains.md) にあります。この版の検査は、軽い群の a (生成し直して差分が無い)・b (手書きの Markdown のリンクとアンカー)・c-2 (手書きの Markdown の参照の循環)・h (YAML の形式と参照先)・i (YAML の参照と手書きの Markdown のリンクの向き)・k (手書きの Markdown の行数) です。リンク・アンカー・参照の向きと循環・行数の規則は、規則の文書 [rules/doc-structured-docs.md](rules/doc-structured-docs.md) にあります。重い群の検査はまだありません。ほかのサブコマンドは、sub-issue ごとに足します。

スキル `doc-structured:generate`・`doc-structured:check`・`doc-structured:links-fix`・`doc-structured:refs` は、このコマンドを実行し、直し方が 1 つに決まるものは直し、内容の判断は利用者に質問します。どれも最初に、インストール済みのプラグインのバージョンと設定の `version` が違えば、そのことを 1 行で伝えます。

## hook

プラグインをインストールすると、PreToolUse の hook (スクリプト [hook-scripts/guard-generated.py](hook-scripts/guard-generated.py)) が、生成したファイルへの Edit・Write・NotebookEdit を、編集が実行される前に拒否し、生成元のパスと生成のコマンドを Claude に伝えます。生成した `.gitattributes` では、生成元の代わりに、属性を足す場所 (リポジトリのルートの `.gitattributes`) を伝えます。

- 生成したファイルかどうかは、ファイル自身の先頭の記述で判定します (形式は規則の文書 [rules/doc-structured-docs.md](rules/doc-structured-docs.md) の「生成したファイル」)。判定には、プラグインに入っているツールのモジュールを使います。プロジェクトの設定は読まず、検査も実行しません。
- まだ無いファイルと、手書きのファイルへの編集は拒否しません。
- Bash での編集と人のエディタでの編集は防げません。スキル `doc-structured:check` の検査 a が検出します。
- Python 3.12 以上の `python3` が要ります。古い `python3` では判定をせず、標準エラー出力に理由を書いて終了コード 1 で終了します。このとき Claude Code は編集をそのまま実行します。

## 設定ファイル

ファイル `.claude/akm-claude-plugins/doc-structured/config.yaml` に書きます。今のバージョンが知っているキーは `version` だけで、知らないキーがあるとツールはエラーで終了します。

```yaml
# 図書館の貸出 (架空の題材) の設定
version: 0.1.0
```

`version` は、`version: 1.2.3` の形の 1 行で書きます。引用符を付けたり、同じ行にコメントを書いたりすると、スクリプトが行を見つけられず、ツールもエラーにします。

## 開発

環境変数 `DOC_STRUCTURED_CHECKOUT` に、このリポジトリのチェックアウトのルートの絶対パスを入れると、スクリプト `bin/doc-structured` は設定の `version` の取得をせず、そのチェックアウトの `doc-structured/tool` を editable で入れた venv (`…/doc-structured/checkout/`) を実行します。開発中のツールを別のプロジェクトで実行するためだけに使います。

```bash
DOC_STRUCTURED_CHECKOUT=/path/to/claude-plugins bin/doc-structured version
```

editable なので、コードを変えた結果はすぐに反映されます。依存を変えたときやチェックアウトの場所を変えたときは、ディレクトリ `…/doc-structured/checkout/` を消すと、次の実行で作り直します。

テストは、Python 3.12 以上の venv にツールを入れてから、リポジトリのルートで実行します。スクリプトのテスト (`tests/test_bin.py`) は、一時的な git のリポジトリにタグを作って取得の動作を確認するので、PyPI への接続が要ります。

```bash
python3 -m venv .venv && .venv/bin/pip install -e doc-structured/tool
```

```bash
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m unittest discover -s doc-structured/tool/tests
```

テストの題材は、架空の「図書館の貸出」のプロジェクト [tool/tests/fixtures/library-loans/](tool/tests/fixtures/library-loans/) です。生成したファイルもコミットしてあり、テスト `tests/test_generate.py` が、生成し直した内容と同じであることを検査します。生成の形を変えたときは、そのディレクトリでツールの `generate` を実行し、生成し直したファイルを同じコミットに含めます。

```bash
(cd doc-structured/tool/tests/fixtures/library-loans && ../../../../../.venv/bin/doc-structured generate)
```

CI では、ワークフロー `.github/workflows/test.yml` がこのテストを Python 3.12 (ファイル `tool/.python-version`) で実行し、ワークフロー `.github/workflows/doc-structured-bin.yml` がランナー `ubuntu-slim` で、公開済みの新しい 2 つのバージョンについて、スクリプトが設定の `version` のとおりのバージョンを実行することを確認します。

## 言語と取得の方法を決めた理由

sub-issue [#193](https://github.com/akm/claude-plugins/issues/193) で決めました。条件は、バージョンを指定して取得し実行できる・ランナー `ubuntu-slim` で時間がかからない・YAML のコメントと記述の順序を保って書き換えられる・取得に失敗したら別の方法を試さずエラーで終了する、の 4 つです。

- **言語は Python (3.12 以上)、YAML は ruamel.yaml**。コメント付きの YAML を読み、1 つの値だけ書き換えて書き出す確認を 3 つの言語で行い、ruamel.yaml (round-trip モード) だけが変えた値以外を 1 文字も変えずに保ちました。Node.js の yaml はコメントの前の空白の数をそろえ、Go の gopkg.in/yaml.v3 は空行を消しました。確認はテスト [tool/tests/test_yamlio.py](tool/tests/test_yamlio.py) に残しています。
- **最低のバージョンは 3.12**。ランナー `ubuntu-slim` に入っている Python が 3.12.3 で、GitHub Actions の実行時間を優先したためです。3.14 以降と uv にする案は、ランナーに uv も 3.14 も無く、ジョブごとに両方の取得が要るので採りませんでした。
- **取得は venv + pip で、このリポジトリのタグから**。ランナーにあるもの (python3・pip・git) だけで取得でき、公開がタグを作るだけで済むためです。Go のバイナリを GitHub Release に置く案と、Node.js のパッケージの案は、ビルドして置くワークフローか npm レジストリへの公開が要るので採りませんでした。

手書きの Markdown の読み取りは、sub-issue [#196](https://github.com/akm/claude-plugins/issues/196) で決めました。

- **ブロックの構造は markdown-it-py で求める**。コードブロック・HTML のブロック・見出しの行の範囲を、CommonMark のとおりに読むためです (リストや引用の中の字下げしたコードブロックを、自分で書いた読み取りでは判別しにくい)。行の中のラベル・インラインコード・エスケープは、ツールが自分で読みます。markdown-it-py は行の範囲を返しますが列を返さず、`links-fix` が書き換えない部分を 1 文字も変えずに保つ必要があるためです。

公開の手順は [docs/release.md](docs/release.md) を参照してください。
