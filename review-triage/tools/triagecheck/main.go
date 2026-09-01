// triagecheck は review-triage の記録 (YAML) と判定フローの正本を検査する。
//
// lappds の tools/doccheck から、review-triage に関わる 2 つの検査
// (review-triage-record / judgment-flow) を切り出したもの。検査の中身は
// 変えていない — 変えたのは、対象のパスをリポジトリごとに決められるように
// した点だけ。
//
// 使い方:
//
//	triagecheck                          # 既定の置き場を検査する
//	triagecheck -record-dir docs/rt/     # 記録の置き場を指定する
//	triagecheck -write-summary           # 記録から生成サマリ (.md) を書き出す
//	triagecheck -install-wrapper <path>  # 呼び出し用のラッパースクリプトを書き出す
package main

import (
	"flag"
	"fmt"
	"os"
	"path"
	"path/filepath"
)

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func run(args []string) error {
	fs := flag.NewFlagSet("triagecheck", flag.ContinueOnError)
	recordDir := fs.String("record-dir", reviewTriageDir,
		"トリアージ記録 (*.yaml) の置き場。末尾のスラッシュは補われる")
	flowPath := fs.String("judgment-flow", "",
		"判定フローの正本 (judgment-flow.md) のパス。省略時は CLAUDE_PLUGIN_ROOT から解決する")
	writeSummary := fs.Bool("write-summary", false,
		"検査せず、記録から生成サマリ (.md) を書き出す")
	installWrapperPath := fs.String("install-wrapper", "",
		"検査せず、-record-dir と -judgment-flow の値を焼き込んだ呼び出し用のラッパースクリプトを指定パスに書き出す")
	if err := fs.Parse(args); err != nil {
		return err
	}

	// -install-wrapper は record-dir をそのまま (呼び出し元の意図した相対/絶対の
	// 形のまま) ラッパーに焼き込む。以降の検査処理に入る前に分岐する。
	if *installWrapperPath != "" {
		return installWrapper(*installWrapperPath, *recordDir, *flowPath)
	}

	// path.Clean で表記の揺れ (".", "./rec", "rec//") を畳む。照合は
	// inReviewTriageDir が両辺を clean して行うので、ここでの末尾のスラッシュは
	// エラーメッセージの見た目のためだけに付ける。
	reviewTriageDir = path.Clean(filepath.ToSlash(*recordDir)) + "/"

	if *writeSummary {
		return writeReviewTriageSummaries(reviewTriageDir)
	}

	if p := resolveJudgmentFlowPath(*flowPath); p != "" {
		judgmentFlowPath = p
	}

	recordFiles, err := listReviewTriageFiles(reviewTriageDir)
	if err != nil {
		return fmt.Errorf("%s: 記録の一覧に失敗しました: %w", reviewTriageDir, err)
	}
	problems := reviewTriageRecordProblems(recordFiles, os.ReadFile)
	problems = append(problems, judgmentFlowProblems(nil, os.ReadFile)...)

	if len(problems) > 0 {
		for _, p := range problems {
			fmt.Fprintln(os.Stderr, "  - "+p)
		}
		return fmt.Errorf("triagecheck: %d 件の問題が見つかりました", len(problems))
	}
	fmt.Printf("triagecheck: 問題は見つかりませんでした（検査: review-triage-record, judgment-flow）\n")
	return nil
}

// resolveJudgmentFlowPath は判定フローの正本の在り処を決める。優先順は
// 明示の指定 → プラグインの展開先 → 既定 (リポジトリ内にスキルを直接置いた形)。
//
// 見つからなかったときに空文字を返して既定のままにするのは、判定フローが
// 無い状態を「検査対象が無い」として通す判断が judgmentFlowProblems 側に
// あるため。ここでエラーにすると、記録の検査まで巻き添えで落ちる。
func resolveJudgmentFlowPath(explicit string) string {
	if explicit != "" {
		return explicit
	}
	root := os.Getenv("CLAUDE_PLUGIN_ROOT")
	if root == "" {
		return ""
	}
	return filepath.Join(root, "skills", "review-triage", "references", "judgment-flow.md")
}
