"""
GIS 作品集扩展 API（面向 GIS MS 申请叙事）
路由前缀: /api/gis

1. /timeline           — 24h 时空立方体切片（P0 时间滑块动画数据源）
2. /projection_audit   — 投影修复证据（23% 误差 → <1%）
3. /spatial_stats      — 全局 Moran's I + 局部 LISA 冷热点（P1 Moran Tab）
4. /od_flows           — OD 潮汐流线（P1 OD 弧线层，真实数据优先，IPF 兜底）
5. /typical_day        — 工作日 vs 周末典型日曲线（P2 研究页）
"""
from __future__ import annotations

import re
from typing import Any, Literal

import numpy as np
from fastapi import APIRouter, HTTPException, Query

from ..config import DATA_DIR, SIM_INTERVAL_MINUTES, TARGET_CAPACITY_RATIO
from ..services.geoutils import (
    distance_between_centers,
    global_morans_i,
    local_morans_i,
    od_ipf_approx,
    pairwise_distance_matrix,
    projection_audit,
    spatial_weight_matrix,
)
from ..state import get_generator, get_zone_order, get_zones, get_zones_version

router = APIRouter()


# ---------------------------------------------------------------------
# 工具：时间格式 & OD 真实数据
# ---------------------------------------------------------------------

def _parse_hhmm(s: str) -> int:
    if not re.match(r"^\d{2}:\d{2}$", s):
        raise HTTPException(status_code=400, detail="Invalid time. Expected HH:MM.")
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _format_hhmm(total: int) -> str:
    total %= 24 * 60
    return f"{total // 60:02d}:{total % 60:02d}"


_OD_CACHE: dict[str, Any] | None = None  # 仅进程内缓存，省掉每次读盘


def _load_od_matrix() -> dict[str, Any] | None:
    """尝试从 data/od_matrix.npz 加载真实 OD（citibike parquet 聚合产物）。
    文件结构（prepare_trips.py 生成）:
      - slot_od: [T_per_day, N, N]   np.uint32   每个时段的双向 OD 计数
      - outflow:   [T_per_day, N]    每时段每站总起点数
      - inflow:    [T_per_day, N]    每时段每站总终点数
      - station_ids: list[str]        顺序映射
    """
    global _OD_CACHE
    if _OD_CACHE is not None:
        return _OD_CACHE
    path = DATA_DIR / "od_matrix.npz"
    if not path.exists():
        return None
    try:
        d = np.load(path, allow_pickle=True)
        _OD_CACHE = {
            "slot_od": np.asarray(d["slot_od"], dtype=np.float32),
            "outflow": np.asarray(d["outflow"], dtype=np.float32),
            "inflow": np.asarray(d["inflow"], dtype=np.float32),
            "station_ids": [str(x) for x in np.asarray(d["station_ids"]).tolist()],
        }
        return _OD_CACHE
    except Exception:
        return None


def _hhmm_to_slot(hhmm: str) -> int:
    return _parse_hhmm(hhmm) // SIM_INTERVAL_MINUTES


# ---------------------------------------------------------------------
# P0：24h 时空立方体切片（时间滑块回放）
# ---------------------------------------------------------------------

