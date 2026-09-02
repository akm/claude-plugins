// record.go はレビュー指摘のトリアージ記録 (docs/review-triages/*.yaml) の
// スキーマと、生成サマリ (*.md) の鮮度を検査する (review-triage-record)。
//
// 記録の正本は YAML で、件数の集計・累計は人が書かず、サマリ生成が計算する。
// 1 回目の試行 (claude/review-triage-skill-bf7714) では手書きの累計・ピン値の
// 誤りが指摘の約 3 分の 1 を占め、書かせて検算する検査は「正しい訂正手順が
// 偽赤になる」穴を生んだ。数えるものを書かせないことで、この類を発生源から消す。
// スキーマの意味の正本は docs/review-triages/README.md。
package main

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"gopkg.in/yaml.v3"
)

// reviewTriageDir はトリアージの記録の置き場。この変数が唯一の定義 —
// 別のリテラルを増やすと、移設のとき片方だけ更新されて検査が黙って外れる。
//
// 既定は docs/review-triages/ で、-record-dir で上書きできる (リポジトリごとに
// 置き場が違うため)。表記の揺れ (".", "./rec", "rec//") は inReviewTriageDir が
// path.Dir どうしの比較で吸収するので、この値の末尾のスラッシュの有無は問わない。
var reviewTriageDir = "docs/review-triages/"

// summaryCommand はサマリの再生成手段を利用者へ案内するときに使う文字列。
// エラーの文言と、生成サマリの 1 行目に埋まる。
//
// 再生成の手段はリポジトリごとに違う (Makefile のターゲット・-install-wrapper で
// 生成したラッパー・go run の直呼び) ので、特定のコマンド名を焼き込まない。
// 既定は「このツール自身をどう呼んでいるかに依らない」一般的な言い方にして、
// -summary-command で利用側の実際の呼び出し方を渡せるようにする
// (-install-wrapper 経由なら、生成時にラッパー自身のリポジトリ相対パスを
// 案内として焼き込む。値の決め方は resolveInputs)。
//
// この値は生成サマリの 1 行目としてコミットされるため、変えると既存サマリの
// 鮮度検査に差分が出る。再生成で吸収する。
//
// 既定値は定数に分ける。テストが既定を検査するとき、run が書き換えた後の
// 変数ではなく定数を読めるようにするため。
const defaultSummaryCommand = "triagecheck -write-summary"

var summaryCommand = defaultSummaryCommand

// inReviewTriageDir は f が記録の置き場の直下にあるかを返す。
//
// 文字列の接頭辞ではなくディレクトリどうしを比較する。一覧側 (listReviewTriageFiles)
// は path.Join でパスを clean するため、置き場の表記だけを整えて接頭辞で照合すると
// "." や "./rec" や "rec//" で一致せず、検査が 1 件も走らないまま緑になった。
// 両辺を path.Clean に通せば、どちらの表記でも同じ判定になる。
func inReviewTriageDir(f string) bool {
	return path.Dir(f) == path.Clean(reviewTriageDir)
}

// --- スキーマ (意味の正本は docs/review-triages/README.md) ---

type recordDoc struct {
	Runs []recordRun `yaml:"runs"`
}

type recordRun struct {
	Date     string          `yaml:"date"`
	Skill    string          `yaml:"skill"`
	RunID    string          `yaml:"run_id"`
	Model    string          `yaml:"model"`
	Level    string          `yaml:"level"`
	Scope    string          `yaml:"scope"`
	Head     string          `yaml:"head"`
	Findings []recordFinding `yaml:"findings"`
	Plans    []recordPlan    `yaml:"plans"`
	Notes    string          `yaml:"notes"`
}

type recordFinding struct {
	ID              int               `yaml:"id"`
	File            string            `yaml:"file"`
	Line            int               `yaml:"line"`
	Summary         string            `yaml:"summary"`
	Category        string            `yaml:"category"`
	Audience        string            `yaml:"audience"`
	AudienceInitial string            `yaml:"audience_initial"`
	Consequence     recordConsequence `yaml:"consequence"`
	PremiseCheck    recordPremise     `yaml:"premise_check"`
	GatesFired      []string          `yaml:"gates_fired"`
	Verdict         string            `yaml:"verdict"`
	VerdictReason   string            `yaml:"verdict_reason"`
	PlanRef         *recordPlanRef    `yaml:"plan_ref"`
	Attrs           map[string]any    `yaml:"attrs"`
}

type recordConsequence struct {
	Condition     string `yaml:"condition"`
	Who           string `yaml:"who"`
	What          string `yaml:"what"`
	Detectability string `yaml:"detectability"`
}

type recordPremise struct {
	Stages string `yaml:"stages"`
	Result string `yaml:"result"`
}

// recordPlanRef は採択の束ね先 (どの回のどの問題で直すか) の構造化参照。
// 回をまたいで同因の指摘を束ねたとき (並列レビューの運用)、対応関係を
// 自由記述でなく機械で辿れる形で残す。run は同じファイル内の 1 始まりの回番号。
type recordPlanRef struct {
	Run     int    `yaml:"run"`
	Problem string `yaml:"problem"`
}

