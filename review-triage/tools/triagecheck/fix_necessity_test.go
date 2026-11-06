package main

import (
	"fmt"
	"strings"
	"testing"
)

// fixNecessityFindingYAML は、必要度を判定した指摘 1 件の YAML を返す。reason は
// fix_necessity_reason の中身 (各行をインデント済みで渡す)。necessity が空なら
// fix_necessity を書かない。
func fixNecessityFindingYAML(id int, necessity, reason, verdict, verdictReason string) string {
	var b strings.Builder
	fmt.Fprintf(&b, "      - id: %d\n", id)
	fmt.Fprintf(&b, "        file: docs/f%d.md\n", id)
	fmt.Fprintf(&b, "        line: %d\n", id*10)
	fmt.Fprintf(&b, "        summary: 指摘 %d\n", id)
	b.WriteString("        category: doc-other\n")
	b.WriteString("        audience: developer\n")
	b.WriteString("        consequence:\n")
	b.WriteString("          condition: 読むとき\n")
	b.WriteString("          who: developer\n")
	fmt.Fprintf(&b, "          what: 問題 %d が起きる\n", id)
	b.WriteString("          detectability: 気づかされない\n")
	b.WriteString("        premise_check:\n")
	b.WriteString("          stages: A\n")
	b.WriteString("          result: verified\n")
	if necessity != "" {
		fmt.Fprintf(&b, "        fix_necessity: %s\n", necessity)
	}
	if reason != "" {
		b.WriteString("        fix_necessity_reason:\n" + reason)
	}
	fmt.Fprintf(&b, "        verdict: %s\n", verdict)
	fmt.Fprintf(&b, "        verdict_reason: %s\n", verdictReason)
	return b.String()
}

// 必要度ごとの fix_necessity_reason の中身。
const (
	reasonMust      = "          goal_without_action: not-holds\n          workaround: not-holds\n          workaround_reason: 誤った結果がエラーにならずに記録される\n"
	reasonShould    = "          goal_without_action: not-holds\n          workaround: holds\n          workaround_reason: 実装のテストが失敗して気づかされる\n"
	reasonCould     = "          goal_without_action: holds\n"
	reasonUndecided = "          goal_without_action: not-holds\n          workaround: undecided\n          workaround_reason: 後の工程で気づかされるかが分からない\n"
)

// fixNecessityRunYAML は回 1 つの YAML を返す。minimum が空なら min_fix_necessity を書かない。
func fixNecessityRunYAML(minimum, findings, plans string) string {
	var b strings.Builder
	b.WriteString("  - date: \"2026-11-07\"\n    skill: code-review\n    model: opus\n    scope: incremental\n    head: abc1234\n")
	if minimum != "" {
		fmt.Fprintf(&b, "    min_fix_necessity: %s\n", minimum)
	}
	b.WriteString("    findings:\n" + findings)
	if plans != "" {
		b.WriteString("    plans:\n" + plans)
	}
	return b.String()
}

// omittedFindingYAML は、D9 で当たって判定を省略した指摘 (A3・B2) の YAML を返す。
func omittedFindingYAML(id, refRun, refFinding int, origin, verdict, verdictReason string) string {
	var b strings.Builder
	fmt.Fprintf(&b, "      - id: %d\n", id)
	fmt.Fprintf(&b, "        file: docs/f%d.md\n", refFinding)
	fmt.Fprintf(&b, "        line: %d\n", refFinding*10)
	fmt.Fprintf(&b, "        summary: 指摘 %d\n", refFinding)
	if origin != "" {
		fmt.Fprintf(&b, "        origin: %s\n", origin)
	}
	fmt.Fprintf(&b, "        verdict: %s\n", verdict)
	fmt.Fprintf(&b, "        verdict_reason: %s\n", verdictReason)
	b.WriteString("        below_minimum_ref:\n")
	fmt.Fprintf(&b, "          run: %d\n", refRun)
	fmt.Fprintf(&b, "          finding: %d\n", refFinding)
	b.WriteString("          line_check: holds\n")
	b.WriteString("          line_reason: 前の回でレビューした内容のまま\n")
	return b.String()
}

const fixNecessityPlanYAML = "      - problem_id: P1\n        cause: 原因\n        finding_ids: [1]\n        approach: 直す\n        sha: abc1234\n        status: done\n"

