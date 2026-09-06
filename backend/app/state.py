from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from typing import Any

from .config import ZONES_GEOJSON_PATH
from .services.data_generator import load_default_generator
from .services.geoutils import Zone, load_zones_from_geojson


@dataclass
class RuntimeStats:
    dispatch_count: int = 0
    last_dispatch_time: str | None = None
    dispatch_tasks: list[dict[str, Any]] | None = None


_LOCK = RLock()
_ZONES: dict[str, Zone] = {}
_GENERATOR = None
_ZONE_ORDER: list[str] = []
_ZONES_VERSION: int = 0
_STATS = RuntimeStats()


def _load() -> None:
    global _ZONES, _GENERATOR, _ZONE_ORDER
    _ZONES = load_zones_from_geojson(ZONES_GEOJSON_PATH)
    _GENERATOR = load_default_generator(str(ZONES_GEOJSON_PATH))
    _ZONE_ORDER = getattr(_GENERATOR, "zone_ids", sorted(list(_ZONES.keys())))


def init_state() -> None:
    global _ZONES_VERSION
    with _LOCK:
        _load()
        _ZONES_VERSION += 1


def reload_zones_from_disk() -> None:
    """
    Reload zones and generator after GeoJSON replacement.
    """
    global _ZONES_VERSION, _STATS
    with _LOCK:
        _load()
        _ZONES_VERSION += 1
        # Reset runtime counters for a clean simulation cycle after zone redefinition.
        _STATS = RuntimeStats()


def get_zones() -> dict[str, Zone]:
    with _LOCK:
        if not _ZONES:
            # Uvicorn --reload 会在子进程里重新 import main.py,
            # 某些时序下 create_app() 里的 init_state() 与当前模块变量不同步,
            # 此处做惰性兜底保证 zone_order / generator 永远非空。
            _load()
        return dict(_ZONES)


def get_generator():
    with _LOCK:
        if _GENERATOR is None:
            _load()
        return _GENERATOR


def get_zone_order() -> list[str]:
    with _LOCK:
        if not _ZONE_ORDER and not _ZONES:
            _load()
        return list(_ZONE_ORDER)


def get_zones_version() -> int:
    with _LOCK:
        return int(_ZONES_VERSION)


def register_dispatch(when: str | None = None, tasks: list[dict[str, Any]] | None = None) -> None:
    global _STATS
    with _LOCK:
        _STATS.dispatch_count += 1
        _STATS.last_dispatch_time = when or datetime.now().strftime("%H:%M:%S")
        if tasks:
            if _STATS.dispatch_tasks is None:
                _STATS.dispatch_tasks = []
            # Keep last 50 tasks in memory (monitor screen).
            _STATS.dispatch_tasks.extend(tasks)
            _STATS.dispatch_tasks = _STATS.dispatch_tasks[-50:]


def get_runtime_stats() -> RuntimeStats:
    with _LOCK:
        return RuntimeStats(
            dispatch_count=_STATS.dispatch_count,
            last_dispatch_time=_STATS.last_dispatch_time,
            dispatch_tasks=list(_STATS.dispatch_tasks) if _STATS.dispatch_tasks else [],
        )


def get_live_stats(time_hhmm: str) -> dict[str, Any]:
    """
    Live stats used by /ws/live and /api/monitor/stats.
    """
    generator = get_generator()
    zones = get_zones()
    zone_order = get_zone_order()
    snap = generator.simulate_snapshot(time_hhmm)
    total = int(sum(snap.vehicles_by_zone.values()))

    # saturation uses baseline noon snapshot for display (demo).
    baseline = generator.simulate_snapshot("12:30")

    zones_out: list[dict[str, Any]] = []
    for zid in zone_order:
        z = zones[zid]
        cur = float(snap.vehicles_by_zone[zid])
        base = float(baseline.vehicles_by_zone.get(zid, max(cur, 1.0)))
        zones_out.append(
            {
                "zone_id": zid,
                "name": z.name,
                "vehicles": int(cur),
                "center_lonlat": list(z.center_lonlat),
                "saturation_ratio": (cur / base) if base > 0 else 1.0,
            }
        )

    rt = get_runtime_stats()
    return {
        "time": time_hhmm,
        "total_bikes": total,
        "zones": zones_out,
        "dispatch_count": rt.dispatch_count,
        "last_dispatch_time": rt.last_dispatch_time,
        "dispatch_tasks": rt.dispatch_tasks or [],
        "zones_version": get_zones_version(),
    }

