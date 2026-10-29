# レビューの起動

**このファイルが `review-triage-loop` からレビューを起動する経路の SSOT。** 依頼文の中身 (報告前の検証・報告しない条件・出力様式) は [review-request.md](../../review-triage/references/review-request.md) が SSOT — ここでは言い直さず、経路ごとの違いだけを定める。レビューを別のプロセスに任せるループ (`review-loop`) が結果を取り込むときの共通の規則も、末尾の節「別のプロセスでレビューした結果の取り込み」が SSOT。

## なぜ経路がスキルごとに違うか

2 つのレビュースキルは、独立した文脈で実行する手段が違う。

- `code-review` は sub-agent に包む。
- `ce-code-review` は**自身が並列 sub-agent を 6〜9 個立てる**ので、sub-agent に包むと入れ子になる。代わりに `mode:agent` を使う — このモードは JSON だけを返すので、レビューの推論過程が呼び出し元の文脈に流れ込まない。

**独立した文脈で実行するのは、レビュアとトリアージを分けるため。** 同じ文脈で実行すると、指摘を出したセッションがそのまま採否を判断することになる。

## 実効モデル (定義の SSOT)

**モデルを指す語は 2 つだけ。** **指定** (`review_model` / `--model` に書かれた生の表記。G0 でしか使わない) と、**実効モデル** (G0 で解決した後のモデル名。sub-agent への受け渡し・記録・報告のすべてがこれを使う)。「ループが決めたモデル」「継承」「呼び出し元」のような中間の語は持たない — 語が増えるたびに規則ごとに違う語を選んで不統一になった (記録の 5〜19 回目)。

### G0 での解決

指定と経路から、実効モデルの**名前**を G0 で決める。以降の規則は名前だけを扱い、表記を比べない。

| 経路 | 実効モデル (名前) |
| --- | --- |
| `code-review` | 指定があれば、それを名前に解決したもの — `opus` のような別名は対応する名前に、`inherit` は呼び出し元 (このセッションが動いているモデル) の名前に。指定が未設定 (定義の SSOT は [project-config.md](../../review-triage/references/project-config.md) の「「未設定」の定義」) なら既定 — 呼び出し元の 1 つ前の世代の同じ位置のモデル (下の対応表。表に無ければ推測せず人間に質問する) |
| `ce-code-review` | 呼び出し元の名前。**指定は適用されない** — sub-agent に包まないので渡す先が無く、`ce-code-review` は主要な 3 つのペルソナに呼び出し元のモデルを継承させ、残りは mid-tier を使う。**指定が空でなければ「指定 X はこの経路では適用されない」と報告する** — 比較ではなく経路で決めるので、表記と名前の違いで誤報は出ない |

既定の対応表 (SSOT。表に無い組み合わせは人間に質問する):

| 呼び出し元 | 既定 |
| --- | --- |
| Fable 5.1 (`claude-fable-5-1`) | Opus 5 (`opus`) |

既定を呼び出し元と別のモデルにするのは、書いたセッションと同じモデルで読み返すより別のモデルで読ませるほうが見落としに気づきやすく、費用も抑えられるため。

### G0 より後の規則

- **sub-agent には実効モデルを `model` として必ず明示して渡す** (`code-review` の経路)。省略すると、agent 定義の `model` → 環境変数 `CLAUDE_CODE_SUBAGENT_MODEL` → 親のモデルの順で解決され、ループが知らない値で実行されうる。
- **記録の `model` と報告には、実効モデルの名前** (`opus-5` のような記録の表記) を書く。空欄にしない。

### effort の既定

`review_args` が無いとき、`code-review` には effort `high` を渡す。**`ce-code-review` は effort を持たないので渡さない。**

### skill を呼んだことの確認

依頼文に skill・effort・モデルを値で明記する義務と、報告させる義務の SSOT は [review-request.md](../../review-triage/references/review-request.md) の「呼ぶ skill・effort・モデル — 値で明記し、報告させる」。報告に無いとき・指定と一致しないときの扱い (人間に報告する) もそこが定める。

## 記録のキーの出所 (定義の SSOT)

**記録の `model` / `skill` / `level` / `scope` を何から採るかは、経路ごとにこの表が定める。ただし、レビューを別のプロセスに任せる経路 (`review-loop`) では、この表の値の一部を替える。** キーの意味の SSOT は [record-schema.md](../../review-triage/references/record-schema.md) の `runs[]` の表で、ここはループがその値をどこから採るかを定める。どれをどう替えるかは、末尾の節「別のプロセスでレビューした結果の取り込み」の「`review-triage` に渡すもの」が定める。そこで定めずに、それぞれのスキルの文書に委ねるもの (`model` の採り方) もある。

