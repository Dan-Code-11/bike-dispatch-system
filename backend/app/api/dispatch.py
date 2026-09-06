from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import (
    DISPATCH_SHORTAGE_THRESHOLD,
    DISPATCH_SURPLUS_THRESHOLD,
)
from ..models.scheduler import greedy_match_dispatch, mincost_match_dispatch  # 贪心匹配 / 最小费用流全局最优调度算法
from ..state import get_zones, register_dispatch  # 获取区域数据和注册调度

router = APIRouter()


class DispatchRequest(BaseModel):
    """
    Stage3 dispatch input.

    predicted_need_by_zone:
      - positive => shortage (need bikes)
      - negative => surplus  (extra bikes to move out)

    worst_minutes_by_zone (optional):
      - 每站"最需要调度时刻"的分钟偏移（相对于请求 time）。
        用于 dispatch plan 展示"该次调运在几点完成最合适"。
    """

    time: str = Field(description="Time of day, format HH:MM.")
    predicted_need_by_zone: dict[str, float] = Field(description="Shortage positive, surplus negative.")
    worst_minutes_by_zone: dict[str, int] | None = Field(default=None)
    shortage_threshold: float = Field(
        default=DISPATCH_SHORTAGE_THRESHOLD,
        description="Ignore smaller shortages (dispatch need ≥ this).",
    )
    surplus_threshold: float = Field(
        default=DISPATCH_SURPLUS_THRESHOLD,
        description="Ignore smaller surpluses (dispatch need ≤ -this).",
    )
    metric: Literal["euclidean", "manhattan"] = Field(default="euclidean")
    solver: Literal["mincost", "greedy"] = Field(
        default="mincost",
        description="调度求解器: mincost=最小费用流全局最优(默认), greedy=贪心距离匹配(对照).",
    )
    use_osrm: bool = Field(
        default=True,
        description="If True, request OSRM for real street routes; else straight fallback.",
    )
    horizon: str = Field(
        default="worst",
        description="Horizon used for need (mirrored in response as horizon_used).",
    )


class DispatchPlan(BaseModel):
    from_zone: str  # 源区域（富余区域）
    to_zone: str  # 目标区域（短缺区域）
    quantity: int  # 调度车辆数
    route_geometry: dict[str, Any]  # GeoJSON LineString 路由几何信息(OSRM真实街道或降级直线)
    route_source: Literal["osrm", "straight"] = Field(
        description="OSRM 真实街道 or 降级直线"
    )
    worst_min_from: int | None = Field(
        default=None,
        description="盈余站最危险时刻偏移(分钟)；用于前端展示调度紧迫性。",
    )
    worst_min_to: int | None = Field(
        default=None,
        description="短缺站最危险时刻偏移(分钟)；作为建议送达 deadline。",
    )


class DispatchResponse(BaseModel):
    plans: list[DispatchPlan] = Field(default_factory=list)  # 调度计划列表（前端用）
    tasks: list[dict[str, Any]] = Field(default_factory=list)  # 兼容 alias：同 plans 简化为 dict list
    summary: dict[str, Any] = Field(default_factory=dict)  # 总览
    note: str = ""  # 备注信息
    horizon_used: str | None = Field(default=None, description="Need horizon passed via request.horizon.")
    route_source: str | None = Field(default=None, description="Aggregate route source: osrm/straight/mixed/none.")


