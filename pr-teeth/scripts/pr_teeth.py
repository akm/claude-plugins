#!/usr/bin/env python3
"""pr-teeth の CLI（SKILL.md から呼ばれる）。

判定・保存・描画のうち、機械的に決まる部分をここに閉じ込める。モデルが担うのは
「読んで、噛み砕いて、書く」ことだけにし、範囲判定や用語のステータス遷移が実行の
たびに揺れないようにする。

出力はすべて JSON（stdout）。トークンの値は決して出力しない。
"""

import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from prteeth import auth, config, glossary, labels, render, scope, state, store  # noqa: E402


def _paths(config_dir):
    return {
        "config": os.path.join(config_dir, "config.toml"),
        "glossary": os.path.join(config_dir, "glossary.json"),
        "state": os.path.join(config_dir, "state.json"),
        "out": os.path.join(config_dir, "out"),
        "repos_dir": os.path.join(config_dir, "repos"),
    }


def _load(args, warnings):
    """設定ディレクトリ・パス一覧・設定内容を返す。

    設定は config.toml 1枚にまとまっている（言語もリポジトリ別設定も同じファイル）。
    """
    d = config.config_dir(args.plugin_source)
    p = _paths(d)
    return d, p, store.load_toml(p["config"], {}, warnings)


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _emit(obj):
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


def cmd_prepare(args):
    """設定を読み、言語と認証の有無を返す。skill の最初に呼ぶ。"""
    warnings = []
    config_dir, paths, cfg = _load(args, warnings)

    token, source, token_error = auth.resolve()
    if not token:
        if token_error:
            warnings.append(token_error)
        warnings.append(
            "GitHub のトークンが見つかりません。次のいずれかを設定してください: "
            "環境変数 " + auth.ENV_TOKEN + "、"
            "環境変数 " + auth.ENV_TOKEN_FILE + "（トークンを書いたファイルのパス）、"
            "または `gh auth login`。"
        )

    saved = store.load_json(paths["state"], {}, warnings) if args.mode == "changes-only" else {}

    return _emit({
        "config_dir": config_dir,
        "paths": paths,
        "mode": args.mode,
        "default_language": config.default_language(cfg, args.lang),
        # トークンの値は返さない。入手元だけ。
        "token_source": source,
        "has_token": bool(token),
        "notified": state.load_notified(saved),
        "warnings": warnings,
    })


def cmd_select(args):
    """PR 一覧から、新規・更新のものだけを選ぶ（mode=changes-only）。

    入力: [{"repo","number","sha","updated_at", ...}]
    出力: 対象のみ。status(new/updated) と base_sha(差分の起点) が付く。
    """
    warnings = []
    _, paths, _ = _load(args, warnings)
    saved = store.load_json(paths["state"], {}, warnings)

    with open(args.input, "r", encoding="utf-8") as f:
        prs = json.load(f)
    if isinstance(prs, dict):
        prs = prs.get("prs") or []

    targets = state.select_targets(saved, prs)
    return _emit({
        "targets": targets,
        "total": len(prs),
        "selected": len(targets),
        "warnings": warnings,
    })


def cmd_classify(args):
    """PR の変更ファイルを範囲分類し、その PR の出力言語を決める。"""
    warnings = []
    _, _, cfg = _load(args, warnings)

    if args.files_from:
        raw = store.load_json(args.files_from, None, warnings)
        if raw is None:
            with open(args.files_from, "r", encoding="utf-8") as f:
                raw = json.load(f)
    else:
        raw = json.load(sys.stdin)

    # gh の `--json files` は [{"path": ...}] を返す。素の文字列配列も受ける。
    if isinstance(raw, dict):
        raw = raw.get("files") or []
    files = [x.get("path") if isinstance(x, dict) else x for x in raw]
    files = [f for f in files if f]

    result = scope.classify_files(files, args.repo, cfg)
    result["repo"] = args.repo
    result["language"] = config.resolve_language(args.repo, cfg, args.lang)
    result["warnings"] = warnings
    return _emit(result)


