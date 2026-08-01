---
name: pr-teeth
description: 自分にレビュー依頼が来ているGitHubのPRを巡回し、各PRを差分とチェックアウトしたブランチまで見て精査し、リポジトリ別の範囲設定に照らして、硬くてとっつきにくい部分を噛み砕いて、設定した出力言語(既定: 日本語)で分かりやすい解説をHTMLで作る。Use when: レビュー依頼のPRを噛み砕いて確認したい, review-requested PRs, PR巡回, PRの内容を分かりやすく説明, explain review-requested PRs, /pr-teeth。
---

# pr-teeth

レビュー依頼が来ている PR を噛み砕いて解説する。

**このスキルは読み取り専用です。** GitHub へのコメント・承認・マージ等の書き込みは、
ユーザーに明示的に指示されても行いません（レビューはユーザー自身が行うため）。

## 引数

- `mode=full`（既定）… 現在オープンのレビュー依頼 PR を全件解説する。
- `mode=changes-only` … 前回以降の新規・更新分のみ。定期実行用。
- `lang=<言語タグ>` … その実行の出力言語を上書きする（例 `lang=en`）。

引数が無ければ `mode=full`、言語は設定ファイル任せ（既定 `ja`）。

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
- `default_language` … 通知の地の文と HTML の `lang` に使う言語
- `warnings` … 設定ファイルが壊れている等。**あれば最終出力の冒頭に必ず載せる**
  （黙って既定値で動くと、設定したのに効いていないことに気づけない）
- `token_source` … 見つかった認証の入手元。`null` なら**その旨だけ伝えて終了する**
  （`GITHUB_TOKEN` → `GITHUB_TOKEN_FILE` → `gh auth token` の順に探した結果。
  探索や回避を自分で試みない）

### 2. PR 一覧の取得

`gh` があれば使い、無ければ `curl` で REST API を叩く。トークンは環境変数で渡し、
**値をログ・生成物・通知に出さない。** 表示してよいのは `token_source` だけ。

```bash
gh search prs --review-requested=@me --state=open --json repository,number,title,author,updatedAt --limit 50
```

各 PR について変更ファイル一覧と head SHA を取得する。

```bash
gh pr view <番号> --repo <owner/repo> --json files,headRefOid,body,labels,closingIssuesReferences
```

### 3. 範囲分類と言語解決

PR ごとに、変更ファイル一覧を渡して分類する。

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pr_teeth.py" classify \
  --plugin-source "github.com/akm/claude-plugins" \
  --repo "<owner/repo>" --files-from <ファイル一覧のJSON>
```

戻り値の `priority`（`must_review` / `should_review` / `ignore`）で PR を並べ、
`language` をその PR の解説言語として使う。

`mode=changes-only` のときは `state.json` と比べ、新規または head SHA が変わった
PR だけを対象にする。対象が 0 件なら**何も通知せず静かに終了する**。

### 4. 深掘り

`must_review` / `should_review` に該当する変更を中心に調べる。
`ignore` のみの PR は軽く要約するだけでよく、clone もしない。

1. リポジトリを clone（既存なら fetch）し、PR のブランチを checkout する。
   作業場所は `config_dir` の `repos/` 配下を使う。
2. 差分と PR 本文を読む。
3. **文脈依存の語は憶測せず、そのブランチ上で裏取りする。**
   `rg` で定義・使われ方・呼び出し元を検索し、一次情報で意味を確定する。
   根拠が見つからなければ「（コード上で定義を確認できず）」と明記する。
   用語集で `known` の語は裏取りも説明も省いてよい。

巨大な PR は中心的な変更に絞る。無制限に clone・解析してディスクと時間を使わない。

### 5. 用語の扱い

説明が必要そうな語ごとに、状態と既存の定義を引く。

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pr_teeth.py" lookup \
  --plugin-source "github.com/akm/claude-plugins" \
  --language <その PR の言語> --terms "語1" "語2"
```

