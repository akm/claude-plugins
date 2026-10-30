# 開始の前提・レビューのセッションの起動・ループの状態のファイル

**このファイルが、`review-rally` の開始の前提、ループのディレクトリの作り方、レビューのセッションの起動と起動の直後の確認、ループの状態のファイル `rally.yaml` の様式の SSOT。** 起動の後の 1 回のレビューの流れは [round.md](round.md)、停止と片付けは [stops.md](stops.md) が SSOT。

## 開始の前提

新しいループを始める前に、次をすべて確認する。**何かを書く前 (ループのディレクトリを作る前・レビューのセッションを起動する前) に確認する。** `review-rally` 自身が書くファイル (`rally.yaml`・依頼文・結果) が原因で、作業ツリーが clean でなくなって停止することを避けるためである。

**満たさないものがあれば始めない。** 満たさないものをすべて、一度に報告する。1 つずつ報告すると、直して起動し直すたびに別の理由で始まらない。報告には、項目ごとに下の表の「直し方」を書く。

| # | 確認すること | 確認の仕方 | 満たさないときの直し方 |
| --- | --- | --- | --- |
| 1 | メインのセッションが worktree で動いていない | `git rev-parse --path-format=absolute --git-dir` と `git rev-parse --path-format=absolute --git-common-dir` が同じ | メインの作業ツリー (`git rev-parse --git-common-dir` の親) で動くセッションから起動し直す。worktree で動くセッションは、ほかの worktree への書き込みと git の操作を拒否されるので、レビューの worktree を HEAD に合わせられない |
| 2 | メインの作業ツリーから見て、`tmp/review-rally/` が git に無視されている | `git check-ignore -q tmp/review-rally/<ループの id>/rally.yaml` | ファイル `.gitignore` に `tmp/` を足し、現在のブランチにコミットしてから起動し直す。レビューの worktree は現在のブランチの HEAD に合わせるので、コミットすればレビューの worktree でも無視される |
| 3 | メインの作業ツリーから見て、`.claude/worktrees/` が git に無視されている | `git check-ignore -q .claude/worktrees/review-rally` | ファイル `.gitignore` に `.claude/worktrees/` を足し、現在のブランチにコミットしてから起動し直す。無視されていないと、レビューの worktree ができた時点で、メインの作業ツリーに `?? .claude/` (`.claude/` の下に追跡するファイルがあれば `?? .claude/worktrees/`) が出て clean でなくなる |
| 4 | メインの作業ツリーが clean である | `git status --porcelain` が空 | 出ている変更をコミットするか退避してから起動し直す。出ているのが `?? tmp/` か `?? .claude/` か `?? .claude/worktrees/` なら、2 か 3 の直し方に当たる (2・3 の確認が先に失敗しているはずなので、直し方は 2・3 の行に書いたものだけでよい) |
| 5 | 記録が読める | 記録 YAML (ディレクトリは設定の `record_dir`、ファイルは `<ブランチ名>.yaml`) が無いか、YAML として読める | 無ければ新規として扱う。あるのに読めなければ、読めない理由を報告する |
| 6 | 全量の起点のブランチが決まる | [arguments.md](arguments.md) の `--base` の段落と「値の検査」 | `--base` で、使えるブランチを指定する |

- 2 と 3 は、`git check-ignore` が存在しないパスでも判定できることを使う。2・3 の無視の出所 (`.gitignore`・`.git/info/exclude`・利用者の設定 `core.excludesFile`) は問わない。`.git/info/exclude` と `core.excludesFile` は、メインの作業ツリーとレビューの worktree で共通だからである。
- 2〜4 の組み合わせと、メインの作業ツリー・レビューの worktree に出るものは、2026-10-29 に一時リポジトリで確認した (`tmp/` と `.claude/worktrees/` のどちらを無視するか・`.claude/` の下に追跡するファイルがあるかの 6 通り)。2 と 3 がともに満たされれば、メインの作業ツリーもレビューの worktree も clean のままになる。

## ループのディレクトリを作る

1. **ループの id を決める**: `<YYYYMMDD>-<hhmm>-<ブランチ名>`。ブランチ名の整え方は [review-request の SKILL.md](../../review-request/SKILL.md) の手順 3 の表の「ブランチ名」の行と同じ。
2. **ループのディレクトリ `tmp/review-rally/<ループの id>/` を、メインの作業ツリーに作る。** 既にあれば (同じ分に 2 度始めた) 作らずに報告して終了する。
3. **`rally.yaml` を書く** (様式は下の「`rally.yaml`」)。`session` はまだ空にしておき、起動の後に書く。一時名 `.rally.yaml.tmp` に書いてから `mv` で改名する。

## 起動

**レビューのセッションの起動は、開始のターン (`/review-rally` を受けたターン) で行う。** アプリは、メッセージや自動の通知で始まったターンからはセッションを起動させないので、2 回目以降の回では起動し直せない。

1. **ツール `start_session` を、次の値で呼び出す。**

   | 引数 | 値 |
   | --- | --- |
   | `initiation` | `user_asked` (人間が `/review-rally` でループを頼んだ) |
   | `context` | `fresh` |
   | `use_worktree` | `true` |
   | `model` | レビューのセッションのモデルの指定 (`rally.yaml` の `loop.model`) |
   | `effort` | レビューのセッションの effort (`loop.effort`) |
   | `name` | `rally-<hhmm>` (ループの id の時刻。24 文字以内) |
   | `branch_name` | `review-rally` |
   | `title` | `review-rally <ループの id> のレビュー` |
   | `prompt` | 下の「最初の指示文」 |
   | `background` | ループの目的 (このブランチのレビューを回ごとに依頼すること)・レビューのセッションは指摘を直さないこと・依頼のたびに会話が消されること |

   **`permission_mode` は渡さない。** メインのセッションの権限モードが引き継がれ、メッセージが承認待ちにならない ([arguments.md](arguments.md) の「様式」)。

   `start_session` が失敗したら RR2 ([stops.md](stops.md))。

