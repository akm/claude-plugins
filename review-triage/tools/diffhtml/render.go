package main

import (
	"html"
	"strings"
)

// diffStyle は、差分の色分けに使う <style>。fill が </head> の前に 1 度だけ入れる。
// 日本語の長い 1 行が横に伸びないように、行を折り返す。
const diffStyle = `<style id="` + styleID + `">
.rt-diff { border: 1px solid #d0d7de; border-radius: 6px; margin: 0.5rem 0; overflow: auto; }
.rt-diff pre { margin: 0; padding: 0.5rem 0; font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
               white-space: pre-wrap; overflow-wrap: anywhere; }
.rt-diff span { display: block; padding: 0 0.75rem; min-height: 1.5em; }
.rt-diff .rt-file { color: #57606a; font-weight: 600; background: #f6f8fa; }
.rt-diff .rt-hunk { color: #0550ae; background: #ddf4ff; }
.rt-diff .rt-add { background: #e6ffec; }
.rt-diff .rt-del { background: #ffebe9; }
.rt-diff .rt-add mark { background: #abf2bc; }
.rt-diff .rt-del mark { background: #ff8182; }
.rt-diff .rt-meta { color: #57606a; }
</style>
`

// diffLine は、差分の 1 行と、その種類 (CSS のクラス名)。
type diffLine struct {
	class string
	text  string
	// mark は、行の中で強調する部分 (text の rune の位置。先頭の +・- を含む)。from == to なら強調しない
	from, to int
}

// renderDiff は、unified diff を、行の種類で色を分けた HTML の断片にする。
func renderDiff(diff string) string {
	lines := classify(diff)
	markPairs(lines)
	var b strings.Builder
	b.WriteString(`<div class="rt-diff"><pre>`)
	for _, l := range lines {
		b.WriteString(`<span class="` + l.class + `">`)
		r := []rune(l.text)
		if l.from < l.to {
			b.WriteString(html.EscapeString(string(r[:l.from])))
			b.WriteString("<mark>" + html.EscapeString(string(r[l.from:l.to])) + "</mark>")
			b.WriteString(html.EscapeString(string(r[l.to:])))
		} else {
			b.WriteString(html.EscapeString(l.text))
		}
		b.WriteString("</span>")
	}
	b.WriteString("</pre></div>")
	return b.String()
}

// classify は、行の種類を決める。diff --git から最初の @@ の前まではファイルの見出しで、
// hunk の中は先頭の 1 文字で決める。hunk の中の --- や +++ で始まる行を見出しとして扱わないため、
// 位置 (見出しの中か hunk の中か) で分ける。
func classify(diff string) []diffLine {
	text := strings.TrimSuffix(diff, "\n")
	if text == "" {
		return nil
	}
	var out []diffLine
	inHunk := false
	for _, s := range strings.Split(text, "\n") {
		class := "rt-file"
		switch {
		case strings.HasPrefix(s, "diff --git "):
			inHunk = false
		case strings.HasPrefix(s, "@@"):
			inHunk = true
			class = "rt-hunk"
		case !inHunk:
		case strings.HasPrefix(s, "+"):
			class = "rt-add"
		case strings.HasPrefix(s, "-"):
			class = "rt-del"
		case strings.HasPrefix(s, `\`):
			class = "rt-meta"
		default:
			class = "rt-ctx"
		}
		out = append(out, diffLine{class: class, text: s})
	}
	return out
}

// markPairs は、続けて並ぶ削除の行と追加の行を先頭から順に 1 つずつ組にし、組の 2 行から先頭と末尾の
// 共通部分を除いた部分を強調の範囲にする。共通部分が無い組は、行全体が変わったので強調しない。
func markPairs(lines []diffLine) {
	for i := 0; i < len(lines); {
		if lines[i].class != "rt-del" {
			i++
			continue
		}
		delStart := i
		for i < len(lines) && lines[i].class == "rt-del" {
			i++
		}
		addStart := i
		for i < len(lines) && lines[i].class == "rt-add" {
			i++
		}
		dels, adds := lines[delStart:addStart], lines[addStart:i]
		for k := 0; k < len(dels) && k < len(adds); k++ {
			markPair(&dels[k], &adds[k])
		}
	}
}

func markPair(del, add *diffLine) {
	a, b := []rune(del.text)[1:], []rune(add.text)[1:]
	p := 0
	for p < len(a) && p < len(b) && a[p] == b[p] {
		p++
	}
	s := 0
	for s < len(a)-p && s < len(b)-p && a[len(a)-1-s] == b[len(b)-1-s] {
		s++
	}
	if p == 0 && s == 0 {
		return
	}
	// 位置は先頭の +・- の 1 文字を含めて数える
	del.from, del.to = 1+p, 1+len(a)-s
	add.from, add.to = 1+p, 1+len(b)-s
}
