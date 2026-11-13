# 用語

プラグイン issue-practice のスキルと文書が使う語を、ここで定義します (計画の R1)。スキルと文書は、この定義のとおりに使い、別の言い方をしません。

| 語 | 意味 |
| --- | --- |
| 管理 Issue (managing-issue) | 管理セッションが受け持つ Issue。多くの場合、GitHub の親 Issue |
| 作業 Issue (working-issue) | 作業セッションが受け持つ Issue。多くの場合、管理 Issue の sub-issue。子の sub-issue を持つ作業 Issue は、その子にとっての管理 Issue でもある |
| 管理セッション | 管理 Issue の計画を立て、作業セッションを起動して記録し、確認して閉じる Claude Code のセッション |
| 作業セッション | 作業 Issue 1 つを受け持って進め、管理セッションに報告する Claude Code のセッション |
| 自己管理 Issue (self-managing-issue) | PR 1 つで済む Issue で、1 つのセッションが管理セッションと作業セッションの両方の役割で進めるもの。作業 Issue を持たない |
| リリース計画 Issue | リリースの順番と、各リリースに含める Issue を計画する Issue。リリース対象ごとに、ラベル `current` が付いたものが 1 つだけ有効 |
| リリース Issue | 1 回のリリースを表す Issue。リリースマイルストーンと 1 対 1 で、お互いの URL を持つ |
| リリースマイルストーン | 1 回のリリースを表す GitHub のマイルストーン。リリースに含める Issue に設定する |
| リリース対象 | リリースする単位。通常はリポジトリに 1 つ |
| 計画案 | Issue を作る・書き換える前に、会話で調整する Markdown のファイル。ディレクトリ `tmp/issue-practice/` の下に置く。書式は [draft-plan.md](draft-plan.md)。リリース Issue の題名の `[DRAFT]` とは別のもの |
| 記録のコメント | スキルが Issue に書くコメントのうち、1 行目を決まった形にしたもの。承認・計画の変更・報告・確認の結果などの経緯を記録する。形は [record-comments.md](record-comments.md) |
| 最初の指示 | 管理セッションが作業セッションを起動するときに渡す文。受け持つ作業 Issue を作業セッションに渡す手段。形は [start-instruction.md](start-instruction.md) |
| 検査のスクリプト | プラグインに入れた Python のスクリプト (ファイル `issue-practice/scripts/issue_practice.py`)。GitHub の状態を読み、決めた形になっているかを判定する。手順が複数ある書き込みも、このスクリプトが行う |
| クローズ条件 | Issue を閉じてよい条件。本文の節「クローズ条件」に、「期待する状態」と「確認するポイント」のチェックボックスで書く。書き方は [closing-conditions.md](closing-conditions.md) |
| PR マージ計画 | 管理 Issue の本文に書く、どの作業 Issue の PR を・どの順で・どのブランチにマージするかの表と図 |

## 役割の語と GitHub の関係の語

「親 Issue」「sub-issue」は GitHub の Issue どうしの関係の名前で、セッションの役割とは対応しません。子の sub-issue を持つ sub-issue は、その子にとっては管理 Issue で、親にとっては作業 Issue です。そのため、役割を表すときは「管理 Issue」「作業 Issue」と書き、GitHub の関係を表すときだけ「親 Issue」「sub-issue」と書きます (計画の KD1)。
