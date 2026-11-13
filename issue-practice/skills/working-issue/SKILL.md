---
name: working-issue
description: 管理セッションから受け持った作業 Issue 1 つを進める作業セッションの手順。最初の指示 (無ければ作業 Issue の記録のコメント) から受け持ちを読み、ブランチを作って作業し、Closes を書かない PR を作り、クローズ条件にチェックと根拠のリンクを入れ、報告 (PR を作った・チェックを入れた・分けたい・条件を変えたい・切り出したい・中断する) を作業 Issue の記録のコメントとメッセージで管理セッションに送る。自己管理 Issue では報告を省いて同じ手順で進める。最初の指示に「スキル issue-practice:working-issue を使って」とあるときや、「この作業 Issue を進めて」「working-issue を実行して」のような依頼で使う。
---

# issue-practice:working-issue: 作業 Issue を進めて報告する

作業セッションとして、作業 Issue 1 つを受け持って進め、管理セッションに報告する (計画の R25・R27・R30・R18・R21・R24)。自己管理 Issue を進めるセッションも、報告を省いてこの手順で進める (R26)。

用語は [terms.md](../../references/terms.md) にある。最初の指示と記録のコメント `session` の形は [start-instruction.md](../../references/start-instruction.md)、記録のコメントの 1 行目は [record-comments.md](../../references/record-comments.md)、チェックの入れ方は [closing-conditions.md](../../references/closing-conditions.md) にある。

検査のスクリプトは `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_practice.py" <サブコマンド>` で実行する (以下では `issue_practice.py <サブコマンド>` と略す)。引数・出力の JSON・終了コードは、サブコマンドの `--help` で確認する。終了コードは、どのサブコマンドも次のとおりに扱う。

| 終了コード | 扱い |
| --- | --- |
| 0 | 続ける |
| 3 | 出力の `errors` (や満たさない項目) を利用者に示し、どうするかを質問する。回答の無いまま進めない |
| 4 | `gh` か `git` が失敗した。出力の `gh_error` か `git_error` を利用者に示して中断する |
| 1・2 | スクリプトの不具合。出力をそのまま利用者に示して中断する |

Issue の番号・URL は、文から読み取らず、スクリプトの出力の値をそのまま使う (計画の R52)。

## 報告の送り方

報告は、作業 Issue に記録のコメント `report` を書き、そのコメントの URL を、報告先の管理セッションにセッション間のメッセージで知らせる (R30・KTD16)。自己管理 Issue では報告を省く。

1. 1 行目を `issue_practice.py records format report type=<種類> [pr=<PR の URL>]` で作る。種類は `pr`・`check`・`split`・`condition-change`・`carve-out`・`suspend` のどれか。
2. `gh issue comment <作業 Issue の URL> --body-file -` で、1 行目・空行・本文 (何をしたか・何を判断してほしいか・根拠の URL) を書く。出力のコメントの URL を控える。
3. メッセージのツール (`SendMessage`) で、報告先の管理セッションの**名前**に宛てて、1 行目に「<作業 Issue の URL> の報告 (<種類>): <コメントの URL>」と書いて送る。セッションの ID には宛てない (計画の KTD17。ID 宛ては、利用者の入力が無いと途中で拒否される)。

## 手順

1. **受け持ちを読む**: 最初の指示から、作業 Issue・管理 Issue・報告先の管理セッションの名前と ID・ブランチと作る元・PR のマージ先・PR をマージする人を読む。最初の指示が見当たらないとき (会話が要約されたときなど) は、`issue_practice.py records list --issue <作業 Issue> --kind session` の最後の記録を読む (KTD6)。報告先の管理セッションが替わったというメッセージを受け取ったら、それ以降はその名前に宛てる。
2. **条件を確認する**: `issue_practice.py checkboxes list --issue <作業 Issue>` でクローズ条件を読み、`issue_practice.py records list --issue <作業 Issue> --kind approval` で承認の記録があることを確認する。条件が足りない・作業の形で書かれている・承認の記録が無いときは、着手せずに報告 (`condition-change`) を送り、管理セッションの判断があるまで待機する (R17・R24)。
3. **ブランチを作る**: `git fetch origin` の後、`git switch -c <ブランチ> origin/<作る元>` でブランチを作る。
4. **作業する**: プロジェクトの規約 (`CLAUDE.md` やほかのスキル) に従って作業する。作業の途中で次のことが分かったら、作業を中断して報告を送り、管理セッションの判断があるまで待機する。
   - 1 つの PR では大きすぎて、分けたい (`split`。R31)
   - クローズ条件を変えたい (`condition-change`。R24)
   - 後で行う作業を、別の Issue に切り出したい (`carve-out`。R13)。切り出すかを決めるのは利用者で、Issue を作るのは管理セッション (スキル `new-issue`)
   - 作業を続けられない (`suspend`)
