{{ config(tags=["mart"], materialized='table') }}

/*
  mart_value_quality_inputs
  ─────────────────────────
  int_prices_universe_daily에서 팩터 계산만 담당.
  무거운 join은 intermediate에서 이미 완료됨.
*/

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
    effective_as_of,

    -- Market cap & Enterprise value
    adjusted_close * shares_outstanding                                                                             as market_cap,
    (adjusted_close * shares_outstanding)
        + coalesce(short_term_debt, 0)
        + coalesce(long_term_debt, 0)
        - coalesce(cash_and_equivalents, 0)                                                                        as enterprise_value,

    -- Per-share
    net_income / nullif(shares_outstanding, 0)                                                                     as earnings_per_share_proxy,

    -- Valuation ratios
    adjusted_close / nullif(net_income / nullif(shares_outstanding, 0), 0)                                         as pe_ratio,
    (adjusted_close * shares_outstanding) / nullif(total_equity, 0)                                                as pb_ratio,
    ((adjusted_close * shares_outstanding)
        + coalesce(short_term_debt, 0)
        + coalesce(long_term_debt, 0)
        - coalesce(cash_and_equivalents, 0)) / nullif(coalesce(ebitda, operating_income), 0)                      as ev_to_ebitda,
    (coalesce(operating_cash_flow, 0) - coalesce(capex, 0))
        / nullif(adjusted_close * shares_outstanding, 0)                                                           as fcf_yield,
    revenue / nullif(adjusted_close * shares_outstanding, 0)                                                       as sales_yield,

    -- Quality ratios
    net_income / nullif(total_equity, 0)                                                                           as roe,
    operating_income / nullif(total_assets - coalesce(cash_and_equivalents, 0), 0)                                 as roic_proxy,
    gross_profit / nullif(revenue, 0)                                                                              as gross_margin,
    operating_income / nullif(revenue, 0)                                                                          as operating_margin,

    -- Leverage
    (coalesce(short_term_debt, 0) + coalesce(long_term_debt, 0)) / nullif(total_equity, 0)                        as debt_to_equity,
    operating_income / nullif(interest_expense, 0)                                                                 as interest_coverage,

    -- Accruals
    (net_income - coalesce(operating_cash_flow, 0)) / nullif(total_assets, 0)                                      as accruals

from {{ ref('int_prices_universe_daily') }}
