from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

# 距离度量类型:欧几里得距离或曼哈顿距离
Metric = Literal["euclidean", "manhattan"]

# WGS84 椭球赤道半径(米),用于 haversine
EARTH_RADIUS_M = 6_371_000.0

# 尝试导入 pyproj(可选,用于精确 UTM 投影);失败则降级到 haversine + 局部 ENU
try:
    import pyproj  # type: ignore

    _HAS_PYPROJ = True
except Exception:  # ImportError / DLL load failed 等
    pyproj = None  # type: ignore
    _HAS_PYPROJ = False

# 尝试导入 shapely(可选);失败则用纯 python 几何
try:
    from shapely.geometry import Point as _ShapelyPoint  # type: ignore
    from shapely.geometry import shape as _shapely_shape  # type: ignore

    _HAS_SHAPELY = True
except Exception:
    _HAS_SHAPELY = False

# pyproj UTM Transformer 缓存（按 EPSG 码复用，避免每次投影都新建 Transformer，
# 此前 OD / LISA 接口因逐对新建 Transformer 慢到 2~8 秒，等价卡死）
_TRANSFORMER_CACHE: dict[int, Any] = {}


def _get_utm_transformer(ref_lon: float, ref_lat: float) -> Any:
    """按参考点 UTM 分带缓存并返回 4326→UTM 的 Transformer。"""
    zone_num = int(math.floor((ref_lon + 180.0) / 6.0)) + 1
    epsg = 32600 + zone_num if ref_lat >= 0.0 else 32700 + zone_num
    t = _TRANSFORMER_CACHE.get(epsg)
    if t is None:
        t = pyproj.Transformer.from_crs(  # type: ignore[union-attr]
            pyproj.CRS.from_epsg(4326),  # type: ignore[union-attr]
            pyproj.CRS.from_epsg(epsg),  # type: ignore[union-attr]
            always_xy=True,
        )
        _TRANSFORMER_CACHE[epsg] = t
    return t


@dataclass(frozen=True)
class Zone:
    """区域类,包含区域ID、名称、几何多边形(原始 GeoJSON dict)和质心"""

    zone_id: str
    name: str
    polygon: Any  # GeoJSON geometry dict(Polygon 或 MultiPolygon)
    _center_lonlat: tuple[float, float] = field(repr=False)

    @property
    def center_lonlat(self) -> tuple[float, float]:
        """质心 (lon, lat)"""
        return self._center_lonlat


def _polygon_centroid_coords(geom: dict[str, Any]) -> tuple[float, float]:
    """
    计算多边形质心(经度, 纬度)。
    对凸多边形(如圆形 buffer)用顶点平均即可;通用多边形用面积加权。
    shapely 可用时优先用 shapely。
    """
    if _HAS_SHAPELY:
        try:
            g = _shapely_shape(geom)
            c = g.centroid
            return float(c.x), float(c.y)
        except Exception:
            pass
    # 纯 python:取外环顶点平均(对 prepare_trips 生成的圆形 buffer 多边形精确)
    gtype = geom.get("type")
    if gtype == "Polygon":
        ring = geom["coordinates"][0]
    elif gtype == "MultiPolygon":
        # 取最大多边形的外环
        polys = geom["coordinates"]
        ring = max(polys, key=lambda p: len(p[0]))[0]
    else:
        raise ValueError(f"不支持的几何类型: {gtype}")
    xs = [pt[0] for pt in ring]
    ys = [pt[1] for pt in ring]
    return float(sum(xs) / len(xs)), float(sum(ys) / len(ys))


def _point_in_polygon(lon: float, lat: float, geom: dict[str, Any]) -> bool:
    """点是否在多边形内(ray casting)。shapely 可用时优先用。"""
    if _HAS_SHAPELY:
        try:
            return bool(_shapely_shape(geom).covers(_ShapelyPoint(lon, lat)))
        except Exception:
            pass
    gtype = geom.get("type")
    if gtype == "Polygon":
        return _ray_casting(lon, lat, geom["coordinates"][0])
    if gtype == "MultiPolygon":
        for poly in geom["coordinates"]:
            if _ray_casting(lon, lat, poly[0]):
                return True
        return False
    return False


