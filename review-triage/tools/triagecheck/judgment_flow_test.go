package main

import (
	"io/fs"
	"os"
	"strings"
	"testing"
)

// judgmentFlowFixture は図と表の ID が一致する最小のフィクスチャ。
const judgmentFlowFixture = "# 判定フロー\n\n" +
	"```mermaid\n" +
	"flowchart TD\n" +
	"  D1{\"D1: 設定の分類に当たるか\"}\n" +
	"  A2[\"A2: 採択\"]\n" +
	"  H1[\"H1: 保留 (種類不明)\"]\n" +
	"  D1 -- 当たらない --> H1\n" +
	"  D1 -- 当たる --> A2\n" +
	"  style A2 fill:#16a34a2e\n" +
	"```\n\n" +
	"| ID | 種類 | 条件・内容 | 記録に書くもの |\n" +
	"| --- | --- | --- | --- |\n" +
	"| D1 | 判定 | 分類に当たるか | category |\n" +
	"| A2 | 決着 | 採択 | verdict |\n" +
	"| H1 | 決着 | 保留 | verdict |\n"

func judgmentFlowRead(content string) func(string) ([]byte, error) {
	return func(_ string) ([]byte, error) { return []byte(content), nil }
}

func TestJudgmentFlowConsistentPasses(t *testing.T) {
	problems := judgmentFlowProblems([]string{judgmentFlowPath}, judgmentFlowRead(judgmentFlowFixture), "")
	if len(problems) != 0 {
		t.Fatalf("一致しているのに問題が出た: %v", problems)
	}
}

func TestJudgmentFlowDiagramOnlyID(t *testing.T) {
	content := strings.Replace(judgmentFlowFixture,
		"  D1 -- 当たる --> A2\n",
		"  D1 -- 当たる --> A2\n  A2 --> D9\n", 1)
	problems := judgmentFlowProblems([]string{judgmentFlowPath}, judgmentFlowRead(content), "")
	found := false
	for _, p := range problems {
		if strings.Contains(p, "D9") && strings.Contains(p, "図") {
			found = true
		}
	}
	if !found {
		t.Fatalf("図だけにある D9 が報告されない。出た問題: %v", problems)
	}
}

func TestJudgmentFlowTableOnlyID(t *testing.T) {
	content := judgmentFlowFixture + "| H9 | 決着 | 保留 | verdict |\n"
	problems := judgmentFlowProblems([]string{judgmentFlowPath}, judgmentFlowRead(content), "")
	found := false
	for _, p := range problems {
		if strings.Contains(p, "H9") && strings.Contains(p, "表") {
			found = true
		}
	}
	if !found {
		t.Fatalf("表だけにある H9 が報告されない。出た問題: %v", problems)
	}
}

func TestJudgmentFlowDuplicateTableRow(t *testing.T) {
	content := judgmentFlowFixture + "| A2 | 決着 | 重複 | verdict |\n"
	problems := judgmentFlowProblems([]string{judgmentFlowPath}, judgmentFlowRead(content), "")
	found := false
	for _, p := range problems {
		if strings.Contains(p, "A2") && strings.Contains(p, "重複") {
			found = true
		}
	}
	if !found {
		t.Fatalf("表の A2 の重複が報告されない。出た問題: %v", problems)
	}
}

// mermaid のコメント行 (%%) に書いた ID と、色コード (大文字 16 進) は
// ノード ID として数えない — 正規表現の反例 (verification.md の型 F)。
func TestJudgmentFlowIgnoresCommentsAndColors(t *testing.T) {
	content := strings.Replace(judgmentFlowFixture,
		"flowchart TD\n",
		"flowchart TD\n  %% D9 は将来の拡張のためのメモ\n", 1)
	content = strings.Replace(content,
		"  style A2 fill:#16a34a2e\n",
		"  style A2 fill:#A12,stroke:#16A34A2E\n", 1)
	problems := judgmentFlowProblems([]string{judgmentFlowPath}, judgmentFlowRead(content), "")
	if len(problems) != 0 {
		t.Fatalf("コメント行の D9 や色コード #A12 が ID として数えられた: %v", problems)
	}
}

// ノードを消して style 行を消し忘れた編集ミスを検査が捕まえる —
// style / class などの行は ID の出所にしない。
func TestJudgmentFlowStyleOnlyNodeIsNotSatisfied(t *testing.T) {
	content := strings.Replace(judgmentFlowFixture, "  A2[\"A2: 採択\"]\n", "", 1)
	content = strings.Replace(content, "  D1 -- 当たる --> A2\n", "", 1)
	problems := judgmentFlowProblems([]string{judgmentFlowPath}, judgmentFlowRead(content), "")
	found := false
	for _, p := range problems {
		if strings.Contains(p, "A2") && strings.Contains(p, "図にありません") {
			found = true
		}
	}
	if !found {
		t.Fatalf("style 行だけの A2 が図の ID として満たされてしまう。出た問題: %v", problems)
	}
}

// タブ区切りの装飾行 (style<TAB>A2 …) も装飾として除外される — 区切りを
// 半角スペース 1 種と仮定すると、実ノードの無い ID が図側に混入する。
func TestJudgmentFlowTabSeparatedDecoration(t *testing.T) {
	content := strings.Replace(judgmentFlowFixture, "  A2[\"A2: 採択\"]\n", "", 1)
	content = strings.Replace(content, "  D1 -- 当たる --> A2\n", "", 1)
	content = strings.Replace(content, "  style A2 fill:#16a34a2e\n", "  style\tA2 fill:#16a34a2e\n", 1)
	problems := judgmentFlowProblems([]string{judgmentFlowPath}, judgmentFlowRead(content), "")
	found := false
	for _, p := range problems {
		if strings.Contains(p, "A2") && strings.Contains(p, "図にありません") {
			found = true
		}
	}
	if !found {
		t.Fatalf("タブ区切りの style 行の A2 が図の ID として満たされてしまう。出た問題: %v", problems)
	}
}

