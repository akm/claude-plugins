package main

import (
	"regexp"
	"strings"
	"unicode"
)

// block は Markdown の構造 1 つ (見出し・表・箇条書き・段落・節)。Start と End は 1 始まりの行番号で、
// End は含む。節 (section) の Start は見出しの行。
type block struct {
	Kind    string // heading / table / list / paragraph / section / code
	Start   int
	End     int
	Heading string // heading と section の見出しの文 (先頭の # を除く)
	Level   int    // heading と section の見出しの深さ
}

// document は 1 ファイルの構造。行は 1 始まりで参照する (lines[0] は使わない)。
type document struct {
	lines    []string // lines[1..n]
	headings []block
	tables   []block
	lists    []block
	codes    []block
}

var (
	headingLine  = regexp.MustCompile(`^(#{1,6})\s+(.*?)\s*#*\s*$`)
	listItemLine = regexp.MustCompile(`^\s*(?:[-*+]|\d+[.)])\s+`)
	fenceLine    = regexp.MustCompile("^\\s*(```|~~~)")
)

// parseMarkdown は行の列から構造を読む。末尾の空行 (ファイル末尾の改行による空要素) は落とす。
// コードフェンスの中の行は見出し・表・箇条書きとして読まない。
func parseMarkdown(raw []string) *document {
	lines := append([]string{}, raw...)
	for len(lines) > 0 && strings.TrimSpace(lines[len(lines)-1]) == "" {
		lines = lines[:len(lines)-1]
	}
	d := &document{lines: append([]string{""}, lines...)}
	n := len(lines)
	inFence := false
	fenceStart := 0
	for i := 1; i <= n; i++ {
		l := d.lines[i]
		if fenceLine.MatchString(l) {
			if inFence {
				d.codes = append(d.codes, block{Kind: "code", Start: fenceStart, End: i})
				inFence = false
			} else {
				inFence = true
				fenceStart = i
			}
			continue
		}
		if inFence {
			continue
		}
		if m := headingLine.FindStringSubmatch(l); m != nil {
			d.headings = append(d.headings, block{Kind: "heading", Start: i, End: i, Heading: m[2], Level: len(m[1])})
		}
	}
	if inFence {
		d.codes = append(d.codes, block{Kind: "code", Start: fenceStart, End: n})
	}
	// 表: 先頭が | の行の連続。
	for i := 1; i <= n; {
		if d.inCode(i) || !isTableLine(d.lines[i]) {
			i++
			continue
		}
		start := i
		for i <= n && !d.inCode(i) && isTableLine(d.lines[i]) {
			i++
		}
		d.tables = append(d.tables, block{Kind: "table", Start: start, End: i - 1})
	}
	// 箇条書き: 項目の行から始まり、項目・字下げされた続きの行・(次が項目か続きなら) 空行、で続く範囲。
	for i := 1; i <= n; {
		if d.inCode(i) || !listItemLine.MatchString(d.lines[i]) {
			i++
			continue
		}
		start := i
		end := i
		for j := i + 1; j <= n; j++ {
			l := d.lines[j]
			switch {
			case d.inCode(j):
				j = n // フェンスは箇条書きの続きではない
			case listItemLine.MatchString(l), isIndentedContinuation(l):
				end = j
				continue
			case strings.TrimSpace(l) == "":
				// 空行は、次の非空行が項目か続きなら箇条書きの中。
				k := j + 1
				for k <= n && strings.TrimSpace(d.lines[k]) == "" {
					k++
				}
				if k <= n && !d.inCode(k) && (listItemLine.MatchString(d.lines[k]) || isIndentedContinuation(d.lines[k])) {
					continue
				}
			}
			break
		}
		d.lists = append(d.lists, block{Kind: "list", Start: start, End: end})
		i = end + 1
	}
	return d
}

func isTableLine(l string) bool { return strings.HasPrefix(strings.TrimLeft(l, " \t"), "|") }

