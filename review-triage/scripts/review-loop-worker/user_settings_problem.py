"""起動時の確認の 14。利用者の設定ファイル (settings.json) が、コマンドをサンドボックスの外で実行させず、
Unix ソケットへの接続を許さないかを確かめる。

ファイルが JSON として読めないか、空でない sandbox.excludedCommands か sandbox.network.allowUnixSockets を持てば、
起動しない理由とする。ファイルが無ければ何もしない。

引数: 利用者の設定ファイルのパス (ファイルの場所の決め方は呼び出し元が持つ)。
標準出力: 理由があれば、理由 (見つけたキーをすべて) を 1 行。無ければ何も出さない。
終了コード: 理由があれば 1、無ければ 0。

呼び出し元: ファイル review-triage/scripts/review-loop-worker.sh の関数 user_settings_problem。
語の意味と振る舞いの正本は、ファイル review-triage/skills/review-loop/references/worker.md。
"""

import json, sys

path = sys.argv[1]
try:
    with open(path, encoding="utf-8") as f:
        settings = json.load(f)
except FileNotFoundError:
    sys.exit(0)
except (OSError, ValueError) as e:
    print(f"利用者の設定 {path} を JSON として読めない ({e})。検査できないので起動しない")
    sys.exit(1)
if not isinstance(settings, dict):
    print(f"利用者の設定 {path} のトップレベルがオブジェクトではない。検査できないので起動しない")
    sys.exit(1)
sandbox = settings.get("sandbox")
network = sandbox.get("network") if isinstance(sandbox, dict) else None
excluded = sandbox.get("excludedCommands") if isinstance(sandbox, dict) else None
sockets = network.get("allowUnixSockets") if isinstance(network, dict) else None
found = []
if excluded:
    found.append(f"sandbox.excludedCommands ({json.dumps(excluded, ensure_ascii=False)}) がある "
                 "(当たるコマンドはサンドボックスの外で動く)")
if sockets:
    found.append(f"sandbox.network.allowUnixSockets ({json.dumps(sockets, ensure_ascii=False)}) がある "
                 "(サンドボックスの中の Bash が、当たる Unix ソケットに接続できる。Docker のソケットなら、"
                 "コンテナを通してサンドボックスの外に書ける)")
if found:
    print(f"利用者の設定 {path} に " + "。".join(found) + "。当たったキーを消すか空にしてから起動し直す")
    sys.exit(1)
