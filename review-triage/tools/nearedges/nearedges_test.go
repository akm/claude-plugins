package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// fixtureMD は構造 (見出し・表・箇条書き・段落・リンク・コードフェンス) を一通り持つ文書。
const fixtureMD = `# 題

## 前置き

段落 1。

## 表の節

導入の段落。[準備の表](#準備の表) を参照する。

| 手順 | 必要とするもの |
| --- | --- |
| a | x |
| b | y |

表の後の段落。

### 準備の表

- 項目 1
- 項目 2
    - 子項目
- 項目 3

箇条書きの後。正本は [表の節](#表の節)。

## 別の節

` + "```" + `sh
echo "# 見出しではない"
` + "```" + `

最後の段落。件数は 3 つ。必ず通る。
`

// unifiedDiff は fixtureMD の「| b | y |」の行と「- 項目 2」の行を変え、
// 「最後の段落」に 1 行足した差分 (post-image の行番号は fixtureMD と同じ位置)。
const unifiedDiff = `diff --git a/docs/a.md b/docs/a.md
index 1111111..2222222 100644
--- a/docs/a.md
+++ b/docs/a.md
@@ -13,3 +13,3 @@
 | a | x |
-| b | y0 |
+| b | y |

@@ -20,3 +20,3 @@
 - 項目 1
-- 項目 2 (旧)
+- 項目 2
     - 子項目
@@ -33,1 +33,1 @@
-最後の段落。
+最後の段落。件数は 3 つ。必ず通る。
`

func writeFixture(t *testing.T) string {
	t.Helper()
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, "docs"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "docs/a.md"), []byte(fixtureMD), 0o644); err != nil {
		t.Fatal(err)
	}
	return root
}

func TestParseUnifiedDiffPostLines(t *testing.T) {
	changes, err := parseUnifiedDiff(strings.NewReader(unifiedDiff))
	if err != nil {
		t.Fatal(err)
	}
	got := changes["docs/a.md"]
	if len(got) != 3 {
		t.Fatalf("変更行が 3 つのはず: %+v", got)
	}
	want := []int{14, 21, 33}
	for i, c := range got {
		if c.Line != want[i] {
			t.Errorf("%d 番目の変更行の post-image の行番号: got %d want %d", i, c.Line, want[i])
		}
	}
	if !strings.Contains(got[2].Text, "必ず通る") {
		t.Errorf("追加した行の文が取れていない: %q", got[2].Text)
	}
}

func TestParseUnifiedDiffDeletionOnlyHunkKeepsPosition(t *testing.T) {
	d := "diff --git a/x.md b/x.md\n--- a/x.md\n+++ b/x.md\n@@ -5,2 +5,1 @@\n 前\n-消した行\n"
	changes, err := parseUnifiedDiff(strings.NewReader(d))
	if err != nil {
		t.Fatal(err)
	}
	got := changes["x.md"]
	if len(got) != 1 || got[0].Line != 6 || !got[0].Deleted {
		t.Fatalf("削除だけの変更は、削除の直後の位置 (post-image 6 行目) を変更位置として残す: %+v", got)
	}
}

func TestBlocksOfMarkdown(t *testing.T) {
	doc := parseMarkdown(strings.Split(fixtureMD, "\n"))
	if tb := doc.tableAt(14); tb == nil || tb.Start != 11 || tb.End != 14 {
		t.Fatalf("14 行目は表 (11〜14 行目) の中のはず: %+v", tb)
	}
	if ls := doc.listAt(21); ls == nil || ls.Start != 20 || ls.End != 23 {
		t.Fatalf("21 行目は箇条書き (20〜23 行目) の中のはず: %+v", ls)
	}
	if sec := doc.sectionAt(33); sec == nil || sec.Heading != "別の節" || sec.Start != 27 || sec.End != 33 {
		t.Fatalf("33 行目は節「別の節」(27〜33 行目) の中のはず: %+v", sec)
	}
	// コードフェンスの中の「# 見出しではない」は見出しにしない。
	if sec := doc.sectionAt(30); sec == nil || sec.Heading != "別の節" {
		t.Fatalf("フェンスの中の # は見出しではない: %+v", sec)
	}
	if got := doc.sectionByAnchor("準備の表"); got == nil || got.Start != 18 {
		t.Fatalf("アンカー「準備の表」から節を引ける: %+v", got)
	}
}

