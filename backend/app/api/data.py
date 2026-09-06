from __future__ import annotations

import random
import urllib.request
import urllib.error
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

from ..config import ZONES_GEOJSON_PATH  # 站点区域GeoJSON文件路径
from ..config import HISTORY_STEPS, SIM_INTERVAL_MINUTES  # 历史步数和模拟间隔
from ..state import (
    get_generator,  # 获取数据生成器
    get_zone_order,  # 获取区域顺序
    get_zones,  # 获取区域数据
    get_zones_version,  # 获取区域版本
    reload_zones_from_disk,  # 从磁盘重新加载区域数据
)


router = APIRouter()  # 创建API路由器

# ---- 瓦片代理配置（绕过海外超时 / 国内防盗链 Referer 检查）----
# 经 2026-09-01 用户本机实测:
#   esri = 1.3s 稳定实景(28-49KB, WGS84 纽约无偏移) <- 首选
#   osmfr = 1.1~4.3s 波动 + 约22% 502
#   amap = 181~399ms 最快但纽约返回空白图(179B, 无海外数据) -> 仅作最后兜底
TILE_PROVIDERS: dict[str, dict[str, Any]] = {
    # ESRI 世界街道图：全球通用，无防盗链，WGS84坐标系（纽约无偏移）
    "esri": {
        "url_tpl": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        "subdomains": [],
        "referer": None,
        "ext": "jpeg",
    },
    # OSM France 镜像：欧洲机房，WGS84原生坐标系
    "osmfr": {
        "url_tpl": "https://{s}.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png",
        "subdomains": ["a", "b", "c", "d"],
        "referer": None,
        "ext": "png",
    },
    # 高德矢量：国内最快，但 Referer 必须为地图域名（否则403），纽约海外数据为空白图
    "amap": {
        "url_tpl": "https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}",
        "subdomains": ["1", "2", "3", "4"],
        "referer": "https://ditu.amap.com/",
        "ext": "png",
    },
}

# ---- 瓦片内存缓存：重复浏览/切图层不再打外网，直接命中内存 ----
_TILE_CACHE: dict[tuple[str, int, int, int], tuple[str, bytes]] = {}
_TILE_CACHE_MAX = 4000
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36"
)


@router.get("/tiles/{provider}/{z}/{x}/{y}")
def tile_proxy(provider: str, z: int, x: int, y: int) -> Response:
    """
    同源瓦片代理：
    - 绕过国内对海外瓦片源（OSM/Carto）的超时墙
    - 绕过 amap 等瓦片的 Referer 防盗链（浏览器带 Origin=localhost 会被拒，后端请求带伪装 Referer 可通过）
    - 支持 /api/tiles/esri|osmfr|amap/{z}/{x}/{y}，返回 image/png 或 image/jpeg 字节流；命中内存缓存秒回
    """
    cfg = TILE_PROVIDERS.get(provider.lower())
    if cfg is None:
        raise HTTPException(status_code=400, detail=f"Unknown provider. Available: {list(TILE_PROVIDERS)}")
    if z < 0 or z > 20:
        raise HTTPException(status_code=400, detail="zoom z out of range [0..20]")
    # 命中内存缓存：切图/回放/缩放重复请求直接秒回
    cache_key = (provider.lower(), z, x, y)
    cached = _TILE_CACHE.get(cache_key)
    if cached is not None:
        return Response(content=cached[1], media_type=cached[0], headers={"Cache-Control": "public, max-age=86400"})
    # 按高德/OSM习惯：{s} 子域名随机选一个做负载均衡
    sub = random.choice(cfg["subdomains"]) if cfg["subdomains"] else ""
    url = cfg["url_tpl"].format(s=sub, z=z, x=x, y=y)
    req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_UA})
    if cfg["referer"]:
        req.add_header("Referer", cfg["referer"])
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = resp.read()
            ctype = resp.headers.get("Content-Type") or (
                "image/jpeg" if cfg["ext"] == "jpeg" else "image/png"
            )
    except urllib.error.HTTPError as e:
        raise HTTPException(status_code=e.code or 502, detail=f"Upstream {provider}: {e.reason}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise HTTPException(status_code=502, detail=f"Upstream {provider} unreachable: {e}")
    # 写入缓存，超容量时整体清空（简单可接受的淘汰策略）
    if len(_TILE_CACHE) >= _TILE_CACHE_MAX:
        _TILE_CACHE.clear()
    _TILE_CACHE[cache_key] = (ctype, data)
    headers = {"Cache-Control": "public, max-age=86400"}  # 浏览器缓存1天
    return Response(content=data, media_type=ctype, headers=headers)


@router.get("/simulate")
def simulate(time: str = Query(..., description="Time of day, format HH:MM. Example: 08:10")) -> dict[str, Any]:
    """
    Stage1 API: simulate bike vehicles for each zone at the given time-of-day.

    Notes:
    - This simulator only models time-of-day patterns (no date component).
    - The returned numbers are deterministic for stable demos.
    """
    import re

    # 验证时间格式
    if not re.match(r"^\d{2}:\d{2}$", time):
        raise HTTPException(status_code=400, detail="Invalid time format. Expected HH:MM.")

    try:
        zones = get_zones()  # 获取区域数据
        generator = get_generator()  # 获取数据生成器
        snapshot = generator.simulate_snapshot(time=time)  # 模拟指定时间的单车分布
        payload = snapshot.to_api(zones=zones)  # 转换为API响应格式
        payload["zones_version"] = get_zones_version()  # 添加区域版本
        return payload
    except Exception as e:  # noqa: BLE001 - 为演示向客户端显示错误
        raise HTTPException(status_code=500, detail=f"Simulation failed: {e}") from e


# 辅助函数：将HH:MM格式的时间字符串转换为分钟数
def _parse_hhmm(time_str: str) -> int:
    from datetime import datetime

    dt = datetime.strptime(time_str, "%H:%M")
    return dt.hour * 60 + dt.minute


# 辅助函数：将分钟数转换为HH:MM格式的时间字符串
def _format_hhmm(total_minutes: int) -> str:
    total_minutes %= 24 * 60
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


@router.get("/history")
def history(
    time: str = Query(..., description="Time of day, format HH:MM. Example: 08:10"),
    steps: int = Query(default=HISTORY_STEPS, ge=2, le=48),
) -> dict[str, Any]:
    """
    Stage2 helper endpoint:
    Return history array for LSTM input.

    History includes the current time slot and the previous (steps-1) slots.
    For 5-minute intervals, steps=12 -> history covers 60 minutes (t-55 .. t).
    """
    import re

    # 验证时间格式
    if not re.match(r"^\d{2}:\d{2}$", time):
        raise HTTPException(status_code=400, detail="Invalid time format. Expected HH:MM.")

    try:
        cur_min = _parse_hhmm(time)  # 转换为分钟数
        interval = SIM_INTERVAL_MINUTES  # 模拟间隔（5分钟）

        history_times: list[str] = []  # 历史时间列表
        history: list[list[float]] = []  # 历史数据列表
        zone_order = get_zone_order()  # 获取区域顺序
        generator = get_generator()  # 获取数据生成器

        # 生成历史数据（从 oldest 到 newest）
        for i in range(steps):
            t = cur_min - (steps - 1 - i) * interval  # 计算历史时间点
            hhmm = _format_hhmm(t)  # 转换为HH:MM格式
            history_times.append(hhmm)  # 添加到时间列表

            snap = generator.simulate_snapshot(time=hhmm, day_index=0)  # 模拟该时间点的单车分布
            history.append([float(snap.vehicles_by_zone[zid]) for zid in zone_order])  # 添加到历史数据

        return {
            "time": time,
            "interval_minutes": interval,
            "history_steps": steps,
            "history_times": history_times,
            "zone_order": list(zone_order),
            "history": history,
            "zones_version": get_zones_version(),
        }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"History failed: {e}") from e


