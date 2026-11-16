# gh-notification-dispatch

GitHub の通知から PR のレビューの依頼と PR のマージを判定し、(リポジトリ, 種類) で登録した Claude Desktop のセッションへ届けるプラグインです。**作成中**です。何を作るかは Issue [#284](https://github.com/akm/claude-plugins/issues/284) と、計画 [docs/plans/2026-11-14-1428-feat-gh-notification-dispatch-plan.md](../docs/plans/2026-11-14-1428-feat-gh-notification-dispatch-plan.md) にあります。

## 使えるスキル

まだありません。スキルは、計画の実装単位 U2〜U5 で足します。

## テスト

```bash
python3 -m unittest discover -s gh-notification-dispatch/tests
```

Python 3.11 以上の標準ライブラリだけを使います。テストは実物の `gh` を使いません。
