# 記録

**このファイルが、記録 (管理のセッションが手元に持つファイル群) のディレクトリ・様式・扱いの正本。** モジュール `issue-dispatch/scripts/issue_dispatch/record.py` と、CLI `issue-dispatch/scripts/issue_dispatch.py` のサブコマンド `record read` / `record apply` / `record log` はこれに従う。ほかの文書はキーの名前を参照するだけで、様式と扱いを言い直さない。

**記録には、GitHub から導けないものだけを書く。** 導けるもの (下の「記録が持たないもの」) はターンのたびに GitHub から導く。記録と GitHub が矛盾する場面と、記録を失ったときに作り直す別の手順を無くすため。

## ディレクトリ

`<管理ディレクトリ>/<record_dir>/<owner>-<number>/`。`record_dir` は管理ディレクトリの設定のキー (デフォルト値はキーの表 [project-config.md](project-config.md) が持つ)。`<owner>-<number>` は設定の `project` から作る。ディレクトリを Project ごとに分けるのは、設定の `project` を後で別の Project に書き換えたときに、前の Project の記録と混ざらないようにするため。このディレクトリは git が無視する (設定は追跡し、記録は追跡しない)。

| ファイル | 書き込み元 | 内容 | 様式の正本 |
| --- | --- | --- | --- |
| `record.json` | 管理のセッション (CLI の `record apply`) | 本体。下の「`record.json`」 | この文書 |
| `actions.log` | 管理のセッション (CLI の `record log`) | GitHub への書き込みの追記専用のログ。下の「`actions.log`」 | この文書 |
| `snapshot.json` | 管理のセッション (観測の単位) | ポーリングの基準になる Project の状態の写し。作り直せるキャッシュ | [observation.md](observation.md) |
| `wait.pid` | 待機のスクリプト | 実行中の待機の PID・開始時刻・所有者のセッション ID | [observation.md](observation.md) |

**書き込み元は管理のセッション (とそのスクリプト) だけ。** 作業のセッションは記録を持たない。

## 一時名と改名

ほかのプロセス (待機のスクリプトなど) が読むファイルは、同じディレクトリの一時名 (`.` で始まり `.tmp` で終わる名前) に書いてから `os.replace` (改名) で置き換える。同じファイルシステムの中の改名は一度に起きるので、ファイルを読むプロセスが書きかけを読むことが無く、書く途中で失敗しても元のファイルが残る。`record.json` の保存はこの形で行い、`actions.log` は追記だけなので一時名を使わない。

## 種類ごとの扱い

データは「壊れていたときに何が失われるか」で種類を分け、読めない・壊れているときの振る舞いを種類ごとに決める (考え方の正本は `docs/solutions/architecture-patterns/fail-soft-by-data-class.md`)。

| 種類 | ファイル | 失われるもの | 読めない・壊れているとき |
| --- | --- | --- | --- |
| 設定 | `config.json` | 利用者が書いた数行 | デフォルト値で続けて警告する ([project-config.md](project-config.md)) |
| 記録 | `record.json` | 割り当ての意図・質問と回答・フラグ (作り直せない) | 中断して知らせ、新規として扱わない (`Corrupt`)。無いときだけ新規 |
| スナップショット | `snapshot.json` | 無い (Project から導出し直せる) | 作り直して 1 行報告する |
| ログ | `actions.log` | 書き込みの履歴 | 読まない (追記だけ)。壊れた行は、読み込む処理が飛ばす |
| 宣言 (エージェントが組み立てる入力) | Issue のコメント | その 1 件 | 形を検査して差し戻す ([issue-format.md](issue-format.md)) |

壊れた記録を新規として扱わないのは、新規の記録を保存すると元の記録 (割り当ての意図や質問の回答) を失うため。壊れていれば利用者に知らせ、利用者がバックアップから戻すか消すかを決める。

## `record.json`

トップレベルのキー:

| キー | 内容 |
| --- | --- |
| `project` | `owner/number`。設定の `project` と違えば壊れているとみなす (別の Project の記録を読まないため) |
| `manager` | 管理のセッション (下の表)。開始前は null |
| `sessions` | 作業のセッションの ID → 下の表 |
| `items` | 項目 (`owner/repo#番号`) → 下の表。項目が属する作業のセッションは記録に持たず、Project のフィールド `Agent session ID` から導く |
| `opt_in_proposals` | リポジトリ (`owner/repo`) → 第三者による本文の編集の確認のオプトインの提案 (`proposed_at` 提案した時刻・`answer` 回答。未回答は null) |
| `notices` | 項目に紐づかない「1 回だけ報告する」通知のフラグ。通知の名前 → 報告した時刻 |
| `questions` | 質問の ID → 下の表 |

