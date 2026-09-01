<!-- 生成物。手で編集しない。正本は feat-review-triage-done-external.yaml — `make docs-review-triage-summary` で再生成する。 -->

# feat-review-triage-done-external のトリアージ記録

正本は [feat-review-triage-done-external.yaml](feat-review-triage-done-external.yaml)。読み方と収束の目安は [README](README.md)。

## 推移

| 回 | 日付 | スキル | model | scope | 全件 | 採択 | 保留 | 却下 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2026-09-01 | `code-review` | `opus-5` | full | 3 | 3 | 0 | 0 |

## 回 1: 2026-09-01 `code-review`

- HEAD `9654d3a` / model `opus-5` / scope full

| # | 指摘 | 分類 / 被害者 | 帰結 (条件 / 何が / 気づけるか) | 検証 | ゲート | 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `review-triage/tools/triagecheck/record.go:636` サマリの修正計画の表で、証拠の列の見出しが SHA のままなのに、done-external の行には applied_external_url の URL が入る。見出しと中身の型が食い違う。 | plugin-code / operator | done-external の問題を含む記録のサマリ (.md) を読むとき / 見出し SHA の列に URL が出る。列の意味を推測させ、URL を SHA として読む余地を残す / 気づかない。サマリの鮮度検査は YAML から生成した内容と .md の一致だけを見るので、 見出しと中身の型の食い違いは生成の両側で同じになり検出されない | A: verified | — | **採択** — A2 — 段 A で見出し (record.go:636) と renderPlanCells の URL 分岐 (record.go:720-729) を 逐語で確認し一致。全ゲートを評価して発火 0 件 (テストで再現でき仮定でない・環境の異常でなく 対象も利用者が読むサマリ・修正は見出しの文字列 1 箇所で不相応でない・赤くなる関門を挙げられない) |
| 2 | `review-triage/skills/review-triage/references/record-schema.md:68` スキーマ表は applied_external_url を done-external のときだけ書くと規定するが、検査は それを守らない。pending / done / awaiting-human に書いても無言で通る。 | skill / operator | done-external 以外の状態の問題に applied_external_url や notes を書いたとき / 検査が通るので、done でコミット済みなのに外部 URL が残る記録が作れる。 正本の規定が機械検査で守られない箇所になる / 気づかない。検査は status の枝ごとに見るキーを決めており、枝の外のキーは評価しない | A: verified | — | **採択** — A2 — 段 A で表の行 (record-schema.md:68) と status の switch (record.go:454-478) を照合し、 done-external の枝以外が AppliedExternalURL / Notes を見ないことを確認。実際に 3 通り (pending+url / done+url / awaiting-human+notes) を検査に通して問題 0 件を再現した。 全ゲートを評価して発火 0 件。なお同じ排他を持つ sha は検査されており (record.go:456)、 applied_external_url だけが規定と検査で食い違う |
| 3 | `review-triage/skills/review-triage/references/record-schema.md:96` 「だから notes に反映を確認した方法を書く」と規範は述べるが、検査は URL か notes の どちらかで通す。URL だけの記録は検査を通り、サマリにも反映済みの行が出ない。 | skill / operator | リポジトリ外の反映先に URL がある場合 (PR 本文の修正など。最も起きやすい経路) / 反映を確認した方法がどこにも残らない記録が作れる。URL は現在の本文を返すだけで 修正の前後を判別できないため、後から反映の有無を確かめる手段が無くなる / 気づかない。検査は URL があれば notes を要求せず、サマリ生成も notes が空なら 表の外の行を出さないので、欠落を知らせる経路が一つも無い | A: verified | already-visible | **採択** — A1 — 免除条項。条件 1: 指摘は機械検査 (triagecheck) が規範の要求を検出しないこと、 すなわち検出能力の欠落を主張している。条件 2: 3 層から候補を挙げていずれも検出しない — make ターゲットはこのリポジトリに Makefile が無く存在しない / 検査項目は review-triage-record と judgment-flow の 2 つで、前者は status の枝ごとのキーしか見ず 後者は判定フローの図と表の照合なので対象外 / テスト関数は TestReviewTriageRecordDoneExternalPasses が「URL だけで通る」ことを逆に固定しており 欠落を検出しない。URL のみ (notes 無し) を実際に検査とサマリ生成へ通し、問題 0 件かつ 「リポジトリ外へ反映済み」の行が出ないことを再現した |

### 修正計画

| 問題 | 原因 | 含む指摘 | 修正方法 | 順 | 状態 | SHA |
| --- | --- | --- | --- | --- | --- | --- |
| P1 | 証拠の欄の役割を SHA から証拠に広げたとき、セルを埋めるコードだけを直し、 同じ関数の呼び出し元にある見出しの文字列に追随しなかった | #1 | サマリの修正計画の表の見出しを SHA から 証拠 (SHA / URL) に変え、列が 2 つの型を 取ることを見出しで示す。既存の記録のサマリは再生成で追随する | 1 | 未着手 | — |
| P2 | status の枝ごとにキーを検査する既存の形にキーを足したとき、 done-external のときだけ書くという排他をスキーマ表に書いておきながら、検査に写さなかった | #2 | done-external 以外の枝で applied_external_url と notes が空であることを検査する。 排他を検査する既存の sha (pending / awaiting-human の枝) と同じ形に揃える | 2 | 未着手 | — |
| P3 | URL か notes のどちらかを必須にするという検査の規則を決めた後、同じ節に前から 書いてあった「だから notes に反映を確認した方法を書く」という無条件の文を読み直さなかった | #3 | 規範の文言を検査に合わせて緩める (人間が選択)。notes を無条件に要求する文を、 URL があっても確認方法を残すことを推奨する文に改め、必須なのは 「URL か notes のどちらか」であることを明記する。検査は変えない | 3 | 未着手 | — |

### 観察

レビューは報告のみで走った (head 9654d3a が現在の HEAD と一致、作業ツリーは不変)。 指摘 3 件はいずれも、この差分自身が「正本と実装の乖離」を直す変更であるにもかかわらず、 同じ型の乖離を新たに作っている点を突いている。#2 と #3 は record-schema.md (正本) と record.go (検査) の食い違いで、依頼文で重点として挙げた箇所からそのまま出た。 residual の 3 件に目を通した。1 つ目 (SKILL.md 手順 7 の報告対象が done-external に触れない) は、done-external が再開対象外である以上、報告しなくても壊れるものが無いという読みに同意する。 2 つ目 (notes が run 直下と plans 直下の両方にある) は階層が違い YAML として曖昧にならない。 3 つ目 (.tool-versions が指す golang 1.25.4 が未インストール) はこの差分と無関係だが、 レビュアがテストを走らせられるよう依頼文で 1.25.1 の直接指定を案内した。 P3 は規範と検査のどちらを動かすかの設計判断を含むため review-triage-fix が 人間に返し、「規範の文言を検査に合わせて緩める」が選ばれた。もう一方の案 (検査を厳しくして notes を無条件に必須にする) は、URL を持たない対象のために notes を逃がし弁として残した設計と衝突するため採らなかった。
