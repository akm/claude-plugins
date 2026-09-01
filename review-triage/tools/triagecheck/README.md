# triagecheck

トリアージ記録 (YAML) のスキーマと、判定フローの正本を検査する。生成サマリ (`.md`) の書き出しも行う。

lappds の `tools/doccheck` から、review-triage に関わる 2 つの検査を切り出したもの。**検査の中身は変えていない** — 変えたのは対象のパスの決め方だけ。

## 何を検査するか

| 検査 | 内容 |
| --- | --- |
| `review-triage-record` | 必須キー・列挙値・参照の整合・未知のキー・行内コメント・`depends_on` の循環・生成サマリの鮮度 |
| `judgment-flow` | 判定フローの mermaid 図のノード ID 集合と、決定表の ID 集合が 1:1 で一致するか |

**記録は git 追跡でなくファイルシステムを走査する。** `git add` 前の最初の記録が検査されず素通りする穴を塞ぐため。

## 前提

**Go が必要。** `.tool-versions` に版を宣言している。プラグインはバイナリを配らないので、`go run` で都度実行する。

`go install` で入れたバイナリを使う運用にすると、プラグインを更新してもバイナリが古いまま残り、**新しいスキーマを検査せず素通りする**。`go run` なら、プラグインの更新がそのまま検査に反映される。

## 使い方

**`go run -C` でツールのモジュールに入って実行する。** `go run <ディレクトリ>` は呼び出し側のモジュールから解決しようとして失敗する。

```sh
go run -C <プラグインの展開先>/tools/triagecheck . \
  -record-dir <リポジトリ>/docs/review-triage \
  -judgment-flow <プラグインの展開先>/skills/review-triage/references/judgment-flow.md
```

`-judgment-flow` を省くと、環境変数 `CLAUDE_PLUGIN_ROOT` から解決する。

| フラグ | 既定 | 内容 |
| --- | --- | --- |
| `-record-dir` | `docs/review-triage/` | 記録の置き場。末尾のスラッシュは補う |
| `-judgment-flow` | `CLAUDE_PLUGIN_ROOT` から解決 | 判定フローの正本のパス |
| `-write-summary` | | 検査せず、記録から生成サマリ (`.md`) を書き出す |

判定フローのファイルが見つからないときは、その検査だけを何もせず通す (記録の検査は続ける)。

## Makefile に置く例

```makefile
# 展開先は版ごとに分かれる (cache/<マーケットプレイス>/<プラグイン>/<版>)。
# 版を固定して書くと更新のたびに直すことになるので、最新の 1 つを拾う。
PLUGIN_CACHE = $(HOME)/.claude/plugins/cache/akm-claude-plugins/review-triage
REVIEW_TRIAGE_ROOT ?= $(shell ls -d $(PLUGIN_CACHE)/*/ 2>/dev/null | sort -V | tail -1)

TRIAGECHECK = go run -C $(REVIEW_TRIAGE_ROOT)/tools/triagecheck . \
  -record-dir $(CURDIR)/docs/review-triage \
  -judgment-flow $(REVIEW_TRIAGE_ROOT)/skills/review-triage/references/judgment-flow.md

.PHONY: triage-check
triage-check: ## トリアージ記録を検査する
	@test -n "$(REVIEW_TRIAGE_ROOT)" || { echo "review-triage プラグインが見つかりません"; exit 1; }
	$(TRIAGECHECK)

.PHONY: triage-summary
triage-summary: ## トリアージ記録から生成サマリを書き出す
	@test -n "$(REVIEW_TRIAGE_ROOT)" || { echo "review-triage プラグインが見つかりません"; exit 1; }
	$(TRIAGECHECK) -write-summary
```

**展開先は環境によって違い、版ごとにディレクトリが分かれる。** 上の例は最新の版を拾うが、`claude plugin list` で確認して `REVIEW_TRIAGE_ROOT` を直接渡してもよい。

**空のまま実行すると `go run -C /tools/triagecheck` になり、分かりにくいエラーになる。** 上の `test -n` は、見つからないことをその場で言うためのもの。

## 呼び出し用のラッパースクリプトを作る (-install-wrapper)

**リポジトリの Makefile に手を入れたくないとき、または個人的にインストールした
プラグインをリポジトリのビルド定義に混ぜたくないときは、上の Makefile 例の
代わりにラッパースクリプトを生成させる。** `-record-dir` と (指定していれば)
`-judgment-flow` の値を、プラグインの展開先を都度解決するシェルスクリプトへ
焼き込んで書き出す。

```sh
# プラグインの展開先で一度だけ実行する。<path> はリポジトリ側の
# .gitignore 済みの置き場 (例: bin/review-triage-check) を指定する。
go run -C <プラグインの展開先>/tools/triagecheck . \
  -install-wrapper <path> \
  -record-dir <リポジトリ>/docs/review-triage
```

生成される `<path>` は実行権限つきのシェルスクリプトで、実行のたびに
プラグインキャッシュの最新版を解決してから `go run -C` する。**プラグインを
更新してもラッパー自体を作り直す必要はない** — 都度 `go run` する設計は
変わらないため。

以降は `<path>` を直接叩けば、`triage-check` / `triage-summary` 相当の
操作になる:

```sh
bin/review-triage-check                  # 検査する
bin/review-triage-check -write-summary   # 生成サマリを書き出す
```

**`-install-wrapper` は `go run -C <展開先>/tools/triagecheck . ...` の形で
呼ぶ必要がある。** 実行時のカレントディレクトリ (`.../<版>/tools/triagecheck`)
からプラグインキャッシュのルートを逆算するため、`-C` を経ずに別の場所から
呼ぶと、実体と食い違ったパスを書き出す代わりにエラーで止まる。

**`-judgment-flow` を明示しなかったときは、ラッパー内で `$root` (実行時に
解決した展開先) からの既定パスを使う。** プラグインのバージョンが上がって
展開先が変わっても、ラッパーを再生成せずに追随する。

## テスト

```sh
go test ./...
```

89 件 (部分テストを含む数。`go test -v ./... | grep -c 'PASS:'` で数える)。

## 依存

`gopkg.in/yaml.v3` の 1 つだけ。
