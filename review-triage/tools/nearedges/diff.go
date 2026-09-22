package main

import (
	"bufio"
	"fmt"
	"io"
	"regexp"
	"strconv"
	"strings"
)

// change は unified diff から読んだ変更 1 つ。Line は変更後 (post-image) の行番号。
// 追加・変更した行は Text にその行の文を持つ。削除だけの変更は、削除の直後の位置を
// Line に持ち Deleted が真になる (読み直す範囲を決めるのに位置だけが要る)。
type change struct {
	Line    int
	Text    string
	Deleted bool
}

var hunkHeader = regexp.MustCompile(`^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@`)

// parseUnifiedDiff は unified diff (git diff の出力) を読み、ファイルごとの変更行を
// 変更後の行番号で返す。キーは "+++ b/" の後のパス。
func parseUnifiedDiff(r io.Reader) (map[string][]change, error) {
	out := map[string][]change{}
	sc := bufio.NewScanner(r)
	sc.Buffer(make([]byte, 1024*1024), 16*1024*1024)
	file := ""
	post := 0
	inHunk := false
	deletedRun := false
	flushDeleted := func() {
		if deletedRun && file != "" {
			out[file] = append(out[file], change{Line: post, Deleted: true})
			deletedRun = false
		}
	}
	for sc.Scan() {
		line := sc.Text()
		switch {
		case strings.HasPrefix(line, "+++ "):
			flushDeleted()
			file = strings.TrimPrefix(strings.TrimPrefix(line, "+++ "), "b/")
			if file == "/dev/null" {
				file = ""
			}
			inHunk = false
		case strings.HasPrefix(line, "--- "), strings.HasPrefix(line, "diff --git "), strings.HasPrefix(line, "index "):
			flushDeleted()
			inHunk = false
		case strings.HasPrefix(line, "@@ "):
			flushDeleted()
			m := hunkHeader.FindStringSubmatch(line)
			if m == nil {
				return nil, fmt.Errorf("hunk の見出しを読めません: %q", line)
			}
			n, err := strconv.Atoi(m[1])
			if err != nil {
				return nil, fmt.Errorf("hunk の見出しの行番号を読めません: %q", line)
			}
			post = n
			inHunk = true
		case !inHunk || file == "":
			// hunk の外の行 (diff の前置きなど) は読まない。
		case strings.HasPrefix(line, "+"):
			deletedRun = false
			out[file] = append(out[file], change{Line: post, Text: line[1:]})
			post++
		case strings.HasPrefix(line, "-"):
			deletedRun = true
		case strings.HasPrefix(line, "\\"):
			// "\ No newline at end of file" は行ではない。
		default:
			flushDeleted()
			post++
		}
	}
	flushDeleted()
	if err := sc.Err(); err != nil {
		return nil, err
	}
	return out, nil
}
