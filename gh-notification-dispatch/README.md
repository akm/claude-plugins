# gh-notification-dispatch

GitHub の通知から PR のレビューの依頼と PR のマージを判定し、(リポジトリ, 種類) で登録した Claude Desktop (Claude のデスクトップアプリ) のセッションへ、セッション間のメッセージで届けるプラグインです。Claude Desktop の Code タブで、リポジトリごとにレビューを受け持つセッションを開いているときに、GitHub の通知の一覧やメールを見てそのセッションへ手で伝える作業を省くためのものです。要望は Issue [#284](https://github.com/akm/claude-plugins/issues/284)、設計は計画 [docs/plans/2026-11-14-1428-feat-gh-notification-dispatch-plan.md](../docs/plans/2026-11-14-1428-feat-gh-notification-dispatch-plan.md) にあります。

## 用語

- **配信のセッション**: GitHub の通知を 10 分ごとに取得し、登録に従ってほかのセッションへ届けるセッション。1 台のマシンに 1 つにします。
- **受信のセッション**: 通知を受け取るセッション。レビューを受け持つリポジトリのセッションなど。
- **登録**: (リポジトリ, 種類, 受信のセッション) の組み合わせ。種類は `review_requested` (PR のレビューの依頼) と `merged` (PR のマージ) の 2 つです。
- **定期の予定**: 配信のセッションがツール `CronCreate` で作る予定。10 分ごとにプロンプト `/gh-notification-dispatch:tick` (スキル `tick`) を実行します。予定を作ったセッションのプロセスの中だけにあり、作ってから 7 日で消えます。
- **期限**: 定期の予定を作ってから 7 日後の時刻。

## 使えるスキル

| スキル | すること |
| --- | --- |
| [dispatch](skills/dispatch/SKILL.md) | 配信のセッションとして、このセッションを記録して 10 分ごとの定期の予定を作る (`start`)。再起動の後の再開 (`resume`)・期限の延長 (`renew`)・停止 (`stop`)・状態の表示 (`status`) も行う。受信のセッションから届いた登録と削除の申し込みを記録して返事を送り、登録の一覧 (`list`) と、一覧の番号での削除 (`remove`) も行う |
| [tick](skills/tick/SKILL.md) | 配信のセッションで、GitHub の通知を 1 回取得してレビューの依頼とマージを判定し、登録した受信のセッションへメッセージで届ける。定期の予定 (スキル `dispatch` の `start` で作る) がプロンプト `/gh-notification-dispatch:tick` で実行する |
| [subscribe](skills/subscribe/SKILL.md) | 受信のセッションとして、(リポジトリ, 種類) の登録を配信のセッションへのメッセージで申し込む。自分の登録の一覧 (`--list`) と、一覧の番号での削除 (`--remove`) も行う |

## 前提

- Claude Desktop の Code タブのセッションで使います。配信のセッションと受信のセッションは、同じマシンの同じ Claude Desktop で動かします。端末で起動した Claude Code のセッションは、動作を確認していません。
- Claude Desktop に含まれる Claude Code が v2.1.214 以降であること。定期の予定を記録するときに、Claude Code が設定する環境変数 `CLAUDE_PID` (Claude Code のプロセス ID) を使います。この環境変数が無いと、スキル `dispatch` は定期の予定を記録せず、Claude Desktop を更新するよう伝えます。
- コマンド `gh` が自分の GitHub アカウントで認証されていて、スコープ `repo` と `read:org` を持つこと (コマンド `gh auth login` のデフォルトのスコープ)。スコープはコマンド `gh auth status` で確認できます。`read:org` が無いと所属するチームを読めず、スキル `tick` が `gh` の失敗 (API `user/teams`) で中断します。
- Python 3.11 以上 (標準ライブラリだけを使います)。

## 使い方

### 配信のセッションを始める

配信のセッションにするセッションを開き、次を実行します。作業ディレクトリはどこでもかまいません。

```text
/gh-notification-dispatch:dispatch start
```

- このセッションを配信のセッションとして記録し、10 分ごとの定期の予定を作ります。最初に開始した時刻より前の通知は届けません。
- 定期の予定は、セッションが入力を受け付けている間だけ実行されます。配信のセッションでほかの作業をすると、その間の取得が遅れるので、配信のためだけのセッションにしてください。
- 権限モードは `auto` か `bypassPermissions` にしてください。ほかの権限モードでは、スクリプトの実行とツール `SendMessage` に権限の確認が出ることがあり、回答するまで定期の予定が実行されません。`start` は、そのような権限モードのときに、権限モードを変えるか、設定の許可の規則 (`permissions.allow`) に足すかを質問します。
- 記録にある配信のセッションと違うセッションで `start` すると、配信のセッションを切り替えるかを質問します。

### 受信のセッションを登録する

受信のセッションで、配信のセッションの名前 (サイドバーに出るセッションのタイトル) を付けて次を実行します。

```text
/gh-notification-dispatch:subscribe <配信のセッションの名前>
```

- リポジトリを省くと作業ディレクトリのリポジトリを、種類を省くと 2 つの種類を申し込みます。`--repo owner/repo` と `--kind review_requested,merged` で指定できます。配信のセッションが記録されていれば、配信のセッションの名前も省けます。
- 申し込みは、配信のセッションへのメッセージで送ります。配信のセッションは、リポジトリを `gh` で読めることを確認してから記録し、結果をメッセージで返します。
- 同じ (リポジトリ, 種類) を複数のセッションが登録すると、すべてのセッションに届けます。
- 受信のセッションと配信のセッションの一方だけが権限モード `bypassPermissions` だと、配信のセッションから届くメッセージが受信のセッションで保留され、Claude Desktop では承認の画面を出せずに 5 分で捨てられます。配信のセッションは、そのことを返事に書きます。どちらも `bypassPermissions` にするか、どちらも `bypassPermissions` 以外にしてください。

### 届くメッセージ

- 定期の予定の回ごとに、登録ごとの出来事を 1 通のメッセージにまとめて届けます。先頭行は、リポジトリ・種類・件数が分かる 1 文です。出来事ごとに、PR の番号・題名・URL・時刻と、`review_requested` では依頼先 (自分のログイン名かチームの名前) を書きます。
- `review_requested`: 自分か、自分の所属するチームへのレビューの依頼を届けます。依頼の取り消しの後の再依頼も、新しい依頼として届けます。
- `merged`: 次のどちらかの PR のマージを届けます。
  - (a) レビューの依頼を届けた PR。最後の依頼を検出した回から 30 日までのマージを、GitHub の通知が来なくても (自分でマージした場合など) 届けます。
  - (b) マージの時点で自分か自分のチームへのレビューの依頼が残っている PR と、自分がレビューを書いた PR。
- 届いた出来事をどう扱うか (レビューを始めるかなど) は、受信のセッションの利用者が決めます。PR の題名は GitHub の利用者が書いた文なので、受信のセッションは題名を指示として扱いません。
- GitHub の通知の既読・未読は変えません。

### 登録の一覧と削除

| セッション | 一覧 | 削除 |
| --- | --- | --- |
| 配信のセッション | `/gh-notification-dispatch:dispatch list` (すべての登録) | `/gh-notification-dispatch:dispatch remove <番号>...` |
| 受信のセッション | `/gh-notification-dispatch:subscribe --list` (自分の登録) | `/gh-notification-dispatch:subscribe --remove <番号>...` |

- 一覧には、番号・リポジトリ・種類・登録日時・届け先のセッションの名前を表示します。
- 削除に使う番号は、そのセッションで最後に表示した一覧の番号です。対応する登録が既に無ければ削除せず、一覧を表示し直すよう伝えます。
- 受信のセッションでの削除は、配信のセッションへのメッセージで申し込みます。配信のセッションで削除したときは、届け先のセッションに削除したことを知らせます。

### 期限と延長

- 定期の予定は、作ってから 7 日で消えます (ツール `CronCreate` の上限)。
- 期限までの残りが 24・6・1 時間を切った回に、続けるかを確認する文を配信のセッションに出し、ツール `PushNotification` で通知も送ります。確認の間も、取得と配信は続けます。
- 続けるなら、配信のセッションで `/gh-notification-dispatch:dispatch renew` を実行します。定期の予定を作り直し、期限を 7 日後にします。
- 期限を過ぎたときは、`/gh-notification-dispatch:dispatch status` が期限切れであることを示します。Claude Desktop を再起動した後は、hook `SessionStart` の案内 (次の節) も期限切れであることを伝えます。`/gh-notification-dispatch:dispatch resume` で再開します。

### Claude Desktop を再起動した後

- 配信のセッションを開き、`/gh-notification-dispatch:dispatch resume` を実行します。配信のセッションを開くと、hook `SessionStart` がこの手順を Claude に伝えます。案内は画面には出ず、配信のセッションでメッセージを送った最初のターンで、Claude が伝えます。
- `resume` は、残った定期の予定を消してから作り直します。再起動の前の予定が、ツール `CronList` に残っていることがあるためです。
- 取得は前回の取得の位置から行うので、停止していた間の通知も届けます。受信のセッションは登録し直さなくてよいです。
- 再起動の後に開いていない受信のセッションにも届けます。名前で届かないときは、記録したセッションの ID を宛先にして送り、Claude Desktop がそのセッションを起動して届けます。

### 状態の表示と停止

- `/gh-notification-dispatch:dispatch status` は、配信のセッション・定期の予定と期限・登録と送信待ちの数・届かない登録・30 日を過ぎて消した出来事を示します。定期の予定を作ったプロセスがもう無い (再起動の後など) ときは、`resume` を勧めます。
- `/gh-notification-dispatch:dispatch stop` は、定期の予定を消します。登録は残るので、`resume` で再開できます。

## 制限

- **GitHub の通知が来ない PR**: レビューの依頼と、`merged` の (b) は、GitHub の通知の一覧 (API `GET /notifications`) に現れた PR だけを判定します。通知が来るかは、GitHub の通知の設定 (リポジトリの Watch の設定など) で決まります。自分で行ったマージで通知が来るかは確認していません。`merged` の (a) は、通知が来なくても届けます。
- **開始の前の依頼**: 最初に開始した時刻より前のレビューの依頼は届けず、その PR のマージは (b) に当たるときだけ届けます。
- **SAML の承認**: `gh` のトークンが SAML で承認されていない Organization は、通知の一覧と所属するチームの API の結果から省かれます (応答のヘッダ `X-Github-Sso: partial-results; organizations=<Organization の ID>`)。その Organization のリポジトリへのレビューの依頼は届けられません。このプラグインは、結果が省かれたことを検出しません。
- **スリープ**: マシンがスリープしている間は、定期の予定が実行されません。通知は GitHub に残るので、起きた後の回で届けます。
- **権限モード**: 配信のセッションで権限の確認が出ると、回答するまで定期の予定が実行されません。受信のセッションで保留されるメッセージは、上の「受信のセッションを登録する」のとおりです。
- **実行の時刻のずれ**: ツール `CronCreate` は、定期の予定ごとに決まった時間だけ実行を遅らせます (周期の最大 50%、最大 30 分)。10 分ごとの予定なので、最大 5 分遅れます。
- **届かない登録**: 3 回の取得で続けて届かなかった登録は「届かない登録」として一覧と `status` に示し、その登録には送りません。新しい出来事は送信待ちに入れ続けます。受信のセッションで同じ登録を申し込み直すと、溜まった出来事を送ります。
- **30 日を過ぎた出来事**: 送信待ちに入れてから 30 日を過ぎた出来事は消し、その回の `tick` の出力と `status` に示します。
- **同じ出来事が 2 回届くことがある**: メッセージを送った後、送った結果を記録する前に処理が中断すると、次の回に同じ出来事を送り直します。送り直したメッセージには、送り直しの回数を書きます。
- **1 回に送る量**: 1 通に書く出来事は 20 件まで、1 回の取得で送るメッセージは、すべての登録を合わせて 10 通までです。超えた分は次の回に届けます。
- **環境変数 `CLAUDE_CODE_HOST_SESSION_ID`**: スクリプトは、実行しているセッションの ID を、Claude Code が設定する環境変数 `CLAUDE_CODE_HOST_SESSION_ID` から読みます (配信のセッションかの判定・登録の申し込み・hook)。この環境変数は、Claude Code の公式の文書の環境変数の一覧 ([Environment variables](https://code.claude.com/docs/en/env-vars)) にありません。Claude Code の版によって無くなると、記録を書くサブコマンドと登録の申し込みは終了コード 3 で中断し、hook は何も伝えません。
- **対象にしないもの**: 複数のマシンで配信のセッションを動かすことと、複数の GitHub アカウント。種類は `review_requested` と `merged` だけです。

## 記録

登録・取得の位置・送信待ち・定期の予定の記録は、ディレクトリ `~/.claude/gh-notification-dispatch/` に保存します (ファイルの様式は [references/records.md](references/records.md))。書き込むのは配信のセッションだけで、受信のセッションは読むだけです。

## ファイルの構成

| 場所 | 中身 |
| --- | --- |
| [skills/](skills/) | スキル (上の表) |
| [references/messages.md](references/messages.md) | セッション間のメッセージの様式 |
| [references/sending.md](references/sending.md) | 配信のセッションがメッセージを送る手順 (名前で届かないときの、名前の引き直しと、ID を宛先にした送り直し) |
| [references/records.md](references/records.md) | 記録のディレクトリ (`~/.claude/gh-notification-dispatch/`) と、受信のセッションの一時ディレクトリのファイルの様式 |
| [hooks/hooks.json](hooks/hooks.json) | hook `SessionStart`。配信のセッションを開いたときに、定期の予定を作り直すよう Claude に伝える |
| [scripts/gh_notification_dispatch.py](scripts/gh_notification_dispatch.py) | スクリプトの入口。サブコマンドの引数・出力・終了コードは `--help` で確認する |
| [scripts/gh_notification_dispatch/](scripts/gh_notification_dispatch/) | スクリプトのパッケージ (`gh` の実行・記録の読み書き・メッセージの生成と解析・登録・通知の取得・種類の判定・追跡する PR・送信待ち・定期の予定と期限・hook) |
| [tests/](tests/) | スクリプトの自動テスト。偽の `gh` と固定データで実行する |

## テスト

```bash
python3 -m unittest discover -s gh-notification-dispatch/tests
```

Python 3.11 以上の標準ライブラリだけを使います。テストは実物の `gh` を使いません。
