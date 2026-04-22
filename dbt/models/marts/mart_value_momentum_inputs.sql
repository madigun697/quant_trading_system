with universe as (
    select symbol from {{ ref('int_universe_snapshots') }}
),
prices as (
    select
        p.*,
        count(*) over (
            partition by p.symbol
            order by p.trade_date
            rows between 272 preceding and current row
        ) as lookback_observations,
        lag(p.adjusted_close, 21) over (partition by p.symbol order by p.trade_date) as adjusted_close_1m_ago,
        lag(p.adjusted_close, 252) over (partition by p.symbol order by p.trade_date) as adjusted_close_12m_ago,
        lag(p.adjusted_close, 273) over (partition by p.symbol order by p.trade_date) as adjusted_close_13m_ago
    from {{ ref('stg_daily_prices') }} p
    join universe u using (symbol)
),
value_inputs as (
    select symbol, trade_date, pe_ratio, pb_ratio, ev_to_ebitda, fcf_yield, sales_yield
    from {{ ref('mart_value_quality_inputs') }}
)
select
    prices.symbol,
    prices.trade_date,
    prices.adjusted_close,
    prices.lookback_observations,
    case
        when prices.lookback_observations >= 273 and prices.adjusted_close_13m_ago is not null and prices.adjusted_close_1m_ago is not null
            then (prices.adjusted_close_1m_ago / nullif(prices.adjusted_close_13m_ago, 0)) - 1
    end as momentum_12_1,
    case
        when lag(prices.adjusted_close, 126) over (partition by prices.symbol order by prices.trade_date) is not null
            then (prices.adjusted_close / nullif(lag(prices.adjusted_close, 126) over (partition by prices.symbol order by prices.trade_date), 0)) - 1
    end as momentum_6m,
    case
        when lag(prices.adjusted_close, 63) over (partition by prices.symbol order by prices.trade_date) is not null
            then (prices.adjusted_close / nullif(lag(prices.adjusted_close, 63) over (partition by prices.symbol order by prices.trade_date), 0)) - 1
    end as momentum_3m,
    value_inputs.pe_ratio,
    value_inputs.pb_ratio,
    value_inputs.ev_to_ebitda,
    value_inputs.fcf_yield,
    value_inputs.sales_yield
from prices
left join value_inputs
    on value_inputs.symbol = prices.symbol
   and value_inputs.trade_date = prices.trade_date