type recordPlan struct {
	ProblemID  string `yaml:"problem_id"`
	Cause      string `yaml:"cause"`
	FindingIDs []int  `yaml:"finding_ids"`
	Approach   string `yaml:"approach"`
	// Investigation は修正方法を決める前の調査 (類似箇所・影響範囲) の範囲と結果。
	// 無いことは「未調査」を意味し、「調査済みで波及なし」は scope だけを書いた
	// 値で表す — この 2 つを記録上で区別するため、ポインタで有無を持つ。
	// 調査の手順の正本は review-triage-fix の references/investigation.md。
	Investigation *recordInvestigation `yaml:"investigation"`
	Options       string               `yaml:"options"`
	Order         int                  `yaml:"order"`
	DependsOn     []string             `yaml:"depends_on"`
	SHA           string               `yaml:"sha"`
	Status        string               `yaml:"status"`
	// AppliedExternalURL / Notes は status: done-external の反映先の記録。
	// リポジトリ外の成果物 (PR 本文・Issue のコメント・外部 Wiki など) への修正は
	// コミットが立たないので sha を書けない。URL を必須にすると、URL を持たない
	// 対象 (ローカルの外部ツール設定など) で同じ行き詰まりが起きるため、
	// 「URL か notes のどちらか」を必須にする。
	//
	// URL は sha ほど強い証拠にならない — sha はリポジトリがある限り不変だが、
	// PR 本文の URL は現在の本文を返すので、後から修正の前後を判別できない。
	// applied_external_url は「反映先を指すもの」であって「反映内容を固定するもの」
	// ではない。だから notes には反映を確認した方法を書く。
	AppliedExternalURL string `yaml:"applied_external_url"`
	Notes              string `yaml:"notes"`
}

// recordInvestigation は plans[].investigation — 直す前の調査の範囲と結果。
// scope は調べた範囲 (実行したコマンドと目で読んだ対象)、included は同じ原因の
// 別の現れとして問題に含めた箇所、excluded は見つけたが含めなかった箇所と理由。
// included / excluded が両方空なら「調べたが波及先は無かった」。
type recordInvestigation struct {
	Scope    string   `yaml:"scope"`
	Included []string `yaml:"included"`
	Excluded []string `yaml:"excluded"`
}

// recordAllowedKeys は階層ごとに許すキー。未知のキーは報告する — 旧いキー名の
// 残存が「エラーなしで空」に化ける型を避けるため。attrs だけは任意のキーを許す
// (上流固有の属性のパススルー)。
var recordAllowedKeys = map[string]map[string]bool{
	"トップレベル": {"runs": true},
	"実行": {"date": true, "skill": true, "run_id": true, "model": true, "level": true,
		"scope": true, "head": true, "findings": true, "plans": true, "notes": true},
	"指摘": {"id": true, "file": true, "line": true, "summary": true, "category": true,
		"audience": true, "audience_initial": true, "consequence": true, "premise_check": true,
		"gates_fired": true, "verdict": true, "verdict_reason": true, "plan_ref": true, "attrs": true},
	"束ね先":   {"run": true, "problem": true},
	"帰結":    {"condition": true, "who": true, "what": true, "detectability": true},
	"根拠の検証": {"stages": true, "result": true},
	"修正計画": {"problem_id": true, "cause": true, "finding_ids": true, "approach": true,
		"investigation": true, "options": true, "order": true, "depends_on": true, "sha": true,
		"status": true, "applied_external_url": true, "notes": true},
	"調査": {"scope": true, "included": true, "excluded": true},
}

// reviewTriageRecordProblems は docs/review-triages/ の記録 YAML を検査する。
// README.md は対象外。検査は (1) スキーマ (未知キー・必須キー・列挙値・参照の整合)、
// (2) サマリの鮮度 (YAML から生成した内容と *.md の一致)、(3) 孤児のサマリ。
func reviewTriageRecordProblems(files []string, readFile func(string) ([]byte, error)) []string {
	var problems []string
	fileSet := make(map[string]bool, len(files))
	for _, f := range files {
		fileSet[f] = true
	}
	var stems []string
	var mds []string
	for _, f := range files {
		if !inReviewTriageDir(f) || path.Base(f) == "README.md" {
			continue
		}
		switch {
		case strings.HasSuffix(f, ".yaml"):
			stems = append(stems, strings.TrimSuffix(f, ".yaml"))
		case strings.HasSuffix(f, ".md"):
			mds = append(mds, f)
		}
	}
	sort.Strings(stems)
	stemSet := make(map[string]bool, len(stems))
	for _, s := range stems {
		stemSet[s] = true
	}

	for _, stem := range stems {
		yf := stem + ".yaml"
		data, err := readFile(yf)
		if err != nil {
			problems = append(problems, fmt.Sprintf("%s: 読み込みに失敗しました: %v", yf, err))
			continue
		}
		ps, doc := recordProblemsInYAML(yf, data)
		problems = append(problems, ps...)

		// サマリの鮮度。スキーマに問題がある間は比較しない (直せば両方直る)。
		mdPath := stem + ".md"
		if !fileSet[mdPath] {
			problems = append(problems, fmt.Sprintf(
				"%s: サマリ %s がありません (`%s` で生成してコミットする)", yf, mdPath, summaryCommand))
			continue
		}
		if len(ps) > 0 || doc == nil {
			continue
		}
		want := renderReviewTriageSummaryDoc(yf, doc)
		got, err := readFile(mdPath)
		if err != nil {
			problems = append(problems, fmt.Sprintf("%s: 読み込みに失敗しました: %v", mdPath, err))
			continue
		}
		if string(got) != want {
			problems = append(problems, fmt.Sprintf(
				"%s: サマリが正本 (%s) と食い違っています (`%s` で再生成する)", mdPath, yf, summaryCommand))
		}
	}

	sort.Strings(mds)
	for _, md := range mds {
		if !stemSet[strings.TrimSuffix(md, ".md")] {
			problems = append(problems, fmt.Sprintf(
				"%s: 対応する YAML (正本) がありません。記録の正本は <ブランチ名>.yaml で、サマリはその生成物", md))
		}
	}
	return problems
}

