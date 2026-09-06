from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import (
    DISPATCH_SHORTAGE_THRESHOLD,
    DISPATCH_SURPLUS_THRESHOLD,
    HISTORY_STEPS,
    PRED_FULL_STEPS,
    PRED_KEY_HORIZONS,
    PRED_KEY_LABELS,
    PRED_KEY_MINUTES,
    SIM_INTERVAL_MINUTES,
    TARGET_CAPACITY_RATIO,
    now_nyc_hhmm,
)
from ..state import get_generator, get_zone_order, get_zones

router = APIRouter()

# ============== 路径与全局缓存 ==============
# Stage3 多尺度权重（train_model.py 生成）
_WEIGHTS_MULTI_PATH = Path(__file__).resolve().parents[2] / "models" / "lstm_weights_multi.pth"
# Stage1/2 旧权重（兜底：若 multi 不存在，尝试读旧路径做 legacy 推理）
_WEIGHTS_LEGACY_PATH = Path(__file__).resolve().parents[2] / "models" / "lstm_weights.pth"

_MODEL_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {
    # stage3 cache
    "s3_model": None,
    "s3_meta": None,          # checkpoint 里的 train_meta
    "s3_metrics": None,       # checkpoint 里的 metrics（作品集 UI 展示基线对比）
    "s3_ckpt_order": None,    # list[str] — checkpoint 存的 station_ids
    "s3_ckpt_cap": None,      # np.ndarray [N_ckpt] — checkpoint 存的 capacity
    # public → ckpt 列映射
    "pub_to_ckpt": None,      # np.ndarray [N_pub] — pub[i] 在 ckpt 里的列号
    "ckpt_to_pub": None,      # np.ndarray [N_ckpt] — 反向
    # legacy 缓存（当 s3_model 未加载时使用）
    "legacy_model": None,
    "legacy_zone_order": None,
    "legacy_perm": None,
}


def reset_model_cache() -> None:
    with _MODEL_LOCK:
        for k in list(_CACHE.keys()):
            _CACHE[k] = None


# ============== 时间小工具 ==============
def _parse_hhmm(time_str: str) -> int:
    from datetime import datetime

    dt = datetime.strptime(time_str, "%H:%M")
    return dt.hour * 60 + dt.minute


def _format_hhmm(total_minutes: int) -> str:
    total_minutes %= 24 * 60
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def _shift_hhmm(time_str: str, delta_minutes: int) -> str:
    return _format_hhmm(_parse_hhmm(time_str) + delta_minutes)


# ============== Stage3: 加载 multi-horizon 权重 ==============
def _torch_load_safe(path: Path) -> dict[str, Any]:
    """兼容新旧 PyTorch 版本的 torch.load。"""
    import torch

    try:
        return torch.load(str(path), map_location="cpu", weights_only=False)
    except TypeError:
        return torch.load(str(path), map_location="cpu")


def _try_load_stage3() -> bool:
    """尝试加载 Stage3 权重（成功返回 True）。"""
    if _CACHE["s3_model"] is not None:
        return True
    if not _WEIGHTS_MULTI_PATH.exists():
        return False

    try:
        from ..models.lstm_model import MultiHorizonLSTM, TORCH_AVAILABLE

        if not TORCH_AVAILABLE:
            return False
        ckpt = _torch_load_safe(_WEIGHTS_MULTI_PATH)
        state_dict = ckpt.get("state_dict")
        meta = ckpt.get("train_meta") or {}
        metrics = ckpt.get("metrics") or {}
        if state_dict is None or not meta:
            return False

        n_stations = int(meta.get("n_stations", 0))
        scalar_dim = int(meta.get("scalar_dim", 8))
        embed_dim = int(meta.get("embed_dim", 4))
        hidden_size = int(meta.get("hidden_size", 128))
        num_layers = int(meta.get("num_layers", 2))
        pred_full_steps = int(meta.get("pred_full_steps", PRED_FULL_STEPS))
        pred_key_horizons = list(meta.get("pred_key_horizons", PRED_KEY_HORIZONS))

        model = MultiHorizonLSTM(
            n_stations=n_stations,
            scalar_dim=scalar_dim,
            embed_dim=embed_dim,
            hidden_size=hidden_size,
            num_layers=num_layers,
            pred_full_steps=pred_full_steps,
            pred_key_len=len(pred_key_horizons),
        )
        model.load_state_dict(state_dict, strict=True)
        model.eval()

        ckpt_order = [str(z) for z in meta.get("station_ids", [])]
        ckpt_cap = np.asarray(meta.get("capacity", []), dtype=np.float32).reshape(-1)
        if not ckpt_order or len(ckpt_order) != n_stations or ckpt_cap.shape[0] != n_stations:
            return False

        _CACHE["s3_model"] = model
        _CACHE["s3_meta"] = meta
        _CACHE["s3_metrics"] = metrics
        _CACHE["s3_ckpt_order"] = ckpt_order
        _CACHE["s3_ckpt_cap"] = ckpt_cap
        return True
    except Exception:
        # 加载失败：清缓存避免下次用脏数据
        for k in ("s3_model", "s3_meta", "s3_metrics", "s3_ckpt_order", "s3_ckpt_cap"):
            _CACHE[k] = None
        return False


