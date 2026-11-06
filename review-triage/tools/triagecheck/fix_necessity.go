// fix_necessity.go は、修正の必要度 (findings[].fix_necessity と fix_necessity_reason)・
// 必要度の下限 (runs[].min_fix_necessity)・判定「下限未満」(verdict: below_minimum)・
// 下限未満の指摘の参照 (findings[].below_minimum_ref) の検査と、生成サマリへの描画を持つ。
// 判定の条件の SSOT は skills/review-triage/references/judgment-flow.md の D9〜D12・E3、
// キーの意味の SSOT は同じディレクトリの record-schema.md。
package main

import (
	"fmt"
	"strings"
)

// recordFixNecessityReason は findings[].fix_necessity_reason を表し、E3 の 2 つの条件の
// 結果を持つ。goal_without_action は条件 1 (困る人は、何もしなくても目的を達成できるか)、
// workaround は条件 2 (困る人が気づいて取れる回避策があるか) の結果で、条件 1 が not-holds の
// ときだけ書く。必要度 (fix_necessity) はこの結果から決まる (fixNecessityFromReason)。
// 判定理由の文に書く形にしないのは、書き忘れを検査で見つけられないため (prior_defect と同じ)。
type recordFixNecessityReason struct {
	GoalWithoutAction string `yaml:"goal_without_action"`
	Workaround        string `yaml:"workaround"`
	WorkaroundReason  string `yaml:"workaround_reason"`
}

// recordBelowMinimumRef は findings[].below_minimum_ref を表す。D9 の (1) (前の回までの
// 下限未満の指摘と問題が同じ) が成り立った指摘に書く。run と finding は参照先 (1 始まりの
// 回番号と、その回の指摘の id)、line_check は D9 の (2) (対象の行が変わっていない) の結果。
type recordBelowMinimumRef struct {
	Run        int    `yaml:"run"`
	Finding    int    `yaml:"finding"`
	LineCheck  string `yaml:"line_check"`
	LineReason string `yaml:"line_reason"`
}

// fixNecessityRank は必要度の高さを返す (must が最も高い)。列挙に無い値は 0。
func fixNecessityRank(v string) int {
	switch v {
	case "must":
		return 3
	case "should":
		return 2
	case "could":
		return 1
	}
	return 0
}

// fixNecessityJa は必要度を生成サマリに出す表記にする。
func fixNecessityJa(v string) string {
	switch v {
	case "must":
		return "Must"
	case "should":
		return "Should"
	case "could":
		return "Could"
	}
	return recordCell(v)
}

// fixNecessityBelow は、必要度が下限に満たないかを返す。下限が無ければ満たないことは無い。
// どちらかが列挙に無い値のときは、比べられないので偽を返す (列挙の誤りは別に報告する)。
func fixNecessityBelow(necessity, minimum string) bool {
	n, m := fixNecessityRank(necessity), fixNecessityRank(minimum)
	return n > 0 && m > 0 && n < m
}

// fixNecessityFromReason は、2 つの条件の結果から決まる必要度を返す。どちらかの条件が
// undecided なら空 (必要度を付けない)。ok が偽なら、結果の形が誤っていて決まらない。
func fixNecessityFromReason(r *recordFixNecessityReason) (necessity string, ok bool) {
	switch r.GoalWithoutAction {
	case "holds":
		return "could", r.Workaround == ""
	case "undecided":
		return "", r.Workaround == ""
	case "not-holds":
		switch r.Workaround {
		case "holds":
			return "should", true
		case "not-holds":
			return "must", true
		case "undecided":
			return "", true
		}
	}
	return "", false
}

// judgmentOmitted は、D9 で当たって判定を省略した指摘 (A3・B2) かを返す。
func judgmentOmitted(fd recordFinding) bool {
	return fd.BelowMinimumRef != nil && fd.BelowMinimumRef.LineCheck == "holds"
}

