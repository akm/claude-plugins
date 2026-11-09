# diffhtml

HTML のファイルに書いたマークのコメントを、差分を表示する HTML に置き換える。`review-triage-fix` が説明の HTML (選択待ちの問題を判断するためのものと、直した問題を確認するためのもの) を作るときに使う (作る場面と構成の SSOT は [explainer-html.md](../../skills/review-triage-fix/references/explainer-html.md))。

**なぜ要るか。** 差分の文字列をモデルが HTML にコピーすると、コピーの誤りが起こりうる。判断のための HTML の差分が記録のパッチと違うと、人間が HTML で見た差分と、そのパッチを当てたコミットが一致しなくなる。このツールは差分を記録 YAML と git から取るので、モデルは差分の位置を指すマークだけを書けばよい。

## マーク

差分を表示する位置に、HTML のコメントで 1 つずつ書く。

| マーク | 置き換える差分 |
| --- | --- |
| `<!-- review-triage-diff patch run=<回番号> problem=<problem_id> option=<ラベル> -->` | 記録 YAML の `runs` の <回番号> 番目 (1 から数える) の回の、`problem_id` が一致する問題の、`option_patches` のうち `option` が一致する要素の `patch` |
| `<!-- review-triage-diff commit <SHA> -->` | そのコミットの差分。`git show --format= --no-ext-diff --no-color --no-textconv --src-prefix=a/ --dst-prefix=b/ <SHA>` の出力 (利用者の git の設定で形が変わらないオプションを付ける) |

`<SHA>` は 4〜40 文字の英小文字の 16 進数で書く。次の場合はエラーにする。

- `review-triage-diff` で始まるコメントが、上の形に合わない (`review-triage-diff` の直後に空白が無いものを含む)
- `review-triage-diff` で始まるコメントに、閉じ `-->` が無い
- 回・問題・案が記録 YAML に無いか、案の要素に `patch` が無い (`no_change` か `covered_by` の要素)
- `git show` が失敗する (コミットが無いなど)

## 何に置き換えるか

- 差分は `<pre>` の中に 1 行ずつ書き出し、`&`・`<`・`>` をエスケープする。
- 行の種類で色を分ける。追加 (`+`)・削除 (`-`)・hunk の見出し (`@@`)・ファイルの見出し (`diff --git` から hunk の見出しの前まで)。
- 続けて並ぶ削除の行と追加の行を、先頭から順に 1 つずつ組にし、組になった 2 行から先頭と末尾の共通部分を除いた部分を強調する (`<mark>`)。日本語の長い 1 行の中の数文字だけが変わる差分でも、変わった箇所が分かるようにするため。共通部分が無い組は強調しない。
- 色分けの `<style id="rt-diff-style">` を、`</head>` の前に入れる。既にあれば入れない。

## 使い方

```sh
go run -C <プラグインの展開先>/tools/diffhtml . -html <HTML の絶対パス> -record <記録 YAML の絶対パス> -root <リポジトリのルートの絶対パス>
```

- すべてのマークを置き換えられたときだけ、HTML を上書きする。エラーのときは HTML を変えず、すべての理由を標準エラー出力に書いて、終了コード 1 で終了する。
- マークが 1 つも無くても成功する (`done-external` の問題だけを載せた確認のための HTML など)。
- HTML に `</head>` が無ければエラーにする。

## 前提

**Go と git が要る。** [triagecheck](../triagecheck/README.md) と同じく、バイナリは配らず `go run` で都度実行する (理由はそちらの「前提」)。

## テスト

```sh
go test ./...
```
