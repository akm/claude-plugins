---
name: build
description: 構成案 (outline.md) の図の説明から資料ごとのスクリプト deck.mts を書き、検査して、PowerPoint のファイル build/deck.pptx を作る。ライブラリが入っていなければ、利用者の承認を得てからキャッシュのディレクトリに入れる。「構成案から PowerPoint を作って」「図を直したので作り直して」「slide-deck:build を実行して」のような依頼や、スキル slide-deck:outline の後に使う。Google スライドへの反映はスキル slide-deck:publish が行う。
---

# slide-deck:build: PowerPoint のファイルを作る

構成案 `outline.md` の図の説明 (`- 図:` の行) から、資料ごとのスクリプト `deck.mts` を書き、検査してから、PowerPoint のファイル `build/deck.pptx` を作る。題名・一言・発表者ノートは構成案から読むので、`deck.mts` には書かない。

`deck.mts` の書き方は、ファイル [references/deck-script.md](../../references/deck-script.md) を読んでから書く。構成案の書式は、ファイル [references/outline-format.md](../../references/outline-format.md)。入口のサブコマンドの引数・出力・終了コードは、`node "${CLAUDE_PLUGIN_ROOT}/src/cli.ts" <サブコマンド> --help` の出力を参照する。

この文書で使う語:

- **資料のディレクトリ**: 1 つの資料の `outline.md` と `deck.mts` があるディレクトリ。
- **キャッシュのディレクトリ**: ライブラリ (Node.js の `node_modules` と Python の venv) を入れる、利用者のディレクトリ。場所は `setup status --help` が示す。
- **pptx のスキル**: Claude のデスクトップアプリが配る、Anthropic の公式のスキル `anthropic-skills:pptx`。テーマの色を書き込むファイル `scripts/apply_theme.js` と、形式を検査するファイル `scripts/office/validate.py` を使う。

## 手順

例は、プラグインに同梱した見本の資料 (ディレクトリ [examples/sample/](../../examples/sample/)。題材は「キャッシュのしくみ」) を、資料のディレクトリ `tmp/slides/cache` に作った場合で示す。

1. **ライブラリを確認する**: まず `node --version` で、Node.js 24 以上があることを確認する。コマンド `node` が無いか、24 より前の版なら、Node.js 24 以上を入れるよう利用者に伝えて中断する (.ts のファイルを実行できない版では、次のサブコマンドが版を確認する前に失敗するため)。続けて、サブコマンド `setup status` を実行する。

   ```bash
   node "${CLAUDE_PLUGIN_ROOT}/src/cli.ts" setup status
   ```

   - **終了コード 0**: ライブラリは入っている。質問せずに手順 2 に進む。
   - **終了コード 1**: 入れるものがある。出力の「取得するもの」と、キャッシュのディレクトリを利用者に示し、入れてよいか承認を得る。承認を得たら `setup install` を実行する。`setup install` が終了コード 2 なら、出力をそのまま伝えて中断する。承認を得られなければ中断する。
   - **終了コード 2**: 入れられない。出力の「入れられない理由」(uv か npm が無い・Node.js が古い・`node_modules` が壊れているなど) と直し方を利用者に伝えて中断する。別の方法 (pip や npm でほかの場所に入れるなど) を試さない。
2. **資料のディレクトリを決める**: この会話でスキル `outline` が決めたディレクトリを使う。会話に無ければ、利用者に質問する。`outline.md` が無ければ、スキル `slide-deck:outline` で構成案を作るよう伝えて中断する。
   - 資料のディレクトリに `deck.ts` があり、`deck.mts` が無ければ、slide-deck の 0.1.0 で作った資料。今のファイル名は `deck.mts` (理由は、ファイル [references/deck-script.md](../../references/deck-script.md) の節「形」)。`check` は、`deck.ts` があると終了コード 2 で終了する。名前を `deck.mts` に変えてよいか利用者に質問し、承認を得てから変える。資料のディレクトリを git で管理していれば `git mv` で変える。承認を得られなければ中断する。
