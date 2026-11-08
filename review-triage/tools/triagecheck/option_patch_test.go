package main

import (
	"strings"
	"testing"
)

// optionPatchP1 は、optionRecordYAML の問題 P1 の案 A のパッチ。
const optionPatchP1 = "              diff --git a/docs/manual.md b/docs/manual.md\n" +
	"              index 9804839..4e231ad 100644\n" +
	"              --- a/docs/manual.md\n" +
	"              +++ b/docs/manual.md\n" +
	"              @@ -1,4 +1,4 @@\n" +
	"               ## 再開\n" +
	"               中断した作業は、記録を読んで続ける。\n" +
	"               記録の状態から、どのフェーズから続けるかが決まる。\n" +
	"              -再開のときは、調査からやり直す。\n" +
	"              +再開のときに続けるフェーズは、上の手順のとおり。\n"

// optionRecordYAML は、判断待ちの 2 つの問題を持つ記録。P1 の案 A はパッチ、案 B はファイルを変えない案で、
// P2 の案 A は P1 の案 A のパッチで覆う。様式は record-schema.md の「案のパッチ」の例と同じ。
const optionRecordYAML = `runs:
  - date: "2026-11-08"
    skill: code-review
    model: sonnet-5
    scope: incremental
    head: 3dfff27
    findings:
      - id: 1
        file: docs/manual.md
        line: 4
        summary: 再開の説明が手順と矛盾する
        category: doc-other
        audience: developer
        consequence:
          condition: 中断した作業を再開するとき
          who: developer
          what: 調査からやり直す
          detectability: 気づかない
        premise_check:
          stages: A
          result: verified
        verdict: adopted
        verdict_reason: ゲート 0 件で採択 (A2)
      - id: 2
        file: docs/guide.md
        line: 9
        summary: 再開の説明が手順と矛盾する
        category: doc-other
        audience: developer
        consequence:
          condition: 中断した作業を再開するとき
          who: developer
          what: 調査からやり直す
          detectability: 気づかない
        premise_check:
          stages: A
          result: verified
        verdict: adopted
        verdict_reason: ゲート 0 件で採択 (A2)
    plans:
      - problem_id: P1
        cause: 再開の手順を変えたとき、説明を読み直さなかった
        finding_ids: [1]
        options: |
          A (推奨): 再開の説明を、上の手順への参照に書き換える
          B: 直さない
        option_patches:
          - option: A
            base: 3dfff27
            patch: |
` + optionPatchP1 + `          - option: B
            no_change: true
        status: awaiting-human
      - problem_id: P2
        cause: 再開の説明を、別の文書にもコピーした
        finding_ids: [2]
        options: |
          A: P1 の案 A の修正で、この問題も直る
        option_patches:
          - option: A
            covered_by:
              problem_id: P1
              option: A
        status: awaiting-human
`

// optionP1Pending は、P1 に人間の回答 (案 A) を反映した後の、立案の結果と状態。
const optionP1Pending = "        approach: 案 A のとおり、再開の説明を上の手順への参照に書き換える\n" +
	"        chosen_option: A\n" +
	"        decision:\n" +
	"          target: docs/manual.md の 4 行目\n" +
	"          baseline: 上の手順\n" +
	"          choice: baseline\n" +
	"          choice_reason: 手順は実装と一致している\n"

// optionP1NotFixed は、P1 に「決めない」の回答を反映した後の立案の結果。chosen が空でなければ chosen_option も書く。
func optionP1NotFixed(chosen string) string {
	c := ""
	if chosen != "" {
		c = "        chosen_option: " + chosen + "\n"
	}
	return c + "        decision:\n" +
		"          target: docs/manual.md の 4 行目\n" +
		"          baseline: 上の手順\n" +
		"          choice: undecided\n" +
		"          choice_reason: 今回は直さない\n"
}

