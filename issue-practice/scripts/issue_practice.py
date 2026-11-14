#!/usr/bin/env python3
"""issue-practice の検査のスクリプトの入口。サブコマンドごとにパッケージ issue_practice のモジュールの関数を実行する。

出力は標準出力の JSON 1 つ。サブコマンドごとの引数・出力の JSON のキー・終了コードは、`<サブコマンド> --help` が SSOT
(計画 docs/plans/2026-11-13-2156-feat-issue-practice-plugin-plan.md の KTD2)。スキルの SKILL.md は引数を書かずに `--help` を参照する。

サブコマンドの一覧:
  refs parse <参照> [--repo <owner/repo>]       Issue か PR の参照を解析する
  refs milestone <名前>                          リリースマイルストーンの名前を解析する
  body show --issue <参照> [--region <名前>]     Issue の本文 (かマークで囲んだ範囲) と本文のハッシュ値を返す
  draft dir-check --root <ルート>                計画案のディレクトリが git に無視されているかを確認する
  draft path --root <ルート> --skill <スキル> --target <対象>   新しい計画案のパスを決め、ディレクトリを作る
  draft parse <ファイル>                         計画案の先頭の書式を解析する
  draft compare <ファイル>                       計画案の元にした Issue の本文が、計画案を作ったときから変わったかを比べる
  records format <種類> [<キー>=<値> ...] [--body-line]   記録のコメントの 1 行目 (か作る Issue の本文の末尾の行) を作る
  records parse <行>                             記録のコメントの 1 行目を解析する
  records list --issue <参照> [--kind <種類>]    Issue の記録のコメントを集める
  checkboxes list --issue <参照>                 節「クローズ条件」のチェックボックスを、根拠のリンクの有無で分ける
  checkboxes check --issue <参照> --line <行番号> (--evidence <URL> | --carved-out <URL>) --expect-sha256 <値>   チェックを入れてリンクを足す
  checkboxes common --issue <管理 Issue>         開いている作業 Issue のうち、共通の条件のコピーが古いものを一覧にする
  release current --repo <owner/repo> [--target <名前>] [--carve-out]   今のリリースと次のリリースを決める
  release review --repo <owner/repo> [--target <名前>]   決めた形の崩れ・マイルストーンの無い Issue・依存先の書き損ねを見直す
  release show --issue <リリース Issue>          リリース Issue の状態 (題名・マイルストーン・記録・メモ・PR) を返す
  release plan <ファイル> --repo <owner/repo>    リリース計画の計画案から、行う書き込みの一覧を示す (示す)
  release apply <ファイル> --repo <owner/repo>   リリース計画の計画案を GitHub に書く (実行する)
  issues plan <ファイル> --repo <owner/repo>     計画案の節「作る Issue」から、行う書き込みの一覧を示す (示す)
  issues create <ファイル> --repo <owner/repo> [--record-approval]   計画案の節「作る Issue」の Issue を作る (実行する)
  sessions active --issue <管理 Issue>           管理セッションと、動いている作業セッションを記録のコメントから集める
  managing plan <ファイル> --repo <owner/repo>   管理 Issue の計画案から、作業 Issue の作成と本文の書き換えを示す (示す)
  managing apply <ファイル> --repo <owner/repo>  管理 Issue の計画案の作業 Issue を作り、本文を書き換える (実行する)
  merge-plan show --issue <参照>                 管理 Issue の PR マージ計画の表を読み、表から作った図と本文の図を比べる
  close check --issue <参照> --role <種類> [--managing <管理 Issue>]   閉じる前の検査をする
  dependents plan --issue <参照>                 閉じる Issue を依存先とする Issue への書き込みを示す (示す)
  dependents resolve --issue <参照>              閉じた Issue を依存先とする Issue に記録を書き、節「依存先」から消す (実行する)
  merge-plan set-pr --issue <参照> [--work <作業 Issue>] --pr <URL> --expect-sha256 <値>   表の列「PR」か、管理 Issue の PR を書く

終了コード (計画の KTD10):
  0  検査して満たす (解析できた・決めた形になっている)
  3  検査して満たさない (入力や GitHub の状態が決めた形になっていない)。満たさない項目を JSON の `errors` などで返す
  4  外部のコマンド (gh・git) が失敗して検査できなかった。JSON の `gh_error` か `git_error` に理由を返す
1 と 2 は Python 自身が使う (捕まえていない例外の 1・引数の誤りの 2)。スキルはこの 2 つをスクリプトの不具合として扱い、
中断する。例外を捕まえて 3 や 4 にすることはしない (「検査できなかった」を「満たさない」と取り違えないため)。
"""

import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from issue_practice import (bodies, checkboxes, closecheck, draft, gh, issues, managing, mergeplan, records, refs,  # noqa: E402
                            releaseops, releaseplan)

EXIT_OK = 0
EXIT_UNSATISFIED = 3
EXIT_EXTERNAL_FAILED = 4

_EXIT_CODES_HELP = """終了コード:
  0  {ok}
  3  {unsatisfied}
  4  {failed}
  1 と 2 は Python 自身の失敗 (例外と引数の誤り)。スクリプトの不具合として扱う"""


def _exit_help(ok, unsatisfied, failed="使わない (gh も git も実行しない)"):
    return _EXIT_CODES_HELP.format(ok=ok, unsatisfied=unsatisfied, failed=failed)


def _emit(payload):
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


# --- refs ---------------------------------------------------------------------------------------------------------

def cmd_refs_parse(args):
    ref = refs.parse_ref(args.ref, default_repo=args.repo)
    if "error" in ref:
        _emit({"ref": None, "errors": [ref["error"]]})
        return EXIT_UNSATISFIED
    _emit({"ref": ref, "errors": []})
    return EXIT_OK


def cmd_refs_milestone(args):
    parsed = refs.parse_milestone_name(args.name)
    if "error" in parsed:
        _emit({"milestone": None, "errors": [parsed["error"]]})
        return EXIT_UNSATISFIED
    _emit({"milestone": parsed, "errors": []})
    return EXIT_OK


# --- 共通 -------------------------------------------------------------------------------------------------------

def _issue_ref(args):
    """引数 --issue と --repo から、リポジトリまで決まった参照を作る。決まらなければ (None, 理由)。"""
    ref = refs.parse_ref(args.issue, default_repo=args.repo)
    if "error" in ref:
        return None, ref["error"]
    if ref["key"] is None:
        return None, f"リポジトリが分からない: {args.issue!r} (--repo <owner/repo> を付けるか、owner/repo#番号 か URL で書く)"
    return ref, None


def _add_issue_args(parser):
    parser.add_argument("--issue", required=True, help="Issue の参照 (owner/repo#番号・URL・#番号)")
    parser.add_argument("--repo", help="--issue が #番号 か番号だけのときのリポジトリ (owner/repo)")


# --- body ---------------------------------------------------------------------------------------------------------

def cmd_body_show(args):
    ref, error = _issue_ref(args)
    if error:
        _emit({"issue": None, "errors": [error]})
        return EXIT_UNSATISFIED
    issue, failure = bodies.fetch_issue(ref)
    if failure:
        _emit({"issue": ref["key"], "gh_error": gh.describe_failure(failure)})
        return EXIT_EXTERNAL_FAILED
    payload = {"issue": ref["key"], "url": issue["url"], "title": issue["title"], "state": issue["state"],
               "updated_at": issue["updated_at"], "sha256": issue["sha256"], "content": issue["body"], "region": None,
               "errors": []}
    if args.region:
        region = bodies.find_region(issue["body"], args.region)
        if "error" in region:
            payload["errors"] = [region["error"]]
            _emit(payload)
            return EXIT_UNSATISFIED
        payload["region"] = {"name": region["name"], "start_line": region["start_line"], "end_line": region["end_line"],
                             "content": region["content"]}
    _emit(payload)
    return EXIT_OK


