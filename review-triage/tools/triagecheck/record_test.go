package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// validRecordYAML はスキーマに沿った記録のフィクスチャ。採択・保留・却下を 1 件ずつ持つ。
const validRecordYAML = `runs:
  - date: "2026-08-30"
    skill: code-review
    run_id: ""
    model: sonnet-5
    level: medium
    scope: full
    head: abc1234
    findings:
      - id: 1
        file: docs/foo.md
        line: 10
        summary: 数の食い違い
        category: doc-other
        audience: developer
        consequence:
          condition: 検算するとき
          who: developer
          what: 分母を誤る
          detectability: 気づかない
        premise_check:
          stages: A
          result: verified
        verdict: adopted
        verdict_reason: ゲート 0 件で採択 (A2)
      - id: 2
        file: internal/bar.go
        summary: 仕様違反の主張
        category: production
        audience: operator
        consequence:
          condition: 運用中
          who: operator
          what: 配信が止まる
          detectability: 気づかない
        premise_check:
          stages: A+B
          result: unverifiable
        verdict: held
        verdict_reason: 根拠を確かめられず保留 (H3)
        attrs:
          severity: P2
      - id: 3
        file: tools/baz_test.go
        summary: 一時ファイルの削除が雑
        category: test
        audience: developer
        consequence:
          condition: disk full のとき
          who: developer
          what: テストが落ちる
          detectability: 気づく
        premise_check:
          stages: A
          result: verified
        gates_fired: [developer-domain]
        verdict: rejected
        verdict_reason: 開発者の領域で却下 (R3)
    plans:
      - problem_id: P1
        cause: 数えずに書いた
        finding_ids: [1]
        approach: 数え直して単位を書く
        order: 1
        sha: ""
        status: pending
    notes: 最初の回。
`

// recordFiles はフィクスチャ 1 組 (yaml + 生成済みサマリ) の files と readFile を作る。
func recordFiles(t *testing.T, yamlContent string) ([]string, func(string) ([]byte, error)) {
	t.Helper()
	yamlPath := reviewTriageDir + "feat-x.yaml"
	mdPath := reviewTriageDir + "feat-x.md"
	summary, err := renderReviewTriageSummary(yamlPath, []byte(yamlContent))
	if err != nil {
		t.Fatalf("サマリの生成に失敗: %v", err)
	}
	contents := map[string]string{
		yamlPath: yamlContent,
		mdPath:   summary,
	}
	read := func(p string) ([]byte, error) {
		c, ok := contents[p]
		if !ok {
			t.Fatalf("想定外の読み込み: %s", p)
		}
		return []byte(c), nil
	}
	return []string{yamlPath, mdPath, reviewTriageDir + "README.md"}, read
}

func TestReviewTriageRecordValidPasses(t *testing.T) {
	files, read := recordFiles(t, validRecordYAML)
	if problems := reviewTriageRecordProblems(files, read); len(problems) != 0 {
		t.Fatalf("正しい記録で問題が出た: %v", problems)
	}
}

