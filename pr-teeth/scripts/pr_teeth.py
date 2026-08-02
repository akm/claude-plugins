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

from prteeth import (  # noqa: E402
    agent_input, auth, config, document, glossary, labels, prspec, render, scope, state,
    store,
)


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

    saved = {}
    if args.mode == "changes-only":
        # prepare は読むだけで保存しないため、壊れていても続行してよい。
        # ただし黙って空扱いにすると全件が新規に見えるので、必ず理由を伝える。
        try:
            saved = store.load_precious(paths["state"], {})
        except store.Corrupt as e:
            warnings.append(
                str(e) + "。全件が新規として扱われます。"
                "意図しない場合は state.json を退避または修復してください。"
            )

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
    # state も蓄積データ。壊れていれば止める（空扱いすると全件を再通知してしまう）。
    saved = store.load_precious(paths["state"], {})

    with open(args.input, "r", encoding="utf-8") as f:
        raw = json.load(f)
    prs, skipped = agent_input.prs(raw)
    warnings.extend(skipped)

    targets = state.select_targets(saved, prs)
    return _emit({
        "targets": targets,
        "total": len(prs),
        "skipped": len(skipped),
        "selected": len(targets),
        "warnings": warnings,
    })


def cmd_resolve(args):
    """PR の指定（`owner/repo#123` や URL）を repo / number に解釈する。

    番号指定コマンド（/pr-teeth-pick）の入口。解釈をモデルに任せると、URL の末尾や
    フラグメントの取り違えで**別の PR を正しい体裁で解説してしまう**（読み手には
    誤りと分からない）。ここで機械的に確定させる。

    解釈できなかった指定は `invalid` に理由付きで返す。黙って捨てない。
    """
    warnings = []
    _, _, cfg = _load(args, warnings)

    # 解釈できなかった指定は `invalid` だけに入れる。`warnings` にも同じものを
    # 積むと、SKILL.md が両方を出すよう指示しているため同じ文言が2回並ぶ。
    # `warnings` は他のコマンドと同じく設定読み込みの問題のために取っておく。
    targets, errors = prspec.parse(args.specs)
    for t in targets:
        t["language"] = config.resolve_language(t["repo"], cfg, args.lang)

    return _emit({
        "targets": targets,
        "requested": len(args.specs),
        "resolved": len(targets),
        "invalid": errors,
        "default_language": config.default_language(cfg, args.lang),
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
    # lookup は読むだけで保存しない。壊れていても続行できるが、全語が new に
    # 見えてしまうため、既知の語まで再説明されないよう理由を必ず伝える。
    try:
        g = _load_glossary(paths)
    except store.Corrupt as e:
        warnings.append(
            str(e) + "。すべての語が未登録として扱われます。"
            "説明が増えるのを避けるには glossary.json を退避または修復してください。"
        )
        g = glossary.load_or_seed({})

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


def _out_path(paths, name, default_name):
    """HTML の出力先を決める。

    相対パスは設定ディレクトリの `out/` 配下に解決する。利用者は作業中のリポジトリで
    コマンドを呼ぶため、素直に相対解決すると生成物がそのリポジトリに散らかる。
    絶対パスを渡されたときだけ、その場所をそのまま使う。
    """
    os.makedirs(paths["out"], exist_ok=True)
    name = name or default_name
    return name if os.path.isabs(name) else os.path.join(paths["out"], name)


def _open_command(path):
    """生成した HTML を開くコマンドを返す。

    パスにはタイムスタンプが入り設定ディレクトリ配下にあるため、手で打つには長い。
    そのまま実行できる形で返し、利用者が「どう開くか」を考えずに済むようにする。
    プラットフォームの判定をモデルに委ねると実行のたびに揺れるため、ここで決める。
    """
    if sys.platform == "darwin":
        opener = "open"
    elif sys.platform == "win32":
        opener = "start"
    else:
        # Linux / WSL。WSL でも xdg-open は既定のブラウザに渡せる。
        opener = "xdg-open"
    return opener + ' "' + path + '"'


def _load_glossary(paths):
    """用語集を読む。壊れていれば Corrupt が上がり、保存に進まない。

    無い場合は seed を作る（正常な初回実行）。壊れている場合に seed で上書きすると
    蓄積した学習を失うため、そこは区別する。docs/design/data-integrity.md 参照。
    """
    return glossary.load_or_seed(store.load_precious(paths["glossary"], {}))


def cmd_record(args):
    """出現した語と新しく書いた定義を用語集に反映する。state も必要なら更新。"""
    warnings = []
    config_dir, paths, _ = _load(args, warnings)
    g = _load_glossary(paths)

    with open(args.input, "r", encoding="utf-8") as f:
        payload = json.load(f)
    # 形が違えば例外で止まる。黙って0件記録して成功を返さない。
    items, skipped = agent_input.terms(payload)
    warnings.extend(skipped)

    now = _now()
    for item in items:
        glossary.record(
            g,
            item["term"],
            language=item.get("language"),
            definition=item.get("definition"),
            provenance=item.get("provenance"),
            now=now,
        )
    store.save_json(paths["glossary"], g)

    def _read_prs(path):
        with open(path, "r", encoding="utf-8") as f:
            accepted, bad = agent_input.prs(json.load(f))
        warnings.extend(bad)
        return accepted

    saved_state = False
    state_recorded = 0
    state_pruned = 0
    if args.notified or args.open_prs:
        # state は changes-only のときだけ更新する（第11節）。
        # --notified は部分でよい（マージ）。--open-prs は完全な一覧の宣言で、
        # 渡されたときだけ、そこに無い記録を掃除する。
        saved = store.load_precious(paths["state"], {})
        recorded = _read_prs(args.notified) if args.notified else []
        prune_to = _read_prs(args.open_prs) if args.open_prs else None
        before = set(state.load_notified(saved))
        updated = state.record_notified(saved, recorded, prune_to=prune_to)
        after = set(state.load_notified(updated))
        store.save_json(paths["state"], updated)
        saved_state = True
        state_recorded = len(recorded)
        state_pruned = len(before - after)

    return _emit({
        "glossary_path": paths["glossary"],
        # 受理件数を返す。0 件なら入力が意図どおりでなかったと気づける。
        "terms_recorded": len(items),
        "terms_skipped": len(skipped),
        "counts": glossary.counts(g),
        "state_saved": saved_state,
        "state_recorded": state_recorded,
        "state_pruned": state_pruned,
        "warnings": warnings,
    })


def cmd_promote(args):
    """ユーザーの確認を経たステータス変更を確定する。"""
    warnings = []
    config_dir, paths, _ = _load(args, warnings)
    g = _load_glossary(paths)
    existed = glossary.get(g, args.term) is not None
    entry = glossary.set_status(g, args.term, args.status, now=_now())
    store.save_json(paths["glossary"], g)
    if not existed:
        # 綴り違いを黙って新規作成すると、直したつもりの語が別エントリになる。
        warnings.append(
            "「" + args.term + "」は用語集にありませんでした。新規に登録しています"
            "（綴りが違っていないか確認してください）。"
        )
    return _emit({
        "term": args.term,
        "status": entry.get("status"),
        "created": not existed,
        "counts": glossary.counts(g),
        "warnings": warnings,
    })


def cmd_render(args):
    """解説データを自己完結 HTML にして保存する。"""
    warnings = []
    config_dir, paths, cfg = _load(args, warnings)

    with open(args.input, "r", encoding="utf-8") as f:
        payload = json.load(f)
    # キー名の誤りや必須の欠落はここで弾く。黙って空のセクションを出さない。
    # 畳み込みと並び替えも from_payload が行う。
    # --context は入力 JSON の context より優先する（コマンド側が文脈を知っている）。
    if args.context:
        payload = dict(payload, context=args.context)
    doc = document.from_payload(payload)
    if not doc.language:
        doc.language = config.default_language(cfg, args.lang)
    if not doc.generated_at:
        doc.generated_at = _now()
    doc.warnings = list(doc.warnings) + warnings

    # 既定のファイル名に文脈を入れる。巡回と番号指定の生成物が out/ に混ざったとき、
    # ファイル名だけでどちらか分かるようにする。
    prefix = "pr-teeth-pick-" if doc.context == labels.CONTEXT_PICK else "pr-teeth-"
    path = _out_path(
        paths, args.output, prefix + _now().replace(":", "").replace("-", "") + ".html"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(render.render(doc))

    return _emit({
        "path": path,
        "open_command": _open_command(path),
        "count": len(doc.prs),
        "warnings": doc.warnings,
    })


def cmd_glossary_html(args):
    """用語集をポートフォリオ HTML にする（/pr-glossary）。"""
    warnings = []
    config_dir, paths, cfg = _load(args, warnings)
    # 表示するだけなので続行できるが、空のポートフォリオを黙って見せると
    # 「学習が消えた」と誤解させるため、理由を必ず添える。
    try:
        g = _load_glossary(paths)
    except store.Corrupt as e:
        warnings.append(
            str(e) + "。用語集を読めないため空で表示しています。"
            "ファイルを退避または修復してください（この画面では上書きしていません）。"
        )
        g = glossary.load_or_seed({})
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
    path = _out_path(paths, args.output, "pr-glossary.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(render.render_glossary(data))
    return _emit({
        "path": path,
        "open_command": _open_command(path),
        "counts": glossary.counts(g),
        "warnings": warnings,
    })


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

    sp = sub.add_parser("resolve", help="PR の指定を repo / number に解釈する")
    common(sp)
    sp.add_argument(
        "specs",
        nargs="+",
        help="PR の指定。owner/repo#123 または https://github.com/owner/repo/pull/123。"
             "`#` が shell で消える場合は owner/repo/123 でもよい",
    )
    sp.set_defaults(func=cmd_resolve)

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
        "--notified",
        default=None,
        help='changes-only のときだけ渡す。今回処理した PR: '
             '[{"repo","number","sha","updated_at"}]。既存の記録にマージする'
             "（部分的な一覧でよい）",
    )
    sp.add_argument(
        "--open-prs",
        default=None,
        help="オープンな依頼の**全件**を渡せたときだけ指定する。同じ形式。"
             "ここに無い記録を掃除する（閉じた PR の記録を消すため）。"
             "取得が途中で失敗した・件数上限で切り詰めた場合は渡さないこと",
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
    sp.add_argument(
        "--input",
        required=True,
        help='解説データ JSON: {"prs": [{"repo": "<owner/repo>", "number": <番号>, '
             '"title": "...", "priority": "must_review|should_review|ignore", '
             '"language", "author", "counts", "summary", "background", "recommendation", '
             '"changes": [], "review_points": [], "terms": [{"term","definition","status","evidence"}], '
             '"diagram", "note"}]}。必須は repo / number / title / priority。'
             "url は repo と number から導出するので渡さない。詳細は SKILL.md。",
    )
    sp.add_argument("--output", default=None)
    sp.add_argument(
        "--context",
        default=None,
        choices=[labels.CONTEXT_PATROL, labels.CONTEXT_PICK],
        help="レビュー範囲の表示文言を切り替える。既定は " + labels.CONTEXT_PATROL
             + "（巡回）。番号指定 (/pr-teeth-pick) では " + labels.CONTEXT_PICK
             + " を渡し、「重点 / 参考 / 周辺」で表示する。分類の値そのものは変わらない",
    )
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
    except store.Corrupt as e:
        # 蓄積データが壊れている。保存には進んでいないので、元ファイルは無事。
        json.dump({
            "error": str(e),
            "hint": "上書きを避けるため保存していません。"
                    + e.path + " を退避（別名にコピー）してから削除するか、"
                    "JSON として直せる場合は修復してください。",
            "path": e.path,
        }, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 1
    except (agent_input.InvalidInput, document.InvalidDocument) as e:
        # 入力の形が違う。期待する形は例外メッセージに含まれている。
        json.dump({"error": str(e)}, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 1
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
