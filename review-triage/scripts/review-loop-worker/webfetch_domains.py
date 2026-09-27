"""起動時の確認の 15 (表示)。利用者の設定ファイルの許可の規則 (permissions.allow) のうち、WebFetch(domain:<ドメイン>) の形のものから、
ドメインを読む。

引数: 利用者の設定ファイルのパス。起動時の確認の 14 の後に呼ぶので、ファイルは無いか JSON として読める。
標準出力: ドメインを、重ねずに 1 行に 1 つずつ。ファイルが無ければ何も出さない。
終了コード: 0。14 の後にファイルを読めなくなったときなどは、Python の例外で 0 以外になる (呼び出し元は終了コードを見ない)。

呼び出し元: ファイル review-triage/scripts/review-loop-worker.sh の関数 webfetch_domains。
語の意味と振る舞いの正本は、ファイル review-triage/skills/review-loop/references/worker.md。
"""

import json, re, sys

try:
    with open(sys.argv[1], encoding="utf-8") as f:
        settings = json.load(f)
except FileNotFoundError:
    sys.exit(0)
permissions = settings.get("permissions") if isinstance(settings, dict) else None
allow = permissions.get("allow") if isinstance(permissions, dict) else None
domains = []
for rule in allow if isinstance(allow, list) else []:
    m = re.fullmatch(r"\s*WebFetch\(domain:(.+)\)\s*", rule) if isinstance(rule, str) else None
    if m and m.group(1).strip() not in domains:
        domains.append(m.group(1).strip())
for d in domains:
    print(d)
