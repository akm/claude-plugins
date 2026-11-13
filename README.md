# akm-claude-plugins

akm のチーム共有 Claude Code プラグイン集 (マーケットプレイス) です。

## 収録プラグイン

| プラグイン | 説明 |
| --- | --- |
| [commit-rules-guard](commit-rules-guard/README.md) | コミットルールを想起させ、動機の混在を気づかせる (セッション開始時・作業着手時・計画作成時・`git commit` 直前) |
| [pr-teeth](pr-teeth/README.md) | レビュー依頼が来ている GitHub の PR を巡回し、レビュー範囲に照らして噛み砕いた解説を HTML で作る (出力言語は設定可能) |
| [doc-dag](doc-dag/README.md) | 文書群の依存と重複を調べ、mermaid 図で示して DAG になるよう修正する (mermaid-preview と併用) |
| [mermaid-preview](mermaid-preview/README.md) | mermaid の図を含む HTML を生成してブラウザで見せる (他のスキルからの図の提示にも使う) |
| [commit-squash](commit-squash/README.md) | 未 push のコミットを、同じ関心事のものどうしでまとめて数を減らす |
| [review-triage](review-triage/README.md) | レビューの依頼文を生成し、レビュー指摘を採択 / 保留 / 却下 / 下限未満に選り分け、採択したものを原因で束ねて直し、レビューから修正までを上限回数まで回す。レビューは同じセッションの sub-agent か、人間が端末で起動するワーカー (モデルと effort を人間が選ぶ) か、スキル `review-rally` を実行するセッションが起動する別のセッション (Claude のデスクトップアプリで使う。モデルと effort は、`review-rally` を実行するセッションのモデルと effort 以下の範囲で人間が選ぶ) で実行する。スキル `review-triage-fix` の各フェーズ (調査 / 立案 / 修正) は sub-agent で実行できる (Go が必要) |
| [work-log-gh-comment](work-log-gh-comment/README.md) | 実行したコマンドと出力を、機密を伏せたうえで省略せずに GitHub の Issue / PR へ記録する |
| [wording-guard](wording-guard/README.md) | これから外へ出す日本語の文章の不自然な表現を、リポジトリの規約が定める原則に照らして見つけ、種類ごとに広げて直す。言い換えを決めた語を用語ファイルに記録し、textlint と hook で検出できる |
| [session-handoff](session-handoff/README.md) | セッションの引き継ぎ文を GitHub の PR / Issue のコメントかローカルファイルに書き出し、新しいセッションでそれを読んで再開する (モデルの使い分けや、compact せずに作業を継続したいときに使う) |
| [doc-structured](doc-structured/README.md) | アプリケーションの文書を、列挙できる事実は YAML に書いて人が読む Markdown を生成し、生成物と参照を検査する構成で書く (作成中) |
| [issue-practice](issue-practice/README.md) | GitHub の Issue の使い方 (リリースの計画と記録・管理 Issue と作業 Issue の分担・PR との対応・クローズ条件・後で行う作業の切り出し) に従って Issue を扱う (作成中) |

## 使い方

### user レベルでインストールする

自分の環境全体で使う場合は、以下のコマンドでインストールします。

```bash
claude plugin marketplace add akm/claude-plugins
claude plugin install commit-rules-guard
```

`marketplace add` はリポジトリを clone するため、`owner/repo` 形式か clone 可能な URL (`https://….git` / `git@…`) を指定します。GitHub のブラウザ用の閲覧 URL (`https://github.com/…/blob/…/marketplace.json`) は clone できないため使えません。

### リポジトリに明示的に設定する

特定のリポジトリで利用するプラグインを設定として明示し、チームで共有したい場合は、プロジェクトの `.claude/settings.json` にマーケットプレイスの登録とプラグインの有効化を記述します。

```json
{
  "extraKnownMarketplaces": {
    "akm-claude-plugins": {
      "source": {
        "source": "github",
        "repo": "akm/claude-plugins"
      }
    }
  },
  "enabledPlugins": {
    "commit-rules-guard@akm-claude-plugins": true
  }
}
```

