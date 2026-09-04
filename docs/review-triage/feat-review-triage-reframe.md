<!-- 生成物。手で編集しない。正本は feat-review-triage-reframe.yaml — `triagecheck -write-summary` で再生成する。 -->

# feat-review-triage-reframe のトリアージ記録

正本は [feat-review-triage-reframe.yaml](feat-review-triage-reframe.yaml)。読み方と収束の目安は [README](README.md)。

## 推移

| 回 | 日付 | スキル | model | scope | 全件 | 採択 | 保留 | 却下 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2026-09-04 | `code-review` | `opus-5` | full | 2 | 2 | 0 | 0 |
| 2 | 2026-09-04 | `code-review` | `opus-5` | incremental | 1 | 1 | 0 | 0 |
| 3 | 2026-09-04 | `code-review` | `opus-5` | incremental | 1 | 1 | 0 | 0 |
| 4 | 2026-09-04 | `code-review` | `opus-5` | incremental | 0 | 0 | 0 | 0 |
| 5 | 2026-09-04 | `code-review` | `opus-5` | full | 1 | 1 | 0 | 0 |

## 回 1: 2026-09-04 `code-review`

- HEAD `cbca585` / model `opus-5` / scope full / level high

| # | 指摘 | 分類 / 被害者 | 帰結 (条件 / 何が / 気づけるか) | 検証 | ゲート | 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `review-triage/tools/triagecheck/record.go:716` fix-derived の根拠の prior に「直前の回の採択を指す文字列」(指摘 3 など) を書くと 検査が必ず落ちる。recurrence-detection.md の「発火したときに記録に書くもの」は prior の 3 つの形を condition で場合分けせずに定めているのに、検査は fix-derived の prior を「比べた回の plans の問題の識別子」か「捉え直し」だけに絞っている | plugin-code / operator | review-triage が正本どおりに fix-derived の prior を「指摘 N」と書いたとき (直前の回の修正を review-triage-fix を経ずに人間が直したために plans が無い、または採択そのものを比べた先にした場合) / 検査が赤くなり、正本どおりに書いた記録が通らない。書き手は通すために prior を 実在する問題の識別子に書き換える方向へ誘導され、根拠の監査経路 (なぜ同じ型と 読んだか) が実態と食い違う / 検査が赤くなるので落ちたことには気づく。ただし、書き換えて通した記録が実態と食い違うことは気づかない (文書と検査の食い違いを捕まえる関門は無い) | A+B: verified | — | **採択** — A2。段 A: record.go:713-718 を読み、fix-derived の prior を plansByRun の問題の 識別子か、比べた回が reframed のときの「捉え直し」に限っていることを確認した。 段 B: recurrence-detection.md の「発火したときに記録に書くもの」を逐語で読み、 prior の 3 つの形 (問題の識別子・採択を指す文字列・捉え直し) が condition で 場合分けされていないことを確認した。record-schema.md の prior の行も 3 値を 並べ、どれを書くかを recurrence-detection.md に委ねている。文書と検査の契約が 食い違うという主張は成り立つ。全 4 ゲートを評価して発火 0 件 — hypothetical: レビュアのプローブがそのままテストになる。developer-domain: 検査は利用者の 記録にかかる。disproportionate-cost: 直すのは文の場合分け 1 文か検査の条件 1 行。 already-visible: fix-derived で「指摘 N」を通すテストは無い (TestReviewTriageRecordRecurrenceViolations は不在の問題識別子と捉え直しの 誤用だけ)。免除条項は検出能力の欠落の主張ではないので対象外。 修正方法は設計判断を含む — 文書側を「fix-derived は問題の識別子か捉え直し、 same-location は採択を指す文字列」と場合分けして絞るか、検査側で採択を指す 文字列も受けるか。どちらにするかは review-triage-fix が人間に諮る対象 |
| 2 | `CONCEPTS.md:89` CONCEPTS.md の「修正由来の指摘」が「2 回続けて現れたら…次の修正の前に捉え直しを 行う」と無条件に定めるが、手順の正本 reframing.md では人間が繰り返しを認めなければ 捉え直しはせず declined で終える。用語の正本と手順の正本が食い違う | doc-dev / developer → operator | スキル文書が用語の正本として案内する CONCEPTS.md を先に読んだ実行者 (スキルを走らせるエージェントと、それを見ている人間) が、第 1 段で人間が「繰り返しではない」と答えた場面に当たったとき / 「2 回続いたら捉え直しを行う」を定義の一部と読み、declined で終える選択肢を 持たないまま第 2 段へ進む。人間の判断を手順が上書きする形になり、俯瞰が 人間の確認を軸にする設計 (問いが先、見立ては後) と食い違う / 気づかない — 用語集と手順書の文の矛盾を捕まえる機械検査は無く、リンク検査は文面を見ない | A: verified | — | **採択** — A2。被害者はパスの分類 (doc-dev) では開発者だが、review-triage-fix/SKILL.md と reframing.md が CONCEPTS.md を「用語の正本」として利用者 (スキルの実行者) に 読ませるので、要求水準の高い側 (利用者) へ上書きした。段 A: CONCEPTS.md:89 と reframing.md:42 を逐語で読み比べ、前者が無条件の「捉え直しを行う」、後者が 「認めなければ捉え直しは書かない」であることを確認した。 全 4 ゲートを評価して発火 0 件 — hypothetical: 読めば再現する。 developer-domain: 対象は利用者に届く文書。disproportionate-cost: 修正は 1 文の 書き換え (「次の修正の前に俯瞰を行い、捉え直すかどうかを人間と決める」)。 already-visible: 文の矛盾を検出する関門は無い。免除条項は対象外 |

