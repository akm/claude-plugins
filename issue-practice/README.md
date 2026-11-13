# issue-practice

GitHub の Issue の使い方 (リリースの計画と記録・管理 Issue と作業 Issue の分担・PR との対応・クローズ条件・後で行う作業の切り出し) に従って、Claude Code のセッションが Issue を扱うためのプラグインです。**作成中**です。何を作るかは管理 Issue [#239](https://github.com/akm/claude-plugins/issues/239) と、計画 [docs/plans/2026-11-13-2156-feat-issue-practice-plugin-plan.md](../docs/plans/2026-11-13-2156-feat-issue-practice-plugin-plan.md) にあります。

## 使えるスキル

まだありません。スキルは、計画の実装単位 U2〜U4 で足します。

## 今あるもの

| 場所 | 中身 |
| --- | --- |
| [references/](references/) | すべてのスキルが参照する、用語と書式の文書 (下の表) |
| [scripts/issue_practice.py](scripts/issue_practice.py) | 検査のスクリプトの入口。GitHub の状態を読み、決めた形になっているかを判定する。サブコマンドの引数・出力・終了コードは `--help` で確認する |
| [scripts/issue_practice/](scripts/issue_practice/) | 検査のスクリプトのパッケージ (`gh` の実行・識別子・記録のコメント・計画案・本文の範囲・クローズ条件のチェックボックス) |
| [tests/](tests/) | 検査のスクリプトの自動テスト。偽の `gh` と固定データで実行する |

共有の references:

| 文書 | 中身 |
| --- | --- |
| [references/terms.md](references/terms.md) | 用語 (管理 Issue・作業 Issue・計画案・記録のコメントなど) |
| [references/closing-conditions.md](references/closing-conditions.md) | 節「クローズ条件」の書き方と、チェックの入れ方 |
| [references/draft-plan.md](references/draft-plan.md) | 計画案のファイルの保存先・名前・書式 |
| [references/record-comments.md](references/record-comments.md) | 記録のコメントの 1 行目の形と、作る Issue の本文の末尾に書く行の形 |
| [references/start-instruction.md](references/start-instruction.md) | 管理セッションが作業セッションに渡す最初の指示の形 |

## テスト

```bash
python3 -m unittest discover -s issue-practice/tests
```

Python 3.11 以上の標準ライブラリだけを使います。テストは実物の `gh` を使いません。
