{{ config(tags=["mart"]) }}

with prices as (
    select *
    from {{ ref('stg_daily_prices') }}
),
universe as (
    select *
    from {{ ref('int_universe_snapshots') }}
),
security_master as (
    select *
    from {{ ref('stg_security_master') }}
),
fundamentals as (
    select *
    from {{ ref('int_point_in_time_fundamentals') }}
),
joined as (
    select
        sm.symbol,
        prices.trade_date,
        sm.stable_id_or_cik,
        universe.cohort,
        universe.effective_date as snapshot_date,
        universe.liquidity_rank,
        universe.adv60 as snapshot_adv60,
        prices.adjusted_close,
        prices.close,
        coalesce(sm.shares_outstanding, fundamentals.weighted_average_shares) as shares_outstanding,
        fundamentals.net_income,
        fundamentals.total_equity,
        fundamentals.total_assets,
        fundamentals.gross_profit,
        fundamentals.operating_income,
        fundamentals.ebitda,
        fundamentals.revenue,
        fundamentals.cash_and_equivalents,
        fundamentals.short_term_debt,
        fundamentals.long_term_debt,
        fundamentals.operating_cash_flow,
        fundamentals.capex,
        fundamentals.interest_expense,
        prices.effective_as_of
    from security_master sm
    join prices on prices.symbol = sm.symbol
    join universe
      on universe.symbol = sm.symbol
     and prices.trade_date >= universe.effective_date
     and (universe.next_effective_date is null or prices.trade_date < universe.next_effective_date)
    left join fundamentals
        on fundamentals.stable_id_or_cik = sm.stable_id_or_cik
       and fundamentals.available_at <= prices.trade_date
)
select
    symbol,
    trade_date,
    stable_id_or_cik,
    cohort,
    snapshot_date,
    liquidity_rank,
    snapshot_adv60,
    adjusted_close,
    shares_outstanding,
    adjusted_close * shares_outstanding as market_cap,
    (adjusted_close * shares_outstanding) + coalesce(short_term_debt, 0) + coalesce(long_term_debt, 0) - coalesce(cash_and_equivalents, 0) as enterprise_value,
    net_income / nullif(shares_outstanding, 0) as earnings_per_share_proxy,
    adjusted_close / nullif(net_income / nullif(shares_outstanding, 0), 0) as pe_ratio,
    (adjusted_close * shares_outstanding) / nullif(total_equity, 0) as pb_ratio,
    ((adjusted_close * shares_outstanding) + coalesce(short_term_debt, 0) + coalesce(long_term_debt, 0) - coalesce(cash_and_equivalents, 0)) / nullif(ebitda, 0) as ev_to_ebitda,
    (coalesce(operating_cash_flow, 0) - coalesce(capex, 0)) / nullif(adjusted_close * shares_outstanding, 0) as fcf_yield,
    revenue / nullif(adjusted_close * shares_outstanding, 0) as sales_yield,
    net_income / nullif(total_equity, 0) as roe,
    operating_income / nullif(total_assets - coalesce(cash_and_equivalents, 0), 0) as roic_proxy,
    gross_profit / nullif(revenue, 0) as gross_margin,
    operating_income / nullif(revenue, 0) as operating_margin,
    (coalesce(short_term_debt, 0) + coalesce(long_term_debt, 0)) / nullif(total_equity, 0) as debt_to_equity,
    operating_income / nullif(interest_expense, 0) as interest_coverage,
    (net_income - coalesce(operating_cash_flow, 0)) / nullif(total_assets, 0) as accruals,
    effective_as_of
from joined
