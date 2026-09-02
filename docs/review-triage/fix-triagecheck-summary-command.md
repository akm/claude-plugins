<!-- 生成物。手で編集しない。正本は fix-triagecheck-summary-command.yaml — `triagecheck -write-summary` で再生成する。 -->

# fix-triagecheck-summary-command のトリアージ記録

正本は [fix-triagecheck-summary-command.yaml](fix-triagecheck-summary-command.yaml)。読み方と収束の目安は [README](README.md)。

## 推移

| 回 | 日付 | スキル | model | scope | 全件 | 採択 | 保留 | 却下 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2026-09-02 | `code-review` | `opus-5` | full | 4 | 3 | 0 | 1 |
| 2 | 2026-09-02 | `code-review` | `opus-5` | incremental | 2 | 1 | 0 | 1 |
| 3 | 2026-09-03 | `code-review` | `opus-5` | incremental | 0 | 0 | 0 | 0 |
| 4 | 2026-09-03 | `code-review` | `opus-5` | full | 1 | 1 | 0 | 0 |

## 回 1: 2026-09-02 `code-review`

- HEAD `33c62b8` / model `opus-5` / scope full / level high

| # | 指摘 | 分類 / 被害者 | 帰結 (条件 / 何が / 気づけるか) | 検証 | ゲート | 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `review-triage/tools/triagecheck/wrapper.go:63` ラッパーが渡す "$0 -write-summary" が叩いた形とカレントに依存するため、 コミットされるサマリ 1 行目が起動方法ごとに変わり、生成直後のサマリが 別の叩き方の検査で落ちる | plugin-code / operator | ラッパーを導入した利用側で、生成と検査が違う叩き方で行われるとき (相対パスで生成し CI やエディタが絶対パスで検査する、PATH に置いた リンク経由で叩く、サブディレクトリから ../bin/rtc で叩く) / サマリの内容は同一なのに 1 行目だけが食い違い、triagecheck が 「サマリが正本と食い違っています」で exit 1 になる。再生成しても 叩き方が違えば毎回差分が出続け、2 人が別の形で叩くと git 上で サマリが往復する / CI が赤くなるので気づくが、原因は分かりにくい。案内される再生成 コマンドを実行しても直らないため、利用者は記録の中身を疑う | A: verified | — | **採択** — A2。全 4 ゲートを評価していずれも不発火。hypothetical は再現テストを 実際に書いて FAIL させたので不成立。developer-domain は対象が利用者の 環境で走るラッパーなので不成立。disproportionate-cost は対象 (wrapper.go 155 行) に対し既存の同型テストが 61-112 行で釣り合うため 不成立。already-visible は赤くなる関門を名前で挙げられない (TestInstallWrapperSummaryCommandPointsAtWrapper は生成も検査も ./bin/rtc の 1 形だけを使うため、この欠陥がある状態で緑になる) ので不成立 |
| 2 | `review-triage/tools/triagecheck/main.go:72` -install-wrapper と -summary-command を併記すると指定が黙って捨てられる。 -write-summary には同型のガードがあるのにこちらには無い | plugin-code / operator | 利用側が Makefile 経由の案内を焼き込むつもりで -install-wrapper と -summary-command を併記してラッパーを配るとき / コマンドは exit 0 で「生成: ...」と表示して成功したように見えるが、 生成されたラッパーに指定した文字列は一切入らず、案内は "$0 -write-summary" のままになる。利用者は意図と違う案内を 配ったことに気づかない / 気づかない。生成は成功して見え、生成物を開いて grep しない限り 指定が消えたことは分からない | A: verified | — | **採択** — A2。全 4 ゲートを評価していずれも不発火。hypothetical は既存の TestRunInstallWrapperRejectsUnusedFlags と同じ形で再現テストを書けるので 不成立 (実測でも exit 0 と grep 0 件を確認)。developer-domain は対象が 利用者に配るラッパーの生成なので不成立。disproportionate-cost は 既存ガードが 3 行 (条件 1 行 + return 2 行) で済んでおり不成立。 already-visible は赤くなる関門を挙げられない (併用を検査する TestRunInstallWrapperRejectsUnusedFlags は -write-summary だけを試す) ので不成立 |
| 3 | `review-triage/tools/triagecheck/main_test.go:788` TestSummaryCommandDefaultIsGeneric が可変グローバル summaryCommand を 読むため実行順に依存し、既定の回帰を検出しなくなる | test / developer | withRunGlobals を呼ばずに run を呼ぶテストが 1 つでも増え、 そのテストがこのテストより先に走るとき (このテスト自身は withRunGlobals を呼んでいない) / 既定値ではなく先行テストが残した汚染値を検査してしまう。 record.go の既定が Issue #36 の焼き込みに戻されても、汚染値が 無害な文字列であればこのテストは緑のまま通り、回帰を見逃す。 逆に汚染値が make を含めば偽陽性で落ちる / 気づかない。テストは緑のまま通るので、検出能力が失われたことは 回帰が実際に起きるまで分からない | A: verified | already-visible | **採択** — A1 (免除条項)。全 4 ゲートを評価し already-visible のみ発火したが、 免除条項の 2 条件がともに成立するため却下しない。 条件 1: 指摘は関門 (テスト) そのものが既定の回帰を検出しなくなることを 主張しており、検出能力の消失に当たる。 条件 2: この欠落を検出する関門が 3 層のいずれにも無い — 層 1 (make ターゲット) はこのリポジトリに Makefile が無いため 0 件、 層 2 (機械検査の項目) は review-triage-record と judgment-flow の 2 つで どちらも Go テストの順序依存を見ない、層 3 (テスト関数) には order/pollution/global/isolation を扱うテストが 1 件も無い (grep で確認)。 なお already-visible の発火は go test 自体が赤くなりうる点によるが、 それは汚染値が make を含む偽陽性の場合だけで、見逃しの側は緑のまま通る |
| 4 | `review-triage/tools/triagecheck/main.go:76` コマンド文字列の空判定に isBlankPath を再利用している。関数名と doc コメントが示す対象 (パス) と用途がずれている | plugin-code / operator | 将来 isBlankPath にパス特有の規則 (path.Clean、区切り文字の扱い、 拡張子の検査など) を足したとき / -summary-command が巻き添えで壊れ、パスとしては無効だが コマンド文字列としては正当な値が弾かれる、あるいはその逆が通る / そのときテストが赤くなるかは、足す規則しだいで分からない。 現時点では挙動は正しく、実害は出ていない | A: verified | hypothetical | **却下** — R3。全 4 ゲートを評価し hypothetical が発火した — 帰結が 「将来 isBlankPath にパス特有の規則を足したら」という仮定の条件に 依存しており、現在のコードでは再現するテストを書けない (現時点の挙動は空白・不可視の除去として正しく、実測でも空指定は errEmptySummaryCommand で正しく弾かれる)。再現には未着手の変更を 先に入れる必要があり、それはテストで作れない。 developer-domain・disproportionate-cost・already-visible は不発火。 D7 の被害者は developer — 対象は同梱ツールだが、帰結が生じるのは このリポジトリの保守者が isBlankPath を変更する場面であり、 その時点でコンパイルとテストを回す開発者が調べて対処できる。 製品の利用者に届く経路が無いため却下する |

