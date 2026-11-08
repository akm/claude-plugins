package main

import (
	"strings"
	"testing"
)

// decisionPlanOld は、validRecordYAML の問題 P1 の状態と立案の結果。
const decisionPlanOld = "        status: pending\n" +
	"        decision:\n" +
	"          target: docs/foo.md の 10 行目\n" +
	"          baseline: 実際の件数\n" +
	"          choice: baseline\n" +
	"          choice_reason: 実際の件数が実測の値である\n"

// decisionBaselineYAML は、基準の内容を正として消す立案の結果。
const decisionBaselineYAML = "        decision:\n" +
	"          target: docs/foo.md の 10 行目\n" +
	"          baseline: 記録の数\n" +
	"          choice: baseline\n" +
	"          choice_reason: 記録の数が実測の値である\n" +
	"          doc_change: remove\n"

// decisionRecordYAML は、validRecordYAML の問題 P1 に立案の結果を書いた記録。
func decisionRecordYAML(t *testing.T, decision, status string) string {
	t.Helper()
	if !strings.Contains(validRecordYAML, decisionPlanOld) {
		t.Fatalf("フィクスチャの置換が適用されていない: %q", decisionPlanOld)
	}
	return strings.Replace(validRecordYAML, decisionPlanOld, decision+"        status: "+status+"\n", 1)
}

func decisionProblems(src string) []string {
	read := func(_ string) ([]byte, error) { return []byte(src), nil }
	var got []string
	for _, p := range reviewTriageRecordProblems([]string{reviewTriageDir + "feat-x.yaml"}, read) {
		// サマリを渡していないので、サマリが無いという問題は除く。
		if !strings.Contains(p, "サマリ") {
			got = append(got, p)
		}
	}
	return got
}

func TestReviewTriageRecordDecisionPasses(t *testing.T) {
	files, read := recordFiles(t, decisionRecordYAML(t, decisionBaselineYAML, "pending"))
	if problems := reviewTriageRecordProblems(files, read); len(problems) != 0 {
		t.Fatalf("立案の結果を書いた記録で問題が出た: %v", problems)
	}
}

// 今回は直さないと人間が決めた問題は、approach も sha も無くて通り、採択を覆う。
func TestReviewTriageRecordNotFixedPasses(t *testing.T) {
	src := strings.Replace(validRecordYAML,
		"        approach: 数え直して単位を書く\n        order: 1\n        sha: \"\"\n"+decisionPlanOld,
		"        decision:\n          target: docs/foo.md の 10 行目\n          baseline: 記録の数\n          choice: undecided\n          choice_reason: 別の Issue で直す\n        status: not-fixed\n", 1)
	if src == validRecordYAML {
		t.Fatal("フィクスチャの置換が適用されていない")
	}
	src += "  - date: \"2026-08-31\"\n    skill: code-review\n    model: sonnet-5\n    scope: incremental\n    head: abc1235\n    findings: []\n"
	files, read := recordFiles(t, src)
	if problems := reviewTriageRecordProblems(files, read); len(problems) != 0 {
		t.Fatalf("not-fixed の記録で問題が出た: %v", problems)
	}
	summary, err := renderReviewTriageSummary(reviewTriageDir+"feat-x.yaml", []byte(src))
	if err != nil {
		t.Fatalf("サマリの生成に失敗: %v", err)
	}
	for _, want := range []string{
		"| P1 | 数えずに書いた | #1 | — | — | 直さない | — |",
		"- **P1 の立案**: 箇所: docs/foo.md の 10 行目 / 基準: 記録の数 / 選択: 決めない / 理由: 別の Issue で直す\n",
	} {
		if !strings.Contains(summary, want) {
			t.Fatalf("生成サマリに %q が無い:\n%s", want, summary)
		}
	}
}

// status の誤字は、列挙違反の 1 件だけを報告する。decision の検査 (undecided と状態の組み合わせ) を
// 重ねると、1 つの誤字が 2 つの問題として報告される。
func TestReviewTriageRecordDecisionUnknownStatusReportedOnce(t *testing.T) {
	undecided := strings.Replace(decisionBaselineYAML, "choice: baseline", "choice: undecided", 1)
	undecided = strings.Replace(undecided, "          doc_change: remove\n", "", 1)
	problems := decisionProblems(decisionRecordYAML(t, undecided, "not_fixed"))
	enum := 0
	for _, p := range problems {
		if strings.Contains(p, "status は investigated / pending") {
			enum++
		}
		if strings.Contains(p, "decision.") {
			t.Fatalf("status の誤字に decision の問題が重なった: %v", problems)
		}
	}
	if enum != 1 {
		t.Fatalf("列挙違反が 1 件ではない (%d 件): %v", enum, problems)
	}
}

