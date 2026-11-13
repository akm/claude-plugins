# 偽の `gh` が返す固定データ

実物の `gh` の出力をコピーしたファイル。偽の `gh` (ファイル `issue-practice/tests/fake-gh`) がモードや応答の指定に従って返し、テストが `gh` の出力の形を確認するのに使う。名前は `<場合>.stdout` と `<場合>.stderr` の組で、標準出力と標準エラー出力をそのまま書いている。

出所は 3 つある。

- **issue-dispatch からコピーしたもの**: プラグイン issue-dispatch の固定データ (ディレクトリ `issue-dispatch/tests/fixtures/gh/`) を、そのままコピーした。取った日は 2026-10-21〜22、`gh` は 2.102.0。取り方は、issue-dispatch の固定データの README にある。
- **このプラグインで取ったもの**: 公開のリポジトリ akm/claude-plugins に対して、読むだけのコマンドで取った。書き込みはしていない。取った日は 2026-11-14、`gh` は 2.103.3。
- **確認用のリポジトリで取ったもの**: 確認用のリポジトリ akm/issue-practice-sandbox (公開) で、Issue・マイルストーン・ラベルを実際に作って取った (計画の U2 の手順 1)。名前は `sandbox-` で始まる。取った日は 2026-11-14、`gh` は 2.103.3。マイルストーンと Issue の一覧の応答は、使うキーだけに切り詰めた。