### 修正計画

| 問題 | 原因 | 含む指摘 | 修正方法 | 順 | 状態 | 証拠 (SHA / URL) |
| --- | --- | --- | --- | --- | --- | --- |
| P1 | 検査に fix-derived の prior と plans の照合を足したとき、prior の形を定める正本 (recurrence-detection.md「発火したときに記録に書くもの」) を condition ごとの 場合分けに直さず、検査側にだけ条件を入れた。文書は 3 つの形を無条件に並べたまま になり、文書と検査の契約が食い違った | #1 | 文書と検査のどちらを規範にするかは設計判断なので人間に返した (options)。 人間は (a) を選んだ。文書を場合分けして絞り、検査は現状のまま。 決まった側に合わせて、prior の形を定める 3 箇所 (recurrence-detection.md:38・ record-schema.md:120 の prior の行・reframing.md 第 1 段の辺の説明) と検査 (record.go の fix-derived の照合とそのテスト) を同じ動機で直す。順序は P2 と 独立 (依存なし) | — | 済 | `061f26b` |
| P2 | CONCEPTS.md の「修正由来の指摘」を要件の段階で書き、後で手順 (reframing.md) に 「人間が繰り返しと認めなければ捉え直さない」を定めたとき、用語集の文を追随させ なかった | #2 | CONCEPTS.md:89 の「次の修正の前に捉え直しを行う」を、俯瞰で人間と確かめ、繰り返しと 認めたときに捉え直す、という条件つきの文に書き換える。用語の定義は変えない。 P1 と依存なし。影響範囲が狭いので先に直す | — | 済 | `1fc8b17` |

- **P1 の調査**: 範囲: 前向き: grep -rn '指摘 3\\|採択を指す\\|捉え直しを指す' CONCEPTS.md review-triage/README.md review-triage/skills (--include='*.md') → 一致は recurrence-detection.md:30,38 と record-schema.md:120 の 3 行。同じ語を 持たない近くの辺として reframing.md「第 1 段 > 図」の辺の説明 (問題の識別子、 採択、または捉え直し) を目で読んだ。後ろ向き: record.go:706-718 の照合と record_test.go の TestReviewTriageRecordRecurrenceViolations (prior が plans に 無い・捉え直しの誤用の 2 ケース) と TestReviewTriageRecordRecurrencePriorReframed / 含めた: record-schema.md:120 の prior の行 — 3 値を並べて recurrence-detection.md に委ねており、正本を場合分けすれば追随が要る; reframing.md 第 1 段の辺の説明 — 同じ 3 値を並べている; record.go の fix-derived の照合と record_test.go の該当テスト — 検査側を規範にするなら不変、文書側を規範にするなら採択を指す文字列の受け入れを足す / 含めなかった: recurrence-detection.md:30 (捉え直し後の照らし方) — prior に捉え直しを指す旨は場合分けと矛盾しないので変えない

