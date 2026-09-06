# BikeDispatch · Citi Bike NYC Rebalancing System

> Spatial-temporal Analysis and Geographic Visualization System for Urban Micromobility —
> Bike rebalancing decision support for 30 high-frequency Citi Bike stations in Manhattan.

```
Data:      Citi Bike NYC  |  2025 Jan–May  |  5 months × 30 stations × 5 min  =  151 × 288 × 30 space-time cube
Pipeline:  Parquet → bbox filter → trip counts → vehicle-series inversion → 9-feature tensor (w/ time encoding & station embedding)
ML:        Shared LSTM encoder (2L × 96h, DO 0.2) + Dual Head:  1h/2h/3h anchors (Dense)  &  3 h full curve (Conv1D)
GIS:       UTM/ENU projection repair, Space-Time Cube slicing, Global & Local Moran's I, Gravity-IPF OD approximation,
           OSRM real-street routing
UI:        Leaflet + 5 analytic GIS layer tabs, 24 h time-slider replay, LISA HH/LL hotspots, Typical-Day weekday vs weekend
```

---

## 1. Research Framing (GIS Portfolio Narrative)

### Research Questions (RQ)

| # | RQ | Method | Evidence produced |
|---|----|--------|-------------------|
| RQ1 | **What is the quantitative error of naïve lon/lat Euclidean distance when used for distance-based dispatch and spatial-weight construction around Manhattan (40.73°N)?**  Does a proper UTM/ENU local projection materially reduce the error? | Pairwise distance audit (30 zones × 30 zones) comparing *naïve degree-Euclidean* vs *UTM 18N projected Haversine-free metric* vs *ENU tangent-plane metric*. | Naïve **mean abs err 12.49 %** → projected **0.0312 %**  (↓ **401×**). P95 < 0.04 %.  lon/lat ≈ 76 % cosine ratio at 40.73°N. |
| RQ2 | **Does Citi Bike availability in Manhattan exhibit statistically significant *spatial autocorrelation* at commute hours?**  Is the shortage/surplus pattern random (CSR) or clustered? | **Global Moran's I** (Cliff & Ord variance, normal-approximation two-sided p-value) + **Local LISA** (Anselin 1995, 199 conditional permutations, α = 0.05) on KNN (k=5) weights. | At 09:00 for *vehicles* attribute: **Moran's I = 0.0559**, **Z = 7.36**, **p ≈ 1.9 × 10⁻¹³** → **Significant clustering (reject CSR)**. LISA recovers HH / HL / LH / LL clusters on specific stations (e.g. residential LL vs campus-core HH). |
| RQ3 | **Can a 2D Origin–Destination matrix be reconstructed from aggregate outflows/inflows + a distance-decay gravity model when route-level OD is missing?** | **Gravity + Iterative Proportional Fitting (IPF)** impedance function *exp(−β · d), β = 0.001 2*. Compare convergence *TOL ≤ 10⁻⁴*, max 50 iter. Top-40 edges rendered on map as flow arcs. | IPF converges in ≤ 12 iterations for all time windows.  Hourly total flow ≈ 3 237 trips,  highest symmetric pair *West St & Chambers St ↔ Vesey Pl & River Ter* at ≈ 110 trips/hr roundtrip. |
| RQ4 | **Does the weekday/weekend *typical-day* curve show the expected tidal phase shift and amplitude change consistent with commute vs leisure behavior?** | Typical-day aggregation: 108 weekdays vs 43 weekend samples (30-min half-hour slots), per-station CV ranking, matched peak-shift analysis on early-peak stations. | Top CV tidal station: CV = 23 % (nightlife area, peak 23:30).  At least 1 of top-5 tidal stations has commute peak 06:00–12:00 or 16:00–21:00.  Early-peak station WD peak 09:30 → WE peak 23:30 (evidence of weekend lifestyle delay). |

---

## 2. Architecture Overview

