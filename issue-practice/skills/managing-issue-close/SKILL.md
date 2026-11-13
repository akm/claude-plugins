---
name: managing-issue-close
description: 管理セッションとして、PR がマージされた作業 Issue を、検査のスクリプトで PR のマージとクローズ条件のチェックと根拠のリンクを確認してから閉じる。作業 Issue がすべて閉じたら、管理 Issue (と自己管理 Issue) を、確認の結果を利用者に示して承認を得てから閉じる。閉じた Issue を依存先とする Issue に、片付いたことを書く。「PR をマージした」「この作業 Issue を閉じて」「管理 Issue を閉じて」「managing-issue-close を実行して」のような依頼や、PR をマージした人がマージしたことを伝えたときに使う。
---

# issue-practice:managing-issue-close: 確認して閉じる

作業 Issue・管理 Issue・自己管理 Issue を、閉じる前の検査をしてから閉じる (計画の R20・R22・R23・R50・R51)。作業 Issue は利用者の承認を得ずに閉じ、管理 Issue と自己管理 Issue は承認を得てから閉じる (KD10)。

用語は [terms.md](../../references/terms.md) にある。閉じる前に検査することは [closing-conditions.md](../../references/closing-conditions.md) の節「閉じ方」、記録のコメントの 1 行目は [record-comments.md](../../references/record-comments.md) にある。

検査のスクリプトは `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_practice.py" <サブコマンド>` で実行する (以下では `issue_practice.py <サブコマンド>` と略す)。引数・出力の JSON・終了コードは、サブコマンドの `--help` で確認する。終了コードは、どのサブコマンドも次のとおりに扱う。

| 終了コード | 扱い |
| --- | --- |
| 0 | 続ける |
| 3 | 出力の満たさない項目 (`unsatisfied`) と `errors` を利用者に示し、どうするかを質問する。回答の無いまま進めない |
| 4 | `gh` が失敗して検査できなかった。出力の `gh_error` を利用者に示して中断する。満たさないものとして扱わない |
| 1・2 | スクリプトの不具合。出力をそのまま利用者に示して中断する |

Issue の番号・URL は、文から読み取らず、スクリプトの出力の値をそのまま使う (計画の R52)。

## 閉じた後にすること

Issue を閉じたら、どの種類の Issue でも次のことをする。

1. **記録する**: 閉じた Issue に、記録のコメント `close-check` (1 行目は `issue_practice.py records format close-check result=pass`) を書く。本文には、確認した項目と、`close check` の出力の `evidence` (根拠の URL) を書く。
2. **依存先とする Issue に知らせる**: `issue_practice.py dependents plan --issue <閉じた Issue>` で書き込みを確認し、`issue_practice.py dependents resolve --issue <閉じた Issue>` で、閉じた Issue を依存先とする開いた Issue に記録のコメント `dependency-resolved` を書き、節「依存先」から項目を消す (R50)。依存先が無くなった Issue に着手するかは、利用者に質問する。

## 手順

### 作業 Issue

1. **作業 Issue を決める**: マージされた PR から、PR マージ計画の表 (`issue_practice.py merge-plan show --issue <管理 Issue>` の `rows[].pr_url`) で作業 Issue を決める。
2. **検査する**: `issue_practice.py close check --issue <作業 Issue> --role working --managing <管理 Issue>` を実行する。
   - 終了コードが 0 なら、利用者の承認を得ずに `gh issue close <作業 Issue の URL> --reason completed` で閉じる (R22)。チェックを入れるセッション (作業セッション) と閉じるセッションを分けて、確認の漏れに気づけるようにするため。
   - 終了コードが 3 なら、閉じない。満たさない項目を利用者に示し、どうするか (作業セッションにチェックや根拠を足してもらう・条件を変えるなど) を質問する。PR がマージされずに閉じられて作り直されたときは、表の URL を書き換え (スキル `managing-issue-run` の報告 `pr` と同じ手順)、作業セッションに、閉じた PR を根拠にしていたチェックを確認し直してもらう (R34)。
3. **閉じた後にすること** (上の節) をする。
4. **作業セッションを片付ける**: 作業セッションをアーカイブするかを利用者に質問し、承認を得てから `archive_session` でアーカイブする。

### 管理 Issue

作業 Issue がすべて閉じたら、管理 Issue を閉じる。

1. **管理 Issue の PR (構成 2・3)**: 構成 2 では、draft の PR を ready にするかを利用者に質問する。構成 3 では、ここで管理 Issue の PR を作り (本文に `Closes` を書かず、管理 Issue へのリンクを書く)、`issue_practice.py merge-plan set-pr --issue <管理 Issue> --pr <URL> --expect-sha256 <merge-plan show の sha256>` で書く。PR をマージする人がマージするまで待機する。
2. **管理 Issue 自身の条件にチェックを入れる**: マーク `closing-conditions` の中の管理 Issue 自身の条件 (作業 Issue がすべて閉じている・管理 Issue の PR がマージされたなど) を確認し、`issue_practice.py checkboxes check --issue <管理 Issue> --line <行番号> --evidence <根拠の URL> --expect-sha256 <checkboxes list の sha256>` で入れる。根拠は、作業 Issue の `close-check` の記録のコメントや PR の URL。
3. **検査する**: `issue_practice.py close check --issue <管理 Issue> --role managing` を実行する。
4. **承認を得て閉じる**: 確認の結果 (満たした項目と根拠の URL・作業 Issue の一覧) を利用者に示し、承認を得てから `gh issue close <管理 Issue の URL> --reason completed` で閉じる (R23)。終了コードが 3 なら、満たさない項目を示して質問する。
5. **閉じた後にすること** (上の節) をする。

### 自己管理 Issue

1. `issue_practice.py close check --issue <自己管理 Issue> --role self-managing` を実行する。
2. 確認の結果を利用者に示し、承認を得てから閉じる (R23)。
3. **閉じた後にすること** (上の節) をする。

## 閉じた Issue が開き直されたとき

閉じた作業 Issue が開き直されたときは、チェックを外すか・管理 Issue も開き直すか・マイルストーンをどうするか・作業セッションを起動し直すかを、利用者に質問する (R51)。

## このスキルがしないこと

- PR をマージすること。マージする人は、管理 Issue の計画で決めた人 (スキル `managing-issue-run` の節「C. 報告を受ける」)。
- 満たさない項目が残っている Issue を閉じること。
- `close check` の終了コード 4 (検査できなかった) を、満たさないものとして扱うこと。
- 管理 Issue と自己管理 Issue を、利用者の承認の無いまま閉じること。
