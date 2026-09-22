package main

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

// edge は読み直す範囲 1 つ (近くの辺)。File はリポジトリのルートからの相対パス。
type edge struct {
	File    string
	Kind    string // table / list / section / link / paragraph / heading
	Start   int
	End     int
	Heading string
	Reason  string
	Lines   []int // この範囲を読む理由になった変更行
	Parent  *edge // 箇条書きの親 (直前の段落か見出し)
}

var linkPattern = regexp.MustCompile(`\]\(([^)\s]+)\)`)

// nearEdges は変更行ごとに読み直す範囲を求め、同じ範囲はまとめて返す。
// 表のセルならその表の全行、箇条書きの項目なら同じ箇条書き全体と親、段落なら節全体、
// 変更行のリンクならその参照先の節。
func nearEdges(root string, changes map[string][]change) ([]edge, error) {
	docs := map[string]*document{}
	load := func(rel string) (*document, error) {
		if d, ok := docs[rel]; ok {
			return d, nil
		}
		data, err := os.ReadFile(filepath.Join(root, rel))
		if err != nil {
			return nil, err
		}
		d := parseMarkdown(strings.Split(string(data), "\n"))
		docs[rel] = d
		return d, nil
	}
	type key struct {
		file, kind string
		start, end int
	}
	merged := map[key]*edge{}
	order := []key{}
	add := func(e edge, line int) {
		k := key{e.File, e.Kind, e.Start, e.End}
		if ex, ok := merged[k]; ok {
			ex.Lines = append(ex.Lines, line)
			return
		}
		e.Lines = []int{line}
		merged[k] = &e
		order = append(order, k)
	}
	files := make([]string, 0, len(changes))
	for f := range changes {
		files = append(files, f)
	}
	sort.Strings(files)
	for _, f := range files {
		if !strings.HasSuffix(f, ".md") {
			continue
		}
		d, err := load(f)
		if err != nil {
			return nil, fmt.Errorf("%s: %w", f, err)
		}
		for _, c := range changes[f] {
			n := c.Line
			if n > len(d.lines)-1 {
				n = len(d.lines) - 1
			}
			if n < 1 {
				continue
			}
			switch {
			case d.tableAt(n) != nil:
				t := d.tableAt(n)
				add(edge{File: f, Kind: "table", Start: t.Start, End: t.End, Reason: "表のセルを変えた — その表の全行"}, n)
			case d.listAt(n) != nil:
				l := d.listAt(n)
				e := edge{File: f, Kind: "list", Start: l.Start, End: l.End, Reason: "箇条書きの項目を変えた — 同じ箇条書き全体と、その親"}
				if p := d.blockBefore(l.Start); p != nil {
					e.Parent = &edge{File: f, Kind: p.Kind, Start: p.Start, End: p.End, Heading: p.Heading}
				}
				add(e, n)
			default:
				s := d.sectionAt(n)
				add(edge{File: f, Kind: "section", Start: s.Start, End: s.End, Heading: s.Heading, Reason: "段落を変えた — 同じ節の全文"}, n)
			}
			for _, m := range linkPattern.FindAllStringSubmatch(c.Text, -1) {
				target := m[1]
				if strings.HasPrefix(target, "http://") || strings.HasPrefix(target, "https://") {
					continue
				}
				path, anchor := target, ""
				if i := strings.Index(target, "#"); i >= 0 {
					path, anchor = target[:i], target[i+1:]
				}
				tf, td := f, d
				if path != "" {
					tf = filepath.ToSlash(filepath.Join(filepath.Dir(f), path))
					if !strings.HasSuffix(tf, ".md") {
						continue
					}
					var err error
					if td, err = load(tf); err != nil {
						add(edge{File: tf, Kind: "link", Start: 0, End: 0, Reason: "変更行のリンク先 (読めない: " + err.Error() + ")"}, n)
						continue
					}
				}
				if anchor == "" {
					add(edge{File: tf, Kind: "link", Start: 1, End: len(td.lines) - 1, Reason: "変更行のリンク先 (ファイル全体)"}, n)
					continue
				}
				if s := td.sectionByAnchor(anchor); s != nil {
					add(edge{File: tf, Kind: "link", Start: s.Start, End: s.End, Heading: s.Heading, Reason: "変更行のリンク先の節"}, n)
				} else {
					add(edge{File: tf, Kind: "link", Start: 0, End: 0, Heading: anchor, Reason: "変更行のリンク先 (アンカーに一致する見出しが無い)"}, n)
				}
			}
		}
	}
	out := make([]edge, 0, len(order))
	for _, k := range order {
		e := merged[k]
		sort.Ints(e.Lines)
		out = append(out, *e)
	}
	return out, nil
}

// render は辺を人が読む形にする。withContent が真なら範囲の本文を行番号つきで添える。
func render(root string, edges []edge, withContent bool) string {
	var b strings.Builder
	byFile := map[string][]edge{}
	files := []string{}
	for _, e := range edges {
		if _, ok := byFile[e.File]; !ok {
			files = append(files, e.File)
		}
		byFile[e.File] = append(byFile[e.File], e)
	}
	sort.Strings(files)
	if len(edges) == 0 {
		b.WriteString("読み直す範囲はありません (Markdown の変更が無い)\n")
		return b.String()
	}
	b.WriteString("# 修正の近くの辺 (読み直す範囲)\n\n")
	for _, f := range files {
		fmt.Fprintf(&b, "## %s\n\n", f)
		for _, e := range byFile[f] {
			renderEdge(&b, root, e, withContent)
			if e.Parent != nil {
				p := *e.Parent
				p.Reason = "箇条書きの親"
				p.Lines = nil
				renderEdge(&b, root, p, withContent)
			}
		}
	}
	return b.String()
}

func renderEdge(b *strings.Builder, root string, e edge, withContent bool) {
	loc := "範囲を決められない"
	if e.Start > 0 {
		loc = fmt.Sprintf("%d〜%d 行目", e.Start, e.End)
	}
	head := ""
	if e.Heading != "" {
		head = " (" + e.Heading + ")"
	}
	lines := ""
	if len(e.Lines) > 0 {
		parts := make([]string, len(e.Lines))
		for i, n := range e.Lines {
			parts[i] = fmt.Sprint(n)
		}
		lines = " — 変更行: " + strings.Join(parts, ", ")
	}
	fmt.Fprintf(b, "### %s %s%s%s\n\n%s\n\n", kindJa(e.Kind), loc, head, lines, e.Reason)
	if !withContent || e.Start <= 0 {
		return
	}
	data, err := os.ReadFile(filepath.Join(root, e.File))
	if err != nil {
		fmt.Fprintf(b, "(本文を読めない: %v)\n\n", err)
		return
	}
	all := strings.Split(string(data), "\n")
	const cap = 200
	n := 0
	for i := e.Start; i <= e.End && i <= len(all); i++ {
		if n >= cap {
			fmt.Fprintf(b, "    … (%d 行で打ち切り。残りはファイルを読む)\n", cap)
			break
		}
		fmt.Fprintf(b, "    %5d  %s\n", i, all[i-1])
		n++
	}
	b.WriteString("\n")
}

func kindJa(k string) string {
	switch k {
	case "table":
		return "表"
	case "list":
		return "箇条書き"
	case "section":
		return "節"
	case "link":
		return "リンク先"
	case "paragraph":
		return "段落"
	case "heading":
		return "見出し"
	}
	return k
}