### 修正計画

| 問題 | 原因 | 含む指摘 | 修正方法 | 順 | 状態 | 証拠 (SHA / URL) |
| --- | --- | --- | --- | --- | --- | --- |
| P1 | 案内の値を「経路の分岐より前で 1 回決める」規則を置かず、-install-wrapper の 経路では決めきらずに実行時の $0 に委ね、利用者の -summary-command は その経路で捨てた。パスの規則を 3 経路で揃えた設計を、案内という 1 つのパス値には当てていなかった | #1 #2 | run() で案内の値を経路の分岐より前に 1 回決める — -summary-command が 明示されればその値、明示が無く -install-wrapper があるときは filepath.Rel(-current-dir, ラッパーの絶対パス) + " -write-summary" (区切りを含まないときだけ ./ を前置。baseUsed を立てる)、明示も -current-dir も無いときはエラーで要求する (errSummaryCommandNeedsBase。 エラー文に -current-dir と -summary-command の両方の直し方を書く)。 installWrapper に案内を引数で渡し、シェルの単一引用符で焼き込む。 テンプレートの summary_command="$0 -write-summary" の行を削る。 既定値を定数 defaultSummaryCommand に切り出し、生成サマリ 1 行目を その定数と突き合わせるテストを置く。 TestInstallWrapperSummaryCommandPointsAtWrapper は検査側を絶対パスで 叩く形に変え、叩き方に依らないことを固定する。-install-wrapper と -summary-command の併記で値が焼き込まれることを固定するテストと、 基準無しの既定でエラーになるテストを足す。 README 56 行目と project-config.md 32 行目 (自動で渡す・設定は要らない) を焼き込みの記述に改める。 このリポジトリ自身のサマリ 1 行目は既定値のままなので変わらない (変わるのはラッパー経由で生成した利用側のサマリだけ)。 順序: P2 が使う定数をここで導入するので P1 が先 | 1 | 済 | `aef68ce` |
| P2 | 既定値の検査を、run() が書き換える可変のパッケージ変数を読む形で書き、 自身は withRunGlobals も呼ばなかった | #3 | TestSummaryCommandDefaultIsGeneric を、可変の summaryCommand ではなく P1 で切り出した定数 defaultSummaryCommand に対して検査する形に変える | 2 (P1 の後) | 済 | `2faba65` |

