# 記録のファイルの様式

gh-notification-dispatch のスクリプトが読み書きするファイルの様式。どのファイルも UTF-8 の JSON で、キー `version` (今は `1`) を持つ。時刻は UTC の `YYYY-MM-DDTHH:MM:SSZ` で書く。

この文書は、計画 [docs/plans/2026-11-14-1428-feat-gh-notification-dispatch-plan.md](../../docs/plans/2026-11-14-1428-feat-gh-notification-dispatch-plan.md) の U2 で使うファイルだけを書いている。取得の位置・送信待ち・届けた出来事・追跡する PR・定期の予定のファイルとキーは、U3〜U5 で足す。

## 記録のディレクトリ

記録のディレクトリは `~/.claude/gh-notification-dispatch/` (計画の KD9)。テストでは、環境変数 `GH_NOTIFICATION_DISPATCH_HOME` で場所を変える。

| ファイル | 中身 |
| --- | --- |
| `state.json` | 配信のセッション |
| `subscriptions.json` | 登録 |
| `snapshots/<セッションの ID>.json` | 配信のセッションで一覧を表示したときの、一覧の番号と登録の ID の対応 |
| `lock` | 書き込みを順にするためのロックのファイル (中身は空) |

記録のディレクトリに書くのは、配信のセッションだけにする (計画の R19・KTD3)。

- 書き込みは、ファイル `lock` の排他ロック (`fcntl.flock`) を取ってから行う。ロックを取ったまま読み、書き換え、書く。同じマシンで並行して動くスクリプトどうしの書き込みを順にするため。
- 書き込みは、同じディレクトリの一時ファイルに書いてから名前を変える (`os.replace`)。書き込みの途中で失敗しても、元のファイルが残る。
- 書き込みの前に、スクリプトを実行しているセッションの ID (環境変数 `CLAUDE_CODE_HOST_SESSION_ID`) が、`state.json` の配信のセッションの ID と同じかを確認する。違えば、何も書かずに終了コード 3 で返す。確認しないのは、配信のセッションを記録するサブコマンド `dispatcher set` だけ。`state.json` に配信のセッションが記録されていないときも、何も書かず、記録のディレクトリも作らない。
- 受信のセッションは、記録のディレクトリを読むだけにする。

### `state.json`

```json
{
  "version": 1,
  "dispatcher": {
    "session_id": "local_00000000-0000-4000-8000-000000000000",
    "name": "GitHub の通知の配信",
    "permission_mode": "auto",
    "recorded_at": "2026-11-16T05:00:00Z"
  }
}
```

| キー | 値 |
| --- | --- |
| `dispatcher.session_id` | 配信のセッションの ID。サブコマンド `dispatcher set` が、環境変数 `CLAUDE_CODE_HOST_SESSION_ID` から読んで書く |
| `dispatcher.name` | 配信のセッションの名前 (サイドバーのタイトル) |
| `dispatcher.permission_mode` | 配信のセッションの権限モード。登録の返事に、保留されることを書くかの判定に使う (計画の R4) |
| `dispatcher.recorded_at` | 記録した時刻 |

### `subscriptions.json`

```json
{
  "version": 1,
  "subscriptions": [
    {
      "id": "0123456789ab",
      "repo": "akm/claude-plugins",
      "kind": "review_requested",
      "session_id": "local_00000000-0000-4000-8000-000000000001",
      "session_name": "claude-plugins のレビュー",
      "permission_mode": "auto",
      "created_at": "2026-11-16T05:10:00Z"
    }
  ]
}
```

| キー | 値 |
| --- | --- |
| `id` | 登録の ID。12 桁の 16 進数で、登録を足すときに乱数で作る。削除した登録の ID は使い直さない |
| `repo` | リポジトリ。GitHub の API (`GET /repos/{owner}/{repo}`) が返した `full_name` |
| `kind` | 種類 (`review_requested`・`merged`)。登録 1 件に種類 1 つ |
| `session_id`・`session_name`・`permission_mode` | 受信のセッションの ID・名前・権限モード。同じ登録を申し込み直すと、名前と権限モードを申し込みの値に変える |
| `created_at` | 登録日時。一覧の番号は、この順に振る (同じ時刻なら、ファイルの順) |

(`repo`, `kind`, `session_id`) が同じ登録は 1 件だけにする (計画の R3)。リポジトリの名前は、大文字と小文字を区別せずに比べる。

### `snapshots/<セッションの ID>.json`

```json
{
  "version": 1,
  "viewer": "local_00000000-0000-4000-8000-000000000000",
  "mine": false,
  "listed_at": "2026-11-16T05:20:00Z",
  "entries": [
    {"number": 1, "subscription_id": "0123456789ab"}
  ]
}
```

| キー | 値 |
| --- | --- |
| `viewer` | 一覧を表示したセッションの ID |
| `mine` | そのセッションの登録だけを一覧にしたか (サブコマンド `subscriptions list` の引数 `--mine`) |
| `listed_at` | 一覧を表示した時刻 |
| `entries` | 一覧の番号と登録の ID の対応 |

一覧を表示するたびに、そのセッションのファイルを置き換える。番号での削除は、このファイルの対応で行い、対応する登録が既に無ければ、何も削除せずに理由を返す (計画の R6)。

## 受信のセッションの一時ディレクトリ

受信のセッションの一覧の番号と登録の ID の対応は、記録のディレクトリの外の `${TMPDIR:-/tmp}/gh-notification-dispatch/<セッションの ID>/snapshot.json` に書く (計画の R6)。様式は `snapshots/<セッションの ID>.json` と同じ。このファイルの書き込みは記録のディレクトリへの書き込みではないので、配信のセッションかの確認をしない。受信のセッションが、自分の一覧を表示して番号で削除を申し込めるようにするため。
