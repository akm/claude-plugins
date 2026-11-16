"""検査 c-2 (手書きの Markdown の参照に、節 (ID) の単位で循環が無い)。

手書きのファイルと節の ID を点とし、「リンクを書いた行が属する ID → リンクが指す ID」を矢印とするグラフに、循環が無いことを
確認する。決めた経緯は Issue #198 のコメントの 2 と 3。要点:
  - 行が属する ID は、モジュール references が求める (最も内側のアンカー付きの節。無ければファイルの ID)
  - 矢印にするのは、手書きのファイルを指すリンクだけ。生成したファイルを指すリンクと、参照先のアンカーが無いリンク
    (検査 b が報告する) は数えない。自分自身を指すリンクも数えない。ファイルと節の包含関係は矢印にしない
  - 循環のまとまり (互いにたどり着ける ID の集まり。グラフの用語では強連結成分) ごとに 1 件を報告する。
    メッセージには、まとまりの中で最も小さい ID から始まる最も短い循環を、矢印ごとのリンクの位置と一緒に書き、
    まとまりのほかの ID も並べる。報告の位置は、書いた循環の最初のリンクの位置
規則の SSOT はプラグインの規則の文書 (ファイル doc-structured/rules/doc-structured-docs.md)。
"""

from dataclasses import dataclass

from .documents import Index
from .graphs import shortest_cycle, strongly_connected
from .links import resolve
from .problems import Problem
from .references import all_references

CHECK = "c-2"


@dataclass(frozen=True)
class Link:
    """2 つの ID の間の矢印と、それを作るリンクのうち最初のものの位置。"""

    path: str
    line: int
    column: int

    def where(self) -> str:
        return f"{self.path}:{self.line}:{self.column}"


def build_graph(index: Index) -> dict[str, dict[str, Link]]:
    """属する ID から、指す ID と、その矢印を作る最初のリンクへの対応。"""
    graph: dict[str, dict[str, Link]] = {}
    for reference in all_references(index):
        if not reference.in_body:
            continue
        target = resolve(reference.file, reference.definition, index).target
        if target is None or index.file(target.path) is None:
            continue
        if target.id == reference.owner_id:
            continue
        edges = graph.setdefault(reference.owner_id, {})
        edges.setdefault(target.id, Link(reference.path, reference.line, reference.column))
    return graph


def check_cycles(index: Index) -> list[Problem]:
    graph = build_graph(index)
    problems: list[Problem] = []
    for component in strongly_connected(graph):
        cycle = shortest_cycle(graph, component)
        links = [(a, b, graph[a][b]) for a, b in zip(cycle, cycle[1:])]
        steps = "、".join(f"{a} → {b} ({link.where()})" for a, b, link in links)
        message = f"参照が循環している: {steps}。"
        others = [m for m in component if m not in cycle]
        if others:
            message += f"ほかに循環に関わる ID: {'・'.join(others)}。"
        message += "循環のどれかのリンクを外すか、参照される内容を別の節に移す"
        first = links[0][2]
        problems.append(Problem(CHECK, first.path, message, first.line, first.column))
    return problems
