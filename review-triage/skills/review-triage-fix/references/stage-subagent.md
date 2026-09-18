# 段を sub-agent で走らせる

**このファイルが、`review-triage-fix` の段 (調査 / 立案 / 修正) を sub-agent で走らせるときの、走らせ方の決定・依頼文・呼び出し側の検証の正本。** 段の中身の規範 (調査の 2 方向・束ねる基準・順序・検証の観点 A〜F・機械検査の関門・1 問題 1 コミット) は [SKILL.md](../SKILL.md) の手順と references/ 配下の各文書が正本で、ここでは言い直さない — sub-agent で走らせても、その段の規範は変わらない。設定と引数の様式・優先順位・値の検査は [arguments.md](arguments.md) と [project-config.md](../../review-triage/references/project-config.md) の「`fix`」が正本。effort ごとの agent 定義 (`review-triage/agents/` の 6 ファイル) の中身は各定義が正本。

## なぜ段ごとに sub-agent に出せるか

- **段のあいだの受け渡しは記録 YAML だけ** (SKILL.md の前提知識)。段の結果は記録に書いてから次の段に渡すので、段をどこで走らせても、次の段は記録の状態だけから続けられる。
- **段ごとに model と effort を選べる。** 調査は広く読む段、修正はコミットまで行う段で、向く model と effort が違う。
- **既定はどの段もセッション内** (現行と同じ)。sub-agent に出すのは、設定か引数で選んだ段だけ。

モデルを指す語は [review-invocation.md](../../review-triage-loop/references/review-invocation.md) の「実効モデル」と同じ 2 つだけ — **指定** (設定 `fix.stages.<段>.model` / 引数 `--stage` に書かれた生の綴り) と **実効モデル** (指定を解決した後、呼び出し時に `model` に渡す値)。effort も同じ形で、**指定** (設定 `fix.stages.<段>.effort` / 引数の `:<effort>`) と **定義名** (指定から下の対応表で決めた agent 定義の名前) の 2 つで扱う。

## 段と手順・文書の対応

| 段 | 名前 (設定・引数) | sub-agent に含める手順 (番号の正本は [SKILL.md](../SKILL.md) の「手順」の直下にある段と手順の対応) | 段の規範 (references/) | 進める状態 |
| --- | --- | --- | --- | --- |
| 段 1 (調査) | `investigate` | 段 1 の手順のうち、**末尾の「立案者の選択」は含めない** — 人間に問うのはセッション側 | [grouping.md](grouping.md)・[investigation.md](investigation.md)・[doc-fix-form.md](doc-fix-form.md) | 覆われていない採択 → `plans` (`status: investigated`) か `plan_ref` |
| 段 2 (立案) | `plan` | 段 2 の手順 | [ordering.md](ordering.md)・[doc-fix-form.md](doc-fix-form.md) | `investigated` → `pending` か `awaiting-human` |
| 段 3 (修正) | `fix` | 段 3 の手順のうち、**報告と `doc-dag` の確認は含めない** — セッション側で行う | [committing.md](committing.md)・[verification.md](verification.md) | `pending` → `done` (`sha`) か `done-external` |

全段に共通して読ませる文書: [SKILL.md](../SKILL.md) (該当の手順と「原則」)、[record-schema.md](../../review-triage/references/record-schema.md) (記録の様式・状態・コミット節)、[project-config.md](../../review-triage/references/project-config.md) (設定のキーの意味)。

手順 1 (入力を読む・対象の解決・人間の答えの反映) はどの段にも含めず、セッション側で行う。

## 走らせ方の決定

段ごとに「セッション内か sub-agent か」を決め、sub-agent なら定義名と実効モデルを決める。値の優先順位 (引数 > 設定 > 既定) と値の検査の正本は [arguments.md](arguments.md) — ここは決定の結果を求める規則だけを持つ。

