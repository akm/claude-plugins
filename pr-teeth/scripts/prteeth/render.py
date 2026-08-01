"""自己完結 HTML の生成（pr-teeth プラグイン）。

CONCEPTS.md 第9節の実装。

CSS はインライン。オフラインで開けることを優先する。Mermaid だけは図がある場合に
CDN から読み込むが、**読み込めなくても本文が読めるように**、元のコードを
<pre> として残し、描画できたときにそれを置き換える方式にする。
"""

import html

from . import labels

# 範囲名 → CSS クラス。表示文言は labels 側で言語ごとに切り替える。
_SCOPE_CLASS = {
    "must_review": "must",
    "should_review": "should",
    "ignore": "ignore",
}

_CSS = """
:root {
  --fg: #1a1a1a; --bg: #fff; --muted: #666; --line: #e0e0e0;
  --must: #b3261e; --should: #7a5900; --ignore: #5a5a5a;
  --card: #fafafa; --accent: #0b57d0;
}
@media (prefers-color-scheme: dark) {
  :root {
    --fg: #e8e8e8; --bg: #16181c; --muted: #a0a0a0; --line: #333;
    --must: #ff8a80; --should: #ffd54f; --ignore: #b0b0b0;
    --card: #1e2126; --accent: #8ab4f8;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 2rem 1rem 4rem; background: var(--bg); color: var(--fg);
  font-family: system-ui, -apple-system, "Hiragino Sans", "Noto Sans JP", sans-serif;
  line-height: 1.8; font-size: 16px;
}
main { max-width: 52rem; margin: 0 auto; }
h1 { font-size: 1.6rem; line-height: 1.4; margin: 0 0 .5rem; }
h2 { font-size: 1.2rem; line-height: 1.5; margin: 0 0 .25rem; }
h3 { font-size: 1rem; margin: 1.5rem 0 .5rem; }
a { color: var(--accent); }
.sub { color: var(--muted); font-size: .9rem; margin-bottom: 2rem; }
.warn {
  border-left: 4px solid var(--should); background: var(--card);
  padding: .75rem 1rem; margin: 0 0 1.5rem; border-radius: 4px;
}
.warn ul { margin: .5rem 0 0; padding-left: 1.2rem; }
.pr {
  border: 1px solid var(--line); border-radius: 8px; padding: 1.25rem 1.5rem;
  margin-bottom: 1.5rem; background: var(--card);
}
.pr.collapsed { padding: .75rem 1.5rem; }
.meta { color: var(--muted); font-size: .85rem; margin-bottom: .75rem; }
.badge {
  display: inline-block; font-size: .75rem; font-weight: 700; padding: .1rem .5rem;
  border-radius: 999px; border: 1px solid currentColor; margin-left: .5rem;
  vertical-align: middle;
}
.badge.must { color: var(--must); }
.badge.should { color: var(--should); }
.badge.ignore { color: var(--ignore); }
/* 用語ポートフォリオのステータス別 */
.badge.known { color: var(--accent); }
.badge.learning { color: var(--should); }
.badge.new { color: var(--muted); }
.scope { font-size: .9rem; margin: .75rem 0; }
.scope span { margin-right: 1rem; white-space: nowrap; }
.term { border-left: 3px solid var(--line); padding-left: .9rem; margin: .75rem 0; }
.term .t { font-weight: 700; }
.term .s { color: var(--muted); font-size: .8rem; margin-left: .4rem; }
.src { color: var(--muted); font-size: .85rem; }
code {
  background: rgba(127,127,127,.15); padding: .1rem .35rem; border-radius: 3px;
  font-size: .9em; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
pre { overflow-x: auto; background: rgba(127,127,127,.1); padding: .75rem; border-radius: 6px; }
pre code { background: none; padding: 0; }
.mermaid-wrap { overflow-x: auto; margin: 1rem 0; }
footer { color: var(--muted); font-size: .85rem; margin-top: 3rem; text-align: center; }
"""