// awaitingOptionsYAML は、判断待ちの問題に書く最小の options と option_patches (案 1 つで、ファイルを変えない)。
// 選択待ちの問題を使うほかのテストのフィクスチャが使う。
const awaitingOptionsYAML = "        options: |\n" +
	"          A: 直さない\n" +
	"        option_patches:\n" +
	"          - option: A\n" +
	"            no_change: true\n"

// optionReplace は src の old を new に置き換える。置き換えが適用されなければ、テストを失敗として終える (t.Fatalf)。
func optionReplace(t *testing.T, src, old, new string) string {
	t.Helper()
	if !strings.Contains(src, old) {
		t.Fatalf("フィクスチャの置換が適用されていない: %q", old)
	}
	return strings.Replace(src, old, new, 1)
}

// optionPatchProblems は記録 1 つの問題を返す。サマリを渡していないので、サマリが無いという問題は除く。
func optionPatchProblems(src string) []string {
	read := func(_ string) ([]byte, error) { return []byte(src), nil }
	var got []string
	for _, p := range reviewTriageRecordProblems([]string{reviewTriageDir + "feat-x.yaml"}, read) {
		if !strings.Contains(p, "サマリ") {
			got = append(got, p)
		}
	}
	return got
}

func TestReviewTriageRecordOptionPatchesPass(t *testing.T) {
	cases := []struct {
		name string
		src  func(t *testing.T) string
	}{
		{"判断待ちの 2 つの問題", func(t *testing.T) string { return optionRecordYAML }},
		{"options の空の行は数えない", func(t *testing.T) string {
			return optionReplace(t, optionRecordYAML, "          B: 直さない\n", "\n          B: 直さない\n")
		}},
		{"人間の回答の後 (pending と chosen_option)", func(t *testing.T) string {
			return optionReplace(t, optionRecordYAML, "            no_change: true\n        status: awaiting-human\n",
				"            no_change: true\n"+optionP1Pending+"        status: pending\n")
		}},
		{"直した後 (done と chosen_option)", func(t *testing.T) string {
			return optionReplace(t, optionRecordYAML, "            no_change: true\n        status: awaiting-human\n",
				"            no_change: true\n"+optionP1Pending+"        sha: 1a2b3c4\n        status: done\n")
		}},
		{"covered_by の要素を選んだ pending", func(t *testing.T) string {
			src := optionReplace(t, optionRecordYAML, "            no_change: true\n        status: awaiting-human\n",
				"            no_change: true\n"+optionP1Pending+"        status: pending\n")
			return optionReplace(t, src, "              option: A\n        status: awaiting-human\n",
				"              option: A\n        approach: P1 の案 A の修正で直す\n        chosen_option: A\n"+
					"        decision:\n          target: docs/guide.md の 9 行目\n          baseline: 上の手順\n"+
					"          choice: baseline\n          choice_reason: 手順は実装と一致している\n        status: pending\n")
		}},
		{"決めないと回答し、ファイルを変えない案を選んだ (not-fixed と chosen_option)", func(t *testing.T) string {
			return optionReplace(t, optionRecordYAML, "            no_change: true\n        status: awaiting-human\n",
				"            no_change: true\n"+optionP1NotFixed("B")+"        status: not-fixed\n")
		}},
		{"案を選ばずに決めないと回答した (not-fixed で chosen_option 無し)", func(t *testing.T) string {
			return optionReplace(t, optionRecordYAML, "            no_change: true\n        status: awaiting-human\n",
				"            no_change: true\n"+optionP1NotFixed("")+"        status: not-fixed\n")
		}},
		{"option_patches の無い pending の自由な書き方の options", func(t *testing.T) string {
			// 過去の記録の pending に残る options は、ラベルで始まらなくても報告しない (書き換えられないため)。
			return optionReplace(t, validRecordYAML, "        status: pending\n",
				"        options: 案 a は最小修正 / 案 b は構造の変更\n        status: pending\n")
		}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			files, read := recordFiles(t, tc.src(t))
			if problems := reviewTriageRecordProblems(files, read); len(problems) != 0 {
				t.Fatalf("問題が出た: %v", problems)
			}
		})
	}
}

