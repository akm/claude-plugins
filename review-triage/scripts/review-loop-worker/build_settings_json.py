"""レビュアの実行に渡す --settings の JSON を組み立てる。
中身の正本は、ファイル review-triage/skills/review-loop/references/worker.md の「サンドボックス」と
「/tmp を含むコマンドを拒否するフック」。

サンドボックスの制限を外す真偽値のキー (allowAppleEvents・filesystem.disabled・network.allowAllUnixSockets) は、
制限する側の値 (false) を書く。--settings は利用者とブランチの設定より優先されるので、それらの設定の値は効かなくなる。
PreToolUse のフック (review-loop-worker/deny_tmp_hook.py) は、中身をフックのコマンドに埋め込む。フックのたびにファイルを
開かないのは、ほかの .py をワーカーが起動時に読み込むのと同じ理由 (プラグインの更新で古いバージョンのディレクトリが消えても、
フックを実行できるように)。
追加の引数の --settings の値を合成した後に、サンドボックス・自動メモリ・フックのキーがワーカーの値のままで、ほかのキーが
enabledPlugins だけであることを確かめる。

引数: 1 つ目は作業場所のパス、2 つ目は python3 の絶対パス、3 つ目はフックのファイル (deny_tmp_hook.py) の中身。
続けて、-w <書き込みを許す場所>・-d <接続を許すドメイン>・-s <追加の引数の --settings の値> の組を並べる。
標準出力: JSON を 1 行。
終了コード: 組み立てられれば 0。合成の後の確かめで食い違えば、理由を標準エラーに出して 1。

呼び出し元: ファイル review-triage/scripts/review-loop-worker.sh の関数 build_settings_json。
語の意味と振る舞いの正本も、同じ worker.md。
"""

import json, shlex, sys

workspace, python3, hook_source, pairs = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
lists = {"-w": [], "-d": [], "-s": []}
for flag, value in zip(pairs[0::2], pairs[1::2]):
    lists[flag].append(value)
settings = {
    "sandbox": {
        "enabled": True,
        "autoAllowBashIfSandboxed": True,
        "allowUnsandboxedCommands": False,
        "failIfUnavailable": True,
        "allowAppleEvents": False,
        "filesystem": {"allowWrite": [workspace] + lists["-w"], "disabled": False},
        "network": {"strictAllowlist": True, "allowedDomains": lists["-d"], "allowAllUnixSockets": False},
    },
    "autoMemoryEnabled": False,
    # Claude Code はフックのコマンドをシェルで実行するので、python3 のパスとフックの中身を 1 つずつシェルの引用符で囲む
    "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
        {"type": "command", "command": f"{shlex.quote(python3)} -I -c {shlex.quote(hook_source)}"},
    ]}]},
}
worker_values = json.loads(json.dumps(settings))
for text in lists["-s"]:
    for key, value in json.loads(text).items():
        if key == "enabledPlugins":
            settings.setdefault("enabledPlugins", {}).update(value)
        else:
            settings[key] = value
if {k: v for k, v in settings.items() if k != "enabledPlugins"} != worker_values:
    print("review-loop-worker: 追加の引数の --settings を合成すると、サンドボックス・自動メモリ・フックの設定がワーカーの値から変わるか、"
          "enabledPlugins 以外のキーが加わる", file=sys.stderr)
    sys.exit(1)
print(json.dumps(settings, ensure_ascii=False))
