---
name: pr-teeth
description: 自分にレビュー依頼が来ているGitHubのPRを巡回し、各PRを差分とチェックアウトしたブランチまで見て精査し、リポジトリ別の範囲設定に照らして、硬くてとっつきにくい部分を噛み砕いて、設定した出力言語(既定: 日本語)で分かりやすい解説をHTMLで作る。Use when: レビュー依頼のPRを噛み砕いて確認したい, review-requested PRs, PR巡回, PRの内容を分かりやすく説明, explain review-requested PRs, /pr-teeth。
---

# pr-teeth

レビュー依頼が来ている PR を噛み砕いて解説する。

**このスキルは読み取り専用です。** GitHub へのコメント・承認・マージ等の書き込みは、
ユーザーに明示的に指示されても行いません（レビューはユーザー自身が行うため）。

**番号や URL で PR を指定された場合は、このスキルではなく `/pr-teeth-pick` を使う。**
こちらは「レビュー待ちを消化する」ためのもので、対象はオープンな依頼に限られる
（クローズ済み・マージ済みは取得クエリの `--state=open` で落ちる）。

## 引数

- `mode=full`（既定）… 現在オープンのレビュー依頼 PR を全件解説する。
- `mode=changes-only` … 前回以降の新規・更新分のみ。定期実行用。
- `lang=<言語タグ>` … その実行の出力言語を上書きする（例 `lang=en`）。

引数が無ければ `mode=full`、言語は設定ファイル任せ（既定 `ja`）。

## 手順

### 1. 準備（設定の読み込み）

次を実行する。

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pr_teeth.py" prepare \
  --mode full
```

`lang=` が指定されていれば `--lang <値>` を付ける。

出力される JSON から次を読み取る。

- `config_dir` … 設定ディレクトリ
- `default_language` … 通知の地の文と HTML の `lang` に使う言語
- `warnings` … 設定ファイルが壊れている等。**あれば最終出力の冒頭に必ず載せる**
  （知らせずに既定値で動くと、設定したのに適用されていないことに気づけない）
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
  --repo "<owner/repo>" --files-from <ファイル一覧のJSON>
```

戻り値の `priority`（`must_review` / `should_review` / `ignore`）で PR を並べ、
`language` をその PR の解説言語として使う。

`mode=changes-only` のときは、対象を絞り込む。

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pr_teeth.py" select \
  --input <PR一覧のJSON>
```

入力は `[{"repo","number","sha","updated_at","body"}]`。**`body` には手順 2 で
取得した PR 本文をそのまま入れる**（本文の差分を出すのに使う）。返る `targets` の
各要素には次が付く。**`selected` が 0 なら何も通知せず終了する。**

- `status` … `new`（初めて見る）／ `updated`（前回から変わった）
- `base_sha` … `updated` のときの**差分の起点**。手順 4・6 で使う
- `body_diff` … 前回の本文からの差分（unified diff）。手順 6 で使う
- `body_diff_available` … 前回の本文が保管されていたか。`false` なら比較できない
  （初回・掃除済み）ので、本文の差分は出さずに全体を説明する

`sha` と `updated_at` のどちらかが変われば更新と判定される。コミットを伴わない
更新（PR 本文の書き直し、レビューコメントの追加）も拾うため。

**`body_diff` が空文字なら本文は変わっていない。** コードだけが変わった更新で
「本文が変わった」と書かないこと。

### 4. 深掘り

`must_review` / `should_review` に該当する変更を中心に調べる。
`ignore` のみの PR は軽く要約するだけでよく、clone もしない。

1. 作業リポジトリを用意する。**`git clone` を直接実行しない**
   （置き場所・取得量・掃除をコード側で決めるため）。

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pr_teeth.py" repo \
     --repo "<owner/repo>"
   ```

   返り値の `path` が作業場所。既にあれば fetch される。上限を超えた古い
   リポジトリの掃除もここで行われるため、別途消す必要はない。
   `removed` が空でなければ、何を消したか最終出力に含めてよい。

   用意できたら PR のブランチを checkout する。clone は `--no-checkout` の
   部分クローンなので、**まず対象のコミットを取得する**。

   ```bash
   git -C "<path>" fetch origin "pull/<番号>/head"
   git -C "<path>" checkout FETCH_HEAD
   ```