def cmd_lookup(args):
    """語のステータスと、その言語の既存定義を引く。"""
    warnings = []
    config_dir, paths, _ = _load(args, warnings)
    g = glossary.load_or_seed(store.load_json(paths["glossary"], {}, warnings))

    out = []
    for term in args.terms:
        out.append({
            "term": term,
            "status": glossary.status_of(g, term),
            "needs_explanation": glossary.needs_explanation(g, term),
            "definition": glossary.definition_for(g, term, args.language),
            "other_languages": glossary.other_language_definitions(g, term, args.language),
        })
    return _emit({"language": args.language, "terms": out, "warnings": warnings})


def cmd_record(args):
    """出現した語と新しく書いた定義を用語集に反映する。state も必要なら更新。"""
    warnings = []
    config_dir, paths, _ = _load(args, warnings)
    g = glossary.load_or_seed(store.load_json(paths["glossary"], {}, warnings))

    with open(args.input, "r", encoding="utf-8") as f:
        payload = json.load(f)

    now = _now()
    for item in payload.get("terms") or []:
        glossary.record(
            g,
            item.get("term"),
            language=item.get("language"),
            definition=item.get("definition"),
            provenance=item.get("provenance"),
            now=now,
        )
    store.save_json(paths["glossary"], g)

    saved_state = False
    if args.state:
        # state は changes-only のときだけ更新する（第11節）。
        with open(args.state, "r", encoding="utf-8") as f:
            prs = json.load(f)
        if isinstance(prs, dict):
            prs = prs.get("prs") or []
        # オープンな依頼の全件を渡す。ここに無い記録は掃除される。
        store.save_json(paths["state"], state.record_notified({}, prs))
        saved_state = True

    return _emit({
        "glossary_path": paths["glossary"],
        "counts": glossary.counts(g),
        "state_saved": saved_state,
        "warnings": warnings,
    })


def cmd_promote(args):
    """ユーザーの確認を経たステータス変更を確定する。"""
    warnings = []
    config_dir, paths, _ = _load(args, warnings)
    g = glossary.load_or_seed(store.load_json(paths["glossary"], {}, warnings))
    entry = glossary.set_status(g, args.term, args.status, now=_now())
    store.save_json(paths["glossary"], g)
    return _emit({"term": args.term, "status": entry.get("status"), "counts": glossary.counts(g)})


