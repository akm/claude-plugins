# doc-structured の公開の手順

プロジェクトは、設定の `version` に書いたバージョンのツールを、このリポジトリのタグから取得します (取得の仕方の SSOT は [README](../README.md) の「ツールの実行」)。公開とは、**バージョンの名前のタグを origin に push すること**です。GitHub Release は作りません (添付するものが無いため)。

## タグの名前

`doc-structured--v<バージョン>` (例: `doc-structured--v0.1.0`)。公式のプラグインのリリースのタグと同じ形です。バージョンは、ファイル `doc-structured/.claude-plugin/plugin.json` の `version` と、ファイル `doc-structured/tool/src/doc_structured/__init__.py` の `__version__` の値で、2 つは同じにします (同じであることはテスト `doc-structured/tool/tests/test_versions.py` が検査します)。

## 手順

1. バージョンを上げる PR (plugin.json と `__init__.py` の両方を上げる) を `main` にマージする。
2. 手元で `main` を取り込み、マージしたコミットに注釈付きタグを作って push する。

```bash
git checkout main && git pull --ff-only
```

```bash
git tag -a doc-structured--v0.1.0 -m "doc-structured 0.1.0"
```

```bash
git push origin doc-structured--v0.1.0
```

3. 架空のプロジェクトで、設定の `version` をそのバージョンにして `bin/doc-structured version` を実行し、そのバージョンが表示されることを確認する。CI では、ワークフロー `.github/workflows/doc-structured-bin.yml` が、公開済みの新しい 2 つのバージョンについて同じことをランナー `ubuntu-slim` で確認する。

一度 push したタグは、付け替えません (取得済みの venv は、タグの名前 (バージョン) で区別していて、タグの先のコミットが変わっても取り直さないため)。直すときは、バージョンを上げて新しいタグを作ります。
