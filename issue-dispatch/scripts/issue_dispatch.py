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
  project items --project <owner>/<番号> [--write-snapshot --dir <管理ディレクトリ>]   項目の一覧を位置の順に全部読む (キーの表は project-schema.md の「CLI」)。
      --write-snapshot なら、読んだ内容とコメントの URL の PR の状態をスナップショットに書く (observation.md)
  observe diff --dir <管理ディレクトリ> --project <owner>/<番号>   スナップショットと今の Project の差分を処理の順に返す (書かない)
  書き込みのサブコマンド (project set-status / issue add-label / blocked-by add / comment post) の --snapshot-dir <管理ディレクトリ>:
      書いた値だけをスナップショットに反映する (無い・壊れていれば反映せず warnings。書き込みの結果は変えない)
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
  resources attributes --dir <管理ディレクトリ> [--name <資源>]   設定の resources にデフォルト値を当てた属性を返す (警告つき)
  resources judge --dir <管理ディレクトリ> --trigger assign|declare|update|close|release (--body <JSON> | --body-file <ファイル|->)
      契機ごとの資源の判断。本文のキーは resources.md の契機の表 (使用・資源・答えは呼び出し元が渡す。gh は実行しない)
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

import datetime

from issue_dispatch import comments, config, declaration, filekinds, ids, issues, itemstate, observe, project, record, repo, resources, sessions


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


def _snapshot_dir(manager_dir, parsed_project=None):
    """管理ディレクトリの設定からスナップショットの置き場 (記録の置き場と同じ) を決める。返り値は (ディレクトリ, 設定の project, errors)。"""
    loaded = config.load(manager_dir, "manager")
    project_setting = parsed_project or loaded["config"].get("project")
    if not project_setting:
        return None, None, [{"key": "project", "message": "管理ディレクトリの設定に project が無い", "failure": None}]
    return record.record_dir(manager_dir, loaded["config"]["record_dir"], project_setting), project_setting, []


def _now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_comment_prs(items, login, extra_urls=()):
    """開いている項目のコメントに URL で書かれた PR (と extra_urls) の状態を読む。返り値は (URL → 状態 (読めなければ {"partial": 理由}), problems)。"""
    states, problems = {}, []
    urls = observe.pr_urls_in_comments(items, login)
    urls += [u for u in extra_urls if u not in urls]
    for url in urls:
        r = issues.pr_state(url)
        if r["status"] == "ok":
            states[url] = {"state": r["state"], "draft": r["draft"], "merged": r["merged"]}
        else:
            states[url] = {"partial": r["message"]}
            problems.append({"what": "comment-pr", "url": url, "failure": r.get("failure"), "message": r["message"], "exit_code": r.get("exit_code")})
    return states, problems


def _list_problems(problems):
    return [p for p in problems if p.get("what") in observe.LIST_PROBLEMS]


def cmd_project_items(args):
    parsed = _project_arg(args)
    if parsed is None:
        return 0
    if args.write_snapshot and not args.dir:
        build_parser().error("--write-snapshot には --dir <管理ディレクトリ> が要る")
    result = project.items(parsed)
    if result["status"] == "error":
        _emit({"status": "error", "items": [], "errors": [{"key": "project", "message": result["message"], "failure": result.get("failure")}]})
        return 0
    out = {"status": result["status"], "project_id": result["project_id"], "items": result["items"],
           "problems": result["problems"], "rate_limit": result["rate_limit"], "errors": []}
    if args.write_snapshot:
        directory, _, errors = _snapshot_dir(args.dir, parsed)
        if errors:
            _emit({**out, "status": "error", "errors": errors})
            return 0
        login, problem = comments.token_login()
        if problem:
            _emit({**out, "status": "error", "errors": [{"key": "login", "message": problem["message"], "failure": problem.get("failure")}]})
            return 0
        if _list_problems(result["problems"]):
            # 項目の一覧そのものが欠けていれば保存しない (読めなかっただけの項目を「除かれた」と読ませないため)
            _emit({**out, "status": "error", "snapshot": None,
                   "errors": [{"key": "partial", "message": "項目の一覧の一部が読めなかった (problems) ので、スナップショットを書かない", "failure": None}]})
            return 0
        # 1 項目の中の欠けと PR の読み取りの失敗は、既存のスナップショットに引き継ぐ元があれば前の値を引き継ぎ、無ければフラグ partial を付けて保存する
        previous = observe.load_snapshot(directory)
        warnings = []
        if previous["status"] == "corrupt":
            warnings.append({"key": "snapshot", "message": f"既存のスナップショット {previous['path']} が壊れている ({previous.get('message', '')}) ので、前の値を引き継がずに書き直す"})
        # 読むのは今のコメントに書かれた PR だけ (前のスナップショットにだけある URL は保存に残さない。差分のための読み直しは observe diff が行う)
        comment_prs, problems = _read_comment_prs(result["items"], login)
        out["problems"] = out["problems"] + problems
        snapshot = observe.build_snapshot(result, comment_prs, _now(), previous=previous["snapshot"])
        path = observe.save_snapshot(directory, snapshot)
        out["status"] = "partial" if out["problems"] else out["status"]
        out["snapshot"] = {"path": path, "taken_at": snapshot["taken_at"], "comment_prs": comment_prs,
                           "skipped": observe.skipped(snapshot, snapshot), "carried": observe.carried(snapshot), "warnings": warnings}
    _emit(out)
    return 0