@router.get("/timeline")
def timeline(
    time: str = Query("00:00", description="起始时间 HH:MM"),
    steps: int = Query(288, ge=2, le=576, description="时间步数（默认288=24h × 5min）"),
    interval: int = Query(SIM_INTERVAL_MINUTES, ge=5, le=60, description="聚合步长(分钟)，需为5的倍数"),
    day_index: int = Query(0, ge=0, description="回放的天序号(0~150,超过自动取模)"),
    mode: Literal["vehicle", "need", "ratio"] = Query("vehicle", description="返回模式：车辆数/短缺度/容量比"),
) -> dict[str, Any]:
    """
    返回以 time 为起点、steps 步、每步 interval 分钟的时空立方体切片：
      times: [steps] 时间标签
      zones: [steps, N_zone] 对应值矩阵（按 zone_order 排序）
    用于前端 P0 时间滑块 + 潮汐动画。
    """
    if interval % SIM_INTERVAL_MINUTES != 0:
        raise HTTPException(status_code=400, detail=f"interval must be multiple of {SIM_INTERVAL_MINUTES}")
    agg = interval // SIM_INTERVAL_MINUTES  # 每聚合块含多少原始5分钟槽

    zones = get_zones()
    zone_order = get_zone_order()
    gen = get_generator()
    capacity_map = gen.capacity_by_zone()

    # 取一整天序列（从 start 起始 + 必要时取第二天补齐）
    start_slot = _hhmm_to_slot(time)
    total_need = steps * agg
    # 从 day_index 起最多读两天
    mats = []
    for offset_day in range(0, 2):
        times_day, mat_day = gen.generate_day_series("00:00", day_index + offset_day)  # [T, Nz]
        mats.append(mat_day)
    mat = np.concatenate(mats, axis=0)  # [2T, Nz]
    # 切出需要的窗口
    T_per_day = mats[0].shape[0]
    slot_start_abs = start_slot  # 相对于第0天起点
    mat_window = mat[slot_start_abs: slot_start_abs + total_need]  # [steps*agg, Nz]

    # 聚合（每 agg 块取均值或末值；车辆数用末值更贴近当时状态）
    if agg > 1:
        n = mat_window.shape[0] // agg * agg
        mat_window = mat_window[:n].reshape(-1, agg, mat_window.shape[1])
        mat_agg = mat_window[:, -1, :]  # 每块取最后一个时间片
    else:
        mat_agg = mat_window

    # 时间标签
    start_min = _parse_hhmm(time)
    times = [_format_hhmm(start_min + i * interval) for i in range(steps)]

    # 值变换
    capacity_vec = np.asarray([capacity_map.get(z, 0.0) for z in zone_order], dtype=np.float32)
    target_vec = capacity_vec * TARGET_CAPACITY_RATIO
    if mode == "need":
        # need = target - current  (正=短缺,负=盈余)
        values = (target_vec[None, :] - mat_agg).astype(np.float32)
    elif mode == "ratio":
        safe_cap = np.where(capacity_vec > 0, capacity_vec, 1.0)
        values = (mat_agg / safe_cap[None, :]).astype(np.float32)
    else:
        values = mat_agg.astype(np.float32)

    return {
        "mode": mode,
        "interval_minutes": interval,
        "times": times,
        "zone_order": zone_order,
        "values": values.tolist(),
        "capacity": [float(capacity_map.get(z, 0.0)) for z in zone_order],
        "zones_version": get_zones_version(),
        "n_zones": len(zone_order),
        "n_steps": len(times),
    }


# ---------------------------------------------------------------------
# 投影审计（作品集证据卡）
# ---------------------------------------------------------------------

@router.get("/projection_audit")
def api_projection_audit() -> dict[str, Any]:
    """
    返回投影修复证据：对比 naive（经纬度直接当米，~23% 系统误差）
    与 UTM/ENU 投影（误差 <1%）。
    """
    zones = get_zones()
    try:
        return projection_audit(zones)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"projection_audit failed: {e}")


# ---------------------------------------------------------------------
# 空间自相关：全局 Moran's I + 局部 LISA
# ---------------------------------------------------------------------