func TestSlug(t *testing.T) {
	cases := map[string]string{
		"準備の表":               "準備の表",
		"稼働確認(`Healthy`)の判定": "稼働確認healthyの判定",
		"一回限りのサービスと `up -d` の呼び分け":     "一回限りのサービスと-up--d-の呼び分け",
		"適用前バックアップは対象を取る (Issue #378)": "適用前バックアップは対象を取る-issue-378",
	}
	for in, want := range cases {
		if got := slug(in); got != want {
			t.Errorf("slug(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestNearEdgesForChanges(t *testing.T) {
	root := writeFixture(t)
	changes, err := parseUnifiedDiff(strings.NewReader(unifiedDiff))
	if err != nil {
		t.Fatal(err)
	}
	edges, err := nearEdges(root, changes)
	if err != nil {
		t.Fatal(err)
	}
	kinds := map[string]bool{}
	for _, e := range edges {
		kinds[e.Kind+"@"+e.File] = true
	}
	for _, want := range []string{"table@docs/a.md", "list@docs/a.md", "section@docs/a.md"} {
		if !kinds[want] {
			t.Errorf("%s の辺が無い。得られた辺: %+v", want, edges)
		}
	}
	// 表のセルを変えたら、その表の全行 (11〜14 行目) が範囲になる。
	var table *edge
	for i := range edges {
		if edges[i].Kind == "table" {
			table = &edges[i]
		}
	}
	if table == nil || table.Start != 11 || table.End != 14 {
		t.Fatalf("表の辺の範囲: %+v", table)
	}
	// 箇条書きの項目を変えたら、その箇条書き全体と直前の段落 (親) が範囲になる。
	var list *edge
	for i := range edges {
		if edges[i].Kind == "list" {
			list = &edges[i]
		}
	}
	if list == nil || list.Start != 20 || list.End != 23 || list.Parent == nil || list.Parent.Start != 18 {
		t.Fatalf("箇条書きの辺の範囲と親の段落: %+v", list)
	}
}

func TestNearEdgesFollowLinksInChangedLines(t *testing.T) {
	root := writeFixture(t)
	// 「箇条書きの後。正本は [表の節](#表の節)。」の行 (25 行目) を変えた差分。
	d := "diff --git a/docs/a.md b/docs/a.md\n--- a/docs/a.md\n+++ b/docs/a.md\n@@ -25,1 +25,1 @@\n-箇条書きの後。\n+箇条書きの後。正本は [表の節](#表の節)。\n"
	changes, err := parseUnifiedDiff(strings.NewReader(d))
	if err != nil {
		t.Fatal(err)
	}
	edges, err := nearEdges(root, changes)
	if err != nil {
		t.Fatal(err)
	}
	found := false
	for _, e := range edges {
		if e.Kind == "link" && e.Heading == "表の節" && e.Start == 7 {
			found = true
		}
	}
	if !found {
		t.Fatalf("変更行のリンク先 (節「表の節」) が辺として列挙される: %+v", edges)
	}
}

func TestHintsFromChangedLines(t *testing.T) {
	root := writeFixture(t)
	changes, err := parseUnifiedDiff(strings.NewReader(unifiedDiff))
	if err != nil {
		t.Fatal(err)
	}
	edges, err := nearEdges(root, changes)
	if err != nil {
		t.Fatal(err)
	}
	hs := hints(changes, edges)
	joined := strings.Join(hs, "\n")
	for _, want := range []string{"観点 B", "観点 C", "観点 F"} {
		if !strings.Contains(joined, want) {
			t.Errorf("%s が提示されない: %v", want, hs)
		}
	}
	if !strings.Contains(joined, "必ず") {
		t.Errorf("全称の語 (必ず) が根拠として示されない: %v", hs)
	}
}

func TestRenderIsReadable(t *testing.T) {
	root := writeFixture(t)
	changes, err := parseUnifiedDiff(strings.NewReader(unifiedDiff))
	if err != nil {
		t.Fatal(err)
	}
	edges, err := nearEdges(root, changes)
	if err != nil {
		t.Fatal(err)
	}
	out := render(root, edges, true)
	if !strings.Contains(out, "## docs/a.md") || !strings.Contains(out, "| b | y |") {
		t.Fatalf("出力にファイル名と範囲の本文が含まれる: %s", out)
	}
}