// fixNecessityRecordYAML は、必要度と下限を書いた 3 回の記録。
//   - 1 回目 (下限 must): Must の採択・Should と Could の下限未満 (B1)・必要度を決められない
//     保留 (H8)・Should の却下 (R3。下限に満たなくても却下のまま)
//   - 2 回目 (下限 should): 1 回目の Should を採択 (A3。下限を下げたので足した指摘)・
//     1 回目の Could がまた報告されて判定を省略 (B2)
//   - 3 回目 (下限なし): 1 回目の Could の行が変わっていたので判定し直して採択
func fixNecessityRecordYAML() string {
	run1 := fixNecessityRunYAML("must",
		fixNecessityFindingYAML(1, "must", reasonMust, "adopted", "A2")+
			fixNecessityFindingYAML(2, "should", reasonShould, "below_minimum", "B1")+
			fixNecessityFindingYAML(3, "could", reasonCould, "below_minimum", "B1")+
			fixNecessityFindingYAML(4, "", reasonUndecided, "held", "H8")+
			strings.Replace(fixNecessityFindingYAML(5, "should", reasonShould, "rejected", "R3"),
				"        verdict: rejected\n", "        gates_fired: [developer-domain]\n        verdict: rejected\n", 1),
		fixNecessityPlanYAML)
	run2 := fixNecessityRunYAML("should",
		omittedFindingYAML(1, 1, 2, "prior_below_minimum", "adopted", "A3")+
			omittedFindingYAML(2, 1, 3, "", "below_minimum", "B2"),
		fixNecessityPlanYAML)
	rejudged := strings.Replace(fixNecessityFindingYAML(1, "could", reasonCould, "adopted", "A2"),
		"        verdict: adopted\n",
		"        below_minimum_ref:\n          run: 1\n          finding: 3\n          line_check: not-holds\n          line_reason: 30 行目は 2 回目の修正が書き換えた\n        verdict: adopted\n", 1)
	run3 := fixNecessityRunYAML("", rejudged, "")
	return "runs:\n" + run1 + run2 + run3
}

