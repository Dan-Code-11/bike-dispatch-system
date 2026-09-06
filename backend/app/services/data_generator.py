from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ..config import DATA_DIR, SIM_INTERVAL_MINUTES
from .geoutils import Zone, load_zones_from_geojson


@dataclass(frozen=True)
class SimulationSnapshot:
    """单个时间片的系统快照(接口不变,内部数据源换成真实回放)"""

    time: str  # HH:MM
    vehicles_by_zone: dict[str, int]

    def to_api(self, zones: dict[str, Zone]) -> dict[str, Any]:
        """将快照转换为 API 响应格式(与旧版完全兼容)"""
        out_zones: list[dict[str, Any]] = []
        for zone_id, vehicles in self.vehicles_by_zone.items():
            z = zones[zone_id]
            out_zones.append(
                {
                    "zone_id": zone_id,
                    "name": z.name,
                    "vehicles": int(vehicles),
                    "center_lonlat": list(z.center_lonlat),
                }
            )
        # 按 zone_id 稳定排序,保证 UI 渲染顺序一致
        out_zones.sort(key=lambda x: x["zone_id"])
        return {"time": self.time, "zones": out_zones}


def _slot_to_hhmm(slot: int, interval_min: int = SIM_INTERVAL_MINUTES) -> str:
    """时间片序号 → HH:MM 字符串"""
    total_min = (slot * interval_min) % (24 * 60)
    return f"{total_min // 60:02d}:{total_min % 60:02d}"


def _hhmm_to_slot(hhmm: str, interval_min: int = SIM_INTERVAL_MINUTES) -> int:
    """HH:MM 字符串 → 时间片序号(一天内)"""
    h, m = hhmm.split(":")
    total_min = int(h) * 60 + int(m)
    return total_min // interval_min