返る `status` に従って説明の厚みを変える。

| status | 説明 |
| --- | --- |
| `new` | フルで説明する |
| `learning` | 1〜2行の軽い再掲にとどめる |
| `known` | **説明しない**（原語のまま使う） |

`definition` が返ればそれを使う。無ければその言語の説明を書き、手順 7 で記録する。
`other_languages` に他言語の定義があれば、それを訳す形で揃えると表現がぶれない。

### 6. 解説の作成

PR ごとに、**その PR の解決済み言語**で書く。

- 見出し … `owner/repo #番号 「タイトルをその言語で要約したもの」`
- レビュー範囲サマリ … 必須・推奨・対象外の件数と推奨アクション
- 何をする PR か（1〜3文）／なぜ必要か・背景
- 図（後述。単純なら省略）
- 主な変更点（必須・推奨範囲を厚めに）
- レビューで見るべき点・注意点
- 用語解説（手順 5 のとおり。裏取りの根拠を添える）

言語ルール:

- 設定された出力言語で書き、不必要な他言語の混入を避ける。
- `known` の語と固有名詞・識別子（リポジトリ名、パス、関数名、コマンド）は原語のまま。
- 曖昧な点は「推測」と明示する。断定しない。
- 出力言語が変わっても、構成・粒度・裏取りの厳しさは変えない。

**図（Mermaid）** は理解を助けるときだけ付ける。PR/Issue の関係、変更が関わる
構造や処理の流れなど。Issue と PR が 1 対 1 で他に関係が無く、構造的にも示すほどの
関係が無い場合は省略する。ノードのラベルはその PR の言語で書く（識別子は原語）。

### 7. 出力と保存

HTML を生成する。

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pr_teeth.py" render \
  --plugin-source "github.com/akm/claude-plugins" \
  --input <解説をまとめたJSON> --open
```

入力 JSON の形は `render --help` を参照。生成された HTML の**パスを必ず伝える**。

続いて用語集と状態を保存する。

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pr_teeth.py" record \
  --plugin-source "github.com/akm/claude-plugins" \
  --input <出現語と定義のJSON>
```

`mode=changes-only` のときだけ `--state <PRと head SHA のJSON>` も渡す。
`mode=full` では state を変更しない。

プッシュ通知（使える環境なら）は件数と各 PR の1行要約。地の文は `default_language`、
各 PR の要約はその PR の言語で書く。

### 8. 昇格の提案（対話実行時のみ）

会話の中で、ユーザーがその語を自分から正しく使う・別の説明に用いる・その語を前提に
した踏み込んだ質問をする、といった兆候があれば、末尾で軽く確認する。

> 「◯◯」は理解済みにしますか？（以降この語の説明を省きます）

**承認を得るまで昇格させない。** 推定だけで確定すると、偽陽性で説明が勝手に消える。
`mode=changes-only`（無人実行）では会話が無いため、**この手順は行わない。**

承認されたら記録する。

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pr_teeth.py" promote \
  --plugin-source "github.com/akm/claude-plugins" \
  --term "<語>" --status known
```

## 失敗したとき

- 取得・解析に失敗した PR があっても**全体を止めない。** その PR に注記を付け、
  成功した分だけでも出力する。
- トークンが無い場合は、その旨だけ伝えて終了する（探索や回避を試みない）。

## fork する場合

`--plugin-source` の値（`github.com/akm/claude-plugins`）は、このファイル内の
**すべての実行例で同じ値を使っている。** fork して別のマーケットプレイスから配布する
場合は、この値を fork 側の配布元に一括で書き換えること。設定ディレクトリの場所が
変わるため、既存利用者には移行を案内する。

実行時に配布元を推定する手段は採らない（`${CLAUDE_PLUGIN_ROOT}` はインストール先しか
返さず、そこから配布元を辿る経路は非公式で、壊れると設定と用語集を見失うため）。