# Mermaid は CDN から。読めなくても本文は読めるよう、失敗時は元のコードを残す。
_MERMAID = """
<script src="https://cdnjs.cloudflare.com/ajax/libs/mermaid/10.9.1/mermaid.min.js"></script>
<script>
(function () {
  if (!window.mermaid) return;  // オフライン等。<pre> のまま残す。
  var dark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  mermaid.initialize({ startOnLoad: false, theme: dark ? 'dark' : 'default' });
  document.querySelectorAll('pre.mermaid-src').forEach(function (el, i) {
    var code = el.textContent;
    var box = document.createElement('div');
    box.className = 'mermaid-wrap';
    el.parentNode.insertBefore(box, el);
    mermaid.render('m' + i, code).then(function (r) {
      box.innerHTML = r.svg;
      el.remove();
    }).catch(function () { box.remove(); });  // 描画失敗時もコードは残る
  });
})();
</script>
"""


def _e(text):
    return html.escape(str(text if text is not None else ""))


def _scope_summary(counts, L):
    parts = []
    for key in ("must_review", "should_review", "ignore"):
        n = (counts or {}).get(key) or 0
        if not n:
            continue
        parts.append(
            '<span class="' + _SCOPE_CLASS[key] + '">' + _e(L[key]) + ": " + str(n) + "</span>"
        )
    return "".join(parts)


def _render_terms(terms, L):
    if not terms:
        return ""
    out = ["<h3>" + _e(L["terms"]) + "</h3>"]
    for t in terms:
        status = t.get("status") or ""
        # known は説明しない語なので、そもそも渡ってこない想定。来ても出さない。
        if status == "known":
            continue
        out.append('<div class="term">')
        out.append('<span class="t">' + _e(t.get("term")) + "</span>")
        if status:
            out.append('<span class="s">' + _e(status) + "</span>")
        out.append("<div>" + _e(t.get("definition")) + "</div>")
        if t.get("evidence"):
            out.append('<div class="src">' + _e(L["evidence"]) + ": " + _e(t["evidence"]) + "</div>")
        out.append("</div>")
    return "\n".join(out)


def _render_pr(pr):
    lang = pr.get("language") or "ja"
    # 見出しもその PR の言語に合わせる。本文だけ英語で見出しが日本語だと読めない。
    L = labels.for_language(lang)
    counts = pr.get("counts") or {}
    priority = pr.get("priority") or "should_review"
    cls = _SCOPE_CLASS.get(priority, "should")
    label = L.get(priority, L["should_review"])
    collapsed = bool(pr.get("collapsed"))

    out = []
    out.append('<article class="pr' + (" collapsed" if collapsed else "") + '" lang="' + _e(lang) + '">')
    title = _e(pr.get("title"))
    url = pr.get("url")
    heading = '<a href="' + _e(url) + '">' + title + "</a>" if url else title
    out.append("<h2>" + heading + '<span class="badge ' + cls + '">' + _e(label) + "</span></h2>")
    out.append('<div class="meta">' + _e(pr.get("repo")) + " #" + _e(pr.get("number")))
    if pr.get("author"):
        out.append(" · " + _e(pr["author"]))
    out.append("</div>")

    summary = _scope_summary(counts, L)
    if summary:
        out.append('<div class="scope">' + summary + "</div>")

    if collapsed:
        # ignore のみの PR は1行に畳む。リンクは残す（第7節）。
        if pr.get("summary"):
            out.append("<div>" + _e(pr["summary"]) + "</div>")
        out.append("</article>")
        return "\n".join(out)

    if pr.get("recommendation"):
        out.append("<p>" + _e(pr["recommendation"]) + "</p>")
    if pr.get("summary"):
        out.append("<h3>" + _e(L["summary"]) + "</h3><p>" + _e(pr["summary"]) + "</p>")
    if pr.get("background"):
        out.append("<h3>" + _e(L["background"]) + "</h3><p>" + _e(pr["background"]) + "</p>")
    if pr.get("diagram"):
        out.append('<pre class="mermaid-src">' + _e(pr["diagram"]) + "</pre>")
    if pr.get("changes"):
        out.append("<h3>" + _e(L["changes"]) + "</h3><ul>")
        for c in pr["changes"]:
            out.append("<li>" + _e(c) + "</li>")
        out.append("</ul>")
    if pr.get("review_points"):
        out.append("<h3>" + _e(L["review_points"]) + "</h3><ul>")
        for c in pr["review_points"]:
            out.append("<li>" + _e(c) + "</li>")
        out.append("</ul>")
    out.append(_render_terms(pr.get("terms"), L))
    if pr.get("note"):
        out.append('<div class="warn">' + _e(pr["note"]) + "</div>")
    out.append("</article>")
    return "\n".join(out)


