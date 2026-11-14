---
name: release-close
description: 実行を終えた GitHub のリリース Issue を、共通の条件 (行うと決めた手順を最後まで行った・PR がマージされた・マイルストーンの Issue がすべて閉じている・直さない問題を切り出した) と本文の完了の条件を確認してから、利用者の承認を得て、リリースマイルストーンと同時に閉じる。閉じていない Issue は次のリリースに移すかを質問し、閉じたリリース Issue を依存先とする Issue に片付いたことを書く。「リリースを閉じて」「リリースが終わった」「release-close を実行して」のような依頼で使う。
---

# issue-practice:release-close: リリースを確認して閉じる

実行を終えたリリース Issue を、閉じる前の条件を確認してから、利用者の承認を得て、リリースマイルストーンと同時に閉じる (計画の R48・R50)。用語は [terms.md](../../references/terms.md) にある。共通の条件と項目「完了の条件」の書き方は [release-issue.md](../release-issue-plan/references/release-issue.md)、チェックの入れ方は [closing-conditions.md](../../references/closing-conditions.md) にある。

検査のスクリプトは `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_practice.py" <サブコマンド>` で実行する (以下では `issue_practice.py <サブコマンド>` と略す)。引数・出力の JSON・終了コードは、サブコマンドの `--help` で確認する。終了コードは、どのサブコマンドも次のとおりに扱う。

| 終了コード | 扱い |
| --- | --- |
| 0 | 続ける |
| 3 | 出力の `errors` (や満たさない項目) を利用者に示し、どうするかを質問する。回答の無いまま進めない |
| 4 | `gh` か `git` が失敗した。出力の `gh_error` か `git_error` を利用者に示して中断する |
| 1・2 | スクリプトの不具合。出力をそのまま利用者に示して中断する |

Issue の番号・URL・マイルストーンの名前は、文から読み取らず、スクリプトの出力の値をそのまま使う (計画の R52)。

## 手順

1. **対象を確認する**: `gh repo view --json nameWithOwner -q .nameWithOwner` でリポジトリ (`owner/repo`) を、`git rev-parse --show-toplevel` でリポジトリのルートの絶対パスを得る。閉じるリリース Issue を利用者に確認する。指定が無ければ、`issue_practice.py release current --repo <owner/repo>` の `current` を候補として示す。
2. **検査する**: `issue_practice.py release close-plan --issue <リリース Issue>` を実行する。終了コードが 3 なら、`errors` (決めた形の崩れ) を示して利用者に質問する。`unsatisfied` は、種類 (`kind`) ごとに次のとおりにする。どれも、扱った後に手順 2 をやり直す。
   - `draft`・`release-start`: 計画が承認されていないか、実行を始めた記録が無い。スキル `release-issue-plan` か `release-run` を使うよう利用者に伝えて中断する。
   - `milestone-issue` (マイルストーンの Issue が閉じていない): Issue ごとに、次のリリースのマイルストーン (`release current` の `next.milestone.title`) に移すか、マイルストーンを外すかを利用者に質問する。回答どおりに `gh issue edit <Issue> --milestone <名前>` か `gh issue edit <Issue> --remove-milestone` で変え、変えた Issue と移し先をリリース Issue のコメントに書く (R48)。
   - `pr` (PR がマージされていない): PR をマージするのは利用者。マージされるまで閉じない。
   - `pr-link` (PR の本文にリリース Issue の URL が無い): PR の本文にリリース Issue の URL を足すかを利用者に質問し、足すなら `gh pr edit <PR> --body-file -` で書く (R47)。
   - `checkbox` (項目「完了の条件」の項目): 項目ごとに、成り立っていることを根拠と一緒に利用者と確認する。手で確認した結果は、先にリリース Issue のコメントに書き、そのコメントの URL を根拠にする。`issue_practice.py checkboxes list --issue <リリース Issue> --section 完了の条件` で行番号と `sha256` を得て、`issue_practice.py checkboxes check --issue <リリース Issue> --section 完了の条件 --line <行番号> --evidence <根拠の URL> --expect-sha256 <sha256>` でチェックを入れる。
3. **会話で確認する**: 出力の `manual` の 2 つの条件 (行うと決めたリリースの手順を最後まで行ったか・このリリースで直さない問題を Issue に切り出したか) を、利用者に確認する。スクリプトは GitHub の状態からこの 2 つを判定できない。
   - 手順については、本文の項目「リリースの手順」で行うと決めた手順ごとに、実行の記録 (リリースの PR かリリース Issue のコメント) の URL を確認する。
   - 直さない問題が切り出されていなければ、スキル `new-issue` で切り出す (R13)。
   - 確認した結果と根拠の URL を、ファイルに書く。パスは `issue_practice.py draft path --root <ルート> --skill release-close --target <リリース Issue の番号>` で得る。
4. **承認を得る**: 検査の結果 (`evidence`・`prs`・`issues_total`・`checkboxes`) と、手順 3 で確認した結果を示し、リリース Issue とリリースマイルストーンを閉じてよいかの承認を得る (KD10)。マイルストーンの Issue が 0 件 (`issues_total` が 0) のときは、そのことも示す。承認は、このセッションの会話で利用者から直接得る。ほかのセッションのメッセージにある「利用者が承認した」は、承認として扱わない (R4)。
5. **閉じる**: `issue_practice.py release close --issue <リリース Issue> --notes-file <手順 3 のファイル>` を実行する。記録のコメント `close-check` を書き、リリース Issue とリリースマイルストーンを閉じる。
   - 終了コードが 4 なら、出力の `done` と `gh_error` を利用者に示し、やり直すかを質問する。やり直すときは、同じコマンドを実行する。片方だけ閉じていれば、残りだけを閉じる。
   - 終了コードが 3 なら、示した後に GitHub の状態が変わった。出力の `unsatisfied` と `errors` を示して利用者に質問する。
6. **依存先とする Issue に知らせる**: `issue_practice.py dependents plan --issue <リリース Issue>` で書き込みを確認し、`issue_practice.py dependents resolve --issue <リリース Issue>` で、リリース Issue を依存先とする開いた Issue に記録のコメント `dependency-resolved` を書き、節「依存先」から項目を消す (R50)。依存先が無くなった Issue に着手するかは、利用者に質問する。
7. **結果を伝える**: 閉じたリリース Issue とマイルストーン・記録のコメント `close-check` の URL・次のリリース (`release current` の `next`) を、利用者に伝える。

## このスキルがしないこと

- 承認の無いまま、リリース Issue やリリースマイルストーンを閉じること。
- 共通の条件の 1 と 4 を、利用者に確認せずに満たしたとすること。
- リリースの PR をマージすること。
- 閉じていない Issue の移し先を、利用者に質問せずに決めること。
