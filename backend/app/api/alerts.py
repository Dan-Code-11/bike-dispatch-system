from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from ..config import now_nyc_hhmm
from ..db import get_session
from ..persistence.models import AlertEvent, AlertRule, Base
from ..state import get_live_stats, get_zone_order

router = APIRouter()


class RuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    rule_type: Literal["zone_saturation_high", "zone_shortage_high"]
    params: dict[str, Any] = Field(default_factory=dict)


class RuleOut(BaseModel):
    id: int
    name: str
    enabled: bool
    rule_type: str
    params: dict[str, Any]
    created_at: datetime


class RuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None
    params: dict[str, Any] | None = None


class EventOut(BaseModel):
    id: int
    rule_id: int | None
    level: str
    title: str
    message: str
    payload: dict[str, Any]
    created_at: datetime


@router.on_event("startup")
async def _ensure_tables() -> None:
    # Lightweight auto-create for demo (no Alembic yet).
    from sqlalchemy.ext.asyncio import AsyncEngine

    from ..db import engine

    eng: AsyncEngine = engine
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@router.get("/alerts/rules", response_model=list[RuleOut])
async def list_rules() -> list[RuleOut]:
    async with get_session() as session:
        rows = (await session.execute(select(AlertRule).order_by(AlertRule.id))).scalars().all()
        return [
            RuleOut(
                id=r.id,
                name=r.name,
                enabled=r.enabled,
                rule_type=r.rule_type,
                params=r.params or {},
                created_at=r.created_at,
            )
            for r in rows
        ]


@router.post("/alerts/rules", response_model=RuleOut)
async def create_rule(payload: RuleCreate) -> RuleOut:
    async with get_session() as session:
        r = AlertRule(name=payload.name, enabled=payload.enabled, rule_type=payload.rule_type, params=payload.params)
        session.add(r)
        await session.commit()
        await session.refresh(r)
        return RuleOut(
            id=r.id,
            name=r.name,
            enabled=r.enabled,
            rule_type=r.rule_type,
            params=r.params or {},
            created_at=r.created_at,
        )


@router.patch("/alerts/rules/{rule_id}", response_model=RuleOut)
async def update_rule(rule_id: int, payload: RuleUpdate) -> RuleOut:
    async with get_session() as session:
        r = (await session.execute(select(AlertRule).where(AlertRule.id == rule_id))).scalar_one_or_none()
        if not r:
            raise HTTPException(status_code=404, detail="rule not found")
        if payload.name is not None:
            r.name = payload.name
        if payload.enabled is not None:
            r.enabled = payload.enabled
        if payload.params is not None:
            r.params = payload.params
        await session.commit()
        await session.refresh(r)
        return RuleOut(
            id=r.id,
            name=r.name,
            enabled=r.enabled,
            rule_type=r.rule_type,
            params=r.params or {},
            created_at=r.created_at,
        )


@router.delete("/alerts/rules/{rule_id}")
async def delete_rule(rule_id: int) -> dict[str, Any]:
    async with get_session() as session:
        r = (await session.execute(select(AlertRule).where(AlertRule.id == rule_id))).scalar_one_or_none()
        if not r:
            return {"ok": True, "deleted": 0}
        await session.delete(r)
        await session.commit()
        return {"ok": True, "deleted": 1}


def _eval_rule(rule: AlertRule, live: dict[str, Any]) -> list[AlertEvent]:
    zone_order = get_zone_order()
    zones = live.get("zones") or []
    by_id = {z.get("zone_id"): z for z in zones if z.get("zone_id")}

    events: list[AlertEvent] = []
    if rule.rule_type == "zone_saturation_high":
        thr = float((rule.params or {}).get("threshold", 0.85))
        for zid in zone_order:
            z = by_id.get(zid)
            if not z:
                continue
            sr = float(z.get("saturation_ratio", 0.0))
            if sr >= thr:
                events.append(
                    AlertEvent(
                        rule_id=rule.id,
                        level="warning",
                        title="区域饱和度过高",
                        message=f"{z.get('name') or zid} 饱和度 {sr:.2f} ≥ {thr:.2f}",
                        payload={"zone_id": zid, "saturation_ratio": sr, "threshold": thr, "time": live.get("time")},
                    )
                )
    elif rule.rule_type == "zone_shortage_high":
        # shortage_high: bikes below min_bikes
        min_bikes = int((rule.params or {}).get("min_bikes", 5))
        for zid in zone_order:
            z = by_id.get(zid)
            if not z:
                continue
            bikes = int(z.get("vehicles", 0))
            if bikes <= min_bikes:
                events.append(
                    AlertEvent(
                        rule_id=rule.id,
                        level="critical" if bikes <= max(0, min_bikes // 2) else "warning",
                        title="区域车辆不足",
                        message=f"{z.get('name') or zid} 车辆数 {bikes} ≤ {min_bikes}",
                        payload={"zone_id": zid, "vehicles": bikes, "min_bikes": min_bikes, "time": live.get("time")},
                    )
                )
    return events


@router.post("/alerts/check")
async def check_alerts(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    # payload: {"time": "HH:MM"} optional
    t = (payload or {}).get("time")
    if not t:
        t = now_nyc_hhmm()
    live = get_live_stats(str(t))
    created = 0

    async with get_session() as session:
        rules = (await session.execute(select(AlertRule).where(AlertRule.enabled == True))).scalars().all()  # noqa: E712
        for r in rules:
            evs = _eval_rule(r, live)
            for ev in evs:
                session.add(ev)
                created += 1
        await session.commit()

    return {"ok": True, "created": created, "time": live.get("time")}


@router.get("/alerts/history", response_model=list[EventOut])
async def list_history(limit: int = 100) -> list[EventOut]:
    limit = max(1, min(int(limit), 500))
    async with get_session() as session:
        rows = (await session.execute(select(AlertEvent).order_by(desc(AlertEvent.id)).limit(limit))).scalars().all()
        return [
            EventOut(
                id=e.id,
                rule_id=e.rule_id,
                level=e.level,
                title=e.title,
                message=e.message,
                payload=e.payload or {},
                created_at=e.created_at,
            )
            for e in rows
        ]