- **P2 の調査**: 範囲: 前向き: grep -rn '捉え直しを行う\\|捉え直します\\|次の修正の前に' CONCEPTS.md review-triage/README.md review-triage/skills (--include='*.md') → CONCEPTS.md:89、 README.md:16、recurrence-detection.md:57 の 3 行。後ろ向き: CONCEPTS.md を 用語の正本として参照する reframing.md:3・recurrence-detection.md:3・ review-triage-fix/SKILL.md 前提知識・grouping.md「捉え直しがあるとき」を目で読んだ / 含めなかった: README.md:16 — 「人間と確かめてから」と条件を含む描写で、無条件ではない; recurrence-detection.md:57 — 従来の目安の引用で、表を書く作業を俯瞰に委ねる文。無条件の捉え直しを述べていない; CONCEPTS.md の参照元 4 箇所 — 用語の定義そのものは変えないので追随は不要

### 観察

レビューは別セッションの code-review (opus-5, high, 全量) で、報告のみで走った (実行前後で HEAD cbca585 と作業ツリーが不変であることを確認)。 residual の 3 件のうち、記録に残す価値があるのは次の 2 つ。 (1) reframing.md「対象の選び方」の「declined_reason も reframe も無い回」は、検査が detected にその 2 つを禁じているので後半の条件は常に真で、読み手には冗長。 (2) same-location の prior は自由文字列のままで、fix-derived との非対称は監査経路の 強さの違いとして残る (record-schema.md の設計どおり)。 このブランチで足した検知の手順は、回 1 では判断しない (比べる過去の回が無い)。

## 回 2: 2026-09-04 `code-review`

- HEAD `3e548d4` / model `opus-5` / scope incremental / level high

| # | 指摘 | 分類 / 被害者 | 帰結 (条件 / 何が / 気づけるか) | 検証 | ゲート | 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `review-triage/skills/review-triage/references/recurrence-detection.md:39` 回 1 の修正で足した「直前の回に plans が無いときは修正由来の根拠は書けない」が 無条件に書かれているが、直前の回が捉え直し済み (reframed) なら plans が無くても prior: 捉え直し で修正由来の根拠を書けて検査も通る。同じ文書の捉え直し後の照らし方 (L30) と検査の双方に反する | skill / operator | 直前の回で捉え直しに合意して記録に書いたが、その単位の修正計画 (plans) をまだ書いていない状態で次のレビューを回し、捉え直しの軸の別のマスを指す採択が出たとき / L39 に従った実行者は「修正計画が無いので修正由来の根拠は書けない」と読んで 検知を書かず、L30 と検査が許す prior: 捉え直し の経路を使わない。俯瞰の連鎖が 記録上で途切れ、捉え直しの後に同じ型が続いたことが残らない / 気づかない — 文書内の矛盾を捕まえる機械検査は無く、検知を書かなかったことは記録に現れない | A: verified | — | **採択** — A2。段 A: recurrence-detection.md:30 (捉え直し後は reframe.axes と照らし、prior には 捉え直しを指す)、同 :38 (reframed なら捉え直しを指す文字列)、同 :39 (plans が無ければ 修正由来の根拠は書けない、と無条件) を逐語で読み比べ、:39 が :30/:38 の経路を除外して いないことを確認した。record.go:715 の isReframe も plansByRun を見ないので、検査は この経路を通す。主張どおり。 全 4 ゲートを評価して発火 0 件 — hypothetical: 状態は reframing.md の 「記録に書いてから束ねに進む」の途中で普通に起きる。developer-domain: 対象は 利用者に届くスキル文書。disproportionate-cost: 修正は 1 文に例外を添えるだけ。 already-visible: 文書内の矛盾を検出する関門は無い。免除条項は対象外 |

### 修正計画