func fixNecessityProblems(src string) []string {
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

func TestReviewTriageRecordFixNecessityPasses(t *testing.T) {
	files, read := recordFiles(t, fixNecessityRecordYAML())
	if problems := reviewTriageRecordProblems(files, read); len(problems) != 0 {
		t.Fatalf("必要度と下限を書いた記録で問題が出た: %v", problems)
	}
}

// 判定は、必要度と回の下限の組み合わせで決まる (judgment-flow.md の D10・D11)。
// 採択は下限以上か下限が無いとき、下限未満は下限に満たないときだけ通る。保留と却下は、
// 下限に満たなくても、そのままで通る (下限は採択の手前でだけ適用する)。
func TestReviewTriageRecordVerdictByNecessityAndMinimum(t *testing.T) {
	reasons := map[string]string{"must": reasonMust, "should": reasonShould, "could": reasonCould}
	for _, necessity := range []string{"must", "should", "could"} {
		for _, minimum := range []string{"", "must", "should", "could"} {
			below := minimum != "" && fixNecessityRank(necessity) < fixNecessityRank(minimum)
			for _, tc := range []struct {
				verdict string
				ok      bool
			}{
				{"adopted", !below},
				{"below_minimum", below},
				{"held", true},
				{"rejected", true},
			} {
				name := fmt.Sprintf("必要度 %s・下限 %q・判定 %s", necessity, minimum, tc.verdict)
				t.Run(name, func(t *testing.T) {
					src := "runs:\n" + fixNecessityRunYAML(minimum,
						fixNecessityFindingYAML(1, necessity, reasons[necessity], tc.verdict, "X"), "")
					problems := fixNecessityProblems(src)
					if tc.ok != (len(problems) == 0) {
						t.Fatalf("通るべきか: %v。出た問題: %v", tc.ok, problems)
					}
				})
			}
		}
	}
}

// 必要度を決められなかった指摘は、採択にも下限未満にもできない (H8 の保留)。
// 下限が無い回でも同じ。保留と却下は通る。
func TestReviewTriageRecordUndecidedNecessity(t *testing.T) {
	for _, minimum := range []string{"", "must"} {
		for _, tc := range []struct {
			verdict string
			want    string // 空なら問題が出ない
		}{
			{"adopted", "H8 の保留"},
			{"below_minimum", "必要度を決めた指摘だけ"},
			{"held", ""},
			{"rejected", ""},
		} {
			t.Run(fmt.Sprintf("下限 %q・判定 %s", minimum, tc.verdict), func(t *testing.T) {
				src := "runs:\n" + fixNecessityRunYAML(minimum,
					fixNecessityFindingYAML(1, "", reasonUndecided, tc.verdict, "X"), "")
				problems := fixNecessityProblems(src)
				if tc.want == "" {
					if len(problems) != 0 {
						t.Fatalf("問題が出た: %v", problems)
					}
					return
				}
				if len(problems) != 1 || !strings.Contains(problems[0], tc.want) {
					t.Fatalf("%q を含む問題が 1 件だけ出るべき。出た問題: %v", tc.want, problems)
				}
			})
		}
	}
}

// 判定を省略した指摘の判定は、参照先の必要度と、その回の下限で決まる (D12)。
func TestReviewTriageRecordOmittedVerdictByMinimum(t *testing.T) {
	for _, tc := range []struct {
		necessity, minimum, want string
	}{
		{"should", "must", "below_minimum"},
		{"should", "should", "adopted"},
		{"should", "could", "adopted"},
		{"should", "", "adopted"},
		{"could", "should", "below_minimum"},
		{"could", "could", "adopted"},
		{"could", "", "adopted"},
	} {
		reason := reasonShould
		if tc.necessity == "could" {
			reason = reasonCould
		}
		run1 := fixNecessityRunYAML("must", fixNecessityFindingYAML(1, tc.necessity, reason, "below_minimum", "B1"), "")
		for _, verdict := range []string{"adopted", "below_minimum"} {
			t.Run(fmt.Sprintf("参照先 %s・下限 %q・判定 %s", tc.necessity, tc.minimum, verdict), func(t *testing.T) {
				src := "runs:\n" + run1 + fixNecessityRunYAML(tc.minimum, omittedFindingYAML(1, 1, 1, "", verdict, "X"), "")
				problems := fixNecessityProblems(src)
				if verdict == tc.want {
					if len(problems) != 0 {
						t.Fatalf("問題が出た: %v", problems)
					}
					return
				}
				if len(problems) != 1 || !strings.Contains(problems[0], "判定を省略した指摘の verdict は") {
					t.Fatalf("判定の食い違いが 1 件だけ出るべき。出た問題: %v", problems)
				}
			})
		}
	}
}

func TestReviewTriageRecordFixNecessityViolations(t *testing.T) {
	cases := []struct {
		name string
		old  string // fixNecessityRecordYAML の中で置き換える文字列 (最初の 1 か所)
		new  string
		want string // 問題文に含まれるべき語
	}{
		{"回の下限の列挙値違反", "    min_fix_necessity: must\n", "    min_fix_necessity: high\n", "min_fix_necessity は must / should / could"},
		{"必要度の列挙値違反", "        fix_necessity: must\n", "        fix_necessity: high\n", "fix_necessity は must / should / could"},
		{"理由から決まる値と違う", "        fix_necessity: must\n", "        fix_necessity: should\n", "fix_necessity_reason から決まる must と違います"},
		{"決まらないのに必要度がある", "        fix_necessity_reason:\n" + reasonUndecided, "        fix_necessity: should\n        fix_necessity_reason:\n" + reasonUndecided,
			"必要度が決まらない"},
		{"必要度があるのに理由が無い", "        fix_necessity_reason:\n" + reasonMust, "", "fix_necessity があるのに fix_necessity_reason がありません"},
		{"理由の値が無い (null)", "        fix_necessity_reason:\n" + reasonMust, "        fix_necessity_reason:\n", "fix_necessity_reason に値がありません"},
		{"理由の未知のキー", "          workaround: not-holds\n", "          workaround: not-holds\n          severity: P1\n", "severity"},
		{"条件 1 の列挙値違反", "          goal_without_action: not-holds\n          workaround: not-holds\n", "          goal_without_action: no\n          workaround: not-holds\n",
			"fix_necessity_reason.goal_without_action"},
		{"条件 2 が無い", "          workaround: not-holds\n          workaround_reason: 誤った結果がエラーにならずに記録される\n", "", "fix_necessity_reason.workaround がありません"},
		{"条件 2 の列挙値違反", "          workaround: not-holds\n", "          workaround: none\n", "fix_necessity_reason.workaround は"},
		{"条件 2 の理由が無い", "          workaround_reason: 誤った結果がエラーにならずに記録される\n", "", "fix_necessity_reason.workaround_reason"},
		{"条件 1 が成り立つのに条件 2 がある", "          goal_without_action: holds\n", "          goal_without_action: holds\n          workaround: holds\n          workaround_reason: r\n",
			"goal_without_action が not-holds のときだけ"},
		{"E3 を行っていない指摘に書いた", "          result: verified\n        fix_necessity: must\n", "          result: unverifiable\n        fix_necessity: must\n",
			"fix_necessity_reason は E3 を行った指摘"},
		{"判定の列挙値違反", "        verdict: below_minimum\n", "        verdict: deferred\n", "verdict は adopted / held / rejected / below_minimum"},
		{"出所の列挙値違反", "        origin: prior_below_minimum\n", "        origin: lowered\n", "origin は review / residual / prior_below_minimum"},
		{"足した指摘に参照が無い",
			"        below_minimum_ref:\n          run: 1\n          finding: 2\n          line_check: holds\n          line_reason: 前の回でレビューした内容のまま\n", "",
			"origin が prior_below_minimum なのに below_minimum_ref がありません"},
		{"参照の値が無い (null)",
			"        below_minimum_ref:\n          run: 1\n          finding: 2\n          line_check: holds\n          line_reason: 前の回でレビューした内容のまま\n", "        below_minimum_ref:\n",
			"below_minimum_ref に値がありません"},
		{"参照の未知のキー", "          finding: 2\n", "          finding: 2\n          problem: P1\n", "problem"},
		{"参照先の回がこの回より前でない", "          run: 1\n          finding: 2\n", "          run: 2\n          finding: 2\n", "この回より前の回ではありません"},
		{"参照先の指摘が無い", "          run: 1\n          finding: 2\n", "          run: 1\n          finding: 9\n", "finding 9 は 1 回目の findings にありません"},
		{"参照先が下限未満でない", "          run: 1\n          finding: 2\n", "          run: 1\n          finding: 1\n", "必要度を判定して下限未満にした指摘ではありません"},
		{"行の確認の列挙値違反", "          line_check: not-holds\n          line_reason: 30 行目", "          line_check: changed\n          line_reason: 30 行目", "below_minimum_ref.line_check"},
		{"行の確認の理由が無い", "          line_reason: 30 行目は 2 回目の修正が書き換えた\n", "", "below_minimum_ref.line_reason"},
		{"判定を省略した指摘に分類を書いた", "        origin: prior_below_minimum\n", "        origin: prior_below_minimum\n        category: doc-other\n",
			"では category を書かない"},
		{"判定を省略した指摘に必要度を書いた", "        origin: prior_below_minimum\n", "        origin: prior_below_minimum\n        fix_necessity: should\n",
			"では fix_necessity を書かない"},
		{"判定し直した指摘に分類が無い", "        category: doc-other\n        audience: developer\n        consequence:\n          condition: 読むとき\n          who: developer\n          what: 問題 1 が起きる\n          detectability: 気づかされない\n        premise_check:\n          stages: A\n          result: verified\n        fix_necessity: could\n",
			"        audience: developer\n        consequence:\n          condition: 読むとき\n          who: developer\n          what: 問題 1 が起きる\n          detectability: 気づかされない\n        premise_check:\n          stages: A\n          result: verified\n        fix_necessity: could\n",
			"category がありません"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			src := fixNecessityRecordYAML()
			mutated := strings.Replace(src, tc.old, tc.new, 1)
			if mutated == src {
				t.Fatalf("フィクスチャの置換が適用されていない: %q", tc.old)
			}
			problems := fixNecessityProblems(mutated)
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

// fix_necessity_reason を必須にするのは、記録の中で最初に fix_necessity_reason か、回の
// min_fix_necessity を書いた回と、それより後の回。それより前の回と、どちらも 1 度も書いて
// いない記録は、必要度の判定が無い判定フローで判定したものと見なし、無くても報告しない。
func TestReviewTriageRecordFixNecessityRequiredFromFirstRun(t *testing.T) {
	without := func() string {
		return fixNecessityRunYAML("", fixNecessityFindingYAML(1, "", "", "adopted", "A2"), fixNecessityPlanYAML)
	}
	with := func() string {
		return fixNecessityRunYAML("", fixNecessityFindingYAML(1, "must", reasonMust, "adopted", "A2"), fixNecessityPlanYAML)
	}
	cases := []struct {
		name string
		src  string
		want []string // 欠落が報告される回。空なら報告されない
	}{
		{"1 度も書いていない記録は報告しない", "runs:\n" + without() + without(), nil},
		{"書いた回より前の回は報告しない", "runs:\n" + without() + with(), nil},
		{"書いた回より後の回の書き忘れを報告する", "runs:\n" + with() + without(), []string{"runs[1]"}},
		{"下限だけを書いた回の書き忘れを報告する",
			"runs:\n" + fixNecessityRunYAML("must", fixNecessityFindingYAML(1, "", "", "adopted", "A2"), fixNecessityPlanYAML),
			[]string{"runs[0]"}},
		{"下限だけを書いた回より前の回は報告しない",
			"runs:\n" + without() + fixNecessityRunYAML("must", fixNecessityFindingYAML(1, "", "", "adopted", "A2"), fixNecessityPlanYAML),
			[]string{"runs[1]"}},
		{"書いた回の中の書き忘れを報告する",
			"runs:\n" + fixNecessityRunYAML("",
				fixNecessityFindingYAML(1, "must", reasonMust, "adopted", "A2")+fixNecessityFindingYAML(2, "", "", "held", "H6"),
				fixNecessityPlanYAML),
			[]string{"runs[0] (2026-11-07 code-review): findings[1] (id 2)"}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			var got []string
			for _, p := range fixNecessityProblems(tc.src) {
				if strings.Contains(p, "fix_necessity_reason がありません (D4") {
					got = append(got, p)
				}
			}
			if len(got) != len(tc.want) {
				t.Fatalf("欠落の報告が %d 件、want %d 件 (%v)。出た問題: %v", len(got), len(tc.want), tc.want, got)
			}
			for i, w := range tc.want {
				if !strings.Contains(got[i], w) {
					t.Fatalf("欠落の報告 %d に %q が無い: %q", i, w, got[i])
				}
			}
		})
	}
}

// 記録の最後の回が、残っている下限未満の指摘のうち、必要度がその回の下限以上のものを、
// その回の指摘として足していなければ報告する。下限に満たないもの・その回が参照しているもの・
// 前の回で判定し直したか採択にしたものは報告しない。下限が無い回では足さないので、何も求めない。
// 前の回の足し忘れは、findings を後から書き換えないので報告しない。
func TestReviewTriageRecordPriorBelowMinimumMustBeAdded(t *testing.T) {
	// 1 回目 (下限 must) に、Should (id 1) と Could (id 2) の下限未満がある。
	run1 := fixNecessityRunYAML("must",
		fixNecessityFindingYAML(1, "should", reasonShould, "below_minimum", "B1")+
			fixNecessityFindingYAML(2, "could", reasonCould, "below_minimum", "B1"), "")
	other := fixNecessityFindingYAML(9, "must", reasonMust, "adopted", "A2")
	addShould := omittedFindingYAML(1, 1, 1, "prior_below_minimum", "adopted", "A3")
	addCould := omittedFindingYAML(2, 1, 2, "prior_below_minimum", "adopted", "A3")
	const missing = "この回の findings に足されていません"
	cases := []struct {
		name string
		runs string
		want []string // 報告に含まれるべき語 (1 件に 1 つ)。空なら報告されない
	}{
		{"下限が同じ回は、足さなくてよい", fixNecessityRunYAML("must", other, ""), nil},
		{"下限を should に下げた回は、Should を足す", fixNecessityRunYAML("should", other, ""),
			[]string{"1 回目の id 1。必要度 should) が、この回の下限 should 以上なのに、この回の findings に"}},
		{"下限を should に下げて Should を足した回は、報告しない", fixNecessityRunYAML("should", addShould, ""), nil},
		{"下限が無い回は、足さなくてよい", fixNecessityRunYAML("", other, ""), nil},
		{"下限を could に下げた回は、すべて足す", fixNecessityRunYAML("could", other, ""),
			[]string{"1 回目の id 1。必要度 should) が、この回の下限 could 以上なのに、この回の findings に", "1 回目の id 2。必要度 could) が、この回の下限 could 以上なのに、この回の findings に"}},
		{"下限を could に下げて両方を足した回は、報告しない", fixNecessityRunYAML("could", addShould+addCould, ""), nil},
		{"前の回で採択にした指摘は、後の回で足さなくてよい",
			fixNecessityRunYAML("should", addShould, fixNecessityPlanYAML) + fixNecessityRunYAML("should", other, ""), nil},
		{"足し忘れが続いていれば、最後の回だけを報告する",
			fixNecessityRunYAML("should", fixNecessityFindingYAML(1, "must", reasonMust, "adopted", "A2"), fixNecessityPlanYAML) +
				fixNecessityRunYAML("should", other, ""),
			[]string{"runs[2]"}},
		{"足し忘れた回の後の回で足していれば、報告しない",
			fixNecessityRunYAML("should", fixNecessityFindingYAML(1, "must", reasonMust, "adopted", "A2"), fixNecessityPlanYAML) +
				fixNecessityRunYAML("should", addShould, ""),
			nil},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			var got []string
			for _, p := range fixNecessityProblems("runs:\n" + run1 + tc.runs) {
				if strings.Contains(p, missing) {
					got = append(got, p)
				} else {
					t.Fatalf("足し忘れのほかの問題が出た: %s", p)
				}
			}
			if len(got) != len(tc.want) {
				t.Fatalf("足し忘れの報告が %d 件、want %d 件 (%v)。出た問題: %v", len(got), len(tc.want), tc.want, got)
			}
			for i, w := range tc.want {
				if !strings.Contains(got[i], w) {
					t.Fatalf("報告 %d に %q が無い: %q", i, w, got[i])
				}
			}
		})
	}
}

// 下限が無い回に、前の回までの下限未満の指摘を足すと報告する。下限を指定せずにループを起動し直した
// だけで、下限未満の指摘が採択になることを防ぐため。レビュアがその回に報告した同じ問題の指摘
// (origin が prior_below_minimum でないもの) は報告しない。
func TestReviewTriageRecordPriorBelowMinimumNotAddedWithoutMinimum(t *testing.T) {
	run1 := fixNecessityRunYAML("must", fixNecessityFindingYAML(1, "should", reasonShould, "below_minimum", "B1"), "")
	const want = "下限が無い回では、前の回までの下限未満の指摘を足さない"
	cases := []struct {
		name   string
		origin string
		report bool
	}{
		{"足した指摘は報告する", "prior_below_minimum", true},
		{"レビュアが報告した指摘は報告しない", "", false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			src := "runs:\n" + run1 + fixNecessityRunYAML("", omittedFindingYAML(1, 1, 1, tc.origin, "adopted", "A3"), "")
			problems := fixNecessityProblems(src)
			if !tc.report {
				if len(problems) != 0 {
					t.Fatalf("問題が出た: %v", problems)
				}
				return
			}
			if len(problems) != 1 || !strings.Contains(problems[0], want) {
				t.Fatalf("%q を含む問題が 1 件だけ出るべき。出た問題: %v", want, problems)
			}
		})
	}
}

