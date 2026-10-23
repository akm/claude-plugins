#!/usr/bin/env python3
"""issue-dispatch の CLI の入口。サブコマンドごとにパッケージ issue_dispatch のモジュールの関数を実行する。入出力は JSON。

サブコマンドの一覧の正本は、計画 docs/plans/2026-10-06-2025-feat-issue-dispatch-plan.md の KTD14。
この版にあるサブコマンド:
  config read --dir <ルート> --role manager|repo   設定を読み、デフォルト値を当てた後の設定と警告・エラーを返す
  config add-edit-check --dir <ルート> --repo <owner/repo>   管理ディレクトリの設定の third_party_edit_check に足す
  record read --dir <管理ディレクトリ>   記録を返す (無ければ新規の空の記録。壊れていれば status corrupt と errors)
  record apply --dir <管理ディレクトリ>  標準入力の JSON (操作の配列) を記録に適用して保存する (1 つでも誤りがあれば保存しない)
  record log --dir <管理ディレクトリ>    標準入力の JSON (1 件) を actions.log に追記する
  repo name --dir <作業ツリー>   今の作業ツリーの origin の URL から owner/repo を返す (gh は実行しない)
  project check --project <owner>/<番号>     フィールド・Status の選択肢・ワークフローの不足と案内、作る手順の案を返す (読むだけ)
  project items --project <owner>/<番号>     項目の一覧を位置の順に全部読む (キーの表は project-schema.md の「CLI」)
  project set-status --project <owner>/<番号> --item <項目の ID> --status <値>   Status を書く (5 つ以外と Done は gh を実行せずに拒否)
  project add-fields --project <owner>/<番号>   check の案を実行する (承認を得た後に呼ぶ)
  issue create --repo <owner/name> --title <題> (--body <本文> | --body-file <ファイル|->) --split-from <宣言のコメントの URL> [--label ...] [--assignee ...]
      分割で Issue を作る。本文の先頭行に分割の元を書き、同じ先頭行の開いた Issue があれば作らずにその番号を返す
  issue add-label --issue <owner/repo#番号|URL> --label <名前> [--description <説明>]   ラベルを足す。無ければ先に作る (承認を得た後に呼ぶ)
  blocked-by add --issue <owner/repo#番号|URL> --blocker <owner/repo#番号|URL>   blockedBy に足す (失敗は理由付きで返し、再試行しない)
  pr observe --url <PR の URL>   PR の状態・参照する Issue・変えたファイルを読み、種類 (kind) を返す (読むだけ。表は issue-format.md)
  comment list --issue <owner/repo#番号|URL>   コメントを時刻の順に全部読む (書き手がトークンのログインと違うものは除く。先頭行は解析済み)
  comment post --issue <参照> --role manager|worker --name <名前> --session-id <ID> --kind <種類> [値のオプション] (--body <本文> | --body-file <ファイル|->)
      先頭行を組み立てて投稿する。同じ出来事への同じコメントが既にあれば投稿せず posted false を返す (値のオプションは issue-format.md の「コメント」)
  comment parse --line <先頭行>   先頭行を解析する (gh は実行しない。形でなければ header は null)
  declaration parse --dir <リポジトリのルート> (--body <JSON> | --body-file <ファイル|->)   宣言の JSON を検査し、パスをそろえ、種類を付けて返す
      (リポジトリの設定の規則は --dir から読む。作業のセッションが投稿の前に確かめる)
  declaration conflictability --dir <管理ディレクトリ> --repo <owner/name> (--body <JSON> | --body-file <ファイル|->)
      標準入力の JSON {"declaration": <宣言>, "others": [{"id", "repo", "declaration"}]} で競合の可能性を判定する。リポジトリの設定は
      repositories の clone から既定のブランチの内容として読み、読めなければ判定しない (KTD9)
  files classify --dir <リポジトリのルート> <パス>...   パスごとの種類と属性 (リポジトリの設定の files とデフォルトの表で決める)。
      `paths` の要素は入力と同じ並びで、どの要素も `path` に書いたままの入力の値を持つ。照合できた要素は `normalized`
      (そろえた後のパス) と種類・属性・`matched` を持ち、差し戻した要素は `error` (理由) だけを持つ

終了コード: JSON を出せたときは、エラーの有無によらず 0 (エラーは JSON の `errors` で伝える)。0 以外は Python 自身の失敗
(捕まえていない例外の 1・引数の誤りの 2) で、呼び出す側はそれを停止の条件として扱う (正本は同じ計画の R25。
1 と 2 は Python 自身が使うので、サブコマンドの専用の終了コードには使わない)。
"""

