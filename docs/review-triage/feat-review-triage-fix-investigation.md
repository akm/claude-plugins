<!-- 生成物。手で編集しない。正本は feat-review-triage-fix-investigation.yaml — `triagecheck -write-summary` で再生成する。 -->

# feat-review-triage-fix-investigation のトリアージ記録

正本は [feat-review-triage-fix-investigation.yaml](feat-review-triage-fix-investigation.yaml)。読み方と収束の目安は [README](README.md)。

## 推移

| 回 | 日付 | スキル | model | scope | 全件 | 採択 | 保留 | 却下 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2026-09-03 | `code-review` | `opus-5` | full | 3 | 2 | 0 | 1 |

## 回 1: 2026-09-03 `code-review`

- HEAD `64fa3b2` / model `opus-5` / scope full

| # | 指摘 | 分類 / 被害者 | 帰結 (条件 / 何が / 気づけるか) | 検証 | ゲート | 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `review-triage/skills/review-triage-fix/references/investigation.md:5` 「検証 (型 A〜F) はコミット前にかかる」と全称で述べているが、正本の verification.md は型を「書いている最中 (A・C・F)」と「コミット前 (B・D・E)」に 分けており矛盾する。同ファイル 63 行目は型 A を調査の段階で当てていて、 内側でも矛盾している | skill / operator | 利用者 (とスキルを実行するエージェント) が investigation.md を読んで、調査と検証のフェーズの違いを理解しようとするとき / 「型 A〜F はコミット前」を信じて、書いている最中に当てるべき A・C・F を コミット前まで持ち越す (実行で確かめられる主張を記憶で書いて後から直す)。 または 5 行目と 63 行目のどちらが正しいか分からず、正本を読みに行く / 気づかない — 文の矛盾を捕まえる機械検査は無く、リンク検査は文面を見ない | A: verified | — | **採択** — A2。段 A: investigation.md:5 と verification.md:11 を逐語で読み比べ、 指摘どおり verification.md が A・C・F を「書いている最中」に置いているのを確認した。 investigation.md:63 が型 A を scope の記述時に当てているのも確認した。 全 4 ゲートを評価して発火 0 件 — hypothetical: 読めば再現する。 developer-domain: 対象はスキル文書で利用者に届く。disproportionate-cost: 修正は 1 文の書き換え。already-visible: 文の矛盾を検出する関門は無い。 免除条項は検出能力の主張ではないので対象外 |
| 2 | `review-triage/tools/triagecheck/record.go:535` `investigation:` とキーだけ書いて値を省いた記録 (YAML の null) が検査を 素通りし、サマリにも出ない。`investigation: {}` は scope 欠落として報告 されるので、値の書き方だけで挙動が割れる | plugin-code / operator | 書き手が手順 4 に従って investigation キーを立て、scope を書く前に中断した、または箇条書きのインデントを誤って値が null になったとき / 検査が緑のまま通り、サマリに調査の行が出ない。書き手は調査済みのつもりだが 記録上は「未調査」と同一になり、次の回で調査漏れか新規かを判別する材料が消える / 気づかない — 検査は緑、サマリは無表示、キーは YAML に残っているので目視でも見過ごす | A: verified | — | **採択** — A2。段 A: レビュアと同じプローブ (一時テストで `investigation:` / `investigation: null` / `investigation: {}` の 3 形を validRecordYAML に 入れて検査とサマリ生成を通す) を自分で実行し、null の 2 形は問題 0 件・ 調査の行なし、{} は scope 欠落を報告することを確認した。実施後に一時 ファイルを消し、作業ツリーが空・HEAD が 64fa3b2 であることを確認した。 record-schema.md は「無いことは未調査」と定めるが、キーが書かれて値が null の形は定めておらず、検査もそこを区別しない。 全 4 ゲートを評価して発火 0 件 — hypothetical: テストで再現できる (プローブがそのままテストになる)。developer-domain: 検査は利用者の記録に かかる。disproportionate-cost: null の検出は数行で、対象の検査ブロックより 小さい。already-visible: null の形を踏むテストは無い (TestReviewTriageRecordSchemaViolations は {} の形だけ)。 免除条項は対象外 |
| 3 | `review-triage/skills/review-triage-fix/SKILL.md:33` 手順 4 の `plans[].investigation` の参照だけがアンカー無しのファイル参照で、 同じ SKILL.md の手順 6・手順 7 の正本参照が節アンカーを持つのと食い違う。 investigation.md:63 も同じくアンカー無し | skill / operator | record-schema.md の「調査」節の見出しが改名されたとき、または読み手がリンクから様式の表へ直接飛ぼうとしたとき / リンクはファイル先頭に届き、読み手は地の文の「`plans[].investigation` の表」を 頼りに表を探す。地の文はキー名で指しているので見出しの改名では古くならず、 壊れるものは無い — 増えるのは探す手間だけ / 気づかない — 地の文はアンカー検査の対象外だが、古くなる条件 (キー名の改名) では他の全箇所も同時に直す | 対象外 | — | **却下** — R2 (空虚)。指摘は「様式の正本への参照に節アンカーを付けて、同じファイルの 手順 6・7 の形に揃える」と読んだ。逐語引用は正しいが、帰結の「何が」を 壊れる形で書けない — 参照は `plans[].investigation` というキー名で表を 指しており、見出しの改名では古くならない。また同じ SKILL.md の 10・28・46 行目 (スキーマ表・状態の表への参照) も同じアンカー無しの形で、投稿の 「この参照だけが列に入らない」は成り立たない (アンカー付きは手順 6・7 の 2 箇所で、ファイル内で両方の形が混在している)。依頼文の「整理・統一の好み (放置して壊れるものが無いもの)」に当たる。 なお evidence の「6 件がヒット」は自分の実行では 7 行 (両スキルの SKILL.md と committing.md) — 結論には影響しない |