# --- draft --------------------------------------------------------------------------------------------------------

def _emit_dir_result(result, extra=None):
    status = result["status"]
    payload = {**(extra or {}), **{k: v for k, v in result.items() if k != "status"}}
    payload.setdefault("errors", [])
    _emit(payload)
    if status == "ok":
        return EXIT_OK
    if status == "git_failed":
        return EXIT_EXTERNAL_FAILED
    return EXIT_UNSATISFIED


def cmd_draft_dir_check(args):
    return _emit_dir_result(draft.check_dir(args.root))


def cmd_draft_path(args):
    stamp = args.stamp or datetime.datetime.now().strftime("%Y%m%d-%H%M")
    return _emit_dir_result(draft.new_path(args.root, args.skill, args.target, stamp))


def cmd_draft_parse(args):
    parsed = draft.read(args.file)
    _emit(parsed)
    return EXIT_UNSATISFIED if parsed["errors"] else EXIT_OK


def cmd_draft_compare(args):
    parsed = draft.read(args.file)
    if parsed["errors"]:
        _emit({"file_name": parsed["file_name"], "results": [], "errors": [
            f"行 {e['line']}: {e['message']}" if e["line"] else e["message"] for e in parsed["errors"]]})
        return EXIT_UNSATISFIED
    compared = draft.compare(parsed["sources"])
    payload = {"file_name": parsed["file_name"], "results": compared["results"], "errors": []}
    if compared["gh_error"]:
        payload["gh_error"] = gh.describe_failure(compared["gh_error"])
        _emit(payload)
        return EXIT_EXTERNAL_FAILED
    payload["errors"] = [f"{r['issue']} の本文が、計画案を作ったときから変わった" for r in compared["results"] if r["changed"]]
    _emit(payload)
    return EXIT_UNSATISFIED if payload["errors"] else EXIT_OK


# --- records ------------------------------------------------------------------------------------------------------

def cmd_records_format(args):
    values, errors = records.parse_assignments(args.values)
    if not errors:
        made = records.format_line(args.kind, values, where="body" if args.body_line else "comment")
        if "line" in made:
            _emit({"line": made["line"], "errors": []})
            return EXIT_OK
        errors = made["errors"]
    _emit({"line": None, "errors": errors})
    return EXIT_UNSATISFIED


def cmd_records_parse(args):
    parsed = records.parse_line(args.line, where="body" if args.body_line else "comment")
    if "errors" in parsed:
        _emit({"kind": None, "values": None, "errors": parsed["errors"]})
        return EXIT_UNSATISFIED
    _emit({**parsed, "errors": []})
    return EXIT_OK


def cmd_records_list(args):
    ref, error = _issue_ref(args)
    if error:
        _emit({"issue": None, "errors": [error]})
        return EXIT_UNSATISFIED
    listed, failure = records.list_records(ref)
    if failure:
        _emit({"issue": ref["key"], "gh_error": gh.describe_failure(failure)})
        return EXIT_EXTERNAL_FAILED
    if args.kind:
        listed["records"] = [r for r in listed["records"] if r["kind"] == args.kind]
    _emit({"issue": ref["key"], **listed, "errors": []})
    return EXIT_UNSATISFIED if listed["invalid"] else EXIT_OK


# --- checkboxes ---------------------------------------------------------------------------------------------------

def cmd_checkboxes_list(args):
    ref, error = _issue_ref(args)
    if error:
        _emit({"issue": None, "errors": [error]})
        return EXIT_UNSATISFIED
    issue, failure = bodies.fetch_issue(ref)
    if failure:
        _emit({"issue": ref["key"], "gh_error": gh.describe_failure(failure)})
        return EXIT_EXTERNAL_FAILED
    parsed = checkboxes.parse(issue["body"])
    payload = {"issue": ref["key"], "url": issue["url"], "sha256": issue["sha256"], "source": None, "items": [],
               "summary": None, "errors": []}
    if "error" in parsed:
        payload["errors"] = [parsed["error"]]
        _emit(payload)
        return EXIT_UNSATISFIED
    payload.update(source=parsed["source"], items=parsed["items"], summary=parsed["summary"])
    if not parsed["items"]:
        payload["errors"] = ["節「クローズ条件」にチェックボックスが無い"]
    _emit(payload)
    return EXIT_UNSATISFIED if payload["errors"] or parsed["summary"]["unsatisfied"] else EXIT_OK


def cmd_checkboxes_check(args):
    ref, error = _issue_ref(args)
    if error:
        _emit({"issue": None, "changed": False, "errors": [error]})
        return EXIT_UNSATISFIED
    issue, failure = bodies.fetch_issue(ref)
    if failure:
        _emit({"issue": ref["key"], "gh_error": gh.describe_failure(failure)})
        return EXIT_EXTERNAL_FAILED
    payload = {"issue": ref["key"], "url": issue["url"], "line": args.line, "changed": False, "item": None,
               "sha256": issue["sha256"], "errors": []}
    if issue["sha256"] != args.expect_sha256:
        payload["errors"] = ["本文が、読んだとき (--expect-sha256) から変わった。checkboxes list で本文を再度読み込んでからやり直す"]
        _emit(payload)
        return EXIT_UNSATISFIED
    result = checkboxes.check_line(issue["body"], args.line, evidence=args.evidence, carved_out=args.carved_out)
    if "error" in result:
        payload["errors"] = [result["error"]]
        _emit(payload)
        return EXIT_UNSATISFIED
    payload["item"] = result["item"]
    if result["changed"]:
        written = bodies.write_body(issue["url"], result["body"])
        if gh.failed(written):
            _emit({**payload, "gh_error": gh.describe_failure(written)})
            return EXIT_EXTERNAL_FAILED
        payload.update(changed=True, sha256=bodies.body_sha256(result["body"]))
    _emit(payload)
    return EXIT_OK


# --- release ------------------------------------------------------------------------------------------------------

def cmd_release_current(args):
    repo = refs.parse_repo(args.repo)
    if "error" in repo:
        _emit({"repo": args.repo, "errors": [repo["error"]]})
        return EXIT_UNSATISFIED
    result = releaseplan.current_and_next(repo["repo_key"], target=args.target, carve_out=args.carve_out)
    status = result.pop("status")
    if status == "gh_failed":
        result["gh_error"] = gh.describe_failure(result["gh_error"])
        _emit(result)
        return EXIT_EXTERNAL_FAILED
    _emit(result)
    return EXIT_OK if status == "ok" else EXIT_UNSATISFIED


def _release_repo(args):
    repo = refs.parse_repo(args.repo)
    if "error" in repo:
        _emit({"repo": args.repo, "errors": [repo["error"]]})
        return None
    return repo["repo_key"]


def cmd_release_review(args):
    repo = _release_repo(args)
    if repo is None:
        return EXIT_UNSATISFIED
    return _emit_status(releaseops.review(repo, target=args.target))


def cmd_release_show(args):
    ref, error = _issue_ref(args)
    if error:
        _emit({"issue": None, "errors": [error]})
        return EXIT_UNSATISFIED
    return _emit_status(releaseops.show(ref))


def cmd_release_plan(args):
    repo = _issues_repo(args)
    if repo is None:
        return EXIT_UNSATISFIED
    return _emit_status(releaseops.plan(args.file, repo))


def cmd_release_apply(args):
    repo = _issues_repo(args)
    if repo is None:
        return EXIT_UNSATISFIED
    return _emit_status(releaseops.apply(args.file, repo))


# --- issues -------------------------------------------------------------------------------------------------------