// recordFixNecessityFirstRun は、記録の中で最初に fix_necessity_reason か、回の
// min_fix_necessity を書いた回の添字を返す。無ければ -1。この回と、それより後の回では
// fix_necessity_reason を必須にする。過去の記録を書き換えさせずに通すための決め方で、理由は
// recordPriorDefectFirstRun と同じ。回の下限も見るのは、下限を書いた回は必要度を判定する規則で
// 判定した回なので、その回で必要度を全件書き忘れた記録を報告するため。
func recordFixNecessityFirstRun(runs []recordRun) int {
	for ri, run := range runs {
		if run.MinFixNecessity != "" {
			return ri
		}
		for _, fd := range run.Findings {
			if fd.FixNecessityReason != nil {
				return ri
			}
		}
	}
	return -1
}

// recordFixNecessityProblems は、判定を省略していない指摘 1 件の必要度を検査する。
// 書く条件は E3 を行ったかで決まる。判定フローでは、D4 で根拠を確認した指摘
// (premise_check.result が verified) だけが E3 に進む。required が偽の回
// (recordFixNecessityFirstRun の回より前の回) では、無くても報告しない。
// minimum はその回の必要度の下限 (無ければ空)。
func recordFixNecessityProblems(required bool, minimum string, fd recordFinding) []string {
	var problems []string
	add := func(format string, args ...any) {
		problems = append(problems, fmt.Sprintf(format, args...))
	}
	if fd.FixNecessity != "" && fixNecessityRank(fd.FixNecessity) == 0 {
		add("fix_necessity は must / should / could のいずれか (決められなければ書かない): %q", fd.FixNecessity)
	}
	// 下限未満にできるのは、必要度を決めた指摘だけ。必要度の無い下限未満は、下の対応の
	// 検査では見つからない (理由の無い指摘と、決められなかった指摘の両方がある) ので、ここで見る。
	if fd.Verdict == "below_minimum" && fd.FixNecessity == "" {
		add("verdict が below_minimum なのに fix_necessity がありません (下限未満にできるのは、必要度を決めた指摘だけ)")
	}
	verified := fd.PremiseCheck.Result == "verified"
	r := fd.FixNecessityReason
	if r == nil {
		switch {
		case fd.FixNecessity != "":
			add("fix_necessity があるのに fix_necessity_reason がありません (必要度は、E3 の 2 つの条件の結果から決める)")
		case verified && required:
			add("fix_necessity_reason がありません (D4 で根拠を確認した指摘は E3 で必要度を判定するので、条件の結果を書く。この記録では、この回かそれより前の回で fix_necessity_reason を書いている)")
		}
		return problems
	}
	if !verified {
		// E3 に進んでいない指摘の必要度は、どの値でも判定の経路と矛盾するので、中身は検査しない。
		add("fix_necessity_reason は E3 を行った指摘 (premise_check.result が verified) にだけ書く (result %q)", fd.PremiseCheck.Result)
		return problems
	}
	shapeValid := true
	switch r.GoalWithoutAction {
	case "holds", "not-holds", "undecided":
	default:
		shapeValid = false
		add("fix_necessity_reason.goal_without_action は holds / not-holds / undecided のいずれか: %q", r.GoalWithoutAction)
	}
	switch {
	case r.GoalWithoutAction == "not-holds":
		switch r.Workaround {
		case "holds", "not-holds", "undecided":
		case "":
			shapeValid = false
			add("fix_necessity_reason.workaround がありません (goal_without_action が not-holds なら条件 2 を判定する)")
		default:
			shapeValid = false
			add("fix_necessity_reason.workaround は holds / not-holds / undecided のいずれか: %q", r.Workaround)
		}
		if r.Workaround != "" && r.WorkaroundReason == "" {
			add("fix_necessity_reason.workaround_reason がありません (回避策の手段か、無い理由か、決められなかった理由)")
		}
	case shapeValid:
		// 条件 1 が成り立つか決められなければ、条件 2 は判定しない。
		if r.Workaround != "" || r.WorkaroundReason != "" {
			shapeValid = false
			add("fix_necessity_reason.workaround と workaround_reason は、goal_without_action が not-holds のときだけ書く (goal_without_action %q)", r.GoalWithoutAction)
		}
	}
	if !shapeValid {
		return problems
	}
	want, _ := fixNecessityFromReason(r)
	if fd.FixNecessity != want {
		if want == "" {
			add("fix_necessity_reason では必要度が決まらない (undecided がある) のに、fix_necessity %q があります", fd.FixNecessity)
		} else {
			add("fix_necessity は、fix_necessity_reason から決まる %s と違います: %q", want, fd.FixNecessity)
		}
		return problems
	}
	switch {
	case want == "" && fd.Verdict == "adopted":
		add("必要度を決められなかった (fix_necessity_reason に undecided がある) のに、verdict が adopted です (決められなければ H8 の保留)")
	case fd.Verdict == "adopted" && fixNecessityBelow(want, minimum):
		add("必要度 %s が回の下限 %s に満たないのに、verdict が adopted です (下限に満たなければ B1 の下限未満)", want, minimum)
	case fd.Verdict == "below_minimum" && want != "" && !fixNecessityBelow(want, minimum):
		if minimum == "" {
			add("回に下限 (min_fix_necessity) が無いのに、verdict が below_minimum です")
		} else {
			add("必要度 %s が回の下限 %s 以上なのに、verdict が below_minimum です", want, minimum)
		}
	}
	return problems
}