| 場合 | コマンド | 終了コード | 出所 |
| --- | --- | --- | --- |
| `auth-invalid-token` | `GH_TOKEN` に無効なトークンを入れて `gh api graphql` (認証切れ) | 1 | issue-dispatch からコピー |
| `auth-not-logged-in` | 認証の無い `GH_CONFIG_DIR` と空の `GH_TOKEN` で `gh api graphql` | 4 | issue-dispatch からコピー |
| `network-unreachable` | `https_proxy` を繋がらない宛先 (`127.0.0.1:9`) にして `gh api graphql` | 1 | issue-dispatch からコピー |
| `graphql-rate-limited` | GraphQL のレート制限の応答 (`errors[].type` が `RATE_LIMITED`) | 1 | issue-dispatch からコピー (issue-dispatch で手で作ったもの) |
| `graphql-bad-field` | `gh api graphql` で存在しないフィールドを読む (`errors` の形) | 1 | issue-dispatch からコピー |
| `issue-not-found` | `gh issue view 999 --json number` (無い番号) | 1 | issue-dispatch からコピー |
| `api-user` | `gh api user` (REST。トークンのログイン)。`login`・`id`・`node_id`・`html_url`・`type` だけを残したもの | 0 | issue-dispatch からコピー |
| `issue-view-266` | `gh issue view 266 -R akm/claude-plugins --json number,url,state,title,body,updatedAt` (節「クローズ条件」をマークで囲んでいない作業 Issue) | 0 | このプラグインで取った |
| `issue-view-239` | `gh issue view 239 -R akm/claude-plugins --json number,url,state,title,body,updatedAt` (節「クローズ条件」と「PR マージ計画」をマークで囲んだ管理 Issue) | 0 | このプラグインで取った |
| `issue-comments-266` | `gh api repos/akm/claude-plugins/issues/266/comments --paginate --slurp` (ページの配列の中にコメントの配列)。コメントのキーを `id`・`html_url`・`created_at`・`updated_at`・`body`・`user` (`login`・`type`) だけに切り詰めた | 0 | このプラグインで取ったものを切り詰めた |
| `issue-view-pr-271` | `gh issue view 271 -R akm/claude-plugins --json number,url,state` (PR の番号を `gh issue view` に渡す。PR として応答し、`url` が `/pull/` になる) | 0 | このプラグインで取った |
| `sandbox-issue-create` | `gh issue create -R akm/issue-practice-sandbox --title … --body …` (標準出力は作った Issue の URL) | 0 | 確認用のリポジトリで取った |
| `sandbox-issue-view-sub-issues` | `gh issue view 1 --json number,url,subIssues,subIssuesSummary` (`gh issue edit 1 --add-sub-issue <#2 の URL>` の後の親 Issue) | 0 | 確認用のリポジトリで取った |
| `sandbox-issue-view-parent` | `gh issue view 2 --json number,url,parent` (同じ操作の後の sub-issue) | 0 | 確認用のリポジトリで取った |
| `sandbox-issue-edit-add-sub-issue-duplicate` | `gh issue edit 1 --add-sub-issue <#2 の URL>` (既に #1 の sub-issue である #2 をもう一度足す) | 1 | 確認用のリポジトリで取った |
| `sandbox-issue-edit-parent-same` | `gh issue edit 2 --parent 1` (既に #1 の sub-issue である #2 の親を #1 にする) | 1 | 確認用のリポジトリで取った |
| `sandbox-issue-view-blocked-by` | `gh issue view 2 --json blockedBy,number,url` (`gh issue edit 2 --add-blocked-by <#4 の URL>` の後) | 0 | 確認用のリポジトリで取った |
| `sandbox-issue-view-blocking` | `gh issue view 4 --json blocking,number,url` (同じ操作の後の依存先。blocking の一覧) | 0 | 確認用のリポジトリで取った |
| `sandbox-issue-edit-add-blocked-by-duplicate` | `gh issue edit 2 --add-blocked-by 4` (既にある blocked by をもう一度足す) | 1 | 確認用のリポジトリで取った |
| `sandbox-issue-edit-add-blocked-by-self` | `gh issue edit 2 --add-blocked-by 2` (自分自身) | 1 | 確認用のリポジトリで取った |
| `sandbox-issue-edit-add-blocked-by-missing` | `gh issue edit 2 --add-blocked-by 999` (無い番号) | 1 | 確認用のリポジトリで取った |
| `sandbox-issue-create-blocked-by-missing` | `gh issue create --title … --body … --blocked-by 999` (無い番号)。**終了コードは 1 だが、Issue は作られた** (#5) | 1 | 確認用のリポジトリで取った |
| `sandbox-issue-create-milestone-missing` | `gh issue create … --milestone 無いマイルストーン`。Issue は作られない | 1 | 確認用のリポジトリで取った |
| `sandbox-issue-create-milestone-closed` | `gh issue create … --milestone <閉じたマイルストーンの名前>`。無い名前と同じ応答で、Issue は作られない | 1 | 確認用のリポジトリで取った |
| `sandbox-issue-view-relations` | `gh issue view 2 --json number,url,state,title,body,milestone,labels,parent,blockedBy` | 0 | 確認用のリポジトリで取った |
| `sandbox-issue-view-milestone` | `gh issue view 4 --json number,milestone,labels` (`milestone` は `number`・`title`・`description`・`dueOn` だけで、URL と状態は無い) | 0 | 確認用のリポジトリで取った |
| `sandbox-milestone-create` | `gh api repos/akm/issue-practice-sandbox/milestones -X POST -f title=… -f description=…` (応答をキー `html_url`・`number`・`title`・`description`・`state`・`open_issues`・`closed_issues`・`created_at`・`updated_at`・`closed_at` に切り詰めた) | 0 | 確認用のリポジトリで取った |
| `sandbox-milestone-create-duplicate` | 同じ名前のマイルストーンをもう一度作る (HTTP 422、`errors[].code` が `already_exists`) | 1 | 確認用のリポジトリで取った |
| `sandbox-milestone-rename` | `gh api repos/…/milestones/2 -X PATCH -f title=… --jq '{number,title,state,description}'` (名前の変更) | 0 | 確認用のリポジトリで取った |
| `sandbox-milestone-close` | `gh api repos/…/milestones/2 -X PATCH -f state=closed --jq '{number,title,state,closed_at}'` (閉じる) | 0 | 確認用のリポジトリで取った |
| `sandbox-milestones-list` | `gh api 'repos/…/milestones?state=all&per_page=100' --paginate --slurp` (ページの配列。`sandbox-milestone-create` と同じキーに切り詰めた) | 0 | 確認用のリポジトリで取った |
| `sandbox-label-list` | `gh label list -R akm/issue-practice-sandbox --json name,color,description --limit 1000` | 0 | 確認用のリポジトリで取った |
| `sandbox-label-create-duplicate` | `gh label create no-release --color cfd3d7` (既にあるラベル) | 1 | 確認用のリポジトリで取った |
| `sandbox-issue-edit-label-missing` | `gh issue edit 4 --add-label 無いラベル` | 1 | 確認用のリポジトリで取った |
| `sandbox-issues-open` | `gh api 'repos/…/issues?state=open&per_page=100' --paginate --slurp` (ページの配列。キーを `html_url`・`number`・`title`・`state`・`body`・`created_at`・`updated_at`・`user.login`・`labels[].name`・`milestone` の `number` と `title`・`pull_request.html_url` に切り詰めた) | 0 | 確認用のリポジトリで取った |
| `sandbox-issue-list-current` | `gh issue list -R akm/issue-practice-sandbox --state open --label current --json number,url,title,body,createdAt --limit 100` (文書 `issue-practice/references/release-plan-table.md` の書式で手で作ったリリース計画 Issue) | 0 | 確認用のリポジトリで取った |

### 確認用のリポジトリで分かった振る舞い

固定データに表れない振る舞いも、ここに書く。スクリプトは、これを前提に書いている。

- **既に別の親 Issue がある Issue に `gh issue edit <子> --parent <別の親>` か `gh issue edit <別の親> --add-sub-issue <子>` をすると、エラーにならずに親が置き換わる** (終了コード 0)。親を設定する前に、`--json parent` で今の親を読み、別の親があれば設定しない。
- 同じ親に同じ sub-issue をもう一度足すと、エラーになる (`sandbox-issue-edit-add-sub-issue-duplicate`・`sandbox-issue-edit-parent-same`)。同じ blocked by をもう一度足しても、エラーになる (`sandbox-issue-edit-add-blocked-by-duplicate`)。やり直しのときは、今の状態と比べて足りないものだけを設定する。
- `gh issue create` に `--blocked-by` を付けて、その設定が失敗すると、終了コードは 1 でも Issue は作られている (`sandbox-issue-create-blocked-by-missing`)。`--milestone` の名前が無いときや閉じているときは、Issue は作られない。そのため、Issue は親と blocked by を付けずに作り、別の `gh issue edit` で設定する。
- 閉じた Issue も、親 Issue にできる (`gh issue edit 4 --parent 5` で #5 が閉じていても終了コード 0)。
- Issue を作った直後に `gh issue list --label <ラベル>` を実行すると、作った Issue が一覧に入らないことがあった (数秒後に実行し直すと入った)。
- マイルストーンの作成・名前の変更・閉じること・一覧の取得は、`gh api` の REST の API (`repos/<owner>/<repo>/milestones`) でできる。`gh` にはマイルストーンのサブコマンドが無い。

後の単位が固定データを足すときは、同じ名前の付け方でこの表に行を足す。