def cmd_observe_diff(args):
    parsed = _project_arg(args)
    if parsed is None:
        return 0
    directory, _, errors = _snapshot_dir(args.dir, parsed)
    if errors:
        _emit({"status": "error", "diffs": [], "errors": errors})
        return 0
    loaded = observe.load_snapshot(directory)
    if loaded["status"] != "ok":
        _emit({"status": "error", "diffs": [], "errors": [{"key": "snapshot", "message": f"スナップショット {loaded['path']} が{'無い' if loaded['status'] == 'missing' else '壊れている (' + loaded.get('message', '') + ')'}。`project items --write-snapshot` で作る", "failure": None}]})
        return 0
    result = project.items(parsed)
    if result["status"] == "error":
        _emit({"status": "error", "diffs": [], "errors": [{"key": "project", "message": result["message"], "failure": result.get("failure")}]})
        return 0
    login, problem = comments.token_login()
    if problem:
        _emit({"status": "error", "diffs": [], "errors": [{"key": "login", "message": problem["message"], "failure": problem.get("failure")}]})
        return 0
    if _list_problems(result["problems"]):
        # 項目の一覧そのものが欠けていれば差分を返さない (読めなかっただけの項目が removed として現れるため)
        _emit({"status": "error", "snapshot_taken_at": loaded["snapshot"]["taken_at"], "diffs": [], "problems": result["problems"],
               "rate_limit": result["rate_limit"], "errors": [{"key": "partial", "message": "項目の一覧の一部が読めなかった (problems) ので、差分を返さない", "failure": None}]})
        return 0
    # スナップショットにある PR (コメントが消えても、待っていた PR の状態の変化を見つけるため) も読む
    comment_prs, problems = _read_comment_prs(result["items"], login, extra_urls=list(loaded["snapshot"]["comment_prs"]))
    current = observe.build_snapshot(result, comment_prs, _now(), previous=loaded["snapshot"])
    all_problems = result["problems"] + problems
    _emit({"status": "partial" if all_problems else "ok", "snapshot_taken_at": loaded["snapshot"]["taken_at"],
           "diffs": observe.diff(loaded["snapshot"], current), "skipped": observe.skipped(loaded["snapshot"], current), "carried": observe.carried(current),
           "problems": all_problems, "rate_limit": result["rate_limit"], "errors": []})
    return 0


def _reflect(args, ops):
    """書き込みのサブコマンドの共通の処理: --snapshot-dir があれば、書いた値をスナップショットに反映する。
    返り値は出力に足す {"snapshot": {"reflected", "warnings"}} (指定が無ければ空)。"""
    if not getattr(args, "snapshot_dir", None):
        return {}
    directory, _, errors = _snapshot_dir(args.snapshot_dir)
    warnings = [{"key": "snapshot", "message": e["message"]} for e in errors]
    if not errors:
        loaded = observe.load_snapshot(directory)
        if loaded["status"] != "ok":
            warnings.append({"key": "snapshot", "message": f"スナップショット {loaded['path']} が{'無い' if loaded['status'] == 'missing' else '壊れている'}ので反映しない"})
        else:
            snapshot = loaded["snapshot"]
            for op in ops:
                snapshot, problem = observe.reflect(snapshot, op)
                if problem:
                    warnings.append({"key": "snapshot", "message": f"反映できない: {problem}"})
            if not warnings:
                observe.save_snapshot(directory, snapshot)
    return {"snapshot": {"reflected": not warnings, "warnings": warnings}}


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
    extra = {}
    if result["status"] == "ok" and args.snapshot_dir:
        # 項目の ID からキーを引く (スナップショットの項目は owner/repo#番号 で持つ)
        directory, _, errors = _snapshot_dir(args.snapshot_dir)
        loaded = observe.load_snapshot(directory) if not errors else {"status": "error"}
        key = next((k for k, v in (loaded.get("snapshot") or {}).get("items", {}).items() if v["item_id"] == args.item), None) if loaded["status"] == "ok" else None
        extra = _reflect(args, [{"kind": "status", "item": key or args.item, "value": args.status}])
    _emit({**result, **extra, "errors": [] if result["status"] == "ok" else [{"key": "status", "message": result["message"]}]})
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