import argparse
import json
import os
import sys

from issue_dispatch import comments, config, declaration, filekinds, issues, project, record, repo


def _emit(payload):
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def cmd_config_read(args):
    _emit(config.load(args.dir, args.role))
    return 0


def cmd_config_add_edit_check(args):
    _emit(config.add_edit_check(args.dir, args.repo))
    return 0


def cmd_files_classify(args):
    loaded = config.load(args.dir, "repo")
    table = filekinds.load_default_table()
    results = []
    for path in args.paths:
        normalized, problem = filekinds.normalize_path(path)
        if problem:
            results.append({"path": path, "error": problem})
            continue
        results.append({"path": path, "normalized": normalized,
                        **filekinds.classify(normalized, loaded["config"]["files"], table)})
    _emit({"paths": results, "config_status": loaded["status"], "warnings": loaded["warnings"], "errors": loaded["errors"]})
    return 0


def _record_target(args):
    """管理ディレクトリの設定から、記録の置き場と project を決める。設定に誤りがあれば (None, None, errors)。"""
    loaded = config.load(args.dir, "manager")
    if loaded["errors"]:
        return None, None, loaded["errors"]
    project = loaded["config"]["project"]
    return record.record_dir(args.dir, loaded["config"]["record_dir"], project), project, []


def _read_stdin_json():
    text = sys.stdin.read()
    try:
        return json.loads(text), None
    except ValueError as e:
        return None, f"標準入力が JSON として読めない: {e}"


def cmd_record_read(args):
    directory, project, errors = _record_target(args)
    if errors:
        _emit({"status": "config-error", "path": None, "record": None, "errors": errors})
        return 0
    path = os.path.join(directory, record.RECORD_FILE)
    try:
        rec = record.load(directory, project)
    except record.Corrupt as e:
        _emit({"status": "corrupt", "path": path, "record": None, "errors": [{"key": "record", "message": str(e)}]})
        return 0
    _emit({"status": "ok" if os.path.exists(path) else "new", "path": path, "record": rec, "errors": []})
    return 0


def cmd_record_apply(args):
    directory, project, errors = _record_target(args)
    if errors:
        _emit({"status": "config-error", "path": None, "applied": 0, "errors": errors})
        return 0
    path = os.path.join(directory, record.RECORD_FILE)
    operations, problem = _read_stdin_json()
    if problem:
        _emit({"status": "rejected", "path": path, "applied": 0, "errors": [{"key": "stdin", "message": problem}]})
        return 0
    try:
        rec = record.load(directory, project)
    except record.Corrupt as e:
        _emit({"status": "corrupt", "path": path, "applied": 0, "errors": [{"key": "record", "message": str(e)}]})
        return 0
    rec, errors = record.apply(rec, operations)
    if errors:
        _emit({"status": "rejected", "path": path, "applied": 0, "errors": errors})
        return 0
    record.save(directory, rec)
    _emit({"status": "ok", "path": path, "applied": len(operations), "errors": []})
    return 0


def cmd_record_log(args):
    directory, project, errors = _record_target(args)
    if errors:
        _emit({"status": "config-error", "path": None, "errors": errors})
        return 0
    path = os.path.join(directory, record.ACTIONS_LOG)
    entry, problem = _read_stdin_json()
    if problem:
        _emit({"status": "rejected", "path": path, "errors": [{"key": "stdin", "message": problem}]})
        return 0
    try:
        record.append_action(directory, entry)
    except ValueError as e:
        _emit({"status": "rejected", "path": path, "errors": [{"key": "stdin", "message": str(e)}]})
        return 0
    _emit({"status": "ok", "path": path, "errors": []})
    return 0


def cmd_repo_name(args):
    result = repo.repo_name(args.dir)
    if result["status"] == "ok":
        _emit({"status": "ok", "repo": result["repo"], "host": result["host"], "errors": []})
    else:
        _emit({"status": "error", "reason": result["reason"], "repo": None, "host": None,
               "errors": [{"key": "origin", "message": result["message"]}]})
    return 0


