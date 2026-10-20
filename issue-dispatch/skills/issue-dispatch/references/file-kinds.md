# ファイルの種類

**このファイルが、ファイルの種類と、競合の可能性の判定の規則の正本。** パスから種類と属性を決めるモジュール `issue-dispatch/scripts/issue_dispatch/filekinds.py` と、同梱のデフォルトの表 `issue-dispatch/scripts/issue_dispatch/file-kinds.json` はこれに従う。リポジトリの設定の `files` の様式と、読み込むときにそろえる表記の正本は [project-config.md](project-config.md) で、ここでは言い直さない。ほかの文書は種類と属性の名前を参照するだけで、問いや判定の規則を言い直さない。

**種類は宣言に書かず、スクリプトがパスから決める。** 作業のセッションは宣言にパスと節の名前だけを書く ([issue-format.md](issue-format.md))。

## 6 段の問いと種類

種類は、パスについて次の問いに上から順に答え、最初に当てはまったものにする。1 つのパスが種類の違う複数の規則に一致すれば、この表で先の種類にする (下の「照合の順」)。

| 段 | 問い | 当てはまれば | 競合の可能性の判定 | 競合の可能性があるときに示す扱い |
| --- | --- | --- | --- | --- |
| 1 | 内容を知らない (パスに一致するパターンが、リポジトリの設定にもデフォルトの表にも無い) | `unknown-content` | 同じパスなら、競合しうるかどうかを利用者に尋ねる | — |
| 2 | ツールが生成する | `generated` | 判定しない | — |
| 3 | 構造を知らない | `unknown-structure` | 同じパスなら競合しうる | 待つ・共通の変更を先に小さな PR にする・競合しうるまま進める、の 3 つ |
| 4 | 分割できない | `indivisible` | 節で判定する (下) | 同上 |
| 5 | 分割すると意味が変わる可能性がある | `unstable` | 節で判定する | 同上。共通の変更を先にする小さな PR で、分けるリファクタリングも行える (意味が変わりうる点を添える) |
| 6 | (上のどれでもない) | `divisible` | 節で判定する | 同上。共通の変更を先にする小さな PR で、分けるリファクタリングも行える |

`unknown-content` は、どの規則にも一致しないパスの種類なので、規則の `kind` には書けない。規則に書ける種類は段 2〜6 の 5 つ。

節 (unit) は種類ではなく、構造を知っている種類 (段 4〜6) の判定の細かさとして扱う。

**レビューでの修正による競合の可能性は判定しない。** 競合しうる相手とのマージの衝突は利用者が解消する (レビューで変わる範囲は宣言の時点で決まらないため)。

## 節で判定する

構造を知っている種類 (`indivisible`・`unstable`・`divisible`) は、両方の宣言がそのパスに `units` を書いていれば、節が同じか、一方の配列が他方の配列の先頭部分 (`["dependencies"]` と `["dependencies", "react"]` など) のときだけ競合しうる。`["dependencies", "react"]` と `["dependencies", "zod"]` は競合しない。どちらかが `units` を省けば、同じパスで競合しうる。

節は階層ごとの名前の配列で表す (`["dependencies", "zod"]`)。区切りの文字を使わないのは、名前に `.` や `/` が含まれることがあるため (`package.json` の `exports` のキー `./utils`、`go.mod` のモジュール名 `github.com/foo/bar`、見出し「v1.2 の変更」)。名前はファイルにある文字のまま比べ、正規化しない (`"./utils"` と `"utils"` は JSON では別のキー)。節の名前は作業のセッションがファイルを読んで書き、スクリプトは名前を比べるだけで、ファイルを構文解析しない。

## 節の表記 (`unit_notation`)

規則の `unit_notation` は、そのファイルの節をどの構造の名前で書くかを示す。宣言の `units` と混同しないよう名前を分けている。