def _build_pub_ckpt_maps() -> None:
    """用 server 的 public zone_order 和 checkpoint order 构造排列映射。"""
    if _CACHE["pub_to_ckpt"] is not None:
        return
    pub_order = list(get_zone_order())
    ckpt_order = list(_CACHE["s3_ckpt_order"])
    idx_of = {zid: j for j, zid in enumerate(ckpt_order)}
    N_pub = len(pub_order)
    pub_to_ckpt = np.full(N_pub, -1, dtype=np.int64)
    for i, zid in enumerate(pub_order):
        if zid in idx_of:
            pub_to_ckpt[i] = idx_of[zid]
    # 反向映射：只覆盖真正存在的
    ckpt_to_pub = np.full(len(ckpt_order), -1, dtype=np.int64)
    for i, j in enumerate(pub_to_ckpt):
        if j >= 0:
            ckpt_to_pub[j] = i
    _CACHE["pub_to_ckpt"] = pub_to_ckpt
    _CACHE["ckpt_to_pub"] = ckpt_to_pub


# ============== Stage3: 推理时间特征 ==============
def _build_time_features(
    time_hhmm: str,
    steps: int,
    *,
    lookback: bool = True,
) -> np.ndarray:
    """
    根据起始时间 HH:MM 生成 (steps, 7) 的时间特征矩阵。
    如果 lookback=True：向前取 steps（包含 time 本身为最后一格）；否则向后取 steps。
    7 列 = [hour_sin, hour_cos, dow_sin, dow_cos, is_morning_peak, is_evening_peak, is_weekend]。
    注意: 只做"时间模式"回放，dow 用周一(weekday=0)，周末掩码恒为 0。
    """
    cur_min = _parse_hhmm(time_hhmm)
    interval = SIM_INTERVAL_MINUTES
    mins_arr = np.arange(steps, dtype=np.float32) * interval
    if lookback:
        # 索引 0 = oldest, 索引 steps-1 = cur_min（now）
        mins_arr = cur_min - (steps - 1) * interval + mins_arr
    else:
        # 索引 0 = next step (cur_min + 5min)
        mins_arr = cur_min + interval + mins_arr
    mins_arr_mod = np.mod(mins_arr, 24 * 60)
    slot = mins_arr_mod / interval  # steps
    T_per_day = 24 * 60 / interval
    two_pi = 2.0 * np.pi
    hour_sin = np.sin(two_pi * slot / T_per_day).astype(np.float32)
    hour_cos = np.cos(two_pi * slot / T_per_day).astype(np.float32)

    # dow: 演示稳定用 Monday=0 (weekday pattern 最典型)
    weekday_const = 0
    dow_sin = np.full(steps, np.sin(two_pi * weekday_const / 7.0), dtype=np.float32)
    dow_cos = np.full(steps, np.cos(two_pi * weekday_const / 7.0), dtype=np.float32)

    mp = np.zeros(steps, dtype=np.float32)
    ep = np.zeros(steps, dtype=np.float32)
    we = np.zeros(steps, dtype=np.float32)
    for k in range(steps):
        mm = int(mins_arr_mod[k])
        # morning peak: 07:30 <= t < 09:30
        if 7 * 60 + 30 <= mm < 9 * 60 + 30:
            mp[k] = 1.0
        # evening peak: 17:00 <= t < 20:00
        if 17 * 60 <= mm < 20 * 60:
            ep[k] = 1.0
    out = np.stack([hour_sin, hour_cos, dow_sin, dow_cos, mp, ep, we], axis=-1)
    assert out.shape == (steps, 7)
    return out