def _emit_issues(result):
    status = result.pop("status")
    if status == "gh_failed":
        result["gh_error"] = gh.describe_failure(result["gh_error"])
        _emit(result)
        return EXIT_EXTERNAL_FAILED
    _emit(result)
    return EXIT_OK if status == "ok" else EXIT_UNSATISFIED


def _issues_repo(args):
    repo = refs.parse_repo(args.repo)
    if "error" in repo:
        _emit({"draft": os.path.basename(args.file), "repo": args.repo, "errors": [{"line": None, "message": repo["error"]}]})
        return None
    return repo["repo_key"]


def cmd_issues_plan(args):
    repo = _issues_repo(args)
    if repo is None:
        return EXIT_UNSATISFIED
    result, _ = issues.plan(args.file, repo)
    return _emit_issues(result)


def cmd_issues_create(args):
    repo = _issues_repo(args)
    if repo is None:
        return EXIT_UNSATISFIED
    return _emit_issues(issues.create(args.file, repo, record_approval=args.record_approval))


# --- merge-plan ---------------------------------------------------------------------------------------------------

def _errors_text(errors):
    return [f"行 {e['line']}: {e['message']}" if e["line"] else e["message"] for e in errors]


def cmd_merge_plan_show(args):
    ref, error = _issue_ref(args)
    if error:
        _emit({"issue": None, "errors": [error]})
        return EXIT_UNSATISFIED
    issue, failure = bodies.fetch_issue(ref)
    if failure:
        _emit({"issue": ref["key"], "gh_error": gh.describe_failure(failure)})
        return EXIT_EXTERNAL_FAILED
    payload = {"issue": ref["key"], "url": issue["url"], "sha256": issue["sha256"], "settings": None, "rows": [],
               "graph": None, "graph_matches": None, "managing_pr_notice": None, "errors": []}
    plan = mergeplan.read_region(issue["body"])
    if "error" in plan:
        payload["errors"] = [plan["error"]]
        _emit(payload)
        return EXIT_UNSATISFIED
    payload.update(settings=plan["settings"], rows=mergeplan.rows_output(plan, ref["owner"], ref["repo"]))
    if plan["errors"]:
        payload["errors"] = _errors_text(plan["errors"])
        _emit(payload)
        return EXIT_UNSATISFIED
    payload["graph"] = mergeplan.graph(plan)
    payload["graph_matches"] = mergeplan.extract_graph(plan["content"]) == payload["graph"]
    if plan["settings"]["config"] == "2":
        payload["managing_pr_notice"] = mergeplan.DRAFT_PR_NOTICE.format(url=issue["url"])
    _emit(payload)
    return EXIT_OK if payload["graph_matches"] else EXIT_UNSATISFIED


def cmd_merge_plan_set_pr(args):
    ref, error = _issue_ref(args)
    work = refs.parse_ref(args.work, default_repo=ref["key"].split("#")[0]) if ref and args.work else None
    if error or (work and "error" in work):
        _emit({"issue": ref["key"] if ref else None, "changed": False, "errors": [error or work["error"]]})
        return EXIT_UNSATISFIED
    payload = {"issue": ref["key"], "work": work["key"] if work else None, "pr": args.pr, "changed": False, "previous": None,
               "sha256": None, "errors": []}
    if work and f"{work['owner']}/{work['repo']}".lower() != f"{ref['owner']}/{ref['repo']}".lower():
        payload["errors"] = ["作業 Issue は、管理 Issue と同じリポジトリの Issue にする"]
        _emit(payload)
        return EXIT_UNSATISFIED
    issue, failure = bodies.fetch_issue(ref)
    if failure:
        _emit({**payload, "gh_error": gh.describe_failure(failure)})
        return EXIT_EXTERNAL_FAILED
    payload["sha256"] = issue["sha256"]
    if issue["sha256"] != args.expect_sha256:
        payload["errors"] = ["本文が、読んだとき (--expect-sha256) から変わった。本文を再度読み込んでからやり直す"]
        _emit(payload)
        return EXIT_UNSATISFIED
    plan = mergeplan.read_region(issue["body"])
    if "error" in plan or plan["errors"]:
        payload["errors"] = [plan["error"]] if "error" in plan else _errors_text(plan["errors"])
        _emit(payload)
        return EXIT_UNSATISFIED
    changed = mergeplan.set_pr(plan, work["number"], args.pr) if work else mergeplan.set_managing_pr(plan, args.pr)
    if "error" in changed:
        payload["errors"] = [changed["error"]]
        _emit(payload)
        return EXIT_UNSATISFIED
    payload["previous"] = changed["previous"]
    if changed["previous"] == args.pr:
        _emit(payload)
        return EXIT_OK
    new_body = bodies.replace_region(issue["body"], mergeplan.REGION, mergeplan.render(changed["plan"]))["body"]
    result = bodies.write_body(issue["url"], new_body)
    if gh.failed(result):
        _emit({**payload, "gh_error": gh.describe_failure(result)})
        return EXIT_EXTERNAL_FAILED
    payload.update(changed=True, sha256=bodies.body_sha256(new_body))
    _emit(payload)
    return EXIT_OK


# --- close・dependents --------------------------------------------------------------------------------------------

def _emit_status(result):
    status = result.pop("status")
    if status == "gh_failed":
        result["gh_error"] = gh.describe_failure(result["gh_error"])
        _emit(result)
        return EXIT_EXTERNAL_FAILED
    _emit(result)
    return EXIT_OK if status == "ok" else EXIT_UNSATISFIED


def cmd_checkboxes_common(args):
    ref, error = _issue_ref(args)
    if error:
        _emit({"issue": None, "errors": [error]})
        return EXIT_UNSATISFIED
    return _emit_status(closecheck.common_copies(ref))


def cmd_close_check(args):
    ref, error = _issue_ref(args)
    managing = None
    if not error and args.managing:
        managing = refs.parse_ref(args.managing, default_repo=f"{ref['owner']}/{ref['repo']}")
        error = managing.get("error")
    if not error and args.role == "working" and managing is None:
        error = "--role working では、--managing <管理 Issue> が要る"
    if error:
        _emit({"issue": ref["key"] if ref else None, "satisfied": False, "errors": [error]})
        return EXIT_UNSATISFIED
    return _emit_status(closecheck.check(ref, args.role, managing))


def cmd_dependents_plan(args):
    ref, error = _issue_ref(args)
    if error:
        _emit({"issue": None, "errors": [error]})
        return EXIT_UNSATISFIED
    result = closecheck.dependents_plan(ref)
    for dependent in result["dependents"]:
        dependent.pop("new_body")
    return _emit_status(result)


def cmd_dependents_resolve(args):
    ref, error = _issue_ref(args)
    if error:
        _emit({"issue": None, "errors": [error]})
        return EXIT_UNSATISFIED
    result = closecheck.dependents_resolve(ref)
    for dependent in result["dependents"]:
        dependent.pop("new_body")
    return _emit_status(result)


# --- sessions -----------------------------------------------------------------------------------------------------

def cmd_sessions_active(args):
    ref, error = _issue_ref(args)
    if error:
        _emit({"issue": None, "errors": [error]})
        return EXIT_UNSATISFIED
    issue, failure = bodies.fetch_issue(ref)
    if failure:
        _emit({"issue": ref["key"], "gh_error": gh.describe_failure(failure)})
        return EXIT_EXTERNAL_FAILED
    payload = {"issue": ref["key"], "url": issue["url"], "managing": None, "sessions": [], "excluded": [], "errors": []}
    plan = mergeplan.read_region(issue["body"])
    if "error" in plan or plan["errors"]:
        payload["errors"] = [plan["error"]] if "error" in plan else _errors_text(plan["errors"])
        _emit(payload)
        return EXIT_UNSATISFIED
    numbers = [row["work"]["number"] for row in plan["rows"] if row["work"]["number"] != ref["number"]]
    found, failure = records.active_sessions(ref, numbers)
    if failure:
        _emit({**payload, "gh_error": gh.describe_failure(failure)})
        return EXIT_EXTERNAL_FAILED
    payload.update(found)
    _emit(payload)
    return EXIT_OK


