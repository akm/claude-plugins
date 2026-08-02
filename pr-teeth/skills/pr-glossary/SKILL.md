---
name: pr-glossary
description: pr-teeth が蓄積した用語集を、理解済み・学習中・新出のポートフォリオとしてHTMLで表示し、用語のステータス変更(理解済みにする/戻す)や定義の編集を行う。Use when: 用語集を見たい, 用語ポートフォリオ, 理解済みにする, どれくらい用語を覚えたか, glossary, /pr-glossary。
---

# pr-glossary

pr-teeth の用語集を確認・編集する。

用語のステータスは説明の厚みを決める（`new`=フル説明 / `learning`=軽い再掲 /
`known`=説明を省略）。ここでの変更は、以降の `/pr-teeth` と `/pr-teeth-pick` の
出力に効く（用語集は全リポジトリ・全コマンド横断でひとつ）。

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

出力された `path` をユーザーに伝える。併せて、返り値の `open_command` を
**`bash` のコードブロックで示す**（実行ボタンが出るため、クリック1回で開ける）。
コマンドは返り値のものをそのまま使う。プラットフォーム別の判定は済んでいる。
`counts` を使い、理解済み・学習中・新出がそれぞれ何語かを一言添える。

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

返り値の **`created` が `true` なら綴り違いを疑う。** その語は用語集に無く、新しく
作られている。ユーザーに確認してから、不要なら元の語で入れ直す。

用語集が壊れていて読めない場合、コマンドは**保存せずエラーで終了する**（上書きを避けるため）。
その場合は `hint` の内容をユーザーに伝え、退避か修復を仰ぐ。勝手に削除・再作成しない。

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

`--plugin-source` の値は `/pr-teeth`・`/pr-teeth-pick` 側と**必ず同じ値**にする。
一部だけ書き換えると設定ディレクトリが分かれ、用語集を見失う。
