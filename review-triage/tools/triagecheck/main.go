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
	"errors"
	"flag"
	"fmt"
	"os"
	"path"
	"path/filepath"
	"strings"
)

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func run(args []string) error {
	fs := flag.NewFlagSet("triagecheck", flag.ContinueOnError)
	recordDir := fs.String("record-dir", "",
		"トリアージ記録 (*.yaml) の置き場 (必須)。相対パスなら -current-dir も要る")
	currentDir := fs.String("current-dir", "",
		"相対パスを解決する基準のディレクトリ。絶対パスで、実在すること")
	flowPath := fs.String("judgment-flow", "",
		"判定フローの正本 (judgment-flow.md) のパス。省略時は CLAUDE_PLUGIN_ROOT から解決する")
	writeSummary := fs.Bool("write-summary", false,
		"検査せず、記録から生成サマリ (.md) を書き出す")
	installWrapperPath := fs.String("install-wrapper", "",
		"検査せず、-record-dir と -judgment-flow の値を焼き込んだ呼び出し用のラッパースクリプトを指定パスに書き出す")
	if err := fs.Parse(args); err != nil {
		return err
	}

	// 明示的に渡されたフラグを拾う。既定値との一致では判定しない — 利用者が
	// 既定と同じ値を明示的に渡すことがあり、そのとき「指定していない」と誤って
	// 扱うと、不在を報告すべき経路が黙って通る。flag.Visit は実際に指定された
	// フラグだけを回すので、意思表示の有無をそのまま読める。
	explicit := map[string]bool{}
	fs.Visit(func(f *flag.Flag) { explicit[f.Name] = true })

	// -install-wrapper は record-dir をそのまま (呼び出し元の意図した相対/絶対の
	// 形のまま) ラッパーに焼き込む。以降の検査処理に入る前に分岐する。
	if *installWrapperPath != "" {
		return installWrapper(*installWrapperPath, *recordDir, *flowPath)
	}

	// -record-dir は必須。既定値を持たせない — 既定が相対パスだと「基準の無い相対」を
	// 許すことになり、下の規則が崩れる。省略を許して既定の場所を検査したことにするより、
	// どこを検査するのかを必ず言わせる。
	if *recordDir == "" {
		return fmt.Errorf("-record-dir は必須です (検査する記録の置き場を指定する)")
	}
	// 空文字の明示指定はパスとして意味を持たないので、検査に入る前に弾く。
	// -judgment-flow "" を通すと在り処が定まらないまま指定として扱われ、
	// 「指定したのに検査されない」— この検査が塞ごうとしている型そのものになる。
	for _, name := range []string{"judgment-flow", "current-dir"} {
		if explicit[name] && strings.TrimSpace(fs.Lookup(name).Value.String()) == "" {
			return fmt.Errorf("-%s に空のパスが指定されました", name)
		}
	}

	// 相対パスの基準は推測せず、-current-dir で明示させる。
	//
	// このツールは `go run -C <展開先>/tools/triagecheck .` の形で起動される。
	// go run -C は子プロセスのカレントを指定ディレクトリへ移すので、Getwd は
	// ツール自身を指し、呼び出し元のカレントはプロセスの中から知りようがない。
	// $PWD はシェルが更新する慣習にすぎず (make -C やプログラムからの chdir では
	// 更新されない)、基準に使うと検査対象が黙ってすり替わる。
	// 知り得ないものを推測するより、知っている側に書かせる。
	base, err := resolveBaseDir(*currentDir)
	if err != nil {
		return err
	}
	absRecordDir, baseUsed, err := resolvePath(*recordDir, base, "-record-dir")
	if err != nil {
		return err
	}
	// path.Clean で表記の揺れ (".", "./rec", "rec//") を畳む。照合は
	// inReviewTriageDir が両辺を clean して行うので、ここでの末尾のスラッシュは
	// エラーメッセージの見た目のためだけに付ける。
	reviewTriageDir = path.Clean(filepath.ToSlash(absRecordDir)) + "/"

	if *writeSummary {
		// 生成の経路は判定フローを見ないので、-current-dir が使われたかは
		// ここまでで確定する。検査の経路と同じ規則を課す (下の同じ検査と対)。
		if explicit["current-dir"] && !baseUsed {
			return errCurrentDirUnused
		}
		return writeReviewTriageSummaries(reviewTriageDir, true)
	}

	// 判定フローのパスも -record-dir と同じ規則で解決する。
	//
	// ただし「絶対パスに -current-dir を併記したらエラー」は -judgment-flow で
	// 明示されたときにだけ課す。CLAUDE_PLUGIN_ROOT から組み立てた値は常に絶対で、
	// 利用者が -current-dir を書いたかどうかとは無関係に決まるため、そこで
	// 弾くと「環境変数を設定していると -current-dir が使えない」ことになる。
	p, flowOrigin := resolveJudgmentFlowPath(*flowPath, explicit["judgment-flow"])
	if p != "" {
		flowBase := base
		if flowOrigin == "CLAUDE_PLUGIN_ROOT" {
			flowBase = ""
		}
		absFlow, used, err := resolvePath(p, flowBase, "-judgment-flow")
		if err != nil {
			return err
		}
		baseUsed = baseUsed || used
		judgmentFlowPath = absFlow
	}

	// -current-dir を渡したのに一度も基準として使われなかったなら、指定は効いて
	// いない。黙って通すと「基準を渡したつもり」のまま別の解決結果を受け取る。
	if explicit["current-dir"] && !baseUsed {
		return errCurrentDirUnused
	}

	// 置き場の不在は problems に積む — judgment-flow 側と扱いを揃える。
	// 即 return すると判定フローの検査に到達せず、片方を直して再実行するまで
	// もう一方も壊れていることを知れない。
	var problems []string
	recordFiles, err := listReviewTriageFiles(reviewTriageDir, true)
	switch {
	case errors.Is(err, errRecordDirMissing):
		problems = append(problems, fmt.Sprintf("%s: %v", reviewTriageDir, err))
	case err != nil:
		// 権限・I/O など、続行しても他の検査が意味を持たないエラーは即座に返す。
		return fmt.Errorf("%s: 記録の一覧に失敗しました: %w", reviewTriageDir, err)
	default:
		problems = append(problems, reviewTriageRecordProblems(recordFiles, os.ReadFile)...)
	}
	// 判定フローは -judgment-flow だけでなく CLAUDE_PLUGIN_ROOT からも解決される。
	// どちらも「この場所を検査せよ」という指定なので、実在を要求する対象に含める
	// (解決できず既定のままのときだけ、未導入として通す)。
	problems = append(problems, judgmentFlowProblems(nil, os.ReadFile, flowOrigin)...)

	if len(problems) > 0 {
		for _, p := range problems {
			fmt.Fprintln(os.Stderr, "  - "+p)
		}
		return fmt.Errorf("triagecheck: %d 件の問題が見つかりました", len(problems))
	}
	fmt.Printf("triagecheck: 問題は見つかりませんでした（検査: review-triage-record, judgment-flow）\n")
	return nil
}

