---
title: "プラグインは自分の配布元を実行時に知れない"
date: 2026-08-01
module: pr-teeth
problem_type: convention
category: conventions
component: tooling
severity: medium
applies_when:
  - "Claude Code プラグインが配布元ごとに分かれた場所へ設定を保存する"
  - "実行中のコードが自分の入手元をパスに使いたい"
  - "動作はするが公式に保証されていない経路しか見つからない"
tags:
  - claude-code-plugin
  - plugin-root
  - configuration
  - unofficial-api
---

## Context

Claude Code のプラグインが、利用者ごとの設定・蓄積データをローカルに保存したい場合、
その置き場所を決める必要がある。同名のプラグインが複数のマーケットプレイスから
配布されうるため、**配布元ごとに設定を分ける**のが素直な設計になる。

```
$HOME/config/<host>/<owner>/<repo>/<plugin>/
```

このとき「実行中のプラグインは自分がどこから配布されたかを知れるか」が問題になる。
`pr-teeth` プラグインの実装にあたって調査したところ、**公式な手段は存在しなかった**
(2026-08 時点)。

判断を誤ると症状が分かりにくい。パスが変われば設定と蓄積データを見失い、利用者からは
「積み上げた用語集が消えた」という形で現れる。原因の特定が難しい部類の壊れ方になる。

## Guidance

**配布元をパスに使う設計では、値を実行時に推定せず、プラグイン内にリテラルで持たせる。**

調査で確認した事実:

| 手段 | 公式か | 得られるもの |
| --- | --- | --- |
| `${CLAUDE_PLUGIN_ROOT}` | **公式** (plugins-reference に記載) | **インストール先パスのみ。配布元は含まない** |
| キャッシュのパス構造から2階層上を取る | 非公式 (内部実装) | マーケットプレイス名 |
| `~/.claude/plugins/known_marketplaces.json` を引く | 非公式 (内部実装) | マーケットプレイス名 → リポジトリ |

後者2つを組み合わせれば逆引きは**実際に動作する**。しかしどちらも公式ドキュメントに
記載がなく、変更されても告知されない。動くことと、依存してよいことは別である。

補足として、`${CLAUDE_PLUGIN_ROOT}` の展開場所には注意が要る。これは SKILL.md の
本文に書けばハーネスが文字列置換するもので、**シェルの環境変数として読めるとは限らない**。
実際に配布されているプラグインの SKILL.md も、本文にリテラルで書く形で使っている。

リテラルで持たせる場合の運用ルール:

- **書き換え箇所は1箇所にまとめ、そこが書き換え対象であることをコメントで明示する。**
  fork 時に一部だけ書き換えると、コマンドによって別のディレクトリを見る状態になる。
- 環境変数による上書き経路 (`PR_TEETH_CONFIG_DIR` 等) を用意しておく。
  リテラル値が実環境に合わない場合の逃げ道になる。
- 複数の SKILL.md がある場合、値が一致することを検証するテストを置く。

## Why This Matters

プラグインは**自分の配布元をビルド時に知っている**。実行時に推定する必要が
そもそも無い。にもかかわらず推定に頼ると、非公式な内部実装に依存する対価だけを
払うことになる。

壊れ方も悪い。パス解決が変わっても例外は出ず、単に「別のディレクトリを見る」だけなので、
プラグインは正常に動いているように見える。利用者に見えるのは蓄積データの消失で、
そこから原因に辿り着くのは難しい。

一般化すると、**「動くから使う」と「公式に保証されているから依存する」を区別する**という
話になる。逆引き経路は実際に動作を確認したうえで採用しなかった。壊れたときの
症状が分かりにくいほど、非公式な経路に賭ける価値は下がる。

## When to Apply

- Claude Code プラグインが、配布元ごとに分かれた場所へ設定や蓄積データを保存する場合
- より一般に、**実行中のコードが「自分がどこから来たか」をパスに使いたい**場合
  (パッケージの配布元、インストール経路、テナント識別子など)
- 調査の結果「動くが非公式」な経路しか見つからず、かつ壊れたときの症状が
  静かなデータ損失になる場合

逆に、推定が妥当なケースもある。壊れたときに即座に例外として現れ、
利用者が原因を特定できるなら、非公式経路を試す判断はありうる。
今回は症状が静かすぎたので採らなかった。

## Examples

**採らなかった方式** (逆引き。動作はするが非公式):

```python
# CLAUDE_PLUGIN_ROOT = ~/.claude/plugins/cache/<marketplace>/<plugin>/<version>
marketplace = os.path.basename(os.path.dirname(os.path.dirname(plugin_root)))
known = json.load(open(os.path.expanduser("~/.claude/plugins/known_marketplaces.json")))
repo = known[marketplace]["source"]["repo"]   # → "akm/claude-plugins"
```

パス構造と `known_marketplaces.json` の両方が内部実装。どちらかが変わると
設定と蓄積データを見失う。

**採った方式** (SKILL.md にリテラルで持たせ、CLI に渡す):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pr_teeth.py" prepare \
  --plugin-source "github.com/akm/claude-plugins"
```

```python
def config_dir(plugin_source):
    """設定ディレクトリの絶対パスを返す。

    plugin_source: 配布元を "<host>/<owner>/<repo>" で表した文字列。
                   SKILL.md にリテラルで書かれた値を渡す。
    """
    override = os.environ.get(CONFIG_DIR_ENV, "").strip()
    if override:
        return os.path.abspath(os.path.expanduser(override))
    source = (plugin_source or "").strip().strip("/")
    if not source:
        raise ValueError("plugin_source が空です。SKILL.md のリテラル値を渡すか、"
                         "環境変数 " + CONFIG_DIR_ENV + " を設定してください。")
    return os.path.join(os.path.expanduser("~"), "config", source, "pr-teeth")
```

空文字を黙って受けず `ValueError` にしているのは、変な場所に書き込むより
はっきり失敗させるため。

**残った課題**: この方式でも、値が複数の SKILL.md に散在すると fork 時の
書き換え漏れが起きる。実際に `pr-teeth` では12箇所に重複しており、
「1箇所にまとめる」という自らの設計方針に違反した状態になった
(別途 Issue 化して対応予定)。**リテラルで持つ判断と、それを1箇所に保つ実装は別問題**で、
後者を怠ると前者の利点が失われる。
