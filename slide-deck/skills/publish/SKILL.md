---
name: publish
description: 構成案 (outline.md) と資料ごとのスクリプト deck.ts から、Google スライドの資料を作る・直す。内容が変わったスライドだけを作り直し、足したスライドを挿入し、消したスライドを消し、順序を並べ替え、発表者ノートを入れて、ノートと画像で確認する。「Google スライドに反映して」「スライドを直したので Google スライドも更新して」「slide-deck:publish を実行して」のような依頼や、スキル slide-deck:build の後に使う。Google スライドのコネクタが要る。
---

# slide-deck:publish: Google スライドに反映する

構成案 `outline.md` と資料ごとのスクリプト `deck.ts` から、Google スライドの資料を作る、または直す。直すときは、内容が変わったスライドだけを同じ位置に作り直し、ほかのスライドと、利用者が Google スライドで足したスライドはそのまま残す。

コネクタの使い方・`build/presentation.json` の書き方・指示のファイルの送り方・ID の形・Google スライドの API への対処は、ファイル [references/google-slides.md](../../references/google-slides.md) を読んでから行う。入口のサブコマンドの引数・出力・終了コードは、`node "${CLAUDE_PLUGIN_ROOT}/src/cli.ts" <サブコマンド> --help` の出力を参照する。

この文書で使う語:

- **資料のディレクトリ**・**キー**: ファイル [references/outline-format.md](../../references/outline-format.md) の説明のとおり。
- **コネクタ**・**資料の ID**・**指示のファイル**: ファイル [references/google-slides.md](../../references/google-slides.md) の説明のとおり。
- **作り直す・消す・並べ替える**: サブコマンド `requests` が、資料のスライドと構成案を比べて決める作業。作り直すのは題名・一言・図が変わったスライド、消すのは構成案から消したキーのスライド、並べ替えるのは構成案で順序を変えたスライド。

## 手順

例は、プラグインに同梱した見本の資料 (ディレクトリ [examples/sample/](../../examples/sample/)。題材は「キャッシュのしくみ」) を、資料のディレクトリ `tmp/slides/cache` で、新しい Google スライドの資料に作る場合で示す。

1. **前提を確認する**:
   - スキル `slide-deck:build` の手順 1 と同じく `setup status` を実行し、ライブラリが入っていなければ、承認を得てから入れる。
   - 資料のディレクトリは、この会話で使ったものを使い、無ければ利用者に質問する。
   - スキル `anthropic-skills:google-workspace` を読み込み、その書き込みの規則 (読み込んでから書く・`revisionId` を付けて送る・書いた後に読み込んで確認する・利用者が頼んでいないファイルをゴミ箱に移さない) に従う。そのスキルの、資料のデザインの規則と補助のスクリプトは使わない (デザインは `deck.ts` が決める)。スキルが無ければ、何が無いかを伝えて中断する。
2. **コネクタを確認する**: ファイル [references/google-slides.md](../../references/google-slides.md) の節「使うツール」のとおりに、Google スライドと Google ドライブのコネクタのツールがあるかを確認する。Google スライドのコネクタが無ければ中断し、有効にするよう利用者に求める。Google スライドの代わりに PowerPoint のファイル `build/deck.pptx` を使うかは、利用者が選ぶ。利用者が選んだときだけ、スキル `slide-deck:build` で作ったファイルを渡す。
3. **構成案の資料の情報を読む**: サブコマンド `check-outline` を実行する。

   ```bash
   node "${CLAUDE_PLUGIN_ROOT}/src/cli.ts" check-outline tmp/slides/cache
   ```

   出力の「Google スライド」の行から URL と資料の ID を、「slide-deck の版」の行から構成案に記録した版と今の版を読む。終了コード 1 なら、構成案の書式の誤りを直してから (スキル `build` の手順 5 と同じ)、もう一度実行する。終了コード 2 なら、出力を伝えて中断する。
4. **資料が無ければ作る**: 「Google スライド: 無い」なら、ファイル [references/google-slides.md](../../references/google-slides.md) の節「新しい資料を作る」のとおりに空の資料を作り、すぐにサブコマンド `write-info` で URL を構成案に書き込む。

   ```bash
   node "${CLAUDE_PLUGIN_ROOT}/src/cli.ts" write-info tmp/slides/cache --google-slides "https://docs.google.com/presentation/d/<ファイルの ID>/edit"
   ```

   URL があれば、その資料を使う。資料を作り直さない。
