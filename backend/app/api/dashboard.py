from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from .prediction import get_or_create_model
from ..config import HISTORY_STEPS, SIM_INTERVAL_MINUTES, now_nyc_hhmm
from ..models.lstm_model import predict as lstm_predict
from ..state import get_generator, get_runtime_stats, get_zone_order

router = APIRouter()


def _format_hhmm(total_minutes: int) -> str:
    total_minutes %= 24 * 60
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def _parse_hhmm(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


@router.get("/dashboard/stats")
def dashboard_stats(
    time: str | None = Query(default=None, description="Optional HH:MM; defaults to current NYC time."),
    threshold: float = Query(default=5.0, ge=0.0),
) -> dict[str, Any]:
    try:
        hhmm = time or now_nyc_hhmm()

        generator = get_generator()
        zone_order = get_zone_order()

        # Current snapshot.
        snap = generator.simulate_snapshot(hhmm)
        current_by_zone = snap.vehicles_by_zone
        total_bikes = int(sum(current_by_zone.values()))

        # Build history for LSTM input.
        cur_min = _parse_hhmm(hhmm)
        history = []
        for i in range(HISTORY_STEPS):
            t = cur_min - (HISTORY_STEPS - 1 - i) * SIM_INTERVAL_MINUTES
            th = _format_hhmm(t)
            s = generator.simulate_snapshot(th)
            history.append([float(s.vehicles_by_zone[z]) for z in zone_order])

        model, _ = get_or_create_model()
        import numpy as np

        # 用 prediction.predict_with_model 统一封装: 输入 server public 顺序 → 输出 public 顺序 + 真实辆数
        from .prediction import predict_with_model
        history_arr = np.asarray(history, dtype=np.float32)
        pred = predict_with_model(model, history_arr)  # [3, num_zones]

        shortage_count = 0
        surplus_count = 0
        for i, zid in enumerate(zone_order):
            cur = float(current_by_zone[zid])
            avg = float((pred[0][i] + pred[1][i] + pred[2][i]) / 3.0)
            gap = cur - avg  # positive=surplus, negative=shortage
            if -gap > threshold:
                shortage_count += 1
            # demand upper bound approximation
            upper = avg + threshold
            if cur > upper:
                surplus_count += 1

        stats = get_runtime_stats()
        status = "预警" if shortage_count > 0 else "正常"
        return {
            "time": hhmm,
            "current_total_bikes": total_bikes,
            "shortage_zone_count": shortage_count,
            "surplus_zone_count": surplus_count,
            "today_dispatch_count": stats.dispatch_count,
            "last_dispatch_time": stats.last_dispatch_time,
            "system_status": status,
            "threshold": threshold,
            "zones_count": len(zone_order),
        }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"dashboard stats failed: {e}") from e