`manager`:

| キー | 内容 |
| --- | --- |
| `id` / `name` | 管理のセッションの ID と名前 |
| `started_at` | 開始した時刻 |
| `state` | `active` (動いている)・`stopped` (停止)・`ended` (終了) |
| `stop_reason` | 停止の理由。`active` では null |
| `exchanges_since_input` | 利用者の最後の入力からの送受の数 (R9)。利用者の入力で 0 に戻す |

`sessions` の要素 (作業のセッション):

| キー | 内容 |
| --- | --- |
| `name` / `repo` / `worktree` | 名前・リポジトリ (`owner/repo`)・作業ツリーの絶対パス |
| `seen_state` | 前のターンに `ListAgents` で見た状態 (R10 の `waiting-for-user` の判断に使う)。未確認は null |
| `waiting_since` | 待機中なら待機を始めた時刻。待機中でなければ null |
| `refused` | 合図を受信拒否された最初の記録 (`at` 時刻・`signal` 合図の種類)。無ければ null。以後の送り方と戻し方は、スキル `issue-work` と `issue-dispatch` の手順で決める (Open Questions の R9 (2) の項) |

`items` の要素 (項目):

| キー | 内容 |
| --- | --- |
| `intent` | 割り当ての書き込みの意図 (`session_id`・`session_title`・`status` に書く予定の値、`assignment` 割り当ての番号、`at` 決めた時刻)。無ければ null。Project の値が意図と一致すれば自分の書き込みと判定する (再入のときに、途中まで書いた割り当てを継続するため。R24) |
| `notified_at` | 合図 `assigned` を送ったことを示すフラグ (時刻)。意図があってフラグが無い項目は、再入で合図を送り直す候補。同じフラグを 2 度付けても最初の時刻のまま。いつ付くかの正本は [flow.md](flow.md) |
| `resend_count` | 合図の再送の回数。再送は項目ごとに通算 1 回で、1 回再送した後は再送しない (R24)。再送の前に回数を確認し、再送したら数える |
| `conflict_choice` | 競合の可能性があるときに選んだ扱い。判定 ([flow.md](flow.md) の「判定」) は書かず、質問 `conflict` の回答 (相手ごと) で代える。消すかは U21 で決める |
| `reported` | 報告済みのフラグ。報告の種類 (人の変更・割り当てない理由など) → 最初に報告した時刻 |
| `body_edit_confirmed_at` | 利用者が確認した本文の最新の編集の時刻 (KD17) |

`questions` の要素 (質問):

| キー | 内容 |
| --- | --- |
| `item` / `kind` | 質問の対象の項目と種類 |
| `options` | 選択肢の配列。要素は空でない文字列で、重複しない (回答は選択肢と同じ文字列で照合する)。空なら自由回答 |
| `asked_at` | 質問した時刻 |
| `answer` / `answered_at` | 回答と回答した時刻。未回答はどちらも null。撤回した質問 (`withdraw`) は `answer` が null で `answered_at` がある |
| `subject` | 質問の対象 (任意。無ければ null)。同じ項目・種類でも対象が違えば別の質問。判定の質問が使う: 資源の名前、相手の宣言 (`<相手の項目>:<相手の宣言の ID>`)、パス付き (`<相手の項目>:<相手の宣言の ID>:<パス>`)。形の正本は [flow.md](flow.md) の「判定」 |

質問の種類 (`kind`) と選択肢 (`options`) の一覧は、質問を導く文書 [flow.md](flow.md) が持つ (項目の状態の質問は「ターンで行うこと」の質問の表、判定の質問は「判定」の質問の表)。回答に従う処理も同じ文書が決める (項目の状態の質問は U16・U21 で決める)。記録は種類の一覧を持たず、`answer` は質問に書かれた `options` と照合する。

### 操作 (`record apply`)

`record.json` は、操作の配列を標準入力で受ける CLI の `record apply` で更新する。1 ターンの複数の更新を 1 回の保存にまとめ、**1 つでも誤りがあれば何も適用せず、誤りを返す** (部分的に適用すると、意図とフラグの対応が崩れるため)。各操作は `op` と、種類ごとのキーを持つ。項目のキー `item` は `owner/repo#番号` の形。時刻は呼び出し元が書く (ISO 8601、UTC)。

