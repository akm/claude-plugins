# 周回の開始と 1 回のレビュー (RG0・RL1)

**このファイルが、`review-loop` が `review-triage-loop` の G0 と L1 を差し替えるノード RG0・RL1 の条件と手順の正本。** ノードと遷移の正本は [stops.md](stops.md) の図で、差し替えないノード (G2・G3・L2・J2・J4・J5・J7・J8・J9・F1・S2〜S6) は [loop-flow.md](../../review-triage-loop/references/loop-flow.md) が正本 — ここでは言い直さない。

## 決定表

| ID | 種類 | 条件・内容 | 報告に書くもの |
| --- | --- | --- | --- |
| RG0 | 手順 | 新しい周回なら、条件を決め ([arguments.md](arguments.md))、下の「開始の前提」を確かめ、下の「置き場を作る」を行う。再入 (通知・`--resume`) なら、条件を `loop.yaml` から読み、[reentry.md](reentry.md) の「再入の手順」で行き先を決める | 新しい周回のときだけ、決まった条件を周回の開始前に出す — ワーカーのモデルの指定と effort・権限モードと許可の一覧・レビュースキルとそのオプション・上限・構造の関門 k・`review-triage-fix` に渡す回数の閾値 N と段ごとの走らせ方 (書き方は [loop-flow.md](../../review-triage-loop/references/loop-flow.md) の G0 の行と同じ。ただしモデルは実効モデルではなくワーカーへの指定を書き、実効モデルは各回の完了の印で分かることを添える)・待機の期限と停滞の秒数・`review_loop` の設定の警告 (あれば)・周回の id と置き場の絶対パス |
| RL1 | 手順 | 下の「1 回のレビュー」の (a) 依頼文を書く → (b) 完了の印を待つ → (c) 突き合わせる。再入の手順からは (b) か (c) に入る | いま何回目か (この起動で数えた回数) と上限、記録の回番号、識別子 |

## 開始の前提

新しい周回を始める前に、次をすべて確かめる。**満たさなければ始めず、何を片付ければよいかを報告する。**

1. **作業ツリーが clean である** (`git status --porcelain` が空)。満たさなければ、変更をコミットするか退避してから起動し直すよう案内する。
2. **周回の置き場の親 (`review_loop.dir`) が git に無視されている** (`git check-ignore -q <dir>`)。満たさなければ、`.gitignore` に足してコミットしてから起動し直すよう案内する (スキルは `.gitignore` を変えない)。
3. **記録 YAML が読める** (置き場は設定の `record_dir`、ファイルは `<ブランチ名>.yaml`)。無ければ新規として扱う。あるのに読めなければ、読めない理由を報告する。
4. **同じブランチに `ended` でない周回が無い。** `find <review_loop.dir> -mindepth 2 -maxdepth 2 -name loop.yaml` で探し (zsh の glob は一致が無いと失敗するので使わない)、`branch` が現在のブランチで `state` が `ended` でないものがあれば、その置き場を添えて `--resume` か `--end` を案内する。**読めない `loop.yaml` があれば、止めて知らせる** — 新規に寄せると、同じブランチに終わっていない周回が 2 つでき、同じ記録の同じ回番号の依頼文が 2 つできる。

## 置き場を作る

1. **周回 id を決める**: `<YYYYMMDD>-<hhmm>-<ブランチ名>`。ブランチ名の整え方は [review-request の SKILL.md](../../review-request/SKILL.md) の手順 3 の表の「ブランチ名」の行と同じ。
2. **置き場 `<review_loop.dir>/<周回 id>/` を作る。** 既にあれば (同じ分に 2 度始めた) 作らずに報告して終わる。
3. **`loop.yaml` を書く** (様式の正本は [loop-files.md](loop-files.md) の「`loop.yaml`」)。`repo_dir` は作業ツリーのルートの実体パス、`state` は `active`。一時名 `.loop.yaml.tmp` に書いてから `mv` で改名する。

## 1 回のレビュー (RL1)

### (a) 依頼文を書く

1. **作業ツリーが clean でなければ RA3。**
2. **記録が読めなければ RA3。**
3. **増分の基点が HEAD の祖先でなければ RA3。** 記録に回があれば、最後の回の `head` について `git merge-base --is-ancestor <head> HEAD` を確かめる (reset や squash で履歴から外れていると、増分の範囲が成り立たない)。記録に回が無ければ (全量) 確かめない。
4. **[review-request](../../review-request/SKILL.md) を呼ぶ**: `review-request <review.skill> <worker.model> <review.args> --dir <置き場>` (値は `loop.yaml`。置き場はリポジトリのルートからの相対パス。`ce-code-review` は effort を受け取らないので `<review.args>` を渡さない)。**範囲と基点は `review-request` の手順 2 に従う** (全量は分岐元、増分は直前の回の `head`)。`review-triage-loop` の [review-invocation.md](../../review-triage-loop/references/review-invocation.md) の「範囲」(merge-base で基点を決める規則) は使わない — 依頼文を書くのは `review-request` なので、基点の規則を 2 か所に持たないため。
5. **`review-request` が「同じ識別子の依頼文か結果が既にある」で書かなかったら** (RA1 の後に同じ分のうちに書き直した)、分が変わるのを待ってからやり直す。Bash ツールで `sleep 60` をバックグラウンドで起動し (`run_in_background: true`)、`description` を「review-loop <周回 id>: 識別子の衝突を避けるため分が変わるまで待つ。通知を受けたら review-loop の再入の手順へ」にして、ターンを終える。再入の手順は、取り込む印も印の無い依頼文も無いので G2 に進み、L1 でここに戻る。識別子の成分に秒を足すことはしない (成分を変えると `review-request` の表の全欄を確かめ直すことになる)。
6. **それ以外の理由で `review-request` が依頼文を書かなかったら RA3** (報告には `review-request` が報告した理由を書く)。
7. **書けたら、この起動で数えた回数を 1 つ増やす** (J5 が見る回数。数えるのはここだけ)。依頼文の絶対パスと識別子を控える。
8. **回 1 の最初の依頼文なら** (置き場に `worker.yaml` が無い)、ワーカーの起動を人間に案内する ([guide-template.md](guide-template.md))。