// 生成サマリの、推移の表・節「下限未満の指摘」・指摘の表の判定の欄を検証する。
func TestReviewTriageSummaryFixNecessity(t *testing.T) {
	summary, err := renderReviewTriageSummary(reviewTriageDir+"feat-x.yaml", []byte(fixNecessityRecordYAML()))
	if err != nil {
		t.Fatalf("サマリの生成に失敗: %v", err)
	}
	// 推移の表と、節「下限未満の指摘」は、全文で比べる。
	// 1 回目の Should (#2) は 2 回目で採択 (A3) に、Could (#3) は 3 回目で判定し直したので、
	// どちらも残っていない。
	wantHead := "## 推移\n" +
		"\n" +
		"| 回 | 日付 | スキル | model | scope | 下限 | 全件 | 採択 | 保留 | 却下 | 下限未満 | Must | Should | Could |\n" +
		"| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n" +
		"| 1 | 2026-11-07 | `code-review` | `opus` | incremental | must | 5 | 1 | 1 | 1 | 2 | 1 | 2 | 1 |\n" +
		"| 2 | 2026-11-07 | `code-review` | `opus` | incremental | should | 2 | 1 | 0 | 0 | 1 | 0 | 1 | 1 |\n" +
		"| 3 | 2026-11-07 | `code-review` | `opus` | incremental | — | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 1 |\n" +
		"\n" +
		"## 下限未満の指摘\n" +
		"\n" +
		"残っている下限未満の指摘はありません (後の回で判定し直したか、採択にしたか、採択した問題と一緒に直した)。\n" +
		"\n" +
		"## 1 回目: "
	if !strings.Contains(summary, wantHead) {
		t.Fatalf("推移の表と節「下限未満の指摘」が期待と違う:\n%s", summary)
	}
	for _, want := range []string{
		"| **採択** — A2 (必要度: Must) |",
		"| **下限未満** — B1 (必要度: Should) |",
		"| **保留** — H8 (必要度: 決められない) |",
		"| 1 | `docs/f2.md:20` 指摘 2 | — | — | — | — | **採択** — A3 (1 回目の #2 と同じ) |",
		"| 2 | `docs/f3.md:30` 指摘 3 | — | — | — | — | **下限未満** — B2 (1 回目の #3 と同じ) |",
		"| **採択** — A2 (必要度: Could) (1 回目の #3 と同じ問題を判定し直した) |",
	} {
		if !strings.Contains(summary, want) {
			t.Fatalf("生成サマリに %q が無い:\n%s", want, summary)
		}
	}
}

