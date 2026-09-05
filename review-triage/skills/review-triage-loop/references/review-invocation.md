# レビューの起動

**このファイルが `review-triage-loop` からレビューを起動する経路の正本。** 依頼文の中身 (検証の前払い・報告しない条件・出力様式) は [review-request.md](../../review-triage/references/review-request.md) が正本 — ここでは言い直さず、経路ごとの違いだけを定める。

## なぜ経路がスキルごとに違うか

2 つのレビュースキルは、独立した文脈で走らせる手段が違う。

- `code-review` は sub-agent に包む。
- `ce-code-review` は**自身が並列 sub-agent を 6〜9 個立てる**ので、sub-agent に包むと入れ子になる。代わりに `mode:agent` を使う — このモードは JSON だけを返すので、レビューの推論過程が呼び出し元の文脈に流れ込まない。

**独立した文脈で走らせるのは、レビュアとトリアージを分けるため。** 同じ文脈で走らせると、指摘を出した側がそのまま採否を判断することになる。

## `code-review` の場合

sub-agent を立て、[review-request.md](../../review-triage/references/review-request.md) の依頼文を渡す。

- **モデルは指定しない** — 周回の途中でモデルを変えない (SKILL.md の前提知識)。sub-agent は呼び出し元のモデルを継承する。
- `review_args` (effort など) は依頼文に含めて渡す。
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

**無い属性を補完しない** — 記録の `attrs` は上流が付けたものをそのまま残す欄である ([SKILL.md](../../review-triage/SKILL.md) の「このスキルが検出しないもの」)。

## 範囲

**1 周目は全量、2 周目以降は増分。** 増分の基点は前の回の `head` で、記録 YAML から読む。規則の理由は [review-request.md](../../review-triage/references/review-request.md) の「範囲の規則」にある — 全量を繰り返すと指摘が際限なく出続ける。

## 起動の後に確かめること

**レビューの前後で HEAD と作業ツリーが変わっていないこと。** 変わっていれば、そのレビューは報告のみで走っていない。`review-triage` に渡さず、周回を止めて報告する — 適用済みの修正を前提に採否を判断すると、判断の前提が実態と食い違う。