// 決定表のパイプ前後の空白の詰め方が違っても ID は収集される。
func TestJudgmentFlowTableSpacingVariants(t *testing.T) {
	content := strings.Replace(judgmentFlowFixture,
		"| D1 | 判定 | 分類に当たるか | category |\n",
		"|D1| 判定 | 分類に当たるか | category |\n", 1)
	if problems := judgmentFlowProblems([]string{judgmentFlowPath}, judgmentFlowRead(content), ""); len(problems) != 0 {
		t.Fatalf("空白を詰めた表の行の ID が収集されない: %v", problems)
	}
}

// 見出しの先頭セルが ID の形でも、直後が区切り行なら本体行として数えない
// (偽の重複報告を出さない)。
func TestJudgmentFlowHeaderRowNotCounted(t *testing.T) {
	content := strings.Replace(judgmentFlowFixture,
		"| ID | 種類 | 条件・内容 | 記録に書くもの |\n",
		"| D1 | 種類 | 条件・内容 | 記録に書くもの |\n", 1)
	problems := judgmentFlowProblems(nil, judgmentFlowRead(content), "")
	for _, p := range problems {
		if strings.Contains(p, "重複") {
			t.Fatalf("見出し行の D1 が本体行として数えられ、偽の重複が報告された: %v", p)
		}
	}
}

func TestJudgmentFlowMissingDiagram(t *testing.T) {
	content := "# 判定フロー\n\n| ID | 種類 |\n| --- | --- |\n| D1 | 判定 |\n"
	problems := judgmentFlowProblems([]string{judgmentFlowPath}, judgmentFlowRead(content), "")
	if len(problems) == 0 {
		t.Fatalf("mermaid の図が無いのに問題が出ない")
	}
}

// readFile の失敗は問題として報告される (黙って緑にしない)。
func TestJudgmentFlowReadError(t *testing.T) {
	read := func(_ string) ([]byte, error) { return nil, os.ErrPermission }
	problems := judgmentFlowProblems([]string{judgmentFlowPath}, read, "")
	found := false
	for _, p := range problems {
		if strings.Contains(p, "読み込みに失敗") {
			found = true
		}
	}
	if !found {
		t.Fatalf("readFile の失敗が報告されない。出た問題: %v", problems)
	}
}

// mermaid はあるが決定表の行が 1 つも無い場合は報告される。
func TestJudgmentFlowMissingTable(t *testing.T) {
	content := "# 判定フロー\n\n```mermaid\nflowchart TD\n  D1{\"D1: x\"}\n```\n"
	problems := judgmentFlowProblems([]string{judgmentFlowPath}, judgmentFlowRead(content), "")
	found := false
	for _, p := range problems {
		if strings.Contains(p, "決定表") {
			found = true
		}
	}
	if !found {
		t.Fatalf("決定表の不在が報告されない。出た問題: %v", problems)
	}
}

// git 追跡に依らず、ファイルが読めれば検査する — 追跡前の判定フローが
// 素通りする「0 件マッチで黙って緑」の型 (B1 と同じ) を塞ぐ。
func TestJudgmentFlowChecksUntrackedFile(t *testing.T) {
	problems := judgmentFlowProblems(nil, judgmentFlowRead("# 図も表も無い\n"), "")
	if len(problems) == 0 {
		t.Fatalf("追跡外でも読める判定フローが検査されない")
	}
}

// ファイルがそもそも無いリポジトリ (スキル未導入) では検査は黙って通る。
// 在り処の指定が無い (origin が空) ときだけの扱いであることは、次のテストが対にする。
func TestJudgmentFlowAbsentFileSkipped(t *testing.T) {
	read := func(_ string) ([]byte, error) { return nil, fs.ErrNotExist }
	problems := judgmentFlowProblems(nil, read, "")
	if len(problems) != 0 {
		t.Fatalf("対象ファイルが無いのに問題が出た: %v", problems)
	}
}

// 在り処を指定したのにファイルが無いなら報告する。指定は「そこを検査せよ」という
// 意思表示なので、黙って通すと検査が無効になったことに気づけない (診断ツールの偽陰性)。
// 報告にはどちらの指定を直せばよいか (origin) を載せる — 解決の経路が 2 つあるため。
func TestJudgmentFlowAbsentFileReportedWhenOriginGiven(t *testing.T) {
	read := func(_ string) ([]byte, error) { return nil, fs.ErrNotExist }
	for _, origin := range []string{"-judgment-flow", "CLAUDE_PLUGIN_ROOT"} {
		t.Run(origin, func(t *testing.T) {
			problems := judgmentFlowProblems(nil, read, origin)
			if len(problems) != 1 {
				t.Fatalf("指定したパスが不在なのに報告が 1 件でない: %v", problems)
			}
			if !strings.Contains(problems[0], origin) {
				t.Fatalf("報告に指定の出所 %q が無い: %q", origin, problems[0])
			}
			if !strings.Contains(problems[0], judgmentFlowPath) {
				t.Fatalf("報告に対象のパスが無い: %q", problems[0])
			}
		})
	}
}
