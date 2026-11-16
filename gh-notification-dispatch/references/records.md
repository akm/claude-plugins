# 記録のファイルの様式

gh-notification-dispatch のスクリプトが読み書きするファイルの様式。どのファイルも UTF-8 の JSON で、キー `version` (今は `1`) を持つ。時刻は UTC の `YYYY-MM-DDTHH:MM:SSZ` で書く。

この文書は、計画 [docs/plans/2026-11-14-1428-feat-gh-notification-dispatch-plan.md](../../docs/plans/2026-11-14-1428-feat-gh-notification-dispatch-plan.md) の U2〜U5 で使うファイルを書いている。

## 記録のディレクトリ

記録のディレクトリは `~/.claude/gh-notification-dispatch/` (計画の KD9)。テストでは、環境変数 `GH_NOTIFICATION_DISPATCH_HOME` で場所を変える。

| ファイル | 中身 |
| --- | --- |
| `state.json` | 配信のセッション |
| `subscriptions.json` | 登録 |
| `snapshots/<セッションの ID>.json` | 配信のセッションで一覧を表示したときの、一覧の番号と登録の ID の対応 |
| `delivered.json` | 届けた出来事 (送信待ちに入れた出来事) と、その登録 |
| `outbox.json` | 送信待ちと、この回に出力したメッセージの対応 |
| `tracked.json` | 追跡する PR (レビューの依頼を送信待ちに入れた PR。マージを、通知が来なくても届けるため) |
| `log.jsonl` | 取得・判定・送信の結果の記録 (調べるときのため)。1 行に 1 つの JSON |
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
  },
  "started_at": "2026-11-16T06:00:00Z",
  "position": "2026-11-16T06:30:00Z",
  "etag": "W/\"1603b258f8836649eeae355c8d09800ce6b712606dad04662f57ad4b5d2cc71e\"",
  "viewer": {
    "login": "akm",
    "teams": [{"id": 3859946, "slug": "reviewers", "organization": "akm-org"}],
    "fetched_at": "2026-11-16T06:00:00Z"
  },
  "last_allocated": {"subscription_id": "0123456789ab", "created_at": "2026-11-16T05:10:00Z"},
  "schedule": {
    "state": "running",
    "job_id": "a1b2c3d4",
    "cron": "7-59/10 * * * *",
    "created_at": "2026-11-16T05:30:00Z",
    "expires_at": "2026-11-23T05:30:00Z",
    "reminders": [24],
    "stopped_at": null
  }
}
```

| キー | 値 |
| --- | --- |
| `dispatcher.session_id` | 配信のセッションの ID。サブコマンド `dispatcher set` が、環境変数 `CLAUDE_CODE_HOST_SESSION_ID` から読んで書く |
| `dispatcher.name` | 配信のセッションの名前 (サイドバーのタイトル) |
| `dispatcher.permission_mode` | 配信のセッションの権限モード。登録の返事に、保留されることを書くかの判定に使う (計画の R4) |
| `dispatcher.recorded_at` | 記録した時刻 |
| `started_at` | 最初に開始した時刻。これより前の通知と出来事は届けない (計画の R8)。U3 では、記録が無いときの最初の `tick` が書く |
| `position` | 取得の位置。取得と判定で `gh` が 1 度も失敗しなかった直近の回の、`tick` を始めた時刻 (計画の KTD5) |
| `etag` | `position` を書いた回の、通知の一覧の 1 ページ目の応答のヘッダ `Etag`。次の回のヘッダ `If-None-Match` に付ける (計画の KTD5) |
| `viewer` | 自分のログイン名 (`login`) と、所属するチーム (`teams`。チームの `id`・`slug`・Organization の `login`) と、それらを取得した時刻 (`fetched_at`)。取得し直す時機は計画の KTD4 にある。サブコマンド `dispatcher set` (スキル `dispatch` の `start` と `resume` が実行する) はこの値を消し、次の `tick` が取得し直す |
| `last_allocated` | 前の回に、最後にメッセージを割り当てた登録の ID と登録日時。次の回は、登録日時の順でこの登録の次の登録から割り当てる (計画の R13)。この登録が削除されていても、登録日時で次の登録が決まる |
| `schedule.state` | 定期の予定の状態。`running` (動いている) か `stopped` (停止した)。期限切れは書かず、`expires_at` と今の時刻を比べて判定する (計画の KTD9) |
| `schedule.job_id`・`schedule.cron` | ツール `CronCreate` が返したジョブの ID と、渡した cron の式。`stopped` では null |
| `schedule.created_at`・`schedule.expires_at` | 定期の予定を記録した時刻と、その 7 日後の期限 (ツール `CronCreate` の定期の予定は、作ってから 7 日で消える)。`stopped` では null |
| `schedule.reminders` | 期限までの残りが切ったことを、続けるかの確認として出した閾値 (`24`・`6`・`1` 時間) の配列。それぞれの確認を 1 回だけ出すため (計画の R17) |
| `schedule.stopped_at` | 停止した時刻。`running` では null |

取得の範囲の起点は、`position` の 5 分前と `started_at` の遅いほうにする。起点は、API `GET /notifications` の引数 `since` と、出来事の時刻と比べる値の両方に使う (計画の KTD5)。

`schedule` は、スキル `dispatch` が定期の予定を作り直したときにサブコマンド `schedule record` が書き、停止したときに `schedule clear` が書く。`schedule record` は、`created_at` を今の時刻、`expires_at` をその 7 日後にし、`reminders` を空にする。定期の予定を作る前の記録には `schedule` が無い。

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
      "created_at": "2026-11-16T05:10:00Z",
      "consecutive_failures": 0,
      "expired_events": 0,
      "last_expired_at": null
    }
  ],
  "last_settled_round": "fedcba987654"
}
```

