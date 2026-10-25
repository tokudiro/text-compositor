"""フローチャートの線を、水平と垂直だけで引く（#540。独自記法の図だけ。Mermaidの試作は、`dot`の曲線のまま）。

位置は、`dot`が決めた箱の位置を、そのまま使う。ここでは、線の通り道だけを決める。

* 判断のひし形は、出口を、行き先の左右の位置で割り当てる。左にある行き先は左の頂点、右にある行き先は右の頂点、真下は下の頂点から出す。
* 次の記号に入る線が2本以上のときは、記号の少し上の高さで水平にまとめ、1本にして入れる。矢じりは、入るところに1つだけ付ける。
  規格（JIS X 0121 9.2.1）は、2本以上の線を1本にまとめて出してよいと定める。
* 線は、記号の上から入り、下（または左右の頂点）から出る。

`box`は、`x`・`y`（中心）・`width`・`height`・`node`（`shape`を持つ）を持つもの。座標は、下向きがプラス。
"""
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

EPS = 1.0           # 位置が「同じ」とみなす差（pt）
SNAP = 12.0         # 頂点と行き先の中心が、これ以内のずれなら、頂点から、まっすぐ下ろす（pt）
MERGE_GAP = 14.0    # 合流の水平線を、次の記号の上辺から離す距離（pt）
LABEL_PAD = 3.0     # 分岐の文字と、線の間の余白（pt）

Point = Tuple[float, float]


@dataclass
class OrthoRoute:
    points: List[Point]
    arrow: bool = True
    label_pos: Optional[Point] = None


@dataclass
class _Exit:
    point: Point
    side: str       # left | right | bottom


def _assign_exits(box, indexes: List[int], edges, boxes) -> Dict[int, _Exit]:
    """判断のひし形の出口を、行き先の左右の位置で割り当てる。行き先が頂点より外にあるときだけ、左右の頂点を使う。"""
    left = (box.x - box.width / 2, box.y)
    right = (box.x + box.width / 2, box.y)
    bottom = (box.x, box.y + box.height / 2)
    ordered = sorted(indexes, key=lambda i: (boxes[edges[i].target].x, i))
    exits = {i: _Exit(bottom, 'bottom') for i in ordered}
    first, last = ordered[0], ordered[-1]
    # 行き先が、頂点とほぼ同じ位置か、それより外なら、その頂点を使う（頂点より内側にあると、水平な線がひし形の中を通る）
    if boxes[edges[first].target].x < min(left[0] + SNAP, box.x - EPS):
        exits[first] = _Exit(left, 'left')
    if last != first and boxes[edges[last].target].x > max(right[0] - SNAP, box.x + EPS):
        exits[last] = _Exit(right, 'right')
    return exits


def _dedupe(points: List[Point]) -> List[Point]:
    """重なる点と、一直線上の途中の点を除く。"""
    out: List[Point] = []
    for p in points:
        if out and abs(out[-1][0] - p[0]) < 0.01 and abs(out[-1][1] - p[1]) < 0.01:
            continue
        out.append(p)
    result: List[Point] = []
    for p in out:
        while len(result) >= 2 and ((abs(result[-2][0] - result[-1][0]) < 0.01 and abs(result[-1][0] - p[0]) < 0.01)
                                    or (abs(result[-2][1] - result[-1][1]) < 0.01 and abs(result[-1][1] - p[1]) < 0.01)):
            result.pop()
        result.append(p)
    return result


def _label_position(exit_: _Exit, points: List[Point], size: Tuple[float, float]) -> Point:
    """分岐の文字の中心。最初の水平な線があれば、その上（出口の側）。なければ、最初の垂直な線のそば。"""
    width, height = size
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        if abs(ay - by) < 0.01 and abs(ax - bx) > 0.01:
            direction = 1.0 if bx > ax else -1.0
            run = abs(bx - ax)       # 文字が収まらないほど短いときは、線の中央に置く
            offset = width / 2 + LABEL_PAD if run >= width + 2 * LABEL_PAD else run / 2
            return (ax + direction * offset, ay - height / 2 - LABEL_PAD)
    x, y = points[0]
    side = -1.0 if exit_.side == 'left' else 1.0      # 左の頂点からの線は、頂点の外（左）。ほかは、右
    return (x + side * (width / 2 + LABEL_PAD), y + height / 2 + LABEL_PAD)