- `extraKnownMarketplaces` はマーケットプレイス名をキーとするオブジェクトで、値の `source` にマーケットプレイスの取得元を指定します。
- `enabledPlugins` は `プラグイン名@マーケットプレイス名` をキー、有効/無効を表す真偽値を値とするオブジェクトです。

`settings.json` の詳しい説明については [公式ドキュメント](https://code.claude.com/docs/en/settings#plugin-settings) を参照してください。

`.claude/settings.json` は git 管理下に置くとチーム全体で共有されます。一方、自分だけで有効化したい場合や個人的にオーバーライドしたい場合は、同じ内容を `.claude/settings.local.json` に記述することもできます。`.claude/settings.local.json` は通常 gitignore され、`.claude/settings.json` よりも優先されます。

### 最新版に更新する

このリポジトリの `main` に PR がマージされてプラグインが更新されても、手元のプラグインはそのままでは更新されません。マーケットプレイス akm-claude-plugins はサードパーティのマーケットプレイスで、自動更新がデフォルトで無効なためです。最新の版を取り込む手順は、次の 3 つです。

- [make のターゲットを使う](#make-のターゲットを使う-このリポジトリを-clone-している人向け): このリポジトリを clone している人向け。どのプラグインが古いかを表示し、user スコープに入っていないものをインストールする
- [マーケットプレイスの自動更新を有効にする](#マーケットプレイスの自動更新を有効にする): インストール済みのプラグインを、Claude Code が自動で更新する
- [手作業で更新する](#手作業で更新する-自動更新を使わない人向け): 自動更新を使わない人向け。プラグインを 1 つずつ更新する

#### make のターゲットを使う (このリポジトリを clone している人向け)

リポジトリのルートのファイル `Makefile` に、2 つのターゲットがあります。どちらも、最新の版を[配布元](CONCEPTS.md#配布元)の `main` から読みます。振る舞い (前提の検査・終了コード・途中で中止したときの表示など) の [SSOT](CONCEPTS.md#ssot) は、スクリプト [`scripts/plugins.py`](scripts/plugins.py) のモジュールの docstring で、以下はその要約です。

```bash
make plugins-status
make plugins-install
```

- ターゲット `plugins-status` は、このリポジトリのプラグインごとに、最新の版と、スコープ (user / project / local) ごとのインストール済みの版を並べ、最新の版と比べた結果 (同じ・古い・新しい) を示します。表示するだけで、インストール済みのプラグインは変えません。
- ターゲット `plugins-install` は、user スコープにインストールされていないプラグインを、user スコープにインストールします。user スコープにインストール済みのプラグインは、古くても更新しません。更新には、次の節のマーケットプレイスの自動更新を使います。インストールの後に必要な手順は、実行の最後に表示します。

変数 `PLUGINS` にプラグインの名前をカンマで区切って指定すると、そのプラグインだけを対象にします。make のコマンドラインで指定したときだけ対象を絞り、同じ名前の環境変数では絞りません。

```bash
make plugins-status PLUGINS=doc-dag,wording-guard
```

#### マーケットプレイスの自動更新を有効にする

自動更新を有効にすると、Claude Code はマーケットプレイス akm-claude-plugins の定義を取得し直し、インストール済みのプラグインを更新します。インストールされていないプラグインは、インストールしません。有効にする方法は、次の 2 つです。

- Claude Code のセッションでコマンド `/plugin` を実行し、Marketplaces タブで akm-claude-plugins を選んで、「Enable auto-update」を選ぶ
- ファイル `~/.claude/settings.json` のキー `extraKnownMarketplaces.akm-claude-plugins` に、`"autoUpdate": true` を書く。取得元を表す `source` も一緒に書く (下の例)

```json
{
  "extraKnownMarketplaces": {
    "akm-claude-plugins": {
      "source": {
        "source": "github",
        "repo": "akm/claude-plugins"
      },
      "autoUpdate": true
    }
  }
}
```

すぐに更新したいときは、同じ Marketplaces タブで akm-claude-plugins を選んで、「Update marketplace」を選びます。詳しくは、公式ドキュメント[プラグインのインストールと管理](https://code.claude.com/docs/ja/plugins/install)の節[マーケットプレイスの自動更新をオンまたはオフにする](https://code.claude.com/docs/ja/plugins/install#turn-auto-update-on-or-off-for-a-marketplace)を参照してください。自動更新がいつ実行され、更新した版がいつ読み込まれるかは、公式ドキュメント[プラグイン読み込みリファレンス](https://code.claude.com/docs/ja/plugins/loading)の節[自動アップデートが実行される場合](https://code.claude.com/docs/ja/plugins/loading#when-auto-update-runs)を参照してください。

プラグイン wording-guard で textlint を使っている場合は、wording-guard の版が変わったら、textlint を入れるコマンド `wording_lint.py setup` をもう一度実行します。実行するコマンドは、ファイル `wording-guard/README.md` の節「[textlint による検査 (任意)](wording-guard/README.md#textlint-による検査-任意)」を参照してください。

#### 手作業で更新する (自動更新を使わない人向け)

**1. インストール先のスコープを確認する**

更新コマンドはスコープを取り違えると失敗するため、先に現状を確認します。

```bash
claude plugin list
```

```
❯ commit-rules-guard@akm-claude-plugins
  Version: 0.1.0
  Scope: project        ← このスコープを次の手順で使う
```

**2. マーケットプレイス定義を更新する**

```bash
claude plugin marketplace update akm-claude-plugins
```

マーケットプレイス定義 (収録プラグインの一覧) を取得元から取り直します。マーケットプレイス名を省略すると、登録済みのすべてのマーケットプレイスが更新されます。

**3. プラグイン本体を更新する**

`marketplace update` だけではプラグイン本体は更新されないため、続けて実行します。**プラグイン名は `プラグイン名@マーケットプレイス名` の形式で指定してください。** 短い名前 (`commit-rules-guard`) だけでは解決できず `Plugin "..." not found` になります。

user スコープ (既定) の場合:

```bash
claude plugin update commit-rules-guard@akm-claude-plugins
```

project / local スコープの場合は、**`--scope` の指定と、そのプロジェクトのディレクトリでの実行**が必要です。`plugin update` の既定は user スコープのため、指定しないと `not installed at scope user` になります。

```bash
claude plugin update commit-rules-guard@akm-claude-plugins --scope project
```

更新した版を実行中のセッションに読み込む方法は、公式ドキュメント[プラグイン読み込みリファレンス](https://code.claude.com/docs/ja/plugins/loading)の節[プラグインが到達したステージを確認](https://code.claude.com/docs/ja/plugins/loading#check-which-stage-a-plugin-reached)を参照してください。

`.claude/settings.json` の `enabledPlugins` で有効化している場合も、プラグイン本体の取得は同じ仕組みのため、更新手順は同様です。設定ファイルに書いてあるだけでは最新版が自動で使われるわけではない点に注意してください。

なお、収録プラグインは `main` ブランチを参照する設定 (`marketplace.json` の `ref`) のため、更新するとマージ済みの最新の内容が取り込まれます。

各プラグインの詳細は上表のリンク先 README を参照してください。

## 構成

```
.
├── .claude-plugin/
│   └── marketplace.json          # マーケットプレイス定義 (収録プラグインの一覧)
├── .github/
│   ├── test-targets.txt          # CI が期待するテストの対象の一覧
│   └── workflows/test.yml        # 自動テストを GitHub Actions で実行する
├── Makefile                      # プラグインのインストール状況の表示 (plugins-status) とインストール (plugins-install)
├── scripts/                      # どのプラグインにも属さないスクリプト
│   ├── plugins.py                # Makefile のターゲットが実行する本体。振る舞いはモジュールの docstring
│   └── tests/                    # python3 -m unittest discover -s scripts/tests
├── commit-rules-guard/           # hooks 型
│   ├── .claude-plugin/plugin.json
│   ├── hooks/hooks.json
│   ├── hook-scripts/              # 各フックの本体 (4 本)
│   ├── rules/commit-rules.md      # 同梱の既定ルール
│   ├── tests/                     # python3 -m unittest discover -s commit-rules-guard/tests
│   └── README.md
├── pr-teeth/                     # skill 型
│   ├── .claude-plugin/plugin.json
│   ├── skills/pr-teeth/SKILL.md
│   ├── skills/pr-glossary/SKILL.md
│   ├── scripts/                   # 判定・保存・HTML 生成
│   ├── tests/                     # python3 -m unittest discover -s pr-teeth/tests
│   ├── CONCEPTS.md                # 設計
│   └── README.md
├── mermaid-preview/              # skill 型
│   ├── .claude-plugin/plugin.json
│   ├── skills/mermaid-preview/
│   │   ├── SKILL.md
│   │   └── template.html
│   └── README.md
├── commit-squash/                # skill 型
│   ├── .claude-plugin/plugin.json
│   ├── skills/commit-squash/     # SKILL.md と references/
│   └── README.md
├── doc-dag/                      # skill 型
│   ├── .claude-plugin/plugin.json
│   ├── skills/doc-dag/           # SKILL.md と references/
│   └── README.md
├── work-log-gh-comment/          # skill 型
│   ├── .claude-plugin/plugin.json
│   ├── skills/work-log-gh-comment/  # SKILL.md、references/
│   │   └── evals/                # python3 -m unittest discover -s work-log-gh-comment/skills/work-log-gh-comment/evals
│   └── README.md
├── wording-guard/                # skill 型 + hooks 型
│   ├── .claude-plugin/plugin.json
│   ├── skills/wording-guard/     # SKILL.md と references/
│   ├── hooks/hooks.json
│   ├── hook-scripts/             # Markdown に書き足した文章を textlint で検査する
│   ├── scripts/                  # 用語ファイルの読み込みと textlint の実行 (wording_lint.py)
│   ├── textlint/                 # textlint と規則集の版を固定する package.json と package-lock.json
│   ├── tests/                    # python3 -m unittest discover -s wording-guard/tests
│   └── README.md
├── session-handoff/              # skill 型 + hooks 型
│   ├── .claude-plugin/plugin.json
│   ├── skills/handoff-write/     # 引き継ぎ文を書いて保存する。SKILL.md と references/
│   ├── skills/handoff-resume/    # 引き継ぎ文を読んで再開する。SKILL.md と references/
│   ├── hooks/hooks.json
│   ├── hook-scripts/             # 引き継ぎ文の保存先を貼ったときに再開を促す
│   ├── tests/                     # python3 -m unittest discover -s session-handoff/tests
│   └── README.md
├── doc-structured/               # skill 型 + 同梱ツール (作成中)
│   ├── .claude-plugin/plugin.json
│   ├── skills/generate/          # YAML から文書を生成し直す
│   ├── skills/check/             # 文書を検査し、直す
│   ├── rules/                    # 規則の文書 (プロジェクトの .claude/rules/ に置くコピーの元)
│   ├── scripts/                  # スキルの前置き (プラグインと設定のバージョンの比較)
│   ├── bin/doc-structured        # プロジェクトに置く、ツールの入口のスクリプト
│   ├── tool/                     # 生成と検査のツール (Python)。テストは tool/tests/
│   └── README.md
├── issue-practice/               # skill 型 + 同梱スクリプト (作成中)
│   ├── .claude-plugin/plugin.json
│   ├── skills/new-issue/         # 要望・バグ・切り出しの Issue を作る
│   ├── references/               # すべてのスキルが参照する用語と書式の文書
│   ├── scripts/                  # 検査のスクリプト (issue_practice.py とパッケージ issue_practice/)
│   ├── tests/                    # python3 -m unittest discover -s issue-practice/tests
│   └── README.md
└── review-triage/                # skill 型 + 同梱ツール
    ├── .claude-plugin/plugin.json
    ├── agents/                    # フェーズを sub-agent で実行する effort ごとの agent 定義
    ├── skills/review-request/     # レビューの依頼文の生成
    ├── skills/review-triage/      # SKILL.md と references/
    ├── skills/review-triage-fix/
    ├── skills/review-triage-loop/  # レビューから修正までのループ
    ├── skills/review-loop/        # レビューを端末のワーカーに任せるループ
    ├── skills/review-rally/       # レビューを別のセッションに任せるループ
    ├── scripts/                   # ワーカー (python3 で実行するファイルを置く review-loop-worker/ を含む) と、review-loop のセッションの待機スクリプト
    ├── tests/                     # python3 -m unittest discover -s review-triage/tests
    ├── tools/triagecheck/         # 記録を検査する Go ツール (go test ./...)
    ├── tools/nearedges/           # Markdown の修正の差分から、コミット前に読む範囲を列挙する Go ツール (go test ./...)
    ├── tools/lineorigin/          # 指摘の対象の行が、全量の起点から変わっていないかを確認する Go ツール (go test ./...)
    ├── tools/diffhtml/            # HTML のマークを、案のパッチかコミットの差分に置き換える Go ツール (go test ./...)
    └── README.md
```

プラグインは 2 つの型があります。**hooks 型**は Claude Code の動作に自動で割り込むもの、**skill 型**は依頼に応じて呼び出されるものです。skill 型はプラグイン直下の `skills/<スキル名>/SKILL.md` に置きます。1 つのプラグインが複数の skill を持つこともあります (`review-triage`)。

## 自動テスト

テストは、上の「構成」の節で各ディレクトリに添えたコマンドで実行します。各プラグインのテストのほかに、どのプラグインにも属さないスクリプトのテスト (ディレクトリ `scripts/tests/`) もあります。GitHub Actions のワークフロー (ファイル `.github/workflows/test.yml`) が、ブランチ `main` への push と、PR を開いたときと PR に push したときに、同じテストを実行します。

対象はワークフローに書かず、リポジトリが追跡しているファイル (コマンド `git ls-files` が挙げるファイル) から見つけ、ファイル `.github/test-targets.txt` に書いた期待の一覧と比べます。差があれば失敗にするので、テストが対象から外れても、一覧に無いテストが増えても気づけます。テストの種類ごとの見つけ方 (ファイルの命名) と比べ方はワークフローの冒頭のコメントに、各 job の失敗の条件は各 job の手順のコメントに書いてあり、どちらもワークフローのコメントが [SSOT](CONCEPTS.md#ssot) です。

プラグインのテストでも、`scripts/tests/` のようにどのプラグインにも属さないテストでも、ワークフローの冒頭のコメントの命名でテストを書き、`.github/test-targets.txt` に 1 行足せば、ワークフローを変えずにテストが実行されるようになります。

## 文書の書き方

このリポジトリの文書を書く・直すときの規則は [CLAUDE.md](CLAUDE.md) にあります。Claude Code はこのファイルを自動で読みます。

## プロジェクト固有の設定

いくつかのプラグインは、リポジトリごとに違う値を `.claude/akm-claude-plugins/<プラグイン名>/config.json` から読みます。パスにマーケットプレイス名が入る理由は [CONCEPTS.md](CONCEPTS.md) の「配布元」「設定ディレクトリ」を参照してください。**プラグインは共通の規則を持ち、リポジトリ固有の宣言だけを設定に置く**という分け方です。

| プラグイン | 主な設定 |
| --- | --- |
| `commit-rules-guard` | `generated_globs`・`custom_rules` |
| `doc-dag` | `frozen_paths`・`doc_check_command` |
| `wording-guard` | `convention_paths`・`frozen_paths`・`quote_markers`・`terms_paths`・`textlint` |
| `review-triage` | `record_dir`・`gates`・`triage_check_command` ほか |

いずれも**設定が無くても動きます** (該当の判断を人間に確認するか、その手順を飛ばして報告します)。詳細は各プラグインの README を参照してください。
