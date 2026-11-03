# 偽の `claude` と比べる固定データ

ファイル `plugin-list.json` は、本物の `claude plugin list --json` の出力から、代表的な要素を選んで写したもの。テスト (ファイル `scripts/tests/test_fake_claude.py`) が、偽の `claude` (ファイル `scripts/tests/fake-claude`) の返す要素のキーが本物の要素のキーと同じであることを確認するのに使う。

本物は、読み取りだけのコマンド `claude plugin list --json` を、空の一時ディレクトリを cwd にして実行して取った。取った日は 2026-11-02、`claude --version` の出力は `2.1.285 (Claude Code)`。本物の出力には 46 個の要素があり、そのうち次の 4 つを、本物の出力の順のまま残した。

| 要素 (`id` と `scope`) | 選んだ理由 |
| --- | --- |
| `commit-rules-guard@akm-claude-plugins` の `project` | このマーケットプレイス (akm-claude-plugins) の project スコープの要素。`projectPath` を持つ |
| `commit-rules-guard@akm-claude-plugins` の `user` | このマーケットプレイスの user スコープの要素 |
| `discord@claude-plugins-official` の `user` | ほかのマーケットプレイスの要素。無効 (`enabled` が `false`) |
| `skill-creator@claude-plugins-official` の `user` | ほかのマーケットプレイスの要素。`version` が X.Y.Z の形でない |

置き換えた値は次の 2 つで、ほかの値は本物のまま。

- `projectPath`: 別のプロジェクトのパスを、架空のパス `/Users/example/other-project` に置き換えた。公開のリポジトリに、ほかのプロジェクトの名前を書かないため
- `installPath` の先頭のホームディレクトリ: 利用者の名前を含むので、`/Users/example` に置き換えた
