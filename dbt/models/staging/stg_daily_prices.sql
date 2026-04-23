with ranked_prices as (
    select
        *,
        row_number() over (
            partition by symbol, trade_date
            order by
                case
                    when source = 'tiingo' then 1
                    when source = 'yfinance_history' then 2
                    else 99
                end,
                ingested_at desc
        ) as source_rank
    from {{ source('raw', 'market_daily_prices') }}
)
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
from ranked_prices
where source_rank = 1
