with facts as (
    select *
    from {{ source('raw', 'sec_companyfacts_facts') }}
),
pivoted as (
    select
        cik as stable_id_or_cik,
        accession_number,
        period_end,
        filing_date,
        available_at,
        max(case when concept = 'Assets' then value end) as total_assets,
        max(case when concept = 'Liabilities' then value end) as total_liabilities,
        max(case when concept in ('StockholdersEquity', 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest') then value end) as total_equity,
        max(case when concept in (
            'CashAndCashEquivalentsAtCarryingValue',
            'CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents'
        ) then value end) as cash_and_equivalents,
        max(case when concept in (
            'ShortTermBorrowings',
            'ShortTermDebt',
            'LongTermDebtCurrent',
            'CurrentPortionOfLongTermDebt'
        ) then value end) as short_term_debt,
        max(case when concept in (
            'LongTermDebtNoncurrent',
            'LongTermDebtAndFinanceLeaseObligations',
            'LongTermDebt',
            'LongTermBorrowings'
        ) then value end) as long_term_debt
    from facts
    group by 1, 2, 3, 4, 5
)
select * from pivoted
