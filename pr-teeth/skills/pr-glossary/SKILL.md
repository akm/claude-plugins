---
name: pr-glossary
description: pr-teeth が蓄積した用語集を、理解済み・学習中・新出のポートフォリオとしてHTMLで表示し、用語のステータス変更(理解済みにする/戻す)や定義の編集を行う。Use when: 用語集を見たい, 用語ポートフォリオ, 理解済みにする, どれくらい用語を覚えたか, glossary, /pr-glossary。
---

# pr-glossary

pr-teeth の用語集を確認・編集する。

用語のステータスは説明の厚みを決める（`new`=フル説明 / `learning`=軽い再掲 /
`known`=説明を省略）。ここでの変更は、以降の `/pr-teeth` の出力に効く。

## 引数

- 引数なし … ポートフォリオを HTML で表示する。
- `known <語>` / `learning <語>` / `new <語>` … その語のステータスを変更する。
- `lang=<言語タグ>` … 表示言語を上書きする。

## 手順

### 表示する

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pr_teeth.py" glossary-html \
  --plugin-source "github.com/akm/claude-plugins"
```

出力された `path` をユーザーに伝える。`counts` を使い、理解済み・学習中・新出が
それぞれ何語かを一言添える。

画面の地の文はユーザー既定の言語で出る。ある語にその言語の定義がまだ無い場合は、
他言語の定義が `(ja) …` のように言語タグ付きで表示される（既存の定義を隠さないため）。

### ステータスを変える

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pr_teeth.py" promote \
  --plugin-source "github.com/akm/claude-plugins" \
  --term "<語>" --status known
```

- `known` にすると、以降その語は**説明されなくなる。**
- ステータスは言語をまたいで共有される。日本語で `known` にした語は、英語で出力した
  ときも説明が省かれる（理解しているかどうかは出力言語に依らないため）。
- 戻したい場合は `--status learning` または `--status new` を指定する。

ユーザーが語を明示せずに「理解済みにして」とだけ言った場合は、**どの語かを確認してから**
実行する。取り違えると、まだ理解していない語の説明が黙って消える。

### 定義を編集する

`glossary.json` を直接編集する。場所は次で確認できる。

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pr_teeth.py" prepare \
  --plugin-source "github.com/akm/claude-plugins"
```

`definitions` は言語タグをキーにしたマッピングで、言語ごとに説明文を持つ。
`term` / `status` / `occurrences` は言語非依存なので、言語ごとに分けない。

```json
{
  "term": "reconciliation loop",
  "status": "learning",
  "definitions": {
    "ja": "あるべき状態と実際の状態を突き合わせて差分を埋め続ける処理。",
    "en": "A loop that continuously compares desired state to actual state."
  },
  "occurrences": 4
}
```

## fork する場合

`--plugin-source` の値は `/pr-teeth` 側と**必ず同じ値**にする。片方だけ書き換えると
設定ディレクトリが分かれ、用語集を見失う。
