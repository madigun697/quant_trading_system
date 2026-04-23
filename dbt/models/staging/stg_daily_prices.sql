select
    symbol,
    trade_date,
    open,
    high,
    low,
    close,
    adjusted_open,
    adjusted_high,
    adjusted_low,
    adjusted_close,
    volume,
    adjusted_volume,
    dividend_amount,
    split_coefficient,
    coalesce(adjusted_volume, volume) * coalesce(adjusted_close, close) as dollar_volume,
    ingested_at as effective_as_of,
    source
from {{ source('raw', 'tiingo_daily_prices') }}