1. **セッション内か sub-agent か**: 引数 `--stage <段>` があれば、値が `session` ならセッション内、それ以外は sub-agent。無ければ設定 `fix.stages.<段>.subagent` (`true` なら sub-agent)。どちらにも無ければセッション内。
2. **定義名** (sub-agent のとき): effort の指定から下の「effort と定義名の対応」で決める。
3. **実効モデル** (sub-agent のとき): モデルの指定から下の「実効モデルの解決」で決める。
4. **回 N+1 以上の段 2 は、この決定を使わない** — 手順 4 の「立案者の選択」の答えが優先する。設定 `fix.stages.plan` と引数 `--stage plan` は使わず、指定があれば「使わなかった」と報告に書く。段 1 と段 3 の決定は回の番号に関わらず使う。

**決定は手順 1 で 3 段分をまとめて行い、報告 (手順 8) に書く。** 段の直前に決めると、後の段の設定や引数の誤りに前の段を走らせた後で気づく。

### effort と定義名の対応 (正本)

| effort の指定 | 定義名 (Agent ツールの `subagent_type` に渡す値) |
| --- | --- |
| 未設定 (空) — セッションの effort を継承する | `review-triage:fix-stage` |
| `low` | `review-triage:fix-stage-low` |
| `medium` | `review-triage:fix-stage-medium` |
| `high` | `review-triage:fix-stage-high` |
| `xhigh` | `review-triage:fix-stage-xhigh` |
| `max` | `review-triage:fix-stage-max` |

**この表はここにしか置かない。** 6 つの定義の違いは effort だけで、どの段を行うかは依頼文が指示し、モデルは呼び出し時に渡す。**報告の effort は、この表を逆に引いて、使った定義名から導く** — sub-agent は自分の effort を確かめられないので、自己申告を根拠にしない。

**限界**: 検査するのは指定が 5 値のいずれかであること (綴り) だけ。実効モデルがその effort に対応していない (受け付けない、または別の値として扱われる) ことは検出できない。

### 実効モデルの解決

Agent ツールの `model` は、モデルの別名 (`opus` / `sonnet` のような、版を含まない短い名前) の列挙で受ける。**列挙に無い綴りは、別名に置き換わるのではなく入力エラーになりうる。** 列挙は環境 (Claude Code の版) で決まるので、ここに写さない — 起動するセッションが Agent ツールの定義で確かめる。

| 指定 | 実効モデル |
| --- | --- |
| 未設定 (空) | 呼び出し元 (このセッションが動いているモデル) の別名 |
| 別名 (列挙にある綴り) | そのまま |
| 名前 (`claude-opus-5` のような、版を含む表記) | その名前のうち版を除いた部分が列挙にあれば、その別名 |
| 上のいずれにも解決できない | **止めて報告する** (指定と、それが引数と設定のどちらから来たかを添える)。推測で別名を選ばない |

**sub-agent には実効モデルを `model` として必ず明示して渡す。** [review-invocation.md](../../review-triage-loop/references/review-invocation.md) の「G0 より後の規則」と同じ理由 — 省略すると agent 定義・環境変数・親のモデルの順で解決され、呼び出し側が知らないモデルで走りうる。指定が未設定でも省略しない。

## 起動の形

- **Agent ツール**で、`subagent_type` に定義名、`model` に実効モデル、`prompt` に依頼文 (下の雛形を埋めたもの) を渡す。
- **`run_in_background: false` を明示して渡す。** 省略すると background で走り、結果を待たずに次に進んでしまう。結果が返り、検証が通るまで次の段に進まない。
- **段は逐次で、同時に走らせる sub-agent は 1 つ。** 記録 YAML を複数の sub-agent が同時に書くと、後から書いた側が先の結果を消す。
- **`isolation` は渡さない。** 段は呼び出し側と同じ作業ツリーで走る — 段 3 のコミットと記録の更新が呼び出し側の HEAD に載る必要があり、agent 定義が `isolation` を持たないのも同じ理由。
- **止まった sub-agent を再開しない** (追加の指示を送らない)。途中で止まった段は、記録の状態から新しい段の実行として始める — 再開に必要な情報は記録にあり、止まった sub-agent の文脈には無い (SKILL.md の前提知識「段のあいだの受け渡しは記録 YAML だけ」)。
- **sub-agent を起動する前に記録の写しを取らない。** 記録はブランチ単位で短命で、壊れれば呼び出し側の検証が止めて人間が直す。置き場を git の追跡内にしている利用者は git で戻せる。写しは置き場にファイルを増やし、検査の対象の扱いを決める必要を生むので、費用に見合わない。

