"""レビュアの実行のログ (stream-json) から、実効モデル・skill の呼び出し・拒否された呼び出し・実効の権限モード・
ワーカーのフックが拒否した呼び出し・サンドボックスが止めた確認・リポジトリの行を表示しただけの呼び出しを読む
(回の終わりの処理の 2)。読み方の正本は、ファイル review-triage/skills/review-loop/references/worker.md の「ログの読み方」。

引数: 1 つ目はログのパス。読めなければ、空のログとして扱う。2 つ目はワーカーのフックのファイル
(review-loop-worker/deny_tmp_hook.py) の中身で、__name__ を "__main__" 以外にして実行し、関数 denies と文字列 REASON を使う。
3 つ目は作業側の作業ツリーのルートの実体パス、4 つ目は依頼文の base の値 (依頼文に無ければ空文字列)、
5 つ目は依頼文の head を作業側で解決した完全な SHA。レビュー対象のコミットの行を読むのに使い、git は作業側のリポジトリに
対して実行する (作業場所の下では実行しない)。行を読むのは、文面かタグを含む Bash の結果が 1 つでもあるときだけ。
標準出力: 次の行。値はどれも 1 行 (改行を含まない)。読めない値は unknown にする。
  1 行目: 実効モデルの名前 / 2 行目: skill_called / 3 行目: 拒否の件数 (ワーカーのフックが拒否したものを除く) /
  4 行目: 拒否されたツールの名前の列 (JSON。ワーカーのフックが拒否したものを除く) / 5 行目: 実効の権限モード /
  6 行目: ワーカーのフックが拒否した件数 / 7 行目: サンドボックスが止めた件数 (リポジトリの行を表示しただけのものを除く) /
  8 行目: リポジトリの行を表示しただけと確かめた件数 /
  9 行目から: 止められた呼び出しごとに、コマンドと文面の 2 行。続けて、リポジトリの行を表示しただけの呼び出しごとに、
  同じくコマンドと文面の 2 行 (どれも先頭 200 文字まで)。
  サンドボックスが止めた件数が unknown なら、8 行目も unknown にし、9 行目からの行は出さない。
  レビュー対象のコミットの行を読めなければ、文面かタグを含む結果はすべてサンドボックスが止めた確認に数え、8 行目を unknown にする。
終了コード: 0。

呼び出し元: ファイル review-triage/scripts/review-loop-worker.sh の関数 read_log_facts。
語の意味と振る舞いの正本も、同じ worker.md。
"""

import json, re, subprocess, sys

# 印の YAML に書く値を 1 行に直すときに空白にする文字: 改行とタブを含む制御文字・行と段落の区切りの文字・
# 対になっていないサロゲート (JSON の \ud800 のように、2 つ組で 1 文字を表す符号の片方だけをエスケープで書いたもの)・
# 文字として使わない符号 (U+FFFE と U+FFFF)。どれも YAML の文字列にそのまま書けないか、書くと行が分かれるか、
# ワーカーがこの出力を行ごとに読むのを乱す
NOT_ONE_LINE = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029\ud800-\udfff\ufffe\uffff]")
LIMIT = 200
PHRASE = "operation not permitted"   # ファイルの書き込みを止められたときの文面 (大文字と小文字を区別しない)
TAG = "<sandbox_violations>"         # 接続を止められたときに本文に付くタグ
TAG_END = "</sandbox_violations>"