func TestReviewTriageRecordOptionPatchesViolations(t *testing.T) {
	const p1Tail = "            no_change: true\n        status: awaiting-human\n"
	cases := []struct {
		name     string
		old, new string
		want     string
	}{
		{"options の行がラベルで始まらない", "          B: 直さない\n", "          B: 直さない\n          説明の続き\n", "options の 3 行目がラベルで始まっていません"},
		{"ラベルの後に区切りが無い", "          B: 直さない\n", "          B直さない\n", "options の 2 行目がラベルで始まっていません"},
		{"C の立案待ちの 1 行だけの options",
			"        options: |\n          A: P1 の案 A の修正で、この問題も直る\n        option_patches:\n          - option: A\n            covered_by:\n              problem_id: P1\n              option: A\n",
			"        options: \"立案者 C: 人間が立案する。案を会話で伝える\"\n",
			"options の 1 行目がラベルで始まっていません"},
		{"options のラベルの重複", "          B: 直さない\n", "          B: 直さない\n          A: 消す\n", "options にラベル \"A\" の行が 2 つあります"},
		{"option_patches の option の重複", p1Tail, "            no_change: true\n          - option: B\n            no_change: true\n        status: awaiting-human\n", "option_patches に option \"B\" の要素が 2 つあります"},
		{"option が options に無い", "          - option: B\n", "          - option: C\n", "option \"C\" は options のどの行の先頭にもありません"},
		{"option が無い", "          - option: B\n            no_change: true\n", "          - no_change: true\n", "option_patches[1]: option がありません"},
		{"patch・no_change・covered_by のどれも無い", p1Tail, "        status: awaiting-human\n", "patch・no_change・covered_by のどれか 1 つだけを書く (2 つ以上か、どれも無い)"},
		{"patch と no_change の両方がある", "            base: 3dfff27\n", "            base: 3dfff27\n            no_change: true\n", "patch・no_change・covered_by のどれか 1 つだけを書く"},
		{"patch があるのに base が無い", "            base: 3dfff27\n", "", "base がありません"},
		{"patch が diff --git で始まらない", "              diff --git a/docs/manual.md b/docs/manual.md\n", "", "patch が diff --git で始まっていません"},
		{"patch の末尾に改行が無い", "            patch: |\n", "            patch: |-\n", "patch の末尾に改行がありません"},
		{"patch が無いのに base がある", p1Tail, "            no_change: true\n            base: 3dfff27\n        status: awaiting-human\n", "patch が無い要素に base があります"},
		{"no_change が false", p1Tail, "            no_change: false\n        status: awaiting-human\n", "no_change は true だけを書く"},
		{"covered_by の問題が無い", "              problem_id: P1\n", "              problem_id: P9\n", "covered_by の問題 \"P9\" は同じ回の plans にありません"},
		{"covered_by の案が無い", "              problem_id: P1\n              option: A\n", "              problem_id: P1\n              option: C\n", "covered_by の案 \"C\" は、問題 P1 の option_patches にありません"},
		{"covered_by がパッチの無い要素を指す", "              problem_id: P1\n              option: A\n", "              problem_id: P1\n              option: B\n", "covered_by が指す P1 の案 \"B\" は、パッチを持つ要素ではありません"},
		{"covered_by が自分の問題を指す", "              problem_id: P1\n", "              problem_id: P2\n", "covered_by が自分の問題を指しています"},
		{"covered_by の option が無い", "              problem_id: P1\n              option: A\n", "              problem_id: P1\n", "covered_by.option がありません"},
		{"判断待ちで案の要素が無い", "          - option: B\n            no_change: true\n", "", "案 \"B\" の要素が option_patches にありません"},
		{"判断待ちで option_patches が無い", "        option_patches:\n          - option: A\n            covered_by:\n              problem_id: P1\n              option: A\n", "", "案 \"A\" の要素が option_patches にありません"},
		{"chosen_option が option_patches に無い", p1Tail, "            no_change: true\n" + strings.Replace(optionP1Pending, "chosen_option: A", "chosen_option: C", 1) + "        status: pending\n", "chosen_option \"C\" は option_patches のどの要素の option でもありません"},
		{"判断待ちに chosen_option がある", p1Tail, "            no_change: true\n        chosen_option: A\n        status: awaiting-human\n", "判断待ち (awaiting-human) に chosen_option があります"},
		{"covered_by の案を選んだのに、参照先の問題が同じ案を選んでいない", "              option: A\n        status: awaiting-human\n",
			"              option: A\n        approach: P1 の案 A の修正で直す\n        chosen_option: A\n" +
				"        decision:\n          target: docs/guide.md の 9 行目\n          baseline: 上の手順\n" +
				"          choice: baseline\n          choice_reason: 手順は実装と一致している\n        status: pending\n",
			"chosen_option \"A\" は P1 の案 \"A\" のパッチで覆う案なのに、P1 の chosen_option が \"\" です"},
		{"covered_by の案を選んで直したのに、参照先の問題が同じ案を選んでいない", "              option: A\n        status: awaiting-human\n",
			"              option: A\n        approach: P1 の案 A の修正で直す\n        chosen_option: A\n" +
				"        decision:\n          target: docs/guide.md の 9 行目\n          baseline: 上の手順\n" +
				"          choice: baseline\n          choice_reason: 手順は実装と一致している\n        sha: 1a2b3c4\n        status: done\n",
			"chosen_option \"A\" は P1 の案 \"A\" のパッチで覆う案なのに、P1 の chosen_option が \"\" です"},
		{"案を選んで pending にしたのに chosen_option が無い", p1Tail, "            no_change: true\n" + strings.Replace(optionP1Pending, "        chosen_option: A\n", "", 1) + "        status: pending\n", "status pending で option_patches があるのに、chosen_option がありません"},
		{"直した問題に chosen_option が無い", p1Tail, "            no_change: true\n" + strings.Replace(optionP1Pending, "        chosen_option: A\n", "", 1) + "        sha: 1a2b3c4\n        status: done\n", "status done で option_patches があるのに、chosen_option がありません"},
		{"決めないと回答したのに chosen_option がファイルを変える案を指す", p1Tail, "            no_change: true\n" + optionP1NotFixed("A") + "        status: not-fixed\n", "status not-fixed なのに、chosen_option \"A\" はファイルを変える案です"},
		{"pending の chosen_option がファイルを変えない案を指す", p1Tail, "            no_change: true\n" + strings.Replace(optionP1Pending, "chosen_option: A", "chosen_option: B", 1) + "        status: pending\n", "chosen_option \"B\" はファイルを変えない案 (no_change) です"},
		{"option_patches の値が無い (null)", "        option_patches:\n          - option: A\n            covered_by:\n              problem_id: P1\n              option: A\n", "        option_patches:\n", "option_patches に値がありません"},
		{"covered_by の値が無い (null)", "            covered_by:\n              problem_id: P1\n              option: A\n", "            covered_by:\n", "covered_by に値がありません"},
		{"案のパッチの未知のキー", "            base: 3dfff27\n", "            base: 3dfff27\n            sha: 3dfff27\n", "案のパッチに未知のキー \"sha\""},
		{"パッチの参照の未知のキー", "              option: A\n        status", "              option: A\n              run: 1\n        status", "パッチの参照に未知のキー \"run\""},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			problems := optionPatchProblems(optionReplace(t, optionRecordYAML, tc.old, tc.new))
			found := false
			for _, p := range problems {
				found = found || strings.Contains(p, tc.want)
			}
			if !found {
				t.Fatalf("%q を含む問題が出ない。出た問題: %v", tc.want, problems)
			}
		})
	}
}