5. **すべて作り直すかを決める**: 構成案に記録した版があり、今の版と違うときは、すべてのスライドを作り直すかを利用者に質問する。プラグインの版が変わると、指示の作り方が変わっていても、スライドの ID (ハッシュ値) は変わらず、作り直されないため。作り直すと、利用者が Google スライドで手で直した内容は、キーのあるすべてのスライドで失われることも伝える。記録した版が無いか、今の版と同じなら、質問しない。
6. **読み込み、指示のファイルを書く**: 資料を読み込んで `build/presentation.json` に書き (同じ文書の節「資料を読み込み、`build/presentation.json` に書く」)、サブコマンド `requests` を実行する。手順 5 ですべて作り直すことになったら、`--recreate-all` を付ける。

   ```bash
   node "${CLAUDE_PLUGIN_ROOT}/src/cli.ts" requests tmp/slides/cache
   ```

   - **終了コード 0**: 見本の資料を新しい資料に作るときの出力は次のとおり (パスは短くした)。

     ```text
     検査の指摘は無い (スライド 4 枚)
     キーごとの作業:
       read-path: 作る (sd_read-path_6a6952b508)
       hit-miss: 作る (sd_hit-miss_fe17e34a97)
       stale: 作る (sd_stale_5206d1f52b)
       expire: 作る (sd_expire_271e967d07)
     新しく作った資料の、最初からあるスライドを消す: p
     並べ替え: なし
     配色を変えるマスター: simple-light-2
     ノートを入れ直すキー: なし
     送る指示のファイル (この順に送る。どのファイルも、送る直前に読み込んだ資料の revisionId を付ける):
       tmp/slides/cache/build/requests-1.json (指示 68 個、16471 字)
       tmp/slides/cache/build/requests-2.json (指示 82 個、18114 字)
       tmp/slides/cache/build/requests-3.json (指示 33 個、8033 字)
     作る・作り直すスライドのノートは、指示を送った後に資料を再度読み込み、もう一度 requests を実行すると、ノートの指示のファイルに入る
     ```

   - **終了コード 1**: `check` の指摘か、図形が多すぎるスライドがある。スキル `build` の手順 5 と同じく直し、`build` からやり直す。
   - **終了コード 2**: `build/presentation.json` の形が違うと出たら、読み込みの項目の指定を確認して、読み込みからやり直す。ほかは、出力をそのまま伝えて中断する。
7. **作り直す・消す・並べ替える前に承認を得る**: 出力に、作り直すキー・消すスライド・並べ替え (回数が 0 でない) のどれかがあれば、送る前に、それぞれの対象のキーの一覧を示し、作り直すスライドと消すスライドで、利用者が Google スライドで手で直した内容が失われることを伝えて、承認を得る。承認を得られなければ、何も送らずに中断する。作るスライド・ノート・マスターの配色・新しい資料の最初からあるスライドを消すことだけなら、質問しない。後の繰り返しで、承認を得ていないキーが出たら、もう一度承認を得る。
8. **指示のファイルを送る**: 同じ文書の節「指示のファイルを送る」のとおりに、出力の先頭のファイルだけを `revisionId` を付けて送り、手順 6 (読み込み → `build/presentation.json` に書く → `requests`) に戻る。`requests` が「送る指示は無い」と示すまで繰り返す。スライドを作った後の繰り返しで、発表者ノートの指示のファイルが出る。`--recreate-all` のときだけは、`requests` を 1 回だけ実行して、書いたスライドの指示のファイルを順にすべて送り、その後は `--recreate-all` を付けずに繰り返す。送ったときの誤りの扱いは、同じ文書の節「送ったときの誤り」のとおり。
9. **発表者ノートを確認する**: 最後の繰り返しの `requests` の出力が「ノートを入れ直すキー: なし」で「送る指示は無い」なら、資料から読み込んだ発表者ノートの文が、キーごとに構成案の文と一致している。続けて、サブコマンド `write-info` の `--plugin-version` で、今の版を構成案に記録する。

   ```bash
   node "${CLAUDE_PLUGIN_ROOT}/src/cli.ts" write-info tmp/slides/cache --plugin-version
   ```

10. **画像で確認する**: 同じ文書の節「画像で確認する」のとおりに、スライドの画像を 6 枚ずつ 1 枚にまとめて見る。最後の 1 文字だけの行・はみ出し・位置のずれを見つけたら、利用者に示し、`deck.ts` か構成案を直して (構成案の文を変えるときは利用者の承認を得て)、スキル `slide-deck:build` からやり直す。
11. **報告する**: 資料の題名を、Google スライドの URL へのリンクにして伝え、URL は前と変わらないことを伝える。作った・作り直した・消した・並べ替えたキーを伝える。スライド番号は付けていないので、メニューの「挿入 > スライド番号」で付けるよう伝える。画像で確認できなかったことがあれば、それも伝える。

## このスキルがしないこと

- `revisionId` を付けずに送ること。指示のファイルの中身を手で変えて送ること。
- 作り直す・消す・並べ替えるを、対象のキーの一覧を示して承認を得ずに行うこと。
- コネクタが無いときに、PowerPoint のファイルを Google ドライブにアップロードして変換するなど、別の方法で作ること。
- 構成案に URL があるのに、新しい資料を作ること。資料をゴミ箱に移すこと。
- スライド番号を API で付けること。
- 構成案の Google スライドの URL と slide-deck の版の行を、サブコマンド `write-info` を使わずに書くこと。
- `deck.ts` を書くこと、PowerPoint のファイルを作ること。スキル `build` が行う。