# 依頼文の base として受け付ける値。0.14.0 以前の review-request はブランチ名 (main など) を、それより後は短縮 SHA を書く。
# - で始まる値は git のオプションとして読まれるので受け付けない
BASE_NAME = re.compile(r"[0-9A-Za-z._/][0-9A-Za-z._/-]*")
FULL_SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
# 表示のコマンドが行の前に付けるもの。リポジトリの行を表示しただけかを確かめるときに、1 つだけ除いて比べる
DIFF_MARK = ("+", "-")                  # 差分の追加と削除の行 (文脈の行の空白は、前後の空白を除くときに消える)
LINE_NUMBER = re.compile(r"\s*\d+\t")    # cat -n と nl の行番号とタブ
# grep -n の「<ファイル>:<行番号>:」と、前後の行の「<ファイル>-<行番号>-」の後半。ファイル名が同じ形を含むこともあるので、
# 重なり合うものも含めて、行の中のすべての位置で探す (先読みで探し、グループ 1 がその長さ)
GREP_NUMBER = re.compile(r"(?=(:\d+:|-\d+-))")
# grep -n で 1 つのファイルだけを検索したときに行の先頭に付く「<行番号>:」と、前後の行の「<行番号>-」
GREP_LINE_NUMBER = re.compile(r"\d+[:-]")
# git blame の「<SHA> (<作者> <日時> <行番号>) 」。-s (「<SHA> <行番号>) 」)・-f (SHA の後にファイル名)・-n・-e・
# -b (SHA の代わりに空白) の形も、行番号に続く「) 」までとして除く。SHA の前の ^ は、範囲の始まりのコミットの印
BLAME_PREFIX = re.compile(r"[\^0-9a-f ]{8,}[^)]*?\d+\) ")
# git log --oneline の「<短縮 SHA> 」
ONELINE_PREFIX = re.compile(r"[0-9a-f]{7,64} ")
# git の差分の hunk の見出し。git は、hunk の前にある行の先頭の一部 (80 バイトまで。文字の途中では切らない) を後ろに付ける
DIFF_HUNK = re.compile(r"@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@ (.*)")

# ワーカーのフック。__name__ を "__main__" 以外にするので、フックとしての処理 (標準入力を読む) は実行されない
hook = {"__name__": "deny_tmp_hook"}
exec(sys.argv[2], hook)


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


def by_worker_hook(denial, results_by_id):
    """拒否 (result の行の permission_denials の要素) が、ワーカーのフックによるものと確かめられるか。
    ツールが Bash で、コマンドがフックの規則に当たり、その呼び出しの tool_result の本文がフックの返す理由の文面と一致すること。
    どれも Claude Code が書く行なので、レビュアには書けない"""
    if not isinstance(denial, dict) or denial.get("tool_name") != "Bash":
        return False
    inp = denial.get("tool_input")
    if not isinstance(inp, dict) or not hook["denies"](inp.get("command")):
        return False
    tid = denial.get("tool_use_id")
    r = results_by_id.get(tid) if isinstance(tid, str) else None
    return r is not None and body_text(r.get("content")) == hook["REASON"]


def marked(line):
    """行が、文面 (大文字と小文字を区別しない) かタグを含むか。"""
    return PHRASE in line.lower() or TAG in line