@router.get("/spatial_stats")
def spatial_stats(
    time: str = Query("08:30", description="时间 HH:MM"),
    day_index: int = Query(0, ge=0, description="天序号"),
    weight: Literal["knn", "distance_band"] = Query("knn", description="空间权重类型"),
    k: int = Query(5, ge=1, le=29, description="knn 邻居数"),
    band_m: float = Query(800.0, ge=50.0, description="distance_band 阈值(米)"),
    attr: Literal["need", "vehicles", "ratio"] = Query("need", description="计算 I 的属性"),
    threshold_shortage: float = Query(3.0, ge=0.0, description="短缺阈值"),
    threshold_surplus: float = Query(3.0, ge=0.0, description="盈余阈值"),
) -> dict[str, Any]:
    """
    返回时空数据下某时刻的空间自相关结果：
      global: {I, expected, z_score, interpretation}
      local:  [{zone_id, Ii, cluster(HH/LL/HL/LH/NS), p_sim, z_x, lag_z}]
      W_meta: 权重矩阵元信息
      status_map: {zone_id → shortage/surplus/healthy}
    """
    zones = get_zones()
    zone_order = get_zone_order()
    gen = get_generator()
    snap = gen.simulate_snapshot(time=time, day_index=day_index)
    cap = gen.capacity_by_zone()

    # 组装属性向量 x（按 zone_order）
    x_list = []
    statuses = {}
    for zid in zone_order:
        v = float(snap.vehicles_by_zone.get(zid, 0))
        c = float(cap.get(zid, 0.0)) or 1.0
        target = c * TARGET_CAPACITY_RATIO
        need = target - v
        ratio = v / c if c > 0 else 0.0
        if attr == "need":
            x_list.append(need)
        elif attr == "ratio":
            x_list.append(ratio)
        else:
            x_list.append(v)
        # status（基于 need，与地图配色一致）
        if need >= threshold_shortage:
            statuses[zid] = "shortage"
        elif need <= -threshold_surplus:
            statuses[zid] = "surplus"
        else:
            statuses[zid] = "healthy"

    x = np.asarray(x_list, dtype=np.float64)
    W = spatial_weight_matrix(zones, zone_order, weight=weight, k=k, band_m=band_m)
    g = global_morans_i(x, W)
    lisa = local_morans_i(x, W, n_perm=199, seed=42)

    local_list: list[dict[str, Any]] = []
    for i, zid in enumerate(zone_order):
        lon, lat = zones[zid].center_lonlat
        local_list.append({
            "zone_id": zid,
            "name": zones[zid].name,
            "center_lonlat": [lon, lat],
            "Ii": float(lisa["Ii"][i]),
            "z_x": float(lisa["z_x"][i]),
            "lag_z": float(lisa["lag_z"][i]),
            "cluster": str(lisa["cluster"][i]),
            "p_sim": float(lisa["p_sim"][i]),
            "status": statuses[zid],
            "vehicles": int(snap.vehicles_by_zone.get(zid, 0)),
            "need": float(target - snap.vehicles_by_zone.get(zid, 0))
                if attr == "need" else None,
            "attr_value": float(x[i]),
        })

    # 用于前端图层的冷热点颜色映射
    cluster_count = {"HH": 0, "LL": 0, "HL": 0, "LH": 0, "NS": 0}
    for it in local_list:
        cluster_count[it["cluster"]] = cluster_count.get(it["cluster"], 0) + 1

    return {
        "time": time,
        "day_index": day_index,
        "attr": attr,
        "weight": weight,
        "weight_param": {"k": k, "band_m": band_m} if weight == "knn" else {"band_m": band_m},
        "global": g,
        "cluster_count": cluster_count,
        "local": local_list,
        "zones_version": get_zones_version(),
    }


# ---------------------------------------------------------------------
# P1 OD 潮汐流线（真实 OD 优先，IPF 兜底）
# ---------------------------------------------------------------------

