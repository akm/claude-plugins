# ループの開始と 1 回のレビュー (RG0・RL1)

**このファイルが、`review-loop` が `review-triage-loop` の G0 と L1 を差し替えるノード RG0・RL1 の条件と手順の SSOT。** ノードと遷移の SSOT は [stops.md](stops.md) の図で、差し替えないノード (G2・G3・L2・J2・J4・J5・J7・J8・J9・F1・S2〜S6) は [loop-flow.md](../../review-triage-loop/references/loop-flow.md) が SSOT。ここでは言い直さない。

## 決定表

| ID | 種類 | 条件・内容 | 報告に書くもの |
| --- | --- | --- | --- |
| RG0 | 手順 | 新しいループなら、条件を決め ([arguments.md](arguments.md)。`--base` を省いたときの `review.base` の決め方もそこが SSOT)、下の「開始の前提」を確認し、下の「ループのディレクトリを作る」を行う。再入 (通知・`--resume`) なら、条件を `loop.yaml` から読み、[reentry.md](reentry.md) の「再入の手順」で遷移先を決める | 新しいループのときだけ、決まった条件をループの開始前に出す。出す条件は、ワーカーのモデルの指定と effort・権限モードと許可の一覧・サンドボックスで書き込みを許す場所と接続を許すドメイン (`loop.yaml` の `worker.sandbox_allow_write`・`worker.sandbox_allowed_domains`。空なら「無し」と書き、接続を許すホストには利用者の設定の `WebFetch(domain:…)` の許可も加わり、ワーカーが起動時に表示することを添える。SSOT は [worker.md](worker.md) の「ネットワーク」)・レビュースキルとそのオプション・上限・構造の関門 k・収束後の全量レビューをループの中で行うか (`review.full_review`)・全量の起点のブランチ (`review.base` と、`--base` による指定か `origin/HEAD` による既定か。由来は `loop.yaml` に残らないので、書くのはこの開始の報告だけ)・`review-triage-fix` に渡す回数の閾値 N とフェーズごとの実行方法 (書き方は [loop-flow.md](../../review-triage-loop/references/loop-flow.md) の G0 の行と同じ。ただしモデルは実効モデルではなくワーカーへの指定を書き、実効モデルは各回の完了のフラグファイルで分かることを添える)・待機の期限と停滞の秒数・`review_loop` の設定の警告 (あれば)・ループの id とループのディレクトリの絶対パスである |
| RL1 | 手順 | 下の「1 回のレビュー」の (a) 依頼文を書く → (b) 完了のフラグファイルが現れるまで待機する → (c) 突き合わせる。再入の手順からは (b) か (c) に入る | いま何回目か (この起動で数えた回数) と上限、記録の回番号、識別子。収束後の全量の回なら、上限に数えないことと、この起動で行った収束後の全量の回の数 |

## 開始の前提

新しいループを始める前に、次をすべて確認する。**満たさなければ始めず、何を片付ければよいかを報告する。**

1. **作業ツリーが clean である** (`git status --porcelain` が空)。満たさなければ、変更をコミットするか退避してから起動し直すよう案内する。
2. **ループのディレクトリの親 (`review_loop.dir`) が git に無視されている** (`git check-ignore -q <dir>`)。満たさなければ、`.gitignore` に足してコミットしてから起動し直すよう案内する (スキルは `.gitignore` を変えない)。
3. **記録 YAML が読める** (ディレクトリは設定の `record_dir`、ファイルは `<ブランチ名>.yaml`)。無ければ新規として扱う。あるのに読めなければ、読めない理由を報告する。
4. **同じブランチに `ended` でないループが無い。** `find <review_loop.dir> -mindepth 2 -maxdepth 2 -name loop.yaml` で探し (zsh の glob は一致が無いと失敗するので使わない)、`branch` が現在のブランチで `state` が `ended` でないものがあれば、そのディレクトリを添えて `--resume` か `--end` を案内する。**読めない `loop.yaml` があれば、中断して知らせる。** 新規に寄せると、同じブランチに終了していないループが 2 つでき、同じ記録の同じ回番号の依頼文が 2 つできる。

