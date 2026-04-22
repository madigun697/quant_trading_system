select
    symbol,
    trade_date,
    open,
    high,
    low,
    close,
    adjusted_close,
    volume,
    dividend_amount,
    split_coefficient,
    volume * close as dollar_volume,
    ingested_at as effective_as_of,
    source
from {{ source('raw', 'alpha_vantage_daily_prices') }}