// belowMinimumRefTarget は below_minimum_ref の参照先の指摘を返す。参照先にできるのは、
// この回 (添字 ri) より前の回の、必要度を判定して下限未満にした指摘 (B1) だけ。
// 判定を省略した指摘 (B2) は必要度を持たないので、参照先にしない。
func belowMinimumRefTarget(doc *recordDoc, ri int, ref *recordBelowMinimumRef) (*recordFinding, string) {
	if ref.Run < 1 || ref.Run > ri {
		return nil, fmt.Sprintf("below_minimum_ref の run %d は、この回より前の回ではありません (この回は %d 回目)", ref.Run, ri+1)
	}
	findings := doc.Runs[ref.Run-1].Findings
	for i := range findings {
		if findings[i].ID != ref.Finding {
			continue
		}
		t := &findings[i]
		if t.Verdict != "below_minimum" || fixNecessityRank(t.FixNecessity) == 0 {
			return nil, fmt.Sprintf("below_minimum_ref の参照先 (%d 回目の id %d) は、必要度を判定して下限未満にした指摘ではありません (verdict %q / fix_necessity %q)",
				ref.Run, ref.Finding, t.Verdict, t.FixNecessity)
		}
		return t, ""
	}
	return nil, fmt.Sprintf("below_minimum_ref の finding %d は %d 回目の findings にありません", ref.Finding, ref.Run)
}

