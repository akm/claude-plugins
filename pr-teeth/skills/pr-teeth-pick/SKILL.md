---
name: pr-teeth-pick
description: 番号やURLで指定したGitHubのPRを、オープン・クローズ済み・マージ済みを問わず取得し、差分とチェックアウトしたブランチまで見て精査して、硬くてとっつきにくい部分を噛み砕いて、設定した出力言語(既定: 日本語)で分かりやすい解説をHTMLで作る。複数のPRをまとめて指定できる。Use when: マージ済みPRを後から読んで理解したい, この PR の内容を教えて, 指定したPRを解説, owner/repo#123 を噛み砕いて, PRのURLを貼って説明を求める, explain this PR, /pr-teeth-pick。
---

# pr-teeth-pick

**番号や URL で指定した** PR を噛み砕いて解説する。オープン・クローズ済み・マージ済みを問わない。

`/pr-teeth`（レビュー依頼の巡回）との違いは**対象の決め方だけ**で、噛み砕き方・用語集・
出力は共通。想定する使い方は次の2つ。

- マージ済み PR を後から読んで**学習する**（レビューではなく理解のため）
- レビューし損ねた PR を**振り返る**

**このスキルは読み取り専用です。** GitHub へのコメント・承認・マージ等の書き込みは、
ユーザーに明示的に指示されても行いません（レビューはユーザー自身が行うため）。

## 引数

- PR の指定（1つ以上、**必須**）… 次のどちらの形でもよい。混在も可。
  - `owner/repo#123`
  - `https://github.com/owner/repo/pull/123`（末尾に `/files` 等が付いていてもよい）
- `lang=<言語タグ>` … その実行の出力言語を上書きする（例 `lang=en`）。

指定が無ければ、**どの PR を解説するかを尋ねてから**進む。推測で対象を決めない。

## `/pr-teeth` と違うところ

| | `/pr-teeth`（巡回） | `/pr-teeth-pick`（番号指定） |
| --- | --- | --- |
| 対象 | レビュー依頼が来ているオープンな PR 全件 | **指定された PR だけ**（open/closed 問わず） |
| `state.json` | `mode=changes-only` で読み書き | **読み書きしない** |
| 「前回からの変更」 | 更新された PR で出す | **出さない**（毎回全体を解説する） |
| レビュー範囲の表示 | 必須 / 推奨 / 対象外 | **重点 / 参考 / 周辺**（`--context pick`） |
| 用語集 | 蓄積する | **同じように蓄積する** |

**`state.json` を読み書きしない理由:** あれは巡回時の通知の重複抑制用で、
指定した PR を解説することとは無関係。番号指定は state を見ないので「前回からの
差分」という概念も無く、毎回全体を解説する。

**レビュー範囲を表示する理由:** 分類そのものは、大きい PR でどこから読むべきかの
手がかりとして有用。ただしマージ済み PR に「レビュー必須」と出るのは意味がずれる
（レビューはもう終わっている）ため、**読み方の指標**として文言を変えて見せる。

## 手順

### 1. 準備（設定の読み込み）

次を実行する。`--plugin-source` の値は**このプラグインの配布元**であり、
設定ディレクトリの場所を決める。

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pr_teeth.py" prepare \
  --plugin-source "github.com/akm/claude-plugins" \
  --mode full
```

`lang=` が指定されていれば `--lang <値>` を付ける。

出力される JSON から次を読み取る。

- `config_dir` … 設定ディレクトリ
- `default_language` … HTML の `lang` に使う言語
- `warnings` … 設定ファイルが壊れている等。**あれば最終出力の冒頭に必ず載せる**
- `token_source` … 見つかった認証の入手元。`null` なら**その旨だけ伝えて終了する**
  （探索や回避を自分で試みない）

`--mode full` を渡すのは、state を読ませないため（`changes-only` を渡すと state を
読みにいく）。番号指定は state と無関係。

### 2. 指定された PR の解釈

**URL や番号の解釈を自分で行わない。** 次に渡す。

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pr_teeth.py" resolve \
  --plugin-source "github.com/akm/claude-plugins" \
  "owner/repo#123" "https://github.com/owner/repo/pull/456"
```

返る `targets` の各要素に `repo` / `number` / `language` が付く。同じ PR を2回
指定した場合は1件に畳まれる。

- **`invalid` が空でなければ、その内容を最終出力に必ず載せる。** 解釈できなかった
  指定を黙って捨てると、渡したはずの PR が出力に無いことに気づけない。
- `resolved` が 0 なら、解釈できた指定が1つも無い。**その旨を伝えて終了する**
  （勝手に別の PR を探しにいかない）。