@router.post("/dispatch", response_model=DispatchResponse)
def dispatch(req: DispatchRequest) -> Any:
    """
    Stage3 dispatch algorithm.
    """
    try:
        zone_data = get_zones()  # 获取区域数据

        # worst_minutes 映射（按 zone_id）—— 缺失站为 None
        worst_map: dict[str, int | None] = {}
        if req.worst_minutes_by_zone:
            for zid, m in req.worst_minutes_by_zone.items():
                worst_map[zid] = int(m) if isinstance(m, (int, float)) else None

        # 选择调度求解器：mincost=最小费用流全局最优（默认）/ greedy=贪心对照
        if req.solver == "greedy":
            plans = greedy_match_dispatch(
                req.predicted_need_by_zone,
                zone_data,
                metric=req.metric,
                shortage_threshold=float(req.shortage_threshold),
                surplus_threshold=float(req.surplus_threshold),
            )
            solver_used = "greedy"
        else:
            plans = mincost_match_dispatch(
                req.predicted_need_by_zone,
                zone_data,
                metric=req.metric,
                shortage_threshold=float(req.shortage_threshold),
                surplus_threshold=float(req.surplus_threshold),
            )
            solver_used = "mincost"

        # 注册调度记录（含路线坐标，供调度队列页内嵌地图渲染单条路线）
        if plans:
            tasks: list[dict[str, Any]] = []
            for idx, p in enumerate(plans):
                geom = dict(p.route_geometry or {})
                coords = geom.get("coordinates", []) if isinstance(geom, dict) else []
                d: dict[str, Any] = {
                    "id": f"{req.time}-{idx}",
                    "from_zone": p.from_zone,
                    "to_zone": p.to_zone,
                    "quantity": int(p.quantity),
                    "created_at": req.time,
                }
                if coords:
                    d["route_lonlats"] = coords
                    try:
                        if len(coords) >= 2:
                            import math as _m
                            fx, fy = coords[0]
                            tx, ty = coords[-1]
                            dy = (ty - fy) * 111_000
                            dx = (tx - fx) * 111_000 * _m.cos(_m.radians((fy + ty) / 2))
                            d["distance_m"] = round(_m.hypot(dx, dy), 1)
                    except Exception:
                        pass
                tasks.append(d)
            register_dispatch(req.time, tasks=tasks)

        # 附加 worst_min + route_source 字段（scheduler.Dataclass 本身不带这些字段，在 API 层补齐）
        # scheduler 返回的 DispatchRoute.route_geometry 已经带 _route_source 私有键（若 OSRM 分支写入），
        # 为了兼容：优先读私有键，否则根据 coordinates 是否是直线（len>2 视为 OSRM，否则 straight）判定。
        out_plans: list[DispatchPlan] = []
        osrm_cnt = 0
        straight_cnt = 0
        total_qty = 0
        for p in plans:
            geom = dict(p.route_geometry or {})
            src_raw = geom.pop("_route_source", None) if isinstance(geom, dict) else None
            coords = geom.get("coordinates", []) if isinstance(geom, dict) else []
            route_source: Literal["osrm", "straight"]
            if src_raw == "osrm":
                route_source = "osrm"
                osrm_cnt += 1
            elif len(coords) > 2:
                route_source = "osrm"
                osrm_cnt += 1
            else:
                route_source = "straight"
                straight_cnt += 1
            total_qty += int(p.quantity)
            out_plans.append(
                DispatchPlan(
                    from_zone=p.from_zone,
                    to_zone=p.to_zone,
                    quantity=int(p.quantity),
                    route_geometry=geom,
                    route_source=route_source,
                    worst_min_from=worst_map.get(p.from_zone, None) if worst_map else None,
                    worst_min_to=worst_map.get(p.to_zone, None) if worst_map else None,
                )
            )

        summary = {
            "n_plans": len(out_plans),
            "total_vehicles": total_qty,
            "routes_from_osrm": osrm_cnt,
            "routes_from_straight_fallback": straight_cnt,
            "shortage_threshold": float(req.shortage_threshold),
            "surplus_threshold": float(req.surplus_threshold),
            "solver": solver_used,
        }

        if osrm_cnt == 0 and straight_cnt > 0:
            fallback_note = (
                " 路由使用直线降级（OSRM 未启动或请求失败）。"
                "启动 OSRM 服务（docker-compose 中的 osrm 容器）即可使用真实街道。"
            )
            route_source_agg: str | None = "straight"
        elif osrm_cnt > 0 and straight_cnt == 0:
            route_source_agg = "osrm"
            fallback_note = ""
        elif osrm_cnt > 0 and straight_cnt > 0:
            route_source_agg = "mixed"
            fallback_note = ""
        else:
            route_source_agg = "none" if len(out_plans) == 0 else None
            fallback_note = ""

        # 兼容 tasks 字段：简化 dict 列表形式（和前端约定的 from_id/to_id/qty）
        tasks_out: list[dict[str, Any]] = []
        for p in out_plans:
            geom = p.route_geometry or {}
            coords = geom.get("coordinates", []) if isinstance(geom, dict) else []
            d: dict[str, Any] = {
                "from_id": p.from_zone,
                "to_id": p.to_zone,
                "qty": p.quantity,
                "route_source": p.route_source,
                "worst_min_from": p.worst_min_from,
                "worst_min_to": p.worst_min_to,
            }
            if coords:
                d["route_lonlats"] = coords
                # 粗略估算距离（首尾直线，米）
                try:
                    if len(coords) >= 2:
                        import math as _m
                        fx, fy = coords[0]; tx, ty = coords[-1]
                        dy = (ty - fy) * 111_000
                        dx = (tx - fx) * 111_000 * _m.cos(_m.radians((fy + ty) / 2))
                        d["distance_m"] = round(_m.hypot(dx, dy), 1)
                except Exception:
                    pass
            tasks_out.append(d)

        return DispatchResponse(
            plans=out_plans,
            tasks=tasks_out,
            summary=summary,
            horizon_used=req.horizon or ("worst" if req.worst_minutes_by_zone else None),
            route_source=route_source_agg,
            note=(
                f"{'Min-cost-flow' if solver_used == 'mincost' else 'Greedy'} dispatch"
                f" ({solver_used}): {len(out_plans)} plans / {total_qty} vehicles."
                + fallback_note
            ),
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Dispatch failed: {e}") from e