| 構造 | 表記 | 例 (節の配列) |
| --- | --- | --- |
| JSON のキー | `json-key` | `["dependencies", "zod"]`・`["exports", "./utils"]` |
| YAML のキー | `yaml-key` | `["jobs", "test"]` |
| TOML のテーブル | `toml-table` | `["tool", "ruff"]` |
| Markdown の見出しと frontmatter | `markdown-heading` | `["手順", "1. 入力を読む"]`・`["frontmatter", "title"]` |
| Makefile のターゲット | `make-target` | `["test"]` |
| `go.mod` のディレクティブ | `go-mod-directive` | `["require", "github.com/foo/bar"]` |
| Dockerfile のステージ | `dockerfile-stage` | `["builder"]` |
| Terraform のブロック | `terraform-block` | `["resource", "aws_s3_bucket", "logs"]` |

値は、表記の名前の文字列 (`"markdown-heading"`) か、表記とキーの深さを持つオブジェクト `{"notation": "json-key", "keys": ["dependencies", "devDependencies"]}` のどちらか。`keys` は、そのキーの下を 1 つ下の階層ごとの節として扱うキーの配列で、`package.json` では `dependencies` の下を依存ごとの節にする。`keys` に無いキーは、そのキー全体が 1 つの節になる。`keys` は `json-key`・`yaml-key`・`toml-table` でだけ意味を持つ。

`unit_notation` の無い規則のファイル (`.go`・`.ts` など) は、節の表記を決めていないので、宣言に `units` を書かない。

## パターンの書き方

- `*` は 1 つのディレクトリの名前の中だけで一致し (`/` を越えない)、`**` は 0 個以上のディレクトリに一致する。`?` は `/` 以外の 1 文字。
- パターンは、リポジトリのルートからのパス全体と照合する。`*.pb.go` はルートのファイルだけに一致し、どの階層にも一致させるには `**/*.pb.go` と書く。
- 末尾が `/` のパターン (`dist/`) は、そのディレクトリの下のすべて (`dist/**`) と同じに扱う。

Python 3.13 の `PurePath.full_match` と同じ規則で、`.gitignore` や `.gitattributes` の規則 (`/` を含まないパターンがどの階層にも一致する) とは違う。Python 3.11 には `full_match` が無く、`fnmatch` は `*` が `/` を越えて一致するので、`filekinds` はパターンを正規表現に変換して照合する。

| パターン | 一致する | 一致しない |
| --- | --- | --- |
| `*.pb.go` | `api.pb.go` | `gen/api.pb.go` |
| `**/*.pb.go` | `api.pb.go`・`gen/api.pb.go` | |
| `src/*.ts` | `src/app.ts` | `src/lib/a.ts` |
| `dist/` | `dist/app.js`・`dist/assets/a.js` | `dist` (ディレクトリそのものの名前)・`distribution/a.js` |

## 照合の順

照合の前に、パスをリポジトリのルート基準にそろえる (`./a`・`a/`・`a//b` を `a`・`a/b` と同じに)。絶対パス (`/` で始まる) と `..` を含むパス (ルートの外を指しうる) と、ルートそのものを指すパスは、照合せずに差し戻す (`files classify` はそのパスに `error` を返す)。

1. リポジトリの設定の `files` の規則を先に、デフォルトの表を後に照合する。設定に一致する規則があれば、デフォルトの表は見ない。
2. 同じ側 (設定、またはデフォルトの表) で種類の違う複数の規則に一致すれば、6 段の表で先の種類の規則を選ぶ。規則の並び順では決めない。
3. どちらにも一致しなければ `unknown-content`。

設定の規則がデフォルトの表より先なのは、同じ拡張子でも扱いがリポジトリで違うため (同じ `.js` でも、自前で書いたものと、`.ts` やビルドから生成したものがある)。種類は拡張子ではなくパスのパターンで決める。

## 分けたときの参照のされ方 (`split_reference`)

`unstable` と `divisible` の規則には、ほかのファイルがそのファイルをどう参照するか (`split_reference`) を書く。共通の変更を先にする小さな PR で、ファイルを分けるリファクタリングを行うときに、参照元を宣言に含めるかを決めるため。

