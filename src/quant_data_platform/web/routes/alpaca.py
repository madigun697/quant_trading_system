"""Alpaca Paper Trading 라우트."""
from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from quant_data_platform.web.services.alpaca_service import AlpacaPageService


def build_router(
    templates: Jinja2Templates,
    service_factory: Callable[[Request], AlpacaPageService],
) -> APIRouter:
    router = APIRouter()

    @router.get("/alpaca", response_class=HTMLResponse, name="alpaca_page")
    async def alpaca_page(request: Request) -> HTMLResponse:
        service = service_factory(request)
        context = service.get_page_context()
        return templates.TemplateResponse(request, "alpaca/index.html", context)

    @router.post("/alpaca/orders", response_class=JSONResponse)
    async def submit_orders(request: Request) -> JSONResponse:
        service = service_factory(request)
        body = await request.json()
        order_inputs = body if isinstance(body, list) else body.get("orders", [])
        result = service.submit_orders(order_inputs)
        status_code = 200 if result.get("ok") else 422
        return JSONResponse(result, status_code=status_code)

    return router