// 生成サマリには、option_patches を持つ問題ごとに小節「#### <問題> の案」が出る。案ごとに options の行と、
// パッチ (diff のコードブロック)・ファイルを変えないこと・覆う参照のどれかを出す。
func TestReviewTriageSummaryOptionPatches(t *testing.T) {
	summary, err := renderReviewTriageSummary(reviewTriageDir+"feat-x.yaml", []byte(optionRecordYAML))
	if err != nil {
		t.Fatalf("サマリの生成に失敗: %v", err)
	}
	patch := strings.ReplaceAll(optionPatchP1, "              ", "")
	for _, want := range []string{
		"\n#### P1 の案\n\nA (推奨): 再開の説明を、上の手順への参照に書き換える\n\nパッチ (起点 `3dfff27`):\n\n```diff\n" + patch + "```\n\nB: 直さない\n\nファイルを変えない。\n",
		"\n#### P2 の案\n\nA: P1 の案 A の修正で、この問題も直る\n\nP1 の案 A のパッチで覆う。\n",
	} {
		if !strings.Contains(summary, want) {
			t.Fatalf("生成サマリに %q が無い:\n%s", want, summary)
		}
	}
	if strings.Contains(summary, "選んだ案") {
		t.Fatalf("chosen_option の無い記録に選んだ案が出ている:\n%s", summary)
	}
	// 既存の選択待ちの行は変えない (既存のサマリを古くしないため)。
	if !strings.Contains(summary, "- **P1 は選択待ち (人間が選ぶ)**: A (推奨): 再開の説明を、上の手順への参照に書き換える B: 直さない\n") {
		t.Fatalf("選択待ちの行が変わっている:\n%s", summary)
	}
}