| 問題 | 原因 | 含む指摘 | 修正方法 | 順 | 状態 | 証拠 (SHA / URL) |
| --- | --- | --- | --- | --- | --- | --- |
| P1 | 回 1 の P1 で「直前の回に plans が無いとき」の文を足したとき、直前の回の状態 (通常 / reframed / declined / plans 無し) を軸にした表として他の文と突き合わせず、 主の条件 2 (L21) と捉え直し後の照らし方 (L30) との整合を見なかった。同じ規則 (修正由来の根拠が成り立つ条件・prior の形) が 3 つの文に散っていたので、1 文を 足すと他の文との矛盾が生まれた | #1 | 例外を 1 文足すのではなく、「直前の回の状態 × 規則」の表を recurrence-detection.md に 1 つ置き、主の条件・捉え直し後・発火したときに書くものの各文をその表への参照にする。 列は 通常 (plans あり) / reframed / declined / plans 無し、行は 主の条件 1 の照らし先 / 条件 2 の要否 / prior に書くもの。reframed の列では条件 2 を不要にする (捉え直しは 人間が繰り返しを認めた結果なので、今回の採択が表の別のマスを指すかだけで足りる)。 あわせて、reframed で plans の無い回を prior: 捉え直し で通す実装済みの挙動の 回帰テストを record_test.go に足す。順序: 問題は 1 つ | — | 済 | `061f26b` |

- **P1 の調査**: 範囲: 前向き: recurrence-detection.md の主の条件 (L14-22)・捉え直し後 (L28-32)・ 発火したときに記録に書くもの (L34-45) を全文読み直し、grep -n '修正由来の根拠\\|plans\\| 修正計画' を recurrence-detection.md・record-schema.md・reframing.md に当てた。 後ろ向き: record.go:713-718 の照合 (isReframe は plansByRun を見ない) と record_test.go の recurrenceReframedThenRecordYAML (reframed の回に plans がある fixture)、reframing.md:79「記録に書いてから束ねに進む」(reframed かつ plans 未記入を 正当な途中状態として生む文)、record-schema.md:120 の prior の行、reframing.md:19 の辺 / 含めた: recurrence-detection.md L21 主の条件 2 — reframed の後の扱いが未定義 (直前の回の検知が同じ場所の条件だけで発火して捉え直しに至った場合、条件 2 を満たせず L30 の経路が使えない)。同じ原因の別の現れ; record_test.go — reframed で plans の無い回を prior: 捉え直し で通すことを固定するテスト (レビュアのプローブと同じ形)。実装済みの挙動の回帰テスト / 含めなかった: record.go:715 の isReframe — plans を見ない現状が文書の意図と一致するので変えない; record-schema.md:120・reframing.md:19 — 既に『reframed なら捉え直し』と書いており追随不要; reframing.md:79 — reframed かつ plans 未記入を途中状態として生む文だが、それ自体は正しい。L39 の例外がこの状態を同じ語で指すようにする

### 観察

レビューは別セッションの code-review (opus-5, high, 増分 cbca585..3e548d4) で、 報告のみで走った (実行前後で HEAD と作業ツリーが不変であることを確認)。 residual の 3 件はいずれも「委譲の宣言があり二重管理にならない」「設計どおりの非対称」 という観察で、放置して壊れるものが無いため記録には写さない。 このブランチで足した検知の手順を当てると、指摘 1 は回 1 の P1 の修正由来 (plans の 無い場合の文を足したときに reframed の経路を除外しなかった) だが、回 1 には修正由来の 指摘が無い (回 1 の指摘はレビュー前の作業に由来し、比べる前の回が無い) ので、主の条件の 2 回連続には当たらない。補助の条件 (同じ場所への採択 2 回連続) は、回 1 の指摘 1 が record.go、回 2 の指摘 1 が recurrence-detection.md を指すので当たらない。発火しない

## 回 3: 2026-09-04 `code-review`

- HEAD `faa30bf` / model `opus-5` / scope incremental / level high

