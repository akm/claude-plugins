# doc-structured: ドメインの規則

ディレクトリ `docs/domains/` と、ロールを書くファイル `docs/system/roles.yaml` の規則です。ID・限定付きの名前・生成したファイルの判別の方法は [doc-structured-docs.md](doc-structured-docs.md) にあります。規則の SSOT (single source of truth。ある事実を定めている唯一の記述) はプラグインのこのファイルで、プロジェクトのファイル `.claude/rules/doc-structured-domains.md` はそのコピーです。

## ドメインのディレクトリ

アプリケーションを小さなゴールの単位 (ドメイン) に分け、ドメインごとにディレクトリ `docs/domains/NN-<名前>/` を作ります。

- `NN` は 2 桁以上の数字で、ドメインを作った順に付け、後から変えない。名前は英語名で snake_case。
- 同じ番号や同じ名前のドメインを 2 つ作らない。
- 列挙できる事実 (モデル・属性・値・未分類の用語・操作・前提・イベント・状態の遷移) は YAML に書き、説明と判断は手書きの Markdown (`concept.md`・`problem.md`・`design.md`) に書く。
- 人が読む一覧の Markdown は YAML から生成する。

| ファイル | 書くこと |
|---|---|
| `domain.yaml` (直下に必須) とその他の `*.yaml` | 生成の元。ドメインの説明・モデル・属性・値・未分類の用語・操作・前提・イベント・状態の遷移 (属性の下に書けないものは `state-machines-<名前>.yaml`) |
| `README.md` | 生成。ドメインの説明と、手書きのファイルと生成したファイルへのリンク |
| `models.md` | 生成。モデル・属性・値の定義と、状態の遷移の表と図 |
| `unclassified_app_terms.md` | 生成。未分類のアプリケーション用語の定義 |
| `functions.md` | 生成。操作・前提・イベントの定義 |
| `terms.md` | 生成。このドメインの用語の索引 |
| `concept.md` | 手書き。概念・境界・不変条件・方針・理由 |
| `problem.md` | 手書き。問題 |
| `design.md` | 手書き。設計の判断と短い理由 |
| `<種類>/<名前>.md` | 手書き。`concept.md`・`problem.md`・`design.md` を話題ごとに分けた子のファイル (下の節「手書きの Markdown」) |

全ドメインの用語の索引 `docs/glossary.md` と、ロールと操作の表 `docs/system/permissions.md` (下の節「ロール」) も生成します。

## YAML の形式

英語名をマッピングのキーにし、日本語名を `name_ja`、定義を `definition` に書きます。

```yaml
# docs/domains/02-loans/domain.yaml
domain:
  description: 図書の貸出と返却を扱う。
models:
  loan:
    name_ja: 貸出
    definition: 利用者が図書を借りてから返すまでの 1 回の記録。
    attributes:
      book:
        name_ja: 貸出図書
        definition: 貸し出した図書。
        refers_to: d-catalog-m-book
      status:
        name_ja: 貸出状態
        definition: 貸出が今どの段階にあるか。
        values:
          on_loan:
            name_ja: 貸出中
            definition: 図書が利用者の手元にある。
unclassified_app_terms:
  business_day:
    name_ja: 開館日
    definition: 図書館が利用者に開いている日。休館日を除く。
operations:
  lend:
    name_ja: 貸し出す
    definition: 利用者に図書を貸し出し、貸出を作る。
    targets:
      - d-loans-m-loan
    preconditions:
      - d-loans-pre-book_shelved
    events:
      - d-loans-ev-book_lent
    roles:
      - r-librarian
preconditions:
  book_shelved:
    name_ja: 図書が配架中
    definition: 貸し出す図書が書架にある。
    targets:
      - d-catalog-m-book-a-shelf_status-v-shelved
events:
  book_lent:
    name_ja: 図書を貸し出した
    definition: 図書が利用者の手元に移った。
```