| 値 | 意味 | 例 |
| --- | --- | --- |
| `directory` | 参照元のファイルがディレクトリを指定する。同じディレクトリの中で分けるかぎり参照元は変わらない | Go の `import` のパッケージ、Terraform のモジュール |
| `file` | 参照元のファイルがファイルを指定する。分けると参照元も変わるので、リファクタリングの宣言には変わる参照元も含める | TypeScript の `import './app'`・Makefile の `include`・CSS の `@import` |

## マージできないファイル (`mergeable`)

画像など、差分でマージできないファイルは、規則に `"mergeable": false` を書く (省略は真)。そのファイルで「競合しうるまま進める」を選ぼうとしたら、後で衝突を直せないことを添えて尋ねる。

## 共有の状態を持つファイル

`terraform.tfstate` のように、ファイルが共有の状態 (実際のインフラ) を記録しているものは、種類 (`generated`) とは別に資源 (ラベル `resource:…`) として扱う。種類はファイルの変更の競合の可能性を判定するもので、共有の状態の取り合いは資源で判定する。

## デフォルトの表

表そのものの正本は `file-kinds.json` で、ここでは行を言い直さない。行は、パターンと種類と、この文書の各節の属性 (`unit_notation`・`split_reference`・`mergeable`) を持ち、`filekinds` は設定の規則と同じ規則で照合する。各行を選んだ理由は次のとおり。

- **`generated`** — ツールが書き、人が編集しないもの: Protocol Buffers の出力 (`**/*.pb.go`)、生成の印を名前に持つ Go のファイル (`**/*_generated.go`)、パッケージマネージャのロックファイル (`**/package-lock.json`・`**/yarn.lock`・`**/pnpm-lock.yaml`・`**/go.sum`・`**/Cargo.lock`)、縮小した JavaScript と CSS (`**/*.min.js`・`**/*.min.css`)、Terraform の状態 (`**/terraform.tfstate*`。共有の状態は上のとおり資源でも扱う)。
- **`unknown-structure`** — 中身を読んで節を決められないもの: Excel のブック (`**/*.xlsx`)。
- **`indivisible` で `mergeable` が偽** — 画像とフォントとバイナリの文書 (`**/*.png`・`**/*.jpg`・`**/*.jpeg`・`**/*.gif`・`**/*.svg`・`**/*.ico`・`**/*.pdf`・`**/*.woff`・`**/*.woff2`)。分けられず、差分でマージできない。SVG はテキストだが、描画ツールが全体を書き直すので画像と同じに扱う。
- **`unstable`** — 分けると適用の順や意味が変わりうるもの: マイグレーション (`**/migrations/**`) と SQL (`**/*.sql`) は実行の順に意味があり、Protocol Buffers の定義 (`**/*.proto`) はフィールド番号の割り当てに意味がある。参照のされ方は `file`。
- **`divisible` で節の表記があるもの** — `**/package.json` (`json-key`。`dependencies` と `devDependencies` の下を依存ごとの節にする)、`**/go.mod` (`go-mod-directive`。参照のされ方は `directory`)、`**/*.md` (`markdown-heading`)、`**/Makefile` (`make-target`)、`**/*.toml` (`toml-table`)、`**/*.yaml`・`**/*.yml` (`yaml-key`)、`**/Dockerfile` (`dockerfile-stage`)、`**/*.tf` (`terraform-block`。参照のされ方は `directory`)。
- **`divisible` で節の表記の無いもの** — 自前で書くソースコード: `**/*.go` (参照のされ方は `directory`)、`**/*.ts`・`**/*.tsx`・`**/*.js`・`**/*.py`・`**/*.rb`・`**/*.css` (参照のされ方は `file`)。節の表記を決めていないので、宣言に `units` は書けない。

リポジトリで扱いが違うもの (生成した `.js`・`.gitattributes` で `linguist-generated` にしたディレクトリなど) は、リポジトリの設定の `files` に書く。候補はスキル `repo-preflight` が示す。