| # | 指摘 | 分類 / 被害者 | 帰結 (条件 / 何が / 気づけるか) | 検証 | ゲート | 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `review-triage/skills/review-triage/references/recurrence-detection.md:26` 回 2 の修正で足した表の「通常」の行が直前の回の recurrence を「無いか declined」に 限定したため、同じ文書が正常と明言する「直前の回が detected のまま未処理で plans が ある」状態がどの行にも当たらない。表を正本にした各文が、その状態で照らし先も 条件 2 の要否も prior も定めない | skill / operator | 直前の回で検知が出たが人間が review-triage-fix を呼ばず (または呼んで俯瞰を保留したまま)、別途 plans が書かれた状態で次のレビューを回し、今回の採択が直前の修正作業に由来するとき / 表に当たる行が無く、実行者は「捉え直し済み」でも「修正計画が無い」でもない状態を どう扱うか決められない。字面どおり「修正計画が無い」行に寄せると、plans が あるのに発火しない誤読になる。検知が記録に残らず、連鎖が途切れる / 気づかない — 文書内の網羅の抜けを捕まえる機械検査は無く、発火しなかったことは記録に現れない | A: verified | — | **採択** — A2。段 A: recurrence-detection.md:26 の表の「通常」の行 (recurrence は無いか declined) と、同 :63 の「直前の回が detected のまま未処理でも、判断を止めず通常 どおり行う」を逐語で読み比べ、detected かつ plans がある状態が表のどの行にも 当たらないことを確認した。主張どおり。 全 4 ゲートを評価して発火 0 件 — hypothetical: 状態は運用で普通に起きる (人間が review-triage-fix を呼ばずにレビューを回す)。developer-domain: 対象は 利用者に届くスキル文書。disproportionate-cost: 修正は表の行 1 つの条件の書き換え。 already-visible: 表の網羅を検査する関門は無い。免除条項は対象外 |

### 検知

- 状態: 捉え直し済み
- 根拠: 修正由来の指摘 (fix-derived) — 指摘 #1 と回 2 の P1: 回 2 の P1 で「直前の回の状態 × 規則」の表を足したとき、直前の回の状態の 列挙から detected (未処理) を落とし、L63 の文と食い違った。回 2 の指摘 1 も 回 1 の P1 (plans が無い場合の文を足したときに reframed の経路を除外しなかった) の修正由来で、修正由来の指摘が回 2 と回 3 で連続した。同じ場所の条件は、 回 2 が「発火したときに記録に書くもの」の節、回 3 が「主の条件」の表なので 当たらない
- 捉え直し: 型 直前の回の状態の列挙が、状態 × 修正計画の有無の組み合わせを網羅していない / 軸 recurrence.status (無し / detected / declined / reframed) × plans の有無 / 根本の原因 表の行を「状態の列挙」で書いているため、状態を 1 つ考慮するたびにマスを 1 つ 埋める修正になり、埋めていないマス (detected かつ plans あり) が残る / 修正の単位 行の条件を列挙ではなく順に問う 2 つの問い (reframed か → 捉え直し済み、 そうでなければ plans があるか → 通常 / 修正計画が無い) で定め、どの状態でも 必ずどれかの行に落ちるようにする / 出所 スキルの見立て (skill)

### 修正計画

| 問題 | 原因 | 含む指摘 | 修正方法 | 順 | 状態 | 証拠 (SHA / URL) |
| --- | --- | --- | --- | --- | --- | --- |
| P1 | 回 2 の P1 で「直前の回の状態 × 規則」の表を足したとき、行の条件を状態の列挙で 書き、recurrence.status × plans の有無の組み合わせを網羅しなかった (detected かつ plans あり が抜けた)。回 1・回 2 と同じく、状態を 1 つ考慮するたびにマスを 1 つ 埋める修正になっていた | #1 | 捉え直しの単位のとおり、表の行の条件を順に問う 2 つの問いで定め直す。表の下に 「通常の行には未処理の検知 (detected) も含む」と添えて「回ごとに判断する」の文と 結びつける。検査とテストは変えない (照らし先の選択は検査の対象外)。問題は 1 つ | — | 済 | `061f26b` |

