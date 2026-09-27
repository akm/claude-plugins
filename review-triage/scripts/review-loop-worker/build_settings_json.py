"""レビュアの実行に渡す --settings の JSON を組み立てる。
中身の正本は、ファイル review-triage/skills/review-loop/references/worker.md の「サンドボックス」。

サンドボックスの制限を外す真偽値のキー (allowAppleEvents・filesystem.disabled・network.allowAllUnixSockets) は、
制限する側の値 (false) を書く。--settings は利用者とブランチの設定より優先されるので、それらの設定の値は効かなくなる。
追加の引数の --settings の値を合成した後に、サンドボックスと自動メモリのキーがワーカーの値のままで、ほかのキーが
enabledPlugins だけであることを確かめる。

引数: 1 つ目は作業場所のパス。続けて、-w <書き込みを許す場所>・-d <接続を許すドメイン>・-s <追加の引数の --settings の値> の組を並べる。
標準出力: JSON を 1 行。
終了コード: 組み立てられれば 0。合成の後の確かめで食い違えば、理由を標準エラーに出して 1。

呼び出し元: ファイル review-triage/scripts/review-loop-worker.sh の関数 build_settings_json。
語の意味と振る舞いの正本も、同じ worker.md。
"""

import json, sys

workspace, pairs = sys.argv[1], sys.argv[2:]
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
}
worker_values = json.loads(json.dumps(settings))
for text in lists["-s"]:
    for key, value in json.loads(text).items():
        if key == "enabledPlugins":
            settings.setdefault("enabledPlugins", {}).update(value)
        else:
            settings[key] = value
if {k: v for k, v in settings.items() if k != "enabledPlugins"} != worker_values:
    print("review-loop-worker: 追加の引数の --settings を合成すると、サンドボックスか自動メモリの設定がワーカーの値から変わるか、"
          "enabledPlugins 以外のキーが加わる", file=sys.stderr)
    sys.exit(1)
print(json.dumps(settings, ensure_ascii=False))