def _read_report_prs(items, login):
    """項目の今の割り当ての `PR の報告` に書かれた PR の状態を issues.observe_pr で読む。返り値は (URL → 結果, problems)。"""
    states, problems = {}, []
    for url in itemstate.report_pr_urls(items, login):
        r = issues.observe_pr(url, login=login)
        states[url] = r
        if r["status"] != "ok":
            problems.append({"what": "report-pr", "url": url, "failure": r.get("failure"), "message": r["message"], "exit_code": r.get("exit_code")})
    return states, problems


def _items_for_state(parsed):
    """項目の状態の導出のために項目を読む。項目の一覧そのものが欠ければ (LIST_PROBLEMS) エラー (読めなかった項目を終わったと読まないため)。"""
    result = project.items(parsed)
    if result["status"] == "error":
        return None, {"status": "error", "errors": [{"key": "project", "message": result["message"], "failure": result.get("failure")}]}
    if _list_problems(result["problems"]):
        return None, {"status": "error", "problems": result["problems"], "rate_limit": result["rate_limit"],
                      "errors": [{"key": "partial", "message": "項目の一覧の一部が読めなかった (problems) ので、項目の状態を導かない", "failure": None}]}
    return result, None


def cmd_item_state(args):
    loaded = config.load(args.dir, "manager")
    project_setting = args.project or loaded["config"].get("project")
    if isinstance(project_setting, dict) and isinstance(project_setting.get("owner"), str) and isinstance(project_setting.get("number"), int):
        parsed = {"owner": project_setting["owner"], "number": project_setting["number"]}
    else:
        parsed = project.parse_project(project_setting) if isinstance(project_setting, str) else None
    if parsed is None:
        _emit({"status": "error", "items": [], "errors": [{"key": "project", "message": "管理ディレクトリの設定にも --project にも owner/番号 の Project が無い", "failure": None}]})
        return 0
    table, warnings = resources.attributes(loaded["config"].get("resources") or {})
    login, problem = comments.token_login()
    if problem:
        _emit({"status": "error", "items": [], "errors": [{"key": "login", "message": problem["message"], "failure": problem.get("failure")}]})
        return 0
    result, error = _items_for_state(parsed)
    if error:
        _emit({**error, "items": []})
        return 0
    items = [it for it in result["items"] if it.get("key") and (not args.issue or ids.same_issue(it["key"], args.issue))]
    pr_states, pr_problems = _read_report_prs(items, login)
    states = [itemstate.derive(it, login, pr_states, parsed["number"], table) for it in items]
    states = [st for st in states if st["assignment"]]
    problems = result["problems"] + pr_problems
    _emit({"status": "partial" if problems else "ok", "items": states, "usage": itemstate.resource_usage(states), "problems": problems,
           "rate_limit": result["rate_limit"], "warnings": loaded["warnings"] + warnings, "errors": []})
    return 0


def _session_arg(args):
    if args.session:
        value = sessions.normalize_session_id(args.session)
        if value is None:
            _emit({"status": "error", "errors": [{"key": "session", "message": f"--session の値がセッション ID の形ではない: {args.session!r}", "failure": None}]})
        return value
    value, _ = sessions.own_session_id(os.environ)
    if value is None:
        _emit({"status": "error", "errors": [{"key": "session", "message": f"--session が無く、環境変数 {sessions.ENV_HOST_SESSION_ID} も {sessions.ENV_SESSION_ID} も無い", "failure": None}]})
    return value


