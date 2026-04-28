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
            'NetCashProvidedByUsedInOperatingActivities',
            'NetCashProvidedByUsedInOperatingActivitiesContinuingOperations',
            'NetCashProvidedByUsedInContinuingOperations'
        ) then value end) as operating_cash_flow,
        max(case when concept in (
            'PaymentsToAcquirePropertyPlantAndEquipment',
            'CapitalExpendituresIncurredButNotYetPaid',
            'PropertyPlantAndEquipmentAdditions',
            'PaymentsToAcquireProductiveAssets'
        ) then value end) as capex,
        max(case when concept in ('PaymentsOfDividends', 'PaymentsOfDividendsCommonStock') then value end) as dividends_paid,
        max(case when concept in ('PaymentsForRepurchaseOfCommonStock', 'CommonStockRepurchasedDuringPeriodValue') then value end) as share_repurchases
    from facts
    group by 1, 2, 3, 4, 5
)
select * from pivoted
