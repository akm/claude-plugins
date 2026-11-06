---
name: review-rally
description: レビューを、このセッションから起動した別の Claude Code のセッション (レビューのセッション。専用の worktree で動く) に任せ、トリアージと修正をこのセッションで行うループを、停止するまで回す。依頼と完了の通知はセッション間のメッセージで行い、2 回目以降は依頼の前にレビューのセッションの会話を消す。「レビューを別のセッションに任せて回して」「セッションを起動してレビューから修正までを回して」「review-rally を実行して」のような依頼で使う。引数でレビューのセッションのモデル (--model) と effort (--effort)・レビュースキルとそのオプション・上限・全量の起点にする派生元のブランチ (--base)・1 回目を全量にするか (--full-first)・収束の後に全量の回を行うか (--full-review)・回数の閾値とフェーズの実行方法 (どちらも review-triage-fix に渡す)・修正の必要度の下限 (--min-fix-necessity。review-triage に渡す) を指定できる。Claude のデスクトップアプリのセッションから使う。セッションは worktree で動いていても、メインの作業ツリーで動いていてもよい。
---

# review-rally: レビューを別のセッションに任せるループ

このスキルを呼び出したセッション (以下「呼び出し元のセッション」) は、ツール `start_session` でセッション (以下「レビューのセッション」) を起動し、レビューを任せる。レビューのセッションは、アプリが作る専用の git worktree (以下「レビューの worktree」) で動く。`git worktree add` で追加したものではない、元の作業ツリーを「メインの作業ツリー」と呼ぶ。

## 実現すること

1. レビューの結果を、Skill ツールで [review-triage](../review-triage/SKILL.md) を呼び出してトリアージする。
2. 直すものが無くなったら、収束として終了する。`--full-review` を付けたときは、収束後の全量の回が要れば、その回を行ってから終了する。
3. 採択したものを、Skill ツールで [review-triage-fix](../review-triage-fix/SKILL.md) を呼び出して直す。
4. 直したものを、レビューのセッションに再び依頼する。
5. 収束しなくても停止する。
6. どの回も、レビューのセッションに同じ条件でレビューさせる。

## SSOT の宣言

ループの順序・分岐・停止の条件・報告の SSOT (single source of truth。ある事実を定めている唯一の記述) は、`review-triage-loop` の [loop-flow.md](../review-triage-loop/references/loop-flow.md) と [reporting.md](../review-triage-loop/references/reporting.md)。このスキルは `review-triage-loop` を呼び出さず、同じ図に従って自分で `review-triage` と `review-triage-fix` を呼び出す。

| 流用元 | 使うもの | 使わないもの (このスキルの SSOT) |
| --- | --- | --- |
| [loop-flow.md](../review-triage-loop/references/loop-flow.md) の図と決定表 | G2・G3・L2・J2・J4・J5・J7・J8・J9・F1・S2〜S6 のノードと行 | G0 → RRG0、L1 → RRL1 ([round.md](references/round.md))。J2 の「無い」と S3 の間に RRJ1。追加の判定 RRJ1 と停止 RR1〜RR4 ([stops.md](references/stops.md)) |
| [reporting.md](../review-triage-loop/references/reporting.md) | 必ず出すもの (停止した理由に RR1〜RR4 を含める) | このループで足す項目 ([stops.md](references/stops.md) の「停止の報告に足すもの」) |
| [review-invocation.md](../review-triage-loop/references/review-invocation.md) | 「記録のキーの出所」の表・「モデルの名前の比べ方」・「effort の既定」・「別のプロセスでレビューした結果の取り込み」(呼ぶスキル・結果のファイルの照合・`review-triage` に渡すもの) | 「G0 での解決」(レビューのセッションのモデルは人間が決める)・「範囲」(基点は `review-request` の規則) |
| [arguments.md (review-triage-loop)](../review-triage-loop/references/arguments.md) | 優先順位と、`loop`・`fix`・`triage` のキーの値の検査 | このスキルの引数の様式 ([arguments.md](references/arguments.md)) |

## 手順

### 開始 (`/review-rally`)

1. RRG0 を行う ([round.md](references/round.md) の決定表)。
2. G2 から [loop-flow.md](../review-triage-loop/references/loop-flow.md) の図に従う。L1 に来たら RRL1 ([round.md](references/round.md))。

### 再入

人間のメッセージ以外で始まったターンは、[round.md](references/round.md) の「再入の手順」に入る。

- L2 では、Skill ツールで `review-triage` を呼び出す。指摘が 0 件の回も呼び出す。`rally.yaml` に `loop.min_fix_necessity` があれば、`--min-fix-necessity` に渡す (扱いの SSOT は [arguments.md](references/arguments.md))。渡すものは [round.md](references/round.md) の「L2 で `review-triage` に渡すもの」。
- F1 では、Skill ツールで `review-triage-fix` を呼び出し、ループの状態のファイル `tmp/review-rally/<ループの id>/rally.yaml` (様式は [session.md](references/session.md)) の `loop.threshold` を `--threshold` に、`loop.stages` の各要素を `--stage` に渡す。

### 停止

停止ノード (S2〜S6・RR1〜RR4) に到達したら、[stops.md](references/stops.md) の「停止のときに行うこと」を行って報告する。
