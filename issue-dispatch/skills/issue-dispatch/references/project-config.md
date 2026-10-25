# 設定

issue-dispatch は、管理ディレクトリ (管理のセッションが動くディレクトリ) とリポジトリの、同じ相対パス `.claude/akm-claude-plugins/issue-dispatch/config.json` を読む。ファイル名は同じで、キーで役割が分かれる。**この文書が、設定のキーと「未設定」のときの扱いの正本。** 読み込みはモジュール `scripts/issue_dispatch/config.py` が行い、CLI の `config read` で読める (入出力は JSON)。

[review-triage](https://github.com/akm/claude-plugins/tree/main/review-triage) と同じ流儀で、プラグインは共通の規則を持ち、リポジトリ固有の宣言だけをこのファイルに書く。

## 様式

管理ディレクトリの設定:

```json
{
  "project": { "owner": "akm", "number": 3 },
  "record_dir": "tmp/issue-dispatch",
  "poll_minutes": 3,
  "wait_minutes": 60,
  "declare_deadline_minutes": 60,
  "third_party_edit_check": ["akm/example-public"],
  "resources": {
    "dev-port": { "capacity": 1, "reserve": "on_declare" }
  },
  "repositories": {
    "akm/example": "/Users/me/src/example"
  }
}
```

リポジトリの設定:

```json
{
  "project": { "owner": "akm", "number": 3 },
  "files": [
    { "pattern": "dist/**", "kind": "generated" },
    { "pattern": "docs/**/*.md", "kind": "unstable", "unit_notation": "markdown-heading", "split_reference": "file", "mergeable": true }
  ],
  "protected_paths": ["infra/prod/"],
  "hooks": { "guard_other_worktrees": true },
  "poll_minutes": 3,
  "wait_minutes": 60
}
```

## キーの表

| キー | 置き場 | 意味 | 未設定のときの扱い |
| --- | --- | --- | --- |
| `project` | 管理 / リポジトリ | Project の `owner` (文字列) と `number` (1 以上の整数)。管理ディレクトリでは、管理のセッションが読む Project。リポジトリでは、`issue-work` が管理のセッションの規約の名前を導くのに使う (1 つだけ書く。ほかの Project の作業をさせるときは `issue-work` の引数 `--manager` で名前を渡す) | 管理ディレクトリでは**必須**で、無ければ `config read` がエラーを返し、管理のセッションは Project の owner と番号を利用者に質問して設定の雛形を示す。リポジトリでは省略できる (`issue-work` は開始時に利用者に質問する) |
| `record_dir` | 管理 | 記録の置き場 (管理ディレクトリからの相対パス)。記録の契約は [records.md](records.md) | `tmp/issue-dispatch` |
| `poll_minutes` | 管理 / リポジトリ | 管理ディレクトリでは、管理のセッションのポーリングの間隔 (分)。リポジトリでは、作業のセッションの待機 (`wait-assignment`・`wait-decision`) の間隔 (`--interval`) | 3 |
| `wait_minutes` | 管理 / リポジトリ | 管理ディレクトリでは、管理のセッションの待機の期限 (分)。リポジトリでは、作業のセッションの待機の期限 (`--minutes`) | 60 |
| `declare_deadline_minutes` | 管理 | 割り当てから着手の宣言までの期限 (分)。過ぎると `Agent stuck state` に `deadline-passed` を書く | 60 |
| `third_party_edit_check` | 管理 | 第三者による Issue の本文の編集を割り当ての前に確認するリポジトリ (`owner/repo`) の配列。管理のセッションが承認を得て `config add-edit-check` で足す | 空 (どのリポジトリも確認しない) |
| `resources` | 管理 | 資源の名前ごとの属性 (`capacity`・`reserve`・`when_busy`・`release_undeclared` など)。属性の意味とデフォルト値の正本は [resources.md](resources.md)。1 つの資源を複数のリポジトリの Issue が使うので、Project 全体の設定である管理ディレクトリに書く | 空 (どの資源も、すべての属性がデフォルト値) |
| `repositories` | 管理 | リポジトリ (`owner/repo`。大文字と小文字を区別せず、綴りだけ違うキーは後のものを警告して使わない) ごとの、worktree を作った元の clone のディレクトリの絶対パス。管理のセッションがリポジトリの設定を読むのに使う (読み方の正本は [repositories.md](repositories.md))。マシンごとに違う値なので管理ディレクトリに書く | 空 (どのリポジトリの設定も読めないので、管理のセッションは宣言の判定を止めてパスの設定を頼む) |
| `files` | リポジトリ | パスのパターンごとの、ファイルの種類の規則の配列 (下の「`files` の規則の書き方」)。デフォルトの表より先に照合する | 空 (デフォルトの表だけと照合する。どちらのパターンにも一致しないパスは `unknown-content`) |
| `protected_paths` | リポジトリ | フックが書き込みを拒否するパス (リポジトリのルートからの相対パス) の配列 | 空 |
| `hooks.guard_other_worktrees` | リポジトリ | ほかの worktree と `protected_paths` への操作を拒否するフックを有効にするか (真偽値) | 設定ファイルがあれば真。設定ファイルが無いリポジトリではフックは何もしない |

**役割に無いキー (管理ディレクトリの設定に `files` を書くなど) と、表に無いキーは、使わずに警告する。**

## 「未設定」の定義 (正本)

**キーが「未設定」とは、キーが無いことだけを指す。** 整数のキー (`poll_minutes`・`wait_minutes`・`declare_deadline_minutes`) の空文字列は未設定と読まず、値の誤りとして扱う。

**値の誤り (型が違う・整数が 1 未満・配列の要素の形が違う) は、そのキーをデフォルト値にして続行し、警告を返す。** 止めない。`poll_minutes` が `wait_minutes` 以上のときは、2 つとも値の誤りとして警告し、両方をデフォルト値に戻す (間隔が期限以上だと、待機が 1 回読むごとに期限で終わって送り直しが増えるため)。警告は、管理のセッションの開始時の検査と `repo-preflight` の報告に出す。

**読めない設定 (JSON として読めない・最上位がオブジェクトでない) は、エラーとして返し、デフォルト値で続ける。** `config add-edit-check` は読めない設定を上書きしない。

`project` の形の誤り (owner が無い・number が整数でない) は、管理ディレクトリではエラー (デフォルト値が無いため)。

## `files` の規則の書き方

要素は `pattern` と `kind` が必須で、`unit_notation`・`split_reference`・`mergeable` は省略できる。**`kind` と省略できる属性の意味と、パターンの照合の規則の正本は [file-kinds.md](file-kinds.md)** — この文書は様式と、読み込むときにそろえる表記だけを定める。

| キー | 必須 | 内容 |
| --- | --- | --- |
| `pattern` | ✓ | パスのパターン (リポジトリのルートからの相対パス) |
| `kind` | ✓ | ファイルの種類 (値の一覧は file-kinds.md) |
| `unit_notation` | | 節の表記とキーの深さ |
| `split_reference` | | 分けたときの参照のされ方 (`directory` / `file`) |
| `mergeable` | | マージできるか (真偽値) |

**読み込むときに `pattern` の表記をそろえる**: `.` の区切り (先頭の `./` と途中の `/./`) を取り除き、`//` を `/` にする。末尾の `/` は取り除かない (`posixpath.normpath` を使わないのは、`dist/` を `dist` という名前のファイルだけに一致するパターンに変えてしまうため)。**絶対パス (`/` で始まる) と `..` を含むパターンは、その規則を使わずに警告する** (ルートの外を指しうるため)。`pattern` か `kind` の無い要素と、`kind` が規則に書ける種類 (file-kinds.md の段 2〜6) でない要素も、使わずに警告する。

| 書いた値 | そろえた後 |
| --- | --- |
| `./dist/**` | `dist/**` |
| `dist//**` | `dist/**` |
| `docs/./a.md` | `docs/a.md` |
| `docs/` | `docs/` (そのまま) |
| `/dist/**` | 使わない (警告) |
| `../x/**` | 使わない (警告) |

## CLI

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_dispatch.py" config read --dir <ルート> --role manager
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_dispatch.py" config read --dir <ルート> --role repo
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_dispatch.py" config add-edit-check --dir <管理ディレクトリ> --repo <owner/repo>
```

`config read` の出力は `{"status", "path", "role", "config", "warnings", "errors"}` で、`status` は `ok` / `missing` (設定ファイルが無い) / `unreadable` (読めない)。`config` はデフォルト値を当てた後の値。`warnings` と `errors` の要素は `{"key", "message"}`。JSON を出せたときの終了コードは、`errors` の有無によらず 0。0 以外は Python 自身の失敗 (捕まえていない例外の 1・引数の誤りの 2) で、呼び出す側は停止の条件として扱う。