// 節「下限未満の指摘」には、残っている指摘だけを必要度ごとに並べる。同じ問題がまた
// 報告されて判定を省略した回 (B2) は、行を増やさず「また報告された回」に出す。
func TestReviewTriageSummaryBelowMinimumSection(t *testing.T) {
	run1 := fixNecessityRunYAML("must",
		fixNecessityFindingYAML(1, "should", reasonShould, "below_minimum", "B1")+
			fixNecessityFindingYAML(2, "could", reasonCould, "below_minimum", "B1")+
			fixNecessityFindingYAML(3, "should", reasonShould, "below_minimum", "B1"), "")
	run2 := fixNecessityRunYAML("must",
		omittedFindingYAML(1, 1, 1, "", "below_minimum", "B2")+
			omittedFindingYAML(2, 1, 2, "", "below_minimum", "B2"), "")
	run3 := fixNecessityRunYAML("must", omittedFindingYAML(1, 1, 1, "", "below_minimum", "B2"), "")
	src := "runs:\n" + run1 + run2 + run3
	if problems := fixNecessityProblems(src); len(problems) != 0 {
		t.Fatalf("フィクスチャに問題がある: %v", problems)
	}
	summary, err := renderReviewTriageSummary(reviewTriageDir+"feat-x.yaml", []byte(src))
	if err != nil {
		t.Fatalf("サマリの生成に失敗: %v", err)
	}
	want := "\n## 下限未満の指摘\n" +
		"\n" +
		"### Should (2 件)\n" +
		"\n" +
		"| 判定した回 | 指摘 | 回避策 | また報告された回 |\n" +
		"| --- | --- | --- | --- |\n" +
		"| 1 回目 #1 | `docs/f1.md:10` 指摘 1 | 実装のテストが失敗して気づかされる | 2 回目 #1、3 回目 #1 |\n" +
		"| 1 回目 #3 | `docs/f3.md:30` 指摘 3 | 実装のテストが失敗して気づかされる | — |\n" +
		"\n" +
		"### Could (1 件)\n" +
		"\n" +
		"| 判定した回 | 指摘 | 回避策 | また報告された回 |\n" +
		"| --- | --- | --- | --- |\n" +
		"| 1 回目 #2 | `docs/f2.md:20` 指摘 2 | — | 2 回目 #2 |\n" +
		"\n" +
		"## 1 回目: "
	if !strings.Contains(summary, want) {
		t.Fatalf("節「下限未満の指摘」が期待と違う:\n%s", summary)
	}
	// 推移の表の必要度の列は、判定を省略した指摘を参照先の必要度で数える。
	if !strings.Contains(summary, "| must | 2 | 0 | 0 | 0 | 2 | 0 | 1 | 1 |\n") {
		t.Fatalf("2 回目の推移の行が期待と違う:\n%s", summary)
	}
}