## ループのディレクトリを作る

1. **ループ id を決める**: `<YYYYMMDD>-<hhmm>-<ブランチ名>`。ブランチ名の整え方は [review-request の SKILL.md](../../review-request/SKILL.md) の手順 3 の表の「ブランチ名」の行と同じ。
2. **ループのディレクトリ `<review_loop.dir>/<ループ id>/` を作る。** 既にあれば (同じ分に 2 度始めた) 作らずに報告して終了する。
3. **`loop.yaml` を書く** (様式の SSOT は [loop-files.md](loop-files.md) の「`loop.yaml`」)。`repo_dir` は作業ツリーのルートの実体パス、`state` は `active`。一時名 `.loop.yaml.tmp` に書いてから `mv` で改名する。

## 呼ぶスキル

**このスキルが呼ぶ 3 つのスキル (RL1 の手順 a の `review-request`・L2 の `review-triage`・F1 の `review-triage-fix`) は、回ごとに Skill ツールで呼ぶ。** 規則と理由の SSOT は [review-invocation.md](../../review-triage-loop/references/review-invocation.md) の「別のプロセスでレビューした結果の取り込み」の「呼ぶスキル」。

## 1 回のレビュー (RL1)

### (a) 依頼文を書く

1. **作業ツリーが clean でなければ RA3。**
2. **記録が読めなければ RA3。**
3. **増分の基点が HEAD の祖先でなければ RA3。** 増分の回 (記録に回があり、`loop.yaml` の `full_review_next` が偽) なら、最後の回の `head` について `git merge-base --is-ancestor <head> HEAD` を確認する (reset や squash で履歴から外れていると、増分の範囲が成り立たない)。全量の回 (記録に回が無いか、`full_review_next` が真) なら確認しない。全量の基点は merge-base で、常に HEAD の祖先である。
4. **Skill ツールで [review-request](../../review-request/SKILL.md) を呼ぶ** (回ごとに。上の「呼ぶスキル」): `review-request <review.skill> <worker.model> <review.args> --dir <ループのディレクトリ>` (値は `loop.yaml`。ループのディレクトリはリポジトリのルートからの相対パス。`ce-code-review` は effort を受け取らないので `<review.args>` を渡さない)。**全量の回 (上の 3 と同じ区別) なら `--base <review.base>` を、`full_review_next` が真なら `--full-review` も渡す** (真にするのは `--resume --full-review` と、[stops.md](stops.md) の RJ0・RJ1 の「はい」)。増分の回に `--base` を渡さないのは、`review-request` が増分の回の `--base` を無視し、無視したことを報告に書くため (毎回の報告に意味の無い注記が出る)。**範囲と基点は `review-request` の手順 2 に従う** (全量は `--base` のブランチとの merge-base、増分は直前の回の `head`)。`review-triage-loop` の [review-invocation.md](../../review-triage-loop/references/review-invocation.md) の「範囲」(merge-base で基点を決める規則) は使わない。依頼文を書くのは `review-request` なので、基点の規則を 2 か所に持たないため。
5. **`review-request` が「同じ識別子の依頼文か結果が既にある」で書かなかったら** (RA1 の後に同じ分のうちに依頼文を作り直した)、分が変わるまで待機してからやり直す。Bash ツールで `sleep 60` をバックグラウンドで起動し (`run_in_background: true`)、`description` を「review-loop <ループ id>: 識別子の衝突を避けるため分が変わるまで待機する。通知を受けたら review-loop の再入の手順へ」にして、ターンを終える。再入の手順は、取り込むフラグファイルもフラグファイルの無い依頼文も無いので G2 に進み、L1 でここに戻る。識別子の成分に秒を足すことはしない (成分を変えると `review-request` の表の全欄を再確認することになる)。
6. **それ以外の理由で `review-request` が依頼文を書かなかったら RA3** (報告には `review-request` が報告した理由を書く)。
7. **書けたら、回数を数える。記録に回がある状態で全量の依頼文 (`full_review_next` が真で書いた依頼文) を書いたら、この起動で行った収束後の全量の回の数を 1 つ増やし、数えた回数は増やさない** (収束後の全量の回は上限に数えない。停止する理由の SSOT は [review-request.md](../../review-triage/references/review-request.md) の「収束後の全量レビューと、その要否」)。**それ以外 (増分の回と、記録に回が無いときの 1 回目の全量の回) は、この起動で数えた回数を 1 つ増やす** (J5 が見る回数。数えるのはここだけ)。**`full_review_next` が真なら偽にする** (`loop.yaml` を一時名に書いてから改名する)。依頼文の絶対パスと識別子を控える。
8. **1 回目の最初の依頼文なら** (ループのディレクトリに `worker.yaml` が無い)、ワーカーを起動するか、起動を人間に案内する ([guide-template.md](guide-template.md) の「起動の手順」)。