def cmd_render(args):
    """解説データを自己完結 HTML にして保存する。"""
    warnings = []
    config_dir, paths, cfg = _load(args, warnings)

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("language", config.default_language(cfg, args.lang))
    data.setdefault("generated_at", _now())
    data["warnings"] = list(data.get("warnings") or []) + warnings

    # ignore のみの PR は1行に畳む（第7節）。
    for pr in data.get("prs") or []:
        if pr.get("collapsed") is None:
            pr["collapsed"] = pr.get("priority") == scope.IGNORE
    data["prs"] = sorted(
        data.get("prs") or [],
        key=lambda p: scope.sort_key({"priority": p.get("priority") or scope.SHOULD}),
    )

    os.makedirs(paths["out"], exist_ok=True)
    name = args.output or ("pr-teeth-" + _now().replace(":", "").replace("-", "") + ".html")
    path = name if os.path.isabs(name) else os.path.join(paths["out"], name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(render.render(data))

    return _emit({"path": path, "count": len(data["prs"]), "warnings": data["warnings"]})


def cmd_glossary_html(args):
    """用語集をポートフォリオ HTML にする（/pr-glossary）。"""
    warnings = []
    config_dir, paths, cfg = _load(args, warnings)
    g = glossary.load_or_seed(store.load_json(paths["glossary"], {}, warnings))
    language = config.default_language(cfg, args.lang)

    L = labels.for_language(language)
    by_status = {glossary.KNOWN: [], glossary.LEARNING: [], glossary.NEW: []}
    for entry in (g.get("terms") or {}).values():
        by_status.setdefault(entry.get("status") or glossary.NEW, []).append(entry)

    groups = []
    # 到達度が分かるよう known を先頭に、以降 learning → new の順で並べる。
    for status in (glossary.KNOWN, glossary.LEARNING, glossary.NEW):
        items = sorted(by_status.get(status) or [], key=lambda e: str(e.get("term") or "").lower())
        if not items:
            continue
        terms = []
        for e in items:
            defs = e.get("definitions") or {}
            text = defs.get(language)
            if not text and defs:
                # その言語の定義がまだ無くても、既存の定義を隠さない（第8節）。
                other = next(iter(defs.items()))
                text = "(" + other[0] + ") " + other[1]
            terms.append({
                "term": e.get("term"),
                "definition": text or L["no_definition"],
                "occurrences": e.get("occurrences") or 0,
                "evidence": e.get("provenance"),
            })
        groups.append({"status": status, "terms": terms})

    data = {
        "language": language,
        "generated_at": _now(),
        "warnings": warnings,
        "groups": groups,
    }
    os.makedirs(paths["out"], exist_ok=True)
    path = args.output or os.path.join(paths["out"], "pr-glossary.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(render.render_glossary(data))
    return _emit({"path": path, "counts": glossary.counts(g), "warnings": warnings})


def main(argv=None):
    p = argparse.ArgumentParser(description="pr-teeth の内部 CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument(
            "--plugin-source",
            required=True,
            help="配布元 (<host>/<owner>/<repo>)。SKILL.md のリテラル値を渡す。",
        )
        sp.add_argument("--lang", default=None, help="実行時の言語上書き")

    sp = sub.add_parser("prepare", help="設定・言語・認証の有無を返す")
    common(sp)
    sp.add_argument("--mode", default="full", choices=["full", "changes-only"])
    sp.set_defaults(func=cmd_prepare)

    sp = sub.add_parser("classify", help="変更ファイルを範囲分類する")
    common(sp)
    sp.add_argument("--repo", required=True, help="owner/repo")
    sp.add_argument("--files-from", default=None, help="ファイル一覧 JSON。省略時は stdin")
    sp.set_defaults(func=cmd_classify)

    sp = sub.add_parser("lookup", help="語のステータスと既存定義を引く")
    common(sp)
    sp.add_argument("--language", required=True)
    sp.add_argument("--terms", nargs="+", required=True)
    sp.set_defaults(func=cmd_lookup)

    sp = sub.add_parser("record", help="出現語と定義を用語集に反映する")
    common(sp)
    sp.add_argument("--input", required=True, help='{"terms":[{"term","language","definition"}]}')
    sp.add_argument(
        "--state",
        default=None,
        help='changes-only のときだけ渡す。[{"repo","number","sha","updated_at"}] '
             "(オープンな依頼の全件。ここに無い記録は掃除される)",
    )
    sp.set_defaults(func=cmd_record)

    sp = sub.add_parser("select", help="新規・更新の PR だけを選ぶ (changes-only)")
    common(sp)
    sp.add_argument("--input", required=True, help='[{"repo","number","sha","updated_at"}]')
    sp.set_defaults(func=cmd_select)

    sp = sub.add_parser("promote", help="ステータスを確定する（要ユーザー確認）")
    common(sp)
    sp.add_argument("--term", required=True)
    sp.add_argument("--status", required=True, choices=["new", "learning", "known"])
    sp.set_defaults(func=cmd_promote)

    sp = sub.add_parser("render", help="解説を自己完結 HTML にする")
    common(sp)
    sp.add_argument("--input", required=True, help="解説データ JSON")
    sp.add_argument("--output", default=None)
    sp.add_argument("--open", action="store_true", help="（互換のため受けるが何もしない）")
    sp.set_defaults(func=cmd_render)

    sp = sub.add_parser("glossary-html", help="用語ポートフォリオを HTML にする")
    common(sp)
    sp.add_argument("--output", default=None)
    sp.set_defaults(func=cmd_glossary_html)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except BrokenPipeError:
        return 0
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