5. **PR を作る**: `gh pr create --base <PR のマージ先> --head <ブランチ>` で PR を作る。本文には作業 Issue へのリンクを書き、`Closes #<番号>` は書かない (R21)。
   - 作業 Issue なら、報告 (`pr`、`pr=<PR の URL>`) を送る。管理セッションが、PR マージ計画の表に PR の URL を書く。
   - 自己管理 Issue なら、`issue_practice.py merge-plan show --issue <Issue>` の `sha256` を使って、`issue_practice.py merge-plan set-pr --issue <Issue> --work <Issue> --pr <PR の URL> --expect-sha256 <sha256>` で表に書く。
6. **チェックを入れる**: クローズ条件の項目ごとに、確認できたものからチェックを入れる。
   - `issue_practice.py checkboxes list --issue <作業 Issue>` で項目の行番号と `sha256` を得て、`issue_practice.py checkboxes check --issue <作業 Issue> --line <行番号> --evidence <根拠の URL> --expect-sha256 <sha256>` で入れる。1 つ入れるたびに本文のハッシュ値が変わるので、次の項目は `checkboxes list` を実行し直してから入れる。
   - 根拠は、テストを実行した PR・CI の実行・確認を記録したコメントなどの URL (R18・KTD9)。手で確認した結果は、先に作業 Issue のコメントに書き、そのコメントの URL を根拠にする。
   - CI の項目は、CI の実行がすべて完了して成功してからチェックを入れる。
   - 切り出した項目は、`--carved-out <切り出した Issue の URL>` で入れる (R15)。
   - チェックを入れたら、作業 Issue なら報告 (`check`) を送る。チェックを入れていない項目が残っているときは、その理由も本文に書く。
7. **マージまで待機する**: PR をマージする人が利用者なら、利用者がマージする。PR がマージされずに閉じられて作り直したら、その PR を根拠にしていたチェックを確認し直し、報告 (`pr`) で新しい PR を知らせる (R34)。作業 Issue を閉じるのは管理セッション (R22)。自己管理 Issue は、スキル `managing-issue-close` で閉じる。
8. **作業 Issue を閉じずに終えるとき**: `issue_practice.py records format abandon session=<このセッションの ID>` で 1 行目を作り、理由を本文に書いて作業 Issue に記録のコメント `abandon` を書く (R29)。作業 Issue なら、報告 (`suspend`) も送る。このセッションの ID は、環境変数 `CLAUDE_CODE_HOST_SESSION_ID` で確認する。

## 自己管理 Issue のとき

- 最初の指示は無い。手順 1 では、自己管理 Issue の本文の PR マージ計画 (`merge-plan show`) からブランチとマージ先を読む。
- 着手するときに、自己管理 Issue に記録のコメント `session` (`role=self-managing`。形は [start-instruction.md](../../references/start-instruction.md) の節「起動の後の記録」) を書く。
- 報告は送らない。チェックを入れるのも、表に PR を書くのも、このセッションが行う。

## このスキルがしないこと

- 作業 Issue を閉じること・PR マージ計画の表を書き換えること (自己管理 Issue の表の列「PR」を除く)。それは管理セッションが行う。
- 切り出す Issue を作ること・クローズ条件を書き換えること。報告して、管理セッションと利用者の判断があるまで待機する。
- PR の本文に `Closes` を書くこと。
- 根拠のリンクの無いチェックを入れること。
