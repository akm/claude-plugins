# doc-dag

文書群を「セクションをノード、依存と重複を辺とするグラフ」として調べ、**同じ事実が 2 箇所で語られて片方だけ古びる構造**を見つけて解消する skill を配布するプラグインです。

## 収録スキル

| スキル | 説明 |
| --- | --- |
| `doc-dag` | 文書の依存と重複を調査し、1 枚の mermaid 図で示して、DAG (有向非巡回グラフ) になるよう修正する |

## 何を解決するか

考え方と手順の正本は同梱の [SKILL.md](skills/doc-dag/SKILL.md) です。ここは要点だけを書きます。

同じ規則・値・手順が複数の文書に書かれていると、**片方を直しても、もう片方が古い事実を語り続けます。** レビュー指摘が修正のたびに再生産されるループは、たいていこの構造が発生源です。

このスキルは、重複を「片方を消す」のではなく **「向きを付ける」** ことで解消します。正本を 1 つ決め、他はそこへの参照にします。読みやすさのための要約は残してよく、その場合は正本へのリンクを添えます。

**機械検査ではありません。** 意味の重複の同定には読みの判断が要るため、エージェントが読み比べ、図にして人間に示します。

## mermaid-preview との関係

図の提示は [mermaid-preview](../mermaid-preview/README.md) が担います。**別プラグインなので、併せて導入してください。**

```bash
claude plugin install mermaid-preview@akm-claude-plugins
claude plugin install doc-dag@akm-claude-plugins
```

`mermaid-preview` が無くても調査と図のソース生成までは動きますが、ブラウザでの提示はできません (無いときの振る舞いは [SKILL.md](skills/doc-dag/SKILL.md) の手順 3 が定めます)。

## プロジェクト固有の設定 (任意)

`.claude/akm-claude-plugins/doc-dag/config.json` に置きます。**無くても動きます。**

```json
{
  "frozen_paths": ["docs/brainstorms/", "docs/plans/", "docs/solutions/"],
  "doc_check_command": "make check-docs"
}
```

- `frozen_paths` — 当時の記録として書き換えない文書のパス接頭辞。重複の片側がここにある場合、書き換えずに済む解消案を人間に提案します。
- `doc_check_command` — 修正後に走らせるドキュメント検査。このスキルの修正はリンクの張り替えを伴うため、**リンク切れの検査があると安全**です。未設定の場合、検査を走らせていないことを報告に明記します。

詳細は同梱の [project-config.md](skills/doc-dag/references/project-config.md) を参照してください。

## 使い方

インストール手順は [リポジトリの README](../README.md#使い方) を参照してください。

```bash
claude plugin marketplace add akm/claude-plugins
claude plugin install doc-dag@akm-claude-plugins
```

「ドキュメントの依存関係を図にして」「重複を調べて DAG にして」のように依頼すると起動します。規範文書を書いた直後や、修正ラウンドの後の構造確認にも使えます。
