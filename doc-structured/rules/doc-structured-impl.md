# doc-structured: 設計と実装の差分の規則

YAML に書いた設計と、実装 (実際のスキーマ) の差分を確認する検査 j と、差分の解消の規則です。テーブルとカラムの YAML の形式は [doc-structured-domains.md](doc-structured-domains.md) の節「テーブルとカラム」にあります。規則の SSOT (single source of truth。ある事実を定めている唯一の記述) はプラグインのこのファイルで、プロジェクトのファイル `.claude/rules/doc-structured-impl.md` はそのコピーです。

## 検査 j

検査 j は、ファイル名が `schema` で始まる YAML のテーブルとカラムと、マイグレーションを一時的なデータベースに適用した実際のスキーマを比べます。データベースが要るので、重い群の検査です。YAML の形式に誤りがある (検査 h が失敗する) ときは実行しません。

設定ファイル `.claude/akm-claude-plugins/doc-structured/config.yaml` に、マイグレーションのパターンとデータベースを書きます。

```yaml
version: 0.11.0
paths:
  migrations: migrations/**/*.sql
database:
  kind: postgresql
  image: postgres:17
  schema_actual: true
```

| キー | 中身 |
|---|---|
| `paths.migrations` | マイグレーションの SQL のファイルの glob のパターン 1 つ。リポジトリのルートからの相対パスで書く。`**` も使える |
| `database.kind` | `sqlite` か `postgresql` (必須) |
| `database.image` | PostgreSQL のコンテナのイメージ。`kind` が `postgresql` のときだけ書け、そのときは必須 |
| `database.schema_actual` | `true` を書くと、実際のスキーマのファイル `docs/system/schema-actual.md` を作る (下の節「実際のスキーマのファイル」) |

- `paths.migrations` と `database` は、どちらも書くか、どちらも書かないかのどちらかにする。書かないプロジェクトでは、検査 j は「設定に書く」と報告する。
- マイグレーションは、パターンに合うファイルを、リポジトリのルートからの相対パスの文字コードの順に適用する。
- SQLite は、Python の標準ライブラリ `sqlite3` で、メモリ上にデータベースを作る。PostgreSQL は、Docker で `database.image` のコンテナを起動し、スキーマを読んだ後に削除する。
- データベースが無い (SQLite では `sqlite3` を読み込めない、PostgreSQL ではコマンド `docker` が無いか Docker のデーモンに接続できない) ときは、検査 j を実行できない。マイグレーションを適用できないときは、検査 j の誤りとして報告する。

## 比べる項目

| 比べる | 比べない |
|---|---|
| テーブルの有無、カラムの名前・型・NULL を許可するか・デフォルト値、主キー、1 カラムの外部キー、一意の制約、インデックスのカラムの組 | カラムの並び順、制約とインデックスの名前、コメント、所有者と権限、CHECK 制約、部分インデックスの条件、外部キーの `ON DELETE`・`ON UPDATE`、式を含むインデックス、複数のカラムからなる外部キー |

- 比べるテーブルは、SQLite では名前が `sqlite_` で始まる内部のテーブルを除くすべてのテーブル、PostgreSQL ではスキーマ `public` のテーブル。ビュー・トリガー・シーケンス・関数は比べない。
- 主キーとインデックスのカラムの組は、順序を含めて比べる。
- 一意の制約 (`UNIQUE`) と一意のインデックス (`CREATE UNIQUE INDEX`) は、どちらも YAML の `indexes` の `unique: true` と比べる。主キーのためにデータベースが作るインデックスは比べない。
- 外部キーは、カラムの `references` が指すテーブルとカラムと比べる。参照先のカラムを省いた外部キー (`REFERENCES books`) は、参照先の主キーを指すものとして比べる。
- SQLite の `INTEGER PRIMARY KEY` のカラムは、NULL を許可しないものとして比べる。それ以外の主キーのカラムに `NOT NULL` が無ければ、SQLite では NULL が入るので、差分になる (YAML の主キーのカラムには `nullable` を書けないので、マイグレーションに `NOT NULL` を付ける)。
- 式を含むインデックスと、複数のカラムからなる外部キーは、YAML に書けないので比べない。実際のスキーマのファイルには載せる。

## 正規化

型とデフォルト値は、YAML の値と実際のスキーマの値を、同じ規則で正規化してから比べます。

| 対象 | 正規化 |
|---|---|
| 型 | 前後の空白を除き、連続する空白を 1 つにし、括弧とカンマの前後の空白を除き、小文字にする |
| 型 (PostgreSQL) | 別名を正式な名前にする (下の表)。`serial`・`bigserial`・`smallserial` (と `serial4`・`serial8`・`serial2`) は、型 `integer`・`bigint`・`smallint` とデフォルト値「連番」にする。実際のスキーマでは、そのカラムが持つシーケンスの `nextval(…)` をデフォルト値「連番」にする |
| デフォルト値 | 前後の空白と、全体を囲む括弧を除く。引用符の外は小文字にし、引用符の中はそのまま比べる |
| デフォルト値 (PostgreSQL) | 末尾の、そのカラムの型への型変換 (`::text` など) を除く |