def _project_arg(args):
    parsed = project.parse_project(args.project)
    if parsed is None:
        _emit({"status": "error", "errors": [{"key": "project", "message": f"--project は owner/番号 の形 (値 {args.project!r})"}]})
    return parsed


def _meta_or_emit(parsed):
    meta = project.read_meta(parsed)
    if meta["status"] != "ok":
        _emit({"status": "error", "errors": [{"key": "project", "message": meta["message"], "failure": meta.get("failure")}]})
        return None
    return meta


def cmd_project_check(args):
    parsed = _project_arg(args)
    if parsed is None:
        return 0
    meta = _meta_or_emit(parsed)
    if meta is None:
        return 0
    checked = project.check(meta["project"])
    checked["partial"] = bool(meta["warnings"])  # 一部が読めなかった応答から作った案 (add-fields は実行しない)
    _emit({"status": "ok", "project": {k: meta["project"][k] for k in ("id", "title", "url", "owner", "number")},
           "check": checked, "rate_limit": meta["rate_limit"], "warnings": meta["warnings"], "errors": []})
    return 0


def cmd_project_items(args):
    parsed = _project_arg(args)
    if parsed is None:
        return 0
    result = project.items(parsed)
    if result["status"] == "error":
        _emit({"status": "error", "items": [], "errors": [{"key": "project", "message": result["message"], "failure": result.get("failure")}]})
        return 0
    _emit({"status": result["status"], "project_id": result["project_id"], "items": result["items"],
           "problems": result["problems"], "rate_limit": result["rate_limit"], "errors": []})
    return 0


def cmd_project_set_status(args):
    parsed = _project_arg(args)
    if parsed is None:
        return 0
    if args.status not in project.MANAGER_STATUSES:
        _emit({"status": "rejected", "errors": [{"key": "status", "message": f"Status {args.status!r} は書かない (書けるのは {', '.join(project.MANAGER_STATUSES)}。Done は組み込みワークフローが書く)"}]})
        return 0
    meta = _meta_or_emit(parsed)
    if meta is None:
        return 0
    result = project.set_status(meta["project"], args.item, args.status)
    _emit({**result, "errors": [] if result["status"] == "ok" else [{"key": "status", "message": result["message"]}]})
    return 0


def cmd_project_add_fields(args):
    parsed = _project_arg(args)
    if parsed is None:
        return 0
    meta = _meta_or_emit(parsed)
    if meta is None:
        return 0
    if meta["warnings"]:
        # 一部のフィールドが読めなかった応答から案を作って実行すると、読めなかったフィールドを作り直す (同じ名前が 2 つできる)
        _emit({"status": "rejected", "results": [], "warnings": meta["warnings"],
               "errors": [{"key": "project", "message": "Project の一部が読めなかった (warnings) ので、構造を変える書き込みは行わない。読めるようにしてから実行する"}]})
        return 0
    checked = project.check(meta["project"])
    results = project.add_fields(meta["project"], checked)
    _emit({"status": "ok" if all(r["ok"] for r in results) else "error", "results": results,
           "errors": [{"key": r["action"], "message": r.get("stderr") or json.dumps(r.get("errors"), ensure_ascii=False)} for r in results if not r["ok"]]})
    return 0


def _issue_error(result, key):
    return {k: v for k, v in result.items() if k != "status"} | {"status": "error", "errors": [{"key": result.get("key") or key, "message": result["message"], "failure": result.get("failure")}]}


def cmd_pr_observe(args):
    result = issues.observe_pr(args.url)
    if result["status"] != "ok":
        _emit(_issue_error(result, "url"))
        return 0
    _emit({**result, "errors": []})
    return 0


def cmd_issue_create(args):
    if args.body_file is not None:
        try:
            if args.body_file == "-":
                body = sys.stdin.read()
            else:
                with open(args.body_file, encoding="utf-8") as f:
                    body = f.read()
        except (OSError, UnicodeDecodeError) as e:
            _emit({"status": "error", "created": None, "number": None, "url": None,
                   "errors": [{"key": "body-file", "message": f"本文のファイル {args.body_file!r} を読めない: {e}", "failure": None}]})
            return 0
    else:
        body = args.body or ""
    result = issues.create_issue(args.repo, args.title, body, args.split_from, labels=args.label or (), assignees=args.assignee or ())
    _emit({**result, "errors": []} if result["status"] == "ok" else _issue_error(result, "create"))
    return 0