```
┌────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                          Frontend (Vue 3 + Vite)                               │
│  ┌─────────────┐ ┌───────────────┐ ┌─────────────┐ ┌──────────────┐ ┌────────────────────────┐ │
│  │ 📌 Status/  │ │ ⏱ Timeline    │ │ 🌊 OD flows │ │ 📊  Moran I   │ │ 📈 Typical-Day (WD/WE)  │ │
│  │  Dispatch   │ │ 24h slider    │ │ arcs w/ β   │ │  + LISA map   │ │ curve + peak-shift     │ │
│  └──────┬──────┘ └──────┬────────┘ └──────┬──────┘ └──────┬───────┘ └───────────┬────────────┘ │
│         └───────────────┴─────────────────┴───────────────┴──────────────────────┘              │
│                                        Leaflet map + ECharts panels                             │
└──────────────────────────────────────────────┬─────────────────────────────────────────────────┘
                                               │  HTTP 8080 → 8000
┌──────────────────────────────────────────────▼─────────────────────────────────────────────────┐
│                                  Backend (FastAPI + PyTorch + NumPy)                           │
│                                                                                                │
│   prediction.py  ──►  MultiHorizonLSTM:  history(24)  →  3 anchors + 36-step curve              │
│                      →  predicted_need_by_zone / worst_by_zone dicts  (horizon-aware dispatch) │
│                                                                                                │
│   dispatch.py    ──►  Greedy nearest-pair:  surplus ⇄ shortage,  qty = min(|surplus|, shortage) │
│                      OSRM real street (ghcr.io/project-osrm/osrm-backend:v5.27.1)  OR  line  │
│                      fall-back.  horizon_used = worst,  route_source ∈ {osrm / straight / …}   │
│                                                                                                │
│   gis.py         ──►  /timeline  /od_flows  /spatial_stats  /projection_audit  /typical_day    │
│                                                                                                │
│   geoutils.py    ──►  UTM/ENU projectors · KNN/band W · Global Moran I · Local LISA · IPF OD    │
│                      (Moran variance stable: clamp var_i ≤ 1e-10 → random,  avoids Z = 2.7e7)  │
└────────────────────────────────────────────────────────────────────────────────────────────────┘
         ▲                           ▲
         │  npz tensors              │  OSRM (HTTP 5000 · NYC contracted graph from BBBike extract)
         ▼                           ▼
 data/train_ready.npz       docker-compose: ghcr.io/project-osrm/osrm-backend:v5.27.1
 data/od_matrix.npz
 backend/models/lstm_weights_multi.pth   (stage3 checkpoint: state_dict + train_meta + metrics)
```

### Stage3 Prediction Contract (per zone)

Response model: `POST /api/predict` → `zones: list[ZonePredict]` (30 entries in zone-order), plus top-level dicts for dispatch inputs.

```python
ZonePredict = {
    "zone_id", "name", "capacity", "current_count", "current_ratio",
    "status": "shortage | surplus | healthy",
    "need": float,             # positive → shortage (需调入),  negative → surplus (可调出)
    "forecast_anchors": [{     # 1h / 2h / 3h  anchor points
        "label", "minutes", "time", "vehicles", "delta_vs_now", "need", "baseline_persistent"
    }],
    "worst_horizon": { "label", "minutes", "time", "need" },
}
# Plus top-level:  predicted_need_by_zone[zid]=need,  worst_by_zone[zid]={horizon_label, minutes, need},
#                 series_by_zone[zid]: {history_times(24), history_vehicles, curve_times(36), curve_vehicles_lstm, …},
#                 summary: {n_shortage, n_surplus, n_healthy, thresholds},
#                 baseline_evidence: {model_type, per_horizon: {MAE, RMSE, MAPE, improvement_pct_mae}}
```

### Dispatch Contract

`POST /api/dispatch`  takes **predicted_need_by_zone** and optional **worst_minutes_by_zone**.
Always returns: `tasks[*]` (simplified list: `from_id, to_id, qty, route_lonlats, distance_m, route_source, worst_min_from, worst_min_to`)
plus `horizon_used`,  `route_source: "osrm | straight | mixed | none"`,  `summary: {n_plans, total_vehicles, routes_from_osrm, routes_from_straight_fallback}`.

---

## 3. Key Evidence Numbers (Portfolio-ready)

All figures come from `test_api_acceptance_v2.py` — the **76 / 76 automated GIS acceptance checks**.