| 別名 | 正式な名前 |
|---|---|
| `int`・`int4` | `integer` |
| `int8` | `bigint` |
| `int2` | `smallint` |
| `varchar` | `character varying` |
| `char`・`bpchar` | `character` (長さが無ければ `character(1)`) |
| `timestamp`・`time` | `timestamp without time zone`・`time without time zone` |
| `timestamptz`・`timetz` | `timestamp with time zone`・`time with time zone` |
| `bool` | `boolean` |
| `float8`・`float` | `double precision` |
| `float4` | `real` |
| `decimal` | `numeric` |
| `varbit` | `bit varying` |

- SQLite では、型の別名 (`int` と `integer` など) を同じものとして扱わない。SQLite は書いた型の文字列をそのまま保存し、別名の対応も決まっていないため。
- PostgreSQL の識別列 (`GENERATED … AS IDENTITY`) は、正規化しない。

## 結果の表

テーブル・カラム・インデックスのそれぞれについて、次の表で判定します。インデックスは、カラムの組で同じものかどうかを決め、一意かどうかは比べる項目として扱います。主キーはテーブルの、外部キーはカラムの比べる項目です。

| YAML | 実装 | `planned` | 結果 |
|---|---|---|---|
| ある | ある | なし | 成功 (比べる項目が違えばエラー「YAML か実装を直す」) |
| ある | ある | あり | エラー「実装されたので planned を外す」 |
| ある | ない | あり | 成功 |
| ある | ない | なし | エラー「planned: true を付けるか、YAML から消す」 |
| ない | ある | - | エラー「YAML に足す (または実装を戻す)」 |

- テーブルがエラーになれば (実装に無い・`planned` なのに実装にある・YAML に無い)、そのテーブルのカラムとインデックスは判定しない。
- `planned` のテーブル・カラム・インデックスは、実装にあれば「planned を外す」だけを報告し、比べる項目の違いは報告しない。
- 実装にだけあるものの誤りの位置は、設定ファイルの `paths.migrations` の位置。

差分は、設計と実装を 1 行に 1 つの事実を書いたテキスト (正規化した形) にし、その unified diff で示します。設計の正規化した形には、`planned` のものを含めません。

```diff
--- 設計 (docs/domains/ の schema*.yaml)
+++ 実装 (migrations/*.sql を sqlite に適用したもの)
@@ -21,7 +21,7 @@
 table loans column book_id: text not null
 table loans column id: text not null
 table loans column member_id: text not null
-table loans column reservation_id: text null
+table loans column reservation_id: integer null
 table loans column status: text not null default 'on_loan'
 table loans primary key id
 table loans foreign key book_id: books.id
```

- 行の種類は `table <テーブル>`・`column <カラム>: <型> null|not null [default <値>]`・`primary key <カラム>, …`・`foreign key <カラム>: <テーブル>.<カラム>`・`index <カラム>, … [unique]` の 5 つ。どの行も先頭にテーブル名を書く。
- 行は、テーブル名の順、テーブルの中は行の種類の順、同じ種類の中は名前の順に並べる。
- 削除の行 (`-`) は設計にだけあり、追加の行 (`+`) は実装にだけある。文脈は前後 3 行。

## 差分の解消

検査 j の差分は、`bin/doc-structured impl-diff-resolve` で 1 件ずつ、YAML を書き換えて解消できます。1 件は、節「結果の表」で判定する項目 (テーブル・カラム・インデックス) の 1 つです。カラムの型と NULL の両方が違っても 1 件です。マイグレーションは書き換えません。

件は、次の ID で指定します。`--list` は、件の ID と使えるフラグを、ほかの件より先に解消しないと検査 h が失敗する件から順に出力します (インデックスを消すのはカラムを消す前、足すのはカラムを足した後、など)。

| 項目 | ID |
|---|---|
| テーブル | テーブルの ID (`d-catalog-t-books`)。実装にだけあるテーブルは、足すドメインを含めた ID (`d-loans-t-fines`) |
| カラム | カラムの ID (`d-catalog-t-books-c-isbn`)。実装にだけあるカラムも、YAML に足した後の ID |
| インデックス | テーブルの ID の後に `:` と、カラム名をカンマ区切りで書く (`d-loans-t-loans:member_id,status`) |

| 件の場合 | `--planned` | `--unplanned` | `--match-impl` |
|---|---|---|---|
| YAML にあり、実装にもあり、`planned` がある | - | `planned` を外す | `planned` を外し、比べる項目も実装に合わせる |
| YAML にあり、実装に無く、`planned` が無い | `planned: true` を付ける | - | YAML から消す |
| YAML に無く、実装にある | - | - | YAML に足す |
| どちらにもあり、比べる項目が違う | - | - | 比べる項目を実装の値に書き換える |

