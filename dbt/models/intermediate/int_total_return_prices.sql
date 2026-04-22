select
    symbol,
    trade_date,
    adjusted_close,
    close,
    volume,
    dollar_volume,
    ln(adjusted_close / nullif(lag(adjusted_close) over (partition by symbol order by trade_date), 0)) as daily_log_return
from {{ ref('stg_daily_prices') }}