## 依頼文

[review-request-template.md](../../review-triage/references/review-request-template.md) と同じ流儀 — **値は依頼文に書き、sub-agent に自分で別の値を選ばせない。報告の様式を定め、様式のとおり報告させる。禁止事項を節にして書く。** 雛形の `{{…}}` を埋め、埋め残しが無いことを確かめてから渡す。雛形の各節はそのまま写し、生成のたびに言い直さない。

### 運ぶもの

| 埋める箇所 | 値 |
| --- | --- |
| `{{stage_no}}` / `{{stage_name}}` / `{{steps}}` | 段の番号・名前と、その段の手順の範囲 (番号は [SKILL.md](../SKILL.md) の段と手順の対応から写す。「段と手順・文書の対応」の除外を引いた範囲) |
| `{{record_path}}` | 記録 YAML の絶対パス |
| `{{config_path}}` | 設定ファイル `.claude/akm-claude-plugins/review-triage/config.json` の絶対パス |
| `{{repo_dir}}` / `{{branch}}` | `git rev-parse --show-toplevel` / 現在のブランチ名 |
| `{{round}}` | 対象の回の番号 (記録の `runs` の要素数) |
| `{{targets}}` | 手順 1 で解決した対象 — 段 1: 覆われていない採択の回と `id`。段 2: `status: investigated` の問題の回と `problem_id`。段 3: `status: pending` の問題の回と `problem_id` |
| `{{consider_design_change}}` | 設計・仕様変更を含めて検討するか (`true` / `false`)。回 N+1 以上の段 2 なら `true`、それ以外 (段 1・3 と、回 N 以下の段 2) は `false`。**回 N+1 以上かどうかを sub-agent に計算させない** — N の決め方は呼び出し側にしか無い |
| `{{skill_md_path}}` / `{{record_schema_path}}` / `{{project_config_path}}` / `{{stage_references}}` | 読ませる文書の絶対パス (「段と手順・文書の対応」)。**プラグインの展開先の絶対パスで書く** — 依頼文を書くセッションは自分のスキルの置き場 (この SKILL.md を読んだディレクトリ) を知っている。相対パスは sub-agent の作業ディレクトリ (リポジトリ) から解決できない |
| `{{agent_name}}` | 定義名 (「effort と定義名の対応」)。sub-agent は自分の定義名を知らないので、報告に写させるために書く |
| `{{stage_prohibitions}}` | 下の「段ごとの禁止事項」の該当する段の項目 |

### 運ばないもの

- **指摘や計画の中身の言い直し。** 記録が正本で、sub-agent は記録から読む。依頼文に写すと、写し間違いが段の前提になる。
- **回数の閾値 N、対象の回が N+1 以上かどうか、立案者の選択の答え。** 段が受け取るのは「設計・仕様変更を含めて検討するか」の真偽だけ。

### 段ごとの禁止事項

全段に共通:

- `git push` しない。
- 記録に行内コメント (` #` 以降) を書かない — YAML は「半角スペース + `#`」以降をコメントとして取り除くので、値が警告なく切り詰められる。
- `status: awaiting-human` の問題に触らない — 人間に返した判断を代わりに決めない。
- 指示された段の前後の段に進まない。
- sub-agent を入れ子で立てた場合、その結果も検証してから使う。
- 人間に問えない。人間の判断が要るものは、記録の該当の問題を `status: awaiting-human` にして `options` に案とトレードオフを書き、報告に残す。

段 1・段 2:

- 記録 YAML と生成サマリ以外のファイルを作らない・変えない・消さない。
- コミットしない。**記録のコミットも含む** — 置き場が git の追跡内でも、コミットは呼び出し側が検証の後に行う。
- 段 1 は `approach` と `order` を書かない (`investigated` の条件の正本は record-schema.md の `plans[]` の表)。段 2 は記録の外のファイルを変えない。

段 3:

- 対象 (`{{targets}}`) 以外の問題を直さない。
- 1 問題 1 コミット。各コミットの前に、設定の `gates` の関門と観点 A〜F を通す (正本は committing.md・verification.md)。
- コミットしたら記録の該当の問題を `status: done`・`sha` に更新する。区切り (全問題の完了、または中断) で、記録の置き場が git の追跡内なら記録とサマリをコミットする (分け方の正本は record-schema.md のコミット節)。**未コミットの変更を残して返らない。**
- 手順 8 (報告) と手順 9 (`doc-dag`) を行わない。

