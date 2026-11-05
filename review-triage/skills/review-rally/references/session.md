# 開始の前提・レビューのセッションの起動・ループの状態のファイル

**このファイルが、開始の前提・ループのディレクトリの作り方・レビューのセッションの起動・ループの状態のファイル `rally.yaml` の様式の SSOT。**

## 開始の前提

新しいループを始める前に、何かを書く前 (ループのディレクトリを作る前・レビューのセッションを起動する前) に、次をすべて確認する。**満たさないものがあれば始めない。** 満たさないものをすべて、項目ごとに「直し方」を添えて一度に報告する。

| # | 確認すること | 確認の仕方 | 満たさないときの直し方 |
| --- | --- | --- | --- |
| 1 | 呼び出し元のセッションの作業ツリーから見て、`tmp/review-rally/` が git に無視されている | `git check-ignore -q tmp/review-rally/x/rally.yaml` | ファイル `.gitignore` に `tmp/` を足し、現在のブランチにコミットしてから起動し直す |
| 2 | 呼び出し元のセッションの作業ツリーから見て、`.claude/worktrees/` が git に無視されている | `git check-ignore -q .claude/worktrees/review-rally` | ファイル `.gitignore` に `.claude/worktrees/` を足し、現在のブランチにコミットしてから起動し直す |
| 3 | 呼び出し元のセッションの作業ツリーが clean である | `git status --porcelain` が空 | 出ている変更をコミットするか退避してから起動し直す |
| 4 | 記録が読める | 記録 YAML (ディレクトリは設定の `record_dir`、ファイルは `<ブランチ名>.yaml`) が無いか、YAML として読める | 無ければ新規として扱う。あるのに読めなければ、読めない理由を報告する |
| 5 | 全量の起点のブランチが決まる | [arguments.md](arguments.md) の `--base` の段落と「値の検査」 | `--base` で、使えるブランチを指定する |

呼び出し元のセッションは、worktree で動いていても、メインの作業ツリーで動いていてもよい。どちらでも手順は同じで、上の確認はすべて呼び出し元のセッションの作業ツリーについて行う。記録とループのディレクトリもこの作業ツリーにあるので、別の作業ツリーで同じブランチのループを始めると、記録が無いものとして扱われる。

## ループのディレクトリを作る

1. **ループの id を決める**: `<YYYYMMDD>-<hhmm>-<ブランチ名>`。ブランチ名の整え方は [review-request の SKILL.md](../../review-request/SKILL.md) の手順 3 の表の「ブランチ名」の行と同じ。
2. **ループのディレクトリ `tmp/review-rally/<ループの id>/` を、呼び出し元のセッションの作業ツリーに作る。** 既にあれば作らずに報告して終了する。
3. **`rally.yaml` を書く** (様式は下の「`rally.yaml`」)。`next_full` には `loop.full_first` の値を書く。`rounds` と `requests` は 0、`waiting` は `run_id`・`sent_at`・`main_head` を空、`refs`・`worktree_branches` を空の配列にする (下の例は 1 回目の依頼を送った後の状態)。`session` は空にしておき、起動の後に書く。

## 起動

**レビューのセッションの起動は、開始のターン (`/review-rally` を受けたターン) で行う。**

1. **ツール `start_session` を、次の値で呼び出す。** 失敗したら RR2。

   | 引数 | 値 |
   | --- | --- |
   | `initiation` | `user_asked` |
   | `context` | `fresh` |
   | `use_worktree` | `true` |
   | `model` | `rally.yaml` の `loop.model` |
   | `effort` | `loop.effort` |
   | `name` | `rally-<hhmm>` (ループの id の時刻) |
   | `branch_name` | `review-rally` |
   | `title` | `review-rally <ループの id> のレビュー` |
   | `prompt` | 下の「最初の指示文」 |
   | `background` | ループの目的 (このブランチのレビューを回ごとに依頼すること)・レビューのセッションは指摘を直さないこと・依頼のたびに会話が消されること |

   **`permission_mode` は渡さない。** 呼び出し元のセッションの権限モードが引き継がれ、メッセージが承認待ちにならない。

