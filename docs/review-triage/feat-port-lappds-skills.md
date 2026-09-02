<!-- 生成物。手で編集しない。正本は feat-port-lappds-skills.yaml — `triagecheck -write-summary` で再生成する。 -->

# feat-port-lappds-skills のトリアージ記録

正本は [feat-port-lappds-skills.yaml](feat-port-lappds-skills.yaml)。読み方と収束の目安は [README](README.md)。

## 推移

| 回 | 日付 | スキル | model | scope | 全件 | 採択 | 保留 | 却下 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2026-09-01 | `code-review` | `opus-5` | full | 2 | 2 | 0 | 0 |
| 2 | 2026-09-01 | `code-review` | `opus-5` | incremental | 1 | 1 | 0 | 0 |
| 3 | 2026-09-01 | `code-review` | `opus-5` | incremental | 0 | 0 | 0 | 0 |

## 回 1: 2026-09-01 `code-review`

- HEAD `bf16d7d` / model `opus-5` / scope full

| # | 指摘 | 分類 / 被害者 | 帰結 (条件 / 何が / 気づけるか) | 検証 | ゲート | 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `review-triage/tools/triagecheck/record.go:133` -record-dir に "." / "./rec" / "rec//" のようにパスの正規化で形が変わる値を渡すと、 記録の検査が全件スキップされ「問題は見つかりませんでした」と exit 0 で緑になる。 main.go:44 の正規化が生パスに "/" を足すだけなのに対し、listReviewTriageFiles は path.Join でパスを clean するため、record.go:133 の HasPrefix が一致しなくなる。 | plugin-code / operator | 利用者が triagecheck を -record-dir に "." や "./docs/rt" や末尾二重スラッシュを 含む値で呼ぶとき。Makefile やスクリプトで相対パスを組み立てると自然に発生する。 / スキーマ検査・サマリ鮮度・孤児サマリの 3 つがすべて黙って外れ、 検査が 1 件も走らないまま exit 0 で緑になる。壊れた記録が緑のまま通る。 / 気づかない。exit 0 かつ「問題は見つかりませんでした（検査: review-triage-record, judgment-flow）」と検査名まで表示されるため、走ったように見える。 既存のテストはこの経路を踏まない (下記 premise_check)。 | A: verified | — | **採択** — A2。段 A で逐語照合と再現の両方を確認 — main.go:44 の `reviewTriageDir = strings.TrimSuffix(filepath.ToSlash(*recordDir), "/") + "/"` と record.go:133 の `if !strings.HasPrefix(f, reviewTriageDir) \|\| path.Base(f) == "README.md" {` は指摘のとおり実在する (指摘の行番号 377 は 133 だったが、premise-check.md の 「行番号のずれだけで wrong にしない」に従い位置を補正して verified)。 ビルドしたバイナリで再現: 同一内容に対し "-record-dir rec4" は 2 件を報告し exit=1、 "-record-dir ./rec4" と "-record-dir rec4//" は「問題は見つかりませんでした」exit=0。 機序も go run のプローブで確認 (norm(".")="./" に対し path.Join(".","x.yaml")="x.yaml" で HasPrefix=false)。E2 は 4 ゲートすべてを評価し、発火 0 件: 仮定の条件 = テストで再現できる (フラグを渡すテストを書けば足りる) ため非該当。 開発者の領域 = 帰結の条件が環境の異常ではなく通常の引数、かつ対象は利用者が 実行するツールなので非該当。不相応なコスト = 修正は正規化の 1 行 (path.Clean 相当) で、対象より小さいので非該当。既に見える = 赤くなる関門を挙げられない (go test の 44 個の Test 関数を完全一致で列挙したが、run() / flag / os.Args に 触れるテストは 1 つも無く、テストはすべて既定の reviewTriageDir を直接使う)。 発火 0 件のため D6 で採択。 |
| 2 | `review-triage/tools/triagecheck/record.go:460` plans を書かないまま次の回が追記された過去の回では、verdict: adopted の指摘が どの plans にも plan_ref にも載っていなくても検査が何も報告しない。 被覆の検査が `len(run.Plans) > 0` で条件づけられており、「fix 前だから免除」が 回が進んだ後も解除されないため。 | plugin-code / operator | ある回で採択したまま review-triage-fix を走らせず (plans を書かず)、 次の回のトリアージを追記したとき。増分レビューを繰り返す運用で自然に起きる。 / 過去の回の採択が、どの修正計画にも載らないまま検査から漏れる。 review-triage-fix も「最後の回」の findings しか見ないため、 スキルからも検査からも見えなくなり、採択が黙って消える。 / 気づかない。triagecheck は exit 0 で緑、生成サマリにも警告は出ない。 人間が過去の回を遡って目視しない限り分からない。 | A+B: verified | — | **採択** — A2。段 A: record.go:457-460 のコメントと `if len(run.Plans) > 0 {` は指摘の 逐語のとおり実在。段 B (仕組みの不在を前提にする指摘なので実施): review-triage-fix/SKILL.md:21 の「**最後の回**の `findings` から `verdict: adopted` の指摘を取る。」と :22 の「**全回の `plans` を 1 パスで見て**」を逐語で確認し、 スキル側の再開の網が plans のエントリだけを見ることを裏取りした。 2 回分の記録を作って再現: 回 1 に plans 無しの adopted、回 2 に plans ありの 構成で exit=0 (緑)。対照として回 2 の finding_ids を空にすると 「findings id 1: 採択が修正計画に載っていません」が出て exit=1 になり、 回 1 側だけが検査されない非対称を確認した。 E2 は 4 ゲートすべてを評価し、発火 0 件: 仮定の条件 = テストで再現できる (TestReviewTriageRecordAdoptedCoverage と同じ形で 2 回分の記録を組めばよい)。 開発者の領域 = 環境の異常ではなく通常の運用手順、対象も利用者が使うツール。 不相応なコスト = 修正は条件の見直し (最新の回だけ免除する) で対象より小さい。 既に見える = 赤くなる関門を挙げられない (TestReviewTriageRecordAdoptedCoverage は 実在するが、plans を持つ回の被覆しか見ておらず、この経路は検出しない)。 発火 0 件のため D6 で採択。 |