def _ray_casting(lon: float, lat: float, ring: list[list[float]]) -> bool:
    """射线法判断点在多边形内"""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-30) + xi
        ):
            inside = not inside
        j = i
    return inside


def _require_exists(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"GeoJSON not found: {path}")


def load_zones_from_geojson(geojson_path: str | Path) -> dict[str, Zone]:
    """从 GeoJSON 加载区域多边形(WGS84 经纬度)"""
    geojson_path = Path(geojson_path)
    _require_exists(geojson_path)

    data = json.loads(geojson_path.read_text(encoding="utf-8"))
    if data.get("type") != "FeatureCollection":
        raise ValueError("GeoJSON must be a FeatureCollection.")

    zones: dict[str, Zone] = {}
    for feat in data.get("features", []):
        props = feat.get("properties", {}) or {}
        zone_id = props.get("zone_id")
        name = props.get("name", zone_id)
        geom = feat.get("geometry")
        if not zone_id or not geom:
            continue
        center = _polygon_centroid_coords(geom)
        zones[str(zone_id)] = Zone(
            zone_id=str(zone_id), name=str(name), polygon=geom, _center_lonlat=center
        )

    if not zones:
        raise ValueError(f"No zones loaded from {geojson_path}")
    return zones


def is_point_in_zone(lon: float, lat: float, zone: Zone) -> bool:
    """判断点是否在区域内"""
    return _point_in_polygon(lon, lat, zone.polygon)


# ---------------------- 距离计算(测地距离,无 pyproj 依赖) ----------------------

def haversine_m(
    lon_a: float, lat_a: float, lon_b: float, lat_b: float
) -> float:
    """
    Haversine 测地距离(米)。

    修正说明:旧实现对 WGS84 经纬度直接做欧氏,忽略了 1° 经度与 1° 纬度
    代表的实际距离不同(在 40.7°N 附近相差约 23%),无物理意义。
    Haversine 在球面三角下计算两点最短弧长,误差 <0.5%,足够校园尺度使用。
    """
    phi1, phi2 = math.radians(lat_a), math.radians(lat_b)
    dphi = math.radians(lat_b - lat_a)
    dlmb = math.radians(lon_b - lon_a)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return float(EARTH_RADIUS_M * c)


@lru_cache(maxsize=8)
def _geod() -> Any:
    """pyproj.Geod(若有),否则返回 None 走 haversine 路径"""
    if not _HAS_PYPROJ:
        return None
    try:
        return pyproj.Geod(ellps="WGS84")  # type: ignore[union-attr]
    except Exception:
        return None


def geodesic_distance_m(
    lon_a: float, lat_a: float, lon_b: float, lat_b: float
) -> float:
    """测地距离(米):优先 pyproj.Geod,降级 haversine"""
    geod = _geod()
    if geod is not None:
        try:
            _, _, dist_m = geod.inv(lon_a, lat_a, lon_b, lat_b)  # type: ignore[union-attr]
            return float(dist_m)
        except Exception:
            pass
    return haversine_m(lon_a, lat_a, lon_b, lat_b)


def project_lonlat(
    lon: float,
    lat: float,
    ref_lon: float,
    ref_lat: float,
) -> tuple[float, float]:
    """
    把 WGS84 经纬度投影到以 (ref_lon, ref_lat) 为原点的局部平面坐标系,返回 (x_m, y_m)。

    优先使用 pyproj UTM 投影(精确);若 pyproj 不可用,降级为局部 ENU 切平面近似:
      north = (lat - ref_lat) * 111_320
      east  = (lon - ref_lon) * 111_320 * cos(ref_lat)
    校园尺度(<10km)下 ENU 与 UTM 误差 <1%。
    """
    if _HAS_PYPROJ:
        try:
            transformer = _get_utm_transformer(ref_lon, ref_lat)
            x, y = transformer.transform(lon, lat)
            return float(x), float(y)
        except Exception:
            pass
    # 降级:局部 ENU
    north = (lat - ref_lat) * 111_320.0
    east = (lon - ref_lon) * 111_320.0 * math.cos(math.radians(ref_lat))
    return float(east), float(north)