// recordLineCommentProblems は行内コメント (LineComment) を持つノードを検出する。
// YAML の素のスカラーは半角スペースに続く # 以降をコメントとして落とすため、
// 引用符の無い値に # を書くと値が黙って切り詰められる (実測で cause が「PR」だけに
// なった)。切り詰められた分はパーサが LineComment として保持するので、そこを見る —
// 生テキストの正規表現で字句規則を再現する方式は、キーの形・空白・ブロックスカラー・
// 値全体のコメントと境界のたびに穴が開いた (列挙する検査は穴を再生産する既知の型)。
// ブロックスカラーの本文の # は内容でありコメントにならないので、構造的に区別される。
// 行頭コメント (HeadComment) は値を壊さないため対象にしない。
func recordLineCommentProblems(f string, root *yaml.Node) []string {
	var problems []string
	var walk func(n *yaml.Node)
	walk = func(n *yaml.Node) {
		if n.LineComment != "" {
			problems = append(problems, fmt.Sprintf(
				"%s:%d: 行内コメント (%q) は使えません — YAML は ' #' 以降をコメントとして落とし、値が黙って切り詰められる。値に # を含めるときは引用符で囲む",
				f, n.Line, n.LineComment))
		}
		for _, c := range n.Content {
			walk(c)
		}
	}
	walk(root)
	return problems
}

// recordProblemsInYAML は 1 ファイル分のスキーマ検査を行い、問題と (読めた場合の) 文書を返す。
func recordProblemsInYAML(f string, data []byte) ([]string, *recordDoc) {
	var root yaml.Node
	dec := yaml.NewDecoder(bytes.NewReader(data))
	if err := dec.Decode(&root); err != nil {
		// 空・コメントのみ・空白のみは EOF になる。生の文言では実際の状態が読めない。
		if errors.Is(err, io.EOF) {
			return []string{fmt.Sprintf("%s: 記録が空です (runs がありません)", f)}, nil
		}
		return []string{fmt.Sprintf("%s: YAML を解析できません: %v", f, err)}, nil
	}
	// 記録は単一ドキュメント。--- 区切りの 2 つ目以降は読まれずに消えるため、存在自体を弾く。
	var extra yaml.Node
	if err := dec.Decode(&extra); err == nil {
		return []string{fmt.Sprintf(
			"%s: --- 区切りの 2 つ目のドキュメントがあります — 記録は単一ドキュメントで、2 つ目以降は読まれず消える", f)}, nil
	} else if !errors.Is(err, io.EOF) {
		return []string{fmt.Sprintf("%s: 2 つ目のドキュメントの解析に失敗しました: %v", f, err)}, nil
	}
	if len(root.Content) == 0 ||
		(root.Content[0].Kind == yaml.ScalarNode && root.Content[0].Tag == "!!null") {
		// null・~・--- だけのファイルは null スカラーのルートとして解析され、
		// EOF にも空 Content にもならない。実質的に空なので同じ文言に揃える。
		return []string{fmt.Sprintf("%s: 記録が空です (runs がありません)", f)}, nil
	}
	problems := recordLineCommentProblems(f, &root)
	problems = append(problems, recordUnknownKeyProblems(f, root.Content[0])...)
	var doc recordDoc
	if err := root.Decode(&doc); err != nil {
		problems = append(problems, fmt.Sprintf("%s: スキーマに合いません: %v", f, err))
		return problems, nil
	}
	problems = append(problems, recordSemanticProblems(f, &doc)...)
	return problems, &doc
}

// recordNullSilentKeys は、値を省いて null にすると他のどの検査でも赤くならない
// 構造キー。キーの有無をポインタの nil で見る plan_ref / investigation は、
// 「キーを書いて値を省いた」(書きかけ・インデントの誤り) が「キーが無い」と
// 同一になり、書き手は書いたつもりのまま記録上は無い扱いになる (実測:
// investigation: だけの記録が検査 0 件でサマリにも出なかった)。
// consequence / premise_check の null は必須サブキーの欠落として既に報告されるので
// ここに含めない — 重ねると 1 つの書き忘れが複数の問題になる。
var recordNullSilentKeys = map[string]bool{"plan_ref": true, "investigation": true}