3. **pptx のスキルを読み込む**: スキル `anthropic-skills:pptx` を読み込み、示されるスキルのディレクトリ (Base directory) を、手順 6 で使う。読み込むのはディレクトリを得るためで、そのスキルの手順で資料を作り直さない。スキルが無いときは、Claude のデスクトップアプリが配る pptx のスキルが要ること (マーケットプレイスで配る版には `scripts/apply_theme.js` が無いので使えない) を伝えて中断する。
4. **`deck.mts` を書く**: 構成案のキーごとの図の説明から、資料のディレクトリの `deck.mts` を書く。
   - テーマの 6 つのアクセント色に、資料で使う意味 (例: アプリケーション・キャッシュ・DB・ヒット・ミス・注意) を割り当てる。
   - 図の中の文字にも、利用者とプロジェクトの文章の規約を当てる。
   - 直すときは、構成案で変わったキーの図だけを直し、足したキーの図を足し、消したキーの図を消す。変えていないキーの図は変えない (Google スライドで作り直しになるため)。
5. **検査する**: サブコマンド `check` を実行する。

   ```bash
   node "${CLAUDE_PLUGIN_ROOT}/src/cli.ts" check tmp/slides/cache
   ```

   - **終了コード 0**: 見本の資料では「検査の指摘は無い (スライド 4 枚)」と出る。手順 6 に進む。
   - **終了コード 1**: 指摘の種類ごとに直し、もう一度実行する。
     - **構成案の書式の誤り**: 書式のとおりに `outline.md` を直す。ただし、Google スライドの行か slide-deck の版の行の値の誤りは、直す前に、ファイル [references/outline-format.md](../../references/outline-format.md) の節「資料の題名と資料の情報」のとおりに利用者に質問する。
     - **【提案】が付いたままのスライド**: 採否は利用者が決める。スキル `slide-deck:outline` の手順で採否を質問する。
     - **tsc・eslint の指摘、`deck.mts` を実行できない、テーマの誤り、キーの不一致**: `deck.mts` を直す。構成案のキーの誤りなら、利用者に確認してから `outline.md` を直す。
     - **文字が箱からはみ出しそうな箇所**: 図の要素なら、`deck.mts` の箱を広げるか、文を縮める。題名・一言を縮めるときは、案を示して利用者の承認を得てから `outline.md` を直す。
   - **終了コード 2**: 出力 (標準エラー出力) をそのまま利用者に伝えて中断する。ライブラリが入っていないと出たら、手順 1 に戻る。
6. **PowerPoint のファイルを作る**: 手順 3 のディレクトリを `--pptx-skill` に渡して、サブコマンド `pptx` を実行する。

   ```bash
   node "${CLAUDE_PLUGIN_ROOT}/src/cli.ts" pptx tmp/slides/cache --pptx-skill "<pptx のスキルのディレクトリ>"
   ```

   - **終了コード 0**: 見本の資料の出力は次のとおり (パスは短くした)。

     ```text
     検査の指摘は無い (スライド 4 枚)
     PowerPoint のファイルを書いた: tmp/slides/cache/build/deck.pptx
     apply_theme.js の出力:
       Theme written to tmp/slides/cache/build/deck.pptx
     validate.py の出力:
       All validations PASSED!
     ```

   - **終了コード 1**: `check` の指摘なら手順 5 と同じく直す。`validate.py` が形式の誤りを見つけたときは、出力を利用者に伝えて中断する (`build/deck.pptx` は調べられるよう残っている)。ツールの不具合の可能性があるので、ファイルを手で直さない。
   - **終了コード 2**: 出力をそのまま利用者に伝えて中断する。pptx のスキルのファイルが無いと出たら、示されたパスを伝える。
7. **報告する**: `build/deck.pptx` のパスと、アクセント色に割り当てた意味を伝える。Google スライドにも作るなら、スキル `slide-deck:publish` を使うことを伝える。資料のディレクトリの `build/` は、ツールが中身を `*` にしたファイル `.gitignore` を書くので、コミットに入らない。

## このスキルがしないこと

- ライブラリを、利用者の承認を得ずに入れること。uv・Node.js・ライブラリ・pptx のスキルが無いときに、別の方法を試すこと。
- 0.1.0 で作った資料の `deck.ts` の名前を、利用者の承認を得ずに変えること。`deck.ts` と `deck.mts` の両方があるときに、どちらかを消すこと (`check` の出力を伝えて、利用者が決める)。
- 題名・一言・発表者ノートを `deck.mts` に書くこと。構成案の内容を、利用者の承認を得ずに変えること。
- 【提案】の採否を決めること。
- `build/` の生成したファイル (`deck.pptx`・`tsconfig.json` など) を手で直すこと。
- Google スライドに書き込むこと。スキル `publish` が行う。
