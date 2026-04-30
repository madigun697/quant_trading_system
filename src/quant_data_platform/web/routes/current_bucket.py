from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from quant_data_platform.web.schemas import (
    CurrentBucketFormInput,
    current_bucket_form_values_from_raw,
    field_errors_from_validation_error,
)
from quant_data_platform.web.services.current_bucket_service import CurrentBucketPageService


def build_router(
    templates: Jinja2Templates,
    service_factory: Callable[[Request], CurrentBucketPageService],
) -> APIRouter:
    router = APIRouter()

    @router.get("/current-bucket", response_class=HTMLResponse)
    async def current_bucket_page(request: Request) -> HTMLResponse:
        service = service_factory(request)
        context = service.empty_context()
        return templates.TemplateResponse(request, "current_bucket/index.html", context.model_dump())

    @router.post("/current-bucket", response_class=HTMLResponse)
    async def run_current_bucket(request: Request) -> HTMLResponse:
        service = service_factory(request)
        raw_form = {key: value for key, value in (await request.form()).multi_items()}
        try:
            form = CurrentBucketFormInput.model_validate(raw_form)
        except ValidationError as exc:
            raw_values = current_bucket_form_values_from_raw(raw_form)
            context = service.error_context(
                form=None,
                message="입력값을 다시 확인해 주세요.",
                field_errors=field_errors_from_validation_error(exc),
                http_status_code=422,
                form_values=raw_values,
            )
            return templates.TemplateResponse(request, "current_bucket/index.html", context.model_dump(), status_code=422)

        context = service.build_context(form)
        return templates.TemplateResponse(request, "current_bucket/index.html", context.model_dump(), status_code=context.http_status_code)

    return router