// recordUnknownKeyProblems は許可キー集合との突き合わせで未知のキーと、
// 値の無い構造キー (recordNullSilentKeys) を列挙する。
// 問題が見つかっても走査を続け、他の問題の報告を妨げない。
func recordUnknownKeyProblems(f string, n *yaml.Node) []string {
	var problems []string
	var walkMap func(n *yaml.Node, kind string)
	walkSeq := func(n *yaml.Node, kind string) {
		if n == nil || n.Kind != yaml.SequenceNode {
			return
		}
		for _, item := range n.Content {
			walkMap(item, kind)
		}
	}
	walkMap = func(n *yaml.Node, kind string) {
		if n == nil || n.Kind != yaml.MappingNode {
			return
		}
		allowed := recordAllowedKeys[kind]
		for i := 0; i+1 < len(n.Content); i += 2 {
			k, v := n.Content[i], n.Content[i+1]
			if !allowed[k.Value] {
				problems = append(problems, fmt.Sprintf(
					"%s:%d: %sに未知のキー %q。旧いキー名の残存か置き場の誤り (上流固有の属性は attrs へ) を疑う",
					f, k.Line, kind, k.Value))
				continue
			}
			if recordNullSilentKeys[k.Value] && v.Kind == yaml.ScalarNode && v.Tag == "!!null" {
				problems = append(problems, fmt.Sprintf(
					"%s:%d: %s の %s に値がありません。書くなら中身を書き、書かないならキーごと消す (値の無いキーは「無い」と同じに扱われ、書いたつもりの記録が黙って消える)",
					f, k.Line, kind, k.Value))
				continue
			}
			switch k.Value {
			case "runs":
				walkSeq(v, "実行")
			case "findings":
				walkSeq(v, "指摘")
			case "plans":
				walkSeq(v, "修正計画")
			case "consequence":
				walkMap(v, "帰結")
			case "premise_check":
				walkMap(v, "根拠の検証")
			case "plan_ref":
				walkMap(v, "束ね先")
			case "investigation":
				walkMap(v, "調査")
			}
		}
	}
	walkMap(n, "トップレベル")
	return problems
}

var recordDateRe = regexp.MustCompile(`^\d{4}-\d{2}-\d{2}$`)

// recordAudiences は被害者の列挙 (glossary のロール + 開発者)。設定 (.claude/review-triage.yaml)
// の audience と同じ値域。
var recordAudiences = map[string]bool{
	"operator": true, "admin": true, "provider": true, "developer": true,
}