### 修正計画

| 問題 | 原因 | 含む指摘 | 修正方法 | 順 | 状態 | 証拠 (SHA / URL) |
| --- | --- | --- | --- | --- | --- | --- |
| P1 | 照合の両辺を別々の方法で正規化していた。置き場は生の文字列に "/" を足すだけ、 一覧側は path.Join が clean する、という食い違いのまま HasPrefix で前置を比べた。 | #1 | 文字列の接頭辞ではなく path.Dir どうしの比較 (inReviewTriageDir) に変え、 両辺を path.Clean に通す。別ディレクトリ (rec-old/) を拾わないという元の目的も、 下位ディレクトリを対象外にする形で同時に満たす。表記の揺れを固定する回帰テストを足す。 | 1 | 済 | `a6a820b` |
| P2 | 「fix 前だから免除する」という条件を、回の位置ではなく plans の有無だけで書いた。 後続の回が追記された時点でその回はもう fix 前ではないのに、免除が解けなかった。 | #2 | 免除を「plans がまだ無い最後の回」に限る。同じ原因で書かれていた規範も直す — record-schema.md の被覆の規則と、review-triage-fix の手順 1 (全回の findings から 未被覆の採択を取る) とその frontmatter。回帰テストを足す。 P1 と原因が違うので束ねない (同じファイルだが束ねる根拠は原因)。 | 2 | 済 | `06a4706` |

### 観察

入力は別セッションの 2 ファイル。tmp/review-code-review-opus-5.yaml は head 39f24b1 (origin/main への rebase 前) で現在の HEAD bf16d7d と一致しなかったが、 review-triage/ 配下は rebase 前後で差分ゼロ (rebase が触ったのは README.md / marketplace.json / .gitignore のみ) で指摘対象のコードが不変であることを確認したため、 利用者の判断で合流させた。この回はその full レビューの 2 件。 上流は報告のみで実行済み (両ファイルの evidence に HEAD と作業ツリーが不変である旨の 記載あり)。residual の 4 行にも目を通した — うち「root に .gitignore が無い」は その後 tmp/ を含む .gitignore が追加されて解消済み。

## 回 2: 2026-09-01 `code-review`

- HEAD `bf16d7d` / model `opus-5` / scope incremental

