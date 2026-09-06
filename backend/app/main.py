from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 导入API路由
from .api.data import router as data_router
from .api.dashboard import router as dashboard_router
from .api.dispatch import router as dispatch_router
from .api.monitor import router as monitor_router
from .api.prediction import router as prediction_router
from .api.alerts import router as alerts_router
from .api.lab import router as lab_router
from .api.gis import router as gis_router
from .state import init_state


def create_app() -> FastAPI:
    init_state()

    app = FastAPI(
        title="BikeDispatch · Citi Bike NYC Rebalancing",
        description="Citi Bike NYC 共享单车潮汐调度系统 - 基于真实 Citi Bike 数据的预测与调度",
        version="1.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(data_router, prefix="/api", tags=["data"])
    app.include_router(prediction_router, prefix="/api", tags=["prediction"])
    app.include_router(dispatch_router, prefix="/api", tags=["dispatch"])
    app.include_router(dashboard_router, prefix="/api", tags=["dashboard"])
    app.include_router(monitor_router, prefix="/api", tags=["monitor"])
    app.include_router(alerts_router, prefix="/api", tags=["alerts"])
    app.include_router(lab_router, prefix="/api", tags=["lab"])
    app.include_router(gis_router, prefix="/api/gis", tags=["gis"])

    @app.get("/", tags=["root"])
    def root() -> dict[str, str]:
        return {"message": "BikeDispatch backend is running."}

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