def _work_common(args):
    """`work check` / `work held` の共通: Project・セッション ID・ログイン・項目。返り値は (parsed, session_id, login, result) か None (出力済み)。"""
    parsed = _project_arg(args)
    if parsed is None:
        return None
    session_id = _session_arg(args)
    if session_id is None:
        return None
    login, problem = comments.token_login()
    if problem:
        _emit({"status": "error", "errors": [{"key": "login", "message": problem["message"], "failure": problem.get("failure")}]})
        return None
    result, error = _items_for_state(parsed)
    if error:
        _emit(error)
        return None
    return parsed, session_id, login, result


def cmd_work_check(args):
    common = _work_common(args)
    if common is None:
        return 0
    parsed, session_id, login, result = common
    item = next((it for it in result["items"] if it.get("key") and ids.same_issue(it["key"], args.issue)), None)
    if item is None:
        _emit({"status": "error", "errors": [{"key": "issue", "message": f"Project に項目 {args.issue!r} が無い (除かれた・閉じて除かれた・参照の形が違う)", "failure": None}]})
        return 0
    pr_states, pr_problems = _read_report_prs([item], login)
    checked = itemstate.work_check(item, session_id, login, pr_states)
    problems = result["problems"] + pr_problems
    _emit({"status": "partial" if problems else "ok", "session": session_id, **checked, "problems": problems, "rate_limit": result["rate_limit"], "errors": []})
    return 0


def cmd_work_held(args):
    common = _work_common(args)
    if common is None:
        return 0
    parsed, session_id, login, result = common
    items = [it for it in result["items"] if it.get("key")]
    pr_states, pr_problems = _read_report_prs(items, login)
    held = itemstate.work_held(items, session_id, login, pr_states, parsed["number"])
    problems = result["problems"] + pr_problems
    _emit({"status": "partial" if problems else "ok", "session": session_id, "items": held, "problems": problems, "rate_limit": result["rate_limit"], "errors": []})
    return 0


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
    extra = _reflect(args, [{"kind": "labels", "item": result["issue"], "add": [result["label"]], "remove": []}]) if result["status"] == "ok" and result["added"] else {}
    _emit({**result, **extra, "errors": []} if result["status"] == "ok" else _issue_error(result, "add-label"))
    return 0


def cmd_blocked_by_add(args):
    result = issues.add_blocked_by(args.issue, args.blocker)
    extra = _reflect(args, [{"kind": "blocked_by", "item": result["issue"], "action": "add", "blocker": result["blocker"], "state": "OPEN"}]) if result["status"] == "ok" else {}
    _emit({**result, **extra, "errors": []} if result["status"] == "ok" else _issue_error(result, "blocked-by"))
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
    extra = _reflect(args, [{"kind": "comment", "item": ids.issue_key(args.issue), "id": result["database_id"]}]) if result["status"] == "ok" and result["posted"] else {}
    _emit({**result, **extra, "errors": []} if result["status"] == "ok" else _issue_error(result, "post") | {"posted": None})
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


def cmd_resources_attributes(args):
    loaded = config.load(args.dir, "manager")
    table, warnings = resources.attributes(loaded["config"].get("resources") or {})
    if args.name:
        listed = [resources.attributes_of(table, args.name)]
    else:
        listed = [dict(v) for v in table.values()]
    _emit({"status": "ok", "resources": listed, "defaults": resources.DEFAULTS, "config_status": loaded["status"],
           "warnings": loaded["warnings"] + warnings, "errors": loaded["errors"]})
    return 0


# 契機ごとの本文のキー (必須, 型)。配列は資源の名前か項目の配列、オブジェクトは名前 → 値
_JUDGE_KEYS = {
    "assign": (("item", str), ("resources", list), ("usage", dict)),
    "declare": (("item", str), ("declared", list), ("reserved", list), ("usage", dict)),
    "update": (("item", str), ("kind", str), ("held", list), ("declared", list), ("usage", dict)),
    "close": (("item", str), ("usage", dict)),
    "release": (("resource", str), ("waiting", list)),
}


def _is_name(value):
    return isinstance(value, str) and value.strip() != ""


