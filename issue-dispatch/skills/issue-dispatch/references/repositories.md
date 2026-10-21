# リポジトリの設定の読み方

**このファイルが、リポジトリの設定の読み方の正本。** 管理のセッションは、管理ディレクトリの設定 `repositories` ([project-config.md](project-config.md)) に書かれた clone のパスから、既定のブランチの内容のリポジトリの設定を git で読む。モジュール `issue-dispatch/scripts/issue_dispatch/repo.py` と、CLI `issue-dispatch/scripts/issue_dispatch.py` のサブコマンド `repo name` はこれに従う。ほかの文書は「読めない」の理由の名前を参照するだけで、確かめ方を言い直さない。

管理のセッションがローカルの clone を読むのは、管理ディレクトリで動いていてリポジトリの中にいないが、作業のセッションと同じマシンで動くため。読むのは、作業のセッションの worktree ではなく、worktree を作った元の clone のパス (worktree は Issue ごとに作られて消え、作業中のブランチの変更が見えるため)。ファイルをそのまま読まずに git で既定のブランチの内容を読むのは、checkout しているブランチや編集中の内容に左右されないため。最後に fetch した時点の内容になる。

**管理のセッションは fetch しない。** 利用者のリポジトリに書き込み、作業のセッションの git の操作とぶつかることを避けるため。設定の内容の解釈 (キー・デフォルト値・警告) は [project-config.md](project-config.md) の規則で、モジュール `config` の関数 `load_text` が行う。

## 読む手順

1. 設定 `repositories` にそのリポジトリ (`owner/name`) のパスがあるか。キーは大文字と小文字を区別せずに引く (GitHub のリポジトリ名は区別しないため。綴りだけ違うキーが 2 つあれば、設定の読み込みが後のものを警告して使わない)。
2. パスが clone のルートで、`origin` がそのリポジトリを指し、参照 `origin/HEAD` があるか (下の「読めない」の理由の順に確かめる)。
3. `git ls-tree --name-only refs/remotes/origin/HEAD -- <設定ファイルのパス>` で、既定のブランチに設定ファイルがあるかを確かめる。無ければ「無い」(設定が無いリポジトリと同じく、デフォルト値で続ける)。
4. あれば `git show refs/remotes/origin/HEAD:<設定ファイルのパス>` で読み、`config.load_text` で解釈する。JSON として読めなければ「読めない」(理由 `config-unreadable`)。

`ls-tree` で有無を確かめてから `show` で読むのは、`git show` だけでは参照が無いときもファイルが無いときも同じ終了コード 128 で失敗し、「無い」と「読めない」を見分けられないため。

結果は 3 つに分ける。

| 結果 | 意味 | 管理のセッションの扱い |
| --- | --- | --- |
| ある (`ok`) | 既定のブランチの設定を読めた | その設定で判定する |
| 無い (`missing`) | clone は読めたが、既定のブランチに設定ファイルが無い | 設定が無いリポジトリと同じ (デフォルトの表だけで照合する) |
| 読めない (`unreadable`) | 下の表の理由のどれか | そのリポジトリの宣言の判定を止め、宣言に `待機` を書き、利用者に直し方を頼む (KTD9)。読めないことを「無い」として続けない |

## 「読めない」の理由

次の順に確かめ、最初に当たった理由を返す。直し方は `fix` に、案内する clone のルートは `root_hint` に入れて返す。

| 理由 | 条件 | 直し方 |
| --- | --- | --- |
| `not-in-repositories` | 設定 `repositories` にそのリポジトリが無い | `repositories` に `owner/name` と clone のルートの絶対パスを書く |
| `directory-missing` | パスのディレクトリが無い | 同上 |
| `not-git` | `git -C <パス> rev-parse --is-inside-work-tree` が失敗する (git リポジトリでない) | 同上 |
| `not-clone-root` | 作業ツリーの外 (`--is-inside-work-tree` が `false`: bare リポジトリか `.git` の中) か、サブディレクトリ (`--show-prefix` が空でない) | `.git` の中なら `--git-common-dir` の親、サブディレクトリなら `--show-toplevel` を `root_hint` に入れて案内する。bare リポジトリには設定ファイルを読む作業ツリーが無いので、案内するパスは無い (作業ツリーのある clone を書く) |
| `no-origin` | `git -C <パス> remote get-url origin` が失敗する | `git -C <パス> remote add origin <URL>` |
| `origin-mismatch` | `origin` の URL がそのリポジトリと合わない (別のリポジトリの clone か、名前を変える前の URL) | `git -C <パス> remote set-url origin <新しい URL>`。別のリポジトリの clone なら `repositories` を直す |
| `no-origin-head` | 参照 `origin/HEAD` が無い (`git init` と `remote add` だけのリポジトリなど)。既定のブランチを推測しない | `git -C <パス> remote set-head origin --auto` |
| `git-failed` | git を起動できない、または `ls-tree`・`show` が失敗した | メッセージの git のエラーを見る |
| `config-unreadable` | 既定のブランチの設定ファイルが JSON として読めない | 既定のブランチの設定ファイルを直す (理由は `errors`) |

clone のルートを `origin` の URL より先に確かめるのは、サブディレクトリでも `remote get-url` は成功するので、ルートの直し方を先に示すため。ルートかどうかは git に判定させ、パスの文字列を比べない。シンボリックリンクを経たルートのパスと、大文字と小文字だけがディスク上と違う綴りのパス (大文字と小文字を区別しないファイルシステムのとき) は、どちらもルートとして読む。

## `origin` の URL の形と比べ方

URL は `git -C <パス> remote get-url origin` の値 (`insteadOf` の設定を展開した値) を使う。次の形から host と `owner/name` を取り出す。末尾の `.git` と `/` は取り除く。

| 形 | 例 |
| --- | --- |
| scp 形式 | `git@github.com:akm/verify-a.git` |
| `ssh://` | `ssh://git@github.com/akm/verify-a.git`、`ssh://git@github.com:22/akm/verify-a.git` |
| `https://` / `http://` | `https://github.com/akm/verify-a` |
| `git://` | `git://github.com/akm/verify-a.git` |

同じリポジトリと判定する条件:

- host が `github.com` である。GitHub が案内するほかの接続先 (ポート 443 の SSH の `ssh.github.com`) も同じとみなす。SSH で接続する形 (scp 形式と `ssh://`) では、SSH の設定 (`~/.ssh/config`) の Host の別名を `ssh -G <別名>` の出力の `hostname` の行で解決する (ssh が無い・失敗したときは名前のまま比べるので、別名は合わない)。`https://`・`http://`・`git://` は SSH で接続しないので解決せず、URL の host のまま比べる。それ以外の host (GitHub Enterprise など) は合わない。
- `owner/name` が、大文字と小文字を区別せずに一致する。

名前を変える前のリポジトリの URL は合わないと判定し、GitHub に問い合わせずにローカルで決める。別のリポジトリの clone に設定ファイルがあっても読まない。

## CLI `repo name`

作業のセッションが、今の作業ツリーの `origin` の URL から `owner/repo` を決める (R26)。管理のセッションと同じ関数で決める (2 つのセッションが同じ規則でリポジトリを決めるため)。`gh` は実行しない。

| 入力 | 出力 (JSON) |
| --- | --- |
| `repo name --dir <作業ツリーの中のディレクトリ>` | `status` (`ok` / `error`)・`repo` (`owner/name`。URL の大文字小文字のまま)・`host`・`reason` (`error` のとき: `not-git` / `no-origin` / `url-unparsable` / `not-github` / `git-failed`)・`errors` |