| `op` | キー | 何をするか |
| --- | --- | --- |
| `set_manager` | `id`・`name`・`started_at` | 管理のセッションを `active` で記録する。送受の数は 0 |
| `set_manager_state` | `state`・`stop_reason` (任意) | 状態を変える。`active` にすれば停止の理由は消える |
| `count_exchange` | | 送受の数を 1 増やす |
| `reset_exchanges` | | 送受の数を 0 にする (利用者の入力) |
| `set_session` | `id`・`name`・`repo`・`worktree` | 作業のセッションを記録する (あれば名前などを書き換える) |
| `set_session_state` | `id`・`state` | `ListAgents` で見た状態を記録する |
| `set_waiting` / `clear_waiting` | `id`・`since` / `id` | 待機中の時刻を書く / 消す |
| `set_refused` | `id`・`at`・`signal` | 受信拒否を記録する (最初の 1 回だけ残す) |
| `set_intent` | `item`・`session_id`・`session_title`・`status`・`assignment`・`at` | 割り当ての意図を書く。フラグ `notified_at` と再送の回数は消える |
| `clear_intent` | `item` | 意図とフラグと再送の回数を消す (割り当ての解除・完了) |
| `mark_notified` | `item`・`at` | 合図 `assigned` を送ったことを示すフラグを付ける (意図が無ければ誤り。2 度目は時刻を変えない) |
| `count_resend` | `item` | 再送の回数を 1 増やす (意図が無ければ誤り) |
| `set_conflict_choice` | `item`・`choice` | 競合の可能性があるときに選んだ扱いを書く |
| `mark_reported` | `item`・`kind`・`at` | 報告済みのフラグを付ける (2 度目は時刻を変えない) |
| `set_body_edit_confirmed` | `item`・`at` | 利用者が確認した本文の編集の時刻を書く |
| `set_notice` | `key`・`at` | 項目に紐づかない通知の報告済みのフラグを付ける (2 度目は時刻を変えない) |
| `set_opt_in` | `repo`・`proposed_at`・`answer` (任意) | オプトインの提案と回答を書く |
| `ask` | `question_id`・`item`・`kind`・`options`・`at`・`subject` (任意) | 質問を記録する (同じ ID の質問が既にあれば誤り。回答を消さないため。既にある質問は `record read` の `questions` で見る) |
| `answer` | `question_id`・`answer`・`at` | 回答を書く (質問が無い・選択肢に無い回答は誤り) |
| `withdraw` | `question_id`・`at` | 質問を撤回する (回答待ちの理由が無くなったとき。回答は null のまま `answered_at` を書くので、未回答には数えない。回答のある質問は撤回できない) |

## `actions.log`

GitHub への書き込み (割り当て・Status・フィールド・コメント・`blockedBy`・ラベル) を、1 行 1 JSON で追記する。何を書いたかを後から辿るためのもので、処理の判断には使わない。1 件のキーは次の 6 つで、すべて必須 (値が無ければ null)。

| キー | 内容 |
| --- | --- |
| `at` | 書き込んだ時刻 |
| `kind` | 書き込みの種類 |
| `target` | 対象 (項目 `owner/repo#番号` など) |
| `before` / `after` | 書き込みの前後の値 |
| `reason` | 理由 (割り当ての番号・判定の結果など) |

## CLI

| サブコマンド | 入力 | 出力 (JSON) |
| --- | --- | --- |
| `record read --dir <管理ディレクトリ>` | 設定の `project` と `record_dir` | `status` (`ok` / `new` 無いので新規 / `corrupt` / `config-error`)・`path`・`record`・`errors` |
| `record apply --dir <管理ディレクトリ>` | 標準入力に操作の配列 | `status` (`ok` / `rejected` 操作の誤り / `corrupt` / `config-error`)・`path`・`applied` (適用した操作の数)・`errors` |
| `record log --dir <管理ディレクトリ>` | 標準入力に 1 件 | `status` (`ok` / `rejected` / `config-error`)・`path`・`errors` |

終了コードは、JSON を出せれば 0 (誤りは JSON の `errors`)。`corrupt` のときは何も保存しない。

## 記録が持たないもの

次のものは GitHub から導けるので記録に持たず、ターンのたびに導く (導く単位は項目の状態の文書 [flow.md](flow.md))。

- 宣言 (Issue のコメント)、資源の使用 (ラベルと宣言)、自分が足した `blockedBy`、マージ待ちの小さな PR、Status の復帰先
- Issue の URL・タイトル・本文、項目が属する作業のセッション (フィールド `Agent session ID`)