func TestReviewTriageRecordSchemaViolations(t *testing.T) {
	cases := []struct {
		name string
		old  string // validRecordYAML の中で置き換える文字列
		new  string
		want string // 問題文に含まれるべき語
	}{
		{"model の欠落", "    model: sonnet-5\n", "", "model"},
		{"scope の列挙値違反", "scope: full", "scope: whole", "scope"},
		{"id の重複", "id: 2\n", "id: 1\n", "id"},
		{"帰結の項目の欠落", "          what: 分母を誤る\n", "", "what"},
		{"premise の整合 (none でないのに skipped)", "stages: A\n          result: verified\n        verdict: adopted", "stages: A\n          result: skipped\n        verdict: adopted", "skipped"},
		{"verdict の列挙値違反", "verdict: held", "verdict: pending", "verdict"},
		{"audience の列挙値違反", "audience: operator", "audience: user", "audience"},
		{"audience_initial の列挙値違反", "        audience: operator\n", "        audience: operator\n        audience_initial: user\n", "audience_initial"},
		{"存在しない指摘への参照", "finding_ids: [1]", "finding_ids: [9]", "finding_ids"},
		{"採択でない指摘への参照", "finding_ids: [1]", "finding_ids: [2]", "採択"},
		{"pending なのに sha がある", `sha: ""`, "sha: abc1234", "sha"},
		{"awaiting-human なのに options が無い", "status: pending", "status: awaiting-human", "options"},
		{"done-external なのに sha がある",
			"        sha: \"\"\n        status: pending\n",
			"        sha: abc1234\n        status: done-external\n        notes: PR 本文へ反映\n", "sha"},
		{"done-external なのに反映先が無い", "status: pending", "status: done-external", "applied_external_url"},
		{"status の列挙値違反", "status: pending", "status: done-ext", "status"},
		// done-external 専用のキーの排他 (スキーマ表が「done-external のときだけ書く」と定める)。
		{"pending なのに applied_external_url がある", "        status: pending\n",
			"        status: pending\n        applied_external_url: \"https://example.com/x\"\n", "done-external 専用"},
		{"done なのに applied_external_url がある",
			"        sha: \"\"\n        status: pending\n",
			"        sha: abc1234\n        status: done\n        applied_external_url: \"https://example.com/x\"\n", "done-external 専用"},
		{"awaiting-human なのに notes がある", "        status: pending\n",
			"        status: awaiting-human\n        options: 案 a / 案 b\n        notes: どこかへ反映した\n", "done-external 専用"},
		{"depends_on の宙参照", "order: 1\n", "order: 1\n        depends_on: [P9]\n", "depends_on"},
		// 調査は任意だが、書くなら範囲 (scope) が要る。範囲の無い調査は未調査と区別できない。
		{"investigation に scope が無い", "order: 1\n",
			"order: 1\n        investigation:\n          included: [docs/bar.md の同じ表]\n", "investigation.scope"},
		{"investigation の included に空の要素", "order: 1\n",
			"order: 1\n        investigation:\n          scope: grep -rn foo .\n          included: [\"\"]\n", "investigation.included[0]"},
		{"investigation の未知のキー", "order: 1\n",
			"order: 1\n        investigation:\n          scope: grep -rn foo .\n          found: [docs/bar.md]\n", "found"},
		// 値を省いた構造キー (null) は「無い」と同一に扱われて黙る。書きかけの記録を
		// 未調査・束ね先なしに化けさせないため報告する。
		{"investigation の値が無い (null)", "order: 1\n", "order: 1\n        investigation:\n", "investigation に値がありません"},
		{"plan_ref の値が無い (null)", "        verdict_reason: ゲート 0 件で採択 (A2)\n",
			"        verdict_reason: ゲート 0 件で採択 (A2)\n        plan_ref:\n", "plan_ref に値がありません"},
		{"depends_on の自己参照", "order: 1\n", "order: 1\n        depends_on: [P1]\n", "自己参照"},
		{"未知のキー", "        verdict: adopted\n", "        verdict: adopted\n        severity: P1\n", "severity"},
		{"実行の直下の未知のキー", "    head: abc1234\n", "    head: abc1234\n    foo: 1\n", "foo"},
		{"date が空", "- date: \"2026-08-30\"\n", "- date: \"\"\n", "date"},
		{"id が正の整数でない", "- id: 1\n", "- id: 0\n", "id"},
		{"引用符の無い # を含む値", "cause: 数えずに書いた", "cause: PR #333 を一般化した", "引用符"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			mutated := strings.Replace(validRecordYAML, tc.old, tc.new, 1)
			if mutated == validRecordYAML {
				t.Fatalf("フィクスチャの置換が効いていない: %q", tc.old)
			}
			yamlPath := reviewTriageDir + "feat-x.yaml"
			read := func(_ string) ([]byte, error) { return []byte(mutated), nil }
			problems := reviewTriageRecordProblems([]string{yamlPath}, read)
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

// ' #' 検査の境界: コロン後の空白の揺れ・値全体がコメント・シーケンス先頭キーの
// ブロックスカラーの兄弟・インデント指示子。正規表現では列挙的に穴が開いた型
// (LineComment 走査への置き換えで構造的に守る)。
func TestReviewTriageRecordHashLexicalEdges(t *testing.T) {
	cases := []struct {
		name    string
		old     string
		new     string
		flagged bool // 引用符の問題が出るべきか
	}{
		{"コロン後の空白 2 個でも検出する",
			"    notes: 最初の回。\n", "    notes:  PR #333 の件\n", true},
		{"値全体がコメントでも検出する (任意項目が黙って null になる)",
			"    notes: 最初の回。\n", "    notes: #おぼえがき\n", true},
		{"シーケンス先頭キーのブロックスカラーの兄弟は検査される",
			"      - problem_id: P1\n        cause: 数えずに書いた\n",
			"      - notes_like: |-\n          本文\n        problem_id: P1\n        cause: PR #333 を直す\n",
			true},
		{"インデント指示子つきブロックスカラーの本文は偽陽性にしない",
			"    notes: 最初の回。\n", "    notes: |2-\n      memo: 詳細は PR #333 を見る\n", false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			mutated := strings.Replace(validRecordYAML, tc.old, tc.new, 1)
			if mutated == validRecordYAML {
				t.Fatalf("フィクスチャの置換が効いていない: %q", tc.old)
			}
			yamlPath := reviewTriageDir + "feat-x.yaml"
			read := func(_ string) ([]byte, error) { return []byte(mutated), nil }
			problems := reviewTriageRecordProblems([]string{yamlPath}, read)
			flagged := false
			for _, p := range problems {
				if strings.Contains(p, "引用符") {
					flagged = true
				}
			}
			if flagged != tc.flagged {
				t.Fatalf("引用符の問題の有無が期待と違う (期待 %v)。出た問題: %v", tc.flagged, problems)
			}
		})
	}
}

// LineComment 方式固有の境界の実測ピン: 複数行の素のスカラーの継続行と
// フロー値の後の ' #' は検出され、フロー内の ' #' は解析エラーとして報告される
// (いずれも素通りしない)。
func TestReviewTriageRecordHashNewMethodEdges(t *testing.T) {
	cases := []struct {
		name string
		old  string
		new  string
		want string
	}{
		{"複数行の素のスカラーの継続行の #",
			"    notes: 最初の回。\n", "    notes: 一行目\n      続きの行 #途中のシャープ\n", "行内コメント"},
		{"フロー値の後の #",
			"gates_fired: [developer-domain]", "gates_fired: [developer-domain] #フロー後", "行内コメント"},
		{"フロー内の # は解析エラーになる",
			"gates_fired: [developer-domain]", "gates_fired: [developer-domain #中]", "解析できません"},
		{"引用符付きの値の後ろのコメントも検出する (行内コメントの全面禁止)",
			"cause: 数えずに書いた", "cause: \"数えずに書いた\" # 補足", "行内コメント"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			mutated := strings.Replace(validRecordYAML, tc.old, tc.new, 1)
			if mutated == validRecordYAML {
				t.Fatalf("フィクスチャの置換が効いていない: %q", tc.old)
			}
			read := func(_ string) ([]byte, error) { return []byte(mutated), nil }
			problems := reviewTriageRecordProblems([]string{reviewTriageDir + "feat-x.yaml"}, read)
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

// 自由文字列の欄 (skill・model・head など) に縦棒が入っても表の桁が崩れない。
func TestReviewTriageSummaryEscapesFreeStrings(t *testing.T) {
	mutated := strings.Replace(validRecordYAML, "skill: code-review", "skill: a|b", 1)
	mutated = strings.Replace(mutated, "head: abc1234", "head: h|1", 1)
	summary, err := renderReviewTriageSummary(reviewTriageDir+"feat-x.yaml", []byte(mutated))
	if err != nil {
		t.Fatalf("サマリの生成に失敗: %v", err)
	}
	if !strings.Contains(summary, `a\|b`) {
		t.Fatalf("skill の縦棒が無害化されていない:\n%s", summary)
	}
	if strings.Contains(summary, "| h|1") || strings.Contains(summary, "`h|1`") {
		t.Fatalf("head の縦棒が無害化されていない:\n%s", summary)
	}
}

// 修正計画を書いた回では、採択は自回の plans か plan_ref (束ね先の構造化参照) で
// 覆われる。覆われない採択は「対処しないまま黙って消える」ので検査で捕まえる。
func TestReviewTriageRecordAdoptedCoverage(t *testing.T) {
	extra := `      - id: 4
        file: docs/extra.md
        summary: 束ね忘れの例
        category: doc-other
        audience: developer
        consequence:
          condition: c
          who: developer
          what: w
          detectability: d
        premise_check:
          stages: A
          result: verified
        verdict: adopted
        verdict_reason: A2
`
	base := strings.Replace(validRecordYAML, "    plans:\n", extra+"    plans:\n", 1)
	if base == validRecordYAML {
		t.Fatal("フィクスチャの置換が効いていない")
	}
	yamlPath := reviewTriageDir + "feat-x.yaml"

	t.Run("覆われない採択は報告される", func(t *testing.T) {
		read := func(_ string) ([]byte, error) { return []byte(base), nil }
		problems := reviewTriageRecordProblems([]string{yamlPath}, read)
		found := false
		for _, p := range problems {
			if strings.Contains(p, "修正計画に載っていません") {
				found = true
			}
		}
		if !found {
			t.Fatalf("覆われない採択が報告されない。出た問題: %v", problems)
		}
	})

	t.Run("plan_ref で覆われれば報告されない", func(t *testing.T) {
		covered := strings.Replace(base, "        verdict_reason: A2\n    plans:",
			"        verdict_reason: A2\n        plan_ref:\n          run: 1\n          problem: P1\n    plans:", 1)
		if covered == base {
			t.Fatal("フィクスチャの置換が効いていない")
		}
		read := func(_ string) ([]byte, error) { return []byte(covered), nil }
		for _, p := range reviewTriageRecordProblems([]string{yamlPath}, read) {
			if strings.Contains(p, "修正計画に載っていません") {
				t.Fatalf("plan_ref で覆われた採択が報告された: %v", p)
			}
		}
	})

	t.Run("plans の無い最後の回は被覆を要求しない", func(t *testing.T) {
		noPlans := base[:strings.Index(base, "    plans:")] + "    notes: fix 前の回。\n"
		read := func(_ string) ([]byte, error) { return []byte(noPlans), nil }
		for _, p := range reviewTriageRecordProblems([]string{yamlPath}, read) {
			if strings.Contains(p, "修正計画に載っていません") {
				t.Fatalf("plans の無い最後の回で被覆が要求された: %v", p)
			}
		}
	})

	// plans を書かないまま次の回が追記されたら、その回はもう fix 前ではない。
	// 免除を解かないと、採択が検査からも review-triage-fix からも見えなくなる。
	t.Run("plans の無い過去の回は被覆を要求する", func(t *testing.T) {
		noPlans := base[:strings.Index(base, "    plans:")] + "    notes: fix 前のまま次へ進んだ回。\n"
		next := `  - date: "2026-09-01"
    skill: code-review
    run_id: ""
    model: opus-5
    level: ""
    scope: incremental
    head: abc1234
    findings: []
`
		read := func(_ string) ([]byte, error) { return []byte(noPlans + next), nil }
		problems := reviewTriageRecordProblems([]string{yamlPath}, read)
		found := false
		for _, p := range problems {
			if strings.Contains(p, "修正計画に載っていません") {
				found = true
			}
		}
		if !found {
			t.Fatalf("plans の無い過去の回で被覆が要求されない。出た問題: %v", problems)
		}
	})

	t.Run("plan_ref の宙参照は報告される", func(t *testing.T) {
		for _, ref := range []string{
			"        plan_ref:\n          run: 9\n          problem: P1\n",
			"        plan_ref:\n          run: 1\n          problem: P9\n",
		} {
			dangling := strings.Replace(base, "        verdict_reason: A2\n    plans:",
				"        verdict_reason: A2\n"+ref+"    plans:", 1)
			read := func(_ string) ([]byte, error) { return []byte(dangling), nil }
			problems := reviewTriageRecordProblems([]string{yamlPath}, read)
			found := false
			for _, p := range problems {
				if strings.Contains(p, "plan_ref") {
					found = true
				}
			}
			if !found {
				t.Fatalf("plan_ref の宙参照 (%q) が報告されない。出た問題: %v", ref, problems)
			}
		}
	})
}

// セル単位のテーブル駆動テスト。行に紐付かない部分文字列の照合は別のセルへの
// 偶然一致で通り抜けるため (ミューテーションで実証された 3 度目の同型)、
// セルの値そのものを検証する。
func TestRenderFindingCells(t *testing.T) {
	base := recordFinding{
		ID: 1, File: "docs/foo.md", Summary: "s", Category: "test", Audience: "developer",
		Consequence:  recordConsequence{Condition: "c", Who: "developer", What: "w", Detectability: "d"},
		PremiseCheck: recordPremise{Stages: "A", Result: "verified"},
		Verdict:      "adopted", VerdictReason: "A2",
	}
	cases := []struct {
		name   string
		mutate func(*recordFinding)
		col    int
		want   string
	}{
		{"premise は stages A なら段と結果", nil, 4, "A: verified"},
		{"premise は stages none なら対象外", func(f *recordFinding) {
			f.PremiseCheck = recordPremise{Stages: "none", Result: "skipped"}
		}, 4, "対象外"},
		{"gates 空はダッシュ", nil, 5, "—"},
		{"gates ありは結合", func(f *recordFinding) {
			f.GatesFired = []string{"already-visible", "developer-domain"}
		}, 5, "already-visible, developer-domain"},
		{"audience 上書きは矢印", func(f *recordFinding) {
			f.AudienceInitial = "developer"
			f.Audience = "operator"
		}, 2, "test / developer → operator"},
		{"audience 同値は矢印なし", func(f *recordFinding) {
			f.AudienceInitial = "developer"
		}, 2, "test / developer"},
		{"行番号ありの位置", func(f *recordFinding) { f.Line = 12 }, 1, "`docs/foo.md:12` s"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			fd := base
			if tc.mutate != nil {
				tc.mutate(&fd)
			}
			cells := renderFindingCells(fd)
			if cells[tc.col] != tc.want {
				t.Fatalf("セル %d = %q, want %q", tc.col, cells[tc.col], tc.want)
			}
		})
	}
}

// セルに入る自由文字列は残らず recordCell を通る — loc (file)・depends_on の
// 結合・sha・選択待ち行の problem_id (D3 の取りこぼし 4 箇所)。
func TestRenderCellsEscapeAllFreeStrings(t *testing.T) {
	fd := recordFinding{
		ID: 1, File: "docs/a|b.md", Line: 3, Summary: "s", Category: "test", Audience: "developer",
		Consequence:  recordConsequence{Condition: "c", Who: "developer", What: "w", Detectability: "d"},
		PremiseCheck: recordPremise{Stages: "A", Result: "verified"},
		Verdict:      "adopted", VerdictReason: "A2",
	}
	if cells := renderFindingCells(fd); !strings.Contains(cells[1], `a\|b`) {
		t.Fatalf("file の縦棒が無害化されていない: %q", cells[1])
	}
	pl := recordPlan{ProblemID: "P1", Cause: "c", FindingIDs: []int{1}, Approach: "a",
		Order: 2, DependsOn: []string{"P|9"}, SHA: "a|b", Status: "done"}
	cells := renderPlanCells(pl)
	if !strings.Contains(cells[4], `P\|9`) {
		t.Fatalf("depends_on の縦棒が無害化されていない: %q", cells[4])
	}
	if !strings.Contains(cells[6], `a\|b`) {
		t.Fatalf("sha の縦棒が無害化されていない: %q", cells[6])
	}
	// 選択待ち行の problem_id
	src := strings.Replace(validRecordYAML, "problem_id: P1", "problem_id: P|1", 1)
	src = strings.Replace(src, "status: pending",
		"status: awaiting-human\n        options: 案 a / 案 b", 1)
	summary, err := renderReviewTriageSummary(reviewTriageDir+"feat-x.yaml", []byte(src))
	if err != nil {
		t.Fatalf("サマリの生成に失敗: %v", err)
	}
	if !strings.Contains(summary, `**P\|1 は選択待ち`) {
		t.Fatalf("選択待ち行の problem_id の縦棒が無害化されていない:\n%s", summary)
	}
}

func TestRenderPlanCells(t *testing.T) {
	pl := recordPlan{ProblemID: "P1", Cause: "c", FindingIDs: []int{1, 2}, Approach: "a",
		Order: 2, DependsOn: []string{"P9"}, SHA: "abc1234", Status: "done"}
	cells := renderPlanCells(pl)
	for col, want := range map[int]string{2: "#1 #2", 4: "2 (P9 の後)", 5: "済", 6: "`abc1234`"} {
		if cells[col] != want {
			t.Fatalf("セル %d = %q, want %q", col, cells[col], want)
		}
	}
	empty := recordPlan{ProblemID: "P2", Cause: "c", FindingIDs: []int{1}, Approach: "a", Status: "pending"}
	cells = renderPlanCells(empty)
	for col, want := range map[int]string{4: "—", 5: "未着手", 6: "—"} {
		if cells[col] != want {
			t.Fatalf("空値のセル %d = %q, want %q", col, cells[col], want)
		}
	}
}

// ブロックスカラーの本文は ' #' の検査の対象外 (自由記述の偽陽性を出さない)。
func TestReviewTriageRecordHashInBlockScalarAllowed(t *testing.T) {
	mutated := strings.Replace(validRecordYAML,
		"    notes: 最初の回。\n",
		"    notes: |-\n      最初の回。\n      memo: 詳細は PR #333 を見る\n", 1)
	if mutated == validRecordYAML {
		t.Fatal("フィクスチャの置換が効いていない")
	}
	yamlPath := reviewTriageDir + "feat-x.yaml"
	read := func(_ string) ([]byte, error) { return []byte(mutated), nil }
	for _, p := range reviewTriageRecordProblems([]string{yamlPath}, read) {
		if strings.Contains(p, "引用符") {
			t.Fatalf("ブロックスカラー本文の # が偽陽性になった: %v", p)
		}
	}
}

// シーケンス項目の先頭キー (- cause: … の形) でも ' #' は検出される (偽陰性を残さない)。
func TestReviewTriageRecordHashOnSequenceFirstKey(t *testing.T) {
	mutated := strings.Replace(validRecordYAML,
		"      - problem_id: P1\n        cause: 数えずに書いた\n",
		"      - cause: PR #333 を一般化した\n        problem_id: P1\n", 1)
	if mutated == validRecordYAML {
		t.Fatal("フィクスチャの置換が効いていない")
	}
	yamlPath := reviewTriageDir + "feat-x.yaml"
	read := func(_ string) ([]byte, error) { return []byte(mutated), nil }
	problems := reviewTriageRecordProblems([]string{yamlPath}, read)
	found := false
	for _, p := range problems {
		if strings.Contains(p, "引用符") {
			found = true
		}
	}
	if !found {
		t.Fatalf("シーケンス先頭キーの ' #' が検出されない。出た問題: %v", problems)
	}
}

// サマリの表示分岐 (run_id・audience の上書き・premise 対象外・order 無し・depends_on)
// を固定する。実装済みの挙動の固定 (退行防止)。
func TestReviewTriageSummaryRenderBranches(t *testing.T) {
	src := `runs:
  - date: "2026-08-30"
    skill: code-review
    run_id: run-xyz
    model: opus-5
    scope: incremental
    head: abc1234
    findings:
      - id: 1
        file: docs/foo.md
        summary: 上書きの例
        category: test
        audience: operator
        audience_initial: developer
        consequence:
          condition: c
          who: operator
          what: w
          detectability: d
        premise_check:
          stages: none
          result: skipped
        verdict: held
        verdict_reason: H2
      - id: 2
        file: docs/bar.md
        summary: 採択
        category: test
        audience: developer
        consequence:
          condition: c
          who: developer
          what: w
          detectability: d
        premise_check:
          stages: A
          result: verified
        verdict: adopted
        verdict_reason: A2
      - id: 3
        file: docs/baz.md
        summary: 上書きしない例
        category: test
        audience: developer
        audience_initial: developer
        consequence:
          condition: c
          who: developer
          what: w
          detectability: d
        premise_check:
          stages: A
          result: verified
        verdict: adopted
        verdict_reason: A2
    plans:
      - problem_id: P1
        cause: c1
        finding_ids: [2]
        approach: a1
        sha: ""
        status: pending
      - problem_id: P2
        cause: c2
        finding_ids: [2]
        approach: a2
        order: 2
        depends_on: [P1]
        sha: abc9999
        status: done
`
	summary, err := renderReviewTriageSummary(reviewTriageDir+"feat-x.yaml", []byte(src))
	if err != nil {
		t.Fatalf("サマリの生成に失敗: %v", err)
	}
	for _, want := range []string{
		"(run-xyz)",            // run_id の表示
		"developer → operator", // audience の上書きの表示
		"| 対象外 |",              // premise stages none のセル (summary の語との誤一致を避けて列で照合)
		"| P1 | c1 | #2 | a1 | — | 未着手 | — |",               // order 無しの行全体 (他列の — との誤一致を避ける)
		"| P2 | c2 | #2 | a2 | 2 (P1 の後) | 済 | `abc9999` |", // depends_on と sha 真側の行全体
	} {
		if !strings.Contains(summary, want) {
			t.Fatalf("%q がサマリに無い:\n%s", want, summary)
		}
	}
	// 偽側: audience_initial == audience の指摘 (id 3) には上書きの矢印を出さない。
	if strings.Count(summary, "→") != 1 {
		t.Fatalf("上書きの矢印は 1 箇所 (id 1) だけのはず:\n%s", summary)
	}
}

// 循環する plan と循環しない plan が混在しても、循環だけが報告される。
func TestReviewTriageRecordMixedCyclePlans(t *testing.T) {
	plans := "    plans:\n" +
		recordCyclePlan("P1", "        depends_on: [P2]\n") +
		recordCyclePlan("P2", "        depends_on: [P1]\n") +
		recordCyclePlan("P3", "")
	mutated := replaceRecordPlans(t, plans)
	yamlPath := reviewTriageDir + "feat-x.yaml"
	read := func(_ string) ([]byte, error) { return []byte(mutated), nil }
	problems := reviewTriageRecordProblems([]string{yamlPath}, read)
	var hasCycle, p3InCycle bool
	for _, p := range problems {
		if strings.Contains(p, "循環") {
			hasCycle = true
			if strings.Contains(p, "P3") {
				p3InCycle = true
			}
		}
	}
	if !hasCycle {
		t.Fatalf("混在時に循環が報告されない。出た問題: %v", problems)
	}
	if p3InCycle {
		t.Fatalf("循環していない P3 が循環として報告された。出た問題: %v", problems)
	}
}

// 空・コメントのみ・空白のみの記録は「記録が空です」と報告される (EOF の生の文言にしない)。
func TestReviewTriageRecordEmptyFile(t *testing.T) {
	for _, content := range []string{"", "# コメントだけ\n", "   \n\n", "null\n", "~\n", "---\n"} {
		yamlPath := reviewTriageDir + "feat-x.yaml"
		read := func(_ string) ([]byte, error) { return []byte(content), nil }
		problems := reviewTriageRecordProblems([]string{yamlPath}, read)
		found := false
		for _, p := range problems {
			if strings.Contains(p, "記録が空です") {
				found = true
			}
		}
		if !found {
			t.Fatalf("空の記録 (%q) が「記録が空です」と報告されない。出た問題: %v", content, problems)
		}
	}
}

// --- 区切りの 2 つ目のドキュメントは検出される (2 つ目以降は読まれず消えるため)。
func TestReviewTriageRecordMultiDocument(t *testing.T) {
	mutated := validRecordYAML + "---\nruns: []\n"
	yamlPath := reviewTriageDir + "feat-x.yaml"
	read := func(_ string) ([]byte, error) { return []byte(mutated), nil }
	problems := reviewTriageRecordProblems([]string{yamlPath}, read)
	found := false
	for _, p := range problems {
		if strings.Contains(p, "ドキュメント") {
			found = true
		}
	}
	if !found {
		t.Fatalf("2 つ目のドキュメントが報告されない。出た問題: %v", problems)
	}
}

// 記録の走査は git 追跡でなくファイルシステムを見る。追跡前 (git add 前) の
// 最初の記録が検査も生成もされず素通りする穴を塞ぐため。
func TestListReviewTriageFiles(t *testing.T) {
	dir := t.TempDir()
	for _, name := range []string{"feat-x.yaml", "feat-x.md", "README.md", "README.yaml", "note.txt"} {
		if err := os.WriteFile(filepath.Join(dir, name), []byte("x"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	got, err := listReviewTriageFiles(dir, false)
	if err != nil {
		t.Fatalf("一覧に失敗: %v", err)
	}
	// README.* は記録ではない (README.md は手書きの規範、README.yaml を記録と
	// 見なすと生成器が README.md を上書きする) ので一覧に入れない。
	want := []string{
		filepath.Join(dir, "feat-x.md"),
		filepath.Join(dir, "feat-x.yaml"),
	}
	if len(got) != len(want) {
		t.Fatalf("一覧が期待と違う: got %v want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("一覧が期待と違う: got %v want %v", got, want)
		}
	}
}

// TestInReviewTriageDirNotationVariants は、置き場の表記が揺れても検査の対象が
// 変わらないことを固定する。生の文字列に "/" を足して HasPrefix で照合していた頃は、
// "." / "./rec" / "rec//" で一覧側 (path.Join が clean する) と前置が一致せず、
// 検査が 1 件も走らないまま緑になった。
func TestInReviewTriageDirNotationVariants(t *testing.T) {
	saved := reviewTriageDir
	t.Cleanup(func() { reviewTriageDir = saved })

	for _, tt := range []struct {
		dir  string
		file string
		want bool
	}{
		{"rec/", "rec/feat-x.yaml", true},
		{"rec", "rec/feat-x.yaml", true},
		{"./rec", "rec/feat-x.yaml", true},
		{"rec//", "rec/feat-x.yaml", true},
		{".", "feat-x.yaml", true},
		{"./", "feat-x.yaml", true},
		// 別ディレクトリと下位ディレクトリは対象外のまま。
		{"rec/", "rec-old/feat-x.yaml", false},
		{"rec", "rec-old/feat-x.yaml", false},
		{"rec/", "rec/sub/feat-x.yaml", false},
		{".", "rec/feat-x.yaml", false},
	} {
		reviewTriageDir = tt.dir
		if got := inReviewTriageDir(tt.file); got != tt.want {
			t.Errorf("置き場 %q で %q: inReviewTriageDir = %v, want %v",
				tt.dir, tt.file, got, tt.want)
		}
	}
}

func TestListReviewTriageFilesMissingDir(t *testing.T) {
	got, err := listReviewTriageFiles(filepath.Join(t.TempDir(), "no-such"), false)
	if got != nil || err != nil {
		t.Fatalf("無いディレクトリはスキル未導入としてスキップする (nil, nil) べき: %v, %v", got, err)
	}
}

// 置き場を明示指定したのに無いならエラーにする。指定は「そこを検査せよ」という
// 意思表示なので、記録 0 件として黙って緑を返すと、置き場を移した時点で検査が
// 無効になったことに気づけない (診断ツールの偽陰性)。
func TestListReviewTriageFilesMissingDirExplicit(t *testing.T) {
	_, err := listReviewTriageFiles(filepath.Join(t.TempDir(), "no-such"), true)
	if err == nil {
		t.Fatal("明示指定した置き場が無いのにエラーにならなかった")
	}
	if !strings.Contains(err.Error(), "-record-dir") {
		t.Fatalf("エラーにどの指定を直せばよいかが無い: %v", err)
	}
}

// -write-summary も同じ — 明示指定した置き場が無いなら、0 件生成して
// 黙って成功させない (生成されなかったことに気づけないため)。
func TestWriteReviewTriageSummariesMissingDirExplicit(t *testing.T) {
	if err := writeReviewTriageSummaries(filepath.Join(t.TempDir(), "no-such"), true); err == nil {
		t.Fatal("明示指定した置き場が無いのにエラーにならなかった")
	}
}

// ディレクトリが「無い」以外の読み取りエラー (ENOTDIR など) は握りつぶさず返す —
// 権限や I/O のエラーを「記録 0 件」= 緑に化けさせない。
func TestListReviewTriageFilesErrorReported(t *testing.T) {
	file := filepath.Join(t.TempDir(), "not-a-dir")
	if err := os.WriteFile(file, []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := listReviewTriageFiles(file, false); err == nil {
		t.Fatalf("ディレクトリでないパスの読み取りエラーが握りつぶされた")
	}
}

// README.yaml を置いても、生成器が規範文書 README.md を上書きしない。
func TestWriteReviewTriageSummariesSkipsReadme(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "README.yaml"), []byte(validRecordYAML), 0o644); err != nil {
		t.Fatal(err)
	}
	norm := "# 手書きの規範\n"
	if err := os.WriteFile(filepath.Join(dir, "README.md"), []byte(norm), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := writeReviewTriageSummaries(dir, false); err != nil {
		t.Fatalf("生成に失敗: %v", err)
	}
	got, err := os.ReadFile(filepath.Join(dir, "README.md"))
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != norm {
		t.Fatalf("README.md が上書きされた:\n%s", got)
	}
}

// 生成器はファイルシステム上のすべての記録 YAML からサマリを作る (追跡状況に依らない)。
func TestWriteReviewTriageSummaries(t *testing.T) {
	dir := t.TempDir()
	yamlPath := filepath.Join(dir, "feat-x.yaml")
	if err := os.WriteFile(yamlPath, []byte(validRecordYAML), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := writeReviewTriageSummaries(dir, false); err != nil {
		t.Fatalf("生成に失敗: %v", err)
	}
	got, err := os.ReadFile(filepath.Join(dir, "feat-x.md"))
	if err != nil {
		t.Fatalf("サマリが生成されていない: %v", err)
	}
	want, err := renderReviewTriageSummary(yamlPath, []byte(validRecordYAML))
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != want {
		t.Fatalf("生成内容が render と一致しない")
	}
}

// depends_on の循環 (P1 → P2 → P1) は検出される。循環すると修正の順序が定まらない。
func TestReviewTriageRecordDependsOnCycle(t *testing.T) {
	cyclePlans := `    plans:
      - problem_id: P1
        cause: c1
        finding_ids: [1]
        approach: a1
        depends_on: [P2]
        sha: ""
        status: pending
      - problem_id: P2
        cause: c2
        finding_ids: [1]
        approach: a2
        depends_on: [P1]
        sha: ""
        status: pending
`
	origPlans := `    plans:
      - problem_id: P1
        cause: 数えずに書いた
        finding_ids: [1]
        approach: 数え直して単位を書く
        order: 1
        sha: ""
        status: pending
`
	mutated := strings.Replace(validRecordYAML, origPlans, cyclePlans, 1)
	if mutated == validRecordYAML {
		t.Fatal("フィクスチャの置換が効いていない")
	}
	yamlPath := reviewTriageDir + "feat-x.yaml"
	read := func(_ string) ([]byte, error) { return []byte(mutated), nil }
	problems := reviewTriageRecordProblems([]string{yamlPath}, read)
	found := false
	for _, p := range problems {
		if strings.Contains(p, "循環") {
			found = true
		}
	}
	if !found {
		t.Fatalf("depends_on の循環が報告されない。出た問題: %v", problems)
	}
}

// recordCyclePlan は循環テスト用の plans 要素を組み立てる。
func recordCyclePlan(id string, deps string) string {
	return "      - problem_id: " + id + "\n" +
		"        cause: c\n        finding_ids: [1]\n        approach: a\n" +
		deps +
		"        sha: \"\"\n        status: pending\n"
}

// 間接循環 (P1 → P2 → P3 → P1) も検出される。
func TestReviewTriageRecordIndirectCycle(t *testing.T) {
	plans := "    plans:\n" +
		recordCyclePlan("P1", "        depends_on: [P2]\n") +
		recordCyclePlan("P2", "        depends_on: [P3]\n") +
		recordCyclePlan("P3", "        depends_on: [P1]\n")
	mutated := replaceRecordPlans(t, plans)
	yamlPath := reviewTriageDir + "feat-x.yaml"
	read := func(_ string) ([]byte, error) { return []byte(mutated), nil }
	problems := reviewTriageRecordProblems([]string{yamlPath}, read)
	found := false
	for _, p := range problems {
		if strings.Contains(p, "循環") && strings.Contains(p, "P3") {
			found = true
		}
	}
	if !found {
		t.Fatalf("間接循環 (3 ノード) が報告されない。出た問題: %v", problems)
	}
}

// 合流するが循環しない依存 (ダイヤモンド: P1 → P2/P3 → P4) は検出されない。
func TestReviewTriageRecordDiamondIsNotCycle(t *testing.T) {
	plans := "    plans:\n" +
		recordCyclePlan("P1", "        depends_on: [P2, P3]\n") +
		recordCyclePlan("P2", "        depends_on: [P4]\n") +
		recordCyclePlan("P3", "        depends_on: [P4]\n") +
		recordCyclePlan("P4", "")
	mutated := replaceRecordPlans(t, plans)
	yamlPath := reviewTriageDir + "feat-x.yaml"
	read := func(_ string) ([]byte, error) { return []byte(mutated), nil }
	for _, p := range reviewTriageRecordProblems([]string{yamlPath}, read) {
		if strings.Contains(p, "循環") {
			t.Fatalf("循環でないダイヤモンドの依存が循環と報告された: %v", p)
		}
	}
}

// replaceRecordPlans は validRecordYAML の plans 節を差し替える。
func replaceRecordPlans(t *testing.T, plans string) string {
	t.Helper()
	origPlans := `    plans:
      - problem_id: P1
        cause: 数えずに書いた
        finding_ids: [1]
        approach: 数え直して単位を書く
        order: 1
        sha: ""
        status: pending
`
	mutated := strings.Replace(validRecordYAML, origPlans, plans, 1)
	if mutated == validRecordYAML {
		t.Fatal("フィクスチャの plans の置換が効いていない")
	}
	return mutated
}

// 未知のキーがあっても他の検査は続く (最初の問題で止めない)。
func TestReviewTriageRecordUnknownKeyDoesNotAbort(t *testing.T) {
	mutated := strings.Replace(validRecordYAML,
		"        verdict: adopted\n",
		"        verdict: adopted\n        severity: P1\n", 1)
	mutated = strings.Replace(mutated, "verdict: held", "verdict: maybe", 1)
	yamlPath := reviewTriageDir + "feat-x.yaml"
	read := func(_ string) ([]byte, error) { return []byte(mutated), nil }
	problems := reviewTriageRecordProblems([]string{yamlPath}, read)
	var hasUnknown, hasVerdict bool
	for _, p := range problems {
		if strings.Contains(p, "severity") {
			hasUnknown = true
		}
		if strings.Contains(p, "maybe") || strings.Contains(p, "verdict") {
			hasVerdict = true
		}
	}
	if !hasUnknown || !hasVerdict {
		t.Fatalf("未知キーと列挙値違反の両方が報告されるべき。出た問題: %v", problems)
	}
}

func TestReviewTriageRecordSummaryMissing(t *testing.T) {
	yamlPath := reviewTriageDir + "feat-x.yaml"
	read := func(_ string) ([]byte, error) { return []byte(validRecordYAML), nil }
	problems := reviewTriageRecordProblems([]string{yamlPath}, read)
	found := false
	for _, p := range problems {
		if strings.Contains(p, "feat-x.md") {
			found = true
		}
	}
	if !found {
		t.Fatalf("サマリの不在が報告されない。出た問題: %v", problems)
	}
}

func TestReviewTriageRecordSummaryStale(t *testing.T) {
	files, read := recordFiles(t, validRecordYAML)
	mdPath := reviewTriageDir + "feat-x.md"
	staleRead := func(p string) ([]byte, error) {
		if p == mdPath {
			return []byte("# 古いサマリ\n"), nil
		}
		return read(p)
	}
	problems := reviewTriageRecordProblems(files, staleRead)
	found := false
	for _, p := range problems {
		if strings.Contains(p, "feat-x.md") && strings.Contains(p, "食い違っています") {
			found = true
		}
	}
	if !found {
		t.Fatalf("古いサマリが報告されない。出た問題: %v", problems)
	}
}

// 対応する yaml の無いサマリ (孤児) は報告される。README.md は対象外。
func TestReviewTriageRecordOrphanSummary(t *testing.T) {
	orphan := reviewTriageDir + "old-branch.md"
	read := func(_ string) ([]byte, error) { return []byte("# x\n"), nil }
	problems := reviewTriageRecordProblems([]string{orphan, reviewTriageDir + "README.md"}, read)
	var hasOrphan, hasReadme bool
	for _, p := range problems {
		if strings.Contains(p, "old-branch.md") {
			hasOrphan = true
		}
		if strings.Contains(p, "README.md") {
			hasReadme = true
		}
	}
	if !hasOrphan {
		t.Fatalf("孤児のサマリが報告されない。出た問題: %v", problems)
	}
	if hasReadme {
		t.Fatalf("README.md が対象になっている。出た問題: %v", problems)
	}
}

// 推移の表の件数は YAML から計算される (全件 3 / 採択 1 / 保留 1 / 却下 1)。
func TestReviewTriageSummaryCounts(t *testing.T) {
	summary, err := renderReviewTriageSummary(reviewTriageDir+"feat-x.yaml", []byte(validRecordYAML))
	if err != nil {
		t.Fatalf("サマリの生成に失敗: %v", err)
	}
	if !strings.Contains(summary, "| 3 | 1 | 1 | 1 |") {
		t.Fatalf("推移の表に計算された件数 (3/1/1/1) が無い:\n%s", summary)
	}
	if !strings.Contains(summary, "生成物") {
		t.Fatalf("生成物であることの注記が無い:\n%s", summary)
	}
	// 選択待ちの表示は awaiting-human の行があるときだけ (このフィクスチャは pending のみ)。
	if strings.Contains(summary, "選択待ち") {
		t.Fatalf("pending だけの記録に選択待ちの表示が出ている:\n%s", summary)
	}
	// gates_fired の結合表示 (真側)。
	if !strings.Contains(summary, "developer-domain") {
		t.Fatalf("gates_fired の表示が無い:\n%s", summary)
	}
	// run_id 空の見出しに括弧を付けない・depends_on 空の順序セルに接尾辞を付けない (偽側)。
	if !strings.Contains(summary, "`code-review`\n") {
		t.Fatalf("run_id 空の見出しに余計な表示が付いている:\n%s", summary)
	}
	if strings.Contains(summary, "の後)") {
		t.Fatalf("depends_on 空なのに接尾辞が出ている:\n%s", summary)
	}
}

// awaiting-human の問題は、サマリに選択待ちの明示と options (選択肢) が出る。
func TestReviewTriageSummaryAwaitingHuman(t *testing.T) {
	mutated := strings.Replace(validRecordYAML, "status: pending",
		"status: awaiting-human\n        options: 案 a は最小修正 / 案 b は構造の変更", 1)
	summary, err := renderReviewTriageSummary(reviewTriageDir+"feat-x.yaml", []byte(mutated))
	if err != nil {
		t.Fatalf("サマリの生成に失敗: %v", err)
	}
	if !strings.Contains(summary, "選択待ち") {
		t.Fatalf("awaiting-human の問題に選択待ちの表示が無い:\n%s", summary)
	}
	if !strings.Contains(summary, "案 a は最小修正") {
		t.Fatalf("options (選択肢) がサマリに出ていない:\n%s", summary)
	}
}

// done-external は sha を書けない代わりに applied_external_url か notes の
// どちらかがあれば通る。URL を必須にすると、URL を持たない対象 (ローカルの
// 外部ツール設定など) で done にできない行き詰まりが再発する。
func TestReviewTriageRecordDoneExternalPasses(t *testing.T) {
	cases := []struct {
		name string
		new  string
	}{
		{"URL だけ", "        status: done-external\n" +
			"        applied_external_url: \"https://github.com/o/r/pull/123\"\n"},
		{"notes だけ (URL を持たない対象)", "        status: done-external\n" +
			"        notes: ローカルの外部ツール設定へ反映し、再実行して反映を確認した\n"},
		{"URL と notes の両方", "        status: done-external\n" +
			"        applied_external_url: \"https://github.com/o/r/pull/123\"\n" +
			"        notes: PR 本文を書き換え、Files changed と読み比べて一致を確認した\n"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			mutated := strings.Replace(validRecordYAML,
				"        sha: \"\"\n        status: pending\n", tc.new, 1)
			if mutated == validRecordYAML {
				t.Fatal("フィクスチャの置換が効いていない")
			}
			files, read := recordFiles(t, mutated)
			if problems := reviewTriageRecordProblems(files, read); len(problems) != 0 {
				t.Fatalf("正しい done-external で問題が出た: %v", problems)
			}
		})
	}
}

// investigation は「調査済みで波及なし」(scope だけ) と「見つけた箇所あり」の
// どちらの形でも通る。無いことが未調査の表現なので、無い記録も通る (validRecordYAML)。
func TestReviewTriageRecordInvestigationPasses(t *testing.T) {
	cases := []struct {
		name string
		new  string
	}{
		{"scope だけ (波及先なし)", "order: 1\n" +
			"        investigation:\n" +
			"          scope: grep -rn '分母' . と docs/foo.md の同じ表の全行\n"},
		{"含めた箇所と含めなかった箇所", "order: 1\n" +
			"        investigation:\n" +
			"          scope: grep -rn '分母' . と docs/foo.md の同じ表の全行\n" +
			"          included: [docs/foo.md:22 の同じ表の別の行]\n" +
			"          excluded: [docs/baz.md:5 は数えていない見積りなので原因が違う]\n"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			mutated := strings.Replace(validRecordYAML, "order: 1\n", tc.new, 1)
			if mutated == validRecordYAML {
				t.Fatal("フィクスチャの置換が効いていない")
			}
			files, read := recordFiles(t, mutated)
			if problems := reviewTriageRecordProblems(files, read); len(problems) != 0 {
				t.Fatalf("正しい investigation で問題が出た: %v", problems)
			}
		})
	}
}

// 調査の範囲と結果はサマリの表の外に出る。included / excluded が両方空なら
// 「波及先なし」と明示し、無い問題には何も出さない (未調査)。
func TestReviewTriageSummaryInvestigation(t *testing.T) {
	render := func(t *testing.T, yamlSrc string) string {
		t.Helper()
		summary, err := renderReviewTriageSummary(reviewTriageDir+"feat-x.yaml", []byte(yamlSrc))
		if err != nil {
			t.Fatalf("サマリの生成に失敗: %v", err)
		}
		return summary
	}
	if summary := render(t, validRecordYAML); strings.Contains(summary, "の調査**") {
		t.Fatalf("investigation の無い問題に調査の行が出ている:\n%s", summary)
	}
	scopeOnly := strings.Replace(validRecordYAML, "order: 1\n",
		"order: 1\n        investigation:\n          scope: grep -rn '分母' .\n", 1)
	summary := render(t, scopeOnly)
	if !strings.Contains(summary, "- **P1 の調査**: 範囲: grep -rn '分母' . / 波及先なし") {
		t.Fatalf("scope だけの調査が「波及先なし」として出ていない:\n%s", summary)
	}
	withFound := strings.Replace(validRecordYAML, "order: 1\n",
		"order: 1\n        investigation:\n          scope: grep -rn '分母' .\n"+
			"          included: [\"docs/foo.md:22 | 同じ表\", docs/foo.md:30]\n"+
			"          excluded: [docs/baz.md:5 は見積り]\n", 1)
	summary = render(t, withFound)
	want := "- **P1 の調査**: 範囲: grep -rn '分母' . / 含めた: docs/foo.md:22 \\| 同じ表; docs/foo.md:30 / 含めなかった: docs/baz.md:5 は見積り"
	if !strings.Contains(summary, want) {
		t.Fatalf("%q がサマリに無い:\n%s", want, summary)
	}
	if strings.Contains(summary, "波及先なし") {
		t.Fatalf("見つけた箇所があるのに「波及先なし」が出ている:\n%s", summary)
	}
}

// 列挙外の status に done-external 専用のキーが付いていても、報告するのは
// 列挙違反の 1 件だけ。1 つの誤字を 2 つの問題に増やさない。
func TestReviewTriageRecordUnknownStatusReportsOnce(t *testing.T) {
	mutated := strings.Replace(validRecordYAML,
		"        status: pending\n",
		"        status: done-ext\n        applied_external_url: \"https://example.com/x\"\n", 1)
	if mutated == validRecordYAML {
		t.Fatal("フィクスチャの置換が効いていない")
	}
	read := func(_ string) ([]byte, error) { return []byte(mutated), nil }
	problems := reviewTriageRecordProblems([]string{reviewTriageDir + "feat-x.yaml"}, read)
	for _, p := range problems {
		if strings.Contains(p, "done-external 専用") {
			t.Fatalf("列挙外の status に排他の問題を重ねている: %v", problems)
		}
	}
}

// 修正計画の表の最終列は SHA と URL の 2 つの型を取るので、見出しは「証拠」で
// なければならない。見出しを SHA に戻すと、done-external の行の URL を SHA として
// 読ませることになる (セルを埋める側だけ直して見出しに追随しなかった型)。
func TestReviewTriageSummaryPlanEvidenceHeader(t *testing.T) {
	mutated := strings.Replace(validRecordYAML,
		"        sha: \"\"\n        status: pending\n",
		"        status: done-external\n"+
			"        applied_external_url: \"https://example.com/pr/1\"\n", 1)
	if mutated == validRecordYAML {
		t.Fatal("フィクスチャの置換が効いていない")
	}
	summary, err := renderReviewTriageSummary(reviewTriageDir+"feat-x.yaml", []byte(mutated))
	if err != nil {
		t.Fatalf("サマリの生成に失敗: %v", err)
	}
	if !strings.Contains(summary, "| 順 | 状態 | 証拠 (SHA / URL) |") {
		t.Fatalf("修正計画の表の最終列の見出しが「証拠」でない:\n%s", summary)
	}
	if strings.Contains(summary, "| 順 | 状態 | SHA |") {
		t.Fatalf("最終列の見出しが SHA のまま残っている:\n%s", summary)
	}
}

// done-external の問題は、サマリで状態がリポジトリ外と分かり、証拠の欄に
// 反映先の URL が、表の外に反映を確認した方法 (notes) が出る。
func TestReviewTriageSummaryDoneExternal(t *testing.T) {
	mutated := strings.Replace(validRecordYAML,
		"        sha: \"\"\n        status: pending\n",
		"        status: done-external\n"+
			"        applied_external_url: \"https://github.com/o/r/pull/123\"\n"+
			"        notes: PR 本文を書き換え、Files changed と読み比べて一致を確認した\n", 1)
	if mutated == validRecordYAML {
		t.Fatal("フィクスチャの置換が効いていない")
	}
	summary, err := renderReviewTriageSummary(reviewTriageDir+"feat-x.yaml", []byte(mutated))
	if err != nil {
		t.Fatalf("サマリの生成に失敗: %v", err)
	}
	for _, want := range []string{
		"済 (リポジトリ外)",
		"`https://github.com/o/r/pull/123`",
		"**P1 はリポジトリ外へ反映済み**: PR 本文を書き換え、Files changed と読み比べて一致を確認した",
	} {
		if !strings.Contains(summary, want) {
			t.Fatalf("%q がサマリに出ていない:\n%s", want, summary)
		}
	}
}

// 証拠の欄は sha が優先で、done-external では URL、どちらも無ければ「—」。
func TestRenderPlanCellsExternalEvidence(t *testing.T) {
	base := recordPlan{ProblemID: "P1", Cause: "c", FindingIDs: []int{1}, Approach: "a"}
	cases := []struct {
		name string
		plan recordPlan
		want string
	}{
		{"done-external は URL を出す", func() recordPlan {
			pl := base
			pl.Status, pl.AppliedExternalURL = "done-external", "https://example.com/pr/1"
			return pl
		}(), "`https://example.com/pr/1`"},
		{"URL の縦棒を無害化する", func() recordPlan {
			pl := base
			pl.Status, pl.AppliedExternalURL = "done-external", "https://example.com/a|b"
			return pl
		}(), `https://example.com/a\|b`},
		{"URL が無ければダッシュ", func() recordPlan {
			pl := base
			pl.Status, pl.Notes = "done-external", "反映済み"
			return pl
		}(), "—"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if cells := renderPlanCells(tc.plan); !strings.Contains(cells[6], tc.want) {
				t.Fatalf("証拠のセル = %q, want %q を含む", cells[6], tc.want)
			}
		})
	}
	pl := base
	pl.Status, pl.Notes = "done-external", "反映済み"
	if cells := renderPlanCells(pl); cells[5] != "済 (リポジトリ外)" {
		t.Fatalf("状態のセル = %q, want %q", cells[5], "済 (リポジトリ外)")
	}
}

// docs/review-triages/ の外のファイルと README.md は対象外。
func TestReviewTriageRecordIgnoresOtherFiles(t *testing.T) {
	read := func(_ string) ([]byte, error) { return []byte("x: 1\n"), nil }
	problems := reviewTriageRecordProblems([]string{
		"docs/design/00-architecture.md",
		"docs/manual/units/dependencies.yaml",
		reviewTriageDir + "README.md",
	}, read)
	if len(problems) != 0 {
		t.Fatalf("対象外のファイルで問題が出た: %v", problems)
	}
}

// 生成サマリの 1 行目は、既定のまま生成すると既定の案内を含む決まった形になる。
// 1 行目はコミットされる値なので、組み立て方の変更をここで捕まえる。可変の
// summaryCommand ではなく定数と突き合わせる (run が書き換えた後の値を既定と
// 取り違えないため)。
func TestReviewTriageSummaryFirstLineUsesDefaultCommand(t *testing.T) {
	saved := summaryCommand
	summaryCommand = defaultSummaryCommand
	t.Cleanup(func() { summaryCommand = saved })

	summary, err := renderReviewTriageSummary(reviewTriageDir+"feat-x.yaml", []byte(validRecordYAML))
	if err != nil {
		t.Fatal(err)
	}
	first, _, _ := strings.Cut(summary, "\n")
	want := "<!-- 生成物。手で編集しない。正本は feat-x.yaml — `" + defaultSummaryCommand + "` で再生成する。 -->"
	if first != want {
		t.Errorf("1 行目が既定の形ではない:\n got: %s\nwant: %s", first, want)
	}
}

// recurrenceRecordYAML は validRecordYAML に回 2 を足し、その回の直下に recurrence を
// 置いた記録を返す。検知は過去の回との比較なので、回が 2 つ無いと正しい形を書けない。
// recurrence が空文字列なら回 2 に recurrence を書かない。
func recurrenceRecordYAML(recurrence string) string {
	run2 := `  - date: "2026-08-31"
    skill: code-review
    model: sonnet-5
    scope: incremental
    head: def5678
    findings:
      - id: 1
        file: docs/foo.md
        line: 12
        summary: 同じ表の別の行の数の食い違い
        category: doc-other
        audience: developer
        consequence:
          condition: 検算するとき
          who: developer
          what: 分母を誤る
          detectability: 気づかない
        premise_check:
          stages: A
          result: verified
        verdict: adopted
        verdict_reason: ゲート 0 件で採択 (A2)
      - id: 2
        file: tools/baz_test.go
        summary: 一時ファイルの削除が雑
        category: test
        audience: developer
        consequence:
          condition: disk full のとき
          who: developer
          what: テストが落ちる
          detectability: 気づく
        premise_check:
          stages: A
          result: verified
        gates_fired: [developer-domain]
        verdict: rejected
        verdict_reason: 開発者の領域で却下 (R3)
`
	if recurrence != "" {
		run2 += "    recurrence:\n" + recurrence
	}
	return validRecordYAML + run2
}

const recurrenceEvidenceYAML = `      evidence:
        - condition: fix-derived
          finding_id: 1
          prior_run: 1
          prior: P1
          reason: 回 1 の P1 で直した表の隣の行に同じ規則を当て忘れた
`

// recurrence は detected / declined / reframed の 3 状態のどれでも通る。
// 無いことが「検知なし」の表現なので、無い記録も通る (validRecordYAML と
// recurrenceRecordYAML(""))。
func TestReviewTriageRecordRecurrencePasses(t *testing.T) {
	cases := []struct {
		name       string
		recurrence string
	}{
		{"検知なし (キーが無い)", ""},
		{"detected", "      status: detected\n" + recurrenceEvidenceYAML},
		{"declined", "      status: declined\n" + recurrenceEvidenceYAML +
			"      declined_reason: 回 1 の指摘は元から残っていた欠陥で、修正由来ではない\n"},
		{"reframed", "      status: reframed\n" + recurrenceEvidenceYAML +
			"      reframe:\n" +
			"        pattern: 表の行ごとに規則を当てている\n" +
			"        axes: 規則 × 表の行\n" +
			"        root_cause: 数え方の規則が表の外に無い\n" +
			"        fix_unit: 数え方の規則を 1 か所に書き、表の全行をそこから引く\n" +
			"        source: human\n"},
		{"same-location の根拠", "      status: detected\n" +
			"      evidence:\n" +
			"        - condition: same-location\n" +
			"          finding_id: 1\n" +
			"          prior_run: 1\n" +
			"          prior: 指摘 1\n" +
			"          reason: 回 1 の指摘 1 と同じ表を指す\n"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			files, read := recordFiles(t, recurrenceRecordYAML(tc.recurrence))
			if problems := reviewTriageRecordProblems(files, read); len(problems) != 0 {
				t.Fatalf("正しい recurrence で問題が出た: %v", problems)
			}
		})
	}
}

func TestReviewTriageRecordRecurrenceViolations(t *testing.T) {
	cases := []struct {
		name       string
		recurrence string
		want       string // 問題文に含まれるべき語
	}{
		{"status の列挙値違反", "      status: found\n" + recurrenceEvidenceYAML, "status"},
		{"status が無い", recurrenceEvidenceYAML, "status"},
		{"evidence が空", "      status: detected\n      evidence: []\n", "evidence"},
		{"evidence が無い", "      status: detected\n", "evidence"},
		{"condition の列挙値違反", "      status: detected\n" +
			strings.Replace(recurrenceEvidenceYAML, "fix-derived", "same-file", 1), "condition"},
		{"finding_id が採択でない指摘を指す", "      status: detected\n" +
			strings.Replace(recurrenceEvidenceYAML, "finding_id: 1", "finding_id: 2", 1), "採択"},
		{"finding_id が存在しない指摘を指す", "      status: detected\n" +
			strings.Replace(recurrenceEvidenceYAML, "finding_id: 1", "finding_id: 9", 1), "finding_id"},
		{"prior_run が自回以上", "      status: detected\n" +
			strings.Replace(recurrenceEvidenceYAML, "prior_run: 1", "prior_run: 2", 1), "prior_run"},
		{"prior_run が 0", "      status: detected\n" +
			strings.Replace(recurrenceEvidenceYAML, "prior_run: 1", "prior_run: 0", 1), "prior_run"},
		{"prior_run が直前でない回を指す", "      status: detected\n" +
			strings.Replace(recurrenceEvidenceYAML, "prior_run: 1", "prior_run: 0", 1), "直前の回"},
		{"prior が無い", "      status: detected\n" +
			strings.Replace(recurrenceEvidenceYAML, "          prior: P1\n", "", 1), "prior"},
		{"reason が無い", "      status: detected\n" +
			strings.Replace(recurrenceEvidenceYAML, "          reason: 回 1 の P1 で直した表の隣の行に同じ規則を当て忘れた\n", "", 1), "reason"},
		{"declined なのに declined_reason が無い", "      status: declined\n" + recurrenceEvidenceYAML, "declined_reason"},
		{"detected なのに declined_reason がある", "      status: detected\n" + recurrenceEvidenceYAML +
			"      declined_reason: 違う\n", "declined_reason"},
		{"reframed なのに reframe が無い", "      status: reframed\n" + recurrenceEvidenceYAML, "reframe"},
		{"reframe の項目が無い", "      status: reframed\n" + recurrenceEvidenceYAML +
			"      reframe:\n        pattern: 表の行ごと\n        axes: 規則 × 行\n        root_cause: 規則が外に無い\n        source: human\n", "fix_unit"},
		{"reframe.source の列挙値違反", "      status: reframed\n" + recurrenceEvidenceYAML +
			"      reframe:\n        pattern: 表の行ごと\n        axes: 規則 × 行\n        root_cause: 規則が外に無い\n        fix_unit: 規則を 1 か所に\n        source: claude\n", "source"},
		{"detected なのに reframe がある", "      status: detected\n" + recurrenceEvidenceYAML +
			"      reframe:\n        pattern: 表の行ごと\n        axes: 規則 × 行\n        root_cause: 規則が外に無い\n        fix_unit: 規則を 1 か所に\n        source: human\n", "reframe"},
		{"declined なのに reframe がある", "      status: declined\n" + recurrenceEvidenceYAML +
			"      declined_reason: 回 1 の指摘は元から残っていた欠陥で、修正由来ではない\n" +
			"      reframe:\n        pattern: 表の行ごと\n        axes: 規則 × 行\n        root_cause: 規則が外に無い\n        fix_unit: 規則を 1 か所に\n        source: human\n", "reframe"},
		{"fix-derived の prior が比べた回の plans に無い", "      status: detected\n" +
			strings.Replace(recurrenceEvidenceYAML, "prior: P1", "prior: P9", 1), "plans"},
		{"fix-derived の prior が捉え直しなのに比べた回は reframed でない", "      status: detected\n" +
			strings.Replace(recurrenceEvidenceYAML, "prior: P1", "prior: 捉え直し", 1), "plans"},
		{"recurrence の未知のキー", "      status: detected\n" + recurrenceEvidenceYAML + "      fired: true\n", "fired"},
		{"evidence の未知のキー", "      status: detected\n" +
			strings.Replace(recurrenceEvidenceYAML, "          prior: P1\n", "          prior: P1\n          where: docs/foo.md\n", 1), "where"},
		{"reframe の未知のキー", "      status: reframed\n" + recurrenceEvidenceYAML +
			"      reframe:\n        pattern: 表の行ごと\n        axes: 規則 × 行\n        root_cause: 規則が外に無い\n        fix_unit: 規則を 1 か所に\n        source: human\n        table: x\n", "table"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			yamlSrc := recurrenceRecordYAML(tc.recurrence)
			yamlPath := reviewTriageDir + "feat-x.yaml"
			read := func(_ string) ([]byte, error) { return []byte(yamlSrc), nil }
			problems := reviewTriageRecordProblems([]string{yamlPath}, read)
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

// recurrenceReframedThenRecordYAML は recurrenceRecordYAML の回 2 を reframed にして
// 回 3 を足し、回 3 の recurrence に引数を置いた記録を返す。fix-derived の prior が
// 「捉え直し」を指せるのは、比べた回が捉え直し済み (reframed) のときだけなので、
// その形を書くには捉え直した回とそれを比べる回の 2 つが要る。回 2 は最後の回で
// なくなるので、採択 (指摘 1) を覆う plans も足す。
func recurrenceReframedThenRecordYAML(recurrence string) string {
	run2 := recurrenceRecordYAML("      status: reframed\n" + recurrenceEvidenceYAML +
		"      reframe:\n" +
		"        pattern: 表の行ごとに規則を当てている\n" +
		"        axes: 規則 × 表の行\n" +
		"        root_cause: 数え方の規則が表の外に無い\n" +
		"        fix_unit: 数え方の規則を 1 か所に書き、表の全行をそこから引く\n" +
		"        source: human\n")
	run2 += `    plans:
      - problem_id: P2
        cause: 表の外に規則が無い
        finding_ids: [1]
        approach: 規則を 1 か所に書く
        order: 1
        sha: ""
        status: pending
`
	run3 := `  - date: "2026-09-01"
    skill: code-review
    model: sonnet-5
    scope: incremental
    head: 0123abc
    findings:
      - id: 1
        file: docs/foo.md
        line: 30
        summary: 規則を 1 か所に寄せた後も別の表が旧規則のまま
        category: doc-other
        audience: developer
        consequence:
          condition: 検算するとき
          who: developer
          what: 分母を誤る
          detectability: 気づかない
        premise_check:
          stages: A
          result: verified
        verdict: adopted
        verdict_reason: ゲート 0 件で採択 (A2)
    recurrence:
` + recurrence
	return run2 + run3
}

// fix-derived の prior は、比べた回の plans の問題の識別子か、比べた回が
// reframed のときの「捉え直し」のどちらか。
// 捉え直し済み (reframed) の回に plans がまだ無くても、次の回の fix-derived の根拠は
// prior: 捉え直し で通る — recurrence-detection.md「直前の回の状態と主の条件」の
// 捉え直し済みの行 (plans の有無を問わない) を固定する。実装済みの挙動の回帰テスト。
// reframing.md の「記録に書いてから束ねに進む」の直後は、この状態が普通に起きる。
func TestReviewTriageRecordRecurrencePriorReframedWithoutPlans(t *testing.T) {
	yamlSrc := recurrenceReframedThenRecordYAML("      status: detected\n" +
		"      evidence:\n" +
		"        - condition: fix-derived\n" +
		"          finding_id: 1\n" +
		"          prior_run: 2\n" +
		"          prior: 捉え直し\n" +
		"          reason: 回 2 の捉え直しで寄せた規則を別の表に当て忘れた\n")
	// 回 2 の plans を外す。回 2 の採択は最後の回ではないので、回 3 の問題で覆う。
	plans := "    plans:\n" +
		"      - problem_id: P2\n" +
		"        cause: 表の外に規則が無い\n" +
		"        finding_ids: [1]\n" +
		"        approach: 規則を 1 か所に書く\n" +
		"        order: 1\n" +
		"        sha: \"\"\n" +
		"        status: pending\n"
	if !strings.Contains(yamlSrc, plans) {
		t.Fatal("fixture に回 2 の plans が見つからない (fixture が変わった)")
	}
	yamlSrc = strings.Replace(yamlSrc, plans, "", 1)
	// 回 2 の指摘 1 に plan_ref を足す。同じ文面の指摘は回 1 (validRecordYAML) にもあるので、
	// 回 2 の recurrence より前で最後に現れる箇所を選ぶ。
	marker := "        verdict_reason: ゲート 0 件で採択 (A2)\n      - id: 2\n"
	recIdx := strings.Index(yamlSrc, "    recurrence:\n      status: reframed")
	if recIdx < 0 {
		t.Fatal("fixture に回 2 の recurrence が見つからない (fixture が変わった)")
	}
	head := yamlSrc[:recIdx]
	mIdx := strings.LastIndex(head, marker)
	if mIdx < 0 {
		t.Fatal("fixture に回 2 の指摘 1 の終わりが見つからない (fixture が変わった)")
	}
	yamlSrc = head[:mIdx] +
		"        verdict_reason: ゲート 0 件で採択 (A2)\n        plan_ref:\n          run: 3\n          problem: P3\n      - id: 2\n" +
		head[mIdx+len(marker):] + yamlSrc[recIdx:]
	yamlSrc += "    plans:\n" +
		"      - problem_id: P3\n" +
		"        cause: 表の外に規則が無い (回 2 の指摘 1 も同じ原因で束ねる)\n" +
		"        finding_ids: [1]\n" +
		"        approach: 規則を 1 か所に書き、回 2 の指摘 1 もここで直す\n" +
		"        order: 1\n" +
		"        sha: \"\"\n" +
		"        status: pending\n"
	files, read := recordFiles(t, yamlSrc)
	if problems := reviewTriageRecordProblems(files, read); len(problems) != 0 {
		t.Fatalf("plans の無い捉え直し済みの回を指す prior 捉え直し で問題が出た: %v", problems)
	}
}

// 回 1 に recurrence を書いた記録は、比べる過去の回が無いので専用の文で弾く —
// recurrence-detection.md「過去の回が無い記録では判断しない」。範囲の検査の副作用
// (直前の回が 0) で弾くと「直前の回 (0)」という読めない文になる。
func TestReviewTriageRecordRecurrenceOnFirstRun(t *testing.T) {
	yamlSrc := validRecordYAML + "    recurrence:\n      status: detected\n" + recurrenceEvidenceYAML
	files, read := recordFiles(t, yamlSrc)
	problems := reviewTriageRecordProblems(files, read)
	if len(problems) != 1 || !strings.Contains(problems[0], "回 1 の recurrence") || !strings.Contains(problems[0], "過去の回が無い") {
		t.Fatalf("回 1 の recurrence が専用の 1 件で報告されない: %v", problems)
	}
}

// 直前でない回を指す根拠は弾く — 比べる相手は直前の 1 回 (recurrence-detection.md)。
// 3 回の記録で、回 3 の根拠が回 1 を指す形。
func TestReviewTriageRecordRecurrencePriorRunNotPrevious(t *testing.T) {
	yamlSrc := recurrenceReframedThenRecordYAML("      status: detected\n" +
		"      evidence:\n" +
		"        - condition: fix-derived\n" +
		"          finding_id: 1\n" +
		"          prior_run: 1\n" +
		"          prior: P1\n" +
		"          reason: 回 1 の P1 の修正由来\n")
	files, read := recordFiles(t, yamlSrc)
	problems := reviewTriageRecordProblems(files, read)
	found := false
	for _, pr := range problems {
		if strings.Contains(pr, "prior_run 1") && strings.Contains(pr, "直前の回") {
			found = true
		}
	}
	if !found {
		t.Fatalf("直前でない回 (回 3 から回 1) を指す prior_run が報告されない: %v", problems)
	}
}

// 比べた回が捉え直し済み (reframed) なら、fix-derived の prior は 捉え直し と書く —
// 表の捉え直し済みの行。問題の識別子で指す根拠は、正本と食い違うので弾く。
func TestReviewTriageRecordRecurrencePriorReframedRunRequiresReframeMarker(t *testing.T) {
	yamlSrc := recurrenceReframedThenRecordYAML("      status: detected\n" +
		"      evidence:\n" +
		"        - condition: fix-derived\n" +
		"          finding_id: 1\n" +
		"          prior_run: 2\n" +
		"          prior: P2\n" +
		"          reason: 回 2 の P2 の修正由来\n")
	files, read := recordFiles(t, yamlSrc)
	problems := reviewTriageRecordProblems(files, read)
	found := false
	for _, pr := range problems {
		if strings.Contains(pr, "捉え直し") && strings.Contains(pr, `"P2"`) {
			found = true
		}
	}
	if !found {
		t.Fatalf("捉え直し済みの回を問題の識別子で指す根拠が報告されない: %v", problems)
	}
}

func TestReviewTriageRecordRecurrencePriorReframed(t *testing.T) {
	yamlSrc := recurrenceReframedThenRecordYAML("      status: detected\n" +
		"      evidence:\n" +
		"        - condition: fix-derived\n" +
		"          finding_id: 1\n" +
		"          prior_run: 2\n" +
		"          prior: 捉え直し\n" +
		"          reason: 回 2 の捉え直しで寄せた規則を別の表に当て忘れた\n")
	files, read := recordFiles(t, yamlSrc)
	if problems := reviewTriageRecordProblems(files, read); len(problems) != 0 {
		t.Fatalf("捉え直し済みの回を指す prior 捉え直し で問題が出た: %v", problems)
	}
}

// キーだけ書いて値を省いた recurrence (null) は「無い」と同一に扱われて黙る。
// 書きかけの検知を「検知なし」に化けさせないため報告する (investigation と同じ)。
func TestReviewTriageRecordRecurrenceNull(t *testing.T) {
	yamlSrc := strings.Replace(recurrenceRecordYAML("      status: detected\n"),
		"    recurrence:\n      status: detected\n", "    recurrence:\n", 1)
	files, read := recordFiles(t, yamlSrc)
	problems := reviewTriageRecordProblems(files, read)
	if len(problems) != 1 || !strings.Contains(problems[0], "recurrence に値がありません") {
		t.Fatalf("recurrence の null が 1 件の問題として報告されない: %v", problems)
	}
}

// 検知の小節は回ごとの節の中、指摘の表の後に出る。無い回には出さない。
// 自由文字列の縦棒は recordCell で無害化する。
func TestReviewTriageSummaryRecurrence(t *testing.T) {
	render := func(t *testing.T, yamlSrc string) string {
		t.Helper()
		summary, err := renderReviewTriageSummary(reviewTriageDir+"feat-x.yaml", []byte(yamlSrc))
		if err != nil {
			t.Fatalf("サマリの生成に失敗: %v", err)
		}
		return summary
	}
	if summary := render(t, recurrenceRecordYAML("")); strings.Contains(summary, "### 検知") {
		t.Fatalf("recurrence の無い回に検知の小節が出ている:\n%s", summary)
	}

	detected := render(t, recurrenceRecordYAML("      status: detected\n"+
		"      evidence:\n"+
		"        - condition: fix-derived\n"+
		"          finding_id: 1\n"+
		"          prior_run: 1\n"+
		"          prior: \"P1 | 別\"\n"+
		"          reason: \"隣の行 | に当て忘れた\"\n"))
	for _, want := range []string{
		"\n### 検知\n\n- 状態: 検知済み・未処理\n",
		"- 根拠: 修正由来の指摘 (fix-derived) — 指摘 #1 と回 1 の P1 \\| 別: 隣の行 \\| に当て忘れた\n",
	} {
		if !strings.Contains(detected, want) {
			t.Fatalf("%q がサマリに無い:\n%s", want, detected)
		}
	}
	// 小節の位置: 指摘の表の後、観察の前。
	if strings.Index(detected, "### 検知") < strings.Index(detected, "| 2 | `tools/baz_test.go`") {
		t.Fatalf("検知の小節が指摘の表より前に出ている:\n%s", detected)
	}
	if strings.Contains(detected, "判断した理由") || strings.Contains(detected, "捉え直し:") {
		t.Fatalf("detected なのに declined / reframed の行が出ている:\n%s", detected)
	}

	declined := render(t, recurrenceRecordYAML("      status: declined\n"+recurrenceEvidenceYAML+
		"      declined_reason: \"元から | 残っていた欠陥\"\n"))
	for _, want := range []string{
		"- 状態: 繰り返しではないと判断\n",
		"- 判断した理由: 元から \\| 残っていた欠陥\n",
	} {
		if !strings.Contains(declined, want) {
			t.Fatalf("%q がサマリに無い:\n%s", want, declined)
		}
	}

	reframed := render(t, recurrenceRecordYAML("      status: reframed\n"+
		"      evidence:\n"+
		"        - condition: same-location\n"+
		"          finding_id: 1\n"+
		"          prior_run: 1\n"+
		"          prior: 指摘 1\n"+
		"          reason: 同じ表を指す\n"+
		"      reframe:\n"+
		"        pattern: \"行ごと | の規則\"\n"+
		"        axes: 規則 × 行\n"+
		"        root_cause: 規則が表の外に無い\n"+
		"        fix_unit: 規則を 1 か所に書く\n"+
		"        source: skill\n"))
	for _, want := range []string{
		"- 状態: 捉え直し済み\n",
		"- 根拠: 同じ場所への採択 (same-location) — 指摘 #1 と回 1 の 指摘 1: 同じ表を指す\n",
		"- 捉え直し: 型 行ごと \\| の規則 / 軸 規則 × 行 / 根本の原因 規則が表の外に無い / 修正の単位 規則を 1 か所に書く / 出所 スキルの見立て (skill)\n",
	} {
		if !strings.Contains(reframed, want) {
			t.Fatalf("%q がサマリに無い:\n%s", want, reframed)
		}
	}
}
