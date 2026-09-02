// triagecheck は review-triage の記録 (YAML) と判定フローの正本を検査する。
//
// lappds の tools/doccheck から、review-triage に関わる 2 つの検査
// (review-triage-record / judgment-flow) を切り出したもの。検査の中身は
// 変えていない — 変えたのは、対象のパスをリポジトリごとに決められるように
// した点だけ。
//
// 使い方 (-record-dir は必須。相対パスを渡すなら -current-dir も要る。
// パスの規則は 3 つの経路 (検査 / -write-summary / -install-wrapper) で同じ):
//
//	triagecheck -record-dir /abs/docs/rt
//	triagecheck -current-dir "$(pwd)" -record-dir docs/rt
//	triagecheck -record-dir /abs/docs/rt -write-summary     # 生成サマリ (.md) を書き出す
//	triagecheck -current-dir "$(pwd)" -install-wrapper bin/rtc -record-dir docs/rt  # ラッパーを書き出す
package main

import (
	"errors"
	"flag"
	"fmt"
	"io/fs"
	"os"
	"path"
	"path/filepath"
	"strings"
	"unicode"
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

	// 経路どうしの衝突は、パスの規則より前に見る。-install-wrapper と
	// -write-summary=true は「何を書き出すか」が食い違うので、黙って片方を
	// 無視すると「指定したのに効かない」を作る。弾くのは「何かを要求したとき」
	// だけ — -write-summary=false は「生成サマリは要らない」= -install-wrapper の
	// 既定の挙動そのものを頼んでいるだけで、拒否する理由が無い。flag.Visit は
	// 値を見ずに「指定された」と報告するので、値の側も見る。
	if explicit["install-wrapper"] && explicit["write-summary"] && *writeSummary {
		return fmt.Errorf("-write-summary は %w (生成の経路では使われません)", errFlagUnusedWithInstallWrapper)
	}

	// パスの規則は、経路 (検査 / -write-summary / -install-wrapper) で分岐する前に
	// 1 か所で当てる。経路ごとに書くと、規則を 1 つ足すたびに他の経路へ書き忘れ、
	// 同じ入力に経路ごとに違う契約ができる (このブランチのレビューで、その型の
	// 指摘が回を重ねて続いた)。ここを通った後の経路は、解決済みの絶対パスを
	// 受け取るだけで、パスを検査しない。
	in, err := resolveInputs(pathInputs{
		recordDir:      *recordDir,
		currentDir:     *currentDir,
		judgmentFlow:   *flowPath,
		installWrapper: *installWrapperPath,
		explicit:       explicit,
	})
	if err != nil {
		return err
	}

	// 明示した在り処の不在は、経路を問わず「指定したのに検査できない」なので
	// ここで止める。置き場と判定フローの両方が無いときは 1 回の実行で両方を
	// 報告する — 片方で即 return すると、片方を直して再実行するまで
	// もう一方も壊れていることを知れない。
	if problems := missingPathProblems(in); len(problems) > 0 {
		for _, p := range problems {
			fmt.Fprintln(os.Stderr, "  - "+p)
		}
		return fmt.Errorf("triagecheck: %d 件の問題が見つかりました: %w", len(problems), errPathMissing)
	}

	// path.Clean で表記の揺れ (".", "./rec", "rec//") を畳む。照合は
	// inReviewTriageDir が両辺を clean して行うので、ここでの末尾のスラッシュは
	// エラーメッセージの見た目のためだけに付ける。
	reviewTriageDir = path.Clean(filepath.ToSlash(in.recordDir)) + "/"
	if in.judgmentFlow != "" {
		judgmentFlowPath = in.judgmentFlow
	}

	// 以降は経路ごとの処理。パスは上で解決済みなので、どの経路も値を検査しない。
	if in.installWrapper != "" {
		return installWrapper(in.installWrapper, in.recordDir, in.embedJudgmentFlow)
	}
	if *writeSummary {
		return writeReviewTriageSummaries(reviewTriageDir, true)
	}

	var problems []string
	recordFiles, err := listReviewTriageFiles(reviewTriageDir, true)
	if err != nil {
		// 不在は上で報告済みなので、ここに来るのは権限・I/O など、続行しても
		// 他の検査が意味を持たないエラーだけ。
		return fmt.Errorf("%s: 記録の一覧に失敗しました: %w", reviewTriageDir, err)
	}
	problems = append(problems, reviewTriageRecordProblems(recordFiles, os.ReadFile)...)
	problems = append(problems, judgmentFlowProblems(nil, os.ReadFile, in.judgmentFlowOrigin)...)

	if len(problems) > 0 {
		for _, p := range problems {
			fmt.Fprintln(os.Stderr, "  - "+p)
		}
		return fmt.Errorf("triagecheck: %d 件の問題が見つかりました", len(problems))
	}
	fmt.Printf("triagecheck: 問題は見つかりませんでした（検査: review-triage-record, judgment-flow）\n")
	return nil
}

