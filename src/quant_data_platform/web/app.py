from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from quant_data_platform.web.repositories.backtest_repo import BacktestRepository
from quant_data_platform.web.routes.backtest import build_router as build_backtest_router
from quant_data_platform.web.routes.current_bucket import build_router as build_current_bucket_router
from quant_data_platform.web.services.backtest_service import BacktestPageService
from quant_data_platform.web.services.current_bucket_service import CurrentBucketPageService


BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


def create_app(
    service: BacktestPageService | None = None,
    current_bucket_service: CurrentBucketPageService | None = None,
) -> FastAPI:
    app = FastAPI(title="Quant Backtest Web", version="0.1.0")
    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.state.backtest_service = service or BacktestPageService(BacktestRepository())
    app.state.current_bucket_service = current_bucket_service or CurrentBucketPageService(BacktestRepository())

    def service_factory(request: Request) -> BacktestPageService:
        return request.app.state.backtest_service

    def current_bucket_service_factory(request: Request) -> CurrentBucketPageService:
        return request.app.state.current_bucket_service

    app.include_router(build_backtest_router(templates, service_factory))
    app.include_router(build_current_bucket_router(templates, current_bucket_service_factory))
    return app


app = create_app()
