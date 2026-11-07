# doc-structured

Claude Code で作るアプリケーションの文書を、定義が 1 か所だけにあり、参照が機械的に検査される構成で書くための、規則・生成と検査のツール・スキル・hook を配布するプラグインです。**作成中**です。何を作るかは親の Issue [#192](https://github.com/akm/claude-plugins/issues/192) と sub-issues に、決めたことはファイル [doc-structured/docs/decisions.md](docs/decisions.md) にあります。

今あるもの:

| 場所 | 中身 |
| --- | --- |
| [bin/doc-structured](bin/doc-structured) | プロジェクトに置くスクリプト (ツールの入口)。プロジェクトが設定したバージョンのツールを取得して実行する |
| [tool/](tool/) | ツール `doc-structured` の Python パッケージ (コマンド `doc-structured`) とテスト |
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

ほかのサブコマンド (`generate`・`check` など) は、sub-issue ごとに足します。

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

CI では、ワークフロー `.github/workflows/test.yml` がこのテストを Python 3.12 (ファイル `tool/.python-version`) で実行し、ワークフロー `.github/workflows/doc-structured-bin.yml` がランナー `ubuntu-slim` で、公開済みの新しい 2 つのバージョンについて、スクリプトが設定の `version` のとおりのバージョンを実行することを確認します。

## 言語と取得の方法を決めた理由

sub-issue [#193](https://github.com/akm/claude-plugins/issues/193) で決めました。条件は、バージョンを指定して取得し実行できる・ランナー `ubuntu-slim` で時間がかからない・YAML のコメントと記述の順序を保って書き換えられる・取得に失敗したら別の方法を試さずエラーで終了する、の 4 つです。

- **言語は Python (3.12 以上)、YAML は ruamel.yaml**。コメント付きの YAML を読み、1 つの値だけ書き換えて書き出す確認を 3 つの言語で行い、ruamel.yaml (round-trip モード) だけが変えた値以外を 1 文字も変えずに保ちました。Node.js の yaml はコメントの前の空白の数をそろえ、Go の gopkg.in/yaml.v3 は空行を消しました。確認はテスト [tool/tests/test_yamlio.py](tool/tests/test_yamlio.py) に残しています。
- **最低のバージョンは 3.12**。ランナー `ubuntu-slim` に入っている Python が 3.12.3 で、GitHub Actions の実行時間を優先したためです。3.14 以降と uv にする案は、ランナーに uv も 3.14 も無く、ジョブごとに両方の取得が要るので採りませんでした。
- **取得は venv + pip で、このリポジトリのタグから**。ランナーにあるもの (python3・pip・git) だけで取得でき、公開がタグを作るだけで済むためです。Go のバイナリを GitHub Release に置く案と、Node.js のパッケージの案は、ビルドして置くワークフローか npm レジストリへの公開が要るので採りませんでした。

公開の手順は [docs/release.md](docs/release.md) を参照してください。
