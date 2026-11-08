// option_patch.go は、判断待ちの問題の案ごとのパッチ (plans[].option_patches) と、人間が選んだ案
// (plans[].chosen_option) の検査と、生成サマリへの描画を持つ。
// キーの意味の SSOT は skills/review-triage/references/record-schema.md の修正計画の表と「案のパッチ」。
package main

import (
	"fmt"
	"regexp"
	"strings"
)

// recordOptionPatch は plans[].option_patches の 1 要素。patch・no_change・covered_by のどれか 1 つを持つ。
// NoChange と CoveredBy は、書いてあるかどうかを見るためにポインタで持つ。
type recordOptionPatch struct {
	Option    string          `yaml:"option"`
	Patch     string          `yaml:"patch"`
	Base      string          `yaml:"base"`
	NoChange  *bool           `yaml:"no_change"`
	CoveredBy *recordPatchRef `yaml:"covered_by"`
}

// recordPatchRef は covered_by の参照。同じ回の、ほかの問題の、パッチを持つ要素を指す。
type recordPatchRef struct {
	ProblemID string `yaml:"problem_id"`
	Option    string `yaml:"option"`
}

// recordOptionLabelRe は options の 1 行の先頭の案のラベル。ラベルは英大文字で始まる英大文字と数字で、
// 後に半角空白か ( か : が続く (record-schema.md の options の行)。
var recordOptionLabelRe = regexp.MustCompile(`^([A-Z][A-Z0-9]*)[ (:]`)

// recordOptionLine は options の 1 行。no は 1 始まりの行番号で、ラベルで始まらない行の label は空。
type recordOptionLine struct {
	no    int
	label string
	text  string
}

// recordOptionLines は options の空でない行を返す。
func recordOptionLines(options string) []recordOptionLine {
	var lines []recordOptionLine
	for i, line := range strings.Split(options, "\n") {
		if strings.TrimSpace(line) == "" {
			continue
		}
		label := ""
		if m := recordOptionLabelRe.FindStringSubmatch(line); m != nil {
			label = m[1]
		}
		lines = append(lines, recordOptionLine{no: i + 1, label: label, text: line})
	}
	return lines
}

