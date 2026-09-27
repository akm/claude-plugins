"""ワーカーのバージョンを、プラグインのファイル review-triage/.claude-plugin/plugin.json から読んで標準出力に出す。

プラグインのディレクトリは、ワーカーのスクリプトの実体パス (シンボリックリンクを解決した絶対パス) から決める
(スクリプトがあるディレクトリ scripts の親)。環境変数 CLAUDE_PLUGIN_ROOT は、人間が端末で起動するワーカーには
設定されないので使わない。

引数: ワーカーのスクリプト (review-loop-worker.sh) のパス。
標準出力: バージョンを 1 行。
終了コード: 読めれば 0。ファイルを読めないか、キー version の値が空でない文字列でなければ、理由を標準エラーに出して 1。

呼び出し元: ファイル review-triage/scripts/review-loop-worker.sh の関数 read_worker_version。
語の意味と振る舞いの正本は、ファイル review-triage/skills/review-loop/references/worker.md。
"""

import json, os, sys

root = os.path.dirname(os.path.dirname(os.path.realpath(sys.argv[1])))
path = os.path.join(root, ".claude-plugin", "plugin.json")
try:
    with open(path, encoding="utf-8") as f:
        version = json.load(f).get("version")
except (OSError, ValueError, AttributeError) as e:
    print(f"review-loop-worker: プラグインのファイル {path} から版を読めない ({e})", file=sys.stderr)
    sys.exit(1)
if not isinstance(version, str) or not version:
    print(f"review-loop-worker: プラグインのファイル {path} に版 (version) が無い", file=sys.stderr)
    sys.exit(1)
print(version)
