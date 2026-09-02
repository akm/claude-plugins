# mermaid-preview

mermaid の図を含む HTML を生成し、ブラウザで人間に見せる skill を配布するプラグインです。

## 収録スキル

| スキル | 説明 |
| --- | --- |
| `mermaid-preview` | 図のソースから HTML を作り、プロジェクト内の `tmp/` に置いてブラウザで開く |

## 前提

導入時に必要な 2 点だけを挙げます。制約の全体と理由の正本は同梱の [SKILL.md](skills/mermaid-preview/SKILL.md) の「検証済みの制約」です。

- **プロジェクトルートに `tmp/` を作れること。** スクラッチパッド (`/private/tmp/...`) では in-app ブラウザが静的スナップショット扱いにするため、図がテキストのまま表示されます。`tmp/` は `.gitignore` に入れてください。
- **mermaid の読み込みに CDN へ到達できること。** 同梱 (約 3.4MB) は負担に見合わないため CDN 参照にしています。読み込みに失敗した場合はページ上にフォールバック文言が出ます。

## in-app ブラウザ前提の知見であること

出力先の制約は、Claude Code の in-app ブラウザで検証した結果に基づきます。別のブラウザで開く運用では `tmp/` に置く必然性はありませんが、**制約を外しても害は無い**ため既定のままにしています。

## 使い方

インストール手順は [リポジトリの README](../README.md#使い方) を参照してください。

```bash
claude plugin marketplace add akm/claude-plugins
claude plugin install mermaid-preview@akm-claude-plugins
```

図を見せたいときに「この図を HTML で見せて」「mermaid をプレビューして」のように依頼すると起動します。他のスキル (`doc-dag` など) が図の提示を必要とするときにも使われます。
