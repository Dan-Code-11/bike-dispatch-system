"""
prepare_trips.py — 真实 Citi Bike 数据预处理

输入:d:/bike_dispatch_system/citibike/2501.parquet ~ 2505.parquet (5 个月)
输出:
  data/trips_5min.npz         — 训练用矩阵 [N_day, T_per_day, N_station, 2(outflow,inflow)]
  data/bikes_5min.npz         — 站点车辆数序列 [N_day, T_per_day, N_station]
  data/stations.json          — 站点元数据(id, name, lat, lng)
  data/manhattan_zones.geojson — 用站点 buffer 自动生成的真实区域(曼哈顿周边真实坐标)

策略:
  1. 以 NYU Washington Square Park (40.7293, -73.9974) 为中心,矩形 bbox 半径 ~2km 过滤
  2. 统计 bbox 内所有站点频次,取 top-30 作为预测区域
  3. 仅保留 top-30 站点之间的 trip
  4. 按 5min 时间片聚合:每个站点每片的 outflow(借出) / inflow(还入)
  5. 构建车辆数序列:初始容量 + 累积(inflow - outflow),clip 到 [0, capacity]
  6. buffer(100m)生成每个站点的真实多边形区域

运行:
    cd d:\\bike_dispatch_system
    python backend/scripts/prepare_trips.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------- 配置 ----------------------
ROOT = Path(__file__).resolve().parent.parent.parent
CITIBIKE_DIR = ROOT / "citibike"
OUT_DIR = ROOT / "data"

# NYU Washington Square Park 中心
CENTER_LAT = 40.7293
CENTER_LNG = -73.9974
# bbox 半度偏移(约 ±2km)
LAT_OFFSET = 0.018   # ≈ ±2.0 km
LNG_OFFSET = 0.024   # ≈ ±2.0 km(在 40.7°N)
BBOX = (CENTER_LNG - LNG_OFFSET, CENTER_LAT - LAT_OFFSET,
        CENTER_LNG + LNG_OFFSET, CENTER_LAT + LAT_OFFSET)  # (min_lng, min_lat, max_lng, max_lat)

TOP_N_STATIONS = 30
TIME_BIN_MIN = 5
BUFFER_RADIUS_M = 100  # 站点缓冲半径(米)
# 容量推断:不再用固定 30,从每站真实借还波动幅度推断
# 高频站(借还多)→ 容量大;低频站 → 容量小
MIN_CAPACITY = 12   # 最小容量(避免极低频站容量为个位数)
CAPACITY_BUFFER = 1.3  # 容量 = 波动幅度 × 1.3 + 5,留余量

# Stage3 多步预测超参数（与 config.py 对齐）
HISTORY_STEPS = 24          # 24*5min = 2h 历史
PRED_FULL_STEPS = 36        # 36*5min = 3h 预测全长
PRED_KEY_HORIZONS = [12, 24, 36]  # 3 个关键锚点(step index,1-based → 1h/2h/3h)


def main() -> None:
    print("=" * 70)
    print("Citi Bike 真实数据预处理")
    print("=" * 70)
    print(f"中心点: NYU Washington Square Park ({CENTER_LAT}, {CENTER_LNG})")
    print(f"bbox: lng[{BBOX[0]:.4f}, {BBOX[2]:.4f}] lat[{BBOX[1]:.4f}, {BBOX[3]:.4f}]")
    print(f"目标: top-{TOP_N_STATIONS} 站点, {TIME_BIN_MIN}min 聚合")
    print()

    # ---------------------- Step 1: 读 + bbox 过滤 ----------------------
    print("[1/6] 读取 5 个月 parquet 并做 bbox 过滤...")
    parquet_files = sorted(CITIBIKE_DIR.glob("*.parquet"))
    print(f"  发现 {len(parquet_files)} 个 parquet 文件: {[f.name for f in parquet_files]}")

    cols = ["started_at", "ended_at",
            "start_station_id", "start_station_name", "start_lat", "start_lng",
            "end_station_id", "end_station_name", "end_lat", "end_lng"]

    frames = []
    total_raw = 0
    for f in parquet_files:
        df = pd.read_parquet(f, columns=cols)
        total_raw += len(df)
        # bbox 过滤:起点或终点至少有一个在 bbox 内
        s_in = (df["start_lng"].between(BBOX[0], BBOX[2]) &
                df["start_lat"].between(BBOX[1], BBOX[3]))
        e_in = (df["end_lng"].between(BBOX[0], BBOX[2]) &
                df["end_lat"].between(BBOX[1], BBOX[3]))
        df_in = df[s_in | e_in].copy()
        frames.append(df_in)
        print(f"  {f.name}: 原始 {len(df):,} → bbox 内 {len(df_in):,}")
    df_all = pd.concat(frames, ignore_index=True)
    print(f"  合计:原始 {total_raw:,} → bbox 内 {len(df_all):,}")
    print()

    # ---------------------- Step 2: 站点频次统计 + top-N ----------------------
    print(f"[2/6] 统计站点频次,取 top-{TOP_N_STATIONS}...")
    # 站点元数据(去重,取经纬度均值)
    start_meta = (df_all.groupby("start_station_id")
                  .agg(name=("start_station_name", "first"),
                       lat=("start_lat", "mean"),
                       lng=("start_lng", "mean"))
                  .reset_index().rename(columns={"start_station_id": "station_id"}))
    end_meta = (df_all.groupby("end_station_id")
                .agg(name=("end_station_name", "first"),
                     lat=("end_lat", "mean"),
                     lng=("end_lng", "mean"))
                .reset_index().rename(columns={"end_station_id": "station_id"}))
    # 合并起终点元数据(同一 id 可能作起点也作终点)
    meta = pd.concat([start_meta, end_meta]).groupby("station_id", as_index=False).agg(
        name=("name", "first"),
        lat=("lat", "mean"),
        lng=("lng", "mean"),
    )
    # 频次 = 作起点次数 + 作终点次数
    start_cnt = df_all["start_station_id"].value_counts()
    end_cnt = df_all["end_station_id"].value_counts()
    freq = start_cnt.add(end_cnt, fill_value=0).astype(int)
    meta["freq"] = meta["station_id"].map(freq).fillna(0).astype(int)
    meta = meta.sort_values("freq", ascending=False).reset_index(drop=True)

    top = meta.head(TOP_N_STATIONS).copy()
    print(f"  top-{TOP_N_STATIONS} 站点频次范围: "
          f"{top['freq'].min():,} ~ {top['freq'].max():,}")
    print(f"  示例站点:")
    for _, r in top.head(5).iterrows():
        print(f"    {r['station_id']:>10}  {r['name']:<40} freq={r['freq']:,}")
    print()

    # ---------------------- Step 3: 仅保留 top-N 间 trip ----------------------
    print(f"[3/6] 仅保留 top-{TOP_N_STATIONS} 站点之间的 trip...")
    top_ids = set(top["station_id"])
    mask = df_all["start_station_id"].isin(top_ids) & df_all["end_station_id"].isin(top_ids)
    df_top = df_all.loc[mask].copy()
    print(f"  保留 {len(df_top):,} 条 trip(占 bbox 内 {len(df_top)/len(df_all)*100:.1f}%)")
    print()

    # ---------------------- Step 4: 5min 聚合 ----------------------
    print(f"[4/6] {TIME_BIN_MIN}min 时间片聚合...")
    df_top["start_bin"] = df_top["started_at"].dt.floor(f"{TIME_BIN_MIN}min")
    df_top["end_bin"] = df_top["ended_at"].dt.floor(f"{TIME_BIN_MIN}min")

    # outflow: 每站每时间片借出数
    outflow = (df_top.groupby(["start_bin", "start_station_id"]).size()
               .unstack(fill_value=0))
    # inflow: 每站每时间片还入数
    inflow = (df_top.groupby(["end_bin", "end_station_id"]).size()
              .unstack(fill_value=0))

    # 对齐到 top 站点顺序 + 完整时间索引
    all_days = pd.date_range(df_top["started_at"].min().floor("D"),
                             df_top["ended_at"].max().floor("D") + pd.Timedelta(days=1),
                             freq=f"{TIME_BIN_MIN}min")
    outflow = outflow.reindex(index=all_days, columns=top["station_id"], fill_value=0).fillna(0)
    inflow = inflow.reindex(index=all_days, columns=top["station_id"], fill_value=0).fillna(0)
    print(f"  时间序列长度: {len(outflow)} 片 × {outflow.shape[1]} 站 "
          f"= {outflow.size:,} 数据点")
    print(f"  时间范围: {outflow.index[0]} ~ {outflow.index[-1]}")
    print()

    # ---------------------- Step 5: 车辆数序列(每天独立累积 + 每站推断容量) ----------------------
    print(f"[5/6] 构建车辆数序列(每天独立累积,每站从单日波动推断容量)...")
    net = (inflow - outflow).values.astype(np.float32)  # [T, N]

    # 先 reshape 到 [N_day, T_per_day, N],每天独立 cumsum(不跨天累积)
    T_per_day = int(24 * 60 / TIME_BIN_MIN)  # 288
    N_day = len(outflow) // T_per_day
    valid_T = N_day * T_per_day

    net_3d = net[:valid_T].reshape(N_day, T_per_day, TOP_N_STATIONS)
    cum_daily = np.cumsum(net_3d, axis=1)  # [N_day, T_per_day, N] 每天从0开始的累积净变化

    # 每站基于单日波动幅度推断容量(不跨天)
    per_station_daily_min = cum_daily.min(axis=(0, 1))   # [N] 所有天中最低的单日累积值
    per_station_daily_max = cum_daily.max(axis=(0, 1))   # [N] 所有天中最高的单日累积值
    per_station_range = per_station_daily_max - per_station_daily_min  # [N] 单日最大波动幅度

    # 容量 = 单日波动 × 1.3 + 5,至少 MIN_CAPACITY
    capacity_per_station = np.maximum(
        per_station_range * CAPACITY_BUFFER + 5, MIN_CAPACITY
    ).astype(np.float32)  # [N]

    # 每天初始车辆数 = 使单日序列居中落在 [0, capacity] 内
    init_vehicles = (-per_station_daily_min) + (capacity_per_station - per_station_range) / 2  # [N]

    # 车辆数 = init + cum_daily,clip 到 [0, capacity_per_station]
    bikes = np.clip(
        init_vehicles + cum_daily,
        0,
        capacity_per_station,
    ).astype(np.float32)  # [N_day, T_per_day, N]

    print(f"  每站容量推断结果(按单日波动排序 top-5):")
    sorted_idx = np.argsort(-per_station_range)[:5]
    for i in sorted_idx:
        s = top.iloc[i]
        print(f"    {str(s['station_id']):>10}  {str(s['name'])[:30]:<30} "
              f"单日波动={per_station_range[i]:>5.0f}  容量={capacity_per_station[i]:>5.0f}  "
              f"初始={init_vehicles[i]:>5.0f}")
    print(f"  容量范围: {capacity_per_station.min():.0f} ~ {capacity_per_station.max():.0f}")
    print(f"  全期车辆数范围: {bikes.min():.0f} ~ {bikes.max():.0f}")
    print()

    # outflow/inflow 也 reshape 到 [N_day, T_per_day, N]
    outflow_arr = outflow.values[:valid_T].astype(np.float32).reshape(N_day, T_per_day, TOP_N_STATIONS)
    inflow_arr = inflow.values[:valid_T].astype(np.float32).reshape(N_day, T_per_day, TOP_N_STATIONS)
    bikes_arr = bikes  # 已是 [N_day, T_per_day, N]
    capacity_arr = capacity_per_station  # [N] 每站容量(存入 npz 供训练/推理使用)

    # reshape flow
    flow = np.stack([outflow_arr, inflow_arr], axis=-1)  # [N_day, T_per_day, N, 2]
    print(f"  flow 矩阵: {flow.shape}  (N_day, T_per_day, N_station, 2)")
    print(f"  bikes 矩阵: {bikes_arr.shape}  (N_day, T_per_day, N_station)")
    print()

    # ---------------------- Step 6: 输出 npz + stations.json + geojson ----------------------
    print("[6/8] 输出基础文件(trips/bikes/stations/geojson)...")
    OUT_DIR.mkdir(exist_ok=True)

    np.savez_compressed(OUT_DIR / "trips_5min.npz",
                        flow=flow,  # [N_day, T, N, 2]
                        timestamps=outflow.index.values[:valid_T].astype(str).reshape(N_day, T_per_day))
    np.savez_compressed(OUT_DIR / "bikes_5min.npz",
                        bikes=bikes_arr,  # [N_day, T, N]
                        capacity=capacity_arr)  # [N] 每站独立容量(数组)
    print(f"  ✓ {OUT_DIR / 'trips_5min.npz'}")
    print(f"  ✓ {OUT_DIR / 'bikes_5min.npz'}")

    # stations.json
    stations = []
    for i, (_, r) in enumerate(top.iterrows()):
        stations.append({
            "zone_id": str(r["station_id"]),
            "name": str(r["name"]),
            "lat": float(r["lat"]),
            "lng": float(r["lng"]),
            "freq": int(r["freq"]),
        })
    (OUT_DIR / "stations.json").write_text(
        json.dumps(stations, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✓ {OUT_DIR / 'stations.json'}  ({len(stations)} 站点)")

    # manhattan_zones.geojson:用 numpy 生成圆形 buffer(各向异性,考虑纬度修正)
    features = []
    deg_lat_per_m = 1.0 / 111_000.0          # 1°lat ≈ 111km
    deg_lng_per_m = 1.0 / (111_000.0 * np.cos(np.radians(CENTER_LAT)))  # 1°lng 在 40.7°N
    n_pts = 36  # 圆形顶点数
    angles = np.linspace(0, 2 * np.pi, n_pts, endpoint=False)
    for s in stations:
        # 各向异性半径(度)
        r_lat = BUFFER_RADIUS_M * deg_lat_per_m
        r_lng = BUFFER_RADIUS_M * deg_lng_per_m
        lons = s["lng"] + r_lng * np.cos(angles)
        lats = s["lat"] + r_lat * np.sin(angles)
        ring = [[float(lon), float(lat)] for lon, lat in zip(lons, lats)]
        # 闭合 ring
        ring.append(ring[0])
        features.append({
            "type": "Feature",
            "properties": {
                "zone_id": s["zone_id"],
                "name": s["name"],
                "freq": s["freq"],
            },
            "geometry": {"type": "Polygon", "coordinates": [ring]},
        })
    geojson = {"type": "FeatureCollection", "features": features}
    (OUT_DIR / "manhattan_zones.geojson").write_text(
        json.dumps(geojson, ensure_ascii=False), encoding="utf-8")
    print(f"  ✓ {OUT_DIR / 'manhattan_zones.geojson'}  ({len(features)} 真实区域,曼哈顿周边真实坐标)")
    print()

    # ---------------------- Step 6.5: 真实 OD 矩阵聚合（GIS P1 潮汐流线数据源） ----------------------
    print("[6.5/8] 聚合真实双向 OD 矩阵(5min slot × N × N)...")
    # 站点id → 数组 index 映射（与 stations.json/zone_order 严格一致）
    sid_list = [s["zone_id"] for s in stations]  # str，top30 station_id
    station_id_to_idx = {sid: i for i, sid in enumerate(sid_list)}
    Nz = len(sid_list)  # 30

    # 把 df_top 中的 start/end station_id 映射为 index
    # 注意 top["station_id"] 本身可能不是 str，统一转 str 再匹配
    sid_set = set(sid_list)

    def _map_ids(series: pd.Series) -> pd.Series:
        return series.astype(str).map(station_id_to_idx)

    # 仅需要：start_bin（作为 slot） + start_station_idx + end_station_idx
    tmp = pd.DataFrame({
        "start_bin": df_top["start_bin"],
        "s_idx": _map_ids(df_top["start_station_id"]),
        "e_idx": _map_ids(df_top["end_station_id"]),
    })
    # 丢弃任何 NaN 索引（理论上不存在，因为 mask 已经限制 top_ids 交集）
    tmp = tmp.dropna(subset=["s_idx", "e_idx"])
    tmp["s_idx"] = tmp["s_idx"].astype(np.int32)
    tmp["e_idx"] = tmp["e_idx"].astype(np.int32)

    # 构造完整的 day-slot 二维轴，按全局 day×slot 聚合后 reshape
    tmp["day_ts"] = tmp["start_bin"].dt.floor("D")
    tmp["slot"] = ((tmp["start_bin"] - tmp["day_ts"]).dt.total_seconds() / 60 / TIME_BIN_MIN).astype(np.int32)
    tmp["day_idx"] = ((tmp["day_ts"] - tmp["day_ts"].min()) / pd.Timedelta(days=1)).round().astype(np.int32)

    # 3 维计数：[day_idx, slot, from, to] → 为避免 4D 数组太稀疏，先按 (day,slot,s,e) 聚合
    agg = tmp.groupby(["day_idx", "slot", "s_idx", "e_idx"]).size().reset_index(name="cnt")

    # 得到完整的 slot_od 形状：[T_per_day, Nz, Nz]（在所有天维度上合并汇总：GIS作品集只看"典型日"聚合）
    slot_od = np.zeros((T_per_day, Nz, Nz), dtype=np.uint32)
    cnts = agg["cnt"].values.astype(np.uint32)
    s_arr = agg["s_idx"].values.astype(np.int64)
    e_arr = agg["e_idx"].values.astype(np.int64)
    sl_arr = (agg["slot"].values % T_per_day).astype(np.int64)  # 防止越界
    # np.add.at 无冲突累加
    np.add.at(slot_od, (sl_arr, s_arr, e_arr), cnts)
    # 对角线 = 站内借还（极少见），显式置 0 避免自环干扰可视化
    for i in range(Nz):
        slot_od[:, i, i] = 0

    # 汇总 outflow / inflow 每 slot 每站：直接 sum 就行
    slot_outflow = slot_od.sum(axis=2).astype(np.uint32)  # [T,N]
    slot_inflow  = slot_od.sum(axis=1).astype(np.uint32)  # [T,N]

    # 保存：gis.py 会读取此文件（如果存在），否则 fallback 到 IPF 重力模型估算
    od_path = OUT_DIR / "od_matrix.npz"
    np.savez_compressed(
        od_path,
        slot_od=slot_od,         # [T_per_day=288, Nz=30, Nz=30]  uint32
        outflow=slot_outflow,    # [T_per_day, Nz]  uint32
        inflow=slot_inflow,      # [T_per_day, Nz]  uint32
        station_ids=np.asarray(sid_list),   # [Nz] str, zone_id 顺序
        T_per_day=np.uint32(T_per_day),
        Nz=np.uint32(Nz),
        bin_minutes=np.uint32(TIME_BIN_MIN),
    )
    total_trips_od = int(slot_od.sum())
    print(f"  ✓ {od_path}")
    print(f"    形状 slot_od={slot_od.shape}, outflow={slot_outflow.shape}, inflow={slot_inflow.shape}")
    print(f"    聚合总 trip={total_trips_od:,}（所有天 merge 为典型日）")
    # 早晚高峰样本检查
    morning_slot = 8 * 12 + 6  # 08:30
    evening_slot = 17 * 12     # 17:00
    print(f"    早高峰(08:30) Top OD 对 count_max={int(slot_od[morning_slot].max())}")
    print(f"    晚高峰(17:00) Top OD 对 count_max={int(slot_od[evening_slot].max())}")
    print()

    # ---------------------- Step 7: 构建 stage3 训练特征张量 ----------------------
    print("[7/8] 构建多步多尺度训练特征 train_ready.npz...")
    N_station = TOP_N_STATIONS
    # 车辆数数组 bikes_arr 形状 [N_day, T_per_day, N] = [D, T, N]  车辆数(已clip到[0,cap])
    D = bikes_arr.shape[0]
    T = bikes_arr.shape[1]  # 288

    # ----- 构建 8 个时间/周期特征（每个 slot 一个全局值,广播到所有站）-----
    #  slot index within day = 0..287
    slot_of_day = np.arange(T, dtype=np.float32)  # [T]
    two_pi = 2.0 * np.pi
    hour_sin = np.sin(two_pi * slot_of_day / T).astype(np.float32)  # [T]
    hour_cos = np.cos(two_pi * slot_of_day / T).astype(np.float32)  # [T]

    # weekday: 用 pandas 给每天算一次(5 个月的真实日期，从 outflow.index 来)
    day_starts = pd.to_datetime(
        outflow.index.values[:valid_T].reshape(N_day, T_per_day)[:, 0]
    )  # [N_day]
    weekday = np.asarray([d.weekday() for d in day_starts], dtype=np.float32)  # [D] (0=Mon..6=Sun)
    dow_sin = np.sin(two_pi * weekday / 7.0).astype(np.float32)  # [D]
    dow_cos = np.cos(two_pi * weekday / 7.0).astype(np.float32)  # [D]

    is_morning_peak = np.zeros((D, T), dtype=np.float32)  # [D,T]
    is_evening_peak = np.zeros((D, T), dtype=np.float32)
    is_weekend = np.zeros((D, T), dtype=np.float32)
    # 07:30-09:30 (slot 90..114, since slot 0=00:00,slot s = 5*s minutes from 00:00
    # slot 90 = 07:30, slot 114 = 09:30 inclusive? 09:30-09:35 starts slot 114 所以 07:30..09:30 的包含边界是 [90, 113] (对应07:30~09:29 5min bin)
    # 但为简化：slot 90 ~ 114 覆盖 07:30 到 09:35 期间 bin（包含两端）。直接把"hour 8~9 周围 bin"圈住就行。
    # 精确: morning_peak = 07:30 ~ 09:29  → bin index [90, 114) → 90 <= slot < 114
    for s in range(T):
        mins = s * TIME_BIN_MIN
        hh, mm = divmod(mins, 60)
        # morning peak: 07:30 <= time < 09:30
        mp_on = (hh * 60 + mm >= 7 * 60 + 30) and (hh * 60 + mm < 9 * 60 + 30)
        # evening peak: 17:00 <= time < 20:00
        ep_on = (hh * 60 + mm >= 17 * 60) and (hh * 60 + mm < 20 * 60)
        if mp_on:
            is_morning_peak[:, s] = 1.0
        if ep_on:
            is_evening_peak[:, s] = 1.0

    for d in range(D):
        if weekday[d] >= 5:  # Sat=5 Sun=6
            is_weekend[d, :] = 1.0

    # 归一化车辆数: 每站除以自己的 capacity → 水位 ratio ∈ [0,1]
    cap_arr = capacity_arr.reshape(1, 1, N_station).astype(np.float32)  # [1,1,N]
    vehicles_ratio = (bikes_arr / cap_arr).astype(np.float32)  # [D,T,N]

    # station_idx 常量：第 n 个站的 id 就是 n（0..29），训练时按站复制 embedding
    station_idx = np.arange(N_station, dtype=np.int64)  # [N]，推理会再用到

    print(f"  feature shape: vehicles_ratio={vehicles_ratio.shape} (D={D},T={T},N={N_station})")
    print(f"  时间特征: hour_sin/hour_cos=[{T}],  dow_sin/dow_cos=[{D}], peak masks=[{D},{T}]")

    # 多步标签：3 个锚点目标(车辆/capacity 水位) + 全长36步水位曲线
    # 注:训练 Dataset 在 train_model.py 中做滑窗；此处只把原始特征存好，避免滑窗后文件太大
    np.savez_compressed(
        OUT_DIR / "train_ready.npz",
        # ---- 核心 ----
        vehicles_ratio=vehicles_ratio,   # [D,T,N]  水位 ratio ∈ [0,1]
        capacity=capacity_arr,           # [N]    每站容量
        station_idx=station_idx,         # [N]    每站整数id(0..29,embedding索引)
        # ---- 时间特征（全局广播，训练时拼到各站每个步）----
        hour_sin=hour_sin,               # [T]
        hour_cos=hour_cos,               # [T]
        dow_sin=dow_sin,                 # [D]
        dow_cos=dow_cos,                 # [D]
        is_morning_peak=is_morning_peak, # [D,T]
        is_evening_peak=is_evening_peak, # [D,T]
        is_weekend=is_weekend,           # [D,T]
        # ---- 超参数（训练脚本直接读，不用手填）----
        HISTORY_STEPS=np.int64(HISTORY_STEPS),
        PRED_FULL_STEPS=np.int64(PRED_FULL_STEPS),
        PRED_KEY_HORIZONS=np.asarray(PRED_KEY_HORIZONS, dtype=np.int64),
        N_STATION=np.int64(N_station),
        N_DAY=np.int64(D),
        T_PER_DAY=np.int64(T),
        station_ids=np.asarray([s["zone_id"] for s in stations]),
        station_names=np.asarray([s["name"] for s in stations]),
    )
    print(f"  ✓ {OUT_DIR / 'train_ready.npz'}")
    print(f"    内容: vehicles_ratio + 时间编码 + peak/weekend masks + station_idx + capacity + 超参")
    print()

    # ---------------------- 总结 ----------------------
    print("=" * 70)
    print("预处理完成。输出概览:")
    print(f"  数据期: {outflow.index[0].date()} ~ {outflow.index[-1].date()}  ({N_day} 天)")
    print(f"  站点数: {TOP_N_STATIONS} (NYU 周边 top 频次)")
    print(f"  时间片: {TIME_BIN_MIN}min × {T_per_day}/天 × {N_day} 天 = {valid_T} 片")
    print(f"  每站容量: {capacity_per_station.min():.0f} ~ {capacity_per_station.max():.0f} "
          f"(从真实波动推断,非固定值)")
    print(f"  全期车辆数: {bikes_arr.min():.0f} ~ {bikes_arr.max():.0f}")
    print(f"  trip 保留: {len(df_top):,} / bbox 内 {len(df_all):,} "
          f"({len(df_top)/len(df_all)*100:.1f}%)")
    print(f"  原始数据压缩比: {total_raw:,} → {flow.size + bikes_arr.size:,} 数据点 "
          f"({(flow.size + bikes_arr.size)/total_raw*100:.2f}%)")
    print(f"  [GIS] OD 真实矩阵: od_matrix.npz (288×30×30, 早晚高峰 OD 对直接可视化)")
    print("=" * 70)


if __name__ == "__main__":
    main()