@router.get("/zones")
def zones() -> dict[str, Any]:
    """Return Citi Bike station zones as GeoJSON features."""
    path = ZONES_GEOJSON_PATH
    if not path.exists():
        raise HTTPException(status_code=500, detail=f"GeoJSON missing: {path}")
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))  # 读取并解析GeoJSON文件
    payload["zones_version"] = get_zones_version()  # 添加区域版本
    return payload


# 更新区域请求模型
class ZonesUpdateRequest(BaseModel):
    geojson: dict[str, Any]


@router.post("/zones/update")
def update_zones(req: ZonesUpdateRequest) -> dict[str, Any]:
    """
    Replace station zones GeoJSON and reload in-memory state.
    """
    geo = req.geojson
    # 验证GeoJSON类型
    if geo.get("type") != "FeatureCollection":
        raise HTTPException(status_code=400, detail="GeoJSON must be FeatureCollection.")

    features = geo.get("features", [])
    # 验证features
    if not isinstance(features, list) or not features:
        raise HTTPException(status_code=400, detail="GeoJSON must include non-empty features.")

    # 验证每个feature
    for idx, f in enumerate(features):
        props = f.get("properties") or {}
        geom = f.get("geometry") or {}
        if not props.get("name"):
            raise HTTPException(status_code=400, detail=f"Feature {idx} missing properties.name")

        gtype = geom.get("type")
        if gtype not in {"Polygon", "MultiPolygon", "MultiPoint"}:
            raise HTTPException(
                status_code=400,
                detail=f"Feature {idx} geometry.type must be Polygon/MultiPolygon/MultiPoint",
            )

        # 为后端内部索引保持zone_id一致
        if not props.get("zone_id"):
            import re

            zid = re.sub(r"[^a-zA-Z0-9_]+", "_", str(props["name"]).strip()).lower().strip("_")
            props["zone_id"] = zid or f"zone_{idx+1}"

    import json

    # 确保目录存在
    ZONES_GEOJSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    # 写入GeoJSON文件
    ZONES_GEOJSON_PATH.write_text(json.dumps(geo, ensure_ascii=False, indent=2), encoding="utf-8")

    # 重新加载共享运行时状态
    reload_zones_from_disk()

    return {
        "ok": True,
        "message": "Zone data updated successfully. Model/runtime state reinitialized.",
        "zones_version": get_zones_version(),
    }