// recordSemanticProblems は必須キー・列挙値・参照の整合を検査する。
func recordSemanticProblems(f string, doc *recordDoc) []string {
	var problems []string
	add := func(format string, args ...any) {
		problems = append(problems, f+": "+fmt.Sprintf(format, args...))
	}
	if len(doc.Runs) == 0 {
		add("runs がありません (実行が 1 つも無い)")
	}
	// 回ごとの問題 id の索引 (plan_ref の解決と被覆の検査に使う)。
	plansByRun := make([]map[string]bool, len(doc.Runs))
	for ri, run := range doc.Runs {
		plansByRun[ri] = map[string]bool{}
		for _, pl := range run.Plans {
			plansByRun[ri][pl.ProblemID] = true
		}
	}
	for ri, run := range doc.Runs {
		rn := fmt.Sprintf("runs[%d] (%s %s)", ri, run.Date, run.Skill)
		if !recordDateRe.MatchString(run.Date) {
			add("%s: date が YYYY-MM-DD ではありません: %q", rn, run.Date)
		}
		if run.Skill == "" {
			add("%s: skill がありません", rn)
		}
		if run.Model == "" {
			add("%s: model がありません (レビューを実行したモデルを必ず残す)", rn)
		}
		if run.Scope != "incremental" && run.Scope != "full" {
			add("%s: scope は incremental / full のいずれか: %q", rn, run.Scope)
		}
		if run.Head == "" {
			add("%s: head がありません (レビュー時点の短縮 SHA)", rn)
		}

		verdictByID := map[int]string{}
		for fi, fd := range run.Findings {
			fn := fmt.Sprintf("%s: findings[%d] (id %d)", rn, fi, fd.ID)
			if fd.ID <= 0 {
				add("%s: id は正の整数にする", fn)
			} else if _, dup := verdictByID[fd.ID]; dup {
				add("%s: id が同じ回の中で重複しています", fn)
			}
			verdictByID[fd.ID] = fd.Verdict
			for _, kv := range []struct{ key, val string }{
				{"file", fd.File}, {"summary", fd.Summary},
				{"category", fd.Category}, {"audience", fd.Audience},
			} {
				if kv.val == "" {
					add("%s: %s がありません", fn, kv.key)
				}
			}
			// audience の列挙。列挙外の値が黙って通ると D7 (被害者の判定) の入力が壊れる。
			if fd.Audience != "" && !recordAudiences[fd.Audience] {
				add("%s: audience は operator / admin / provider / developer のいずれか: %q", fn, fd.Audience)
			}
			if fd.AudienceInitial != "" && !recordAudiences[fd.AudienceInitial] {
				add("%s: audience_initial は operator / admin / provider / developer のいずれか: %q", fn, fd.AudienceInitial)
			}
			for _, kv := range []struct{ key, val string }{
				{"condition", fd.Consequence.Condition}, {"who", fd.Consequence.Who},
				{"what", fd.Consequence.What}, {"detectability", fd.Consequence.Detectability},
			} {
				if kv.val == "" {
					add("%s: consequence.%s がありません (帰結の 4 項目は必須)", fn, kv.key)
				}
			}
			switch fd.PremiseCheck.Stages {
			case "none", "A", "A+B":
			default:
				add("%s: premise_check.stages は none / A / A+B のいずれか: %q", fn, fd.PremiseCheck.Stages)
			}
			switch fd.PremiseCheck.Result {
			case "verified", "wrong", "unverifiable", "skipped":
			default:
				add("%s: premise_check.result は verified / wrong / unverifiable / skipped のいずれか: %q",
					fn, fd.PremiseCheck.Result)
			}
			if (fd.PremiseCheck.Stages == "none") != (fd.PremiseCheck.Result == "skipped") {
				add("%s: stages が none のときだけ result は skipped (stages %q / result %q)",
					fn, fd.PremiseCheck.Stages, fd.PremiseCheck.Result)
			}
			switch fd.Verdict {
			case "adopted", "held", "rejected":
			default:
				add("%s: verdict は adopted / held / rejected のいずれか: %q", fn, fd.Verdict)
			}
			if fd.VerdictReason == "" {
				add("%s: verdict_reason がありません (判定の経路をノード ID で書く)", fn)
			}
			if fd.PlanRef != nil {
				if fd.PlanRef.Run < 1 || fd.PlanRef.Run > len(doc.Runs) {
					add("%s: plan_ref の run %d は存在しません (回は 1〜%d)", fn, fd.PlanRef.Run, len(doc.Runs))
				} else if !plansByRun[fd.PlanRef.Run-1][fd.PlanRef.Problem] {
					add("%s: plan_ref の問題 %q は回 %d の plans にありません", fn, fd.PlanRef.Problem, fd.PlanRef.Run)
				}
			}
		}

		problemIDs := map[string]bool{}
		for _, pl := range run.Plans {
			if pl.ProblemID != "" && problemIDs[pl.ProblemID] {
				add("%s: problem_id %q が重複しています", rn, pl.ProblemID)
			}
			problemIDs[pl.ProblemID] = true
		}
		for pi, pl := range run.Plans {
			pn := fmt.Sprintf("%s: plans[%d] (%s)", rn, pi, pl.ProblemID)
			for _, kv := range []struct{ key, val string }{
				{"problem_id", pl.ProblemID}, {"cause", pl.Cause}, {"approach", pl.Approach},
			} {
				if kv.val == "" {
					add("%s: %s がありません", pn, kv.key)
				}
			}
			if len(pl.FindingIDs) == 0 {
				add("%s: finding_ids がありません (1 つ以上)", pn)
			}
			for _, id := range pl.FindingIDs {
				v, ok := verdictByID[id]
				if !ok {
					add("%s: finding_ids の %d は同じ回の findings にありません", pn, id)
				} else if v != "adopted" {
					add("%s: finding_ids の %d は採択 (adopted) ではありません (verdict %s)。修正計画は採択だけを束ねる", pn, id, v)
				}
			}
			// externalOnly は done-external 専用のキーが空であることを検査する。
			// スキーマ表が「done-external のときだけ書く」と定める排他で、書かせる
			// だけで検査しないと、done でコミット済みなのに外部 URL が残る記録が
			// 黙って通る (sha の排他は前から検査されていた)。列挙外の status では
			// 呼ばない — default が列挙違反を報告するので、そこへ重ねると 1 つの
			// 誤字が 2 つの問題になる。
			externalOnly := func() {
				for _, kv := range []struct{ key, val string }{
					{"applied_external_url", pl.AppliedExternalURL}, {"notes", pl.Notes},
				} {
					if kv.val != "" {
						add("%s: status %s なのに %s %q があります。%s は status done-external 専用",
							pn, pl.Status, kv.key, kv.val, kv.key)
					}
				}
			}
			switch pl.Status {
			case "pending", "awaiting-human":
				externalOnly()
				if pl.SHA != "" {
					add("%s: status %s なのに sha %q があります。直したのなら status: done にする", pn, pl.Status, pl.SHA)
				}
				if pl.Status == "awaiting-human" && pl.Options == "" {
					add("%s: status awaiting-human には options (選択肢とトレードオフ) が必須", pn)
				}
			case "done":
				externalOnly()
				if pl.SHA == "" {
					add("%s: status done には sha (短縮 SHA) が必須。リポジトリ外の成果物への反映で"+
						"コミットが立たないなら status: done-external にする", pn)
				}
			case "done-external":
				// コミットが無いのだから sha を書けるはずがない。書けているなら
				// リポジトリ内の修正なので done が正しい。
				if pl.SHA != "" {
					add("%s: status done-external なのに sha %q があります。コミットがあるなら status: done にする", pn, pl.SHA)
				}
				if pl.AppliedExternalURL == "" && pl.Notes == "" {
					add("%s: status done-external には applied_external_url (反映先の URL) か "+
						"notes (反映先と、反映を確認した方法) のどちらかが必須", pn)
				}
			default:
				add("%s: status は pending / awaiting-human / done / done-external のいずれか: %q", pn, pl.Status)
			}
			// 調査は任意 (無ければ未調査) だが、書くなら範囲 (scope) が要る。
			// 範囲の無い調査は「どこまで調べたか」を残さず、未調査と区別できない。
			if inv := pl.Investigation; inv != nil {
				if strings.TrimSpace(inv.Scope) == "" {
					add("%s: investigation.scope がありません (調べた範囲 — 実行したコマンドと目で読んだ対象)。範囲を書かない調査は未調査と区別できない", pn)
				}
				for _, kv := range []struct {
					key  string
					vals []string
				}{{"included", inv.Included}, {"excluded", inv.Excluded}} {
					for i, v := range kv.vals {
						if strings.TrimSpace(v) == "" {
							add("%s: investigation.%s[%d] が空です (箇所を書くか要素を消す)", pn, kv.key, i)
						}
					}
				}
			}
			for _, d := range pl.DependsOn {
				if d == pl.ProblemID {
					add("%s: depends_on が自己参照しています", pn)
					continue
				}
				if !problemIDs[d] {
					add("%s: depends_on の %q は同じ回の plans にありません", pn, d)
				}
			}
		}
		// 被覆: 採択は自回の plans か plan_ref で覆われる。覆われない採択は、
		// 対処しないまま黙って消える。
		//
		// 免除するのは「plans がまだ無い最後の回」だけ — fix 前の状態を指す。
		// 後続の回が追記された時点でその回はもう fix 前ではないので、免除を解く。
		// 全回で len(run.Plans) > 0 を条件にしていた頃は、plans を書かないまま
		// 次の回に進んだ過去の回の採択が、検査からも review-triage-fix (最後の回の
		// findings しか見ない) からも見えなくなり、黙って消えていた。
		isLastRun := ri == len(doc.Runs)-1
		if len(run.Plans) > 0 || !isLastRun {
			covered := map[int]bool{}
			for _, pl := range run.Plans {
				for _, id := range pl.FindingIDs {
					covered[id] = true
				}
			}
			for _, fd := range run.Findings {
				if fd.Verdict != "adopted" || covered[fd.ID] {
					continue
				}
				if fd.PlanRef != nil {
					continue // 参照自体の実在は上の finding ループで検査済み
				}
				add("%s: findings id %d: 採択が修正計画に載っていません (自回の plans にも plan_ref にも無い)", rn, fd.ID)
			}
		}
		for _, cycle := range recordDependsOnCycles(run.Plans) {
			add("%s: depends_on が循環しています (%s)。順序が定まらない — 同じ原因の 1 問題に束ねるべきものを分けていないかを疑う",
				rn, strings.Join(cycle, " → "))
		}
	}
	return problems
}