**指定は必ず引用符で囲んで渡す。** `owner/repo#123` の `#` は語の途中にあるため
bash / zsh ではコメントにならないが、囲っておけば履歴展開やグロブを含め、
シェルの解釈に左右されない。

### 3. PR の取得

各 PR について、状態を問わず取得する。`gh pr view` は番号で1件を引くコマンドなので、
状態による絞り込みは起きない（`--state` というフラグ自体が無い）。

`/pr-teeth` でマージ済みが落ちるのは、この取得段ではなく**一覧を検索する段**の
`gh search prs --state=open` による。番号指定にはその検索段が無いため、
下流をそのまま使える。

```bash
gh pr view <番号> --repo <owner/repo> \
  --json files,headRefOid,title,author,body,state,mergedAt,labels,closingIssuesReferences
```

`state` は `OPEN` / `MERGED` / `CLOSED` のいずれかで、**これだけでマージ済みか
クローズのみかが分かる**（`merged` というフィールドは存在しない。指定すると
`Unknown JSON field` でコマンドごと失敗する）。解説の書き分けに使う（手順 7）。

取得に失敗した PR は**注記を付けて残し、他の PR の処理は止めない。**

### 4. 範囲分類と言語解決

PR ごとに、変更ファイル一覧を渡して分類する。手順は `/pr-teeth` と同じ。

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pr_teeth.py" classify \
  --plugin-source "github.com/akm/claude-plugins" \
  --repo "<owner/repo>" --files-from <ファイル一覧のJSON>
```

戻り値の `priority`（`must_review` / `should_review` / `ignore`）と `counts` は
**そのまま手順 7 に渡す。** 表示文言の差し替えは `render` 側で行うので、ここで
「重点」等に読み替えない。

`language` をその PR の解説言語として使う。

### 5. 深掘り

`/pr-teeth` の手順 4 と同じ。**ただし「前回からの差分」は見ない**（毎回全体が対象）。

1. リポジトリを clone（既存なら fetch）し、PR のブランチを checkout する。
   作業場所は `config_dir` の `repos/` 配下を使う。

   マージ済み・クローズ済みの PR でも、head は取得できる。

   ```bash
   git fetch origin pull/<番号>/head:pr-<番号> && git checkout pr-<番号>
   ```

   head が消えている場合（fork が削除された等）は、その旨を注記して
   **差分だけで解説する**（`gh pr diff <番号> --repo <owner/repo>`）。無理に clone しない。
2. 差分と PR 本文を読む。
3. **文脈依存の語は憶測せず、そのブランチ上で裏取りする。**
   `rg` で定義・使われ方・呼び出し元を検索し、一次情報で意味を確定する。
   根拠が見つからなければ「（コード上で定義を確認できず）」と明記する。
   用語集で `known` の語は裏取りも説明も省いてよい。

巨大な PR は中心的な変更に絞る。無制限に clone・解析してディスクと時間を使わない。

### 6. 用語の扱い

`/pr-teeth` の手順 5 と**完全に同じ**。用語集は全リポジトリ横断でひとつなので、
振り返りで読んだ語も巡回時と同じように蓄積する（理解が進めば、どちらの経路でも
説明が減っていく）。

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pr_teeth.py" lookup \
  --plugin-source "github.com/akm/claude-plugins" \
  --language <その PR の言語> --terms "語1" "語2"
```

| status | 説明 |
| --- | --- |
| `new` | フルで説明する |
| `learning` | 1〜2行の軽い再掲にとどめる |
| `known` | **説明しない**（原語のまま使う） |

### 7. 解説の作成

PR ごとに、**その PR の解決済み言語**で書く。構成は `/pr-teeth` と同じだが、
次の2点が違う。

- **「前回からの変更」は出さない。** 毎回全体を解説する。
- **マージ済み・クローズ済みの PR では、その事実を書く。** 手順 3 の `state` と
  `mergedAt` から、「マージ済み（YYYY-MM-DD）」のように冒頭に示す。
  読み手が「これはもう入っている変更か、まだ議論中か」を最初に把握できるようにする。
  **`state` が `CLOSED`（マージされずに閉じられた）の PR は特にそう明記する**
  （入っていない変更を、入ったものとして読ませない）。

書く項目:

- 見出し … `owner/repo #番号 「タイトルをその言語で要約したもの」`
- 状態（マージ済み / クローズ済み / オープン）
- 読み方の指標 … 重点・参考・周辺の件数（`render` が `counts` から出す）
- 何をする PR か（1〜3文）／なぜ必要か・背景
- 図（Mermaid。単純なら省略）
- 主な変更点（重点範囲を厚めに）
- 読むときの手がかり・注意点
- 用語解説（手順 6 のとおり。裏取りの根拠を添える）