### 観察

このブランチの初回トリアージ。レビューは code-review high で報告のみ (--fix 無し) で走らせ、実行前後で HEAD (33c62b8) と作業ツリーが不変で あることを確認した。 プロジェクト設定 (.claude/akm-claude-plugins/review-triage/config.json) が 無いため、記録の置き場は既存の docs/review-triage/ に合わせ、 triage_summary_command / triage_check_command は未設定として扱った (サマリ再生成と検査の実行方法は報告に記す)。 指摘 1 と 2 は同じ原因 (-summary-command を経路ごとに扱った結果、 ラッパーの経路だけ規則から外れた) を共有する。README の 「パスの規則は 3 つの経路で同じ」という設計を -summary-command には 当てていないことが根にあり、review-triage-fix では 1 つの問題として 束ねられる見込み。 PR 説明で著者が挙げた懸念のうち、summaryCommand をパッケージ変数にした 判断は指摘 3 の順序依存という形で表面化した。ラッパーの $0 設計は 指摘 1 のとおり穴があった。シェルの引用符の扱いは "$summary_command" が 単一 argv に収まることを空白・二重引用符を含むパスで実測し、問題なし。 record_test.go の TestReviewTriageRecordSummaryStale の判定を 「食い違っています」への一致に変えた点は、文言への結合ではあるが summaryCommand が可変になった以上コマンド名では判定できず、代替が 無いため指摘として立てなかった。
修正前の追加調査 (関連箇所と影響範囲) で分かったこと。fix の設計に効くので ここに残す。
(1) 指摘 2 の修正には制約がある。ラッパーは -summary-command を必ず付けて 渡し、生成物の末尾に "$@" があるため、利用者は `./bin/w -install-wrapper ...` と叩ける。この経路では -summary-command と -install-wrapper が同時に立つ。 実測 (run() を直接呼ぶ probe) で、現状この組み合わせは通りラッパーが 生成されることを確認した。したがって「explicit の同時成立」だけで弾く 素朴なガードを足すと、この経路が壊れる。既存の併用ガードが -write-summary=false を通すために値も見ているのと同じ配慮が要る。 ただしラッパーが渡す値 ("./bin/w -write-summary") と既定値 ("triagecheck -write-summary") は一致しないため、値だけでは 「ラッパー由来」と「利用者の明示」を見分けられない。ラッパー由来を示す 印を持たせるか、ガードの条件を別の軸で立てる必要がある。
(2) 指摘 3 と同型のグローバル依存が他にもある。可変のパッケージ変数は reviewTriageDir / judgmentFlowPath / summaryCommand の 3 つで、run() が いずれも書き換える。record_test.go と judgment_flow_test.go は reviewTriageDir / judgmentFlowPath をパスの組み立てに広く使っており (record_test.go だけで 20 箇所超)、これらは既定値のままであることを 前提にしている。現時点では withRunGlobals を呼ばずに run() を呼ぶテストは 無いことを確認したので実害は出ていないが、指摘 3 の修正を 「このテストだけ const と比較する」で閉じると、同型の露出は残る。
(3) サマリ 1 行目を検査するテストが 1 つも無い (grep で確認)。 renderReviewTriageSummaryDoc は summaryCommand を 1 行目に埋めるが、 その内容を期待値と突き合わせるテストは存在しない。指摘 1 の修正で 1 行目の組み立て方を変えるなら、ここに関門を 1 つ置くのが自然。
(4) 指摘 1 を直すと生成サマリの 1 行目がもう一度変わる。この PR で 既に `make docs-review-triage-summary` から `triagecheck -write-summary` へ 1 度移行しており、修正は 2 度目の移行になる。このリポジトリの サマリ 3 件 + 今回追加の 1 件が対象。利用側にも同じ差分が出る。 0.4.0 を出す前に直せば移行は 1 度で済む。
(5) 修正時に追随が要る文書。-summary-command / triage_summary_command に 触れているのは review-triage/README.md、tools/triagecheck/README.md (特に $0 の挙動を説明した 56 行目)、skills/review-triage/SKILL.md、 references/project-config.md (32 行目がラッパーの自動受け渡しを前提に 「設定は要らない」と書いている)、references/record-schema.md。 指摘 1 で $0 の扱いを変えるなら、README 56 行目と project-config.md 32 行目は記述が実装と食い違う。
指摘 2 のガード条件の検討と、fix の設計 (人間と合意済み)。
(6) ガードは立てない。見分ける手立てを 3 つ潰した — 引数の順序は flag.Visit が辞書順で回るため情報が無い (実測)。値の内容はラッパーが 渡す値と既定値が一致しないため既存ガードの「値も見る」流儀を移植 できない。シェル側で "$@" を走査する案はフラグ解析のシェルへの再実装で 「列挙する検査は穴を再生産する」型。既存ガードが -write-summary を 弾いてよかったのは両立しえない要求だったからで、-summary-command は -install-wrapper と両立する (生成するラッパーにこの案内を持たせよ)。 正しくは捨てずに焼き込んで効かせること。これで指摘 1 と 2 は 「ラッパーに何を焼き込むか」の 1 つの決定に収束する。
(7) 焼き込む値の不変条件: コミットされる 1 行目に環境固有の値を 入れない。同じコミットを dev (/Users/...) と CI (/home/runner/...) が 検査するので、絶対パスを含むと同じコミットが場所によって赤くなる。 この 1 条件で「基準が無ければ絶対パス」と「実行時に script_dir から 組み立てる」の両案が落ちる。
(8) 値の決め方 (経路の分岐より前で 1 回)。-summary-command が明示 されればその値。明示が無く -install-wrapper があるときは filepath.Rel(-current-dir, ラッパーの絶対パス) + " -write-summary" (区切りを含まないときだけ ./ を前置。既存文書の `bin/<名前> -write-summary` の表記に合わせる)。このとき baseUsed を 立てないと errCurrentDirUnused が誤発火する。明示も -current-dir も 無いときはエラーで要求する — basename だけの案内は「PATH に居るはず」 という推測で、-record-dir で退けた型と同じ。新しい規則ではなく、 既存の「相対パスの基準は渡す側が決める」を案内という 1 つのパス値に 当てるだけ。互換性: -install-wrapper /abs/w -record-dir /abs/rec (基準無し・明示無し) は今まで通っていたのがエラーになる。直し方は -current-dir "$(pwd)" を足すか -summary-command を渡すかの 1 行で、 エラー文に両方を書く。0.4.0 未リリースのうちに揃える。
(9) ラッパーがリポジトリ外にあるとき (../elsewhere/bin/rtc) は そのまま通す。-record-dir の焼き込みも同じ配置 (script_dir からの ../) を既に受け入れており、ここだけ規則を分けると経路ごとに違う契約になる。
(10) 実装の細部。焼き込みの引用に %q は使えない — Go の規則であって シェルの二重引用符と食い違い、`make $(TARGET)` を焼き込むとシェルが 展開して make だけになる (実測)。単一引用符で囲み、中の ' は '\'' に する。既存の -record-dir の %q は同じ穴だが今回は触らず、ここに残す。 1 行目を検査するテストが 0 件なので、指摘 3 の修正で導入する既定値の 定数を使って 1 つ置く。TestInstallWrapperSummaryCommandPointsAtWrapper は 検査側を絶対パスで叩く形に変えれば、指摘 1 の再現がそのまま関門になる。
(11) 束ねる順は P1 (指摘 1・2) → P2 (指摘 3)。P2 が使う定数を P1 で 導入するため。