def _distance_naive_lonlat(
    lon_a: float, lat_a: float, lon_b: float, lat_b: float, metric: Metric
) -> float:
    """
    旧实现(保留仅用于误差对比):直接对经纬度做欧氏/曼哈顿,单位是"度",无物理意义。
    1° 经度与 1° 纬度代表的实际距离不同(40.7°N 附近相差约 23%),不能当米用。
    """
    dx = abs(lon_a - lon_b)
    dy = abs(lat_a - lat_b)
    if metric == "manhattan":
        return float(dx + dy)
    return float(math.sqrt(dx * dx + dy * dy))


def distance_between_centers(
    zone_a: Zone,
    zone_b: Zone,
    metric: Metric = "euclidean",
) -> float:
    """
    两区域质心之间的距离(米)。

    修复说明:
      旧实现直接对 WGS84 经纬度做欧氏,忽略了经纬度并非平面坐标,且
      1° 经度与 1° 纬度代表的实际距离不同(在 40.7°N 附近相差约 23%)。
      现统一投影到局部平面坐标系(UTM 或 ENU)后,在投影坐标系中计算,
      结果单位为米,且对校园尺度(<10km)与测地距离误差 <1%。
    """
    lon_a, lat_a = zone_a.center_lonlat
    lon_b, lat_b = zone_b.center_lonlat
    ax, ay = project_lonlat(lon_a, lat_a, lon_a, lat_a)
    bx, by = project_lonlat(lon_b, lat_b, lon_a, lat_a)
    dx = abs(ax - bx)
    dy = abs(ay - by)
    if metric == "manhattan":
        return float(dx + dy)
    return float(math.sqrt(dx * dx + dy * dy))


def route_distance(
    route_zone_ids: list[str],
    zones: dict[str, Zone],
    metric: Metric = "euclidean",
) -> float:
    """沿区域质心序列的累计路径长度(米)"""
    dist = 0.0
    for i in range(len(route_zone_ids) - 1):
        a = zones[route_zone_ids[i]]
        b = zones[route_zone_ids[i + 1]]
        dist += distance_between_centers(a, b, metric=metric)
    return float(dist)


# ---------------------- 误差对比(技术报告 / 套磁材料证据) ----------------------

def compare_distance_metrics(
    zones: dict[str, Zone], metric: Metric = "euclidean"
) -> list[dict[str, Any]]:
    """
    输出每对区域的距离对照:
      - geod_m           : 测地距离(ground truth, 米)
      - proj_m           : 本实现投影后欧氏/曼哈顿(米)
      - proj_err_vs_geod : 本实现相对测地距离误差(应 <1%,验证实现正确)
      - naive_deg        : 旧实现经纬度直接欧氏/曼哈顿(度,无意义)
      - naive_misread_m  : 旧值若被误当作"度×111000 米"的误读值
      - naive_err_vs_geod: 误读值相对测地距离误差(展示旧实现的危害)
    """
    import numpy as _np  # 延迟导入，避免该文件顶层 import 顺序问题

    rows: list[dict[str, Any]] = []
    ids = sorted(zones.keys())
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a = zones[ids[i]]
            b = zones[ids[j]]
            lon_a, lat_a = a.center_lonlat
            lon_b, lat_b = b.center_lonlat

            geod_m = geodesic_distance_m(lon_a, lat_a, lon_b, lat_b)
            proj_m = distance_between_centers(a, b, metric=metric)
            naive_deg = _distance_naive_lonlat(lon_a, lat_a, lon_b, lat_b, metric)
            naive_misread_m = naive_deg * 111_000.0

            rows.append(
                {
                    "a": ids[i],
                    "b": ids[j],
                    "geod_m": geod_m,
                    "proj_m": proj_m,
                    "proj_err_vs_geod_pct": (proj_m - geod_m) / geod_m * 100.0
                    if geod_m > 0
                    else 0.0,
                    "naive_deg": naive_deg,
                    "naive_misread_m": naive_misread_m,
                    "naive_err_vs_geod_pct": (naive_misread_m - geod_m) / geod_m * 100.0
                    if geod_m > 0
                    else 0.0,
                }
            )
    _ = _np  # 仅为了保证 import 生效（若本函数未来需要聚合统计）
    return rows