- 「-」のフラグと、差分の無い項目には使えない。
- テーブルへの `--match-impl` が書き換えるのは、テーブルの有無と主キーだけ。カラムとインデックスの違いは、それぞれ別の件になる。テーブルを消す・足すときは、その下のカラムとインデックスも一緒に消す・足す。
- テーブルに `planned: true` を付けるときは、その下のカラムとインデックスの `planned` を外す (`planned` を重ねて書けないため)。
- YAML から消すのは、その項目だけ。ほかの記述 (主キー・インデックス・外部キーの `references`・属性の対応) が消す項目を指していれば、消さない。手書きの Markdown のリンクが消した ID を指していれば、その箇所を出力する。ファイルの最後のテーブルを消すときはファイルを、テーブルの最後のインデックスを消すときはキー `indexes` を消す。

YAML に足すときと、比べる項目を書き換えるときは、次の形で書きます。

| 書くもの | 形 |
|---|---|
| テーブルを足す場所 | `--file` で指定した YAML (そのドメインのディレクトリの下の、ファイル名が `schema` で始まる YAML。無ければ作る) か、ドメインのディレクトリの直下の `schema.yaml` (無ければ作る) の、`tables` の最後 |
| カラムを足す場所 | 実装のカラムの並び順で、直前にあるカラムのうち YAML にあるものの後ろ (無ければ `columns` の先頭) |
| インデックスを足す場所 | `indexes` の最後 (無ければ、テーブルの最後のキーとして作る) |
| キーの順 | テーブルは `planned`・`definition`・`model`・`attribute`・`primary_key`・`columns`・`indexes`、カラムは `type`・`nullable`・`default`・`references`・`attribute`・`planned`・`in_overview`・`definition`、インデックスは `columns`・`unique`・`planned` |
| 型とデフォルト値 | 節「正規化」で正規化した形。デフォルト値はいつも二重引用符で囲む (`default: "'on_loan'"`)。PostgreSQL の連番のカラムは、型を `serial`・`bigserial`・`smallserial` にし、`default` を書かない |
| 外部キーの参照先 | 参照先のカラムの完全な ID。参照先のテーブルかカラムが YAML に無ければ、書き換えない (先に参照先を足す) |
| 主キーとインデックスのカラムの組 | フロースタイルの配列 (`[book_id, category_id]`) |
| 定義の文と対応 | `--definition <ID> <文>`・`--model <テーブルの ID> <モデルの ID>`・`--attribute <テーブルかカラムの ID> <属性の ID>` で受け取る。足すテーブルとカラムのすべてに、どれかが要る ([doc-structured-domains.md](doc-structured-domains.md) の節「テーブルとカラム」の `definition` の規則) |

- 実装にある CHECK 制約・部分インデックスの条件・式を含むインデックス・複数のカラムからなる外部キーは、YAML に書けないので書かず、書けなかったことを出力する。値の持ち方と条件の意味は、`design.md` に書く。
- 書き換えない行 (コメント・空行・ほかの項目) は変えない。足す行のインデントは、そのファイルのほかの行に合わせる。消す項目の直前に空行を挟まずに書いたコメントは、項目と一緒に消える。
- フロースタイル (`id: {type: text}`) で書いたマッピングの中は書き換えない。ブロックスタイルで書いてから実行する。
- 書き換えた後の YAML に検査 h の誤りがあれば、元に戻す。
- 生成したファイルは書き換えない。書き換えた後に `bin/doc-structured generate` で生成し直す。

## 実際のスキーマのファイル

設定に `database.schema_actual: true` を書いたプロジェクトでは、実際のスキーマのファイル `docs/system/schema-actual.md` を生成してコミットします。中身はマイグレーションだけで決まり、設計 (`schema.md`) へのリンク・ID・アンカーを持ちません。

- 見出し「# 実際のスキーマ」の後に、適用したマイグレーションのパターンとデータベースの種類を書く。
- mermaid の erDiagram の ER 図に、すべてのテーブルのすべてのカラムを描く。描き方 (キー・線の端・二重引用符) は `schema.md` と同じ。複数のカラムからなる外部キーの線の文字は、カラム名をカンマで区切ったもの。
- テーブルごとの節を、テーブル名の文字コードの順に書く。節には、主キー・カラムの表「カラム | 型 | NULL | デフォルト値 | 参照先」(カラムは実際の並び順)・複数のカラムからなる外部キー・インデックス (一意と、部分インデックスの条件)・CHECK 制約を書く。
- 型とデフォルト値は、正規化する前の、データベースから読んだ形で書く。
- 生成元は `paths.migrations` のパターン。
- `bin/doc-structured generate --all` だけが生成し直す。`bin/doc-structured generate` と検査 a は、このファイルを扱わず、検査 j が最新かを確認する。`schema_actual` を書いていないのにファイルが残っていれば、検査 a が報告し、`bin/doc-structured generate` が消す。
