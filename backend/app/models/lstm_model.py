from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from ..config import (
    HISTORY_STEPS,
    PRED_FULL_STEPS,
    PRED_KEY_HORIZONS,
    STATION_EMBEDDING_DIM,
)

try:
    import torch
    import torch.nn as nn

    TORCH_AVAILABLE = True
except Exception:  # noqa: BLE001
    TORCH_AVAILABLE = False
    torch = None  # type: ignore
    nn = None  # type: ignore


# =========================================================================
# Stage 3 多尺度多步预测模型（当前默认训练/推理）
# 输入(单站独立):
#   x_scalar: [B, H, 8]  8维标量特征 = (vehicles_ratio, hour_sin, hour_cos, dow_sin, dow_cos,
#                                        is_morning_peak, is_evening_peak, is_weekend)
#   s_idx:  [B]          每个样本所属的站 id (int, 0..N_station-1)
# 输出:
#   y_key:  [B, 3]       3 个锚点 (1h/2h/3h) 的水位 ratio 预测
#   y_cur:  [B, 36]      全长 3h 曲线 (每5分钟1步) 的水位 ratio 预测
# =========================================================================
if TORCH_AVAILABLE:
    class MultiHorizonLSTM(nn.Module):  # type: ignore[misc]
        """共享 LSTM + 站点嵌入 + 双输出头。"""

        def __init__(
            self,
            n_stations: int,
            *,
            scalar_dim: int = 8,
            embed_dim: int = STATION_EMBEDDING_DIM,
            hidden_size: int = 96,
            num_layers: int = 2,
            pred_full_steps: int = PRED_FULL_STEPS,
            pred_key_len: int = 3,
        ):
            super().__init__()
            self.n_stations = n_stations
            self.scalar_dim = scalar_dim
            self.embed_dim = embed_dim
            self.hidden_size = hidden_size
            self.num_layers = num_layers
            self.pred_full_steps = pred_full_steps
            self.pred_key_len = pred_key_len

            input_size = scalar_dim + embed_dim   # 8 + 4 = 12
            self.station_emb = nn.Embedding(n_stations, embed_dim)
            self.lstm = nn.LSTM(
                input_size=input_size,
                hidden_size=hidden_size,
                num_layers=num_layers,
                batch_first=True,
                dropout=0.15 if num_layers > 1 else 0.0,
            )
            self.drop = nn.Dropout(0.15)

            # ---- Head A: 3 key horizons (1h/2h/3h) ----
            self.head_key = nn.Sequential(
                nn.Linear(hidden_size, hidden_size // 2),
                nn.ReLU(inplace=True),
                nn.Linear(hidden_size // 2, pred_key_len),
            )

            # ---- Head B: 全长 36 steps (未来3h每5分钟1格) ----
            # 用 2 层 temporal conv1d 出曲线，保证平滑
            inter = max(16, pred_full_steps // 2)
            self.head_curve = nn.Sequential(
                nn.Linear(hidden_size, inter * 8),   # 展开到 (inter*8) 再 reshape
            )
            self.curve_conv = nn.Sequential(
                nn.Conv1d(in_channels=8, out_channels=16, kernel_size=5, padding=2),
                nn.ReLU(inplace=True),
                nn.Conv1d(in_channels=16, out_channels=8, kernel_size=5, padding=2),
                nn.ReLU(inplace=True),
                nn.Conv1d(in_channels=8, out_channels=1, kernel_size=3, padding=1),
            )
            # 将inter对齐到 pred_full_steps（用 interpolate 动态 resize 到目标长度，避免长度硬编码不匹配）
            self._inter_len = inter

        def forward(
            self,
            x_scalar: "torch.Tensor",
            s_idx: "torch.Tensor",
        ) -> tuple["torch.Tensor", "torch.Tensor"]:
            """
            Args:
              x_scalar: [B, H, scalar_dim]  含 vehicles_ratio 在第 0 维
              s_idx:    [B]                  站点索引 int
            Returns:
              y_key: [B, pred_key_len]   水位ratio (可直接用sigmoid约束到[0,1])
              y_cur: [B, pred_full_steps] 同上
            """
            B, H, _ = x_scalar.shape
            emb = self.station_emb(s_idx)           # [B, embed_dim]
            emb_exp = emb.unsqueeze(1).expand(-1, H, -1)  # [B, H, embed_dim]
            x = torch.cat([x_scalar, emb_exp], dim=-1)   # [B, H, scalar_dim+embed_dim]

            out, _ = self.lstm(x)                  # [B, H, hidden_size]
            last = self.drop(out[:, -1, :])        # [B, hidden_size]

            y_key_logits = self.head_key(last)     # [B, 3]
            y_key = torch.sigmoid(y_key_logits)    # 水位 clamp 到 [0,1]

            flat = self.head_curve(last)           # [B, inter*8]
            z = flat.view(B, 8, self._inter_len)   # [B, 8, inter]
            # Interpolate 到 pred_full_steps (处理inter可能 != pred_full_steps 的情况)
            if self._inter_len != self.pred_full_steps:
                z = torch.nn.functional.interpolate(
                    z, size=self.pred_full_steps, mode="linear", align_corners=False
                )
            cur_logits = self.curve_conv(z).squeeze(1)  # [B, pred_full_steps]
            y_cur = torch.sigmoid(cur_logits)
            return y_key, y_cur
else:
    MultiHorizonLSTM = None  # type: ignore


# =========================================================================
# Stage 3 推理 API：给预测 /api/predict 用（单次返回所有站）
#   输入:
#     model          MultiHorizonLSTM (cpu/gpu)
#     history_ratio  [N_station, H]  每站过去 H=HISTORY_STEPS 步的 ratio (vehicles/capacity)
#     time_features  [H, 7]          (hour_sin, hour_cos, dow_sin, dow_cos, mp, ep, we)
#     station_idx    [N_station]     0..N-1
#   输出:
#     key_pred       [N_station, 3]  ratio (1h/2h/3h 3个锚点)
#     cur_pred       [N_station, PRED_FULL_STEPS]  ratio (全长曲线)
# =========================================================================
def predict_multihorizon(
    model: Any,
    history_ratio: np.ndarray,
    time_features: np.ndarray,
    station_idx_arr: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    if not TORCH_AVAILABLE:
        raise RuntimeError("PyTorch is not available.")

    N, H = history_ratio.shape
    assert time_features.shape == (H, 7), time_features.shape
    assert station_idx_arr.shape == (N,), station_idx_arr.shape

    # 拼每站的 x_scalar: [N, H, 8] = (vehicles_ratio, 7 time_features)
    ratio_exp = history_ratio[:, :, None].astype(np.float32)          # [N,H,1]
    tf_exp = np.broadcast_to(time_features[None, :, :], (N, H, 7)).astype(np.float32)  # [N,H,7]
    x_scalar_np = np.concatenate([ratio_exp, tf_exp], axis=-1)        # [N,H,8]

    device = next(model.parameters()).device
    x = torch.tensor(x_scalar_np, dtype=torch.float32, device=device)  # [N,H,8]
    s = torch.tensor(station_idx_arr.astype(np.int64), dtype=torch.long, device=device)  # [N]

    model.eval()
    with torch.no_grad():
        y_key, y_cur = model(x, s)
    key_pred = y_key.detach().float().cpu().numpy().astype(np.float32)   # [N,3]
    cur_pred = y_cur.detach().float().cpu().numpy().astype(np.float32)   # [N,36]
    return key_pred, cur_pred


# =========================================================================
# Stage 3：构造单个样本（训练脚本用）
# 给定: day x [T, N] 的 vehicles_ratio + 7 维时间特征展开
# 产出: (x_scalar [H,8], s_idx int, y_key [3], y_cur [P])
# 注: 严格按站独立滑窗 + 跨天断(不串夜)
# =========================================================================
def make_per_station_windows(
    vehicles_ratio_all: np.ndarray,   # [D, T, N]
    tf_global: dict[str, np.ndarray],
    *,
    day_indices: list[int],
    station_list: list[int],
    history_steps: int = HISTORY_STEPS,
    pred_full_steps: int = PRED_FULL_STEPS,
    pred_key_horizons: list[int] = PRED_KEY_HORIZONS,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Returns:
      X: [N_samples, H, 8]  float32
      S: [N_samples]       int64 (station idx 0..N-1)
      Yk:[N_samples, 3]    float32 (3 key ratios)
      Yc:[N_samples, P]    float32 (full curve ratios)
    """
    D, T, N = vehicles_ratio_all.shape

    # 预先展开 (D,T,7) 的时间特征
    hour_sin = tf_global["hour_sin"].astype(np.float32)   # [T]
    hour_cos = tf_global["hour_cos"].astype(np.float32)
    dow_sin = tf_global["dow_sin"].astype(np.float32)     # [D]
    dow_cos = tf_global["dow_cos"].astype(np.float32)
    mp = tf_global["is_morning_peak"].astype(np.float32)  # [D,T]
    ep = tf_global["is_evening_peak"].astype(np.float32)
    we = tf_global["is_weekend"].astype(np.float32)

    Xs: list[np.ndarray] = []
    Ss: list[int] = []
    Yks: list[np.ndarray] = []
    Ycs: list[np.ndarray] = []

    H = history_steps
    P = pred_full_steps
    kh = list(pred_key_horizons)
    assert len(kh) == 3
    # 时间特征[D,T,7]
    tf = np.zeros((D, T, 7), dtype=np.float32)
    tf[:, :, 0] = hour_sin[None, :]
    tf[:, :, 1] = hour_cos[None, :]
    tf[:, :, 2] = dow_sin[:, None]
    tf[:, :, 3] = dow_cos[:, None]
    tf[:, :, 4] = mp
    tf[:, :, 5] = ep
    tf[:, :, 6] = we

    for d in day_indices:
        vr_day = vehicles_ratio_all[d]   # [T,N]  水位 ratio
        tf_day = tf[d]                   # [T,7]
        for s in station_list:
            vr_st = vr_day[:, s]         # [T]  单站一天的水位序列
            for t in range(H, T - P + 1):
                # 输入窗口: vr[t-H : t]  (不含 t, 因为 t是"当前时刻",即 history 最后1格对应 t-1 之后我用惯例:
                #   history 取 t-H .. t-1 共 H 步（前 H 个观测），预测从 t 开始的 P 步
                hist = vr_st[t - H : t]                                  # [H]
                tf_hist = tf_day[t - H : t, :]                           # [H,7]
                x_scalar = np.concatenate([hist[:, None], tf_hist], axis=-1)  # [H,8]
                # 目标：未来 t .. t+P-1 共 P 步
                curve = vr_st[t : t + P]                                 # [P]
                key = np.asarray([curve[i - 1] for i in kh], dtype=np.float32)  # [3]
                # (key_horizons 是 1-based index after t: step=12 对应 t+11 索引(python中),所以取 i-1)
                # 修正: key_horizons=[12,24,36] 语义是"+12×5min=+60min",相对起点 t(=+1×5min),
                # 即数组 curve 的索引应是 [11,23,35]
                Xs.append(x_scalar)
                Ss.append(s)
                Yks.append(key)
                Ycs.append(curve.astype(np.float32))

    X = np.asarray(Xs, dtype=np.float32)
    S = np.asarray(Ss, dtype=np.int64)
    Yk = np.asarray(Yks, dtype=np.float32)
    Yc = np.asarray(Ycs, dtype=np.float32)
    return X, S, Yk, Yc


# =========================================================================
# Legacy 兼容（prediction.py 兜底：没有权重文件时 stage1 fallback 训练还会走这些老 API）
# 保留旧接口但标 deprecated，避免 stage1 测试路径炸
# =========================================================================
@dataclass(frozen=True)
class TrainMeta:
    num_days: int
    history_steps: int
    pred_steps: int
    train_ratio: float
    epochs: int
    best_val_loss: float
    device: str


if TORCH_AVAILABLE:
    class LSTMPredictor(nn.Module):  # type: ignore[misc]  # noqa: D101 (legacy)
        """Stage 1/2 legacy: 多区一次预测。Stage3 使用 MultiHorizonLSTM。"""

        def __init__(
            self,
            num_zones: int,
            hidden_size: int = 64,
            num_layers: int = 2,
            pred_steps: int = 3,
        ):
            super().__init__()
            self.num_zones = num_zones
            self.pred_steps = pred_steps
            self.lstm = nn.LSTM(
                input_size=num_zones,
                hidden_size=hidden_size,
                num_layers=num_layers,
                batch_first=True,
            )
            self.head = nn.Sequential(
                nn.Linear(hidden_size, hidden_size),
                nn.ReLU(),
                nn.Linear(hidden_size, pred_steps * num_zones),
            )

        def forward(self, x: "torch.Tensor") -> "torch.Tensor":
            out, _ = self.lstm(x)
            last = out[:, -1, :]
            pred_flat = self.head(last)
            return pred_flat.view(-1, self.pred_steps, self.num_zones)
else:
    LSTMPredictor = None  # type: ignore


def _make_supervised_samples(
    x_days: list[np.ndarray],
    history_steps: int,
    pred_steps: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Legacy: used by stage1 _train_and_save fallback path only."""
    xs: list[np.ndarray] = []
    ys: list[np.ndarray] = []
    for x in x_days:
        T = x.shape[0]
        for i in range(history_steps - 1, T - pred_steps - 1):
            xs.append(x[i - history_steps + 1 : i + 1])
            ys.append(x[i + 1 : i + 1 + pred_steps])
    return np.asarray(xs, dtype=np.float32), np.asarray(ys, dtype=np.float32)


def train(*args: Any, **kwargs: Any) -> tuple[Any, TrainMeta]:
    """Legacy stage1 entry only. Not used by real Citi-Bike pipeline."""
    raise NotImplementedError(
        "Legacy train() removed. Use backend/train_model.py with train_ready.npz instead."
    )


def predict(model: Any, input_seq: np.ndarray) -> np.ndarray:
    """Legacy LSTMPredictor inference: [H, num_zones] -> [pred_steps, num_zones]."""
    if not TORCH_AVAILABLE:
        raise RuntimeError("PyTorch is not available.")
    if input_seq.ndim != 2:
        raise ValueError("input_seq must be [history_steps, num_zones]")
    x = torch.tensor(input_seq[None, ...], dtype=torch.float32)
    device = next(model.parameters()).device
    x = x.to(device)
    model.eval()
    with torch.no_grad():
        pred = model(x)
    return pred[0].detach().float().cpu().numpy().astype(np.float32)