| キー | 値 |
| --- | --- |
| `id` | 登録の ID。12 桁の 16 進数で、登録を足すときに乱数で作る。削除した登録の ID は使い直さない |
| `repo` | リポジトリ。GitHub の API (`GET /repos/{owner}/{repo}`) が返した `full_name` |
| `kind` | 種類 (`review_requested`・`merged`)。登録 1 件に種類 1 つ |
| `session_id`・`session_name`・`permission_mode` | 受信のセッションの ID・名前・権限モード。同じ登録を申し込み直すと、名前と権限モードを申し込みの値に変える |
| `created_at` | 登録日時。一覧の番号は、この順に振る (同じ時刻なら、ファイルの順) |
| `consecutive_failures` | 続けて届かなかった回数 (計画の R15)。3 以上の登録は「届かない登録」で、送信待ちを出力しない。同じ登録を申し込み直すと 0 に戻す |
| `expired_events`・`last_expired_at` | 送信待ちに入れてから 30 日を過ぎて消した出来事の累計と、最後に消した時刻 (計画の R15) |
| `last_settled_round` (ファイルの最上位) | 続けて届かなかった回数を最後に集計した回の ID。集計の後、`outbox.json` の対応を消す前に処理が中断しても、同じ回を 2 回数えないため |

U2 で記録した登録には `consecutive_failures`・`expired_events`・`last_expired_at` が無い。無いときは、0・0・null として扱う。

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

### `delivered.json`

```json
{
  "version": 1,
  "events": [
    {"key": "review_requested:35806844747", "subscription_id": "0123456789ab",
     "time": "2026-11-16T06:12:00Z", "recorded_at": "2026-11-16T06:20:00Z"}
  ]
}
```

| キー | 値 |
| --- | --- |
| `key` | 出来事のキー。`review_requested` は `review_requested:<timeline の出来事の ID>`、`merged` は `merged:<リポジトリ (小文字)>#<PR の番号>` |
| `subscription_id` | 届けた登録 |
| `time` | 出来事の時刻 (レビューの依頼の時刻か、マージの時刻) |
| `recorded_at` | 送信待ちに入れた時刻 |

(出来事, 登録) を送信待ちに入れたときに足す。次の回からは、同じ (出来事, 登録) を送信待ちに入れない (計画の R11・KTD6)。出来事の時刻が取得の範囲の起点より前になったものは消す。そのような出来事は、時刻で判定から除かれ、二度と送信待ちに入らないため。追跡する PR のマージ (計画の R10 の (a)) は時刻で除かないが、マージを見つけた回に追跡から外すので、同じく二度と送信待ちに入らない。配信を停止していた期間の長さに関わらず、取得の範囲に入りうる出来事の記録は残る。