# ============== Stage3: 主推理封装（一次性返回所有站） ==============
def _infer_stage3(history_pub: np.ndarray, time_hhmm: str) -> dict[str, Any]:
    """
    history_pub: [H, N_pub]  float32  按 server public zone_order 的原始车辆数
    返回: 推理中间结果 dict（含所有站的 key/curve、need、worst_horizon 等）
    """
    from ..models.lstm_model import predict_multihorizon

    H = history_pub.shape[0]
    pub_order = list(get_zone_order())
    N_pub = len(pub_order)

    # 取 public → ckpt 的列映射
    pub_to_ckpt = _CACHE["pub_to_ckpt"]     # [N_pub]
    ckpt_cap = _CACHE["s3_ckpt_cap"]        # [N_ckpt]
    ckpt_order = list(_CACHE["s3_ckpt_order"])
    N_ckpt = len(ckpt_order)

    # 构造 N_ckpt 个站的 history_ratio（对齐 checkpoint 内部顺序，缺失站用 0.5 水位兜底）
    # 反向: ckpt[j] 在 public 的索引 = ckpt_to_pub[j]
    ckpt_to_pub = _CACHE["ckpt_to_pub"]     # [N_ckpt]
    hist_by_ckpt = np.zeros((N_ckpt, H), dtype=np.float32)  # [N_ckpt, H]
    cap_by_ckpt = ckpt_cap.astype(np.float32)                # [N_ckpt]
    for j in range(N_ckpt):
        pub_idx = ckpt_to_pub[j]
        if pub_idx >= 0:
            raw = history_pub[:, pub_idx].astype(np.float32)
        else:
            # public 中没有该 checkpoint 站：用容量×目标水位做兜底历史
            raw = np.full(H, cap_by_ckpt[j] * TARGET_CAPACITY_RATIO, dtype=np.float32)
        # clamp 到 [0, cap]
        cap = max(cap_by_ckpt[j], 1e-6)
        raw = np.clip(raw, 0.0, cap)
        hist_by_ckpt[j] = raw

    hist_ratio = hist_by_ckpt / cap_by_ckpt[:, None].clip(min=1e-6)  # [N_ckpt, H]

    # 时间特征：过去 H 步（lookback=True）
    tf_hist = _build_time_features(time_hhmm, H, lookback=True)  # [H,7]

    station_idx_arr = np.arange(N_ckpt, dtype=np.int64)  # [N_ckpt]
    model = _CACHE["s3_model"]

    key_pred, cur_pred = predict_multihorizon(
        model, hist_ratio.astype(np.float32), tf_hist.astype(np.float32), station_idx_arr
    )
    # key_pred: [N_ckpt, 3]  ratio；cur_pred: [N_ckpt, 36]  ratio

    # 转回车辆数
    cap_exp = cap_by_ckpt[:, None].astype(np.float32)  # [N_ckpt,1]
    key_veh_ckpt = key_pred * cap_exp                        # [N_ckpt, 3]
    cur_veh_ckpt = cur_pred * cap_exp                        # [N_ckpt, 36]

    # Persistent baseline vehicles：last ratio × cap
    last_ratio = hist_ratio[:, -1:]                          # [N_ckpt,1]
    pers_key_ckpt = (last_ratio * cap_exp).repeat(key_veh_ckpt.shape[1], axis=1)  # [N_ckpt,3]
    pers_cur_ckpt = (last_ratio * cap_exp).repeat(cur_veh_ckpt.shape[1], axis=1)  # [N_ckpt,36]

    # 计算 need（正=短缺，负=盈余）: need = (TARGET_RATIO - ratio) * capacity
    # 也就是 need = TARGET_CAPACITY_RATIO*cap - predicted_vehicles = target_veh - predicted_veh
    target_veh = (TARGET_CAPACITY_RATIO * cap_by_ckpt).astype(np.float32)[:, None]  # [N_ckpt,1]
    need_key_ckpt = target_veh.repeat(3, axis=1) - key_veh_ckpt                     # [N_ckpt,3]

    # worst horizon：按 |need| 最大的锚点（最需要被调度的时刻）
    # worst_min：对应锚点的分钟数；worst_label："1h"/"2h"/"3h"；worst_need：该锚点 need
    kh_minutes = np.asarray(PRED_KEY_MINUTES, dtype=np.int64)
    abs_need = np.abs(need_key_ckpt)                                        # [N_ckpt,3]
    worst_idx = np.argmax(abs_need, axis=1).astype(np.int64)                # [N_ckpt]
    worst_min_ckpt = kh_minutes[worst_idx]                                    # [N_ckpt]
    worst_label_ckpt = np.asarray(PRED_KEY_LABELS)[worst_idx]                # [N_ckpt]
    worst_need_ckpt = np.take_along_axis(need_key_ckpt, worst_idx[:, None], axis=1)[:, 0]  # [N_ckpt]

    # 当前时刻车辆数（public order）：取 history 最后一步
    current_veh_pub = history_pub[-1, :].astype(np.float32)  # [N_pub]

    # 把 ckpt 维度的结果映射回 public order；对 public 中不存在于 ckpt 的站做兜底
    key_veh_pub = np.zeros((N_pub, 3), dtype=np.float32)
    cur_veh_pub = np.zeros((N_pub, PRED_FULL_STEPS), dtype=np.float32)
    need_key_pub = np.zeros((N_pub, 3), dtype=np.float32)
    worst_min_pub = np.zeros(N_pub, dtype=np.int64)
    worst_label_pub = np.array(PRED_KEY_LABELS)[np.zeros(N_pub, dtype=np.int64)]
    worst_need_pub = np.zeros(N_pub, dtype=np.float32)
    pers_key_pub = np.zeros((N_pub, 3), dtype=np.float32)
    pers_cur_pub = np.zeros((N_pub, PRED_FULL_STEPS), dtype=np.float32)
    cap_pub = np.zeros(N_pub, dtype=np.float32)

    # 容量 public order（同时从 generator 取，作为兜底）
    try:
        cap_map_gen = get_generator().capacity_by_zone()
    except Exception:
        cap_map_gen = {}

    for i in range(N_pub):
        j = pub_to_ckpt[i]
        zid = pub_order[i]
        if j >= 0:
            key_veh_pub[i] = key_veh_ckpt[j]
            cur_veh_pub[i] = cur_veh_ckpt[j]
            need_key_pub[i] = need_key_ckpt[j]
            worst_min_pub[i] = int(worst_min_ckpt[j])
            worst_label_pub[i] = str(worst_label_ckpt[j])
            worst_need_pub[i] = float(worst_need_ckpt[j])
            pers_key_pub[i] = pers_key_ckpt[j]
            pers_cur_pub[i] = pers_cur_ckpt[j]
            cap_pub[i] = float(cap_by_ckpt[j])
        else:
            # 兜底：用 generator 容量 + persistent 预测 + 保守 need=0
            cap_fallback = float(cap_map_gen.get(zid, 0.0))
            if cap_fallback <= 0:
                cap_fallback = max(float(current_veh_pub[i]) * 2.0, 30.0)
            cap_pub[i] = cap_fallback
            cur_v = float(current_veh_pub[i])
            key_veh_pub[i] = cur_v
            cur_veh_pub[i, :] = cur_v
            target_v = TARGET_CAPACITY_RATIO * cap_fallback
            need_key_pub[i] = target_v - cur_v
            worst_label_pub[i] = "1h"
            worst_min_pub[i] = 60
            worst_need_pub[i] = float(need_key_pub[i, 0])
            pers_key_pub[i] = cur_v
            pers_cur_pub[i, :] = cur_v

    return {
        "H": H,
        "current_veh_pub": current_veh_pub,     # [N_pub]
        "cap_pub": cap_pub,                     # [N_pub]
        "key_veh_pub": key_veh_pub,             # [N_pub, 3]
        "cur_veh_pub": cur_veh_pub,             # [N_pub, PRED_FULL_STEPS]
        "need_key_pub": need_key_pub,           # [N_pub, 3]
        "worst_min_pub": worst_min_pub,         # [N_pub]
        "worst_label_pub": worst_label_pub,     # [N_pub]
        "worst_need_pub": worst_need_pub,       # [N_pub]
        "pers_key_pub": pers_key_pub,           # [N_pub, 3]
        "pers_cur_pub": pers_cur_pub,           # [N_pub, PRED_FULL_STEPS]
        "history_pub": history_pub,             # [H, N_pub]  原始车辆数（前端图表）
        "meta": _CACHE["s3_meta"],
        "metrics": _CACHE["s3_metrics"],
    }