// recordDependsOnCycles は plans の depends_on の循環を検出する。自己参照は
// 個別に報告するのでここでは扱わない。同じ循環は 1 度だけ返す。
func recordDependsOnCycles(plans []recordPlan) [][]string {
	deps := make(map[string][]string, len(plans))
	for _, pl := range plans {
		for _, d := range pl.DependsOn {
			if d != pl.ProblemID {
				deps[pl.ProblemID] = append(deps[pl.ProblemID], d)
			}
		}
	}
	const (
		visiting = 1
		done     = 2
	)
	state := map[string]int{}
	var cycles [][]string
	var stack []string
	var visit func(id string)
	visit = func(id string) {
		state[id] = visiting
		stack = append(stack, id)
		for _, d := range deps[id] {
			switch state[d] {
			case 0:
				visit(d)
			case visiting:
				// stack の d 以降が循環。
				for i, s := range stack {
					if s == d {
						cycle := append(append([]string{}, stack[i:]...), d)
						cycles = append(cycles, cycle)
						break
					}
				}
			}
		}
		stack = stack[:len(stack)-1]
		state[id] = done
	}
	for _, pl := range plans {
		if state[pl.ProblemID] == 0 {
			visit(pl.ProblemID)
		}
	}
	return cycles
}

// --- サマリの生成 ---

// renderReviewTriageSummary は記録 YAML から人が読むサマリ (Markdown) を生成する。
// 件数はすべてここで計算する — 人が書いた集計をどこからも読まない。
func renderReviewTriageSummary(yamlPath string, data []byte) (string, error) {
	var doc recordDoc
	if err := yaml.Unmarshal(data, &doc); err != nil {
		return "", fmt.Errorf("%s: YAML を読めません: %w", yamlPath, err)
	}
	return renderReviewTriageSummaryDoc(yamlPath, &doc), nil
}