| Metric | Value |
|--------|-------|
| **Coverage** | NYC Manhattan 30 stations (2.5 km buffer around Washington Square Park, GeoJSON `nyu_zones.geojson`) |
| **Train / Test split** | 120 / 31 calendar days (strict monthly cut — no temporal leakage) |
| **Sim interval** | 5 min → 288 daily frames × 151 days = 43 488 obs per station |
| **LSTM architecture** | shared LSTM 2L × hidden=96 + dropout 0.2;  Dense head (3 anchors) + Conv1D head (36 steps) |
| **Features (9)** | vehicles_norm (per-station capacity), hour_sin, hour_cos, dow_sin, dow_cos, am_peak_mask, pm_peak_mask, weekend_flag, station_embedding |
| **Projection repair (RQ1)** | naive: mean 12.49 %, p95 15.6 % → projected: **mean 0.031 %, p95 0.04 %** → **401× error reduction** |
| **Space-Time Cube** | 288 × 30 × 5 min = **8 640 cells / day**,  151-day cube → **1.3 M cells** |
| **Tidal CV** (per-station mean across day) | **5.8 %**;  top tidal station CV **23 %** (amplitude 18 bikes/day, trough 05:30, peak 23:30) |
| **Global Moran (RQ2)** | 09:00 · vehicles · KNN k=5:  **I = 0.0559,  Z = 7.36,  p = 1.9 × 10⁻¹³**  → clustered (✗ CSR) |
| **LISA clusters** | across 5 probe cases:  ≥ 3 / 30 stations HH/HL/LH/LL at α = 0.05 |
| **OD IPF (RQ3)** | β = 0.001 2,  top pair 110 trips/hr (symmetric),  hourly total ≈ 3 237 trips,  converges ≤ 12 iters |
| **Typical day (RQ4)** | n_weekday = 108,  n_weekend = 43;  at least 1 top-5 CV station peaks in 06–12 or 16–21 commute window;  early-peak station WD 09:30 → WE 23:30 phase shift |
| **Stage3 prediction → dispatch** | 22 greedy balanced moves × 87 vehicles for the morning probe window,  route_source=straight (OSRM stand-alone start gives osrm route_polyline) |
| **Stage3 MAE improvement vs persistent baseline** (per checkpoint baseline_evidence) | 1h: −0.9 %,  2h: +5.8 %,  3h: +9.0 %  (increasing horizon rewards predictive signal — persistent alone degrades) |

### Automated Acceptance

```bash
python test_api_acceptance_v2.py
# PASSED:   76 / 76   (100%)
# FAILED:    0 / 76
```

Sections covered:  (1) Backend health,  (2) Projection audit,  (3) Space-Time Cube,  (4) Moran/LISA,  (5) OD flows,  (6) Typical-day,  (7) Stage3 history→predict,  (8) Stage3 dispatch with OSRM-ready route_source & horizon_used.

---

## 4. Quick Start (Docker)

```bash
docker compose up -d --build
# services:
#   postgres   5432  (dispatch history registry — optional; defaults run without)
#   osrm       5000  ghcr.io/project-osrm/osrm-backend:v5.27.1  →  downloads BBBike NYC pbf + contracts graph (≈2 GB disk,  first-run ~5–15 min)
#   backend    8000  FastAPI
#   frontend   8080  Vite dev-server / dist
```

Open:
- Frontend GIS dashboard:  http://localhost:8080/dashboard/live
- Backend Swagger UI:   http://localhost:8000/docs
- OSRM status:          http://localhost:5000/nearest/v1/driving/-73.99,40.73

### GIS Layer Tabs (on `/dashboard/live`)

| Tab | What to see | Controls |
|-----|-------------|----------|
| 📌 **Status / Dispatch** | Shortage (red ≥ 3) / Healthy (gray |need|<3) / Surplus (green ≤ −3). Click “预测未来3小时 → 一键调度” to run Stage3 LSTM + OSRM street moves. | Time combobox (早高峰 08:30入园 / 晚高峰 18:00 etc.) |
| ⏱ **Timeline** | Space-Time Cube slice animation — watch morning inflow → evening outflow. | preset start, display-mode (Need / ratio / vehicles), granularity (10/15/30 min), sample-day, play/pause/rewind, speed (0.8–8×) |
| 🌊 **OD flows** | Gravity-IPF OD flow arcs; thickness = count, colour = Top-K intensity. | Time window, Top-K edges, weekday/weekend |
| 📊 **Moran / LISA** | Global Moran test result + LISA HH/LL/HL/LH clusters on map. | Attribute (Need / ratio / vehicles),  weight (KNN k=3/5/7 or Distance Band) |
| 📈 **Typical day** | Weekday vs weekend curves, peak shift, amplitude contrast. | Time-range, attribute, overlay mode |