class RealTripReplayer:
    """
    真实 Citi Bike 数据回放器。

    从 data/bikes_5min.npz 读取预处理后的真实车辆数序列 [N_day, T_per_day, N_station],
    按 (day_index, HH:MM) 回放对应时间片的真实车辆数。

    对外接口与旧 CampusDataGenerator 完全兼容:
      - simulate_snapshot(time, day_index) -> SimulationSnapshot
      - generate_day_series(day_start_time, day_index) -> (times, ndarray)

    数据源由 backend/scripts/prepare_trips.py 生成,区域为 Manhattan 高频 Citi Bike 站点。
    """

    def __init__(
        self,
        zones: dict[str, Zone],
        bikes_npz_path: str | Path | None = None,
        stations_json_path: str | Path | None = None,
        # 以下参数仅为向后兼容保留,真实回放不需要
        base_vehicles: dict[str, int] | None = None,
        zone_roles: dict[str, str] | None = None,
    ):
        self.zones = zones
        # 稳定排序的 zone_id 列表,保证训练/推理数组顺序一致
        self.zone_ids = sorted(list(zones.keys()))

        bikes_npz_path = Path(bikes_npz_path) if bikes_npz_path else DATA_DIR / "bikes_5min.npz"
        stations_json_path = (
            Path(stations_json_path) if stations_json_path else DATA_DIR / "stations.json"
        )

        if not bikes_npz_path.exists():
            raise FileNotFoundError(
                f"真实数据文件不存在: {bikes_npz_path}\n"
                f"请先运行: python backend/scripts/prepare_trips.py"
            )
        if not stations_json_path.exists():
            raise FileNotFoundError(f"站点元数据不存在: {stations_json_path}")

        # 加载真实车辆数矩阵 [N_day, T_per_day, N_station]
        data = np.load(bikes_npz_path, allow_pickle=True)
        self.bikes: np.ndarray = data["bikes"].astype(np.float32)
        self.n_days, self.n_slots, self.n_stations = self.bikes.shape

        # 每站独立容量(用于"相对容量比例"判断短缺/盈余)
        if "capacity" in data.files:
            self.station_capacity: np.ndarray = data["capacity"].astype(np.float32)
        else:
            # 兜底:用全局最大值的 1.3 倍 + 5 作为近似容量
            self.station_capacity = np.full(self.n_stations, float(self.bikes.max()) * 1.3 + 5, dtype=np.float32)

        # 加载站点元数据,建立 station_id → 矩阵列号 的映射
        stations = json.loads(stations_json_path.read_text(encoding="utf-8"))
        self.station_ids: list[str] = [str(s["zone_id"]) for s in stations]
        self.sid_to_col: dict[str, int] = {
            sid: i for i, sid in enumerate(self.station_ids)
        }

        # 校验:zones 的 zone_id 应在 station_ids 中(否则该区域无真实数据,补 0)
        missing = set(self.zone_ids) - set(self.station_ids)
        if missing:
            # 不抛错,允许 zones 是 stations 的超集(用户编辑 geojson 加了新区域时回退 0)
            pass

    def _align_columns(self) -> list[int]:
        """
        返回与 self.zone_ids 顺序对齐的矩阵列号列表。
        若某 zone_id 在真实数据中不存在,用 -1 标记(回放时补 0)。
        """
        return [self.sid_to_col.get(zid, -1) for zid in self.zone_ids]

    def capacity_by_zone(self) -> dict[str, float]:
        """返回 zone_id → 容量 的映射(按 self.zone_ids 顺序)"""
        out: dict[str, float] = {}
        for zid, col in zip(self.zone_ids, self._align_columns()):
            out[zid] = float(self.station_capacity[col]) if col >= 0 else 0.0
        return out

    def simulate_snapshot(self, time: str, day_index: int = 0) -> SimulationSnapshot:
        """
        回放指定 (day_index, HH:MM) 的真实车辆数快照。

        Args:
            time: HH:MM 格式时间
            day_index: 天序号(0~150,超出自动取模)
        """
        slot = _hhmm_to_slot(time) % self.n_slots
        day = day_index % self.n_days
        row = self.bikes[day, slot, :]  # [N_station] 真实车辆数

        cols = self._align_columns()
        vehicles_by_zone: dict[str, int] = {}
        for zid, col in zip(self.zone_ids, cols):
            vehicles_by_zone[zid] = int(round(row[col])) if col >= 0 else 0

        return SimulationSnapshot(time=time, vehicles_by_zone=vehicles_by_zone)

    def generate_day_series(
        self,
        day_start_time: str = "00:00",
        day_index: int = 0,
    ) -> tuple[list[str], np.ndarray]:
        """
        回放一整天的真实车辆数序列。

        Args:
            day_start_time: 起始时间(真实数据从 00:00 开始,非 00:00 会从该时刻偏移取片)
            day_index: 天序号

        Returns:
            times: list[str] HH:MM 标签,长度 = T_per_day
            x: ndarray [T_per_day, num_zones],按 zone_ids 排序
        """
        day = day_index % self.n_days
        mat = self.bikes[day]  # [T, N_station]

        # 处理起始时间偏移(真实数据按 00:00 起算,这里做循环偏移)
        start_slot = _hhmm_to_slot(day_start_time)
        indices = [(start_slot + i) % self.n_slots for i in range(self.n_slots)]

        times = [_slot_to_hhmm(s) for s in indices]
        cols = self._align_columns()
        x = np.zeros((self.n_slots, len(self.zone_ids)), dtype=np.float32)
        for j, col in enumerate(cols):
            if col >= 0:
                x[:, j] = mat[indices, col]

        return times, x


# 向后兼容别名
CampusDataGenerator = RealTripReplayer


def build_generator(zones: dict[str, Zone]) -> RealTripReplayer:
    """构建真实数据回放器(接口与旧版一致)"""
    return RealTripReplayer(zones=zones)


def load_default_generator(geojson_path: str) -> RealTripReplayer:
    """从 GeoJSON 加载区域,构建真实数据回放器"""
    zones = load_zones_from_geojson(geojson_path)
    return build_generator(zones)
