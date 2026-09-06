from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .prediction import get_or_create_model, reset_model_cache
from ..config import HISTORY_STEPS, PRED_STEPS_15MIN
from ..models.lstm_model import TORCH_AVAILABLE, train as lstm_train
from ..state import get_generator, get_zone_order, get_runtime_stats

from pathlib import Path
import os

router = APIRouter()

_WEIGHTS_PATH = Path(__file__).resolve().parents[2] / "models" / "lstm_weights.pth"

@router.get("/lab/model/status")
def model_status() -> dict[str, Any]:
    try:
        zone_order = get_zone_order()
        weights_exists = _WEIGHTS_PATH.exists()
        stats = get_runtime_stats()

        # 读取训练时保存的评估指标(metrics / train_config),供前端首页展示
        metrics = None
        train_config = None
        num_layers = None
        if weights_exists:
            import torch

            ckpt = torch.load(_WEIGHTS_PATH, map_location="cpu", weights_only=False)
            metrics = ckpt.get("metrics")
            train_config = ckpt.get("train_config")
            num_layers = ckpt.get("num_layers")

        return {
            "time": datetime.now().isoformat(timespec="seconds"),
            "torch_available": bool(TORCH_AVAILABLE),
            "zones_count": len(zone_order),
            "weights_path": str(_WEIGHTS_PATH),
            "weights_exists": bool(weights_exists),
            "available": bool(weights_exists and metrics),
            "metrics": metrics,
            "train_config": train_config,
            "num_layers": num_layers,
            "dispatch_count": stats.dispatch_count,
            "last_dispatch_time": stats.last_dispatch_time,
        }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"model status failed: {e}") from e


class TrainRequest(BaseModel):
    note: str | None = Field(default=None, description="Optional note for the training run.")
    num_days: int = Field(default=7, ge=1, le=30)
    epochs: int = Field(default=8, ge=1, le=50)
    batch_size: int = Field(default=64, ge=8, le=512)
    lr: float = Field(default=1e-3, gt=0.0, le=1.0)
    hidden_size: int = Field(default=64, ge=8, le=512)
    train_ratio: float = Field(default=0.8, gt=0.2, lt=0.99)


@router.post("/lab/model/train")
def train_model(req: TrainRequest | None = None) -> dict[str, Any]:
    """
    Demo endpoint: trigger training synchronously and save weights.
    For production you'd run this as a background job.
    """
    try:
        if not TORCH_AVAILABLE:
            raise HTTPException(status_code=400, detail="PyTorch is not available in this environment.")
        if req is None:
            req = TrainRequest()

        import torch

        _WEIGHTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        zone_order = get_zone_order()
        generator = get_generator()
        device = "cuda" if torch.cuda.is_available() else "cpu"

        model, meta_obj = lstm_train(
            generator,
            zone_order,
            num_days=req.num_days,
            history_steps=HISTORY_STEPS,
            pred_steps=PRED_STEPS_15MIN,
            train_ratio=req.train_ratio,
            epochs=req.epochs,
            batch_size=req.batch_size,
            lr=req.lr,
            hidden_size=req.hidden_size,
            device=device,
        )

        ckpt = {
            "state_dict": model.state_dict(),
            "zone_order": zone_order,
            "history_steps": HISTORY_STEPS,
            "pred_steps": PRED_STEPS_15MIN,
            "hidden_size": req.hidden_size,
            "train_meta": meta_obj.__dict__,
            "note": req.note or "",
        }
        torch.save(ckpt, _WEIGHTS_PATH)

        # ensure serving uses the new weights
        reset_model_cache()
        _ = get_or_create_model()
        return {
            "ok": True,
            "trained_at": datetime.now().isoformat(timespec="seconds"),
            "zones_count": len(get_zone_order()),
            "meta": ckpt.get("train_meta") or {},
        }
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"train failed: {e}") from e