言語ルールは `/pr-teeth` と同じ。`known` の語と固有名詞・識別子は原語のまま、
曖昧な点は「推測」と明示する。

### 8. 出力と保存

HTML を生成する。**`--context pick` を必ず付ける**（付け忘れると「レビュー必須」と
表示され、マージ済み PR に対して意味がずれる）。

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pr_teeth.py" render \
  --plugin-source "github.com/akm/claude-plugins" \
  --context pick \
  --input <解説をまとめたJSON>
```

入力 JSON の形は `/pr-teeth` の手順 7 と**同じ**。`priority` と `counts` には
`classify` が返した値をそのまま入れる（表示文言は `--context pick` が切り替える）。

```json
{
  "prs": [
    {
      "repo": "<owner/repo>",
      "number": 123,
      "title": "<タイトルをその PR の言語で要約したもの>",
      "priority": "must_review",
      "language": "<その PR の言語>",
      "author": "<作者>",
      "counts": {"must_review": 3, "should_review": 5, "ignore": 4},
      "summary": "<何をする PR か。1〜3文>",
      "background": "<なぜ必要か>",
      "changes": ["<主な変更点>"],
      "review_points": ["<読むときの手がかり>"],
      "terms": [
        {"term": "<語>", "definition": "<説明>", "status": "new",
         "evidence": "<裏取りした根拠 file:line>"}
      ],
      "diagram": "<Mermaid のコード。単純なら省略>",
      "note": "<状態（マージ済み等）や、取得・解析に失敗した場合の注記>"
    }
  ]
}
```

- **`url` は渡さない。** `repo` と `number` から導出される。
- **未知のキーを含めるとエラーになる。** 使えるキーは上表のとおり。
- `context` は `--context pick` で渡すので、JSON には入れなくてよい。

生成された HTML の**パスを必ず伝える**。

続いて用語集を保存する。**`--notified` と `--open-prs` は渡さない**
（state を触らないため。渡すと巡回時の記録を汚す）。

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pr_teeth.py" record \
  --plugin-source "github.com/akm/claude-plugins" \
  --input <出現語と定義のJSON>
```

`--input` の形は次のとおり。**`terms` でラップする**（配列を直接渡すとエラーになる）。

```json
{"terms": [
  {"term": "<語>", "language": "<言語タグ>", "definition": "<説明>",
   "provenance": "<owner/repo#番号 file:line>"}
]}
```

返り値の **`terms_recorded` を必ず確認する。** 記録した語数と一致しなければ、
入力が意図どおりでない。`terms_skipped` と `warnings` に理由が出る。

### 9. 昇格の提案（対話実行時のみ）

`/pr-teeth` の手順 8 と同じ。会話の中でユーザーがその語を自分から正しく使う等の
兆候があれば、末尾で軽く確認する。

> 「◯◯」は理解済みにしますか？（以降この語の説明を省きます）

**承認を得るまで昇格させない。**

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pr_teeth.py" promote \
  --plugin-source "github.com/akm/claude-plugins" \
  --term "<語>" --status known
```

## 失敗したとき

- 取得・解析に失敗した PR があっても**全体を止めない。** その PR に注記を付け、
  成功した分だけでも出力する。
- 解釈できなかった指定（手順 2 の `invalid`）は必ず伝える。
- トークンが無い場合は、その旨だけ伝えて終了する（探索や回避を試みない）。

### CLI がエラーを返したとき

出力の `error` を読み、種類に応じて対応する。

| 内容 | 意味 | 対応 |
| --- | --- | --- |
| `... を読めません（JSON として不正 ...）` + `hint` | **用語集が壊れている** | **勝手に削除・再作成しない。** `hint` の内容をそのままユーザーに伝え、退避か修復を仰ぐ |
| `入力に ... キーがありません` / `期待する形: ...` | 渡した JSON の形が違う | メッセージ内の「期待する形」に合わせて組み直し、再実行する |
| `を PR の指定として解釈できません` | 指定の形が違う | 期待する形をユーザーに示し、指定し直してもらう |

**どのコマンドも `warnings` が空でないか確認し、空でなければ最終出力に載せる。**

## fork する場合

`--plugin-source` の値（`github.com/akm/claude-plugins`）は、`/pr-teeth` および
`/pr-glossary` と**必ず同じ値**にする。片方だけ書き換えると設定ディレクトリが分かれ、
用語集を見失う。

実行時に配布元を推定する手段は採らない（`${CLAUDE_PLUGIN_ROOT}` はインストール先しか
返さず、そこから配布元を辿る経路は非公式で、壊れると設定と用語集を見失うため）。