// 指摘が示した解決策 (suggested_fix) は、書いても検査が報告せず、生成サマリにも出ない。
func TestReviewTriageRecordSuggestedFix(t *testing.T) {
	src := strings.Replace(validRecordYAML, "        summary: 数の食い違い\n",
		"        summary: 数の食い違い\n        suggested_fix: 表の数を本文に合わせる\n", 1)
	if src == validRecordYAML {
		t.Fatal("フィクスチャの置換が適用されていない")
	}
	files, read := recordFiles(t, src)
	if problems := reviewTriageRecordProblems(files, read); len(problems) != 0 {
		t.Fatalf("suggested_fix を書いた記録で問題が出た: %v", problems)
	}
	summary, err := renderReviewTriageSummary(reviewTriageDir+"feat-x.yaml", []byte(src))
	if err != nil {
		t.Fatalf("サマリの生成に失敗: %v", err)
	}
	if summary != summaryWithoutInvestigated {
		t.Fatalf("suggested_fix を書いた記録の生成サマリが、書いていない記録と違う:\n%s", summary)
	}
}

// 下限未満の指摘が 1 件も無い記録には、節「下限未満の指摘」を出さない。
func TestReviewTriageSummaryNoBelowMinimumSection(t *testing.T) {
	summary, err := renderReviewTriageSummary(reviewTriageDir+"feat-x.yaml", []byte(validRecordYAML))
	if err != nil {
		t.Fatalf("サマリの生成に失敗: %v", err)
	}
	if strings.Contains(summary, "下限未満の指摘") {
		t.Fatalf("下限未満の指摘が無い記録に節が出ている:\n%s", summary)
	}
}

