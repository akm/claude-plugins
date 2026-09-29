"""回の処理の手順 7。複製の .claude/settings.json と .claude/settings.local.json に、コマンドをサンドボックスの外で実行させる設定と、
Unix ソケットへの接続を許す設定と、localhost の bind と接続を許す設定が無いかを確かめる。

どちらかのファイルが JSON として読めないか、空でない sandbox.excludedCommands か sandbox.network.allowUnixSockets を持つか、
sandbox.network.allowLocalBinding が偽でない値 (真偽値でない値を含む) を持てば、そのファイルと理由を出す。無いファイルは飛ばす。

引数: 複製のパス。
標準出力: 理由を 1 行に 1 つ (clone settings (<ファイル>: <理由>) の形で)。理由が無ければ何も出さない。
終了コード: 理由があれば 1、無ければ 0。

呼び出し元: ファイル review-triage/scripts/review-loop-worker.sh の関数 clone_settings_problem。
語の意味と振る舞いの正本は、ファイル review-triage/skills/review-loop/references/worker.md。
"""

import json, os, stat, sys

tree = sys.argv[1]
problems = []
for rel in (".claude/settings.json", ".claude/settings.local.json"):
    path = os.path.join(tree, rel)
    try:
        # シンボリックリンクなら先を読む (Claude Code もそうする)。通常のファイルでなければ読まない (/dev/zero などで止まらないように)
        if not stat.S_ISREG(os.stat(path).st_mode):
            problems.append(f"{rel}: not a regular file")
            continue
        with open(path, encoding="utf-8") as f:
            settings = json.load(f)
    except FileNotFoundError:
        continue
    except (OSError, ValueError) as e:
        problems.append(f"{rel}: not readable as JSON ({e})")
        continue
    if not isinstance(settings, dict):
        problems.append(f"{rel}: top level is not an object")
        continue
    sandbox = settings.get("sandbox")
    network = sandbox.get("network") if isinstance(sandbox, dict) else None
    excluded = sandbox.get("excludedCommands") if isinstance(sandbox, dict) else None
    sockets = network.get("allowUnixSockets") if isinstance(network, dict) else None
    binding = network.get("allowLocalBinding", False) if isinstance(network, dict) else False
    if excluded:
        problems.append(f"{rel}: sandbox.excludedCommands is not empty ({json.dumps(excluded, ensure_ascii=False)})")
    if sockets:
        problems.append(f"{rel}: sandbox.network.allowUnixSockets is not empty ({json.dumps(sockets, ensure_ascii=False)})")
    if binding is not False:
        problems.append(f"{rel}: sandbox.network.allowLocalBinding is not false ({json.dumps(binding, ensure_ascii=False)})")
for p in problems:
    print(f"clone settings ({p})")
sys.exit(1 if problems else 0)
