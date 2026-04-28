from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from quant_data_platform.web.repositories.backtest_repo import BacktestRepository
from quant_data_platform.web.routes.backtest import build_router
from quant_data_platform.web.services.backtest_service import BacktestPageService


BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


def create_app(service: BacktestPageService | None = None) -> FastAPI:
    app = FastAPI(title="Quant Backtest Web", version="0.1.0")
    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.state.backtest_service = service or BacktestPageService(BacktestRepository())

    def service_factory(request: Request) -> BacktestPageService:
        return request.app.state.backtest_service

    app.include_router(build_router(templates, service_factory))
    return app


app = create_app()