// recordOptionPatchProblems は問題 1 つの options・option_patches・chosen_option を検査する。plans は同じ回の
// 修正計画で、covered_by の参照先を解決するのに使う。
//
// options の書き方を検査するのは、判断待ち (awaiting-human) の問題と、option_patches を持つ問題だけ。
// 過去の記録の pending・done・not-fixed には自由な書き方の options が残っており、記録の過去の回は
// 書き換えないため。判断待ちの問題は、古い記録でも報告する (review-triage-fix で再開して人間が回答すれば、
// パッチが作られて検査を通る)。
func recordOptionPatchProblems(pl recordPlan, plans []recordPlan) []string {
	var problems []string
	add := func(format string, args ...any) {
		problems = append(problems, fmt.Sprintf(format, args...))
	}
	awaiting := pl.Status == "awaiting-human"
	if !awaiting && len(pl.OptionPatches) == 0 && pl.ChosenOption == "" {
		return nil
	}

	// options の行。空の options は、判断待ちなら状態の検査が報告するので、ここでは重ねない。
	labels := map[string]bool{}
	var labelOrder []string
	for _, line := range recordOptionLines(pl.Options) {
		if line.label == "" {
			add("options の %d 行目がラベルで始まっていません (行の先頭に案のラベル (例: A・B・H1) を書き、後に半角空白か ( か : を続ける): %q", line.no, recordCell(line.text))
			continue
		}
		if labels[line.label] {
			add("options にラベル %q の行が 2 つあります (人間がどちらの案を選んだかが決まらない)", line.label)
			continue
		}
		labels[line.label] = true
		labelOrder = append(labelOrder, line.label)
	}

	// option_patches の要素。
	byOption := map[string]recordOptionPatch{}
	for i, op := range pl.OptionPatches {
		en := fmt.Sprintf("option_patches[%d]", i)
		if op.Option == "" {
			add("%s: option がありません (案のラベルを書く)", en)
		} else {
			if !labels[op.Option] {
				add("%s: option %q は options のどの行の先頭にもありません", en, op.Option)
			}
			if _, dup := byOption[op.Option]; dup {
				add("option_patches に option %q の要素が 2 つあります (どちらのパッチを当てるかが決まらない)", op.Option)
			} else {
				byOption[op.Option] = op
			}
		}
		kinds := 0
		if op.Patch != "" {
			kinds++
		}
		if op.NoChange != nil {
			kinds++
			if !*op.NoChange {
				add("%s: no_change は true だけを書く (ファイルを変える案なら patch を書く)", en)
			}
		}
		if op.CoveredBy != nil {
			kinds++
		}
		if kinds != 1 {
			add("%s: patch・no_change・covered_by のどれか 1 つだけを書く (2 つ以上か、どれも無い)", en)
		}
		if op.Patch != "" {
			if op.Base == "" {
				add("%s: patch があるのに base がありません (パッチを作ったときの HEAD の短縮 SHA)", en)
			}
			if !strings.HasPrefix(op.Patch, "diff --git") {
				add("%s: patch が diff --git で始まっていません (git diff の出力をそのまま書く)", en)
			}
			if !strings.HasSuffix(op.Patch, "\n") {
				add("%s: patch の末尾に改行がありません (git apply が末尾の改行を要る。YAML のブロックは |- ではなく | で書く)", en)
			}
		} else if op.Base != "" {
			add("%s: patch が無い要素に base があります (base は patch があるときだけ書く)", en)
		}
		if ref := op.CoveredBy; ref != nil {
			for _, m := range recordPatchRefProblems(pl.ProblemID, *ref, plans) {
				add("%s: %s", en, m)
			}
		}
	}

	// 判断待ちの問題は、options のすべての案にパッチ (かファイルを変えないこと・覆う参照) が要る。
	if awaiting {
		for _, label := range labelOrder {
			if _, ok := byOption[label]; !ok {
				add("判断待ち (awaiting-human) なのに、案 %q の要素が option_patches にありません (案ごとにパッチを作る。ファイルを変えない案は no_change: true)", label)
			}
		}
	}

	// 人間が選んだ案。
	if c := pl.ChosenOption; c != "" {
		op, ok := byOption[c]
		if !ok {
			add("chosen_option %q は option_patches のどの要素の option でもありません", c)
		}
		if awaiting {
			// 残っていると、人間がまだ見ていない作り直したパッチについて、選んだ案があるように読める。
			add("判断待ち (awaiting-human) に chosen_option があります (パッチを作り直して判断待ちに戻すときは消す)")
		} else if ok && pl.Status == "pending" && op.NoChange != nil && *op.NoChange {
			add("status pending なのに、chosen_option %q はファイルを変えない案 (no_change) です (修正フェーズが当てるパッチが無い。直さないなら status: not-fixed にする)", c)
		} else if ok && pl.Status == "not-fixed" && (op.NoChange == nil || !*op.NoChange) {
			add("status not-fixed なのに、chosen_option %q はファイルを変える案です (決めないと回答したときに選べるのは、ファイルを変えない案 (no_change) だけ)", c)
		}
		// 1 つの修正で覆う問題は、同じ回答で参照先の案も選ぶ (SKILL.md の手順 1 の「人間の回答の反映」)。
		// 参照先が選んでいないと、修正フェーズは人間がまだ選んでいない参照先の変更をコミットする。
		if ok && (pl.Status == "pending" || pl.Status == "done") && op.CoveredBy != nil {
			ref := *op.CoveredBy
			for _, other := range plans {
				if other.ProblemID == ref.ProblemID && other.ProblemID != pl.ProblemID && other.ChosenOption != ref.Option {
					add("chosen_option %q は %s の案 %q のパッチで覆う案なのに、%s の chosen_option が %q です (1 つの修正で覆う問題は、同じ回答で参照先の案も選ぶ)",
						c, ref.ProblemID, ref.Option, ref.ProblemID, other.ChosenOption)
				}
			}
		}
	} else if (pl.Status == "pending" || pl.Status == "done") && len(pl.OptionPatches) > 0 {
		// 案を選んで pending にした問題は、修正フェーズが chosen_option の案のパッチを当てる (SKILL.md の手順 1 の
		// 「人間の回答の反映」)。無いと、人間が見たパッチを当てずに approach の文から直すことになる。
		add("status %s で option_patches があるのに、chosen_option がありません (人間が選んだ案のラベルを書く。修正フェーズは、その案のパッチを当てる)", pl.Status)
	}
	return problems
}