2. **ツール `get_session` で、起動したセッションの値を確認する。** 次のどれかに当たれば RR2。
   - `model` が指定と違う。指定が別名 (`opus` など) なら、`model` から `claude-` と版を除いた部分が別名と等しければ一致とする。指定が版を含む名前なら、`claude-` を除いた名前どうしで比べる。アプリは起動元より上のモデルを指定されても誤りにせずに無視するので、ここで比べないと、指定と違うモデルでレビューした回が記録に入る。
   - `effort` が指定と違う。
   - `worktreePath` が無いか、メインの作業ツリーの `.claude/worktrees/` の下にない。
   - `permissionMode` がメインのセッション (`get_session` の `self`) と違う。

3. **レビューの worktree の起動前の状態を控える。** アプリは、以前から残っている worktree を再利用して、新しいブランチに切り替えることがある (#151 の試しで 2 回起きた)。`git -C <worktreePath> reflog -n 2 --format=%gs` の 1 行目が `checkout: moving from <元の HEAD> to <新しいブランチ>` の形なら、再利用された worktree である。`<元の HEAD>` を `rally.yaml` の `session.original_head` に書き、`session.reused` を真にする。`<元の HEAD>` は、元の HEAD が detached HEAD なら SHA、ブランチを指していたならそのブランチ名である (git が reflog にそう書く)。片付けの案内で、元に戻す手順を組み立てるために使う ([stops.md](stops.md) の「片付けの案内」)。

4. **`rally.yaml` の `session` を書く** (様式は下の「`rally.yaml`」)。

### 最初の指示文

起動したセッションは、この指示文を受けて最初のターンを始める。最初のターンでは何もしない。依頼は、回ごとにメッセージで送る ([round.md](round.md) の「依頼のメッセージ」)。2 回目以降は会話を消してから送るので、レビューの規則は依頼のメッセージにすべて書き、ここには書かない。

```
あなたは review-rally のレビューのセッションです。メインのセッション (<メインのセッションの id>) から、
レビューの依頼がメッセージで届きます。このターンでは何もせず、返信も送らずにターンを終えてください。
依頼が届いたら、そのメッセージの指示に従ってください。依頼の前に、この会話は消されます。
```

最初のターンの終了の通知は、メインのセッションに届く。結果待ちの依頼が無いので、再入の手順で何もせずに終える ([round.md](round.md) の「再入の手順」)。

## `rally.yaml`

メインのセッションのループのディレクトリに置く、ループの状態のファイル。**書き込み元はメインのセッションだけ。** 会話が compact されても、再入の手順がこのファイルから状態を戻せるようにする。書き換えるときは、一時名 `.rally.yaml.tmp` に書いてから `mv` で改名する。

```yaml
loop_id: "20261029-0903-feat-foo"
branch: "feat/foo"
repo_dir: "/Users/me/src/repo"
state: active
stop_reason: ""
loop:
  review_skill: code-review
  review_args: "high"
  model: "claude-opus-5-5"
  effort: high
  max_rounds: 5
  structure_rounds: 3
  threshold: 5
  stages: []
  base: "origin/main"
session:
  id: "local_..."
  name: "rally-0903"
  worktree: "/Users/me/src/repo/.claude/worktrees/review-rally-1a2b3c"
  branch: "claude/review-rally-1a2b3c"
  model: "claude-opus-5-5"
  effort: high
  permission_mode: auto
  reused: false
  original_head: ""
rounds: 1
waiting:
  run_id: "20261029-0905-feat-foo-1-code-review-claude-opus-5-5"
  sent_at: "2026-10-29T00:05:12Z"
  timer_fires: 0
```

| キー | 内容 |
| --- | --- |
| `loop_id`・`branch`・`repo_dir` | ループの id・現在のブランチ・メインの作業ツリーのルートの実体パス |
| `state` | `active` (回している) か `stopped` (停止した)。停止したループは続けない ([SKILL.md](../SKILL.md) の前提知識) |
| `stop_reason` | `"<停止ノードの ID>: <1 行の理由>"`。`active` の間は空 |
| `loop` | ループの条件 ([arguments.md](arguments.md) で決めたもの)。`model` と `effort` は指定、`base` は全量の起点のブランチ |
| `session` | 起動したレビューのセッション。`model`・`effort`・`permission_mode` は `get_session` で確認した実際の値。`branch` は `get_session` の `branch`。`reused` と `original_head` は上の「起動」の 3 |
| `rounds` | この起動で数えた回数 (J5 が見る。数える場所は [round.md](round.md) の手順 2) |
| `waiting` | 結果待ちの依頼。`run_id` は依頼文の識別子、`sent_at` は依頼のメッセージを送った時刻 (UTC の秒まで。記録の `notes` の `review_minutes` と、再入の手順の時刻の比較の起点)、`timer_fires` は待機の通知を受けた回数 ([round.md](round.md) の「待機」)。結果待ちが無ければ `run_id` を空にする |