| キー | 書ける場所 | 中身 |
|---|---|---|
| `domain` | 直下の `domain.yaml` だけ (必須) | `description` (ドメインの説明の文。必須) |
| `models` | どの YAML にも | モデルの英語名をキーにしたマッピング |
| `attributes` | モデルの下 | 属性の英語名をキーにしたマッピング |
| `values` | 属性の下 | 値の英語名をキーにしたマッピング |
| `refers_to` | 属性の下 | 参照するモデルの完全な ID (同じドメインでも `d-` から書く) |
| `unclassified_app_terms` | どの YAML にも | 未分類のアプリケーション用語の英語名をキーにしたマッピング |
| `operations` | どの YAML にも | 操作の英語名をキーにしたマッピング |
| `preconditions` | どの YAML にも | 前提の英語名をキーにしたマッピング |
| `events` | どの YAML にも | イベントの英語名をキーにしたマッピング |
| `targets` | 操作の下 | 操作の対象 (操作が作る・変える・消す・読むモデルと属性) の完全な ID の配列 |
| `preconditions` | 操作の下 | 操作の前提の完全な ID の配列 |
| `events` | 操作の下 | 操作が起こすイベントの完全な ID の配列 |
| `roles` | 操作の下 | 操作を行えるロールの完全な ID の配列 |
| `targets` | 前提の下 | 前提が確認するモデル・属性・値の完全な ID の配列 |
| `state_machine` | 値を持つ属性の下、またはファイル名が `state-machines-` で始まる YAML | 状態の遷移 (下の節「状態の遷移」) |
| `name_ja`・`definition` | モデル・属性・値・未分類の用語・操作・前提・イベント・ロール (どれも必須) | 日本語名と、1〜2 文の定義 |

- `name_ja` には、改行と `"` を書けない (完全な名前をリンクの title `"…"` に書くため)。
- `definition` と、`domain` の `description` には、CR (YAML の二重引用符の中の `\r`) を書けない (生成したファイルは改行の CR を LF として読むので、CR を含む文は、生成し直した内容と一致しなくなるため)。
- 参照 (`refers_to`) を書けるのは属性だけで、参照先はモデルだけ。外部キーを持つモデルの属性に書く。自分のモデルを参照してもよい。
- 操作の `targets` は、モデルと属性を参照でき、値は参照できない (どの値に変えるかは状態の遷移で書く)。前提の `targets` は、値も参照できる (前提は値を確認することが多いため)。読むか変えるかは区別しない。
- 完全な ID の配列のキー (`targets`・操作の下の `preconditions`・`events`・`roles`) は省ける。空の配列と、同じ ID を 2 回書くことはエラーになる (省くことと同じ意味の書き方を 2 つ作らないため)。同じドメインの定義も `d-` から書く。
- `roles` を省いた操作は、どのロールも行わない操作 (定期実行など、アプリケーションが自分で行う処理) を表す。操作は、利用者かアプリケーションが行うことを指す。
- イベントは `name_ja` と `definition` だけを持つ。
- どの操作からも参照されない前提・イベント・ロールも書ける。
- 知らないキーはエラーになる。拡張子は `.yaml` にする (`.yml` はエラー)。

### YAML を分ける

ドメインのディレクトリの下に、どの深さのサブディレクトリを作って YAML を分けてもかまいません。ツールはドメインのディレクトリの下のすべての `.yaml` を読み、ID は名前から作るので、ファイルの配置に関係しません。

- 1 つのモデル (その属性と値を含む) は、1 つのファイルに書く。
- 同じ種類の同じ英語名の定義 (モデル・未分類の用語・操作・前提・イベント) を、ドメインの中の 2 つのファイルに書かない。種類が違えば、同じ英語名でよい (ID が違うため)。
- 分けるときは、下の節「参照の向き」に従う。

## 状態の遷移

属性の値が、どの値からどの値に変わるかを、状態の遷移として書きます。状態は属性の値そのもので、別の種類の定義を作りません。状態の遷移と遷移は、ID を持ちません。

書き方は 2 つあり、書く項目は同じです。

- **属性の下に書く**: 属性の下のキー `state_machine` に書く。属性の値が 3 つ以下で、どの遷移にも `preconditions` が無いときだけ書ける (大きな状態の遷移を属性の下に書くと、`domain.yaml` のモデルと属性が読みにくくなるため)。
- **ファイルに書く**: ファイル名が `state-machines-` で始まる YAML のトップのキー `state_machine` に書き、`attribute` で属性を指す。値の数と `preconditions` の制限は無い。