func isIndentedContinuation(l string) bool {
	return strings.TrimSpace(l) != "" && (strings.HasPrefix(l, "  ") || strings.HasPrefix(l, "\t"))
}

func (d *document) inCode(n int) bool {
	for _, c := range d.codes {
		if c.Start <= n && n <= c.End {
			return true
		}
	}
	return false
}

func blockAt(blocks []block, n int) *block {
	for i := range blocks {
		if blocks[i].Start <= n && n <= blocks[i].End {
			b := blocks[i]
			return &b
		}
	}
	return nil
}

// tableAt は n 行目を含む表を返す。無ければ nil。
func (d *document) tableAt(n int) *block { return blockAt(d.tables, n) }

// listAt は n 行目を含む箇条書きを返す。無ければ nil。
func (d *document) listAt(n int) *block { return blockAt(d.lists, n) }

// sectionAt は n 行目を含む節 (直前の見出しから、同じ深さ以上の次の見出しの前まで) を返す。
// 見出しより前の行なら、ファイルの先頭からの範囲を見出し無しで返す。
func (d *document) sectionAt(n int) *block {
	var h *block
	for i := range d.headings {
		if d.headings[i].Start <= n {
			b := d.headings[i]
			h = &b
		}
	}
	if h == nil {
		end := len(d.lines) - 1
		if len(d.headings) > 0 {
			end = d.headings[0].Start - 1
		}
		return &block{Kind: "section", Start: 1, End: end}
	}
	return d.sectionOf(*h)
}

func (d *document) sectionOf(h block) *block {
	end := len(d.lines) - 1
	for _, o := range d.headings {
		if o.Start > h.Start && o.Level <= h.Level {
			end = o.Start - 1
			break
		}
	}
	return &block{Kind: "section", Start: h.Start, End: end, Heading: h.Heading, Level: h.Level}
}

// sectionByAnchor はアンカー (先頭の # を除いた文字列) に一致する見出しの節を返す。
// 見出しの文と、その slug の両方で照合する。
func (d *document) sectionByAnchor(anchor string) *block {
	anchor = strings.TrimPrefix(anchor, "#")
	for _, h := range d.headings {
		if h.Heading == anchor || slug(h.Heading) == anchor || slug(h.Heading) == slug(anchor) {
			return d.sectionOf(h)
		}
	}
	return nil
}

// blockBefore は n 行目より前の、直近の非空の構造 (見出し・表・箇条書き・段落) を返す。
// 箇条書きの「親」(それを導入する段落や見出し) を読むために使う。
func (d *document) blockBefore(n int) *block {
	i := n - 1
	for i >= 1 && strings.TrimSpace(d.lines[i]) == "" {
		i--
	}
	if i < 1 {
		return nil
	}
	for _, h := range d.headings {
		if h.Start == i {
			b := h
			return &b
		}
	}
	if t := d.tableAt(i); t != nil {
		return t
	}
	if l := d.listAt(i); l != nil {
		return l
	}
	// 段落: 空行で区切られた非空の行の連続。
	start := i
	for start > 1 && strings.TrimSpace(d.lines[start-1]) != "" && !d.isStructural(start-1) {
		start--
	}
	return &block{Kind: "paragraph", Start: start, End: i}
}

func (d *document) isStructural(n int) bool {
	for _, h := range d.headings {
		if h.Start == n {
			return true
		}
	}
	return d.tableAt(n) != nil || d.listAt(n) != nil || d.inCode(n)
}

// slug は見出しの文から GitHub 風のアンカーを作る (小文字化・記号を落とす・空白をハイフンに)。
// 日本語の文字はそのまま残す。
func slug(s string) string {
	var b strings.Builder
	for _, r := range strings.ToLower(strings.TrimSpace(s)) {
		switch {
		case r == ' ':
			b.WriteRune('-')
		case r == '-' || r == '_':
			b.WriteRune(r)
		case unicode.IsLetter(r) || unicode.IsNumber(r) || unicode.Is(unicode.Mn, r):
			b.WriteRune(r)
		}
	}
	return b.String()
}
