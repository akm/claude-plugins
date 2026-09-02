# commit-squash

未 push のコミットを、同じ関心事のものどうしでまとめて数を減らす skill を配布するプラグインです。

試行錯誤で膨らんだ履歴 (「直しては見つかり、また直す」の連鎖) を、レビュアが読める粒度に整えます。

## 収録スキル

| スキル | 説明 |
| --- | --- |
| `commit-squash` | 起点を指定して、そこから先の未 push のコミットをグループごとにまとめ直す |

## 特徴

- **`git rebase -i` を使わず、起点から積み直す。** 順序の入れ替えで衝突が起きず、最終ツリーのハッシュ比較で「中身が 1 バイトも変わっていない」ことを機械的に証明できます (理由は同梱の [why-not-rebase.md](skills/commit-squash/references/why-not-rebase.md))。
- **push 済みのコミットは変更しない。** 判定の軸はこれだけで、1 つでも該当すればその場で止まります (正本は同梱の [history-rewriting.md](skills/commit-squash/references/history-rewriting.md))。
- **`git reset --hard` を使わない。** ブランチの付け替えは `--keep` で行うため、未コミットの作業を消しません (同上)。

## 前提

確認の手順の正本は同梱の [SKILL.md](skills/commit-squash/SKILL.md) の「前提の確認」、止まる条件の正本は [history-rewriting.md](skills/commit-squash/references/history-rewriting.md) の「止まるべきとき」です。

- **まとめる範囲がすべて未 push であること。** push 済みのコミットが含まれる場合、スキルは実行せずに報告して終わります。
- **作業ツリーがクリーンであること。**

バックアップブランチはスキルが自動で作りますが、**削除は行いません** (人間に依頼します)。まとめ方に問題が見つかったときの唯一の戻り先のためです (正本は [SKILL.md](skills/commit-squash/SKILL.md) の手順 10)。

## commit-rules-guard との関係

グループ分けの基準は「コミットは変更した動機でグルーピングする」という考え方に基づいています。同じ考え方を `git commit` の直前に想起させるのが [commit-rules-guard](../commit-rules-guard/README.md) です。**併用すると、動機を混ぜないことを事前 (guard) と事後 (squash) の両方で検査できます。**

## 使い方

インストール手順は [リポジトリの README](../README.md#使い方) を参照してください。

```bash
claude plugin marketplace add akm/claude-plugins
claude plugin install commit-squash@akm-claude-plugins
```

「コミットが多すぎるのでまとめて」「`<sha>` 以降のコミットをまとめて」のように依頼すると起動します。引数で起点のコミットを指定でき、省略時は origin の先端が起点になります。