// recordPatchRefProblems は covered_by の参照を検査する。参照先は、同じ回の、ほかの問題の、パッチを持つ要素。
func recordPatchRefProblems(self string, ref recordPatchRef, plans []recordPlan) []string {
	var problems []string
	if ref.ProblemID == "" {
		problems = append(problems, "covered_by.problem_id がありません")
	}
	if ref.Option == "" {
		problems = append(problems, "covered_by.option がありません")
	}
	if ref.ProblemID == "" || ref.Option == "" {
		return problems
	}
	if ref.ProblemID == self {
		return append(problems, "covered_by が自分の問題を指しています (覆うのはほかの問題の案のパッチ)")
	}
	for _, other := range plans {
		if other.ProblemID != ref.ProblemID {
			continue
		}
		for _, op := range other.OptionPatches {
			if op.Option != ref.Option {
				continue
			}
			if op.Patch == "" {
				problems = append(problems, fmt.Sprintf("covered_by が指す %s の案 %q は、パッチを持つ要素ではありません", ref.ProblemID, ref.Option))
			}
			return problems
		}
		return append(problems, fmt.Sprintf("covered_by の案 %q は、問題 %s の option_patches にありません", ref.Option, ref.ProblemID))
	}
	return append(problems, fmt.Sprintf("covered_by の問題 %q は同じ回の plans にありません", ref.ProblemID))
}

// renderOptionPatches は option_patches を持つ問題の小節「#### <問題> の案」を書く。要素ごとに、options の
// 該当の行と、パッチ (diff のコードブロック)・ファイルを変えないこと・覆う参照のどれかを出す。
// option_patches の無い問題には何も書かない。無い記録の出力が変わると、既存のサマリがすべて古いと報告されるため。
func renderOptionPatches(b *strings.Builder, pl recordPlan) {
	if len(pl.OptionPatches) == 0 {
		return
	}
	fmt.Fprintf(b, "\n#### %s の案\n", recordCell(pl.ProblemID))
	if pl.ChosenOption != "" {
		fmt.Fprintf(b, "\n選んだ案: %s\n", recordCell(pl.ChosenOption))
	}
	lines := recordOptionLines(pl.Options)
	for _, op := range pl.OptionPatches {
		// 案の行。options に無いラベル (検査が報告する) は、ラベルだけを出す。
		text := op.Option
		for _, line := range lines {
			if line.label != "" && line.label == op.Option {
				text = line.text
				break
			}
		}
		fmt.Fprintf(b, "\n%s\n", recordCell(text))
		switch {
		case op.Patch != "":
			fence := strings.Repeat("`", max(3, recordLongestBacktickRun(op.Patch)+1))
			patch := op.Patch
			if !strings.HasSuffix(patch, "\n") {
				patch += "\n"
			}
			fmt.Fprintf(b, "\nパッチ (起点 `%s`):\n\n%sdiff\n%s%s\n", recordCell(op.Base), fence, patch, fence)
		case op.NoChange != nil && *op.NoChange:
			b.WriteString("\nファイルを変えない。\n")
		case op.CoveredBy != nil:
			fmt.Fprintf(b, "\n%s の案 %s のパッチで覆う。\n", recordCell(op.CoveredBy.ProblemID), recordCell(op.CoveredBy.Option))
		}
	}
}

// recordLongestBacktickRun は s の中で最も長く続くバッククォートの数を返す。
func recordLongestBacktickRun(s string) int {
	longest, run := 0, 0
	for _, r := range s {
		if r == '`' {
			run++
			if run > longest {
				longest = run
			}
		} else {
			run = 0
		}
	}
	return longest
}