# =========================================================================
# GIS 作品集扩展：投影审计 / 时空立方体描述 / 空间自相关（Moran's I + LISA）
# =========================================================================


def projection_audit(zones: dict[str, Zone]) -> dict[str, Any]:
    """
    作品集用"投影修复"证据：
    - 站点两两距离对照：naive 误读 vs UTM/ENU 投影
    - 汇总：max / mean / p95 误差百分比（理想情况下 naive ~23%，投影 <1%）
    - 在 40.7°N 附近，1°经度 ≈ cos(lat)*111km ≈ 84.6km，即 1°lon/1°lat ≈ 76%，
      因此直接把度当米用平均 ~23% 的系统性误差，正好是 GIS 教授要看到的硬细节。
    """
    import numpy as _np

    if len(zones) < 2:
        return {"error": "Need at least 2 zones for audit."}

    rows = compare_distance_metrics(zones, metric="euclidean")
    proj_errs = _np.asarray([r["proj_err_vs_geod_pct"] for r in rows], dtype=_np.float64)
    naive_errs = _np.asarray([r["naive_err_vs_geod_pct"] for r in rows], dtype=_np.float64)
    lons = [z.center_lonlat[0] for z in zones.values()]
    lats = [z.center_lonlat[1] for z in zones.values()]

    return {
        "n_zones": len(zones),
        "center_lat_deg": float(_np.mean(lats)),
        "degree_lon_vs_lat_ratio_pct": float(
            math.cos(math.radians(float(_np.mean(lats)))) * 100.0
        ),
        "bbox_wgs84": {
            "min_lon": float(min(lons)),
            "max_lon": float(max(lons)),
            "min_lat": float(min(lats)),
            "max_lat": float(max(lats)),
        },
        "sample_pairs": rows[:10],
        "naive": {
            "mean_abs_err_pct": float(_np.mean(_np.abs(naive_errs))),
            "max_abs_err_pct": float(_np.max(_np.abs(naive_errs))),
            "p95_abs_err_pct": float(_np.percentile(_np.abs(naive_errs), 95)),
        },
        "projected": {
            "mean_abs_err_pct": float(_np.mean(_np.abs(proj_errs))),
            "max_abs_err_pct": float(_np.max(_np.abs(proj_errs))),
            "p95_abs_err_pct": float(_np.percentile(_np.abs(proj_errs), 95)),
        },
        "pyproj_available": bool(_HAS_PYPROJ),
        "n_comparisons": len(rows),
    }


def pairwise_distance_matrix(zones: dict[str, Zone], zone_order: list[str]) -> Any:
    """返回 (N,N) 距离矩阵（米），按 zone_order 排序。"""
    import numpy as _np

    n = len(zone_order)
    D = _np.zeros((n, n), dtype=_np.float64)
    for i, a_id in enumerate(zone_order):
        for j in range(i + 1, n):
            b_id = zone_order[j]
            d = distance_between_centers(zones[a_id], zones[b_id])
            D[i, j] = D[j, i] = float(d)
    return D


def spatial_weight_matrix(
    zones: dict[str, Zone],
    zone_order: list[str],
    weight: Literal["knn", "distance_band"] = "knn",
    k: int = 5,
    band_m: float = 800.0,
    row_standardize: bool = True,
) -> Any:
    """
    构造 N×N 空间权重矩阵 W（对角线 0）。
    共享单车邻里效应通常用最近 k 站（客流共享），默认 knn, k=5。
    """
    import numpy as _np

    D = pairwise_distance_matrix(zones, zone_order)
    n = D.shape[0]
    if weight == "knn":
        k_eff = max(1, min(int(k), n - 1))
        W = _np.zeros_like(D)
        for i in range(n):
            # 最近 k_eff 个邻居；对称化：i∈Nk(j) 或 j∈Nk(i)
            order = _np.argsort(D[i, :])
            for j in order[: k_eff + 1]:
                if i != j and _np.isfinite(D[i, int(j)]):
                    W[i, int(j)] = 1.0
                    W[int(j), i] = 1.0
    else:  # distance_band
        band = float(band_m)
        W = ((D < band) & _np.isfinite(D)).astype(_np.float64)
        _np.fill_diagonal(W, 0.0)

    if row_standardize:
        row_sums = W.sum(axis=1, keepdims=True)
        row_sums[row_sums == 0] = 1.0
        W = W / row_sums
    return W