### 雛形

````markdown
# review-triage-fix の段の依頼: 段 {{stage_no}} ({{stage_name}}) — {{branch}} の回 {{round}}

この依頼文は、スキル `review-triage-fix` (採択したレビュー指摘を原因で束ねて直すスキル) が、段を sub-agent で走らせるために書いたものである。受け取った側はこの依頼文と「読む文書」だけを読んで、指示された段を 1 つ実行し、結果を記録 YAML に書き、「報告の様式」のとおり報告する。依頼文の作り方と呼び出し側の検証の正本は `review-triage-fix` の `references/stage-subagent.md` — 受け取った側が読む必要は無い。

## 値 — この値で動く。自分で別の値を選ばない

- 段: 段 {{stage_no}} ({{stage_name}}) — SKILL.md の手順 {{steps}} の範囲。前後の段に進まない。
- 記録 YAML: `{{record_path}}`
- 設定ファイル: `{{config_path}}` — `record_dir`・`gates`・`triage_check_command`・`triage_summary_command` はここから読む
- リポジトリ: `{{repo_dir}}` / ブランチ: `{{branch}}`
- 対象の回: {{round}} (記録の `runs` の要素数)。新しく書く `plans` はこの回に置く。
- 対象: {{targets}}
- 設計・仕様変更を含めて検討する: {{consider_design_change}} — この値をそのまま使う。回の番号から自分で判断しない。
- 定義名: `{{agent_name}}` — 報告にこの値をそのまま写す。

## 読む文書 (絶対パス)

- `{{skill_md_path}}` — 手順 {{steps}} と「原則」。他の手順は行わない。
- `{{record_schema_path}}` — 記録の様式・状態・コミット節
- `{{project_config_path}}` — 設定のキーの意味
- 段の規範: {{stage_references}}

指摘と計画の中身は記録 YAML が正本で、この依頼文には写していない。記録から読む。

## 禁止事項

{{stage_prohibitions}}

## 報告の様式

最後に、次の 8 項目をこの順で、地の文ではなく箇条書きで返す。**項目を足さず、省かない。** 分からない項目は「不明」と書き、推測で埋めない。

- 定義名: (上の「値」の定義名をそのまま)
- 動いているモデル: (自分がどのモデルで動いているか。環境が与える情報から書く。推測しない)
- 段: {{stage_name}}
- 書いた問題: (回と `problem_id` と、進めた状態。段 1 は書いた `plan_ref` も)
- コミット: (`problem_id` → 短縮 SHA の列。コミットしない段は「無し」)
- 通した関門と結果: (走らせたコマンドごとの成否。`triage_check_command` の成否を含む。走らせていないものは「走らせていない」)
- できなかったこと: (段の中で行えなかったこと、`status: awaiting-human` にした問題、途中で止まった理由。無ければ「無し」)
- HEAD と作業ツリー: (段の前後の HEAD の短縮 SHA。記録の置き場の外に変更が無いこと。段 3 は未コミットの変更が無いこと)
````

## 呼び出し側の検証 (段が返ったら必ず)

**sub-agent の報告は要約であって、判定の材料は記録 YAML と git の状態である。結果は検証してから反映する** ([premise-check.md](../../review-triage/references/premise-check.md) と同じ原則 — 上流の結果を追認せず、自分で確かめる)。

段を起動する前に控えるもの: HEAD の SHA と `git status --porcelain` の出力。**段 3 の前は、作業ツリーに未コミットの変更が無いことを確かめる** (あれば始めずに報告する) — 段の後の「未コミットの変更が無い」の確認が、段の前からあった変更と段が残した変更を区別できないため。

全段に共通:

