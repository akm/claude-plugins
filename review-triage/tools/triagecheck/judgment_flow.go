// judgment_flow.go は review-triage の判定フローの正本 (judgment-flow.md) について、
// mermaid の図のノード ID 集合と決定表の ID 集合が 1:1 で一致するかを検査する
// (judgment-flow)。
//
// 図は「ノードと遷移」だけ、表は「各ノードの条件と書くもの」だけを持ち、同じ事実を
// 二度語らない。残るずれ方は ID 集合の不一致だけなので、そこを機械で照合する。
// 生成はしない — 照合のみ。
package main

import (
	"errors"
	"fmt"
	"io/fs"
	"regexp"
	"sort"
	"strings"
)

// judgmentFlowPath は判定フローの正本。ファイルが存在しないときは検査を
// 何もしない (対象は git 追跡でなくファイルの実在で決める)。
//
// スキルがプラグインとして配られると、この正本はリポジトリの外 (プラグインの
// 展開先) に置かれ、パスは環境ごとに違う。main が CLAUDE_PLUGIN_ROOT または
// -judgment-flow から解決して設定する。既定はリポジトリ内にスキルを直接置く
// 形 (プラグイン化前の配置) で、そのときだけこの値がそのまま使われる。
var judgmentFlowPath = ".claude/skills/review-triage/references/judgment-flow.md"

var (
	// judgmentFlowIDRe はノード ID の形。判定 (D)・評価 (E)・採択 (A)・保留 (H)・却下 (R)。
	judgmentFlowIDRe = regexp.MustCompile(`\b([ADEHR]\d+)\b`)
	// judgmentFlowTableRowRe は決定表の行 (先頭セルが ID)。パイプ前後の空白の
	// 詰め方には依存しない。
	judgmentFlowTableRowRe = regexp.MustCompile(`^\|\s*([ADEHR]\d+)\s*\|`)
	// judgmentFlowQuoteRe は mermaid のラベル文字列。ID の抽出前に取り除く
	// (ラベル内の "D1: ..." のような表示用の ID を数えないため)。
	judgmentFlowQuoteRe = regexp.MustCompile(`"[^"]*"`)
	// judgmentFlowColorRe は色コード。`#A12` のような大文字の短い 16 進が
	// ID の形 ([ADEHR]\d+) に一致してしまうため、抽出前に取り除く (型 F の反例)。
	judgmentFlowColorRe = regexp.MustCompile(`#[0-9A-Fa-f]+`)
	// judgmentFlowSeparatorRe は表の区切り行 (| --- | --- |)。直前の行は見出しで、
	// 先頭セルが ID の形でも本体行として数えない。
	judgmentFlowSeparatorRe = regexp.MustCompile(`^\s*\|(\s*:?-{3,}:?\s*\|)+\s*$`)
)

// judgmentFlowDecorations は ID の出所にしない装飾行の先頭トークン。
var judgmentFlowDecorations = map[string]bool{
	"style": true, "class": true, "classDef": true, "click": true, "linkStyle": true,
}

// judgmentFlowProblems は図と表の ID 集合を照合する。対象は git 追跡でなく
// ファイルの実在で決める — 追跡前の判定フローが素通りする「0 件マッチで黙って緑」の
// 型 (B1 と同じ) を塞ぐ。ファイルが無いのはスキル未導入の正常な状態で、何もしない。
// files は他の検査とシグネチャを揃えるための引数で、使わない。
func judgmentFlowProblems(_ []string, readFile func(string) ([]byte, error)) []string {
	data, err := readFile(judgmentFlowPath)
	if err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			return nil
		}
		return []string{fmt.Sprintf("%s: 読み込みに失敗しました: %v", judgmentFlowPath, err)}
	}

	var problems []string
	diagramIDs := map[string]bool{}
	tableIDs := map[string]int{}
	inMermaid := false
	hasMermaid := false
	lines := strings.Split(string(data), "\n")
	for i, line := range lines {
		trimmed := strings.TrimSpace(line)
		switch {
		case strings.HasPrefix(trimmed, "```mermaid"):
			inMermaid = true
			hasMermaid = true
			continue
		case strings.HasPrefix(trimmed, "```"):
			inMermaid = false
			continue
		}
		if inMermaid {
			// コメント行 (%%。ディレクティブ %%{...}%% を含む) は ID の出所にしない。
			if strings.HasPrefix(trimmed, "%%") {
				continue
			}
			// 装飾の行も ID の出所にしない — ノードを消して style 行を消し忘れた
			// 編集ミスを、ID 照合が「図にある」と誤認しないため。先頭トークンは
			// strings.Fields で取り出す (タブ区切りも区切りとして扱う)。
			if fields := strings.Fields(trimmed); len(fields) > 0 && judgmentFlowDecorations[fields[0]] {
				continue
			}
			stripped := judgmentFlowQuoteRe.ReplaceAllString(line, "")
			stripped = judgmentFlowColorRe.ReplaceAllString(stripped, "")
			for _, m := range judgmentFlowIDRe.FindAllStringSubmatch(stripped, -1) {
				diagramIDs[m[1]] = true
			}
			continue
		}
		if m := judgmentFlowTableRowRe.FindStringSubmatch(line); m != nil {
			// 直後が区切り行なら、この行は見出し — 本体行として数えない。
			if i+1 < len(lines) && judgmentFlowSeparatorRe.MatchString(lines[i+1]) {
				continue
			}
			tableIDs[m[1]]++
		}
	}

	if !hasMermaid {
		problems = append(problems, fmt.Sprintf("%s: mermaid の図が見つかりません (図がノードと遷移の正本)", judgmentFlowPath))
	}
	if len(tableIDs) == 0 {
		problems = append(problems, fmt.Sprintf("%s: 決定表 (先頭セルが ID の行) が見つかりません", judgmentFlowPath))
	}
	if !hasMermaid || len(tableIDs) == 0 {
		return problems
	}

	for _, id := range sortedMapKeys(diagramIDs) {
		if tableIDs[id] == 0 {
			problems = append(problems, fmt.Sprintf(
				"%s: %s は図にあるが決定表にありません (条件と書くものを表に足す)", judgmentFlowPath, id))
		}
	}
	for id, n := range tableIDs {
		if !diagramIDs[id] {
			problems = append(problems, fmt.Sprintf(
				"%s: %s は決定表にあるが図にありません (遷移を図に足すか行を消す)", judgmentFlowPath, id))
		}
		if n > 1 {
			problems = append(problems, fmt.Sprintf(
				"%s: %s の行が決定表で重複しています", judgmentFlowPath, id))
		}
	}
	sort.Strings(problems)
	return problems
}

// sortedMapKeys はマップのキーを昇順で返す。出力の順序を入力の反復順に
// 依存させないため (問題の並びが実行ごとに変わると差分が読めない)。
func sortedMapKeys[V any](m map[string]V) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}
