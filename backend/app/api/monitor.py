from __future__ import annotations

from asyncio import sleep
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from ..config import now_nyc_hhmm
from ..state import get_live_stats

router = APIRouter()


@router.get("/monitor/stats")
def monitor_stats(time: str | None = Query(default=None, description="Optional HH:MM; defaults to current NYC time.")) -> dict[str, Any]:
    hhmm = time or now_nyc_hhmm()
    return get_live_stats(hhmm)


@router.websocket("/ws/live")
async def websocket_live(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            hhmm = now_nyc_hhmm()
            await websocket.send_json(get_live_stats(hhmm))
            await sleep(2)
    except WebSocketDisconnect:
        return


@router.websocket("/ws/live/{hhmm}")
async def websocket_live_at_time(websocket: WebSocket, hhmm: str):
    """
    Allows the dashboard to subscribe to a fixed HH:MM time slice.
    Useful for demos to see the spatial pattern without waiting for real time.
    """
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(get_live_stats(hhmm))
            await sleep(2)
    except WebSocketDisconnect:
        return