def global_morans_i(x, W) -> dict[str, Any]:
    """全局 Moran's I。x (N,)，W (N,N) 行标准化。"""
    import numpy as _np

    x = _np.asarray(x, dtype=_np.float64).reshape(-1)
    n = x.shape[0]
    if n < 3 or W.shape != (n, n):
        return {"I": None, "expected": None}
    z = x - x.mean()
    s2 = float((z * z).sum())
    if s2 <= 0:
        return {
            "I": 0.0,
            "expected": float(-1.0 / (n - 1)),
            "z_score": 0.0,
            "p_value": 1.0,
            "var_i": 0.0,
            "S0": 0.0,
            "interpretation": "constant attribute, no variation",
        }
    import math as _math

    S0 = float(W.sum()) or 1.0
    num = float(n * ((z[:, None] * z[None, :]) * W).sum())
    den = S0 * s2
    I = num / den
    expected = float(-1.0 / (n - 1))
    # 正态近似（Cliff & Ord 方差；作品集参考级）
    W2_WT = float((W * W.T).sum())
    S1 = 0.5 * W2_WT
    S2 = float(((W.sum(axis=1) + W.sum(axis=0)) ** 2).sum())
    # b2 = 样本峰度（标准化四阶矩）：b2 = n * Σz^4 / (Σz^2)^2
    z4 = float((z ** 4).sum())
    s2_sq = s2 * s2 or 1.0
    b2 = float(n * z4 / s2_sq) if n > 0 else 0.0
    A = n * ((n ** 2 - 3 * n + 3) * S1 - n * S2 + 3 * S0 ** 2)
    B = b2 * ((n ** 2 - n) * S1 - 2 * n * S2 + 6 * S0 ** 2)
    C = (n - 1) * (n - 2) * (n - 3) * S0 ** 2
    var_i = (A - B) / C - expected ** 2 if C > 0 else 0.0
    # 数值稳定：方差极小时（或因浮点导致负值）视为"近零方差 → 无有效推断"
    # 阈值 1e-10 远低于真实 I 值（~0.01量级）的理论方差，避免 1e-18 clamp 把 z 放大到数千万
    if not (var_i > 1e-10):
        z_score = 0.0
        p_value = 1.0
        interp = "random (near-zero variance; spatial pattern not distinguishable from CSR)"
    else:
        sd = _math.sqrt(var_i)
        z_score = float((I - expected) / sd)
        # 双侧 p 值：基于标准正态近似 |Z|
        abs_z = abs(z_score)
        # erf 近似：P(|Z| > z) ≈ erfc(z/√2)
        p_value = float(_math.erfc(abs_z / 1.41421356237))
        if z_score > 1.96:
            interp = "clustered (HH/LL dominant; significant positive spatial autocorrelation)"
        elif z_score < -1.96:
            interp = "dispersed (HL/LH dominant; significant negative spatial autocorrelation)"
        else:
            interp = "random (weak spatial autocorrelation; pattern not distinguishable from CSR)"
    return {
        "I": float(I),
        "expected": expected,
        "z_score": z_score,
        "p_value": p_value,
        "var_i": float(var_i),
        "S0": S0,
        "interpretation": interp,
    }