// 人間の回答の後は、小節の最初に選んだ案が出る。
func TestReviewTriageSummaryChosenOption(t *testing.T) {
	src := optionReplace(t, optionRecordYAML, "            no_change: true\n        status: awaiting-human\n",
		"            no_change: true\n"+optionP1Pending+"        status: pending\n")
	summary, err := renderReviewTriageSummary(reviewTriageDir+"feat-x.yaml", []byte(src))
	if err != nil {
		t.Fatalf("サマリの生成に失敗: %v", err)
	}
	if !strings.Contains(summary, "\n#### P1 の案\n\n選んだ案: A\n\nA (推奨): ") {
		t.Fatalf("選んだ案が小節の最初に出ていない:\n%s", summary)
	}
}

// パッチが Markdown のコードブロックを含んでも崩れないように、囲みのバッククォートは、パッチの中で最も長く
// 続くバッククォートより 1 つ多くする。
func TestReviewTriageSummaryOptionPatchFence(t *testing.T) {
	src := optionReplace(t, optionRecordYAML, "              +再開のときに続けるフェーズは、上の手順のとおり。\n",
		"              +再開のときに続けるフェーズは、上の手順のとおり。\n              +````sh\n              +make resume\n              +````\n")
	summary, err := renderReviewTriageSummary(reviewTriageDir+"feat-x.yaml", []byte(src))
	if err != nil {
		t.Fatalf("サマリの生成に失敗: %v", err)
	}
	if !strings.Contains(summary, "\n`````diff\ndiff --git") || !strings.Contains(summary, "+````\n`````\n") {
		t.Fatalf("囲みのバッククォートが 5 つになっていない:\n%s", summary)
	}
}

// option_patches の無い記録には、案の小節が出ない (既存のサマリの出力を変えないため)。
func TestReviewTriageSummaryNoOptionPatches(t *testing.T) {
	src := optionReplace(t, validRecordYAML, "status: pending", "status: awaiting-human\n        options: 案 a / 案 b")
	summary, err := renderReviewTriageSummary(reviewTriageDir+"feat-x.yaml", []byte(src))
	if err != nil {
		t.Fatalf("サマリの生成に失敗: %v", err)
	}
	if strings.Contains(summary, "の案\n") {
		t.Fatalf("option_patches の無い記録に案の小節が出ている:\n%s", summary)
	}
}