# ============== Legacy fallback：Stage1/2 老权重兜底 ==============
def _try_load_legacy() -> bool:
    """加载旧 lstm_weights.pth（Stage1 结构）。返回是否成功。"""
    if _CACHE["legacy_model"] is not None:
        return True
    if not _WEIGHTS_LEGACY_PATH.exists():
        return False
    try:
        from ..models.lstm_model import LSTMPredictor, TORCH_AVAILABLE

        if not TORCH_AVAILABLE:
            return False
        ckpt = _torch_load_safe(_WEIGHTS_LEGACY_PATH)
        zone_order = ckpt.get("zone_order")
        if not zone_order:
            return False
        hs = int(ckpt.get("history_steps", HISTORY_STEPS))
        ps = int(ckpt.get("pred_steps", 3))
        nz = len(zone_order)
        hsz = int(ckpt.get("hidden_size", 64))
        nlayers = int(ckpt.get("num_layers", 2))
        try:
            m = LSTMPredictor(num_zones=nz, hidden_size=hsz, num_layers=nlayers, pred_steps=ps)
        except TypeError:
            m = LSTMPredictor(num_zones=nz, hidden_size=hsz, pred_steps=ps)
        m.load_state_dict(ckpt["state_dict"], strict=True)
        m.eval()

        server_order = list(get_zone_order())
        idx_of = {z: j for j, z in enumerate(zone_order)}
        perm = np.array([idx_of[z] if z in idx_of else -1 for z in server_order], dtype=np.int64)
        _CACHE["legacy_model"] = m
        _CACHE["legacy_zone_order"] = list(server_order)
        _CACHE["legacy_perm"] = perm
        return True
    except Exception:
        _CACHE["legacy_model"] = None
        return False