def read_repo_lines(repo, base, head):
    """レビュー対象のコミット (base と、base..head の各コミット) で追跡されているファイルの行と、それらのコミットのコミットメッセージの
    行のうち、文面かタグを含むものを、前後の空白を除いた文字列の集合にして返す。文面だけの行とタグだけの行は含めない — 止められたときの
    本物の行と同じになりうるため。読めなければ (base か head の値が形に合わない・git が失敗した) None を返す。"""
    if not BASE_NAME.fullmatch(base) or not FULL_SHA.fullmatch(head):
        return None

    def git(*args):
        # 利用者の git の設定で git grep の出力の形 (行番号・桁・色) が変わらないように、それぞれを -c で打ち消す
        p = subprocess.run(["git", "-C", repo, "-c", "grep.lineNumber=false", "-c", "grep.column=false",
                            "-c", "color.grep=never", *args],
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        return p.returncode, p.stdout.decode("utf-8", "replace")

    try:
        rc, out = git("rev-parse", "--verify", "-q", base + "^{commit}")
        if rc != 0:
            return None
        base_full = out.strip()
        rc, out = git("rev-list", base_full + ".." + head)
        if rc != 0:
            return None
        commits = [base_full, *out.split()]
        # -h でファイル名 (と、コミットの名前) を出さない。-I で中身が文字でないファイルを除く
        rc, files = git("grep", "-h", "-I", "-i", "-F", "-e", PHRASE, "-e", TAG, *commits, "--")
        if rc not in (0, 1):   # 1 は、当たる行が無いとき
            return None
        # git log・git show・git cat-file -p は、コミットメッセージも表示する
        rc, messages = git("show", "-s", "--format=%B", *commits, "--")
        if rc != 0:
            return None
    except OSError:
        return None
    lines = set()
    for l in (files + "\n" + messages).splitlines():
        s = l.strip()
        if marked(s) and s.lower() != PHRASE and s != TAG:
            lines.add(s)
    return lines


def shows_repo_line(line, repo_lines):
    """本文の行が、リポジトリの行を表示したものか。行そのもの・表示のコマンドが前に付けるもの (差分の + と -・
    cat -n と nl の行番号とタブ・grep -n のファイル名と行番号・grep -n の行番号・git blame の SHA から行番号まで・
    git log --oneline の短縮 SHA・-n 無しの grep のファイル名) を 1 つ除いたもののどれかが、前後の空白を除いてリポジトリの行と
    一致するか、git の差分の hunk の見出しで、後ろに付いた文字列がリポジトリの行の先頭の部分と一致すれば、表示したものとする。"""
    m = DIFF_HUNK.fullmatch(line.strip())
    if m:
        text = m.group(1).strip()
        if text and any(r.startswith(text) for r in repo_lines):
            return True
    rests = [line]
    if line.startswith(DIFF_MARK):
        rests.append(line[1:])
    m = LINE_NUMBER.match(line)
    if m:
        rests.append(line[m.end():])
    rests.extend(line[m.start() + len(m.group(1)):] for m in GREP_NUMBER.finditer(line))
    for prefix in (GREP_LINE_NUMBER, BLAME_PREFIX, ONELINE_PREFIX):
        m = prefix.match(line)
        if m:
            rests.append(line[m.end():])
    # -n 無しの grep と git grep の「<ファイル>:」(コミットの名前つきは「<コミット>:<ファイル>:」)。ファイル名は空白を含まないものとし、
    # 行の先頭の空白を含まない部分にある「:」のそれぞれについて、そこまでを除く
    head = re.match(r"\S*", line).group()
    rests.extend(line[i + 1:] for i, c in enumerate(head) if c == ":")
    return any(r.strip() in repo_lines for r in rests)


def blocked_message(body, skip=frozenset()):
    """本文のうち、文面を含む行と、タグの行から閉じるタグの行 (無ければ本文の終わり) までの行を、空白で繋ぐ。
    接続を止められたときは、止められたホストがタグの次の行にあるため、タグの中の行も含める。
    skip にある番号の行 (リポジトリの行を表示したと確かめた行) は含めず、タグの行でもタグの中の行を含め始めない。"""
    out = []
    in_tag = False
    for i, l in enumerate(body.splitlines()):
        if i in skip:
            continue
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
hook_denials = None
if isinstance(denials, list):
    results_by_id = {r.get("tool_use_id"): r for r in results if isinstance(r.get("tool_use_id"), str)}
    others = [d for d in denials if not by_worker_hook(d, results_by_id)]
    hook_denials = len(denials) - len(others)
    tools = []
    for d in others:
        n = d.get("tool_name") if isinstance(d, dict) else None
        n = n if isinstance(n, str) and n else "unknown"
        if n not in tools:
            tools.append(n)
    print(len(others))
    print(json.dumps(tools, ensure_ascii=False))
else:
    print("unknown")
    print("[]")
print(mode or "unknown")
print("unknown" if hook_denials is None else hook_denials)
if isinstance(result, dict):
    blocked = []
    shown = []
    repo_lines = None
    repo_read = False
    for r in results:
        name_cmd = uses.get(r.get("tool_use_id"))
        # is_error は見ない — 出力を | tail に渡したコマンドや、; echo で終わるコマンドは、止められても成功で終わる (実測)
        if not name_cmd or name_cmd[0] != "Bash":
            continue
        body = body_text(r.get("content"))
        if not (PHRASE in body.lower() or TAG in body):
            continue
        if not repo_read:
            repo_read = True
            repo_lines = read_repo_lines(sys.argv[3], sys.argv[4], sys.argv[5])
        body_lines = body.splitlines()
        hits = [i for i, l in enumerate(body_lines) if marked(l)]
        repo_hits = frozenset(i for i in hits if repo_lines and shows_repo_line(body_lines[i], repo_lines))
        cmd = one_line(name_cmd[1], LIMIT)
        if hits and len(repo_hits) == len(hits):
            shown.append((cmd, one_line(blocked_message(body), LIMIT)))
        else:
            blocked.append((cmd, one_line(blocked_message(body, repo_hits), LIMIT)))
    print(len(blocked))
    # 行を読もうとして読めなかったときだけ unknown (文面かタグを含む結果が無ければ、読まずに 0)
    print("unknown" if repo_read and repo_lines is None else len(shown))
    for cmd, message in blocked + shown:
        print(cmd)
        print(message)
else:
    print("unknown")
    print("unknown")