// pathInputs はフラグから読んだ、パスに関わる入力。explicit は flag.Visit で
// 拾った「明示されたか」。
type pathInputs struct {
	recordDir      string
	currentDir     string
	judgmentFlow   string
	installWrapper string
	explicit       map[string]bool
}

// resolvedInputs は規則を当てた後の、解決済みの絶対パス。
type resolvedInputs struct {
	recordDir string
	// judgmentFlow は検査に使う判定フローの絶対パス。指定も CLAUDE_PLUGIN_ROOT も
	// 無ければ空 (そのとき判定フローの検査は未導入として通る)。
	judgmentFlow string
	// judgmentFlowOrigin は判定フローの在り処を指定したものの名前
	// (-judgment-flow / CLAUDE_PLUGIN_ROOT)。報告に使う。既定なら空。
	judgmentFlowOrigin string
	// embedJudgmentFlow はラッパーに焼き込む判定フローの絶対パス。明示された
	// ときだけ非空。省略時はラッパーが実行時に $root から既定を解決するので、
	// CLAUDE_PLUGIN_ROOT からは埋めない — 埋めると版のディレクトリを含む固定の
	// パスになり、プラグインの更新でそのラッパーが壊れる。これは規則の違いでは
	// なく「省略時の既定」の違いで、規則 (明示した値の扱い) は他の経路と同じ。
	embedJudgmentFlow string
	// installWrapper はラッパーの出力先の絶対パス。明示されたときだけ非空。
	installWrapper string
}

// resolveInputs は、明示された各パスに同じ規則を同じ順で当てる。
//
//  1. 空・空白・不可視の値は弾く (isBlankPath)。空の明示はパスとして意味を持たず、
//     通すと「指定したのに検査されない」になる。
//  2. 相対パスは -current-dir を基準に解決する (無ければ resolvePath がエラー)。
//     基準は推測しない — go run -C で起動されるためカレントはツール側を指し、
//     呼び出し元のカレントはプロセスの中から知りようがない。
//  3. -current-dir を渡したのに一度も基準として使われなければエラー。黙って通すと
//     「基準を渡したつもり」のまま別の解決結果を受け取る。
//
// 実在の要求は missingPathProblems が担う (全件をまとめて報告するため)。
//
// -record-dir は必須で既定値を持たせない。既定が相対パスだと「基準の無い相対」を
// 許すことになり、上の規則が崩れる。省略を許して既定の場所を検査したことにする
// より、どこを検査するのかを必ず言わせる。空文字は省略と区別できないので、
// 空のパスではなく必須の検査として弾かれる。
func resolveInputs(in pathInputs) (resolvedInputs, error) {
	var out resolvedInputs
	if in.recordDir == "" {
		return out, errRecordDirRequired
	}
	for _, f := range []struct{ name, value string }{
		{"record-dir", in.recordDir},
		{"current-dir", in.currentDir},
		{"judgment-flow", in.judgmentFlow},
		{"install-wrapper", in.installWrapper},
	} {
		if in.explicit[f.name] && isBlankPath(f.value) {
			return out, fmt.Errorf("-%s に%w", f.name, errEmptyPath)
		}
	}

	base, err := resolveBaseDir(in.currentDir)
	if err != nil {
		return out, err
	}
	absRecordDir, baseUsed, err := resolvePath(in.recordDir, base, "-record-dir")
	if err != nil {
		return out, err
	}
	out.recordDir = absRecordDir

	// 判定フローの在り処は、明示の指定 → CLAUDE_PLUGIN_ROOT → 既定 (無し) の順。
	//
	// 「絶対パスに -current-dir を併記したらエラー」は -judgment-flow で明示された
	// ときにだけ課す。CLAUDE_PLUGIN_ROOT から組み立てた値は常に絶対で、利用者が
	// -current-dir を書いたかどうかとは無関係に決まるため、そこで弾くと
	// 「環境変数を設定していると -current-dir が使えない」ことになる。
	// 報告には値の出所 (origin) を使う。固定のフラグ名で報告すると、環境変数から
	// 解決した値の誤りを、利用者が渡していない -judgment-flow の名前で叱ることになる。
	p, origin := resolveJudgmentFlowPath(in.judgmentFlow, in.explicit["judgment-flow"])
	if p != "" {
		flowBase := base
		if origin == "CLAUDE_PLUGIN_ROOT" {
			flowBase = ""
		}
		absFlow, used, err := resolvePath(p, flowBase, origin)
		if err != nil {
			return out, err
		}
		baseUsed = baseUsed || used
		out.judgmentFlow = absFlow
		out.judgmentFlowOrigin = origin
		if origin == "-judgment-flow" {
			out.embedJudgmentFlow = absFlow
		}
	}

	if in.explicit["install-wrapper"] {
		absOut, used, err := resolvePath(in.installWrapper, base, "-install-wrapper")
		if err != nil {
			return out, err
		}
		baseUsed = baseUsed || used
		out.installWrapper = absOut
	}

	if in.explicit["current-dir"] && !baseUsed {
		return out, errCurrentDirUnused
	}
	return out, nil
}