// recordBelowMinimumRefProblems は指摘 1 件の below_minimum_ref と、それに関わるキーを検査する。
func recordBelowMinimumRefProblems(doc *recordDoc, ri int, fd recordFinding) []string {
	var problems []string
	add := func(format string, args ...any) {
		problems = append(problems, fmt.Sprintf(format, args...))
	}
	// 下限が無い回では、前の回までの下限未満の指摘を足さない (record-schema.md の「下限未満の指摘の参照」)。
	// 足すと、下限を指定していないのに、下限未満の指摘が採択になる。
	if fd.Origin == "prior_below_minimum" && doc.Runs[ri].MinFixNecessity == "" {
		add("回に下限 (min_fix_necessity) が無いのに、origin が prior_below_minimum の指摘があります (下限が無い回では、前の回までの下限未満の指摘を足さない)")
	}
	ref := fd.BelowMinimumRef
	if ref == nil {
		if fd.Origin == "prior_below_minimum" {
			add("origin が prior_below_minimum なのに below_minimum_ref がありません (足した指摘は、前の回のどの指摘かを書く)")
		}
		return problems
	}
	target, msg := belowMinimumRefTarget(doc, ri, ref)
	if msg != "" {
		add("%s", msg)
	}
	switch ref.LineCheck {
	case "holds", "not-holds", "unverifiable":
	default:
		add("below_minimum_ref.line_check は holds / not-holds / unverifiable のいずれか: %q", ref.LineCheck)
	}
	if ref.LineReason == "" {
		add("below_minimum_ref.line_reason がありません (対象の行が変わっていないかの結果の理由)")
	}
	if !judgmentOmitted(fd) {
		return problems
	}
	if fd.Verdict == "below_minimum" && fd.PlanRef != nil {
		add("判定を省略した下限未満の指摘 (B2) には plan_ref を書かない (一緒に直したことは、必要度を判定した参照先の指摘に書く)")
	}
	// 判定を省略した指摘 (A3・B2)。分類・被害者・帰結・根拠の検証・ゲート・必要度は書かない。
	// 書いてあると、参照先の値と、この指摘の値のどちらを読むのかが決まらない。
	for _, kv := range []struct {
		key     string
		written bool
	}{
		{"category", fd.Category != ""},
		{"audience", fd.Audience != ""},
		{"audience_initial", fd.AudienceInitial != ""},
		{"consequence", fd.Consequence != recordConsequence{}},
		{"premise_check", fd.PremiseCheck != recordPremise{}},
		{"gates_fired", len(fd.GatesFired) > 0},
		{"prior_defect", fd.PriorDefect != nil},
		{"fix_necessity", fd.FixNecessity != ""},
		{"fix_necessity_reason", fd.FixNecessityReason != nil},
	} {
		if kv.written {
			add("判定を省略した指摘 (below_minimum_ref.line_check が holds) では %s を書かない (参照先の指摘のものを読む)", kv.key)
		}
	}
	if target == nil {
		return problems
	}
	// D12: 参照先の必要度が、この回の下限以上なら採択 (A3)、満たなければ下限未満 (B2)。
	want := "adopted"
	if fixNecessityBelow(target.FixNecessity, doc.Runs[ri].MinFixNecessity) {
		want = "below_minimum"
	}
	if fd.Verdict != want {
		minimum := doc.Runs[ri].MinFixNecessity
		if minimum == "" {
			minimum = "無し"
		}
		add("判定を省略した指摘の verdict は、参照先の必要度 %s と回の下限 %s から %s に決まりますが、%q です",
			target.FixNecessity, minimum, want, fd.Verdict)
	}
	return problems
}

// recordPriorBelowMinimumProblems は、回 (添字 ri) に足すべき下限未満の指摘が、足されているかを
// 検査する。それより前の回の、残っている下限未満の指摘 (必要度を判定して下限未満にした指摘で、
// この回より前の回の指摘が参照して、判定し直しても採択にしてもいないもの) のうち、必要度がこの回の
// 下限以上のものは、この回の指摘として足す (record-schema.md の「下限未満の指摘の参照」)。
// 足し忘れると、下限を下げても、その指摘は採択にならず直されないまま残る。下限が無い回では足さない
// (下限を指定せずにループを起動し直しただけで、下限未満の指摘が採択にならないようにするため) ので、何も求めない。
// 足したかどうかは、この回の指摘の below_minimum_ref が参照しているかで見る。呼び出し元は、
// 記録の最後の回についてだけ呼ぶ。
func recordPriorBelowMinimumProblems(doc *recordDoc, ri int) []string {
	referenced := map[[2]int]bool{}
	for _, fd := range doc.Runs[ri].Findings {
		if ref := fd.BelowMinimumRef; ref != nil {
			referenced[[2]int{ref.Run, ref.Finding}] = true
		}
	}
	minimum := doc.Runs[ri].MinFixNecessity
	// 下限が無い回では足さない。下限が列挙に無い値のときは、比べられないので報告しない
	// (列挙の誤りは別に報告する)。
	if fixNecessityRank(minimum) == 0 {
		return nil
	}
	var problems []string
	for _, e := range belowMinimumEntries(doc, ri) {
		necessity := e.finding.FixNecessity
		if e.resolved || referenced[[2]int{e.run, e.finding.ID}] || fixNecessityBelow(necessity, minimum) {
			continue
		}
		problems = append(problems, fmt.Sprintf(
			"残っている下限未満の指摘 (%d 回目の id %d。必要度 %s) が、この回の下限 %s 以上なのに、この回の findings に足されていません (origin: prior_below_minimum と below_minimum_ref を書いて足す)",
			e.run, e.finding.ID, necessity, minimum))
	}
	return problems
}