// status の誤字があっても、status に関係しない decision の検査 (choice の列挙など) は行う。
// 行わないのは、status と組み合わせる検査だけである。
func TestReviewTriageRecordDecisionChecksWithUnknownStatus(t *testing.T) {
	typo := strings.Replace(decisionBaselineYAML, "choice: baseline", "choice: basline", 1)
	problems := decisionProblems(decisionRecordYAML(t, typo, "pendng"))
	var enum, choice bool
	for _, p := range problems {
		if strings.Contains(p, "status は investigated / pending") {
			enum = true
		}
		if strings.Contains(p, "decision.choice は baseline / target / neither / undecided") {
			choice = true
		}
	}
	if !enum || !choice {
		t.Fatalf("status と decision.choice の列挙違反が両方報告されない: %v", problems)
	}
}

func TestReviewTriageRecordDecisionViolations(t *testing.T) {
	undecided := strings.Replace(decisionBaselineYAML, "choice: baseline", "choice: undecided", 1)
	undecided = strings.Replace(undecided, "          doc_change: remove\n", "", 1)
	cases := []struct {
		name     string
		decision string
		status   string
		want     string
	}{
		{"値が無い (null)", "        decision:\n", "pending", "decision に値がありません"},
		{"未知のキー", decisionBaselineYAML + "          reason: r\n", "pending", "reason"},
		{"箇所が無い", strings.Replace(decisionBaselineYAML, "          target: docs/foo.md の 10 行目\n", "", 1), "pending", "decision.target がありません"},
		{"基準が無い", strings.Replace(decisionBaselineYAML, "          baseline: 記録の数\n", "", 1), "pending", "decision.baseline がありません"},
		{"理由が無い", strings.Replace(decisionBaselineYAML, "          choice_reason: 記録の数が実測の値である\n", "", 1), "pending", "decision.choice_reason がありません"},
		{"選択肢の列挙値違反", strings.Replace(decisionBaselineYAML, "choice: baseline", "choice: fix", 1), "pending", "decision.choice は"},
		{"基準が変えられないのに target", strings.Replace(decisionBaselineYAML, "choice: baseline", "baseline_fixed: true\n          choice: target", 1), "pending", "decision.baseline_fixed が true"},
		{"基準が変えられないのに neither", strings.Replace(decisionBaselineYAML, "choice: baseline", "baseline_fixed: true\n          choice: neither", 1), "pending", "decision.baseline_fixed が true"},
		{"決めないのに未着手", undecided, "pending", "decision.choice が undecided なのに、status が pending"},
		{"決めないのに文書の修正がある", undecided + "          doc_change: remove\n", "awaiting-human", "decision.doc_change があります"},
		{"not-fixed なのに決めないではない", decisionBaselineYAML, "not-fixed", "status not-fixed なのに"},
		{"not-fixed に立案の結果が無い", "", "not-fixed", "status not-fixed には decision が必須"},
		{"調査済みに書いた", decisionBaselineYAML, "investigated", "調査済み (investigated) では decision を書かない"},
		{"文書の修正の列挙値違反", strings.Replace(decisionBaselineYAML, "doc_change: remove", "doc_change: delete", 1), "pending", "decision.doc_change は"},
		{"書き換えるのに理由が無い", strings.Replace(decisionBaselineYAML, "doc_change: remove", "doc_change: rewrite", 1), "pending", "doc_change_reason がありません"},
		{"足すのに理由が無い", strings.Replace(decisionBaselineYAML, "doc_change: remove", "doc_change: add", 1), "pending", "doc_change_reason がありません"},
		{"消すのに理由がある", decisionBaselineYAML + "          doc_change_reason: r\n", "pending", "rewrite か add のときだけ"},
		{"文書の修正が無いのに理由がある", strings.Replace(decisionBaselineYAML, "doc_change: remove", "doc_change_reason: r", 1), "pending", "rewrite か add のときだけ"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			problems := decisionProblems(decisionRecordYAML(t, tc.decision, tc.status))
			found := false
			for _, p := range problems {
				if strings.Contains(p, tc.want) {
					found = true
				}
			}
			if !found {
				t.Fatalf("%q を含む問題が出ない。出た問題: %v", tc.want, problems)
			}
		})
	}
}