| # | 指摘 | 分類 / 被害者 | 帰結 (条件 / 何が / 気づけるか) | 検証 | ゲート | 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `README.md:154` 構成ツリーの直後に残る注記「(commit-squash・doc-dag・work-log-gh-comment も skill 型で、構成は mermaid-preview と同じです。)」が、コンフリクト解消の取り残し。 統合後のツリーは 3 つとも明示的に列挙しているため注記は不要で、 内容も誤り (mermaid-preview と構成が同じではない)。 | doc-user / operator | 利用者がリポジトリの README を読んで各プラグインの構成を把握しようとするとき。 / ツリーに 3 つとも列挙されているのに「ツリーに無いものの補足」の形の注記が残り、 記述が二重になる。さらに「構成は mermaid-preview と同じ」が事実に反するため、 work-log-gh-comment に template.html があると誤解しうる。 / 気づかない。文書の内部矛盾を検出する関門は無く、読者が実ディレクトリと 突き合わせて初めて分かる。 | A: verified | — | **採択** — A2。段 A で確認 — README.md:154 に当該の注記が実在し、同ファイルの 134-145 行で commit-squash / doc-dag / work-log-gh-comment が明示的に 列挙されていることを確認した。「構成は mermaid-preview と同じ」の誤りも 実ディレクトリで裏取り: mermaid-preview/skills/mermaid-preview/ は SKILL.md と template.html、work-log-gh-comment/skills/work-log-gh-comment/ は SKILL.md・evals・references、commit-squash と doc-dag は SKILL.md・references で、 いずれも一致しない。E2 は 4 ゲートすべてを評価し、発火 0 件: 仮定の条件 = 文書の記述の誤りで、再現の必要が無い (現物を読めば確認できる)。 開発者の領域 = 対象は利用者が読む README で非該当。 不相応なコスト = 修正は 1 行の削除で、対象より小さい。 既に見える = 赤くなる関門を挙げられない (Makefile は evals の 1 つだけで 文書の検査は無く、go test の 44 個にも README の内容を見るものは無い)。 発火 0 件のため D6 で採択。 |

### 修正計画

| 問題 | 原因 | 含む指摘 | 修正方法 | 順 | 状態 | 証拠 (SHA / URL) |
| --- | --- | --- | --- | --- | --- | --- |
| P1 | rebase のコンフリクト解消でツリーに 3 つを明示的に列挙したとき、その直後にある 「ツリーに載せなかったものの補足」を読み直さなかった。補足の前提が消えたのに 補足だけが残った。 | #1 | ツリーが 3 つとも列挙している以上その注記は不要なので削除する。 回 1 の P1・P2 とは原因も対象も違うので束ねない。 | 1 | 済 | `af374c4` |

### 観察

tmp/review-code-review-opus-5-2nd.yaml (head bf16d7d、現在の HEAD と一致) の 1 件。 この指摘は rebase のコンフリクト解消の取り残しを正しく捉えている。 residual の 4 行にも目を通した — プラグインの並び順が 3 箇所で不一致という観察は、 レビュア自身が「rebase 前から表とツリーの順序は異なっており、統合で新たに生じた 食い違いではない」「順序が違って壊れるものは無い」と結論しており、指摘として 数えない扱いに同意する。

## 回 3: 2026-09-01 `code-review`

- HEAD `79b8490` / model `opus-5` / scope incremental

| # | 指摘 | 分類 / 被害者 | 帰結 (条件 / 何が / 気づけるか) | 検証 | ゲート | 判定 |
| --- | --- | --- | --- | --- | --- | --- |

### 観察

修正 (回 1 の P1・P2、回 2 の P1) の後の再レビュー。範囲は bf16d7d..79b8490 の増分。 指摘 0 件。上流は報告のみで実行済み (HEAD・作業ツリーとも不変を確認)。 出力先は review-triage/tools/triagecheck/tmp/ だった (レビュア側の cwd が Go ツールの ディレクトリだったため)。依頼様式が指す tmp/ はリポジトリ直下なので、次からは 置き場を明示する。 residual の 4 行に目を通した。うち 2 つは設定 (.claude/review-triage.yaml) への観察で、 レビュア自身が実害なしと結論している — 追認した: 現在の追跡ファイル 103 件で 種類不明は 0 件。ただし 1 件 (.claude/review-triage.yaml 自身) が受け皿の shared に 落ちており、設定の分類を後で見直す余地がある (判定への影響は無い。audience は developer で、この回に指摘は無い)。 残る 2 つ (finding_ids の回内一意による束ね方、README の 84 件の数え方) も レビュアが解消経路・数え方の併記を確認済みで、いずれも欠陥ではない。
