from __future__ import annotations

"""
Stage3 dispatch scheduling + 真实街道路线(OSRM)。

调度模型:
  - predicted_need_by_zone[z] > 0 => shortage (need bikes)
  - predicted_need_by_zone[z] < 0 => surplus  (excess bikes to move out)

算法:
  - 按阈值过滤(ignore 小偏差)
  - 贪心全局匹配: 每次选择距离最小的 (surplus, deficit) 对，搬运 min(surplus, shortage) 辆

路线几何:
  1) OSRM 优先：向 OSRM_BASE_URL/route/v1/driving/a;b 发 HTTP 请求(overview=full,geometries=geojson)
     拿到真实街道坐标（coordinates 是完整 polyline，通常 30~200 点）
  2) 降级：OSRM 不可达或超时 → 退化为两站之间 2 点直线（和旧版本一致）

注意:
  - 对 OSRM 返回的 coordinates 做 "首尾锚定修正"（把 OSRM 自己吸附到最近道路的起点/终点，
    强制替换为真实站点经纬度，避免路线端点和站点圆区之间出现"悬浮断点"）
  - 加进程级 LRU 缓存：同一对站点往返共享缓存（往返同一条路，避免重复请求）
"""

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Literal

from ..config import OSRM_BASE_URL
from ..services.geoutils import Zone, distance_between_centers


Metric = Literal["euclidean", "manhattan"]


@dataclass(frozen=True)
class DispatchRoute:
    from_zone: str
    to_zone: str
    quantity: int
    route_geometry: dict[str, Any]  # GeoJSON LineString. 带私有键 _route_source (osrm/straight)


# ============== OSRM 请求缓存（同 pair 往返共享） ==============
_OSRM_LOCK = threading.Lock()
_OSRM_CACHE_MAX = 512
_OSRM_CACHE: "OrderedDict[tuple[str, str], dict[str, Any]]" = OrderedDict()

# OSRM 默认超时（网络不好时快速 fallback 直线，不阻塞调度 UI）
_OSRM_TIMEOUT_SEC = 3.5

_DEFAULT_UA = (
    "Mozilla/5.0 (bike-dispatch-system portfolio demo; "
    "+https://github.com/internal) Python-urllib/3"
)


def _osrm_key(from_id: str, to_id: str) -> tuple[str, str]:
    """稳定 key：往返同一路视为同一 key（sorted）。"""
    return tuple(sorted((from_id, to_id)))  # type: ignore[return-value]


