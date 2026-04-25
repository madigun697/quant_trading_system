{{ config(
    tags=["int"],
    materialized='table',
    indexes=[
      {'columns': ['stable_id_or_cik', 'available_at']},
      {'columns': ['stable_id_or_cik', 'period_end']},
    ]
) }}

select
    income.stable_id_or_cik,
    income.accession_number,
    income.period_end,
    income.filing_date,
    income.available_at,
    income.revenue,
    income.gross_profit,
    income.operating_income,
    income.ebitda,
    income.interest_expense,
    income.net_income,
    income.basic_eps,
    income.diluted_eps,
    income.weighted_average_shares,
    balance.total_assets,
    balance.total_liabilities,
    balance.total_equity,
    balance.cash_and_equivalents,
    balance.short_term_debt,
    balance.long_term_debt,
    cash.operating_cash_flow,
    cash.capex,
    cash.dividends_paid,
    cash.share_repurchases
from {{ ref('stg_fundamentals_income_statement') }} income
left join {{ ref('stg_fundamentals_balance_sheet') }} balance
    using (stable_id_or_cik, accession_number, period_end, filing_date, available_at)
left join {{ ref('stg_fundamentals_cash_flow') }} cash
    using (stable_id_or_cik, accession_number, period_end, filing_date, available_at)