### `outbox.json`

```json
{
  "version": 1,
  "pending": [
    {"subscription_id": "0123456789ab",
     "event": {"kind": "review_requested", "key": "review_requested:35806844747", "repo": "akm/claude-plugins",
               "number": 301, "title": "✨ feat: 通知を届ける", "url": "https://github.com/akm/claude-plugins/pull/301",
               "time": "2026-11-16T06:12:00Z", "requested": "akm"},
     "enqueued_at": "2026-11-16T06:20:00Z", "outputs": 1}
  ],
  "round": {
    "id": "fedcba987654",
    "tick_at": "2026-11-16T06:20:00Z",
    "messages": [
      {"message_id": "a1b2c3d4e5f6", "subscription_id": "0123456789ab",
       "event_keys": ["review_requested:35806844747"], "result": null, "reason": null}
    ]
  }
}
```

| キー | 値 |
| --- | --- |
| `pending` | 送信待ち。登録と出来事の組。`outputs` は、その出来事をメッセージに入れて出力した回数で、2 回目からの出力は送り直しになる |
| `round` | この回に出力したメッセージの対応。`result` は `ack` (届いた)・`fail` (届かなかった。理由は `reason`)・null (まだ記録されていない)。出力したメッセージが無い回は null |

- `ack` で、そのメッセージの出来事を送信待ちから消す。
- `settle` で登録ごとに集計し (`fail` があれば続けて届かなかった回数に 1 を足し、`fail` が無く `ack` があれば 0 に戻し、どちらも無ければ変えない)、`round` を null にする。`settle` が呼ばれないまま次の `tick` が始まったら、`tick` が始めに同じ集計をする (計画の KTD6)。
- 送信待ちに入れてから 30 日を過ぎた出来事は消す (計画の R15)。
- 登録を削除すると、その登録の送信待ちと `round` の対応を消す。同じ登録を申し込み直すと、その登録の `round` の対応を消す。

### `tracked.json`

```json
{
  "version": 1,
  "prs": [
    {"repo": "akm/claude-plugins", "number": 301, "enqueued_at": "2026-11-16T06:20:00Z"}
  ]
}
```

| キー | 値 |
| --- | --- |
| `repo` | PR のリポジトリ (`owner/repo`)。レビューの依頼の出来事のリポジトリの名前 |
| `number` | PR の番号 |
| `enqueued_at` | この PR へのレビューの依頼を、最後に送信待ちに入れた時刻。追跡する期間の起点 (計画の R10) |

- レビューの依頼を送信待ちに入れたときに、その PR を足す。そのリポジトリに `merged` の登録が無ければ足さない。既に追跡していれば、`enqueued_at` をその時刻にする (依頼のやり直しで、追跡する期間の起点が変わる。計画の R10)。
- `tick` のたびに、PR の状態を読む前に、そのリポジトリに `merged` の登録が無くなった PR と、`enqueued_at` から 30 日を過ぎた PR を、状態を読まずに外す (計画の KTD4)。
- 状態を読んで、マージされていたら届けて外し、マージされずに閉じていたら届けずに外す (計画の KTD4)。

### `log.jsonl`

`tick`・`ack`・`fail`・`settle` が、1 回ごとに 1 行の JSON (`time`・`action` と、結果の要約) を足す。調べるときに読むもので、スクリプトは読まない。1 MB を超えたら、新しい 1,000 行だけを残す。

## 受信のセッションの一時ディレクトリ

受信のセッションの一覧の番号と登録の ID の対応は、記録のディレクトリの外の `${TMPDIR:-/tmp}/gh-notification-dispatch/<セッションの ID>/snapshot.json` に書く (計画の R6)。様式は `snapshots/<セッションの ID>.json` と同じ。このファイルの書き込みは記録のディレクトリへの書き込みではないので、配信のセッションかの確認をしない。受信のセッションが、自分の一覧を表示して番号で削除を申し込めるようにするため。
