# 用語ファイル

**用語ファイルは、言い換えを決めた語 (避ける語) と、使い続けると決めた語 (許容する語) を、理由と決めた場所とともに記録するファイル。** 置き場は設定キー `terms_paths` で指定する (ファイル [wording-guard/skills/wording-guard/references/project-config.md](project-config.md))。

## 用語ファイルは例であって、範囲ではない

**用語ファイルに書いた語は、決めたことの記録であって、検査の範囲ではない。** 用語ファイルに無い言い回しも、SKILL.md の手順 2 で読んだ原則に照らして判断する。

用語ファイルを範囲として扱うと、このスキルが解こうとしている問題がそのまま起きる — 一覧に無い表現が検査されないまま残る (理由づけの正本は [project-config.md](project-config.md) の「`convention_paths` — なぜ基準を外から読むか」)。それでも記録を残すのは、決めた後に同じ語が再び書かれるのを防ぐためである。[#89](https://github.com/akm/claude-plugins/issues/89) では、[#35](https://github.com/akm/claude-plugins/issues/35) で言い換えを決めた語が、その後に書いた文書に 55 か所現れていた。決めた結果を記録する場所が無かったためである。

許容する語を記録するのも同じ理由による。使い続けると決めた語を記録しておかないと、走査のたびに同じ語を候補に挙げ直すことになる。

## 様式

TOML で書く (Python 3.11 以降の標準ライブラリ `tomllib` で読める)。最上位には `[[terms]]` の表の並びだけを書く。

```toml
# このファイルは決めたことの記録であって、検査の範囲ではない。

[[terms]]
pattern = "/効(く|かない|き方)/"
verdict = "avoid"
replacements = ["適用される", "機能する", "役に立つ"]
reason = "#35 で言い換えを決めた。何がどう働くかを書く"
decided_in = "https://github.com/akm/claude-plugins/issues/35"

[[terms]]
pattern = "同じ型の"
verdict = "avoid"
replacements = ["同じ種類の"]
autofix = true
reason = "type の直訳。Go の型と紛らわしい"
decided_in = "https://github.com/akm/claude-plugins/issues/35"

[[terms]]
pattern = "/触(る|ら|り|っ|れ)/"
verdict = "avoid"
replacements = ["変更する"]
exceptions = ["触れるに留める"]
reason = "口語"
decided_in = "https://github.com/akm/claude-plugins/issues/35"

[[terms]]
pattern = "近くの辺"
verdict = "allow"
reason = "用語として定義して使い続けると決めた"
decided_in = "https://github.com/akm/claude-plugins/issues/35"
```

**この例は様式を示すもので、そのまま写さない。** どの語を避け、どの語を許容するかはリポジトリごとに違う。

| キー | 必須 | 意味 |
| --- | --- | --- |
| `pattern` | ○ | 対象の語。`/` で始まり `/` で終わる文字列は正規表現 (JavaScript の正規表現。textlint の規則 textlint-rule-prh と同じ書き方)、それ以外は文字列のまま照合する |
| `verdict` | ○ | `avoid` (避ける) か `allow` (許容する) |
| `reason` | ○ | 決めた理由。読み手が言い換えを選ぶ材料になるように、何が問題なのかを書く |
| `decided_in` | ○ | 決めた場所 (Issue・PR の URL など)。後から理由の正当性を確かめられるようにする |
| `replacements` | 避ける語は ○ | 言い換えの候補。文脈で選ぶものは複数書く。許容する語には書けない |
| `autofix` | | 自動修正してよいか (省略時は `false`)。`true` にできるのは、どの文脈でも同じ言い換えになる語だけで、`replacements` を 1 つに決める。許容する語には書けない |
| `exceptions` | | 避ける語の `pattern` に一致しても問題ない言い方 (例: 「触れるに留める」は言及するの意味)。許容する語には書けない |

様式の誤り (必須のキーが無い・知らないキーがある・同じファイルに同じ `pattern` が 2 つある、など) は、コマンド `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/wording_lint.py terms` がすべて挙げて、終了コード 2 で終わる。

## 複数の用語ファイル

設定キー `terms_paths` には複数のファイルを書ける。**同じ `pattern` が複数のファイルにあれば、後に書いたファイルの項目を使う。** ユーザー単位のファイル (`~` で始まるパス) を先に、リポジトリのファイルを後に書けば、リポジトリの決定が優先される。

**`terms_paths` に書いたファイルは、どれも存在しなければならない。** 無ければ誤りとして報告する — 書いたファイルを読まずに進むと、決めたことが使われないまま検査が終わり、利用者がそれに気づけない。ホームディレクトリのファイルを書くと、そのファイルを持たない人の環境では誤りになるので、共有するリポジトリにはリポジトリの中のファイルだけを書く。

## 決めた語を足す

走査の中で人間が言い換えを決めたら、用語ファイルへの登録を人間に提案する (SKILL.md の手順 5)。登録するかどうかは人間が決める。登録するときは `reason` と `decided_in` を必ず書く — 理由が無いと、後から読む人はなぜ避けるのかを確かめられず、用語ファイルに載っていることだけを判断の根拠にしてしまう (用語ファイルを範囲として扱うことになる)。