2. 差分と PR 本文を読む。
   **`status` が `updated` の PR では、`base_sha` からの差分を中心に見る。**

   ```bash
   git diff <base_sha>..<現在のSHA>
   ```

   `base_sha` がローカルに無い場合（fetch していない等）は、その旨を注記して
   全体を対象にする。無理に差分を作らない。
3. **文脈依存の語は憶測せず、そのブランチ上で裏取りする。**
   `rg` で定義・使われ方・呼び出し元を検索し、一次情報で意味を確定する。
   根拠が見つからなければ「（コード上で定義を確認できず）」と明記する。
   用語集で `known` の語は裏取りも説明も省いてよい。

巨大な PR は中心的な変更に絞る。無制限に解析してディスクと時間を使わない
（clone の量と保持数は `repo` 側で抑えている）。

### 5. 用語の扱い

説明が必要そうな語ごとに、状態と既存の定義を引く。

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pr_teeth.py" lookup \
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
- **前回からの変更**（`status` が `updated` のときだけ。新規では出さない）
  … `base_sha` からのコード差分で、何がどう変わったかを先に示す。
  そのうえで以下の全体解説を続ける。時間が空くと前回の内容を覚えていないため、
  差分だけでは読めない。
  - **本文（description）が変わっていれば、それも示す。** 手順 3 の `body_diff`
    を読み、追記・修正された箇所を噛み砕いて説明する。レビューを受けて本文が
    補足されるケースは多く、コードの差分と同じくらい重要な更新である。
  - `body_diff` が空、または `body_diff_available` が `false` なら**本文には触れない**。
    前者は本文が変わっていない場合、後者は比較する材料が無い場合。
  - 差分をそのまま貼らない。**何がどう変わったかを文章で説明する**
    （`+`/`-` の羅列は読み手の負担になる）。
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
  --input <解説をまとめたJSON>
```

入力 JSON の形は次のとおり。

```json
{
  "language": "<ページ全体の言語。省略時は設定から>",
  "prs": [
    {
      "repo": "<owner/repo>",
      "number": 123,
      "title": "<タイトルをその PR の言語で要約したもの>",
      "priority": "must_review",
      "language": "<その PR の言語>",
      "author": "<作者>",
      "counts": {"must_review": 3, "should_review": 5, "ignore": 4},
      "recommendation": "<推奨アクション。手順 3 の範囲サマリから>",
      "summary": "<何をする PR か。1〜3文>",
      "background": "<なぜ必要か>",
      "changes": ["<主な変更点>"],
      "review_points": ["<見るべき点>"],
      "terms": [
        {"term": "<語>", "definition": "<説明>", "status": "new",
         "evidence": "<裏取りした根拠 file:line>"}
      ],
      "diagram": "<Mermaid のコード。単純なら省略>",
      "note": "<取得や解析に失敗した場合の注記>"
    }
  ]
}
```

| キー | 必須 | 内容 |
| --- | --- | --- |
| `repo` / `number` | ○ | `gh` から取得したもの。**PR の URL はここから導出される** |
| `title` | ○ | その PR の言語で要約したタイトル |
| `priority` | ○ | 手順 3 の `classify` が返した値をそのまま |
| `counts` | | 手順 3 の `classify` が返した値をそのまま |
| その他 | | 省略可。空なら該当セクションが出ない |

- **`url` は渡さない。** `repo` と `number` から導出される。
- **未知のキーを含めるとエラーになる。** タイポを知らせずに捨てると、そのセクションが
  消えたまま成功したように見えるため。上表以外のキーは使えない。
- `priority` が `ignore` の PR は自動で1行に畳まれる。並び替えも自動。

生成された HTML の**パスを必ず伝える**。併せて、返り値の `open_command` を
**`bash` のコードブロックで示す**（実行ボタンが出るため、クリック1回で開ける）。
コマンドは返り値のものをそのまま使う。プラットフォーム別の判定は済んでいる。

続いて用語集と状態を保存する。

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pr_teeth.py" record \
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

`mode=changes-only` のときは、状態の保存も行う。形式は手順 3 の `select` と同じ
`[{"repo","number","sha","updated_at","body"}]`。**引数を2つに分けている**ので、渡す
一覧が何なのかで使い分ける。

| 引数 | 渡すもの | 挙動 |
| --- | --- | --- |
| `--notified` | **今回処理した PR**（部分でよい） | 既存の記録にマージする |
| `--open-prs` | **オープンな依頼の全件** | ここに無い記録を掃除する |

**`--notified` には `body` を必ず入れる。** 次回の実行で本文の差分を出すための
材料になる（入れないと、次回は「比較する材料が無い」状態になる）。
`--open-prs` 側は掃除の判定にしか使わないため `body` は不要。

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pr_teeth.py" record \
  --input <出現語と定義のJSON> \
  --notified <今回処理したPRのJSON> \
  --open-prs <オープンな依頼の全件のJSON>
```