// findingFixNecessity は指摘の必要度を返す。判定を省略した指摘は、参照先の必要度。
// 分からなければ空。
func findingFixNecessity(doc *recordDoc, ri int, fd recordFinding) string {
	if !judgmentOmitted(fd) {
		return fd.FixNecessity
	}
	if target, _ := belowMinimumRefTarget(doc, ri, fd.BelowMinimumRef); target != nil {
		return target.FixNecessity
	}
	return ""
}

// renderFixNecessityCounts は推移の表の必要度の 3 列 (Must・Should・Could) を返す。
// 判定に関わらず、その回で必要度が分かる指摘を数える。fix_necessity_reason を必須にする回
// (recordFixNecessityFirstRun) より前の回 (必須にする回が無い記録ではすべての回) は「—」にする。0 と書くと、
// 必要度を判定して 0 件だったように読めるため。
func renderFixNecessityCounts(doc *recordDoc, ri, firstRun int) []string {
	if firstRun < 0 || ri < firstRun {
		return []string{"—", "—", "—"}
	}
	counts := map[string]int{}
	for _, fd := range doc.Runs[ri].Findings {
		counts[findingFixNecessity(doc, ri, fd)]++
	}
	return []string{
		fmt.Sprint(counts["must"]), fmt.Sprint(counts["should"]), fmt.Sprint(counts["could"]),
	}
}

// belowMinimumEntry は、節「下限未満の指摘」の 1 行になる指摘 (必要度を判定して下限未満に
// した指摘)。resolved は、後の回の指摘が参照して、判定し直したか採択 (A3) にしたか、
// 採択した問題と一緒に直した (plan_ref の問題が直った) こと。
// reported は、同じ問題がまた報告されて判定を省略した指摘 (B2) の位置。
type belowMinimumEntry struct {
	run      int
	finding  recordFinding
	resolved bool
	reported []string
}

// belowMinimumEntries は、記録の最初の n 回の中の、必要度を判定して下限未満にした指摘を、記録の順に返す。
// 足し忘れの検査と節「下限未満の指摘」の両方が、これで「残っている」を決める。別々に決めると、
// 片方だけを変えたときに、検査と生成サマリの結果が一致しなくなる。
func belowMinimumEntries(doc *recordDoc, n int) []*belowMinimumEntry {
	var entries []*belowMinimumEntry
	index := map[[2]int]*belowMinimumEntry{}
	for ri, run := range doc.Runs[:n] {
		for _, fd := range run.Findings {
			if ref := fd.BelowMinimumRef; ref != nil {
				if e := index[[2]int{ref.Run, ref.Finding}]; e != nil {
					if judgmentOmitted(fd) && fd.Verdict == "below_minimum" {
						e.reported = append(e.reported, fmt.Sprintf("%d 回目 #%d", ri+1, fd.ID))
					} else {
						e.resolved = true
					}
				}
			}
			if fd.Verdict == "below_minimum" && fixNecessityRank(fd.FixNecessity) > 0 {
				e := &belowMinimumEntry{run: ri + 1, finding: fd, resolved: planRefFixed(doc, fd.PlanRef)}
				entries = append(entries, e)
				index[[2]int{ri + 1, fd.ID}] = e
			}
		}
	}
	return entries
}