@router.get("/od_flows")
def od_flows(
    time: str = Query("08:30", description="时间 HH:MM（起点站发车时刻）"),
    window_minutes: int = Query(60, ge=15, le=180, description="聚合窗口（分钟，5的倍数）"),
    day_index: int = Query(0, ge=0, description="工作日/周末样例天序号"),
    top_k: int = Query(40, ge=5, le=300, description="返回流量最大的 K 条（地图性能）"),
    beta: float = Query(0.0012, ge=1e-5, description="重力模型距离衰减系数（真实OD缺失时兜底用）"),
) -> dict[str, Any]:
    """
    返回指定时间窗口内站点间 OD 流线（供前端弧线层渲染）：
      edges: [{from_id, to_id, from_lonlat, to_lonlat, count, weight_norm}]
      outflow_top / inflow_top: 各站净差值 Top-10（叙事）
      source: 'real_od' | 'ipf_approx'
    """
    if window_minutes % SIM_INTERVAL_MINUTES != 0:
        raise HTTPException(
            status_code=400,
            detail=f"window_minutes must be multiple of {SIM_INTERVAL_MINUTES}",
        )
    n_slots = window_minutes // SIM_INTERVAL_MINUTES
    start_slot = _hhmm_to_slot(time)

    zones = get_zones()
    zone_order = get_zone_order()
    Nz = len(zone_order)
    idx_of = {zid: i for i, zid in enumerate(zone_order)}

    # ---- 1) 优先真实 OD ----
    real_od = _load_od_matrix()
    source = "ipf_approx"
    od_mat: np.ndarray | None = None
    outflow_vec: np.ndarray | None = None
    inflow_vec: np.ndarray | None = None

    if real_od is not None:
        try:
            st_ids = real_od["station_ids"]
            st_idx_of = {s: i for i, s in enumerate(st_ids)}
            Nst = len(st_ids)
            T_per_day = real_od["slot_od"].shape[0]

            # 读窗口内 slot_od 并累加
            slot_od_win = np.zeros((Nz, Nz), dtype=np.float64)
            O_win = np.zeros(Nz, dtype=np.float64)
            I_win = np.zeros(Nz, dtype=np.float64)
            n_days_data = 1  # slot_od 如为 [T,N,N]，已聚合所有天；否则再从 prepare_trips 保证
            # 注意: prepare_trips 生成的 slot_od 形状可以是 [T,N,N]（跨天累计的平均）或完整
            # 这里采用最宽容策略：按 [T,N,N] 的时间窗口切片求和
            for k in range(n_slots):
                s = (start_slot + k) % T_per_day
                slice_mat = real_od["slot_od"][s]  # [Nst, Nst] 假设
                if slice_mat.shape[0] < Nst or slice_mat.shape[1] < Nst:
                    continue
                for zi, zid in enumerate(zone_order):
                    si = st_idx_of.get(zid, -1)
                    if si < 0:
                        continue
                    for zj, zjd in enumerate(zone_order):
                        sj = st_idx_of.get(zjd, -1)
                        if sj < 0:
                            continue
                        slot_od_win[zi, zj] += float(slice_mat[si, sj])
                # 边际
                out_slice = real_od["outflow"][s]  # [Nst]
                in_slice = real_od["inflow"][s]
                for zi, zid in enumerate(zone_order):
                    si = st_idx_of.get(zid, -1)
                    if si < 0:
                        continue
                    O_win[zi] += float(out_slice[si])
                    I_win[zi] += float(in_slice[si])
            total_flow = float(slot_od_win.sum())
            if total_flow > 0:
                od_mat = slot_od_win
                outflow_vec = O_win
                inflow_vec = I_win
                source = "real_od"
            _ = n_days_data
        except Exception:
            od_mat = None

    # ---- 2) IPF 兜底（重力模型 + 迭代比例拟合）----
    if od_mat is None:
        gen = get_generator()
        # 用时间窗口内的平均 net_delta 近似 outflow/inflow 边际
        # inflow/outflow 需要近似；这里用窗口内首尾车辆数差作为 net，
        # 再用 capacity 比例分配 gross，保证可作为 IPF 输入
        cap_map = gen.capacity_by_zone()
        cap_vec = np.asarray([cap_map.get(z, 1.0) for z in zone_order], dtype=np.float64)
        # 先取窗口内每站起点/终点总流量的近似：
        #   近似：用每站的容量 * 0.4 作为基准总活动度，再用高峰时段放大
        is_morning = 6.5 <= _parse_hhmm(time) / 60 <= 10.5
        is_evening = 16 <= _parse_hhmm(time) / 60 <= 20
        peak_factor = 1.4 if (is_morning or is_evening) else 0.6
        # outflow 近似: 早高峰从居住区流出 → 核心区属于目的地区，inflow 偏大
        base = cap_vec * peak_factor
        O_base = base * (0.7 if is_morning else 1.2 if is_evening else 1.0)
        I_base = base * (1.3 if is_morning else 0.8 if is_evening else 1.0)
        # 用窗口内车辆数变化做轻微校正（net = last - first）
        # 先读窗口两端 snapshot
        snap_first = gen.simulate_snapshot(time=_format_hhmm(_parse_hhmm(time)), day_index=day_index)
        snap_last = gen.simulate_snapshot(
            time=_format_hhmm(_parse_hhmm(time) + window_minutes),
            day_index=day_index,
        )
        first = np.asarray([snap_first.vehicles_by_zone.get(z, 0) for z in zone_order], dtype=np.float64)
        last = np.asarray([snap_last.vehicles_by_zone.get(z, 0) for z in zone_order], dtype=np.float64)
        net = last - first  # 正值=净流入,负值=净流出
        # 令 outflow - inflow = -net (车辆数增加意味着 inflow > outflow)
        # 解 O - I = -net 且 O,I>=0；简单做法: 让 gross = max(|net|*1.8, base_mean)
        gross_per_station = np.maximum(np.abs(net) * 2.2, O_base + I_base) * 0.5 + 1.0
        outflow_vec = np.maximum(0.0, gross_per_station - net * 0.5)
        inflow_vec = np.maximum(0.0, gross_per_station + net * 0.5)

        # 距离矩阵 + IPF
        D = pairwise_distance_matrix(zones, zone_order)
        od_mat = od_ipf_approx(outflow_vec, inflow_vec, D, beta=float(beta))
        # 去掉对角线
        for i in range(Nz):
            od_mat[i, i] = 0.0

    # ---- 3) Top-K 边（流量最大者优先，保证地图性能）----
    edges: list[dict[str, Any]] = []
    for i in range(Nz):
        for j in range(Nz):
            if i == j:
                continue
            c = float(od_mat[i, j])
            if c <= 0:
                continue
            z_a = zone_order[i]
            z_b = zone_order[j]
            la = zones[z_a].center_lonlat
            lb = zones[z_b].center_lonlat
            edges.append({
                "from_id": z_a,
                "to_id": z_b,
                "from_name": zones[z_a].name,
                "to_name": zones[z_b].name,
                "from_lonlat": [la[0], la[1]],
                "to_lonlat": [lb[0], lb[1]],
                "count": round(c, 2),
                "distance_m": round(float(distance_between_centers(zones[z_a], zones[z_b])), 1),
            })
    edges.sort(key=lambda e: e["count"], reverse=True)
    edges = edges[: max(1, int(top_k))]
    if edges:
        max_c = max(e["count"] for e in edges)
        for e in edges:
            e["weight_norm"] = round(max(0.08, min(1.0, e["count"] / max(max_c, 1e-9))), 3)
    else:
        for e in edges:
            e["weight_norm"] = 0.0

    # ---- 4) Outflow/Inflow Top 站（叙事用）----
    if outflow_vec is not None and inflow_vec is not None:
        net = inflow_vec - outflow_vec
    else:
        net = np.zeros(Nz, dtype=np.float64)
    ranked_idx = np.argsort(-net).tolist()
    inflow_top = [
        {"zone_id": zone_order[i], "name": zones[zone_order[i]].name,
         "net": round(float(net[i]), 2),
         "outflow": round(float(outflow_vec[i]), 2) if outflow_vec is not None else None,
         "inflow": round(float(inflow_vec[i]), 2) if inflow_vec is not None else None}
        for i in ranked_idx[:10]
    ]
    outflow_top = [
        {"zone_id": zone_order[i], "name": zones[zone_order[i]].name,
         "net": round(float(net[i]), 2),
         "outflow": round(float(outflow_vec[i]), 2) if outflow_vec is not None else None,
         "inflow": round(float(inflow_vec[i]), 2) if inflow_vec is not None else None}
        for i in ranked_idx[-10:][::-1]
    ]

    return {
        "time": time,
        "window_minutes": window_minutes,
        "source": source,
        "total_flow_estimate": round(float(od_mat.sum()), 2),
        "edges": edges,
        "inflow_top": inflow_top,
        "outflow_top": outflow_top,
        "zone_order": zone_order,
        "zones_version": get_zones_version(),
    }