```yaml
# docs/domains/02-loans/domain.yaml (属性の下に書く)
models:
  loan:
    name_ja: 貸出
    definition: 利用者が図書を借りてから返すまでの 1 回の記録。
    attributes:
      status:
        name_ja: 貸出状態
        definition: 貸出が今どの段階にあるか。
        values:
          on_loan: ...
          overdue: ...
          returned: ...
        state_machine:
          initial: on_loan
          transitions:
            - from: [on_loan]
              to: overdue
              operations: [d-loans-op-notify_overdue]
            - from: [on_loan, overdue]
              to: returned
              operations: [d-loans-op-return_book]
```

```yaml
# docs/domains/02-loans/state-machines-status.yaml (ファイルに書く)
state_machine:
  attribute: d-loans-m-reservation-a-status
  initial: waiting
  transitions:
    - from: [waiting]
      to: on_hold
      operations: [d-loans-op-return_book]
      preconditions: [d-loans-pre-first_in_line]
    - from: [on_hold]
      to: cancelled
      preconditions: [d-loans-pre-hold_expired]
```

| キー | 書ける場所 | 中身 |
|---|---|---|
| `attribute` | ファイルに書く `state_machine` の下 (必須) | 状態の遷移を持つ属性の完全な ID。同じドメインの属性だけ |
| `initial` | `state_machine` の下 | 最初の状態 (属性を持つモデルを作った直後の値) の英語名。省ける |
| `transitions` | `state_machine` の下 (必須) | 遷移の配列 |
| `from` | 遷移の下 (必須) | 前の状態の、値の英語名の配列 |
| `to` | 遷移の下 (必須) | 後の状態の、値の英語名 |
| `operations` | 遷移の下 | 遷移を起こす操作の完全な ID の配列。省ける |
| `preconditions` | 遷移の下 (ファイルに書くときだけ) | 遷移の条件にする前提の完全な ID の配列。省ける |

- `from`・`to`・`initial` には、完全な ID ではなく、その属性の値の英語名を書く。
- `transitions` と `from` は空の配列にできない。`operations`・`preconditions` の空の配列と、同じ ID を 2 回書くことは、操作の参照と同じくエラーになる。
- 前の状態と後の状態が同じ遷移と、前の状態と後の状態の組が同じ遷移を 2 つ書いてもよい。どの遷移にも出てこない値があってもよい。
- 最後の状態 (そこからどこへも変わらない状態) は書かない。
- 1 つの属性の状態の遷移は、1 か所にだけ書く。
- ファイル名が `state-machines-` で始まる YAML には、トップのキー `state_machine` だけを書き、状態の遷移を 1 つだけ書く。そのほかの YAML のトップには `state_machine` を書かない。
- 状態の遷移のファイルは、属性を定義した YAML と同じディレクトリか、その祖先のディレクトリに置く (下の節「参照の向き」)。

## ロール

ロールは、ドメインの外のファイル `docs/system/roles.yaml` のキー `roles` に書きます。ロールは権限だけの単位で、階層を持ちません。ID は親を持たない `r-<英語名>` です (例 `r-librarian`)。どのドメインにも属さないので、ロールを参照するドメインのあいだに依存は生まれません。

```yaml
# docs/system/roles.yaml
roles:
  librarian:
    name_ja: 司書
    definition: 図書館の窓口で、貸出と返却を扱う職員。
```

- `roles` の下には、ロールの英語名をキーにしたマッピングを書き、各ロールに `name_ja` と `definition` を書く (どちらも必須)。
- ファイルが無ければ、ロールは無い。ロールを参照する操作があれば、検査 h が参照先が無いと報告する。

## 手書きの Markdown

- ドメインのディレクトリの直下に書く手書きの Markdown は、`concept.md`・`problem.md`・`design.md` だけ。
- 100 行を超えたファイルを分けるときは、種類と同じ名前のサブディレクトリに、話題ごとの子のファイル `<名前>.md` を作る (例 `design/overdue_notice.md`)。名前は snake_case にする。サブディレクトリは 1 階層だけ。
- 元のファイルは残し、子のファイルへのリンクを書く。子のファイルは、生成する `README.md` には載らない。
- ドメインのサブディレクトリには、子のファイルのほかに `.md` を書かない (YAML を分けたサブディレクトリにも書かない)。
- アンカー・リンク・行数の規則は [doc-structured-docs.md](doc-structured-docs.md) にある。