1. **報告が様式のとおりか** — 項目の欠け・様式に無い項目・「不明」の項目。
2. **記録 YAML を読み直し、設定の `triage_check_command` を走らせる** (未設定なら走らせていないことを報告に書く — [project-config.md](../../review-triage/references/project-config.md))。
3. **モデルの突き合わせ** — 報告の「動いているモデル」が実効モデルの指すモデルと同じか。別名は版を含まないので、申告の名前のうち版を除いた部分と比べる。**食い違えば人間に報告する** ([review-request.md](../../review-triage/references/review-request.md) の「値で明記し、報告させる」の規則と同じ — sub-agent の側で変わった値を、依頼どおりの値として報告しないため)。
4. **effort** — 報告には、使った定義名から導いた effort を書く (「effort と定義名の対応」を逆に引く)。

段ごとに確かめること:

| 段 | 状態の遷移 | HEAD と作業ツリー |
| --- | --- | --- |
| 段 1 | `{{targets}}` の採択がすべて `plans` (`status: investigated`) か `plan_ref` で覆われた。`investigated` に `approach`・`order` が無い (検査が報告する) | HEAD が段の前と同じ。`git status --porcelain` の差分が記録の置き場 (`record_dir`) 配下だけ |
| 段 2 | `{{targets}}` の `investigated` がすべて `pending` か `awaiting-human` に進んだ。`awaiting-human` に `options` がある (検査が報告する)。`investigated` のまま残った問題があれば、理由が報告の「できなかったこと」にある | 同上 |
| 段 3 | `{{targets}}` の `pending` が `done` (`sha`) か `done-external` に進んだ。**`done` の各 `sha` が HEAD の履歴にある** (`git merge-base --is-ancestor <sha> HEAD`)。`pending` のまま残った問題があれば、理由が報告にある (区切りでの中断は失敗ではない — 次の再開が段 3 から続ける) | **作業ツリーに未コミットの変更が無い** (`git status --porcelain` が空)。**最終 HEAD で設定の `gates` を 1 度走らせる** — sub-agent がコミットごとに通したと報告していても、呼び出し側は最終状態を自分で確かめる。`gates` が未設定なら、走らせていないことを報告に書く |

検証が通ったら次の段に進む (段 1 の後は、手順 4 の末尾の「立案者の選択」をセッション側で行ってから)。

## 失敗時

次のどれかなら、**止めて、検査の出力と sub-agent の報告を一緒に人間に報告する。** 再試行しない。セッション内に切り替えて続けない。止まった sub-agent を再開しない。

- 記録の検査 (`triage_check_command`) が失敗した
- 記録を書かずに返った (状態が進んでいない、`{{targets}}` が覆われていない)
- 段の外に触った — 段 1・2 で記録の置き場の外が変わった、HEAD が変わった。段 3 で対象外の問題を直した、未コミットの変更が残った
- 報告が様式に合わない、動いているモデルが実効モデルと食い違う
- 段 3 の `done` の `sha` が HEAD の履歴に無い、最終 HEAD で `gates` が失敗した

**再試行しない理由**: 同じ依頼文で走らせても同じ結果になりやすく、壊れた記録の上に 2 度目の結果が重なる。**セッション内に切り替えない理由**: 走らせ方は手順 1 で決めて報告するもので、失敗を契機に呼び出し側が変えると、報告した走らせ方と実態が食い違う。壊れた記録は人間が直す (置き場が git の追跡内なら git で戻せる)。

## 記録の置き場が git の追跡内のとき

- **段 1・2 の後**: 検証が通ったら、**呼び出し側が**記録とサマリをコミットする (分け方の正本は [record-schema.md](../../review-triage/references/record-schema.md#コミット) のコミット節)。sub-agent はコミットしない (禁止事項)。
- **段 3**: 現行の手順 7 どおり、区切りで sub-agent が記録とサマリをコミットする。呼び出し側は未コミットの変更が無いことを確かめる (上の表)。
- 追跡外 (既定の置き場) では、どの段でも記録のコミットは無い。

## 段の実行情報は報告に書き、記録には残さない

手順 8 の報告に、段ごとに「セッション内か sub-agent か」を書き、sub-agent なら定義名・effort (定義名から導く)・実効モデル (と sub-agent が申告したモデル) を書く。**記録 YAML には書かない** — 記録の様式を変えないため。セッションが切れた後の再開では走らせ方の出所が失われるが、再開は記録の状態から新しい段として始め、回 N+1 以上なら立案者を再度尋ねる (SKILL.md の手順 1) ので、判断には影響しない。