## 回 2: 2026-09-02 `code-review`

- HEAD `59d5e2d` / model `opus-5` / scope incremental

| # | 指摘 | 分類 / 被害者 | 帰結 (条件 / 何が / 気づけるか) | 検証 | ゲート | 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `review-triage/tools/triagecheck/main.go:281` -install-wrapper でラッパーを -current-dir の外に置くと、案内が "../" で 始まるリポジトリ外向きの相対パスになりそのままコミットされる。別マシンでは 兄弟ディレクトリが同じ位置に無く、案内が実在しないコマンドを指す。 「絶対パスを焼き込むと場所によって外れる」と同じ型の穴が残っている | plugin-code / operator | 利用者がラッパーをリポジトリの外 (兄弟ディレクトリなど) に置いて -current-dir をリポジトリのルートにして生成し、そのサマリを 別マシンで読むとき / サマリ 1 行目の案内 "../tools/rtc -write-summary" が、その配置を 持たないマシンでは叩けない。ただし鮮度検査は落ちない (焼き込んだ 文字列はマシンに依らず同じ) / 気づかない。検査は緑のまま、案内を試した人が「無い」と分かるだけ | A+B: wrong | — | **却下** — R1。段 A は verified — 引用どおり main.go:281-292 は ".." を含む結果を そのまま通し、プローブの再現も追認した。段 B (設計との照合) で根拠が 崩れる。指摘は「絶対パスを退けたのと同じ型の穴」と主張するが、退けた 理由は main.go:267-271 の直前の文が言うとおり「同じコミットが検査する 場所によって赤くなる」ことで、"../" の案内は焼き込んだ文字列として マシンに依らず同じなので検査は赤くならない — 同じ型ではない。 「案内が実在しないコマンドを指す」も、リポジトリ内の bin/rtc が README (tools/triagecheck/README.md:143-145) のとおり .gitignore 済みで 別マシンには存在しないのと同じで、リポジトリ外の配置に固有の欠陥では ない。加えてこの配置は 1 回目の notes (9) で「-record-dir が script_dir からの ../ で同じ配置を既に受け入れており、ここだけ規則を分けると 経路ごとに違う契約になる」として人間と合意のうえ受け入れた設計。 全 4 ゲートは評価して不発火 (E2 の結果は判定に使われないが残す)。 ただし main.go:270 の「リポジトリ相対でなければならない」は、目的 (検査が環境に依らない) より強く読める文言で、この指摘を誘った。 文言を目的に揃える価値はあるが欠陥ではないので、notes に残す |
| 2 | `review-triage/tools/triagecheck/wrapper.go:112` -summary-command は shellSingleQuote で保護されたが、同じテンプレート内の -record-dir と -judgment-flow は %q のままで、bash が $(...)・ バックティック・$VAR を実行時に展開する。同じ穴の一方だけを塞いだことで テンプレート内で規則が不揃い | plugin-code / operator | 記録の置き場か判定フローのパスに $、バックティック、$( を含む ディレクトリ名があるとき / 焼き込んだパスが実行時に展開されて別のパスになり、存在しない 置き場を検査して不在のエラーになるか、展開結果がたまたま実在すれば 別の場所を検査して緑を返す / 不在なら errRecordDirMissing で気づく。実在してしまう場合は気づかない | A: verified | — | **採択** — A2。段 A verified — wrapper.go:112 と 115 の引用どおり %q が残り、 プローブで docs/$(echo PWNED) が docs/PWNED に展開されることが示された。 全 4 ゲート不発火: hypothetical はレビュアが再現済み、developer-domain は 対象が利用者の環境で走るラッパー、disproportionate-cost は修正が shellSingleQuote への置き換え 2 箇所、already-visible は TestInstallWrapperQuotesSummaryCommandForShell が -summary-command だけを見ており赤くなる関門を挙げられない。増分の外から存在した穴だが、 1 回目の notes (10) で「同じ穴だが今回は触らず残す」と記したもので、 増分が規則を不揃いにした以上ここで直す |

### 修正計画

| 問題 | 原因 | 含む指摘 | 修正方法 | 順 | 状態 | 証拠 (SHA / URL) |
| --- | --- | --- | --- | --- | --- | --- |
| P1 | 1 回目の修正で、焼き込み値の引用の規則 (bash では単一引用符) を -summary-command にだけ当て、同じテンプレートの他の焼き込み値 (plugin_cache・-record-dir・明示の -judgment-flow) には当てなかった。 「同じ穴だが今回は触らない」と notes に残して先送りした結果、 テンプレート内で規則が不揃いになった | #2 | 生成時に決まった値を焼き込む 3 箇所 (wrapper.go:60 plugin_cache、 69 -record-dir、112 明示の -judgment-flow) を %q から %s + shellSingleQuote に変える。実行時に展開させる二重引用符 (-current-dir "$script_dir"、既定の -judgment-flow "$root/..."、 -C "$root/...") は残し、この区別を installWrapper のコメントに書く。 テンプレート引数の説明の番号を更新する。 二重引用符形を assert する 5 箇所 (wrapper_test.go:126・137・181、 main_test.go:667・670) を単一引用符形に直し、3 箇所の焼き込み値に $(...) を含めて展開されないことを固定するテストを置く。 レビュアが挙げなかった plugin_cache も同じ原因なので含める。 docs/solutions の生成物の写しは当時の記録なので触らない | 1 | 済 | `c471354` |

### 観察

2 回目 (増分 33c62b8..59d5e2d、別セッションのレビュー結果を tmp/review-code-review-opus-5-3rd.yaml で受領)。head は現在の HEAD と一致し、 レビュー前後で HEAD と作業ツリーが不変であることを確認した。 residual 8 件に目を通した — いずれも「特に見てほしい点」への確認結果 (switch の網羅・baseUsed の位置・ToSlash の順・shellSingleQuote の網羅・ テストが焼き直しでないこと・記録とサマリの整合・文書と実装の一致・ 互換性変更のエラー文) で、増分の設計を追認するもの。指摘として立てる ものは無い。 指摘 1 を R1 にした判断は、1 回目の notes (9) の設計判断 (人間と合意) を 前提にしている。設計判断そのものを見直すなら、それは記録の訂正ではなく 新しい決定として扱う。main.go:270 の「リポジトリ相対でなければならない」 の文言は目的 (検査が環境に依らない) に揃えた方が誤読を防げる — 指摘 2 の 修正と同じファイル群を触るので、そのときに文言だけ直すのが安い。
修正前の追加調査 (指摘 2 の関連箇所と影響範囲)。
(12) 同じ穴がもう 1 箇所ある。wrapper.go:60 の plugin_cache=%q も値を bash の二重引用符に入れており、指摘 2 が挙げた -record-dir (69) と -judgment-flow (112) と同じ規則違反。レビュアは挙げていないが原因が同じ なので同じ問題に含めて直す。値はプラグインキャッシュのルート ($HOME 配下) で、$ やバックティックを含む HOME は稀だが、規則を 3 箇所のうち 2 箇所 だけ直すと今回と同じ「不揃い」を再生産する。
(13) 機械的に %q を全部単一引用符にしてはいけない。テンプレートには 意図して実行時に展開させる二重引用符が 3 つある — -current-dir "$script_dir"、-judgment-flow "$root/skills/..." (省略時の既定行、 wrapper.go:108)、-C "$root/tools/triagecheck"。直すのは「生成時に決まった 値を焼き込む」3 箇所 (plugin_cache・-record-dir・明示の -judgment-flow) だけで、「実行時の変数を展開する」箇所は二重引用符のまま残す。 この区別を installWrapper のコメントに書く。
(14) 生成物の引用形に依存するテストの assert が 5 箇所あり、単一引用符に 変えると壊れる — wrapper_test.go:126 (-record-dir)、137 (plugin_cache)、 181 (明示の -judgment-flow)、main_test.go:667 (-record-dir)、670 (明示の -judgment-flow)。wrapper_test.go:142 と main_test.go:442・722 は既定の "$root/..." 行を見ており、こちらは変えない (展開させる側)。あわせて TestInstallWrapperQuotesSummaryCommandForShell と同じ形で、3 箇所の 焼き込み値に $(...) を含めて展開されないことを固定するテストを置く。
(15) docs/solutions/tooling-decisions/require-explicit-basis-for-relative-paths.md の 250-255 行に生成物の写し (二重引用符の形) がある。当時の記録なので 書き換えない (このリポジトリに frozen_paths の設定は無いが、docs/solutions は検討の記録として扱う)。README (tools/triagecheck) には生成物の引用形は 写っていないので追随は不要。
(16) 修正の形: テンプレートの %q を %s に変え、installWrapper 側で shellSingleQuote を通す。焼き込み値が 3 つになるので、テンプレートの 引数の説明 (wrapper.go:18-21) の番号も更新する。

## 回 3: 2026-09-03 `code-review`

- HEAD `f915ad5` / model `opus-5` / scope incremental

| # | 指摘 | 分類 / 被害者 | 帰結 (条件 / 何が / 気づけるか) | 検証 | ゲート | 判定 |
| --- | --- | --- | --- | --- | --- | --- |

### 観察

3 回目 (増分 59d5e2d..f915ad5、別セッションのレビュー結果を tmp/review-code-review-opus-5-4th.yaml で受領。レビューの実行日は 2026-09-02)。head は現在の HEAD と一致し、レビュー前後で HEAD と作業ツリーが 不変であることを確認した。指摘 0 件。 residual 8 件はすべて「特に見てほしい点」への確認結果で、2 回目の P1 の 設計を追認するもの — 焼き込む 3 値と展開させる 3 箇所の区別に取り違えは 無い、shellSingleQuote は ' ・空白・$(...)・改行を含む plugin_cache でも `ls -d "$plugin_cache"/*/` を壊さない (実測)、ラッパーを実行する 2 テストは Skip に落ちていない、TestInstallWrapperQuotesAllBakedValuesForShell は %q に戻すミューテーションと "$script_dir" を単一にするミューテーションの 両方で FAIL する (焼き直しではない)、$(echo Y) を含む置き場で生成物を 実行しても別の場所に化けない (レビュア側のプローブ)。 最後の 1 件 ($root が ls -d 由来で末尾 / を持ち "$root/tools/triagecheck" が 二重スラッシュになる) は POSIX 上同一パスで、増分より前から存在する 挙動。指摘として立てない。 これで増分レビューが 0 件に到達した。scope の規則どおり、最終確認として full を 1 回走らせるかは人間の判断 — 1 回目の full (4 件) 以降の変更は すべて増分でレビュー済み。

## 回 4: 2026-09-03 `code-review`

- HEAD `f085d30` / model `opus-5` / scope full

| # | 指摘 | 分類 / 被害者 | 帰結 (条件 / 何が / 気づけるか) | 検証 | ゲート | 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `review-triage/tools/triagecheck/README.md:251` README 末尾のテスト件数が 190 のまま。このブランチでテストを 17 件 増やしたのに数え直していない。README 自身が「増減させたら数え直す」と 定めている規則を破っている | doc-user / operator | README を読んだ人が件数を確かめようとして、書いてあるコマンドを 実行したとき / 190 と書かれているのに 207 が出る。README が「記憶で書くと実測と ずれる」と自ら警告している型のずれがその場で起きており、読み手は README の他の数字も疑う / 気づかない。件数を検査する関門は無い (Makefile も workflows も 無く、grep -c 'PASS' はこの行にしか現れない) | A: verified | — | **採択** — A2。段 A verified — README.md:251 の逐語は 190、HEAD で `go test -v ./... \| grep -c 'PASS:'` を実行して 207、main の同じ行も 190 で本ブランチが数え直していないことを追認した。全 4 ゲート不発火: hypothetical は実測で再現、developer-domain は対象が利用者向け README、 disproportionate-cost は修正が数字 1 つ、already-visible は件数を 検査する関門を挙げられない (レビュアの確認も同じ) |

### 修正計画

| 問題 | 原因 | 含む指摘 | 修正方法 | 順 | 状態 | 証拠 (SHA / URL) |
| --- | --- | --- | --- | --- | --- | --- |
| P1 | README にテストの実測値 (件数) を書き、テストを足すたびに増分の外の その行へ追随する運用にしていた。review-triage 自身の原則「規範文書に 実測値を書かない」に反しており、前のブランチで一度直した後も 同じ行が再び古くなった (2 度目) | #1 | 案 B (人間が決定)。README:251 の数字を消し、数え方のコマンド (`go test -v ./... \| grep -c 'PASS:'`) だけを残す — 「件数はこの コマンドで数える」の形にして、数字を書かないことでずれを発生源から 消す。案 A (207 に直す) は 3 度目を招くので採らない。 あわせて「増減させたら数え直す」の規則文も、数字を持たなくなるので削る | 1 | 済 | `769f929` |

### 観察

4 回目 (最終確認の full、main f6e777f..f085d30。別セッションのレビュー 結果を tmp/review-code-review-opus-5-5th.yaml で受領)。head は現在の HEAD と 一致し、レビュー前後で HEAD と作業ツリーが不変であることを確認した。 指摘 1 件は増分の継ぎ目で落ちたもの — 各増分はテストを足したがコード側 だけを見ており、README 末尾の件数 (増分の外) に追随しなかった。full を 最終確認に置く規則の狙いどおりの検出。 residual 4 件のうち、記録に残す価値があるもの: (a) ラッパー経由で追加引数 -record-dir を上書きすると、焼き込まれた -summary-command の案内は上書き前の置き場を前提にしたまま 1 行目に入る (実測)。README:173-176 は -record-dir 上書きの相対パス要件だけを書き、 案内には触れていない。上書きは明示的な高度用途で既定の置き場では正しく 動くため指摘にしないが、上書き時は -summary-command も併せて渡す旨を README に 1 行足す価値はある。 (b) -summary-command の空判定が -record-dir の必須判定より前に走り、 両方誤ると片方しか報告されない。missingPathProblems の「1 回で全件 報告する」方針とは揃わないが、どちらも 1 回直せば次に進める。 (c) main.go 冒頭のパッケージコメントの使い方の例に -summary-command が 無い。フラグの説明と README にあるので実害無し。 (d) リファクタ提案 1 件 — resolveInputs の案内決定 switch だけが baseUsed を 書き換え、errCurrentDirUnused の判定との依存が位置に暗黙に乗る。 壊れる入力は無い。
修正前の追加調査 (関連箇所と影響範囲)。
(17) 同じ欠陥が 2 度目である。前のブランチ fix-triagecheck-explicit-path-must-exist の記録 (1 回目の指摘 8) で「README のテスト件数が 89 のまま、実測 121」を 採択して直している。同じ行が、次のブランチでまた古くなった。数字を直す だけの修正は 1 ブランチしか持たない — テストを足すたびに README の末尾 (増分の外) へ追随する規則は、増分レビューでは検出されず full まで残る (今回もそうだった)。
(18) 文書に書かれた実測値で同型のものは他に無い。skills/ 配下の数字 (gate-examples の 12 行・40 行、verification の 2 箇所・4 箇所) は例文の 中身であって測った値ではない。他のツールの README にテスト件数の行は無い。 同型の再発源はこの 1 行だけ。
(19) 数え方は再現する。`go test -v ./... | grep -c 'PASS:'` を 2 回実行して いずれも 207 (部分テストを含む数、キャッシュや並列で揺れない)。
(20) review-triage のスキル自身が「規範文書に実測値を書かない。実測は記録だけが 持つ」と定めている (SKILL.md の前提知識)。README のこの行はその原則に 反する形で、原則が予言したとおり 2 度ずれた。修正の選択肢は 2 つ — 数字を 207 に直す (指摘の文面どおり。次にテストを足したとき 3 度目が起きる) か、数字を消して数え方のコマンドだけ残す (「件数はこのコマンドで数える」に する。数字が無ければずれない)。後者は README の書き方を変える設計判断なので fix では決めず、人間に返す。