func renderReviewTriageSummaryDoc(yamlPath string, doc *recordDoc) string {
	base := path.Base(yamlPath)
	stem := strings.TrimSuffix(base, ".yaml")
	var b strings.Builder
	fmt.Fprintf(&b, "<!-- 生成物。手で編集しない。正本は %s — `%s` で再生成する。 -->\n\n", base, summaryCommand)
	fmt.Fprintf(&b, "# %s のトリアージ記録\n\n", stem)
	fmt.Fprintf(&b, "正本は [%s](%s)。読み方と収束の目安は [README](README.md)。\n\n", base, base)

	b.WriteString("## 推移\n\n")
	b.WriteString("| 回 | 日付 | スキル | model | scope | 全件 | 採択 | 保留 | 却下 |\n")
	b.WriteString("| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n")
	for i, run := range doc.Runs {
		adopted, held, rejected := 0, 0, 0
		for _, fd := range run.Findings {
			switch fd.Verdict {
			case "adopted":
				adopted++
			case "held":
				held++
			case "rejected":
				rejected++
			}
		}
		// 自由文字列の欄 (skill・model など) は recordCell で無害化する — 縦棒が
		// 入ると桁がずれ、偽の数字が集計値の手前に並ぶ (列挙で守られない欄は検査も
		// 捕まえない)。
		fmt.Fprintf(&b, "| %d | %s | `%s` | `%s` | %s | %d | %d | %d | %d |\n",
			i+1, recordCell(run.Date), recordCell(run.Skill), recordCell(run.Model),
			recordCell(run.Scope), len(run.Findings), adopted, held, rejected)
	}

	for i, run := range doc.Runs {
		fmt.Fprintf(&b, "\n## 回 %d: %s `%s`", i+1, recordCell(run.Date), recordCell(run.Skill))
		if run.RunID != "" {
			fmt.Fprintf(&b, " (%s)", recordCell(run.RunID))
		}
		b.WriteString("\n\n")
		fmt.Fprintf(&b, "- HEAD `%s` / model `%s` / scope %s",
			recordCell(run.Head), recordCell(run.Model), recordCell(run.Scope))
		if run.Level != "" {
			b.WriteString(" / level " + recordCell(run.Level))
		}
		b.WriteString("\n\n")

		b.WriteString("| # | 指摘 | 分類 / 被害者 | 帰結 (条件 / 何が / 気づけるか) | 検証 | ゲート | 判定 |\n")
		b.WriteString("| --- | --- | --- | --- | --- | --- | --- |\n")
		for _, fd := range run.Findings {
			b.WriteString(recordRow(renderFindingCells(fd)))
		}

		if len(run.Plans) > 0 {
			b.WriteString("\n### 修正計画\n\n")
			// 最終列の見出しは「証拠」— コミットの SHA とリポジトリ外の反映先の URL の
			// 2 つの型を取る (renderPlanCells の証拠の欄)。見出しを SHA のままにすると、
			// done-external の行に出る URL を SHA として読ませることになる。
			b.WriteString("| 問題 | 原因 | 含む指摘 | 修正方法 | 順 | 状態 | 証拠 (SHA / URL) |\n")
			b.WriteString("| --- | --- | --- | --- | --- | --- | --- |\n")
			for _, pl := range run.Plans {
				b.WriteString(recordRow(renderPlanCells(pl)))
			}
			for _, pl := range run.Plans {
				if pl.Status == "awaiting-human" {
					fmt.Fprintf(&b, "\n- **%s は選択待ち (人間が選ぶ)**: %s\n", recordCell(pl.ProblemID), recordCell(pl.Options))
				}
			}
			// リポジトリ外への反映は、コミットを辿っても内容を確かめられない。
			// 反映を確認した方法 (notes) を表の外に出して、後から追えるようにする。
			for _, pl := range run.Plans {
				if pl.Status == "done-external" && pl.Notes != "" {
					fmt.Fprintf(&b, "\n- **%s はリポジトリ外へ反映済み**: %s\n", recordCell(pl.ProblemID), recordCell(pl.Notes))
				}
			}
			// 直す前の調査の範囲と結果。次のレビューで同じ型の指摘が来たとき、前回の
			// 調査漏れ (範囲の外だった) か新規かを判別する材料なので表の外に出す。
			// 無い問題は出さない — 無いことが「未調査」の表現。
			for _, pl := range run.Plans {
				if pl.Investigation != nil {
					fmt.Fprintf(&b, "\n- **%s の調査**: %s\n", recordCell(pl.ProblemID), renderInvestigation(pl.Investigation))
				}
			}
		}

		if run.Notes != "" {
			b.WriteString("\n### 観察\n\n" + strings.TrimRight(run.Notes, "\n") + "\n")
		}
	}
	return b.String()
}

// recordRow はセルの列から表の 1 行を組み立てる。
func recordRow(cells []string) string {
	return "| " + strings.Join(cells, " | ") + " |\n"
}

// renderFindingCells は指摘 1 件の表のセル列を返す。行を 1 つの書式文字列で
// 組み立てると、テストがセル単位で分岐を検証できず、存在確認のアサーションが
// 別のセルへの偶然一致で通り抜ける (実測で 3 度起きた型)。
func renderFindingCells(fd recordFinding) []string {
	loc := fd.File
	if fd.Line > 0 {
		loc = fmt.Sprintf("%s:%d", fd.File, fd.Line)
	}
	aud := fd.Audience
	if fd.AudienceInitial != "" && fd.AudienceInitial != fd.Audience {
		aud = fd.AudienceInitial + " → " + fd.Audience
	}
	premise := "対象外"
	if fd.PremiseCheck.Stages != "none" {
		premise = fd.PremiseCheck.Stages + ": " + fd.PremiseCheck.Result
	}
	gates := "—"
	if len(fd.GatesFired) > 0 {
		gates = strings.Join(fd.GatesFired, ", ")
	}
	return []string{
		strconv.Itoa(fd.ID),
		"`" + recordCell(loc) + "` " + recordCell(fd.Summary),
		recordCell(fd.Category) + " / " + recordCell(aud),
		recordCell(fd.Consequence.Condition) + " / " + recordCell(fd.Consequence.What) +
			" / " + recordCell(fd.Consequence.Detectability),
		premise,
		recordCell(gates),
		renderVerdictCell(fd),
	}
}

// renderVerdictCell は判定セル (判定 — 経路。束ね先があれば添える) を返す。
func renderVerdictCell(fd recordFinding) string {
	cell := recordVerdictJa(fd.Verdict) + " — " + recordCell(fd.VerdictReason)
	if fd.PlanRef != nil {
		cell += fmt.Sprintf(" (束ね先: 回 %d の %s)", fd.PlanRef.Run, recordCell(fd.PlanRef.Problem))
	}
	return cell
}

// renderPlanCells は修正計画 1 件の表のセル列を返す。
func renderPlanCells(pl recordPlan) []string {
	var ids []string
	for _, id := range pl.FindingIDs {
		ids = append(ids, "#"+strconv.Itoa(id))
	}
	order := "—"
	if pl.Order > 0 {
		order = strconv.Itoa(pl.Order)
	}
	if len(pl.DependsOn) > 0 {
		order += " (" + recordCell(strings.Join(pl.DependsOn, ", ")) + " の後)"
	}
	// 証拠の欄。コミットがあれば SHA、リポジトリ外への反映なら反映先の URL を出す。
	// URL をコードスパンで包むのは、記録が引用を含む文書で、リンク記法にすると
	// リンク切れ検査に引っかかるため (record-schema.md の「表記の機械検査から外す」)。
	sha := "—"
	switch {
	case pl.SHA != "":
		sha = "`" + recordCell(pl.SHA) + "`"
	case pl.AppliedExternalURL != "":
		sha = "`" + recordCell(pl.AppliedExternalURL) + "`"
	}
	return []string{
		recordCell(pl.ProblemID),
		recordCell(pl.Cause),
		strings.Join(ids, " "),
		recordCell(pl.Approach),
		order,
		recordStatusJa(pl.Status),
		sha,
	}
}