def local_morans_i(x, W, n_perm: int = 199, seed: int = 42) -> dict[str, Any]:
    """
    局部 Moran's I (LISA)：返回每站 Ii / z_x / lag_z / cluster (HH/LL/HL/LH/NS) / 置换 p_sim。
    cluster 采用 Anselin 四象限分类 + 弱显著性阈值（|z|<1 → NS），便于 GIS 作品集地图直接上色。
    """
    import numpy as _np

    x = _np.asarray(x, dtype=_np.float64).reshape(-1)
    n = x.shape[0]
    if n < 3:
        return {"Ii": [], "z_x": [], "lag_z": [], "cluster": ["NS"] * n, "p_sim": [1.0] * n}

    z = x - x.mean()
    m2 = float((z * z).sum() / max(1, n - 1)) or 1.0
    z_std = z / math.sqrt(m2)
    lag = W @ z
    lag_std = W @ z_std

    Ii = _np.zeros(n, dtype=_np.float64)
    for i in range(n):
        Ii[i] = float((z[i] / m2) * lag[i])

    clusters: list[str] = []
    sig_thresh = 1.0
    for i in range(n):
        zx = float(z_std[i])
        lz = float(lag_std[i])
        if abs(zx) < sig_thresh and abs(lz) < sig_thresh:
            clusters.append("NS")
        elif zx > 0 and lz > 0:
            clusters.append("HH")
        elif zx < 0 and lz < 0:
            clusters.append("LL")
        elif zx > 0 and lz < 0:
            clusters.append("HL")
        else:
            clusters.append("LH")

    rng = _np.random.default_rng(seed)
    p_sim = _np.ones(n, dtype=_np.float64)
    if n_perm and n > 3:
        Ii_abs = _np.abs(Ii)
        counts = _np.zeros(n, dtype=_np.int64)
        for _ in range(n_perm):
            idx = rng.permutation(n)
            zp = z[idx]
            lag_p = W @ zp
            Ii_p = _np.zeros(n, dtype=_np.float64)
            for i in range(n):
                Ii_p[i] = float((z[i] / m2) * lag_p[i])
            counts += (_np.abs(Ii_p) >= Ii_abs).astype(_np.int64)
        p_sim = (counts + 1.0) / (n_perm + 1.0)

    return {
        "Ii": [float(v) for v in Ii.tolist()],
        "z_x": [float(v) for v in z_std.tolist()],
        "lag_z": [float(v) for v in lag_std.tolist()],
        "cluster": clusters,
        "p_sim": [float(v) for v in p_sim.tolist()],
    }


def od_ipf_approx(outflow, inflow, cost, beta: float = 0.0012,
                  max_iter: int = 200, tol: float = 1e-5):
    """
    近似 OD 矩阵：重力模型（exp(-β·d) 阻抗）+ IPF 使行列边际匹配 outflow / inflow。
    - outflow (N,) / inflow (N,): 各站该时段起点/终点总流量
    - cost (N,N): 米制距离矩阵
    - beta: 距离衰减系数（Citi Bike 短租 ~ 0.0008–0.0015 m⁻¹）
    返回 (N,N) 非负矩阵，对角线为 0。
    """
    import numpy as _np

    outflow = _np.asarray(outflow, dtype=_np.float64).reshape(-1).clip(min=0.0)
    inflow = _np.asarray(inflow, dtype=_np.float64).reshape(-1).clip(min=0.0)
    n = outflow.shape[0]
    cost = _np.asarray(cost, dtype=_np.float64).reshape(n, n)

    f = _np.exp(-beta * cost)
    _np.fill_diagonal(f, 0.0)
    f = _np.clip(f, 1e-9, None)

    T = f.copy()
    for _ in range(max_iter):
        row_sum = T.sum(axis=1, keepdims=True)
        row_sum[row_sum == 0] = 1.0
        T = T * (outflow[:, None] / row_sum)
        col_sum = T.sum(axis=0, keepdims=True)
        col_sum[col_sum == 0] = 1.0
        T = T * (inflow[None, :] / col_sum)
        err_row = float(_np.max(_np.abs(T.sum(axis=1) - outflow)))
        err_col = float(_np.max(_np.abs(T.sum(axis=0) - inflow)))
        if max(err_row, err_col) < tol:
            break
    return T