// errCurrentDirUnused は -current-dir を渡したのに一度も基準として使われなかった
// ことを表す。検査の経路と生成の経路の両方で同じ文言を返すために切り出す。
var errCurrentDirUnused = errors.New(
	"-current-dir を指定しましたが、パスがすべて絶対なので使われません (どちらか一方にしてください)")

// resolveBaseDir は -current-dir の値を検証して返す。指定が無ければ空を返す
// (そのとき相対パスは resolvePath がエラーにする)。
//
// 基準そのものが相対だと「基準の基準」が要り、元の問題に戻る。実在も要求する —
// 存在しないディレクトリを基準にすると、そこからの相対も存在しないので、
// 「指定したのに検査できない」を作る。
func resolveBaseDir(currentDir string) (string, error) {
	if currentDir == "" {
		return "", nil
	}
	if !filepath.IsAbs(currentDir) {
		return "", fmt.Errorf("-current-dir は絶対パスで指定してください: %q", currentDir)
	}
	st, err := os.Stat(currentDir)
	if err != nil {
		return "", fmt.Errorf("-current-dir を読めません: %w", err)
	}
	if !st.IsDir() {
		return "", fmt.Errorf("-current-dir がディレクトリではありません: %q", currentDir)
	}
	return currentDir, nil
}

// resolvePath は p を絶対パスにして返す。絶対ならそのまま、相対なら base を基準にする。
// 2 つ目の戻り値は base を実際に使ったか (呼び出し側が「-current-dir が一度も
// 使われなかった」ことを検出するために使う)。
//
// base が空 (= -current-dir が無い) のに相対を渡されたらエラーにする。ここで
// 推測した基準を当てにいくと、外れたときに別の場所を検査して黙って緑を返す。
func resolvePath(p, base, flagName string) (string, bool, error) {
	if filepath.IsAbs(p) {
		return p, false, nil
	}
	if base == "" {
		return "", false, fmt.Errorf(
			"%s が相対パスです。基準を -current-dir で指定するか、絶対パスにしてください: %s", flagName, p)
	}
	return filepath.Join(base, p), true, nil
}

// resolveJudgmentFlowPath は判定フローの正本の在り処を決める。優先順は
// 明示の指定 → プラグインの展開先 → 既定 (リポジトリ内にスキルを直接置いた形)。
//
// 見つからなかったときに空文字を返して既定のままにするのは、判定フローが
// 無い状態を「検査対象が無い」として通す判断が judgmentFlowProblems 側に
// あるため。ここでエラーにすると、記録の検査まで巻き添えで落ちる。
//
// 2 つ目の戻り値は在り処を指定したものの名前 (origin)。-judgment-flow と
// CLAUDE_PLUGIN_ROOT のどちらも、その場所を検査せよという指定なので名前を返す。
// 既定に落ちたときだけ空で、そのとき不在は未導入として通る。名前を返すのは、
// 不在の報告にどちらを直せばよいかを載せるため。
//
// 指定の有無は値ではなく specified (呼び出し側が flag.Visit で読んだ意思表示) で
// 判定する。値が空かどうかで見ると、-judgment-flow "" の明示指定が「指定なし」に
// 化け、検査が走らないまま緑になる (-record-dir で避けたはずの型と同じ)。
func resolveJudgmentFlowPath(value string, specified bool) (flowPath, origin string) {
	if specified {
		return value, "-judgment-flow"
	}
	root := os.Getenv("CLAUDE_PLUGIN_ROOT")
	if root == "" {
		return "", ""
	}
	return filepath.Join(root, "skills", "review-triage", "references", "judgment-flow.md"), "CLAUDE_PLUGIN_ROOT"
}
