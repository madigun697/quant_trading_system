from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from quant_data_platform.web.schemas import BacktestFormInput, field_errors_from_validation_error, form_values_from_raw
from quant_data_platform.web.services.backtest_service import BacktestPageService


def build_router(
    templates: Jinja2Templates,
    service_factory: Callable[[Request], BacktestPageService],
) -> APIRouter:
    router = APIRouter()

    @router.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/backtest", status_code=302)

    @router.get("/healthz")
    async def healthz(request: Request) -> JSONResponse:
        service = service_factory(request)
        readiness = service.readiness_status()
        payload = {
            "status": "ok" if readiness.ok else "unavailable",
            "code": readiness.code,
            "detail": readiness.detail,
            "checked_relations": list(readiness.checked_relations),
        }
        return JSONResponse(payload, status_code=200 if readiness.ok else 503)

    @router.get("/backtest", response_class=HTMLResponse)
    async def backtest_page(request: Request) -> HTMLResponse:
        service = service_factory(request)
        context = service.empty_context()
        return templates.TemplateResponse(request, "backtest/index.html", context.model_dump())

    @router.post("/backtest", response_class=HTMLResponse)
    async def run_backtest(request: Request) -> HTMLResponse:
        service = service_factory(request)
        raw_form = {key: value for key, value in (await request.form()).multi_items()}
        try:
            form = BacktestFormInput.model_validate(raw_form)
        except ValidationError as exc:
            context = service.error_context(
                form=None,
                message="입력값을 다시 확인해 주세요.",
                field_errors=field_errors_from_validation_error(exc),
                http_status_code=422,
            )
            context.form_values = form_values_from_raw(raw_form)
            return templates.TemplateResponse(request, "backtest/index.html", context.model_dump(), status_code=422)

        context = service.build_context(form)
        return templates.TemplateResponse(request, "backtest/index.html", context.model_dump(), status_code=context.http_status_code)

    return router
