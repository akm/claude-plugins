package main

import (
	"errors"
	"fmt"
	"regexp"
	"strconv"
	"strings"
	"unicode"
)

// marker は、HTML に書いたマークのコメント 1 つ。kind が "patch" なら run・problem・option で記録 YAML の
// 案のパッチを、"commit" なら sha でコミットを指す。
type marker struct {
	kind    string
	run     int
	problem string
	option  string
	sha     string
}

// markerRe は、マークの候補になるコメント。review-triage-diff で始まるコメントはすべて対象にし (直後に空白が
// 無いものも含む)、形の検査は関数 parseMarker が行う。形の誤ったマークを、マークでないコメントとして残さないため。
var markerRe = regexp.MustCompile(`<!--(\s*review-triage-diff[\s\S]*?)-->`)

// markerStartRe は、マークの始まり。この数が markerRe の一致の数と違えば、閉じ --> の無いマークがある
var markerStartRe = regexp.MustCompile(`<!--\s*review-triage-diff`)

var (
	patchRe  = regexp.MustCompile(`^patch run=([0-9]+) problem=(\S+) option=(\S+)$`)
	commitRe = regexp.MustCompile(`^commit ([0-9a-f]{4,40})$`)
	// headEndRe は </head> を大文字と小文字を区別せずに探す。元の文字列に当てるので、見つけた位置で
	// 元の文字列を切れる。strings.ToLower で変えた文字列の位置は、小文字にするとバイト数が変わる文字
	// (ケルビン記号 U+212A など) があると、元の文字列の位置と一致しない
	headEndRe = regexp.MustCompile(`(?i)</head>`)
)

// parseMarker は、コメントの中身 (<!-- と --> の間) をマークとして読む。
func parseMarker(body string) (marker, error) {
	s := strings.TrimSpace(body)
	rest, ok := strings.CutPrefix(s, "review-triage-diff")
	// review-triage-diff の直後には空白を求める (review-triage-diffpatch のような書き誤りをエラーにする)
	if ok && rest != "" && !unicode.IsSpace([]rune(rest)[0]) {
		ok = false
	}
	rest = strings.TrimSpace(rest)
	if !ok || rest == "" {
		return marker{}, fmt.Errorf("マークの形が違います: <!--%s-->", body)
	}
	rest = strings.Join(strings.Fields(rest), " ")
	if m := patchRe.FindStringSubmatch(rest); m != nil {
		run, err := strconv.Atoi(m[1])
		if err != nil || run < 1 {
			return marker{}, fmt.Errorf("マークの回番号は 1 以上の整数で書いてください: <!--%s-->", body)
		}
		return marker{kind: "patch", run: run, problem: m[2], option: m[3]}, nil
	}
	if m := commitRe.FindStringSubmatch(rest); m != nil {
		return marker{kind: "commit", sha: m[1]}, nil
	}
	return marker{}, fmt.Errorf("マークの形が違います (patch run=<回番号> problem=<problem_id> option=<ラベル> か commit <SHA>): <!--%s-->", body)
}

// shower は、コミットの差分を返すもの。本番では gitRunner、テストでは偽物を使う。
type shower interface {
	show(sha string) (string, error)
}

type sources struct {
	record *record
	git    shower
}

// styleID は、ツールが入れる <style> の id。既にあれば入れない。
const styleID = "rt-diff-style"

// fill は、HTML のマークをすべて差分の HTML に置き換え、</head> の前に <style> を入れた HTML を返す。
// 1 つでも置き換えられないマークがあれば、すべての理由をまとめてエラーにする。
func fill(html string, src sources) (string, error) {
	var errs []error
	if starts, closed := len(markerStartRe.FindAllStringIndex(html, -1)), len(markerRe.FindAllStringIndex(html, -1)); starts != closed {
		errs = append(errs, fmt.Errorf("閉じ --> の無いマークがあります (マークの始まり %d 個に対し、閉じたマーク %d 個)", starts, closed))
	}
	out := markerRe.ReplaceAllStringFunc(html, func(c string) string {
		body := markerRe.FindStringSubmatch(c)[1]
		m, err := parseMarker(body)
		if err != nil {
			errs = append(errs, err)
			return c
		}
		diff, err := src.diff(m)
		if err != nil {
			errs = append(errs, err)
			return c
		}
		return renderDiff(diff)
	})
	if !strings.Contains(out, `id="`+styleID+`"`) {
		loc := headEndRe.FindStringIndex(out)
		if loc == nil {
			errs = append(errs, errors.New("HTML に </head> がありません (色分けの <style> を入れる位置が無い)"))
		} else {
			out = out[:loc[0]] + diffStyle + out[loc[0]:]
		}
	}
	if len(errs) > 0 {
		return "", errors.Join(errs...)
	}
	return out, nil
}

func (s sources) diff(m marker) (string, error) {
	switch m.kind {
	case "patch":
		return s.record.patch(m)
	case "commit":
		return s.git.show(m.sha)
	}
	return "", fmt.Errorf("マークの種類が違います: %s", m.kind)
}
