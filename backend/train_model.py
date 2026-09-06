"""
backend/train_model.py — Stage3 多尺度多步预测训练

目标:
  - 训练 MultiHorizonLSTM（LSTM+station_embedding+dual_head，3锚点+3h曲线）
  - 严格按天 70/15/15 切 train/val/test（按月切，120天/22天/9天 → 避免时间泄露）
  - 双 head 损失 + peak 加权，关键窗口(早晚高峰)学习权重 2x
  - 评估 1h/2h/3h 锚点 MAE/RMSE，并与 Persistent baseline(ratio[t+h]=ratio[t]) 对比
  - 权重 + train_meta + metrics 一起打包保存到 backend/models/lstm_weights_multi.pth
    （prediction.py 加载后按 station_ids 对齐 public zone_order）

服务器训练命令:
  cd /workspace/bike_dispatch_system
  BIKE_TRAIN_EPOCHS=50 python backend/train_model.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

repo_backend_dir = Path(__file__).resolve().parent
if str(repo_backend_dir) not in sys.path:
    sys.path.insert(0, str(repo_backend_dir))

from app.config import (  # noqa: E402
    HISTORY_STEPS,
    PRED_FULL_STEPS,
    PRED_KEY_HORIZONS,
    PRED_KEY_MINUTES,
    PRED_KEY_LABELS,
    STATION_EMBEDDING_DIM,
    TARGET_CAPACITY_RATIO,
)
from app.models.lstm_model import (  # noqa: E402
    MultiHorizonLSTM,
    make_per_station_windows,
    TORCH_AVAILABLE,
)


def _version_compat_amp():
    """返回 (bfloat_dtype, is_bf16_supported_fn, make_grad_scaler_fn, autocast_ctx_maker)."""
    import torch
    bf = getattr(torch, "bfloat16", None)
    if bf is None:
        bf = getattr(torch, "bf16", None)

    def _bf_supported() -> bool:
        if not torch.cuda.is_available():
            return False
        try:
            cc = torch.cuda.get_device_capability(0)[0]
            if cc >= 8:
                return True
        except Exception:
            pass
        fn = getattr(torch.cuda, "is_bf16_supported", None)
        if callable(fn):
            try:
                return bool(fn())
            except Exception:
                return False
        return False

    def _scaler(enabled: bool):
        if not enabled:
            return None
        try:
            ampm = getattr(torch, "amp", None)
            cls = getattr(ampm, "GradScaler", None) if ampm else None
            if cls is not None:
                return cls("cuda", enabled=True)
        except Exception:
            pass
        try:
            camp = getattr(torch.cuda, "amp", None)
            cls = getattr(camp, "GradScaler", None) if camp else None
            if cls is not None:
                return cls(enabled=True)
        except Exception:
            pass
        return None

    def _ctx(enabled: bool, dtype):
        if not enabled:
            class _N:
                def __enter__(self): return None
                def __exit__(self, *a): return False
            return _N()
        try:
            ampm = getattr(torch, "amp", None)
            fn = getattr(ampm, "autocast", None) if ampm else None
            if fn is not None:
                return fn("cuda", dtype=dtype)
        except Exception:
            pass
        try:
            camp = getattr(torch.cuda, "amp", None)
            fn = getattr(camp, "autocast", None) if camp else None
            if fn is not None:
                return fn(dtype=dtype)
        except Exception:
            pass
        class _N2:
            def __enter__(self): return None
            def __exit__(self, *a): return False
        return _N2()
    return bf, _bf_supported, _scaler, _ctx


def main() -> None:
    if not TORCH_AVAILABLE:
        raise RuntimeError("PyTorch not installed.")
    import torch
    import torch.nn as nn

    print(f"PyTorch {torch.__version__}")
    cuda_ok = torch.cuda.is_available()
    print(f"CUDA: {cuda_ok}")
    if cuda_ok:
        props = torch.cuda.get_device_properties(0)
        vram = getattr(props, "total_memory", None)
        if vram is None:
            vram = getattr(props, "total_mem", 0)
        print(f"GPU : {torch.cuda.get_device_name(0)}  VRAM: {vram/1024**3:.1f}GB  "
              f"CC={torch.cuda.get_device_capability(0)}")
    print()

    _bf16_dtype, _is_bf16, _make_scaler, _autocast_ctx = _version_compat_amp()

    repo_root = Path(__file__).resolve().parent
    data_dir = repo_root / ".." / "data"
    weights_path = repo_root / "models" / "lstm_weights_multi.pth"

    print("=" * 72)
    print("Stage3 Multi-Horizon LSTM 训练（1h/2h/3h 3锚点 + 3h全长曲线）")
    print("=" * 72)

    # ---- 数据加载 ----
    train_ready = np.load(data_dir / "train_ready.npz", allow_pickle=True)
    vehicles_ratio = train_ready["vehicles_ratio"].astype(np.float32)  # [D,T,N]
    capacity = train_ready["capacity"].astype(np.float32)              # [N]
    station_idx = train_ready["station_idx"].astype(np.int64)          # [N]
    station_ids = [str(s) for s in train_ready["station_ids"].tolist()]
    station_names = [str(s) for s in train_ready["station_names"].tolist()]

    hour_sin = train_ready["hour_sin"].astype(np.float32)   # [T]
    hour_cos = train_ready["hour_cos"].astype(np.float32)
    dow_sin = train_ready["dow_sin"].astype(np.float32)     # [D]
    dow_cos = train_ready["dow_cos"].astype(np.float32)
    is_morning_peak = train_ready["is_morning_peak"].astype(np.float32)
    is_evening_peak = train_ready["is_evening_peak"].astype(np.float32)
    is_weekend = train_ready["is_weekend"].astype(np.float32)

    tf_global = {
        "hour_sin": hour_sin, "hour_cos": hour_cos,
        "dow_sin": dow_sin, "dow_cos": dow_cos,
        "is_morning_peak": is_morning_peak,
        "is_evening_peak": is_evening_peak,
        "is_weekend": is_weekend,
    }
    HISTORY_STEPS_V = int(train_ready.get("HISTORY_STEPS", HISTORY_STEPS).item() if hasattr(train_ready.get("HISTORY_STEPS", None), "item") else train_ready.get("HISTORY_STEPS", HISTORY_STEPS))
    PRED_FULL_STEPS_V = int(train_ready["PRED_FULL_STEPS"].item())
    PRED_KEY_HORIZONS_V = train_ready["PRED_KEY_HORIZONS"].astype(int).tolist()

    D, T, N = vehicles_ratio.shape
    print(f"train_ready: D={D} days  T={T} slots/day  N={N} stations")
    print(f"  H (history)={HISTORY_STEPS_V} slots ({HISTORY_STEPS_V*5}min)  "
          f"P (full curve)={PRED_FULL_STEPS_V} slots ({PRED_FULL_STEPS_V*5}min)")
    print(f"  KEY horisons (step idx) = {PRED_KEY_HORIZONS_V} = "
          f"[{PRED_KEY_MINUTES[0]}/{PRED_KEY_MINUTES[1]}/{PRED_KEY_MINUTES[2]} min]")
    print(f"  station ids (first 3, last 3): {station_ids[:3]} ... {station_ids[-3:]}")
    print(f"  capacity range: [{capacity.min():.0f}, {capacity.max():.0f}]")
    print()

    # ---- 时序划分（70/15/15 按天连续切，按月对齐：1-4月=~120 train，5月31天=test+val) ----
    n_train = int(D * 0.70)   # 105 days (1~3月下旬)
    n_val = int(D * 0.15)     # 22 days (4月中-4月底)
    train_days = list(range(0, n_train))
    val_days = list(range(n_train, n_train + n_val))
    test_days = list(range(n_train + n_val, D))
    print(f"Split (day index, strictly time-series):")
    print(f"  train {len(train_days)} days: [{train_days[0]} .. {train_days[-1]}]")
    print(f"  val   {len(val_days)} days: [{val_days[0]} .. {val_days[-1]}]")
    print(f"  test  {len(test_days)} days: [{test_days[0]} .. {test_days[-1]}]")
    print()

    N_STATION = N
    station_list = list(range(N_STATION))
    print("Building windows (per-station + per-day, no cross-day leak)...")
    X_tr, S_tr, Yk_tr, Yc_tr = make_per_station_windows(
        vehicles_ratio, tf_global,
        day_indices=train_days, station_list=station_list,
        history_steps=HISTORY_STEPS_V,
        pred_full_steps=PRED_FULL_STEPS_V,
        pred_key_horizons=PRED_KEY_HORIZONS_V,
    )
    X_va, S_va, Yk_va, Yc_va = make_per_station_windows(
        vehicles_ratio, tf_global,
        day_indices=val_days, station_list=station_list,
        history_steps=HISTORY_STEPS_V,
        pred_full_steps=PRED_FULL_STEPS_V,
        pred_key_horizons=PRED_KEY_HORIZONS_V,
    )
    X_te, S_te, Yk_te, Yc_te = make_per_station_windows(
        vehicles_ratio, tf_global,
        day_indices=test_days, station_list=station_list,
        history_steps=HISTORY_STEPS_V,
        pred_full_steps=PRED_FULL_STEPS_V,
        pred_key_horizons=PRED_KEY_HORIZONS_V,
    )
    print(f"  train: X={X_tr.shape}  Yk={Yk_tr.shape}  Yc={Yc_tr.shape}")
    print(f"  val  : X={X_va.shape}  Yk={Yk_va.shape}  Yc={Yc_va.shape}")
    print(f"  test : X={X_te.shape}  Yk={Yk_te.shape}  Yc={Yc_te.shape}")
    print()

    # ---- peak 权重（每个样本：若是 morning/evening peak 窗口末时刻，weight=2.0）----
    def _peak_weight(X_arr: np.ndarray) -> np.ndarray:
        """Use last history frame's is_morning_peak or is_evening_peak as proxy (channels 4/5 of scalar 8)
        channel 4=mp_last, channel 5=ep_last"""
        last = X_arr[:, -1, :]   # [B, 8]
        mp = last[:, 4] > 0.5
        ep = last[:, 5] > 0.5
        w = np.where(mp | ep, 2.0, 1.0).astype(np.float32)
        return w

    W_tr = _peak_weight(X_tr)
    W_va = _peak_weight(X_va)
    W_te = _peak_weight(X_te)
    print(f"Peak weighting: train {100*(W_tr>1.0).mean():.1f}% peaks, "
          f"val {100*(W_va>1.0).mean():.1f}%, test {100*(W_te>1.0).mean():.1f}%")
    print()

    # ---- 训练超参数（5090 默认配置，环境变量覆盖） ----
    epochs = int(os.getenv("BIKE_TRAIN_EPOCHS", "50"))
    batch_size = int(os.getenv("BIKE_TRAIN_BATCH", "1024"))
    lr = float(os.getenv("BIKE_TRAIN_LR", "3e-4"))
    hidden_size = int(os.getenv("BIKE_TRAIN_HIDDEN", "128"))
    num_layers = int(os.getenv("BIKE_TRAIN_LAYERS", "2"))
    weight_decay = float(os.getenv("BIKE_TRAIN_WD", "1e-4"))
    grad_clip = float(os.getenv("BIKE_TRAIN_GRADCLIP", "1.0"))
    use_amp = os.getenv("BIKE_TRAIN_AMP", "1") != "0"
    loss_w_key = float(os.getenv("BIKE_LOSS_W_KEY", "0.55"))
    loss_w_cur = float(os.getenv("BIKE_LOSS_W_CUR", "0.35"))
    loss_w_mae = float(os.getenv("BIKE_LOSS_W_MAE", "0.10"))  # MAE 正则 (L1 on key)
    device = "cuda" if cuda_ok else "cpu"

    torch.manual_seed(42)
    np.random.seed(42)
    if cuda_ok:
        torch.cuda.manual_seed_all(42)
        torch.backends.cudnn.benchmark = True

    model = MultiHorizonLSTM(
        n_stations=N_STATION,
        scalar_dim=8,
        embed_dim=int(STATION_EMBEDDING_DIM),
        hidden_size=hidden_size,
        num_layers=num_layers,
        pred_full_steps=PRED_FULL_STEPS_V,
        pred_key_len=len(PRED_KEY_HORIZONS_V),
    ).to(device)
    total_params = sum(p.numel() for p in model.parameters())
    print(f"Model: {num_layers}-layer LSTM hidden={hidden_size}  emb={STATION_EMBEDDING_DIM}  "
          f"params={total_params:,}")
    print(f"  loss = {loss_w_key}*MSE(key) + {loss_w_cur}*MSE(curve) + {loss_w_mae}*MAE(key)")
    print(f"  epochs={epochs} batch={batch_size} lr={lr:.2e} wd={weight_decay:.1e} amp={'ON' if use_amp else 'OFF'}")

    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs, eta_min=lr * 0.02)

    use_bf16 = bool(use_amp and cuda_ok and _is_bf16() and _bf16_dtype is not None)
    amp_enabled = bool(use_amp and cuda_ok)
    scaler = _make_scaler(enabled=(amp_enabled and not use_bf16))
    amp_dtype = _bf16_dtype if use_bf16 else torch.float16
    gpu_name = torch.cuda.get_device_name(0) if cuda_ok else "CPU"
    print(f"  AMP dtype = {'bf16' if use_bf16 else ('fp16' if amp_enabled else 'fp32')}  device={device} ({gpu_name})")
    print("-" * 72)

    def _to_t(arr, dtype=torch.float32, dev=device):
        return torch.as_tensor(np.ascontiguousarray(arr), dtype=dtype, device=dev)

    X_tr_t = _to_t(X_tr)
    S_tr_t = _to_t(S_tr, dtype=torch.long)
    Yk_tr_t = _to_t(Yk_tr)
    Yc_tr_t = _to_t(Yc_tr)
    W_tr_t = _to_t(W_tr)
    X_va_t = _to_t(X_va)
    S_va_t = _to_t(S_va, dtype=torch.long)
    Yk_va_t = _to_t(Yk_va)
    Yc_va_t = _to_t(Yc_va)

    best_val = float("inf")
    best_state = None
    mse = nn.MSELoss(reduction="none")
    mae = nn.L1Loss(reduction="none")

    def _weighted_mean(loss_per_sample, w):
        """loss_per_sample: [B] or [B, ...], w: [B]"""
        B = loss_per_sample.shape[0]
        flat = loss_per_sample.reshape(B, -1).mean(dim=1)  # [B]  样本级均值
        return (flat * w).sum() / w.sum().clamp(min=1e-8)

    def _loss_fn(y_key, y_cur, yk_true, yc_true, w):
        k_mse = _weighted_mean(mse(y_key, yk_true), w)
        c_mse = _weighted_mean(mse(y_cur, yc_true), w)
        k_mae = _weighted_mean(mae(y_key, yk_true), w)
        return loss_w_key * k_mse + loss_w_cur * c_mse + loss_w_mae * k_mae, (k_mse, c_mse, k_mae)

    Ntrain = X_tr_t.shape[0]
    for epoch in range(1, epochs + 1):
        model.train()
        perm = torch.randperm(Ntrain, device=device)
        total_l = 0.0
        total_n = 0
        for s0 in range(0, Ntrain, batch_size):
            idx = perm[s0 : s0 + batch_size]
            xb = X_tr_t[idx]
            sb = S_tr_t[idx]
            ykb = Yk_tr_t[idx]
            ycb = Yc_tr_t[idx]
            wb = W_tr_t[idx]
            optimizer.zero_grad(set_to_none=True)
            if amp_enabled:
                with _autocast_ctx(enabled=True, dtype=amp_dtype):
                    yk, yc = model(xb, sb)
                    loss, _sub = _loss_fn(yk, yc, ykb, ycb, wb)
                if use_bf16:
                    loss.backward()
                else:
                    scaler.scale(loss).backward()
            else:
                yk, yc = model(xb, sb)
                loss, _sub = _loss_fn(yk, yc, ykb, ycb, wb)
                loss.backward()
            if amp_enabled and not use_bf16:
                scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), grad_clip)
            if amp_enabled and not use_bf16:
                scaler.step(optimizer)
                scaler.update()
            else:
                optimizer.step()
            total_l += float(loss.item()) * xb.shape[0]
            total_n += xb.shape[0]
        train_loss = total_l / max(1, total_n)
        scheduler.step()

        # ---- 验证：分批前向，避免 OOM ----
        model.eval()
        val_loss_total = 0.0
        val_weight_sum = 0.0
        batch_size_val = max(batch_size, 2048)  # 可根据显存调整
        N_va = X_va_t.shape[0]
        for s0 in range(0, N_va, batch_size_val):
            xb = X_va_t[s0:s0 + batch_size_val]
            sb = S_va_t[s0:s0 + batch_size_val]
            ykb = Yk_va_t[s0:s0 + batch_size_val]
            ycb = Yc_va_t[s0:s0 + batch_size_val]
            wb = torch.as_tensor(W_va[s0:s0 + batch_size_val], device=device, dtype=torch.float32)
            with torch.no_grad():
                if amp_enabled:
                    with _autocast_ctx(enabled=True, dtype=amp_dtype):
                        yk, yc = model(xb, sb)
                        loss, _sub = _loss_fn(yk, yc, ykb, ycb, wb)
                else:
                    yk, yc = model(xb, sb)
                    loss, _sub = _loss_fn(yk, yc, ykb, ycb, wb)
            # loss 是当前 batch 的加权平均，需乘以权重和，用于全局加权平均
            w_sum = wb.sum().item()
            val_loss_total += loss.item() * w_sum
            val_weight_sum += w_sum
        val_loss = val_loss_total / max(1e-8, val_weight_sum)

        if val_loss < best_val:
            best_val = val_loss
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        bl = 20
        filled = int(bl * epoch / epochs)
        bar = "=" * filled + ">" + " " * (bl - filled - 1)
        lr_c = optimizer.param_groups[0]["lr"]
        print(f"[{bar}] ep {epoch:>2d}/{epochs}  train={train_loss:.5f}  val={val_loss:.5f}  "
              f"best={best_val:.5f}  lr={lr_c:.2e}")

    if best_state is not None:
        model.load_state_dict(best_state)
    print()

    # ====================================================================
    # 先保存权重（即使后续评估阶段出问题，训练成果不丢失）
    # ====================================================================
    threshold = 3.0  # 调度阈值（和前端/调度对齐），评估和 meta 共用
    weights_path.parent.mkdir(parents=True, exist_ok=True)
    train_meta = {
        # 模型结构
        "arch": "MultiHorizonLSTM",
        "n_stations": int(N_STATION),
        "scalar_dim": 8,
        "embed_dim": int(STATION_EMBEDDING_DIM),
        "hidden_size": int(hidden_size),
        "num_layers": int(num_layers),
        "pred_full_steps": int(PRED_FULL_STEPS_V),
        "pred_key_horizons": list(PRED_KEY_HORIZONS_V),
        "pred_key_minutes": list(PRED_KEY_MINUTES),
        "pred_key_labels": list(PRED_KEY_LABELS),
        "history_steps": int(HISTORY_STEPS_V),
        "target_capacity_ratio": float(TARGET_CAPACITY_RATIO),
        "station_ids": station_ids,               # 关键：checkpoint 内部列顺序的 zone_id
        "station_names": station_names,
        "capacity": capacity.tolist(),            # [N] 每站容量（推理和前端都要用）
        "shortage_threshold": threshold,
        "surplus_threshold": threshold,
        # 训练环境
        "n_day_total": int(D),
        "train_days": list(train_days),
        "val_days": list(val_days),
        "test_days": list(test_days),
    }
    train_config = {
        "epochs": epochs, "batch_size": batch_size, "lr": lr,
        "weight_decay": weight_decay, "grad_clip": grad_clip,
        "loss_weights": {"key_mse": loss_w_key, "curve_mse": loss_w_cur, "key_mae": loss_w_mae},
        "peak_weight": 2.0,
        "amp": ("bf16" if use_bf16 else ("fp16" if amp_enabled else "off")),
        "device": gpu_name,
        "params_total": int(total_params),
    }
    # 先保存一份"仅训练结果"的 checkpoint，保证评估失败也有可用权重
    model.eval()
    _cpu_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
    _prelim_path = weights_path.with_name(weights_path.name + ".tmp")
    torch.save({
        "state_dict": _cpu_state,
        "train_meta": train_meta,
        "train_config": train_config,
        "metrics": {},
        "note": "preliminary (before test-eval)",
    }, str(_prelim_path))
    print(f"[save] preliminary weights -> {_prelim_path}")

    # ====================================================================
    # Test 评估（反归一化回真实车辆数，并和 persistent baseline 对比）
    # ====================================================================
    print("=" * 72)
    print("Test 集评估 (真实车辆数单位 + Persistent 基线)")
    print("=" * 72)
    metric_out = {}
    try:
        model.eval()
        with torch.no_grad():
            # 分批避免 OOM
            Bt = max(4096, batch_size * 4)
            N_te = X_te.shape[0]
            K_len = len(PRED_KEY_LABELS)
            P_len = int(PRED_FULL_STEPS_V)
            key_preds_list = []
            cur_preds_list = []
            for s0 in range(0, N_te, Bt):
                xb = _to_t(X_te[s0 : s0 + Bt])
                sb = _to_t(S_te[s0 : s0 + Bt], dtype=torch.long)
                if amp_enabled:
                    with _autocast_ctx(enabled=True, dtype=amp_dtype):
                        yk, yc = model(xb, sb)
                else:
                    yk, yc = model(xb, sb)
                key_preds_list.append(yk.detach().float().cpu().numpy())
                cur_preds_list.append(yc.detach().float().cpu().numpy())
        key_pred = np.concatenate(key_preds_list, axis=0)   # [N_te, K] ratio
        cur_pred = np.concatenate(cur_preds_list, axis=0)   # [N_te, P] ratio

        # 防御：真实 Yk/Yc 维度兼容（prepare/模型改动时 K 可能不一致，这里统一 min 处理）
        K_eval = min(K_len, key_pred.shape[1], Yk_te.shape[1])
        P_eval = min(P_len, cur_pred.shape[1], Yc_te.shape[1])
        # 真实车辆数: ratio × station_capacity[S_te]
        cap_by_s = capacity[S_te.astype(np.int64)].astype(np.float32)         # [N_te]
        cap_col = cap_by_s[:, None]                                           # [N_te,1]
        key_pred_veh = key_pred[:, :K_eval] * cap_col                         # [N_te,K]
        key_true_veh = Yk_te[:, :K_eval] * cap_col                            # [N_te,K]
        cur_pred_veh = cur_pred[:, :P_eval] * cap_col                         # [N_te,P]
        cur_true_veh = Yc_te[:, :P_eval] * cap_col                            # [N_te,P]

        # Persistent baseline：显式 tile 到目标形状（不再依赖广播乘法）
        hist_last_ratio = X_te[:, -1, 0].astype(np.float32)                   # [N_te] ratio
        last_veh_1d = hist_last_ratio * cap_by_s                              # [N_te]
        pers_key_veh = np.tile(last_veh_1d[:, None], (1, K_eval))             # [N_te,K]
        pers_cur_veh = np.tile(last_veh_1d[:, None], (1, P_eval))             # [N_te,P]

        def _mae(a, b): return float(np.mean(np.abs(a - b)))
        def _rmse(a, b): return float(np.sqrt(np.mean((a - b) ** 2)))

        # --- 每个锚点评估 ---
        header = f"{'Window':>7}{'LSTM MAE':>12}{'PERS MAE':>12}{'Improve':>12}{'LSTM RMSE':>12}{'PERS RMSE':>12}"
        print(header)
        print("-" * len(header))
        metrics = {"lstm_key_mae": [], "lstm_key_rmse": [], "pers_key_mae": [], "pers_key_rmse": []}
        for i, (lbl, mins) in enumerate(zip(PRED_KEY_LABELS[:K_eval], PRED_KEY_MINUTES[:K_eval])):
            lm = _mae(key_pred_veh[:, i], key_true_veh[:, i])
            pm = _mae(pers_key_veh[:, i], key_true_veh[:, i])
            lr2 = _rmse(key_pred_veh[:, i], key_true_veh[:, i])
            pr2 = _rmse(pers_key_veh[:, i], key_true_veh[:, i])
            imp = (pm - lm) / pm * 100 if pm > 0 else 0.0
            metrics["lstm_key_mae"].append(lm); metrics["lstm_key_rmse"].append(lr2)
            metrics["pers_key_mae"].append(pm); metrics["pers_key_rmse"].append(pr2)
            print(f"{lbl+f'({mins}m)':>7} {lm:>12.3f} {pm:>12.3f} {imp:>+11.1f}% {lr2:>12.3f} {pr2:>12.3f}")
        # full curve 综合
        lcm = _mae(cur_pred_veh, cur_true_veh); pcm = _mae(pers_cur_veh, cur_true_veh)
        lcr = _rmse(cur_pred_veh, cur_true_veh); pcr = _rmse(pers_cur_veh, cur_true_veh)
        imp_mae = (pcm - lcm) / pcm * 100 if pcm > 0 else 0
        print("-" * len(header))
        print(f"{'Cur(3h)':>7} {lcm:>12.3f} {pcm:>12.3f} {imp_mae:>+11.1f}% {lcr:>12.3f} {pcr:>12.3f}")
        metrics["lstm_curve_mae"] = lcm; metrics["lstm_curve_rmse"] = lcr
        metrics["pers_curve_mae"] = pcm; metrics["pers_curve_rmse"] = pcr
        print()

        # ---- 水位 need 命中（作品集最重要的定性指标：shortage/surplus 分类精度）----
        print(f"need 分类精度（阈值 |need|≥{threshold} 辆，类别=shortage/surplus/ok）")
        need_true = (TARGET_CAPACITY_RATIO - Yk_te[:, :K_eval]) * cap_col     # [N,K]
        need_pred = (TARGET_CAPACITY_RATIO - key_pred[:, :K_eval]) * cap_col
        for i, lbl in enumerate(PRED_KEY_LABELS[:K_eval]):
            def _cat(x):
                return np.where(x >= threshold, 1, np.where(x <= -threshold, 2, 0))
            ct = _cat(need_true[:, i])
            cp = _cat(need_pred[:, i])
            acc = (ct == cp).mean() * 100
            pr_sh = ((cp == 1) & (ct == 1)).sum() / max(1, (cp == 1).sum()) * 100
            rc_sh = ((cp == 1) & (ct == 1)).sum() / max(1, (ct == 1).sum()) * 100
            pr_su = ((cp == 2) & (ct == 2)).sum() / max(1, (cp == 2).sum()) * 100
            rc_su = ((cp == 2) & (ct == 2)).sum() / max(1, (ct == 2).sum()) * 100
            print(f"  {lbl:>3s}: 类别Acc={acc:>5.1f}%  "
                  f"shortage P/R={pr_sh:>4.0f}/{rc_sh:>4.0f}%  "
                  f"surplus  P/R={pr_su:>4.0f}/{rc_su:>4.0f}%")
        print()

        # ---- 打包前端用的 baseline evidence 结构 ----
        per_h = {}
        for i, lbl in enumerate(PRED_KEY_LABELS[:K_eval]):
            per_h[lbl] = {
                "lstm": {"mae": metrics["lstm_key_mae"][i], "rmse": metrics["lstm_key_rmse"][i]},
                "persistent": {"mae": metrics["pers_key_mae"][i], "rmse": metrics["pers_key_rmse"][i]},
                "improvement_pct_mae": float((metrics["pers_key_mae"][i] - metrics["lstm_key_mae"][i])
                                            / max(1e-9, metrics["pers_key_mae"][i]) * 100),
            }
        metric_out = {
            "per_horizon": per_h,
            "curve_3h": {
                "lstm": {"mae": metrics["lstm_curve_mae"], "rmse": metrics["lstm_curve_rmse"]},
                "persistent": {"mae": metrics["pers_curve_mae"], "rmse": metrics["pers_curve_rmse"]},
                "improvement_pct_mae": float((metrics["pers_curve_mae"] - metrics["lstm_curve_mae"])
                                             / max(1e-9, metrics["pers_curve_mae"]) * 100),
            },
            "aggregate": {
                "lstm_avg_key_mae": float(np.mean(metrics["lstm_key_mae"])),
                "pers_avg_key_mae": float(np.mean(metrics["pers_key_mae"])),
                "avg_improvement_pct_mae": float((np.mean(metrics["pers_key_mae"]) - np.mean(metrics["lstm_key_mae"]))
                                                 / max(1e-9, np.mean(metrics["pers_key_mae"])) * 100),
            },
        }
    except Exception as _e:  # noqa: BLE001
        # 评估异常：仅打日志，不影响权重保存（前端 evidence 会显示空，推理仍正常）
        import traceback
        print(f"[WARN] Test evaluation skipped due to error: {_e}")
        traceback.print_exc()
        metric_out = {}

    # ====================================================================
    # 最终保存权重（带完整 metrics）；覆盖 preliminary
    # ====================================================================
    try:
        torch.save({
            "state_dict": _cpu_state,
            "train_meta": train_meta,
            "train_config": train_config,
            "metrics": metric_out,
            "best_val_loss": float(best_val) if best_val is not None else None,
            "note": f"{gpu_name} | epochs={epochs} | train_loss={train_loss:.5f} | best_val={best_val:.5f}",
        }, str(weights_path))
        print(f"[save] final weights -> {weights_path}")
        # 安全起见，再复制一份 backup
        bak = weights_path.with_name(weights_path.name + ".bak")
        try:
            import shutil
            shutil.copyfile(str(weights_path), str(bak))
            print(f"[save] backup -> {bak}")
        except Exception:  # noqa: BLE001
            pass
        try:
            if _prelim_path.exists():
                _prelim_path.unlink()
        except Exception:  # noqa: BLE001
            pass
    except Exception as _e2:  # noqa: BLE001
        import traceback
        print(f"[ERROR] Final torch.save failed: {_e2}")
        traceback.print_exc()
        # 兜底：如果 preliminary 已保存，改名为目标路径
        try:
            if _prelim_path.exists():
                import shutil
                shutil.move(str(_prelim_path), str(weights_path))
                print(f"[save] recovered preliminary as final -> {weights_path}")
        except Exception:  # noqa: BLE001
            pass

    # 给一个 JSON snippet 方便贴申请作品集报告
    try:
        report = {
            "model": "MultiHorizonLSTM (LSTM + station-embedding + dual-head)",
            "params": int(total_params),
            "device": gpu_name,
            "epochs": epochs,
            "batch_size": batch_size,
            "history": f"{HISTORY_STEPS_V * 5}min",
            "forecast": f"3 anchors ({PRED_KEY_LABELS}) + {PRED_FULL_STEPS_V * 5}min full curve",
            "best_val_loss": float(best_val) if best_val is not None else None,
            "metrics": metric_out,
        }
        print("JSON for portfolio report:\n" + json.dumps(report, ensure_ascii=False, indent=2))
    except Exception as _e3:  # noqa: BLE001
        print(f"[WARN] report JSON skipped: {_e3}")


if __name__ == "__main__":
    main()