| 記録のキー | `code-review` | `ce-code-review` |
| --- | --- | --- |
| `model` | 実効モデル (上の定義)。**空にしない** — 記録の必須キーで、`triagecheck` が欠落をエラーにする | 同左 |
| `skill` | sub-agent の報告で「実際に呼んだ」と確認した `code-review` | `ce-code-review` |
| `level` | sub-agent の報告で確認した effort (`review_args`、無ければ既定。上の定義) | 空 (このスキルは effort を持たない) |
| `scope` | ループが決めた範囲 (下の「範囲」) | 同左。JSON の `scope` は差分の基点を持つ別物なので、そのまま写さない |

**「無い属性を補完しない」が掛かるのは `attrs` だけ** — そこは上流が付けたものをそのまま残す欄である ([SKILL.md](../../review-triage/SKILL.md) の「このスキルが検出しないもの」)。記録の必須キーは別で、上の表のとおりループが埋める。

## `code-review` の場合

sub-agent を立て、[review-request-template.md](../../review-triage/references/review-request-template.md) を埋めた依頼文を渡す (運用の SSOT は [review-request.md](../../review-triage/references/review-request.md))。雛形を埋める値は、ループはスキルを呼ばないが、次のとおり [review-request スキル](../../review-request/SKILL.md) と同じ規則で決める — 識別子と出力先 (`{{output_path}}`) は手順 3・4 (別の名前を付けると `review-triage` の手順 1 が読む対象と一致しない)。識別子の成分の回・`head`・`scope_note` は手順 2 (回は記録の `runs` の数 + 1 — ループが上限のために起動時に 0 から数える回数とは別物)。モデルはこのファイルの「実効モデル」、`base` と `scope` は「範囲」が SSOT で、そのスキルの手順 1・2 のモデルと範囲の規則だけは使わない。

- **`model` には実効モデル (上の定義) を必ず明示して渡す。** ループが回ごとに勝手に切り替えない (SKILL.md の原則)。
- `review_args` (無ければ既定の effort。上の定義) と実効モデルは、依頼文に**値で**書いて渡し、skill を呼んだことと実際の effort・モデルを報告させる (上の定義。値で書く理由もそこが引く SSOT にある)。
- 出力は雛形の「出力様式」の YAML で書き出させる。**地の文で返させない** — `review-triage` の手順 1 がファイル経由で読む形である。

## `ce-code-review` の場合

sub-agent に包まず、`mode:agent` を付けて呼ぶ。

- **`mode:agent` は必須。** これが無いと修正を適用してしまい、`review-triage` が求める「報告のみ」([SKILL.md](../../review-triage/SKILL.md) の前提知識) が破れる。
- 出力は JSON 1 個と、`review.json` のファイル。**分量が多いときはファイルのパスから読む。**
- `review_args` があれば渡す。ただし `ce-code-review` はモデルや effort を指定する引数を持たない — 渡せるのは範囲などの指定に限る。
- **JSON を [review-request.md](../../review-triage/references/review-request.md) の YAML 様式に写してから `review-triage` に渡す。** キーの対応は下記。

### JSON から記録の様式への対応

| `ce-code-review` の JSON | 記録の様式 |
| --- | --- |
| `findings[].file` / `line` | `file` / `line` |
| `findings[].title` または要旨 | `summary` |
| `findings[].evidence` / `first_evidence` | `evidence` |
| `findings[].severity` / `confidence` | `attrs.severity` / `attrs.confidence` |
| `scope.head_sha` | `head` |

**記録の必須キーのうち、JSON に無いものはループが持つ** — 何から採るかは上の「記録のキーの出所」の表のとおり。`ce-code-review` はモデルや effort を指定する引数を持たないので、JSON にも出てこない。

## 範囲

**全量にするのは、記録に回が 1 件も無いときだけ。** 全量の基点は、起点のブランチと HEAD の merge-base (共通祖先のコミット) で、求め方の SSOT は [review-request の SKILL.md](../../review-request/SKILL.md) の手順 2。**起点のブランチは、引数 `--base` があればそのブランチ、無ければ `origin/HEAD` が指すブランチで、使うのはこの全量の回だけである。** それ以外はすべて増分で、基点は記録の最後の回の `head` から読む。規則の理由は [review-request.md](../../review-triage/references/review-request.md) の「範囲の規則」にある — 全量を繰り返すと指摘が際限なく出続ける。

