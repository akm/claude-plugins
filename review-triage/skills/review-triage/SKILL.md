---
name: review-triage
description: code-review や ce-code-review が出したレビュー指摘を一件ずつ吟味し、採択 / 保留 / 却下を判断して記録する。修正は行わない。「レビューの指摘を選り分けて」「この指摘は対処すべきか判断して」「review-triage を実行して」のような依頼で使う。同じセッションで直前に走らせたレビューの指摘を対象にする。唯一の引数 --gen-config は、指摘の有無に関わらず設定ファイルの雛形を生成して終了する。
---

# review-triage: レビュー指摘の採否の判断

レビュー指摘を一件ずつ吟味し、未対処時の帰結を自分で構成してから採否を決める。**成果物は判定済みの記録であって、修正ではない** — 採択した指摘を直すのは後段の [review-triage-fix](../review-triage-fix/SKILL.md)。呼ぶかどうかは人間が決める。

**判定の順序・分岐・各ノードの条件は [references/judgment-flow.md](references/judgment-flow.md) が正本。** このファイルでは言い直さない — 以下、ノード ID (D1〜D7・E1・E2・A / H / R) はそこを指す。

## 前提知識

- **上流のレビューは報告のみで走らせる。** 指摘を見つけるたびに直すと、先に直した修正が後の判断の前提を変える (`code-review` は `--fix` 無し、`ce-code-review` は `mode:agent`)。
- **別セッションでレビューを走らせて結果をファイルで受け取る場合、依頼文と受け渡し様式の正本は [references/review-request.md](references/review-request.md)。** 検証の前払い (evidence の必須化) と報告しない条件を依頼文に入れるほど、判定のコストが下がる。
- **レビューの範囲は、最初の全量の後は増分にする** (規則の正本は [references/review-request.md](references/review-request.md) の「範囲の規則」)。どのモデル・範囲で走らせたかは記録の `model` / `scope` に必ず残し、粒度の違いを後から比較できるようにする。モデルの使い分けの運用ガイドは [記録 README の収束の目安](references/record-schema.md#生成サマリの読み方)。
- **却下ゲートは仮説である** ([references/rejection-gates.md](references/rejection-gates.md))。記録を取り、どのゲートが機能しているかを後から確かめる。
- **規範文書に実測値を書かない。** 件数・比率などの実測は記録 ([スキーマ](references/record-schema.md)) だけが持ち、必要なときにそこから数える。

## 手順

**手順 1 より前に `--gen-config` を処理する。** 指定されていれば、指摘の有無に関わらず雛形を生成して終了する (生成の内容と既存があるときの振る舞いは [references/config-schema.md](references/config-schema.md))。設定がまだ無い利用者は、レビューを走らせる前にこれを実行するので、手順 1 の「指摘が無ければ終了」より先に置かないと到達できない。

1. **入力の確認**: 入力の経路は 2 つ — 同じセッションの文脈から受け取るか、**別セッションのレビュー結果を YAML ファイルで受け取る** (様式の正本は [references/review-request.md](references/review-request.md))。どのスキルかは記録の `skill` に残す。
   - ファイル経由の場合、`head` が現在の HEAD と一致することを確かめてから判定に進む。`residual` の列は指摘として数えず、目を通して気になるものだけ記録の `notes` に写す。
   - **出力先には過去の回のファイルが残る。** 複数あるときは `head` が現在の HEAD と一致するものだけを対象にし、一致するものが無ければ指摘が無い場合と同じ扱いにする — 古い結果を現在の HEAD への指摘として判定すると、既に直した箇所を再び却下・採択することになる。
   - **上流が報告のみで走ったかを確かめる** (実行前後で HEAD と作業ツリーが不変)。適用済みなら判定に進まず、その旨を報告して次から報告のみで走らせるよう案内する。
   - 指摘が見当たらなければ、レビューを先に走らせるよう案内して終了する。**勝手にレビューを走らせない。**
2. **設定の読み込み**: `.claude/review-triage.yaml` を読む。読み込みは 3 値 ([references/config-schema.md](references/config-schema.md)) — 「読めない」なら判定を始めずにエラーを報告する。無ければ `--gen-config` を案内して終了する。
   - あわせて `.claude/akm-claude-plugins/review-triage/config.json` を読む ([references/project-config.md](references/project-config.md))。記録の置き場・関門の一覧・検査コマンドを決める。**無くても判定は進むが、関門の一覧が無いと免除条項は使えない** (突き合わせ先が無いまま関門名を書かせると、実在しない名前が検査されないまま通る)。
3. **判定**: 指摘ごとに [references/judgment-flow.md](references/judgment-flow.md) の図に従って決着させる。
   - 帰結の 4 項目 (D3 で書くもの) は**全件に書く** — D1・D2 で決着した指摘にも記録の材料として残す。
   - 評価 (E1・E2) の結果は、判定がどこで決まっても**すべて記録に載せる** (評価と判定の分離)。照合の仕方は [references/premise-check.md](references/premise-check.md)、ゲートの定義は [references/rejection-gates.md](references/rejection-gates.md)。
   - 境目が判断しづらいときは [references/gate-examples.md](references/gate-examples.md) の対になった例と突き合わせる。
4. **記録の追記**: 記録 YAML に 1 回分を追記する (様式・スキーマの正本は [references/record-schema.md](references/record-schema.md))。`model`・`scope`・`head` を必ず書く。`verdict_reason` には決着ノードの ID を書く。
5. **サマリの再生成**: 設定の `triage_summary_command` でサマリを再生成し、`triage_check_command` の検査が通ることを確かめる ([references/project-config.md](references/project-config.md))。**どちらも未設定なら、走らせていないことを報告に書く。**
6. **コミット**: 記録 YAML の追記を単独でコミットし、生成サマリを別のコミットにする (規範の正本は [記録 README のコミット節](references/record-schema.md#コミット))。**修正はコミットしない** (判断までが範囲)。
7. **報告**: 全件数・採択・保留・却下と、決着ノード別の内訳 (生成サマリの推移の表と同じ値) を出す。保留があれば [references/hold-presentation.md](references/hold-presentation.md) の形で提示する。採択があれば [review-triage-fix](../review-triage-fix/SKILL.md) を案内する。**勝手に呼ばない** — 直すかどうかは人間が決める。

## 原則

- **このスキルは修正しない。** 判断までが範囲。修正まで持たせると、判断が甘くても修正が進む。
- **記録を省かない。** 却下は「対処しなかった欠陥」を作る操作で、誤った却下を検証する経路は記録しかない (理由の正本は [記録 README](references/record-schema.md))。
- **sub-agent の結果は鵜呑みにせず、検証してから反映する。** 段 B の依頼の仕方は [references/premise-check.md](references/premise-check.md)。
- **対抗ペルソナは保留にだけ使う。** 保留になった指摘に限り、「対処すべきでない」と主張する側を立てて突き合わせてよい。全件に回すとコストが高く、もっともらしい反論で正しい指摘を却下する危険がある。
- **判定は実行のたびに揺れうる。** 記録に判断の材料 (帰結・評価の結果・決着ノード) を残すので、後から読めば同じ判定になるかを人間が確かめられる。

## このスキルが検出しないもの

- **指摘がコードの記述と合っているか** — 段 A で確かめるが、それは指摘の主張とコードの照合であって、コードの正しさの検証ではない。
- **指摘の深刻度が妥当か** — 上流が付けた属性 (`severity` / `confidence` / `verdict`) は記録の `attrs` にそのまま残す。無い属性を補完しない。
- **修正の内容が正しいか** — このスキルは修正しないので、修正のレビューは別に行う。