def _infer_legacy(history_pub: np.ndarray, time_hhmm: str) -> dict[str, Any]:
    """
    Stage1 老权重兜底：不再信任旧 LSTMPredictor 的输出（旧模型语义未统一：既可能是 raw vehicles
    也可能是 ratio，且与 1h/2h/3h 锚点完全不匹配）。这里改成 100% persistent baseline：
    锚点和曲线都以最后一帧车辆数延展，保证 need/状态 稳定、颜色分布可信，不出现全站被误判短缺。
    Stage3 权重训练完成后会自然切换到真正的多尺度预测。
    """
    model = _CACHE["legacy_model"]  # 仅用于判定 legacy 已加载，避免该函数被直接调用到空上下文
    _ = model
    N_pub = history_pub.shape[1]
    H = history_pub.shape[0]
    P_need = PRED_FULL_STEPS
    current_veh_pub = history_pub[-1, :].astype(np.float32)  # [N_pub]

    # 锚点 + 曲线 = persistent（last frame 复制），杜绝负数/语义漂移
    key_veh_pub = np.tile(current_veh_pub[:, None], (1, 3)).astype(np.float32)  # [N_pub,3]
    cur_veh_pub = np.tile(current_veh_pub[:, None], (1, P_need)).astype(np.float32)  # [N_pub,36]

    # 容量：优先 generator 的真实 station_capacity（从 bikes_5min.npz 读）
    pub_order = list(get_zone_order())
    try:
        cap_map = get_generator().capacity_by_zone()
    except Exception:
        cap_map = {}
    cap_pub = np.zeros(N_pub, dtype=np.float32)
    for i, zid in enumerate(pub_order):
        cap_fallback = float(cap_map.get(zid, 0.0))
        if cap_fallback <= 0:
            cap_fallback = max(float(current_veh_pub[i]) * 2.0, 30.0)
        cap_pub[i] = cap_fallback

    target_veh = (TARGET_CAPACITY_RATIO * cap_pub)[:, None].astype(np.float32)
    need_key_pub = target_veh.repeat(3, axis=1) - key_veh_pub  # [N_pub, 3]
    kh_minutes = np.asarray(PRED_KEY_MINUTES, dtype=np.int64)
    abs_need = np.abs(need_key_pub)
    worst_idx = np.argmax(abs_need, axis=1).astype(np.int64)
    worst_min_pub = kh_minutes[worst_idx]
    worst_label_pub = np.asarray(PRED_KEY_LABELS)[worst_idx]
    worst_need_pub = np.take_along_axis(need_key_pub, worst_idx[:, None], axis=1)[:, 0]
    # persistent baseline
    pers_key_pub = np.tile(current_veh_pub[:, None], (1, 3))
    pers_cur_pub = np.tile(current_veh_pub[:, None], (1, P_need))
    return {
        "H": H,
        "current_veh_pub": current_veh_pub,
        "cap_pub": cap_pub,
        "key_veh_pub": key_veh_pub,
        "cur_veh_pub": cur_veh_pub,
        "need_key_pub": need_key_pub,
        "worst_min_pub": worst_min_pub,
        "worst_label_pub": worst_label_pub,
        "worst_need_pub": worst_need_pub,
        "pers_key_pub": pers_key_pub,
        "pers_cur_pub": pers_cur_pub,
        "history_pub": history_pub,
        "meta": None,
        "metrics": None,
        "legacy_fallback": True,
    }


# ============== 缓存入口：加载 stage3 → 失败则 legacy ==============
def get_or_load_backend() -> tuple[str, Any]:
    """返回 ("stage3", _) 或 ("legacy", _) 或抛错。"""
    with _MODEL_LOCK:
        server_order = list(get_zone_order())
        if _CACHE["s3_ckpt_order"] is None:
            _try_load_stage3()
        if _CACHE["s3_model"] is not None and _CACHE["s3_ckpt_order"] is not None:
            # 检查 server order 和 ckpt 是否有交集（否则无法预测）
            common = len(set(server_order) & set(_CACHE["s3_ckpt_order"]))
            if common > 0:
                _build_pub_ckpt_maps()
                return "stage3", None
        # 兜底 legacy
        if _try_load_legacy():
            return "legacy", None
    raise RuntimeError(
        "未找到任何可用的模型权重文件。\n"
        f"Stage3: {_WEIGHTS_MULTI_PATH} (运行 train_model.py 训练后生成)\n"
        f"Legacy:  {_WEIGHTS_LEGACY_PATH}\n"
        "请把训练好的权重放入 backend/models/ 目录下。"
    )


# ============== Pydantic 模型 ==============
class PredictRequest(BaseModel):
    time: str = Field(description="Time of day HH:MM; history ends at this slot.")
    history: list[list[float]] = Field(description="[history_steps, num_zones],按 zone_order 列排序。")
    zone_order: list[str] | None = Field(default=None)