- **P1 の調査**: 範囲: 前向き: recurrence-detection.md の表 (L24-28)・捉え直し後の節・回ごとに判断する (L61-64) を全文読み直し、recurrence.status × plans の有無の 8 マスを表に書き出した。 reframing.md「対象の選び方」と record-schema.md の状態の行 (状態を列挙する箇所) を 目で読んだ。後ろ向き: record.go:713-718 (照らし先の選択を検査は行わない)、 record_test.go の recurrence のテスト / 含めた: recurrence-detection.md の表の下の注記 — 通常の行が detected を含むことを L63 と結びつける / 含めなかった: 捉え直し後の節の「declined なら通常の行」 — 新しい定義でも成り立つので変えない; reframing.md「対象の選び方」・record-schema.md の状態の行 — 状態の定義そのものの列挙で、同じ原因ではない; record.go・record_test.go — 照らし先の選択は検査の対象外で変更不要。residual のテストのコメントの位置ずれは別の整理として残す

### 観察

レビューは別セッションの code-review (opus-5, high, 増分 3e548d4..faa30bf) で、 報告のみで走った (実行前後で HEAD と作業ツリーが不変であることを確認)。 residual の 3 件は整理の範疇か確認済みの事項で、放置して壊れるものが無いため記録には 写さない。ただし 1 件目 (新テストの挿入で元のテストのコメントが移った) は、 修正で record_test.go に触るなら同じ動機で直してよい。 検知はこのブランチで足した手順 (recurrence-detection.md) をこのセッションで当てた もので、インストール済みのスキルの版には無い手順である。主の条件 (修正由来の指摘が 2 回連続) で発火した。俯瞰は review-triage-fix の冒頭が担う

## 回 4: 2026-09-04 `code-review`

- HEAD `80f8609` / model `opus-5` / scope incremental / level high

| # | 指摘 | 分類 / 被害者 | 帰結 (条件 / 何が / 気づけるか) | 検証 | ゲート | 判定 |
| --- | --- | --- | --- | --- | --- | --- |

### 観察

レビューは別セッションの code-review (opus-5, high, 増分 faa30bf..80f8609) で、 報告のみで走った (実行前後で HEAD と作業ツリーが不変であることを確認)。指摘 0 件。 residual のうち 1 件を写す: recurrence-detection.md:47 の「declined なら表の通常の行の とおり修正作業と照らす」は、その回に plans があるときだけ成り立つ (無ければ問い 2 で 「修正計画が無い」の行に落ちる)。表が正本で L47 はそれを引くだけなので行の選択は 狂わないが、文としては条件を省いている。放置して壊れるものは無い。 採択が無いので検知の判断は行わない (対象は今回の採択だけ)。回 3 の捉え直しの後の 増分で同じ型の指摘は出なかった

## 回 5: 2026-09-04 `code-review`

- HEAD `068efa8` / model `opus-5` / scope full / level high

| # | 指摘 | 分類 / 被害者 | 帰結 (条件 / 何が / 気づけるか) | 検証 | ゲート | 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `review-triage/skills/review-triage/references/recurrence-detection.md:9` 検知の正本は「比べる相手は直前の 1 回」と定めるが、検査は prior_run を 「1 以上かつ自回より小さい」としか見ないため、直前を飛び越して古い回を指す 根拠が検査を通り、サマリと俯瞰の第 1 段の図にそのまま出る | skill / operator | 書き手が「繰り返しの起点はもっと前の回だ」と読んで、直前でない回を prior_run に 書いたとき (たとえば直前の回の検知が declined で、その前の回を指す) / 検査は緑のまま通り、reframing.md の第 1 段の図は prior_run の prior から今回の 指摘へ辺を引くので、途中の回を飛ばした連鎖が描かれる。人間は途中の回を見ない まま「繰り返していると認めますか」に答える / 気づかない — 検査は緑で、サマリも図も飛び越しをそのまま描く | A+B: verified | — | **採択** — A2。段 A: record.go の priorRunOK (ev.PriorRun >= 1 && ev.PriorRun < runNo) を 読み、上限が自回-1 で下限が 1 なので直前でない回も通ることを確認した。段 B: recurrence-detection.md:9「比べる相手は直前の 1 回」と record-schema.md の prior_run の行「1 以上かつ自回より小さいこと」を読み比べ、様式の表は検査と同じ 広い範囲を書いていて、判断の正本 (直前の 1 回) だけが狭いことを確認した。 回 2 の residual に同じ非対称を「どちらを規範にするか」と残していたが、今回は 飛び越した辺が俯瞰の図に出るという具体の帰結が示されたので指摘として採る。 免除条項の条件 1 (検査が正本の規則を検出しない) は成り立つが、関門の一覧 (設定の gates) が未設定なので免除条項は使わない。全 4 ゲートを評価して発火 0 件 — hypothetical: レビュアのプローブがそのままテストになる。developer-domain: 検査は利用者の記録にかかる。disproportionate-cost: 直すのは検査の条件 1 行と テスト 1 ケースと様式の表の 1 行。already-visible: prior_run が直前でない回を 指すケースのテストは無い (TestReviewTriageRecordRecurrenceViolations は 0 と 自回以上だけ)。 規範は判断の正本 (直前の 1 回。計画の KTD4 で人間が選んだ) に合わせ、検査と 様式の表をそれに寄せる |