---

## 5. Retraining the Stage3 Model

Transfer these files to your GPU server (no local training — compute credits are expensive):

```
backend/scripts/prepare_trips.py      # Step 0-7: parquet → train_ready.npz + od_matrix.npz
backend/train_model.py                # Stage3 trainer: MultiHorizonLSTM dual-head, 50 epochs, RTX 5090-ready
backend/app/config.py                 # HISTORY_STEPS=24, PRED_FULL_STEPS=36, PRED_KEY_MINUTES=[60,120,180]
backend/app/models/lstm_model.py      # Model forward signature (keep identical)
backend/requirements-train.txt
citibike/2501.parquet … 2505.parquet  # Citi Bike raw
data/nyu_zones.geojson                # 30 stations (bbox & freq filtered)
```

Training design points (for the portfolio reader):
- Sliding window per station,  normalizes capacity per station → bounded targets.
- Dual-head loss:  `L = α·MAE(key anchors) + (1−α)·MAE(full 36-step curve)`,  α=0.5.
- Evaluation *before* final save (weights → `.tmp` first),  persistent baseline explicitly tiled to `[N_eval, K_eval]`,  try/except on metrics → always writes a valid checkpoint,  final checkpoint backed up to `.bak` to avoid overwriting accidents.
- PyTorch compatibility:  `getattr` + try/except dual-path for torch 1.x / 2.0–2.3 / ≥ 2.4 APIs (bfloat16 handling; `.float()` before `.cpu().numpy()` since server numpy < 2.0 has no bfloat16).

The checkpoint `backend/models/lstm_weights_multi.pth` is a `torch.save({state_dict, train_meta, metrics, zone_order, capacity})` bundle — loadable directly in `prediction.py` with `LSTMPredictor(...)` shape matched.

---

## 6. GIS Acceptance Screenshots

Generated via automated browser pass (3 full-page captures for each of the three core GIS layers):

```
portfolio_screenshots/
├── timeline_peak_0830.png      # Timeline tab,  08:30 peak frame,  Need colouring,  summary cards
├── od_morning_rush.png         # OD tab,  08:30 (入园),  top-40 arc flows  (thickness ≈ flow)
└── moran_lisa_spatial.png      # Moran/LISA tab,  Need attribute,  KNN k=5,  HH/LL/HL/LH legend
```

---

## 7. Why This Reads as GIS, not Generic ML

| Generic “AI bike dispatcher” slot | GIS-framework slot this repo fills |
|---|---|
| “ML predicts demand” → black-box | *Space-time cube input*; LSTM encoder is a *time-series interpolator between geographic states*. |
| Distance is `sqrt(dx²+dy²)` on raw lat/lon | **RQ1 projection audit** proves naive distance is *systematically wrong* at 40.73°N by ~12.5 %; we repair and quantify the improvement (401×). |
| Dispatch is “shortage + surplus pair” | Greedy nearest-pair uses **projected metric** and routes via **OSRM real-street** engine from OpenStreetMap NYC pbf; `route_source` recorded. |
| Demand pattern is “unexplained” | **RQ2 spatial autocorrelation (Moran I + LISA)** answers “is shortage random or clustered?”, producing significance tests you cite in a GIS methods section. |
| OD matrix treated as ground truth | **RQ3 Gravity + IPF** shows how you *estimate* flows from marginals when route logs are missing — a classic spatial interaction model. |
| Daily seasonality ignored | **RQ4 Typical-day weekday/weekend** demonstrates tidal phase shift (commute vs leisure) as the expected geographic behavioural pattern. |
| Visualization = dashboard | Visualization = *GIS layer tabs* with cartographically meaningful legends, time-slider, flow arcs, and LISA cluster colouring. |

---

© BikeDispatch — Citi Bike NYC Rebalancing System. Data source: Citi Bike System Data (© Lyft). Map tiles: OpenStreetMap contributors. OSRM: Project-OSRM (ghcr.io/project-osrm/osrm-backend:v5.27.1).