class PredictResponse(BaseModel):
    time: str
    # 多窗口时间标签
    key_horizon_labels: list[str]     # ["1h","2h","3h"]
    key_horizon_minutes: list[int]   # [60,120,180]
    key_horizon_times: list[str]     # HH:MM 对应 time + 60/120/180
    curve_full_steps: int            # 36 (每5min 一步)
    curve_times: list[str]           # 全长 36 步的 HH:MM
    zone_order: list[str]
    # 每站预测详情（前端 map / 摘要 / 图表使用）
    zones: list[dict[str, Any]]
    # 四栏摘要（短缺 / 盈余 / 健康 / 总数）按当前站数
    summary: dict[str, Any]
    # 作品集用：基线对比（metrics from checkpoint；若 legacy fallback 则为空 dict）
    baseline_evidence: dict[str, Any]
    # 调度用：need 映射（每站 worst need 值，正=短缺需补，负=盈余可调出）
    predicted_need_by_zone: dict[str, float]
    # 调度辅助：每站 worst_horizon 时间（分钟数），前端展示"该站最危险时刻"
    worst_by_zone: dict[str, dict[str, Any]]
    # 供前端图表用：所有站 history(24步)+ curve(36步) 车辆数序列（稠密，但30站×60步很小）
    series_by_zone: dict[str, dict[str, Any]]
    note: str = ""