def cmd_issue_add_label(args):
    result = issues.add_label(args.issue, args.label, description=args.description)
    _emit({**result, "errors": []} if result["status"] == "ok" else _issue_error(result, "add-label"))
    return 0


def cmd_blocked_by_add(args):
    result = issues.add_blocked_by(args.issue, args.blocker)
    _emit({**result, "errors": []} if result["status"] == "ok" else _issue_error(result, "blocked-by"))
    return 0


def _read_body(args):
    """--body か --body-file (- なら標準入力) から本文を読む。返り値は (本文, None) か (None, 理由)。"""
    if args.body_file is None:
        return args.body or "", None
    try:
        if args.body_file == "-":
            return sys.stdin.read(), None
        with open(args.body_file, encoding="utf-8") as f:
            return f.read(), None
    except (OSError, UnicodeDecodeError) as e:
        return None, f"本文のファイル {args.body_file!r} を読めない: {e}"


def cmd_comment_list(args):
    result = comments.list_comments(args.issue)
    if result["status"] != "ok":
        _emit(_issue_error(result, "issue") | {"comments": [], "excluded": 0})
        return 0
    _emit({**result, "errors": []})
    return 0


def cmd_comment_parse(args):
    _emit({"status": "ok", "header": comments.parse_header(args.line), "errors": []})
    return 0


def cmd_comment_post(args):
    body, problem = _read_body(args)
    if problem:
        _emit({"status": "error", "posted": None, "errors": [{"key": "body-file", "message": problem, "failure": None}]})
        return 0
    values = {"to": args.to, "assignment": args.assignment, "declaration": args.declaration, "request_kind": args.request_kind,
              "waiting_issue": args.waiting_issue, "waiting_declaration": args.waiting_declaration, "previous_pr": args.previous_pr,
              "pr": args.pr, "release_reason": args.release_reason, "stuck_state": args.stuck_state, "blockers": args.blocker or []}
    try:
        values["waits"] = [comments.parse_wait_reason(r) for r in (args.reason or [])]
    except ValueError as e:
        _emit({"status": "error", "posted": None, "errors": [{"key": "header", "message": str(e), "failure": None}]})
        return 0
    result = comments.post(args.issue, args.role, args.name, args.session_id, args.kind, values, body)
    _emit({**result, "errors": []} if result["status"] == "ok" else _issue_error(result, "post") | {"posted": None})
    return 0


def _read_json_body(args, key="body"):
    """--body か --body-file の JSON を読む。返り値は (値, None) か (None, errors の要素)。"""
    text, problem = _read_body(args)
    if problem:
        return None, {"key": "body-file", "message": problem, "failure": None}
    try:
        return json.loads(text), None
    except ValueError as e:
        return None, {"key": key, "message": f"JSON として読めない: {e}", "failure": None}


def cmd_declaration_parse(args):
    body, problem = _read_json_body(args)
    if problem:
        _emit({"status": "error", "declaration": None, "count": None, "config_status": None, "errors": [problem]})
        return 0
    loaded = config.load(args.dir, "repo")
    result = declaration.parse(body, loaded["config"]["files"], filekinds.load_default_table())
    _emit({**result, "config_status": loaded["status"], "warnings": loaded["warnings"], "config_errors": loaded["errors"]})
    return 0


