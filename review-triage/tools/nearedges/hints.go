package main

import (
	"fmt"
	"regexp"
	"sort"
	"strings"
)

// 全称の語の候補。検証の観点 F (全称の主張は書く前に反例を挙げる) を差分の行に当てるための
// 手がかりで、規則ではない — 一致しても書いてよいし、一致しなくても全称の主張はありうる。
var universalWords = []string{
	"必ず", "すべて", "全て", "常に", "一切", "決して", "今後増えない", "閉じて", "収まる", "解消しない", "同じ向き", "だけで", "しか無い", "しかない",
}

var countPattern = regexp.MustCompile(`\d+\s*(?:つ|件|箇所|か所|回|行|個|種|通り)`)

// hints は変更行と近くの辺から、コミット前に当てる検証の観点 (verification.md の A〜F) を
// 差分の種類に応じて提示する。
func hints(changes map[string][]change, edges []edge) []string {
	set := map[string]bool{}
	add := func(s string) { set[s] = true }
	for _, e := range edges {
		switch e.Kind {
		case "table":
			add(fmt.Sprintf("観点 B: 表のセルを変えた (%s %d〜%d 行目) — その表の全行を同じ基準で読み直す (第 1 列の条件・他の列の理由・行どうしの重なりと網羅)", e.File, e.Start, e.End))
		case "list":
			add(fmt.Sprintf("観点 B: 箇条書きを変えた (%s %d〜%d 行目) — 同じ箇条書きの全項目と、それを導入する親を読み直す", e.File, e.Start, e.End))
		case "section":
			add(fmt.Sprintf("観点 B: 段落を変えた (%s %d〜%d 行目) — 同じ節の全文を読み直す (冒頭の包括文と離れた文との矛盾)", e.File, e.Start, e.End))
		case "link":
			add(fmt.Sprintf("観点 B: 変更行が参照する先 (%s %s) を読み直す — 参照先が主張の所在か、参照先の側が古びていないか", e.File, e.Heading))
		}
	}
	for f, cs := range changes {
		for _, c := range cs {
			if c.Deleted {
				continue
			}
			for _, w := range universalWords {
				if strings.Contains(c.Text, w) {
					add(fmt.Sprintf("観点 F: 全称の語「%s」が変更行にある (%s %d 行目) — その主張を偽にする状態を 1 つ挙げてから確定する", w, f, c.Line))
				}
			}
			if m := countPattern.FindString(c.Text); m != "" {
				add(fmt.Sprintf("観点 C: 変更行に数がある「%s」(%s %d 行目) — 何を 1 と数えるかと範囲を先に決め、数を 1 増減しても主張が変わらないなら数を書かない", m, f, c.Line))
			}
			if strings.Contains(c.Text, "正本は") && !strings.Contains(c.Text, "](") {
				add(fmt.Sprintf("観点 B: 変更行に「正本は」があるがリンクが無い (%s %d 行目) — 正本の側を読み直し、参照をリンクにする", f, c.Line))
			}
		}
	}
	out := make([]string, 0, len(set))
	for s := range set {
		out = append(out, s)
	}
	sort.Strings(out)
	return out
}