// fixedTogetherRecordYAML は、1 回目の下限未満の指摘 (id 1。必要度 Should) を、2 回目の問題 P1 と
// 一緒に直す記録。plan は 2 回目の P1 の YAML、last は 3 回目の下限。
func fixedTogetherRecordYAML(plan, last string) string {
	run1 := fixNecessityRunYAML("must", strings.Replace(
		fixNecessityFindingYAML(1, "should", reasonShould, "below_minimum", "B1"),
		"        verdict: below_minimum\n",
		"        plan_ref:\n          run: 2\n          problem: P1\n        verdict: below_minimum\n", 1), "")
	run2 := fixNecessityRunYAML("must", fixNecessityFindingYAML(1, "must", reasonMust, "adopted", "A2"), plan)
	run3 := fixNecessityRunYAML(last, fixNecessityFindingYAML(9, "must", reasonMust, "adopted", "A2"), "")
	return "runs:\n" + run1 + run2 + run3
}

const (
	planPendingYAML      = "      - problem_id: P1\n        cause: 原因\n        finding_ids: [1]\n        approach: 直す\n        status: pending\n"
	planNotFixedYAML     = "      - problem_id: P1\n        cause: 原因\n        finding_ids: [1]\n        decision:\n          target: t\n          baseline: b\n          choice: undecided\n          choice_reason: r\n        status: not-fixed\n"
	planDoneExternalYAML = "      - problem_id: P1\n        cause: 原因\n        finding_ids: [1]\n        approach: 直す\n        applied_external_url: \"https://example.com\"\n        status: done-external\n"
)

