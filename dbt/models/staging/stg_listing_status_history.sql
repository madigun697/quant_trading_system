with source as (
    select *
    from {{ source('raw', 'alpha_vantage_listing_status') }}
)
select
    symbol,
    name,
    exchange,
    asset_type,
    ipo_date,
    delisting_date,
    status,
    source_file_date,
    ingested_at
from source