### 修正計画

| 問題 | 原因 | 含む指摘 | 修正方法 | 順 | 状態 | 証拠 (SHA / URL) |
| --- | --- | --- | --- | --- | --- | --- |
| P1 | 構造を持つ任意キー (investigation) の有無をポインタの nil で見たため、 「キーを書いて値を省いた (YAML の null)」が「キーが無い」と同一になった。 未知キーの walker も値が mapping でなければ何も見ずに抜ける | #2 | recordUnknownKeyProblems の walker で、mapping を期待するキーのうち null が 他の検査で赤くならないもの (plan_ref・investigation) の値が null なら 「値がありません (書くなら中身を、書かないならキーごと消す)」と報告する。 consequence / premise_check は必須サブキーの欠落として既に報告されるので 対象にしない (重ねると 1 つの書き忘れが 5 件になる)。 TestReviewTriageRecordSchemaViolations に investigation: (null) と plan_ref: (null) の 2 ケースを足す。record-schema.md の調査の節と plan_ref 行に 「キーだけ書いて値を省いた形は検査が報告する」を足し、triagecheck README の 検査項目の列に「値の無い構造キー」を足す。 順序: 影響範囲が広い (コード・テスト・スキーマ・README) のでこちらが先 | 1 | 済 | `6126c54` |
| P2 | Issue #38 の「型 A〜F はコミット前の検査」という文を、正本 verification.md (A・C・F は書いている最中、B・D・E はコミット前) を読み直さずに写した | #1 | investigation.md:5 の 1 文を、committing.md:37 と同じく正本どおりに絞った 言い方に直す — 調査は手順 4 (方法を決める前)、検証は書いている最中 (A・C・F) とコミット前 (B・D・E) で、どちらも調査の後にかかる。 同ファイル 63 行目 (型 A を scope の記述時に当てる) はそのまま整合する | 2 | 済 | `aec403f` |

- **P1 の調査**: 範囲: record.go の yaml タグ付きフィールドのうち構造を持つもの全部 (ポインタ 2・ 構造体 2・スライス 5・map 1) と walker の case 全部を読み、 plan_ref / investigation / consequence / premise_check を null にした フィクスチャで検査とサマリ生成をプローブ (一時テスト、実施後に削除)。 docs/review-triage/*.yaml 5 ファイルを yaml.v3 で走査し、構造キーが null の形が無いことを確認 / 含めた: plan_ref (record.go:96): 同じポインタ nil の判定で、plan_ref: と書いて値を省くと plans がある回でも plans の無い最後の回でも問題 0 件 (プローブで実測); triagecheck README:11 の検査項目の列: 必須キーの粒度に収まらない新しい項目なので追随させる / 含めなかった: consequence / premise_check の null: 必須サブキーの欠落として既に報告される。重ねると 1 つの書き忘れが複数の問題になる; スライス (included / excluded / gates_fired / depends_on / plans / findings) の null: 空と同義でスキーマも「無ければ省略」としている; record.go:8・64 のコメントが正本を docs/review-triages/README.md と指す取り残し: 移植時の別原因なので含めない

- **P2 の調査**: 範囲: 両スキルの *.md を「コミット前」「型 A〜F」「書いている最中」で grep し、 このブランチの差分で足した文のうち verification.md や型を参照する 7 箇所を読み直した。investigation.md:5 の参照元 (SKILL.md 手順 4・前提知識) を確認 / 含めなかった: investigation.md:63 と record-schema.md の scope 行 (型 A を書く時点で当てる) は正本と整合しており直さない; トリアージ記録 YAML の逐語引用: 過去の回の記録は書き換えない

### 観察

このブランチの初回トリアージ (Issue #38 の対応。full、main 08479a1..64fa3b2)。 別セッションのレビュー結果を tmp/review-code-review-opus-5-6th.yaml で受領した。 head は現在の HEAD と一致し、レビュー前後で HEAD と作業ツリーが不変であることを レビュア側の報告と自分の git status で確認した。 プロジェクト設定 (.claude/akm-claude-plugins/review-triage/config.json) が 無いため、記録の置き場は既存の docs/review-triage/ に合わせ、 triage_summary_command / triage_check_command は未設定として扱い、 サマリ生成と検査は tools/triagecheck を go run で直接叩いた。 関門の一覧 (gates) も無いので免除条項は使っていない (今回は対象の指摘も無い)。 residual 5 件のうち記録に残す価値があるもの: (a) investigation.md の「後ろ向きの調査」の表と verification.md の型 B / D / E の 対象が部分的に重なる。Issue #38 は型 G として足さないと決めており、重なりは 「調査で範囲に入れる対象」と「コミット前に読み直す対象」が同じものを指す構造 によるもの。doc-dag で見る対象。 (b) status: awaiting-human の問題にも investigation を書けるが、書くべきかを スキーマも SKILL.md も述べていない。手順 4 は手順 5 より前なので書けるのが自然。 規則としては未定義のまま残す — 実装しない問題の調査結果が要るかは運用で見る。 (c) renderInvestigation の要素の区切り「; 」は要素自身が「; 」を含むと境目が 読めない。箇条書きの行で表のセルではないので、読みにくさに留まる。 (d) triagecheck README の検査項目の列に investigation.scope の必須検査が明示 されないが「必須キー」に含まれる粒度なので追随漏れとはしない。