def render_glossary(data):
    """用語ポートフォリオの HTML（第8節 /pr-glossary）。

    PR 用の描画を流用すると「必須」バッジや PR 件数といった無関係な体裁が付くため、
    専用の描画にする。
    """
    lang = data.get("language") or "ja"
    L = labels.for_language(lang)
    groups = data.get("groups") or []
    warnings = data.get("warnings") or []
    total = sum(len(g.get("terms") or []) for g in groups)

    out = ['<!doctype html>', '<html lang="' + _e(lang) + '">', "<head>",
           '<meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1">',
           "<title>" + _e(L["glossary_title"]) + "</title>",
           "<style>" + _CSS + "</style>", "</head>", "<body>", "<main>"]
    out.append("<h1>" + _e(L["glossary_title"]) + "</h1>")
    sub = []
    if data.get("generated_at"):
        sub.append(_e(data["generated_at"]))
    sub.append(str(total) + L["terms_count"])
    out.append('<div class="sub">' + " · ".join(sub) + "</div>")

    if warnings:
        out.append('<div class="warn"><strong>' + _e(L["warning"]) + "</strong><ul>")
        for w in warnings:
            out.append("<li>" + _e(w) + "</li>")
        out.append("</ul></div>")

    for group in groups:
        terms = group.get("terms") or []
        if not terms:
            continue
        status = group.get("status") or ""
        out.append('<section class="pr">')
        out.append(
            "<h2>" + _e(L.get(status, status))
            + '<span class="badge ' + _e(status) + '">' + str(len(terms)) + "</span></h2>"
        )
        for t in terms:
            out.append('<div class="term">')
            out.append('<span class="t">' + _e(t.get("term")) + "</span>")
            if t.get("occurrences"):
                out.append('<span class="s">×' + _e(t["occurrences"]) + "</span>")
            out.append("<div>" + _e(t.get("definition")) + "</div>")
            if t.get("evidence"):
                out.append('<div class="src">' + _e(L["evidence"]) + ": " + _e(t["evidence"]) + "</div>")
            out.append("</div>")
        out.append("</section>")

    out.append("</main></body></html>")
    return "\n".join(out)


def render(data):
    """解説データ全体を自己完結 HTML にする。

    data:
      title, language, generated_at, warnings[], prs[]
    """
    lang = data.get("language") or "ja"
    # ページ全体の地の文はユーザー既定の言語（第5.3節）。
    L = labels.for_language(lang)
    prs = data.get("prs") or []
    warnings = data.get("warnings") or []
    has_diagram = any(p.get("diagram") for p in prs)
    title = data.get("title") or L["page_title"]

    out = ['<!doctype html>', '<html lang="' + _e(lang) + '">', "<head>",
           '<meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1">',
           "<title>" + _e(title) + "</title>",
           "<style>" + _CSS + "</style>", "</head>", "<body>", "<main>"]
    out.append("<h1>" + _e(title) + "</h1>")
    sub = []
    if data.get("generated_at"):
        sub.append(_e(data["generated_at"]))
    sub.append(str(len(prs)) + L["count_suffix"])
    out.append('<div class="sub">' + " · ".join(sub) + "</div>")

    if warnings:
        out.append('<div class="warn"><strong>' + _e(L["warning"]) + "</strong><ul>")
        for w in warnings:
            out.append("<li>" + _e(w) + "</li>")
        out.append("</ul></div>")

    if not prs:
        out.append("<p>" + _e(L["no_prs"]) + "</p>")
    for pr in prs:
        out.append(_render_pr(pr))

    out.append("</main>")
    if has_diagram:
        out.append(_MERMAID)
    out.append("</body></html>")
    return "\n".join(out)
