"""有向グラフの循環を求める関数。検査 c-1 (YAML の依存の循環) と検査 c-2 (手書きの Markdown の参照の循環) が使う。

グラフは、点の ID から、矢印の先の ID と、その矢印についての情報 (矢印を作るリンクや参照の位置など) への対応で表す。
関数は矢印の情報を使わない。
"""

from collections import deque

Graph = dict[str, dict[str, object]]


def strongly_connected(graph: Graph) -> list[list[str]]:
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


def shortest_cycle(graph: Graph, component: list[str]) -> list[str]:
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