@router.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest) -> Any:
    """
    Stage3 多尺度预测 API：返回 1h/2h/3h 锚点 + 3h 全长曲线 + worst horizon 分类。

    兼容：如未训练 Stage3 权重但存在旧 lstm_weights.pth，则回退到 legacy 推理。
    """
    import re

    try:
        # ---- 1. 校验输入 ----
        if not re.match(r"^\d{2}:\d{2}$", req.time):
            raise HTTPException(status_code=400, detail="Invalid time format (HH:MM).")
        if len(req.history) != HISTORY_STEPS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid history length: expected {HISTORY_STEPS}, got {len(req.history)}",
            )
        if not req.history or not req.history[0]:
            raise HTTPException(status_code=400, detail="History is empty.")
        num_zones = len(req.history[0])
        for i, step in enumerate(req.history):
            if len(step) != num_zones:
                raise HTTPException(status_code=400, detail=f"History shape mismatch at step {i}.")

        zone_order_req = req.zone_order or get_zone_order()
        server_zone_order = list(get_zone_order())
        if len(zone_order_req) != num_zones:
            raise HTTPException(status_code=400, detail="zone_order length mismatch.")
        if list(zone_order_req) != list(server_zone_order):
            raise HTTPException(
                status_code=400,
                detail="zone_order does not match server zone_order (for stable demo we enforce identity).",
            )

        # ---- 2. 加载模型 ----
        mode, _ = get_or_load_backend()

        # ---- 3. 推理 ----
        history_np = np.asarray(req.history, dtype=np.float32)  # [H, N_pub]
        if mode == "stage3":
            out = _infer_stage3(history_np, req.time)
        else:
            out = _infer_legacy(history_np, req.time)

        N_pub = len(server_zone_order)
        key_labels = list(PRED_KEY_LABELS)
        key_mins = list(PRED_KEY_MINUTES)
        key_times = [_shift_hhmm(req.time, m) for m in key_mins]
        # 曲线全长时间：step=1..PRED_FULL_STEPS（每步 5min）
        curve_times = [
            _shift_hhmm(req.time, (k + 1) * SIM_INTERVAL_MINUTES)
            for k in range(PRED_FULL_STEPS)
        ]
        # 历史 24 步时间标签（给图表）
        hist_times = [
            _shift_hhmm(req.time, -(HISTORY_STEPS - 1 - k) * SIM_INTERVAL_MINUTES)
            for k in range(HISTORY_STEPS)
        ]

        zones = get_zones()
        # 取 generator 容量（兜底）
        try:
            cap_map_gen = get_generator().capacity_by_zone()
        except Exception:
            cap_map_gen = {}

        shortage_th = float(DISPATCH_SHORTAGE_THRESHOLD)
        surplus_th = float(DISPATCH_SURPLUS_THRESHOLD)

        # ---- 4. 组装 zones 列表（与 server_zone_order 对齐） ----
        zones_out: list[dict[str, Any]] = []
        predicted_need_by_zone: dict[str, float] = {}
        worst_by_zone: dict[str, dict[str, Any]] = {}
        series_by_zone: dict[str, dict[str, Any]] = {}

        # 统计计数
        cnt_shortage = 0
        cnt_surplus = 0
        cnt_healthy = 0

        cur_veh_all = out["current_veh_pub"]   # [N_pub]
        cap_all = out["cap_pub"]               # [N_pub]
        key_all = out["key_veh_pub"]           # [N_pub, 3]
        cur_all = out["cur_veh_pub"]           # [N_pub, PRED_FULL_STEPS]
        need_all = out["need_key_pub"]         # [N_pub, 3]
        worst_min_all = out["worst_min_pub"]   # [N_pub]
        worst_label_all = out["worst_label_pub"]  # [N_pub]
        worst_need_all = out["worst_need_pub"]    # [N_pub]
        pers_key_all = out["pers_key_pub"]     # [N_pub, 3]
        pers_cur_all = out["pers_cur_pub"]     # [N_pub, PRED_FULL_STEPS]
        hist_all = out["history_pub"]          # [H, N_pub]

        for i, zid in enumerate(server_zone_order):
            z = zones.get(zid)
            zname = z.name if z else zid
            cur_v = float(cur_veh_all[i])
            cap_v = float(cap_all[i])
            if cap_v <= 0:
                cap_v = float(cap_map_gen.get(zid, max(cur_v * 2.0, 30.0)))

            anchors = [float(x) for x in key_all[i].tolist()]           # [3]
            curve = [float(x) for x in cur_all[i].tolist()]             # [PRED_FULL_STEPS]
            needs = [float(x) for x in need_all[i].tolist()]            # [3]
            pers_k = [float(x) for x in pers_key_all[i].tolist()]
            pers_c = [float(x) for x in pers_cur_all[i].tolist()]
            hist_v = [float(x) for x in hist_all[:, i].tolist()]        # [H]

            # 该站状态分类：使用 worst need（3 锚点中 |need| 最大的）
            worst_need = float(worst_need_all[i])
            worst_min = int(worst_min_all[i])
            worst_label = str(worst_label_all[i])
            # 取"当前状态+未来最差趋势"中的更严重者（和调度阈值一致）
            # 注:调度 API 使用 need（worst_need）作为 predicted_need_by_zone 取值，保证一致
            if worst_need >= shortage_th:
                status = "shortage"
                cnt_shortage += 1
            elif worst_need <= -surplus_th:
                status = "surplus"
                cnt_surplus += 1
            else:
                status = "healthy"
                cnt_healthy += 1

            need_val = worst_need  # 统一：need = worst_need（正=缺/负=盈）
            predicted_need_by_zone[zid] = need_val
            worst_by_zone[zid] = {
                "horizon_label": worst_label,
                "horizon_minutes": worst_min,
                "need": round(need_val, 2),
            }

            # 图表序列：过去2h(24) + 未来3h(36)，按时间连续
            series_by_zone[zid] = {
                "history_times": list(hist_times),
                "history_vehicles": hist_v,
                "curve_times": list(curve_times),
                "curve_vehicles_lstm": curve,
                "curve_vehicles_persistent": pers_c,
                "anchors_times": list(key_times),
                "anchors_vehicles_lstm": anchors,
                "anchors_vehicles_persistent": pers_k,
                "anchors_need": needs,
            }

            # 当前水位
            cur_ratio = cur_v / cap_v if cap_v > 0 else TARGET_CAPACITY_RATIO

            zones_out.append({
                "zone_id": zid,
                "name": zname,
                "capacity": round(cap_v, 1),
                "current_count": round(cur_v, 1),
                "current_ratio": round(cur_ratio, 3),
                "status": status,              # shortage / surplus / healthy
                "need": round(need_val, 2),    # 调度量（正=短缺需补,负=盈余可调出）
                # 3 锚点
                "forecast_anchors": [
                    {
                        "label": key_labels[k],
                        "minutes": key_mins[k],
                        "time": key_times[k],
                        "vehicles": round(anchors[k], 2),
                        "delta_vs_now": round(anchors[k] - cur_v, 2),
                        "need": round(needs[k], 2),
                        "baseline_persistent": round(pers_k[k], 2),
                    }
                    for k in range(3)
                ],
                "worst_horizon": {
                    "label": worst_label,
                    "minutes": worst_min,
                    "time": _shift_hhmm(req.time, worst_min),
                    "need": round(need_val, 2),
                },
            })

        # ---- 5. baseline_evidence（作品集用：LSTM vs Persistent） ----
        baseline_evidence: dict[str, Any] = {}
        metrics = out.get("metrics")
        if isinstance(metrics, dict) and metrics:
            baseline_evidence = metrics

        summary = {
            "n_total": N_pub,
            "n_shortage": cnt_shortage,
            "n_surplus": cnt_surplus,
            "n_healthy": cnt_healthy,
            "shortage_threshold": shortage_th,
            "surplus_threshold": surplus_th,
            "target_capacity_ratio": TARGET_CAPACITY_RATIO,
        }

        note_parts = []
        if mode == "stage3":
            note_parts.append(
                f"Stage3 Multi-Horizon LSTM (anchors {key_labels} + {PRED_FULL_STEPS}×5min curve)."
            )
            if baseline_evidence:
                lbl1 = key_labels[0]
                ev = (baseline_evidence.get("per_horizon") or {}).get(lbl1) or {}
                imp = ev.get("improvement_pct_mae")
                if imp is not None:
                    note_parts.append(f"Test {lbl1} improvement vs persistent: {float(imp):+.1f}% MAE.")
        else:
            note_parts.append(
                "Legacy LSTM fallback (stage1 weights). 1h/2h/3h anchors use persistent extension. "
                "Run backend/train_model.py on server to enable Stage3 multi-horizon predictions."
            )

        return PredictResponse(
            time=req.time,
            key_horizon_labels=key_labels,
            key_horizon_minutes=key_mins,
            key_horizon_times=key_times,
            curve_full_steps=PRED_FULL_STEPS,
            curve_times=curve_times,
            zone_order=list(server_zone_order),
            zones=zones_out,
            summary=summary,
            baseline_evidence=baseline_evidence,
            predicted_need_by_zone=predicted_need_by_zone,
            worst_by_zone=worst_by_zone,
            series_by_zone=series_by_zone,
            note=" ".join(note_parts),
        )
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Predict failed: {e}") from e