# ---------------------------------------------------------------------
# P2 典型日对比：工作日 vs 周末
# ---------------------------------------------------------------------

@router.get("/typical_day")
def typical_day(
    interval_minutes: int = Query(30, ge=5, le=120, description="聚合粒度"),
) -> dict[str, Any]:
    """
    返回工作日平均 vs 周末平均的每站车辆数曲线（按 zone_order 排列）：
      weekday: {times, values_by_zone [Nz][T]}
      weekend: {times, values_by_zone [Nz][T]}
      n_weekday, n_weekend: 样本天数
    """
    if interval_minutes % SIM_INTERVAL_MINUTES != 0:
        raise HTTPException(status_code=400,
                            detail=f"interval must be multiple of {SIM_INTERVAL_MINUTES}")
    agg = interval_minutes // SIM_INTERVAL_MINUTES

    gen = get_generator()
    zone_order = get_zone_order()
    n_days = gen.n_days

    # 天 0 是 2025-01-01（周三；这里用简单模7判断，prepare_trips 用连续日期）
    # 因为我们不知道起始星期，采用近似: 前120天训练集，其中第 5..9,12..16,... 视为工作日
    # 更稳妥的方式：用内置 day_index 近似（1/7 周末比例），假设从周三起：
    # weekday_idx: [0,1,2,3,5,6,7,8,10,11,...] 即 (idx + 2) % 7 not in {5,6}
    weekday_idx = []
    weekend_idx = []
    for d in range(n_days):
        w = (d + 2) % 7  # day0=Wednesday，加2→周五开始，因此 {5,6}=周末
        if w in (5, 6):
            weekend_idx.append(d)
        else:
            weekday_idx.append(d)

    def _avg(day_list: list[int]) -> tuple[list[str], list[list[float]]]:
        if not day_list:
            return [], []
        # 先聚合为 [T/agg, Nz] 每天，再按天平均
        _, mat0 = gen.generate_day_series("00:00", day_list[0])
        T_raw = mat0.shape[0]
        Nz = mat0.shape[1]
        T_agg = T_raw // agg
        acc = np.zeros((T_agg, Nz), dtype=np.float64)
        for d in day_list:
            _, m = gen.generate_day_series("00:00", d)
            m_agg = m[: T_agg * agg].reshape(T_agg, agg, Nz).mean(axis=1)
            acc += m_agg
        acc /= len(day_list)
        times = [_format_hhmm(i * interval_minutes) for i in range(T_agg)]
        values_by_zone = [acc[:, i].round(2).tolist() for i in range(Nz)]
        return times, values_by_zone

    wd_times, wd_values = _avg(weekday_idx)
    we_times, we_values = _avg(weekend_idx)

    return {
        "interval_minutes": interval_minutes,
        "n_weekday": len(weekday_idx),
        "n_weekend": len(weekend_idx),
        "weekday": {"times": wd_times, "values_by_zone": wd_values},
        "weekend": {"times": we_times, "values_by_zone": we_values},
        "zone_order": zone_order,
        "zones_version": get_zones_version(),
    }
