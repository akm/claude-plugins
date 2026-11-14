"""テストで、関数 `issue_practice.gh.run` を差し替える、状態を持つ偽の GitHub。

偽の `gh` (ファイル `issue-practice/tests/fake-gh`) は応答を前もって決めておく形なので、書き込みの後の状態を読み直す
手順 (途中で失敗させてから、同じ計画案でやり直す) を表しにくい。この偽物は、Issue・ラベル・マイルストーン・コメントを
メモリに持ち、リリースの書き込み (モジュール `issue_practice.releaseops` と `issue_practice.closecheck`) が使う `gh` の
コマンドだけを解釈する。知らないコマンドは、例外 `AssertionError` で知らせる (指定の漏れを、成功した応答と取り違えないため)。

失敗させるときは、`fail_when` に、引数の配列を受け取って真を返す関数を入れる。真を返した呼び出しを 1 回だけ失敗させる。
"""

import json
import re

LOGIN = "akm"


def _result(args, stdout="", exit_code=0, stderr=""):
    parsed = None
    if stdout.strip():
        try:
            parsed = json.loads(stdout)
        except ValueError:
            parsed = None
    return {"args": list(args), "exit_code": exit_code, "stdout": stdout, "stderr_tail": stderr, "timed_out": False,
            "failure": None if exit_code == 0 else "other", "json": parsed, "json_error": None}


