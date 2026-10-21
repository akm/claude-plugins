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

from issue_dispatch import config, filekinds, record, repo


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
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