def cmd_declaration_conflictability(args):
    body, problem = _read_json_body(args)
    if problem:
        _emit({"status": "error", "result": None, "others": [], "repo_config": None, "errors": [problem]})
        return 0
    loaded = config.load(args.dir, "manager")
    read = repo.read_repo_config(loaded["config"].get("repositories") or {}, args.repo)
    repo_config = {k: read.get(k) for k in ("status", "reason", "message", "fix", "root_hint", "path", "warnings", "errors")}
    if read["status"] == "unreadable":
        # 読めない設定をデフォルト値で続けると誤った判定をするので、判定しない (KTD9)
        _emit({"status": "error", "result": None, "others": [], "repo_config": repo_config,
               "errors": [{"key": "repo-config", "message": f"{args.repo} のリポジトリの設定を読めない ({read['reason']}): {read['message']}。{read.get('fix') or ''}", "failure": None}]})
        return 0
    rules = read["config"]["files"]
    table = filekinds.load_default_table()
    if not isinstance(body, dict) or "declaration" not in body:
        _emit({"status": "error", "result": None, "others": [], "repo_config": repo_config,
               "errors": [{"key": "body", "message": "本文は {\"declaration\": <宣言>, \"others\": [{\"id\", \"repo\", \"declaration\"}]} のオブジェクト", "failure": None}]})
        return 0
    errors = []
    mine = declaration.parse(body["declaration"], rules, table)
    errors += [{"key": f"declaration.{e['key']}", "message": e["message"], "failure": None} for e in mine["errors"]]
    others = []
    for i, other in enumerate(body.get("others") or []):
        if not isinstance(other, dict) or not isinstance(other.get("repo"), str) or "declaration" not in other:
            errors.append({"key": f"others[{i}]", "message": "others の要素は {\"id\", \"repo\", \"declaration\"} のオブジェクト", "failure": None})
            continue
        if other["repo"].lower() != args.repo.lower():
            # 別のリポジトリの宣言は競合しない (比べるパスが無い) ので、そのリポジトリの規則で検査せずに相手として残す
            others.append({"id": other.get("id"), "repo": other["repo"], "declaration": {"files": [], "resources": [], "split": None}})
            continue
        parsed = declaration.parse(other["declaration"], rules, table)
        if parsed["status"] == "ok":
            others.append({"id": other.get("id"), "repo": other["repo"], "declaration": parsed["declaration"]})
        else:
            # 相手の宣言は過去に受理されたもの。今の規則で読めなくても、判定する宣言の側は正しいので、その相手だけを
            # needs-user (自動では判定できない) として残し、ほかの相手の判定は続ける
            others.append({"id": other.get("id"), "repo": other["repo"], "declaration": None, "problems": parsed["errors"]})
    if errors:
        _emit({"status": "error", "result": None, "others": [], "repo_config": repo_config, "errors": errors})
        return 0
    result = declaration.conflictability({"repo": args.repo, "declaration": mine["declaration"]}, others)
    _emit({"status": "ok", **result, "declaration": mine["declaration"], "repo_config": repo_config, "errors": []})
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="issue_dispatch.py", description="issue-dispatch の同梱 CLI (入出力は JSON)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_config = sub.add_parser("config", help="設定の読み込みと書き換え")
    config_sub = p_config.add_subparsers(dest="subcommand", required=True)

    p_read = config_sub.add_parser("read", help="設定を読む")
    p_read.add_argument("--dir", required=True, help="管理ディレクトリかリポジトリのルート")
    p_read.add_argument("--role", required=True, choices=config.ROLES, help="manager (管理ディレクトリ) / repo (リポジトリ)")
    p_read.set_defaults(func=cmd_config_read)

    p_add = config_sub.add_parser("add-edit-check", help="third_party_edit_check にリポジトリを足す (承認を得た後)")
    p_add.add_argument("--dir", required=True, help="管理ディレクトリ")
    p_add.add_argument("--repo", required=True, help="owner/repo")
    p_add.set_defaults(func=cmd_config_add_edit_check)

    p_record = sub.add_parser("record", help="記録 (管理のセッションの本体 record.json と actions.log)")
    record_sub = p_record.add_subparsers(dest="subcommand", required=True)
    for name, func, help_text in (("read", cmd_record_read, "記録を返す"),
                                  ("apply", cmd_record_apply, "標準入力の操作の配列を適用して保存する"),
                                  ("log", cmd_record_log, "標準入力の 1 件を actions.log に追記する")):
        p = record_sub.add_parser(name, help=help_text)
        p.add_argument("--dir", required=True, help="管理ディレクトリ (設定の project と record_dir を読む)")
        p.set_defaults(func=func)

    p_project = sub.add_parser("project", help="Project")
    project_sub = p_project.add_subparsers(dest="subcommand", required=True)
    for name, func, help_text in (("check", cmd_project_check, "フィールド・選択肢・ワークフローの検査 (読むだけ)"),
                                  ("items", cmd_project_items, "項目の一覧を位置の順に全部読む"),
                                  ("add-fields", cmd_project_add_fields, "check の案を実行する (承認を得た後)")):
        p = project_sub.add_parser(name, help=help_text)
        p.add_argument("--project", required=True, help="owner/番号")
        p.set_defaults(func=func)
    p_set = project_sub.add_parser("set-status", help="Status を書く (5 つ以外と Done は拒否)")
    p_set.add_argument("--project", required=True, help="owner/番号")
    p_set.add_argument("--item", required=True, help="項目の ID (project items の item_id)")
    p_set.add_argument("--status", required=True, help="Todo / Ready / Blocked / In Progress / In review")
    p_set.set_defaults(func=cmd_project_set_status)

    p_repo = sub.add_parser("repo", help="リポジトリ")
    repo_sub = p_repo.add_subparsers(dest="subcommand", required=True)
    p_name = repo_sub.add_parser("name", help="作業ツリーの origin の URL から owner/repo を返す")
    p_name.add_argument("--dir", required=True, help="作業ツリー (その中のどのディレクトリでもよい)")
    p_name.set_defaults(func=cmd_repo_name)

    p_files = sub.add_parser("files", help="ファイルの種類")
    files_sub = p_files.add_subparsers(dest="subcommand", required=True)
    p_classify = files_sub.add_parser("classify", help="パスごとの種類と属性を返す (gh は実行しない)")
    p_classify.add_argument("--dir", required=True, help="リポジトリのルート (設定の files を読む)")
    p_classify.add_argument("paths", nargs="+", help="ルートからの相対パス (照合の前にそろえる。絶対パスと `..` を含むパスは error を返す)")
    p_classify.set_defaults(func=cmd_files_classify)

    p_issue = sub.add_parser("issue", help="Issue")
    issue_sub = p_issue.add_subparsers(dest="subcommand", required=True)
    p_create = issue_sub.add_parser("create", help="分割で Issue を作る (同じ先頭行の開いた Issue があれば作らない)")
    p_create.add_argument("--repo", required=True, help="owner/name")
    p_create.add_argument("--title", required=True)
    body = p_create.add_mutually_exclusive_group()
    body.add_argument("--body", help="本文 (先頭行はこの CLI が足す)")
    body.add_argument("--body-file", help="本文のファイル (- なら標準入力)")
    p_create.add_argument("--split-from", required=True, help="分割の元の宣言のコメントの URL (https://github.com/owner/repo/issues/番号#issuecomment-<id>)")
    p_create.add_argument("--label", action="append", help="付けるラベル (繰り返せる)")
    p_create.add_argument("--assignee", action="append", help="担当者のログイン (繰り返せる)")
    p_create.set_defaults(func=cmd_issue_create)
    p_label = issue_sub.add_parser("add-label", help="ラベルを足す。リポジトリに無ければ先に作る (承認を得た後)")
    p_label.add_argument("--issue", required=True, help="owner/repo#番号 か URL")
    p_label.add_argument("--label", required=True)
    p_label.add_argument("--description", help="ラベルを作るときの説明")
    p_label.set_defaults(func=cmd_issue_add_label)

    p_blocked = sub.add_parser("blocked-by", help="Issue の blockedBy")
    blocked_sub = p_blocked.add_subparsers(dest="subcommand", required=True)
    p_badd = blocked_sub.add_parser("add", help="blocker を足す (失敗しても再試行しない)")
    p_badd.add_argument("--issue", required=True, help="owner/repo#番号 か URL")
    p_badd.add_argument("--blocker", required=True, help="owner/repo#番号 か URL")
    p_badd.set_defaults(func=cmd_blocked_by_add)

    p_comment = sub.add_parser("comment", help="Issue のコメント")
    comment_sub = p_comment.add_subparsers(dest="subcommand", required=True)
    p_clist = comment_sub.add_parser("list", help="コメントを時刻の順に全部読む (書き手が違うものは除く)")
    p_clist.add_argument("--issue", required=True, help="owner/repo#番号 か URL")
    p_clist.set_defaults(func=cmd_comment_list)
    p_cparse = comment_sub.add_parser("parse", help="先頭行を解析する (gh は実行しない)")
    p_cparse.add_argument("--line", required=True)
    p_cparse.set_defaults(func=cmd_comment_parse)
    p_cpost = comment_sub.add_parser("post", help="先頭行を組み立てて投稿する (既投稿なら投稿しない)")
    p_cpost.add_argument("--issue", required=True, help="owner/repo#番号 か URL")
    p_cpost.add_argument("--role", required=True, choices=("manager", "worker"))
    p_cpost.add_argument("--name", required=True, help="書くセッションの名前")
    p_cpost.add_argument("--session-id", required=True, help="書くセッションの ID")
    p_cpost.add_argument("--kind", required=True, help="コメントの種類 (issue-format.md の表)")
    p_cpost.add_argument("--to", help="対象 (作業のセッションの ID)")
    p_cpost.add_argument("--assignment", help="割り当ての番号")
    p_cpost.add_argument("--declaration", help="宣言のコメントの ID")
    p_cpost.add_argument("--reason", action="append", help="待機の理由 (繰り返せる): 利用者の答え / Issue <参照> / 小さな PR <参照> [PR <URL>] / 資源 <名前> / 設定")
    p_cpost.add_argument("--request-kind", help="依頼の種類: 宣言の書き直し / 本文の追記 / 小さな PR")
    p_cpost.add_argument("--waiting-issue", help="待つ Issue (依頼 小さな PR と小さな PR の報告)")
    p_cpost.add_argument("--waiting-declaration", help="待つ側の宣言のコメントの ID")
    p_cpost.add_argument("--previous-pr", help="作り直しのとき、閉じた前の PR の URL")
    p_cpost.add_argument("--pr", help="本文の追記を頼む PR の URL")
    p_cpost.add_argument("--release-reason", help="解放の理由: 解除 / close / ID の変更 / 除去")
    p_cpost.add_argument("--stuck-state", help="停滞の値 (Agent stuck state)")
    p_cpost.add_argument("--blocker", action="append", help="依存の待ちで待つ Issue (繰り返せる)")
    body = p_cpost.add_mutually_exclusive_group()
    body.add_argument("--body", help="本文 (先頭行はこの CLI が足す)")
    body.add_argument("--body-file", help="本文のファイル (- なら標準入力)")
    p_cpost.set_defaults(func=cmd_comment_post)

    p_decl = sub.add_parser("declaration", help="宣言")
    decl_sub = p_decl.add_subparsers(dest="subcommand", required=True)
    p_dparse = decl_sub.add_parser("parse", help="宣言の JSON を検査し、パスをそろえ、種類を付けて返す (gh は実行しない)")
    p_dparse.add_argument("--dir", required=True, help="リポジトリのルート (設定の files の規則を読む)")
    body = p_dparse.add_mutually_exclusive_group(required=True)
    body.add_argument("--body", help="宣言の JSON")
    body.add_argument("--body-file", help="宣言の JSON のファイル (- なら標準入力)")
    p_dparse.set_defaults(func=cmd_declaration_parse)
    p_dconf = decl_sub.add_parser("conflictability", help="競合の可能性を判定する (リポジトリの設定は repositories の clone から読む)")
    p_dconf.add_argument("--dir", required=True, help="管理ディレクトリ")
    p_dconf.add_argument("--repo", required=True, help="判定する Issue のリポジトリ (owner/name)")
    body = p_dconf.add_mutually_exclusive_group(required=True)
    body.add_argument("--body", help='{"declaration": <宣言>, "others": [{"id", "repo", "declaration"}]} の JSON')
    body.add_argument("--body-file", help="同じ JSON のファイル (- なら標準入力)")
    p_dconf.set_defaults(func=cmd_declaration_conflictability)

    p_pr = sub.add_parser("pr", help="PR")
    pr_sub = p_pr.add_subparsers(dest="subcommand", required=True)
    p_observe = pr_sub.add_parser("observe", help="PR の状態・参照する Issue・変えたファイルを読み、種類を返す (読むだけ)")
    p_observe.add_argument("--url", required=True, help="PR の URL")
    p_observe.set_defaults(func=cmd_pr_observe)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
