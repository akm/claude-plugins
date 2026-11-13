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

from collections import deque
from dataclasses import dataclass

from .documents import Index
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


def strongly_connected(graph: dict[str, dict[str, Link]]) -> list[list[str]]:
    """2 つ以上の ID を持つ循環のまとまり。それぞれは ID の文字コードの順に並べ、まとまりは最も小さい ID の順に並べる。"""
    nodes = sorted(set(graph) | {t for edges in graph.values() for t in edges})
    order: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    found: list[list[str]] = []
    counter = 0
    for root in nodes:
        if root in order:
            continue
        # Tarjan のアルゴリズムを、再帰を使わずに書いたもの
        work: list[tuple[str, list[str]]] = [(root, sorted(graph.get(root, {})))]
        order[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, rest = work[-1]
            if rest:
                child = rest.pop(0)
                if child not in order:
                    order[child] = low[child] = counter
                    counter += 1
                    stack.append(child)
                    on_stack.add(child)
                    work.append((child, sorted(graph.get(child, {}))))
                elif child in on_stack:
                    low[node] = min(low[node], order[child])
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == order[node]:
                component: list[str] = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                if len(component) > 1:
                    found.append(sorted(component))
    return sorted(found, key=lambda c: c[0])


def shortest_cycle(graph: dict[str, dict[str, Link]], component: list[str]) -> list[str]:
    """まとまりの中で、最も小さい ID から始まり、そこへ戻る最も短い循環。配列の最初と最後の要素は、同じ ID になる。"""
    members = set(component)
    start = component[0]
    parent: dict[str, str] = {}
    queue = deque([start])
    seen = {start}
    while queue:
        node = queue.popleft()
        for child in sorted(graph.get(node, {})):
            if child not in members:
                continue
            if child == start:
                # start から node までを parent でたどり、start に戻る矢印を足す
                path = [node]
                while path[-1] != start:
                    path.append(parent[path[-1]])
                return list(reversed(path)) + [start]
            if child not in seen:
                seen.add(child)
                parent[child] = node
                queue.append(child)
    raise AssertionError(f"循環のまとまり {component} に、{start} へ戻る循環が無い")


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