// planRefFixed は、plan_ref の問題が直ったか (状態が done か done-external か) を返す。問題がまだ
// 直っていないか、直さないと決めた (not-fixed) なら、指摘の箇所も直っていない。参照の実在は別に検査する。
func planRefFixed(doc *recordDoc, ref *recordPlanRef) bool {
	if ref == nil || ref.Run < 1 || ref.Run > len(doc.Runs) {
		return false
	}
	for _, pl := range doc.Runs[ref.Run-1].Plans {
		if pl.ProblemID == ref.Problem {
			return pl.Status == "done" || pl.Status == "done-external"
		}
	}
	return false
}

// renderBelowMinimumSection は節「下限未満の指摘」を書く。記録に下限未満の指摘が 1 件も
// 無ければ何も書かない。並べるのは残っている指摘だけで、必要度ごとの表にする。
// 件数はここで数え、人が書いた集計をどこからも読まない (推移の表と同じ)。
func renderBelowMinimumSection(b *strings.Builder, doc *recordDoc) {
	hasBelowMinimum := false
	for _, run := range doc.Runs {
		for _, fd := range run.Findings {
			if fd.Verdict == "below_minimum" {
				hasBelowMinimum = true
			}
		}
	}
	if !hasBelowMinimum {
		return
	}
	b.WriteString("\n## 下限未満の指摘\n")
	entries := belowMinimumEntries(doc, len(doc.Runs))
	remaining := 0
	for _, necessity := range []string{"must", "should", "could"} {
		var rows []*belowMinimumEntry
		for _, e := range entries {
			if !e.resolved && e.finding.FixNecessity == necessity {
				rows = append(rows, e)
			}
		}
		if len(rows) == 0 {
			continue
		}
		remaining += len(rows)
		fmt.Fprintf(b, "\n### %s (%d 件)\n\n", fixNecessityJa(necessity), len(rows))
		b.WriteString("| 判定した回 | 指摘 | 回避策 | また報告された回 |\n")
		b.WriteString("| --- | --- | --- | --- |\n")
		for _, e := range rows {
			b.WriteString(recordRow(renderBelowMinimumCells(e)))
		}
	}
	if remaining == 0 {
		b.WriteString("\n残っている下限未満の指摘はありません (後の回で判定し直したか、採択にしたか、採択した問題と一緒に直した)。\n")
	}
}

// renderBelowMinimumCells は節「下限未満の指摘」の 1 行のセルのスライスを返す。
func renderBelowMinimumCells(e *belowMinimumEntry) []string {
	fd := e.finding
	loc := fd.File
	if fd.Line > 0 {
		loc = fmt.Sprintf("%s:%d", fd.File, fd.Line)
	}
	// 回避策は、条件 2 を判定した指摘 (Should) だけが持つ。条件 1 が成り立つ指摘 (Could) は
	// 何もしなくても目的を達成できるので、回避策を書かない。
	workaround := "—"
	if r := fd.FixNecessityReason; r != nil && r.WorkaroundReason != "" {
		workaround = recordCell(r.WorkaroundReason)
	}
	reported := "—"
	if len(e.reported) > 0 {
		reported = strings.Join(e.reported, "、")
	}
	return []string{
		fmt.Sprintf("%d 回目 #%d", e.run, fd.ID),
		"`" + recordCell(loc) + "` " + recordCell(fd.Summary),
		workaround,
		reported,
	}
}

// renderFixNecessityNote は、判定セルに添える必要度と、下限未満の指摘の参照を返す。
// どちらも無い指摘では空。過去の記録の判定セルを変えないため。
func renderFixNecessityNote(fd recordFinding) string {
	var note string
	if fd.FixNecessityReason != nil {
		necessity := "決められない"
		if fd.FixNecessity != "" {
			necessity = fixNecessityJa(fd.FixNecessity)
		}
		note += " (必要度: " + necessity + ")"
	}
	if ref := fd.BelowMinimumRef; ref != nil {
		if judgmentOmitted(fd) {
			note += fmt.Sprintf(" (%d 回目の #%d と同じ)", ref.Run, ref.Finding)
		} else {
			note += fmt.Sprintf(" (%d 回目の #%d と同じ問題を判定し直した)", ref.Run, ref.Finding)
		}
	}
	return note
}