def _try_osrm_route(a: Zone, b: Zone) -> dict[str, Any] | None:
    """
    请求 OSRM 真实街道路线。
    返回 GeoJSON LineString dict（带 _route_source="osrm"），失败返回 None。
    """
    base = OSRM_BASE_URL.rstrip("/")
    if not base:
        return None

    ax, ay = a.center_lonlat  # [lon, lat]
    bx, by = b.center_lonlat

    key = _osrm_key(a.zone_id, b.zone_id)
    with _OSRM_LOCK:
        if key in _OSRM_CACHE:
            _OSRM_CACHE.move_to_end(key)
            cached = _OSRM_CACHE[key]
            # 根据 a->b 或 b->a 决定是否反转坐标
            if (a.zone_id, b.zone_id) == key:
                coords = list(cached["coordinates"])
            else:
                coords = list(reversed(cached["coordinates"]))
            geom = {
                "type": "LineString",
                "coordinates": coords,
                "_route_source": "osrm",
                # 保留原始 distance(m) / duration(s)（可选，前端若需要可展示）
                "_distance_m": cached.get("_distance_m"),
                "_duration_s": cached.get("_duration_s"),
            }
            return geom

    # OSRM driving route 请求坐标按 (lon,lat) 排列
    coords_csv = f"{ax:.6f},{ay:.6f};{bx:.6f},{by:.6f}"
    q = urllib.parse.urlencode({
        "overview": "full",         # 返回完整几何（默认=simplified 会丢弯道细节）
        "geometries": "geojson",    # GeoJSON LineString（coordinates=[[lon,lat],..]）
        "steps": "false",           # 不需要 turn-by-turn 步骤
        "annotations": "false",
    })
    url = f"{base}/route/v1/driving/{coords_csv}?{q}"
    req = urllib.request.Request(url, headers={"User-Agent": _DEFAULT_UA, "Accept": "application/json"})
    raw: bytes | None = None
    try:
        with urllib.request.urlopen(req, timeout=_OSRM_TIMEOUT_SEC) as resp:
            raw = resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None
    if not raw:
        return None

    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None

    # OSRM 正常返回 code=Ok，routes 非空
    if data.get("code") != "Ok":
        return None
    routes = data.get("routes") or []
    if not routes:
        return None
    first = routes[0]
    geom = first.get("geometry") or {}
    if geom.get("type") != "LineString":
        return None
    coords: list[list[float]] = geom.get("coordinates") or []
    if len(coords) < 2:
        return None

    # 首尾锚定修正：强制起点=站点A中心，终点=站点B中心
    # （OSRM 会把点吸附到最近道路，可能与站点 buffer 圆心偏离 20~100m，
    #  视觉上会出现"路线端点没落在区域圆圈上"）
    coords[0] = [float(ax), float(ay)]
    coords[-1] = [float(bx), float(by)]

    distance_m = float(first.get("distance") or 0.0)
    duration_s = float(first.get("duration") or 0.0)

    # 存入缓存（存 canonical 方向，key 的顺序）
    canon_coords: list[list[float]]
    if key == (a.zone_id, b.zone_id):
        canon_coords = [[float(c[0]), float(c[1])] for c in coords]
    else:
        # key 和实际方向相反：存 reversed 后的版本作为 canonical
        canon_coords = [[float(c[0]), float(c[1])] for c in reversed(coords)]
    cache_entry: dict[str, Any] = {
        "coordinates": canon_coords,
        "_distance_m": distance_m,
        "_duration_s": duration_s,
    }
    with _OSRM_LOCK:
        _OSRM_CACHE[key] = cache_entry
        _OSRM_CACHE.move_to_end(key)
        while len(_OSRM_CACHE) > _OSRM_CACHE_MAX:
            _OSRM_CACHE.popitem(last=False)

    # 返回当前方向（key 的 canonical 版本可能和 a→b 不一致，因此再判定一次）
    with _OSRM_LOCK:
        entry2 = _OSRM_CACHE[key]
    if key == (a.zone_id, b.zone_id):
        out_coords = [[float(c[0]), float(c[1])] for c in entry2["coordinates"]]
    else:
        out_coords = [[float(c[0]), float(c[1])] for c in reversed(entry2["coordinates"])]
    return {
        "type": "LineString",
        "coordinates": out_coords,
        "_route_source": "osrm",
        "_distance_m": entry2.get("_distance_m"),
        "_duration_s": entry2.get("_duration_s"),
    }


# 创建两个区域之间的路线：OSRM 优先 + 直线降级
def _make_line(a: Zone, b: Zone) -> dict[str, Any]:
    ax, ay = a.center_lonlat
    bx, by = b.center_lonlat
    straight = {
        "type": "LineString",
        "coordinates": [[float(ax), float(ay)], [float(bx), float(by)]],
        "_route_source": "straight",
    }
    # 真实站点一般都在纽约曼哈顿，OSRM 可以正常出路线；若网络失败/容器未启动，直接走直线
    try:
        osrm = _try_osrm_route(a, b)
    except Exception:  # noqa: BLE001 — 任何异常都走直线降级，避免 UI 阻塞
        osrm = None
    return osrm if osrm is not None else straight