2. **ツール `get_session` で起動したセッションの値を読み、`rally.yaml` の `session` に書いてから確認する** (書く値の出所は下の「`rally.yaml`」の `session` の行。`reused` と `original_head` は次の 3 で書く)。次のどれかに当たれば RR2。アプリは起動元より上のモデルと effort を指定されてもエラーにせずに無視するので、ここで比べる。
   - `model` が指定と違う。指定が別名 (`opus` など) なら、`model` から `claude-` と版を除いた部分が別名と等しければ一致とする。指定が版を含む名前なら、`claude-` を除いた名前どうしで比べる。
   - `effort` が指定と違う。
   - `worktreePath` が無いか、次のどれかを満たさない。レビューのセッションがこの作業ツリーの HEAD を切り替えるので、メインの作業ツリーと呼び出し元のセッションの作業ツリーを除く。
     - 同じリポジトリの worktree のルートである (確認の仕方の SSOT は [review-request の SKILL.md](../../review-request/SKILL.md) の手順 1 の `--target-dir` の確認)。
     - メインの作業ツリーではない (`git -C <worktreePath> rev-parse --path-format=absolute --git-dir` が、同じオプションの `--git-common-dir` の値と違う)。
     - 呼び出し元のセッションの作業ツリーと違う。
   - `session.branch` が空である。レビューの worktree の HEAD がブランチを指していないので、依頼のメッセージの `git checkout -B` に渡す名前が決まらない。
   - `permissionMode` が呼び出し元のセッション (`get_session` の `self`) と違う。

3. **レビューの worktree が再利用されたかを控える。** アプリは、残っている worktree を再利用して新しいブランチに切り替えることがある。`git -C <worktreePath> reflog -n 2 --format=%gs` の 1 行目が `checkout: moving from <元の HEAD> to <新しいブランチ>` の形なら、再利用された worktree である。`<元の HEAD>` (detached HEAD なら SHA、ブランチならブランチ名) を `rally.yaml` の `session.original_head` に書き、`session.reused` を真にする。片付けの案内 ([stops.md](stops.md)) で使う。

### 最初の指示文

```
あなたは review-rally のレビューのセッションです。呼び出し元のセッション (<呼び出し元のセッションの id>) から、
レビューの依頼がメッセージで届きます。このターンでは何もせず、返信も送らずにターンを終えてください。
依頼が届いたら、そのメッセージの指示に従ってください。依頼の前に、この会話は消されます。
```

## `rally.yaml`

ループのディレクトリに置く、ループの状態のファイル。**書き込み元は呼び出し元のセッションだけ。** 会話が compact されても、再入の手順がこのファイルから状態を戻せるようにする。書くときは、一時名 `.rally.yaml.tmp` に書いてから `mv` で改名する。

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
  full_first: false
  full_review: true
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
requests: 1
next_full: false
waiting:
  run_id: "20261029-0905-feat-foo-1-code-review-claude-opus-5-5"
  sent_at: "2026-10-29T00:05:12Z"
  refs:
    - "claude/review-rally-1a2b3c 1a2b3c4"
    - "feat/foo 1a2b3c4"
    - "main 5d6e7f8"
  main_head: "feat/foo"
  worktree_branches:
    - "claude/review-rally-1a2b3c"
```

| キー | 内容 |
| --- | --- |
| `loop_id`・`branch`・`repo_dir` | ループの id・現在のブランチ (取り方は [round.md](round.md) の手順 5 の 3)・呼び出し元のセッションの作業ツリーのルートの実体パス |
| `state` | `active` (回している) か `stopped` (停止した) |
| `stop_reason` | `"<停止ノードの ID>: <1 行の理由>"`。`active` の間は空 |
| `loop` | ループの条件 ([arguments.md](arguments.md) で決めたもの)。`model` と `effort` は指定、`base` は全量の起点のブランチ |
| `session` | 起動したレビューのセッション。`id` は `start_session` の結果、`name` は `start_session` に渡した `name`、`worktree` は `get_session` の `worktreePath`、`model`・`effort`・`permission_mode` は `get_session` の値、`branch` は `git -C <worktreePath> branch --show-current` の出力。`branch` に `get_session` の値を使わないのは、依頼のメッセージの `git checkout -B` が動かし、片付けの案内の `git branch -D` が消すブランチなので、実際にチェックアウトされているブランチを書くためである。`reused` と `original_head` は上の「起動」の 3 |
| `rounds` | この起動で数えた回数 (J5 が見る) |
| `requests` | この起動でレビューのセッションに送った依頼の数 |
| `next_full` | 真なら、次に書く依頼文を全量にする ([round.md](round.md) の手順 1) |
| `waiting` | 結果待ちの依頼。`run_id` は依頼文の識別子、`sent_at` は依頼のメッセージを送った時刻 (UTC の秒まで)、`refs` は依頼を送る直前のリポジトリのブランチの一覧 (1 つのブランチが 1 要素)、`main_head` は依頼を送る直前のメインの作業ツリーの HEAD が指すブランチの名前 (detached HEAD なら SHA)、`worktree_branches` は依頼を送る直前にメインの作業ツリー以外の worktree がチェックアウトしていたブランチの名前の配列。結果待ちが無ければ `run_id` を空にする |