### 修正計画

| 問題 | 原因 | 含む指摘 | 修正方法 | 順 | 状態 | 証拠 (SHA / URL) |
| --- | --- | --- | --- | --- | --- | --- |
| P1 | 検査を書いたとき、判断の正本の prior_run の規則 (比べる相手は直前の 1 回・回 1 では 判断しない・捉え直し済みの回は prior に 捉え直し と書く) を直接写さず、「1 以上かつ 自回より小さい」という広い範囲で代用した。様式の表と README もその広い範囲を写した | #1 | 検査を正本の規則そのものに合わせる。prior_run は直前の回 (自回 - 1) に限り、回 1 の recurrence は「比べる過去の回が無い」と専用の文で弾き、比べた回が reframed なら fix-derived の prior は 捉え直し に限る (人間が含めると決めた)。様式の表の prior_run の 行と README の検査項目の説明を同じ精度にそろえ、テストを足す。問題は 1 つ | — | 済 | `020d835` |

- **P1 の調査**: 範囲: 前向き: recurrence-detection.md の prior_run に関わる規則 (L9・L10・表の捉え直し 済みの行) と、record.go の priorRunOK・isReframe・plansByRun の照合、 record-schema.md:119 の prior_run の行、triagecheck/README.md:11 の検査項目の説明を 読み比べた。後ろ向き: record_test.go の recurrence のテスト全件 (prior_run は すべて直前の回を指す)、docs/review-triage/*.yaml の prior_run (この記録の回 3 の prior_run: 2 のみ、直前)、reframing.md:27 (根拠の外の辺を足してよい、という文)、 計画 docs/plans/…-plan.md の U1 の検査の記述 / 含めた: record-schema.md:119 の prior_run の行 — 広い範囲を写しているので直前の回に直す; record.go の回 1 の扱い — 範囲の副作用で弾いていた形を、正本どおり専用の文で弾く; record.go の捉え直し済みの回の prior — 正本は 捉え直し に限るが検査は問題の識別子も通していた。人間が含めると決めた; triagecheck/README.md:11 — 「過去の回」を「直前の回」に / 含めなかった: reframing.md:27 — 根拠の外の辺を足す文は、根拠が直前を指す規則と整合するので変えない; docs/plans/…-plan.md の U1 — 当時の計画の記録なので直さない; 既存のテストの fixture と実記録 — すべて直前の回を指しており、絞っても落ちない

### 観察

レビューは別セッションの code-review (opus-5, high, 最終確認の全量 main..068efa8) で、 報告のみで走った (実行前後で HEAD と作業ツリーが不変であることを確認)。 residual の 3 件は、根拠の重複 (図の辺が二重になるだけ)、捉え直しと修正計画の 単位の一致は検査の対象外 (計画の KTD9 どおり)、reframing.md の対象の選び方の冗長な 条件 (回 1 の観察に既出) で、いずれも放置して壊れるものが無いため記録には写さない。 検知の判断: 直前の回 (回 4) は指摘 0 件で修正計画が無く、表の「修正計画が無い」の 行に当たるので修正由来の根拠は書けない。回 4 に採択が無いので同じ場所の条件も 当たらない。発火しない
