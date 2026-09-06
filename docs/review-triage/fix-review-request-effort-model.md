<!-- 生成物。手で編集しない。正本は fix-review-request-effort-model.yaml — `triagecheck -write-summary` で再生成する。 -->

# fix-review-request-effort-model のトリアージ記録

正本は [fix-review-request-effort-model.yaml](fix-review-request-effort-model.yaml)。読み方と収束の目安は [README](README.md)。

## 推移

| 回 | 日付 | スキル | model | scope | 全件 | 採択 | 保留 | 却下 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2026-09-06 | `code-review` | `opus-5` | full | 1 | 1 | 0 | 0 |
| 2 | 2026-09-06 | `code-review` | `opus-5` | incremental | 1 | 1 | 0 | 0 |
| 3 | 2026-09-06 | `code-review` | `opus-5` | incremental | 1 | 1 | 0 | 0 |
| 4 | 2026-09-06 | `code-review` | `opus-5` | incremental | 1 | 1 | 0 | 0 |
| 5 | 2026-09-06 | `code-review` | `opus-5` | incremental | 0 | 0 | 0 | 0 |
| 6 | 2026-09-06 | `code-review` | `opus-5` | full | 1 | 1 | 0 | 0 |
| 7 | 2026-09-06 | `code-review` | `opus-5` | incremental | 0 | 0 | 0 | 0 |

## 回 1: 2026-09-06 `code-review`

- HEAD `226e248` / model `opus-5` / scope full / level high

| # | 指摘 | 分類 / 被害者 | 帰結 (条件 / 何が / 気づけるか) | 検証 | ゲート | 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `review-triage/skills/review-triage/references/review-request.md:13` 新設の項目 7 が記録の model を「レビュアの報告から確定する」と定めたが、 参照元の review-invocation.md は同じ model を「周回側が持つ実効モデルから採る。 空にしない」と定めており矛盾する。ce-code-review の経路ではモデルの報告が 存在しないため、項目 7 を字義どおり適用すると毎回人間へ差し戻される | skill / operator | review-triage-loop を ce-code-review の経路で走らせ、review-request.md の 項目 7 に従って記録の model を「報告から確定」しようとしたとき。 ce-code-review はモデルを指定する引数も報告も持たない / 2 つの正本が同じ model の出所を別に定めているので、周回は「報告が無いので 人間に報告する」(項目 7) と「実効モデルを書いて空にしない」(review-invocation.md) のどちらかを選ぶことになる。前者を選べば ce-code-review の周回は毎回止まり、 後者を選べば項目 7 が守られないまま記録が書かれ、どちらに従ったかが回ごとに 揺れうる / 気づかない。文書どうしの矛盾を検出する機械検査は無い (triagecheck は judgment-flow の図と決定表の一致だけを検査し、 doc-dag は人間が起動する)。運用中に ce-code-review の周回が毎回止まって初めて気づく | A+B: verified | — | **採択** — A2。段 A: 引用 3 箇所 (review-request.md:13、review-invocation.md:38・:79) を 読んで一致を確認した。段 B: 矛盾の主張なので両方の正本を自分で読んで照合した (sub-agent は使わず、引用がそのまま正本の記述)。ce-code-review がモデルの指定も 報告も持たないことは review-invocation.md:62・:75 で確認した。 全 4 ゲートを評価していずれも不発火。hypothetical は ce-code-review で周回を 起動すれば実運用で必ず起きる条件なので不成立。developer-domain は環境の異常では なく、対象は利用者が使う skill の規範文書なので不成立。disproportionate-cost は 修正が項目 7 の 1 文の書き分けで済み、対象 (1 段落) より小さいので不成立。 already-visible は失敗する関門を名前で挙げられない (Go の関門は Markdown を 見ない) ので不成立 |

### 修正計画