class FakeGitHub:

    def __init__(self, repo="o/r"):
        self.repo = repo
        self.issues = {}  # 番号 -> 辞書
        self.milestones = {}  # 番号 -> 辞書
        self.labels = {}  # 名前 -> 辞書
        self.comments = {}  # Issue の番号 -> コメントの配列
        self.prs = {}  # 番号 -> 辞書
        self.next_number = 1
        self.next_milestone = 1
        self.next_comment = 1
        self.clock = 0
        self.calls = []
        self.fail_when = None

    # --- 状態を作る ---------------------------------------------------------------------------------------------

    def url(self, number, kind="issues"):
        return f"https://github.com/{self.repo}/{kind}/{number}"

    def _time(self):
        self.clock += 1
        return f"2026-11-14T00:{self.clock // 60:02d}:{self.clock % 60:02d}Z"

    def add_issue(self, title, body="", labels=(), milestone=None, state="OPEN", number=None):
        number = number or self.next_number
        self.next_number = max(self.next_number, number + 1)
        self.issues[number] = {"number": number, "title": title, "body": body, "labels": list(labels),
                               "milestone": milestone, "state": state, "created_at": self._time(), "blocked_by": [],
                               "blocking": [], "state_reason": None}
        self.comments.setdefault(number, [])
        return number

    def add_pr(self, number=None, state="MERGED", base="main", body=""):
        number = number or self.next_number
        self.next_number = max(self.next_number, number + 1)
        self.prs[number] = {"number": number, "state": state, "base": base, "body": body}
        return number

    def add_label(self, name):
        self.labels[name] = {"name": name, "color": "ededed", "description": ""}

    def add_milestone(self, title, description="", state="open"):
        number = self.next_milestone
        self.next_milestone += 1
        self.milestones[number] = {"number": number, "title": title, "description": description, "state": state,
                                   "html_url": f"https://github.com/{self.repo}/milestone/{number}"}
        return number

    def add_comment(self, number, body, login=LOGIN):
        comment_id = self.next_comment
        self.next_comment += 1
        self.comments.setdefault(number, []).append({
            "id": comment_id, "html_url": f"{self.url(number)}#issuecomment-{comment_id}", "body": body,
            "created_at": self._time(), "updated_at": "x", "user": {"login": login}})
        return f"{self.url(number)}#issuecomment-{comment_id}"

    # --- 読む -------------------------------------------------------------------------------------------------

    def _milestone_of(self, title):
        return next((m for m in self.milestones.values() if m["title"] == title), None)

    def _issue_json(self, number):
        if number in self.prs:
            pr = self.prs[number]
            return {"number": number, "url": self.url(number, "pull"), "state": pr["state"], "title": "PR", "body": pr["body"]}
        issue = self.issues[number]
        milestone = self.milestones.get(issue["milestone"]) if issue["milestone"] else None
        return {"number": number, "url": self.url(number), "state": issue["state"], "title": issue["title"],
                "body": issue["body"], "updatedAt": "x", "createdAt": issue["created_at"],
                "milestone": {"number": milestone["number"], "title": milestone["title"], "description": milestone["description"],
                              "dueOn": None} if milestone else None,
                "labels": [{"name": name} for name in issue["labels"]],
                "blockedBy": {"nodes": [self._node(n) for n in issue["blocked_by"]]},
                "blocking": {"nodes": [self._node(n) for n in issue["blocking"]]}, "parent": None}

    def _node(self, number):
        issue = self.issues[number]
        return {"number": number, "url": self.url(number), "title": issue["title"], "state": issue["state"]}

    def _rest_issue(self, number):
        issue = self.issues[number]
        milestone = self.milestones.get(issue["milestone"]) if issue["milestone"] else None
        return {"html_url": self.url(number), "number": number, "title": issue["title"], "state": issue["state"].lower(),
                "body": issue["body"], "created_at": issue["created_at"], "user": {"login": LOGIN},
                "labels": [{"name": name} for name in issue["labels"]],
                "milestone": {"number": milestone["number"], "title": milestone["title"]} if milestone else None}

    def _number(self, text):
        m = re.search(r"/(?:issues|pull)/([0-9]+)$", text)
        return int(m.group(1)) if m else int(text)

    # --- gh の実行 --------------------------------------------------------------------------------------------

    def run(self, args, timeout=None, mutation=False, expect_json=False, stdin=None):
        args = list(args)
        self.calls.append({"args": args, "stdin": stdin})
        if self.fail_when is not None and self.fail_when(args):
            self.fail_when = None
            return _result(args, exit_code=1, stderr="HTTP 502: Bad Gateway")
        return self._dispatch(args, stdin)

    def _dispatch(self, args, stdin):
        out = lambda value: _result(args, json.dumps(value, ensure_ascii=False))  # noqa: E731
        if args[:2] == ["api", "user"]:
            return out({"login": LOGIN})
        if args[:2] == ["label", "list"]:
            return out([{"name": name} for name in self.labels])
        if args[:2] == ["label", "create"]:
            self.add_label(args[2])
            return _result(args)
        if args[0] == "api":
            return self._api(args, out)
        if args[:2] == ["issue", "list"]:
            labels = [args[i + 1] for i, a in enumerate(args) if a == "--label"]
            found = [self._issue_json(n) for n, i in sorted(self.issues.items())
                     if i["state"] == "OPEN" and all(label in i["labels"] for label in labels)]
            return out(found)
        if args[:2] == ["issue", "view"] or args[:2] == ["pr", "view"]:
            number = self._number(args[2])
            if args[0] == "pr":
                pr = self.prs[number]
                return out({"number": number, "url": self.url(number, "pull"), "state": pr["state"],
                            "mergedAt": "x" if pr["state"] == "MERGED" else None, "baseRefName": pr["base"],
                            "isDraft": False, "body": pr["body"]})
            return out(self._issue_json(number))
        if args[:2] == ["issue", "create"]:
            title = args[args.index("--title") + 1]
            labels = [args[i + 1] for i, a in enumerate(args) if a == "--label"]
            missing = [label for label in labels if label not in self.labels]
            if missing:
                return _result(args, exit_code=1, stderr=f"could not add label: '{missing[0]}' not found")
            number = self.add_issue(title, body=stdin or "", labels=labels)
            return _result(args, self.url(number) + "\n")
        if args[:2] == ["issue", "edit"]:
            return self._edit(args, stdin)
        if args[:2] == ["issue", "comment"]:
            return _result(args, self.add_comment(self._number(args[2]), stdin or "") + "\n")
        if args[:2] == ["issue", "close"]:
            issue = self.issues[self._number(args[2])]
            issue["state"] = "CLOSED"
            issue["state_reason"] = args[args.index("--reason") + 1] if "--reason" in args else "completed"
            return _result(args)
        raise AssertionError(f"偽の GitHub が知らないコマンド: {args!r}")

    def _edit(self, args, stdin):
        issue = self.issues[self._number(args[2])]
        i = 3
        while i < len(args):
            flag = args[i]
            if flag == "--title":
                issue["title"] = args[i + 1]
            elif flag == "--body-file":
                issue["body"] = stdin or ""
            elif flag == "--milestone":
                milestone = self._milestone_of(args[i + 1])
                if milestone is None or milestone["state"] != "open":
                    return _result(args, exit_code=1, stderr=f"could not add to milestone '{args[i + 1]}': not found")
                issue["milestone"] = milestone["number"]
            elif flag == "--remove-milestone":
                issue["milestone"] = None
                i += 1
                continue
            elif flag == "--add-label":
                if args[i + 1] not in self.labels:
                    return _result(args, exit_code=1, stderr=f"'{args[i + 1]}' not found")
                if args[i + 1] not in issue["labels"]:
                    issue["labels"].append(args[i + 1])
            elif flag == "--remove-label":
                if args[i + 1] in issue["labels"]:
                    issue["labels"].remove(args[i + 1])
            else:
                raise AssertionError(f"偽の GitHub が知らない issue edit のフラグ: {flag}")
            i += 2
        return _result(args)

    def _api(self, args, out):
        path = args[1]
        prefix = f"repos/{self.repo}/"
        assert path.startswith(prefix), path
        path = path[len(prefix):]
        fields = {args[i + 1].split("=", 1)[0]: args[i + 1].split("=", 1)[1] for i, a in enumerate(args) if a == "-f"}
        method = args[args.index("-X") + 1] if "-X" in args else "GET"
        m = re.match(r"^milestones\?state=(open|all)&per_page=100$", path)
        if m:
            found = [ms for _, ms in sorted(self.milestones.items()) if m.group(1) == "all" or ms["state"] == "open"]
            return out([found])
        if path == "milestones" and method == "POST":
            if self._milestone_of(fields["title"]):
                return _result(args, exit_code=1, stderr="HTTP 422: Validation Failed (already_exists)")
            number = self.add_milestone(fields["title"], fields.get("description", ""))
            return out(self.milestones[number])
        m = re.match(r"^milestones/([0-9]+)$", path)
        if m and method == "PATCH":
            milestone = self.milestones[int(m.group(1))]
            milestone.update(fields)
            return out(milestone)
        if path == "issues?state=open&per_page=100":
            return out([[self._rest_issue(n) for n, i in sorted(self.issues.items()) if i["state"] == "OPEN"]])
        m = re.match(r"^issues\?milestone=([0-9]+)&state=all&per_page=100$", path)
        if m:
            return out([[self._rest_issue(n) for n, i in sorted(self.issues.items()) if i["milestone"] == int(m.group(1))]])
        m = re.match(r"^issues/([0-9]+)/comments$", path)
        if m:
            return out([list(self.comments.get(int(m.group(1)), []))])
        raise AssertionError(f"偽の GitHub が知らない API: {args!r}")