// 下限未満の指摘を、採択した問題と一緒に直したら (plan_ref の問題が done か done-external)、
// 残っている指摘から除く。問題がまだ直っていなければ (未着手・直さない)、残っている。
func TestBelowMinimumFixedTogether(t *testing.T) {
	cases := []struct {
		name      string
		plan      string
		remaining bool
	}{
		{"問題が done なら残っていない", fixNecessityPlanYAML, false},
		{"問題が done-external なら残っていない", planDoneExternalYAML, false},
		{"問題が pending なら残っている", planPendingYAML, true},
		{"問題が not-fixed なら残っている", planNotFixedYAML, true},
	}
	const missing = "1 回目の id 1。必要度 should) が、この回の下限 could 以上なのに"
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			src := fixedTogetherRecordYAML(tc.plan, "could")
			reported := false
			for _, p := range fixNecessityProblems(src) {
				if strings.Contains(p, missing) {
					reported = true
				} else if !strings.Contains(p, "採択が修正計画に載っていません") {
					t.Fatalf("足し忘れのほかの問題が出た: %s", p)
				}
			}
			if reported != tc.remaining {
				t.Fatalf("足し忘れを報告するべきか: %v。報告: %v", tc.remaining, reported)
			}
			summary, err := renderReviewTriageSummary(reviewTriageDir+"feat-x.yaml", []byte(src))
			if err != nil {
				t.Fatalf("サマリの生成に失敗: %v", err)
			}
			if listed := strings.Contains(summary, "### Should (1 件)"); listed != tc.remaining {
				t.Fatalf("節に並ぶべきか: %v。生成サマリ:\n%s", tc.remaining, summary)
			}
			if !tc.remaining && !strings.Contains(summary, "残っている下限未満の指摘はありません (後の回で判定し直したか、採択にしたか、採択した問題と一緒に直した)。") {
				t.Fatalf("節の文が期待と違う:\n%s", summary)
			}
			if !strings.Contains(summary, "**下限未満** — B1 (必要度: Should) (束ね先: 2 回目の P1)") {
				t.Fatalf("判定の欄に束ね先が無い:\n%s", summary)
			}
		})
	}
}

// 判定を省略した下限未満の指摘 (B2) には plan_ref を書かない。一緒に直したことは、必要度を判定した
// 指摘 (B1) に書く。判定を省略した採択 (A3) には、今までどおり書ける。
// 一緒に直した後に、行が変わらないまま同じ問題が報告されたら (B2)、箇所は直っていないので
// 残っている。節に並び、また報告された回も出て、下限を下げた回では足し忘れの検査の対象になる。
func TestBelowMinimumFixedTogetherReportedAgain(t *testing.T) {
	src := fixedTogetherRecordYAML(fixNecessityPlanYAML, "must") +
		fixNecessityRunYAML("must", omittedFindingYAML(1, 1, 1, "", "below_minimum", "B2"), "") +
		fixNecessityRunYAML("could", fixNecessityFindingYAML(1, "must", reasonMust, "adopted", "A2"), "")
	const missing = "1 回目の id 1。必要度 should) が、この回の下限 could 以上なのに"
	reported := false
	for _, p := range fixNecessityProblems(src) {
		reported = reported || strings.Contains(p, missing)
	}
	if !reported {
		t.Fatalf("足し忘れが報告されない: %v", fixNecessityProblems(src))
	}
	summary, err := renderReviewTriageSummary(reviewTriageDir+"feat-x.yaml", []byte(src))
	if err != nil {
		t.Fatalf("サマリの生成に失敗: %v", err)
	}
	for _, want := range []string{"### Should (1 件)", "4 回目 #1"} {
		if !strings.Contains(summary, want) {
			t.Fatalf("生成サマリに %q が無い:\n%s", want, summary)
		}
	}
}

func TestBelowMinimumPlanRefOnOmitted(t *testing.T) {
	planRef := "        plan_ref:\n          run: 1\n          problem: P1\n"
	withPlan := fixNecessityRunYAML("must",
		fixNecessityFindingYAML(1, "should", reasonShould, "below_minimum", "B1")+fixNecessityFindingYAML(2, "must", reasonMust, "adopted", "A2"),
		strings.Replace(fixNecessityPlanYAML, "finding_ids: [1]", "finding_ids: [2]", 1))
	const want = "判定を省略した下限未満の指摘 (B2) には plan_ref を書かない"
	b2 := "runs:\n" + withPlan + fixNecessityRunYAML("must", omittedFindingYAML(1, 1, 1, "", "below_minimum", "B2")+planRef, "")
	problems := fixNecessityProblems(b2)
	if len(problems) != 1 || !strings.Contains(problems[0], want) {
		t.Fatalf("%q を含む問題が 1 件だけ出るべき。出た問題: %v", want, problems)
	}
	a3 := "runs:\n" + withPlan + fixNecessityRunYAML("should", omittedFindingYAML(1, 1, 1, "prior_below_minimum", "adopted", "A3")+planRef, "")
	if problems := fixNecessityProblems(a3); len(problems) != 0 {
		t.Fatalf("A3 の plan_ref で問題が出た: %v", problems)
	}
}
