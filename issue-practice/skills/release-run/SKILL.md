---
name: release-run
description: 計画を承認した GitHub のリリース Issue について、リリースの実行を始めたことを記録し、リリースの PR とリリース Issue にお互いの URL を書き、実行の記録を PR かリリース Issue のコメントに書く。実行中の計画の変更と、このリリースで直さない問題の切り出しも扱う。「リリースを始めて」「リリースの実行を記録して」「リリースの PR を作って」「実行中のリリースの計画を変えたい」「release-run を実行して」のような依頼で使う。
---

# issue-practice:release-run: リリースを実行して記録する

計画を承認したリリース Issue (題名に `[DRAFT]` が無いもの) について、実行を始めたことを記録し、実行の記録を書く (計画の R46・R47)。リリースの手順そのもの (タグを打つ・本番を更新するなど) は、プロジェクトの手順の文書に従って、利用者か別のスキルが行う。このスキルは、行ったことを記録する。用語は [terms.md](../../references/terms.md) にある。リリース Issue の本文の形は [release-issue.md](../release-issue-plan/references/release-issue.md)、名前の形は [release-plan-issue.md](../release-plan/references/release-plan-issue.md) にある。

検査のスクリプトは `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_practice.py" <サブコマンド>` で実行する (以下では `issue_practice.py <サブコマンド>` と略す)。引数・出力の JSON・終了コードは、サブコマンドの `--help` で確認する。終了コードは、どのサブコマンドも次のとおりに扱う。

| 終了コード | 扱い |
| --- | --- |
| 0 | 続ける |
| 3 | 出力の `errors` を利用者に示し、どうするかを質問する。回答の無いまま進めない |
| 4 | `gh` か `git` が失敗した。出力の `gh_error` か `git_error` を利用者に示して中断する |
| 1・2 | スクリプトの不具合。出力をそのまま利用者に示して中断する |

Issue の番号・URL は、文から読み取らず、スクリプトの出力の値をそのまま使う (計画の R52)。記録のコメントの 1 行目は `issue_practice.py records format <種類> <キー>=<値> ...` で作り、出力の JSON の `line` の値だけを書く (JSON をそのまま書かない)。

## 手順

1. **対象を確認する**: `gh repo view --json nameWithOwner -q .nameWithOwner` でリポジトリ (`owner/repo`) を得る。実行するリリース Issue を利用者に確認する。指定が無ければ、`issue_practice.py release current --repo <owner/repo>` の `current` を候補として示す。
2. **リリース Issue の状態を読む**: `issue_practice.py release show --issue <リリース Issue>` を実行する。
   - 終了コードが 3 なら、決めた形が崩れている (R8)。`errors` を示して利用者に質問する。
   - `draft` が true なら、計画が承認されていない。スキル `release-issue-plan` で計画を立てるよう利用者に伝えて中断する。
3. **実行を始めたことを記録する**: `release_start` が null なら、実行を始めてよいかを利用者に確認してから、`issue_practice.py records format release-start` で 1 行目を作り、`gh issue comment <リリース Issue の URL> --body-file -` で、1 行目・空行・本文 (実行を始めたこと・本文の項目「リリースの手順」で行うと決めた手順) を書く (R46)。このコメントがあるリリース Issue を、実行中とする。
4. **リリースの PR を作る (PR が要るときだけ)**: リリースに PR が要るか (本文の項目「リリースの手順」) を確認する。要るなら、次のとおりにする (R47)。
   - ブランチの名前は `release/<リリース Issue の番号>-<英語の短い名前>` にする。
   - PR の本文に、リリース Issue の URL を書く。`Closes #<番号>` は書かない。PR のマージより後に行う手順があると、その手順を終える前にリリース Issue が閉じてしまうため。
   - リリース Issue の本文の項目「参照」に `- PR: <PR の URL>` の行を足す。`issue_practice.py body show --issue <リリース Issue>` で本文と `sha256` を読み、項目「参照」の最後の行の後に足した本文を作る。書く直前に `body show` を実行し直して `sha256` が変わっていないことを確認してから、`gh issue edit <リリース Issue の URL> --body-file -` で書く (R6)。
5. **実行の記録を書く**: 手順を 1 つ行うたびに、何を行ったか・結果・根拠の URL (CI の実行・タグ・デプロイの記録など) を、コメントに書く (R47)。
   - リリースの PR があれば、その PR のコメントに書く (`gh pr comment <PR の URL> --body-file -`)。
   - PR が無ければ、リリース Issue のコメントに書く。
   - 行うと決めた手順を省いたとき・手順の結果が想定と違ったときは、そのことと理由も書く。
6. **実行中に計画を変える**: 範囲・順序・手順・完了の条件を変えるときは、スキル `release-issue-plan` の手順 5〜8 と同じく、新しい計画案に節「変えたこと」(何を変えたか・理由・決めた人) を書き、`issue_practice.py release issue-plan <ファイル>` で示して利用者の承認を得てから、`issue_practice.py release issue-apply <ファイル>` で書く。本文を書き換え、記録のコメント `plan-change` を書く。題名に `[DRAFT]` は付け直さない (R46)。
7. **このリリースで直さない問題を切り出す**: 実行の中で見つかった問題を、このリリースで直さないと利用者が決めたら、スキル `new-issue` で切り出す (R13)。入れるリリースを決めるときは `issue_practice.py release current --repo <owner/repo> --carve-out` を使う。実行中のリリースは、入れるリリースに選べない。切り出した Issue の URL を、手順 5 の実行の記録に書く。
8. **閉じる**: 行うと決めた手順をすべて行ったら、スキル `release-close` で、リリース Issue とリリースマイルストーンを閉じる。

## このスキルがしないこと

- リリースの手順そのもの (タグ・デプロイ・告知など) を決めること。手順はプロジェクトの手順の文書に従う。
- 計画を承認する前のリリース Issue の計画を立てること。それはスキル `release-issue-plan` が行う。
- 実行中に計画を変えるときに、題名に `[DRAFT]` を付け直すこと。
- リリースの PR をマージすること・リリース Issue を閉じること。PR は利用者がマージし、閉じるのはスキル `release-close`。
- 承認の無いまま、実行を始めた記録を書くことや計画を変えること。