### (b) 完了の印を待つ

[reentry.md](reentry.md) の「待機」のとおり、待機スクリプトをバックグラウンドで起動して**ターンを終える**。印が現れると通知で次のターンが始まり、再入の手順で (c) に入る。

### (c) 突き合わせる

完了の印と結果を依頼文と比べる。**上から順に確かめ、最初に通らなかったところで RA1** — 報告にはその項目と、食い違った両方の値を書く。

1. **印が読める**: YAML として読め、必須キー ([loop-files.md](loop-files.md) の「`delivered-<識別子>.yaml`」の表) があり、`id` が識別子と一致し、`status` が `ok` か `failed`。
2. **`status` が `ok`**: `failed` なら、印の `error` を報告に書く。
3. **HEAD と作業ツリー**: 印の `head_before` と `head_after` が依頼文の `head` と同じコミットを指し、`tree_clean_after` が `true`。**作業側でも** `git rev-parse --short HEAD` が依頼文の `head` と同じで、`git status --porcelain` が空であることを確かめる (印を信じるだけにしない)。
4. **effort とモデル**: 印の `effort` が `loop.yaml` の `worker.effort` と、`model.specified` が `worker.model` と等しい (人間が案内と違う値でワーカーを起動していない)。`model.effective` が `unknown` でなければ、実効モデルの名前が指定に一致する — 比べ方は [stage-subagent.md](../../review-triage-fix/references/stage-subagent.md) の「実効モデルの解決」と同じで、名前 (`opus-5` のような版を含む表記) から版を除いた部分が指定の別名 (`opus`) と等しければ一致とする。指定が版を含む名前なら、`claude-` を除いた名前どうしで比べる。`unknown` なら比べない (記録の `notes` に「不明」と残る)。
5. **skill を呼んだ**: `skill_called` が `false` なら RA1 — skill を呼ばずに読んだ結果を、依頼どおりの結果として記録しない (規則の正本は [review-request.md](../../review-triage/references/review-request.md) の「呼ぶ skill・effort・モデル — 値で明記し、報告させる」)。`unknown` なら止めない (`notes` に「不明」と残る)。
6. **拒否されたツールの呼び出しが無い**: `permission_denials.count` が 1 以上なら RA1 — 調べられなかった範囲の指摘が欠けた結果を、採択 0 の収束として記録に入れないため。報告に書くもの (拒否の理由と、許可の一覧で直せるか) の正本は [stops.md](stops.md) の RA1 の行。`unknown` なら止めない (`notes` に「不明」と残る)。
7. **結果**: 結果ファイル (`<置き場>/review-<識別子>.yaml`) が YAML として読め、`findings` キーがあり、`run_id` が識別子と一致する。

すべて通れば L2 に進む。

## L2 で `review-triage` に渡すもの

**L2 では、回ごとに Skill ツールで `review-triage` を呼ぶ。指摘が 0 件の回も同じ。** 前の回で読んだ `review-triage` の手順を、このスキルが自分で実行して記録に書かない — 記録への回の追記・residual を自己採択にするかの判断・生成サマリの再生成と検査は `review-triage` が行う。このスキルが代わりに行うと、`review-triage` の手順で確かめないまま判断が記録に入る (通し確認で、指摘が 0 件の回に作業側がこれを行った)。F1 の `review-triage-fix` も同じく、回ごとに Skill ツールで呼ぶ。

`review-triage` を呼ぶときは、結果ファイルのパスと、次の値を渡す。

- **記録のキー (`model` / `skill` / `level` / `scope`) の値の出所は、[review-invocation.md](../../review-triage-loop/references/review-invocation.md) の「記録のキーの出所」の、そのレビュースキル (`code-review` か `ce-code-review`) の列のとおり。ただし「sub-agent の報告」を「完了の印」と読み替える。** この周回は新しい経路ではないので、出所の表を増やさない (表を複数の文書に持つと、同じ場所への採択が続いた実測がある)。`model` は印の `model.effective` で、`unknown` なら `loop.yaml` の `worker.model` (記録の `model` は空にできない)。
- **記録の `notes` に書く 1 行** (下の「`notes` の固定書式」)。
- **`run_id` は結果 YAML の値をそのまま写すこと** (規則の正本は [review-request.md](../../review-triage/references/review-request.md) の「出力様式」の節)。

**`review-triage` が結果の様式を差し戻したら RA1。** `review-triage` が返ったら、**記録の末尾の回の `run_id` が識別子と一致することを確かめ、一致しなければ RA1** (報告に「`review-triage` が `run_id` を写さなかった」と書く)。一致しないまま進むと、再入の手順が同じ結果を 2 度取り込む。

## `notes` の固定書式

```
review-loop: <周回 id> / worker_model: <指定> (実効: <名前 or 不明>) / worker_effort: <値> / skill_called: <true / false / 不明> / permission_denials: <件数 or 不明> / review_minutes: <分>
```

- 値は完了の印から採る。`unknown` は「不明」と書く。`review_minutes` は印の `started` から `finished` までの分 (小数第 1 位まで)。
- **記録のスキーマは変えない。** この周回 (ワーカーの経路) で回した回であることと、ワーカーのモデルと effort は、この 1 行だけに残る。sub-agent の経路 (`review-triage-loop`) の回と収束を比べるときは、この行の有無で経路を分ける。
