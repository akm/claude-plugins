"""設定ディレクトリと出力言語の解決（pr-teeth プラグイン）。

CONCEPTS.md 第5節の実装。

設定ディレクトリを実行時に推定しないのが要点。実行中のプラグインへ配布元を伝える
公式な手段が無いため、配布元は呼び出し側（SKILL.md）からリテラルで渡してもらう。
`known_marketplaces.json` やキャッシュのパス構造からの逆引きは可能だが、どちらも
非公式・内部実装であり、変わると設定と用語集を見失う。ユーザーからは「積み上げた
用語集が消えた」ように見えるため、その経路は採らない。
"""

import os

# 言語未設定時の既定（CONCEPTS.md 第5.2節）。
DEFAULT_LANGUAGE = "ja"

# 設定ディレクトリを直接指定する環境変数。リテラルの配布元が実環境に合わない場合の逃げ道。
CONFIG_DIR_ENV = "PR_TEETH_CONFIG_DIR"


def config_dir(plugin_source):
    """設定ディレクトリの絶対パスを返す。

    plugin_source: 配布元を "<host>/<owner>/<repo>" で表した文字列。
                   SKILL.md にリテラルで書かれた値を渡す（第5.1節）。
    """
    override = os.environ.get(CONFIG_DIR_ENV, "").strip()
    if override:
        return os.path.abspath(os.path.expanduser(override))
    source = (plugin_source or "").strip().strip("/")
    if not source:
        raise ValueError(
            "plugin_source が空です。SKILL.md のリテラル値（例 github.com/akm/claude-plugins）"
            "を渡すか、環境変数 " + CONFIG_DIR_ENV + " を設定してください。"
        )
    return os.path.join(os.path.expanduser("~"), "config", source, "pr-teeth")


def resolve_language(repo, user_config, repos_config, cli_lang=None):
    """PR 1件の出力言語を決める（第5.3節。優先度: 高→低）。

    1. 実行時引数 cli_lang
    2. repos.yml の repos.<owner>/<repo>.language
    3. config.yaml の language
    4. 組み込み既定 "ja"

    無人実行では cli_lang が None になり、2〜4 段だけで解決する（第14節）。
    """
    if cli_lang:
        cli_lang = cli_lang.strip()
        if cli_lang:
            return cli_lang

    entry = ((repos_config or {}).get("repos") or {}).get(repo) or {}
    repo_lang = (entry.get("language") or "").strip()
    if repo_lang:
        return repo_lang

    user_lang = ((user_config or {}).get("language") or "").strip()
    if user_lang:
        return user_lang

    return DEFAULT_LANGUAGE


def default_language(user_config, cli_lang=None):
    """ユーザー既定の言語。通知の地の文や HTML の lang 属性に使う（第5.3節）。

    リポジトリ単位の設定は個々の PR にしか効かないため、ここでは参照しない。
    """
    if cli_lang:
        cli_lang = cli_lang.strip()
        if cli_lang:
            return cli_lang
    user_lang = ((user_config or {}).get("language") or "").strip()
    return user_lang or DEFAULT_LANGUAGE
