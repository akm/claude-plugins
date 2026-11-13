# issue-practice

GitHub の Issue の使い方 (リリースの計画と記録・管理 Issue と作業 Issue の分担・PR との対応・クローズ条件・後で行う作業の切り出し) に従って、Claude Code のセッションが Issue を扱うためのプラグインです。**作成中**です。何を作るかは管理 Issue [#239](https://github.com/akm/claude-plugins/issues/239) と、計画 [docs/plans/2026-11-13-2156-feat-issue-practice-plugin-plan.md](../docs/plans/2026-11-13-2156-feat-issue-practice-plugin-plan.md) にあります。

## 使えるスキル

| スキル | すること |
| --- | --- |
| [new-issue](skills/new-issue/SKILL.md) | 要望・バグ・切り出しの Issue を、決めた本文の形で作り、入れるリリース (今のリリース・次のリリース・未定) のマイルストーンと、親 Issue・blocked by を設定する |
| [managing-issue-plan](skills/managing-issue-plan/SKILL.md) | 管理 Issue を作業 Issue に分ける計画 (クローズ条件・ブランチの構成・PR マージ計画の表と図) を計画案で調整し、承認を得てから作業 Issue を作って管理 Issue の本文に書く。PR 1 つで済む Issue は自己管理 Issue として計画する |
| [managing-issue-run](skills/managing-issue-run/SKILL.md) | 管理セッションとして、作業セッションを最初の指示を渡して起動し、報告を受けて PR マージ計画の表を書き換え、管理セッションの交代を扱う |
| [managing-issue-close](skills/managing-issue-close/SKILL.md) | 作業 Issue・管理 Issue・自己管理 Issue を、閉じる前の検査をしてから閉じ、依存先とする Issue に片付いたことを書く |
| [working-issue](skills/working-issue/SKILL.md) | 作業セッションとして作業 Issue を進め、PR を作り、チェックと根拠のリンクを入れて、管理セッションに報告する |

リリースのスキルは、計画の実装単位 U4 で足します。

## 今あるもの

| 場所 | 中身 |
| --- | --- |
| [skills/](skills/) | スキル (上の表) |
| [references/](references/) | すべてのスキルが参照する、用語と書式の文書 (下の表) |
| [scripts/issue_practice.py](scripts/issue_practice.py) | 検査のスクリプトの入口。GitHub の状態を読み、決めた形になっているかを判定する。サブコマンドの引数・出力・終了コードは `--help` で確認する |
| [scripts/issue_practice/](scripts/issue_practice/) | 検査のスクリプトのパッケージ (`gh` の実行・識別子・記録のコメント・計画案・本文の範囲・クローズ条件のチェックボックス・リリース計画 Issue の順番の表・Issue の作成・PR マージ計画・管理 Issue の計画案の書き込み・閉じる前の検査) |
| [tests/](tests/) | 検査のスクリプトの自動テスト。偽の `gh` と固定データで実行する |

共有の references:

| 文書 | 中身 |
| --- | --- |
| [references/terms.md](references/terms.md) | 用語 (管理 Issue・作業 Issue・計画案・記録のコメントなど) |
| [references/closing-conditions.md](references/closing-conditions.md) | 節「クローズ条件」の書き方と、チェックの入れ方 |
| [references/draft-plan.md](references/draft-plan.md) | 計画案のファイルの保存先・名前・書式 |
| [references/record-comments.md](references/record-comments.md) | 記録のコメントの 1 行目の形と、作る Issue の本文の末尾に書く行の形 |
| [references/start-instruction.md](references/start-instruction.md) | 管理セッションが作業セッションに渡す最初の指示の形 |
| [references/issue-bodies.md](references/issue-bodies.md) | 要望・バグ・切り出しの Issue の本文の形・計画案の節「作る Issue」の書式・スキルが作るラベル |
| [references/release-plan-table.md](references/release-plan-table.md) | リリース計画 Issue の順番の表の書式と、今のリリースと次のリリースの決め方 |

スキル固有の references:

| 文書 | 中身 |
| --- | --- |
| [skills/managing-issue-plan/references/merge-plan.md](skills/managing-issue-plan/references/merge-plan.md) | ブランチの構成・PR マージ計画の表と図の書式・管理 Issue の計画案の書式 |

## テスト

```bash
python3 -m unittest discover -s issue-practice/tests
```

Python 3.11 以上の標準ライブラリだけを使います。テストは実物の `gh` を使いません。
