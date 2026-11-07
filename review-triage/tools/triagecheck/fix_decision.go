// fix_decision.go は、立案の結果 (plans[].decision) の検査と、生成サマリへの描画を持つ。
// キーの意味の SSOT は skills/review-triage/references/record-schema.md の「立案の結果」、
// 選択肢の意味の SSOT は skills/review-triage-fix/references/fix-decision.md。
package main

import "fmt"

// recordDecision は plans[].decision を表す。修正の内容は approach に書くので、ここには持たない。
type recordDecision struct {
	Target          string `yaml:"target"`
	Baseline        string `yaml:"baseline"`
	BaselineFixed   bool   `yaml:"baseline_fixed"`
	Choice          string `yaml:"choice"`
	ChoiceReason    string `yaml:"choice_reason"`
	DocChange       string `yaml:"doc_change"`
	DocChangeReason string `yaml:"doc_change_reason"`
}

// recordDecisionProblems は問題 1 つの decision を検査する。done と done-external には求めない。
// 理由は record-schema.md の「立案の結果」。statusKnown が偽 (status が列挙の外) なら、choice と状態を
// 組み合わせる検査はしない。status の列挙違反は呼び出し元が報告するので、重ねると 1 つの誤字が
// 2 つの問題になるため。
func recordDecisionProblems(pl recordPlan, statusKnown bool) []string {
	var problems []string
	add := func(format string, args ...any) {
		problems = append(problems, fmt.Sprintf(format, args...))
	}
	d := pl.Decision
	if d == nil {
		switch pl.Status {
		case "not-fixed":
			add("status not-fixed には decision が必須 (choice: undecided と、直さない理由を書く)")
		case "pending":
			add("status pending には decision が必須 (立案の結果を書く)")
		}
		return problems
	}
	if pl.Status == "investigated" {
		add("調査済み (investigated) では decision を書かない。修正方法を決めたのなら status: pending にする")
		return problems
	}
	for _, kv := range []struct{ key, val string }{
		{"target", d.Target}, {"baseline", d.Baseline}, {"choice_reason", d.ChoiceReason},
	} {
		if kv.val == "" {
			add("decision.%s がありません", kv.key)
		}
	}
	switch d.Choice {
	case "baseline", "target", "neither", "undecided":
	default:
		add("decision.choice は baseline / target / neither / undecided のいずれか: %q", d.Choice)
	}
	if d.BaselineFixed && (d.Choice == "target" || d.Choice == "neither") {
		add("decision.baseline_fixed が true なのに、decision.choice が %s です (基準が変えられないなら、基準を直す選択肢は候補にならない)", d.Choice)
	}
	if d.Choice == "undecided" {
		if statusKnown && pl.Status != "not-fixed" && pl.Status != "awaiting-human" {
			add("decision.choice が undecided なのに、status が %s です (今回は直さないなら not-fixed、人間の回答を待つなら awaiting-human)", pl.Status)
		}
		if d.DocChange != "" {
			add("decision.choice が undecided なのに、decision.doc_change があります (直さないので、修正の内容は無い)")
		}
	}
	if pl.Status == "not-fixed" && d.Choice != "undecided" {
		add("status not-fixed なのに、decision.choice が undecided ではありません: %q", d.Choice)
	}
	switch d.DocChange {
	case "rewrite", "add":
		if d.DocChangeReason == "" {
			add("decision.doc_change が %s なのに、decision.doc_change_reason がありません (前の順のもので済まない理由を書く)", d.DocChange)
		}
	case "remove", "":
		if d.DocChangeReason != "" {
			add("decision.doc_change_reason は、decision.doc_change が rewrite か add のときだけ書く (doc_change %q)", d.DocChange)
		}
	default:
		add("decision.doc_change は remove / rewrite / add のいずれか: %q", d.DocChange)
	}
	return problems
}

// renderDecision は立案の結果を 1 行にする。自由文字列はすべて recordCell を通す。
func renderDecision(d *recordDecision) string {
	s := "箇所: " + recordCell(d.Target) + " / 基準: " + recordCell(d.Baseline)
	if d.BaselineFixed {
		s += " (変えられない)"
	}
	s += " / 選択: " + recordChoiceJa(d.Choice) + " / 理由: " + recordCell(d.ChoiceReason)
	if d.DocChange != "" {
		s += " / 文書の修正: " + recordDocChangeJa(d.DocChange)
	}
	if d.DocChangeReason != "" {
		s += " (" + recordCell(d.DocChangeReason) + ")"
	}
	return s
}

func recordChoiceJa(s string) string {
	switch s {
	case "baseline":
		return "基準の内容を正とする"
	case "target":
		return "指摘された箇所の内容を正とする"
	case "neither":
		return "どちらも正としない"
	case "undecided":
		return "決めない"
	}
	return recordCell(s)
}

func recordDocChangeJa(s string) string {
	switch s {
	case "remove":
		return "消す"
	case "rewrite":
		return "書き換える"
	case "add":
		return "足す"
	}
	return recordCell(s)
}
