# レビューの起動

**このファイルが `review-triage-loop` からレビューを起動する経路の正本。** 依頼文の中身 (検証の前払い・報告しない条件・出力様式) は [review-request.md](../../review-triage/references/review-request.md) が正本 — ここでは言い直さず、経路ごとの違いだけを定める。

## なぜ経路がスキルごとに違うか

2 つのレビュースキルは、独立した文脈で走らせる手段が違う。

- `code-review` は sub-agent に包む。
- `ce-code-review` は**自身が並列 sub-agent を 6〜9 個立てる**ので、sub-agent に包むと入れ子になる。代わりに `mode:agent` を使う — このモードは JSON だけを返すので、レビューの推論過程が呼び出し元の文脈に流れ込まない。

**独立した文脈で走らせるのは、レビュアとトリアージを分けるため。** 同じ文脈で走らせると、指摘を出した側がそのまま採否を判断することになる。

## 実効モデル (定義の正本)

**モデルを指す語は 2 つだけ。** **指定** (`review_model` / `--model` に書かれた生の綴り。G0 でしか使わない) と、**実効モデル** (G0 で解決した後のモデル名。sub-agent への受け渡し・記録・報告のすべてがこれを使う)。「周回が決めたモデル」「継承」「呼び出し元」のような中間の語は持たない — 語が増えるたびに規則ごとに違う語を選んで食い違った (記録の回 5〜19)。

### G0 での解決

指定と経路から、実効モデルの**名前**を G0 で決める。以降の規則は名前だけを扱い、綴りを比べない。

| 経路 | 実効モデル (名前) |
| --- | --- |
| `code-review` | 指定があれば、それを名前に解決したもの — `opus` のような別名は対応する名前に、`inherit` は呼び出し元 (このセッションが動いているモデル) の名前に。指定が未設定 (定義の正本は [project-config.md](../../review-triage/references/project-config.md) の「「未設定」の定義」) なら既定 — 呼び出し元の 1 つ前の世代の同じ位置のモデル (下の対応表。表に無ければ推測せず人間に尋ねる) |
| `ce-code-review` | 呼び出し元の名前。**指定は効かない** — sub-agent に包まないので渡す先が無く、`ce-code-review` は主要な 3 つのペルソナに呼び出し元のモデルを継承させ、残りは mid-tier を使う。**指定が空でなければ「指定 X はこの経路では効かない」と報告する** — 比較ではなく経路で決めるので、綴りと名前の違いで誤報は出ない |

既定の対応表 (正本。表に無い組み合わせは人間に尋ねる):

| 呼び出し元 | 既定 |
| --- | --- |
| Fable 5.1 (`claude-fable-5-1`) | Opus 5 (`opus`) |

既定を呼び出し元と別のモデルにするのは、書いた側と同じモデルで読み返すより別のモデルで読ませるほうが見落としを拾いやすく、費用も抑えられるため。

### G0 より後の規則

- **sub-agent には実効モデルを `model` として必ず明示して渡す** (`code-review` の経路)。省略すると、agent 定義の `model` → 環境変数 `CLAUDE_CODE_SUBAGENT_MODEL` → 親のモデルの順で解決され、周回が知らない値で走りうる。
- **記録の `model` と報告には、実効モデルの名前** (`opus-5` のような記録の表記) を書く。空欄にしない。

### effort の既定

`review_args` が無いとき、`code-review` には effort `high` を渡す。**`ce-code-review` は effort を持たないので渡さない。**

### skill を呼んだことの確認

依頼文に skill・effort・モデルを値で明記する義務と、報告させる義務の正本は [review-request.md](../../review-triage/references/review-request.md) の「依頼文に含めるもの」の 6 と 7。報告に無いとき・指定と食い違うときの扱い (人間に報告する) もそこが定める。

## `code-review` の場合

sub-agent を立て、[review-request.md](../../review-triage/references/review-request.md) の依頼文を渡す。

- **`model` には実効モデル (上の定義) を必ず明示して渡す。** 周回が回ごとに勝手に切り替えない (SKILL.md の原則)。
- `review_args` (無ければ既定の effort。上の定義) と実効モデルは、依頼文に**値で**書いて渡し、skill を呼んだことと実際の effort・モデルを報告させる (上の定義)。値を書かずに「報告せよ」とだけ書くと、sub-agent が自分で選んだ値で走る。
- 出力は [review-request.md](../../review-triage/references/review-request.md) の「出力様式」の YAML で書き出させる。**地の文で返させない** — `review-triage` の手順 1 がファイル経由で読む形である。

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

**記録の必須キーのうち、JSON に無いものは周回の側が持つ。** `ce-code-review` はモデルや effort を指定する引数を持たないので、JSON にも出てこない。

| 記録のキー | どこから採るか |
| --- | --- |
| `model` | 実効モデル (上の定義)。**空にしない** — 記録の必須キーで、`triagecheck` が欠落をエラーにする |
| `scope` | 周回が決めた範囲 (下の「範囲」)。JSON の `scope` は差分の基点を持つ別物なので、そのまま写さない |
| `skill` | `ce-code-review` |
| `level` | 空 (このスキルは effort を持たない) |

**「無い属性を補完しない」が掛かるのは `attrs` だけ** — そこは上流が付けたものをそのまま残す欄である ([SKILL.md](../../review-triage/SKILL.md) の「このスキルが検出しないもの」)。記録の必須キーは別で、上の表のとおり周回の側が埋める。

## 範囲

**全量にするのは、記録に回が 1 件も無いときだけ。** 全量の基点は、このブランチが分岐した main ブランチとの共通祖先 (`git merge-base <main ブランチ> HEAD`)。main ブランチの名前は `origin/HEAD` が指すものを使い、それで決まらなければ人間に尋ねる。それ以外はすべて増分で、基点は記録の最後の回の `head` から読む。規則の理由は [review-request.md](../../review-triage/references/review-request.md) の「範囲の規則」にある — 全量を繰り返すと指摘が際限なく出続ける。

**最終確認の全量は周回に含めない。** [review-request.md](../../review-triage/references/review-request.md) の範囲の規則が求める 2 つの `full` のうち、周回が担うのは最初の 1 回だけである。最終確認を周回に入れると、収束のたびに全量が 1 回増え、上限の意味 (収束しない周回を止める関門) が変わってしまう。**代わりに、収束の報告で最終確認がまだであることを伝える** ([loop-flow.md](loop-flow.md) の決定表 S3)。

**「周回の 1 周目」と「記録の回 1」を同一視しない。** 既に回のある記録に対して loop を起動すれば、その周回の 1 周目は記録の 2 回目以降にあたる。周回の内側だけで数えると、2 度目以降の全量レビューを走らせることになり、この行が引く規則に反する。

## 起動の後に確かめること

**レビューの前後で HEAD と作業ツリーが変わっていないこと。** 変わっていれば、そのレビューは報告のみで走っていない。`review-triage` に渡さず、周回を止めて報告する — 適用済みの修正を前提に採否を判断すると、判断の前提が実態と食い違う。