def _check_judge_body(trigger, body):
    """`resources judge` の本文の形を、入れ子の中身まで検査する (本文はスキルが組み立てるので、誤った形を誤った判断にしない)。"""
    errors = []
    if not isinstance(body, dict):
        return [{"key": "body", "message": "本文はオブジェクト", "failure": None}]
    for key, kind in _JUDGE_KEYS[trigger]:
        if key not in body:
            errors.append({"key": "body", "message": f"契機 {trigger} の本文に {key} が無い (必須のキー: {', '.join(k for k, _ in _JUDGE_KEYS[trigger])})", "failure": None})
        elif not isinstance(body[key], kind):
            errors.append({"key": f"body.{key}", "message": f"{key} は {kind.__name__} ({body[key]!r})", "failure": None})
    if errors:
        return errors
    for key in ("resources", "declared", "reserved", "held"):
        if key in body and not all(_is_name(n) for n in body[key]):
            errors.append({"key": f"body.{key}", "message": f"{key} は資源の名前 (空でない文字列) の配列: {body[key]!r}", "failure": None})
    if "usage" in body:
        for name, items in body["usage"].items():
            if not _is_name(name) or not isinstance(items, list) or not all(_is_name(i) for i in items):
                errors.append({"key": f"body.usage.{name}", "message": f"usage は資源の名前 → 項目 (owner/repo#番号 の文字列) の配列: {items!r}", "failure": None})
    for key in ("answers", "undeclared_answers"):
        if key in body and (not isinstance(body[key], dict) or not all(_is_name(k) and isinstance(v, str) for k, v in body[key].items())):
            errors.append({"key": f"body.{key}", "message": f"{key} は資源の名前 → 答え (文字列) のオブジェクト: {body[key]!r}", "failure": None})
    if "waiting" in body:
        for i, w in enumerate(body["waiting"]):
            # judge_release が読むキーをすべて確かめる (絞り込みの item・wait_for と、並べ替えの posted_at・position)
            ok = (isinstance(w, dict) and _is_name(w.get("item")) and "declaration" in w
                  and isinstance(w.get("wait_for"), list) and all(_is_name(r) for r in w["wait_for"])
                  and (w.get("posted_at") is None or isinstance(w["posted_at"], str))
                  and (w.get("position") is None or (isinstance(w["position"], int) and not isinstance(w["position"], bool))))
            if not ok:
                errors.append({"key": f"body.waiting[{i}]", "message": f"waiting の要素は item (文字列)・declaration・posted_at (文字列)・position (整数)・wait_for (資源の名前の配列) を持つオブジェクト: {w!r}", "failure": None})
    if "kind" in body and body["kind"] not in declaration.UPDATE_KINDS:
        errors.append({"key": "body.kind", "message": f"kind は更新の種類 ({', '.join(declaration.UPDATE_KINDS)}): {body['kind']!r}", "failure": None})
    return errors