| 問題 | 原因 | 含む指摘 | 修正方法 | 順 | 状態 | 証拠 (SHA / URL) |
| --- | --- | --- | --- | --- | --- | --- |
| P1 | 項目 7 を書くとき、sub-agent がモデルを報告できる code-review の経路だけを 想定して model を skill / level と同列に「報告から確定する」に含めた。 review-invocation.md が記録の model の出所を実効モデルと定めていること、 ce-code-review の経路にはモデルの報告が無いことを見なかった | #1 | 項目 7 で「この報告から確定する」のは skill / level に戻し、model は review-invocation.md の実効モデルから採ることを明記して、報告のモデルは 指定との一致を確かめる用途に限る (ce-code-review は報告が無いので確かめない)。 見出しも「呼んだ skill・effort・モデルの報告」に合わせる (residual の 1 件)。 出力様式の YAML の model のコメントも、実効モデルを正本として参照する形にする | — | 済 | `85ba20d` |

- **P1 の調査**: 範囲: grep -rn '確定\\|この報告から\\|実効モデル' を review-triage/skills/*/SKILL.md、 同 references/*.md、review-triage/README.md に実行し、 review-invocation.md の「実効モデル」「skill を呼んだことの確認」の節と review-request.md の出力様式の節を目で読んだ / 含めた: review-request.md の出力様式の YAML の model のコメント (実効モデルを正本として参照する形にする) / 含めなかった: review-invocation.md:38・:79 は実効モデルを正本として正しく定めているので変えない; level の同種の食い違い (報告から確定 vs 依頼文で指定) は指摘 1 の対象外だが、項目 7 が「指定との一致を確かめる」に変わることで同時に解ける

### 観察

レビューの residual に 1 件: 項目 7 の見出しが「呼んだ skill と effort の報告」の ままで、本文が扱うようになったモデルの報告を含んでいない。指摘 1 を直すときに 同じ段落を触るので、そのときに見出しも合わせるのが自然。 レビューは依頼文で指定した effort high・モデル Opus 5 のとおりに走り、 /code-review を実際に呼んだと報告された (指定との食い違い無し)。

## 回 2: 2026-09-06 `code-review`

- HEAD `9ac9dab` / model `opus-5` / scope incremental / level high

| # | 指摘 | 分類 / 被害者 | 帰結 (条件 / 何が / 気づけるか) | 検証 | ゲート | 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `review-triage/skills/review-triage/references/review-request.md:13` 回 1 の P1 が項目 7 の model だけを「報告から確定する」から外して書き分けたため、 skill / level について同じ矛盾が残った。ce-code-review の経路には skill・effort の 報告が無く、review-invocation.md は周回側が skill に ce-code-review、level に空を 埋めると定めている | skill / operator | review-triage-loop を ce-code-review の経路で走らせ、項目 7 に従って記録の skill / level を「報告から確定」しようとしたとき。この経路の出力には 呼んだ skill と effort の報告が無い / 項目 7 (無ければ人間に報告する) と review-invocation.md:82-83 (周回側が埋める) の どちらに従うかを周回が選ぶことになり、前者なら ce-code-review の周回が毎回止まり、 後者なら項目 7 が守られないまま記録が書かれる。回 1 の指摘 1 と同じ壊れ方が 残りの 2 キーで起きる / 気づかない。文書どうしの矛盾を検出する機械検査は無い (triagecheck は記録の スキーマと judgment-flow の一致だけを検査する)。ce-code-review の周回を 走らせて初めて気づく | A+B: verified | — | **採択** — A2。段 A: review-request.md:13 の第 2 文と第 3 文、review-invocation.md:75・:82・:83 を 読んで引用の一致を確認した。段 B: 矛盾の主張なので両方の正本を自分で照合した (sub-agent は使わない)。全 4 ゲートを評価していずれも不発火。hypothetical は ce-code-review で周回を起動すれば実運用で必ず起きるので不成立。developer-domain は 環境の異常ではなく対象は利用者が使う skill の規範文書なので不成立。 disproportionate-cost は修正が項目 7 の 1 文の書き分けで済むので不成立。 already-visible は失敗する関門を名前で挙げられない (レビューが go test を通して 確かめた) ので不成立 |

### 検知

- 状態: 捉え直し済み
- 根拠: 同じ場所への採択 (same-location) — 指摘 #1 と回 1 の 指摘 1: 回 1 の採択 1 と回 2 の採択 1 はどちらも review-request.md の 「依頼文に含めるもの」の項目 7 (13 行目) を指す。主の条件は、回 2 の採択が 回 1 の P1 の修正由来 (P1 が 3 キーのうち model だけを書き分けた取り残し) で あるものの、回 1 に先立つ回が無く回 1 の採択を修正由来と読めないので当たらない
- 捉え直し: 型 出所を定める正本が複数ある (同じキーの出所を 3 つの文書が別々に定める) / 軸 記録のキー × 経路 × 出所を定める文書 / 根本の原因 review-request.md の項目 7 が、経路 (sub-agent の報告があるか、周回が埋めるか) で 決まる記録のキーの出所を、経路を持たない依頼文の規則として自分で定めている。 キーや経路ごとに例外を足すたびに、経路ごとの採り方を定める review-invocation.md と 食い違う / 修正の単位 項目 7 を「報告を 6 の指定と突き合わせ、食い違いを人間に返す」だけにし、 記録のキーの出所の定めは record-schema.md (意味) と review-invocation.md (経路ごとの採り方) に委ねて参照する。出力様式の YAML のコメントも出所を言わず参照だけにする / 出所 スキルの見立て (skill)

### 修正計画

| 問題 | 原因 | 含む指摘 | 修正方法 | 順 | 状態 | 証拠 (SHA / URL) |
| --- | --- | --- | --- | --- | --- | --- |
| P2 | 回 1 の P1 が、項目 7 の「記録のキーは報告から確定する」という扱いを model の 1 キーだけ書き分けて直し、skill / level に同じ扱いを残した。項目 7 が記録の 3 キーを一律に報告由来と扱っていることが原因で、キーごとに例外を足す直し方では 残りのキーに同じ矛盾が残る | #1 | 項目 7 を、記録の skill / level / model にはいずれも 6 で指定した値を書き、 報告はその指定と一致するかを確かめる用途に限る形にまとめる (周回での 6 の値の 決め方は review-invocation.md の「実効モデル」「effort の既定」「JSON から記録の 様式への対応」が正本)。報告があるはずの経路で報告が無ければ人間に報告し、 ce-code-review のように報告が無い経路では確かめない。出力様式の YAML の model / level のコメントも同じ言い方に揃える | — | 済 | `353ab74` |

- **P2 の調査**: 範囲: grep -rn 'この報告から\\|報告から確定' を review-triage/ (docs/ を除く) と README.md に 実行し、該当が review-request.md:13 だけであることを確かめた。 review-invocation.md の「G0 より後の規則」「effort の既定」 「JSON から記録の様式への対応」の表と、review-request.md の出力様式の YAML のコメントを目で読んだ / 含めた: review-request.md の出力様式の YAML の model / level のコメント (出所を 6 の指定に揃える) / 含めなかった: review-invocation.md:38・:82-83 は周回側が記録のキーを埋める規則として正しく、項目 7 が 6 の指定に委ねる形になれば矛盾しないので変えない; 回 2 の residual (review-invocation.md:53 の間接な参照) は原因が違う (参照の書き方) ので含めない

### 観察

レビューの residual に 1 件: 9ac9dab が review-invocation.md:53 に足した 「値で書く理由もそこが引く正本にある」は参照先を節名でも番号でも指さず、 読み手が 46 行目を経由して項目 6 へ二段たどる必要がある (現状で壊れるものは無い)。 レビューは依頼文で指定した effort high・モデル Opus 5 のとおりに走り、 /code-review を実際に呼んだと報告された。なお 1 度目の実行者は結果ファイルを 書かず報告も欠いたまま終了したため、同じ条件で走らせ直した結果がこの回である。

## 回 3: 2026-09-06 `code-review`

- HEAD `d13063f` / model `opus-5` / scope incremental / level high

| # | 指摘 | 分類 / 被害者 | 帰結 (条件 / 何が / 気づけるか) | 検証 | ゲート | 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `review-triage/skills/review-triage/references/review-request.md:13` 回 2 の P2 が記録の 3 キーの出所を「6 で指定した値」に揃えた結果、model の出所が review-invocation.md の「記録には実効モデルを書き、空にしない」と逆向きに 定義された。6 は ce-code-review にモデルを受け取らない旨を書かせるので、 その経路では項目 7 に従うと model を埋められない | skill / operator | review-triage-loop を ce-code-review の経路で走らせ、項目 7 に従って記録の model を「6 で指定した値」から採ろうとしたとき (6 はその経路でモデルを 受け取らない旨を書かせるので値が無い)。また review-invocation.md が 「指定」を review_model の生の綴りを指す語として予約しているため、項目 7 の 「6 で指定した値」をその意味に読むと、別名 (opus) や inherit の綴りが記録に残る / 記録の model の出所が 2 つの正本で逆向きになり、周回はどちらかを選ぶことになる。 項目 7 に従えば ce-code-review の回で model が空になり triagecheck の 必須キー検査で失敗する。review-invocation.md に従えば項目 7 が守られない / model が空になった場合だけ triagecheck (review-triage-record 検査) が 必須キーの欠落として検出する。文書どうしの矛盾そのものを検出する関門は無い | A+B: verified | — | **採択** — A2。段 A: review-request.md:13・:65、review-invocation.md:16・:24・:25・:38・:79 を 読んで引用の一致を確認した (record-schema.md の model の定義は 31 行目ではなく 30 行目だが、行のずれだけで主張は正しい)。段 B: 項目 6 が ce-code-review に 「モデルを受け取らない旨を書く」と定めることを読み、項目 7 の「6 で指定した値」 ではその経路の model を埋められないことを確認した。全 4 ゲートを評価していずれも 不発火。hypothetical は ce-code-review で周回を起動すれば起きるので不成立。 developer-domain は環境の異常ではなく対象は利用者が使う skill の規範文書なので 不成立。disproportionate-cost は修正が項目 7 の 1 文で済むので不成立。 already-visible は、矛盾の顕在化の一方 (model が空) は triagecheck が捕まえるが もう一方 (項目 7 が守られない) を捕まえる関門を名前で挙げられず、指摘そのもの (文書の矛盾) を検出する関門も無いので不成立 |

### 検知

- 状態: 捉え直し済み
- 根拠: 修正由来の指摘 (fix-derived) — 指摘 #1 と回 2 の 捉え直し: 回 3 の採択 1 は、回 2 の捉え直しの軸 (記録のキー × 経路 × 出所を定める文書) の 別のマス (model × 両経路) を指す。回 2 の P2 が記録の 3 キーの出所を 「6 で指定した値」に揃えたことで model の向きが反転した修正由来で、回 2 の 採択 1 も回 1 の P1 の修正由来だった (回 2 の俯瞰で人間が認めた)
- 根拠: 同じ場所への採択 (same-location) — 指摘 #1 と回 2 の 指摘 1: 回 1・回 2・回 3 の採択はいずれも review-request.md の「依頼文に含めるもの」の 項目 7 (13 行目) を指す
- 捉え直し: 型 出所を定める正本が複数ある (同じキーの出所を 3 つの文書が別々に定める) / 軸 記録のキー × 経路 × 出所を定める文書 / 根本の原因 回 2 の捉え直しと同じ。review-request.md の項目 7 が、経路で決まる記録のキーの 出所を、経路を持たない依頼文の規則として自分で定めている / 修正の単位 回 2 の捉え直しと同じ。項目 7 を「報告を 6 の指定と突き合わせ、食い違いを人間に 返す」だけにし、出所の定めは record-schema.md と review-invocation.md に委ねて参照する / 出所 スキルの見立て (skill)

### 修正計画

| 問題 | 原因 | 含む指摘 | 修正方法 | 順 | 状態 | 証拠 (SHA / URL) |
| --- | --- | --- | --- | --- | --- | --- |
| P3 | 捉え直しの root_cause のとおり。review-request.md の項目 7 が、経路で決まる記録の キーの出所を、経路を持たない依頼文の規則として自分で定めている。回 1 の P1・ 回 2 の P2 はいずれも項目 7 の中で向きを付け替えただけで、出所を定める文書が 3 つある構造を変えなかった | #1 | 捉え直しの fix_unit のとおり。項目 7 から記録のキーの出所の定めを外し、 「報告を 6 の指定と突き合わせ、食い違い (skill を呼んでいない・effort やモデルが 違う・報告があるはずの経路なのに報告が無い) を人間に返す」だけにする。記録の 各キーの意味は record-schema.md の runs[] の表、周回が経路ごとに何から採るかは review-invocation.md の「実効モデル」「JSON から記録の様式への対応」を正本として 参照する。出力様式の YAML の model / level のコメントも出所を言わず、キーの意味の 正本 (record-schema.md) への参照だけにする | — | 済 | `25106f9` |

- **P3 の調査**: 範囲: grep -rn '指定した値\\|報告から確定\\|出所' を review-triage/skills と review-triage/README.md に実行し、記録のキーの出所を定める記述が review-request.md の項目 7 と出力様式のコメント以外に無いことを確かめた。 record-schema.md:30-31 (model / level の意味) と review-invocation.md:46 (項目 6・7 の参照元) を目で読んだ / 含めた: review-request.md の出力様式の YAML の model / level のコメント (出所の記述を外し、record-schema.md への参照にする) / 含めなかった: review-invocation.md:46 は「報告に無いとき・指定と食い違うときの扱いは項目 7 が定める」と書いており、修正後も項目 7 がその扱いを持つので変えない; record-schema.md と review-invocation.md の出所の定めは正本として残す; 回 3 の residual (項目 7 の最終文の理由が規則を説明しない) は、出所の定めを外すことで理由と規則が噛み合うので、別の問題にはしない

### 観察

レビューの residual に 1 件: 項目 7 の最終文の理由「レビュアの判断で変わった値を、 依頼どおりの値として記録しないため」は、記録に指定値を書くという同項の規則を 説明しておらず、食い違い時に記録へ何を書くかは人間への報告で止まっている。 レビューは依頼文で指定した effort high・モデル Opus 5 のとおりに走り、 /code-review を実際に呼んだと報告された (指定との食い違い無し)。 回 2 の検知は人間の指示で俯瞰を行わずに P2 を直したため detected のまま残っている。

## 回 4: 2026-09-06 `code-review`

- HEAD `341770f` / model `opus-5` / scope incremental / level high

| # | 指摘 | 分類 / 被害者 | 帰結 (条件 / 何が / 気づけるか) | 検証 | ゲート | 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `review-triage/skills/review-triage/references/review-request.md:13` 回 3 の P3 が項目 7 から記録のキーの出所の定めを外して record-schema.md と review-invocation.md に委ねたが、委ね先は code-review 経路の skill / level の 出所を定めていない (review-invocation.md の表は ce-code-review 専用、 「実効モデル」は model だけ、record-schema.md は意味だけ)。code-review 経路で 記録の skill / level に何を書くかがどこにも無くなった | skill / operator | code-review 経路で、依頼文の 6 で effort を指定しレビュアが報告した回に、 トリアージ側が記録の level (と skill) に何を書くかを決めるとき / 2 つの委ね先のどちらも code-review 経路の skill / level を定めないので、 「指定した値」か「報告された値」かを回ごとに読み手が決めることになり、 記録の level が回によって違う出所の値になりうる (粒度の比較に使う列) / 気づかない。level は必須キーではないので triagecheck は空でも通し、 出所の違いは値からは分からない | A+B: verified | — | **採択** — A2。段 A: review-request.md:13・:66、review-invocation.md:56・:65・:82、 record-schema.md:31 を読んで引用の一致を確認し、grep '`level`' の 4 件も 再現した。段 B: review-invocation.md の「code-review の場合」(48-54 行) を読み、 記録の skill / level の採り方を書いた行が無いことを確認した。全 4 ゲートを 評価していずれも不発火。hypothetical は code-review 経路の毎回で起きるので不成立。 developer-domain は環境の異常ではなく対象は利用者が使う skill の規範文書なので 不成立。disproportionate-cost は修正が review-invocation.md の箇条書き 1 行で 済むので不成立。already-visible は失敗する関門を名前で挙げられない (level は必須キーでなく triagecheck は出所を見ない) ので不成立 |

### 検知

- 状態: 捉え直し済み
- 根拠: 修正由来の指摘 (fix-derived) — 指摘 #1 と回 3 の 捉え直し: 回 4 の採択 1 は、回 3 の捉え直しの軸 (記録のキー × 経路 × 出所を定める文書) で 空いていたマス (skill / level × code-review × review-invocation.md) を指す。 回 3 の P3 が出所の定めを委ねた先に、このマスを埋める行が無かった
- 根拠: 同じ場所への採択 (same-location) — 指摘 #1 と回 3 の 指摘 1: 回 1〜回 4 の採択はいずれも review-request.md の「依頼文に含めるもの」の 項目 7 (13 行目) を指す
- 捉え直し: 型 出所を定める正本が複数ある (同じキーの出所を 3 つの文書が別々に定める) / 軸 記録のキー × 経路 × 出所を定める文書 / 根本の原因 回 3 の捉え直しと同じ。項目 7 が出所を定めるのをやめて委ねた先 (review-invocation.md) が、記録のキーの採り方を ce-code-review の節の中にだけ 持ち、code-review × skill / level のマスが空いていた / 修正の単位 回 3 の捉え直しと同じ単位で、委ね先の側を経路をまたぐ 1 つの表にする。 review-invocation.md に「記録のキーの出所」の節を設け、キー × 経路の表で 全マスを 1 箇所に置く。項目 7 と両経路の節はそこを参照する / 出所 スキルの見立て (skill)

### 修正計画

| 問題 | 原因 | 含む指摘 | 修正方法 | 順 | 状態 | 証拠 (SHA / URL) |
| --- | --- | --- | --- | --- | --- | --- |
| P4 | 捉え直しの root_cause のとおり。P3 が出所の定めを委ねた review-invocation.md は、 記録のキーの採り方を ce-code-review の節の中の表にだけ持っていて、 code-review 経路の skill / level を定める行が無かった | #1 | review-invocation.md に「記録のキーの出所」の節を設け、キー (model / skill / level / scope) × 経路 (code-review / ce-code-review) の表で全マスを定める。 code-review の skill / level は、7 の突き合わせを通った sub-agent の報告から採る。 ce-code-review の節にあった「記録のキー \| どこから採るか」の表は新しい節への参照に 置き換え、「JSON から記録の様式への対応」は findings の対応だけを残す。 review-request.md の項目 7 の参照先を「記録のキーの出所」に変える (「code-review の場合」を参照させると、その節が項目 7 を参照しているので 節どうしの巡回になる) | — | 済 | `c2e5540` |

- **P4 の調査**: 範囲: grep -rn '`level`' --include='*.md' review-triage/skills (4 件) と、 review-invocation.md の「code-review の場合」「ce-code-review の場合」 「JSON から記録の様式への対応」の全行、loop-flow.md の決定表 G0・L2、 review-request.md の項目 7 と出力様式のコメントを目で読んだ / 含めた: review-invocation.md の ce-code-review の節にある「記録のキー \| どこから採るか」の表 (新しい節へ移す); review-request.md の項目 7 の参照先 (「実効モデル」「JSON から記録の様式への対応」→「記録のキーの出所」) / 含めなかった: loop-flow.md の決定表 G0 は周回の条件の報告を定めるもので、記録のキーの出所は定めていないので変えない; record-schema.md の runs[] の表はキーの意味の正本として残す

### 観察

レビューは依頼文で指定した effort high・モデル Opus 5 のとおりに走り、 /code-review を実際に呼んだと報告された (指定との食い違い無し)。residual は 0 件。

## 回 5: 2026-09-06 `code-review`

- HEAD `a677417` / model `opus-5` / scope incremental / level high

| # | 指摘 | 分類 / 被害者 | 帰結 (条件 / 何が / 気づけるか) | 検証 | ゲート | 判定 |
| --- | --- | --- | --- | --- | --- | --- |

### 観察

レビューは依頼文で指定した effort high・モデル Opus 5 のとおりに走り、/code-review を実際に呼んだと報告された (指定との食い違い無し)。指摘 0 件。 レビューの residual に 1 件: review-invocation.md の「G0 より後の規則」(:38) が「記録の `model` と報告には、実効モデルの名前を書く。空欄にしない」と述べており、新設した「記録のキーの出所」の表 (:54) の `model` の行と同じことを 2 箇所で定めている。値は一致しているので放置して壊れるものは無いが、この節は「この表だけが定める」と宣言しているため、`model` については宣言どおりの単一箇所になっていない (整理・統一の好み)。

## 回 6: 2026-09-06 `code-review`

- HEAD `adffd77` / model `opus-5` / scope full / level high

| # | 指摘 | 分類 / 被害者 | 帰結 (条件 / 何が / 気づけるか) | 検証 | ゲート | 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `review-triage/skills/review-triage/references/review-request.md:12` 新設した項目 6 に説明のない比喩「引っ張り合う」が入っている。リポジトリの CLAUDE.md の「文書の言い回し」の原則 1 に反し、この差分で新しく持ち込まれた語 | skill / operator | 依頼文の正本 (毎回のレビュー起動で読まれる) を人間やエージェントが読み、 依頼文・記録・コミットメッセージに語を複製するとき / 「何が何に対して逆向きに働くか」を述べない比喩が、依頼文や記録に複製されて 広がる。文脈を知らない読み手には effort と報告しない条件の関係が伝わらない / 気づかない。語彙を検査する機械検査は無く、CLAUDE.md は一覧による検査を 意図して持たない | A: verified | — | **採択** — A2。段 A: review-request.md:12 に「引っ張り合う」があること、リポジトリ内 (docs/・tmp/ を除く) でこの 1 箇所だけであることを grep で確認した。段 B は 該当しない (仕様違反の主張ではなく語彙の規則)。全 4 ゲートを評価していずれも 不発火。hypothetical は、条件 (正本が読まれて語が複製される) が CLAUDE.md が 理由として挙げる実測の事象で、先例 (fix-unnatural-wording-35 の記録) でも skill の文書の語彙の指摘は不発火として採択しているので不成立。developer-domain は 利用者が読む skill の文書なので不成立。disproportionate-cost は 1 文の 書き換えなので不成立。already-visible は語彙を検査する関門が無いので不成立 |

### 修正計画

| 問題 | 原因 | 含む指摘 | 修正方法 | 順 | 状態 | 証拠 (SHA / URL) |
| --- | --- | --- | --- | --- | --- | --- |
| P5 | 項目 6 を書くとき、effort と「報告しない条件」の関係を、何が何に対して逆向きに 働くかを述べずに比喩で書いた | #1 | 「effort が高いほど、レビュアは不確かな指摘も報告するようになり、 『報告しない条件』で落とすはずの指摘が増える」のように、関係を直接述べる文に 書き換える | — | 済 | `46fb42d` |

- **P5 の調査**: 範囲: grep -rn '引っ張り合' --include='*.md' を docs/・tmp/ を除くリポジトリ全体に 実行し、review-request.md:12 の 1 件だけであることを確かめた。同じ差分で 足した文 (項目 6・7、review-invocation.md の「記録のキーの出所」の節) を CLAUDE.md の 3 原則に照らして目で読み直した / 波及先なし

### 観察

最終確認の全量レビュー。レビューは依頼文で指定した effort high・モデル Opus 5 の とおりに走り、/code-review を実際に呼んだと報告された (指定との食い違い無し)。 residual は 0 件。レビューは、記録のキーの出所が「記録のキーの出所」の表に 1 箇所に集まっていること、相対リンク 11 本と参照した節名の実在、周辺文書 (README・loop-flow.md・reporting.md・arguments.md・project-config.md・SKILL.md) との矛盾が無いことを確認したと報告した。

## 回 7: 2026-09-06 `code-review`

- HEAD `1700370` / model `opus-5` / scope incremental / level high

| # | 指摘 | 分類 / 被害者 | 帰結 (条件 / 何が / 気づけるか) | 検証 | ゲート | 判定 |
| --- | --- | --- | --- | --- | --- | --- |

### 観察

回 6 (最終確認の全量) の指摘 1 件 (語彙) の修正後の増分。レビューは依頼文で指定した effort high・モデル Opus 5 のとおりに走り、/code-review を実際に呼んだと報告された (指定との食い違い無し)。指摘 0 件、residual 0 件。