// renderInvestigation は調査の範囲と結果を 1 行にする。included / excluded が
// 両方空なら「波及先なし」と明示する — 範囲だけ出すと、調べて無かったのか
// 結果を書き忘れたのかが読めない。
func renderInvestigation(inv *recordInvestigation) string {
	s := "範囲: " + recordCell(inv.Scope)
	if len(inv.Included) == 0 && len(inv.Excluded) == 0 {
		return s + " / 波及先なし"
	}
	join := func(items []string) string {
		cells := make([]string, 0, len(items))
		for _, it := range items {
			cells = append(cells, recordCell(it))
		}
		return strings.Join(cells, "; ")
	}
	if len(inv.Included) > 0 {
		s += " / 含めた: " + join(inv.Included)
	}
	if len(inv.Excluded) > 0 {
		s += " / 含めなかった: " + join(inv.Excluded)
	}
	return s
}

// recordCell は表のセルに入れる文字列を 1 行に整える。
func recordCell(s string) string {
	return strings.NewReplacer("|", "\\|", "\n", " ").Replace(strings.TrimSpace(s))
}

func recordVerdictJa(v string) string {
	switch v {
	case "adopted":
		return "**採択**"
	case "held":
		return "**保留**"
	case "rejected":
		return "**却下**"
	}
	return v
}

func recordStatusJa(s string) string {
	switch s {
	case "pending":
		return "未着手"
	case "awaiting-human":
		return "**選択待ち**"
	case "done":
		return "済"
	case "done-external":
		return "済 (リポジトリ外)"
	}
	return s
}

// errRecordDirMissing は「明示指定した置き場が無い」ことを表す番兵。呼び出し側が
// errors.Is で見分け、他の検査を続けたうえで報告に積めるようにする — 即座に返すと
// 判定フローの検査に到達せず、片方を直して再実行するまでもう一方の不在を知れない。
// 権限・I/O のエラーは続行しても意味が無いので、これとは区別して返す。
var errRecordDirMissing = errors.New(
	"-record-dir に指定された置き場が存在しません (記録の検査が行われないまま緑になるため報告する)")

// listReviewTriageFiles は記録の置き場のファイル (yaml と md) をファイルシステムから
// 列挙する。doccheck の他の検査は git 追跡ファイルを対象にするが、記録は
// 「これから追跡される」ファイルなので、追跡前でも検査・生成の対象に入れる —
// git add 前の最初の記録が素通りする穴 (0 件マッチで黙って緑の型) を塞ぐため。
//
// ディレクトリが無いときの扱いは explicit で分かれる。置き場を明示的に渡すこと
// (-record-dir) は「そこを検査せよ」という意思表示なので、不在はエラーにする。
// 未指定 (既定値) のまま不在なのはスキル未導入の正常な状態で、nil を返す。
// 判定を分けないと、置き場を移した時点で検査が黙って無効になる
// (judgment_flow.go の explicit と同じ理由)。
func listReviewTriageFiles(dir string, explicit bool) ([]string, error) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		// ディレクトリが無いのはスキル未導入の正常な状態 (明示指定のときを除く)。
		// それ以外 (権限・I/O) のエラーを「記録 0 件」に潰すと、守りが黙って外れる。
		// 判定は judgment_flow.go と同じ errors.Is に揃える (ラップされたエラーも
		// 正しく分類するため)。
		if errors.Is(err, fs.ErrNotExist) {
			if explicit {
				return nil, errRecordDirMissing
			}
			return nil, nil
		}
		return nil, err
	}
	var files []string
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		name := e.Name()
		// README.* は記録ではない — README.md は手書きの規範文書で、README.yaml を
		// 記録と見なすと生成器が README.md を上書きしてしまう (検査側の除外と対称にする)。
		if strings.TrimSuffix(strings.TrimSuffix(name, ".md"), ".yaml") == "README" {
			continue
		}
		if strings.HasSuffix(name, ".yaml") || strings.HasSuffix(name, ".md") {
			files = append(files, path.Join(dir, name))
		}
	}
	sort.Strings(files)
	return files, nil
}

// writeReviewTriageSummaries は記録 YAML すべてについてサマリを再生成する
// (-write-summary の経路)。explicit は listReviewTriageFiles と同じ意味 —
// 明示指定した置き場が無いなら、0 件生成して黙って成功させない。
func writeReviewTriageSummaries(dir string, explicit bool) error {
	files, err := listReviewTriageFiles(dir, explicit)
	if err != nil {
		return err
	}
	for _, f := range files {
		if !strings.HasSuffix(f, ".yaml") {
			continue
		}
		data, err := os.ReadFile(f)
		if err != nil {
			return err
		}
		summary, err := renderReviewTriageSummary(f, data)
		if err != nil {
			return err
		}
		mdPath := strings.TrimSuffix(f, ".yaml") + ".md"
		if err := os.WriteFile(mdPath, []byte(summary), 0o644); err != nil {
			return err
		}
		fmt.Printf("生成: %s (正本: %s)\n", mdPath, f)
	}
	return nil
}