# --- managing -----------------------------------------------------------------------------------------------------

def cmd_managing_plan(args):
    repo = _issues_repo(args)
    if repo is None:
        return EXIT_UNSATISFIED
    return _emit_status(managing.plan(args.file, repo))


def cmd_managing_apply(args):
    repo = _issues_repo(args)
    if repo is None:
        return EXIT_UNSATISFIED
    return _emit_status(managing.apply(args.file, repo))


# --- 引数 ---------------------------------------------------------------------------------------------------------

def _add(sub, name, func, description, output, exit_help):
    parser = sub.add_parser(name, help=description.splitlines()[0], description=description,
                            epilog=f"出力 (標準出力の JSON):\n{output}\n\n{exit_help}",
                            formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.set_defaults(func=func)
    return parser


def build_parser():
    parser = argparse.ArgumentParser(prog="issue_practice.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    groups = parser.add_subparsers(dest="group", required=True)

    g = groups.add_parser("refs", help="識別子 (Issue と PR の参照・マイルストーンの名前) を解析する").add_subparsers(
        dest="command", required=True)
    p = _add(g, "parse", cmd_refs_parse,
             "Issue か PR の参照を解析する。gh は実行しない。\n"
             "受け付ける形: 12・#12 (リポジトリは --repo)・owner/repo#12・https://github.com/owner/repo/issues/12・…/pull/12",
             "  ref     解析した参照 {owner, repo, number, kind (issue・pull・null), key (owner/repo#番号), url}。\n"
             "          12 と #12 で --repo が無いときは、owner・repo・key・url が null。解析できなければ null\n"
             "  errors  解析できなかった理由の配列",
             _exit_help("解析できた", "解析できなかった"))
    p.add_argument("ref", help="参照")
    p.add_argument("--repo", help="12 と #12 の形のときのリポジトリ (owner/repo)")
    p = _add(g, "milestone", cmd_refs_milestone,
             "リリースマイルストーンの名前 (R<番号> (主題) か R<番号> <リリース対象> (主題)) を解析する。gh は実行しない。",
             "  milestone  {number (リリース Issue の番号), target (リリース対象。名前に無ければ null), subject (主題)}。\n"
             "             解析できなければ null\n"
             "  errors     解析できなかった理由の配列",
             _exit_help("解析できた", "名前の形ではない"))
    p.add_argument("name", help="マイルストーンの名前")

    g = groups.add_parser("body", help="Issue の本文を読む").add_subparsers(dest="command", required=True)
    p = _add(g, "show", cmd_body_show,
             "Issue の本文と、本文のハッシュ値 (計画案に書く値。UTF-8 の SHA-256) を返す。読むだけ。\n"
             "--region を付けると、マークで囲んだ範囲 (closing-conditions・merge-plan) も返す",
             "  issue       Issue の参照 (owner/repo#番号)\n"
             "  url・title・state・updated_at   Issue の URL・題名・状態・更新日時\n"
             "  sha256      本文の全体のハッシュ値 (--region を付けても全体のもの)\n"
             "  content     本文の全体\n"
             "  region      --region の範囲 {name, start_line, end_line, content}。付けていなければ null\n"
             "  errors      参照が決まらない・範囲が無いなどの理由の配列\n"
             "  gh_error    gh が失敗したときだけ {args, exit_code, failure, stderr_tail, json_error}",
             _exit_help("読めた (--region の範囲もあった)", "参照が決まらない・範囲が無いか形が崩れている",
                        "gh が失敗した"))
    _add_issue_args(p)
    p.add_argument("--region", choices=bodies.REGIONS, help="返す範囲の名前")

    g = groups.add_parser("draft", help="計画案のファイルを扱う").add_subparsers(dest="command", required=True)
    dir_output = ("  dir       計画案のディレクトリの絶対パス (確認できたときだけ)\n"
                  "  errors    満たさない理由の配列 (--root がルートでない・ディレクトリが git に無視されていない)\n"
                  "  git_error git が失敗したときだけ {args, exit_code, stdout, stderr}")
    dir_exit = _exit_help("ディレクトリが git に無視されている", "--root がリポジトリのルートでない・無視されていない",
                          "git が失敗した (--root がリポジトリでないなど)")
    p = _add(g, "dir-check", cmd_draft_dir_check,
             "計画案のディレクトリ (<ルート>/tmp/issue-practice/) が git に無視されているかを、git check-ignore で確認する。\n"
             "書き込みはしない", dir_output, dir_exit)
    p.add_argument("--root", required=True, help="リポジトリのルートの絶対パス (git rev-parse --show-toplevel の出力)")
    p = _add(g, "path", cmd_draft_path,
             "新しい計画案のパスを決める。dir-check と同じ確認をし、ファイル名が既にあれば返さない (上書きしない)。\n"
             "確認できたら、ディレクトリを作る (ファイルは作らない)",
             "  path       計画案の絶対パス\n"
             "  relative   リポジトリのルートからの相対パス\n"
             "  file_name  ファイル名 (<YYYYMMDD>-<hhmm>-<スキル名>-<対象>.md)\n"
             "  errors     満たさない理由の配列 (dir-check の理由と、スキルの名前・対象の形の誤り・ファイルが既にある)\n"
             "  git_error  git が失敗したときだけ {args, exit_code, stdout, stderr}",
             _exit_help("パスを決めた", "dir-check で満たさない・名前の形の誤り・ファイルが既にある", "git が失敗した"))
    p.add_argument("--root", required=True, help="リポジトリのルートの絶対パス (git rev-parse --show-toplevel の出力)")
    p.add_argument("--skill", required=True, help="計画案を作るスキルの名前")
    p.add_argument("--target", required=True, help="計画の対象 (管理 Issue の番号か、英小文字・数字・ハイフンの短い名前)")
    p.add_argument("--stamp", help="ファイル名の日時 (YYYYMMDD-hhmm)。省略すると今のローカル時刻")
    p = _add(g, "parse", cmd_draft_parse,
             "計画案の先頭の書式 (題と節「元にした Issue」) とファイル名を解析する。gh は実行しない。\n"
             "ファイルを開けないときは、例外で終了する (終了コード 1)",
             "  file_name・title・skill・target・created   ファイル名・題・スキルの名前・対象・作った日時\n"
             "  sources   節「元にした Issue」の項目 {issue, url, sha256, line} の配列\n"
             "  sections  節「元にした Issue」の後のレベル 2 の節 {title, line} の配列\n"
             "  errors    形の誤り {line (行番号。行に結び付かないものは null), message} の配列",
             _exit_help("形どおり", "形が違う"))
    p.add_argument("file", help="計画案のファイルのパス")
    p = _add(g, "compare", cmd_draft_compare,
             "計画案の節「元にした Issue」のすべての Issue の本文を再度読み込み、計画案に書いたハッシュ値と比べる。\n"
             "Issue の updatedAt は比べない (コメントが付くだけでも変わるため)。計画案の形が違えば gh を実行しない",
             "  file_name  計画案のファイル名\n"
             "  results    {issue, url, sha256_draft, sha256_now, changed, updated_at} の配列\n"
             "  errors     本文が変わった Issue か、計画案の形の誤りの配列\n"
             "  gh_error   gh が失敗したときだけ {args, exit_code, failure, stderr_tail, json_error}",
             _exit_help("どの本文も変わっていない", "変わった本文がある・計画案の形が違う", "gh が失敗した"))
    p.add_argument("file", help="計画案のファイルのパス")

    g = groups.add_parser("records", help="記録のコメントを作る・読む").add_subparsers(dest="command", required=True)
    comment_kinds = [k for k, spec in records.KINDS.items() if spec["where"] == "comment"]
    p = _add(g, "format", cmd_records_format,
             "記録のコメントの 1 行目を作る。キーは文書 references/record-comments.md の表の順に並べる。gh は実行しない。\n"
             "--body-line を付けると、作る Issue の本文の末尾の行 (種類 created-from) を作る",
             "  line    作った行。誤りがあれば null\n"
             "  errors  知らない種類・知らないキー・必須のキーが無い・値の形の誤りの配列",
             _exit_help("作れた", "種類・キー・値が形どおりではない"))
    p.add_argument("kind", choices=list(records.KINDS), help="種類")
    p.add_argument("values", nargs="*", metavar="<キー>=<値>", help="キーと値の組")
    p.add_argument("--body-line", action="store_true", help="作る Issue の本文の末尾の行を作る")
    p = _add(g, "parse", cmd_records_parse,
             "記録のコメントの 1 行目を解析する。gh は実行しない。--body-line を付けると、作る Issue の本文の末尾の行として解析する",
             "  kind    種類。誤りがあれば null\n"
             "  values  キーと値の辞書。誤りがあれば null\n"
             "  errors  形の誤りの配列",
             _exit_help("形どおり", "形が違う"))
    p.add_argument("line", help="1 行目")
    p.add_argument("--body-line", action="store_true", help="作る Issue の本文の末尾の行として解析する")
    p = _add(g, "list", cmd_records_list,
             "Issue のコメントを投稿の順に全部読み、記録を集める。読むだけ。\n"
             "投稿者が gh の認証のログインと違うコメントと、1 行目が issue-practice: で始まらないコメントは除く",
             "  issue                  Issue の参照 (owner/repo#番号)\n"
             "  login                  gh の認証のログイン\n"
             "  records                記録 {kind, values, id, url, created_at, updated_at, body} の配列 (投稿の順)。\n"
             "                         body は 1 行目と続く空行を除いた本文\n"
             "  invalid                1 行目が issue-practice: で始まるのに形が違うコメント {id, url, line, errors} の配列\n"
             "  skipped_other_authors  投稿者が違うので除いた、1 行目が issue-practice: で始まるコメントの数\n"
             "  errors                 参照が決まらないときの理由の配列\n"
             "  gh_error               gh が失敗したときだけ {args, exit_code, failure, stderr_tail, json_error}",
             _exit_help("読めて、形の違う記録が無い", "形の違う記録がある・参照が決まらない", "gh が失敗した"))
    _add_issue_args(p)
    p.add_argument("--kind", choices=comment_kinds, help="この種類の記録だけを返す")

    g = g_checkboxes = groups.add_parser("checkboxes", help="節「クローズ条件」のチェックボックスを読む・書く").add_subparsers(
        dest="command", required=True)
    p = _add(g, "list", cmd_checkboxes_list,
             "Issue の本文の節「クローズ条件」のチェックボックスを読み、状態 (unchecked・checked・checked_without_evidence・\n"
             "carved_out) に分ける。読むだけ。範囲は、マーク closing-conditions があればマークの中、無ければ見出しの節",
             "  issue・url  Issue の参照 (owner/repo#番号) と URL\n"
             "  sha256      本文の全体のハッシュ値 (チェックを入れる前の照合に使う)\n"
             "  source      範囲の決め方 (region: マーク、section: 見出し)。範囲が無ければ null\n"
             "  items       項目 {line, text, raw, checked, state, evidence, carved_out, group, heading, indent, details} の配列\n"
             "  summary     {counts (状態ごとの数), unsatisfied (満たさない項目の行番号の配列)}\n"
             "  errors      範囲が無い・マークの形が崩れている・項目が無いときの理由の配列\n"
             "  gh_error    gh が失敗したときだけ {args, exit_code, failure, stderr_tail, json_error}",
             _exit_help("すべての項目が checked か carved_out", "満たさない項目がある・範囲や項目が無い", "gh が失敗した"))
    _add_issue_args(p)

    g = groups.add_parser("release", help="リリース計画 Issue とリリース Issue を読む").add_subparsers(
        dest="command", required=True)
    release_item = ("{order, number, url, title, subject, draft, running, milestone {number, title, url}, selectable, reason}")
    p = _add(g, "current", cmd_release_current,
             "ラベル current の付いたリリース計画 Issue の節「リリースの順番」の表から、今のリリースと次のリリースを決める。読むだけ。\n"
             "規則は文書 references/release-plan-table.md。決めたリリース Issue とリリースマイルストーンのお互いの URL と、\n"
             "今のリリースの記録のコメント draft-removed も確認する",
             "  repo       リポジトリ (owner/repo)\n"
             "  target     --target の値 (指定しなければ null)\n"
             "  targets    リポジトリのラベル release-target:<名前> から集めたリリース対象の名前の配列\n"
             "  plan       表を読んだリリース計画 Issue {number, url, title, created_at}。計画が無ければ null\n"
             "  swapping   ラベル current の付いた計画が 2 つある (付け替えの途中) なら true\n"
             f"  current    今のリリース {release_item}。無ければ null。\n"
             "             running は記録のコメント release-start があるか。--carve-out を付けて running なら selectable が false\n"
             f"  next       次のリリース (current と同じ形)。無ければ null\n"
             "  errors     満たさない理由の配列 (リリース対象の指定が要る・計画が 3 つ以上・表の形・お互いの URL・\n"
             "             draft-removed が無い など)。誤りがあれば current と next は null\n"
             "  gh_error   gh が失敗したときだけ {args, exit_code, failure, stderr_tail, json_error}",
             _exit_help("決められた (今と次が無い場合も含む)", "決めた形が崩れている・リリース対象の指定が要る",
                        "gh が失敗した"))
    p.add_argument("--repo", required=True, help="リポジトリ (owner/repo)")
    p.add_argument("--target", help="リリース対象の名前 (ラベル release-target:<名前> の <名前>)")
    p.add_argument("--carve-out", action="store_true", help="後で行う作業を切り出すときに付ける。実行中の今のリリースを選べないものとして返す")
    release_state = ("{number, url, title, state, draft, running, draft_removed (記録の URL か null), release_start (記録の URL か\n"
                     "             null), milestone {number, title, url, state}, errors}")
    p = _add(g, "review", cmd_release_review,
             "リリースを見直す。読むだけ。決めた形の崩れ (計画の R8: ラベル current の付いた計画が 3 つ以上・表の形・題名の形・\n"
             "リリースマイルストーンが無い・お互いの URL が無い・draft-removed の記録が無いのに [DRAFT] が無い) と、\n"
             "マイルストーンの無い開いた Issue (R37。リリース計画 Issue・リリース Issue・ラベル no-release の付いた Issue を除く) と、\n"
             "本文の節「依存先」に閉じた blocked by の Issue が残っている開いた Issue (R50) を返す",
             "  repo・target・targets  リポジトリ・--target の値・リリース対象の名前の配列\n"
             "  plans      ラベル current の付いたリリース計画 Issue {number, url, title, created_at} の配列\n"
             "  plan       表を読んだリリース計画 Issue {number, url, title} (2 つあれば後に作られたほう)。無ければ null\n"
             "  swapping   ラベル current の付いた計画が 2 つある (付け替えの途中) なら true\n"
             f"  releases   表のリリース Issue の状態 {{order, {release_state[1:]}\n"
             "  unassigned マイルストーンの無い開いた Issue {number, url, title} の配列\n"
             "  dependencies  節「依存先」に閉じた Issue が残っている開いた Issue {number, url, title, resolved [{number, url}]}\n"
             "  errors     決めた形の崩れの配列\n"
             "  gh_error   gh が失敗したときだけ {args, exit_code, failure, stderr_tail, json_error}",
             _exit_help("決めた形の崩れが無い (unassigned と dependencies はあってもよい)",
                        "決めた形の崩れがある・リリース対象の指定が要る", "gh が失敗した"))
    p.add_argument("--repo", required=True, help="リポジトリ (owner/repo)")
    p.add_argument("--target", help="リリース対象の名前 (ラベル release-target:<名前> の <名前>)")
    p = _add(g, "show", cmd_release_show,
             "リリース Issue 1 つの状態を返す。読むだけ。題名の形・リリースマイルストーンとお互いの URL・記録のコメント\n"
             "(draft-removed・release-start)・メモ (記録ではないコメント)・本文の節「参照」の PR を読む",
             "  issue・url・title・state・sha256  リリース Issue の参照・URL・題名・状態・本文のハッシュ値\n"
             "  target・subject  題名のリリース対象 (無ければ null) と主題\n"
             "  draft・running   題名に [DRAFT] があるか・記録のコメント release-start があるか\n"
             "  draft_removed・release_start  記録のコメントの URL (無ければ null)\n"
             "  milestone  リリースマイルストーン {number, title, url, state}。見つからなければ null\n"
             "  prs        本文の節「参照」の「- PR: <URL>」の URL の配列\n"
             "  memos      メモ {url, author, created_at, first_line} の配列 (投稿の順)\n"
             "  errors     決めた形の崩れの配列\n"
             "  gh_error   gh が失敗したときだけ {args, exit_code, failure, stderr_tail, json_error}",
             _exit_help("決めた形どおり", "決めた形の崩れがある", "gh が失敗した"))
    _add_issue_args(p)
    release_output = (
        "  draft・repo・kind・target  計画案のファイル名・リポジトリ・種類 (新しい計画・急ぎのリリースの追加)・リリース対象\n"
        "  current      今の計画 {number, url} (計画案の項目「今の計画」)。無ければ null\n"
        "  plan         新しいリリース計画 Issue {number, url} (作り済みのとき)。無ければ null\n"
        "  current_plans  ラベル current の付いた計画の番号の配列\n"
        "  labels_to_create  作るラベル {name, color, description} の配列\n"
        "  actions      行う書き込み {step, action, ...} の配列 (済んだものは含まない)。step は計画の R38 の手順の番号\n"
        "               (0 はラベルの作成、7 は取りやめたリリース)。急ぎのリリースの追加では、1 が approval の記録、2 が\n"
        "               リリース Issue とマイルストーン、3 が表の書き換え、4 が plan-change の記録。action は\n"
        "               create-label・create-plan・record-approval・create-release・set-release-number・create-milestone・\n"
        "               set-milestone-description・write-release-body・set-milestone・remove-milestone・add-label・\n"
        "               write-plan-table・add-current・remove-current・record-current-swap・close-old-plan・copy-memo・\n"
        "               record-cancel・close-cancelled-release・close-cancelled-milestone・record-plan-change のどれか\n"
        "  errors       誤り {line (計画案の行番号。行に結び付かないものは null), message} の配列\n"
        "  gh_error     gh が失敗したときだけ {args, exit_code, failure, stderr_tail, json_error}")
    p = _add(g, "plan", cmd_release_plan,
             "リリース計画の計画案 (書式は文書 skills/release-plan/references/release-plan-issue.md) と GitHub の今の状態から、\n"
             "行う書き込みの一覧を返す (示す)。GitHub には書き込まない。計画案の形が違えば gh を実行しない。\n"
             "途中で中断した状態 (ラベル current が 2 つ・古い計画が開いているなど) を読み、済んでいない書き込みだけを返す",
             release_output,
             _exit_help("示せた", "計画案の形が違う・GitHub の状態が計画案と合わない (今の計画の本文が変わった・ラベル current の\n"
                                  "     付いた計画が違うなど)", "gh が失敗した"))
    p.add_argument("file", help="計画案のファイルのパス")
    p.add_argument("--repo", required=True, help="リポジトリ (owner/repo)。#番号 の参照もこのリポジトリで解決する")
    p = _add(g, "apply", cmd_release_apply,
             "plan と同じ確認をし、誤りが無ければ書き込む (実行する)。途中で失敗したら、同じ計画案でやり直せる\n"
             "(作り済みの Issue とマイルストーンは作らず、済んでいない書き込みだけを行う)",
             release_output + "\n"
             "  done         行った書き込み (actions と同じ形。作ったものは url を持つ) の配列。gh が失敗したときは、\n"
             "               失敗する前までのもの\n"
             "  releases     表のキーの行のリリース Issue {key, number, url, milestone, milestone_url} の配列",
             _exit_help("すべて書き込んだ (か、書き込み済みだった)",
                        "plan で満たさない (何も書き込まない)。書き込みの途中で、作り済みの Issue の本文が変わっていると\n"
                        "     分かったときも 3 (done までは書き込んだ)", "gh が失敗した (done までは書き込んだ)"))
    p.add_argument("file", help="計画案のファイルのパス")
    p.add_argument("--repo", required=True, help="リポジトリ (owner/repo)。#番号 の参照もこのリポジトリで解決する")

    g = groups.add_parser("issues", help="計画案の節「作る Issue」から Issue を作る").add_subparsers(
        dest="command", required=True)
    issues_output = (
        "  draft             計画案のファイル名\n"
        "  repo              リポジトリ (owner/repo)\n"
        "  labels_to_create  作るラベル {name, color, description} の配列 (スキルが作るラベルで、リポジトリに無いもの)\n"
        "  items             作る Issue {key, title, line, issue, actions} の配列 (計画案の順)。issue は作り済みなら\n"
        "                    {number, url}、無ければ null。actions は行う書き込み {action, ...} の配列で、action は\n"
        "                    create (title・milestone・labels)・set-milestone (milestone)・add-labels (labels)・\n"
        "                    set-parent (parent)・add-blocked-by (issues) のどれか。作り済みで足りないものが無ければ空\n"
        "  errors            誤り {line (計画案の行番号。行に結び付かないものは null), message} の配列\n"
        "  gh_error          gh が失敗したときだけ {args, exit_code, failure, stderr_tail, json_error}")
    p = _add(g, "plan", cmd_issues_plan,
             "計画案 (先頭の書式と節「作る Issue」。書式は文書 references/issue-bodies.md) と GitHub の今の状態から、\n"
             "行う書き込みの一覧を返す (示す)。GitHub には書き込まない。計画案の形が違えば gh を実行しない。\n"
             "本文の末尾に同じ created-from の行を持つ開いた Issue は作り済みとして扱い、足りない設定だけを返す",
             issues_output,
             _exit_help("一覧を作れた", "計画案の形が違う・GitHub の状態が計画案と合わない", "gh が失敗した"))
    p.add_argument("file", help="計画案のファイルのパス")
    p.add_argument("--repo", required=True, help="Issue を作るリポジトリ (owner/repo)。#番号 の参照もこのリポジトリで解決する")
    p = _add(g, "create", cmd_issues_create,
             "plan と同じ一覧を作り、誤りが無ければ書き込む (実行する)。ラベルを作り、Issue を上から順に作って、\n"
             "マイルストーン・ラベル・親 Issue・blocked by を設定する。途中で失敗したら、同じ計画案でやり直せる\n"
             "(作り済みの Issue は作らず、足りない設定だけを行う)",
             issues_output + "\n"
             "  done              行った書き込み {key, action, url} の配列 (action は create-label・record-approval と\n"
             "                    actions の action)。gh が失敗したときは、失敗する前までのもの\n"
             "  issues            作った (か作り済みの) Issue {key, url} の配列",
             _exit_help("すべて書き込んだ", "計画案の形が違う・GitHub の状態が計画案と合わない (何も書き込まない)",
                        "gh が失敗した (done までは書き込んだ)"))
    p.add_argument("file", help="計画案のファイルのパス")
    p.add_argument("--repo", required=True, help="Issue を作るリポジトリ (owner/repo)。#番号 の参照もこのリポジトリで解決する")
    p.add_argument("--record-approval", action="store_true",
                   help="Issue ごとに、記録のコメント approval (draft=<計画案のファイル名>) が無ければ書く")

    p = _add(g_checkboxes, "check", cmd_checkboxes_check,
             "節「クローズ条件」の項目 (--line) にチェックを入れ、末尾に (根拠: <URL>) か (切り出し: <URL>) を足して、本文を書き換える。\n"
             "本文が --expect-sha256 (checkboxes list の sha256) から変わっていれば書かない。既に同じリンクがあれば書かない。\n"
             "別のリンクがあれば書かない (上書きしない)",
             "  issue・url  Issue の参照と URL\n"
             "  line        --line の値\n"
             "  changed     本文を書き換えたか\n"
             "  item        書いた後の項目 (checkboxes list の items の要素と同じ形)。書けなかったら null\n"
             "  sha256      書いた後の本文のハッシュ値 (書かなかったときは今の本文のハッシュ値)\n"
             "  errors      本文が変わった・項目ではない行・既に別のリンクがある・URL ではないなどの理由の配列\n"
             "  gh_error    gh が失敗したときだけ {args, exit_code, failure, stderr_tail, json_error}",
             _exit_help("書いた (か、既に同じリンクがあった)", "本文が変わった・項目ではない・別のリンクがある (何も書かない)",
                        "gh が失敗した"))
    _add_issue_args(p)
    p.add_argument("--line", required=True, type=int, help="項目の行番号 (checkboxes list の items の line)")
    link = p.add_mutually_exclusive_group(required=True)
    link.add_argument("--evidence", help="根拠の URL (テストを実行した PR・確認を記録したコメントなど)")
    link.add_argument("--carved-out", help="切り出した Issue の URL")
    p.add_argument("--expect-sha256", required=True, help="読んだときの本文のハッシュ値 (checkboxes list の sha256)")
    p = _add(g_checkboxes, "common", cmd_checkboxes_common,
             "管理 Issue の節「すべての作業 Issue に共通するクローズ条件」の項目と、PR マージ計画の表の開いている作業 Issue の\n"
             "共通の条件のコピーを比べる。読むだけ。項目の文と「期待する状態」「確認するポイント」の分類を、上から順に比べる",
             "  issue・url  管理 Issue の参照と URL\n"
             "  common      管理 Issue の共通の項目 {group, text} の配列\n"
             "  outdated    コピーが古い作業 Issue {number, url, expected, actual} の配列\n"
             "  up_to_date  コピーが同じ作業 Issue {number, url} の配列\n"
             "  skipped     閉じているので比べなかった作業 Issue {number, url} の配列\n"
             "  errors      PR マージ計画やクローズ条件の形の誤りの配列\n"
             "  gh_error    gh が失敗したときだけ {args, exit_code, failure, stderr_tail, json_error}",
             _exit_help("どの開いている作業 Issue のコピーも同じ", "コピーが古い作業 Issue がある・形の誤り", "gh が失敗した"))
    _add_issue_args(p)

    g = groups.add_parser("close", help="閉じる前の検査をする").add_subparsers(dest="command", required=True)
    p = _add(g, "check", cmd_close_check,
             "Issue を閉じる前の検査をする。読むだけ。検査することは文書 references/closing-conditions.md の節「閉じる前の検査」。\n"
             "--role working は作業 Issue (--managing に管理 Issue)、managing は管理 Issue、self-managing は自己管理 Issue",
             "  issue・url  Issue の参照と URL\n"
             "  role        --role の値\n"
             "  managing    --managing の参照 (owner/repo#番号)。無ければ null\n"
             "  satisfied   満たすか\n"
             "  unsatisfied 満たさない項目 {kind, message, line, url} の配列。kind は checkbox (line は本文の行番号)・pr・\n"
             "              common・milestone・work-issue・managing-pr のどれか\n"
             "  evidence    根拠の URL (チェックの根拠・切り出し・マージされた PR) の配列\n"
             "  pr          作業 Issue か自己管理 Issue の PR {url, state, merged, base}。読まなかったら null\n"
             "  managing_pr 管理 Issue の PR (構成 2・3 の managing のときだけ)\n"
             "  checkboxes  チェックボックスの {counts, unsatisfied}。managing では共通の条件の項目を数えない\n"
             "  work_issues 作業 Issue {number, url, state} の配列 (managing のときだけ)\n"
             "  blocking    この Issue を依存先とする、開いている Issue {number, url, title, state} の配列\n"
             "  errors      クローズ条件や PR マージ計画の形の誤り・表に行が無いなどの配列\n"
             "  gh_error    gh が失敗したときだけ {args, exit_code, failure, stderr_tail, json_error}",
             _exit_help("満たす", "満たさない項目がある・形の誤り", "gh が失敗した (検査できなかった)"))
    _add_issue_args(p)
    p.add_argument("--role", required=True, choices=closecheck.ROLES, help="閉じる Issue の種類")
    p.add_argument("--managing", help="管理 Issue の参照 (--role working のとき)")

    g = groups.add_parser("dependents", help="閉じる Issue を依存先とする Issue に、片付いたことを書く").add_subparsers(
        dest="command", required=True)
    dependents_output = (
        "  issue・url・state  閉じる Issue の参照・URL・状態\n"
        "  dependents  この Issue を依存先とする開いた Issue {number, url, sha256, actions} の配列。actions は\n"
        "              {action: comment, line (記録のコメントの 1 行目)} と {action: edit-dependencies, removed (消す行),\n"
        "              section_removed (節ごと消すか)}。記録が既にあり、消す項目も無ければ空\n"
        "  errors      満たさない理由の配列\n"
        "  gh_error    gh が失敗したときだけ {args, exit_code, failure, stderr_tail, json_error}")
    p = _add(g, "plan", cmd_dependents_plan,
             "閉じる Issue を依存先とする開いた Issue (blocking) に行う書き込みを示す (示す)。書き込まない。\n"
             "書き込みは、記録のコメント dependency-resolved と、節「依存先」から閉じる Issue の項目を消すこと",
             dependents_output, _exit_help("示せた", "使わない", "gh が失敗した"))
    _add_issue_args(p)
    p = _add(g, "resolve", cmd_dependents_resolve,
             "plan の書き込みを行う (実行する)。Issue が閉じていなければ書かない。もう一度実行しても、書いた記録と\n"
             "消した項目は書かない",
             dependents_output + "\n  done        行った書き込み {number, action, url} の配列",
             _exit_help("書き込んだ", "Issue が閉じていない", "gh が失敗した (done までは書き込んだ)"))
    _add_issue_args(p)

    g = groups.add_parser("sessions", help="記録のコメントからセッションを集める").add_subparsers(dest="command", required=True)
    p = _add(g, "active", cmd_sessions_active,
             "管理 Issue の管理セッションと、PR マージ計画の表の作業 Issue の動いている作業セッションを、記録のコメント session\n"
             "から集める。読むだけ。作業 Issue ごとに最後の session の記録を使い、閉じた作業 Issue・session の記録が無い\n"
             "作業 Issue・そのセッションの abandon の記録がある作業 Issue を除く。名前は記録の本文の「- 作業セッションの名前: 」の行",
             "  issue・url  管理 Issue の参照と URL\n"
             "  managing    管理 Issue の最後の session の記録 (role=managing) {session, previous, branch, name, record_url}。\n"
             "              無ければ null\n"
             "  sessions    動いている作業セッション {number, url, session, previous, branch, name, record_url} の配列。\n"
             "              name は記録に名前の行が無ければ null\n"
             "  excluded    除いた作業 Issue {number, url, reason (closed・no-session・abandoned)} の配列\n"
             "  errors      PR マージ計画が無い・形の誤りの配列\n"
             "  gh_error    gh が失敗したときだけ {args, exit_code, failure, stderr_tail, json_error}",
             _exit_help("集められた", "PR マージ計画が無いか形が違う", "gh が失敗した"))
    _add_issue_args(p)

    g = groups.add_parser("managing", help="管理 Issue (か自己管理 Issue) の計画案を GitHub に書く").add_subparsers(
        dest="command", required=True)
    managing_output = (
        "  draft・repo  計画案のファイル名とリポジトリ\n"
        "  target      計画する Issue {issue, url, kind (管理 Issue・自己管理 Issue)}\n"
        "  body_state  計画する Issue の本文の状態。pending (これから書く)・applied (書き込み済み)・changed (計画案を\n"
        "              作ったときから変わった)\n"
        "  issues      作業 Issue の書き込み {labels_to_create, items} (issues plan と同じ形)。作業 Issue を作らなければ null\n"
        "  merge_plan  {settings, rows, content}。content は本文のマーク merge-plan の中に書く中身 (作業 Issue を作る前は、\n"
        "              キーと <番号> のまま)\n"
        "  closing_conditions  本文の節「クローズ条件」に書く中身\n"
        "  approval_recorded   計画する Issue に、この計画案の approval の記録があるか\n"
        "  errors      誤り {line (計画案の行番号。行に結び付かないものは null), message} の配列\n"
        "  gh_error    gh が失敗したときだけ {args, exit_code, failure, stderr_tail, json_error}")
    p = _add(g, "plan", cmd_managing_plan,
             "管理 Issue (か自己管理 Issue) の計画案 (書式は文書 skills/managing-issue-plan/references/merge-plan.md) と GitHub の\n"
             "今の状態から、行う書き込みを示す (示す)。GitHub には書き込まない。計画案の形が違えば gh を実行しない",
             managing_output,
             _exit_help("示せた", "計画案の形が違う・本文が変わった・本文に書き込めない (同じ見出しの節が複数あるなど)・\n"
                                  "     マイルストーンが違う・GitHub の状態が計画案と合わない", "gh が失敗した"))
    p.add_argument("file", help="計画案のファイルのパス")
    p.add_argument("--repo", required=True, help="作業 Issue を作るリポジトリ (owner/repo)。#番号 の参照もこのリポジトリで解決する")
    p = _add(g, "apply", cmd_managing_apply,
             "plan と同じ確認をし、誤りが無ければ書き込む (実行する)。作業 Issue を作り (作業 Issue ごとに approval の記録も書く)、\n"
             "表のキーを作った Issue の番号に置き換えて、計画する Issue の本文の節「クローズ条件」と「PR マージ計画」を書き換え、\n"
             "計画する Issue に approval の記録を書く。途中で失敗したら、同じ計画案でやり直せる",
             managing_output + "\n"
             "  done        行った書き込み {key, action, url} の配列 (action は issues create の action と、write-body・\n"
             "              record-approval)。gh が失敗したときと、作業 Issue を作った後に本文が変わったと分かったときは、\n"
             "              中断する前までのもの",
             _exit_help("すべて書き込んだ (か、書き込み済みだった)",
                        "plan で満たさない (何も書き込まない)。plan で読んだ後から計画する Issue の本文が変わったと、\n"
                        "     作業 Issue を作った後に分かったときも 3 (done までは書き込んだ)",
                        "gh が失敗した (done までは書き込んだ)"))
    p.add_argument("file", help="計画案のファイルのパス")
    p.add_argument("--repo", required=True, help="作業 Issue を作るリポジトリ (owner/repo)。#番号 の参照もこのリポジトリで解決する")

    g = groups.add_parser("merge-plan", help="管理 Issue の PR マージ計画を読む・書く").add_subparsers(
        dest="command", required=True)
    rows_help = ("  rows      表の行 {order, work {number, key, description, url}, branch, base, requires (番号の配列), pr,\n"
                 "            pr_url, line} の配列 (表の順)")
    p = _add(g, "show", cmd_merge_plan_show,
             "管理 Issue の本文のマーク merge-plan の範囲から、設定と PR マージ計画の表を読み、表から gitGraph の図を作って、\n"
             "本文の図と比べる。読むだけ。書式は文書 skills/managing-issue-plan/references/merge-plan.md",
             "  issue・url  管理 Issue の参照 (owner/repo#番号) と URL\n"
             "  sha256    本文の全体のハッシュ値 (set-pr の --expect-sha256 に渡す)\n"
             "  settings  設定 {config (1・2・3), merger (利用者・管理セッション), managing_branch, managing_base, managing_pr}\n"
             f"{rows_help}\n"
             "  graph     表から作った図 (mermaid の gitGraph)。表に誤りがあれば null\n"
             "  graph_matches       本文の図が graph と同じか。表に誤りがあれば null\n"
             "  managing_pr_notice  構成 2 のとき、管理 Issue の PR の本文の先頭に書く注意書き。ほかの構成では null\n"
             "  errors    範囲が無い・表や設定の形の誤りの配列\n"
             "  gh_error  gh が失敗したときだけ {args, exit_code, failure, stderr_tail, json_error}",
             _exit_help("表が形どおりで、本文の図が表から作った図と同じ", "範囲が無い・表や設定の形の誤り・図が表と違う",
                        "gh が失敗した"))
    _add_issue_args(p)
    p = _add(g, "set-pr", cmd_merge_plan_set_pr,
             "管理 Issue の PR マージ計画の表で、作業 Issue (--work) の行の、列「PR」に PR の URL を書き、図を作り直して本文を\n"
             "書き換える。--work を付けなければ、設定「管理 Issue の PR」に書く (ブランチの構成 2・3 だけ)。\n"
             "本文が --expect-sha256 (show の sha256) から変わっていれば書かない。列が既に同じ URL なら書かない",
             "  issue     管理 Issue の参照\n"
             "  work      作業 Issue の参照 (--work を付けなければ null)\n"
             "  pr        書いた PR の URL\n"
             "  changed   本文を書き換えたか\n"
             "  previous  列「PR」の書き換える前の値 (空なら null)\n"
             "  sha256    書いた後の本文のハッシュ値 (書かなかったときは今の本文のハッシュ値)\n"
             "  errors    本文が変わった・行が無い・URL が PR ではない・表の形の誤りの配列\n"
             "  gh_error  gh が失敗したときだけ {args, exit_code, failure, stderr_tail, json_error}",
             _exit_help("書いた (か、既に同じ URL だった)", "本文が変わった・行が無い・形の誤り (何も書かない)", "gh が失敗した"))
    _add_issue_args(p)
    p.add_argument("--work", help="作業 Issue の参照 (#番号・番号・URL。リポジトリは管理 Issue と同じ)。付けなければ管理 Issue の PR")
    p.add_argument("--pr", required=True, help="PR の URL (https://github.com/<owner>/<repo>/pull/<番号>)")
    p.add_argument("--expect-sha256", required=True, help="読んだときの本文のハッシュ値 (merge-plan show の sha256)")


    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