# 贪心匹配调度算法
def greedy_match_dispatch(
    predicted_need_by_zone: dict[str, float],
    zones: dict[str, Zone],
    *,
    metric: Metric = "euclidean",
    shortage_threshold: float = 3.0,
    surplus_threshold: float = 3.0,
) -> list[DispatchRoute]:
    """
    Create dispatch routes by greedy distance matching.

    Args:
      predicted_need_by_zone:
        positive => shortage qty to cover
        negative => surplus qty available to ship out (abs value)
    """
    # 剩余短缺和富余数量
    shortage_rem: dict[str, float] = {}
    surplus_rem: dict[str, float] = {}
    for zid, need in predicted_need_by_zone.items():
        if zid not in zones:
            continue
        need_f = float(need)
        if need_f >= shortage_threshold:
            shortage_rem[zid] = need_f
        elif need_f <= -surplus_threshold:
            surplus_rem[zid] = -need_f

    routes: list[DispatchRoute] = []

    # 全局贪心算法：每次选择距离最小的(富余, 短缺)对
    while shortage_rem and surplus_rem:
        best_pair: tuple[str, str] | None = None
        best_dist: float | None = None

        for s_zid, s_qty in surplus_rem.items():
            if s_qty <= 0:
                continue
            for d_zid, d_qty in shortage_rem.items():
                if d_qty <= 0:
                    continue
                dist = distance_between_centers(zones[s_zid], zones[d_zid], metric=metric)
                if best_dist is None or dist < best_dist:
                    best_dist = dist
                    best_pair = (s_zid, d_zid)

        if best_pair is None:
            break

        s_zid, d_zid = best_pair
        s_avail = surplus_rem.get(s_zid, 0.0)
        d_need = shortage_rem.get(d_zid, 0.0)
        if s_avail <= 0 or d_need <= 0:
            break

        # floor 避免四舍五入导致 >实际可用
        qty = int(min(s_avail, d_need))
        if qty <= 0:
            # 这对配对无效(min<1辆),移出 need 较小的一方,继续找下一对
            if s_avail <= d_need:
                surplus_rem.pop(s_zid, None)
            else:
                shortage_rem.pop(d_zid, None)
            continue

        # OSRM 真实街道（或降级直线）
        geom = _make_line(zones[s_zid], zones[d_zid])

        routes.append(
            DispatchRoute(
                from_zone=s_zid,
                to_zone=d_zid,
                quantity=qty,
                route_geometry=geom,
            )
        )

        # 更新剩余数量
        s_avail -= qty
        d_need -= qty
        surplus_rem[s_zid] = s_avail
        shortage_rem[d_zid] = d_need

        if surplus_rem[s_zid] <= 0:
            surplus_rem.pop(s_zid, None)
        if shortage_rem[d_zid] <= 0:
            shortage_rem.pop(d_zid, None)

    return routes


def _ssp_min_cost_flow(
    adj: dict[str, dict[str, list]],
    source: str,
    sink: str,
    demand: int,
) -> dict[tuple[str, str], int]:
    """
    整数权重 Successive Shortest Path 最小费用流。

    - 边表示: adj[u][v] = [residual_capacity, cost]（含反向边 [0, -cost]）
    - 权重为整数（米 ×100），势能 h 用 int，避免浮点误差导致负环死循环
    - 每次按路径瓶颈容量增广（非 1 单位），30 站规模毫秒级完成
    - 返回原图正向边 (u, v) -> 实际流量（供提取 s: → d: 的调运量）

    与 networkx network_simplex 相比：对流量大/结构差的输入（如早高峰 80+ 辆
    拆成 20+ 条路线）不会出现 20s+ 退化，求解稳定 <10ms。
    """
    import heapq

    h: dict[str, int] = {n: 0 for n in adj}
    flow = 0
    total_cost = 0
    flow_on: dict[tuple[str, str], int] = {}

    while flow < demand:
        dist: dict[str, float] = {n: float("inf") for n in adj}
        prevv: dict[str, str] = {}
        dist[source] = 0
        pq = [(0, source)]
        while pq:
            d, u = heapq.heappop(pq)
            if dist[u] < d:
                continue
            for v, (cap, c) in adj[u].items():
                if cap > 0:
                    nd = d + c + h[u] - h[v]
                    if dist[v] > nd:
                        dist[v] = nd
                        prevv[v] = u
                        heapq.heappush(pq, (nd, v))
        if dist[sink] == float("inf"):
            break  # 无更多增广路

        for n, d in dist.items():
            if d < float("inf"):
                h[n] += d

        # 计算瓶颈增广量
        aug = demand - flow
        v = sink
        seen: set[str] = set()
        while v != source:
            if v in seen:  # 防路径成环（理论不会，防御性保护）
                raise RuntimeError("ssp aug path cycle")
            seen.add(v)
            u = prevv[v]
            aug = min(aug, adj[u][v][0])
            v = u

        flow += aug
        total_cost += aug * h[sink]
        v = sink
        while v != source:
            u = prevv[v]
            adj[u][v][0] -= aug
            adj[v][u][0] += aug
            # 记录正向边流量：沿 u→v 增广，则 (u,v) 流量 +aug
            flow_on[(u, v)] = flow_on.get((u, v), 0) + aug
            v = u

    return flow_on