**`--open-prs` は「全件を確かに取得できた」ときだけ渡す。** 次のいずれかに当てはまる
場合は**渡さないこと**。渡すと、まだオープンな PR の記録が消えて次回に再通知される。

- 手順 2 の `gh` が途中で失敗した
- `--limit` の上限に達して切り詰められた可能性がある
- 一部のリポジトリだけを対象にした

`--open-prs` を渡さなければ記録は消えないので、**迷ったら渡さない**のが安全。
閉じた PR の記録は、次に全件取得できたときに掃除される。

`mode=full` では状態を変更しない（どちらの引数も渡さない）。

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
  --term "<語>" --status known
```

## 失敗したとき

- 取得・解析に失敗した PR があっても**全体を止めない。** その PR に注記を付け、
  成功した分だけでも出力する。
- トークンが無い場合は、その旨だけ伝えて終了する（探索や回避を試みない）。

### CLI がエラーを返したとき

出力の `error` を読み、種類に応じて対応する。

| 内容 | 意味 | 対応 |
| --- | --- | --- |
| `... を読めません（JSON として不正 ...）` + `hint` | **用語集か状態ファイルが壊れている** | **勝手に削除・再作成しない。** `hint` の内容をそのままユーザーに伝え、退避か修復を仰ぐ。上書きは避けられているのでデータは残っている |
| `入力に ... キーがありません` / `期待する形: ...` | 渡した JSON の形が違う | メッセージ内の「期待する形」に合わせて組み直し、再実行する |

**どのコマンドも `warnings` が空でないか確認し、空でなければ最終出力に載せる。**
設定が壊れている・語がスキップされたといった事実は、伝えないと利用者が気づけない。

## fork する場合

配布元は `scripts/prteeth/config.py` の `PLUGIN_SOURCE` が**唯一の置き場所**で、
設定ディレクトリの場所を決める。fork して別のマーケットプレイスから配布する場合は、
**そこ 1 箇所だけを** fork 側の配布元に書き換える。設定ディレクトリの場所が変わるため、
既存利用者には移行を案内する。

SKILL.md 側に配布元は書かない（3 ファイルに散ると書き換え漏れが起き、
`/pr-teeth` と `/pr-glossary` が別の設定ディレクトリを見て用語集を見失う）。

実行時に配布元を推定する手段は採らない（`${CLAUDE_PLUGIN_ROOT}` はインストール先しか
返さず、そこから配布元を辿る経路は非公式で、壊れると設定と用語集を見失うため）。
