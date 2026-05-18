with latest_overview as (
    select *,
        row_number() over (partition by symbol order by as_of_date desc, ingested_at desc) as rn
    from {{ source('raw', 'alpha_vantage_overview') }}
),
latest_status as (
    select *,
        row_number() over (partition by symbol order by source_file_date desc, ingested_at desc) as rn
    from {{ source('raw', 'alpha_vantage_listing_status') }}
),
latest_sec_reference as (
    select *,
        row_number() over (partition by symbol_alias order by as_of_date desc, fetched_at desc) as rn
    from {{ source('raw', 'sec_ticker_reference') }}
),
latest_sec_submission as (
    select *,
        row_number() over (partition by cik order by fetched_at desc) as rn
    from {{ source('raw', 'sec_submissions') }}
),
security_classification as (
    select
        coalesce(o.symbol, s.symbol, r.symbol_alias) as symbol,
        coalesce(o.cik, r.cik) as stable_id_or_cik,
        coalesce(o.exchange, s.exchange, r.exchange) as exchange,
        coalesce(o.asset_type, s.asset_type) as security_type,
        true as primary_listing_flag,
        s.status as active_delisted_status,
        s.ipo_date as listing_date,
        s.delisting_date,
        o.market_cap,
        o.shares_outstanding,
        o.as_of_date,
        coalesce(o.sector, case
            when sec.sic between 1311 and 1389 then 'ENERGY'
            when sec.sic between 1000 and 1499 then 'MATERIALS'
            when sec.sic between 2833 and 2836 then 'HEALTHCARE'
            when sec.sic between 3570 and 3579 then 'TECHNOLOGY'
            when sec.sic between 3661 and 3699 then 'TECHNOLOGY'
            when sec.sic between 4812 and 4899 then 'COMMUNICATION SERVICES'
            when sec.sic between 4900 and 4999 then 'UTILITIES'
            when sec.sic between 5200 and 5999 then 'CONSUMER CYCLICAL'
            when sec.sic between 6000 and 6499 then 'FINANCIAL SERVICES'
            when sec.sic between 6500 and 6799 then 'REAL ESTATE'
            when sec.sic between 7000 and 7399 then 'TECHNOLOGY'
            when sec.sic between 7800 and 7999 then 'COMMUNICATION SERVICES'
            when sec.sic between 8000 and 8999 then 'HEALTHCARE'
            when upper(coalesce(sec.sic_description, '')) like any (array[
                '%BANK%',
                '%BROKER%',
                '%INSURANCE%',
                '%FINANCE%',
                '%CREDIT%',
                '%MORTGAGE%',
                '%SECURITY & COMMODITY%'
            ]) then 'FINANCIAL SERVICES'
            when upper(coalesce(sec.sic_description, '')) like any (array[
                '%REAL ESTATE%',
                '%PROPERTY%'
            ]) then 'REAL ESTATE'
            when upper(coalesce(sec.sic_description, '')) like any (array[
                '%OIL%',
                '%GAS%',
                '%PETROLEUM%',
                '%DRILLING%',
                '%PIPELINE%',
                '%ENERGY%'
            ]) then 'ENERGY'
            when upper(coalesce(sec.sic_description, '')) like any (array[
                '%ELECTRIC%',
                '%UTILITY%',
                '%WATER SUPPLY%'
            ]) then 'UTILITIES'
            when upper(coalesce(sec.sic_description, '')) like any (array[
                '%SOFTWARE%',
                '%SEMICONDUCTOR%',
                '%COMPUTER%',
                '%ELECTRONIC%',
                '%DATA PROCESSING%'
            ]) then 'TECHNOLOGY'
            when upper(coalesce(sec.sic_description, '')) like any (array[
                '%TELEPHONE%',
                '%COMMUNICATION%',
                '%BROADCAST%',
                '%MEDIA%'
            ]) then 'COMMUNICATION SERVICES'
            when upper(coalesce(sec.sic_description, '')) like any (array[
                '%PHARM%',
                '%BIOTECH%',
                '%MEDICAL%',
                '%HEALTH%',
                '%HOSPITAL%'
            ]) then 'HEALTHCARE'
            when upper(coalesce(sec.sic_description, '')) like any (array[
                '%CHEMICAL%',
                '%MINING%',
                '%METAL%',
                '%LUMBER%',
                '%PAPER%'
            ]) then 'MATERIALS'
            when upper(coalesce(sec.sic_description, '')) like any (array[
                '%FOOD%',
                '%BEVERAGE%',
                '%TOBACCO%',
                '%GROCERY%',
                '%HOUSEHOLD%'
            ]) then 'CONSUMER DEFENSIVE'
            when upper(coalesce(sec.sic_description, '')) like any (array[
                '%RETAIL%',
                '%RESTAURANT%',
                '%DRINKING PLACES%',
                '%HOTEL%',
                '%LEISURE%',
                '%APPAREL%',
                '%AUTO%'
            ]) then 'CONSUMER CYCLICAL'
            when upper(coalesce(sec.sic_description, '')) like any (array[
                '%AEROSPACE%',
                '%MACHINERY%',
                '%TRANSPORTATION%',
                '%RAILROAD%',
                '%TRUCK%',
                '%MANUFACTURING%',
                '%CONSTRUCTION%'
            ]) then 'INDUSTRIALS'
            else null
        end) as sector,
        coalesce(o.industry, sec.sic_description) as industry,
        case
            when o.sector is not null then 'alpha_vantage'
            when sec.sic is not null or sec.sic_description is not null then 'sec_sic'
            else 'missing'
        end as sector_source,
        greatest(
            coalesce(o.ingested_at, '1970-01-01'::timestamptz),
            coalesce(s.ingested_at, '1970-01-01'::timestamptz),
            coalesce(r.fetched_at, '1970-01-01'::timestamptz),
            coalesce(sec.fetched_at, '1970-01-01'::timestamptz)
        ) as effective_as_of,
        case
            when o.symbol is not null then 'alpha_vantage'
            when r.symbol_alias is not null then 'sec'
            else 'alpha_vantage'
        end as source
    from latest_overview o
    full outer join latest_status s
        on o.symbol = s.symbol and s.rn = 1
    full outer join latest_sec_reference r
        on coalesce(o.symbol, s.symbol) = r.symbol_alias and r.rn = 1
    left join latest_sec_submission sec
        on coalesce(o.cik, r.cik) = sec.cik and sec.rn = 1
    where coalesce(o.rn, 1) = 1
)
select *
from security_classification