## 書き方の指針

- YAML の `definition` には、その名前が何を指すかを 1〜2 文で書く。規則・理由・手順は `concept.md` に書く。
- 状態の遷移のファイル名は、`state-machines-<属性の英語名>.yaml` にする。同じディレクトリに、同じ英語名の属性の状態の遷移が 2 つあれば、モデルの英語名も付ける (`state-machines-loan-status.yaml`)。
- 操作のどの遷移にも当てはまる条件は、操作の `preconditions` に書く。遷移ごとに違う条件だけを、遷移の `preconditions` に書く。

## 参照の向き

YAML の参照 (`refers_to`・状態の遷移の `attribute` と、完全な ID の配列のキー) は、参照する YAML のディレクトリの祖先のディレクトリにある YAML の定義を指しません。同じディレクトリ・子孫のディレクトリ・別のサブツリー・ほかのドメインは指してかまいません。ロールを書く `docs/system/` は、ドメインのディレクトリの祖先ではないので、`roles` はこの規則に反しません。状態の遷移の `from`・`to`・`initial` は値の英語名で、参照ではないので、この規則の対象にしません。

依存関係を整理するときに重要なのは、参照される定義をサブディレクトリに移すことであって、参照しているファイルを移すことではありません。複数のサブディレクトリから参照される定義は、親のディレクトリに置かず、参照するファイルと同じディレクトリかその下に置きます。

## 生成するファイルの中身

- 定義ごとに `<a name="ID"></a>` と見出しを書く。見出しは「種類 + 日本語名」の後に英語名をコードの書式で書く (`## モデル「貸出」 `loan``)。
- リンクは reference-style で、ラベルを ID にし、定義の行 `[ID]: 相対パス#ID "完全な名前"` をファイルの末尾に書く。
- `models.md` の定義は、直下の `domain.yaml` を先にし、残りのファイルはパスの文字コードの順、ファイルの中は書いた順に並べる。各モデルに、そのモデルを参照するモデルを書く。
- 状態の遷移を持つ属性には、`models.md` の属性の定義の文の後 (値の定義の前) に、最初の状態の文 (「状態の遷移 (最初の状態: 値「貸出中」):」。最初の状態が無ければ「状態の遷移:」)・遷移の表・図を書く。見出しは付けない。
- 遷移の表の列は「前の状態 | 後の状態 | 操作 | 前提」で、どちらの書き方でも同じにする。YAML に書いた順に、遷移 1 つを 1 行にし、セルには、日本語名を表示の文にしたリンクを「・」で区切って書く。
- 遷移の図は mermaid の stateDiagram-v2 で書く。属性の値をすべて状態として描き、状態の文は日本語名、識別子は値の英語名に `v_` を付けたもの (`end`・`state` などの英語名を識別子にすると、mermaid が図を読めないため) にする。最初の状態があれば `[*]` からの矢印を描く。遷移ごと、前の状態ごとに矢印を 1 本描き、矢印の文字は、操作の日本語名を「・」で区切ったものと、前提があればその日本語名を「・」で区切って `[…]` で囲んだもの。
- `functions.md` は、操作・前提・イベントの順に、`models.md` と同じ並べ方で定義を書く。操作と前提は、定義の文の後に、参照を箇条書き (対象・前提・イベント・行えるロール) で書く。`roles` を省いた操作には「行えるロール: 無し」と書く。
- 参照する側の一覧 (その前提を使う操作など) は書かない。書くのは `models.md` の「このモデルを参照するモデル」だけ。
- 生成したファイルで、ほかの定義を指すリンクの表示の文は、同じドメインの定義なら完全な名前からドメインを省いた形、ほかのドメインの定義とロールなら完全な名前にする。
- `docs/system/permissions.md` は、ロールの定義を `roles.yaml` に書いた順に書く。操作があれば、その後に見出し「操作ごとの、行えるロール」と、行が操作・列がロールの表を書く。行えるセルに ○ を書き、行えないセルは空にする。行は、ドメインのディレクトリの順、ドメインの中は `functions.md` と同じ順に並べる。ファイルのアンカーは持たない。
- 用語の索引 (`terms.md`・`docs/glossary.md`) は定義の文を持たず、日本語名の文字コードの順 (同じなら ID の順) に、定義へのリンクを並べる。漢字の名前は、読みの順にならない。ロールは `docs/glossary.md` にだけ載せ、列「ドメイン」を空にする。
- `docs/glossary.md` と `docs/.gitattributes` の生成元は、ロールがあれば `docs/` (ドメインの外の YAML も読むため)、無ければ `docs/domains/` と書く。`docs/system/permissions.md` の生成元は `docs/`。
- 定義が 1 つも無い種類のファイルは作らない。前に生成したものは、`bin/doc-structured generate` が消す。
- `README.md` の表には、ドメインのディレクトリの直下にある手書きのファイルを `concept.md`・`problem.md`・`design.md` の順に先に、生成したファイルを後に並べる。手書きのファイルを足したり消したりすると、検査 a が生成し直しを求める。
- 生成するファイルの場所に、先頭の記述が無く、空白と BOM 以外の文字があるファイル (手で書いたファイル) があれば、`bin/doc-structured generate` は何も書かずにエラーで終了し、検査 a が報告する。手で書いたファイルを上書きしないため。