def cmd_resources_judge(args):
    body, problem = _read_json_body(args)
    if problem:
        _emit({"status": "error", "trigger": args.trigger, "result": None, "errors": [problem]})
        return 0
    errors = _check_judge_body(args.trigger, body)
    if errors:
        _emit({"status": "error", "trigger": args.trigger, "result": None, "errors": errors})
        return 0
    loaded = config.load(args.dir, "manager")
    table, warnings = resources.attributes(loaded["config"].get("resources") or {})
    answers = body.get("answers") or {}
    if args.trigger == "assign":
        result = resources.judge_assign(body["item"], body["resources"], body["usage"], table, answers)
    elif args.trigger == "declare":
        result = resources.judge_declare(body["item"], body["declared"], body["reserved"], body["usage"], table, answers, body.get("undeclared_answers") or {})
    elif args.trigger == "update":
        result = resources.judge_update(body["item"], body["kind"], body["held"], body["declared"], body["usage"], table, answers)
    elif args.trigger == "close":
        result = resources.judge_close(body["item"], body["usage"])
    else:
        result = resources.judge_release(body["resource"], body["waiting"])
    _emit({"status": "ok", "trigger": args.trigger, **({"result": None} if "result" not in result else {}), **result,
           "config_status": loaded["status"], "warnings": loaded["warnings"] + warnings, "errors": []})
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
        if name == "items":
            p.add_argument("--write-snapshot", action="store_true", help="読んだ内容をスナップショットに書く (--dir が要る)")
            p.add_argument("--dir", help="管理ディレクトリ (スナップショットの置き場は設定の record_dir)")
    p_set = project_sub.add_parser("set-status", help="Status を書く (5 つ以外と Done は拒否)")
    p_set.add_argument("--project", required=True, help="owner/番号")
    p_set.add_argument("--item", required=True, help="項目の ID (project items の item_id)")
    p_set.add_argument("--status", required=True, help="Todo / Ready / Blocked / In Progress / In review")
    p_set.add_argument("--snapshot-dir", help="管理ディレクトリ (書いた値をスナップショットに反映する)")
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
    p_label.add_argument("--snapshot-dir", help="管理ディレクトリ (書いた値をスナップショットに反映する)")
    p_label.set_defaults(func=cmd_issue_add_label)

    p_blocked = sub.add_parser("blocked-by", help="Issue の blockedBy")
    blocked_sub = p_blocked.add_subparsers(dest="subcommand", required=True)
    p_badd = blocked_sub.add_parser("add", help="blocker を足す (失敗しても再試行しない)")
    p_badd.add_argument("--issue", required=True, help="owner/repo#番号 か URL")
    p_badd.add_argument("--blocker", required=True, help="owner/repo#番号 か URL")
    p_badd.add_argument("--snapshot-dir", help="管理ディレクトリ (書いた値をスナップショットに反映する)")
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
    p_cpost.add_argument("--snapshot-dir", help="管理ディレクトリ (投稿したコメントをスナップショットに反映する)")
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

    p_res = sub.add_parser("resources", help="資源")
    res_sub = p_res.add_subparsers(dest="subcommand", required=True)
    p_rattr = res_sub.add_parser("attributes", help="設定の resources にデフォルト値を当てた属性を返す")
    p_rattr.add_argument("--dir", required=True, help="管理ディレクトリ")
    p_rattr.add_argument("--name", help="1 つの資源だけ (設定に無ければデフォルト値)")
    p_rattr.set_defaults(func=cmd_resources_attributes)
    p_rjudge = res_sub.add_parser("judge", help="契機ごとの資源の判断 (gh は実行しない)")
    p_rjudge.add_argument("--dir", required=True, help="管理ディレクトリ (設定の resources を読む)")
    p_rjudge.add_argument("--trigger", required=True, choices=resources.TRIGGERS, help="契機")
    body = p_rjudge.add_mutually_exclusive_group(required=True)
    body.add_argument("--body", help="契機ごとの JSON (キーは resources.md の契機の表)")
    body.add_argument("--body-file", help="同じ JSON のファイル (- なら標準入力)")
    p_rjudge.set_defaults(func=cmd_resources_judge)

    p_obs = sub.add_parser("observe", help="観測 (スナップショットと差分)")
    obs_sub = p_obs.add_subparsers(dest="subcommand", required=True)
    p_odiff = obs_sub.add_parser("diff", help="スナップショットと今の Project の差分を処理の順に返す (書かない)")
    p_odiff.add_argument("--dir", required=True, help="管理ディレクトリ")
    p_odiff.add_argument("--project", required=True, help="owner/番号")
    p_odiff.set_defaults(func=cmd_observe_diff)

    p_item = sub.add_parser("item", help="項目の状態")
    item_sub = p_item.add_subparsers(dest="subcommand", required=True)
    p_istate = item_sub.add_parser("state", help="作業中の項目の状態 (割り当て・PR・宣言の段階・資源) を導く (読むだけ)")
    p_istate.add_argument("--dir", required=True, help="管理ディレクトリ (設定の project と resources を読む)")
    p_istate.add_argument("--project", help="owner/番号 (省略時は設定の project)")
    p_istate.add_argument("--issue", help="1 項目だけ (owner/repo#番号)")
    p_istate.set_defaults(func=cmd_item_state)

    p_work = sub.add_parser("work", help="作業のセッションの確認 (読むだけ)")
    work_sub = p_work.add_subparsers(dest="subcommand", required=True)
    p_wcheck = work_sub.add_parser("check", help="割り当ての確認: フィールド・`割り当て`・`解放`・まだ行っていない `依頼`・第三者の本文の編集")
    p_wcheck.add_argument("--project", required=True, help="owner/番号")
    p_wcheck.add_argument("--issue", required=True, help="owner/repo#番号")
    p_wcheck.add_argument("--session", help="自分のセッション ID (省略時は環境変数)")
    p_wcheck.set_defaults(func=cmd_work_check)
    p_wheld = work_sub.add_parser("held", help="持っている Issue (割り当て中) と Status と宣言の段階")
    p_wheld.add_argument("--project", required=True, help="owner/番号")
    p_wheld.add_argument("--session", help="自分のセッション ID (省略時は環境変数)")
    p_wheld.set_defaults(func=cmd_work_held)

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
