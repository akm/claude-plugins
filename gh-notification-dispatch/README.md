# gh-notification-dispatch

GitHub の通知から PR のレビューの依頼と PR のマージを判定し、(リポジトリ, 種類) で登録した Claude Desktop のセッションへ届けるプラグインです。**作成中**です。今は、登録の申し込み・一覧・番号での削除と、配信のセッションの記録と、手で実行する通知の取得と配信 (レビューの依頼だけ) ができます。マージの判定と定期の予定はまだありません。何を作るかは Issue [#284](https://github.com/akm/claude-plugins/issues/284) と、計画 [docs/plans/2026-11-14-1428-feat-gh-notification-dispatch-plan.md](../docs/plans/2026-11-14-1428-feat-gh-notification-dispatch-plan.md) にあります。

GitHub の通知を定期的に取得してほかのセッションへ届けるセッションを、配信のセッションと呼びます (1 台のマシンに 1 つ)。通知を受け取るセッションを、受信のセッションと呼びます。

## 使えるスキル

| スキル | すること |
| --- | --- |
| [dispatch](skills/dispatch/SKILL.md) | 配信のセッションとして、このセッションを記録し (`start` の最初の手順)、受信のセッションから届いた登録と削除の申し込みを記録して返事を送る。登録の一覧 (`list`) と、一覧の番号での削除 (`remove`) も行う |
| [tick](skills/tick/SKILL.md) | 配信のセッションで、GitHub の通知を 1 回取得してレビューの依頼を判定し、登録した受信のセッションへメッセージで届ける。定期の予定 (計画の U5 で足す) がプロンプト `/gh-notification-dispatch:tick` で実行する |
| [subscribe](skills/subscribe/SKILL.md) | 受信のセッションとして、(リポジトリ, 種類) の登録を配信のセッションへのメッセージで申し込む。自分の登録の一覧 (`--list`) と、一覧の番号での削除 (`--remove`) も行う |

## 今あるもの

| 場所 | 中身 |
| --- | --- |
| [skills/](skills/) | スキル (上の表) |
| [references/messages.md](references/messages.md) | セッション間のメッセージの様式 |
| [references/sending.md](references/sending.md) | 配信のセッションがメッセージを送る手順 (名前で届かないときの、名前の引き直しと、ID を宛先にした送り直し) |
| [references/records.md](references/records.md) | 記録のディレクトリ (`~/.claude/gh-notification-dispatch/`) と、受信のセッションの一時ディレクトリのファイルの様式 |
| [scripts/gh_notification_dispatch.py](scripts/gh_notification_dispatch.py) | スクリプトの入口。サブコマンドの引数・出力・終了コードは `--help` で確認する |
| [scripts/gh_notification_dispatch/](scripts/gh_notification_dispatch/) | スクリプトのパッケージ (`gh` の実行・記録の読み書き・メッセージの生成と解析・登録・通知の取得・種類の判定・送信待ち) |
| [tests/](tests/) | スクリプトの自動テスト。偽の `gh` と固定データで実行する |

## テスト

```bash
python3 -m unittest discover -s gh-notification-dispatch/tests
```

Python 3.11 以上の標準ライブラリだけを使います。テストは実物の `gh` を使いません。