# ============== 兼容层：dashboard.py / lab.py 旧符号 ==================
# 旧代码 dashboard.py / lab.py 依赖 get_or_create_model / predict_with_model。
# Stage3 重写后已移除，此处通过"优先 stage3、失败 legacy"路径返回 model-like 对象与 meta，
# 并实现 predict_with_model(...) 返回 [3, N] 的锚点预测（旧代码约定）。
# 该层不会影响 /predict 主 API 行为，仅做旧入口兼容，避免 import 崩溃导致 uvicorn 子进程重启。


def load_stage3_model_assets() -> tuple[Any, dict[str, Any]]:
    """新版入口：加载 stage3 权重并返回 (model, meta)；失败抛 RuntimeError。"""
    with _MODEL_LOCK:
        if not _try_load_stage3():
            raise RuntimeError(f"Stage3 权重未找到: {_WEIGHTS_MULTI_PATH}")
        _build_pub_ckpt_maps()
        return _CACHE["s3_model"], _CACHE["s3_meta"] or {}


def get_or_create_model() -> tuple[Any, Any]:
    """
    兼容旧调用：返回 (model_like, meta_like)。
    - stage3 可用时：返回 (MultiHorizonLSTM, meta dict)
    - 否则 legacy 可用时：返回 (LSTMPredictor, {"legacy": True, "zone_order": ...})
    - 都不可用：为了不阻塞 /dashboard/stats 这类"无 GPU 也可看 UI"的场景，
      返回 (None, {})，调用方应做 None 判断。
    """
    try:
        get_or_load_backend()
    except RuntimeError:
        return None, {}
    if _CACHE["s3_model"] is not None:
        return _CACHE["s3_model"], _CACHE["s3_meta"] or {}
    if _CACHE["legacy_model"] is not None:
        meta = {
            "legacy": True,
            "zone_order": _CACHE["legacy_zone_order"],
            "perm": _CACHE["legacy_perm"],
        }
        return _CACHE["legacy_model"], meta
    return None, {}


def predict_with_model(_model: Any, history_arr: np.ndarray) -> np.ndarray:
    """
    兼容旧调用：输入 [H, N_pub]，返回 [3, N_pub]（1h/2h/3h 锚点车辆数）。
    旧代码约定: pred[k][i] 对应第 k 个预测步的第 i 个 zone 车辆数。
    这里直接复用 _infer_stage3/_infer_legacy 内部逻辑，避免重复造轮子。
    若两种权重都没有，则退化为 persistent（= 最后一步车辆数复制 3 次）。
    """
    H = int(history_arr.shape[0]) if hasattr(history_arr, "shape") else len(history_arr)
    x = np.asarray(history_arr, dtype=np.float32)
    if x.ndim != 2:
        raise ValueError(f"predict_with_model: history must be 2D, got shape {x.shape}")
    N = x.shape[1]

    # 取一个"最近合理"的时间锚点（dashboard stats 只关心阈值统计，时间特征影响可忽略）
    now_hhmm = now_nyc_hhmm()

    mode = None
    try:
        mode, _ = get_or_load_backend()
    except RuntimeError:
        mode = None
    if mode == "stage3":
        _build_pub_ckpt_maps()
        out = _infer_stage3(x, now_hhmm)
        # key_veh_pub: [N_pub, 3] → 转置为 [3, N_pub]
        return np.asarray(out["key_veh_pub"], dtype=np.float32).T
    if mode == "legacy":
        out = _infer_legacy(x, now_hhmm)
        return np.asarray(out["key_veh_pub"], dtype=np.float32).T
    # 兜底：persistent baseline = last step copied ×3
    last = x[-1:].astype(np.float32)  # [1, N]
    return np.repeat(last, 3, axis=0)