// 選択肢と文書の修正の組み合わせのうち、規則に合うものは通る。awaiting-human の decision は任意で、
// 書くなら undecided でもよい。
func TestReviewTriageRecordDecisionCombinationsPass(t *testing.T) {
	undecided := strings.Replace(decisionBaselineYAML, "choice: baseline", "choice: undecided", 1)
	undecided = strings.Replace(undecided, "          doc_change: remove\n", "", 1)
	cases := []struct {
		name     string
		decision string
		status   string
	}{
		{"書き換えると理由", strings.Replace(decisionBaselineYAML, "doc_change: remove", "doc_change: rewrite\n          doc_change_reason: 消すと手順が分からなくなる", 1), "pending"},
		{"足すと理由", strings.Replace(decisionBaselineYAML, "doc_change: remove", "doc_change: add\n          doc_change_reason: 書き換える記述が無い", 1), "pending"},
		{"コードへの指摘は文書の修正を書かない", strings.Replace(decisionBaselineYAML, "          doc_change: remove\n", "", 1), "pending"},
		{"基準が変えられないなら baseline", strings.Replace(decisionBaselineYAML, "choice: baseline", "baseline_fixed: true\n          choice: baseline", 1), "pending"},
		{"指摘された箇所を正とする", strings.Replace(decisionBaselineYAML, "choice: baseline", "choice: target", 1), "pending"},
		{"どちらも正としない", strings.Replace(decisionBaselineYAML, "choice: baseline", "choice: neither", 1), "pending"},
		{"選択待ちで決めない", undecided + awaitingOptionsYAML, "awaiting-human"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if problems := decisionProblems(decisionRecordYAML(t, tc.decision, tc.status)); len(problems) != 0 {
				t.Fatalf("問題が出た: %v", problems)
			}
		})
	}
}

// decision は pending と not-fixed で必須で、done と awaiting-human では求めない。
func TestReviewTriageRecordDecisionRequiredStatus(t *testing.T) {
	cases := []struct {
		name   string
		status string
		extra  string
		want   string
	}{
		{"pending の書き忘れを報告する", "pending", "", "status pending には decision が必須"},
		{"not-fixed の書き忘れを報告する", "not-fixed", "", "status not-fixed には decision が必須"},
		{"done には求めない", "done", "", ""},
		{"awaiting-human には求めない", "awaiting-human", awaitingOptionsYAML, ""},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			src := decisionRecordYAML(t, tc.extra, tc.status)
			if tc.status == "done" {
				src = strings.Replace(src, "        sha: \"\"\n", "        sha: abc1234\n", 1)
			}
			problems := decisionProblems(src)
			found := false
			for _, p := range problems {
				found = found || (tc.want != "" && strings.Contains(p, tc.want))
			}
			if tc.want != "" && !found {
				t.Fatalf("%q の報告が無い: %v", tc.want, problems)
			}
			if tc.want == "" && len(problems) != 0 {
				t.Fatalf("問題が報告された: %v", problems)
			}
		})
	}
}

// 生成サマリの立案の行は、decision を書いた問題にだけ出る。
func TestReviewTriageSummaryDecision(t *testing.T) {
	summary, err := renderReviewTriageSummary(reviewTriageDir+"feat-x.yaml", []byte(decisionRecordYAML(t,
		strings.Replace(decisionBaselineYAML, "doc_change: remove", "baseline_fixed: true\n          doc_change: add\n          doc_change_reason: 書き換える記述が無い", 1), "pending")))
	if err != nil {
		t.Fatalf("サマリの生成に失敗: %v", err)
	}
	want := "- **P1 の立案**: 箇所: docs/foo.md の 10 行目 / 基準: 記録の数 (変えられない) / 選択: 基準の内容を正とする / 理由: 記録の数が実測の値である / 文書の修正: 足す (書き換える記述が無い)\n"
	if !strings.Contains(summary, want) {
		t.Fatalf("生成サマリに %q が無い:\n%s", want, summary)
	}
	plain, err := renderReviewTriageSummary(reviewTriageDir+"feat-x.yaml", []byte(decisionRecordYAML(t, "        options: 案 A か案 B\n", "awaiting-human")))
	if err != nil {
		t.Fatalf("サマリの生成に失敗: %v", err)
	}
	if strings.Contains(plain, "の立案") {
		t.Fatalf("decision の無い記録に立案の行が出ている:\n%s", plain)
	}
}