# 最小费用流全局最优匹配调度算法（方案A：替代贪心）
def mincost_match_dispatch(
    predicted_need_by_zone: dict[str, float],
    zones: dict[str, Zone],
    *,
    metric: Metric = "euclidean",
    shortage_threshold: float = 3.0,
    surplus_threshold: float = 3.0,
) -> list[DispatchRoute]:
    """
    Create dispatch routes by min-cost-flow global optimization.

    建模（标准运输问题）:
      SUP → 每个盈余站（容量=盈余量, 费用0）
      每个短缺站 → DEM（容量=短缺量, 费用0）
      盈余站 i → 短缺站 j（容量=min(盈余_i,短缺_j), 费用=中心距离）

    一次性求出"总调运距离最小"的全局最优流量分配，等价于运输问题最优解。
    求解用整数权重 SSP（毫秒级稳定），失败兜底回退 greedy（保证 API 始终可响应）。
    """
    # 收集盈余/短缺（int 取整，与 greedy 口径一致：车辆数只能为整数）
    surplus: dict[str, int] = {}
    shortage: dict[str, int] = {}
    for zid, need in predicted_need_by_zone.items():
        if zid not in zones:
            continue
        need_f = float(need)
        if need_f >= shortage_threshold:
            shortage[zid] = int(need_f)
        elif need_f <= -surplus_threshold:
            surplus[zid] = int(-need_f)

    if not surplus or not shortage:
        return []

    total_flow = min(sum(surplus.values()), sum(shortage.values()))
    if total_flow <= 0:
        return []

    adj: dict[str, dict[str, list]] = {}

    def _add_edge(u: str, v: str, cap: int, cost: int) -> None:
        adj.setdefault(u, {})
        adj.setdefault(v, {})
        adj[u].setdefault(v, [0, cost])
        adj[v].setdefault(u, [0, -cost])
        adj[u][v][0] += cap

    for zid, qty in surplus.items():
        _add_edge("SUP", f"s:{zid}", qty, 0)
    for zid, qty in shortage.items():
        _add_edge(f"d:{zid}", "DEM", qty, 0)
    # 记录原图 s:→d: 的初始容量（用于反推流量 = 初始 - 残余）
    orig_cap: dict[tuple[str, str], int] = {}
    for s_zid, s_qty in surplus.items():
        for d_zid, d_qty in shortage.items():
            cap = min(s_qty, d_qty)
            if cap <= 0:
                continue
            dist = int(distance_between_centers(zones[s_zid], zones[d_zid], metric=metric) * 100)
            _add_edge(f"s:{s_zid}", f"d:{d_zid}", cap, dist)
            orig_cap[(f"s:{s_zid}", f"d:{d_zid}")] = cap

    try:
        _ssp_min_cost_flow(adj, "SUP", "DEM", total_flow)
    except Exception:  # noqa: BLE001 — 任何异常兜底贪心，避免 UI 阻塞
        return greedy_match_dispatch(
            predicted_need_by_zone, zones,
            metric=metric,
            shortage_threshold=shortage_threshold,
            surplus_threshold=surplus_threshold,
        )

    routes: list[DispatchRoute] = []
    for (sn, dn), init_cap in orig_cap.items():
        qty = init_cap - adj[sn][dn][0]  # 初始容量 - 残余容量 = 实际调运量
        if qty <= 0:
            continue
        s_zid, d_zid = sn[2:], dn[2:]
        geom = _make_line(zones[s_zid], zones[d_zid])
        routes.append(DispatchRoute(
            from_zone=s_zid,
            to_zone=d_zid,
            quantity=qty,
            route_geometry=geom,
        ))
    return routes
