"""レビュアの実行のログ (stream-json) から、実効モデル・skill の呼び出し・拒否された呼び出し・実効の権限モード・
サンドボックスが止めた確認を読む (回の終わりの処理の 2)。
読み方の正本は、ファイル review-triage/skills/review-loop/references/worker.md の「ログの読み方」。

引数: ログのパス。読めなければ、空のログとして扱う。
標準出力: 次の行。値はどれも 1 行 (改行を含まない)。読めない値は unknown にする。
  1 行目: 実効モデルの名前 / 2 行目: skill_called / 3 行目: 拒否の件数 / 4 行目: 拒否されたツールの名前の列 (JSON) /
  5 行目: 実効の権限モード / 6 行目: サンドボックスが止めた件数 /
  7 行目から: 止められた呼び出しごとに、コマンドと文面の 2 行 (どちらも先頭 200 文字まで)。
  サンドボックスが止めた件数が unknown なら、7 行目からの行は出さない。
終了コード: 0。

呼び出し元: ファイル review-triage/scripts/review-loop-worker.sh の関数 read_log_facts。
語の意味と振る舞いの正本も、同じ worker.md。
"""

import json, re, sys

# 印の YAML に書く値を 1 行に直すときに空白にする文字: 改行とタブを含む制御文字・行と段落の区切りの文字・
# 対になっていないサロゲート (JSON の \ud800 のように、2 つ組で 1 文字を表す符号の片方だけをエスケープで書いたもの)・
# 文字として使わない符号 (U+FFFE と U+FFFF)。どれも YAML の文字列にそのまま書けないか、書くと行が分かれるか、
# ワーカーがこの出力を行ごとに読むのを乱す
NOT_ONE_LINE = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029\ud800-\udfff\ufffe\uffff]")
LIMIT = 200
PHRASE = "operation not permitted"   # ファイルの書き込みを止められたときの文面 (大文字と小文字を区別しない)
TAG = "<sandbox_violations>"         # 接続を止められたときに本文に付くタグ
TAG_END = "</sandbox_violations>"


def one_line(s, limit=None):
    s = NOT_ONE_LINE.sub(" ", s).strip()
    return s[:limit] if limit else s


def body_text(content):
    """tool_result の本文。文字列か、text の要素の text を改行で繋いだもの。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c["text"] for c in content
                         if isinstance(c, dict) and c.get("type") == "text" and isinstance(c.get("text"), str))
    return ""


def blocked_message(body):
    """本文のうち、文面を含む行と、タグの行から閉じるタグの行 (無ければ本文の終わり) までの行を、空白で繋ぐ。
    接続を止められたときは、止められたホストがタグの次の行にあるため、タグの中の行も含める。"""
    out = []
    in_tag = False
    for l in body.splitlines():
        if TAG in l:
            in_tag = True
        if in_tag or PHRASE in l.lower():
            out.append(l.strip())
        if TAG_END in l:
            in_tag = False
    return " ".join(x for x in out if x)


model = None
saw_assistant = False
skill = False
result = None
init_seen = False
mode = None
uses = {}      # tool_use の id → (ツールの名前, 入力の command)。sub-agent の行も含める
results = []   # tool_result の列 (ログの順)。sub-agent の行も含める
try:
    f = open(sys.argv[1], encoding="utf-8", errors="replace")
except OSError:
    f = []
for line in f:
    line = line.strip()
    if not line:
        continue
    try:
        o = json.loads(line)
    except ValueError:
        continue
    if not isinstance(o, dict):
        continue
    t = o.get("type")
    # サンドボックスが止めた確認を数えるための対応は、sub-agent の行 (parent_tool_use_id がある) からも作る
    if t in ("assistant", "user"):
        msg = o.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        for c in content if isinstance(content, list) else []:
            if not isinstance(c, dict):
                continue
            if t == "assistant" and c.get("type") == "tool_use" and isinstance(c.get("id"), str):
                inp = c.get("input")
                cmd = inp.get("command") if isinstance(inp, dict) else None
                uses[c["id"]] = (c.get("name"), cmd if isinstance(cmd, str) else "")
            elif t == "user" and c.get("type") == "tool_result":
                results.append(c)
    # 実効モデル・skill の呼び出し・実効の権限モード・拒否は、最上位の行だけから読む
    if o.get("parent_tool_use_id"):
        continue
    if t == "system" and o.get("subtype") == "init":
        if model is None and isinstance(o.get("model"), str) and o["model"]:
            model = o["model"]
        # 実効の権限モードは、最初の init の行だけから読む (その行に無ければ unknown)
        if not init_seen:
            init_seen = True
            m = o.get("permissionMode")
            mode = one_line(m) if isinstance(m, str) else None
    elif t == "assistant":
        saw_assistant = True
        msg = o.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        for c in content if isinstance(content, list) else []:
            if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") == "Skill":
                skill = True
    elif t == "result":
        result = o

sys.stdout.reconfigure(encoding="utf-8")
name = "unknown"
if model:
    name = one_line(model[len("claude-"):] if model.startswith("claude-") else model) or "unknown"
print(name)
print(("true" if skill else "false") if saw_assistant else "unknown")
denials = result.get("permission_denials") if isinstance(result, dict) else None
if isinstance(denials, list):
    tools = []
    for d in denials:
        n = d.get("tool_name") if isinstance(d, dict) else None
        n = n if isinstance(n, str) and n else "unknown"
        if n not in tools:
            tools.append(n)
    print(len(denials))
    print(json.dumps(tools, ensure_ascii=False))
else:
    print("unknown")
    print("[]")
print(mode or "unknown")
if isinstance(result, dict):
    blocked = []
    for r in results:
        name_cmd = uses.get(r.get("tool_use_id"))
        if not name_cmd or name_cmd[0] != "Bash" or r.get("is_error") is not True:
            continue
        body = body_text(r.get("content"))
        if PHRASE in body.lower() or TAG in body:
            blocked.append((one_line(name_cmd[1], LIMIT), one_line(blocked_message(body), LIMIT)))
    print(len(blocked))
    for cmd, message in blocked:
        print(cmd)
        print(message)
else:
    print("unknown")
