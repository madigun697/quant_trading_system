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
        max(case when concept in (
            'RevenueFromContractWithCustomerExcludingAssessedTax',
            'RevenueFromContractWithCustomerIncludingAssessedTax',
            'Revenues',
            'SalesRevenueNet',
            'SalesRevenueServicesNet',
            'SalesRevenueGoodsNet',
            'SalesRevenueServicesGross',
            'TotalRevenue'
        ) then value end) as revenue,
        max(case when concept = 'GrossProfit' then value end) as gross_profit,
        max(case when concept = 'OperatingIncomeLoss' then value end) as operating_income,
        max(case when concept in ('EarningsBeforeInterestTaxesDepreciationAndAmortization', 'AdjustedEBITDA') then value end) as ebitda,
        max(case when concept in ('InterestExpenseAndOther', 'InterestExpense', 'InterestAndDebtExpense') then value end) as interest_expense,
        max(case when concept in ('NetIncomeLoss', 'ProfitLoss') then value end) as net_income,
        max(case when concept = 'EarningsPerShareBasic' then value end) as basic_eps,
        max(case when concept = 'EarningsPerShareDiluted' then value end) as diluted_eps,
        max(case when concept in (
            'WeightedAverageNumberOfSharesOutstandingBasic',
            'WeightedAverageNumberOfDilutedSharesOutstanding',
            'CommonStockSharesOutstanding'
        ) then value end) as weighted_average_shares
    from facts
    group by 1, 2, 3, 4, 5
)
select * from pivoted