### (b) 完了のフラグファイルが現れるまで待機する

[reentry.md](reentry.md) の「待機」のとおり、待機スクリプトをバックグラウンドで起動して**ターンを終える**。フラグファイルが現れると通知で次のターンが始まり、再入の手順で (c) に入る。

### (c) 突き合わせる

完了のフラグファイルと結果を依頼文と比べる。**上から順に確認し、最初に通らなかったところで RA1。** 報告に書くものの SSOT は [stops.md](stops.md) の決定表の RA1 の行。

1. **フラグファイルが読める**: YAML として読め、`id` が識別子と一致する。
2. **ワーカーのバージョン**: フラグファイルの `worker_version` が 0.14.0 以降 (`.` で区切った数を、先頭から数として比べる)。キーが無いか 0.14.0 より古ければ RA1 (報告に書く項目の SSOT は [stops.md](stops.md) の「RA1 の報告の、原因ごとの項目」の表の「ワーカーのバージョン」の行)。`unknown` なら停止しない (このキーを書くのは 0.14.0 以降のワーカーだけ。レビュアの実行を起動しなかった回は 4 で停止する)。**3 の必須キーより先に見る。** 0.13.0 のワーカーのフラグファイルは 0.14.0 で足したキーを持たないので、必須キーを先に見ると、ワーカーが古いことではなくキーが足りないことを報告してしまう。
3. **フラグファイルの様式**: 必須キー ([loop-files.md](loop-files.md) の「`delivered-<識別子>.yaml`」の表) があり、`status` が `ok` か `failed`。
4. **`status` が `ok`**: `failed` なら RA1。
5. **HEAD と作業ツリー**: フラグファイルの `head_before` と `head_after` が依頼文の `head` と同じコミットを指し、`tree_clean_after` が `true`。**元の作業ツリーでも** `git rev-parse --short HEAD` が依頼文の `head` と同じで、`git status --porcelain` が空であることを確認する (フラグファイルを信じるだけにしない)。
6. **effort とモデル**: フラグファイルの `effort` が `loop.yaml` の `worker.effort` と、`model.specified` が `worker.model` と等しい (人間が案内と違う値でワーカーを起動していない)。`model.effective` が `unknown` でなければ、実効モデルの名前が指定に一致する。比べ方は [stage-subagent.md](../../review-triage-fix/references/stage-subagent.md) の「実効モデルの解決」と同じで、名前 (`opus-5` のような版を含む表記) から版を除いた部分が指定の別名 (`opus`) と等しければ一致とする。指定が版を含む名前なら、`claude-` を除いた名前どうしで比べる。`unknown` なら比べない (記録の `notes` に「不明」と残る)。
7. **skill を呼んだ**: `skill_called` が `false` なら RA1。skill を呼ばずに読んだ結果を、依頼どおりの結果として記録しない (規則の SSOT は [review-request.md](../../review-triage/references/review-request.md) の「呼ぶ skill・effort・モデル — 値で明記し、報告させる」)。`unknown` なら停止しない (`notes` に「不明」と残る)。
8. **拒否されたツールの呼び出しが無い**: `permission_denials.count` が 1 以上なら RA1。調べられなかった範囲の指摘が無い結果を、採択 0 の収束として記録に入れないため。ワーカーのフックが拒否した呼び出し (フラグファイルの `worker_hook_denials`) は、この件数に含まれない (判別の方法と、RA1 にしない理由の SSOT は [worker.md](worker.md) の「`/tmp` を含むコマンドを拒否するフック」)。報告に書くもの (原因ごとの項目と直し方) の SSOT は [stops.md](stops.md) の RA1 の行。`unknown` なら停止しない (`notes` に「不明」と残る)。
9. **権限モードの指定**: フラグファイルの `permission_mode.specified` が `loop.yaml` の `worker.permission_mode` と等しい (人間が案内と違う権限モードでワーカーを起動していない)。`unknown` なら停止しない (`notes` に「不明」と残る)。実効の権限モード (`permission_mode.effective`) が指定と違う回は、ワーカーが `failed` にするので 4 で停止する (SSOT は [worker.md](worker.md) の「ログの読み方」)。
10. **サンドボックスが拒否した確認が無い**: `sandbox_blocked.count` が 1 以上なら RA1。理由は 8 と同じ。8 とは別に確認する (サンドボックスが拒否した確認が `permission_denials` に数えられないことと、件数が `unknown` になる条件の SSOT は [worker.md](worker.md) の「ログの読み方」)。レビュー対象のコミットの行を表示しただけと確認した呼び出し (フラグファイルの `repo_text_displayed`) は、この件数に含まれない (判別の方法と、数えない理由の SSOT は [worker.md](worker.md) の「リポジトリの行を表示しただけの結果」)。報告に書くもの (拒否されたコマンドとパスかホスト、直し方) の SSOT は [stops.md](stops.md) の RA1 の行。`unknown` なら停止しない。そのときは `permission_denials` も `unknown` になっていて、`notes` に「不明」と残る。
11. **結果**: 結果ファイル (`<ループのディレクトリ>/review-<識別子>.yaml`) を照合する。照合することと理由の SSOT は [review-invocation.md](../../review-triage-loop/references/review-invocation.md) の「別のプロセスでレビューした結果の取り込み」の「結果のファイルの照合」で、通らなければ RA1。