**これらの基点 (全量と増分) を依頼文に埋めてレビュアに渡すのは、`code-review` の経路だけである。** `ce-code-review` の経路は範囲の基点をレビュアに渡していないので ([#79](https://github.com/akm/claude-plugins/issues/79))、全量の回でも増分の回でも基点はレビュア (`ce-code-review`) が自分で決め、起点のブランチも使わない。記録の `scope` には、`ce-code-review` の経路でもループが決めた範囲を書く (実際の範囲と一致しないことがあるのも #79 の件)。

**この経路 (`review-triage-loop`) は、収束後の全量レビューをループに含めない。** [review-request.md](../../review-triage/references/review-request.md) の範囲の規則が求める 2 種類の `full` (最初の 1 回と、収束後の全量レビュー) のうち、このループが担うのは最初の 1 回だけである。ループの中で行う手段を持つのは `review-loop` で、引数 `--full-review` を付けると収束後の全量の回をループの中で行い、その回は上限に数えない (数えなくてもループが停止する理由の SSOT は [review-request.md](../../review-triage/references/review-request.md) の「収束後の全量レビューと、その要否」)。

**「ループの 1 回目」と「記録の 1 回目」を同一視しない。** 既に回のある記録に対して loop を起動すれば、そのループの 1 回目は記録の 2 回目以降にあたる。ループの中だけで数えると、2 度目以降の全量レビューを実行することになり、この行が引く規則に反する。

## 起動の後に確認すること

**レビューの前後で HEAD と作業ツリーが変わっていないこと。** 変わっていれば、そのレビューは報告のみで実行されていない。`review-triage` に渡さず、ループを停止して報告する — 適用済みの修正を前提に採否を判断すると、判断の前提が実態と一致しなくなる。

## 別のプロセスでレビューした結果の取り込み

**この節が、レビューを別のプロセスに任せるループ (`review-loop`) が、`review-request` で依頼文を作り、レビューの結果のファイルを受け取って取り込むときの、共通の規則の SSOT。** レビュアの実行を確認する材料 (`review-loop` では完了のフラグファイル) と、規則に反したときに停止するノード (以下「その経路のレビュー不成立」。`review-loop` では RA1) は、経路ごとに違うので、それぞれのスキルの文書が定める。この経路 (`review-triage-loop`) は `review-request` を呼ばず、結果を sub-agent から受け取るので、この節を使わない。

### 呼ぶスキル

**ループが呼ぶ 3 つのスキル (依頼文を書く `review-request`・L2 の `review-triage`・F1 の `review-triage-fix`) は、回ごとに Skill ツールで呼ぶ。** L2 では、指摘が 0 件の回も `review-triage` を呼ぶ。前の回で読んだ手順を、ループのスキルが自分で実行しない。依頼文の識別子の組み立てと雛形の埋め方、記録への回の追記・residual を自己採択にするかの判断・生成サマリの再生成と検査、修正と記録の更新は、それぞれのスキルが行う。ループのスキルが代わりに行うと、そのスキルの手順で確認しないまま、結果がファイルと記録に入る (`review-loop` の通し確認で、指摘が 0 件の回に review-loop のセッションが `review-triage` を、2 回目以降の依頼文で `review-request` を代わりに行った)。

### 結果のファイルの照合

`review-triage` に渡す前に、結果のファイル (`review-request` が依頼文に埋めた出力先) について、次をすべて確認する。**1 つでも通らなければ、その経路のレビュー不成立にする。**

- YAML として読め、`findings` キーがある。
- `run_id` が依頼文の識別子と一致する。
- `scope` と `base` が依頼文の値と一致する。

**`scope` と `base` を比べるのは、記録の `scope` を結果の値から採るため** (下の「`review-triage` に渡すもの」)。レビュアが全量の回を `incremental` と書いたまま記録に入ると、記録に全量の回が無いことになる。すると、収束後の全量レビューの要否 (SSOT は [review-request.md](../../review-triage/references/review-request.md) の「収束後の全量レビューと、その要否」) が毎回「要る」になり、上限に数えない全量の回が繰り返される。

### `review-triage` に渡すもの

`review-triage` を呼ぶときは、結果のファイルのパスと、次の値を渡す。

- **記録のキー (`model` / `skill` / `level` / `scope`) の値の出所は、上の「記録のキーの出所」の表で、そのレビュースキル (`code-review` か `ce-code-review`) の欄に書いたとおり。ただし、表の「sub-agent の報告」は、その経路がレビュアの実行を確認した材料と読み替える。`scope` は、結果のファイルの `scope` の値 (依頼文に `review-request` が埋めた値) を使う。** 表の「ループが決めた範囲」を同じファイルの「範囲」の節で読むと、全量は記録に回が無いときだけなので、収束後の全量の回が `incremental` として記録されるため。別のプロセスに任せる経路のために出所の表を増やさない (表を複数の文書に持つと、同じ場所への採択が続いた実測がある)。`model` の採り方と、記録の `notes` に書く 1 行は、経路ごとにそれぞれのスキルの文書が定める。
- **`run_id` は、結果のファイルの値をそのまま写すこと** (規則の SSOT は [review-request.md](../../review-triage/references/review-request.md) の「出力様式」の節)。

**`review-triage` が結果の様式を差し戻したら、その経路のレビュー不成立にする。** `review-triage` が返ったら、**記録の末尾の回の `run_id` が識別子と一致することを確認し、一致しなければ、その経路のレビュー不成立にする** (報告に「`review-triage` が `run_id` を写さなかった」と書く)。一致しないまま進むと、同じ結果を 2 度取り込むことがある。
