from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

NYC_TZ = ZoneInfo("America/New_York")


def now_nyc() -> datetime:
    """返回纽约当地时间（自动处理夏令时 EDT/EST）。"""
    return datetime.now(NYC_TZ)


def now_nyc_hhmm() -> str:
    """返回纽约当地时间 HH:MM 格式。"""
    return now_nyc().strftime("%H:%M")


# Project layout:
# - repo_root/
#   - bike_dispatch_system/
#     - backend/app/config.py
#     - data/manhattan_zones.geojson
#
# When running in Docker we set BIKE_DATA_DIR=/app/data.
DATA_DIR = Path(os.getenv("BIKE_DATA_DIR", str(Path(__file__).resolve().parents[2] / "data")))

ZONES_GEOJSON_PATH = DATA_DIR / "manhattan_zones.geojson"

# Time discretization: stage1 uses 5-minute time slots.
SIM_INTERVAL_MINUTES = 5

# Zone roles — 保留仅为旧代码兼容,真实训练/调度不使用
# (真实数据 stations.json 的 station_id 是数字字符串,与 ZONE_ROLES key 无关)
ZONE_ROLES: dict[str, str] = {}

# Training-related constants.
# Stage 3 (Multi-Scale Multi-Horizon Prediction):
#   History = 过去 2 小时 (24 * 5min)
#   Predict = 未来 3 小时 全长 (36 * 5min)，其中 3 个关键锚点:
#     KEY_HORIZONS = [12, 24, 36] = 对应 60min / 120min / 180min
HISTORY_STEPS = 24
PRED_FULL_STEPS = 36
PRED_KEY_HORIZONS = [12, 24, 36]        # 对应实际1/2/3小时(步长索引,1-based step from now,即step=12对应+60min)
PRED_KEY_LABELS = ["1h", "2h", "3h"]
PRED_KEY_MINUTES = [60, 120, 180]
# 站点嵌入维度
STATION_EMBEDDING_DIM = 4
# 目标水位（容量比例）
TARGET_CAPACITY_RATIO = 0.50

# Legacy 兼容（旧 API fallback：15 分钟=3 步 × 5 分钟）
# Stage3 训练/推理已不再使用 15 分钟锚点，仅保留以避免历史代码 import 报错
PRED_STEPS_15MIN = 3

# 调度/颜色阈值（和前端 colorFor / dispatch API 保持一致）
DISPATCH_SHORTAGE_THRESHOLD = 3.0   # need >= this → 短缺
DISPATCH_SURPLUS_THRESHOLD = 3.0    # need <= -this → 盈余

# OSRM 服务默认地址（docker-compose 加入 OSRM 容器后可通过 host 访问）
OSRM_BASE_URL = os.getenv("BIKE_OSRM_URL", "http://osrm:5000")