// isBlankPath は、パスとして意味を持たない値かを返す。空文字と、Unicode の空白類
// (unicode.IsSpace) だけの値に加えて、フォーマット文字 (Cf: ゼロ幅スペース U+200B・
// 単語結合子 U+2060・BOM U+FEFF など) だけの値も空とみなす。これらは表示されない
// ので、通すと不可視の名前のファイルや存在しないパスが「指定した」ことになり、
// 利用者は何を渡したのか読み取れない。
func isBlankPath(s string) bool {
	return strings.TrimFunc(s, func(r rune) bool {
		return unicode.IsSpace(r) || unicode.Is(unicode.Cf, r)
	}) == ""
}

// missingPathProblems は、明示した在り処のうち実在しないものを報告の行にして返す。
// 対象は入力として読むパス (記録の置き場と判定フロー) で、ラッパーの出力先は
// 含めない (これから作るものなので、無いのが普通)。
//
// 判定フローは -judgment-flow だけでなく CLAUDE_PLUGIN_ROOT からも解決される。
// どちらも「この場所を検査せよ」という指定なので、実在を要求する対象に含める
// (解決できず既定のままのときだけ、未導入として通す)。生成の経路では
// CLAUDE_PLUGIN_ROOT 由来の値を焼き込まないが、実在の要求は同じ規則として課す —
// 経路で規則を変えると、その差が次の欠陥の置き場になる。
func missingPathProblems(in resolvedInputs) []string {
	var problems []string
	if _, err := os.Stat(in.recordDir); errors.Is(err, fs.ErrNotExist) {
		problems = append(problems, fmt.Sprintf("%s: %v", in.recordDir, errRecordDirMissing))
	}
	if in.judgmentFlow != "" {
		if _, err := os.Stat(in.judgmentFlow); errors.Is(err, fs.ErrNotExist) {
			problems = append(problems, fmt.Sprintf(
				"%s: %s が指す判定フローの正本が存在しません (検査が行われないまま緑になるため報告する)",
				in.judgmentFlow, in.judgmentFlowOrigin))
		}
	}
	return problems
}

// errCurrentDirUnused は -current-dir を渡したのに一度も基準として使われなかった
// ことを表す。検査の経路と生成の経路の両方で同じ文言を返すために切り出す。
var errCurrentDirUnused = errors.New(
	"-current-dir を指定しましたが、パスがすべて絶対なので使われません (どちらか一方にしてください)")

// 次の 3 つは、テストがエラーの種類を文言の部分一致ではなく errors.Is で
// 識別できるようにするための番兵。文言で見ると、挙動を変えないメッセージの
// 書き換えでテストが落ちる一方、別の検査が代わりに立てたエラーの文言に
// 同じ語が含まれていると、検査が失われたことに気づけない。
var (
	// errRecordDirRequired は -record-dir が省略されたことを表す。
	errRecordDirRequired = errors.New("-record-dir は必須です (検査する記録の置き場を指定する)")
	// errEmptyPath は、パスを取るフラグに空文字が明示指定されたことを表す。
	// どのフラグかは包んだ文言が示す。
	errEmptyPath = errors.New("空のパスが指定されました")
	// errFlagUnusedWithInstallWrapper は、生成の経路で使われないフラグが
	// -install-wrapper と併記されたことを表す。
	errFlagUnusedWithInstallWrapper = errors.New("-install-wrapper と併用できません")
	// errPathMissing は、明示した在り処 (記録の置き場・判定フロー) が実在しない
	// ことを表す。どれが無いかは stderr に並べた報告の行が示す。
	errPathMissing = errors.New("指定した在り処が存在しません")
)

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
		// CLAUDE_PLUGIN_ROOT は -current-dir の基準を使わないので、そちらを案内しても
		// 直らない。直すべきは環境変数の側だと言う。
		if flagName == "CLAUDE_PLUGIN_ROOT" {
			return "", false, fmt.Errorf(
				"%s が相対パスです。絶対パスを設定してください: %s", flagName, p)
		}
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
