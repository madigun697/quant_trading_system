from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from quant_data_platform.web.schemas import BacktestFormInput, CurrentBucketFormInput


def test_backtest_form_defaults_to_sgov_100_percent() -> None:
    form = BacktestFormInput(
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 2),
    )

    assert form.safe_asset_weight_sgov == Decimal("100")
    assert form.safe_asset_weight_jpst == Decimal("0")
    assert form.safe_asset_weight_ief == Decimal("0")
    assert form.safe_asset_weight_tlt == Decimal("0")
    assert form.safe_asset_weight_gld == Decimal("0")
    assert form.safe_asset_weight_xle == Decimal("0")
    assert form.safe_asset_summary() == "SGOV 100%"


def test_backtest_form_accepts_legacy_safe_asset_symbol() -> None:
    form = BacktestFormInput.model_validate(
        {
            "safe_asset_symbol": "JPST",
            "start_date": "2024-01-01",
            "end_date": "2024-01-02",
        }
    )

    assert form.safe_asset_weight_sgov == Decimal("0")
    assert form.safe_asset_weight_jpst == Decimal("100")
    assert form.safe_asset_summary() == "JPST 100%"


def test_backtest_form_rejects_invalid_legacy_safe_asset_symbol() -> None:
    with pytest.raises(ValidationError) as exc_info:
        BacktestFormInput.model_validate(
            {
                "safe_asset_symbol": "INVALID",
                "start_date": "2024-01-01",
                "end_date": "2024-01-02",
            }
        )

    assert "safe_asset_symbol 값이 유효하지 않습니다." in str(exc_info.value)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"safe_asset_weight_sgov": "99.9"}, "안전자산 비중 합계는 정확히 100%여야 합니다."),
        ({"safe_asset_weight_sgov": "100.1"}, "안전자산 비중은 100%를 초과할 수 없습니다."),
        ({"safe_asset_weight_sgov": "-1", "safe_asset_weight_jpst": "101"}, "안전자산 비중은 0% 이상이어야 합니다."),
        (
            {
                "safe_asset_weight_sgov": "0",
                "safe_asset_weight_jpst": "0",
                "safe_asset_weight_ief": "0",
                "safe_asset_weight_tlt": "0",
                "safe_asset_weight_gld": "0",
                "safe_asset_weight_xle": "0",
            },
            "안전자산 비중 합계는 정확히 100%여야 합니다.",
        ),
    ],
)
def test_backtest_form_rejects_invalid_safe_asset_weights(overrides: dict[str, str], message: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        BacktestFormInput.model_validate(
            {
                "start_date": "2024-01-01",
                "end_date": "2024-01-02",
                **overrides,
            }
        )

    assert message in str(exc_info.value)


def test_current_bucket_form_defaults_to_sgov_100_percent() -> None:
    form = CurrentBucketFormInput()

    assert form.safe_asset_weight_sgov == Decimal("100")
    assert form.safe_asset_weight_jpst == Decimal("0")
    assert form.safe_asset_weight_ief == Decimal("0")
    assert form.safe_asset_weight_tlt == Decimal("0")
    assert form.safe_asset_weight_gld == Decimal("0")
    assert form.safe_asset_weight_xle == Decimal("0")
    assert form.safe_asset_summary() == "SGOV 100%"


def test_current_bucket_form_accepts_legacy_safe_asset_symbol() -> None:
    form = CurrentBucketFormInput.model_validate({"safe_asset_symbol": "TLT"})

    assert form.safe_asset_weight_sgov == Decimal("0")
    assert form.safe_asset_weight_tlt == Decimal("100")
    assert form.safe_asset_summary() == "TLT 100%"


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"safe_asset_weight_sgov": "60", "safe_asset_weight_ief": "30"}, "안전자산 비중 합계는 정확히 100%여야 합니다."),
        ({"safe_asset_weight_sgov": "100.1"}, "안전자산 비중은 100%를 초과할 수 없습니다."),
        ({"investable_capital": "0"}, "투자 가능 자본은 0보다 커야 합니다."),
    ],
)
def test_current_bucket_form_rejects_invalid_values(payload: dict[str, str], message: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        CurrentBucketFormInput.model_validate(payload)

    assert message in str(exc_info.value)