すべて通れば L2 に進む。

## L2 で `review-triage` に渡すもの

L2 で `review-triage` に渡すもの (記録のキーの出所の読み替え方・`run_id` の写し方) と、`review-triage` が返った後に確認することの SSOT は、[review-invocation.md](../../review-triage-loop/references/review-invocation.md) の「別のプロセスでレビューした結果の取り込み」の「`review-triage` に渡すもの」。そこで「その経路のレビュー不成立」と書くものは、このスキルでは RA1。このスキルの値は次のとおり。

- **「レビュアの実行を確認した材料」は、完了のフラグファイル。**
- **記録の `model` は、フラグファイルの `model.effective`。** `unknown` なら `loop.yaml` の `worker.model` (記録の `model` は空にできない)。
- **記録の `notes` に書く 1 行は、下の「`notes` の固定書式」。**

## `notes` の固定書式

```
review-loop: <ループ id> / worker_model: <指定> (実効: <名前 or 不明>) / worker_effort: <値> / permission_mode: <指定 or 不明> (実効: <値 or 不明>) / skill_called: <true / false / 不明> / permission_denials: <件数 or 不明> / review_minutes: <分>
```

- 値は完了のフラグファイルから採る。`unknown` は「不明」と書く。`permission_mode` はフラグファイルの `permission_mode.specified` と `permission_mode.effective`。`review_minutes` はフラグファイルの `started` から `finished` までの分 (小数第 1 位まで)。
- **記録のスキーマは変えない。** このループ (ワーカーの経路) で回した回であることと、ワーカーのモデルと effort は、この 1 行だけに残る。sub-agent の経路 (`review-triage-loop`) の回と収束を比べるときは、この行の有無で経路を分ける。