def route_edges(boxes: Dict[str, object], edges: Sequence, label_sizes: Dict[int, Tuple[float, float]]) -> List[OrthoRoute]:
    """各矢印の、折れ線（水平・垂直だけ）を、矢印の並びと同じ順で返す。`label_sizes`は、矢印の番号 → 文字の(幅, 高さ)。"""
    outgoing: Dict[str, List[int]] = defaultdict(list)
    incoming: Dict[str, List[int]] = defaultdict(list)
    for i, e in enumerate(edges):
        outgoing[e.source].append(i)
        incoming[e.target].append(i)

    exits: Dict[int, _Exit] = {}
    for source, indexes in outgoing.items():
        box = boxes[source]
        if box.node.shape == 'diamond' and len(indexes) >= 2:
            exits.update(_assign_exits(box, indexes, edges, boxes))
        else:
            for i in indexes:
                exits[i] = _Exit((box.x, box.y + box.height / 2), 'bottom')

    # 合流する記号ごとに、水平にまとめる高さを決める（出口の、いちばん低い所と、記号の上辺の間）
    merge_y: Dict[str, float] = {}
    for target, indexes in incoming.items():
        if len(indexes) < 2:
            continue
        top = boxes[target].y - boxes[target].height / 2
        lowest = max(exits[i].point[1] for i in indexes)
        merge_y[target] = top - min(MERGE_GAP, max((top - lowest) / 2, 0.0))

    # 1つの記号から複数の線が出るときは、水平に折れる高さを、そろえる（行き先のいちばん高い上辺との、中間）
    branch_y: Dict[str, float] = {}
    for source, indexes in outgoing.items():
        if len(indexes) >= 2:
            sy = max(exits[i].point[1] for i in indexes)
            top = min(boxes[edges[i].target].y - boxes[edges[i].target].height / 2 for i in indexes)
            if top > sy:
                branch_y[source] = sy + (top - sy) / 2

    routes: List[OrthoRoute] = []
    for i, e in enumerate(edges):
        exit_ = exits[i]
        sx, sy = exit_.point
        target = boxes[e.target]
        tx, top = target.x, target.y - target.height / 2
        if top <= sy:                                    # 上へ戻る線は、この記法にはない。万一のときは、まっすぐ結ぶ
            points = [(sx, sy), (tx, top)]
        elif e.target in merge_y:
            ym = merge_y[e.target]
            points = [(sx, sy), (sx, ym), (tx, ym), (tx, top)]
        elif exit_.side in ('left', 'right'):
            if abs(sx - tx) <= SNAP:
                points = [(sx, sy), (sx, top)]           # 頂点の真下に行き先がある: まっすぐ下ろす
            else:
                points = [(sx, sy), (tx, sy), (tx, top)]  # 頂点から水平に出て、行き先の真上から垂直に下りる
        elif abs(sx - tx) < EPS:
            points = [(sx, sy), (tx, top)]
        elif abs(sx - tx) <= SNAP and e.source not in branch_y and boxes[e.source].node.shape != 'diamond':
            points = [(tx, sy), (tx, top)]               # 中心が少しずれているだけ: 小さな折れを作らず、行き先の中心へ、まっすぐ下ろす
        else:
            ym = branch_y.get(e.source, sy + (top - sy) / 2)
            points = [(sx, sy), (sx, ym), (tx, ym), (tx, top)]
        points = _dedupe(points)
        label = None
        if e.label and i in label_sizes:
            label = _label_position(exit_, points, label_sizes[i])
        # 合流する線は、最後の区間が重なる。矢じりは、最初の1本だけに付ける
        shares_end = e.target in merge_y and i != min(incoming[e.target])
        routes.append(OrthoRoute(points, arrow=bool(getattr(e, 'arrow', True)) and not shares_end, label_pos=label))
    return routes
