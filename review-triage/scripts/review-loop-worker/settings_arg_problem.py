"""起動時の確認の 13。追加の引数 (-- の後) の --settings の値が、enabledPlugins だけを持つ JSON かを確かめる。

値が JSON として読めて、トップレベルのキーが enabledPlugins だけで、その値がプラグイン名から真偽値への対応であれば受け付ける。

引数: --settings の値。
標準出力: 受け付けないときは、理由を 1 行。受け付けるときは何も出さない。
終了コード: 受け付けるなら 0、受け付けないなら 1。

呼び出し元: ファイル review-triage/scripts/review-loop-worker.sh の関数 settings_arg_problem。
語の意味と振る舞いの正本は、ファイル review-triage/skills/review-loop/references/worker.md。
"""

import json, sys

try:
    value = json.loads(sys.argv[1])
except ValueError as e:
    print(f"JSON として読めない ({e})")
    sys.exit(1)
if not isinstance(value, dict):
    print("トップレベルが、キーに enabledPlugins だけを持つオブジェクトではない")
    sys.exit(1)
if list(value) != ["enabledPlugins"]:
    print(f"トップレベルのキーが enabledPlugins だけではない (キー: {', '.join(value) or '無し'})")
    sys.exit(1)
plugins = value["enabledPlugins"]
if not isinstance(plugins, dict) or not all(isinstance(v, bool) for v in plugins.values()):
    print("enabledPlugins の値が、プラグイン名から真偽値 (true / false) への対応ではない")
    sys.exit(1)