## 検査

スキル `doc-structured:check` (コマンド `bin/doc-structured check`) が、次の 6 つを検査します。誤りは「パス:行:列: 検査 <記号>: メッセージ」の形で出ます。

| 検査 | 確認すること | 直し方 |
|---|---|---|
| a | 生成し直した内容と、今の生成したファイルに差分が無い。生成するファイルの場所に、手で書いたファイルが無い | 生成元の YAML を直し、スキル `doc-structured:generate` を実行する。手で書いたファイルは、名前を変える。または、内容を移してから消す。`docs/.gitattributes` は、手で書いた行のパターンをリポジトリのルートからの相対に書き換えて、ルートの `.gitattributes` に移してから消す |
| b | 手書きの Markdown の名前と場所、アンカーと見出し、リンクの書き方、定義の行 (定義の無いラベル・使われていない定義の行・同じラベル・書く位置・href・title)。規則は [doc-structured-docs.md](doc-structured-docs.md) の節「アンカー」と「リンク」 | スキル `doc-structured:links-fix` を実行する。名前と場所・アンカーと見出し・リンクの書き方は、報告のとおりに直す |
| c-2 | 手書きの Markdown の参照に、節の単位で循環が無い。規則は [doc-structured-docs.md](doc-structured-docs.md) の節「参照の循環」 | 循環のどれかのリンクを外すか、参照される内容を別の節に移す |
| h | YAML の形式と、参照 (`refers_to`・状態の遷移の `attribute` と完全な ID の配列) の参照先が、そのキーで参照できる種類の定義としてある。状態の遷移の `from`・`to`・`initial` が、その属性の値にある | YAML を直す。属性の下に書けない状態の遷移は、ファイル名が `state-machines-` で始まる YAML に移す |
| i | YAML の参照が祖先のディレクトリの YAML の定義を指していない。手書きの Markdown のリンクが、祖先のディレクトリの手書きのファイルを指していない (規則は [doc-structured-docs.md](doc-structured-docs.md) の節「参照の向き」) | 参照される定義をサブディレクトリに移す。状態の遷移のファイルの `attribute` では、属性をサブディレクトリに移すか、状態の遷移のファイルを属性と同じディレクトリに移す。手書きの Markdown では、参照される内容をサブディレクトリの子のファイルに移す |
| k | 手書きの Markdown が 100 行を超えていない。超えていれば、理由のコメントがある | 話題ごとに子のファイルに分けるか、理由のコメントを書く |

検査 h に誤りがあると、検査 a・b・c-2・i は実行しません (検査 a・b・i は定義の一覧と完全な名前を作れないため、検査 c-2 は検査 b が確認するリンクの上で数えるため)。検査 k は YAML を使わないので、いつも実行します。
